"""The memory file: a string with a character limit, edited by ops, with every version kept.

Ops (applied in order):
  {"op": "append",  "text": "..."}                 adds a line (a newline is put before it when the file is not empty)
  {"op": "replace", "old": "...", "new": "..."}    replaces the first occurrence of old
  {"op": "rewrite", "text": "..."}                 replaces the whole file

An edit is all or nothing. If the result would be over the limit, no op is applied and over_by
says by how many characters. Malformed ops (not a dict, unknown op, missing fields, old not
found, empty old) are skipped; the other ops in the same edit still count.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MemoryResult:
    ops: list
    accepted: bool
    over_by: int
    text: str
    chars: int
    limit: int
    applied: int = 0          # how many ops were well formed and applied (0 when rejected)
    skipped: int = 0          # malformed ops

    def record(self) -> dict:
        """The memory.jsonl line without i and t."""
        return {"ops": self.ops, "accepted": self.accepted, "over_by": self.over_by,
                "text": self.text, "chars": self.chars, "limit": self.limit}


@dataclass
class MemoryFile:
    limit: int
    text: str = ""
    versions: list[tuple[int, str]] = field(default_factory=list)   # (step, text) after every change

    @property
    def chars(self) -> int:
        return len(self.text)

    def preview(self, ops: list) -> tuple[str, int, int]:
        """Apply ops to a copy. Returns (new text, applied, skipped)."""
        text, applied, skipped = self.text, 0, 0
        for op in ops:
            if not isinstance(op, dict):
                skipped += 1
                continue
            kind = op.get("op")
            if kind == "append" and isinstance(op.get("text"), str):
                text = text + ("\n" if text else "") + op["text"]
            elif kind == "rewrite" and isinstance(op.get("text"), str):
                text = op["text"]
            elif (kind == "replace" and isinstance(op.get("old"), str) and isinstance(op.get("new"), str)
                  and op["old"] and op["old"] in text):
                text = text.replace(op["old"], op["new"], 1)
            else:
                skipped += 1
                continue
            applied += 1
        return text, applied, skipped

    def apply(self, ops: list, step: int) -> MemoryResult:
        ops = list(ops) if isinstance(ops, list) else []
        new, applied, skipped = self.preview(ops)
        over = len(new) - self.limit
        if over > 0:
            return MemoryResult(ops, False, over, self.text, len(self.text), self.limit, 0, skipped)
        if new != self.text:
            self.text = new
            self.versions.append((step, new))
        return MemoryResult(ops, True, 0, self.text, len(self.text), self.limit, applied, skipped)

    def set(self, text: str, step: int) -> None:
        """Force the file to a value (resume, or a wipe on death)."""
        if text != self.text:
            self.text = text
            self.versions.append((step, text))

    def wipe(self, step: int) -> None:
        self.set("", step)


# ---------------------------------------------------------------- memory_layout "sections"
#
# The file is three parts, kept as one text so logs and the viewer read it like any memory file:
#   GOAL: one line, at most GOAL_CHARS, what the agent is working toward
#   LESSONS: one "- " line per lesson; a rewrite never removes them
#   NOTES: everything else; append and rewrite work here
# Agents rewrote their whole file about every 25 steps and dropped most lessons with it (see
# DECISIONS.md), so the lessons sit where a rewrite cannot reach them.
#
# Extra ops:
#   {"op": "goal",   "text": "..."}   sets the goal line (cut to GOAL_CHARS)
#   {"op": "lesson", "text": "..."}   adds a lesson (one per line of text; a lesson already there is skipped)
# Changed ops:
#   append   adds a note line; a line starting "GOAL:" sets the goal, "LESSON:" / "LESSONS:" adds lessons
#   rewrite  replaces the notes; a full file sent back (with the headers) keeps every lesson and
#            adds the new ones, and sets the goal when it has a GOAL line
#   replace  changes the first match in the notes, else the goal, else a lesson; a lesson
#            replaced by nothing is removed

GOAL_CHARS = 200
GOAL_HEAD, LESSONS_HEAD, NOTES_HEAD = "GOAL:", "LESSONS:", "NOTES:"
GOAL_EMPTY, LESSONS_EMPTY = "(not set)", "(none yet)"
_STAMPED = re.compile(r"^(\[step \d+\] )?")
_HEAD = re.compile(r"^(\[step \d+\] )?\s*(GOAL|LESSONS?|NOTES)\s*:\s*", re.I)


def render_sections(goal: str, lessons: list[str], notes: str) -> str:
    lines = [f"{GOAL_HEAD} {goal or GOAL_EMPTY}"]
    lines += [f"{LESSONS_HEAD}"] + [f"- {x}" for x in lessons] if lessons else [f"{LESSONS_HEAD} {LESSONS_EMPTY}"]
    lines.append(NOTES_HEAD + ("\n" + notes if notes else ""))
    return "\n".join(lines)


def parse_sections(text: str) -> tuple[str, list[str], str, bool]:
    """(goal, lessons, notes, has_headers). Text with no headers is all notes."""
    goal, lessons, notes, part, seen = "", [], [], "notes", False
    for line in text.split("\n"):
        m = _HEAD.match(line)
        if m:
            seen = True
            head, rest = m.group(2).upper(), line[m.end():].strip()
            if head == "GOAL":
                goal = "" if rest == GOAL_EMPTY else rest
                part = "goal"
                continue
            if head.startswith("LESSON"):
                part = "lessons"
                if rest and rest != LESSONS_EMPTY:
                    lessons.append(rest.lstrip("- ").strip())
                continue
            part = "notes"
            if rest:
                notes.append(rest)
            continue
        if part == "lessons" and line.strip():
            lessons.append(line.strip().lstrip("-").strip())
        elif part == "notes" or line.strip():           # a stray line under GOAL counts as a note
            notes.append(line)
    while notes and not notes[0].strip():
        notes.pop(0)
    return goal, [x for x in lessons if x], "\n".join(notes).rstrip(), seen


@dataclass
class SectionedMemory:
    """Same interface as MemoryFile; the text is rendered from goal, lessons and notes."""
    limit: int
    goal: str = ""
    lessons: list[str] = field(default_factory=list)
    notes: str = ""
    versions: list[tuple[int, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return render_sections(self.goal, self.lessons, self.notes)

    @property
    def chars(self) -> int:
        return len(self.text)

    @staticmethod
    def _add_lessons(lessons: list[str], text: str) -> int:
        added = 0
        have = {x.lower() for x in lessons}
        for line in text.split("\n"):
            x = _STAMPED.sub("", line).strip().lstrip("-").strip()
            if x and x.lower() not in have:
                lessons.append(x)
                have.add(x.lower())
                added += 1
        return added

    def preview(self, ops: list) -> tuple[tuple[str, list[str], str], int, int]:
        goal, lessons, notes = self.goal, list(self.lessons), self.notes
        applied = skipped = 0
        for op in ops:
            kind = op.get("op") if isinstance(op, dict) else None
            text = op.get("text") if isinstance(op, dict) else None
            if kind == "goal" and isinstance(text, str):
                goal = text.strip().split("\n")[0][:GOAL_CHARS]
            elif kind == "lesson" and isinstance(text, str) and text.strip():
                self._add_lessons(lessons, text)
            elif kind == "append" and isinstance(text, str):
                for line in text.split("\n"):
                    m = _HEAD.match(line)
                    head = m.group(2).upper() if m else ""
                    rest = line[m.end():].strip() if m else ""
                    if head == "GOAL":
                        if rest and rest != GOAL_EMPTY:
                            goal = rest[:GOAL_CHARS]
                    elif head.startswith("LESSON"):
                        if rest and rest != LESSONS_EMPTY:
                            self._add_lessons(lessons, rest)
                    elif head == "NOTES":
                        if rest:
                            notes = notes + ("\n" if notes else "") + (m.group(1) or "") + rest
                    else:
                        notes = notes + ("\n" if notes else "") + line
            elif kind == "rewrite" and isinstance(text, str):
                g, ls, n, has_headers = parse_sections(text)
                if has_headers:
                    goal = g[:GOAL_CHARS] if g else goal
                    self._add_lessons(lessons, "\n".join(ls))
                notes = n
            elif (kind == "replace" and isinstance(op.get("old"), str) and isinstance(op.get("new"), str)
                  and op["old"]):
                old, new = op["old"], op["new"]
                bare = old.strip().lstrip("-").strip()
                hit = [k for k, x in enumerate(lessons) if bare and bare in x]
                if old in notes:
                    notes = notes.replace(old, new, 1)
                elif old in goal:
                    goal = goal.replace(old, new, 1)[:GOAL_CHARS]
                elif hit:
                    k = hit[0]
                    changed = lessons[k].replace(bare, new.strip().lstrip("-").strip(), 1).strip()
                    if changed:
                        lessons[k] = changed
                    else:
                        lessons.pop(k)
                else:
                    skipped += 1
                    continue
            else:
                skipped += 1
                continue
            applied += 1
        return (goal, lessons, notes), applied, skipped

    def apply(self, ops: list, step: int) -> MemoryResult:
        ops = list(ops) if isinstance(ops, list) else []
        (goal, lessons, notes), applied, skipped = self.preview(ops)
        new = render_sections(goal, lessons, notes)
        over = len(new) - self.limit
        if over > 0:
            return MemoryResult(ops, False, over, self.text, self.chars, self.limit, 0, skipped)
        if new != self.text:
            self.goal, self.lessons, self.notes = goal, lessons, notes
            self.versions.append((step, new))
        return MemoryResult(ops, True, 0, self.text, self.chars, self.limit, applied, skipped)

    def set(self, text: str, step: int) -> None:
        """Force the file to a logged value (resume, or a wipe on death)."""
        goal, lessons, notes, _ = parse_sections(text)
        if render_sections(goal, lessons, notes) != self.text:
            self.goal, self.lessons, self.notes = goal, lessons, notes
            self.versions.append((step, self.text))

    def wipe(self, step: int) -> None:
        self.set("", step)
