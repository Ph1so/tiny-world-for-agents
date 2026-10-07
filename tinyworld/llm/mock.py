"""Mock adapters for tests. No network.

MockClient answers from a list of strings or a callable (system, user) -> str.

SensibleMockClient plays like the sensible bot but through the real agent loop: it answers with
JSON in the reply format, appends memory lines now and then, sends an over-limit edit every so
often, and sends an unreadable reply every so often. So a mock run exercises the memory file,
the rejection path, and the parse failure path for real.

It needs the world to decide, which an LLM never sees. The controller hands the world over when
the client has `needs_world = True`.
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable

from .base import LLMClient, Reply

_MEM_LINE = re.compile(r"memory file \((\d+) of (\d+) characters used\)")


class MockClient(LLMClient):
    name = "mock"
    model_id = "mock"

    def __init__(self, script: list[str] | Callable[[str, str], str] | None = None,
                 input_tokens: int = 0, output_tokens: int = 0, latency_s: float = 0.0):
        self.script = script if script is not None else ['{"thought": "", "memory": [], "action": {"name": "wait", "steps": 1}}']
        self.calls: list[tuple[str, str, int]] = []
        self._tok = (input_tokens, output_tokens)
        self._latency = latency_s

    def settings(self) -> dict:
        return {"mock": True}

    def complete(self, system: str, user: str, max_tokens: int) -> Reply:
        self.calls.append((system, user, max_tokens))
        if callable(self.script):
            text = self.script(system, user)
        else:
            text = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        inp = self._tok[0] or max(1, (len(system) + len(user)) // 4)
        out = self._tok[1] or max(1, len(text) // 4)
        return Reply(text=text, input_tokens=inp, output_tokens=out, latency_s=self._latency)


class SensibleMockClient(MockClient):
    """The sensible bot wrapped in the reply format, with memory edits and a few bad replies."""
    name = "mock_sensible"
    model_id = "mock-sensible"
    needs_world = True

    def __init__(self, seed: int = 0, note_every: int = 5, overflow_every: int = 29, garble_every: int = 37,
                 rewrite_every: int = 60):
        super().__init__()
        from tinyworld.bots.sensible_bot import SensibleBot
        self.bot = SensibleBot(seed)
        self.world = None
        self.n = 0
        self.note_every, self.overflow_every = note_every, overflow_every
        self.garble_every, self.rewrite_every = garble_every, rewrite_every

    def replay(self, observation: str, world, step_record: dict) -> None:
        """Bring the bot's private state forward on resume, like a bot controller does."""
        self.world = world
        self.n += 1
        self.bot.replay(observation, world, step_record, None)

    def complete(self, system: str, user: str, max_tokens: int) -> Reply:
        self.calls.append((system, user, max_tokens))
        self.n += 1
        if self.world is None:
            raise RuntimeError("SensibleMockClient needs world set before complete()")
        if self.garble_every and self.n % self.garble_every == 0:
            text = "I will look around first. {not json"
        else:
            action = self.bot.act(self.world.observe(), self.world)
            text = json.dumps({"thought": f"mock step {self.n}", "memory": self._memory_ops(user, action),
                               "action": action})
        return Reply(text=text, input_tokens=(len(system) + len(user)) // 4, output_tokens=max(1, len(text) // 4),
                     latency_s=0.0)

    def _memory_ops(self, user: str, action: dict) -> list[dict]:
        m = _MEM_LINE.search(user)
        if not m:
            return []                                          # memory size 0: nothing to edit
        used, limit = int(m.group(1)), int(m.group(2))
        w = self.world
        if self.overflow_every and self.n % self.overflow_every == 0:
            return [{"op": "append", "text": "x" * (limit - used + 1)}]
        if self.rewrite_every and self.n % self.rewrite_every == 0:
            return [{"op": "rewrite", "text": f"step {w.t} at {tuple(w.pos)}"[:limit]}]
        if self.note_every and self.n % self.note_every == 0:
            line = f"step {w.t} at {tuple(w.pos)} did {action.get('name')}"
            if used + len(line) + 1 > limit:
                return [{"op": "replace", "old": user.split("\n")[1] if "\n" in user else "", "new": line}]
            return [{"op": "append", "text": line}]
        return []
