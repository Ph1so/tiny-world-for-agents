"""World settings the viewer's new-run form can change, and how a change becomes a world file.

Each setting is a dotted key into the world config (configs/world*.yaml). The form shows them
grouped, filled with the chosen base world's values; whatever the person changes is sent as
{key: value}. apply_overrides() writes those into a copy of the base world, checks the result
against WorldConfig (so a bad value is refused before anything starts), and the run gets that
file as its --config. The run's own config.yaml then records every value it ran with.
"""
from __future__ import annotations

import copy
from typing import Any

import yaml
from pydantic import ValidationError

from tinyworld.runner.run import CONFIGS_DIR
from tinyworld.sim import WorldConfig

# key, label, group, kind ("bool" | "int" | "float" | "choice"), extra (min, max, step, choices, hint)
SETTINGS: list[dict[str, Any]] = [
    # rules
    {"key": "recipe_book", "label": "recipe book in the prompt", "group": "rules", "kind": "bool",
     "hint": "lists every craft in the agent's instructions"},
    {"key": "rule_notes", "label": "rule notes", "group": "rules", "kind": "bool",
     "hint": "say why a craft failed, why health is flat, what rain does"},
    {"key": "names", "label": "names", "group": "rules", "kind": "choice", "choices": ["familiar", "alien"],
     "hint": "alien: made-up words for every block and item"},
    {"key": "shuffle_recipes", "label": "shuffle recipes", "group": "rules", "kind": "bool"},
    {"key": "on_death", "label": "on death", "group": "rules", "kind": "choice",
     "choices": ["respawn_keep_memory", "respawn_wipe_memory", "end_run"]},
    {"key": "inventory_slots", "label": "inventory slots", "group": "rules", "kind": "int", "min": 0, "max": 60,
     "hint": "0 = no limit"},
    {"key": "view_radius", "label": "view radius", "group": "rules", "kind": "int", "min": 2, "max": 24},
    {"key": "day_length", "label": "day length (steps)", "group": "rules", "kind": "int", "min": 60, "max": 2000},
    {"key": "night_start", "label": "night starts at", "group": "rules", "kind": "int", "min": 10, "max": 1990,
     "hint": "step of the day; must be under day length"},
    # weather
    {"key": "weather.enabled", "label": "weather", "group": "weather", "kind": "bool"},
    {"key": "weather.rain_prob", "label": "rain chance per spell", "group": "weather", "kind": "float", "min": 0, "max": 1, "step": 0.05},
    {"key": "weather.storm_prob", "label": "storm chance per spell", "group": "weather", "kind": "float", "min": 0, "max": 1, "step": 0.05},
    {"key": "weather.spell", "label": "spell length (steps)", "group": "weather", "kind": "int", "min": 10, "max": 2000},
    {"key": "weather.hail_damage", "label": "hail damage", "group": "weather", "kind": "int", "min": 0, "max": 10},
    # zombies
    {"key": "creatures.zombie_max", "label": "max zombies", "group": "zombies", "kind": "int", "min": 0, "max": 60},
    {"key": "creatures.zombie_spawn_prob", "label": "spawn chance per night step", "group": "zombies", "kind": "float", "min": 0, "max": 1, "step": 0.01},
    {"key": "creatures.zombie_chase_dist", "label": "sight range", "group": "zombies", "kind": "int", "min": 0, "max": 64},
    {"key": "creatures.zombie_damage", "label": "damage per hit", "group": "zombies", "kind": "int", "min": 0, "max": 20},
    {"key": "creatures.zombie_step_every", "label": "steps per zombie move", "group": "zombies", "kind": "float", "min": 1, "max": 10, "step": 0.5,
     "hint": "1 = as fast as an agent"},
    {"key": "creatures.zombie_dark_spawn_prob", "label": "spawns in dark covered cells", "group": "zombies", "kind": "float", "min": 0, "max": 1, "step": 0.005},
    {"key": "creatures.zombie_hits_per_decision", "label": "one hit per decision (multi)", "group": "zombies", "kind": "bool",
     "hint": "time spent thinking is not free hits"},
    # food and survival
    {"key": "vitals.food_drain_every", "label": "steps per food point lost", "group": "food and survival", "kind": "int", "min": 1, "max": 200},
    {"key": "vitals.max_health", "label": "max health", "group": "food and survival", "kind": "int", "min": 1, "max": 100},
    {"key": "creatures.animal_count_mult", "label": "animals (x)", "group": "food and survival", "kind": "float", "min": 0, "max": 5, "step": 0.25},
    {"key": "terrain.berry_density_mult", "label": "berry bushes (x)", "group": "food and survival", "kind": "float", "min": 0, "max": 5, "step": 0.25},
    {"key": "farming.grow_steps", "label": "crop growing time", "group": "food and survival", "kind": "int", "min": 10, "max": 3000},
    {"key": "farming.seed_chance", "label": "seed chance from grass", "group": "food and survival", "kind": "float", "min": 0, "max": 1, "step": 0.05},
    {"key": "farming.wild_patches", "label": "wild wheat patches", "group": "food and survival", "kind": "int", "min": 0, "max": 30,
     "hint": "ripe wheat by water on a new map"},
    {"key": "start_items.seeds", "label": "starting seeds", "group": "food and survival", "kind": "int", "min": 0, "max": 32},
    {"key": "start_items.bread", "label": "starting bread", "group": "food and survival", "kind": "int", "min": 0, "max": 32},
    {"key": "creatures.passive_respawn", "label": "animals back each morning (per kind)", "group": "food and survival", "kind": "float",
     "min": 0, "max": 20, "step": 0.1, "hint": "0.5 = one about every other day"},
    {"key": "bush_regrow", "label": "berry bush regrows after (steps)", "group": "food and survival", "kind": "int", "min": 1, "max": 100000,
     "hint": "a very large number means never"},
    {"key": "farming.zombies_trample", "label": "zombies trample crops", "group": "food and survival", "kind": "bool",
     "hint": "a chasing zombie that steps onto a crop crushes it"},
    {"key": "farming.animal_eat_prob", "label": "animals eat crops (chance per step)", "group": "food and survival", "kind": "float",
     "min": 0, "max": 1, "step": 0.01},
    {"key": "farming.wheat_per_crop", "label": "wheat per ripe crop", "group": "food and survival", "kind": "int", "min": 1, "max": 10},
    {"key": "food.bread", "label": "food from bread", "group": "food and survival", "kind": "int", "min": 1, "max": 20},
    # resources
    {"key": "terrain.hill_place", "label": "stone hill", "group": "resources", "kind": "choice", "choices": ["random", "corner"],
     "hint": "corner: the hill of stone and surface ore sits in a corner"},
    {"key": "terrain.ore_radius", "label": "ore only near the hill (cells)", "group": "resources", "kind": "int", "min": 0, "max": 64,
     "hint": "0 = ore in stone everywhere; e.g. 14 = only around the hill"},
    {"key": "terrain.coal_rate", "label": "coal in stone", "group": "resources", "kind": "float", "min": 0, "max": 0.5, "step": 0.005},
    {"key": "terrain.iron_rate", "label": "iron in stone", "group": "resources", "kind": "float", "min": 0, "max": 0.5, "step": 0.005},
    {"key": "terrain.min_trees", "label": "minimum trees", "group": "resources", "kind": "int", "min": 0, "max": 200},
    # multi-agent
    {"key": "hear_radius", "label": "say reaches (cells)", "group": "multi-agent", "kind": "int", "min": 0, "max": 64},
    {"key": "pvp_loot", "label": "killer takes the victim's items", "group": "multi-agent", "kind": "bool"},
]
KEYS = {s["key"] for s in SETTINGS}


