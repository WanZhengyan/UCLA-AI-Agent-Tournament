"""Normalize supplied observations and publicly drafted fixed configuration cards."""
from __future__ import annotations

import copy
import math
from .dex import idnorm, species, stats

_UNKNOWN = {'unknown', 'unknownitem', 'unknownability', 'unrevealed', 'unrevealeditem', 'unrevealedability', 'questionmark', 'null'}
_STATUS = {'burn':'brn', 'burned':'brn', 'burnt':'brn', 'poison':'psn', 'poisoned':'psn', 'toxic':'tox',
           'badlypoisoned':'tox', 'sleep':'slp', 'asleep':'slp', 'paralysis':'par', 'paralyzed':'par',
           'paralysed':'par', 'freeze':'frz', 'frozen':'frz', 'none':'', 'healthy':'', 'fnt':''}
_PROTECT_MOVES = {'protect', 'detect', 'spikyshield', 'kingsshield', 'banefulbunker', 'silktrap', 'burningbulwark', 'obstruct', 'endure'}
_STAT_KEYS = {'attack':'atk', 'defense':'def', 'defence':'def', 'specialattack':'spa', 'specialdefense':'spd',
              'specialdefence':'spd', 'speed':'spe', 'accuracy':'accuracy', 'evasion':'evasion'}


def as_list(value):
    if isinstance(value, dict):
        return list(value.values())
    return value if isinstance(value, list) else []


def name_of(value):
    if isinstance(value, str):
        return value
    return (value or {}).get('species') or (value or {}).get('name') or ''


def moves_of(value):
    if isinstance(value, dict):
        return [idnorm(k) for k in value if idnorm(k)]
    return [key for x in (value or [])
            if (key := idnorm(x.get('id', x.get('move_id', x.get('name', ''))) if isinstance(x, dict) else x))]


def _known(value):
    if value is None or value == '' or value == [] or value == {}:
        return False
    if isinstance(value, str) and (value.strip() in ('?', '???') or idnorm(value) in _UNKNOWN):
        return False
    return True


def _merge_known(original, observed):
    """Unrevealed preview fields cannot erase a public fixed-set configuration."""
    result = copy.deepcopy(original)
    for key, value in observed.items():
        if not _known(value):
            continue
        if key in ('evs', 'ivs', 'base_stats', 'baseStats', 'stats', 'actual_stats') and isinstance(value, dict):
            accepted = {k: v for k, v in value.items() if _known(v)}
            if key in ('base_stats', 'baseStats'):
                accepted = {k: v for k, v in accepted.items() if isinstance(v, (int, float)) and v > 0}
            result[key] = {**(result.get(key) or {}), **copy.deepcopy(accepted)}
        else:
            result[key] = copy.deepcopy(value)
    return result


def _records(value):
    """Preserve a species name when a team dictionary omits it in its value."""
    if not isinstance(value, dict):
        return as_list(value)
    result = []
    for key, mon in value.items():
        if isinstance(mon, dict) and not name_of(mon):
            label = str(key).split(':', 1)[-1].strip()
            # Do not turn opaque player/slot placeholders into invented Pokemon.
            if species(label).get('exists'):
                mon = {**mon, 'species': label}
        result.append(mon)
    return result


def update_memory(obs, memory, own_seat=None):
    cards = memory.setdefault('cards', {})
    if own_seat and not memory.get('own_seat'):
        memory['own_seat'] = own_seat
    if obs.get('phase') == 'draft' and obs.get('current_seat'):
        memory['own_seat'] = obs['current_seat']

    def remember(card):
        if not isinstance(card, dict) or not name_of(card):
            return
        key = idnorm(name_of(card))
        cards[key] = _merge_known(cards.get(key, {}), card)

    for card in obs.get('available_cards', []):
        remember(card)
    for seat, roster in (obs.get('rosters') or {}).items():
        for card in _records(roster):
            remember(card)
        destination = 'own_roster' if seat == memory.get('own_seat') else 'foe_roster'
        memory[destination] = [_merge_known(cards.get(idnorm(name_of(c)), {}), c if isinstance(c, dict) else {'species': c})
                               for c in _records(roster)]
    for source, destination in [('your_roster', 'own_roster'), ('opponent_roster', 'foe_roster')]:
        if obs.get(source):
            roster = []
            for card in _records(obs[source]):
                card = card if isinstance(card, dict) else {'species': card}
                public = cards.get(idnorm(name_of(card)), {})
                merged = _merge_known(public, card)
                if public.get('moves'):
                    merged['moves'] = copy.deepcopy(public['moves'])
                roster.append(merged)
            memory[destination] = roster


