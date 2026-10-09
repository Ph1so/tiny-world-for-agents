"""Farming (seeds, sprouts, wheat, bread), wool and the bed, sleep, and weather."""
from tinyworld.sim import text as T

from conftest import flat_world, make_world


def calm(**overrides):
    """A flat world with weather drawn by hand: w.weather is whatever the test sets."""
    w = flat_world(**overrides)
    w.cfg.weather.enabled = False
    return w


# ------------------------------------------------------------------ farming

def test_grass_can_give_seeds():
    w = calm()
    w.cfg.farming.seed_chance = 1.0
    r = w.step({"name": "mine", "x": 33, "y": 9, "z": 32})
    assert r.text == "Got 1 grass. Got 1 seeds."
    assert w.inv == {"grass": 1, "seeds": 1}
    w.cfg.farming.seed_chance = 0.0
    r = w.step({"name": "mine", "x": 31, "y": 9, "z": 32})
    assert r.text == "Got 1 grass."


def test_seeds_need_soil_and_water():
    w = calm()
    w._add("seeds", 3)
    r = w.step({"name": "place", "item": "seeds", "x": 33, "y": 10, "z": 32})
    assert r.text == T.NOT_PLANTED.format(item="seeds", soil="dirt or grass", water="water", r=4)
    assert w.block(33, 10, 32) == "air" and w.inv["seeds"] == 3
    w.set_block(36, 9, 32, "water")
    r = w.step({"name": "place", "item": "seeds", "x": 33, "y": 10, "z": 32})
    assert r.text == "Placed seeds at (33, 10, 32)."
    assert w.block(33, 10, 32) == "sprout" and w.crops == {(33, 10, 32): 1} and w.inv["seeds"] == 2
    w.set_block(32, 10, 34, "stone")                       # stone under the cell is not soil
    r = w.step({"name": "place", "item": "seeds", "x": 32, "y": 11, "z": 34})
    assert r.text.startswith("The seeds was not placed. It needs")


def test_seeds_aimed_at_the_soil_say_which_cell_is_empty():
    w = calm()
    w._add("seeds", 1)
    r = w.step({"name": "place", "item": "seeds", "x": 33, "y": 9, "z": 32})
    assert r.text == "The cell is not empty: (33, 9, 32) is grass. seeds go in the empty cell above the grass, (33, 10, 32)."
    assert not r.valid and w.inv["seeds"] == 1
    w.set_block(33, 10, 32, "stone")                       # not soil: the plain line
    assert w.step({"name": "place", "item": "seeds", "x": 33, "y": 10, "z": 32}).text == T.NOT_EMPTY
    w.cfg.rule_notes = False
    assert w.step({"name": "place", "item": "seeds", "x": 31, "y": 9, "z": 32}).text == T.NOT_EMPTY


def test_seeds_cannot_be_jumped_on():
    w = calm()
    w._add("seeds", 1)
    r = w.step({"name": "jump", "item": "seeds"})
    assert r.text == "The seeds was not placed." and w.pos == [32, 10, 32]


def test_sprout_grows_into_wheat_and_rain_counts_double():
    w = calm()
    w.cfg.farming.grow_steps = 20
    w.set_block(32, 9, 35, "water")
    w._add("seeds", 2)
    w.step({"name": "place", "item": "seeds", "x": 33, "y": 10, "z": 32})
    w.step({"name": "place", "item": "seeds", "x": 31, "y": 10, "z": 32})
    w.set_block(31, 14, 32, "stone")                       # a roof over the second sprout
    w.weather = "rain"
    for _ in range(9):
        w.step({"name": "wait", "steps": 1})
    assert w.block(33, 10, 32) == "wheat"                  # 2 clear steps + 2 * 9 in rain >= 20
    assert w.block(31, 10, 32) == "sprout" and w.crops[(31, 10, 32)] == 10
    w.cfg.farming.seed_bonus_chance = 1.0
    r = w.step({"name": "mine", "x": 33, "y": 10, "z": 32})
    assert r.text == "Got 3 wheat. Got 2 seeds."
    r = w.step({"name": "mine", "x": 31, "y": 10, "z": 32})  # an unripe sprout gives its seeds back
    assert r.text == "Got 1 seeds." and w.crops == {}


