"""FastAPI app that serves run folders to the viewer, live or finished.

    GET  /api/runs                       list of runs across every --runs directory
    GET  /api/runs/{run_id}/{file}       one file of a run (config.yaml, world.jsonl, ...)
    WS   /ws/runs/{run_id}               every existing line of world, steps, memory, events as
                                         {"file": "world", "line": {...}}, then new lines as they
                                         are written. The snapshot (world line 0) comes first.
    GET  /                               the built viewer (viewer/dist) when it exists

Run control (off with --read-only). Every POST needs the header X-Tinyworld: 1 and, if the
browser sends an Origin, one that matches the Host, so another web page cannot start runs:

    GET  /api/options                    models, world configs, lineages, and whether control is on
    POST /api/runs                       start a run, JSON body (see control.RunControl.start)
    POST /api/runs/{run_id}/pause        pause before the next agent step
    POST /api/runs/{run_id}/resume       unpause, or continue a stopped run with --resume
    POST /api/runs/{run_id}/stop         stop after the current step (resumable)

See docs/INTERFACES.md, "Live server".
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterator

import yaml
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from tinyworld.server.control import ControlError, RunControl

JSONL_FILES = ["world", "steps", "memory", "events", "longterm"]   # longterm only for lineage runs
SERVED_FILES = {"config.yaml", "summary.json", "prompts.json"} | {f"{n}.jsonl" for n in JSONL_FILES}
TAIL_INTERVAL_S = 0.25
DEFAULT_VIEWER_DIST = Path(__file__).resolve().parents[2] / "viewer" / "dist"


def _read_last_line(path: Path) -> dict | None:
    """The last complete JSON line of a file, read from the end."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        chunk = min(size, 65536)
        fh.seek(size - chunk)
        data = fh.read(chunk)
    lines = [ln for ln in data.split(b"\n") if ln.strip()]
    # The last line may be half written. Walk back until one parses.
    for raw in reversed(lines):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue
    return None


class RunStore:
    """Finds run folders in one or more directories. A run is a folder with config.yaml."""

    def __init__(self, runs_dirs: list[Path]):
        self.dirs = [Path(d) for d in runs_dirs]

    def find(self, run_id: str) -> Path | None:
        if not run_id or "/" in run_id or "\\" in run_id or run_id in (".", ".."):
            return None
        for d in self.dirs:
            p = d / run_id
            if (p / "config.yaml").exists():
                return p
        return None

    def list(self) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for d in self.dirs:
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if not (p / "config.yaml").exists() or p.name in seen:
                    continue
                seen.add(p.name)
                out.append(self.describe(p))
        return out

    @staticmethod
    def describe(p: Path) -> dict[str, Any]:
        try:
            cfg = yaml.safe_load((p / "config.yaml").read_text()) or {}
        except Exception:
            cfg = {}
        last = _read_last_line(p / "world.jsonl")
        agents = cfg.get("agents") or []
        multi = cfg.get("mode") == "multi"
        return {
            "run_id": p.name,
            "controller": f"multi x{len(agents)} ({cfg.get('clock', 'realtime')})" if multi else cfg.get("controller"),
            "model": ", ".join(dict.fromkeys(a.get("model") or a.get("controller") or "?" for a in agents)) if multi
                     else cfg.get("model"),
            "memory_chars": cfg.get("memory_chars", 0),
            "seed": cfg.get("seed"),
            "names": cfg.get("names", "familiar"),
            "max_steps": cfg.get("max_steps"),
            "world_steps": int(last.get("t", 0)) if last else 0,
            "finished": (p / "summary.json").exists(),
            "lineage": cfg.get("lineage"),
            "generation": cfg.get("generation"),
            "longterm_chars": cfg.get("longterm_chars", 0),
        }


