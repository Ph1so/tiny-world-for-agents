"""The LLM agent as a controller for tinyworld.runner.run.run_loop.

One agent step (PLAN.md section 7):
  1. user message = memory file line + text, the last K action/result pairs, the observation
  2. call the model
  3. parse the reply
  4. apply the memory ops (all or nothing against the limit)
  5. hand the action to the run loop, which applies it to the world and logs everything

With a long-term file (longterm_chars > 0, see agent/lineage.py) the reply may also carry
"longterm" ops for it, applied the same way against its own limit, and finish() makes one last
call when the run is over so the agent can edit it before the next generation.
"""
from __future__ import annotations

import re
from pathlib import Path

from tinyworld.llm import LLMClient, ModelSpec, get_model, make_client
from tinyworld.llm.registry import DEFAULT_MODELS_PATH

from .memory import MemoryFile
from .parser import UNREADABLE, WAIT_ONE, parse_reflection, parse_reply
from .prompt import REFLECTION, build_system_prompt, build_user_message, describe_action

MEMORY_REJECTED = "Memory edit rejected. It was {n} characters over the limit."
LONGTERM_REJECTED = "Long-term edit rejected. It was {n} characters over the limit."
# Added when the file is close to full, so the agent learns appending cannot fit and that
# replace or rewrite can shorten it (in runs/haiku_4nights_g2 it kept appending, 182 rejections).
FILE_ROOM = (" The {file} file has {free} of {limit} characters free. Append makes it longer; "
             "replace with shorter text or rewrite can make it shorter.")
LONGTERM_ROOM = FILE_ROOM.replace("{file}", "long-term")
MEMORY_ROOM = FILE_ROOM.replace("{file}", "memory")
# memory_plain "append": each line added to the memory file starts with the world step it was
# written at, so the file is a timeline the agent can read rates and order from.
STAMP = "[step {t}] "
_STAMP_RE = re.compile(r"^\[step \d+\] ")
WIPE_OP = {"op": "wipe", "reason": "death"}


