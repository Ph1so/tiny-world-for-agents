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

# Long-term file (lineages). Only used when longterm_chars > 0; with it off the prompt is the
# PLAN.md section 7 text unchanged.
LONGTERM_PARAGRAPH = ("\nYour long-term file holds at most {L} characters. It carries over to your later runs, "
                      "which may take place in a different world.{memory_note} You may edit it every step with "
                      "the \"longterm\" field{edit_like}. An edit that would go over its limit is "
                      "rejected and the file stays as it was.\n")
LONGTERM_MEMORY_NOTE = " Your memory file starts empty in every run."
REPLY_LONGTERM_MEMORY = '{"thought": "...", "memory": [...], "longterm": [...], "action": {...}}'
REPLY_LONGTERM_ONLY = '{"thought": "...", "longterm": [...], "action": {...}}'
LONGTERM_LINE = "long-term file ({used} of {limit} characters used)"
REFLECTION = ("The run is over. This is the last edit of your long-term file before your next run.\n"
              "Reply with one JSON object and nothing else:\n"
              '{"thought": "...", "longterm": [...]}')

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
    chest = world.dn("chest")
    lines = [
        f'move: {{"name": "move", "dir": {dirs}, "steps": 1 to 8}}',
        f'mine: {{"name": "mine", "x": X, "y": Y, "z": Z}}  a cell within {c.reach} cells',
        f'place: {{"name": "place", "item": {ex_place}, "x": X, "y": Y, "z": Z}}  an item from the inventory into an empty cell within {c.reach} cells',
        f'craft: {{"name": "craft", "items": {ex_craft}}}  item names from the inventory with counts',
        f'eat: {{"name": "eat", "item": {ex_place}}}  an item from the inventory',
        f'attack: {{"name": "attack", "id": ID}}  a creature within {c.attack_reach} cells',
        'wait: {"name": "wait", "steps": 1 to 8}',
        f'store: {{"name": "store", "x": X, "y": Y, "z": Z, "items": {ex_craft}}}  items from the inventory into a {chest} within {c.reach} cells',
        f'take: {{"name": "take", "x": X, "y": Y, "z": Z, "items": {ex_craft}}}  items from a {chest} within {c.reach} cells into the inventory',
        f'drop: {{"name": "drop", "items": {ex_craft}}}  items from the inventory, gone for good',
    ]
    return "\n".join(lines)


def build_system_prompt(world, history_window: int, memory_chars: int, longterm_chars: int = 0) -> str:
    if longterm_chars > 0:
        mem = memory_chars > 0
        clause = ("your memory file, " if mem else "") + "your long-term file, "
        paragraph = (MEMORY_PARAGRAPH.format(N=memory_chars) if mem else "") + LONGTERM_PARAGRAPH.format(
            L=longterm_chars, memory_note=LONGTERM_MEMORY_NOTE if mem else "",
            edit_like=", the same way as the memory file" if mem else "")
        return SYSTEM_TEMPLATE.format(memory_clause=clause, K=history_window, memory_paragraph=paragraph,
                                      action_lines=action_lines(world),
                                      reply_line=REPLY_LONGTERM_MEMORY if mem else REPLY_LONGTERM_ONLY)
    if memory_chars > 0:
        return SYSTEM_TEMPLATE.format(memory_clause="your memory file, ", K=history_window,
                                      memory_paragraph=MEMORY_PARAGRAPH.format(N=memory_chars),
                                      action_lines=action_lines(world), reply_line=REPLY_WITH_MEMORY)
    return SYSTEM_TEMPLATE.format(memory_clause="", K=history_window, memory_paragraph="",
                                  action_lines=action_lines(world), reply_line=REPLY_NO_MEMORY)


def build_user_message(memory_text: str | None, memory_limit: int, history: list[tuple[str, str]],
                       history_window: int, observation: str, longterm_text: str | None = None,
                       longterm_limit: int = 0) -> str:
    """memory_text None means memory is off (size 0) and the memory block is left out. The
    long-term block comes first when longterm_text is not None."""
    parts: list[str] = []
    if longterm_text is not None:
        parts.append(LONGTERM_LINE.format(used=len(longterm_text), limit=longterm_limit))
        parts.append(longterm_text)
        parts.append("")
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
