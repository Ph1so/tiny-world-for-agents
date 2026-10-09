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
    assert r.text == "Got 2 wheat. Got 2 seeds."
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
