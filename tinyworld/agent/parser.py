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
    longterm_ops: list = field(default_factory=list)
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


def normalize_longterm(value) -> list:
    """The "longterm" field. Same op dicts as memory, but plain text is always added, never a
    whole-file replacement: a bare string or a list of strings becomes appends.

    A model that sends only the line it wants to add would otherwise wipe the file, which is
    what happened in runs/haiku_4nights_g2 at agent step 241: one line replaced every recipe and
    lesson the lineage had. Replacing the whole file needs an explicit {"op": "rewrite"}. A
    model that resends the whole file as plain lines gets an over-limit rejection instead of
    duplicates, and the notice tells it so. See docs/DECISIONS.md.
    """
    if isinstance(value, str):
        return [{"op": "append", "text": value}] if value.strip() else []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    ops = []
    for x in value:
        if isinstance(x, dict):
            ops.append(x)
        elif isinstance(x, str) and x.strip():
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


ACTION_NAMES = {"move", "mine", "place", "craft", "eat", "attack", "wait", "store", "take", "drop"}
ACTION_ARGS = {"dir", "steps", "x", "y", "z", "item", "items", "id"}


def _clean_keys(obj: dict) -> dict:
    """Models sometimes emit `" action"` with stray whitespace inside the quotes."""
    return {(k.strip() if isinstance(k, str) else k): v for k, v in obj.items()}


def _is_bare_action(obj: dict) -> bool:
    return isinstance(obj.get("name"), str) and obj["name"].strip() in ACTION_NAMES and "action" not in obj


def extract_object(text: str) -> dict | None:
    """The first JSON object with an "action" key, else a salvaged one, else the first object."""
    first: dict | None = None
    bare_action: dict | None = None
    for cand in _candidates(text):
        for obj in _objects(cand):
            obj = _clean_keys(obj)
            if isinstance(obj.get("action"), dict):
                return obj
            if bare_action is None and _is_bare_action(obj):
                bare_action = obj
            if first is None:
                first = obj
    salvaged = _salvage_tool_call_style(text, bare_action)
    if salvaged is not None:
        return salvaged
    return first


# Some models drift into a function-calling style instead of plain JSON, e.g.
#   <parameter name="thought">...</parameter> <parameter name="memory">[...]</parameter>
#   <parameter="action">{"name": "craft", ...}</parameter> </invoke> ="thought": "...", "memory": [...]
#   <parameter name="name">move</parameter> <parameter name="dir">up</parameter>    (action fields split up)
#   <invoke: {"name": "move", "dir": "west", "steps": 1}                              (bare action object)
# The content is all there, only the wrapping is wrong. Pull the tagged fields out, read whatever
# bare `"key": value` pairs are left over as one object, and assemble an action from the pieces.
_PARAM = re.compile(r"<(?:invoke:)?parameter(?:-type)?\s*(?:name)?\s*=?\s*[\"']?([A-Za-z_]+)[\"']?\s*>(.*?)</parameter>", re.S)
_TAG = re.compile(r"</?(?:invoke|parameter|parameter-type|function_calls|antml:[a-z_]+)[^>]*>", re.S)


def _coerce_value(raw: str):
    raw = raw.strip()
    try:
        return json.loads(raw)                      # JSON object/array/string/number
    except json.JSONDecodeError:
        return raw                                  # bare text, take it as a string


def _salvage_tool_call_style(text: str, bare_action: dict | None = None) -> dict | None:
    params: dict = {}
    for key, raw in _PARAM.findall(text):
        key = key.strip()
        if key not in params:
            params[key] = _coerce_value(raw)

    fields: dict = {k: params[k] for k in ("thought", "memory", "longterm") if k in params}
    action = params.get("action")
    if not isinstance(action, dict):
        # a param whose value is itself an action object, under any key (e.g. <parameter="mine">{...})
        for v in params.values():
            if isinstance(v, dict) and _is_bare_action(v):
                action = v
                break
    if not isinstance(action, dict) and isinstance(params.get("name"), str) and params["name"].strip() in ACTION_NAMES:
        # the action's fields were split into separate tags
        action = {"name": params["name"].strip()}
        for k in ACTION_ARGS:
            if k in params:
                action[k] = params[k]
    if not isinstance(action, dict) and bare_action is not None:
        action = bare_action

    rest = _PARAM.sub(" ", text)
    rest = _TAG.sub(" ", rest).strip().lstrip("=").strip()
    if rest:
        for cand in (rest, "{" + rest + "}", "{" + rest.rstrip(", ") + "}"):
            got = False
            for obj in _objects(cand):
                obj = _clean_keys(obj)
                for k in ("thought", "memory", "longterm"):
                    if k in obj and k not in fields:
                        fields[k] = obj[k]
                if not isinstance(action, dict):
                    if isinstance(obj.get("action"), dict):
                        action = obj["action"]
                    elif _is_bare_action(obj):
                        action = obj
                got = True
                break
            if got and isinstance(action, dict):
                break
    if isinstance(action, dict):
        fields["action"] = action
        return fields
    return None


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
    return Parsed(True, thought=thought, memory_ops=ops, longterm_ops=normalize_longterm(obj.get("longterm", [])),
                  action=action)


def parse_reflection(text: str) -> Parsed:
    """The end of run reply: {"thought": "...", "longterm": [...]}. No action is needed. ok is
    False only when no JSON object can be found at all."""
    if not isinstance(text, str) or not text.strip():
        return Parsed(False, error="empty reply")
    obj = None
    for cand in _candidates(text):
        for o in _objects(cand):
            o = _clean_keys(o)
            if "longterm" in o:
                obj = o
                break
            if obj is None:
                obj = o
        if obj is not None and "longterm" in obj:
            break
    if obj is None:
        return Parsed(False, error="no JSON object")
    thought = obj.get("thought", "")
    if not isinstance(thought, str):
        thought = json.dumps(thought)
    return Parsed(True, thought=thought, longterm_ops=normalize_longterm(obj.get("longterm", [])))
