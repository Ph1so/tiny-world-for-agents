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

from .memory import MemoryFile, SectionedMemory
from .parser import UNREADABLE, WAIT_ONE, parse_plan, parse_reflection, parse_reply
from .plan import PLAN_CHARS, PLAN_SET, PLAN_UNREADABLE, Plan, values as plan_values
from .prompt import REFLECTION, build_system_prompt, build_user_message, describe_action, plan_request

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
PLAN_ACTION = {"name": "plan"}
PLANNING = ("off", "action", "triggers")


class LLMController:
    name = "llm"

    def __init__(self, client: LLMClient, spec: ModelSpec, memory_chars: int = 2000, history_window: int = 3,
                 on_death: str = "respawn_keep_memory", max_tokens: int | None = None, models_file: str | None = None,
                 longterm_chars: int = 0, longterm_start: str = "", memory_plain: str = "append",
                 intro: str | None = None, persona: str | None = None, memory_layout: str = "plain",
                 planning: str = "off", plan_chars: int = PLAN_CHARS, plan_wait: int = 1):
        if planning not in PLANNING:
            raise ValueError(f"planning must be one of {PLANNING}, not {planning!r}")
        # planning (agent/plan.py): "action" adds a plan slot and a plan action; "triggers" also
        # lets the agent set conditions for when it is asked to plan again. plan_wait is how many
        # world steps a planning turn takes (in real time the planner call's own latency adds).
        self.planning = planning
        self.plan = Plan(int(plan_chars or PLAN_CHARS), triggers=planning == "triggers")
        self.plan_wait = max(1, int(plan_wait or 1))
        self.plans_written = 0
        self._plan_turn: dict | None = None         # set while the action under way is a planning turn
        self.intro, self.persona = intro, persona      # multi-agent: first line and character, if any
        if memory_plain not in ("append", "rewrite"):
            raise ValueError(f"memory_plain must be append or rewrite, not {memory_plain!r}")
        if memory_layout not in ("plain", "sections"):
            raise ValueError(f"memory_layout must be plain or sections, not {memory_layout!r}")
        self.memory_plain = memory_plain
        self.memory_layout = memory_layout
        self.client = client
        self.spec = spec
        self.memory_chars = int(memory_chars)
        self.history_window = int(history_window)
        self.on_death = on_death
        self.max_tokens = int(max_tokens or spec.max_tokens)
        self.models_file = models_file
        # sections: GOAL / LESSONS / NOTES, lessons out of a rewrite's reach (agent/memory.py)
        self.memory = SectionedMemory(self.memory_chars) if memory_layout == "sections" else MemoryFile(self.memory_chars)
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

    @property
    def planning_on(self) -> bool:
        return self.planning != "off"

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
                **({"memory_layout": self.memory_layout} if self.memory_layout != "plain" else {}),
                **({"longterm_chars": self.longterm_chars} if self.longterm_on else {}),
                **({"planning": self.planning, "plan_chars": self.plan.limit, "plan_wait": self.plan_wait}
                   if self.planning_on else {}),
                "max_tokens": self.max_tokens, "models_file": self.models_file or str(DEFAULT_MODELS_PATH),
                "llm_settings": self.client.settings(),
                "prices_per_m": {"input": self.spec.input_per_m, "output": self.spec.output_per_m,
                                 "cache_read": self.spec.cache_read_per_m, "cache_write": self.spec.cache_write_per_m}}

    def system_prompt(self, world) -> str:
        if self._system is None:
            self._system = build_system_prompt(world, self.history_window, self.memory_chars, self.longterm_chars,
                                               self.memory_plain, self.intro, self.persona, self.memory_layout,
                                               self.planning, self.plan.limit)
        return self._system

    def user_message(self, observation: str, t: int = 0) -> str:
        mem = self.memory.text if self.memory_on else None
        lt = self.longterm.text if self.longterm_on else None
        return build_user_message(mem, self.memory_chars, self.history, self.history_window, observation,
                                  lt, self.longterm_chars, self.plan.render(t) if self.planning_on else None)

    # ------------------------------------------------------------ interface

    def act(self, observation: str, world) -> dict:
        self.i += 1
        if getattr(self.client, "needs_world", False):
            self.client.world = world
        system, user = self.system_prompt(world), self.user_message(observation, world.t)
        self._plan_turn = None
        if self.planning == "triggers" and self.plan.is_set:
            hit = self.plan.fired(plan_values(world, self.plan, self.deaths))
            if hit is not None:
                # A condition the agent set turned true: this turn is the planner call alone.
                return self.plan_turn(world, system, user, fired=hit.text)
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
        if self.planning_on and parsed.ok and str(action.get("name", "")).strip().lower() == "plan":
            # The agent chose to plan: a second call asks for the plan, and the turn is a wait.
            # Memory edits sent with the choice are applied above and shown to the planner call.
            user = self.user_message(observation, world.t)
            plan_out = self.plan_turn(world, system, user, fired=None, notices=notices)
            for k in ("input_tokens", "output_tokens", "cost_usd"):
                out[k] += plan_out[k]
            out["latency_s"] = round(out["latency_s"] + plan_out["latency_s"], 4)
            out["plan"], out["action"] = plan_out["plan"], plan_out["action"]
            out["events"] = events + plan_out["events"]
            return out
        self._last_action = action
        out["action"] = action
        if events:
            out["events"] = events
        return out

    def plan_turn(self, world, system: str, user: str, fired: str | None, notices: list[str] | None = None) -> dict:
        """One planner call. The reply replaces the plan, all or nothing (agent/plan.py). Returns
        a step output whose action is a wait of plan_wait steps and whose "plan" is the record
        that goes into steps.jsonl."""
        reply = self.client.complete(system, user + "\n\n" + plan_request(self.planning, fired), self.max_tokens)
        cost = self.spec.cost_usd(reply)
        self.total_cost_usd += cost
        self.total_input_tokens += reply.input_tokens
        self.total_output_tokens += reply.output_tokens
        obj = parse_plan(reply.text)
        before = self.plan.record() if self.plan.is_set else None
        res = self.plan.write(obj, world.t, plan_values(world, self.plan, self.deaths))
        if res.accepted:
            self.plans_written += 1
        notes = list(notices or []) + ([PLAN_UNREADABLE] if obj is None else res.notices)
        if notes:
            world.set_notice(" ".join(notes))
        thought = obj.get("thought", "") if isinstance(obj, dict) else ""
        record = {"cause": "condition" if fired else "action", "fired": fired, "accepted": res.accepted,
                  "error": "unreadable" if obj is None else res.error, "over_by": res.over_by,
                  **self.plan.record(), "text": self.plan.body(self.plan.goal, self.plan.steps, self.plan.conditions)
                  if self.plan.is_set else "", "limit": self.plan.limit, "before": before,
                  "thought": thought if isinstance(thought, str) else "", "raw_reply": reply.text,
                  "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens,
                  "latency_s": round(reply.latency_s, 4), "cost_usd": cost}
        record["chars"] = len(record["text"])
        self._plan_turn = {"accepted": res.accepted}
        self._last_action = {"name": "wait", "steps": self.plan_wait}
        detail = {"cause": record["cause"], "accepted": res.accepted, "goal": self.plan.goal,
                  "steps": len(self.plan.steps), "conditions": [c.text for c in self.plan.conditions]}
        if fired:
            detail["fired"] = fired
        return {"raw_reply": reply.text, "thought": record["thought"], "parse_ok": obj is not None,
                "input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens,
                "latency_s": round(reply.latency_s, 4), "cost_usd": cost,
                "memory_chars_used": self.memory.chars if self.memory_on else 0, "memory_rejected": False,
                "plan": record, "action": dict(self._last_action), "events": [{"type": "plan", "detail": detail}]}

    def history_pair(self, action: dict, result_text: str, plan: dict | None) -> tuple[str, str]:
        """The history line for a step. A planning turn reads as the plan action, not the wait
        the world was given."""
        if plan is None:
            return describe_action(action), result_text
        said = PLAN_SET if plan.get("accepted") else "No plan was written."
        return describe_action(PLAN_ACTION), f"{said} {result_text}".strip()

    def on_result(self, result, world) -> None:
        self.history.append(self.history_pair(self._last_action, result.text, self._plan_turn))
        self._plan_turn = None
        if result.died:
            self.deaths += 1
            if self.on_death == "respawn_wipe_memory" and self.memory_on and self.memory.chars > 0:
                self.memory.wipe(self.i)
                self._wiped = True
            if self.on_death == "respawn_wipe_memory" and self.planning_on:
                self.plan.wipe()

    def finish(self, world) -> dict | None:
        """The run is over: one last call so the agent can edit its long-term file. Returns the
        longterm.jsonl line for it (with the reply and its cost), or None when the file is off."""
        if not self.longterm_on:
            return None
        if getattr(self.client, "needs_world", False):
            self.client.world = world
        user = self.user_message(world.observe(), world.t) + "\n\n" + REFLECTION
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
        self.replay_plan(step_record, world)

    def replay_plan(self, step_record: dict, world=None) -> None:
        """Resume: a logged planning turn puts its plan back (and marks the turn for the history)."""
        plan = step_record.get("plan")
        self._plan_turn = None
        if not (self.planning_on and isinstance(plan, dict)):
            return
        self._plan_turn = {"accepted": bool(plan.get("accepted"))}
        if plan.get("accepted"):
            self.plans_written += 1
            self.plan.restore(plan, plan_values(world, self.plan, self.deaths) if world is not None else None)