def _finite(value, default=None):
    if isinstance(value, bool):
        return default
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _condition_keys(value):
    if isinstance(value, dict):
        return {idnorm(k): v for k, v in value.items() if idnorm(k)}
    if isinstance(value, str):
        return {idnorm(value): True} if value else {}
    return {idnorm(v.get('id', v.get('name', '')) if isinstance(v, dict) else v): True for v in (value or [])}


def normalize_mon(raw, memory, side='own'):
    if not raw:
        return None
    if isinstance(raw, str):
        raw = {'species': raw}
    if not isinstance(raw, dict) or not name_of(raw) or not _known(name_of(raw)):
        return None
    key = idnorm(name_of(raw))
    card = memory.get('cards', {}).get(key, {})
    for candidate in memory.get(side + '_roster', []):
        if idnorm(name_of(candidate)) == key:
            card = _merge_known(card, candidate)
            break
    data = _merge_known(card, raw)
    dx = species(key)
    stat_data = copy.deepcopy(data)
    if side == 'foe':
        # Opponent HP is usually reported on a 100-point percentage scale.
        # Recover actual HP from the fixed set, not the public display maximum.
        stat_data.pop('max_hp', None)
        stat_data.pop('maxhp', None)
        for field in ('stats', 'actual_stats'):
            if isinstance(stat_data.get(field), dict):
                stat_data[field].pop('hp', None)
    st = stats(stat_data)
    maximum = _finite(raw.get('max_hp', raw.get('maxhp')))
    if maximum and side == 'own':
        st['hp'] = maximum
    fraction = _finite(raw.get('current_hp_fraction', raw.get('hp_fraction')))
    if fraction is None and maximum:
        current = _finite(raw.get('current_hp'), maximum)
        fraction = current / maximum
    if fraction is None:
        fraction = 1.0
    if raw.get('fainted'):
        fraction = 0.0
    known = moves_of(raw.get('moves', []))
    config = moves_of(card.get('moves', []))
    types = raw.get('types') or card.get('types') or dx.get('types') or ['Normal']
    if isinstance(types, str):
        types = [types]
    types = [str(t).title() for t in types if _known(t)] or dx['types']
    status = idnorm(raw.get('status', ''))
    status = _STATUS.get(status, status)
    if status in _UNKNOWN:
        status = ''
    effects = _condition_keys(raw.get('effects') or raw.get('volatiles') or raw.get('volatile_statuses'))
    result = {**data, 'species': key, 'types': types, 'stats': st,
              'hp': max(0.0, min(1.0, fraction)), 'moves': list(dict.fromkeys(config + known)),
              'status': status, 'boosts': {_STAT_KEYS.get(idnorm(k), idnorm(k)): v for k, v in (raw.get('boosts') or {}).items()},
              'item': idnorm(data.get('item', '')), 'ability': idnorm(data.get('ability', '')),
              'effects': effects, 'volatiles': effects, 'first_turn': False, 'protect_count': 0}
    if ('item' in raw and raw['item'] == '') or raw.get('item_consumed') or raw.get('item_lost') or idnorm(raw.get('item')) in ('none', 'noitem'):
        result['item'] = ''
    for field in ('item', 'ability'):
        if result[field] in _UNKNOWN:
            result[field] = ''
    return result


def _forced_request(obs, template):
    force = obs.get('force_switch')
    if isinstance(force, (list, tuple)) and any(force):
        return True
    if force is True:
        return True
    return any(slot.get('force_switch') for slot in template.get('slots', []))