def _get(d: dict, dotted: str):
    for part in dotted.split("."):
        d = d.get(part, {}) if isinstance(d, dict) else {}
    return d if d != {} else None


def base_world(name: str) -> dict:
    """The world yaml as a dict, with every setting filled (missing keys take WorldConfig's defaults)."""
    data = yaml.safe_load((CONFIGS_DIR / f"{name}.yaml").read_text()) or {}
    return WorldConfig.model_validate(data).model_dump(mode="json")


def defaults(name: str) -> dict[str, Any]:
    full = base_world(name)
    return {s["key"]: _get(full, s["key"]) for s in SETTINGS}


def apply_overrides(name: str, overrides: dict[str, Any]) -> dict:
    """The base world with the changed settings written in. Raises ValueError on an unknown key or
    a value WorldConfig refuses."""
    unknown = sorted(set(overrides) - KEYS)
    if unknown:
        raise ValueError(f"unknown setting: {', '.join(unknown)}")
    data = copy.deepcopy(base_world(name))
    for key, value in overrides.items():
        d = data
        *path, last = key.split(".")
        for part in path:
            d = d.setdefault(part, {})
        d[last] = value
    try:
        cfg = WorldConfig.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        raise ValueError(f"{'.'.join(map(str, first['loc']))}: {first['msg']}")
    if cfg.night_start >= cfg.day_length:
        raise ValueError("night_start must be under day_length")
    return cfg.model_dump(mode="json")
