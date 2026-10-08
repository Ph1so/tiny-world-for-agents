"""Run every combination of a sweep config, with a cost guard, resume, and a report at the end.

    python -m tinyworld.runner.sweep configs/sweeps/memory_sweep.yaml [--yes] [--runs-dir runs]
                                     [--parallel N] [--budget USD] [--dry-run] [--no-report]

Sweep yaml (PLAN.md section 11 plus two keys):

    name: memory_sweep
    controller: llm              # or random_bot / sensible_bot, or a list of them (default llm)
    seeds: [1, 2, 3]
    max_steps: 1500
    models: [model_a, model_b]   # ignored for bot controllers
    memory_chars: [0, 500, 2000]
    history_window: [3]
    names: familiar
    shuffle_recipes: false
    on_death: respawn_keep_memory
    budget_usd: 25
    parallel_runs: 4

Run folders are runs/<sweep name>/<model>_m<memory>_k<K>_s<seed>/ (for bots the controller name
takes the place of the model). The run_id in config.yaml is the folder name without the sweep, so
the server can serve a sweep with `python -m tinyworld.server --runs runs/<sweep name>` and the
report can link each run as http://localhost:8000/?run=<run_id>.
Each run is one child process of tinyworld.runner.run with --resume,
so a run that was cut off continues from its last complete step. A run with a summary.json is done
and is skipped. Spend is read from the cost_usd field of every steps.jsonl line while the runs are
going. When it reaches budget_usd no new run starts and the running ones are stopped (SIGTERM),
which leaves every file at a complete step, so the sweep can be started again later.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from tinyworld.analysis.metrics import write_summary

BOT_CONTROLLERS = ("random_bot", "sensible_bot")
# Cost estimate inputs. See docs/DECISIONS.md (Analysis). All rough, on purpose.
EST_WORLD_STEPS_PER_CALL = 2.0       # one model call moves the world about 2 steps on average
EST_INPUT_TOKENS_BASE = 900          # system prompt + observation + history, without the memory file
EST_CHARS_PER_TOKEN = 4.0            # the memory file adds memory_chars / 4 input tokens
EST_OUTPUT_TOKENS = 150              # thought + memory ops + action


@dataclass
class RunSpec:
    name: str                        # folder name inside the sweep folder, also the run_id
    run_id: str                      # same as name; the sweep folder is passed as --runs-dir
    controller: str
    model: str | None
    memory_chars: int
    history_window: int
    seed: int
    max_steps: int
    names: str
    on_death: str
    shuffle_recipes: bool
    world: str | None = None

    def argv(self, sweep_dir: Path) -> list[str]:
        """Command line of the child process. sweep_dir is runs/<sweep name>."""
        cmd = [sys.executable, "-m", "tinyworld.runner.run", "--controller", self.controller,
               "--seed", str(self.seed), "--max-steps", str(self.max_steps), "--run-id", self.run_id,
               "--runs-dir", str(sweep_dir), "--names", self.names, "--on-death", self.on_death, "--resume"]
        if self.world:
            cmd += ["--config", self.world]
        if self.shuffle_recipes:
            cmd.append("--shuffle-recipes")
        if self.controller not in BOT_CONTROLLERS:
            cmd += ["--model", str(self.model), "--memory-chars", str(self.memory_chars),
                    "--history-window", str(self.history_window)]
        return cmd


@dataclass
class SweepConfig:
    name: str
    seeds: list[int]
    max_steps: int
    controllers: list[str]
    models: list[str]
    memory_chars: list[int]
    history_window: list[int]
    names: str = "familiar"
    shuffle_recipes: bool = False
    on_death: str = "respawn_keep_memory"
    world: str | None = None
    budget_usd: float = 0.0
    parallel_runs: int = 1
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "SweepConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.from_dict(raw, default_name=Path(path).stem)

    @classmethod
    def from_dict(cls, raw: dict, default_name: str = "sweep") -> "SweepConfig":
        def as_list(v, default):
            if v is None:
                return list(default)
            return list(v) if isinstance(v, (list, tuple)) else [v]
        controllers = as_list(raw.get("controller"), ["llm"])
        models = as_list(raw.get("models", raw.get("model")), [])
        return cls(
            name=str(raw.get("name") or default_name),
            seeds=[int(s) for s in as_list(raw.get("seeds"), [1])],
            max_steps=int(raw.get("max_steps", 1500)),
            controllers=controllers,
            models=[str(m) for m in models],
            memory_chars=[int(m) for m in as_list(raw.get("memory_chars"), [0])],
            history_window=[int(k) for k in as_list(raw.get("history_window"), [3])],
            names=str(raw.get("names", "familiar")),
            shuffle_recipes=bool(raw.get("shuffle_recipes", False)),
            on_death=str(raw.get("on_death", "respawn_keep_memory")),
            world=(str(raw["world"]) if raw.get("world") else None),
            budget_usd=float(raw.get("budget_usd", 0) or 0),
            parallel_runs=max(1, int(raw.get("parallel_runs", 1))),
            raw=raw,
        )

    def to_dict(self) -> dict:
        return {"name": self.name, "controller": self.controllers, "seeds": self.seeds,
                "max_steps": self.max_steps, "models": self.models, "memory_chars": self.memory_chars,
                "history_window": self.history_window, "names": self.names,
                "shuffle_recipes": self.shuffle_recipes, "on_death": self.on_death,
                "world": self.world, "budget_usd": self.budget_usd, "parallel_runs": self.parallel_runs}


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._]+", "-", str(text)).strip("-") or "none"


def expand(cfg: SweepConfig) -> list[RunSpec]:
    """Every combination, in a fixed order: controller, model, memory, history window, seed."""
    specs: list[RunSpec] = []
    for controller in cfg.controllers:
        if controller in BOT_CONTROLLERS:
            conditions = [(controller, None, 0, 0)]
        else:
            models = cfg.models or [None]
            conditions = [(controller, m, mem, k) for m, mem, k in
                          itertools.product(models, cfg.memory_chars, cfg.history_window)]
        for (ctrl, model, mem, k), seed in itertools.product(conditions, cfg.seeds):
            label = slug(model) if model is not None else ctrl
            name = f"{label}_m{mem}_k{k}_s{seed}"
            specs.append(RunSpec(name=name, run_id=name, controller=ctrl, model=model,
                                 memory_chars=mem, history_window=k, seed=seed, max_steps=cfg.max_steps,
                                 names=cfg.names, on_death=cfg.on_death, shuffle_recipes=cfg.shuffle_recipes,
                                 world=cfg.world))
    return specs


# ---------------------------------------------------------------- prices and estimates


def load_prices(path: str | Path = "configs/models.yaml") -> dict[str, tuple[float, float]]:
    """model name -> (usd per million input tokens, usd per million output tokens).

    Tolerant of the yaml shape: a top level mapping of models, or one under a "models" key, as a
    dict or a list of entries with a name/id. Price keys may be input_per_mtok, input_price,
    price_input, input_usd_per_m, or similar; anything with "input"/"output" in the key is taken.
    Missing file or missing model means (0, 0).
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {}
    entries = raw.get("models", raw) if isinstance(raw, dict) else raw
    items: list[tuple[str, dict]] = []
    if isinstance(entries, dict):
        items = [(str(k), v) for k, v in entries.items() if isinstance(v, dict)]
    elif isinstance(entries, list):
        for v in entries:
            if isinstance(v, dict):
                name = v.get("name") or v.get("id") or v.get("model")
                if name:
                    items.append((str(name), v))
    out: dict[str, tuple[float, float]] = {}
    for name, v in items:
        flat = dict(v)
        for sub in ("price", "prices", "cost", "pricing"):
            if isinstance(v.get(sub), dict):
                flat.update({f"{sub}_{k}": x for k, x in v[sub].items()})

        def pick(kind: str) -> float:
            for k, x in flat.items():
                lk = k.lower()
                if kind in lk and isinstance(x, (int, float)) and "cache" not in lk:
                    return float(x)
            return 0.0
        out[name] = (pick("input"), pick("output"))
        for alias in (v.get("id"), v.get("model"), v.get("model_id")):
            if alias:
                out[str(alias)] = out[name]
    return out


