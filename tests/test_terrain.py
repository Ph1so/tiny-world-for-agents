"""Terrain has what the plan asks for, and everything needed can be reached from the start."""
from collections import deque

import numpy as np
import pytest
from conftest import make_world

from tinyworld.sim.defs import HORIZONTAL, ID


def reachable_cells(w) -> set:
    """Every cell the agent can stand in, walking and swimming from the start, without a hurting fall."""
    start = tuple(w.pos)
    seen, q = {start}, deque([start])
    while q:
        p = q.popleft()
        for d in HORIZONTAL:
            r = w.walk_step(p, d)
            if r and r[0] not in seen and (r[1] <= w.cfg.vitals.fall_safe or w.block(*r[0]) == "water"):
                seen.add(r[0])
                q.append(r[0])
    return seen


def within(cells: set, radius: int, shape) -> np.ndarray:
    m = np.zeros(shape, dtype=bool)
    for x, y, z in cells:
        m[max(0, y - radius):y + radius + 1, max(0, z - radius):z + radius + 1, max(0, x - radius):x + radius + 1] = True
    return m


@pytest.mark.parametrize("seed", range(1, 21))
def test_map_features_and_reachable_resources(seed):
    w = make_world(seed)
    b, sea = w.blocks, w.cfg.sea_level
    assert b.shape == (32, 64, 64)
    # Deep water all around the edge.
    for edge in (b[:, 0, :], b[:, -1, :], b[:, :, 0], b[:, :, -1]):
        assert (edge[sea - 4:sea + 1] == ID["water"]).all() and (edge[sea + 1:] == ID["air"]).all()
    # A lake: water that does not connect to the edge.
    surf = b[sea] == ID["water"]
    sea_water = np.zeros_like(surf)
    q = deque([(0, 0)])
    sea_water[0, 0] = True
    while q:
        z, x = q.popleft()
        for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            zz, xx = z + dz, x + dx
            if 0 <= zz < 64 and 0 <= xx < 64 and surf[zz, xx] and not sea_water[zz, xx]:
                sea_water[zz, xx] = True
                q.append((zz, xx))
    assert (surf & ~sea_water).sum() >= 8
    # Sand at the shore, plains, forest.
    assert (b[sea + 1] == ID["sand"]).sum() > 20
    assert (b == ID["grass"]).sum() > 800
    assert (b == ID["log"]).sum() >= 30

    # What can be reached from the start.
    cells = reachable_cells(w)
    near = within(cells, w.cfg.reach, b.shape) & w.exposed_mask()
    need = {"log": 12, "stone": 30, "coal ore": 3, "iron ore": 6, "berry bush": 6, "grass": 100, "sand": 10}
    for name, n in need.items():
        assert (near & (b == ID[name])).sum() >= n, name
    hit = within(cells, w.cfg.attack_reach, b.shape)
    animals = [c for c in w.creatures if hit[c["pos"][1], c["pos"][2], c["pos"][0]]]
    assert {c["kind"] for c in animals} == {"sheep", "chicken"} and len(animals) >= 8
    # Bare stone and ore sit in the hills, above the sea.
    ys = np.argwhere(near & (b == ID["stone"]))[:, 0]
    assert ys.max() >= w.cfg.terrain.stone_line


def test_spawn_is_on_open_grass():
    for seed in range(1, 21):
        w = make_world(seed)
        x, y, z = w.spawn
        assert w.block(x, y - 1, z) == "grass" and w.block(x, y, z) == "air" and w.block(x, y + 1, z) == "air"
