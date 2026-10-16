from pokemon_bot.state import normalize_mon, update_memory, build_battle
from pokemon_bot.dex import stats


def card(name='Incineroar', **extra):
    return {'species': name, 'nature': 'Careful', 'ability': 'Intimidate', 'item': 'Sitrus Berry',
            'level': 50, 'evs': {'hp': 252, 'spd': 252, 'def': 4}, 'ivs': {},
            'moves': ['Fake Out', 'Flare Blitz', 'Parting Shot', 'Knock Off'], **extra}


def mon(name='Incineroar', **extra):
    return {'species': name, 'current_hp_fraction': 1, 'fainted': False, 'revealed': True, **extra}


def template(forced=False):
    return {'slots': [{'slot': 0, 'force_switch': forced}, {'slot': 1, 'force_switch': False}]}


def test_foe_public_percentage_does_not_replace_actual_hp():
    c = card()
    memory = {'cards': {'incineroar': c}}
    foe = normalize_mon(mon(max_hp=100, current_hp=50, current_hp_fraction=.5), memory, 'foe')
    assert foe['stats']['hp'] == stats(c)['hp'] == 202
    assert foe['hp'] == .5
    own = normalize_mon(mon(max_hp=201), memory)
    assert own['stats']['hp'] == 201


def test_preview_unknown_does_not_erase_public_set():
    memory = {}
    update_memory({'phase': 'draft', 'current_seat': 'A', 'available_cards': [card()]}, memory)
    update_memory({'phase': 'team_preview', 'your_roster': [mon(nature='UNKNOWN', ability='unknown_ability', item='unknown_item',
                   evs={}, ivs={}, moves=['fakeout'], base_stats={'hp': 0})]}, memory, own_seat='agent-identifier')
    assert memory['own_seat'] == 'A'
    assert memory['own_roster'][0]['nature'] == 'Careful'
    assert memory['own_roster'][0]['evs']['hp'] == 252
    result = normalize_mon(mon(ability='unknown', item='unknown', nature='unknown'), memory)
    assert result['ability'] == 'intimidate'
    assert result['item'] == 'sitrusberry'
    assert result['stats']['hp'] == 202
    assert len(result['moves']) == 4


def test_first_turn_survives_forced_replacement_but_not_complete_turn():
    memory = {}
    obs = {'turn': 1, 'active_pokemon': [mon(), mon('Rillaboom')], 'opponent_active_pokemon': [mon('Gholdengo'), mon('Amoonguss')]}
    first = build_battle(obs, template(), memory)
    assert all(p['first_turn'] for p in first['own'])
    repeated = build_battle(obs, template(), memory)
    assert all(p['first_turn'] for p in repeated['own'])
    forced = {**obs, 'force_switch': [True, False], 'active_pokemon': [mon(fainted=True, current_hp_fraction=0), mon('Rillaboom')]}
    replacement = build_battle(forced, template(True), memory)
    assert not replacement['own'][1]['first_turn']
    # The replacement enters during the forced-switch phase of turn 1.
    replacement_obs = {**forced, 'active_pokemon': [mon('Iron Hands'), mon('Rillaboom')]}
    replacement = build_battle(replacement_obs, template(True), memory)
    assert replacement['own'][0]['first_turn']
    next_obs = {**obs, 'turn': 2, 'active_pokemon': [mon('Iron Hands'), mon('Rillaboom')]}
    after = build_battle(next_obs, template(), memory)
    assert after['own'][0]['first_turn']
    assert not after['own'][1]['first_turn']
    last = build_battle({**next_obs, 'turn': 3}, template(), memory)
    assert not last['own'][0]['first_turn']


def test_no_six_member_phantom_bench_and_selected_own_lineup():
    names = ['Incineroar', 'Rillaboom', 'Amoonguss', 'Flutter Mane', 'Iron Hands', 'Gholdengo']
    memory = {'own_roster': [card(n) for n in names], 'foe_roster': [card(n) for n in names], 'bring': names[:4]}
    obs = {'turn': 1, 'active_pokemon': [mon(names[0]), mon(names[1])],
           'opponent_active_pokemon': [mon(names[4]), mon(names[5])]}
    state = build_battle(obs, template(), memory)
    assert {m['species'] for m in state['own_bench']} == {'amoonguss', 'fluttermane'}
    assert state['foe_bench'] == []
    assert state['foe_unknown_reserves'] == 2
    obs['opponent_team'] = {n: mon(n, revealed=n in names[4:]) for n in names}
    state = build_battle(obs, template(), memory)
    assert state['foe_bench'] == []
    assert state['foe_unknown_reserves'] == 2


