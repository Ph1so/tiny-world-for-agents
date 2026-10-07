"""Seeded terrain: plains, forest patches, a lake, sandy shores, a stone hill with ore, deep water at the edge."""
from __future__ import annotations

import numpy as np

from .config import WorldConfig
from .defs import ID


def _smooth(t: np.ndarray) -> np.ndarray:
    return t * t * (3 - 2 * t)


def _noise(rng: np.random.Generator, nx: int, nz: int, scale: int) -> np.ndarray:
    """Value noise in 0..1, shape (nz, nx)."""
    g = rng.random((nz // scale + 2, nx // scale + 2))
    xs, zs = np.arange(nx) / scale, np.arange(nz) / scale
    x0, z0 = xs.astype(int), zs.astype(int)
    fx, fz = _smooth(xs - x0)[None, :], _smooth(zs - z0)[:, None]
    a, b = g[z0][:, x0], g[z0][:, x0 + 1]
    c, d = g[z0 + 1][:, x0], g[z0 + 1][:, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fz) + (c * (1 - fx) + d * fx) * fz


def generate(cfg: WorldConfig, rng: np.random.Generator):
    """Return (blocks[y, z, x] uint8, spawn (x, y, z), list of (kind, (x, y, z)))."""
    nx, ny, nz = cfg.size
    tc, sea = cfg.terrain, cfg.sea_level
    xx, zz = np.meshgrid(np.arange(nx), np.arange(nz))

    h = np.full((nz, nx), tc.base_height)
    for scale, amp in zip(tc.noise_scales, tc.noise_amps):
        h = h + amp * (_noise(rng, nx, nz, scale) - 0.5)

    # One hill and one lake, kept apart and away from the edge.
    lo, hi = tc.edge_width + 6, min(nx, nz) - tc.edge_width - 6
    hill = rng.integers(lo, hi, size=2)
    lake = rng.integers(lo, hi, size=2)
    for _ in range(50):
        if np.abs(lake - hill).max() >= 16:
            break
        lake = rng.integers(lo, hi, size=2)
    d_hill = np.hypot(xx - hill[0], zz - hill[1])
    d_lake = np.hypot(xx - lake[0], zz - lake[1])
    h = h + tc.hill_height * np.exp(-((d_hill / tc.hill_radius) ** 2))
    w = np.exp(-((d_lake / tc.lake_radius) ** 2))
    h = h * (1 - w) + (sea - tc.lake_depth) * w

    edge = np.minimum(np.minimum(xx, zz), np.minimum(nx - 1 - xx, nz - 1 - zz))
    f = _smooth(np.clip(edge / tc.edge_width, 0, 1))
    h = (sea - tc.edge_depth) * (1 - f) + h * f
    top = np.clip(np.rint(h).astype(int), 2, ny - 6)      # y of the highest ground block

    ys = np.arange(ny)[:, None, None]
    t3 = top[None, :, :]
    blocks = np.zeros((ny, nz, nx), dtype=np.uint8)
    under = ys <= t3
    blocks[under] = ID["stone"]
    r = rng.random(blocks.shape)
    blocks[under & (r < tc.coal_rate)] = ID["coal ore"]
    blocks[under & (r >= tc.coal_rate) & (r < tc.coal_rate + tc.iron_rate)] = ID["iron ore"]
    sand_col = t3 <= sea + 1
    grass_col = (t3 > sea + 1) & (t3 < tc.stone_line)
    blocks[under & sand_col & (ys > t3 - 3)] = ID["sand"]
    blocks[under & grass_col & (ys > t3 - 4)] = ID["dirt"]
    blocks[grass_col & (ys == t3)] = ID["grass"]
    blocks[(ys > t3) & (ys <= sea)] = ID["water"]

    # Ore that can be seen on the bare stone surface.
    stone_cols = np.argwhere(top >= tc.stone_line)          # rows of (z, x)
    stone_cols = stone_cols[rng.permutation(len(stone_cols))]
    kinds = [k for i in range(max(tc.surface_coal, tc.surface_iron))
             for k, n in (("coal ore", tc.surface_coal), ("iron ore", tc.surface_iron)) if i < n]
    for (z, x), kind in zip(stone_cols, kinds):
        blocks[top[z, x], z, x] = ID[kind]

    # Trees and berry bushes on grass.
    is_grass = (top > sea + 1) & (top < tc.stone_line)
    inner = (xx >= 3) & (xx < nx - 3) & (zz >= 3) & (zz < nz - 3)
    forest = _noise(rng, nx, nz, 10) > 0.58
    r_tree, r_bush = rng.random((nz, nx)), rng.random((nz, nx))
    tall = rng.integers(3, 5, size=(nz, nx))
    trunk = np.zeros((nz, nx), dtype=bool)
    taken = np.zeros((nz, nx), dtype=bool)
    order = np.argwhere(is_grass & inner)
    extra = order[rng.permutation(len(order))]

    def tree(z: int, x: int) -> bool:
        if taken[z, x] or trunk[z - 1:z + 2, x - 1:x + 2].any():
            return False
        y0, hh = top[z, x], int(tall[z, x])
        blocks[y0 + 1:y0 + hh + 1, z, x] = ID["log"]
        ring = blocks[y0 + hh, z - 1:z + 2, x - 1:x + 2]
        ring[ring == ID["air"]] = ID["leaves"]
        for dz, dx in ((0, 0), (0, 1), (0, -1), (1, 0), (-1, 0)):
            if blocks[y0 + hh + 1, z + dz, x + dx] == ID["air"]:
                blocks[y0 + hh + 1, z + dz, x + dx] = ID["leaves"]
        trunk[z, x] = taken[z, x] = True
        return True

    def bush(z: int, x: int) -> bool:
        if taken[z, x] or blocks[top[z, x] + 1, z, x] != ID["air"]:
            return False
        blocks[top[z, x] + 1, z, x] = ID["berry bush"]
        taken[z, x] = True
        return True

    n_trees = n_bushes = 0
    for z, x in order:
        rate = tc.forest_tree_rate if forest[z, x] else tc.plain_tree_rate
        if r_tree[z, x] < rate:
            n_trees += tree(int(z), int(x))
        elif r_bush[z, x] < tc.bush_rate:
            n_bushes += bush(int(z), int(x))
    for z, x in extra:
        if n_trees < tc.min_trees:
            n_trees += tree(int(z), int(x))
        elif n_bushes < tc.min_bushes:
            n_bushes += bush(int(z), int(x))
        else:
            break

    # Spawn on the free grass column nearest the map centre.
    free = [(int(z), int(x)) for z, x in order
            if not taken[z, x] and (blocks[top[z, x] + 1:top[z, x] + 3, z, x] == ID["air"]).all()]
    if not free:
        raise ValueError("no free grass column to start on")
    sz, sx = min(free, key=lambda c: ((c[1] - nx // 2) ** 2 + (c[0] - nz // 2) ** 2, c))
    spawn = (sx, int(top[sz, sx]) + 1, sz)

    cc = cfg.creatures
    spots = [c for c in free if c != (sz, sx)]
    picks = rng.permutation(len(spots))[: cc.sheep_start + cc.chicken_start]
    kinds = ["sheep"] * cc.sheep_start + ["chicken"] * cc.chicken_start
    creatures = [(k, (spots[int(p)][1], int(top[spots[int(p)]]) + 1, spots[int(p)][0])) for k, p in zip(kinds, picks)]
    return blocks, spawn, creatures
