"""A shared clock for several agents in one world.

The world only changes inside Engine.tick(), which one thread calls. Agents never touch the
world: they submit an action (submit) and later collect its result (results of tick). So there
are no data races and nothing to lock; what is left are game conflicts, settled by rules in
World (random order each step, swapping places, damage at the end of the step).

Each action is a generator from World.activity(): it does one world step's worth of work and
yields. tick() does, in a fresh random order of the agents:

  1. start the submitted action of every agent with one waiting (an agent busy with another
     action has that one cut short), running it up to its first yield;
  2. advance the world one step (creatures, weather, vitals, agent-on-agent damage);
  3. resume every running action up to its next yield, or to its end.

For one agent stepped back to back this is exactly World.step(), which the tests check. How the
caller paces tick() (a wall clock, or waiting for every idle agent) is up to the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import text as T
from .body import Body
from .world import World


@dataclass
class Result:
    agent: int
    text: str
    valid: bool
    desc: str
    action: dict | None
    t_start: int
    t_end: int
    died: str | None


@dataclass
class _Slot:
    body: Body
    inbox: dict | None = None
    activity: object = None
    action: dict | None = None
    t0: int = 0
    done: list = field(default_factory=list)       # finished (value, action, t0), reported after the step


class Engine:
    def __init__(self, world: World):
        self.w = world
        self.slots: dict[int, _Slot] = {}
        self._order_rng = np.random.default_rng([world.seed, 0x0DE2])

    # ------------------------------------------------------------ agents

    def add_agent(self, name: str | None = None) -> int:
        b = self.w.add_body(name)
        self.slots[b.id] = _Slot(b)
        return b.id

    def submit(self, agent: int, action: dict) -> None:
        """The agent's next action. A second submit before it starts replaces the first."""
        self.slots[agent].inbox = action

    def idle(self, agent: int) -> bool:
        """Alive, with nothing running and nothing waiting to start."""
        s = self.slots[agent]
        return s.body.alive and s.activity is None and s.inbox is None

    def observe(self, agent: int) -> str:
        self.w.me = self.slots[agent].body
        return self.w.observe()

    def alive(self) -> list[int]:
        return [i for i, s in self.slots.items() if s.body.alive]

    # -------------------------------------------------------------- tick

    def tick(self) -> tuple[list[Result], list[dict], list[dict]]:
        """One world step. Returns (finished actions, world deltas, events) for this step."""
        w = self.w
        w._deltas, w._events = [], []
        if w.done:
            return [], [], []
        live = [s for s in self.slots.values() if s.body.alive]
        order = [live[int(i)] for i in self._order_rng.permutation(len(live))]
        for s in order:
            if s.inbox is not None:
                if s.activity is not None:
                    self._cut_short(s)
                self._start(s)
        w._tick()
        for s in order:
            if s.activity is not None and s.body.alive:
                self._advance(s)
        results = []
        for s in order:
            for value, action, t0 in s.done:
                results.append(self._finish(s, value, action, t0))
            s.done = []
        return results, w._deltas, w._events

    def _start(self, s: _Slot) -> None:
        w, b = self.w, s.body
        w.me = b
        b._hurt, b._died = False, None
        if b._notice_shown:
            b._notice, b._notice_shown = None, False
        s.action, s.inbox, s.t0 = s.inbox, None, w.t
        b.decisions += 1
        s.activity = w.activity(s.action)
        self._advance(s)

    def _advance(self, s: _Slot) -> None:
        self.w.me = s.body
        try:
            next(s.activity)
        except StopIteration as e:
            s.done.append((e.value, s.action, s.t0))
            s.activity = None

    def _cut_short(self, s: _Slot) -> None:
        self.w.me = s.body
        s.activity.close()
        s.activity = None
        name = s.action.get("name") if isinstance(s.action, dict) else None
        s.done.append(((T.CUT_SHORT.strip(), True, str(name)), s.action, s.t0))

    def _finish(self, s: _Slot, value, action, t0) -> Result:
        w, b = self.w, s.body
        w.me = b
        text, valid, desc = value
        w._check_stuck()
        text += "".join(b._hits)
        b._hits = []
        b.last_action, b.last_result = desc, text
        return Result(b.id, text, valid, desc, action, t0, max(w.t, t0 + 1), b._died)