class LLMController:
    name = "llm"

    def __init__(self, client: LLMClient, spec: ModelSpec, memory_chars: int = 2000, history_window: int = 3,
                 on_death: str = "respawn_keep_memory", max_tokens: int | None = None, models_file: str | None = None,
                 longterm_chars: int = 0, longterm_start: str = "", memory_plain: str = "append",
                 intro: str | None = None, persona: str | None = None):
        self.intro, self.persona = intro, persona      # multi-agent: first line and character, if any
        if memory_plain not in ("append", "rewrite"):
            raise ValueError(f"memory_plain must be append or rewrite, not {memory_plain!r}")
        self.memory_plain = memory_plain
        self.client = client
        self.spec = spec
        self.memory_chars = int(memory_chars)
        self.history_window = int(history_window)
        self.on_death = on_death
        self.max_tokens = int(max_tokens or spec.max_tokens)
        self.models_file = models_file
        self.memory = MemoryFile(self.memory_chars)
        self.longterm_chars = int(longterm_chars or 0)
        self.longterm = MemoryFile(self.longterm_chars, longterm_start or "")
        self.rejected_longterm = 0
        self.history: list[tuple[str, str]] = []
        self.i = 0                                  # agent step, same count as the run loop's i
        self.parse_fails = 0
        self.rejected_edits = 0
        self.deaths = 0
        self.total_cost_usd = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._system: str | None = None
        self._last_action: dict = dict(WAIT_ONE)
        self._wiped = False                         # a wipe happened since the last memory record

    # ------------------------------------------------------------ config

    @property
    def memory_limit(self) -> int:
        return self.memory_chars

    @property
    def memory_on(self) -> bool:
        return self.memory_chars > 0

    @property
    def longterm_on(self) -> bool:
        return self.longterm_chars > 0

    def longterm_start_record(self) -> dict | None:
        """longterm.jsonl line 0: the file as the run starts. None when the long-term file is off."""
        if not self.longterm_on:
            return None
        t = self.longterm.text
        return {"ops": [], "accepted": True, "over_by": 0, "text": t, "chars": len(t), "limit": self.longterm_chars}

    def config_extras(self) -> dict:
        """Merged into config.yaml by the runner."""
        return {"model": self.spec.name, "model_id": self.spec.model, "provider": self.spec.provider,
                "memory_chars": self.memory_chars, "history_window": self.history_window,
                "memory_plain": self.memory_plain,
                **({"longterm_chars": self.longterm_chars} if self.longterm_on else {}),
                "max_tokens": self.max_tokens, "models_file": self.models_file or str(DEFAULT_MODELS_PATH),
                "llm_settings": self.client.settings(),
                "prices_per_m": {"input": self.spec.input_per_m, "output": self.spec.output_per_m,
                                 "cache_read": self.spec.cache_read_per_m, "cache_write": self.spec.cache_write_per_m}}

    def system_prompt(self, world) -> str:
        if self._system is None:
            self._system = build_system_prompt(world, self.history_window, self.memory_chars, self.longterm_chars,
                                               self.memory_plain, self.intro, self.persona)
        return self._system

    def user_message(self, observation: str) -> str:
        mem = self.memory.text if self.memory_on else None
        lt = self.longterm.text if self.longterm_on else None
        return build_user_message(mem, self.memory_chars, self.history, self.history_window, observation,
                                  lt, self.longterm_chars)

    # ------------------------------------------------------------ interface

    def act(self, observation: str, world) -> dict:
        self.i += 1
        if getattr(self.client, "needs_world", False):
            self.client.world = world
        system, user = self.system_prompt(world), self.user_message(observation)
        reply = self.client.complete(system, user, self.max_tokens)
        parsed = parse_reply(reply.text, self.memory_plain)
        cost = self.spec.cost_usd(reply)
        self.total_cost_usd += cost
        self.total_input_tokens += reply.input_tokens
        self.total_output_tokens += reply.output_tokens

        events: list[dict] = []
        notices: list[str] = []
        out: dict = {"raw_reply": reply.text, "thought": parsed.thought, "parse_ok": parsed.ok,
                     "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens,
                     "latency_s": round(reply.latency_s, 4), "cost_usd": cost,
                     "memory_chars_used": self.memory.chars if self.memory_on else 0, "memory_rejected": False}
        if not parsed.ok:
            self.parse_fails += 1
            notices.append(UNREADABLE)
            events.append({"type": "parse_fail", "detail": {"error": parsed.error, "chars": len(reply.text)}})

        ops = parsed.memory_ops if (parsed.ok and self.memory_on) else []
        if self.memory_plain == "append":
            ops = self.stamp_appends(ops, world.t)
        if ops or self._wiped:
            res = self.memory.apply(ops, self.i)
            if not res.accepted:
                self.rejected_edits += 1
                out["memory_rejected"] = True
                notices.append(self.rejected_notice(MEMORY_REJECTED, MEMORY_ROOM, res.over_by,
                                                    self.memory_chars, self.memory.chars))
                events.append({"type": "memory_rejected", "detail": {"over_by": res.over_by, "ops": len(ops)}})
            record = res.record()
            if self._wiped:
                record["ops"] = [dict(WIPE_OP)] + record["ops"]
                self._wiped = False
            out["memory"] = record
            out["memory_chars_used"] = self.memory.chars

        lt_ops = parsed.longterm_ops if (parsed.ok and self.longterm_on) else []
        if lt_ops:
            res = self.longterm.apply(lt_ops, self.i)
            if not res.accepted:
                self.rejected_longterm += 1
                out["longterm_rejected"] = True
                notices.append(self.longterm_rejected_notice(res.over_by))
                events.append({"type": "longterm_rejected", "detail": {"over_by": res.over_by, "ops": len(lt_ops)}})
            out["longterm"] = res.record()
        if notices:
            world.set_notice(" ".join(notices))

        action = parsed.action if parsed.ok else dict(WAIT_ONE)
        self._last_action = action
        out["action"] = action
        if events:
            out["events"] = events
        return out

    def on_result(self, result, world) -> None:
        self.history.append((describe_action(self._last_action), result.text))
        if result.died:
            self.deaths += 1
            if self.on_death == "respawn_wipe_memory" and self.memory_on and self.memory.chars > 0:
                self.memory.wipe(self.i)
                self._wiped = True

    def finish(self, world) -> dict | None:
        """The run is over: one last call so the agent can edit its long-term file. Returns the
        longterm.jsonl line for it (with the reply and its cost), or None when the file is off."""
        if not self.longterm_on:
            return None
        if getattr(self.client, "needs_world", False):
            self.client.world = world
        user = self.user_message(world.observe()) + "\n\n" + REFLECTION
        reply = self.client.complete(self.system_prompt(world), user, self.max_tokens)
        parsed = parse_reflection(reply.text)
        cost = self.spec.cost_usd(reply)
        self.total_cost_usd += cost
        self.total_input_tokens += reply.input_tokens
        self.total_output_tokens += reply.output_tokens
        res = self.longterm.apply(parsed.longterm_ops if parsed.ok else [], self.i + 1)
        replies = [reply]
        if not res.accepted:
            # One more try, told why: a rejected reflection would leave the lesson unwritten.
            self.rejected_longterm += 1
            retry = user + "\n\n" + self.longterm_rejected_notice(res.over_by)
            reply = self.client.complete(self.system_prompt(world), retry, self.max_tokens)
            replies.append(reply)
            parsed = parse_reflection(reply.text)
            cost += self.spec.cost_usd(reply)
            self.total_cost_usd += self.spec.cost_usd(reply)
            self.total_input_tokens += reply.input_tokens
            self.total_output_tokens += reply.output_tokens
            res = self.longterm.apply(parsed.longterm_ops if parsed.ok else [], self.i + 1)
            if not res.accepted:
                self.rejected_longterm += 1
        rec = {**res.record(), "reflection": True, "parse_ok": parsed.ok, "thought": parsed.thought,
               "raw_reply": reply.text, "input_tokens": sum(r.input_tokens for r in replies),
               "output_tokens": sum(r.output_tokens for r in replies), "cost_usd": cost}
        if len(replies) > 1:
            rec["attempts"] = len(replies)
            rec["first_raw_reply"] = replies[0].text
        return rec

    def longterm_rejected_notice(self, over_by: int) -> str:
        return self.rejected_notice(LONGTERM_REJECTED, LONGTERM_ROOM, over_by, self.longterm_chars, self.longterm.chars)

    @staticmethod
    def rejected_notice(rejected: str, room: str, over_by: int, limit: int, used: int) -> str:
        """The rejection, plus how much is free and what shortens the file when under a quarter is free."""
        text = rejected.format(n=over_by)
        if limit - used < limit // 4:
            text += room.format(free=limit - used, limit=limit)
        return text

    def stamp_appends(self, ops: list, t: int) -> list:
        """Appends become one op per line, each starting with [step t]. A line already in the
        file (stamps ignored) is skipped, so a model that resends its notes does not double them."""
        have = {_STAMP_RE.sub("", x).strip() for x in self.memory.text.split("\n")}
        out = []
        for op in ops:
            if not (isinstance(op, dict) and op.get("op") == "append" and isinstance(op.get("text"), str)):
                out.append(op)
                continue
            for line in op["text"].split("\n"):
                bare = _STAMP_RE.sub("", line).strip()
                if bare and bare not in have:
                    have.add(bare)
                    out.append({"op": "append", "text": STAMP.format(t=t) + bare})
        return out

    def replay_longterm(self, record: dict) -> None:
        """Resume: put the long-term file back to a logged version."""
        if self.longterm_on:
            if not record.get("accepted", True):
                self.rejected_longterm += 1
            self.longterm.set(record.get("text", ""), self.i)

    def replay(self, observation: str, world, step_record: dict, memory_record: dict | None) -> None:
        """Resume: rebuild memory, history, counters, and the pending notice with no model call."""
        self.i += 1
        if getattr(self.client, "needs_world", False):
            self.client.world = world
            if hasattr(self.client, "replay"):
                self.client.replay(observation, world, step_record)
        if not step_record.get("parse_ok", True):
            self.parse_fails += 1
            world.set_notice(UNREADABLE)
        if memory_record is not None and self.memory_on:
            if not memory_record.get("accepted", True):
                self.rejected_edits += 1
                world.set_notice(self.rejected_notice(MEMORY_REJECTED, MEMORY_ROOM, memory_record.get("over_by", 0),
                                                      self.memory_chars, len(memory_record.get("text", ""))))
            self.memory.set(memory_record.get("text", ""), self.i)
        self.total_cost_usd += float(step_record.get("cost_usd", 0.0) or 0.0)
        self.total_input_tokens += int(step_record.get("input_tokens", 0) or 0)
        self.total_output_tokens += int(step_record.get("output_tokens", 0) or 0)
        self._last_action = step_record.get("action", dict(WAIT_ONE))


