"""Baseline: a hand-coded bot. It gathers food, makes tools, and walls itself in at night.

It reads the world's internals directly (block grid, recipe table, creature list).
All names inside this file are familiar names. They are turned into shown names on the way out.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

from tinyworld.sim import defs
from tinyworld.sim.recipes import reach_order
from tinyworld.sim.world import cheb

WAIT = {"name": "wait", "steps": 1}
FILL = ["dirt", "grass", "sand", "leaves", "stone", "planks", "log"]      # used for walls, in this order
SOFT = ["grass", "dirt", "sand", "leaves"]                                 # dug up for wall material
BLOCK_SOURCE = {"log": "log", "stone": "stone", "coal": "coal ore", "iron ore": "iron ore",
                "dirt": "dirt", "grass": "grass", "sand": "sand", "leaves": "leaves", "berries": "berry bush"}
GOALS = ["wood pickaxe", "stone pickaxe", "stone sword", "furnace", "torch", "iron pickaxe", "iron sword", "door"]
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
            self.deaths, self.walls = w.deaths, []
        tod = w.t % w.cfg.day_length
        stuck = self.last is not None and self.last[0] == tuple(w.pos) and "'move'" in self.last[1]
        if stuck:                                             # something stood in the way
            near = [c for c in w.creatures if cheb(c["pos"], w.pos) <= w.cfg.attack_reach]
            return {"name": "attack", "id": near[0]["id"]} if near else WAIT

        a = self._eat(w)
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
        crafted = w.firsts["craft"]
        for goal in GOALS:
            if goal in crafted or w.inv.get(goal, 0):
                continue
            a = self._station(w, "furnace", frozenset()) if goal == "furnace" and w.inv.get("furnace") \
                else self._want(w, goal, 1, frozenset())
            if a:
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
        if self._food_points(w) < 3 * self.food_target:
            a = self._get_food(w)
            if a:
                return a
        return {"name": "wait", "steps": 4}

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
        fill = next((i for i in FILL if w.inv.get(i, 0)), None)
        if fill:
            if cell not in self.walls:
                self.walls.append(cell)
            return {"name": "place", "item": fill, "x": cell[0], "y": cell[1], "z": cell[2]}
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
            if w.block(*c) in FILL and cheb(c, w.pos) <= w.cfg.reach and w.mine_steps(w.block(*c)):
                return {"name": "mine", "x": c[0], "y": c[1], "z": c[2]}
            self.walls.pop(0)
        return WAIT

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
