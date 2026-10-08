"""Run one controller in one world and log everything to runs/<run_id>/.

    python -m tinyworld.runner.run --controller sensible_bot --seed 1 --max-steps 1500 --run-id NAME
    python -m tinyworld.runner.run --controller llm --model mock --memory-chars 2000 --history-window 3 --max-steps 200

A controller is any object with

    act(observation: str, world) -> dict

It returns either a bare action dict ({"name": "move", ...}) or a dict with an "action" key
plus any of the optional keys listed in STEP_DEFAULTS and EXTRA_KEYS below. See run_loop.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import yaml

from tinyworld.sim import World, WorldConfig, load_world_config

FILES = ["world", "steps", "memory", "events"]
# Per step values a controller may return next to "action". Bots return none of them.
STEP_DEFAULTS: dict[str, Any] = {
    "raw_reply": "", "thought": "", "parse_ok": True, "memory_chars_used": 0, "memory_rejected": False,
    "input_tokens": 0, "output_tokens": 0, "latency_s": 0.0, "cost_usd": 0.0,
}
# Also read from the controller's return value:
#   "memory": {"ops": [...], "accepted": bool, "over_by": int, "text": str, "chars": int, "limit": int}
#             written to memory.jsonl for this step (leave out when no memory op was sent)
#   "events": [{"type": "parse_fail", "detail": {...}}, ...]  written to events.jsonl with t and i added
EXTRA_KEYS = ["memory", "events"]


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             cwd=Path(__file__).resolve().parent, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def _read_jsonl(path: Path) -> list[dict]:
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


class RunLogger:
    """Writes the run folder described in docs/INTERFACES.md.

    Agent steps are numbered from 1. i = 0 is the state before the first step (the snapshot
    line and the empty memory line). A step counts as complete once its steps.jsonl line is
    on disk, which is written last.
    """

    def __init__(self, run_dir: str | Path, resume: bool = False):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict] = []          # complete steps already on disk (only filled on resume)
        self.memory: list[dict] = []
        if resume and (self.dir / "steps.jsonl").exists():
            self._trim()
        else:
            for name in FILES:
                (self.dir / f"{name}.jsonl").write_text("")
        self._fh = {name: open(self.dir / f"{name}.jsonl", "a") for name in FILES}

    @property
    def last_i(self) -> int:
        return self.steps[-1]["i"] if self.steps else 0

    def _trim(self) -> None:
        """Cut every file back to the last complete agent step."""
        self.steps = _read_jsonl(self.dir / "steps.jsonl")
        last = self.last_i
        for name in FILES:
            rows = [r for r in _read_jsonl(self.dir / f"{name}.jsonl") if r.get("i", 0) <= last]
            if name == "steps":
                rows = self.steps
            if name == "memory":
                self.memory = rows
            (self.dir / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def has_start(self) -> bool:
        return (self.dir / "world.jsonl").stat().st_size > 0

    def write_config(self, config: dict) -> None:
        (self.dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))

    def read_config(self) -> dict:
        return yaml.safe_load((self.dir / "config.yaml").read_text())

    def write_start(self, snapshot: dict, memory_limit: int = 0) -> None:
        """Line 0 of world.jsonl and the empty memory line at i = 0."""
        self._write("world", snapshot)
        self._write("memory", {"i": 0, "t": 0, "ops": [], "accepted": True, "over_by": 0,
                               "text": "", "chars": 0, "limit": memory_limit})
        self.flush()

    def log_step(self, record: dict, deltas: list[dict], events: list[dict], memory: dict | None = None) -> None:
        i = record["i"]
        for d in deltas:
            self._write("world", {"type": d["type"], "t": d["t"], "i": i, **{k: v for k, v in d.items() if k not in ("type", "t")}})
        for e in events:
            self._write("events", {"t": e["t"], "i": i, "type": e["type"], "detail": e.get("detail", {})})
        if memory is not None:
            self._write("memory", {"i": i, "t": record["t_start"], **memory})
        self._write("steps", record)         # last: this line marks the step complete
        self.flush()

    def _write(self, name: str, row: dict) -> None:
        self._fh[name].write(json.dumps(row) + "\n")

    def flush(self) -> None:
        for fh in self._fh.values():
            fh.flush()

    def close(self) -> None:
        for fh in self._fh.values():
            fh.close()


def run_loop(world: World, controller, logger: RunLogger, max_steps: int,
             on_step: Callable[[dict], None] | None = None) -> None:
    """Drive the world with the controller until max_steps world steps or the run ends.

    Each agent step:
      1. obs = world.observe()
      2. out = controller.act(obs, world)
         A bare action dict, or {"action": {...}, plus optional STEP_DEFAULTS and EXTRA_KEYS}.
      3. result = world.step(action)
      4. controller.on_result(result, world) if the controller has that method. This is the
         place to record history, wipe memory when result.died is set, or call world.set_notice.
      5. everything is logged.

    On resume the logged actions are applied again with no controller decisions. For each one
    controller.replay(obs, world, step_record, memory_record_or_None) is called instead of act,
    if the controller has that method, followed by on_result as usual.
    """
    on_result = getattr(controller, "on_result", None)
    replay = getattr(controller, "replay", None)
    if not logger.has_start():
        logger.write_start(world.snapshot(), int(getattr(controller, "memory_limit", 0) or 0))
    mem_by_i = {m["i"]: m for m in logger.memory if m["i"] > 0}
    for rec in logger.steps:
        if replay:
            replay(world.observe(), world, rec, mem_by_i.get(rec["i"]))
        result = world.step(rec["action"])
        if on_result:
            on_result(result, world)

    i = logger.last_i
    while world.t < max_steps and not world.done:
        i += 1
        t_start = world.t
        obs = world.observe()
        out = controller.act(obs, world)
        extras = out if isinstance(out, dict) and "action" in out else {"action": out}
        action = extras["action"]
        result = world.step(action)
        if on_result:
            on_result(result, world)
        record = {"i": i, "t_start": t_start, "t_end": world.t, "observation": obs,
                  "raw_reply": extras.get("raw_reply", STEP_DEFAULTS["raw_reply"]),
                  "thought": extras.get("thought", STEP_DEFAULTS["thought"]),
                  "action": action, "result": result.text, "valid": result.valid,
                  "parse_ok": extras.get("parse_ok", True), "died": result.died,
                  "vitals": world.vitals()}
        for key in ("memory_chars_used", "memory_rejected", "input_tokens", "output_tokens", "latency_s", "cost_usd"):
            record[key] = extras.get(key, STEP_DEFAULTS[key])
        events = [{"t": t_start, **e} for e in extras.get("events", [])] + result.events
        logger.log_step(record, result.deltas, events, extras.get("memory"))
        if on_step:
            on_step(record)


def make_bot(name: str, seed: int):
    if name == "random_bot":
        from tinyworld.bots.random_bot import RandomBot
        return RandomBot(seed)
    if name == "sensible_bot":
        from tinyworld.bots.sensible_bot import SensibleBot
        return SensibleBot(seed)
    raise ValueError(f"unknown controller: {name}")


def make_llm(config: dict, world_cfg: WorldConfig):
    """The LLM controller for a run config (keys model, memory_chars, history_window, ...)."""
    from tinyworld.agent.controller import from_config
    return from_config({**config, "on_death": world_cfg.on_death})


def run(run_id: str, controller_name: str = "sensible_bot", seed: int = 1, max_steps: int = 1500,
        world_cfg: WorldConfig | None = None, runs_dir: str | Path = "runs", resume: bool = False,
        controller=None, extra_config: dict | None = None,
        on_step: Callable[[dict], None] | None = None) -> World:
    """Run one controller. Pass controller= to plug in something that is not a built-in bot.

    extra_config is merged into config.yaml (model, memory_chars, history_window, ...).
    With resume=True and an existing folder, the stored config is used and the run continues.
    """
    run_dir = Path(runs_dir) / run_id
    resume = resume and (run_dir / "config.yaml").exists() and (run_dir / "steps.jsonl").exists()
    logger = RunLogger(run_dir, resume=resume)
    if resume:
        config = logger.read_config()
        world_cfg = WorldConfig.model_validate(config["world"])
        seed, controller_name = config["seed"], config["controller"]
        max_steps = max(max_steps, 0) or config["max_steps"]
    else:
        world_cfg = world_cfg or load_world_config()
        config = {"run_id": run_id, "seed": seed, "controller": controller_name, "model": None,
                  "memory_chars": 0, "history_window": 0, "names": world_cfg.names,
                  "shuffle_recipes": world_cfg.shuffle_recipes, "on_death": world_cfg.on_death,
                  "max_steps": max_steps, "git_commit": git_commit()}
        config.update(extra_config or {})
        if controller is None and controller_name == "llm":
            controller = make_llm(config, world_cfg)
        if hasattr(controller, "config_extras"):
            config.update(controller.config_extras())
        config["world"] = world_cfg.model_dump(mode="json")
        logger.write_config(config)
    world = World(world_cfg, seed=seed)
    if controller is None and controller_name == "llm":
        controller = make_llm(config, world_cfg)
    if controller is None:
        controller = make_bot(controller_name, seed)
    started = time.monotonic()
    try:
        run_loop(world, controller, logger, max_steps, on_step)
    finally:
        logger.close()
    # The loop ended on its own (max_steps or end_run), so the run is complete: write the
    # sixth file. A killed or interrupted run leaves no summary.json, which is how the sweep
    # runner tells a finished run from one to resume.
    from tinyworld.analysis.metrics import write_summary
    write_summary(run_dir, wall_clock_s=time.monotonic() - started)
    return world


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run one controller (bot or LLM agent) in one world and log it.")
    ap.add_argument("--run-config", default=None, help="yaml with defaults for every flag below (configs/run.yaml)")
    ap.add_argument("--controller", default=None, choices=["random_bot", "sensible_bot", "llm"])
    ap.add_argument("--model", default=None, help="entry name in configs/models.yaml (controller llm)")
    ap.add_argument("--models-file", default=None, help="default configs/models.yaml")
    ap.add_argument("--memory-chars", type=int, default=None, help="memory file limit, 0 turns it off")
    ap.add_argument("--history-window", type=int, default=None, help="past action/result pairs shown, K")
    ap.add_argument("--max-tokens", type=int, default=None, help="reply budget per call, default from the model entry")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-steps", type=int, default=None, help="world steps")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--runs-dir", default=None)
    ap.add_argument("--config", default=None, help="world yaml, default configs/world.yaml")
    ap.add_argument("--names", choices=["familiar", "alien"], default=None)
    ap.add_argument("--shuffle-recipes", action="store_true", default=None)
    ap.add_argument("--on-death", default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--step-delay", type=float, default=0.0,
                    help="seconds to sleep after each agent step, so a bot run can be watched live in the viewer")
    args = ap.parse_args(argv)

    # Precedence: CLI flag, then the run config file, then these defaults.
    opts = {"controller": "sensible_bot", "model": None, "models_file": None, "memory_chars": 2000,
            "history_window": 3, "max_tokens": None, "seed": 1, "max_steps": 1500, "run_id": None,
            "runs_dir": "runs", "names": None, "shuffle_recipes": None, "on_death": None}
    if args.run_config:
        file_opts = yaml.safe_load(Path(args.run_config).read_text()) or {}
        opts.update({k: v for k, v in file_opts.items() if k in opts})
    opts.update({k: v for k, v in vars(args).items() if k in opts and v is not None})

    cfg = load_world_config(args.config, names=opts["names"], shuffle_recipes=opts["shuffle_recipes"],
                            on_death=opts["on_death"])
    extra = None
    if opts["controller"] == "llm":
        if not opts["model"]:
            ap.error("--controller llm needs --model NAME (an entry in configs/models.yaml)")
        extra = {"model": opts["model"], "models_file": opts["models_file"], "memory_chars": opts["memory_chars"],
                 "history_window": opts["history_window"], "max_tokens": opts["max_tokens"]}
        default_id = f"llm_{opts['model']}_seed{opts['seed']}"
    else:
        default_id = f"{opts['controller']}_seed{opts['seed']}"
    run_id = opts["run_id"] or default_id
    on_step = (lambda rec: time.sleep(args.step_delay)) if args.step_delay > 0 else None
    # On resume the stored config's max_steps wins unless --max-steps was given on the command line.
    max_steps = 0 if args.resume and args.max_steps is None else opts["max_steps"]
    world = run(run_id, opts["controller"], opts["seed"], max_steps, cfg, opts["runs_dir"], args.resume,
                extra_config=extra, on_step=on_step)
    print(f"{run_id}: world steps {world.t}, deaths {world.deaths}, "
          f"crafted {world.firsts['craft']}, folder {Path(opts['runs_dir']) / run_id}")


if __name__ == "__main__":
    main()
