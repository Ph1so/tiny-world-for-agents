"""The world: state, the seven actions, creatures, vitals, day and night, death."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import zlib
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from . import defs, text as T
from .body import Body, forward_body_fields
from .config import WorldConfig
from .defs import AGENT_PASS, AIR, BLOCKS, CREATURE_PASS, DIRS, ID, SUPPORT, TORCH, WATER
from .names import build_display_names
from .recipes import Recipe, build_recipes
from .terrain import generate

Pos = tuple[int, int, int]
LIGHTS = ["dark", "dim", "bright"]
_SUPPORT_ARR = np.array(SUPPORT)
_SOLID_ROOF = _SUPPORT_ARR.copy()              # blocks that shut out the sky: solid, not leaves
_SOLID_ROOF[ID["leaves"]] = False
_NEIGHBOURS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east", "up": "down", "down": "up"}
WORLD_EVENTS = {"day_start", "night_start", "weather"}   # not about any one agent
STRUCTURES = {"workbench", "furnace", "chest", "bed", "door", "torch"}   # placements listed in the observation


@dataclass
class StepResult:
    text: str
    steps: int
    valid: bool
    died: str | None
    deltas: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


def _int(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == int(v):
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v)
    return None


def _clean(v, n: int = 30) -> str:
    return "".join(ch for ch in str(v)[:n] if ch.isalnum() or ch in " -_")


def cheb(a, b) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


class World:
    def __init__(self, cfg: WorldConfig, seed: int = 0):
        self.me = Body()                                 # the body actions and vitals apply to
        self.bodies: list[Body] = [self.me]
        self.cfg = cfg
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)      # the one generator for terrain and dynamics
        self.blocks, self.spawn, start = generate(cfg, self.rng)
        self.sx, self.sy, self.sz = cfg.size
        self.display: dict[str, str] = build_display_names(cfg.names, self.seed)
        self._internal: dict[str, str] = {v: k for k, v in self.display.items()}
        self.recipes: list[Recipe] = build_recipes(cfg.shuffle_recipes, self.seed)

        self.t = 0
        self.done = False
        self.deaths = 0
        self.stuck = False
        self.pos: list[int] = list(self.spawn)
        self.inv: dict[str, int] = {}
        self.tools: dict[str, int] = {}                  # tool name -> uses left on the one in use
        self.chests: dict[Pos, dict[str, int]] = {}      # chest cell -> items in it; kept through death
        self.world_spawn: Pos = tuple(self.spawn)        # where the first body starts
        self._reset_vitals()
        self._give_start_items()
        self.creatures: list[dict] = []
        self._next_id = 1
        for kind, pos in start:
            self._spawn(kind, pos)
        self.regrow: list[list[int]] = []                # [t_due, x, y, z]
        # Separate streams, so weather and seed drops never shift terrain or creature draws.
        self._weather_rng = np.random.default_rng([self.seed, 0x3EA7])
        self._farm_rng = np.random.default_rng([self.seed, 0xFA23])
        self.weather = "clear"
        self.crops: dict[Pos, int] = {}                  # sprout cell -> growth so far
        self.bed: Pos | None = None                      # respawn point once slept in; kept through death
        self._asleep = False
        self._wild_wheat()
        # output -> (items used, count made), the first way each thing was made. Kept through death
        # unless the memory is wiped, as it stands for what the agent knows.
        self.made: dict[str, tuple[dict[str, int], int]] = {}
        self._strikes: list[tuple[Body, int, Body]] = []   # (target, damage, attacker) this step
        self._last_hit = -10**9
        self.last_action: str | None = None
        self.last_result: str | None = None
        self._notice: str | None = None
        self._notice_shown = False
        self._death_notice: str | None = None
        self._changed: dict[Pos, str] = {}
        self._deltas: list[dict] = []
        self._events: list[dict] = []
        self._hurt = False
        self._hits: list[str] = []       # who hit the agent this step, added to the result
        self._died: str | None = None
        self._cause = ""

    # ---------------------------------------------------------------- names

    def dn(self, name: str) -> str:
        """Familiar name to the name the agent is shown."""
        return self.display.get(name, name)

    def internal(self, shown) -> str | None:
        """What the agent typed to the familiar name, or None."""
        if not isinstance(shown, str):
            return None
        return self._internal.get(" ".join(shown.strip().lower().replace("_", " ").split()))

    # --------------------------------------------------------------- blocks

    def inb(self, x: int, y: int, z: int) -> bool:
        return 0 <= x < self.sx and 0 <= y < self.sy and 0 <= z < self.sz

    def bid(self, x: int, y: int, z: int) -> int:
        """Block id. Outside the map counts as stone, above the map as air."""
        if 0 <= x < self.sx and 0 <= z < self.sz and 0 <= y:
            return int(self.blocks[y, z, x]) if y < self.sy else AIR
        return ID["stone"]

    def block(self, x: int, y: int, z: int) -> str:
        return BLOCKS[self.bid(x, y, z)]

    def set_block(self, x: int, y: int, z: int, name: str) -> None:
        self.blocks[y, z, x] = ID[name]
        self._changed[(x, y, z)] = name

    def find(self, name: str) -> list[Pos]:
        """All cells holding this block, as (x, y, z)."""
        return [(int(x), int(y), int(z)) for y, z, x in np.argwhere(self.blocks == ID[name])]

    def exposed(self, x: int, y: int, z: int) -> bool:
        """True if a face of the cell touches a cell that is not a full block."""
        return any(not SUPPORT[self.bid(x + dx, y + dy, z + dz)] or self.bid(x + dx, y + dy, z + dz) == defs.DOOR
                   for dx, dy, dz in _NEIGHBOURS if self.inb(x + dx, y + dy, z + dz))

    def exposed_mask(self) -> np.ndarray:
        """Bool array [y, z, x], same rule as exposed()."""
        lut = np.array([not s or n == "door" for s, n in zip(SUPPORT, BLOCKS)])
        o = lut[self.blocks]
        m = np.zeros_like(o)
        m[1:] |= o[:-1]; m[:-1] |= o[1:]
        m[:, 1:] |= o[:, :-1]; m[:, :-1] |= o[:, 1:]
        m[:, :, 1:] |= o[:, :, :-1]; m[:, :, :-1] |= o[:, :, 1:]
        return m

    # ------------------------------------------------------------- movement

    def _occupied(self, x: int, y: int, z: int) -> bool:
        """A creature stands in the cell, or another agent's feet or head is in it."""
        return (any(c["pos"][0] == x and c["pos"][1] == y and c["pos"][2] == z for c in self.creatures)
                or self._body_at(x, y, z, but=self.me) is not None)

    # ---------------------------------------------------------- many bodies

    @property
    def multi(self) -> bool:
        """More than one agent, or agents with ids: the multi-agent world."""
        return self.me.id is not None

    def living(self) -> list[Body]:
        return [b for b in self.bodies if b.alive]

    def _body_at(self, x: int, y: int, z: int, but: Body | None = None) -> Body | None:
        """The living body whose feet or head is in this cell, other than but."""
        for b in self.bodies:
            if b is not but and b.alive and b.pos[0] == x and b.pos[2] == z and y in (b.pos[1], b.pos[1] + 1):
                return b
        return None

    def _any_agent_in(self, x: int, y: int, z: int) -> bool:
        return self._body_at(x, y, z) is not None

    def body(self, id: int) -> Body | None:
        return next((b for b in self.bodies if b.id == id), None)

    def others(self) -> list[dict]:
        """Every other living agent, shaped like a creature entry."""
        return [{"id": b.id, "kind": "agent", "pos": b.pos} for b in self.bodies if b is not self.me and b.alive]

    def add_body(self, name: str | None = None) -> Body:
        """Another agent, standing on the free cell nearest the start point. The first call names
        the body the world was made with; each later call adds one."""
        if self.me.id is None:
            b = self.me
        else:
            b = Body()
            self.bodies.append(b)
        b.id, b.name = self._next_id, name
        self._next_id += 1
        me = self.me
        self.me = b
        if b is not self.bodies[0] or b.pos == [0, 0, 0]:
            cell = self._free_cell_near(self.world_spawn)
            b.spawn, b.pos = cell, list(cell)
            self._reset_vitals()
            self._give_start_items()
        self.me = me
        return b

    def _give_start_items(self) -> None:
        """start_items into the current body's inventory (a new agent; not on respawn)."""
        for item, n in self.cfg.start_items.items():
            if item not in defs.ITEMS:
                raise ValueError(f"start_items: unknown item {item!r}")
            if n > 0:
                self._add(item, int(n))

    def _free_cell_near(self, p) -> Pos:
        """The nearest dry standing cell to p (sideways rings, any height) that no agent or
        creature is in."""
        px, py, pz = p
        for r in range(0, max(self.sx, self.sz)):
            for x in range(px - r, px + r + 1):
                for z in range(pz - r, pz + r + 1):
                    if max(abs(x - px), abs(z - pz)) != r or not (0 <= x < self.sx and 0 <= z < self.sz):
                        continue
                    for y in sorted(range(1, self.sy - 1), key=lambda yy: abs(yy - py)):
                        if (self.bid(x, y, z) != WATER and AGENT_PASS[self.bid(x, y, z)]
                                and AGENT_PASS[self.bid(x, y + 1, z)] and SUPPORT[self.bid(x, y - 1, z)]
                                and not self._any_agent_in(x, y, z) and not self._any_agent_in(x, y + 1, z)
                                and not any(c["pos"] == [x, y, z] for c in self.creatures)):
                            return (x, y, z)
        return tuple(p)

    def step_target(self, pos, d: str) -> Pos | None:
        """Cell the agent would step into, before falling. None if blocked."""
        x, y, z = pos
        dx, dy, dz = DIRS[d]
        if dy:
            if dy > 0 and self.bid(x, y, z) == WATER and AGENT_PASS[self.bid(x, y + 2, z)] and y + 2 < self.sy:
                return (x, y + 1, z)
            if dy < 0 and y > 0 and self.bid(x, y - 1, z) == WATER:
                return (x, y - 1, z)
            return None
        nx, nz = x + dx, z + dz
        if not (0 <= nx < self.sx and 0 <= nz < self.sz):
            return None
        if AGENT_PASS[self.bid(nx, y, nz)] and AGENT_PASS[self.bid(nx, y + 1, nz)]:
            return (nx, y, nz)
        if (y + 2 < self.sy and AGENT_PASS[self.bid(nx, y + 1, nz)] and AGENT_PASS[self.bid(nx, y + 2, nz)]
                and AGENT_PASS[self.bid(x, y + 2, z)]):
            return (nx, y + 1, nz)
        return None

    def settle(self, pos) -> tuple[Pos, int]:
        """Apply gravity. Returns (resting cell, cells fallen). Water holds the agent up."""
        x, y, z = pos
        fell = 0
        while y > 0 and self.bid(x, y, z) != WATER and not SUPPORT[self.bid(x, y - 1, z)]:
            y -= 1
            fell += 1
        return (x, y, z), fell

    def walk_step(self, pos, d: str) -> tuple[Pos, int] | None:
        """Where one horizontal step ends after falling, and how far it fell. Ignores creatures."""
        tgt = self.step_target(pos, d)
        return None if tgt is None else self.settle(tgt)

    def _move_once(self, d: str) -> bool:
        me = self.me
        if me.swapped_t == self.t:                    # a partner already swapped places with us
            return True
        tgt = self.step_target(self.pos, d)
        if tgt is None:
            return False
        other = self._body_at(*tgt, but=me) or self._body_at(tgt[0], tgt[1] + 1, tgt[2], but=me)
        if other is not None and other.heading == _OPPOSITE[d] and other.swapped_t != self.t \
                and self.step_target(other.pos, other.heading) == tuple(me.pos):
            # Two agents walking into each other trade places, so a 1-wide tunnel never jams.
            other.pos, me.pos = list(me.pos), list(tgt)
            other.swapped_t = self.t
            return True
        if self._occupied(*tgt) or self._occupied(tgt[0], tgt[1] + 1, tgt[2]):
            return False
        self.pos = list(tgt)
        return True

    # ------------------------------------------------------------ inventory

    def _add(self, item: str, n: int) -> None:
        self.inv[item] = self.inv.get(item, 0) + n
        if item in defs.TOOLS and item not in self.tools:
            self.tools[item] = self.cfg.durability[item]

    def _take(self, item: str, n: int) -> None:
        left = self.inv.get(item, 0) - n
        if left > 0:
            self.inv[item] = left
        else:
            self.inv.pop(item, None)
            self.tools.pop(item, None)

    def slots(self, items: dict[str, int]) -> int:
        """Slots these items fill: one per tool, one per stack_size of anything else."""
        return sum(n if i in defs.TOOLS else math.ceil(n / self.cfg.stack_size) for i, n in items.items())

    def _fits(self, add: dict[str, int], take: dict[str, int] | None = None) -> bool:
        """Whether the inventory would stay within its slots after taking and adding these."""
        if self.cfg.inventory_slots <= 0:
            return True
        after = dict(self.inv)
        for i, n in (take or {}).items():
            after[i] = after.get(i, 0) - n
        for i, n in add.items():
            after[i] = after.get(i, 0) + n
        return self.slots({i: n for i, n in after.items() if n > 0}) <= self.cfg.inventory_slots

    def pick_tier(self) -> int:
        return max([t for p, t in defs.PICKAXES.items() if self.inv.get(p, 0) > 0], default=0)

    def _best_pick(self) -> str | None:
        have = [p for p in defs.PICKAXES if self.inv.get(p, 0) > 0]
        return max(have, key=lambda p: defs.PICKAXES[p]) if have else None

    def _best_sword(self) -> str | None:
        have = [s for s in defs.SWORDS if self.inv.get(s, 0) > 0]
        return max(have, key=lambda s: self.cfg.sword_damage[s]) if have else None

    def _wear(self, tool: str) -> bool:
        """Use the tool once. True if it broke."""
        self.tools[tool] -= 1
        if self.tools[tool] > 0:
            return False
        self.tools.pop(tool)
        self._take(tool, 1)
        if self.inv.get(tool, 0) > 0:
            self.tools[tool] = self.cfg.durability[tool]
        self._event("tool_broke", {"tool": tool})
        return True

    def mine_steps(self, block: str) -> int | None:
        """World steps to break this block with the current tools. None if it will not break."""
        tier = self.pick_tier()
        if block in ("air", "water") or tier < defs.MINE_TIER.get(block, 0):
            return None
        return max(1, math.ceil(self.cfg.hardness[block] / self.cfg.tool_speed[tier]))

    def match_recipe(self, items: dict[str, int]) -> Recipe | None:
        for r in self.recipes:
            need = r.items()
            fuel = need.pop("fuel", 0)
            if not fuel:
                if need == items:
                    return r
                continue
            for f in defs.FUELS:
                n2 = dict(need)
                n2[f] = n2.get(f, 0) + fuel
                if n2 == items:
                    return r
        return None

    def station_near(self, station: str | None) -> bool:
        if station is None:
            return True
        r = self.cfg.station_reach
        x, y, z = self.pos
        box = self.blocks[max(0, y - r):y + r + 1, max(0, z - r):z + r + 1, max(0, x - r):x + r + 1]
        return bool((box == ID[station]).any())

    # ------------------------------------------------------------ creatures

    def _spawn(self, kind: str, pos) -> None:
        self.creatures.append({"id": self._next_id, "kind": kind, "pos": [int(p) for p in pos],
                               "hp": self.cfg.creatures.health[kind]})
        self._next_id += 1

    def _roof(self) -> np.ndarray:
        """Per (z, x) column, the y of the highest block that shuts out the sky (solid, not
        leaves), or -1. A cell is covered when this is above its head (roof >= y + 2)."""
        solid = _SOLID_ROOF[self.blocks]
        any_ = solid.any(axis=0)
        top = self.sy - 1 - np.argmax(solid[::-1], axis=0)
        return np.where(any_, top, -1)

    def covered(self, x: int, y: int, z: int) -> bool:
        """Under a roof: dark at any time of day unless a torch is near."""
        col = self.blocks[y + 2:, z, x]
        return bool(_SOLID_ROOF[col].any()) if y + 2 < self.sy else False

    def _dark_spawn_cell(self) -> Pos | None:
        """A random covered, unlit open cell a zombie could stand in, between
        zombie_dark_min_dist and zombie_spawn_max_dist (sideways) from the agent, or None."""
        cc = self.cfg.creatures
        ax, ay, az = self.pos
        hi, lo = cc.zombie_spawn_max_dist, cc.zombie_dark_min_dist
        x0, x1 = max(0, ax - hi), min(self.sx, ax + hi + 1)
        z0, z1 = max(0, az - hi), min(self.sz, az + hi + 1)
        b = self.blocks[:, z0:z1, x0:x1]
        air = b == AIR
        ok = np.zeros_like(air)
        ok[1:-1] = air[1:-1] & air[2:] & _SUPPORT_ARR[b[:-2]]          # feet, head free, floor below
        roof = self._roof()[z0:z1, x0:x1]
        ys = np.arange(self.sy)[:, None, None]
        ok &= roof[None] >= ys + 2
        zs = np.arange(z0, z1)[None, :, None]
        xs = np.arange(x0, x1)[None, None, :]
        ok &= np.maximum(np.abs(xs - ax), np.abs(zs - az)) >= lo
        if not ok.any():
            return None
        torches = self.find("torch")
        cells = [(int(x + x0), int(y), int(z + z0)) for y, z, x in np.argwhere(ok)]
        cells = [p for p in cells if not self._occupied(*p)
                 and not any(cheb(p, tp) <= max(cc.torch_radius, self.cfg.torch_light) for tp in torches)]
        if not cells:
            return None
        return cells[int(self.rng.integers(len(cells)))]

    def _surface(self, x: int, z: int) -> int | None:
        """y of the open cell on top of the column, or None if the top is water."""
        col = self.blocks[:, z, x]
        top = int(np.flatnonzero(col != AIR)[-1])
        if not SUPPORT[int(col[top])] or top + 1 >= self.sy:
            return None
        return top + 1

    def _creature_target(self, c: dict, d: str) -> Pos | None:
        x, y, z = c["pos"]
        dx, _, dz = DIRS[d]
        nx, nz = x + dx, z + dz
        if not (0 <= nx < self.sx and 0 <= nz < self.sz):
            return None
        if CREATURE_PASS[self.bid(nx, y, nz)]:
            ny = y
        elif CREATURE_PASS[self.bid(nx, y + 1, nz)] and CREATURE_PASS[self.bid(x, y + 1, z)] and y + 1 < self.sy:
            ny = y + 1
        else:
            return None
        fell = 0
        while ny > 0 and CREATURE_PASS[self.bid(nx, ny - 1, nz)]:
            ny -= 1
            fell += 1
        if not SUPPORT[self.bid(nx, ny - 1, nz)] or (fell > 3 and c["kind"] != "zombie"):
            return None                                       # creatures stay out of water
        if self._any_agent_in(nx, ny, nz):
            return None
        if self._occupied(nx, ny, nz):
            return None
        return (nx, ny, nz)

    def _creatures_tick(self, tod: int) -> None:
        cc = self.cfg.creatures
        bodies = self.living()
        for c in self.creatures:                              # list order is id order
            x, y, z = c["pos"]
            while y > 0 and CREATURE_PASS[self.bid(x, y - 1, z)]:
                y -= 1                                        # the ground under it was removed
            c["pos"][1] = y
            d = None
            if c["kind"] == "zombie":
                e = cc.zombie_step_every
                if int(self.t / e) == int((self.t - 1) / e):
                    continue
                prey = min(bodies, key=lambda b: (cheb(c["pos"], b.pos), b.id or 0)) if bodies else None
                if prey is not None and cheb(c["pos"], prey.pos) <= cc.zombie_chase_dist:
                    ddx, ddz = prey.pos[0] - x, prey.pos[2] - z
                    east = ("east" if ddx > 0 else "west", ddx)
                    south = ("south" if ddz > 0 else "north", ddz)
                    pair = (east, south) if abs(ddx) >= abs(ddz) else (south, east)
                    order = [name for name, dd in pair if dd]
                    moved = False
                    for o in order:
                        tgt = self._creature_target(c, o)
                        if tgt:
                            c["pos"] = list(tgt)
                            c.pop("break", None)
                            moved = True
                            if self.cfg.farming.zombies_trample:
                                self._trample(tgt)
                            break
                    if not moved and (cc.zombie_breaks or self.cfg.farming.zombies_trample):
                        self._zombie_break(c, order)
                    continue
                if self.rng.random() < 0.5:
                    d = defs.HORIZONTAL[int(self.rng.integers(4))]
            elif self.rng.random() < cc.passive_move_prob:
                d = defs.HORIZONTAL[int(self.rng.integers(4))]
            if d:
                tgt = self._creature_target(c, d)
                if tgt:
                    c["pos"] = list(tgt)

        if not bodies:
            return
        me = self.me
        # Spawns are placed around one agent: the only one, or one picked at random.
        self.me = bodies[int(self.rng.integers(len(bodies)))] if len(bodies) > 1 else bodies[0]
        ax, ay, az = self.pos
        night = tod >= self.cfg.night_start or self.weather == "storm"
        n_z = sum(c["kind"] == "zombie" for c in self.creatures)
        if night and n_z < cc.zombie_max and self.rng.random() < cc.zombie_spawn_prob:
            torches = self.find("torch")
            lo, hi = cc.zombie_spawn_min_dist, cc.zombie_spawn_max_dist
            for _ in range(8):
                x = int(self.rng.integers(max(0, ax - hi), min(self.sx, ax + hi + 1)))
                z = int(self.rng.integers(max(0, az - hi), min(self.sz, az + hi + 1)))
                if max(abs(x - ax), abs(z - az)) < lo:
                    continue
                y = self._surface(x, z)
                if y is None or self._occupied(x, y, z):
                    continue
                if any(cheb((x, y, z), tp) <= cc.torch_radius for tp in torches):
                    continue
                self._spawn("zombie", (x, y, z))
                break
        # Under a roof it is dark at any hour: zombies can come up out of the agent's own tunnels.
        n_z = sum(c["kind"] == "zombie" for c in self.creatures)
        if cc.zombie_dark_spawn_prob > 0 and n_z < cc.zombie_max and self.rng.random() < cc.zombie_dark_spawn_prob:
            cell = self._dark_spawn_cell()
            if cell is not None:
                self._spawn("zombie", cell)

        for b in bodies:
            self.me = b
            ax, ay, az = self.pos
            once = self.multi and cc.zombie_hits_per_decision
            if self.health > 0 and self.t - self._last_hit >= cc.zombie_cooldown and not (once and b.hit_decision == b.decisions):
                for c in self.creatures:
                    if c["kind"] != "zombie":
                        continue
                    x, y, z = c["pos"]
                    beside = abs(x - ax) + abs(z - az) == 1 and y in (ay, ay + 1)
                    above = (x, z) == (ax, az) and y == ay + 2
                    if beside or above:
                        self._hits.append(T.HIT_YOU.format(kind=self.dn("zombie").capitalize(), id=c["id"], x=x, y=y, z=z))
                        self._damage(self._armored(cc.zombie_damage), "zombie")
                        self._last_hit = self.t
                        b.hit_decision = b.decisions
                        break
        self.me = me

    def _armored(self, n: int) -> int:
        """Zombie damage after armor. Each piece held takes off its points (at least 1 gets
        through) and wears once per hit."""
        worn = [a for a in defs.ARMOR if self.inv.get(a, 0) > 0]
        for a in worn:
            self._wear(a)
        return max(1, n - sum(self.cfg.armor[a] for a in worn))

    def _zombie_break(self, c: dict, order: list[str]) -> None:
        """A chasing zombie blocked by a breakable block grinds it down, then removes it.

        It works on the block right in its path toward the agent, at its own feet level.
        Progress is per zombie and resets if it turns to a different cell. Blocks not in
        zombie_breaks (stone, workbench, furnace, door) stop it, so a stone box is safe.
        """
        breaks = list(self.cfg.creatures.zombie_breaks)
        if self.cfg.farming.zombies_trample:
            breaks += ["sprout", "wheat"]
        x, y, z = c["pos"]
        for o in order:
            dx, _, dz = DIRS[o]
            cell = (x + dx, y, z + dz)
            if not self.inb(*cell) or self.block(*cell) not in breaks:
                continue
            prog = c.get("break")
            if not prog or tuple(prog[0]) != cell:
                prog = [list(cell), 0]
            prog[1] += 1
            if prog[1] >= self.cfg.creatures.zombie_break_steps:
                if self.block(*cell) in ("sprout", "wheat"):
                    self._event("crop_trampled", {"pos": list(cell)})
                self.set_block(*cell, "air")
                c.pop("break", None)
            else:
                c["break"] = prog
            return
        c.pop("break", None)

    def visible_creatures(self) -> list[dict]:
        from .observe import visible_creatures
        return visible_creatures(self)

    # --------------------------------------------------------------- vitals

    def _reset_vitals(self) -> None:
        v = self.cfg.vitals
        self.health, self.food, self.air = v.max_health, v.max_food, v.max_air
        self._food_tick = self._starve_tick = self._heal_tick = self._hail_tick = 0
        # (t, health, food) per world step since the last (re)spawn, for the trend in the observation.
        self._vitals_log: deque = deque([(self.t, self.health, self.food)], maxlen=self.cfg.vitals_lookback + 1)

    def vitals_before(self) -> tuple[int, int, int] | None:
        """(t, health, food) vitals_lookback steps ago, or at the last (re)spawn if that is later.
        None when there is no earlier step to compare with."""
        if self.cfg.vitals_lookback <= 0 or self._vitals_log[0][0] >= self.t:
            return None
        return self._vitals_log[0]

    def vitals(self) -> dict:
        return {"health": self.health, "food": self.food, "air": self.air}

    def _damage(self, n: int, cause: str) -> None:
        if self.health <= 0:
            return
        self.health = max(0, self.health - n)
        self._hurt = True
        self._cause = cause
        self._event("hurt", {"cause": cause, "amount": n})

    def wet(self) -> bool:
        """Rain or a storm, and nothing solid over the agent's head."""
        return self.weather != "clear" and not self.covered(*self.pos)

    def _vitals_tick(self) -> None:
        v, w = self.cfg.vitals, self.cfg.weather
        wet = self.wet()
        self._food_tick += w.rain_food_mult if wet else 1
        if self._food_tick >= v.food_drain_every:
            self._food_tick = 0
            self.food = max(0, self.food - 1)
        if wet and self.weather == "storm":
            self._hail_tick += 1
            if self._hail_tick >= w.hail_every:
                self._hail_tick = 0
                self._hits.append(T.HAIL_HIT)
                self._damage(w.hail_damage, "hail")
        else:
            self._hail_tick = 0
        if self.food == 0:
            self._starve_tick += 1
            if self._starve_tick >= v.starve_every:
                self._starve_tick = 0
                self._damage(1, "hunger")
        else:
            self._starve_tick = 0
        if self._asleep:
            can_heal, every = self.food > 0, self.cfg.sleep_heal_every
        else:
            can_heal, every = self.food >= v.heal_food_min and not wet, v.heal_every
        if can_heal and self.health < v.max_health:
            self._heal_tick += 1
            if self._heal_tick >= every:
                self._heal_tick = 0
                self.health += 1
        else:
            self._heal_tick = 0
        x, y, z = self.pos
        if self.bid(x, y + 1, z) == WATER:
            if self.air > 0:
                self.air -= 1
            else:
                self._damage(v.drown_damage, "drowning")
        else:
            self.air = v.max_air

    def _sky_level(self, weather: bool = True) -> int:
        """2 bright, 1 dim, 0 dark. A storm makes the sky dark at any hour; weather=False gives
        the level by time of day alone."""
        c = self.cfg
        if weather and self.weather == "storm":
            return 0
        tod = self.t % c.day_length
        if tod < c.night_start - c.dim_steps:
            return 2
        if tod < c.night_start or tod >= c.day_length - c.dim_steps:
            return 1
        return 0

    def _weather_tick(self) -> None:
        """Draw the next weather at the start of each spell. The first spell is always clear."""
        w = self.cfg.weather
        if not w.enabled or self.t % w.spell:
            return
        r = self._weather_rng.random()
        new = "storm" if r < w.storm_prob else "rain" if r < w.storm_prob + w.rain_prob else "clear"
        if new != self.weather:
            self.weather = new
            self._event("weather", {"weather": new})

    def _wild_wheat(self) -> None:
        """A few patches of ripe wheat on open soil by water, so wheat (and the seeds it gives) can
        be found. Its own random stream: the terrain, creatures and every later draw are unchanged."""
        f = self.cfg.farming
        if f.wild_patches <= 0 or f.wild_per_patch <= 0:
            return
        rng = np.random.default_rng([self.seed, 0xEA7])
        b = self.blocks
        top = self.sy - 1 - np.argmax((b != AIR)[::-1], axis=0)                 # (z, x)
        zs, xs = np.indices(top.shape)
        soil = np.isin(b[top, zs, xs], [ID[n] for n in defs.SOIL]) & (top + 1 < self.sy)
        sx, _, sz = self.spawn
        taken = {tuple(c["pos"]) for c in self.creatures}
        cells = [(int(x), int(top[z, x]) + 1, int(z)) for z, x in zip(*np.nonzero(soil))
                 if max(abs(x - sx), abs(z - sz)) > 2]
        cells = [p for p in cells if p not in taken and self._water_near(p)]
        for _ in range(f.wild_patches):
            if not cells:
                return
            cx, _, cz = cells[int(rng.integers(len(cells)))]
            near = [p for p in cells if max(abs(p[0] - cx), abs(p[2] - cz)) <= 2]
            for k in rng.permutation(len(near))[:f.wild_per_patch]:
                x, y, z = near[int(k)]
                b[y, z, x] = defs.WHEAT
            cells = [p for p in cells if b[p[1], p[2], p[0]] == AIR]

    def _trample(self, pos) -> None:
        """A zombie that stepped up onto a sprout or wheat crushes it (it drops onto the soil)."""
        x, y, z = pos
        if self.bid(x, y - 1, z) in (defs.SPROUT, defs.WHEAT):
            self.set_block(x, y - 1, z, "air")
            self._event("crop_trampled", {"pos": [x, y - 1, z]})

    def _animals_eat(self) -> None:
        """With animal_eat_prob, a sheep or chicken beside a sprout or wheat (sideways, same level)
        may eat it. Draws come from the farming stream, only while crops stand next to animals."""
        p = self.cfg.farming.animal_eat_prob
        if p <= 0:
            return
        for c in self.creatures:
            if c["kind"] not in defs.PASSIVE:
                continue
            x, y, z = c["pos"]
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                q = (x + dx, y, z + dz)
                if self.inb(*q) and self.bid(*q) in (defs.SPROUT, defs.WHEAT) and self._farm_rng.random() < p:
                    self.set_block(*q, "air")
                    self._event("crop_eaten", {"kind": c["kind"], "pos": list(q)})
                    break

    def _crops_tick(self) -> None:
        """Each sprout grows one step, two in rain or a storm with nothing solid above it, and
        turns into wheat at grow_steps."""
        grow = self.cfg.farming.grow_steps
        for p in list(self.crops):
            x, y, z = p
            if self.bid(*p) != defs.SPROUT:
                del self.crops[p]
                continue
            rained = self.weather != "clear" and not _SOLID_ROOF[self.blocks[y + 1:, z, x]].any()
            self.crops[p] += 2 if rained else 1
            if self.crops[p] >= grow:
                del self.crops[p]
                self.set_block(*p, "wheat")

    def sky(self) -> str:
        """The light of the open sky by time of day, wherever the agent is."""
        return LIGHTS[self._sky_level()]

    def open_beside(self) -> list[tuple[str, Pos]]:
        """Cells touching the body that a creature could stand in, where a zombie could reach it
        from: the four sides at feet and at head level, and the cell above the head. Doors and
        water are not among them (creatures do not enter either)."""
        x, y, z = self.pos
        out = []
        for level, yy in (("feet", y), ("head", y + 1)):
            for d in defs.HORIZONTAL:
                dx, _, dz = DIRS[d]
                p = (x + dx, yy, z + dz)
                if self.inb(*p) and CREATURE_PASS[self.bid(*p)]:
                    out.append((f"{level} {d}", p))
        p = (x, y + 2, z)
        if self.inb(*p) and CREATURE_PASS[self.bid(*p)]:
            out.append(("above head", p))
        return out

    def enclosure(self, cap: int = 200) -> int | None:
        """Floor cells of the closed space the agent is in: the cells a creature could pass through
        (air, torch) joined face to face to the agent's two cells, if they close off before cap
        cells and before the map's edge or top. None when open. Doors, leaves and every solid
        block count as closed; the space must have a roof."""
        x, y, z = self.pos
        start = [(x, y, z), (x, y + 1, z)]
        seen = set(start)
        todo = list(start)
        while todo:
            px, py, pz = todo.pop()
            for dx, dy, dz in _NEIGHBOURS:
                q = (px + dx, py + dy, pz + dz)
                if q in seen:
                    continue
                if not self.inb(*q):
                    return None
                if not CREATURE_PASS[self.bid(*q)]:
                    continue
                seen.add(q)
                if len(seen) > cap:
                    return None
                todo.append(q)
        return sum(1 for (cx, cy, cz) in seen if SUPPORT[self.bid(cx, cy - 1, cz)] and (cx, cy + 1, cz) in seen)

    def light(self) -> str:
        c = self.cfg
        level = self._sky_level()
        x, y, z = self.pos
        if self.covered(x, y, z):                     # under a roof it is dark at any hour
            level = 0
        if level == 0:
            r = c.torch_light
            box = self.blocks[max(0, y - r):y + r + 1, max(0, z - r):z + r + 1, max(0, x - r):x + r + 1]
            if (box == TORCH).any():
                level = 1
        return LIGHTS[level]

    @property
    def day(self) -> int:
        return self.t // self.cfg.day_length + 1

    # ----------------------------------------------------------------- tick

    def _event(self, kind: str, detail: dict) -> None:
        if self.multi and kind not in WORLD_EVENTS:
            detail = {**detail, "agent": self.me.id}
        self._events.append({"t": self.t, "type": kind, "detail": detail})

    def _first(self, group: str, name: str, key: str) -> None:
        if name not in self.firsts[group]:
            self.firsts[group].append(name)
            self._event("first_" + group, {key: name})

    def _tick(self) -> None:
        """Advance the world one step."""
        c = self.cfg
        self.t += 1
        tod = self.t % c.day_length
        self._weather_tick()
        if tod < c.night_start and self.weather != "storm":   # daylight: zombies out under the open sky are gone
            self.creatures = [k for k in self.creatures if k["kind"] != "zombie" or self.covered(*k["pos"])]
        if tod == 0:
            self._event("day_start", {"day": self.day})
            self._respawn_passives()
        elif tod == c.night_start:
            self._event("night_start", {"day": self.day})
        for due in [r for r in self.regrow if r[0] <= self.t]:
            _, x, y, z = due
            if self.bid(x, y, z) == AIR and not self._occupied(x, y, z) and not self._any_agent_in(x, y, z):
                self.set_block(x, y, z, "berry bush")
                self.regrow.remove(due)
            else:
                due[0] = self.t + 10
        self._crops_tick()
        self._animals_eat()

        me = self.me
        bodies = self.living()
        for b in bodies:
            self.me = b
            pos, fell = self.settle(self.pos)
            self.pos = list(pos)
            if fell > c.vitals.fall_safe and self.bid(*pos) != WATER:
                self._damage(fell - c.vitals.fall_safe, "fall")
            self._vitals_tick()
        self._apply_strikes()
        self.me = me
        self._creatures_tick(tod)
        for b in bodies:
            self.me = b
            if self.health <= 0:
                self._die()
            self._vitals_log.append((self.t, self.health, self.food))
        self.me = me
        self._deltas.append(self._delta())

    def _apply_strikes(self) -> None:
        """Agent-on-agent hits from this step, all at once, so the order agents acted in gives no
        edge and two agents can kill each other. Armor works as against zombies."""
        strikes, self._strikes = self._strikes, []
        for target, dmg, attacker in strikes:
            if not target.alive or target.health <= 0:
                continue
            self.me = target
            ax, ay, az = attacker.pos
            self._hits.append(T.HIT_YOU.format(kind=self.dn("agent").capitalize(), id=attacker.id, x=ax, y=ay, z=az))
            self._damage(self._armored(dmg), "agent")
            if self.health <= 0:
                self.me = attacker
                self._event("kill", {"kind": "agent", "id": target.id})
                if self.cfg.pvp_loot:
                    for item, n in list(target.inv.items()):
                        got = next((m for m in range(n, 0, -1) if self._fits({item: m})), 0)
                        if got:
                            uses = target.tools.get(item)
                            self._add(item, got)
                            if uses is not None and item not in self.tools:
                                self.tools[item] = uses

    def _agent_in(self, x: int, y: int, z: int) -> bool:
        ax, ay, az = self.pos
        return (x, z) == (ax, az) and y in (ay, ay + 1)

    def _respawn_passives(self) -> None:
        cc = self.cfg.creatures
        expect = max(0.0, cc.passive_respawn * cc.animal_count_mult)
        pmax = max(0, int(round(cc.passive_max * cc.animal_count_mult)))
        for kind in defs.PASSIVE:
            n = sum(k["kind"] == kind for k in self.creatures)
            # A fractional rate is a chance: 0.5 is one about every other morning. Whole rates draw
            # nothing extra, so runs that use them are unchanged.
            respawn = int(expect) + (int(self._farm_rng.random() < expect % 1) if expect % 1 else 0)
            for _ in range(min(respawn, pmax - n)):
                for _ in range(20):
                    x, z = int(self.rng.integers(3, self.sx - 3)), int(self.rng.integers(3, self.sz - 3))
                    y = self._surface(x, z)
                    if (y is not None and self.bid(x, y - 1, z) == ID["grass"] and not self._occupied(x, y, z)
                            and not self._any_agent_in(x, y, z)):
                        self._spawn(kind, (x, y, z))
                        break

    def _die(self) -> None:
        cause = self._cause
        self._died = cause
        self.deaths += 1
        self._event("death", {"cause": cause, "pos": list(self.pos)})
        if self.cfg.on_death == "end_run":
            self._death_notice = T.DIED_END.format(cause=self.dn(cause))
            if self.multi:                            # out of the world; the others go on
                self.me.alive = False
                self.done = not self.living()
            else:
                self.done = True
            return
        at_bed = self._bed_cell()
        self.pos = list(at_bed or self._respawn_cell())
        self.inv, self.tools = {}, {}
        if self.cfg.on_death == "respawn_wipe_memory":
            self.made = {}
        self._reset_vitals()
        if at_bed:
            bx, by, bz = self.bed
            self._death_notice = T.DIED_RESPAWN_BED.format(cause=self.dn(cause), bed=self.dn("bed"), x=bx, y=by, z=bz)
        else:
            self._death_notice = T.DIED_RESPAWN.format(cause=self.dn(cause))
        if self.cfg.rule_notes:
            if not at_bed:
                self._death_notice += T.DIED_BED_NOTE.format(bed=self.dn("bed"))
            self._death_notice += T.DIED_CHEST_NOTE.format(chest=self.dn("chest"))
        self._event("respawn", {"pos": list(self.pos)})

    def _bed_cell(self) -> Pos | None:
        """A dry standing cell beside the respawn bed, nearest first, or None if there is no bed
        any more (it was broken) or no room beside it."""
        if self.bed is None or self.bid(*self.bed) != defs.BED:
            self.bed = None
            return None
        bx, by, bz = self.bed
        for r in (1, 2):
            for dy in (0, 1, -1, 2, -2):
                for x in range(bx - r, bx + r + 1):
                    for z in range(bz - r, bz + r + 1):
                        y = by + dy
                        if max(abs(x - bx), abs(z - bz)) != r or not self.inb(x, y, z) or y < 1:
                            continue
                        if (self.bid(x, y, z) != WATER and AGENT_PASS[self.bid(x, y, z)]
                                and AGENT_PASS[self.bid(x, y + 1, z)] and SUPPORT[self.bid(x, y - 1, z)]
                                and not self._occupied(x, y, z) and not self._occupied(x, y + 1, z)):
                            return (x, y, z)
        return None

    def _respawn_cell(self) -> Pos:
        """The start point, on top of anything built over it. If the start column has been dug
        out, the nearest cell that stands on a block no more than one cell below the start height,
        so a death never puts the agent back at the bottom of its own shaft."""
        sx, sy, sz = self.spawn
        y = sy
        while y + 1 < self.sy - 1 and not (AGENT_PASS[self.bid(sx, y, sz)] and AGENT_PASS[self.bid(sx, y + 1, sz)]):
            y += 1
        cell = self.settle((sx, y, sz))[0]
        if cell[1] >= sy - 1:
            return cell
        for r in range(1, max(self.sx, self.sz)):
            for x in range(sx - r, sx + r + 1):
                for z in range(sz - r, sz + r + 1):
                    if max(abs(x - sx), abs(z - sz)) != r or not (0 <= x < self.sx and 0 <= z < self.sz):
                        continue
                    for y in range(max(1, sy - 1), self.sy - 1):     # lowest dry standing spot from there up
                        if (self.bid(x, y, z) != WATER and AGENT_PASS[self.bid(x, y, z)]
                                and AGENT_PASS[self.bid(x, y + 1, z)] and SUPPORT[self.bid(x, y - 1, z)]):
                            return (x, y, z)
        return cell

    # ---------------------------------------------------------------- stuck

    def trapped(self) -> bool:
        """True when nothing the agent can do will change its surroundings again: it holds nothing
        it could place or craft with, and from every cell it can walk or swim to, no block within
        reach breaks with the tools it has. Creatures are ignored. Searches at most 256 cells."""
        uses = {k for r in self.recipes for k, _ in r.inputs} | set(defs.FUELS)
        if any(i in defs.PLACEABLE or i in uses for i in self.inv):
            return False
        r = self.cfg.reach
        start = tuple(self.pos)
        seen, todo = {start}, [start]
        while todo:
            x0, y0, z0 = todo.pop()
            for y in range(max(0, y0 - r), min(self.sy, y0 + r + 1)):
                for z in range(max(0, z0 - r), min(self.sz, z0 + r + 1)):
                    for x in range(max(0, x0 - r), min(self.sx, x0 + r + 1)):
                        b = self.bid(x, y, z)
                        if b != AIR and self.mine_steps(BLOCKS[b]) is not None and self.exposed(x, y, z):
                            return False
            for d in DIRS:
                tgt = self.step_target((x0, y0, z0), d)
                if tgt is None:
                    continue
                nxt = self.settle(tgt)[0]
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
            if len(seen) > 256:
                return False
        return True

    def _check_stuck(self) -> None:
        """Log a stuck event when the agent becomes trapped, and end the run if on_stuck says so."""
        if self.done:
            return
        now = self.trapped()
        if now and not self.stuck:
            self._event("stuck", {"pos": list(self.pos)})
            if self.cfg.on_stuck == "end_run" and not self.multi:
                self.done = True
        self.stuck = now

    # -------------------------------------------------------------- actions

    def step(self, action: dict) -> StepResult:
        """Apply one action. Always uses at least one world step."""
        if self.done:
            return StepResult(T.NOTHING, 0, False, None)
        self._deltas, self._events = [], []
        self._hurt, self._died = False, None
        self._hits = []
        self._death_notice = None
        if self._notice_shown:
            self._notice, self._notice_shown = None, False
        t0 = self.t
        text, valid, desc = self._run(self.activity(action))
        if self.t == t0:
            self._tick()
        self._check_stuck()
        text += "".join(self._hits)
        self.last_action, self.last_result = desc, text
        return StepResult(text, self.t - t0, valid, self._died, self._deltas, self._events)

    def activity(self, action):
        """The action as a generator: it yields once per world step it needs and returns
        (result text, valid, description). Nothing happens until it is stepped."""
        name = action.get("name") if isinstance(action, dict) else None
        handler = {"move": self._move, "mine": self._mine, "place": self._place, "craft": self._craft,
                   "eat": self._eat, "attack": self._attack, "wait": self._wait,
                   "store": self._store, "take": self._take_from, "drop": self._drop,
                   "jump": self._jump, "sleep": self._sleep, "say": self._say, "give": self._give,
                   }.get(name if isinstance(name, str) else "")
        return handler(action) if handler else self._unknown(name)

    def _unknown(self, name):
        return T.UNKNOWN_ACTION, False, _clean(name) or "none"
        yield                                         # never reached: makes this a generator

    def _run(self, activity) -> tuple[str, bool, str]:
        """Drive an action to its end in a world of its own: one world tick at each yield.
        (The multi-agent engine instead steps every body's activity once per shared tick.)"""
        try:
            while True:
                next(activity)
                self._tick()
        except StopIteration as e:
            return e.value

    def _stop(self) -> bool:
        return self._hurt or self._died is not None or self.done

    def _move(self, a: dict):
        d, n = a.get("dir"), _int(a.get("steps", 1))
        desc = f"move {_clean(d)} {_clean(a.get('steps', 1))}"
        if d not in DIRS or n is None or not 1 <= n <= 8:
            return T.BAD_ARGS, False, desc
        seen = {c["id"] for c in self.visible_creatures()}
        self.me.heading = d
        try:
            text = yield from self._walk(d, n, seen)
        finally:
            self.me.heading = None
        return text, True, desc

    def _walk(self, d: str, n: int, seen: set):
        moved, blocked = 0, ""
        for _ in range(n):
            before = list(self.pos)
            if not self._move_once(d) and d not in ("up", "down"):
                blocked = self._blockers(d)                   # read before the tick moves creatures
            yield
            ok = self.pos != before
            if ok:
                blocked = ""                                  # moved after all: swapped with an agent
            moved += ok
            if not ok or self._stop():
                break
            now = {c["id"] for c in self.visible_creatures()}
            if now - seen:
                break
            seen |= now
        if moved == 0:
            x, y, z = self.pos
            if d in ("up", "down") and self.bid(x, y, z) != WATER and not (d == "down" and self.bid(x, y - 1, z) == WATER):
                return T.NOT_MOVED_DRY
            return T.NOT_MOVED + blocked
        return T.MOVED.format(n=moved, cells="cell" if moved == 1 else "cells", dir=d) + blocked

    def _blockers(self, d: str) -> str:
        """What stopped a sideways step, as " Blocked by ..." text, or "" at the world's edge.

        A level step needs the two cells ahead (feet and head) free. If the feet cell is solid,
        a step up needs the two cells above it and the cell above the head free instead.
        """
        x, y, z = self.pos
        dx, _, dz = DIRS[d]
        nx, nz = x + dx, z + dz
        if not (0 <= nx < self.sx and 0 <= nz < self.sz):
            return ""
        if AGENT_PASS[self.bid(nx, y, nz)]:
            cells = [(nx, y + 1, nz)]
        else:
            cells = [(nx, y, nz), (nx, y + 1, nz), (nx, y + 2, nz), (x, y + 2, z)]
            if not AGENT_PASS[self.bid(nx, y + 1, nz)]:
                cells = cells[:2]                             # both cells ahead are solid: a wall
        things = [T.BLOCKED_CELL.format(name=self.dn(self.block(*p)), x=p[0], y=p[1], z=p[2])
                  for p in cells if self.inb(*p) and not AGENT_PASS[self.bid(*p)]]
        if not things:                                        # the cells are free: a creature is in the way
            tgt = self.step_target(self.pos, d)
            things = [T.BLOCKED_CREATURE.format(kind=self.dn(c["kind"]), id=c["id"]) for c in self.creatures + self.others()
                      if tgt and c["pos"][0] == tgt[0] and c["pos"][2] == tgt[2] and c["pos"][1] in (tgt[1], tgt[1] + 1)]
        return T.BLOCKED_BY.format(things=" and ".join(things)) if things else ""

    def _xyz(self, a: dict) -> Pos | None:
        p = tuple(_int(a.get(k)) for k in "xyz")
        return None if None in p else p  # type: ignore[return-value]

    def _mine(self, a: dict):
        p = self._xyz(a)
        if p is None:
            return T.BAD_ARGS, False, "mine"
        desc = "mine ({}, {}, {})".format(*p)
        if not self.inb(*p) or cheb(p, self.pos) > self.cfg.reach:
            return T.TOO_FAR, False, desc
        block = self.block(*p)
        if block == "air":
            return T.NOTHING_THERE, False, desc
        n = self.mine_steps(block)
        if n is None or not self.exposed(*p):
            yield
            return T.NOT_BROKEN, True, desc
        if self.chests.get(tuple(p)):
            yield
            return T.CHEST_NOT_EMPTY.format(chest=self.dn("chest")), True, desc
        item = defs.DROPS.get(block, block)
        count = {"berry bush": self.cfg.berries_per_bush, "wheat": self.cfg.farming.wheat_per_crop}.get(block, 1)
        if not self._fits({item: count}):
            yield
            return T.NO_ROOM, True, desc
        for k in range(n):
            if k == n - 1:
                break
            yield
            if self._stop():
                return T.NOT_BROKEN, True, desc
        self.set_block(*p, "air")
        if block == "door":                           # the other half of a two-high door goes too
            for dy in (1, -1):
                q = (p[0], p[1] + dy, p[2])
                if self.inb(*q) and self.bid(*q) == defs.DOOR:
                    self.set_block(*q, "air")
                    break
        self.chests.pop(tuple(p), None)
        self.crops.pop(tuple(p), None)
        if tuple(p) == self.bed:
            self.bed = None
        self._add(item, count)
        if block == "berry bush":
            self.regrow.append([self.t + 1 + self.cfg.bush_regrow, *p])
        self._first("mine", block, "block")
        text = T.GOT.format(n=count, item=self.dn(item))
        seeds = self._seed_drop(block)
        if seeds:
            got = next((m for m in range(seeds, 0, -1) if self._fits({"seeds": m})), 0)
            if got:
                self._add("seeds", got)
                text += " " + T.GOT.format(n=got, item=self.dn("seeds"))
            if got < seeds:
                text += T.NO_ROOM_FOR.format(n=seeds - got, item=self.dn("seeds"))
        pick = self._best_pick()
        if pick and self._wear(pick):
            text += T.TOOL_BROKE.format(tool=self.dn(pick))
        yield
        return text, True, desc

    def _seed_drop(self, block: str) -> int:
        """Seeds that come with a broken block, besides the block's own item."""
        f = self.cfg.farming
        if block == "grass":
            return int(self._farm_rng.random() < f.seed_chance)
        if block == "wheat":
            return f.seeds_per_crop + int(self._farm_rng.random() < f.seed_bonus_chance)
        return 0

    def _water_near(self, p: Pos) -> bool:
        r = self.cfg.farming.water_dist
        if r <= 0:
            return True
        x, y, z = p                                   # p is the planted cell; the soil is at y - 1
        box = self.blocks[max(0, y - 3):y, max(0, z - r):z + r + 1, max(0, x - r):x + r + 1]
        return bool((box == WATER).any())

    def _plant(self, item: str, p: Pos, desc: str):
        """Seeds go into an empty cell with soil under it and water near the soil."""
        x, y, z = p
        if self.bid(*p) != AIR:
            return T.NOT_EMPTY, False, desc
        if self.bid(x, y - 1, z) not in (ID[s] for s in defs.SOIL) or not self._water_near(p):
            if not self.cfg.rule_notes:
                return T.NOT_PLACED.format(item=self.dn(item)), True, desc
            soil = " or ".join(self.dn(s) for s in defs.SOIL)
            return T.NOT_PLANTED.format(item=self.dn(item), soil=soil, water=self.dn("water"),
                                        r=self.cfg.farming.water_dist), True, desc
        self.set_block(*p, defs.PLANTS[item])
        self.crops[tuple(p)] = 0
        self.placed.append([defs.PLANTS[item], [x, y, z]])
        self._take(item, 1)
        self._first("place", item, "block")
        yield
        return T.PLACED.format(item=self.dn(item), x=x, y=y, z=z), True, desc

    def _place(self, a: dict):
        p = self._xyz(a)
        if p is None or not isinstance(a.get("item"), str):
            return T.BAD_ARGS, False, "place"
        desc = "place {} ({}, {}, {})".format(_clean(a["item"]), *p)
        item = self.internal(a["item"])
        if item is None or self.inv.get(item, 0) < 1:
            return T.NO_ITEM, False, desc
        if item not in defs.PLACEABLE and item not in defs.PLANTS:
            return T.NOT_PLACED.format(item=self.dn(item)), False, desc
        if not self.inb(*p) or cheb(p, self.pos) > self.cfg.reach:
            return T.TOO_FAR, False, desc
        if self._agent_in(*p):
            return T.IN_YOUR_CELL, False, desc
        if self.bid(*p) not in (AIR, WATER) or self._occupied(*p):
            under = self.block(*p)
            if item in defs.PLANTS and self.cfg.rule_notes and under in defs.SOIL:   # aimed at the soil itself
                return T.NOT_EMPTY_SOIL.format(x=p[0], y=p[1], z=p[2], y1=p[1] + 1, block=self.dn(under),
                                               item=self.dn(item)), False, desc
            return T.NOT_EMPTY, False, desc
        if item in defs.PLANTS:
            return (yield from self._plant(item, p, desc))
        self.set_block(*p, item)
        if item == "chest":
            self.chests[tuple(p)] = {}
        if item == "door":                            # a doorway is two cells high, like an agent
            up = (p[0], p[1] + 1, p[2])
            if self.inb(*up) and self.bid(*up) in (AIR, WATER) and not self._occupied(*up) and not self._agent_in(*up):
                self.set_block(*up, "door")
        if item in STRUCTURES:
            self.placed.append([item, list(p)])
        self._take(item, 1)
        self._first("place", item, "block")
        yield
        return T.PLACED.format(item=self.dn(item), x=p[0], y=p[1], z=p[2]), True, desc

    def _craft(self, a: dict):
        raw = a.get("items")
        if not isinstance(raw, dict) or not raw:
            return T.BAD_ARGS, False, "craft"
        desc = "craft " + ", ".join(f"{_clean(k)} x{_clean(v, 6)}" for k, v in raw.items())
        items: dict[str, int] = {}
        for k, v in raw.items():
            n = _int(v)
            if n is None or n < 1:
                return T.BAD_ARGS, False, desc
            item = self.internal(k)
            if item is None or self.inv.get(item, 0) < 1:
                return T.NO_ITEM, False, desc
            items[item] = items.get(item, 0) + n
        for item, n in items.items():
            if self.inv[item] < n:
                return T.NOT_ENOUGH.format(item=self.dn(item)), False, desc
        r = self.match_recipe(items)
        if r is None or not self.station_near(r.station):
            self._event("craft_fail", {"items": items})
            yield
            if not self.cfg.rule_notes:
                return T.NOT_MADE, True, desc
            if r is None:
                return T.NOT_MADE_EXACT, True, desc
            return T.NOT_MADE_STATION.format(station=self.dn(r.station), r=self.cfg.station_reach), True, desc
        if not self._fits({r.output: r.count}, items):
            yield
            return T.NO_ROOM, True, desc
        for item, n in items.items():
            self._take(item, n)
        self._add(r.output, r.count)
        self.made.setdefault(r.output, (dict(items), r.count))
        self._first("craft", r.output, "item")
        yield
        return T.MADE.format(n=r.count, item=self.dn(r.output)), True, desc

    def _eat(self, a: dict):
        desc = f"eat {_clean(a.get('item'))}"
        item = self.internal(a.get("item"))
        if item is None or self.inv.get(item, 0) < 1:
            return T.NO_ITEM, False, desc
        if item not in self.cfg.food:
            yield
            return T.NOT_EATEN.format(item=self.dn(item)), True, desc
        self._take(item, 1)
        self.food = min(self.cfg.vitals.max_food, self.food + self.cfg.food[item])
        self._first("eat", item, "item")
        yield
        return T.ATE.format(item=self.dn(item)), True, desc

    def _attack(self, a: dict):
        cid = _int(a.get("id"))
        if cid is None:
            return T.BAD_ARGS, False, "attack"
        desc = f"attack #{cid}"
        c = next((k for k in self.creatures if k["id"] == cid), None)
        target = self.body(cid) if c is None else None
        if target is not None and target is not self.me and target.alive:
            if cheb(target.pos, self.pos) > self.cfg.attack_reach:
                return T.NO_CREATURE.format(id=cid), False, desc
            sword = self._best_sword()
            self._strikes.append((target, self.cfg.sword_damage[sword] if sword else self.cfg.hand_damage, self.me))
            text = T.HIT.format(kind=self.dn("agent"), id=cid)
            if sword and self._wear(sword):
                text += T.TOOL_BROKE.format(tool=self.dn(sword))
            yield
            return text, True, desc
        if c is None or cheb(c["pos"], self.pos) > self.cfg.attack_reach:
            return T.NO_CREATURE.format(id=cid), False, desc
        sword = self._best_sword()
        c["hp"] -= self.cfg.sword_damage[sword] if sword else self.cfg.hand_damage
        kind = self.dn(c["kind"])
        if c["hp"] > 0:
            text = T.HIT.format(kind=kind, id=cid)
        else:
            self.creatures.remove(c)
            self._event("kill", {"kind": c["kind"], "id": cid})
            text = T.HIT_GONE.format(kind=kind, id=cid)
            meat = self.cfg.creatures.meat[c["kind"]]
            got = next((m for m in range(meat, 0, -1) if self._fits({"raw meat": m})), 0)
            if got:
                self._add("raw meat", got)
                text += " " + T.GOT.format(n=got, item=self.dn("raw meat"))
            if got < meat:
                text += T.NO_ROOM_FOR.format(n=meat - got, item=self.dn("raw meat"))
            wool = self.cfg.creatures.wool.get(c["kind"], 0)
            got = next((m for m in range(wool, 0, -1) if self._fits({"wool": m})), 0)
            if got:
                self._add("wool", got)
                text += " " + T.GOT.format(n=got, item=self.dn("wool"))
            if got < wool:
                text += T.NO_ROOM_FOR.format(n=wool - got, item=self.dn("wool"))
        if sword and self._wear(sword):
            text += T.TOOL_BROKE.format(tool=self.dn(sword))
        yield
        return text, True, desc

    def _items_arg(self, raw) -> dict[str, int] | None:
        """{shown name: count} to {familiar name: count}. None if malformed or a name is unknown."""
        if not isinstance(raw, dict) or not raw:
            return None
        items: dict[str, int] = {}
        for k, v in raw.items():
            n, item = _int(v), self.internal(k)
            if n is None or n < 1 or item is None:
                return None
            items[item] = items.get(item, 0) + n
        return items

    def _items_text(self, items: dict[str, int]) -> str:
        return ", ".join(T.OBS_COUNT.format(name=self.dn(i), c=n) for i, n in items.items())

    def _have(self, items: dict[str, int]) -> str | None:
        """Error text if the inventory lacks any of these, else None."""
        for item, n in items.items():
            if self.inv.get(item, 0) < 1:
                return T.NO_ITEM
            if self.inv[item] < n:
                return T.NOT_ENOUGH.format(item=self.dn(item))
        return None

    def _chest_arg(self, a: dict, verb: str):
        """(cell, items, desc, error). error is (text, valid) when the action cannot go ahead."""
        p, items = self._xyz(a), self._items_arg(a.get("items"))
        if p is None or items is None:
            return None, None, verb, (T.BAD_ARGS, False)
        desc = f"{verb} ({p[0]}, {p[1]}, {p[2]}) " + self._items_text(items)
        if not self.inb(*p) or cheb(p, self.pos) > self.cfg.reach:
            return p, items, desc, (T.TOO_FAR, False)
        if self.bid(*p) != defs.CHEST:
            return p, items, desc, (T.NO_CHEST.format(chest=self.dn("chest"), x=p[0], y=p[1], z=p[2]), False)
        return p, items, desc, None

    def _store(self, a: dict):
        p, items, desc, err = self._chest_arg(a, "store")
        if err is None:
            missing = self._have(items)
            err = (missing, False) if missing else None
        if err:
            return err[0], err[1], desc
        tool = next((i for i in items if i in defs.TOOLS), None)
        chest = self.chests.setdefault(tuple(p), {})
        # Keep the chest's order, new kinds after (a set here would order by string hash, which
        # changes from process to process and breaks determinism).
        after = dict(chest)
        for i, n in items.items():
            after[i] = after.get(i, 0) + n
        if tool:
            text = T.NOT_STORED.format(item=self.dn(tool))
        elif self.slots(after) > self.cfg.chest_slots:
            text = T.CHEST_FULL.format(chest=self.dn("chest"))
        else:
            for i, n in items.items():
                self._take(i, n)
            chest.clear()
            chest.update(after)
            text = T.STORED.format(items=self._items_text(items))
        yield
        return text, True, desc

    def _take_from(self, a: dict):
        p, items, desc, err = self._chest_arg(a, "take")
        if err:
            return err[0], err[1], desc
        chest = self.chests.setdefault(tuple(p), {})
        short = next((i for i, n in items.items() if chest.get(i, 0) < n), None)
        if short:
            text = T.NOT_IN_CHEST.format(item=self.dn(short), chest=self.dn("chest"))
        elif not self._fits(items):
            text = T.NO_ROOM
        else:
            for i, n in items.items():
                chest[i] -= n
                if chest[i] == 0:
                    del chest[i]
                self._add(i, n)
            text = T.TOOK.format(items=self._items_text(items))
        yield
        return text, True, desc

    def _drop(self, a: dict):
        items = self._items_arg(a.get("items"))
        if items is None:
            return T.BAD_ARGS, False, "drop"
        desc = "drop " + self._items_text(items)
        missing = self._have(items)
        if missing:
            return missing, False, desc
        for i, n in items.items():
            self._take(i, n)
        yield
        return T.DROPPED.format(items=self._items_text(items)), True, desc

    def _jump(self, a: dict):
        """Up one cell and the item into the cell the feet left, so the agent stands on it.
        Needs the cell above the head free and an item that can be stood on."""
        if not isinstance(a.get("item"), str):
            return T.BAD_ARGS, False, "jump"
        desc = "jump " + _clean(a["item"])
        item = self.internal(a["item"])
        if item is None or self.inv.get(item, 0) < 1:
            return T.NO_ITEM, False, desc
        if item not in defs.PLACEABLE or not SUPPORT[ID[item]]:
            return T.NOT_PLACED.format(item=self.dn(item)), False, desc
        x, y, z = self.pos
        top = (x, y + 2, z)
        if not self.inb(*top):
            return T.NOT_MOVED, True, desc
        if not AGENT_PASS[self.bid(*top)]:
            return T.NOT_MOVED + T.BLOCKED_BY.format(things=T.BLOCKED_CELL.format(
                name=self.dn(self.block(*top)), x=top[0], y=top[1], z=top[2])), True, desc
        blockers = [c for c in self.creatures + self.others()
                    if c["pos"][0] == x and c["pos"][2] == z and c["pos"][1] in (y + 1, y + 2)]
        if blockers:
            return T.NOT_MOVED + T.BLOCKED_BY.format(things=", ".join(
                T.BLOCKED_CREATURE.format(kind=self.dn(c["kind"]), id=c["id"]) for c in blockers)), True, desc
        self.pos = [x, y + 1, z]
        self.set_block(x, y, z, item)
        if item == "chest":
            self.chests[(x, y, z)] = {}
        if item in STRUCTURES:
            self.placed.append([item, [x, y, z]])
        self._take(item, 1)
        self._first("place", item, "block")
        yield
        return T.JUMPED.format(item=self.dn(item), x=x, y=y, z=z), True, desc

    def _say(self, a: dict):
        """Words to every other agent within hear_radius, in their next observation."""
        raw = a.get("text")
        if not isinstance(raw, str) or not " ".join(raw.split()):
            return T.BAD_ARGS, False, "say"
        text = " ".join(raw.split())[:self.cfg.say_max_chars].replace('"', "'")
        desc = f'say "{text[:40]}"'
        x, y, z = self.pos
        heard = [b for b in self.bodies if b is not self.me and b.alive and cheb(b.pos, self.pos) <= self.cfg.hear_radius]
        for b in heard:
            b.heard.append(T.OBS_SAID.format(id=self.me.id, x=x, y=y, z=z, text=text))
        self._event("say", {"text": text, "heard": [b.id for b in heard]})
        who = ", ".join(T.AGENT_REF.format(id=b.id) for b in heard)
        yield
        return T.SAID.format(text=text) + (T.HEARD_BY.format(who=who) if heard else T.HEARD_BY_NONE), True, desc

    def _give(self, a: dict):
        """Items from this inventory into another agent's, if it is within reach and they fit."""
        cid, items = _int(a.get("id")), self._items_arg(a.get("items"))
        if cid is None or items is None:
            return T.BAD_ARGS, False, "give"
        desc = f"give agent #{cid} " + self._items_text(items)
        target = self.body(cid)
        if target is None or target is self.me or not target.alive or cheb(target.pos, self.pos) > self.cfg.reach:
            return T.NO_AGENT.format(id=cid, r=self.cfg.reach), False, desc
        missing = self._have(items)
        if missing:
            return missing, False, desc
        me = self.me
        self.me = target
        fits = self._fits(items)
        self.me = me
        if not fits:
            yield
            return T.NO_ROOM_THEIRS.format(id=cid), True, desc
        uses = {i: self.tools[i] for i in items if i in self.tools}
        for i, n in items.items():
            self._take(i, n)
            self.me = target
            had = i in self.tools
            self._add(i, n)
            if i in uses and not had:
                self.tools[i] = uses[i]               # the tool keeps its wear
            self.me = me
        x, y, z = self.pos
        target.heard.append(T.OBS_GIVEN.format(id=me.id, x=x, y=y, z=z, items=self._items_text(items)))
        self._event("give", {"to": cid, "items": items})
        yield
        return T.GAVE.format(items=self._items_text(items), id=cid), True, desc

    def _wait(self, a: dict):
        n = _int(a.get("steps", 1))
        desc = f"wait {_clean(a.get('steps', 1))}"
        if n is None or not 1 <= n <= 8:
            return T.BAD_ARGS, False, desc
        done = 0
        for _ in range(n):
            yield
            done += 1
            if self._stop():
                break
        return T.WAITED.format(n=done, steps="step" if done == 1 else "steps"), True, desc

    def _sleep(self, a: dict):
        """With a bed within reach, from dusk to dawn and no zombie near: the world runs on until
        dawn, or until the agent is hurt. The bed becomes the respawn point. Asleep with food
        above 0, health rises every sleep_heal_every steps."""
        desc = "sleep"
        r = self.cfg.reach
        x, y, z = self.pos
        box = self.blocks[max(0, y - r):y + r + 1, max(0, z - r):z + r + 1, max(0, x - r):x + r + 1]
        beds = [(int(bx) + max(0, x - r), int(by) + max(0, y - r), int(bz) + max(0, z - r))
                for by, bz, bx in np.argwhere(box == defs.BED)]
        if not beds:
            return T.NO_BED.format(bed=self.dn("bed"), r=r), False, desc
        bed = min(beds, key=lambda b: (cheb(b, self.pos), b))
        if self._sky_level(weather=False) == 2:
            return T.NOT_SLEPT_SKY, True, desc
        near = sorted((c for c in self.creatures if c["kind"] == "zombie"
                       and cheb(c["pos"], self.pos) <= self.cfg.sleep_zombie_dist),
                      key=lambda c: (cheb(c["pos"], self.pos), c["id"]))
        if near:
            c = near[0]
            return T.NOT_SLEPT_CREATURE.format(kind=self.dn("zombie").capitalize(), id=c["id"],
                                               x=c["pos"][0], y=c["pos"][1], z=c["pos"][2]), True, desc
        self.bed = bed
        self._event("sleep", {"bed": list(bed)})
        self._asleep = True
        done = 0
        try:
            for _ in range(self.cfg.day_length):
                yield
                done += 1
                if self._stop() or self.t % self.cfg.day_length == 0:
                    break
        finally:
            self._asleep = False
        return T.SLEPT.format(n=done, steps="step" if done == 1 else "steps", bed=self.dn("bed"),
                              x=bed[0], y=bed[1], z=bed[2]), True, desc

    # ----------------------------------------------------- views of the state

    def observe(self) -> str:
        from .observe import render
        if self._notice is not None:
            self._notice_shown = True
        text = render(self)
        self.me.heard = []                            # shown once
        if self.multi:
            self._death_notice = None                 # (one agent's step() clears it before acting)
        return text

    def set_notice(self, text: str | None) -> None:
        """Extra line shown in the next observation, then dropped."""
        self._notice, self._notice_shown = text, False

    def _agent_dict(self, b: Body | None = None) -> dict:
        b = b or self.bodies[0]
        return {"pos": list(b.pos), "health": b.health, "food": b.food, "air": b.air,
                "inventory": dict(b.inv), "tools": dict(b.tools)}

    def _agents_list(self) -> list[dict]:
        """Multi-agent: every body, with its id, name and whether it is still in the world."""
        return [{"id": b.id, "name": b.name, "alive": b.alive, "bed": list(b.bed) if b.bed else None,
                 **self._agent_dict(b)} for b in self.bodies]

    def _creature_list(self) -> list[dict]:
        return [{"id": c["id"], "kind": c["kind"], "pos": list(c["pos"])} for c in self.creatures]

    def _delta(self) -> dict:
        blocks = [[x, y, z, name] for (x, y, z), name in self._changed.items()]
        self._changed = {}
        extra = {"agents": self._agents_list()} if self.multi else {}
        return {"type": "step", "t": self.t, "blocks": blocks, "agent": self._agent_dict(), **extra,
                "creatures": self._creature_list(), "chests": self._chest_list(), "light": self.light(), "day": self.day,
                "weather": self.weather, "bed": list(self.bed) if self.bed else None}

    def _chest_list(self) -> list[list]:
        return [[x, y, z, dict(items)] for (x, y, z), items in sorted(self.chests.items())]

    def snapshot(self) -> dict:
        return {"type": "snapshot", "t": self.t, "size": [self.sx, self.sy, self.sz],
                "sea_level": self.cfg.sea_level, "palette": list(BLOCKS),
                "blocks_b64": base64.b64encode(zlib.compress(self.blocks.tobytes())).decode("ascii"),
                "agent": self._agent_dict(), **({"agents": self._agents_list()} if self.multi else {}),
                "creatures": self._creature_list(), "chests": self._chest_list(),
                "light": self.light(), "day": self.day, "weather": self.weather,
                "bed": list(self.bed) if self.bed else None, "display_names": dict(self.display),
                "spawn": list(self.spawn)}

    def state_hash(self) -> str:
        state = {
            "t": self.t, "done": self.done, "stuck": self.stuck, "deaths": self.deaths, "agent": self._agent_dict(),
            "agents": [[b.id, b.alive, b.deaths, b.heard, b._food_tick, b._starve_tick, b._heal_tick, b._hail_tick,
                        b._last_hit, b.last_result, b.made, b.firsts, list(b.bed or ())] for b in self.bodies[1:]],
            "ticks": [self._food_tick, self._starve_tick, self._heal_tick, self._hail_tick, self._last_hit],
            "weather": self.weather, "crops": sorted([list(p), n] for p, n in self.crops.items()),
            "bed": self.bed, "rng2": [self._weather_rng.bit_generator.state, self._farm_rng.bit_generator.state],
            "creatures": self.creatures, "chests": self._chest_list(), "next_id": self._next_id, "regrow": self.regrow,
            "firsts": self.firsts, "made": self.made, "last": [self.last_action, self.last_result],
            "notice": [self._notice, self._death_notice], "rng": self.rng.bit_generator.state,
        }
        h = hashlib.sha256(self.blocks.tobytes())
        h.update(json.dumps(state, sort_keys=True).encode())
        return h.hexdigest()

    def valid_actions(self) -> list[dict]:
        """Actions that would not be rejected right now. For bots. Names are the shown names."""
        out: list[dict] = []
        for d in DIRS:
            if self.step_target(self.pos, d) is not None:
                out += [{"name": "move", "dir": d, "steps": n} for n in (1, 2, 4, 8)]
        r = self.cfg.reach
        x0, y0, z0 = self.pos
        for y in range(max(0, y0 - r), min(self.sy, y0 + r + 1)):
            for z in range(max(0, z0 - r), min(self.sz, z0 + r + 1)):
                for x in range(max(0, x0 - r), min(self.sx, x0 + r + 1)):
                    b = self.bid(x, y, z)
                    if b != AIR and self.mine_steps(BLOCKS[b]) is not None and self.exposed(x, y, z):
                        out.append({"name": "mine", "x": x, "y": y, "z": z})
        spots = [(x0 + dx, y0 + dy, z0 + dz) for dx, dy, dz in
                 [(1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (1, 1, 0), (-1, 1, 0), (0, 1, 1), (0, 1, -1), (0, 2, 0)]]
        spots = [p for p in spots if self.inb(*p) and self.bid(*p) in (AIR, WATER) and not self._occupied(*p)]
        head_room = self.inb(x0, y0 + 2, z0) and AGENT_PASS[self.bid(x0, y0 + 2, z0)] and not any(
            c["pos"][0] == x0 and c["pos"][2] == z0 and c["pos"][1] in (y0 + 1, y0 + 2) for c in self.creatures)
        for item in self.inv:
            if item in defs.PLACEABLE:
                out += [{"name": "place", "item": self.dn(item), "x": p[0], "y": p[1], "z": p[2]} for p in spots]
                if head_room and SUPPORT[ID[item]]:
                    out.append({"name": "jump", "item": self.dn(item)})
            if item in defs.PLANTS:
                out += [{"name": "place", "item": self.dn(item), "x": p[0], "y": p[1], "z": p[2]} for p in spots
                        if self.bid(*p) == AIR and self.bid(p[0], p[1] - 1, p[2]) in (ID[s] for s in defs.SOIL)
                        and self._water_near(p)]
            if item in self.cfg.food:
                out.append({"name": "eat", "item": self.dn(item)})
        for rcp in self.recipes:
            if not self.station_near(rcp.station):
                continue
            need = rcp.items()
            fuel = need.pop("fuel", 0)
            for f in (defs.FUELS if fuel else [None]):
                items = dict(need)
                if f:
                    items[f] = items.get(f, 0) + fuel
                if all(self.inv.get(i, 0) >= n for i, n in items.items()):
                    out.append({"name": "craft", "items": {self.dn(i): n for i, n in items.items()}})
        for c in self.creatures:
            if cheb(c["pos"], self.pos) <= self.cfg.attack_reach:
                out.append({"name": "attack", "id": c["id"]})
        r = self.cfg.reach
        if (self._sky_level(weather=False) < 2 and (self.blocks[max(0, y0 - r):y0 + r + 1, max(0, z0 - r):z0 + r + 1,
                                                                max(0, x0 - r):x0 + r + 1] == defs.BED).any()):
            out.append({"name": "sleep"})
        out += [{"name": "wait", "steps": n} for n in (1, 4, 8)]
        return out


forward_body_fields(World)
