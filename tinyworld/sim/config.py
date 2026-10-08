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


class Creatures(_M):
    sheep_start: int = 6
    chicken_start: int = 6
    passive_max: int = 8
    passive_respawn: int = 2
    passive_move_prob: float = 0.25
    animal_count_mult: float = 1.0        # scales sheep+chicken start counts, max, and respawn
    health: dict[str, int] = {"sheep": 6, "chicken": 4, "zombie": 10}
    meat: dict[str, int] = {"sheep": 2, "chicken": 1, "zombie": 0}
    zombie_max: int = 6
    zombie_spawn_prob: float = 0.08
    zombie_spawn_min_dist: int = 12
    zombie_spawn_max_dist: int = 24
    zombie_chase_dist: int = 10
    zombie_step_every: float = 2          # world steps per zombie move (1 matches the agent's speed, 1.5 is 2 of every 3)
    zombie_damage: int = 3
    zombie_cooldown: int = 2
    zombie_breaks: list[str] = []         # block names a blocked zombie can break (empty = none)
    zombie_break_steps: int = 4           # steps spent adjacent to break one soft block
    torch_radius: int = 6                 # a torch this close suppresses zombie spawns


class WorldConfig(_M):
    size: tuple[int, int, int] = (64, 32, 64)          # x, y, z
    sea_level: int = 12
    names: Literal["familiar", "alien"] = "familiar"
    shuffle_recipes: bool = False
    on_death: Literal["respawn_keep_memory", "respawn_wipe_memory", "end_run"] = "respawn_keep_memory"
    on_stuck: Literal["end_run", "continue"] = "end_run"   # trapped for good: end, or only log a stuck event
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
    food: dict[str, int] = {"berries": 2, "raw meat": 3, "cooked meat": 8}
    berries_per_bush: int = 2
    bush_regrow: int = 150
    hardness: dict[str, int] = {}
    tool_speed: list[float] = [1, 2, 3, 4]              # hand, wood, stone, iron pickaxe
    durability: dict[str, int] = {}
    hand_damage: int = 2
    sword_damage: dict[str, int] = {"wood sword": 3, "stone sword": 4, "iron sword": 6}
    armor: dict[str, int] = {"iron helmet": 1, "iron chestplate": 2}   # zombie damage taken off per piece held
    terrain: Terrain = Terrain()
    creatures: Creatures = Creatures()


def load_world_config(path: str | Path | None = None, **overrides) -> WorldConfig:
    """Load the yaml file, then apply top level overrides such as names="alien"."""
    data = yaml.safe_load(Path(path or DEFAULT_PATH).read_text()) or {}
    data.update({k: v for k, v in overrides.items() if v is not None})
    return WorldConfig.model_validate(data)
