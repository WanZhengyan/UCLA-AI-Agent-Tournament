"""Opt-in experiments on server-verified, fully self-owned Testing matches.

The registry shares experiment labels only. A policy NEVER reads another
seat's observations or traces. Local I/O failure must not forfeit a match.
"""
from collections import Counter, deque
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .agent import RedAlertAgent, create_agent as create_default_agent
from .common import View

ROOT = Path(__file__).resolve().parents[1] / 'validation' / 'redalert_selfplay'
PROFILES = {'balanced', 'eco_guard'}


def _atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fingerprint():
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / 'redalert_bot').glob('*.py'))
    files += [root / 'competition_agent.py', root / 'altruagent' / 'worker.py']
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def allocate(root, metadata, context, raw, code_hash):
    """Atomically alternate seats per map/duration, independent of worker order."""
    import fcntl  # The current supported experiment host is macOS/Linux.
    settings = json.loads((root / 'settings.json').read_text())
    profiles = settings.get('profiles')
    if settings.get('enabled') is not True or not isinstance(profiles, list) or len(profiles) != 2:
        return None
    if set(profiles) != PROFILES:
        return None
    run_id = settings.get('run_id', '')
    if not isinstance(run_id, str) or not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in run_id):
        return None
    directory = root / run_id
    directory.mkdir(parents=True, exist_ok=True)
    t = raw.get('time') or {}
    map_id = (raw.get('map') or (raw.get('observation') or {}).get('map') or {}).get('id', 'unknown')
    duration = t.get('max_minutes')
    if duration is None and 'game_seconds' in t and 'remaining_seconds' in t:
        duration = round((float(t['game_seconds']) + float(t['remaining_seconds'])) / 60, 2)
    case = json.dumps([map_id, duration], separators=(',', ':'))
    match_id = metadata['match_id']
    registry_path = directory / 'registry.json'
    with (directory / 'registry.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        registry = json.loads(registry_path.read_text()) if registry_path.exists() else {'matches': {}}
        entries = registry['matches']
        if match_id not in entries:
            previous = sum(e['case'] == case for e in entries.values())
            entries[match_id] = dict(case=case, map=map_id, max_minutes=duration,
                                     profiles=list(reversed(profiles)) if previous % 2 else profiles,
                                     code_hash=code_hash, session_id=context.session_id,
                                     pair_index=previous // 2, leg=previous % 2)
            _atomic_json(registry_path, registry)
        entry = dict(entries[match_id])
    if entry['session_id'] != context.session_id or entry['code_hash'] != code_hash:
        # A restarted seat with different source cannot silently complete an
        # allegedly matched-version experiment. Keep playing the normal bot.
        return None
    seat = context.seat_position
    if type(seat) is not int or seat not in (0, 1):
        return None
    entry.update(match_id=match_id, seat=seat, profile=entry['profiles'][seat], run_id=run_id)
    return directory, entry


def make_policy(metadata, context, state):
    if (metadata.get('verified_selfplay') is not True or context is None
            or context.tournament_id is not None or context.game_type != 'red_alert'):
        return create_default_agent()
    try:
        allocation = allocate(ROOT, metadata, context, state.raw, fingerprint())
        if allocation:
            directory, entry = allocation
            print(f"[self-play] player {entry['seat'] + 1}: {entry['profile']} | "
                  f"map={entry['map']} duration={entry['max_minutes']}m leg={entry['leg'] + 1}", flush=True)
            return RecordedAgent(directory, entry)
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        pass
    return create_default_agent()


class RecordedAgent(RedAlertAgent):
    def __init__(self, directory, entry):
        super().__init__(profile=entry['profile'])
        self.entry = entry
        stem = hashlib.sha256(entry['match_id'].encode()).hexdigest()[:20] + '-seat' + str(entry['seat'])
        self.path = directory / (stem + '.jsonl')
        self.final_path = directory / (stem + '-final.json')
        self.last_sample = -1000.
        self.last_snapshot = None
        self.commands = Counter()
        self.verdicts = Counter()
        self.engine_verdicts = Counter()
        self.verdict_seen = set()
        self.verdict_window = deque()
        self.harvesters_seen = set()
        self.harvester_disappearances = 0
        self.first_times = {}
        self.started = False

    def _append(self, data):
        if self.path.exists() and self.path.stat().st_size > 16 * 1024 * 1024:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'a') as stream:
            stream.write(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')

    def _snapshot(self, raw, context):
        v = View(raw, getattr(context, 'game_config', None))
        own_units = Counter(a.get('type') for a in v.units)
        own_buildings = Counter(a.get('type') for a in v.buildings)
        miners = {a['id'] for a in v.units if a.get('type') == 'harv'}
        self.harvester_disappearances += len(self.harvesters_seen - miners)
        self.harvesters_seen = miners
        for label, reached in [('second_refinery', own_buildings['proc'] >= 2),
                               ('four_harvesters', own_units['harv'] >= 4),
                               ('second_yard', own_buildings['fact'] >= 2)]:
            if reached and label not in self.first_times:
                self.first_times[label] = v.now
        memory = self._memory(context)
        military = {k: v.military[k] for k in ('kills_cost', 'deaths_cost', 'assets_value', 'army_value',
                    'units_killed', 'units_lost', 'buildings_killed', 'buildings_lost') if k in v.military}
        def position(actor):
            return {k: actor[k] for k in ('id','type','x','y','hp') if k in actor}
        snapshot = dict(kind='sample', seconds=v.now, remaining=v.remaining, base=list(v.base),
                        faction=v.obs.get('faction'), enemy_faction=v.obs.get('enemy_faction'),
                        military=military, economy={k: v.econ[k] for k in ('cash', 'ore', 'harvesters',
                        'power_provided', 'power_drained') if k in v.econ},
                        units=dict(own_units), buildings=dict(own_buildings),
                        harvester_positions=[position(a) for a in v.units if a.get('type') == 'harv'],
                        refinery_positions=[position(a) for a in v.buildings if a.get('type') == 'proc'],
                        visible_contacts=[position(a) for a in v.enemies + v.enemy_buildings],
                        harvester_disappearances=self.harvester_disappearances,
                        first_times=dict(self.first_times),
                        map_plan=dict(memory.get('map_adaptation', {}).get('plan', {})),
                        mode=memory.get('combat', {}).get('combat', {}).get('mode'),
                        expansion_site=memory.get('economy', {}).get('expansion_site'),
                        expansion_required_seconds=memory.get('economy', {}).get('expansion_required_seconds'),
                        visible_enemies=dict(Counter(a.get('type') for a in v.enemies)),
                        visible_enemy_buildings=dict(Counter(a.get('type') for a in v.enemy_buildings)),
                        issued_commands=dict(self.commands), immediate_verdicts=dict(self.verdicts),
                        engine_verdicts=dict(self.engine_verdicts))
        self.last_snapshot = snapshot
        return snapshot

    def choose_action(self, state, context):
        result = super().choose_action(state, context)
        try:
            self._read_engine_verdicts(state.raw)
            if isinstance(result, dict):
                for order in result.get('orders', []):
                    key = order['cmd'] + (':' + order['item'] if 'item' in order else '')
                    self.commands[key] += order.get('count', 1)
            raw = state.raw
            now = float((raw.get('time') or {}).get('game_seconds', raw.get('state_version', 0) / 25))
            if raw.get('observation') and now - self.last_sample >= 5:
                if not self.started:
                    self._append(dict(kind='start', **self.entry))
                    self.started = True
                self._append(self._snapshot(raw, context))
                self.last_sample = now
        except (OSError, ValueError, TypeError):
            pass
        return result

    def _read_engine_verdicts(self, raw):
        last = raw.get('last_orders') or {}
        rows = [(last.get('batch',last.get('state_version')), row) for row in last.get('results',[])]
        rows += [(row.get('batch'),row) for row in raw.get('recent_order_problems') or []]
        for batch,row in rows:
            status = row.get('status')
            if batch is None or status not in {'ok','partial','rejected','lost'}:
                continue
            reason = str(row.get('reason','unknown'))
            if len(reason) > 64 or not all(c.isalnum() or c == '_' for c in reason):
                reason = 'other'
            stamp = (batch,row.get('index'),status,reason)
            if stamp in self.verdict_seen:
                continue
            self.verdict_seen.add(stamp)
            self.verdict_window.append(stamp)
            self.engine_verdicts[status+':'+reason] += 1
            if len(self.verdict_window) > 4096:
                self.verdict_seen.discard(self.verdict_window.popleft())

    def on_action_result(self, result, context):
        super().on_action_result(result, context)
        if result.get('error'):
            self.verdicts['batch_error'] += 1
        for row in result.get('results') or []:
            status = row.get('status')
            if status in {'ok', 'pending', 'rejected', 'partial', 'lost'}:
                self.verdicts[status] += 1

    def on_game_end(self, state, context):
        # Saving the server result must not depend on decoding a terminal
        # observation: terminal states can omit/clear live observation fields.
        final_raw = getattr(state, 'raw', {}) or {}
        result = getattr(state, 'final_result', None) or {}
        score = result.get('your_return')
        if score is None:
            score = (getattr(state, 'returns', None) or result.get('returns') or {}).get(context.agent_id)
        snapshot = self.last_snapshot
        exact_observation = False
        snapshot_error = False
        try:
            if final_raw.get('observation'):
                snapshot = self._snapshot(final_raw, context)
                exact_observation = bool(final_raw.get('is_terminal'))
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            snapshot_error = True
        report = dict(kind='final', **self.entry, score=score,
                      termination_reason=getattr(state, 'termination_reason', None) or result.get('termination_reason'),
                      result_source='worker_terminal_callback',
                      exact_final_observation=exact_observation, snapshot_error=snapshot_error,
                      last_observation=snapshot)
        # Two independent sinks: failure of the large timeline must not
        # discard the small authoritative-result file (or vice versa).
        for save in (lambda: _atomic_json(self.final_path, report), lambda: self._append(report)):
            try:
                save()
            except (OSError, ValueError, TypeError):
                print('[self-play] Result sink failed; consult the supervisor console result.', flush=True)


def summarize(root=ROOT):
    """Only terminal, paired, distinct-profile games count as evidence."""
    games = {}
    for path in root.glob('*/registry.json'):
        for match in json.loads(path.read_text()).get('matches', {}):
            games[(path.parent.name, match)] = {}
    for path in root.glob('*/*-final.json'):
        row = json.loads(path.read_text())
        games.setdefault((row['run_id'], row['match_id']), {})[row['seat']] = row
    results, incomplete = [], []
    for (_, match), seats in games.items():
        if set(seats) != {0, 1}:
            incomplete.append(match)
            continue
        a, b = seats[0], seats[1]
        if ({a['profile'], b['profile']} != PROFILES or a['code_hash'] != b['code_hash']
                or a['case'] != b['case'] or a['score'] not in (0, .5, 1)
                or b['score'] not in (0, .5, 1) or a['score'] + b['score'] != 1):
            incomplete.append(match)
            continue
        candidate = a if a['profile'] == 'eco_guard' else b
        results.append(dict(match_id=match, run_id=candidate['run_id'], code_hash=candidate['code_hash'],
                            case=candidate['case'], map=candidate['map'], max_minutes=candidate['max_minutes'],
                            candidate_score=candidate['score'], candidate_seat=candidate['seat'],
                            result_sources=[a.get('result_source','unknown'),b.get('result_source','unknown')],
                            exact_terminal_observations=bool(a.get('exact_final_observation') and b.get('exact_final_observation')),
                            pair_index=candidate['pair_index'], leg=candidate['leg'],
                            termination_reason=candidate['termination_reason']))
    pairs = {}
    for row in results:
        pairs.setdefault((row['run_id'],row['case'],row['pair_index']),[]).append(row)
    swapped = sum(len(rows) == 2 and {r['leg'] for r in rows} == {0,1}
                  and {r['candidate_seat'] for r in rows} == {0,1}
                  and len({r['code_hash'] for r in rows}) == 1 for rows in pairs.values())
    return dict(completed_comparisons=len(results), complete_same_version_swapped_pairs=swapped,
                candidate_wins=sum(r['candidate_score'] == 1 for r in results),
                candidate_losses=sum(r['candidate_score'] == 0 for r in results),
                draws=sum(r['candidate_score'] == .5 for r in results), games=results,
                incomplete_or_invalid=incomplete,
                caution='Pilot self-play only; random factions and seeds are not controlled. Harvester disappearance is not a confirmed kill.')


if __name__ == '__main__':
    print(json.dumps(summarize(), ensure_ascii=False, indent=2))