def _update_protect_counts(memory, previous, turn, board):
    """Commit the previous intended action only after the game turn advances.

    This is a conservative estimate: the public state may not confirm whether
    a planned Protect succeeded. Forced-switch decisions do not use a battle
    turn, so keep the preceding regular action across those intermediate states.
    """
    counts = memory.setdefault('_protect_counts', {})
    planned = memory.get('_planned_action')
    if previous and not previous[1] and isinstance(planned, dict) and planned.get('type') == 'doubles_turn':
        memory['_protect_pending'] = {'turn': previous[0], 'names': previous[2][0], 'action': copy.deepcopy(planned)}
    pending = memory.get('_protect_pending')
    if pending and turn > pending['turn'] and memory.get('_protect_committed_turn') != pending['turn']:
        for slot, name in enumerate(pending['names']):
            if not name:
                continue
            key = 'own:' + name
            action = pending['action'].get('slot_' + str(slot)) or {}
            if action.get('type') == 'move' and idnorm(action.get('move_id')) in _PROTECT_MOVES:
                counts[key] = min(8, counts.get(key, 0) + 1)
            else:
                counts[key] = 0
        memory['_protect_committed_turn'] = pending['turn']
        memory.pop('_protect_pending', None)
    old_names = set(previous[2][0]) if previous else set()
    current_names = set(board[0])
    for name in old_names.symmetric_difference(current_names):
        if name:
            counts['own:' + name] = 0
    return counts