def test_bread_from_wheat_feeds():
    w = calm()
    w._add("wheat", 3)
    w.food = 10
    assert w.step({"name": "craft", "items": {"wheat": 3}}).text == "Made 1 bread."
    w.step({"name": "eat", "item": "bread"})
    assert w.food == 16


def test_sheep_gives_wool():
    w = calm()
    w._add("iron sword", 1)
    w._spawn("sheep", (33, 10, 32))
    w.cfg.creatures.passive_move_prob = 0.0
    r = w.step({"name": "attack", "id": 1})
    assert r.text == "Hit sheep #1. It is gone. Got 2 raw meat. Got 1 wool."


# ---------------------------------------------------------------- bed, sleep

def bed_world():
    w = calm()
    w._add("wool", 3)
    w._add("planks", 3)
    w.set_block(30, 10, 32, "workbench")
    assert w.step({"name": "craft", "items": {"wool": 3, "planks": 3}}).text == "Made 1 bed."
    assert w.step({"name": "place", "item": "bed", "x": 33, "y": 10, "z": 32}).text == "Placed bed at (33, 10, 32)."
    return w


def test_sleep_needs_a_bed_and_night():
    w = calm()
    assert w.step({"name": "sleep"}).text == "No bed within 3 cells."
    w = bed_world()
    t0 = w.t
    assert w.step({"name": "sleep"}).text == T.NOT_SLEPT_SKY and w.t == t0 + 1 and w.bed is None


def test_sleep_runs_to_dawn_heals_and_sets_respawn():
    w = bed_world()
    w.t = 250
    w.health, w.food = 10, 20
    r = w.step({"name": "sleep"})
    assert r.text == "Slept 50 steps. Your respawn point is the bed at (33, 10, 32)."
    assert w.t == 300 and w.bed == (33, 10, 32)
    assert w.health == 20                                  # 1 every 5 steps asleep
    assert "respawn point: bed at (33,10,32)" in w.observe()


def test_sleep_refused_with_a_zombie_near():
    w = bed_world()
    w.t = 250
    w._spawn("zombie", (38, 10, 32))
    r = w.step({"name": "sleep"})
    assert r.text == "You did not sleep. Zombie #1 is at (38, 10, 32)." and w.bed is None


def test_death_respawns_beside_the_bed_until_it_is_broken():
    w = bed_world()
    w.t = 250
    w.step({"name": "sleep"})
    w.pos = [10, 10, 10]
    w.health = 1
    w._damage(1, "hunger")
    w._tick()
    assert w.deaths == 1 and max(abs(w.pos[0] - 33), abs(w.pos[2] - 32)) == 1
    assert "You are back beside your bed at (33, 10, 32)." in w._death_notice
    w.step({"name": "mine", "x": 33, "y": 10, "z": 32})
    assert w.bed is None and "respawn point" not in w.observe()


# ------------------------------------------------------------------- weather

def test_rain_without_a_roof_drains_food_twice_as_fast_and_stops_healing():
    w = calm()
    w.weather = "rain"
    w.health = 15
    w.step({"name": "wait", "steps": 8})
    w.step({"name": "wait", "steps": 8})                   # 2 food ticks a step, 1 food per 15: 2 food in 16 steps
    assert w.food == 18 and w.health == 15
    obs = w.observe()
    assert "weather" not in obs.split("\n")[0]             # weather is off in calm()
    assert "rain is falling on you" in obs
    assert "while rain falls on you, food drops 2 times as fast and health does not rise" in obs
    w.set_block(32, 13, 32, "stone")                       # under a roof: dry
    assert not w.wet() and "falling on you" not in w.observe()


def test_storm_hail_is_dark_and_keeps_zombies_out():
    w = calm()
    w.weather = "storm"
    w._spawn("zombie", (50, 10, 50))
    r = w.step({"name": "wait", "steps": 8})
    assert r.text == "Waited 6 steps. Hail hit you." and w.health == 19
    assert w.sky() == "dark" and w.light() == "dark"
    assert any(c["kind"] == "zombie" for c in w.creatures)  # daylight does not clear them in a storm
    assert "rain and hail is falling on you" in w.observe()
    w.set_block(32, 14, 32, "stone")
    w.step({"name": "wait", "steps": 8})
    assert w.health == 19


