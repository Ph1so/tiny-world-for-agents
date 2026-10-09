"""Balance checks from milestone 2. Bots are run straight on the world, with no logging."""
import pytest
from conftest import make_world

from tinyworld.bots.random_bot import RandomBot
from tinyworld.bots.sensible_bot import SensibleBot
from tinyworld.sim.recipes import BASE


def play(bot, seed: int, steps: int, **overrides):
    w = make_world(seed, **overrides)
    deaths = []
    while w.t < steps and not w.done:
        r = w.step(bot.act("", w))
        assert r.steps >= 1
        deaths += [e["t"] for e in r.events if e["type"] == "death"]
    return w, deaths


@pytest.fixture(scope="module")
def sensible_runs():
    return {seed: play(SensibleBot(seed), seed, 2100) for seed in range(1, 21)}   # bread needs a crop to ripen


def test_random_bot_usually_dies_within_two_days():
    first = [play(RandomBot(seed), seed, 600)[1] for seed in range(1, 11)]
    died = sum(bool(d) for d in first)
    print("random bot first death at", [d[0] if d else None for d in first])
    assert died >= 8


def test_sensible_bot_usually_survives_five_days(sensible_runs):
    alive = [seed for seed in range(1, 11) if not sensible_runs[seed][1]]
    print("sensible bot alive after 1500 steps on seeds", alive)
    assert len(alive) >= 8


def test_sensible_bot_only_sends_valid_actions():
    w, bot = make_world(5), SensibleBot(5)
    bad = 0
    while w.t < 900:
        bad += not w.step(bot.act("", w)).valid
    assert bad == 0


@pytest.mark.parametrize("seed", range(1, 21))
def test_every_recipe_is_reachable_in_play(sensible_runs, seed):
    """The sensible bot starts with nothing and ends up having made all 19 things."""
    w, _ = sensible_runs[seed]
    assert sorted(w.firsts["craft"]) == sorted(r.output for r in BASE)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_alien_shuffled_world_is_playable(seed):
    w, deaths = play(SensibleBot(seed), seed, 2400, names="alien", shuffle_recipes=True)   # seed 3 needs past 2100 with farming (110)
    assert sorted(w.firsts["craft"]) == sorted(r.output for r in BASE)


def test_end_run_stops_the_world():
    w, deaths = play(RandomBot(3), 3, 3000, on_death="end_run")
    assert w.done and len(deaths) == 1 and w.t < 3000
