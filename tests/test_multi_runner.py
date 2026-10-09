"""The multi-agent runner: files, per-agent logs, both clocks, bots and mock LLM agents together."""
import json

import yaml

from tinyworld.runner.multi import run_multi
from tinyworld.sim import load_world_config


def rows(folder, name):
    return [json.loads(l) for l in (folder / f"{name}.jsonl").read_text().splitlines() if l]


AGENTS = [{"name": "Ada", "controller": "llm", "model": "mock", "memory_chars": 500},
          {"name": "Bo", "controller": "llm", "model": "mock", "memory_chars": 500},
          {"name": "Cy", "controller": "sensible_bot"}]


def test_lockstep_run_logs_every_agent(tmp_path):
    w = run_multi("trio", AGENTS, seed=2, max_steps=150, runs_dir=tmp_path, clock="lockstep")
    d = tmp_path / "trio"
    cfg = yaml.safe_load((d / "config.yaml").read_text())
    assert cfg["mode"] == "multi" and [a["name"] for a in cfg["agents"]] == ["Ada", "Bo", "Cy"]
    ids = [a["id"] for a in cfg["agents"]]
    world = rows(d, "world")
    assert world[0]["type"] == "snapshot" and [a["id"] for a in world[0]["agents"]] == ids
    assert [r["t"] for r in world[1:]] == list(range(1, w.t + 1))
    steps = rows(d, "steps")
    for aid in ids:
        mine = [s for s in steps if s["agent"] == aid]
        assert len(mine) > 10 and [s["i"] for s in mine] == list(range(1, len(mine) + 1))
        assert all(s["t_obs"] <= s["t_start"] < s["t_end"] for s in mine)
        assert f"you are agent #{aid}" in mine[0]["observation"]
    # lockstep: an agent's next action starts on the step its last one ended
    for aid in ids:
        mine = [s for s in steps if s["agent"] == aid]
        assert all(b["t_start"] == a["t_end"] for a, b in zip(mine, mine[1:]))
    assert {m["agent"] for m in rows(d, "memory")} == set(ids)
    assert all("agent" in e["detail"] for e in rows(d, "events") if e["type"] not in ("day_start", "night_start", "weather"))
    s = json.loads((d / "summary.json").read_text())
    assert s["world_steps"] == w.t >= 150 and len(s["agents"]) == 3
    p = json.loads((d / "prompts.json").read_text())
    assert set(p["system"]) == {str(ids[0]), str(ids[1])}          # the bot gets no prompt
    assert p["system"][str(ids[0])].startswith("You are in a world. The world moves forward each time you and")
    assert 'say: {"name": "say"' in p["system"][str(ids[0])] and p["history_window"] == 3


def test_lockstep_bots_are_reproducible(tmp_path):
    bots = [{"name": "A", "controller": "sensible_bot"}, {"name": "B", "controller": "sensible_bot"}]
    run_multi("a", bots, seed=3, max_steps=200, runs_dir=tmp_path, clock="lockstep")
    run_multi("b", bots, seed=3, max_steps=200, runs_dir=tmp_path, clock="lockstep")
    assert (tmp_path / "a" / "world.jsonl").read_text() == (tmp_path / "b" / "world.jsonl").read_text()


def test_realtime_world_does_not_wait_for_thinkers(tmp_path):
    w = run_multi("rt", AGENTS[:2], seed=1, max_steps=60, runs_dir=tmp_path, clock="realtime", tick_ms=5)
    steps = rows(tmp_path / "rt", "steps")
    assert w.t >= 60 and steps
    # thinking costs world steps: some action starts after the step its observation was taken at
    assert all(s["t_start"] >= s["t_obs"] for s in steps)


def test_stop_file_ends_without_summary(tmp_path):
    d = tmp_path / "stopme"
    d.mkdir()
    import threading
    def stop_soon():
        import time
        time.sleep(0.3)
        (d / "stop").write_text("")
    threading.Thread(target=stop_soon).start()
    w = run_multi("stopme", AGENTS[2:], seed=1, max_steps=10**6, runs_dir=tmp_path, clock="realtime", tick_ms=1)
    assert w.t < 10**6 and not (d / "summary.json").exists()


def test_recipe_book_reaches_multi_agent_prompts(tmp_path):
    run_multi("book", AGENTS[:1], seed=1, max_steps=5, runs_dir=tmp_path, clock="lockstep",
              world_cfg=load_world_config(recipe_book=True))
    p = json.loads((tmp_path / "book" / "prompts.json").read_text())
    assert "Everything that can be made with craft:" in next(iter(p["system"].values()))
