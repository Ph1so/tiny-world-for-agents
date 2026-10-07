"""The system prompt (PLAN.md section 7, used word for word) and the user message.

The only things filled in are K, N, and the action lines. The action lines are built from the
world's name mapping and config, so alien mode shows alien names and no name is a fixed string.
"""
from __future__ import annotations

import json

SYSTEM_TEMPLATE = """You are in a world. The world moves forward each time you act.

Each step you are shown {memory_clause}your last {K} actions with their results, and what you can observe right now. You do not remember anything else from earlier steps.
{memory_paragraph}
Actions:
{action_lines}

Reply with one JSON object and nothing else:
{reply_line}"""

MEMORY_PARAGRAPH = ("\nYour memory file holds at most {N} characters. You may edit it every step. "
                    "An edit that would go over the limit is rejected and the file stays as it was.\n")

REPLY_WITH_MEMORY = '{"thought": "...", "memory": [...], "action": {...}}'
REPLY_NO_MEMORY = '{"thought": "...", "action": {...}}'

MEMORY_LINE = "memory file ({used} of {limit} characters used)"
HISTORY_HEADER = "last {k} actions:"
HISTORY_NONE = "none yet"
OBSERVATION_HEADER = "observation:"

DIRS = ["north", "south", "east", "west", "up", "down"]


def action_lines(world) -> str:
    """One line per action, mechanical wording only, names taken from the world's display map."""
    c = world.cfg
    dirs = " | ".join(f'"{d}"' for d in DIRS)
    ex_craft = json.dumps({world.dn("dirt"): 2, world.dn("sand"): 1})      # a shape example, not a recipe
    ex_place = json.dumps(world.dn("dirt"))
    lines = [
        f'move: {{"name": "move", "dir": {dirs}, "steps": 1 to 8}}',
        f'mine: {{"name": "mine", "x": X, "y": Y, "z": Z}}  a cell within {c.reach} cells',
        f'place: {{"name": "place", "item": {ex_place}, "x": X, "y": Y, "z": Z}}  an item from the inventory into an empty cell within {c.reach} cells',
        f'craft: {{"name": "craft", "items": {ex_craft}}}  item names from the inventory with counts',
        f'eat: {{"name": "eat", "item": {ex_place}}}  an item from the inventory',
        f'attack: {{"name": "attack", "id": ID}}  a creature within {c.attack_reach} cells',
        'wait: {"name": "wait", "steps": 1 to 8}',
    ]
    return "\n".join(lines)


def build_system_prompt(world, history_window: int, memory_chars: int) -> str:
    if memory_chars > 0:
        return SYSTEM_TEMPLATE.format(memory_clause="your memory file, ", K=history_window,
                                      memory_paragraph=MEMORY_PARAGRAPH.format(N=memory_chars),
                                      action_lines=action_lines(world), reply_line=REPLY_WITH_MEMORY)
    return SYSTEM_TEMPLATE.format(memory_clause="", K=history_window, memory_paragraph="",
                                  action_lines=action_lines(world), reply_line=REPLY_NO_MEMORY)


def build_user_message(memory_text: str | None, memory_limit: int, history: list[tuple[str, str]],
                       history_window: int, observation: str) -> str:
    """memory_text None means memory is off (size 0) and the memory block is left out."""
    parts: list[str] = []
    if memory_text is not None:
        parts.append(MEMORY_LINE.format(used=len(memory_text), limit=memory_limit))
        parts.append(memory_text)
        parts.append("")
    parts.append(HISTORY_HEADER.format(k=history_window))
    shown = history[-history_window:] if history_window > 0 else []
    if shown:
        for n, (action, result) in enumerate(shown, start=1 + len(history) - len(shown)):
            parts.append(f"{n}. {action} -> {result}")
    else:
        parts.append(HISTORY_NONE)
    parts.append("")
    parts.append(OBSERVATION_HEADER)
    parts.append(observation)
    return "\n".join(parts)


def describe_action(action) -> str:
    """One line for the history, exactly the action that was sent."""
    try:
        return json.dumps(action, separators=(", ", ": "))
    except (TypeError, ValueError):
        return str(action)
