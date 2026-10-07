"""Run folder format, replay from the log alone, and resume."""
import base64
import json
import zlib

import numpy as np
import pytest
import yaml

from tinyworld.runner.run import RunLogger, run, run_loop
from tinyworld.sim import World, load_world_config
from tinyworld.sim.defs import BLOCKS

FILES = ["world", "steps", "memory", "events"]


def rows(folder, name):
    return [json.loads(line) for line in (folder / f"{name}.jsonl").read_text().splitlines()]


def replay_blocks(folder) -> tuple[np.ndarray, dict]:
    """Rebuild the final block grid from world.jsonl alone."""
    lines = rows(folder, "world")
    snap = lines[0]
    sx, sy, sz = snap["size"]
    grid = np.frombuffer(zlib.decompress(base64.b64decode(snap["blocks_b64"])), dtype=np.uint8).copy()
    pal = {n: i for i, n in enumerate(snap["palette"])}
    for line in lines[1:]:
        for x, y, z, name in line["blocks"]:
            grid[x + z * sx + y * sx * sz] = pal[name]
    return grid.reshape(sy, sz, sx), lines[-1]


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("runs")
    world = run("full", "sensible_bot", seed=2, max_steps=450, runs_dir=d)
    return d / "full", world


def test_files_and_keys(full_run):
    folder, world = full_run
    cfg = yaml.safe_load((folder / "config.yaml").read_text())
    for key in ["run_id", "seed", "controller", "model", "memory_chars", "history_window", "names",
                "on_death", "max_steps", "git_commit", "world"]:
        assert key in cfg
    assert cfg["controller"] == "sensible_bot" and cfg["model"] is None and cfg["seed"] == 2
    assert cfg["world"] == load_world_config().model_dump(mode="json")

    w = rows(folder, "world")
    assert set(w[0]) >= {"type", "t", "size", "sea_level", "palette", "blocks_b64", "agent", "creatures",
                         "light", "day", "display_names"}
    assert w[0]["type"] == "snapshot" and w[0]["size"] == [64, 32, 64] and w[0]["palette"] == BLOCKS
    assert [r["t"] for r in w[1:]] == list(range(1, world.t + 1))
    assert all(set(r) == {"type", "t", "i", "blocks", "agent", "creatures", "light", "day"} for r in w[1:])
    assert set(w[1]["agent"]) == {"pos", "health", "food", "air", "inventory", "tools"}

    s = rows(folder, "steps")
    assert [r["i"] for r in s] == list(range(1, len(s) + 1))
    assert s[0]["t_start"] == 0 and s[-1]["t_end"] == world.t >= 450
    assert all(a["t_end"] == b["t_start"] for a, b in zip(s, s[1:]))
    for key in ["observation", "raw_reply", "thought", "action", "result", "valid", "parse_ok", "vitals",
                "memory_chars_used", "memory_rejected", "input_tokens", "output_tokens", "latency_s", "cost_usd"]:
        assert key in s[0]
    assert s[0]["raw_reply"] == "" and s[0]["thought"] == "" and s[0]["cost_usd"] == 0
    assert s[0]["observation"].startswith("step 0 | day 1 | light bright")
    by_i = {}
    for r in w[1:]:
        by_i.setdefault(r["i"], []).append(r["t"])
    assert all(by_i[r["i"]] == list(range(r["t_start"] + 1, r["t_end"] + 1)) for r in s)

    assert rows(folder, "memory") == [{"i": 0, "t": 0, "ops": [], "accepted": True, "over_by": 0,
                                       "text": "", "chars": 0, "limit": 0}]
    e = rows(folder, "events")
    assert all(set(r) == {"t", "i", "type", "detail"} for r in e)
    types = {r["type"] for r in e}
    assert {"first_mine", "first_craft", "first_place", "first_eat", "night_start", "day_start"} <= types


def test_log_alone_reproduces_the_final_world(full_run):
    folder, world = full_run
    grid, last = replay_blocks(folder)
    assert (grid == world.blocks).all()
    assert (grid != World(load_world_config(), 2).blocks).sum() > 20      # the run did change the map
    assert last["agent"]["pos"] == world.pos and last["agent"]["inventory"] == world.inv
    assert last["creatures"] == world._creature_list()


class Crash(Exception):
    pass


def crash_at(n):
    def hook(record):
        if record["i"] == n:
            raise Crash
    return hook


