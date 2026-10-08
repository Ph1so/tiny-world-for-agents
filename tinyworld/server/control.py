"""Start, pause, resume and stop runs from the viewer.

Pause and stop go through the control files the runner checks between agent steps
(tinyworld.runner.run.PAUSE_FILE and STOP_FILE), so they work for any run, including one
started from a shell. Start and resume launch the runner as a subprocess whose output goes to
runner.log in the run folder.

A run's state, from its folder:
    finished   summary.json exists
    running    a runner is alive (runner.pid names a live process)
    paused     running, and the pause file exists
    stopping   running, and the stop file exists (it ends after the current step)
    stopped    not finished and no runner: --resume continues it
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from tinyworld.agent.lineage import LINEAGES_DIR, NAME_RE, Lineage
from tinyworld.runner.run import CONFIGS_DIR, PAUSE_FILE, PID_FILE, STOP_FILE

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
CONTROLLERS = ("llm", "sensible_bot", "random_bot")
LOG_FILE = "runner.log"


class ControlError(Exception):
    """A request that cannot be carried out. status is the HTTP code to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunControl:
    def __init__(self, runs_dirs: list[Path], python: str = sys.executable, models_file: Path | None = None):
        self.dirs = [Path(d) for d in runs_dirs]
        self.python = python
        self.models_file = models_file or CONFIGS_DIR / "models.yaml"
        self.procs: dict[str, subprocess.Popen] = {}

    # ------------------------------------------------------------------ state

    def _reap(self) -> None:
        """Collect children that have exited, so a finished one is not counted as alive."""
        for p in self.procs.values():
            p.poll()

    def alive(self, run_dir: Path) -> bool:
        self._reap()
        p = self.procs.get(str(run_dir))
        if p is not None and p.returncode is None:
            return True
        try:
            pid = int((run_dir / PID_FILE).read_text().strip())
        except (OSError, ValueError):
            return False
        return _pid_alive(pid)

    def state(self, run_dir: Path) -> str:
        if (run_dir / "summary.json").exists():
            return "finished"
        if not self.alive(run_dir):
            return "stopped"
        if (run_dir / STOP_FILE).exists():
            return "stopping"
        if (run_dir / PAUSE_FILE).exists():
            return "paused"
        return "running"

    # ------------------------------------------------------------------ options

    def models(self) -> list[dict[str, Any]]:
        data = yaml.safe_load(self.models_file.read_text()) or {}
        out = []
        for name, m in (data.get("models") or {}).items():
            out.append({"name": name, "provider": m.get("provider"), "model": m.get("model"),
                        "input_per_m": m.get("input_per_m"), "output_per_m": m.get("output_per_m")})
        return out

    @staticmethod
    def lineages() -> list[dict[str, Any]]:
        """Existing lineages with their generation count, long-term limit and file size."""
        out = []
        if LINEAGES_DIR.is_dir():
            for d in sorted(LINEAGES_DIR.iterdir()):
                if not d.is_dir() or not NAME_RE.match(d.name):
                    continue
                lin = Lineage(d.name)
                hist = lin.history()
                held = lin.holder()
                out.append({"name": d.name, "generations": len(hist), "chars": len(lin.text()),
                            "longterm_chars": next((h["longterm_chars"] for h in reversed(hist) if h.get("longterm_chars")), None),
                            "busy": held["run_id"] if held else None})
        return out

    @staticmethod
    def worlds() -> list[str]:
        return sorted(p.stem for p in CONFIGS_DIR.glob("world*.yaml"))

    # ------------------------------------------------------------------ actions

    def _exists(self, run_id: str) -> bool:
        return any((d / run_id).exists() for d in self.dirs)

    def _spawn(self, run_dir: Path, args: list[str]) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        log = open(run_dir / LOG_FILE, "a")
        log.write(f"\n--- {datetime.now().isoformat(timespec='seconds')} {' '.join(args)}\n")
        log.flush()
        try:
            p = subprocess.Popen([self.python, "-m", "tinyworld.runner.run", *args], cwd=REPO_ROOT,
                                 stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 start_new_session=True)
        except OSError as e:
            raise ControlError(f"could not launch the runner: {e}", 500)
        finally:
            log.close()
        self.procs[str(run_dir)] = p

    def _wait_started(self, run_dir: Path, timeout: float = 20.0) -> None:
        """Wait until the runner has written its pid file, or fail with the end of its log."""
        p = self.procs[str(run_dir)]
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if (run_dir / PID_FILE).exists() and (run_dir / "config.yaml").exists():
                return
            if p.poll() is not None:
                if (run_dir / "summary.json").exists():
                    return                          # a very short run that already finished
                tail = (run_dir / LOG_FILE).read_text()[-1500:].strip()
                raise ControlError(f"the runner exited (code {p.returncode}):\n{tail}", 500)
            time.sleep(0.1)
        raise ControlError("the runner did not start within 20 s, see runner.log", 504)

    def start(self, spec: dict[str, Any]) -> str:
        """Launch a new run. spec keys: controller, model, memory_chars, max_steps, seed, world,
        run_id, step_delay, and for a long-term file lineage and longterm_chars. Returns the run
        id once the runner is up."""
        controller = spec.get("controller", "llm")
        if controller not in CONTROLLERS:
            raise ControlError(f"controller must be one of {', '.join(CONTROLLERS)}")
        model = spec.get("model")
        if controller == "llm" and model not in {m["name"] for m in self.models()}:
            raise ControlError(f"unknown model: {model!r}")
        try:
            memory = int(spec.get("memory_chars", 2000))
            max_steps = int(spec.get("max_steps", 300))
            seed = int(spec.get("seed", 1))
            delay = float(spec.get("step_delay", 0.0))
        except (TypeError, ValueError):
            raise ControlError("memory_chars, max_steps and seed must be whole numbers, step_delay a number")
        if not 0 <= memory <= 20000:
            raise ControlError("memory_chars must be 0 to 20000")
        if not 1 <= max_steps <= 10000:
            raise ControlError("max_steps must be 1 to 10000")
        if not 0 <= delay <= 5:
            raise ControlError("step_delay must be 0 to 5 seconds")
        lineage = (spec.get("lineage") or "").strip() or None
        try:
            longterm = int(spec.get("longterm_chars") or 0)
        except (TypeError, ValueError):
            raise ControlError("longterm_chars must be a whole number")
        if lineage:
            if controller != "llm":
                raise ControlError("a lineage needs the LLM agent")
            if not NAME_RE.match(lineage):
                raise ControlError("lineage: letters, digits, _ . - only, at most 64 characters")
            if not 1 <= longterm <= 20000:
                raise ControlError("longterm_chars must be 1 to 20000 with a lineage")
            held = Lineage(lineage).holder()
            if held:
                raise ControlError(f"lineage {lineage} is held by the unfinished run {held['run_id']}; resume it first", 409)
        world = spec.get("world") or "world"
        if world not in self.worlds():
            raise ControlError(f"world must be one of {', '.join(self.worlds())}")
        default_id = (f"{lineage}_g{Lineage(lineage).next_generation}" if lineage
                      else f"{model if controller == 'llm' else controller}_{datetime.now():%Y%m%d_%H%M%S}")
        run_id = spec.get("run_id") or default_id
        if not RUN_ID_RE.match(run_id):
            raise ControlError("run id: letters, digits, _ . - only, at most 64 characters")
        if self._exists(run_id):
            raise ControlError(f"a run called {run_id} already exists", 409)
        args = ["--controller", controller, "--seed", str(seed), "--max-steps", str(max_steps),
                "--run-id", run_id, "--runs-dir", str(self.dirs[0]), "--config", str(CONFIGS_DIR / f"{world}.yaml")]
        if controller == "llm":
            args += ["--model", str(model), "--memory-chars", str(memory)]
        if lineage:
            args += ["--lineage", lineage, "--longterm-chars", str(longterm)]
        if delay > 0:
            args += ["--step-delay", str(delay)]
        run_dir = self.dirs[0] / run_id
        self._spawn(run_dir, args)
        self._wait_started(run_dir)
        return run_id

    def pause(self, run_dir: Path) -> None:
        if self.state(run_dir) not in ("running", "paused"):
            raise ControlError("the run is not running", 409)
        (run_dir / PAUSE_FILE).touch()

    def resume(self, run_dir: Path) -> None:
        """Unpause a paused run, or start a runner on a stopped one."""
        state = self.state(run_dir)
        if state == "finished":
            raise ControlError("the run is finished", 409)
        if state == "stopping":
            raise ControlError("the run is stopping, resume it once it has stopped", 409)
        if state in ("running", "paused"):
            (run_dir / PAUSE_FILE).unlink(missing_ok=True)
            return
        self._spawn(run_dir, ["--run-id", run_dir.name, "--runs-dir", str(run_dir.parent), "--resume"])
        self._wait_started(run_dir)

    def stop(self, run_dir: Path) -> None:
        if self.state(run_dir) not in ("running", "paused"):
            raise ControlError("the run is not running", 409)
        (run_dir / STOP_FILE).touch()
