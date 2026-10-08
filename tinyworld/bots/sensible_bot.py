"""Baseline: a hand-coded bot. It gathers food, makes tools, and walls itself in at night.

It reads the world's internals directly (block grid, recipe table, creature list).
All names inside this file are familiar names. They are turned into shown names on the way out.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from tinyworld.sim import defs, text as T
from tinyworld.sim.recipes import reach_order
from tinyworld.sim.world import cheb

WAIT = {"name": "wait", "steps": 1}
FILL = ["dirt", "grass", "sand", "leaves", "stone", "planks", "log"]      # used for walls, in this order
SOFT = ["grass", "dirt", "sand", "leaves"]                                 # dug up for wall material
BLOCK_SOURCE = {"log": "log", "stone": "stone", "coal": "coal ore", "iron ore": "iron ore",
                "dirt": "dirt", "grass": "grass", "sand": "sand", "leaves": "leaves", "berries": "berry bush"}
GOALS = ["wood pickaxe", "wood sword", "stone pickaxe", "stone sword", "furnace", "torch", "iron pickaxe", "iron sword",
         "door", "chest", "iron helmet", "iron chestplate"]
JUNK = ["leaves", "sand", "grass", "chest", "log", "sticks", "planks", "coal", "dirt", "torch", "stone", "iron ore"]   # dropped first
KEEP = {"dirt": 9, "stone": 12, "log": 3, "planks": 8, "sticks": 4, "coal": 4, "iron ore": 8}   # held back from drops
STEP_DIR = {(0, -1): "north", (0, 1): "south", (1, 0): "east", (-1, 0): "west"}


class SensibleBot:
    name = "sensible_bot"

    def __init__(self, seed: int = 0, shelter_at: int = 165, food_target: int = 20):
        self.shelter_at = shelter_at          # step of the day when it stops and builds
        self.food_target = food_target        # food points to carry before working on tools
        self.walls: list[tuple[int, int, int]] = []
        self.deaths = 0
        self.last: tuple | None = None
        self.order: list[str] | None = None
        self._door_placed = False             # a door is in this night's shelter already
        self._wall_stock = 9                  # stone kept on hand for a night's shelter (hard mode)

    # ------------------------------------------------------------ interface

    def act(self, observation: str, world) -> dict:
        a = self._decide(world)
        self.last = (tuple(world.pos), repr(a))
        return self._shown(a, world)

    def replay(self, observation: str, world, step_record: dict, memory_record: dict | None) -> None:
        self.act(observation, world)

    @staticmethod
    def _shown(a: dict, w) -> dict:
        a = dict(a)
        if "item" in a:
            a["item"] = w.dn(a["item"])
        if "items" in a:
            a["items"] = {w.dn(k): v for k, v in a["items"].items()}
        return a

    # ------------------------------------------------------------- deciding

    def _decide(self, w) -> dict:
        if self.order is None:
            self.order = reach_order(w.recipes)
        if w.deaths != self.deaths:
            self.deaths, self.walls, self._door_placed = w.deaths, [], False
        tod = w.t % w.cfg.day_length
        stuck = self.last is not None and self.last[0] == tuple(w.pos) and "'move'" in self.last[1]
        if stuck:                                             # something stood in the way
            near = [c for c in w.creatures if cheb(c["pos"], w.pos) <= w.cfg.attack_reach]
            return {"name": "attack", "id": near[0]["id"]} if near else WAIT

        a = self._eat(w)
        if a:
            return a
        a = self._tidy(w)
        if a:
            return a
        if tod >= self.shelter_at:
            return self._shelter(w)
        if self.walls:
            return self._leave(w)

        if self._food_points(w) < self.food_target:
            a = self._get_food(w)
            if a:
                return a
        if w.cfg.creatures.zombie_breaks:              # hard mode: secure a stone shelter first
            a = self._hard_prep(w)
            if a:
                return a
        crafted = w.firsts["craft"]
        for goal in GOALS:
            if goal in crafted or w.inv.get(goal, 0):
                continue
            a = self._station(w, "furnace", frozenset()) if goal == "furnace" and w.inv.get("furnace") \
                else self._want(w, goal, 1, frozenset())
            if a and a != WAIT:                                    # a stalled goal (nothing reachable) is skipped
                return a
        if w.inv.get("furnace"):
            a = self._station(w, "furnace", frozenset())
            if a:
                return a
        if w.inv.get("raw meat", 0) >= 2 and w.find("furnace"):
            a = self._want(w, "cooked meat", w.inv.get("cooked meat", 0) + 1, frozenset())
            if a:
                return a
        if w.pick_tier() == 0:
            a = self._want(w, self._pick_for(1), 1, frozenset())
            if a:
                return a
        hungry = self._food_points(w) < 3 * self.food_target
        if hungry:
            a = self._get_food(w)
            if a and a != WAIT:
                return a
        if hungry or w.pos[1] < w.spawn[1] - 2:                    # nothing reachable from here: dig out
            a = self._climb(w)
            if a:
                return a
        return {"name": "wait", "steps": 4}

    def _climb(self, w) -> dict | None:
        """Cut a staircase toward the start point, one step up at a time."""
        x, y, z = w.pos
        dx, dz = w.spawn[0] - x, w.spawn[2] - z
        d = ("east" if dx > 0 else "west") if abs(dx) >= abs(dz) else ("south" if dz > 0 else "north")
        sx, _, sz = defs.DIRS[d]
        for c in ((x, y + 2, z), (x + sx, y + 1, z + sz), (x + sx, y + 2, z + sz)):
            if w.inb(*c) and not defs.AGENT_PASS[w.bid(*c)]:
                return {"name": "mine", "x": c[0], "y": c[1], "z": c[2]} if w.mine_steps(w.block(*c)) else None
        return {"name": "move", "dir": d, "steps": 1}

    def _tidy(self, w) -> dict | None:
        """With under two slots free, drop an outdone or spare tool, else junk beyond what it keeps.
        After a pickup failed for want of room, drop a whole junk stack."""
        limit = w.cfg.inventory_slots
        full = w.last_result is not None and w.last_result.startswith(T.NO_ROOM)
        if limit <= 0 or (limit - w.slots(w.inv) >= 2 and not full):
            return None
        for group in (list(defs.PICKAXES), defs.SWORDS):
            held = [t for t in group if w.inv.get(t, 0)]
            for t in held[:-1]:                                    # groups run weakest to strongest
                return {"name": "drop", "items": {t: w.inv[t]}}
            if held and w.inv[held[-1]] > 1:
                return {"name": "drop", "items": {held[-1]: w.inv[held[-1]] - 1}}
        for item in JUNK:
            if w.inv.get(item, 0) > KEEP.get(item, 0):
                return {"name": "drop", "items": {item: w.inv[item] - KEEP.get(item, 0)}}
        if full:                                                   # not what the failed action was using
            used = w.last_action or ""
            item = next((i for i in JUNK if w.inv.get(i, 0) and w.dn(i) not in used), None)
            if item:
                return {"name": "drop", "items": {item: w.inv[item]}}
        return None

    def _food_points(self, w) -> int:
        return sum(w.inv.get(i, 0) * v for i, v in w.cfg.food.items())

    def _eat(self, w) -> dict | None:
        room = w.cfg.vitals.max_food - w.food
        can_cook = bool(w.find("furnace"))
        for item in ("cooked meat", "berries", "raw meat"):
            if not w.inv.get(item):
                continue
            if item == "raw meat" and can_cook and w.food > 6:
                continue
            if w.cfg.food[item] <= room:
                return {"name": "eat", "item": item}
        return None

    # -------------------------------------------------------------- shelter

    def _shell(self, pos) -> list[tuple[int, int, int]]:
        x, y, z = pos
        cells = [(x + dx, y + dy, z + dz) for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)) for dy in (0, 1)]
        return cells + [(x, y + 2, z)]

    def _shelter(self, w) -> dict:
        x, y, z = w.pos
        if not self.walls:
            self._door_placed = False
        if w.bid(x, y, z) == defs.WATER:
            path = self._bfs(w, lambda p: w.bid(*p) != defs.WATER)
            return self._follow(path) if path else WAIT
        shell = self._shell(w.pos)
        gaps = [c for c in shell if w.inb(*c) and (defs.CREATURE_PASS[w.bid(*c)] or w.bid(*c) == defs.WATER)]
        if not gaps:
            left = w.cfg.day_length - w.t % w.cfg.day_length
            return {"name": "wait", "steps": max(1, min(8, left))}
        cell = gaps[0]
        inside = [c for c in w.creatures if tuple(c["pos"]) in gaps]
        if inside:
            return {"name": "attack", "id": inside[0]["id"]}
        fill, is_door = self._wall_choice(w, cell)
        if fill:
            if cell not in self.walls:
                self.walls.append(cell)
            if is_door:
                self._door_placed = True
            return {"name": "place", "item": fill, "x": cell[0], "y": cell[1], "z": cell[2]}
        if w.cfg.creatures.zombie_breaks:                 # hard mode: only stone walls are safe
            return self._mine_for(w, "stone", frozenset())
        # Dig wall material from nearby ground, away from where the walls go.
        keep = set(shell) | {(x, y - 1, z)} | {(c[0], y - 1, c[2]) for c in shell}
        r = w.cfg.reach
        best = None
        for cy in range(y + r, y - r - 1, -1):
            for cz in range(z - r, z + r + 1):
                for cx in range(x - r, x + r + 1):
                    c = (cx, cy, cz)
                    if c in keep or not w.inb(*c) or w.block(*c) not in SOFT or not w.exposed(*c):
                        continue
                    key = (-max(abs(cx - x), abs(cz - z)), -cy, cx, cz)
                    if best is None or key < best[0]:
                        best = (key, c)
        if best:
            return {"name": "mine", "x": best[1][0], "y": best[1][1], "z": best[1][2]}
        return WAIT

    def _leave(self, w) -> dict:
        while self.walls:
            c = self.walls[0]
            b = w.block(*c)
            if (b in FILL or b == "door") and cheb(c, w.pos) <= w.cfg.reach and w.mine_steps(b):
                return {"name": "mine", "x": c[0], "y": c[1], "z": c[2]}
            self.walls.pop(0)
        return WAIT

    def _wall_choice(self, w, cell) -> tuple[str | None, bool]:
        """What to put in a shelter gap. Returns (item or None, is_door).

        Easy mode keeps the old behaviour (any block on hand, soft first). Hard mode builds
        with blocks a zombie cannot break (stone) and sets one door for the entrance.
        """
        breaks = set(w.cfg.creatures.zombie_breaks)
        if not breaks:
            return next((i for i in FILL if w.inv.get(i, 0)), None), False
        roof = (w.pos[0], w.pos[1] + 2, w.pos[2])
        if cell != roof and not self._door_placed and w.inv.get("door", 0):
            return "door", True
        return next((i for i in FILL if i not in breaks and w.inv.get(i, 0)), None), False

    def _hard_prep(self, w) -> dict | None:
        """Hard mode only: make a night in a stone shelter affordable before dusk."""
        if w.pick_tier() < 1:                             # a wood pickaxe already cuts stone
            return self._want(w, self._pick_for(1), 1, frozenset())
        if w.inv.get("stone", 0) < self._wall_stock:
            return self._want(w, "stone", self._wall_stock, frozenset())
        if not w.inv.get("door") and "door" not in w.firsts["craft"]:
            return self._want(w, "door", 1, frozenset())
        return None

    # ----------------------------------------------------------- pathfinding

    def _bfs(self, w, is_goal, limit: int = 8000) -> list[tuple[int, int, int]] | None:
        """Shortest walk from the agent to a cell where is_goal is true."""
        start = tuple(w.pos)
        prev: dict = {start: None}
        q = deque([start])
        safe = w.cfg.vitals.fall_safe
        while q and len(prev) < limit:
            p = q.popleft()
            if is_goal(p):
                path = [p]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])
                return path[::-1]
            for d in defs.HORIZONTAL:
                r = w.walk_step(p, d)
                if r is None or r[0] in prev or (r[1] > safe and w.bid(*r[0]) != defs.WATER):
                    continue
                prev[r[0]] = p
                q.append(r[0])
        return None

    @staticmethod
    def _follow(path) -> dict:
        if len(path) < 2:
            return WAIT
        d = STEP_DIR[(path[1][0] - path[0][0], path[1][2] - path[0][2])]
        n = 1
        while n < min(8, len(path) - 1) and STEP_DIR[(path[n + 1][0] - path[n][0], path[n + 1][2] - path[n][2])] == d:
            n += 1
        return {"name": "move", "dir": d, "steps": n}

    def _goto(self, w, targets: list, reach: int, k: int = 6):
        """("at", target) if a target is within reach, else a move toward the nearest few, else None."""
        pos = tuple(w.pos)
        targets = sorted(targets, key=lambda c: (sum((a - b) ** 2 for a, b in zip(c, pos)), c))
        for tgt in targets:
            if cheb(tgt, pos) <= reach:
                return ("at", tgt)
        rr = range(-reach, reach + 1)
        for chunk in (targets[:k], targets[k:6 * k]):
            if not chunk:
                break
            goal = {(tx + dx, ty + dy, tz + dz) for tx, ty, tz in chunk for dx in rr for dy in rr for dz in rr}
            path = self._bfs(w, goal.__contains__)
            if path:
                return self._follow(path)
        return None

    # -------------------------------------------------------------- getting

    def _get_food(self, w, meat_only: bool = False) -> dict | None:
        bushes = [] if meat_only else w.find("berry bush")
        animals = {tuple(c["pos"]): c for c in w.creatures if c["kind"] in defs.PASSIVE}
        pos = tuple(w.pos)
        near = [c for p, c in animals.items() if cheb(p, pos) <= w.cfg.attack_reach]
        if near:
            return {"name": "attack", "id": near[0]["id"]}
        got = self._goto(w, bushes + list(animals), min(w.cfg.reach, w.cfg.attack_reach))
        if got is None:
            return None
        if isinstance(got, tuple):
            x, y, z = got[1]
            return {"name": "mine", "x": x, "y": y, "z": z}
        return got

    def _mine_for(self, w, block: str, stack: frozenset) -> dict:
        need = defs.MINE_TIER.get(block, 0)
        if w.pick_tier() < need:
            return self._want(w, self._pick_for(need), 1, stack) or WAIT
        mask = (w.blocks == defs.ID[block]) & w.exposed_mask()
        targets = [(int(x), int(y), int(z)) for y, z, x in np.argwhere(mask)]
        got = self._goto(w, targets, w.cfg.reach)
        if got is None:
            return WAIT
        if isinstance(got, tuple):
            x, y, z = got[1]
            return {"name": "mine", "x": x, "y": y, "z": z}
        return got

    def _pick_for(self, tier: int) -> str:
        """The first pickaxe of at least this tier that the recipe table lets one reach."""
        return next((i for i in self.order if defs.PICKAXES.get(i, 0) >= tier), "wood pickaxe")

    def _station(self, w, station: str, stack: frozenset) -> dict | None:
        """None when a station is close enough, else the next action toward that."""
        if w.station_near(station):
            return None
        x, y, z = w.pos
        if w.inv.get(station):
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                for dy in (0, 1, -1):
                    c = (x + dx, y + dy, z + dz)
                    if w.inb(*c) and w.bid(*c) == defs.AIR and not w._occupied(*c):
                        return {"name": "place", "item": station, "x": c[0], "y": c[1], "z": c[2]}
            return WAIT
        cells = w.find(station)
        far = not cells or min(math.dist(c, w.pos) for c in cells) > 15
        if cells and not (far and station == "workbench"):
            got = self._goto(w, cells, w.cfg.station_reach)
            if got is not None and not isinstance(got, tuple):
                return got
        return self._want(w, station, 1, stack) or WAIT

    def _want(self, w, item: str, n: int, stack: frozenset) -> dict | None:
        """None when the inventory holds n of the item, else the next action toward that."""
        have = w.inv.get(item, 0)
        if have >= n:
            return None
        if item in stack:
            return WAIT
        stack = stack | {item}
        if item == "raw meat":
            return self._get_food(w, meat_only=True) or WAIT
        if item in BLOCK_SOURCE:
            return self._mine_for(w, BLOCK_SOURCE[item], stack)
        r = next((r for r in w.recipes if r.output == item), None)
        if r is None:
            return WAIT
        batches = math.ceil((n - have) / r.count)
        items = r.items()
        fuel = items.pop("fuel", 0)
        if fuel:
            f = "coal" if w.inv.get("coal", 0) >= fuel * batches else "planks"
            items[f] = items.get(f, 0) + fuel
        for inp, cnt in items.items():
            a = self._want(w, inp, cnt * batches, stack)
            if a:
                return a
        if r.station:
            a = self._station(w, r.station, stack)
            if a:
                return a
        return {"name": "craft", "items": items}
