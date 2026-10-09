"""The system prompt (PLAN.md section 7, used word for word) and the user message.

The only things filled in are K, N, and the action lines. The action lines are built from the
world's name mapping and config, so alien mode shows alien names and no name is a fixed string.
"""
from __future__ import annotations

import json

from .memory import GOAL_CHARS

SYSTEM_TEMPLATE = """You are in a world. The world moves forward each time you act.

Each step you are shown {memory_clause}your last {K} actions with their results, and what you can observe right now. You do not remember anything else from earlier steps.
{memory_paragraph}
Actions:
{action_lines}

Reply with one JSON object and nothing else:
{reply_line}"""

MEMORY_PARAGRAPH = ("\nYour memory file holds at most {N} characters. You may edit it every step. "
                    "An edit that would go over the limit is rejected and the file stays as it was.\n")

# Multi-agent intros, replacing the first line. Facts about time and company, nothing to do.
INTRO_REALTIME = ("You are in a world. The world moves forward on its own clock, also while you are deciding. "
                  "Other agents act in it at the same time.")
INTRO_LOCKSTEP = ("You are in a world. The world moves forward each time you and the other agents in it act.")

REPLY_WITH_MEMORY = '{"thought": "...", "memory": [...], "action": {...}}'
REPLY_NO_MEMORY = '{"thought": "...", "action": {...}}'

# Long-term file (lineages). Only used when longterm_chars > 0; with it off the prompt is the
# PLAN.md section 7 text unchanged.
LONGTERM_PARAGRAPH = ("\nYour long-term file holds at most {L} characters. It carries over to your later runs, "
                      "which may take place in a different world.{memory_note} You may edit it every step with "
                      "the \"longterm\" field{edit_like}. An edit that would go over its limit is "
                      "rejected and the file stays as it was. A death does not end a run: you start again at "
                      "the starting point and the run goes on.\n")
# How edits work. Only shown with the long-term file on (the PLAN.md prompt never spelled the
# ops out, and a model that guessed wiped its long-term file, see DECISIONS.md).
EDIT_OPS = ('\nAn edit is a list of ops: {{"op": "append", "text": "..."}} adds a line, '
            '{{"op": "replace", "old": "...", "new": "..."}} changes the first match, '
            '{{"op": "rewrite", "text": "..."}} replaces the whole file. In {fields} plain text is added '
            'as a new line.{stamp}\n')
# memory_plain "append" only: appended memory lines get the world step in front.
STAMP_NOTE = ' A line added to the memory file starts with the step it was added at, like "[step 12] ".'
LONGTERM_MEMORY_NOTE = " Your memory file starts empty in every run."
# memory_layout "sections" only (agent/memory.py SectionedMemory): the file's three parts, how to
# edit each, and a push to keep lessons. Agents in runs/4agents_varied_base_s153_r2 learned a rule
# after a failure, lost it in a rewrite, and failed the same way again (DECISIONS.md).
SECTIONS_PARAGRAPH = (
    "\nYour memory file has three parts. GOAL is one line for what you are working toward. LESSONS are what "
    "you have found out about how this world works: what works, what fails and why, what to do or avoid. "
    "NOTES are everything else, such as places and plans. Your health, food, inventory and surroundings "
    "are shown to you every step, so the file does not need them.\n"
    'An edit is a list of ops: {"op": "goal", "text": "..."} sets the goal line (at most <G> characters), '
    '{"op": "lesson", "text": "..."} adds a lesson, {"op": "append", "text": "..."} adds a note, '
    '{"op": "replace", "old": "...", "new": "..."} changes the first match (a lesson changed to "" is removed), '
    '{"op": "rewrite", "text": "..."} replaces all the notes. A rewrite never removes the goal or a lesson. '
    "<PLAIN><STAMP>\n"
    "When something fails, or works in a way you did not expect, add a lesson, so you do not make the same "
    "mistake again. Keep your lessons; they are what you carry forward.\n")
SECTIONS_PLAIN = {"append": 'Plain text in "memory" is added as a note.',
                  "rewrite": 'Plain text in "memory" replaces the notes.'}
STAMP_NOTE_SECTIONS = ' A note added this way starts with the step it was added at, like "[step 12] ".'
REPLY_LONGTERM_MEMORY = '{"thought": "...", "memory": [...], "longterm": [...], "action": {...}}'
REPLY_LONGTERM_ONLY = '{"thought": "...", "longterm": [...], "action": {...}}'
LONGTERM_LINE = "long-term file ({used} of {limit} characters used)"
REFLECTION = ("The run is over. This is the last edit of your long-term file before your next run.\n"
              "Reply with one JSON object and nothing else:\n"
              '{"thought": "...", "longterm": [...]}')