def estimate(spec: RunSpec, prices: dict[str, tuple[float, float]]) -> tuple[int, float]:
    """(estimated model calls, estimated usd) for one run. Bots cost nothing."""
    if spec.controller in BOT_CONTROLLERS:
        return 0, 0.0
    calls = int(round(spec.max_steps / EST_WORLD_STEPS_PER_CALL))
    inp = EST_INPUT_TOKENS_BASE + spec.memory_chars / EST_CHARS_PER_TOKEN
    pin, pout = prices.get(spec.model or "", (0.0, 0.0))
    usd = calls * (inp * pin + EST_OUTPUT_TOKENS * pout) / 1e6
    return calls, usd


# ---------------------------------------------------------------- spend tracking


class SpendMeter:
    """Sums cost_usd over steps.jsonl lines of the sweep, reading only new bytes each time."""

    def __init__(self):
        self.offsets: dict[Path, int] = {}
        self.spent: dict[Path, float] = {}
        self.partial: dict[Path, str] = {}

    def update(self, run_dirs: list[Path]) -> float:
        for d in run_dirs:
            p = d / "steps.jsonl"
            if not p.exists():
                continue
            off = self.offsets.get(p, 0)
            with open(p, "rb") as fh:
                fh.seek(off)
                chunk = fh.read()
            if not chunk:
                continue
            text = self.partial.get(p, "") + chunk.decode("utf-8", errors="replace")
            lines = text.split("\n")
            self.partial[p] = lines[-1]
            self.offsets[p] = off + len(chunk)
            for line in lines[:-1]:
                try:
                    self.spent[p] = self.spent.get(p, 0.0) + float(json.loads(line).get("cost_usd") or 0.0)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
        return self.total

    @property
    def total(self) -> float:
        return float(sum(self.spent.values()))

    def of(self, run_dir: Path) -> float:
        return self.spent.get(run_dir / "steps.jsonl", 0.0)


