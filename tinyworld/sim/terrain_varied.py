"""Varied terrain (terrain.style: varied): a ragged coast with bays and islands, several lakes,
rivers to the sea, mountains of different shapes (sharp peaks, long ridges, stepped mesas,
craters, clusters of hills), biomes (plains, forest, highland pines, dry sandy scrub) and
several tree shapes. Uses only the classic blocks, so the rules and the prompt do not change.

The middle of the map is kept as open plains, with a hill, a lake and woods nearby, so a new
agent can find wood, stone and water without walking far."""
from __future__ import annotations

import numpy as np

from .config import WorldConfig
from .defs import ID
from .terrain import _noise, _smooth

AIR, LOG, LEAVES = ID["air"], ID["log"], ID["leaves"]


def _seg_dist(xx, zz, a, b):
    """Distance from every cell to the segment a-b, and how far along it (0..1) the nearest point is."""
    ab = b - a
    t = np.clip(((xx - a[0]) * ab[0] + (zz - a[1]) * ab[1]) / max(1e-9, ab @ ab), 0, 1)
    return np.hypot(xx - (a[0] + t * ab[0]), zz - (a[1] + t * ab[1])), t


def generate_varied(cfg: WorldConfig, rng: np.random.Generator):
    """Return (blocks[y, z, x] uint8, spawn (x, y, z), list of (kind, (x, y, z)))."""
    nx, ny, nz = cfg.size
    tc, vc, sea = cfg.terrain, cfg.terrain.varied, cfg.sea_level
    xx, zz = np.meshgrid(np.arange(nx), np.arange(nz))
    area = nx * nz / 4096                                   # 1.0 for the classic 64 x 64 map
    cx, cz = nx / 2, nz / 2
    d_center = np.hypot(xx - cx, zz - cz)

    # Base relief, rougher where the "rugged" field is high, plus a broad swell.
    h = np.full((nz, nx), tc.base_height)
    for scale, amp in zip(tc.noise_scales, tc.noise_amps):
        h = h + amp * (_noise(rng, nx, nz, scale) - 0.5)
    rugged = _noise(rng, nx, nz, 28)
    h = tc.base_height + (h - tc.base_height) * (0.45 + 1.1 * rugged)
    h = h + 4.0 * (_noise(rng, nx, nz, 40) - 0.5)
    moisture = _noise(rng, nx, nz, 24)
    wobble = _noise(rng, nx, nz, 8)                         # bends the outlines of lakes and mountains
    calm = _smooth(np.clip((d_center - vc.center_clear) / 6, 0, 1))   # 0 in the open middle

    # Where features go: away from the coast, from the middle and from each other.
    margin = tc.edge_width + 8
    placed: list[tuple[np.ndarray, float]] = []

    def spot(radius: float, near: tuple[float, float] | None = None) -> np.ndarray:
        for _ in range(200):
            if near is not None:
                ang, dist = rng.uniform(0, 2 * np.pi), rng.uniform(*near)
                p = np.array([cx + np.cos(ang) * dist, cz + np.sin(ang) * dist])
            else:
                p = np.array([rng.uniform(margin, nx - margin), rng.uniform(margin, nz - margin)])
            if not (margin <= p[0] < nx - margin and margin <= p[1] < nz - margin):
                continue
            if near is None and np.hypot(p[0] - cx, p[1] - cz) < vc.center_clear + radius:
                continue
            if all(np.hypot(*(p - q)) >= r + radius + 4 for q, r in placed):
                placed.append((p, radius))
                return p
        placed.append((p, radius))
        return p

    # Mountains. The first is a small "home" hill a short walk from the middle.
    kinds = ["peak", "ridge", "mesa", "crater", "hills"]
    mountain_mask = np.zeros((nz, nx))
    mountains: list[tuple[str, np.ndarray, float]] = []
    for i in range(vc.mountains):
        kind = "hills" if i == 0 else kinds[int(rng.integers(len(kinds)))]
        R = rng.uniform(6, 8) if i == 0 else rng.uniform(7, 13)
        c = spot(R, near=(vc.center_clear + 6, vc.center_clear + 12) if i == 0 else None)
        H = vc.mountain_height * (0.55 if i == 0 else rng.uniform(0.75, 1.25))
        d = np.hypot(xx - c[0], zz - c[1]) * (0.85 + 0.3 * wobble)
        if kind == "peak":
            add = H * np.clip(1 - d / R, 0, 1) ** 1.6
        elif kind == "ridge":
            ang = rng.uniform(0, np.pi)
            half = np.array([np.cos(ang), np.sin(ang)]) * R * 1.4
            ds, t = _seg_dist(xx, zz, c - half, c + half)
            add = H * 0.9 * np.exp(-(ds / (R * 0.35)) ** 2) * (1 - 0.5 * np.abs(2 * t - 1) ** 2) * (0.75 + 0.5 * wobble)
        elif kind == "mesa":                                 # flat top, steep sides, two tiers
            add = 0.6 * H * _smooth(np.clip((R - d) / 2.0, 0, 1)) + 0.4 * H * _smooth(np.clip((0.55 * R - d) / 1.5, 0, 1))
        elif kind == "crater":
            add = H * np.clip(1 - d / R, 0, 1) ** 1.3 - 0.55 * H * np.exp(-(d / (0.32 * R)) ** 2)
        else:                                                # a cluster of round hills
            add = np.zeros((nz, nx))
            for _ in range(int(rng.integers(3, 6))):
                o = c + rng.uniform(-R * 0.6, R * 0.6, size=2)
                r = rng.uniform(3, 5.5)
                add = np.maximum(add, H * rng.uniform(0.6, 1.0) * np.exp(-(np.hypot(xx - o[0], zz - o[1]) / r) ** 2))
        if i > 0:
            add = add * calm
        h = h + add
        mountain_mask = np.maximum(mountain_mask, np.clip(add / max(H, 1e-9), 0, 1))
        mountains.append((kind, c, R))

    # Lakes with bumpy shores. The first is a short walk from the middle.
    lakes: list[tuple[np.ndarray, float]] = []
    for i in range(vc.lakes):
        R = rng.uniform(4, 6) if i == 0 else rng.uniform(4, 9)
        c = spot(R, near=(vc.center_clear + 3, vc.center_clear + 9) if i == 0 else None)
        dn = np.hypot(xx - c[0], zz - c[1]) / (R * (0.75 + 0.5 * wobble))
        w = _smooth(np.clip((1.3 - dn) / 0.6, 0, 1))
        bed = sea - 1 - tc.lake_depth * np.sqrt(np.clip(1 - dn, 0, 1))
        h = h * (1 - w) + bed * w
        lakes.append((c, R))

    # Ragged coast: the distance to the map edge is pushed in and out by noise, giving bays and capes.
    edge0 = np.minimum(np.minimum(xx, zz), np.minimum(nx - 1 - xx, nz - 1 - zz)).astype(float)
    edge = edge0 + vc.coast_noise * 2 * (_noise(rng, nx, nz, 14) - 0.5)
    f = _smooth(np.clip(edge / tc.edge_width, 0, 1)) * _smooth(np.clip((edge0 - 1) / 4, 0, 1))  # open sea at the rim
    h = (sea - tc.edge_depth) * (1 - f) + h * f

    # Rivers: from a lake or the foot of a mountain, winding out to the nearest coast.
    river = np.full((nz, nx), np.inf)
    sources = [c for c, _ in lakes[1:]] + [c + (R * 0.9) * np.array([1, 0]) for _, c, R in mountains[1:]]
    order = rng.permutation(len(sources))
    for k in order[:vc.rivers]:
        a = np.asarray(sources[int(k)], dtype=float)
        side = int(np.argmin([a[0], a[1], nx - 1 - a[0], nz - 1 - a[1]]))
        b = a.copy()
        b[side % 2] = -4 if side < 2 else (nx if side % 2 == 0 else nz) + 3
        b[1 - side % 2] += rng.uniform(-12, 12)
        L = np.hypot(*(b - a))
        perp = np.array([-(b - a)[1], (b - a)[0]]) / max(L, 1e-9)
        amp, freq, phase = rng.uniform(3, 6), rng.uniform(1.5, 3.0), rng.uniform(0, 2 * np.pi)
        for s in np.linspace(0, 1, int(L * 2) + 2):
            p = a + (b - a) * s + perp * amp * np.sin(2 * np.pi * freq * s + phase) * np.sin(np.pi * s) ** 0.5
            x0, z0 = int(p[0]), int(p[1])
            xs, zs = slice(max(0, x0 - 9), min(nx, x0 + 10)), slice(max(0, z0 - 9), min(nz, z0 + 10))
            river[zs, xs] = np.minimum(river[zs, xs], np.hypot(xx[zs, xs] - p[0], zz[zs, xs] - p[1]))
    width = vc.river_width
    h = np.where(river <= width, np.minimum(h, sea - 1), h)
    bank = (river > width) & (river < width + 8)
    h = np.where(bank, np.minimum(h, sea + 0.6 + (river - width) * 0.9), h)

    # A few islands off the coast.
    for _ in range(vc.islands):
        R = rng.uniform(2.5, 4.5)
        for _try in range(50):
            p = rng.uniform(3, [nx - 3, nz - 3])
            e = min(p[0], p[1], nx - 1 - p[0], nz - 1 - p[1])
            if R + 3 <= e <= tc.edge_width + 1:
                break
        d = np.hypot(xx - p[0], zz - p[1]) * (0.85 + 0.3 * wobble)
        h = np.maximum(h, sea + rng.uniform(2, 4) - 3 * (d / R) ** 2)

    top = np.clip(np.rint(h).astype(int), 2, ny - 10)      # y of the highest ground block

    # Surfaces: bare stone up high and on cliffs, sand on beaches and in dry low patches.
    pad = np.pad(top, 1, mode="edge")
    slope = np.max([np.abs(top - pad[1:-1, :-2]), np.abs(top - pad[1:-1, 2:]),
                    np.abs(top - pad[:-2, 1:-1]), np.abs(top - pad[2:, 1:-1])], axis=0)
    land = top > sea + 1
    stone_col = land & ((top >= tc.stone_line) | (slope >= 3))
    dry = land & ~stone_col & (moisture < vc.dry_below) & (mountain_mask < 0.2)
    sand_col = (top <= sea + 1) | dry
    grass_col = land & ~stone_col & ~dry

    ys = np.arange(ny)[:, None, None]
    t3 = top[None, :, :]
    blocks = np.zeros((ny, nz, nx), dtype=np.uint8)
    under = ys <= t3
    blocks[under] = ID["stone"]
    r = rng.random(blocks.shape)
    blocks[under & (r < tc.coal_rate)] = ID["coal ore"]
    blocks[under & (r >= tc.coal_rate) & (r < tc.coal_rate + tc.iron_rate)] = ID["iron ore"]
    blocks[under & sand_col[None] & (ys > t3 - 3)] = ID["sand"]
    blocks[under & grass_col[None] & (ys > t3 - 4)] = ID["dirt"]
    blocks[grass_col[None] & (ys == t3)] = ID["grass"]
    blocks[(ys > t3) & (ys <= sea)] = ID["water"]

    # Ore showing on bare stone.
    cols = np.argwhere(stone_col)
    cols = cols[rng.permutation(len(cols))]
    n_coal, n_iron = int(round(tc.surface_coal * area)), int(round(tc.surface_iron * area))
    kinds_ore = [k for i in range(max(n_coal, n_iron)) for k, n in (("coal ore", n_coal), ("iron ore", n_iron)) if i < n]
    for (z, x), kind in zip(cols, kinds_ore):
        blocks[top[z, x], z, x] = ID[kind]

    # Trees: the shape depends on the biome.
    def put(y: int, z: int, x: int, b: int) -> None:
        if 0 <= x < nx and 0 <= z < nz and 0 <= y < ny and blocks[y, z, x] == AIR:
            blocks[y, z, x] = b

    def oak(z, x, y0):
        hh = int(rng.integers(3, 5))
        blocks[y0 + 1:y0 + hh + 1, z, x] = LOG
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                put(y0 + hh, z + dz, x + dx, LEAVES)
        for dz, dx in ((0, 0), (0, 1), (0, -1), (1, 0), (-1, 0)):
            put(y0 + hh + 1, z + dz, x + dx, LEAVES)

    def big_oak(z, x, y0):
        hh = int(rng.integers(5, 7))
        blocks[y0 + 1:y0 + hh + 1, z, x] = LOG
        for dy in range(-1, 3):
            for dz in range(-2, 3):
                for dx in range(-2, 3):
                    if dx * dx + dz * dz + (dy - 0.5) ** 2 <= 6.2:
                        put(y0 + hh + dy, z + dz, x + dx, LEAVES)

    def pine(z, x, y0):
        hh = int(rng.integers(5, 8))
        blocks[y0 + 1:y0 + hh + 1, z, x] = LOG
        # Layers from the trunk top down: a cross, then wide and narrow tiers in turn, so the
        # outline steps in like a cone. Two leaves above the trunk make the spire.
        layers = ["cross", "square", "diamond", "square", "diamond"]
        for i, shape in enumerate(layers[:hh - 2]):
            for dz in range(-2, 3):
                for dx in range(-2, 3):
                    m = abs(dx) + abs(dz)
                    if (shape == "cross" and m <= 1) or (shape == "square" and max(abs(dx), abs(dz)) <= 1) \
                            or (shape == "diamond" and m <= 2):
                        put(y0 + hh - i, z + dz, x + dx, LEAVES)
        put(y0 + hh + 1, z, x, LEAVES)
        put(y0 + hh + 2, z, x, LEAVES)

    def acacia(z, x, y0):
        blocks[y0 + 1:y0 + 4, z, x] = LOG
        dz, dx = (int(v) for v in rng.choice([-1, 1], size=2))
        put(y0 + 4, z + dz, x + dx, LOG)
        put(y0 + 5, z + dz, x + dx, LOG)
        for a in range(-2, 3):
            for b in range(-2, 3):
                if abs(a) + abs(b) <= 3:
                    put(y0 + 6, z + dz + a, x + dx + b, LEAVES)
                if abs(a) <= 1 and abs(b) <= 1:
                    put(y0 + 7, z + dz + a, x + dx + b, LEAVES)

    def shrub(z, x, y0):
        blocks[y0 + 1, z, x] = LOG
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                put(y0 + 1, z + dz, x + dx, LEAVES)
                if abs(dz) + abs(dx) <= 1:
                    put(y0 + 2, z + dz, x + dx, LEAVES)

    def dead(z, x, y0):
        hh = int(rng.integers(2, 5))
        blocks[y0 + 1:y0 + hh + 1, z, x] = LOG
        dz, dx = [(0, 1), (1, 0), (0, -1), (-1, 0)][int(rng.integers(4))]
        put(y0 + hh, z + dz, x + dx, LOG)

    shapes = {"oak": (oak, 1, 7), "big oak": (big_oak, 2, 9), "pine": (pine, 1, 10), "acacia": (acacia, 2, 9),
              "shrub": (shrub, 1, 4), "dead": (dead, 1, 6)}
    is_soil = (grass_col | dry) & land
    inner = (xx >= 4) & (xx < nx - 4) & (zz >= 4) & (zz < nz - 4)
    trunk = np.zeros((nz, nx), dtype=bool)
    taken = np.zeros((nz, nx), dtype=bool)

    def biome(z: int, x: int) -> str:
        if dry[z, x]:
            return "dry"
        if mountain_mask[z, x] > 0.15 or top[z, x] >= tc.stone_line - 3:
            return "highland"
        if moisture[z, x] > 0.58:
            return "forest"
        return "plains"

    menu = {"forest": (tc.forest_tree_rate, ["oak", "oak", "big oak", "pine", "shrub"]),
            "highland": (tc.forest_tree_rate * 0.6, ["pine", "pine", "pine", "oak"]),
            "plains": (tc.plain_tree_rate * 2, ["oak", "shrub", "shrub", "big oak"]),
            "dry": (tc.plain_tree_rate * 2.5, ["acacia", "acacia", "dead", "shrub"])}

    def tree(z: int, x: int, kind: str) -> bool:
        fn, gap, tall = shapes[kind]
        y0 = int(top[z, x])
        if taken[z, x] or y0 + tall + 2 >= ny or trunk[max(0, z - gap):z + gap + 1, max(0, x - gap):x + gap + 1].any():
            return False
        if blocks[y0 + 1, z, x] != AIR:
            return False
        fn(z, x, y0)
        trunk[z, x] = taken[z, x] = True
        return True

    def bush(z: int, x: int) -> bool:
        if taken[z, x] or not grass_col[z, x] or blocks[top[z, x] + 1, z, x] != AIR:
            return False
        blocks[top[z, x] + 1, z, x] = ID["berry bush"]
        taken[z, x] = True
        return True

    cells = np.argwhere(is_soil & inner)
    cells = cells[rng.permutation(len(cells))]
    bush_rate = tc.bush_rate * tc.berry_density_mult
    for z, x in cells:
        z, x = int(z), int(x)
        b = biome(z, x)
        rate, kinds_t = menu[b]
        if d_center[z, x] < vc.center_clear * 0.5:            # keep the very middle open
            rate *= 0.2
        if rng.random() < rate:
            tree(z, x, kinds_t[int(rng.integers(len(kinds_t)))])
        elif b != "dry" and rng.random() < bush_rate:
            bush(z, x)

    # Spawn on the free grass column nearest the middle.
    def free_cols():
        return [(int(z), int(x)) for z, x in np.argwhere(grass_col & inner)
                if not taken[z, x] and (blocks[top[z, x] + 1:top[z, x] + 3, z, x] == AIR).all()]

    free = free_cols()
    if not free:
        raise ValueError("no free grass column to start on")
    sz, sx = min(free, key=lambda c: ((c[1] - nx // 2) ** 2 + (c[0] - nz // 2) ** 2, c))

    # Enough trees and bushes within reach of the start.
    reach = vc.spawn_reach
    near = [(z, x) for z, x in cells if max(abs(int(x) - sx), abs(int(z) - sz)) <= reach
            and max(abs(int(x) - sx), abs(int(z) - sz)) > 2]
    def count(mask):
        z0, z1, x0, x1 = max(0, sz - reach), sz + reach + 1, max(0, sx - reach), sx + reach + 1
        return int(mask[z0:z1, x0:x1].sum())
    for z, x in near:
        if count(trunk) >= tc.min_trees:
            break
        tree(int(z), int(x), "oak")
    n_bush = count(blocks[np.clip(top + 1, 0, ny - 1), zz, xx] == ID["berry bush"])
    for z, x in near:
        if n_bush >= tc.min_bushes:
            break
        n_bush += bush(int(z), int(x))
    spawn = (sx, int(top[sz, sx]) + 1, sz)

    cc = cfg.creatures
    n_sheep = max(0, int(round(cc.sheep_start * cc.animal_count_mult)))
    n_chicken = max(0, int(round(cc.chicken_start * cc.animal_count_mult)))
    spots = [c for c in free_cols() if c != (sz, sx)]
    picks = rng.permutation(len(spots))[: n_sheep + n_chicken]
    kinds_c = ["sheep"] * n_sheep + ["chicken"] * n_chicken
    creatures = [(k, (spots[int(p)][1], int(top[spots[int(p)]]) + 1, spots[int(p)][0])) for k, p in zip(kinds_c, picks)]
    return blocks, spawn, creatures
