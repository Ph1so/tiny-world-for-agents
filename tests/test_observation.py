"""Observation text: layout, line of sight, wording rules, alien names."""
import re

import numpy as np
import pytest
from conftest import flat_world, make_world

from tinyworld.bots.sensible_bot import SensibleBot
from tinyworld.sim import defs, text as T

BANNED = ["goal", "should", "try to", "survive", "danger", "tip", "hint", "recipe"]


def bot_run(seed: int, steps: int, **overrides):
    """Observations and result texts from a sensible bot run."""
    w, bot, obs, results = make_world(seed, **overrides), SensibleBot(seed), [], []
    while w.t < steps:
        o = w.observe()
        obs.append(o)
        results.append(w.step(bot.act(o, w)).text)
    return w, obs, results


@pytest.fixture(scope="module")
def familiar_run():
    return bot_run(1, 2400)


@pytest.fixture(scope="module")
def alien_run():
    return bot_run(1, 2400, names="alien")


def test_layout(flat):
    flat._add("stone pickaxe", 1)
    flat._add("planks", 6)
    flat.cfg.creatures.passive_move_prob = 0.0
    flat._spawn("sheep", (28, 10, 35))
    flat.set_block(34, 10, 32, "stone")
    flat.step({"name": "mine", "x": 34, "y": 10, "z": 32})
    lines = flat.observe().split("\n")
    assert lines[:7] == [
        "step 3 | day 1 | light bright | sky bright | weather clear",
        "position (32, 10, 32), head at (32, 11, 32)",
        "open cells touching you: all 9 (4 sides at feet and at head level, and above the head)",
        "health 20/20 (20 at step 0) | food 20/20 (20 at step 0) | air 10/10",
        "inventory (3 of 10 slots): stone pickaxe (59 uses left), planks x6, stone x1",
        "last action: mine (34, 10, 32). Result: Got 1 stone.",
        "",
    ]
    assert lines[7] == "close (within 3 cells):"
    assert lines[8].startswith("  grass: 49 seen, nearest (32,9,32) ")
    assert lines[9] == "  open air above your head, from (32,12,32) up"
    assert lines[10] == "in view (within 12 cells):"
    assert lines[11].startswith("  grass: ") and lines[11].endswith(" seen, nearest (28,9,32)")
    assert lines[12:] == ["creatures:", "  sheep #1 at (28,10,35)"]


def test_open_cells_touching_the_body_and_the_sky(flat):
    """runs/haiku_fresh_s2_v2: walls at the feet only, killed from head level three times; and a
    roofed shelter read "dark" at noon, so it waited for a daylight that never came."""
    flat.cfg.creatures.passive_move_prob = 0.0
    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        flat.set_block(32 + dx, 10, 32 + dz, "stone")             # feet level walled
    flat.set_block(32, 12, 32, "stone")                           # roof
    lines = flat.observe().split("\n")
    assert lines[0] == "step 0 | day 1 | light dark | sky bright | weather clear"
    assert lines[2] == ("open cells touching you: head north (32,11,31), head south (32,11,33), "
                        "head east (33,11,32), head west (31,11,32)")
    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        flat.set_block(32 + dx, 11, 32 + dz, "stone")
    assert flat.observe().split("\n")[2] == "open cells touching you: none"


def test_vitals_line_shows_health_and_food_a_lookback_ago(flat):
    """Food drain is slow (1 per 15 steps): the agent sees it only by comparing with earlier."""
    flat.cfg.creatures.passive_move_prob = 0.0
    assert "health 20/20 | food 20/20 | air 10/10" in flat.observe()      # step 0: nothing to compare
    for _ in range(10):
        flat.step({"name": "wait", "steps": 8})
    assert flat.t == 80 and flat.food == 15
    assert "health 20/20 (20 at step 20) | food 15/20 (19 at step 20) | air 10/10" in flat.observe()
    flat.cfg.vitals_lookback = 0
    assert "health 20/20 | food 15/20 | air 10/10" in flat.observe()


def test_no_xray(flat):
    """Blocks behind a wall, under the ground, or inside a closed box are not listed."""
    flat.set_block(32, 5, 32, "coal ore")                 # buried
    for y in (10, 11, 12, 13):
        for x in range(20, 45):
            flat.set_block(x, y, 29, "stone")             # a wall to the north
    flat.set_block(32, 10, 26, "iron ore")                # behind the wall
    flat.set_block(32, 10, 36, "log")                     # in the open to the south
    flat._spawn("sheep", (33, 10, 25))
    flat._spawn("chicken", (34, 10, 36))
    obs = flat.observe()
    assert "coal ore" not in obs and "iron ore" not in obs and "sheep" not in obs
    assert "log: nearest (32,10,36)" in obs and "chicken #2" in obs
    flat.set_block(32, 10, 29, "air")
    flat.set_block(32, 11, 29, "air")                     # a gap in the wall
    obs = flat.observe()
    assert "iron ore: nearest (32,10,26)" in obs and "sheep #1" in obs and "coal ore" not in obs


def test_enclosed_agent_sees_only_the_walls():
    w = flat_world()
    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for dy in (0, 1):
            w.set_block(32 + dx, 10 + dy, 32 + dz, "planks")
    w.set_block(32, 12, 32, "planks")
    w.set_block(36, 10, 32, "log")
    obs = w.observe()
    assert "planks: 9 seen" in obs and "log" not in obs
    assert "planks above your head at (32,12,32)" in obs and "open air" not in obs
    assert obs.split("in view (within 12 cells):\n")[1].startswith("  nothing")