# ---------------------------------------------------------------- the sweep


def run_state(run_dir: Path) -> str:
    if (run_dir / "summary.json").exists():
        return "done"
    if (run_dir / "steps.jsonl").exists() and (run_dir / "steps.jsonl").stat().st_size > 0:
        return "partial"
    return "new"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Sweep:
    def __init__(self, cfg: SweepConfig, runs_dir: str | Path = "runs", prices_path: str | Path = "configs/models.yaml"):
        self.cfg = cfg
        self.runs_dir = Path(runs_dir)
        self.dir = self.runs_dir / cfg.name
        self.specs = expand(cfg)
        self.prices = load_prices(prices_path)
        self.status: dict = {"name": cfg.name, "budget_usd": cfg.budget_usd, "spent_usd": 0.0,
                             "stopped": None, "started_at": None, "updated_at": None, "runs": {}}
        self.meter = SpendMeter()

    def run_dir(self, spec: RunSpec) -> Path:
        return self.dir / spec.name

    # ---- plan
    def plan(self) -> dict:
        calls = cost = 0.0
        done = partial = 0
        for s in self.specs:
            st = run_state(self.run_dir(s))
            done += st == "done"
            partial += st == "partial"
            if st != "done":
                c, u = estimate(s, self.prices)
                calls += c
                cost += u
        return {"runs": len(self.specs), "done": done, "partial": partial, "todo": len(self.specs) - done,
                "est_calls": int(calls), "est_usd": cost}

    def print_plan(self) -> None:
        p = self.plan()
        cfg = self.cfg
        print(f"sweep {cfg.name} -> {self.dir}")
        print(f"  controllers {cfg.controllers}  models {cfg.models or '-'}  memory_chars {cfg.memory_chars}  "
              f"history_window {cfg.history_window}  seeds {cfg.seeds}  max_steps {cfg.max_steps}")
        print(f"  runs: {p['runs']} ({p['done']} done, {p['partial']} partial, {p['todo']} to run), "
              f"parallel {cfg.parallel_runs}")
        priced = [m for m in cfg.models if m in self.prices]
        unpriced = [m for m in cfg.models if m not in self.prices]
        print(f"  estimate for the runs left: about {p['est_calls']} model calls, about ${p['est_usd']:.2f}"
              + (f" (no price known for {unpriced}, counted as $0)" if unpriced and any(
                  c not in BOT_CONTROLLERS for c in cfg.controllers) else ""))
        if priced:
            print(f"  prices from configs/models.yaml for {priced}")
        print(f"  budget: ${cfg.budget_usd:.2f}" + ("" if cfg.budget_usd > 0 else " (0 = no limit)"))
        print(f"  estimate assumes {EST_WORLD_STEPS_PER_CALL} world steps per call, {EST_INPUT_TOKENS_BASE} input tokens "
              f"+ memory_chars/{EST_CHARS_PER_TOKEN:g}, {EST_OUTPUT_TOKENS} output tokens per call")
        for s in self.specs:
            print(f"    {run_state(self.run_dir(s)):8s} {s.name}")

    # ---- status
    def write_status(self) -> None:
        self.status["spent_usd"] = round(self.meter.total, 6)
        self.status["updated_at"] = _now()
        (self.dir / "sweep_status.json").write_text(json.dumps(self.status, indent=1) + "\n")

    def _set(self, spec: RunSpec, **kv) -> None:
        entry = self.status["runs"].setdefault(spec.name, {"run_id": spec.run_id, "status": run_state(self.run_dir(spec))})
        entry.update(kv)
        entry["cost_usd"] = round(self.meter.of(self.run_dir(spec)), 6)

    # ---- execute
    def execute(self, parallel: int | None = None, budget: float | None = None, log_dir: Path | None = None) -> dict:
        parallel = parallel or self.cfg.parallel_runs
        budget = self.cfg.budget_usd if budget is None else budget
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "sweep.yaml").write_text(yaml.safe_dump(self.cfg.to_dict(), sort_keys=False))
        self.status["started_at"] = self.status["started_at"] or _now()
        self.status["budget_usd"] = budget
        todo = [s for s in self.specs if run_state(self.run_dir(s)) != "done"]
        for s in self.specs:
            self._set(s)
        self.meter.update([self.run_dir(s) for s in self.specs])
        self.write_status()
        running: dict[str, tuple[subprocess.Popen, RunSpec, float]] = {}
        stop_reason = None
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        cwd = Path(__file__).resolve().parents[2]
        try:
            while todo or running:
                over = budget > 0 and self.meter.total >= budget
                if over and stop_reason is None:
                    stop_reason = f"budget reached: spent ${self.meter.total:.4f} of ${budget:.2f}"
                    print(stop_reason)
                    todo.clear()
                    for proc, spec, _ in running.values():
                        proc.send_signal(signal.SIGTERM)
                while todo and len(running) < parallel and not over:
                    spec = todo.pop(0)
                    d = self.run_dir(spec)
                    d.mkdir(parents=True, exist_ok=True)
                    log = open((log_dir or d) / "sweep_run.log", "a")
                    proc = subprocess.Popen(spec.argv(self.dir), stdout=log, stderr=subprocess.STDOUT,
                                            cwd=cwd, env=env)
                    running[spec.name] = (proc, spec, time.time())
                    self._set(spec, status="running", pid=proc.pid, started_at=_now())
                    print(f"start {self.cfg.name}/{spec.name} (pid {proc.pid})")
                time.sleep(0.25)
                self.meter.update([self.run_dir(s) for s in self.specs])
                for name in list(running):
                    proc, spec, t0 = running[name]
                    rc = proc.poll()
                    if rc is None:
                        self._set(spec)
                        continue
                    del running[name]
                    wall = time.time() - t0
                    if rc == 0:
                        try:
                            summary = write_summary(self.run_dir(spec), wall_clock_s=wall)
                            self._set(spec, status="done", returncode=rc, wall_clock_s=round(wall, 2),
                                      world_steps=summary["world_steps"], deaths=summary["deaths"])
                            print(f"done  {spec.run_id}: world steps {summary['world_steps']}, deaths {summary['deaths']}, "
                                  f"${summary['cost_usd_total']:.4f}, {wall:.0f}s")
                        except Exception as exc:          # a bad run folder must not kill the sweep
                            self._set(spec, status="failed", returncode=rc, error=f"metrics: {exc}")
                            print(f"fail  {spec.run_id}: metrics failed: {exc}")
                    else:
                        state = "stopped" if stop_reason else "failed"
                        self._set(spec, status=state, returncode=rc, wall_clock_s=round(wall, 2))
                        print(f"{state:5s} {spec.run_id}: exit code {rc} (see sweep_run.log)")
                self.write_status()
        except KeyboardInterrupt:
            stop_reason = "interrupted"
            for proc, spec, _ in running.values():
                proc.send_signal(signal.SIGTERM)
            for proc, spec, _ in running.values():
                proc.wait()
                self._set(spec, status="stopped")
            print("interrupted, runs stopped at a complete step")
        self.status["stopped"] = stop_reason
        self.write_status()
        return self.status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run a sweep of runs from a yaml config.")
    ap.add_argument("config", help="configs/sweeps/<name>.yaml")
    ap.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--parallel", type=int, default=None, help="override parallel_runs")
    ap.add_argument("--budget", type=float, default=None, help="override budget_usd")
    ap.add_argument("--models-yaml", default="configs/models.yaml")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    ap.add_argument("--no-report", action="store_true", help="do not write report.html at the end")
    args = ap.parse_args(argv)

    cfg = SweepConfig.load(args.config)
    if args.parallel:
        cfg.parallel_runs = args.parallel
    if args.budget is not None:
        cfg.budget_usd = args.budget
    sweep = Sweep(cfg, args.runs_dir, args.models_yaml)
    sweep.print_plan()
    if args.dry_run:
        return 0
    if sweep.plan()["todo"] == 0:
        print("nothing to run, every run has a summary.json")
    elif not args.yes:
        answer = input("run it? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("stopped")
            return 1
    status = sweep.execute()
    counts = {}
    for r in status["runs"].values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"sweep {cfg.name}: {counts}, spent ${status['spent_usd']:.4f}"
          + (f", stopped: {status['stopped']}" if status["stopped"] else ""))
    if not args.no_report:
        from tinyworld.analysis.report import write_report
        out = write_report(sweep.dir)
        print(f"report: {out}")
    return 0 if not status["stopped"] else 2


if __name__ == "__main__":
    sys.exit(main())
