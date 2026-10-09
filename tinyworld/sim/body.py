"""One agent's body: everything about an agent that is not shared world state.

The World holds a list of bodies and a current one, `world.me`. Every name in BODY_FIELDS read
or written on the World goes to `world.me`, so the action and vitals code reads `self.pos`,
`self.inv` as it did when there was only one agent. Code that works on several bodies (the tick,
creatures, the multi-agent engine) sets `world.me` before touching a body's fields.
"""
from __future__ import annotations

from collections import deque

BODY_FIELDS = (
    "pos", "spawn", "inv", "tools", "health", "food", "air", "bed",
    "_food_tick", "_starve_tick", "_heal_tick", "_hail_tick", "_vitals_log", "_last_hit",
    "made", "placed", "firsts", "deaths", "stuck",
    "last_action", "last_result", "_notice", "_notice_shown", "_death_notice",
    "_hits", "_hurt", "_died", "_cause", "_asleep",
)


class Body:
    def __init__(self, id: int | None = None, name: str | None = None):
        self.id = id                     # creature-namespace id, so others can attack it; None alone
        self.name = name
        self.alive = True                # False once dead for good (on_death end_run)
        self.pos: list[int] = [0, 0, 0]
        self.spawn: tuple[int, int, int] = (0, 0, 0)
        self.inv: dict[str, int] = {}
        self.tools: dict[str, int] = {}
        self.health = self.food = self.air = 0
        self.bed = None
        self._food_tick = self._starve_tick = self._heal_tick = self._hail_tick = 0
        self._vitals_log: deque = deque()
        self._last_hit = -10**9
        self.made: dict = {}
        self.placed: list[list] = []     # [block, [x, y, z]] for structures and crops it placed; kept through death
        self.firsts: dict[str, list[str]] = {"mine": [], "craft": [], "place": [], "eat": []}
        self.deaths = 0
        self.stuck = False
        self.last_action: str | None = None
        self.last_result: str | None = None
        self._notice: str | None = None
        self._notice_shown = False
        self._death_notice: str | None = None
        self._hits: list[str] = []
        self._hurt = False
        self._died: str | None = None
        self._cause = ""
        self._asleep = False
        # Multi-agent only.
        self.heard: list[str] = []       # lines said to or done to this agent since it last looked
        self.heading: str | None = None  # direction of a move in progress, for swapping places
        self.swapped_t = -1              # world step a partner moved this body by swapping
        self.decisions = 0               # actions started (the engine counts them)
        self.hit_decision = -1           # the decision during which a zombie last hit it


def forward_body_fields(cls) -> None:
    """Give cls a property per BODY_FIELDS name that reads and writes self.me."""
    for f in BODY_FIELDS:
        setattr(cls, f, property(lambda s, f=f: getattr(s.me, f), lambda s, v, f=f: setattr(s.me, f, v)))
