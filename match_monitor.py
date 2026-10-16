"""Passive, seat-local match telemetry. Never submits orders or reads other seats.

Bounded timelines + independent latest/final files; no raw contexts or tokens.
All calls from the router are best-effort and cannot change policy decisions.
"""
from collections import Counter, deque
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parent / 'validation' / 'match_monitor'
LIMIT = 8 * 1024 * 1024


def fields(value, names):
    """Only scalar values of explicitly permitted fields, never nested payloads."""
    if not isinstance(value, dict):
        return {}
    return {k: v for k in names if k in value
            for v in [value[k]] if v is None or type(v) in (bool, int)
            or (type(v) is float and math.isfinite(v))
            or (type(v) is str and len(v) <= 128)}


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def strategy_hash(game):
    folder = 'redalert_bot' if game == 'red_alert' else 'pokemon_bot'
    digest = hashlib.sha256()
    for path in sorted((Path(__file__).resolve().parent / folder).glob('*.py')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def make_monitor(context, policy=None):
    sid = getattr(context, 'session_id', '')
    if (not sid or sid.startswith(('offline', 'test', 'selftest'))
            or os.environ.get('COMPETITION_MONITOR_DISABLED') == '1'
            or os.environ.get('POKEMON_BOT_NO_CACHE') == '1'):
        return None
    return MatchMonitor(ROOT, context, policy)


class MatchMonitor:
    def __init__(self, root, context, policy=None):
        self.game = context.game_type
        self.sid = context.session_id
        self.agent_id = context.agent_id
        stem = hashlib.sha256(json.dumps([self.game, self.sid, self.agent_id]).encode()).hexdigest()[:24]
        self.path = root / (stem + '.jsonl')
        self.latest = root / (stem + '-latest.json')
        self.final = root / (stem + '-final.json')
        self.meta = dict(schema=1, game=self.game, session_id=self.sid,
                         seat=getattr(context, 'seat_position', None),
                         competition='tournament' if getattr(context, 'tournament_id', None) else 'testing',
                         profile=getattr(policy, 'profile', 'unknown' if self.game == 'red_alert' else 'pokemon_current'),
                         strategy_version=getattr(policy, 'strategy_version', 'unknown' if self.game == 'red_alert' else 'pokemon_current'),
                         strategy_hash=strategy_hash(self.game), worker_pid=os.getpid(),
                         started_at=time.time())
        self.commands, self.immediate, self.engine = Counter(), Counter(), Counter()
        self.pending_orders = deque(maxlen=32)
        self.dropped_order_batches = 0
        self.seen, self.window = set(), deque()
        self.last_sample = None
        self.last_signature = None
        self.snapshot = None
        self.decision_count = 0
        self.max_decision_seconds = 0.
        self.fallbacks = 0
        self.last_flags = set()
        self.started = False
        self.timeline_truncated = False

    def append(self, payload):
        line = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n'
        size = self.path.stat().st_size if self.path.exists() else 0
        if size + len(line.encode()) > LIMIT:
            self.timeline_truncated = True
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'a') as stream:
            stream.write(line)

    def save(self, row, terminal=False):
        # Independent sinks: a full/unwritable timeline cannot discard the result.
        row['timeline_truncated'] = self.timeline_truncated
        try:
            self.append(row)
        except Exception:
            self.timeline_truncated = True
        row['timeline_truncated'] = self.timeline_truncated
        try:
            atomic_json(self.final if terminal else self.latest, row)
        except Exception:
            pass

    def counters(self):
        return dict(decisions=self.decision_count, max_decision_seconds=self.max_decision_seconds,
                    strategy_fallbacks=self.fallbacks, proposed_commands=dict(self.commands),
                    immediate_verdicts=dict(self.immediate), engine_verdicts=dict(self.engine),
                    dropped_order_batches=self.dropped_order_batches)

    def read_verdicts(self, raw):
        last = raw.get('last_orders') or {}
        rows = [(last.get('batch', last.get('state_version')), r) for r in last.get('results', [])]
        rows += [(r.get('batch'), r) for r in raw.get('recent_order_problems') or []]
        for batch, row in rows:
            status = row.get('status')
            if batch is None or status not in {'ok', 'partial', 'rejected', 'lost'}:
                continue
            reason = row.get('reason', 'unknown')
            if not isinstance(reason, str) or len(reason) > 64 or not reason.replace('_', '').isalnum():
                reason = 'other'
            stamp = (batch, row.get('index'), status, reason)
            if stamp in self.seen:
                continue
            self.seen.add(stamp)
            self.window.append(stamp)
            self.engine[status + ':' + reason] += 1
            if len(self.window) > 4096:
                self.seen.discard(self.window.popleft())

    def red_snapshot(self, raw, context, policy):
        from redalert_bot.common import View
        v = View(raw, getattr(context, 'game_config', None))
        memory = getattr(policy, 'sessions', {}).get(self.sid, {})
        actor_fields = ('id', 'type', 'x', 'y', 'hp', 'idle')
        positions = lambda actors: [fields(a, actor_fields) for a in actors[:400]]
        return dict(seconds=v.now, remaining=v.remaining, map=v.map_id,
                    state_version=fields(raw, ('state_version',)).get('state_version'),
                    base=list(v.base),
                    max_minutes=(raw.get('time') or {}).get('max_minutes'),
                    **fields(v.obs, ('faction', 'enemy_faction')),
                    economy=fields(v.econ, ('cash', 'ore', 'harvesters', 'power_provided', 'power_drained')),
                    military=fields(v.military, ('kills_cost', 'deaths_cost', 'assets_value', 'army_value')),
                    units=dict(Counter(a['type'] for a in v.units)),
                    buildings=dict(Counter(a['type'] for a in v.buildings)),
                    own_positions=positions(v.units + v.buildings),
                    visible_contacts=positions(v.enemies + v.enemy_buildings),
                    production=[fields(p, ('item', 'queue', 'count', 'ready', 'progress')) for p in v.production[:50]],
                    mode=memory.get('combat', {}).get('combat', {}).get('mode'),
                    map_plan=fields(memory.get('map_adaptation', {}).get('plan', {}),
                                    ('map_id', 'active', 'style', 'route_cells', 'spawn_distance',
                                     'initial_home_resource_cells', 'early_infantry_cap',
                                     'second_ref_infantry_cap', 'defense_cash', 'defense_refs',
                                     'defense_miners', 'expansion_radius', 'expansion_screen',
                                     'productive_window')))

    def pokemon_snapshot(self, raw, state, action, policy):
        obs = raw.get('observation') or {}
        if isinstance(obs, str):
            obs = json.loads(obs)
        def board(key):
            return [fields(mon, ('species', 'current_hp_fraction', 'current_hp', 'max_hp', 'status', 'fainted'))
                    for mon in (obs.get(key) or [])[:2]]
        proposed = action if isinstance(action, dict) else getattr(action, 'input', {}).get('action', {})
        clean = fields(proposed, ('type', 'card_id'))
        for key in ('slot_0', 'slot_1'):
            if isinstance(proposed.get(key), dict):
                clean[key] = fields(proposed[key], ('type', 'move_id', 'target', 'species'))
        for key in ('bring', 'leads'):
            if isinstance(proposed.get(key), list):
                clean[key] = [v for v in proposed[key][:6] if isinstance(v, str) and len(v) <= 128]
        diagnostics = fields(getattr(policy, 'last_diagnostics', {}), ('fallback', 'seconds', 'phase'))
        return dict(phase=getattr(state, 'phase', None), turn=obs.get('turn'),
                    state_version=getattr(state, 'state_version', None),
                    own=board('active_pokemon'), opponent=board('opponent_active_pokemon'),
                    proposed_action=clean, diagnostics=diagnostics)

    def flags(self, snapshot):
        flags = []
        if self.game == 'red_alert':
            econ, military = snapshot['economy'], snapshot['military']
            if econ.get('power_drained', 0) > econ.get('power_provided', 0):
                flags.append('low_power_observed')
            if snapshot['seconds'] > 120 and snapshot['buildings'].get('proc', 0) and not snapshot['units'].get('harv', 0):
                flags.append('no_harvesters_observed')
            if military.get('deaths_cost', 0) - military.get('kills_cost', 0) > 2000:
                flags.append('negative_trade_over_2000')
            if sum(v for k, v in self.engine.items() if k.startswith(('rejected:', 'lost:'))) >= 5:
                flags.append('repeated_engine_order_problems')
        elif self.fallbacks:
            flags.append('strategy_fallback_observed')
        return flags

    def observe(self, state, context, action, policy, elapsed):
        raw = state.raw or {}
        self.decision_count += 1
        self.max_decision_seconds = max(self.max_decision_seconds, round(elapsed, 6))
        if self.game == 'red_alert':
            self.read_verdicts(raw)
            if isinstance(action, dict):
                cleaned = []
                for order in action.get('orders', []):
                    self.commands[order['cmd'] + (':' + order['item'] if 'item' in order else '')] += order.get('count', 1)
                    clean = fields(order, ('cmd', 'item', 'count', 'target', 'building', 'on', 'queued', 'stance'))
                    for key, cap in (('units', 50), ('to', 2), ('at', 2)):
                        if isinstance(order.get(key), list):
                            clean[key] = [n for n in order[key][:cap] if type(n) is int]
                    cleaned.append(clean)
                if cleaned:
                    self.dropped_order_batches += len(self.pending_orders) == self.pending_orders.maxlen
                    self.pending_orders.append(dict(state_version=raw.get('state_version'), orders=cleaned[:50]))
            now = float((raw.get('time') or {}).get('game_seconds', raw.get('state_version', 0) / 25))
            if self.last_sample is not None and 0 <= now - self.last_sample < 5:
                return
            snapshot = self.red_snapshot(raw, context, policy)
            self.last_sample = now
        else:
            snapshot = self.pokemon_snapshot(raw, state, action, policy)
            signature = json.dumps(snapshot, sort_keys=True)
            if signature == self.last_signature:
                return
            self.last_signature = signature
            self.fallbacks += snapshot['diagnostics'].get('fallback') is True
        if not self.started:
            self.save(dict(kind='start', **self.meta, updated_at=time.time()))
            self.started = True
        self.snapshot = snapshot
        flags = self.flags(snapshot)
        row = dict(kind='sample', **self.meta, updated_at=time.time(),
                   snapshot=snapshot, flags=flags, counters=self.counters())
        if self.game == 'red_alert':
            row['proposed_order_batches'] = list(self.pending_orders)
            self.pending_orders.clear()
        self.save(row)
        for flag in set(flags) - self.last_flags:
            print(f"[monitor {self.game} session={self.sid}] observed {flag}; review flag, not a proven cause", flush=True)
        self.last_flags = set(flags)

    def action_result(self, result):
        if result.get('error'):
            self.immediate['batch_error'] += 1
        for row in result.get('results') or []:
            if row.get('status') in {'ok', 'pending', 'partial', 'rejected', 'lost'}:
                self.immediate[row['status']] += 1

    def finish(self, state, context, policy):
        from altruagent.worker import game_outcome, _score
        outcome = game_outcome(state, self.agent_id)
        result = getattr(state, 'final_result', None) or {}
        # An incomplete/server-failed session is never silently a tactical loss.
        if result.get('status') == 'failed' or result.get('failure_reason'):
            outcome = 'no result'
        snapshot, exact, parse_error = self.snapshot, False, False
        try:
            raw = getattr(state, 'raw', {}) or {}
            if raw.get('observation'):
                if self.game == 'red_alert':
                    self.read_verdicts(raw)
                    snapshot = self.red_snapshot(raw, context, policy)
                else:
                    snapshot = self.pokemon_snapshot(raw, state, {}, policy)
                exact = raw.get('is_terminal') is True
        except Exception:
            parse_error = True
        try:
            flags = self.flags(snapshot) if snapshot else []
        except Exception:
            flags = ['snapshot_diagnostics_unavailable']
        row = dict(kind='final', **self.meta, updated_at=time.time(), outcome=outcome or 'unknown',
                   score=_score(state, self.agent_id),
                   server_failed=bool(result.get('status') == 'failed' or result.get('failure_reason')),
                   termination_reason=getattr(state, 'termination_reason', None) or result.get('termination_reason'),
                   result_source='worker_terminal_callback', snapshot=snapshot,
                   exact_final_observation=exact, snapshot_parse_error=parse_error,
                   flags=flags, counters=self.counters(), pending_order_batches=list(self.pending_orders),
                   review_needed=outcome in {'lost', 'timed out', 'resigned'})
        self.save(row, terminal=True)


def summarize(root=ROOT, now=None):
    """Read-only dashboard. Missing final result means unknown, NOT a loss."""
    now = time.time() if now is None else now
    games, invalid = {}, 0
    for suffix in ('-latest.json', '-final.json'):
        for path in root.glob('*' + suffix):
            try:
                row = json.loads(path.read_text())
                row['record_path'] = str(path)
                row['record_status'] = ('finished' if row['kind'] == 'final' else
                                        'recent_observation' if now - row['updated_at'] < 90 else
                                        'stale_or_waiting_no_result')
                games[path.name.removesuffix(suffix)] = row
            except (OSError, ValueError, KeyError, TypeError):
                invalid += 1
    rows = sorted(games.values(), key=lambda r: r.get('updated_at', 0), reverse=True)
    return dict(generated_at=now, games=rows, invalid_files=invalid,
                review_queue=[r['record_path'] for r in rows if r.get('review_needed')],
                coverage='Only instrumented workers; missing history, waiting states and disconnections are not inferred as losses.')


if __name__ == '__main__':
    print(json.dumps(summarize(), ensure_ascii=False, indent=2))
