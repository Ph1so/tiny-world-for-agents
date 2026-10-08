"""Pull the JSON object out of a model reply.

Tolerates code fences, text before and after the object, and a few stray characters. A reply
that gives no object with an "action" dict inside is a parse failure. The caller turns that into
a one step wait and the "Your reply could not be read." notice.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

WAIT_ONE = {"name": "wait", "steps": 1}
UNREADABLE = "Your reply could not be read."

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)


@dataclass
class Parsed:
    ok: bool
    thought: str = ""
    memory_ops: list = field(default_factory=list)
    action: dict = field(default_factory=lambda: dict(WAIT_ONE))
    error: str | None = None


def normalize_memory(value) -> list:
    """Turn the reply's "memory" field into a list of documented op dicts.

    The schema (PLAN.md section 7) is a list of op objects, but real models often ignore it
    and just emit their notes as text. We coerce the common shapes so the edit is not silently
    lost, and so the logged ops always conform to docs/INTERFACES.md:
      - a bare string                  -> one rewrite to that string
      - a list where every item is str -> one rewrite to the items joined by newlines
                                           (models that emit a full snapshot each step, which is
                                            what we see in practice)
      - a list of op dicts             -> used as-is (the documented form)
      - a mixed list                   -> op dicts kept, bare strings become appends
      - a single op dict               -> wrapped in a list
    See docs/DECISIONS.md "Memory coercion".
    """
    if isinstance(value, str):
        return [{"op": "rewrite", "text": value}]
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    if value and all(isinstance(x, str) for x in value):
        return [{"op": "rewrite", "text": "\n".join(value)}]
    ops = []
    for x in value:
        if isinstance(x, dict):
            ops.append(x)
        elif isinstance(x, str):
            ops.append({"op": "append", "text": x})
    return ops


def _candidates(text: str):
    """Strings that might hold the object, most likely first."""
    t = text.strip()
    yield t
    for m in _FENCE.finditer(t):
        yield m.group(1).strip()
    stripped = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t)
    if stripped != t:
        yield stripped


def _objects(s: str):
    """Every JSON object that starts at some '{' in s, in order. Trailing text is allowed."""
    dec = json.JSONDecoder()
    start = s.find("{")
    while start != -1:
        try:
            obj, _end = dec.raw_decode(s, start)
            if isinstance(obj, dict):
                yield obj
        except json.JSONDecodeError:
            pass
        start = s.find("{", start + 1)


def extract_object(text: str) -> dict | None:
    """The first JSON object with an "action" key, else the first object, else None."""
    first: dict | None = None
    for cand in _candidates(text):
        for obj in _objects(cand):
            if isinstance(obj.get("action"), dict):
                return obj
            if first is None:
                first = obj
    return first


def parse_reply(text: str) -> Parsed:
    if not isinstance(text, str) or not text.strip():
        return Parsed(False, error="empty reply")
    obj = extract_object(text)
    if obj is None:
        return Parsed(False, error="no JSON object")
    action = obj.get("action")
    if not isinstance(action, dict) or not isinstance(action.get("name"), str):
        return Parsed(False, error="no action object with a name")
    thought = obj.get("thought", "")
    if not isinstance(thought, str):
        thought = json.dumps(thought)
    ops = normalize_memory(obj.get("memory", []))
    return Parsed(True, thought=thought, memory_ops=ops, action=action)
