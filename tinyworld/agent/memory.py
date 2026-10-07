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
