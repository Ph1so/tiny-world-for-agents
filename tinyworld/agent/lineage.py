"""Long-term memory that carries over between runs, kept in a lineage folder.

A lineage is a chain of runs (generations) that share one long-term file. Each run starts with
the file as the previous generation left it and, once it finishes, writes its final version
back. Runs stay reproducible: a run's config.yaml stores the text it started from, and its
longterm.jsonl logs every version, so the run folder alone is enough to replay it.

    lineages/<name>/longterm.md      the current long-term file
    lineages/<name>/history.jsonl    one line per finished generation
    lineages/<name>/lock.json        the unfinished run that holds the lineage, if any

Generations are sequential: while a run in the lineage is unfinished (running, paused or
stopped), no other run can start in it. A stopped run keeps the lock until it is resumed to
the end or its folder is deleted.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

LINEAGES_DIR = Path(__file__).resolve().parents[2] / "lineages"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class LineageError(Exception):
    pass


class Lineage:
    def __init__(self, name: str, root: str | Path | None = None):
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise LineageError(f"lineage name: letters, digits, _ . - only, at most 64 characters (got {name!r})")
        self.name = name
        self.dir = Path(root) if root else LINEAGES_DIR
        self.dir = self.dir / name

    @property
    def text_path(self) -> Path:
        return self.dir / "longterm.md"

    def text(self) -> str:
        return self.text_path.read_text() if self.text_path.exists() else ""

    def history(self) -> list[dict]:
        p = self.dir / "history.jsonl"
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]

    @property
    def next_generation(self) -> int:
        return len(self.history()) + 1

    # ------------------------------------------------------------------ lock

    def holder(self) -> dict | None:
        """The unfinished run holding the lineage, or None. A lock whose run finished or whose
        folder is gone does not count."""
        p = self.dir / "lock.json"
        if not p.exists():
            return None
        try:
            lock = json.loads(p.read_text())
        except json.JSONDecodeError:
            return None
        run_dir = Path(lock.get("run_dir", ""))
        if not run_dir.exists() or (run_dir / "summary.json").exists():
            return None
        return lock

    def acquire(self, run_id: str, run_dir: Path) -> None:
        held = self.holder()
        if held and held.get("run_id") != run_id:
            raise LineageError(f"lineage {self.name} is held by the unfinished run {held['run_id']} "
                               f"({held['run_dir']}); resume it to the end or delete its folder first")
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "lock.json").write_text(json.dumps({"run_id": run_id, "run_dir": str(Path(run_dir).resolve())}))

    # ------------------------------------------------------------------ commit

    def commit(self, run_id: str, run_dir: Path, generation: int, start_text: str, end_text: str,
               extra: dict | None = None) -> dict:
        """Write the finished run's long-term file back and record the generation."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self.text_path.write_text(end_text)
        line = {"generation": generation, "run_id": run_id, "run_dir": str(Path(run_dir).resolve()),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "start_chars": len(start_text), "end_chars": len(end_text), "changed": start_text != end_text,
                **(extra or {})}
        with open(self.dir / "history.jsonl", "a") as fh:
            fh.write(json.dumps(line) + "\n")
        lock = self.dir / "lock.json"
        if lock.exists():
            try:
                if json.loads(lock.read_text()).get("run_id") == run_id:
                    lock.unlink()
            except json.JSONDecodeError:
                lock.unlink()
        return line
