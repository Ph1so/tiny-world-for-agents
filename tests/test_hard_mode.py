"""Hard mode: fog, lethal nights (zombies break soft blocks), scarcity.

All three pressures are config knobs that are OFF by default, so these tests drive them
explicitly or load configs/world_hard.yaml. The default world, its tests, and the samples
are untouched by anything here.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import flat_world, make_world

from tinyworld.bots.random_bot import RandomBot
from tinyworld.bots.sensible_bot import SensibleBot
from tinyworld.sim import World, defs, load_world_config, text as T

ROOT = Path(__file__).resolve().parents[1]
HARD = ROOT / "configs" / "world_hard.yaml"
BANNED = ["goal", "should", "try to", "survive", "danger", "tip", "hint", "recipe"]


def banned_in(s: str) -> list[str]:
    return [w for w in BANNED if re.search(rf"\b{re.escape(w)}", s, re.I)]


# ----------------------------------------------------------------- config

def test_hard_config_loads_with_all_three_pressures():
    cfg = load_world_config(HARD)
    assert cfg.view_radius == 4                                 # fog
    assert cfg.creatures.zombie_max == 10
    assert cfg.creatures.zombie_step_every == 1
    assert cfg.creatures.zombie_damage == 4
    assert cfg.creatures.zombie_breaks == ["dirt", "sand", "grass", "leaves", "planks"]
    assert cfg.creatures.zombie_break_steps == 4
    assert cfg.creatures.torch_radius == 3
    assert cfg.vitals.food_drain_every == 6
    assert cfg.terrain.berry_density_mult == 0.5
    assert cfg.creatures.animal_count_mult == 0.5


def test_defaults_keep_the_old_behaviour():
    """Every new/renamed knob reproduces the previous default when left alone."""
    cfg = load_world_config()
    assert cfg.view_radius == 12
    assert cfg.vitals.food_drain_every == 15
    assert cfg.creatures.zombie_step_every == 1.5
    assert cfg.creatures.zombie_damage == 3
    assert cfg.creatures.torch_radius == 6
    assert cfg.creatures.zombie_breaks == []                    # off: zombies cannot break blocks
    assert cfg.terrain.berry_density_mult == 1.0
    assert cfg.creatures.animal_count_mult == 1.0


# ----------------------------------------------------------------- fog

def test_fog_shrinks_the_in_view_radius():
    """view_radius caps the "in view" block. The close list and line of sight are untouched."""
    wide = flat_world()                                         # default view_radius 12
    wide.set_block(38, 10, 32, "stone")                        # 6 cells east
    assert "in view (within 12 cells):" in wide.observe()
    assert "(38,10,32)" in wide.observe()

    fog = flat_world()
    fog.cfg.view_radius = 4
    fog.set_block(38, 10, 32, "stone")                         # now out of view
    fog.set_block(36, 10, 32, "stone")                         # 4 cells east, still in view
    obs = fog.observe()
    assert "in view (within 4 cells):" in obs
    assert "(38,10,32)" not in obs
    assert "(36,10,32)" in obs
    assert "close (within 3 cells):" in obs                     # close block unchanged


def test_fog_keeps_line_of_sight_no_xray():
    """A block the agent could not see is still hidden, fog or not."""
    fog = flat_world()
    fog.cfg.view_radius = 4
    for y in (10, 11):
        fog.set_block(34, y, 32, "stone")                       # a 2-high wall 2 cells east
    fog.set_block(35, 10, 32, "iron ore")                       # right behind it, within 4 cells
    assert "iron ore" not in fog.observe()


# ----------------------------------------------------- lethal nights: breaking

def _break_world(wall: str) -> World:
    cfg = load_world_config(HARD)
    w = World(cfg, seed=1)
    w.blocks[:] = defs.ID["air"]
    w.blocks[:10] = defs.ID["grass"]
    w.pos = [32, 10, 32]
    w.t = 210                                                   # night: a zombie in the open stays
    w.creatures = []
    w._next_id = 1
    w.set_block(33, 10, 32, wall)                               # a 2-high wall just east of the agent
    w.set_block(33, 11, 32, wall)
    w._spawn("zombie", (34, 10, 32))
    return w


def test_zombie_breaks_a_dirt_block():
    w = _break_world("dirt")
    for _ in range(w.cfg.creatures.zombie_break_steps):
        w.step({"name": "wait", "steps": 1})
    assert w.block(33, 10, 32) == "air"                         # ground out after break_steps


def test_zombie_cannot_break_a_stone_block():
    w = _break_world("stone")
    for _ in range(20):
        w.step({"name": "wait", "steps": 1})
    assert w.block(33, 10, 32) == "stone"                       # stone never yields


@pytest.mark.parametrize("block", ["stone", "workbench", "furnace", "door"])
def test_zombie_cannot_break_hard_blocks(block):
    w = _break_world(block)
    for _ in range(20):
        w.step({"name": "wait", "steps": 1})
    assert w.block(33, 10, 32) == block


def test_zombies_do_not_break_blocks_by_default():
    """With zombie_breaks empty (the default), a dirt wall holds."""
    w = make_world(1)
    w.blocks[:] = defs.ID["air"]
    w.blocks[:10] = defs.ID["grass"]
    w.pos = [32, 10, 32]
    w.creatures = []
    w._next_id = 1
    assert w.cfg.creatures.zombie_breaks == []
    w.set_block(33, 10, 32, "dirt")
    w.set_block(33, 11, 32, "dirt")
    w._spawn("zombie", (34, 10, 32))
    for _ in range(20):
        w.step({"name": "wait", "steps": 1})
    assert w.block(33, 10, 32) == "dirt"


# --------------------------------------------------------- scarcity: food

def test_food_drains_at_the_configured_interval():
    w = flat_world()
    w.cfg.vitals.food_drain_every = 9
    w.food = 20
    for _ in range(8):
        w.step({"name": "wait", "steps": 1})
    assert w.food == 20                                         # not yet
    w.step({"name": "wait", "steps": 1})
    assert w.food == 19                                         # exactly on the 9th step


# ----------------------------------------------------------- determinism

_SCRIPT = """
import json, sys
from tinyworld.sim import World, load_world_config
w = World(load_world_config("configs/world_hard.yaml"), seed=5)
hashes = [w.state_hash()]
for a in json.loads(sys.stdin.read()):
    w.step(a)
