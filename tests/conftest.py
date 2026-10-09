import pytest

from tinyworld.sim import World, load_world_config
from tinyworld.sim.defs import ID


def make_world(seed: int = 1, **overrides) -> World:
    return World(load_world_config(**overrides), seed=seed)


def flat_world(seed: int = 1, **overrides) -> World:
    """A bare arena: grass up to y = 9, the agent at (32, 10, 32), no creatures, no plants."""
    w = make_world(seed, **overrides)
    w.blocks[:] = ID["air"]
    w.blocks[:10] = ID["grass"]
    w.pos = [32, 10, 32]
    w.spawn = (32, 10, 32)
    w.creatures = []
    w._next_id = 1
    w.cfg.farming.seed_chance = 0.0                     # no plants: grass gives only grass
    return w


@pytest.fixture
def flat() -> World:
    return flat_world()
