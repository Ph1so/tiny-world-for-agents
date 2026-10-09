"""The plan slot: a goal and steps the agent writes for itself, and conditions it sets for when to
write them again (controller option `planning`, DECISIONS 125).

    off        no plan (the default; prompts and replies are unchanged)
    action     a "plan" action. Choosing it costs a turn: the agent is asked, in a separate reply,
               for a goal and steps. The plan is shown every step and changes only this way.
    triggers   the same, and with the plan the agent may list conditions ("replan_when"). When one
               becomes true the agent is asked for a new plan before its next action.

The rule for everything here: the harness gives the means to plan and never says when to plan or
what about. No condition is built in. The names a condition can use are the numbers the
observation already shows (taken from world.vitals(), whatever they are), three counters, and
item names. A condition fires on the step it turns from false to true, so one that is already
true when the plan is written waits until it has been false once.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PLAN_CHARS = 1000           # goal, steps and conditions together, as shown to the agent
MAX_CONDITIONS = 5
COUNTERS = ("step", "steps_since_plan", "deaths")
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
       ">=": lambda a, b: a >= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}

_COND = re.compile(r"^\s*(.+?)\s*(<=|>=|==|!=|<|>|=)\s*(-?\d+(?:\.\d+)?)\s*$")

PLAN_NONE = "plan: none"
PLAN_HEADER = "plan (written at step {t}, {n} steps ago):"
PLAN_GOAL = "goal: {goal}"
PLAN_WHEN = "replan when: {conds}"

PLAN_SET = "Plan written."
PLAN_REJECTED = "Plan rejected. It was {n} characters over the limit of {limit}. The plan stays as it was."
PLAN_UNREADABLE = "Your plan could not be read. The plan stays as it was."
PLAN_NO_GOAL = "Your plan had no goal. The plan stays as it was."
COND_UNREADABLE = 'Not understood, left out: {bad}. A condition is a name, one of < <= > >= == !=, and a number.'
COND_TOO_MANY = "Only the first {n} conditions were kept."


@dataclass
class Condition:
    name: str               # as the agent wrote it (lower case, single spaces)
    op: str
    value: float
    armed: bool = False     # seen false since the plan was written; only an armed condition fires

    @property
    def text(self) -> str:
        v = int(self.value) if float(self.value).is_integer() else self.value
        return f"{self.name} {self.op} {v}"


def parse_condition(raw) -> Condition | None:
    """ "food < 8", or {"name": "food", "op": "<", "value": 8}. None when it cannot be read."""
    if isinstance(raw, dict):
        name, op, value = raw.get("name", raw.get("field")), raw.get("op"), raw.get("value")
        if not isinstance(name, str) or isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        raw = f"{name} {op} {value}"
    if not isinstance(raw, str):
        return None
    m = _COND.match(raw)
    if not m:
        return None
    name = " ".join(m.group(1).lower().replace("_", " ").split())
    if name.replace(" ", "_") in COUNTERS:
        name = name.replace(" ", "_")
    op = "==" if m.group(2) == "=" else m.group(2)
    return Condition(name, op, float(m.group(3)))


@dataclass
class PlanResult:
    accepted: bool
    notices: list[str] = field(default_factory=list)
    over_by: int = 0
    error: str | None = None


class Plan:
    def __init__(self, limit: int = PLAN_CHARS, triggers: bool = False):
        self.limit, self.triggers = int(limit), triggers
        self.goal: str = ""
        self.steps: list[str] = []
        self.conditions: list[Condition] = []
        self.set_t: int | None = None             # world step the plan was written at
        self.deaths_at_set = 0

    @property
    def is_set(self) -> bool:
        return self.set_t is not None

    @staticmethod
    def body(goal: str, steps: list[str], conditions: list[Condition]) -> str:
        lines = [PLAN_GOAL.format(goal=goal)] + [f"{n}. {s}" for n, s in enumerate(steps, 1)]
        if conditions:
            lines.append(PLAN_WHEN.format(conds="; ".join(c.text for c in conditions)))
        return "\n".join(lines)

    def render(self, t: int) -> str:
        """The block shown in the user message every step."""
        if not self.is_set:
            return PLAN_NONE
        return PLAN_HEADER.format(t=self.set_t, n=max(0, t - self.set_t)) + "\n" + self.body(
            self.goal, self.steps, self.conditions)

    def write(self, obj, t: int, values: dict | None = None) -> PlanResult:
        """Replace the plan with the planner reply's object. All or nothing: a plan that is over
        the limit or has no goal leaves the old one in place. values (see `values`) arms the new
        conditions that are false right now."""
        if not isinstance(obj, dict):
            return PlanResult(False, [PLAN_UNREADABLE], error="no JSON object")
        goal = obj.get("goal")
        goal = " ".join(goal.split()) if isinstance(goal, str) else ""
        if not goal:
            return PlanResult(False, [PLAN_NO_GOAL], error="no goal")
        raw_steps = obj.get("steps", [])
        if isinstance(raw_steps, str):
            raw_steps = [s for s in raw_steps.split("\n")]
        steps = [re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", " ".join(str(s).split()))
                 for s in (raw_steps if isinstance(raw_steps, list) else []) if isinstance(s, (str, int, float))]
        steps = [s for s in steps if s]
        notices: list[str] = []
        conditions: list[Condition] = []
        if self.triggers:
            raw_conds = obj.get("replan_when", [])
            if isinstance(raw_conds, (str, dict)):
                raw_conds = [raw_conds]
            bad = []
            for rc in raw_conds if isinstance(raw_conds, list) else []:
                c = parse_condition(rc)
                if c is None:
                    bad.append(str(rc)[:60])
                elif all(c.text != have.text for have in conditions):
                    conditions.append(c)
            if bad:
                notices.append(COND_UNREADABLE.format(bad="; ".join(bad)))
            if len(conditions) > MAX_CONDITIONS:
                conditions = conditions[:MAX_CONDITIONS]
                notices.append(COND_TOO_MANY.format(n=MAX_CONDITIONS))
        over = len(self.body(goal, steps, conditions)) - self.limit
        if over > 0:
            return PlanResult(False, [PLAN_REJECTED.format(n=over, limit=self.limit)], over_by=over, error="over limit")
        self.goal, self.steps, self.conditions, self.set_t = goal, steps, conditions, t
        self.deaths_at_set = int((values or {}).get("deaths", 0))
        self.arm(values or {})
        return PlanResult(True, notices)

    def wipe(self) -> None:
        self.goal, self.steps, self.conditions, self.set_t = "", [], [], None

    # ------------------------------------------------------------ conditions

    @staticmethod
    def truth(c: Condition, values: dict) -> bool | None:
        """None when there is no such number. (With `values` below an unknown name reads as an
        item held 0 times.)"""
        v = values.get(c.name)
        return None if v is None else bool(OPS[c.op](v, c.value))

    def arm(self, values: dict) -> None:
        for c in self.conditions:
            if self.truth(c, values) is False:
                c.armed = True

    def fired(self, values: dict) -> Condition | None:
        """The first armed condition that is true now, if any. Arms the ones that are false."""
        hit = None
        for c in self.conditions:
            now = self.truth(c, values)
            if now is False:
                c.armed = True
            elif now and c.armed and hit is None:
                hit = c
        return hit

    # ------------------------------------------------------------ log and resume

    def record(self) -> dict:
        return {"goal": self.goal, "steps": list(self.steps), "replan_when": [c.text for c in self.conditions],
                "set_t": self.set_t, "deaths_at_set": self.deaths_at_set}

    def restore(self, record: dict, values: dict | None = None) -> None:
        """Resume: put back a logged plan (the `plan` object of a step with accepted true)."""
        self.goal, self.steps = record.get("goal", ""), list(record.get("steps", []))
        self.conditions = [c for c in (parse_condition(x) for x in record.get("replan_when", [])) if c]
        self.set_t = record.get("set_t")
        self.deaths_at_set = int(record.get("deaths_at_set", 0))
        self.arm(values or {})


def values(world, plan: Plan, deaths: int) -> dict:
    """Every number a condition may name, by the name the agent is shown: the body's vitals
    (whatever world.vitals() holds), the counters, and how many of each item it holds."""
    out: dict = {}
    for item, n in dict(world.inv).items():
        out[" ".join(str(world.dn(item)).lower().split())] = n
    out.update({str(k).lower(): v for k, v in world.vitals().items()})
    out["step"] = world.t
    out["steps_since_plan"] = world.t - plan.set_t if plan.is_set else 0
    out["deaths"] = deaths
    return _Zero(out)


class _Zero(dict):
    """An item the agent holds none of counts as 0, so "bread < 1" works with an empty hand.
    Names that are neither a vital nor a counter are read as items."""
    def get(self, key, default=None):
        return super().get(key, 0)
