"""Static definitions: blocks, items, creatures, tools. All names here are the familiar names."""
from __future__ import annotations

BLOCKS: list[str] = [
    "air", "grass", "dirt", "sand", "stone", "water", "log", "leaves", "berry bush",
    "coal ore", "iron ore", "planks", "workbench", "furnace", "torch", "door",
]
ID: dict[str, int] = {n: i for i, n in enumerate(BLOCKS)}
AIR, WATER, TORCH, DOOR = ID["air"], ID["water"], ID["torch"], ID["door"]

# Per block id lookup tables (plain lists, fast to index).
AGENT_PASS: list[bool] = [n in ("air", "water", "torch", "door") for n in BLOCKS]   # agent can occupy
CREATURE_PASS: list[bool] = [n in ("air", "torch") for n in BLOCKS]                 # creatures can occupy
SUPPORT: list[bool] = [n not in ("air", "water", "torch") for n in BLOCKS]          # can be stood on
TRANSPARENT: list[bool] = [n in ("air", "water", "torch") for n in BLOCKS]          # sight passes through

# Pickaxe tier needed to break a block. Missing means hand (0). Water never breaks.
MINE_TIER: dict[str, int] = {"stone": 1, "coal ore": 1, "iron ore": 2}
# What a broken block gives, if not itself. Berry count comes from the config.
DROPS: dict[str, str] = {"coal ore": "coal", "berry bush": "berries"}

PLACEABLE: list[str] = [
    "grass", "dirt", "sand", "stone", "log", "leaves", "iron ore", "planks",
    "workbench", "furnace", "torch", "door",
]
PICKAXES: dict[str, int] = {"wood pickaxe": 1, "stone pickaxe": 2, "iron pickaxe": 3}   # name -> tier
SWORDS: list[str] = ["stone sword", "iron sword"]
TOOLS: list[str] = list(PICKAXES) + SWORDS
ITEMS: list[str] = PLACEABLE + [
    "sticks", "coal", "iron ingot", "berries", "raw meat", "cooked meat",
] + TOOLS
FUELS: list[str] = ["coal", "planks"]
EDIBLE: list[str] = ["berries", "raw meat", "cooked meat"]

PASSIVE: list[str] = ["sheep", "chicken"]
CREATURES: list[str] = PASSIVE + ["zombie"]

# Every name the agent can ever be shown or type. "air" is left out: it is never listed as a block.
ALL_NAMES: list[str] = list(dict.fromkeys(BLOCKS[1:] + ITEMS + CREATURES))

DIRS: dict[str, tuple[int, int, int]] = {
    "north": (0, 0, -1), "south": (0, 0, 1), "east": (1, 0, 0), "west": (-1, 0, 0),
    "up": (0, 1, 0), "down": (0, -1, 0),
}
HORIZONTAL: list[str] = ["north", "south", "east", "west"]
