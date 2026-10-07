"""Per run metrics from a run folder (PLAN.md section 11), written to summary.json.

    python -m tinyworld.analysis.metrics runs/<run> [runs/<other> ...]
    from tinyworld.analysis.metrics import compute_metrics, write_summary

summary.json has flat keys only: numbers, strings, booleans, and a few short lists of
scalars (death_causes, life_steps). Key groups:

    run        run_id, seed, controller, model, memory_chars, history_window, names, on_death,
               world_steps, agent_steps, finished, max_steps
    survival   deaths, deaths_<cause>, death_causes, life_steps, life_steps_mean/min/max, first_death_t
    progress   blocks_mined_distinct, items_crafted_distinct, recipes_found, deepest_tool_tier,
               craft_fails, blocks_placed_distinct_kinds, items_eaten_distinct, kills
    activity   share_<action> (share of world steps), agent_share_<action> (share of agent steps),
               cells_visited, blocks_placed, largest_placed_group (face contact),
               largest_placed_group_26 (any contact, diagonals too), placed_blocks_still_standing
    night      night_steps, nights, night_enclosed_share, night_torch_share, night_open_share
    stuck      longest_same_action_streak, longest_identical_action_streak, action_entropy_50,
               unreadable_replies, invalid_actions
    memory     memory_chars_final/mean/max, memory_edits, memory_edits_append/replace/rewrite,
               memory_rejected, memory_chars_changed_per_step, memory_chars_changed_per_edit,
               memory_lines_created, memory_lines_alive_end, memory_line_survival_mean (died lines),
               memory_line_survival_mean_censored (alive lines count until the last step)
    cost       input_tokens_total, output_tokens_total, tokens_total, cost_usd_total,
               latency_total_s, latency_mean_s, wall_clock_s
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import sys
from collections import Counter, deque
from pathlib import Path

from tinyworld.analysis.replay import Grid, RunFiles, replay_grid

ACTIONS = ["move", "mine", "place", "craft", "eat", "attack", "wait"]
TOOL_TIER = {"wood pickaxe": 1, "stone pickaxe": 2, "stone sword": 2, "iron pickaxe": 3, "iron sword": 3}
DEATH_CAUSES = ["hunger", "drowning", "fall", "zombie"]
ENTROPY_WINDOW = 50
NEIGHBOURS_6 = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
NEIGHBOURS_26 = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                 if (dx, dy, dz) != (0, 0, 0)]


def _mean(xs) -> float:
    xs = list(xs)
    return float(sum(xs) / len(xs)) if xs else 0.0


def _round(v):
    return round(v, 4) if isinstance(v, float) else v


# ---------------------------------------------------------------- survival and progress


def survival_metrics(run: RunFiles, world_steps: int) -> dict:
    deaths = [e for e in run.events if e["type"] == "death"]
    causes = [e.get("detail", {}).get("cause", "unknown") for e in deaths]
    out: dict = {"deaths": len(deaths), "death_causes": causes}
    for c in DEATH_CAUSES:
        out[f"deaths_{c}"] = causes.count(c)
    lives, last = [], 0
    for e in deaths:
        lives.append(e["t"] - last)
        last = e["t"]
    lives.append(world_steps - last)          # the life still running at the end
    out["life_steps"] = lives
    out["life_steps_mean"] = _mean(lives)
    out["life_steps_min"] = min(lives)
    out["life_steps_max"] = max(lives)
    out["first_death_t"] = deaths[0]["t"] if deaths else None
    return out


def progress_metrics(run: RunFiles) -> dict:
    ev = run.events
    firsts = lambda kind, key: {e["detail"].get(key) for e in ev if e["type"] == kind}
    crafted = firsts("first_craft", "item")
    return {
        "blocks_mined_distinct": len(firsts("first_mine", "block")),
        "items_crafted_distinct": len(crafted),
        "recipes_found": len(crafted),           # one recipe per distinct output
        "deepest_tool_tier": max([TOOL_TIER.get(i, 0) for i in crafted] + [0]),
        "craft_fails": sum(1 for e in ev if e["type"] == "craft_fail"),
        "blocks_placed_distinct_kinds": len(firsts("first_place", "block")),
        "items_eaten_distinct": len(firsts("first_eat", "item")),
        "kills": sum(1 for e in ev if e["type"] == "kill"),
        "tools_broken": sum(1 for e in ev if e["type"] == "tool_broke"),
    }


# ---------------------------------------------------------------- what it chose to do


def activity_metrics(run: RunFiles) -> dict:
    steps = run.steps
    world_time = Counter()
    agent_count = Counter()
    for s in steps:
        name = (s.get("action") or {}).get("name", "unknown")
        if name not in ACTIONS:
            name = "unknown"
        world_time[name] += max(1, s["t_end"] - s["t_start"])
        agent_count[name] += 1
    total_t = sum(world_time.values()) or 1
    total_i = sum(agent_count.values()) or 1
    out = {}
    for a in ACTIONS:
        out[f"share_{a}"] = world_time[a] / total_t
        out[f"agent_share_{a}"] = agent_count[a] / total_i
    out["share_unknown"] = world_time["unknown"] / total_t
    return out


def largest_group(cells: set[tuple[int, int, int]], neighbours=NEIGHBOURS_6) -> int:
    """Largest connected group of cells. Default is face-connected (6 neighbours in 3D, the
    3D form of 4-connected). Pass NEIGHBOURS_26 to also count edge and corner contact."""
    best, seen = 0, set()
    for start in cells:
        if start in seen:
            continue
        size, todo = 0, [start]
        seen.add(start)
        while todo:
            x, y, z = todo.pop()
            size += 1
            for dx, dy, dz in neighbours:
                n = (x + dx, y + dy, z + dz)
                if n in cells and n not in seen:
                    seen.add(n)
                    todo.append(n)
        best = max(best, size)
    return best


def _is_night(t: int, cfg: dict) -> bool:
    w = cfg.get("world", {})
    day_len, night_start = int(w.get("day_length", 300)), int(w.get("night_start", 200))
    return (t % day_len) >= night_start


def _enclosed(grid: Grid, pos: list[int]) -> bool:
    """Walls on the four sides of the feet cell and of the head cell, and a roof above the head."""
    x, y, z = pos
    for yy in (y, y + 1):
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if not grid.is_solid(x + dx, yy, z + dz):
                return False
    return grid.is_solid(x, y + 2, z)


def _near_torch(grid: Grid, torches: set[tuple[int, int, int]], pos: list[int], dist: int) -> bool:
    x, y, z = pos
    return any(max(abs(tx - x), abs(ty - y), abs(tz - z)) <= dist for tx, ty, tz in torches)


def world_metrics(run: RunFiles) -> dict:
    """Metrics that need the replayed grid: cells visited, placed blocks, where it was at night."""
    cfg = run.config
    torch_dist = int(cfg.get("world", {}).get("torch_light", 6))
    action_by_i = {s["i"]: s.get("action") or {} for s in run.steps}
    visited: set[tuple[int, int]] = set()
    placed_now: set[tuple[int, int, int]] = set()
    placed_total = 0
    largest = largest26 = 0
    torches: set[tuple[int, int, int]] = set()
    night = Counter()
    nights = set()
    snap = run.snapshot
    if snap is not None:
        p = snap["agent"]["pos"]
        visited.add((p[0], p[2]))
        g = Grid(snap)
        arr = g.as_array()
        tid = g.index.get("torch")
        if tid is not None:
            ys, zs, xs = (arr == tid).nonzero()
            torches = {(int(x), int(y), int(z)) for x, y, z in zip(xs, ys, zs)}
    for line, grid, changes in replay_grid(run):
        act = action_by_i.get(line.get("i"), {})
        target = (act.get("x"), act.get("y"), act.get("z")) if act.get("name") == "place" else None
        changed_set = False
        for x, y, z, before, after in changes:
            cell = (x, y, z)
            if after == "torch":
                torches.add(cell)
            elif before == "torch":
                torches.discard(cell)
            if before in ("air", "water") and after not in ("air", "water") and cell == target:
                placed_total += 1
                placed_now.add(cell)
                changed_set = True
            elif cell in placed_now and after in ("air", "water"):
                placed_now.discard(cell)
                changed_set = True
        if changed_set:
            largest = max(largest, largest_group(placed_now))
            largest26 = max(largest26, largest_group(placed_now, NEIGHBOURS_26))
        pos = line["agent"]["pos"]
        visited.add((pos[0], pos[2]))
        t = line["t"]
        if _is_night(t, cfg):
            nights.add(t // int(cfg.get("world", {}).get("day_length", 300)))
            if _enclosed(grid, pos):
                night["enclosed"] += 1
            elif _near_torch(grid, torches, pos, torch_dist):
                night["torch"] += 1
            else:
                night["open"] += 1
    n = sum(night.values())
    return {
        "cells_visited": len(visited),
        "blocks_placed": placed_total,
        "largest_placed_group": largest,
        "largest_placed_group_26": largest26,
        "placed_blocks_still_standing": len(placed_now),
        "night_steps": n,
        "nights": len(nights),
        "night_enclosed_share": night["enclosed"] / n if n else 0.0,
        "night_torch_share": night["torch"] / n if n else 0.0,
        "night_open_share": night["open"] / n if n else 0.0,
    }


# ---------------------------------------------------------------- stuck or looping


def _entropy(counter: Counter) -> float:
    n = sum(counter.values())
    return -sum(c / n * math.log2(c / n) for c in counter.values() if c) if n else 0.0


def stuck_metrics(run: RunFiles) -> dict:
    steps = run.steps
    names = [(s.get("action") or {}).get("name", "unknown") for s in steps]
    keys = [json.dumps(s.get("action") or {}, sort_keys=True) for s in steps]

    def longest(seq):
        best = cur = 0
        prev = object()
        for v in seq:
            cur = cur + 1 if v == prev else 1
            prev = v
            best = max(best, cur)
        return best

    # Mean Shannon entropy (bits) of action names over every window of 50 agent steps.
    window: deque = deque()
    counts: Counter = Counter()
    ents = []
    for n in names:
        window.append(n)
        counts[n] += 1
        if len(window) > ENTROPY_WINDOW:
            counts[window.popleft()] -= 1
        if len(window) == ENTROPY_WINDOW:
            ents.append(_entropy(counts))
    if not ents and names:
        ents.append(_entropy(counts))
    return {
        "longest_same_action_streak": longest(names),
        "longest_identical_action_streak": longest(keys),
        "action_entropy_50": _mean(ents),
        "unreadable_replies": sum(1 for s in steps if not s.get("parse_ok", True)),
        "invalid_actions": sum(1 for s in steps if not s.get("valid", True)),
    }


# ---------------------------------------------------------------- memory


def _chars_changed(a: str, b: str) -> int:
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    same = sum(bl.size for bl in m.get_matching_blocks())
    return len(a) + len(b) - 2 * same


def line_survival(versions: list[tuple[int, str]], last_i: int) -> dict:
    """versions: (agent step, full text) in order. A line is born when it first appears and
    dies at the first later version that does not contain it. Returns survival stats in agent steps."""
    alive: dict[str, int] = {}       # line -> born at
    died: list[int] = []
    created = 0
    for i, text in versions:
        lines = {ln for ln in text.split("\n") if ln.strip()}
        for ln in list(alive):
            if ln not in lines:
                died.append(i - alive.pop(ln))
        for ln in lines:
            if ln not in alive:
                alive[ln] = i
                created += 1
    censored = [last_i - born for born in alive.values()]
    return {
        "memory_lines_created": created,
        "memory_lines_alive_end": len(alive),
        "memory_line_survival_mean": _mean(died),
        "memory_line_survival_mean_censored": _mean(died + censored),
    }


def memory_metrics(run: RunFiles) -> dict:
    steps, mem = run.steps, run.memory
    used = [s.get("memory_chars_used", 0) for s in steps]
    edits = [m for m in mem if m.get("i", 0) > 0]
    ops = Counter(op.get("op", "?") for m in edits if m.get("accepted", True) for op in m.get("ops", []))
    changed = []
    prev = ""
    versions = []
    for m in mem:
        text = m.get("text", "")
        if m.get("i", 0) > 0:
            changed.append(_chars_changed(prev, text))
        versions.append((m.get("i", 0), text))
        prev = text
    last_i = steps[-1]["i"] if steps else 0
    out = {
        "memory_chars_final": used[-1] if used else 0,
        "memory_chars_mean": _mean(used),
        "memory_chars_max": max(used) if used else 0,
        "memory_edits": sum(1 for m in edits if m.get("accepted", True)),
        "memory_edits_append": ops["append"],
        "memory_edits_replace": ops["replace"],
        "memory_edits_rewrite": ops["rewrite"],
        "memory_rejected": sum(1 for m in edits if not m.get("accepted", True))
        + sum(1 for s in steps if s.get("memory_rejected") and not any(m["i"] == s["i"] for m in edits)),
        "memory_chars_changed_per_step": sum(changed) / len(steps) if steps else 0.0,
        "memory_chars_changed_per_edit": _mean(changed),
    }
    out.update(line_survival(versions, last_i))
    return out


# ---------------------------------------------------------------- cost


def cost_metrics(run: RunFiles, wall_clock_s: float | None) -> dict:
    steps = run.steps
    lat = [float(s.get("latency_s") or 0.0) for s in steps]
    inp = sum(int(s.get("input_tokens") or 0) for s in steps)
    outp = sum(int(s.get("output_tokens") or 0) for s in steps)
    return {
        "input_tokens_total": inp,
        "output_tokens_total": outp,
        "tokens_total": inp + outp,
        "cost_usd_total": float(sum(float(s.get("cost_usd") or 0.0) for s in steps)),
        "latency_total_s": float(sum(lat)),
        "latency_mean_s": _mean(lat),
        # Real wall clock when the sweep runner passes it. Otherwise the sum of model latencies.
        "wall_clock_s": float(wall_clock_s) if wall_clock_s is not None else float(sum(lat)),
    }


# ---------------------------------------------------------------- all together


def compute_metrics(run_dir: str | Path, wall_clock_s: float | None = None) -> dict:
    run = RunFiles(run_dir)
    cfg = run.config
    steps = run.steps
    world_steps = steps[-1]["t_end"] if steps else 0
    max_steps = int(cfg.get("max_steps") or 0)
    out: dict = {
        "run_id": cfg.get("run_id", Path(run_dir).name),
        "seed": cfg.get("seed"),
        "controller": cfg.get("controller"),
        "model": cfg.get("model"),
        "memory_chars": cfg.get("memory_chars", 0),
        "history_window": cfg.get("history_window", 0),
        "names": cfg.get("names"),
        "on_death": cfg.get("on_death"),
        "max_steps": max_steps,
        "world_steps": world_steps,
        "agent_steps": len(steps),
        "finished": bool(steps) and (world_steps >= max_steps or cfg.get("on_death") == "end_run"
                                      and any(s.get("died") for s in steps)),
    }
    out.update(survival_metrics(run, world_steps))
    out.update(progress_metrics(run))
    out.update(activity_metrics(run))
    out.update(world_metrics(run))
    out.update(stuck_metrics(run))
    out.update(memory_metrics(run))
    out.update(cost_metrics(run, wall_clock_s))
    return {k: _round(v) for k, v in out.items()}


def write_summary(run_dir: str | Path, wall_clock_s: float | None = None) -> dict:
    summary = compute_metrics(run_dir, wall_clock_s)
    (Path(run_dir) / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Compute metrics for run folders and write summary.json.")
    ap.add_argument("runs", nargs="+", help="run folders")
    ap.add_argument("--print", action="store_true", help="print the summary too")
    ap.add_argument("--no-write", action="store_true", help="only print, do not write summary.json")
    args = ap.parse_args(argv)
    for r in args.runs:
        s = compute_metrics(r) if args.no_write else write_summary(r)
        if args.print or args.no_write:
            print(json.dumps(s, indent=1))
        else:
            print(f"{r}: deaths {s['deaths']}, recipes {s['recipes_found']}, world steps {s['world_steps']}, "
                  f"cost ${s['cost_usd_total']:.4f} -> {Path(r) / 'summary.json'}")


if __name__ == "__main__":
    main(sys.argv[1:])
