"""Run control from the viewer: start, pause, resume, stop through the server, with real runner
subprocesses (sensible bot, no network), and the guard against cross-site requests."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tinyworld.runner.run import PAUSE_FILE, PID_FILE, STOP_FILE, hold
from tinyworld.server import create_app

ROOT = Path(__file__).resolve().parents[1]
H = {"X-Tinyworld": "1"}


@pytest.fixture
def client(tmp_path):
    app = create_app([tmp_path], viewer_dist=ROOT / "does-not-exist")
    with TestClient(app) as c:
        c.runs = tmp_path
        yield c
    for p in app.state.control.procs.values():      # never leave a runner behind
        if p.poll() is None:
            p.kill()


def steps(run_dir: Path) -> int:
    p = run_dir / "steps.jsonl"
    return sum(1 for _ in open(p)) if p.exists() else 0


def wait_for(fn, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if fn():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


def state(client, run_id):
    return client.get(f"/api/runs/{run_id}").json()["state"]


# ------------------------------------------------------------------ runner side

def test_hold_returns_at_once_without_files(tmp_path):
    assert hold(tmp_path) is False


def test_hold_stops_and_clears_both_files(tmp_path):
    (tmp_path / PAUSE_FILE).touch()
    (tmp_path / STOP_FILE).touch()
    assert hold(tmp_path) is True
    assert not (tmp_path / PAUSE_FILE).exists() and not (tmp_path / STOP_FILE).exists()


# ------------------------------------------------------------------ guard

def test_post_needs_the_header_and_a_matching_origin(client):
    spec = {"controller": "sensible_bot", "max_steps": 5}
    assert client.post("/api/runs", json=spec).status_code == 403
    r = client.post("/api/runs", json=spec, headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403
    assert list(client.runs.iterdir()) == []


def test_read_only_server_refuses_control(tmp_path):
    app = create_app([tmp_path], viewer_dist=ROOT / "does-not-exist", controls=False)
    with TestClient(app) as c:
        assert c.get("/api/options").json()["controls"] is False
        assert c.post("/api/runs", json={"controller": "sensible_bot"}, headers=H).status_code == 403


def test_options_lists_models_and_worlds(client):
    o = client.get("/api/options").json()
    assert o["controls"] is True
    assert "haiku" in {m["name"] for m in o["models"]}
    assert {"world", "world_hard"} <= set(o["worlds"])


@pytest.mark.parametrize("spec, code", [
    ({"controller": "nope"}, 400),
    ({"controller": "llm", "model": "no_such_model"}, 400),
    ({"controller": "sensible_bot", "run_id": "../escape"}, 400),
    ({"controller": "sensible_bot", "max_steps": 0}, 400),
    ({"controller": "sensible_bot", "world": "secret"}, 400),
])
def test_start_validates(client, spec, code):
    assert client.post("/api/runs", json=spec, headers=H).status_code == code


# ------------------------------------------------------------------ lifecycle

def test_start_pause_resume_stop_resume_finish(client):
    r = client.post("/api/runs", json={"controller": "sensible_bot", "run_id": "ctl", "max_steps": 60,
                                       "step_delay": 0.1}, headers=H)
    assert r.status_code == 200, r.text
    run_dir = client.runs / "ctl"
    assert r.json()["state"] in ("running", "finished")
    wait_for(lambda: steps(run_dir) >= 2)

    assert client.post("/api/runs/ctl/pause", headers=H).json()["state"] == "paused"
    time.sleep(0.4)                                   # let the step in flight land
    n = steps(run_dir)
    time.sleep(0.6)
    assert steps(run_dir) == n                        # nothing moves while paused

    assert client.post("/api/runs/ctl/resume", headers=H).json()["state"] == "running"
    wait_for(lambda: steps(run_dir) > n)

    client.post("/api/runs/ctl/stop", headers=H)
    wait_for(lambda: state(client, "ctl") == "stopped")
    assert not (run_dir / "summary.json").exists()    # stopped, not finished
    assert not (run_dir / PID_FILE).exists()
    assert client.post("/api/runs/ctl/pause", headers=H).status_code == 409
    n = steps(run_dir)

    assert client.post("/api/runs/ctl/resume", headers=H).status_code == 200   # --resume
    wait_for(lambda: state(client, "ctl") == "finished")
    assert steps(run_dir) > n
    last = json.loads((run_dir / "world.jsonl").read_text().splitlines()[-1])
    assert last["t"] >= 60
    assert client.post("/api/runs/ctl/resume", headers=H).status_code == 409


def test_start_refuses_an_existing_run_id(client):
    r = client.post("/api/runs", json={"controller": "sensible_bot", "run_id": "dup", "max_steps": 3}, headers=H)
    assert r.status_code == 200
    assert client.post("/api/runs", json={"controller": "sensible_bot", "run_id": "dup"}, headers=H).status_code == 409


def test_a_runner_that_fails_reports_its_log(client, monkeypatch):
    monkeypatch.setattr(client.app.state.control, "python", "/bin/sh")     # sh -m ... fails at once
    r = client.post("/api/runs", json={"controller": "sensible_bot", "run_id": "bad"}, headers=H)
    assert r.status_code == 500 and "the runner exited" in r.json()["detail"]
    monkeypatch.setattr(client.app.state.control, "python", str(ROOT / "no-such-python"))
    r = client.post("/api/runs", json={"controller": "sensible_bot", "run_id": "bad2"}, headers=H)
    assert r.status_code == 500 and "could not launch" in r.json()["detail"]
