"""Public observations establish speed-control duration only when justified."""
import pytest

from pokemon_bot.state import build_battle


def view(memory, turn, own=None, foe=None, fields=None, forced=False):
    return build_battle({'turn': turn, 'side_conditions': own or {},
                         'opponent_side_conditions': foe or {}, 'fields': fields or {},
                         'force_switch': [forced, False]}, {}, memory)['field']


@pytest.mark.parametrize('key,kwargs', [
    ('own_tailwind', {'own': {'tailwind': 1}}),
    ('foe_tailwind', {'foe': ['tailwind']}),
    ('trickroom', {'fields': {'trickroom': 1}}),
])
def test_first_active_snapshot_has_unknown_age(key, kwargs):
    field = view({}, 3, **kwargs)
    assert field[key]
    assert key + '_turns' not in field


@pytest.mark.parametrize('key,kwargs,duration', [
    ('own_tailwind', {'own': ['tailwind']}, 4),
    ('foe_tailwind', {'foe': ['tailwind']}, 4),
    ('trickroom', {'fields': ['trickroom']}, 5),
])
def test_observed_activation_counts_current_turn(key, kwargs, duration):
    memory = {}
    view(memory, 1)
    for turn in range(2, duration + 1):
        assert view(memory, turn, **kwargs)[key + '_turns'] == duration + 1 - turn
    # A still-active condition beyond the inferred lifetime invalidates age,
    # rather than overriding the server's authoritative active flag.
    field = view(memory, duration + 1, **kwargs)
    assert field[key] and key + '_turns' not in field


def test_forced_replacement_does_not_age_tailwind():
    memory = {}
    view(memory, 1)
    assert view(memory, 1, own=['tailwind'], forced=True)['own_tailwind_turns'] == 4
    assert view(memory, 1, own=['tailwind'], forced=True)['own_tailwind_turns'] == 4
    assert view(memory, 2, own=['tailwind'])['own_tailwind_turns'] == 3


def test_missing_turns_discard_inferred_duration():
    memory = {}
    view(memory, 1)
    view(memory, 2, own=['tailwind'])
    field = view(memory, 4, own=['tailwind'])
    assert field['own_tailwind'] and 'own_tailwind_turns' not in field


def test_disappearance_then_reapplication_starts_new_counter():
    memory = {}
    view(memory, 1)
    view(memory, 2, fields=['trickroom'])
    assert not view(memory, 3)['trickroom']
    assert view(memory, 4, fields=['trickroom'])['trickroom_turns'] == 4


def test_false_flags_are_inactive_but_zero_is_not_a_boolean():
    field = view({}, 3, own={'tailwind': False}, foe={'tailwind': 0}, fields={'trickroom': False})
    assert not field['own_tailwind'] and not field['trickroom']
    assert field['foe_tailwind'] and 'foe_tailwind_turns' not in field


def test_explicit_named_metadata_is_supported_without_interpreting_bare_numbers():
    field = view({}, 8, own={'tailwind': {'turns_remaining': 1}},
                 fields=[{'id': 'trickroom', 'start_turn': 5}])
    assert field['own_tailwind_turns'] == 1
    assert field['trickroom_turns'] == 2