def make_llm_controller(model: str, memory_chars: int = 2000, history_window: int = 3,
                        on_death: str = "respawn_keep_memory", seed: int = 0, models_file: str | Path | None = None,
                        max_tokens: int | None = None, client: LLMClient | None = None,
                        longterm_chars: int = 0, longterm_start: str = "", memory_plain: str = "append",
                        intro: str | None = None, persona: str | None = None,
                        memory_layout: str = "plain", planning: str = "off", plan_chars: int = PLAN_CHARS,
                        plan_wait: int = 1) -> LLMController:
    spec = get_model(model, models_file)
    client = client or make_client(spec, seed=seed)
    return LLMController(client, spec, memory_chars, history_window, on_death, max_tokens,
                         models_file=str(models_file) if models_file else None,
                         longterm_chars=longterm_chars, longterm_start=longterm_start, memory_plain=memory_plain,
                         intro=intro, persona=persona, memory_layout=memory_layout,
                         planning=planning or "off", plan_chars=plan_chars or PLAN_CHARS, plan_wait=plan_wait or 1)


def from_config(config: dict, client: LLMClient | None = None) -> LLMController:
    """Build the controller a stored run config describes (used on resume)."""
    return make_llm_controller(config["model"], config.get("memory_chars", 0), config.get("history_window", 3),
                               config.get("on_death", "respawn_keep_memory"), config.get("seed", 0),
                               config.get("models_file"), config.get("max_tokens"), client=client,
                               longterm_chars=config.get("longterm_chars", 0) or 0,
                               longterm_start=config.get("longterm_start", "") or "",
                               memory_plain=config.get("memory_plain") or "append",
                               persona=config.get("persona"), memory_layout=config.get("memory_layout") or "plain",
                               planning=config.get("planning") or "off", plan_chars=config.get("plan_chars") or PLAN_CHARS,
                               plan_wait=config.get("plan_wait") or 1)