def test_only_listed_cells_are_really_visible():
    """Every listed far block has a clear straight line from the eye on a real map."""
    from tinyworld.sim.observe import visible_blocks
    w = make_world(4)
    cells, ids = visible_blocks(w)
    assert len(cells) > 50
    assert (np.abs(cells - np.array(w.pos)).max(1) <= w.cfg.view_radius).all()
    assert (ids != defs.AIR).all()
    hidden = w.blocks.copy()
    mask = w.exposed_mask()
    for x, y, z in cells:                                  # nothing buried is listed
        assert mask[y, z, x] or w.block(x, y, z) == "water"
    assert (hidden == w.blocks).all()


def test_templates_have_no_banned_words():
    assert len(T.TEMPLATES) > 30
    for tpl in T.TEMPLATES:
        assert not any(b in tpl.lower() for b in BANNED), tpl


def test_bot_run_text_has_no_banned_words_and_stays_short(familiar_run):
    w, obs, results = familiar_run
    assert len(w.firsts["craft"]) == 19
    for text in obs + results:
        assert not any(b in text.lower() for b in BANNED), text
    # About 600 tokens. Coordinates cost about one token per 2.5 characters. The list of things
    # made grows to all 19 in this run and is measured on its own.
    made = [line for o in obs for line in o.splitlines() if line.startswith("things you have made:")]
    assert max(len(o) for o in obs) - max(map(len, made)) < 1650     # + weather, rain and respawn lines
    assert max(map(len, made)) < 600


def test_same_seed_gives_the_same_terrain_in_both_name_modes():
    for seed in (1, 2, 3):
        a, b = make_world(seed), make_world(seed, names="alien", shuffle_recipes=True)
        assert (a.blocks == b.blocks).all() and a.spawn == b.spawn and a.creatures == b.creatures
        sa, sb = a.snapshot(), b.snapshot()
        assert sa["blocks_b64"] == sb["blocks_b64"] and sa["palette"] == sb["palette"] == defs.BLOCKS
        assert sa["display_names"] == {n: n for n in defs.ALL_NAMES}
        assert set(sb["display_names"]) == set(defs.ALL_NAMES)


def test_alien_names_are_made_up_and_seeded():
    a, b, c = (make_world(s, names="alien").display for s in (1, 1, 2))
    assert a == b and a != c
    words = {w for n in defs.ALL_NAMES for w in n.split()} | {"air"}
    assert len(set(a.values())) == len(a)
    for shown in a.values():
        assert shown.isalpha() and not any(w in shown for w in words)


def test_no_familiar_name_in_alien_observations(alien_run):
    w, obs, results = alien_run
    assert len(w.firsts["craft"]) == 19                        # the run saw every item
    # "air" stays: it is the name of a vital, and air is never listed as a block.
    words = sorted({x for n in defs.ALL_NAMES for x in n.split()})
    pat = re.compile(r"\b(" + "|".join(words) + r")\b", re.I)
    for text in obs + results:
        assert not pat.search(text), pat.search(text).group(0) + " in: " + text
    shown = set(w.display.values())
    assert sum(any(s in o for s in shown) for o in obs) == len(obs)


def test_alien_events_and_deltas_use_familiar_names():
    w = flat_world(names="alien")
    w._add("planks", 2)
    r = w.step({"name": "place", "item": w.dn("planks"), "x": 33, "y": 10, "z": 32})
    assert r.valid and w.dn("planks") in r.text and "planks" not in r.text
    assert r.deltas[0]["blocks"] == [[33, 10, 32, "planks"]] and r.deltas[0]["agent"]["inventory"] == {"planks": 1}
    assert r.events[0] == {"t": 0, "type": "first_place", "detail": {"block": "planks"}}


def test_alien_mode_does_not_accept_familiar_names():
    w = flat_world(names="alien")
    w._add("berries", 1)
    w.food = 5
    r = w.step({"name": "eat", "item": "berries"})
    assert r.text == T.NO_ITEM and not r.valid and w.food == 5
    assert w.step({"name": "eat", "item": w.dn("berries")}).valid


def test_observation_lists_what_was_made_and_keeps_it_through_death():
    from conftest import flat_world
    w = flat_world()
    w._add("log", 2)
    assert "things you have made" not in w.observe()
    w.step({"name": "craft", "items": {"log": 1}})
    w.step({"name": "craft", "items": {"planks": 2}})
    w.step({"name": "craft", "items": {"log": 1}})                     # made again: listed once
    line = next(l for l in w.observe().splitlines() if l.startswith("things you have made"))
    assert line == "things you have made: log -> 4 planks; 2 planks -> 4 sticks"
    w.food, w.health = 0, 1
    assert w.step({"name": "wait", "steps": 8}).died == "hunger"
    assert w.inv == {} and line in w.observe()


def test_made_list_is_wiped_with_the_memory():
    from conftest import flat_world
    w = flat_world(on_death="respawn_wipe_memory")
    w._add("log", 1)
    w.step({"name": "craft", "items": {"log": 1}})
    w.food, w.health = 0, 1
    w.step({"name": "wait", "steps": 8})
    assert "things you have made" not in w.observe()


def test_observation_says_health_does_not_rise_on_low_food():
    from conftest import flat_world
    w = flat_world()
    w.health, w.food = 10, 14
    assert "health does not rise while food is under 15" in w.observe()
    w.food = 15
    assert "does not rise" not in w.observe()
    w.health, w.food = 20, 5                                             # full health: nothing to say
    assert "does not rise" not in w.observe()
