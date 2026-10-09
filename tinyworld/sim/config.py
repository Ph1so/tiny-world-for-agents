"""World config as a pydantic model, loaded from configs/world.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "configs" / "world.yaml"


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vitals(_M):
    max_health: int = 20
    max_food: int = 20
    food_drain_every: int = 15        # world steps between losing one food point
    starve_every: int = 5
    heal_food_min: int = 15
    heal_every: int = 10
    max_air: int = 10
    drown_damage: int = 2
    fall_safe: int = 3


class Terrain(_M):
    base_height: float = 15.2
    noise_scales: list[int] = [16, 8, 4]
    noise_amps: list[float] = [5.0, 2.5, 1.2]
    edge_width: int = 9
    edge_depth: int = 7
    hill_height: float = 9.0
    hill_radius: float = 7.0
    stone_line: int = 19
    lake_radius: float = 4.5
    lake_depth: int = 3
    coal_rate: float = 0.03
    iron_rate: float = 0.02
    surface_coal: int = 8
    surface_iron: int = 8
    forest_tree_rate: float = 0.10
    plain_tree_rate: float = 0.006
    min_trees: int = 10
    bush_rate: float = 0.012
    min_bushes: int = 12
    berry_density_mult: float = 1.0        # scales berry bush spawn rate and minimum count


class Farming(_M):
    seed_chance: float = 0.25          # chance that mining grass also gives 1 seeds
    water_dist: int = 4                # seeds need water within this many cells sideways, level with the soil or up to 2 below; 0 = no need
    grow_steps: int = 300              # world steps for a sprout to turn into wheat; steps in rain count double
    wheat_per_crop: int = 2
    seeds_per_crop: int = 1            # seeds back from ripe wheat, plus 1 more with seed_bonus_chance
    seed_bonus_chance: float = 0.5


class Weather(_M):
    enabled: bool = True
    spell: int = 100                   # a new weather is drawn every this many world steps (the first spell is clear)
    rain_prob: float = 0.25
    storm_prob: float = 0.1
    rain_food_mult: int = 2            # without a roof in rain or storm, food drains this many times as fast and health does not rise
    hail_every: int = 6                # without a roof in a storm, hail_damage every this many steps
    hail_damage: int = 1


class Creatures(_M):
    sheep_start: int = 6
    chicken_start: int = 6
    passive_max: int = 8
    passive_respawn: int = 2
    passive_move_prob: float = 0.25
    animal_count_mult: float = 1.0        # scales sheep+chicken start counts, max, and respawn
    health: dict[str, int] = {"sheep": 6, "chicken": 4, "zombie": 10}
    meat: dict[str, int] = {"sheep": 2, "chicken": 1, "zombie": 0}
    wool: dict[str, int] = {"sheep": 1}
    zombie_max: int = 6
    zombie_spawn_prob: float = 0.08
    zombie_spawn_min_dist: int = 12
    zombie_spawn_max_dist: int = 24
    zombie_dark_spawn_prob: float = 0.0   # chance per step (any hour) of a spawn in a covered, unlit cell
    zombie_dark_min_dist: int = 5         # sideways distance from the agent for those spawns
    zombie_chase_dist: int = 10
    zombie_step_every: float = 2          # world steps per zombie move (1 matches the agent's speed, 1.5 is 2 of every 3)
    zombie_damage: int = 3
    zombie_cooldown: int = 2
    zombie_breaks: list[str] = []         # block names a blocked zombie can break (empty = none)
    zombie_break_steps: int = 4           # steps spent adjacent to break one soft block
    torch_radius: int = 6                 # a torch this close suppresses zombie spawns
    zombie_hits_per_decision: bool = True # multi-agent: zombies hit an agent at most once per action it
                                          # starts, so the steps it spends thinking are not free hits


class WorldConfig(_M):
    size: tuple[int, int, int] = (64, 32, 64)          # x, y, z
    sea_level: int = 12
    names: Literal["familiar", "alien"] = "familiar"
    shuffle_recipes: bool = False
    on_death: Literal["respawn_keep_memory", "respawn_wipe_memory", "end_run"] = "respawn_keep_memory"
    on_stuck: Literal["end_run", "continue"] = "end_run"   # trapped for good: end, or only log a stuck event
    vitals_lookback: int = 60          # observation shows health and food this many steps ago (0 = off)
    rule_notes: bool = True            # say why a craft failed or health is not rising, and list what was made
    recipe_book: bool = False          # list every craft (inputs, output, station) in the system prompt
    day_length: int = 300
    night_start: int = 200
    dim_steps: int = 20
    torch_light: int = 6
    inventory_slots: int = 0           # 0 = no limit. A slot holds one tool or up to stack_size of an item
    stack_size: int = 32
    chest_slots: int = 20
    reach: int = 3
    attack_reach: int = 2
    station_reach: int = 2
    close_radius: int = 3
    view_radius: int = 12
    vitals: Vitals = Vitals()
    food: dict[str, int] = {"berries": 2, "raw meat": 3, "cooked meat": 8, "bread": 6}
    berries_per_bush: int = 2
    bush_regrow: int = 150
    hardness: dict[str, int] = {}
    tool_speed: list[float] = [1, 2, 3, 4]              # hand, wood, stone, iron pickaxe
    durability: dict[str, int] = {}
    hand_damage: int = 2
    sword_damage: dict[str, int] = {"wood sword": 3, "stone sword": 4, "iron sword": 6}
    armor: dict[str, int] = {"iron helmet": 1, "iron chestplate": 2}   # zombie damage taken off per piece held
    sleep_zombie_dist: int = 8         # no sleep with a zombie this close
    sleep_heal_every: int = 5          # asleep with food above 0: 1 health every this many steps
    hear_radius: int = 16              # multi-agent: "say" reaches agents this close
    say_max_chars: int = 200           # longer speech is cut
    pvp_loot: bool = False             # multi-agent: a killer gets what fits of the victim's inventory
    terrain: Terrain = Terrain()
    creatures: Creatures = Creatures()
    farming: Farming = Farming()
    weather: Weather = Weather()


def load_world_config(path: str | Path | None = None, **overrides) -> WorldConfig:
    """Load the yaml file, then apply top level overrides such as names="alien"."""
    data = yaml.safe_load(Path(path or DEFAULT_PATH).read_text()) or {}
    data.update({k: v for k, v in overrides.items() if v is not None})
    return WorldConfig.model_validate(data)
