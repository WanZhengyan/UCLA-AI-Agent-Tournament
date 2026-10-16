"""Regressions for high-impact tactical approximation and boundary handling."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pokemon_bot.battle import damage, evaluate, simulate
from pokemon_bot.state import normalize_mon


def mon(name, moves=(), **kwargs):
    return normalize_mon(dict(species=name, moves=list(moves), current_hp_fraction=1., **kwargs), {})


PASS = {"type": "pass"}


def action(name, target=1):
    return {"type": "move", "move_id": name, "target": target}


def battle(ours, theirs, **kwargs):
    return dict(own=[ours, None], foe=[theirs, None], own_bench=[], foe_bench=[], field={}, **kwargs)


class BattleRegressions(unittest.TestCase):
    def test_ivycudgel_uses_wellspring_water_type(self):
        p=mon("Ogerpon-Wellspring", ["ivycudgel"], item="Wellspring Mask")
        q=mon("Arcanine")
        # Water hits Fire super effectively; the raw Dex default is Grass.
        self.assertGreater(damage(p,q,"ivycudgel"), 3*damage(p,q,"woodhammer"))

    def test_ivycudgel_uses_hearthflame_fire_type(self):
        p=mon("Ogerpon-Hearthflame", ["ivycudgel"], item="Hearthflame Mask")
        q=mon("Scizor")
        self.assertGreater(damage(p,q,"ivycudgel"), 10*damage(p,q,"woodhammer"))

    def test_forced_replacement_does_not_give_opponent_free_attack(self):
        reserve=mon("Garchomp", ["earthquake"], status="brn")
        reserve["hp"] = .5
        foe=mon("Kyogre", ["icebeam"])
        state=battle(None, foe, forced_switch=True)
        state["own_bench"]=[reserve]
        ours=({"type":"switch", "species":"garchomp"}, PASS)
        attacking=simulate(state,(ours,(action("icebeam"),PASS)),horizon=False)
        passing=simulate(state,(ours,(PASS,PASS)),horizon=False)
        self.assertAlmostEqual(attacking,passing)
        expected=evaluate([[reserve,{}],[foe,{}]],[[],[]],{},horizon=False)
        self.assertAlmostEqual(passing,expected)  # no burn/residual damage either

    def test_psychic_terrain_blocks_fakeout_on_grounded_opponent(self):
        p=mon("Incineroar",["fakeout"]); p["first_turn"]=True
        q=mon("Pikachu",["thunderbolt"])
        state=battle(p,q); state["field"]={"terrain":"psychicterrain"}
        attacking=((action("fakeout"),PASS),(action("thunderbolt"),PASS))
        abstaining=((action("splash",0),PASS),(action("thunderbolt"),PASS))
        self.assertAlmostEqual(simulate(state,attacking,False),simulate(state,abstaining,False))

    def test_covert_cloak_prevents_fakeout_flinch(self):
        p=mon("Incineroar",["fakeout"]); p["first_turn"]=True
        q=mon("Pikachu",["thunderbolt"])
        state=battle(p,q)
        acts=((action("fakeout"),PASS),(action("thunderbolt"),PASS))
        flinched=simulate(state,acts,False)
        state["foe"][0]["item"]="covertcloak"
        immune=simulate(state,acts,False)
        self.assertGreater(flinched,immune+.05)

    def test_repeat_protect_is_priced_as_unreliable(self):
        p=mon("Incineroar",["protect"])
        q=mon("Pikachu",["thunderbolt"])
        state=battle(p,q)
        acts=((action("protect",0),PASS),(action("thunderbolt"),PASS))
        first=simulate(state,acts,False)
        state["own"][0]["protect_count"]=1
        second=simulate(state,acts,False)
        state["own"][0]["protect_count"]=2
        third=simulate(state,acts,False)
        self.assertGreater(first,second)
        self.assertGreater(second,third)

    def test_unrevealed_reserve_prevents_false_terminal_win(self):
        state=battle(mon("Incineroar"),None)
        acts=((PASS,PASS),(PASS,PASS))
        terminal=simulate(state,acts,False)
        state["foe_unknown_reserves"]=1
        ongoing=simulate(state,acts,False)
        self.assertGreater(terminal-ongoing,18)

    def test_simulation_does_not_mutate_observed_state(self):
        state=battle(mon("Incineroar",["flareblitz"]),mon("Rillaboom",["woodhammer"]))
        original=copy.deepcopy(state)
        simulate(state,((action("flareblitz"),PASS),(action("woodhammer"),PASS)))
        self.assertEqual(state,original)


if __name__ == "__main__":
    unittest.main()