def build_battle(obs, template, memory):
    def actives(key, side):
        raw = obs.get(key) or [None, None]
        if not isinstance(raw, list):
            raw = [raw, None]
        raw = (raw + [None, None])[:2]
        if side == 'own':
            for i, slot in enumerate(template.get('slots', [])):
                j = slot.get('slot', i)
                if j in (0, 1) and not raw[j] and slot.get('active'):
                    raw[j] = slot['active']
        return raw, [normalize_mon(x, memory, side) for x in raw]

    own_raw, own = actives('active_pokemon', 'own')
    foe_raw, foe = actives('opponent_active_pokemon', 'foe')
    turn = obs.get('turn', 0)
    forced = _forced_request(obs, template)
    board = (tuple(x['species'] if x else None for x in own), tuple(x['species'] if x else None for x in foe))
    stamp = (turn, forced, board)
    previous = memory.get('_request_stamp')
    entries = memory.setdefault('_entry_state', {})
    histories = memory.setdefault('_mon_history', {'own': {}, 'foe': {}})
    protect_counts = _update_protect_counts(memory, previous, turn, board)

    # A forced replacement is not a new battle turn. The previous regular move
    # opportunity has been spent, but a fresh replacement keeps its Fake Out
    # eligibility until it receives and completes a regular move opportunity.
    if previous and previous != stamp and not previous[1] and (forced or turn != previous[0]):
        for side_index, side in enumerate(('own', 'foe')):
            for name in previous[2][side_index]:
                if name and side + ':' + name in entries:
                    entries[side + ':' + name]['first'] = False
    for side_index, (side, mons, raws) in enumerate((('own', own, own_raw), ('foe', foe, foe_raw))):
        old_names = set(previous[2][side_index]) if previous else set()
        old_names.discard(None)
        for mon, raw in zip(mons, raws):
            if not mon:
                continue
            key = side + ':' + mon['species']
            if mon['species'] not in old_names:
                entries[key] = {'first': bool(previous or turn in (0, 1)), 'turn': turn}
            entry = entries.setdefault(key, {'first': False, 'turn': turn})
            mon['first_turn'] = entry['first'] and mon['hp'] > 0
            if isinstance(raw, dict):
                if isinstance(raw.get('first_turn'), bool):
                    mon['first_turn'] = raw['first_turn']
                active_actions = raw.get('active_move_actions', raw.get('activeMoveActions'))
                if isinstance(active_actions, (int, float)):
                    mon['first_turn'] = active_actions == 0
            mon['protect_count'] = protect_counts.get(key, 0)
            if isinstance(raw, dict) and isinstance(raw.get('protect_count'), (int, float)):
                mon['protect_count'] = max(0, min(8, int(raw['protect_count'])))
            histories[side][mon['species']] = copy.deepcopy(raw if isinstance(raw, dict) else {'species': mon['species']})
    memory['_request_stamp'] = stamp
    memory['_board_stamp'] = (turn, *board)

    def reserves(side, team_key, active):
        history = histories[side]
        active_names = {mon['species'] for mon in active if mon}
        observed = _records(obs.get(team_key))
        if side == 'foe' and len(observed) > 4:
            observed = [raw for raw in observed if isinstance(raw, dict) and
                        (raw.get('revealed') or raw.get('active') or raw.get('fainted') or idnorm(name_of(raw)) in active_names)]
        for raw in observed:
            if name_of(raw):
                history[idnorm(name_of(raw))] = copy.deepcopy(raw if isinstance(raw, dict) else {'species': raw})
        bring = memory.get('bring') if side == 'own' else memory.get('foe_bring')
        if isinstance(bring, dict):
            bring = bring.get('bring')
        selected = list(dict.fromkeys(idnorm(name_of(mon)) for mon in (bring or []) if name_of(mon)))
        if side == 'own' and selected:
            candidates = [history.get(name, {'species': name}) for name in selected]
        elif observed:
            # Battle team summaries are authoritative, unlike six-member preview
            # rosters. Hidden entries with no species remain unknown slots.
            candidates = observed
            if len(candidates) > 4:
                candidates = [raw for raw in candidates if isinstance(raw, dict) and
                              (raw.get('revealed') or raw.get('active') or raw.get('fainted') or idnorm(name_of(raw)) in active_names)]
        else:
            candidates = list(history.values())
        candidates_by_name = {idnorm(name_of(raw)): raw for raw in candidates if name_of(raw)}
        # Keep earlier fainted/revealed identities even if the current public
        # dictionary omits them, to avoid resurrecting unknown reserve slots.
        for name, raw in history.items():
            if side == 'foe' or not selected or name in selected:
                candidates_by_name.setdefault(name, raw)
        out = []
        seen = set(active_names)
        fainted_names = {mon['species'] for mon in active if mon and mon['hp'] <= 0}
        for name, raw in candidates_by_name.items():
            mon = normalize_mon(raw, memory, side)
            if not mon:
                continue
            if mon['hp'] <= 0:
                fainted_names.add(mon['species'])
            if mon['species'] not in seen and mon['hp'] > 0:
                out.append(mon)
                seen.add(mon['species'])
        alive_active = sum(mon is not None and mon['hp'] > 0 for mon in active)
        capacity = max(0, 4 - len(fainted_names) - alive_active)
        out = out[:capacity]
        known_identities = set(candidates_by_name) | active_names
        unknown = max(0, 4 - len(known_identities)) if side == 'foe' or not selected else 0
        return out, min(unknown, max(0, capacity - len(out)))

    own_bench, own_unknown = reserves('own', 'team', own)
    foe_bench, foe_unknown = reserves('foe', 'opponent_team', foe)
    weather = obs.get('weather') or ''
    if isinstance(weather, dict):
        weather = next(iter(weather), '')
    elif isinstance(weather, list):
        weather = weather[0] if weather else ''
    field = {'weather': idnorm(weather)}
    fields = _condition_keys(obs.get('fields'))
    own_c = _condition_keys(obs.get('side_conditions'))
    foe_c = _condition_keys(obs.get('opponent_side_conditions'))
    field['terrain'] = next((key for key in fields if 'terrain' in key), '')
    field['trickroom'] = 'trickroom' in fields
    for side, conditions in [('own', own_c), ('foe', foe_c)]:
        for condition in ('tailwind', 'reflect', 'lightscreen', 'auroraveil', 'safeguard'):
            field[side + '_' + condition] = condition in conditions
    available = obs.get('available_moves') or []
    for i, mon in enumerate(own):
        if mon and i < len(available) and isinstance(available[i], list):
            mon['move_details'] = {idnorm(value.get('id', value.get('move_id', ''))): value for value in available[i] if isinstance(value, dict)}
            mon['moves'] = list(dict.fromkeys(mon['moves'] + list(mon['move_details'])))
    return {'own': own, 'foe': foe, 'own_bench': own_bench, 'foe_bench': foe_bench,
            'own_unknown_reserves': own_unknown, 'foe_unknown_reserves': foe_unknown,
            'field': field, 'turn': turn, 'forced_switch': forced}
