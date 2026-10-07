"""Replay the block grid of a run from world.jsonl (snapshot plus per step deltas).

Nothing here imports the simulation. The formats are the ones in docs/INTERFACES.md.

    run = RunFiles("runs/<run>")          # lazily loads config.yaml and the four jsonl files
    for line, grid in replay_grid(run):   # one (world line, Grid) pair per world step, in order
        grid.get(x, y, z) -> block name
"""
from __future__ import annotations

import base64
import json
import zlib
from functools import cached_property
from pathlib import Path
from typing import Iterator

import numpy as np
import yaml

SOLID_EXCEPT = {"air", "water", "torch"}   # anything else blocks movement and sight of creatures


def read_jsonl(path: Path) -> list[dict]:
    """Complete, parseable lines only. A half written last line is dropped."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text().split("\n"):
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return rows


class RunFiles:
    """The files of one run folder, loaded on first use."""

    def __init__(self, run_dir: str | Path):
        self.dir = Path(run_dir)

    @cached_property
    def config(self) -> dict:
        p = self.dir / "config.yaml"
        return yaml.safe_load(p.read_text()) if p.exists() else {}

    @cached_property
    def steps(self) -> list[dict]:
        return read_jsonl(self.dir / "steps.jsonl")

    @cached_property
    def world(self) -> list[dict]:
        return read_jsonl(self.dir / "world.jsonl")

    @cached_property
    def memory(self) -> list[dict]:
        return read_jsonl(self.dir / "memory.jsonl")

    @cached_property
    def events(self) -> list[dict]:
        return read_jsonl(self.dir / "events.jsonl")

    @property
    def snapshot(self) -> dict | None:
        w = self.world
        return w[0] if w and w[0].get("type") == "snapshot" else None

    @property
    def world_steps(self) -> list[dict]:
        return [r for r in self.world if r.get("type") == "step"]


class Grid:
    """A block grid indexed by (x, y, z) with the palette of the snapshot."""

    def __init__(self, snapshot: dict):
        self.sx, self.sy, self.sz = snapshot["size"]
        self.palette: list[str] = list(snapshot["palette"])
        self.index = {n: i for i, n in enumerate(self.palette)}
        raw = zlib.decompress(base64.b64decode(snapshot["blocks_b64"]))
        self.blocks = np.frombuffer(raw, dtype=np.uint8).copy()   # index = x + z*sx + y*sx*sz

    def in_bounds(self, x: int, y: int, z: int) -> bool:
        return 0 <= x < self.sx and 0 <= y < self.sy and 0 <= z < self.sz

    def get(self, x: int, y: int, z: int) -> str:
        """Block name at a cell. Cells outside the map count as air."""
        if not self.in_bounds(x, y, z):
            return "air"
        return self.palette[self.blocks[x + z * self.sx + y * self.sx * self.sz]]

    def set(self, x: int, y: int, z: int, name: str) -> None:
        self.blocks[x + z * self.sx + y * self.sx * self.sz] = self.index[name]

    def is_solid(self, x: int, y: int, z: int) -> bool:
        return self.get(x, y, z) not in SOLID_EXCEPT

    def apply(self, line: dict) -> list[tuple[int, int, int, str, str]]:
        """Apply one world step line. Returns (x, y, z, before, after) for each changed cell."""
        changes = []
        for x, y, z, name in line.get("blocks", []):
            before = self.get(x, y, z)
            self.set(x, y, z, name)
            changes.append((x, y, z, before, name))
        return changes

    def as_array(self) -> np.ndarray:
        """Shape (y, z, x), same layout as World.blocks."""
        return self.blocks.reshape(self.sy, self.sz, self.sx)


def replay_grid(run: RunFiles) -> Iterator[tuple[dict, Grid, list[tuple[int, int, int, str, str]]]]:
    """Yield (world step line, grid after the step, cell changes) for every world step in order.

    The same Grid object is yielded each time and mutated in place, so copy it if you keep it.
    """
    snap = run.snapshot
    if snap is None:
        return
    grid = Grid(snap)
    for line in run.world[1:]:
        if line.get("type") != "step":
            continue
        changes = grid.apply(line)
        yield line, grid, changes


def final_grid(run: RunFiles) -> Grid | None:
    grid = None
    for _, grid, _ in replay_grid(run):
        pass
    if grid is None and run.snapshot is not None:
        grid = Grid(run.snapshot)
    return grid
