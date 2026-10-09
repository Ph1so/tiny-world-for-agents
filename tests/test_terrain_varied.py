"""terrain.style varied: a bigger mixed map that still gives a new agent what it needs near the start."""
from collections import deque
from pathlib import Path

import numpy as np
import pytest
from test_terrain import reachable_cells, within

from tinyworld.sim import World, load_world_config
from tinyworld.sim.defs import ID

VARIED = Path(__file__).resolve().parents[1] / "configs" / "world_varied.yaml"


def varied_world(seed: int) -> World:
    return World(load_world_config(VARIED), seed=seed)


def water_bodies(b, sea) -> list[int]:
    """Sizes of the connected patches of surface water, largest (the sea) first."""
    surf = b[sea] == ID["water"]
    seen = np.zeros_like(surf)
    nz, nx = surf.shape
    sizes = []
    for z0, x0 in np.argwhere(surf):
        if seen[z0, x0]:
            continue
        seen[z0, x0], q, n = True, deque([(z0, x0)]), 0
        while q:
            z, x = q.popleft()
            n += 1
            for dz, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                zz, xx = z + dz, x + dx
                if 0 <= zz < nz and 0 <= xx < nx and surf[zz, xx] and not seen[zz, xx]:
                    seen[zz, xx] = True
                    q.append((zz, xx))
        sizes.append(n)
    return sorted(sizes, reverse=True)


@pytest.mark.parametrize("seed", range(1, 9))
def test_varied_map_shape(seed):
    w = varied_world(seed)
    b, sea = w.blocks, w.cfg.sea_level
    assert b.shape == (48, 128, 128)
    assert set(np.unique(b)) <= {ID[n] for n in ("air", "grass", "dirt", "sand", "stone", "water", "log",
                                                  "leaves", "berry bush", "coal ore", "iron ore", "wheat")}
    for edge in (b[:, 0, :], b[:, -1, :], b[:, :, 0], b[:, :, -1]):
        assert (edge[sea] == ID["water"]).all() and (edge[sea + 1:] == ID["air"]).all()
    assert len([n for n in water_bodies(b, sea)[1:] if n >= 8]) >= 2   # lakes apart from the sea (rivers join some to it)
    top = b.shape[0] - 1 - np.argmax((b != ID["air"])[::-1], axis=0)
    assert top.max() - sea >= 15                                            # real mountains
    assert (b == ID["sand"]).sum() > 500 and (b == ID["grass"]).sum() > 4000
    x, y, z = w.spawn
    assert w.block(x, y - 1, z) == "grass" and w.block(x, y, z) == "air" and w.block(x, y + 1, z) == "air"


@pytest.mark.parametrize("seed", range(1, 6))
def test_varied_start_has_what_is_needed_nearby(seed):
    w = varied_world(seed)
    b, r = w.blocks, w.cfg.terrain.varied.spawn_reach
    sx, _, sz = w.spawn
    box = np.zeros(b.shape, dtype=bool)
    box[:, max(0, sz - 2 * r):sz + 2 * r + 1, max(0, sx - 2 * r):sx + 2 * r + 1] = True
    near = within(reachable_cells(w), w.cfg.reach, b.shape) & w.exposed_mask() & box
    need = {"log": 12, "stone": 20, "coal ore": 2, "iron ore": 2, "berry bush": 6, "water": 4}
    for name, n in need.items():
        assert (near & (b == ID[name])).sum() >= n, name


def test_varied_is_seeded_and_classic_is_untouched():
    assert (varied_world(4).blocks == varied_world(4).blocks).all()
    assert not (varied_world(4).blocks.shape == varied_world(5).blocks.shape
                and (varied_world(4).blocks == varied_world(5).blocks).all())
    assert load_world_config().terrain.style == "classic"