hashes.append(w.state_hash())
hashes.append(w.observe())
print(json.dumps(hashes))
"""


def test_hard_mode_determinism_across_two_processes():
    w, bot, acts = World(load_world_config(HARD), seed=5), RandomBot(5), []
    for _ in range(300):
        a = bot.act("", w)
        acts.append(a)
        w.step(a)
    payload = json.dumps(acts)
    outs = [subprocess.run([sys.executable, "-c", _SCRIPT], input=payload, cwd=str(ROOT),
                           capture_output=True, text=True, check=True).stdout for _ in range(2)]
    assert outs[0] == outs[1]
    first = json.loads(outs[0])[0]
    assert first == World(load_world_config(HARD), seed=5).state_hash()


# ----------------------------------------------------------- alien + banned

def _bot_obs(seed: int, steps: int, **overrides):
    cfg = load_world_config(HARD, **overrides)
    w, bot, obs = World(cfg, seed=seed), SensibleBot(seed), []
    while w.t < steps:
        o = w.observe()
        obs.append(o)
        w.step(bot.act(o, w))
    return w, obs


def test_alien_mode_works_in_hard_mode():
    w, obs = _bot_obs(3, 300, names="alien", shuffle_recipes=True)
    assert w.cfg.view_radius == 4
    words = sorted({x for n in defs.ALL_NAMES for x in n.split()})
    pat = re.compile(r"\b(" + "|".join(words) + r")\b", re.I)    # "air" excluded, as elsewhere
    for o in obs:
        hit = pat.search(o)
        assert hit is None, hit.group(0) + " in alien hard observation"


def test_banned_words_absent_in_hard_observations():
    for tpl in T.TEMPLATES:                                      # templates were not reworded
        assert banned_in(tpl) == [], tpl
    _, obs = _bot_obs(1, 300)
    for o in obs:
        assert banned_in(o) == [], o