# planning "action" / "triggers" only (agent/plan.py, DECISIONS 125). Mechanics only: what a plan
# is, what it costs, how it changes. Nothing on when to plan or what about. The condition's form
# is shown with placeholders, not a real condition: with "steps_since_plan >= 50" as the example,
# Sonnet wrote exactly that 23 times in runs/sonnet_plan_every20_s153_400 (DECISIONS 128).
PLAN_PARAGRAPH = (
    "\nYou can keep a plan: a goal and the steps toward it, at most {P} characters. It is shown to you every "
    "step and it changes only when you write it again. To write it, use the plan action. That takes time "
    "like any other action: you are then asked for the plan in a separate reply, and nothing else is done "
    "that turn.\n")
TRIGGERS_PARAGRAPH = (
    "With a plan you may list up to {C} conditions for when you want to write it again. A condition is a "
    'name, one of < <= > >= == !=, and a number, written like "NAME < NUMBER". The names are '
    "{names}, and any item name for how many of it you hold. On the step a condition turns true you are "
    "asked for a new plan before your next action; that takes the same time as the plan action.\n")
# plan_every > 0 only: a plan is asked for on a fixed count of the agent's own turns. The count
# knows nothing about the world.
PLAN_EVERY_SENTENCE = ("You are also asked for your plan every {N} turns, counted from the last time you were "
                       "asked or chose to write it; that takes the same time as the plan action.\n")
PLAN_REQUEST_EVERY = ("It has been {N} turns since your plan was last written. Write your plan now. It replaces "
                      "the one above.\nReply with one JSON object and nothing else:\n{reply}")
# plan_inline (DECISIONS 129): a plan asked for by a condition or by the count is written in the
# same reply as the next action, so it takes no turn. These replace the endings of the sentences above.
ASKED_OWN_TURN = "you are asked for a new plan before your next action; that takes the same time as the plan action."
ASKED_INLINE = "you are asked to write a new plan in the same reply as your next action; that takes no extra time."
EVERY_OWN_TURN = "; that takes the same time as the plan action."
EVERY_INLINE = ", in the same reply as your next action; that takes no extra time."
# plan_cooldown > 0: conditions are not looked at for that many turns after a plan is written.
COOLDOWN_SENTENCE = "Conditions are not checked until {K} of your turns have gone by since the plan was last written.\n"
PLAN_INLINE_REQUEST = ("{why} In this reply, write your plan again as well as your action. It replaces the plan above.\n"
                       "Reply with one JSON object and nothing else:\n{reply}")
WHY_FIRED = "A condition you set is true now: {cond}."
WHY_EVERY = "It has been {N} turns since your plan was last written."
PLAN_ACTION_LINE = 'plan: {"name": "plan"}  write your plan again; you are asked for it in a separate reply'
PLAN_REPLY = '{"thought": "...", "goal": "...", "steps": ["...", "..."]}'
PLAN_REPLY_TRIGGERS = '{"thought": "...", "goal": "...", "steps": ["...", "..."], "replan_when": ["...", "..."]}'
PLAN_REQUEST = ("You chose the plan action. Write your plan now. It replaces the one above.\n"
                "Reply with one JSON object and nothing else:\n{reply}")
PLAN_REQUEST_FIRED = ("A condition you set is true now: {cond}. Write your plan now. It replaces the one above.\n"
                      "Reply with one JSON object and nothing else:\n{reply}")

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
        f'jump: {{"name": "jump", "item": {ex_place}}}  move up 1 cell and place an item from the inventory in the cell you left',
        f'sleep: {{"name": "sleep"}}  with a {world.dn("bed")} within {c.reach} cells: the world moves on until dawn or until you are hurt',
    ]
    if c.long_actions:
        lines += [
            f'goto: {{"name": "goto", "x": X, "y": Y, "z": Z}} or {{"name": "goto", "id": ID}}  walk until you are beside '
            f'that cell or creature, at most {c.goto_max_steps} steps; it stops early when you are hurt, when something '
            f'new comes into view, or when there is no way on foot',
            'any action may also carry "repeat": 2 to 8, to do it that many times in a row; it stops early when a '
            'try fails or you are hurt',
        ]
    if getattr(world, "multi", False):
        lines[5] = f'attack: {{"name": "attack", "id": ID}}  a creature or agent within {c.attack_reach} cells'
        lines += [
            f'say: {{"name": "say", "text": "..."}}  agents within {c.hear_radius} cells hear it, up to {c.say_max_chars} characters',
            f'give: {{"name": "give", "id": ID, "items": {ex_craft}}}  items from the inventory to an agent within {c.reach} cells',
        ]
    return "\n".join(lines)


