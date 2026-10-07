"""The world: state, the seven actions, creatures, vitals, day and night, death."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import zlib
from dataclasses import dataclass, field

import numpy as np

from . import defs, text as T
from .config import WorldConfig
from .defs import AGENT_PASS, AIR, BLOCKS, CREATURE_PASS, DIRS, ID, SUPPORT, TORCH, WATER
from .names import build_display_names
from .recipes import Recipe, build_recipes
from .terrain import generate

Pos = tuple[int, int, int]
LIGHTS = ["dark", "dim", "bright"]
_NEIGHBOURS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]


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
        self.pos: list[int] = list(self.spawn)
        self.inv: dict[str, int] = {}
        self.tools: dict[str, int] = {}                  # tool name -> uses left on the one in use
        self._reset_vitals()
        self.creatures: list[dict] = []
        self._next_id = 1
        for kind, pos in start:
            self._spawn(kind, pos)
        self.regrow: list[list[int]] = []                # [t_due, x, y, z]
        self.firsts: dict[str, list[str]] = {"mine": [], "craft": [], "place": [], "eat": []}
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
        return any(c["pos"][0] == x and c["pos"][1] == y and c["pos"][2] == z for c in self.creatures)

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
        tgt = self.step_target(self.pos, d)
        if tgt is None or self._occupied(*tgt) or self._occupied(tgt[0], tgt[1] + 1, tgt[2]):
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
        ax, ay, az = self.pos
        if (nx, nz) == (ax, az) and ny in (ay, ay + 1):
            return None
        if self._occupied(nx, ny, nz):
            return None
        return (nx, ny, nz)

    def _creatures_tick(self, tod: int) -> None:
        cc = self.cfg.creatures
        ax, ay, az = self.pos
        for c in self.creatures:                              # list order is id order
            x, y, z = c["pos"]
            while y > 0 and CREATURE_PASS[self.bid(x, y - 1, z)]:
                y -= 1                                        # the ground under it was removed
            c["pos"][1] = y
            d = None
            if c["kind"] == "zombie":
                if self.t % cc.zombie_move_every:
                    continue
                if cheb(c["pos"], self.pos) <= cc.zombie_chase_dist:
                    ddx, ddz = ax - x, az - z
                    east = ("east" if ddx > 0 else "west", ddx)
                    south = ("south" if ddz > 0 else "north", ddz)
                    pair = (east, south) if abs(ddx) >= abs(ddz) else (south, east)
                    order = [name for name, dd in pair if dd]
                    for o in order:
                        tgt = self._creature_target(c, o)
                        if tgt:
                            c["pos"] = list(tgt)
                            break
                    continue
                if self.rng.random() < 0.5:
                    d = defs.HORIZONTAL[int(self.rng.integers(4))]
            elif self.rng.random() < cc.passive_move_prob:
                d = defs.HORIZONTAL[int(self.rng.integers(4))]
            if d:
                tgt = self._creature_target(c, d)
                if tgt:
                    c["pos"] = list(tgt)

        night = tod >= self.cfg.night_start
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
                if any(cheb((x, y, z), tp) <= cc.torch_no_spawn for tp in torches):
                    continue
                self._spawn("zombie", (x, y, z))
                break

        if self.health > 0 and self.t - self._last_hit >= cc.zombie_cooldown:
            for c in self.creatures:
                if c["kind"] != "zombie":
                    continue
                x, y, z = c["pos"]
                beside = abs(x - ax) + abs(z - az) == 1 and y in (ay, ay + 1)
                above = (x, z) == (ax, az) and y == ay + 2
                if beside or above:
                    self._damage(cc.zombie_damage, "zombie")
                    self._last_hit = self.t
                    break

    def visible_creatures(self) -> list[dict]:
        from .observe import visible_creatures
        return visible_creatures(self)

    # --------------------------------------------------------------- vitals

    def _reset_vitals(self) -> None:
        v = self.cfg.vitals
        self.health, self.food, self.air = v.max_health, v.max_food, v.max_air
        self._food_tick = self._starve_tick = self._heal_tick = 0

    def vitals(self) -> dict:
        return {"health": self.health, "food": self.food, "air": self.air}

    def _damage(self, n: int, cause: str) -> None:
        if self.health <= 0:
            return
        self.health = max(0, self.health - n)
        self._hurt = True
        self._cause = cause
        self._event("hurt", {"cause": cause, "amount": n})

    def _vitals_tick(self) -> None:
        v = self.cfg.vitals
        self._food_tick += 1
        if self._food_tick >= v.food_drop_every:
            self._food_tick = 0
            self.food = max(0, self.food - 1)
        if self.food == 0:
            self._starve_tick += 1
            if self._starve_tick >= v.starve_every:
                self._starve_tick = 0
                self._damage(1, "hunger")
        else:
            self._starve_tick = 0
        if self.food >= v.heal_food_min and self.health < v.max_health:
            self._heal_tick += 1
            if self._heal_tick >= v.heal_every:
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

    def light(self) -> str:
        c = self.cfg
        tod = self.t % c.day_length
        if tod < c.night_start - c.dim_steps:
            level = 2
        elif tod < c.night_start or tod >= c.day_length - c.dim_steps:
            level = 1
        else:
            level = 0
        x, y, z = self.pos
        if y + 2 < self.sy and any(SUPPORT[int(b)] and b != ID["leaves"] for b in self.blocks[y + 2:, z, x]):
            level = max(0, level - 1)
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
        if tod == 0:
            self.creatures = [k for k in self.creatures if k["kind"] != "zombie"]
            self._event("day_start", {"day": self.day})
            self._respawn_passives()
        elif tod == c.night_start:
            self._event("night_start", {"day": self.day})
        for due in [r for r in self.regrow if r[0] <= self.t]:
            _, x, y, z = due
            if self.bid(x, y, z) == AIR and not self._occupied(x, y, z) and not self._agent_in(x, y, z):
                self.set_block(x, y, z, "berry bush")
                self.regrow.remove(due)
            else:
                due[0] = self.t + 10

        pos, fell = self.settle(self.pos)
        self.pos = list(pos)
        if fell > c.vitals.fall_safe and self.bid(*pos) != WATER:
            self._damage(fell - c.vitals.fall_safe, "fall")
        self._vitals_tick()
        self._creatures_tick(tod)
        if self.health <= 0:
            self._die()
        self._deltas.append(self._delta())

    def _agent_in(self, x: int, y: int, z: int) -> bool:
        ax, ay, az = self.pos
        return (x, z) == (ax, az) and y in (ay, ay + 1)

    def _respawn_passives(self) -> None:
        cc = self.cfg.creatures
        for kind in defs.PASSIVE:
            n = sum(k["kind"] == kind for k in self.creatures)
            for _ in range(min(cc.passive_respawn, cc.passive_max - n)):
                for _ in range(20):
                    x, z = int(self.rng.integers(3, self.sx - 3)), int(self.rng.integers(3, self.sz - 3))
                    y = self._surface(x, z)
                    if (y is not None and self.bid(x, y - 1, z) == ID["grass"] and not self._occupied(x, y, z)
                            and not self._agent_in(x, y, z)):
                        self._spawn(kind, (x, y, z))
                        break

    def _die(self) -> None:
        cause = self._cause
        self._died = cause
        self.deaths += 1
        self._event("death", {"cause": cause, "pos": list(self.pos)})
        if self.cfg.on_death == "end_run":
            self.done = True
            self._death_notice = T.DIED_END.format(cause=cause)
            return
        x, y, z = self.spawn
        while y + 1 < self.sy - 1 and not (AGENT_PASS[self.bid(x, y, z)] and AGENT_PASS[self.bid(x, y + 1, z)]):
            y += 1
        self.pos = list(self.settle((x, y, z))[0])
        self.inv, self.tools = {}, {}
        self._reset_vitals()
        self._death_notice = T.DIED_RESPAWN.format(cause=cause)
        self._event("respawn", {"pos": list(self.pos)})

    # -------------------------------------------------------------- actions

    def step(self, action: dict) -> StepResult:
        """Apply one action. Always uses at least one world step."""
        if self.done:
            return StepResult(T.NOTHING, 0, False, None)
        self._deltas, self._events = [], []
        self._hurt, self._died = False, None
        self._death_notice = None
        if self._notice_shown:
            self._notice, self._notice_shown = None, False
        t0 = self.t
        name = action.get("name") if isinstance(action, dict) else None
        handler = {"move": self._move, "mine": self._mine, "place": self._place, "craft": self._craft,
                   "eat": self._eat, "attack": self._attack, "wait": self._wait}.get(name if isinstance(name, str) else "")
        if handler is None:
            text, valid, desc = T.UNKNOWN_ACTION, False, _clean(name) or "none"
        else:
            text, valid, desc = handler(action)
        if self.t == t0:
            self._tick()
        self.last_action, self.last_result = desc, text
        return StepResult(text, self.t - t0, valid, self._died, self._deltas, self._events)

    def _stop(self) -> bool:
        return self._hurt or self._died is not None or self.done

    def _move(self, a: dict):
        d, n = a.get("dir"), _int(a.get("steps", 1))
        desc = f"move {_clean(d)} {_clean(a.get('steps', 1))}"
        if d not in DIRS or n is None or not 1 <= n <= 8:
            return T.BAD_ARGS, False, desc
        seen = {c["id"] for c in self.visible_creatures()}
        moved = 0
        for _ in range(n):
            before = list(self.pos)
            self._move_once(d)
            self._tick()
            ok = self.pos != before
            moved += ok
            if not ok or self._stop():
                break
            now = {c["id"] for c in self.visible_creatures()}
            if now - seen:
                break
            seen |= now
        if moved == 0:
            return T.NOT_MOVED, True, desc
        return T.MOVED.format(n=moved, cells="cell" if moved == 1 else "cells", dir=d), True, desc

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
            self._tick()
            return T.NOT_BROKEN, True, desc
        for k in range(n):
            if k == n - 1:
                break
            self._tick()
            if self._stop():
                return T.NOT_BROKEN, True, desc
        self.set_block(*p, "air")
        item = defs.DROPS.get(block, block)
        count = self.cfg.berries_per_bush if block == "berry bush" else 1
        self._add(item, count)
        if block == "berry bush":
            self.regrow.append([self.t + 1 + self.cfg.bush_regrow, *p])
        self._first("mine", block, "block")
        text = T.GOT.format(n=count, item=self.dn(item))
        pick = self._best_pick()
        if pick and self._wear(pick):
            text += T.TOOL_BROKE.format(tool=self.dn(pick))
        self._tick()
        return text, True, desc

    def _place(self, a: dict):
        p = self._xyz(a)
        if p is None or not isinstance(a.get("item"), str):
            return T.BAD_ARGS, False, "place"
        desc = "place {} ({}, {}, {})".format(_clean(a["item"]), *p)
        item = self.internal(a["item"])
        if item is None or self.inv.get(item, 0) < 1:
            return T.NO_ITEM, False, desc
        if item not in defs.PLACEABLE:
            return T.NOT_PLACED.format(item=self.dn(item)), False, desc
        if not self.inb(*p) or cheb(p, self.pos) > self.cfg.reach:
            return T.TOO_FAR, False, desc
        if self.bid(*p) not in (AIR, WATER) or self._agent_in(*p) or self._occupied(*p):
            return T.NOT_EMPTY, False, desc
        self.set_block(*p, item)
        self._take(item, 1)
        self._first("place", item, "block")
        self._tick()
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
            self._tick()
            return T.NOT_MADE, True, desc
        for item, n in items.items():
            self._take(item, n)
        self._add(r.output, r.count)
        self._first("craft", r.output, "item")
        self._tick()
        return T.MADE.format(n=r.count, item=self.dn(r.output)), True, desc

    def _eat(self, a: dict):
        desc = f"eat {_clean(a.get('item'))}"
        item = self.internal(a.get("item"))
        if item is None or self.inv.get(item, 0) < 1:
            return T.NO_ITEM, False, desc
        if item not in self.cfg.food:
            self._tick()
            return T.NOT_EATEN.format(item=self.dn(item)), True, desc
        self._take(item, 1)
        self.food = min(self.cfg.vitals.max_food, self.food + self.cfg.food[item])
        self._first("eat", item, "item")
        self._tick()
        return T.ATE.format(item=self.dn(item)), True, desc

    def _attack(self, a: dict):
        cid = _int(a.get("id"))
        if cid is None:
            return T.BAD_ARGS, False, "attack"
        desc = f"attack #{cid}"
        c = next((k for k in self.creatures if k["id"] == cid), None)
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
            if meat:
                self._add("raw meat", meat)
                text += " " + T.GOT.format(n=meat, item=self.dn("raw meat"))
        if sword and self._wear(sword):
            text += T.TOOL_BROKE.format(tool=self.dn(sword))
        self._tick()
        return text, True, desc

    def _wait(self, a: dict):
        n = _int(a.get("steps", 1))
        desc = f"wait {_clean(a.get('steps', 1))}"
        if n is None or not 1 <= n <= 8:
            return T.BAD_ARGS, False, desc
        done = 0
        for _ in range(n):
            self._tick()
            done += 1
            if self._stop():
                break
        return T.WAITED.format(n=done, steps="step" if done == 1 else "steps"), True, desc

    # ----------------------------------------------------- views of the state

    def observe(self) -> str:
        from .observe import render
        if self._notice is not None:
            self._notice_shown = True
        return render(self)

    def set_notice(self, text: str | None) -> None:
        """Extra line shown in the next observation, then dropped."""
        self._notice, self._notice_shown = text, False

    def _agent_dict(self) -> dict:
        return {"pos": list(self.pos), "health": self.health, "food": self.food, "air": self.air,
                "inventory": dict(self.inv), "tools": dict(self.tools)}

    def _creature_list(self) -> list[dict]:
        return [{"id": c["id"], "kind": c["kind"], "pos": list(c["pos"])} for c in self.creatures]

    def _delta(self) -> dict:
        blocks = [[x, y, z, name] for (x, y, z), name in self._changed.items()]
        self._changed = {}
        return {"type": "step", "t": self.t, "blocks": blocks, "agent": self._agent_dict(),
                "creatures": self._creature_list(), "light": self.light(), "day": self.day}

    def snapshot(self) -> dict:
        return {"type": "snapshot", "t": self.t, "size": [self.sx, self.sy, self.sz],
                "sea_level": self.cfg.sea_level, "palette": list(BLOCKS),
                "blocks_b64": base64.b64encode(zlib.compress(self.blocks.tobytes())).decode("ascii"),
                "agent": self._agent_dict(), "creatures": self._creature_list(),
                "light": self.light(), "day": self.day, "display_names": dict(self.display),
                "spawn": list(self.spawn)}

    def state_hash(self) -> str:
        state = {
            "t": self.t, "done": self.done, "deaths": self.deaths, "agent": self._agent_dict(),
            "ticks": [self._food_tick, self._starve_tick, self._heal_tick, self._last_hit],
            "creatures": self.creatures, "next_id": self._next_id, "regrow": self.regrow,
            "firsts": self.firsts, "last": [self.last_action, self.last_result],
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
        for item in self.inv:
            if item in defs.PLACEABLE:
                out += [{"name": "place", "item": self.dn(item), "x": p[0], "y": p[1], "z": p[2]} for p in spots]
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
        out += [{"name": "wait", "steps": n} for n in (1, 4, 8)]
        return out
