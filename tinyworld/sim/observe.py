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
    """For (N, 3) cells as x, y, z: can the agent's eye see each one.

    A straight line runs from the eye to the nearest point of the cell and is sampled along
    its length. It is blocked by any cell that sight does not pass through. It is also
    blocked where it slips between two such cells that touch only at an edge.
    """
    if len(cells) == 0:
        return np.zeros(0, dtype=bool)
    x, y, z = world.pos
    eye = np.array([x + 0.5, y + 1.5, z + 0.5])
    head = np.array([x, y + 1, z])
    tgt = np.clip(eye, cells, cells + 1)                      # nearest point of each cell
    s = (np.arange(1, _SAMPLES) / _SAMPLES)[:, None, None]
    ijk = np.floor(eye + (tgt - eye) * s).astype(int)         # (samples, N, 3)
    size = np.array([world.sx, world.sy, world.sz])
    flat = ~_TRANSP[world.blocks].ravel()                      # index = x + z*sx + y*sx*sz
    mult = np.array([1, world.sx * world.sz, world.sx])

    def opaque(c: np.ndarray, own: np.ndarray) -> np.ndarray:
        inside = ((c >= 0) & (c < size)).all(-1)
        lin = np.clip(c, 0, size - 1) @ mult
        return flat[lin] & inside & (lin != own) & (lin != head @ mult)

    ok = ~opaque(ijk, cells @ mult).any(0)
    # Second pass, only for the cells still in the running: lines that slip through an edge.
    cells, ijk = cells[ok], ijk[:, ok]
    own = cells @ mult
    seq = np.concatenate([np.broadcast_to(head, (1,) + cells.shape), ijk, cells[None]])
    a, b = seq[:-1], seq[1:]
    changed = a != b
    walls = np.ones(changed.shape[:2], dtype=bool)            # every side cell on the way is opaque
    for axis in range(3):
        side = a.copy()
        side[..., axis] = b[..., axis]
        walls &= ~changed[..., axis] | opaque(side, own)
    ok[ok] = ~(walls & (changed.sum(-1) >= 2)).any(0)
    return ok


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
    near = [c for c in world.creatures + world.others()
            if max(abs(c["pos"][0] - px), abs(c["pos"][1] - py), abs(c["pos"][2] - pz)) <= r]
    if not near:
        return []
    ok = line_of_sight(world, np.array([c["pos"] for c in near]))
    seen = [c for c, v in zip(near, ok) if v]
    return sorted(seen, key=lambda c: (sum((a - b) ** 2 for a, b in zip(c["pos"], world.pos)), c["id"]))


def _coords(cells: np.ndarray) -> str:
    return " ".join(f"({int(c[0])},{int(c[1])},{int(c[2])})" for c in cells)


def open_beside_line(world) -> str:
    cells = world.open_beside()
    if len(cells) == 9:
        text = T.OBS_OPEN_BESIDE_ALL
    elif not cells:
        text = T.OBS_OPEN_BESIDE_NONE
    else:
        text = ", ".join(T.OBS_OPEN_BESIDE_ONE.format(where=w, x=p[0], y=p[1], z=p[2]) for w, p in cells)
    return T.OBS_OPEN_BESIDE.format(cells=text)


def vitals_line(world) -> str:
    v, before = world.cfg.vitals, world.vitals_before()
    if before is None:
        return T.OBS_VITALS.format(h=world.health, hm=v.max_health, f=world.food, fm=v.max_food,
                                   a=world.air, am=v.max_air)
    t0, h0, f0 = before
    return T.OBS_VITALS_BEFORE.format(h=world.health, hm=v.max_health, h0=h0, f=world.food, fm=v.max_food,
                                      f0=f0, t0=t0, a=world.air, am=v.max_air)


def made_line(world) -> str | None:
    """Each thing made so far with the items it was first made from, in the order first made."""
    if not world.made:
        return None
    def count(item: str, n: int) -> str:
        return world.dn(item) if n == 1 else T.OBS_MADE_COUNT.format(c=n, name=world.dn(item))
    parts = []
    for out, (items, n) in world.made.items():
        inputs = " + ".join(count(i, k) for i, k in items.items())
        parts.append(T.OBS_MADE_ONE.format(inputs=inputs, output=count(out, n)))
    return T.OBS_MADE.format(items="; ".join(parts))


def render(world) -> str:
    c, v = world.cfg, world.cfg.vitals
    x, y, z = world.pos
    out = [
        T.OBS_HEADER.format(t=world.t, day=world.day, light=world.light(), sky=world.sky())
        + (T.OBS_WEATHER.format(weather=world.weather) if c.weather.enabled else ""),
        T.OBS_POSITION.format(x=x, y=y, z=z, hy=y + 1),
    ]
    if world.multi:
        out.insert(1, T.OBS_SELF.format(id=world.me.id))
    out += [
        open_beside_line(world),
        vitals_line(world),
    ]
    if c.rule_notes and world.health < v.max_health and world.food < v.heal_food_min:
        out.append(T.OBS_NO_HEAL.format(n=v.heal_food_min))
    if world.wet():
        out.append(T.OBS_WET.format(what="rain and hail" if world.weather == "storm" else "rain"))
        if c.rule_notes:
            out.append(T.OBS_WET_RULE.format(m=c.weather.rain_food_mult))
    inv = []
    for item in sorted(world.inv, key=lambda i: i not in TOOLS):   # tools first, then in the order got
        n, name = world.inv[item], world.dn(item)
        if item in TOOLS:
            fmt = T.OBS_USES if n == 1 else T.OBS_USES_MANY
            inv.append(fmt.format(name=name, c=n, n=world.tools[item]))
        else:
            inv.append(T.OBS_COUNT.format(name=name, c=n))
    items = ", ".join(inv) if inv else T.OBS_EMPTY
    if world.cfg.inventory_slots > 0:
        out.append(T.OBS_INVENTORY_SLOTS.format(used=world.slots(world.inv), limit=world.cfg.inventory_slots, items=items))
    else:
        out.append(T.OBS_INVENTORY.format(items=items))
    made = made_line(world) if c.rule_notes else None
    if made:
        out.append(made)
    if world.bed is not None:
        out.append(T.OBS_RESPAWN.format(bed=world.dn("bed"), x=world.bed[0], y=world.bed[1], z=world.bed[2]))
    if world.last_action is not None:
        out.append(T.OBS_LAST.format(action=world.last_action, result=world.last_result))
    if world._death_notice:
        out.append(world._death_notice)
    if world._notice:
        out.append(world._notice)
    if world.me.heard:
        out.append(T.OBS_HEARD)
        out += world.me.heard[-12:]
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
        out.append(T.OBS_OPEN_ABOVE.format(x=x, y=y + 2, z=z))
    else:
        out.append(T.OBS_BLOCK_ABOVE.format(name=world.dn(BLOCKS[above[1]]), x=x, y=above[0], z=z))
    for (cx, cy, cz), held in sorted(world.chests.items()):          # contents of chests within reach
        if max(abs(cx - x), abs(cy - y), abs(cz - z)) <= c.reach:
            out.append(T.OBS_CHEST.format(chest=world.dn("chest"), x=cx, y=cy, z=cz,
                                          items=world._items_text(held) if held else T.OBS_EMPTY))

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