def book_lines(world) -> str:
    """With recipe_book on, every craft in the world's table (shuffled and alien names included)."""
    from tinyworld.sim import text as T
    from tinyworld.sim.defs import FUELS
    c = world.cfg

    def count(item: str, n: int) -> str:
        if item == "fuel":
            return T.BOOK_FUEL.format(c=n, a=world.dn(FUELS[0]), b=world.dn(FUELS[1]))
        return T.OBS_MADE_COUNT.format(c=n, name=world.dn(item))

    lines = [T.BOOK_HEADER]
    for r in world.recipes:
        station = T.BOOK_STATION.format(station=world.dn(r.station), r=c.station_reach) if r.station else ""
        lines.append(T.BOOK_LINE.format(inputs=" + ".join(count(i, n) for i, n in r.inputs),
                                        output=count(r.output, r.count), station=station))
    cc = c.creatures
    lines += ["", T.BOOK_USE_HEADER,
              T.BOOK_USE_BED.format(bed=world.dn("bed"), r=c.reach),
              T.BOOK_USE_CHEST.format(chest=world.dn("chest"), n=c.chest_slots),
              T.BOOK_USE_DOOR.format(door=world.dn("door")),
              T.BOOK_USE_TORCH.format(torch=world.dn("torch"), r=cc.torch_radius, l=c.torch_light)]
    if c.weather.enabled:
        lines.append(T.BOOK_USE_ROOF.format(leaves=world.dn("leaves"), torch=world.dn("torch")))
    food = ", ".join(f"{world.dn(k)} {v}" for k, v in c.food.items())
    rain = T.BOOK_USE_FOOD_RAIN.format(m=c.weather.rain_food_mult) if c.weather.enabled else ""
    lines.append(T.BOOK_USE_FOOD.format(values=food, d=c.vitals.food_drain_every, rain=rain))
    f = c.farming
    lines += ["", T.BOOK_GROW_HEADER, T.BOOK_GROW.format(
        seeds=world.dn("seeds"), soil=" or ".join(world.dn(s) for s in ("dirt", "grass")), water=world.dn("water"),
        r=f.water_dist, wheat=world.dn("wheat"), n=f.grow_steps, w=f.wheat_per_crop, s=f.seeds_per_crop,
        grass=world.dn("grass"), sprout=world.dn("sprout"))]
    return "\n".join(lines)


def _actions(world) -> str:
    """The action lines, then the craft list when recipe_book is on (off: PLAN.md text unchanged)."""
    if not world.cfg.recipe_book:
        return action_lines(world)
    return action_lines(world) + "\n\n" + book_lines(world)


def build_system_prompt(world, history_window: int, memory_chars: int, longterm_chars: int = 0,
                        memory_plain: str = "rewrite", intro: str | None = None, persona: str | None = None,
                        memory_layout: str = "plain", planning: str = "off", plan_chars: int = 0,
                        plan_every: int = 0, plan_inline: bool = False, plan_cooldown: int = 0) -> str:
    """intro replaces the first line (multi-agent); persona is added as a last paragraph;
    memory_layout "sections" explains the GOAL / LESSONS / NOTES file in place of the plain one;
    planning "action" or "triggers" adds the plan paragraph and the plan action line."""
    text = _system_prompt(world, history_window, memory_chars, longterm_chars, memory_plain, memory_layout)
    if planning != "off":
        text = _with_plan(text, world, planning, plan_chars, plan_every, plan_inline, plan_cooldown)
    if intro:
        text = intro + text[text.index("\n"):]
    if persona:
        text += "\n\n" + persona
    return text


def _with_plan(text: str, world, planning: str, plan_chars: int, plan_every: int = 0, plan_inline: bool = False,
               plan_cooldown: int = 0) -> str:
    """The plan paragraph goes just before "Actions:", the plan line at the end of the action
    lines (before the craft list, when there is one)."""
    from .plan import COUNTERS, MAX_CONDITIONS
    para = PLAN_PARAGRAPH.format(P=plan_chars)
    if planning == "triggers":
        names = ", ".join(list(world.vitals()) + list(COUNTERS))
        para += TRIGGERS_PARAGRAPH.format(C=MAX_CONDITIONS, names=names)
        if plan_cooldown > 0:
            para += COOLDOWN_SENTENCE.format(K=plan_cooldown)
    if plan_every > 0:
        para += PLAN_EVERY_SENTENCE.format(N=plan_every)
    if plan_inline:
        assert ASKED_OWN_TURN in para or planning != "triggers"
        para = para.replace(ASKED_OWN_TURN, ASKED_INLINE).replace(EVERY_OWN_TURN, EVERY_INLINE)
    head, sep, tail = text.partition("\nActions:\n")
    lines = action_lines(world)
    assert sep and tail.startswith(lines), "system prompt layout changed"
    return head + para + sep + lines + "\n" + PLAN_ACTION_LINE + tail[len(lines):]


