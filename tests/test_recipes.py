"""Every recipe, the failure rule, and the shuffle."""
import pytest
from conftest import flat_world

from tinyworld.sim import defs, text as T
from tinyworld.sim.recipes import BASE, all_reachable, build_recipes

CASES = []
for r in BASE:
    items = r.items()
    fuel = items.pop("fuel", 0)
    for f in (defs.FUELS if fuel else [None]):
        full = dict(items)
        if f:
            full[f] = full.get(f, 0) + fuel
        CASES.append((r, full))


def test_table_matches_the_plan():
    assert len(BASE) == 20 and len(CASES) == 22
    assert {r.output: r.count for r in BASE} == {
        "planks": 4, "sticks": 4, "workbench": 1, "door": 1, "wood pickaxe": 1, "stone pickaxe": 1,
        "stone sword": 1, "furnace": 1, "torch": 4, "cooked meat": 1, "iron ingot": 1,
        "iron pickaxe": 1, "iron sword": 1, "wood sword": 1, "iron helmet": 1, "iron chestplate": 1, "chest": 1,
        "bread": 1, "bed": 1}
    assert all(r.output in defs.ITEMS for r in BASE)


@pytest.mark.parametrize("recipe,items", CASES, ids=[f"{r.output} from {'+'.join(i)}" for r, i in CASES])
def test_recipe(recipe, items):
    w = flat_world()
    for k, v in items.items():
        w._add(k, v + 1)
    if recipe.station:
        # Three cells away is not nearby. Nothing is made, nothing is used up, one step passes.
        w.set_block(35, 10, 32, recipe.station)
        r = w.step({"name": "craft", "items": items})
        assert r.text == T.NOT_MADE_STATION.format(station=recipe.station, r=2) and r.valid and r.steps == 1
        assert all(w.inv[k] == v + 1 for k, v in items.items())
        assert [e["type"] for e in r.events] == ["craft_fail"]
        w.set_block(34, 10, 32, recipe.station)
    before = dict(w.inv)
    r = w.step({"name": "craft", "items": items})
    assert r.text == f"Made {recipe.count} {recipe.output}." and r.steps == 1 and r.valid
    for k, v in items.items():
        assert w.inv.get(k, 0) == before[k] - v + (recipe.count if k == recipe.output else 0)
    assert w.inv[recipe.output] >= recipe.count
    assert r.events == [{"t": w.t - 1, "type": "first_craft", "detail": {"item": recipe.output}}]
    if recipe.output in defs.TOOLS:
        assert w.tools[recipe.output] == w.cfg.durability[recipe.output]


def test_failed_craft_keeps_items_and_costs_a_step(flat):
    flat._add("planks", 5)
    flat._add("sticks", 5)
    r = flat.step({"name": "craft", "items": {"planks": 1, "sticks": 1}})
    assert r.text == T.NOT_MADE_EXACT and r.steps == 1 and flat.inv == {"planks": 5, "sticks": 5}
    assert r.events[0]["type"] == "craft_fail" and r.events[0]["detail"] == {"items": {"planks": 1, "sticks": 1}}
    # More than the exact amounts is not a match either.
    assert flat.step({"name": "craft", "items": {"planks": 3}}).text == T.NOT_MADE_EXACT


def test_failed_craft_says_which_station_is_missing(flat):
    flat._add("planks", 5)
    flat._add("sticks", 5)
    r = flat.step({"name": "craft", "items": {"planks": 3, "sticks": 2}})
    assert r.text == "Nothing was made. No workbench within 2 cells." and r.valid
    assert r.events[0]["type"] == "craft_fail"
    flat.set_block(34, 10, 32, "workbench")
    assert flat.step({"name": "craft", "items": {"planks": 3, "sticks": 2}}).text == "Made 1 wood pickaxe."


def test_rule_notes_off_keeps_the_one_failure_line():
    from conftest import flat_world
    w = flat_world(rule_notes=False)
    w._add("planks", 5)
    w._add("sticks", 5)
    for items in ({"planks": 1}, {"planks": 3, "sticks": 2}):
        assert w.step({"name": "craft", "items": items}).text == T.NOT_MADE
    w.step({"name": "craft", "items": {"planks": 2}})
    w.health, w.food = 10, 5
    obs = w.observe()
    assert "things you have made" not in obs and "does not rise" not in obs


def test_craft_with_missing_items_is_invalid(flat):
    flat._add("planks", 1)
    r = flat.step({"name": "craft", "items": {"log": 1}})
    assert r.text == T.NO_ITEM and not r.valid and r.steps == 1
    r = flat.step({"name": "craft", "items": {"planks": 2}})
    assert r.text == "Not enough planks in inventory." and not r.valid
    for bad in [{}, {"planks": 0}, {"planks": "x"}, None, [1]]:
        assert flat.step({"name": "craft", "items": bad}).text == T.BAD_ARGS


def test_base_recipes_are_reachable():
    assert all_reachable(BASE)


@pytest.mark.parametrize("seed", range(1, 21))
def test_shuffle_keeps_every_recipe_reachable(seed):
    rs = build_recipes(True, seed)
    assert rs != BASE and all_reachable(rs)
    assert rs == build_recipes(True, seed)
    assert [(r.output, r.count, r.station) for r in rs] == [(r.output, r.count, r.station) for r in BASE]
    for tier in (0, 1, 2):          # input sets only move within their tier
        assert sorted(r.inputs for r in rs if r.tier == tier) == sorted(r.inputs for r in BASE if r.tier == tier)


def test_shuffle_differs_between_seeds():
    assert len({tuple(build_recipes(True, s)) for s in range(1, 21)}) > 5


def test_shuffled_world_crafts_by_the_shuffled_table():
    w = flat_world(shuffle_recipes=True)
    r = next(r for r in w.recipes if r.station is None and "fuel" not in r.items())
    for k, v in r.items().items():
        w._add(k, v)
    assert w.step({"name": "craft", "items": r.items()}).text == f"Made {r.count} {r.output}."
