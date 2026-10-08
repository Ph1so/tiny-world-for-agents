"""Compare the generations of a lineage: does the long-term file make later runs better?

    python -m tinyworld.analysis.lineage_report haiku_a
    python -m tinyworld.analysis.lineage_report haiku_a --text     # also each generation's file

One row per finished generation, read from lineages/<name>/history.jsonl and each run folder:
deaths, distinct items crafted, the world step of the first wood and stone pickaxe and the
first meal, the first death, the long-term file size at start and end, and cost.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tinyworld.agent.lineage import Lineage

MILESTONES = [("wood pick", "first_craft", "item", "wood pickaxe"),
              ("stone pick", "first_craft", "item", "stone pickaxe"),
              ("first meal", "first_eat", None, None),
              ("first death", "death", None, None)]


def _events(run_dir: Path) -> list[dict]:
    p = run_dir / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def generation_rows(lin: Lineage) -> list[dict]:
    out = []
    for h in lin.history():
        run_dir = Path(h["run_dir"])
        ev = _events(run_dir)
        row = {"gen": h["generation"], "run": h["run_id"], "seed": h.get("seed"), "steps": h.get("world_steps"),
               "deaths": h.get("deaths"), "crafted": h.get("items_crafted_distinct"),
               "lt start": h["start_chars"], "lt end": h["end_chars"], "cost $": h.get("cost_usd_total")}
        for label, kind, key, value in MILESTONES:
            hit = next((e["t"] for e in ev if e["type"] == kind and (key is None or e["detail"].get(key) == value)), None)
            row[label] = hit
        out.append(row)
    return out


def format_table(rows: list[dict]) -> str:
    if not rows:
        return "no finished generations yet"
    cols = ["gen", "run", "seed", "steps", "deaths", "crafted", "wood pick", "stone pick", "first meal",
            "first death", "lt start", "lt end", "cost $"]
    cell = lambda v: "–" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
    width = {c: max(len(c), *(len(cell(r.get(c))) for r in rows)) for c in cols}
    lines = ["  ".join(c.rjust(width[c]) for c in cols), "  ".join("-" * width[c] for c in cols)]
    lines += ["  ".join(cell(r.get(c)).rjust(width[c]) for c in cols) for r in rows]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Compare the generations of a lineage.")
    ap.add_argument("lineage")
    ap.add_argument("--lineages-dir", default=None)
    ap.add_argument("--text", action="store_true", help="print each generation's long-term file at the end of its run")
    args = ap.parse_args(argv)
    lin = Lineage(args.lineage, args.lineages_dir)
    print(f"lineage {lin.name} ({lin.dir})  milestones are world steps, – means never\n")
    print(format_table(generation_rows(lin)))
    if args.text:
        for h in lin.history():
            p = Path(h["run_dir"]) / "longterm.jsonl"
            rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []
            print(f"\n--- generation {h['generation']} ({h['run_id']}), end of run ---")
            print(rows[-1]["text"] if rows else "(no longterm.jsonl)")
    held = lin.holder()
    if held:
        print(f"\nunfinished: {held['run_id']} holds the lineage")


if __name__ == "__main__":
    main()