def plan_inline_request(planning: str, fired: str | None, every: int, reply_line: str) -> str:
    """The plan fields go in front of the step reply's own fields (reply_line, as in the system prompt)."""
    fields = PLAN_REPLY_TRIGGERS if planning == "triggers" else PLAN_REPLY
    fields = fields[:-1].replace('{"thought": "...", ', "{") + ", "
    reply = '{"thought": "...", ' + fields[1:] + reply_line.replace('{"thought": "...", ', "")
    why = WHY_FIRED.format(cond=fired) if fired else WHY_EVERY.format(N=every)
    return PLAN_INLINE_REQUEST.format(why=why, reply=reply)


def plan_request(planning: str, fired: str | None = None, every: int = 0) -> str:
    reply = PLAN_REPLY_TRIGGERS if planning == "triggers" else PLAN_REPLY
    if every:
        return PLAN_REQUEST_EVERY.format(N=every, reply=reply)
    return PLAN_REQUEST_FIRED.format(cond=fired, reply=reply) if fired else PLAN_REQUEST.format(reply=reply)


def _system_prompt(world, history_window: int, memory_chars: int, longterm_chars: int = 0,
                   memory_plain: str = "rewrite", memory_layout: str = "plain") -> str:
    """memory_plain "rewrite" with no long-term file is the PLAN.md section 7 prompt word for word.
    "append" (plain memory text adds lines) spells the edit ops out, as the long-term file does.
    memory_layout "sections" spells out the sectioned file's ops instead (SECTIONS_PARAGRAPH)."""
    mem = memory_chars > 0
    sections = mem and memory_layout == "sections"
    appends = mem and memory_plain == "append" and not sections
    fields = " and ".join(f for f, on in (('"memory"', appends), ('"longterm"', longterm_chars > 0)) if on)
    ops = EDIT_OPS.format(fields=fields, stamp=STAMP_NOTE if appends else "") if fields else ""
    if sections:
        ops = SECTIONS_PARAGRAPH.replace("<G>", str(GOAL_CHARS)).replace("<PLAIN>", SECTIONS_PLAIN[memory_plain]).replace(
            "<STAMP>", STAMP_NOTE_SECTIONS if memory_plain == "append" else "") + ops
    if longterm_chars > 0:
        clause = ("your memory file, " if mem else "") + "your long-term file, "
        paragraph = (MEMORY_PARAGRAPH.format(N=memory_chars) if mem else "") + LONGTERM_PARAGRAPH.format(
            L=longterm_chars, memory_note=LONGTERM_MEMORY_NOTE if mem else "",
            edit_like=", the same way as the memory file" if mem else "") + ops
        return SYSTEM_TEMPLATE.format(memory_clause=clause, K=history_window, memory_paragraph=paragraph,
                                      action_lines=_actions(world),
                                      reply_line=REPLY_LONGTERM_MEMORY if mem else REPLY_LONGTERM_ONLY)
    if mem:
        return SYSTEM_TEMPLATE.format(memory_clause="your memory file, ", K=history_window,
                                      memory_paragraph=MEMORY_PARAGRAPH.format(N=memory_chars) + ops,
                                      action_lines=_actions(world), reply_line=REPLY_WITH_MEMORY)
    return SYSTEM_TEMPLATE.format(memory_clause="", K=history_window, memory_paragraph="",
                                  action_lines=_actions(world), reply_line=REPLY_NO_MEMORY)


def build_user_message(memory_text: str | None, memory_limit: int, history: list[tuple[str, str]],
                       history_window: int, observation: str, longterm_text: str | None = None,
                       longterm_limit: int = 0, plan_text: str | None = None) -> str:
    """memory_text None means memory is off (size 0) and the memory block is left out. The
    long-term block comes first when longterm_text is not None. plan_text (planning on) is the
    plan block, shown after the memory file."""
    parts: list[str] = []
    if longterm_text is not None:
        parts.append(LONGTERM_LINE.format(used=len(longterm_text), limit=longterm_limit))
        parts.append(longterm_text)
        parts.append("")
    if memory_text is not None:
        parts.append(MEMORY_LINE.format(used=len(memory_text), limit=memory_limit))
        parts.append(memory_text)
        parts.append("")
    if plan_text is not None:
        parts.append(plan_text)
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
