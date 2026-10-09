"""Recipes, the optional shuffle, and a check that every recipe can be reached."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import defs


@dataclass(frozen=True)
class Recipe:
    inputs: tuple[tuple[str, int], ...]   # "fuel" stands for coal or planks
    output: str
    count: int
    station: str | None                   # block that must be within station_reach

    @property
    def tier(self) -> int:
        return {None: 0, "workbench": 1, "furnace": 2}[self.station]

    def items(self) -> dict[str, int]:
        return dict(self.inputs)


def _r(inputs: dict[str, int], output: str, count: int = 1, station: str | None = None) -> Recipe:
    return Recipe(tuple(inputs.items()), output, count, station)


BASE: list[Recipe] = [
    _r({"log": 1}, "planks", 4),
    _r({"planks": 2}, "sticks", 4),
    _r({"planks": 4}, "workbench"),
    _r({"coal": 1, "sticks": 1}, "torch", 4),
    _r({"planks": 6}, "door", 1, "workbench"),
    _r({"planks": 3, "sticks": 2}, "wood pickaxe", 1, "workbench"),
    _r({"stone": 3, "sticks": 2}, "stone pickaxe", 1, "workbench"),
    _r({"planks": 2, "sticks": 1}, "wood sword", 1, "workbench"),
    _r({"stone": 2, "sticks": 1}, "stone sword", 1, "workbench"),
    _r({"stone": 8}, "furnace", 1, "workbench"),
    _r({"planks": 8}, "chest", 1, "workbench"),
    _r({"iron ingot": 3, "sticks": 2}, "iron pickaxe", 1, "workbench"),
    _r({"iron ingot": 2, "sticks": 1}, "iron sword", 1, "workbench"),
    _r({"iron ingot": 3}, "iron helmet", 1, "workbench"),
    _r({"iron ingot": 5}, "iron chestplate", 1, "workbench"),
    _r({"raw meat": 1, "fuel": 1}, "cooked meat", 1, "furnace"),
    _r({"iron ore": 1, "fuel": 1}, "iron ingot", 1, "furnace"),
    _r({"wheat": 3}, "bread"),
    _r({"wool": 3, "planks": 3}, "bed", 1, "workbench"),
    _r({"wheat": 3, "planks": 3}, "bed", 1, "workbench"),     # a straw bed: wool is scarce, wheat is farmed
]

# Kept out of the shuffle: wheat takes a crop's growing time and wool a sheep each, so swapped
# onto planks or a pickaxe they would hold up everything after it. The other 17 shuffle as before.
UNSHUFFLED = {"bread", "bed"}

# Things that can be had with bare hands, with any pickaxe, and with a stone or iron pickaxe.
RAW_BY_TIER: list[list[str]] = [
    ["log", "grass", "dirt", "sand", "leaves", "berries", "raw meat", "seeds", "wheat", "wool"],
    ["stone", "coal"],
    ["iron ore"],
]


def reach_order(recipes: list[Recipe]) -> list[str]:
    """Items in the order they become obtainable, starting from bare hands."""
    have: list[str] = list(RAW_BY_TIER[0])
    changed = True
    while changed:
        changed = False
        tier = max([defs.PICKAXES[p] for p in defs.PICKAXES if p in have], default=0)
        for t in range(1, tier + 1):
            for item in RAW_BY_TIER[min(t, 2)] if t <= 2 else []:
                if item not in have:
                    have.append(item)
                    changed = True
        for r in recipes:
            if r.output in have or r.output in r.items():
                continue
            ok = all((any(f in have for f in defs.FUELS) if i == "fuel" else i in have) for i in r.items())
            if ok and (r.station is None or r.station in have):
                have.append(r.output)
                changed = True
    return have


def all_reachable(recipes: list[Recipe]) -> bool:
    have = reach_order(recipes)
    return all(r.output in have and r.output not in r.items() for r in recipes)


def build_recipes(shuffle: bool, seed: int) -> list[Recipe]:
    """The base table, or a seeded shuffle of input sets among recipes of the same tier
    (bread and bed keep theirs)."""
    if not shuffle:
        return list(BASE)
    rng = np.random.default_rng([int(seed), 0x5EC1])
    for _ in range(500):
        out: list[Recipe] = list(BASE)
        for tier in (0, 1, 2):
            idx = [i for i, r in enumerate(BASE) if r.tier == tier and r.output not in UNSHUFFLED]
            perm = [idx[int(j)] for j in rng.permutation(len(idx))]
            for i, j in zip(idx, perm):
                out[i] = Recipe(BASE[j].inputs, BASE[i].output, BASE[i].count, BASE[i].station)
        if out != BASE and all_reachable(out):
            return out
    return list(BASE)