def test_weather_is_drawn_per_spell_from_its_own_stream():
    a, b = make_world(3), make_world(3)
    off = make_world(3)
    off.cfg.weather.enabled = False
    seen = []
    for _ in range(300):
        a.step({"name": "wait", "steps": 8})
        b.step({"name": "wait", "steps": 8})
        off.step({"name": "wait", "steps": 8})
        if a.t <= 100:
            assert a.weather == "clear"
        seen.append(a.weather)
        assert a.weather == b.weather
    assert {"rain", "storm"} <= set(seen)
    assert off.weather == "clear"
    assert a.observe().split("\n")[0].endswith(f"| weather {a.weather}")


def test_new_names_are_alien_in_alien_mode():
    w = make_world(1, names="alien")
    for name in ("seeds", "wheat", "bread", "wool", "bed", "sprout"):
        assert w.dn(name) != name


def test_new_maps_have_wild_wheat_by_water_and_nothing_else_changes():
    import numpy as np
    from tinyworld.sim import defs
    w, bare = make_world(2), make_world(2)
    bare.cfg.farming.wild_patches = 0
    bare2 = __import__("tinyworld.sim", fromlist=["World"]).World(bare.cfg, seed=2)
    wheat = w.find("wheat")
    assert 4 <= len(wheat) <= 12 and bare2.find("wheat") == []
    for p in wheat:
        assert w.block(p[0], p[1] - 1, p[2]) in defs.SOIL and w._water_near(p)
    diff = np.argwhere(w.blocks != bare2.blocks)
    assert len(diff) == len(wheat)                       # the only change is the wheat itself
    assert w.creatures == bare2.creatures and w.spawn == bare2.spawn
    w.pos = list(wheat[0]); w.pos[0] += 1                # stand beside it (cell may be odd; mine checks reach only)
    w.cfg.farming.seed_bonus_chance = 0.0
    r = w.step({"name": "mine", "x": wheat[0][0], "y": wheat[0][1], "z": wheat[0][2]})
    assert r.text.startswith("Got 3 wheat. Got 1 seeds.")


def test_corner_hill_keeps_all_ore_near_it():
    import numpy as np
    from tinyworld.sim import World, load_world_config
    from tinyworld.sim.defs import ID
    base = load_world_config()
    cfg = load_world_config(terrain={**base.terrain.model_dump(), "hill_place": "corner", "ore_radius": 14})
    w = World(cfg, seed=153)
    ore = np.argwhere((w.blocks == ID["iron ore"]) | (w.blocks == ID["coal ore"]))
    centre = np.array([ore[:, 2].mean(), ore[:, 1].mean()])
    assert len(ore) > 500
    assert np.hypot(*(ore[:, [2, 1]] - centre).T).max() <= 14 * 2 + 1   # one clump
    assert max(abs(centre[0] - w.spawn[0]), abs(centre[1] - w.spawn[2])) > 12   # out of sight from the start


def test_start_items_go_to_every_new_agent_but_not_on_respawn():
    from tinyworld.sim.engine import Engine
    w = make_world(1, start_items={"seeds": 4, "bread": 2})
    assert w.inv == {"seeds": 4, "bread": 2}
    eng = Engine(w)
    a, b = eng.add_agent("A"), eng.add_agent("B")
    assert w.body(a).inv == {"seeds": 4, "bread": 2} and w.body(b).inv == {"seeds": 4, "bread": 2}
    w.me = w.body(b)
    w.health = 1
    w._damage(1, "hunger")
    eng.tick()
    assert w.body(b).deaths == 1 and w.body(b).inv == {}


