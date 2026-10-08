"""Tests for the live server: list runs, fetch a file, websocket streams the snapshot first and tails."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tinyworld.server import create_app

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


@pytest.fixture
def client():
    app = create_app([SAMPLES], viewer_dist=ROOT / "does-not-exist")
    with TestClient(app) as c:
        yield c


def test_list_runs(client):
    runs = client.get("/api/runs").json()
    ids = {r["run_id"] for r in runs}
    assert {"sensible_seed1", "random_seed1"} <= ids
    r = next(r for r in runs if r["run_id"] == "sensible_seed1")
    assert r["controller"] == "sensible_bot"
    assert r["seed"] == 1
    assert r["memory_chars"] == 0
    assert r["world_steps"] >= 1500
    assert r["finished"] is True           # samples are complete runs with a summary.json


def test_fetch_file(client):
    r = client.get("/api/runs/sensible_seed1/config.yaml")
    assert r.status_code == 200
    assert "run_id: sensible_seed1" in r.text
    r = client.get("/api/runs/sensible_seed1/events.jsonl")
    assert r.status_code == 200
    first = json.loads(r.text.splitlines()[0])
    assert {"t", "i", "type", "detail"} <= set(first)


def test_fetch_bad_paths(client):
    assert client.get("/api/runs/sensible_seed1/notes.txt").status_code == 404
    assert client.get("/api/runs/nope/world.jsonl").status_code == 404
    assert client.get("/api/runs/..%2Fpyproject.toml/world.jsonl").status_code == 404


def test_websocket_snapshot_first(client):
    with client.websocket_connect("/ws/runs/random_seed1") as ws:
        msg = ws.receive_json()
        assert msg["file"] == "world"
        assert msg["line"]["type"] == "snapshot"
        assert msg["line"]["t"] == 0
        seen = {"world"}
        # Read until the history marker. Every message has file and line.
        for _ in range(100000):
            msg = ws.receive_json()
            if msg["file"] == "status":
                assert msg["line"]["history_done"] is True
                break
            assert msg["file"] in ("world", "steps", "memory", "events")
            assert isinstance(msg["line"], dict)
            seen.add(msg["file"])
        else:
            pytest.fail("no history_done marker")
        assert seen == {"world", "steps", "memory", "events"}


def test_websocket_tails_growing_file(tmp_path):
    run = tmp_path / "live1"
    run.mkdir()
    (run / "config.yaml").write_text("run_id: live1\nseed: 3\ncontroller: random_bot\nmemory_chars: 0\n")
    snap = {"type": "snapshot", "t": 0, "size": [4, 4, 4]}
    (run / "world.jsonl").write_text(json.dumps(snap) + "\n")
    for name in ("steps", "memory", "events"):
        (run / f"{name}.jsonl").write_text("")
    app = create_app([tmp_path], viewer_dist=tmp_path / "nope")
    with TestClient(app) as c:
        with c.websocket_connect("/ws/runs/live1") as ws:
            assert ws.receive_json()["line"]["type"] == "snapshot"
            assert ws.receive_json()["file"] == "status"
            # Append a half line, then finish it. Only the complete line may arrive.
            with open(run / "world.jsonl", "a") as fh:
                fh.write('{"type": "step", "t": 1, "i": 1')
                fh.flush()
                fh.write(', "blocks": []}\n')
            with open(run / "events.jsonl", "a") as fh:
                fh.write(json.dumps({"t": 1, "i": 1, "type": "first_mine", "detail": {"block": "dirt"}}) + "\n")
            got = [ws.receive_json() for _ in range(2)]
            assert [g["file"] for g in got] == ["world", "events"]
            assert got[0]["line"]["t"] == 1
            (run / "summary.json").write_text("{}")
            assert ws.receive_json() == {"file": "status", "line": {"finished": True}}