def test_remember_observed_reserves_and_do_not_resurrect_fainted():
    memory = {}
    obs = {'turn': 1, 'active_pokemon': [mon(), mon('Rillaboom')],
           'opponent_active_pokemon': [mon('Amoonguss'), mon('Gholdengo')]}
    build_battle(obs, template(), memory)
    obs = {**obs, 'turn': 2, 'opponent_active_pokemon': [mon('Iron Hands'), mon('Gholdengo')]}
    result = build_battle(obs, template(), memory)
    assert [m['species'] for m in result['foe_bench']] == ['amoonguss']
    assert result['foe_unknown_reserves'] == 1
    obs['opponent_team'] = {'a': mon('Amoonguss', fainted=True, current_hp_fraction=0)}
    result = build_battle(obs, template(), memory)
    assert result['foe_bench'] == []
    assert result['foe_unknown_reserves'] == 1


def test_status_and_field_case_normalization():
    memory = {}
    obs = {'turn': 1, 'active_pokemon': [mon(status='BURN', boosts={'Special Attack': 1}, effects={'TAUNT': 1}), None],
           'weather': {'RAINDANCE': 1}, 'fields': {'TRICK_ROOM': 1, 'PSYCHIC_TERRAIN': 1}, 'side_conditions': {'TAILWIND': 1}}
    result = build_battle(obs, template(), memory)
    assert result['own'][0]['status'] == 'brn'
    assert result['own'][0]['boosts'] == {'spa': 1}
    assert result['own'][0]['effects'] == {'taunt': 1}
    assert result['field']['terrain'] == 'psychicterrain'
    assert result['field']['trickroom'] and result['field']['own_tailwind']


def test_empty_item_means_consumed_and_unknown_means_hidden():
    memory = {'cards': {'incineroar': card()}}
    for side in ('own', 'foe'):
        assert normalize_mon(mon(item=''), memory, side)['item'] == ''
        assert normalize_mon(mon(item=None), memory, side)['item'] == 'sitrusberry'
        assert normalize_mon(mon(item='unknown_item'), memory, side)['item'] == 'sitrusberry'


def test_protect_streak_committed_once_on_turn_advance_and_resets():
    memory = {}
    obs = {'turn': 1, 'active_pokemon': [mon(), mon('Rillaboom')]}
    build_battle(obs, template(), memory)
    memory['_planned_action'] = {'type': 'doubles_turn', 'slot_0': {'type': 'move', 'move_id': 'protect'},
                                  'slot_1': {'type': 'move', 'move_id': 'detect'}}
    same = build_battle(obs, template(), memory)
    assert same['own'][0]['protect_count'] == 0
    second = build_battle({**obs, 'turn': 2}, template(), memory)
    assert [m['protect_count'] for m in second['own']] == [1, 1]
    second_repeat = build_battle({**obs, 'turn': 2}, template(), memory)
    assert [m['protect_count'] for m in second_repeat['own']] == [1, 1]
    memory['_planned_action'] = {'type': 'doubles_turn', 'slot_0': {'type': 'move', 'move_id': 'spikyshield'},
                                  'slot_1': {'type': 'move', 'move_id': 'grassyglide'}}
    third = build_battle({**obs, 'turn': 3}, template(), memory)
    assert [m['protect_count'] for m in third['own']] == [2, 0]
    memory['_planned_action'] = {'type': 'doubles_turn', 'slot_0': {'type': 'switch', 'species': 'Amoonguss'},
                                  'slot_1': {'type': 'pass'}}
    fourth = build_battle({**obs, 'turn': 4, 'active_pokemon': [mon('Amoonguss'), mon('Rillaboom')]}, template(), memory)
    assert [m['protect_count'] for m in fourth['own']] == [0, 0]
    assert memory['_protect_counts']['own:incineroar'] == 0


def test_protect_streak_survives_intermediate_forced_switch_pass():
    memory = {}
    obs = {'turn': 1, 'active_pokemon': [mon(), mon('Rillaboom')]}
    build_battle(obs, template(), memory)
    memory['_planned_action'] = {'type': 'doubles_turn', 'slot_0': {'type': 'move', 'move_id': 'protect'},
                                  'slot_1': {'type': 'move', 'move_id': 'grassyglide'}}
    forced_obs = {**obs, 'force_switch': [False, True], 'active_pokemon': [mon(), mon('Rillaboom', fainted=True, current_hp_fraction=0)]}
    build_battle(forced_obs, template(True), memory)
    assert memory['_protect_counts'].get('own:incineroar', 0) == 0
    memory['_planned_action'] = {'type': 'doubles_turn', 'slot_0': {'type': 'pass'},
                                  'slot_1': {'type': 'switch', 'species': 'Amoonguss'}}
    next_obs = {**obs, 'turn': 2, 'active_pokemon': [mon(), mon('Amoonguss')]}
    result = build_battle(next_obs, template(), memory)
    assert [m['protect_count'] for m in result['own']] == [1, 0]