def test_placed_line_lists_what_still_stands_and_chest_contents():
    w = calm()
    w.set_block(32, 9, 35, "water")
    w._add("chest", 1); w._add("seeds", 2); w._add("torch", 1); w._add("wheat", 5)
    w.step({"name": "place", "item": "chest", "x": 33, "y": 10, "z": 32})
    w.step({"name": "store", "x": 33, "y": 10, "z": 32, "items": {"wheat": 5}})
    w.step({"name": "place", "item": "seeds", "x": 31, "y": 10, "z": 32})
    w.step({"name": "place", "item": "torch", "x": 32, "y": 10, "z": 33})
    w.step({"name": "place", "item": "seeds", "x": 31, "y": 10, "z": 33})
    line = next(l for l in w.observe().split("\n") if l.startswith("things you have placed:"))
    assert line == ("things you have placed: chest at (33,10,32) holds wheat x5; "
                    "sprout at (31,10,32) (31,10,33); torch at (32,10,33)")
    w.cfg.farming.grow_steps = 1
    w.step({"name": "wait", "steps": 1})
    assert "wheat at (31,10,32) (31,10,33)" in w.observe()          # ripe crops show as wheat
    w.step({"name": "mine", "x": 32, "y": 10, "z": 33})
    assert "torch at" not in w.observe()                              # gone from the list once broken


def test_zombies_can_trample_crops_and_animals_can_eat_them():
    w = calm()
    w.t = 210
    w.cfg.creatures.zombie_step_every = 1
    w.cfg.farming.zombies_trample = True
    w.set_block(36, 10, 32, "sprout")                     # between the zombie and the agent
    w._spawn("zombie", (37, 10, 32))
    for _ in range(6):
        w.step({"name": "wait", "steps": 1})
    assert w.block(36, 10, 32) == "air"
    w2 = calm()
    w2.cfg.farming.animal_eat_prob = 1.0
    w2.cfg.creatures.passive_move_prob = 0.0
    w2.set_block(36, 10, 32, "wheat")
    w2._spawn("sheep", (37, 10, 32))
    r = w2.step({"name": "wait", "steps": 1})
    assert w2.block(36, 10, 32) == "air" and any(e["type"] == "crop_eaten" for e in r.events)


def test_death_notice_says_chests_keep_their_items():
    w = calm()
    w.health = 1
    w._damage(1, "hunger")
    w._tick()
    assert w._death_notice.endswith("Your items are gone. Sleeping at a bed makes you come back beside it. "
                                    "What is in a chest is not lost.")
    w2 = calm(rule_notes=False)
    w2.health = 1
    w2._damage(1, "hunger")
    w2._tick()
    assert w2._death_notice.endswith("Your items are gone.")


def test_straw_bed_from_wheat():
    w = calm()
    w._add("wheat", 3); w._add("planks", 3)
    w.set_block(30, 10, 32, "workbench")
    assert w.step({"name": "craft", "items": {"wheat": 3, "planks": 3}}).text == "Made 1 bed."


def test_closed_space_is_reported_with_its_floor():
    w = calm()
    assert w.enclosure() is None and "closed space" not in w.observe()
    # a 3 x 3 room around the agent at (32, 10, 32): walls two high at x/z 30 and 34, roof at y 12
    for x in range(30, 35):
        for z in range(30, 35):
            for y in (10, 11):
                if x in (30, 34) or z in (30, 34):
                    w.set_block(x, y, z, "planks")
            w.set_block(x, 12, z, "dirt")
    assert w.enclosure() == 9
    assert "you are in a closed space of 9 floor cells: no open path for creatures leads outside" in w.observe()
    w.set_block(34, 10, 32, "door")                      # a door keeps it closed
    assert w.enclosure() == 9
    w.set_block(34, 11, 32, "air")                       # a hole above the door opens it
    assert w.enclosure() is None


def test_fractional_animal_respawn_is_a_chance_per_morning():
    w = make_world(1)
    w.cfg.creatures.passive_respawn = 0.5
    w.creatures = [c for c in w.creatures if c["kind"] not in ("sheep", "chicken")]
    born = []
    for _ in range(10):
        before = len(w.creatures)
        w._respawn_passives()
        born.append(len(w.creatures) - before)
    assert set(born) <= {0, 1, 2} and 4 <= sum(born) <= 16    # about one per kind every other morning
