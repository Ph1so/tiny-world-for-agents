"""Make a small run with memory edits for testing the memory panel and timeline.

    uv run python viewer/fixtures/make_memdemo.py            # writes viewer/fixtures/memdemo/

The sensible bot picks the actions. A scripted wrapper adds memory ops (append, replace, rewrite,
and a few edits that go over the limit and are rejected) and a short thought, using the same log
formats the LLM agent writes (docs/INTERFACES.md). No new formats, no model calls.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tinyworld.bots.sensible_bot import SensibleBot          # noqa: E402
from tinyworld.runner.run import run                         # noqa: E402
from tinyworld.sim import load_world_config                  # noqa: E402

LIMIT = 800


class MemoryDemoController:
    """Wraps a bot and scripts memory ops the way an LLM agent would send them."""

    name = "sensible_bot"

    def __init__(self, seed: int):
        self.bot = SensibleBot(seed)
        self.memory_limit = LIMIT
        self.text = ""
        self.i = 0
        self.history: list[str] = []

    def _apply(self, ops: list[dict]) -> tuple[str, bool, int]:
        text = self.text
        for op in ops:
            if op["op"] == "append":
                text = text + ("\n" if text else "") + op["text"]
            elif op["op"] == "replace":
                text = text.replace(op["old"], op["new"], 1)
            elif op["op"] == "rewrite":
                text = op["text"]
        over = len(text) - LIMIT
        if over > 0:
            return self.text, False, over
        return text, True, 0

    def _ops(self, obs: str, world) -> list[dict]:
        i = self.i
        pos = re.search(r"position \((\d+), (\d+), (\d+)\)", obs)
        p = f"({pos.group(1)},{pos.group(2)},{pos.group(3)})" if pos else "?"
        light = re.search(r"light (\w+)", obs)
        lines = self.text.split("\n") if self.text else []
        if i == 1:
            return [{"op": "append", "text": f"start point {p}. light {light.group(1) if light else '?'}."}]
        if i % 7 == 3:
            seen = re.findall(r"^  ([a-z ]+): .*?nearest \((\d+),(\d+),(\d+)\)", obs, re.M)
            if seen:
                name, x, y, z = seen[(i // 7) % len(seen)]
                return [{"op": "append", "text": f"{name.strip()} near ({x},{y},{z})"}]
        if i % 11 == 5 and len(lines) > 1:
            old = lines[1]
            return [{"op": "replace", "old": old, "new": old + f" (checked step {i})"}]
        if i == 40 or (i > 40 and i % 29 == 0):
            keep = [ln for ln in lines if "near" in ln or "inventory" in ln][-4:]
            return [{"op": "rewrite", "text": "\n".join([f"notes, rewritten at step {i}:"] + keep)}]
        if i in (24, 61, 88):
            return [{"op": "append", "text": "x" * (LIMIT - len(self.text) + 25)}]   # over the limit on purpose
        if i % 13 == 0:
            inv = re.search(r"inventory: (.*)", obs)
            return [{"op": "append", "text": f"step {i} inventory: {inv.group(1)[:60] if inv else 'empty'}"}]
        return []

    def act(self, observation: str, world) -> dict:
        self.i += 1
        action = self.bot.act(observation, world)
        ops = self._ops(observation, world)
        out: dict = {"action": action, "thought": f"I will {action['name']}. Memory has {len(self.text)} chars.",
                     "raw_reply": "", "parse_ok": True}
        if ops:
            text, accepted, over = self._apply(ops)
            self.text = text
            out["memory"] = {"ops": ops, "accepted": accepted, "over_by": over, "text": text, "chars": len(text), "limit": LIMIT}
            out["memory_rejected"] = not accepted
            if not accepted:
                out["events"] = [{"type": "memory_rejected", "detail": {"over_by": over}}]
        out["memory_chars_used"] = len(self.text)
        return out

    def on_result(self, result, world) -> None:
        if hasattr(self.bot, "on_result"):
            self.bot.on_result(result, world)


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    cfg = load_world_config()
    ctl = MemoryDemoController(seed=2)
    world = run("memdemo", "sensible_bot", seed=2, max_steps=420, world_cfg=cfg, runs_dir=out_dir,
                controller=ctl, extra_config={"memory_chars": LIMIT, "history_window": 3, "model": "scripted-demo"})
    print(f"memdemo: world steps {world.t}, agent steps {ctl.i}, folder {out_dir / 'memdemo'}")


if __name__ == "__main__":
    main()