def make_llm_controller(model: str, memory_chars: int = 2000, history_window: int = 3,
                        on_death: str = "respawn_keep_memory", seed: int = 0, models_file: str | Path | None = None,
                        max_tokens: int | None = None, client: LLMClient | None = None,
                        longterm_chars: int = 0, longterm_start: str = "", memory_plain: str = "append",
                        intro: str | None = None, persona: str | None = None) -> LLMController:
    spec = get_model(model, models_file)
    client = client or make_client(spec, seed=seed)
    return LLMController(client, spec, memory_chars, history_window, on_death, max_tokens,
                         models_file=str(models_file) if models_file else None,
                         longterm_chars=longterm_chars, longterm_start=longterm_start, memory_plain=memory_plain,
                         intro=intro, persona=persona)


def from_config(config: dict, client: LLMClient | None = None) -> LLMController:
    """Build the controller a stored run config describes (used on resume)."""
    return make_llm_controller(config["model"], config.get("memory_chars", 0), config.get("history_window", 3),
                               config.get("on_death", "respawn_keep_memory"), config.get("seed", 0),
                               config.get("models_file"), config.get("max_tokens"), client=client,
                               longterm_chars=config.get("longterm_chars", 0) or 0,
                               longterm_start=config.get("longterm_start", "") or "",
                               memory_plain=config.get("memory_plain") or "append",
                               persona=config.get("persona"))
