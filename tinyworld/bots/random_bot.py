"""Baseline: picks a random action type, then a random valid action of that type."""
from __future__ import annotations

import numpy as np


class RandomBot:
    name = "random_bot"

    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng([int(seed), 0xB07])

    def act(self, observation: str, world) -> dict:
        groups: dict[str, list[dict]] = {}
        for a in world.valid_actions():
            groups.setdefault(a["name"], []).append(a)
        names = list(groups)
        acts = groups[names[int(self.rng.integers(len(names)))]]
        return acts[int(self.rng.integers(len(acts)))]

    def replay(self, observation: str, world, step_record: dict, memory_record: dict | None) -> None:
        """Called on resume for each logged step, to bring the bot's own state forward."""
        self.act(observation, world)
