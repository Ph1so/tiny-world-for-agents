"""Text observations. Only blocks and creatures in line of sight are listed."""
from __future__ import annotations

import numpy as np

from . import text as T
from .defs import AIR, BLOCKS, TOOLS, TRANSPARENT, WATER

_TRANSP = np.array(TRANSPARENT)
_SAMPLES = 72


def _near(mask: np.ndarray) -> np.ndarray:
    """True where any of the six neighbours is True in mask."""
    m = np.zeros_like(mask)
    m[1:] |= mask[:-1]; m[:-1] |= mask[1:]
    m[:, 1:] |= mask[:, :-1]; m[:, :-1] |= mask[:, 1:]
    m[:, :, 1:] |= mask[:, :, :-1]; m[:, :, :-1] |= mask[:, :, 1:]
    return m


def line_of_sight(world, cells: np.ndarray) -> np.ndarray:
    """For (N, 3) cells as x, y, z: can the agent's eye see each one."""
    if len(cells) == 0:
        return np.zeros(0, dtype=bool)
    x, y, z = world.pos
    eye = np.array([x + 0.5, y + 1.5, z + 0.5])
    tgt = np.clip(eye, cells + 0.05, cells + 0.95)            # nearest point of each cell
    s = (np.arange(1, _SAMPLES) / _SAMPLES)[:, None, None]
    ijk = np.floor(eye + (tgt - eye) * s).astype(int)         # (samples, N, 3)
    size = np.array([world.sx, world.sy, world.sz])
    inside = ((ijk >= 0) & (ijk < size)).all(-1)
    c = np.clip(ijk, 0, size - 1)
    opaque = ~_TRANSP[world.blocks[c[..., 1], c[..., 2], c[..., 0]]]
    own = (ijk == cells).all(-1) | (ijk == np.array([x, y + 1, z])).all(-1)
    return ~(opaque & inside & ~own).any(0)


def visible_blocks(world) -> tuple[np.ndarray, np.ndarray]:
    """Cells within view_radius that the agent can see: ((N, 3) x, y, z, (N,) block ids)."""
    b = world.blocks
    cand = (b != AIR) & np.where(b == WATER, _near(b == AIR), _near(_TRANSP[b]))
    r = world.cfg.view_radius
    x, y, z = world.pos
    y0, z0, x0 = max(0, y - r), max(0, z - r), max(0, x - r)
    box = cand[y0:y + r + 1, z0:z + r + 1, x0:x + r + 1]
    yzx = np.argwhere(box) + np.array([y0, z0, x0])
    cells = yzx[:, [2, 0, 1]]
    cells = cells[line_of_sight(world, cells)]
    return cells, b[cells[:, 1], cells[:, 2], cells[:, 0]]


def visible_creatures(world) -> list[dict]:
    """Creatures within view_radius and in line of sight, nearest first."""
    r = world.cfg.view_radius
    px, py, pz = world.pos
    near = [c for c in world.creatures
            if max(abs(c["pos"][0] - px), abs(c["pos"][1] - py), abs(c["pos"][2] - pz)) <= r]
    if not near:
        return []
    ok = line_of_sight(world, np.array([c["pos"] for c in near]))
    seen = [c for c, v in zip(near, ok) if v]
    return sorted(seen, key=lambda c: (sum((a - b) ** 2 for a, b in zip(c["pos"], world.pos)), c["id"]))


def _coords(cells: np.ndarray) -> str:
    return " ".join(f"({int(c[0])},{int(c[1])},{int(c[2])})" for c in cells)


def render(world) -> str:
    c, v = world.cfg, world.cfg.vitals
    x, y, z = world.pos
    out = [
        T.OBS_HEADER.format(t=world.t, day=world.day, light=world.light()),
        T.OBS_POSITION.format(x=x, y=y, z=z),
        T.OBS_VITALS.format(h=world.health, hm=v.max_health, f=world.food, fm=v.max_food,
                            a=world.air, am=v.max_air),
    ]
    inv = []
    for item in sorted(world.inv, key=lambda i: i not in TOOLS):   # tools first, then in the order got
        n, name = world.inv[item], world.dn(item)
        if item in TOOLS:
            fmt = T.OBS_USES if n == 1 else T.OBS_USES_MANY
            inv.append(fmt.format(name=name, c=n, n=world.tools[item]))
        else:
            inv.append(T.OBS_COUNT.format(name=name, c=n))
    out.append(T.OBS_INVENTORY.format(items=", ".join(inv) if inv else T.OBS_EMPTY))
    if world.last_action is not None:
        out.append(T.OBS_LAST.format(action=world.last_action, result=world.last_result))
    if world._death_notice:
        out.append(world._death_notice)
    if world._notice:
        out.append(world._notice)
    out.append("")

    cells, ids = visible_blocks(world)
    rel = cells - np.array([x, y, z])
    d2, ch = (rel ** 2).sum(1), np.abs(rel).max(1)
    order = np.lexsort((cells[:, 2], cells[:, 1], cells[:, 0], d2))
    cells, ids, ch = cells[order], ids[order], ch[order]
    close, far = ch <= c.close_radius, ch > c.close_radius

    out.append(T.OBS_CLOSE.format(r=c.close_radius))
    for b in range(1, len(BLOCKS)):
        sel = cells[close & (ids == b)]
        if len(sel) == 0:
            continue
        name = world.dn(BLOCKS[b])
        if len(sel) <= 4:
            out.append(T.OBS_FEW.format(name=name, coords=_coords(sel)))
        else:
            out.append(T.OBS_MANY.format(name=name, n=len(sel), coords=_coords(sel[:4])))
    above = next(((yy, int(bb)) for yy, bb in enumerate(world.blocks[y + 2:, z, x], start=y + 2) if bb != AIR), None)
    if above is None:
        out.append(T.OBS_OPEN_ABOVE)
    else:
        out.append(T.OBS_BLOCK_ABOVE.format(name=world.dn(BLOCKS[above[1]]), x=x, y=above[0], z=z))

    out.append(T.OBS_VIEW.format(r=c.view_radius))
    n_far = 0
    for b in range(1, len(BLOCKS)):
        sel = cells[far & (ids == b)]
        if len(sel) == 0:
            continue
        n_far += 1
        name = world.dn(BLOCKS[b])
        if len(sel) == 1:
            out.append(T.OBS_ONE.format(name=name, coords=_coords(sel[:1])))
        else:
            out.append(T.OBS_MANY.format(name=name, n=len(sel), coords=_coords(sel[:1])))
    if n_far == 0:
        out.append(T.OBS_NONE)

    out.append(T.OBS_CREATURES)
    seen = visible_creatures(world)
    for k in seen[:8]:
        out.append(T.OBS_CREATURE.format(kind=world.dn(k["kind"]), id=k["id"],
                                         x=k["pos"][0], y=k["pos"][1], z=k["pos"][2]))
    if not seen:
        out.append(T.OBS_NONE)
    return "\n".join(out)