class LineTailer:
    """Reads complete lines from a jsonl file, remembering the byte offset between reads."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0

    def read_new(self) -> Iterator[dict]:
        if not self.path.exists():
            return
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            data = fh.read()
        if not data:
            return
        end = data.rfind(b"\n")
        if end < 0:
            return                       # only a partial line so far
        complete, self.offset = data[: end + 1], self.offset + end + 1
        for raw in complete.split(b"\n"):
            if not raw.strip():
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


def create_app(runs_dirs: list[Path] | None = None, viewer_dist: Path | None = None,
               controls: bool = True) -> FastAPI:
    store = RunStore(runs_dirs or [Path("runs")])
    control = RunControl(store.dirs)
    app = FastAPI(title="tinyworld")
    app.state.store = store
    app.state.control = control

    def with_state(d: dict, run_dir: Path) -> dict:
        d["state"] = control.state(run_dir)
        return d

    def guard(request: Request) -> None:
        if not controls:
            raise HTTPException(403, "run control is off (server started with --read-only)")
        if request.headers.get("x-tinyworld") != "1":
            raise HTTPException(403, "missing X-Tinyworld header")
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "cross-origin request refused")

    def act(request: Request, run_id: str, fn) -> dict:
        guard(request)
        run_dir = store.find(run_id)
        if run_dir is None:
            raise HTTPException(404, "no such run")
        try:
            fn(run_dir)
        except ControlError as e:
            raise HTTPException(e.status, str(e))
        return with_state(RunStore.describe(run_dir), run_dir)

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        return [with_state(r, store.find(r["run_id"])) for r in store.list()]

    @app.get("/api/options")
    def options() -> dict:
        from .settings import SETTINGS, defaults
        worlds = control.worlds()
        return {"controls": controls, "models": control.models(), "worlds": worlds,
                "lineages": control.lineages(), "settings": SETTINGS,
                "world_defaults": {w: defaults(w) for w in worlds}}

    @app.post("/api/runs")
    def start_run(request: Request, spec: dict = Body(...)) -> dict:
        guard(request)
        try:
            run_id = control.start(spec)
        except ControlError as e:
            raise HTTPException(e.status, str(e))
        run_dir = store.find(run_id)
        return with_state(RunStore.describe(run_dir), run_dir) if run_dir else {"run_id": run_id}

    @app.post("/api/runs/{run_id}/pause")
    def pause_run(request: Request, run_id: str) -> dict:
        return act(request, run_id, control.pause)

    @app.post("/api/runs/{run_id}/resume")
    def resume_run(request: Request, run_id: str) -> dict:
        return act(request, run_id, control.resume)

    @app.post("/api/runs/{run_id}/stop")
    def stop_run(request: Request, run_id: str) -> dict:
        return act(request, run_id, control.stop)

    @app.get("/api/runs/{run_id}/{file}")
    def get_file(run_id: str, file: str):
        if file not in SERVED_FILES:
            raise HTTPException(404, "no such file")
        run_dir = store.find(run_id)
        if run_dir is None:
            raise HTTPException(404, "no such run")
        path = run_dir / file
        if not path.exists():
            raise HTTPException(404, "file not written yet")
        media = "application/json" if file.endswith(".json") else "text/plain; charset=utf-8"
        return FileResponse(path, media_type=media, headers={"Cache-Control": "no-cache"})

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        run_dir = store.find(run_id)
        if run_dir is None:
            raise HTTPException(404, "no such run")
        return JSONResponse(with_state(RunStore.describe(run_dir), run_dir))

    @app.websocket("/ws/runs/{run_id}")
    async def ws_run(ws: WebSocket, run_id: str):
        run_dir = store.find(run_id)
        if run_dir is None:
            await ws.close(code=4404)
            return
        await ws.accept()
        tailers = {name: LineTailer(run_dir / f"{name}.jsonl") for name in JSONL_FILES}
        try:
            # History first, world (snapshot at line 0) before the rest.
            for name in JSONL_FILES:
                for line in tailers[name].read_new():
                    await ws.send_json({"file": name, "line": line})
            await ws.send_json({"file": "status", "line": {"history_done": True,
                                                            "finished": (run_dir / "summary.json").exists()}})
            # Then tail. Stops when the client goes away.
            finished_sent = False
            while True:
                sent = 0
                for name in JSONL_FILES:
                    for line in tailers[name].read_new():
                        await ws.send_json({"file": name, "line": line})
                        sent += 1
                if sent == 0:
                    if not finished_sent and (run_dir / "summary.json").exists():
                        await ws.send_json({"file": "status", "line": {"finished": True}})
                        finished_sent = True
                    # Poll for a client close while idle, without blocking the tail.
                    try:
                        await asyncio.wait_for(ws.receive_text(), timeout=TAIL_INTERVAL_S)
                    except asyncio.TimeoutError:
                        pass
        except (WebSocketDisconnect, RuntimeError):
            return

    dist = viewer_dist if viewer_dist is not None else DEFAULT_VIEWER_DIST
    if dist.is_dir() and (dist / "index.html").exists():
        index = dist / "index.html"

        @app.get("/compare")
        def compare_page():
            return FileResponse(index)

        app.mount("/", StaticFiles(directory=dist, html=True), name="viewer")
    else:
        @app.get("/")
        def no_viewer():
            return JSONResponse({"message": "viewer not built. Run `npm run build` in viewer/ or use `npm run dev`.",
                                 "runs": "/api/runs"})

    return app