@pytest.mark.parametrize("bot", ["sensible_bot", "random_bot"])
def test_resume_gives_the_same_files_as_an_unbroken_run(tmp_path, bot):
    a = run("a", bot, seed=3, max_steps=450, runs_dir=tmp_path)
    with pytest.raises(Crash):
        run("b", bot, seed=3, max_steps=450, runs_dir=tmp_path, on_step=crash_at(60))
    assert len(rows(tmp_path / "b", "steps")) == 60
    # A crash in the middle of step 61: its world lines are on disk, its steps line is half written.
    with open(tmp_path / "b" / "world.jsonl", "a") as f:
        f.write(json.dumps({"type": "step", "t": 99999, "i": 61, "blocks": []}) + "\n")
    with open(tmp_path / "b" / "events.jsonl", "a") as f:
        f.write(json.dumps({"t": 99999, "i": 61, "type": "hurt", "detail": {}}) + "\n")
    with open(tmp_path / "b" / "steps.jsonl", "a") as f:
        f.write('{"i": 61, "t_start": 12')
    b = run("b", bot, seed=1234, max_steps=450, runs_dir=tmp_path, resume=True)
    assert b.state_hash() == a.state_hash()
    for name in FILES:
        assert (tmp_path / "a" / f"{name}.jsonl").read_text() == (tmp_path / "b" / f"{name}.jsonl").read_text(), name
    # Resuming a finished run changes nothing.
    c = run("b", bot, max_steps=450, runs_dir=tmp_path, resume=True)
    assert c.state_hash() == a.state_hash()
    assert (tmp_path / "a" / "steps.jsonl").read_text() == (tmp_path / "b" / "steps.jsonl").read_text()


def test_resume_without_a_folder_starts_fresh(tmp_path):
    w = run("new", "random_bot", seed=1, max_steps=20, runs_dir=tmp_path, resume=True)
    assert w.t >= 20 and len(rows(tmp_path / "new", "steps")) >= 3


class Scripted:
    """Stands in for an LLM controller: returns the rich form and uses every hook."""
    memory_limit = 100

    def __init__(self):
        self.results, self.replayed, self.n = [], 0, 0

    def act(self, observation, world):
        self.n += 1
        if self.n == 2:
            world.set_notice("Your reply could not be read.")
            return {"action": {"name": "wait", "steps": 1}, "raw_reply": "garbage", "parse_ok": False,
                    "events": [{"type": "parse_fail", "detail": {}}], "input_tokens": 10}
        return {"action": {"name": "move", "dir": "north", "steps": 1}, "raw_reply": "{...}", "thought": "hm",
                "input_tokens": 900, "output_tokens": 120, "latency_s": 1.2, "cost_usd": 0.004,
                "memory_chars_used": 5, "memory_rejected": False,
                "memory": {"ops": [{"op": "append", "text": "hello"}], "accepted": True, "over_by": 0,
                           "text": "hello", "chars": 5, "limit": 100}}

    def on_result(self, result, world):
        self.results.append(result.text)

    def replay(self, observation, world, step_record, memory_record):
        self.n += 1
        self.replayed += 1
        assert (memory_record is None) == (step_record["i"] == 2)


def test_rich_controller_is_logged_and_can_resume(tmp_path):
    world = World(load_world_config(), 1)
    logger = RunLogger(tmp_path / "x")
    ctl = Scripted()
    run_loop(world, ctl, logger, max_steps=3)
    logger.close()
    s, m, e = (rows(tmp_path / "x", n) for n in ("steps", "memory", "events"))
    assert len(s) == 3 and len(ctl.results) == 3
    assert s[0]["thought"] == "hm" and s[0]["input_tokens"] == 900 and s[0]["cost_usd"] == 0.004
    assert s[0]["memory_chars_used"] == 5 and s[1]["parse_ok"] is False and s[1]["raw_reply"] == "garbage"
    assert "Your reply could not be read." in s[2]["observation"]
    assert "Your reply could not be read." not in s[1]["observation"]
    assert [r["i"] for r in m] == [0, 1, 3] and m[0]["limit"] == 100 and m[1]["text"] == "hello" and m[1]["t"] == 0
    assert {"t": 1, "i": 2, "type": "parse_fail", "detail": {}} in e

    world2, ctl2 = World(load_world_config(), 1), Scripted()
    logger2 = RunLogger(tmp_path / "x", resume=True)
    assert logger2.last_i == 3
    run_loop(world2, ctl2, logger2, max_steps=5)
    logger2.close()
    assert ctl2.replayed == 3 and len(ctl2.results) == 5
    assert [r["i"] for r in rows(tmp_path / "x", "steps")] == [1, 2, 3, 4, 5]
    assert len(rows(tmp_path / "x", "world")) == 6
