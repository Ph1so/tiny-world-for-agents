"""Memory file, reply parser, and the LLM controller through the real run loop with the mock adapter."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tinyworld.agent.controller import LLMController, MEMORY_REJECTED, make_llm_controller
from tinyworld.agent.memory import MemoryFile
from tinyworld.agent.parser import UNREADABLE, WAIT_ONE, parse_reply
from tinyworld.llm import ModelSpec, get_model
from tinyworld.llm.mock import MockClient, SensibleMockClient
from tinyworld.runner.run import run
from tinyworld.sim import load_world_config

from conftest import flat_world, make_world

STEP_KEYS = {"i", "t_start", "t_end", "observation", "raw_reply", "thought", "action", "result", "valid", "parse_ok",
             "died", "vitals", "memory_chars_used", "memory_rejected", "input_tokens", "output_tokens", "latency_s",
             "cost_usd"}
MEMORY_KEYS = {"i", "t", "ops", "accepted", "over_by", "text", "chars", "limit"}


def rows(folder, name):
    return [json.loads(line) for line in (Path(folder) / f"{name}.jsonl").read_text().splitlines()]


# ----------------------------------------------------------------- memory


def test_memory_ops_in_order_and_versions():
    m = MemoryFile(100)
    r = m.apply([{"op": "append", "text": "one"}, {"op": "append", "text": "two"},
                 {"op": "replace", "old": "two", "new": "2"}], step=1)
    assert r.accepted and m.text == "one\n2" and r.chars == 5 and r.applied == 3
    r = m.apply([{"op": "rewrite", "text": "fresh"}], step=2)
    assert m.text == "fresh" and [s for s, _ in m.versions] == [1, 2]
    r = m.apply([], step=3)
    assert r.accepted and len(m.versions) == 2                 # no change, no version


def test_memory_over_limit_is_all_or_nothing():
    m = MemoryFile(10)
    m.apply([{"op": "append", "text": "12345"}], 1)
    r = m.apply([{"op": "replace", "old": "1", "new": "x"}, {"op": "append", "text": "abcdefg"}], 2)
    assert not r.accepted and r.over_by == 3 and r.text == "12345" and m.text == "12345"
    assert r.record() == {"ops": r.ops, "accepted": False, "over_by": 3, "text": "12345", "chars": 5, "limit": 10}
    assert len(m.versions) == 1


def test_memory_malformed_ops_are_skipped():
    m = MemoryFile(50)
    r = m.apply(["junk", {"op": "nope"}, {"op": "replace", "old": "", "new": "x"},
                 {"op": "replace", "old": "missing", "new": "x"}, {"op": "append", "text": "ok"}], 1)
    assert r.accepted and m.text == "ok" and r.applied == 1 and r.skipped == 4


def test_memory_wipe():
    m = MemoryFile(50)
    m.apply([{"op": "append", "text": "x"}], 1)
    m.wipe(2)
    assert m.text == "" and m.versions[-1] == (2, "")


# ----------------------------------------------------------------- parser


GOOD = {"thought": "hm", "memory": [{"op": "append", "text": "a"}], "action": {"name": "move", "dir": "north", "steps": 2}}


@pytest.mark.parametrize("text", [
    json.dumps(GOOD),
    "```json\n" + json.dumps(GOOD) + "\n```",
    "```\n" + json.dumps(GOOD) + "```",
    "Sure, here is my reply:\n" + json.dumps(GOOD) + "\nLet me know.",
    json.dumps(GOOD, indent=2) + " trailing",
    '{"note": 1} ' + json.dumps(GOOD),
])
def test_parse_tolerant(text):
    p = parse_reply(text)
    assert p.ok and p.thought == "hm" and p.action == GOOD["action"] and p.memory_ops == GOOD["memory"]


@pytest.mark.parametrize("text", ["", "   ", "no json here", "{not json", '{"thought": "x"}',
                                  '{"action": "move"}', '{"action": {"dir": "north"}}', "[1, 2]"])
def test_parse_failures_give_one_step_wait(text):
    p = parse_reply(text)
    assert not p.ok and p.action == WAIT_ONE and p.memory_ops == [] and p.error


def test_parse_odd_shapes():
    p = parse_reply('{"thought": {"a": 1}, "memory": {"op": "append", "text": "x"}, "action": {"name": "wait"}}')
    assert p.ok and p.thought == '{"a": 1}' and p.memory_ops == [{"op": "append", "text": "x"}]
    # a bare string memory is read as a rewrite to that string (see normalize_memory)
    p = parse_reply('{"memory": "bad", "action": {"name": "wait"}}')
    assert p.ok and p.memory_ops == [{"op": "rewrite", "text": "bad"}] and p.thought == ""


# ----------------------------------------------------------------- controller, one step at a time


def controller(script, memory_chars=50, history_window=3, on_death="respawn_keep_memory"):
    spec = ModelSpec(provider="mock", model="m", input_per_m=1.0, output_per_m=2.0)
    return LLMController(MockClient(script, input_tokens=1000, output_tokens=500), spec, memory_chars, history_window, on_death)


def test_one_step_fields_and_cost():
    w = flat_world()
    c = controller([json.dumps(GOOD)])
    assert c.memory_limit == 50
    out = c.act(w.observe(), w)
    assert out["action"] == GOOD["action"] and out["parse_ok"] and out["thought"] == "hm"
    assert out["raw_reply"] == json.dumps(GOOD)
    assert out["input_tokens"] == 1000 and out["output_tokens"] == 500
    assert out["cost_usd"] == pytest.approx((1000 * 1.0 + 500 * 2.0) / 1e6)
    assert out["memory"] == {"ops": GOOD["memory"], "accepted": True, "over_by": 0, "text": "a", "chars": 1, "limit": 50}
    assert out["memory_chars_used"] == 1 and out["memory_rejected"] is False and "events" not in out
    sys_prompt, user, max_tokens = c.client.calls[0]
    assert sys_prompt.startswith("You are in a world.") and user.startswith("memory file (0 of 50 characters used)")
    assert max_tokens == 1024
    res = w.step(out["action"])
    c.on_result(res, w)
    assert c.history == [('{"name": "move", "dir": "north", "steps": 2}', res.text)]
    out2 = c.act(w.observe(), w)
    user2 = c.client.calls[1][1]
    assert "memory file (1 of 50 characters used)\na\n" in user2
    assert '1. {"name": "move", "dir": "north", "steps": 2} -> ' + res.text in user2
    assert "memory" not in out2 or out2["memory"]["ops"] == GOOD["memory"]


def test_rejected_edit_sets_notice_and_event():
    w = flat_world()
    big = {"thought": "", "memory": [{"op": "append", "text": "x" * 60}], "action": {"name": "wait", "steps": 1}}
    c = controller([json.dumps(big)])
    out = c.act(w.observe(), w)
    assert out["memory_rejected"] and out["memory"]["accepted"] is False and out["memory"]["over_by"] == 10
    assert out["events"] == [{"type": "memory_rejected", "detail": {"over_by": 10, "ops": 1}}]
    w.step(out["action"])
    assert MEMORY_REJECTED.format(n=10) in w.observe()
    w.step(WAIT_ONE)
    assert "Memory edit rejected" not in w.observe()


def test_parse_failure_waits_and_sets_notice():
    w = flat_world()
    c = controller(["garbage"])
    out = c.act(w.observe(), w)
    assert out["action"] == WAIT_ONE and out["parse_ok"] is False and out["raw_reply"] == "garbage"
    assert out["events"][0]["type"] == "parse_fail" and c.parse_fails == 1
    assert "memory" not in out
    w.step(out["action"])
    assert UNREADABLE in w.observe()


def test_memory_off_hides_memory_and_ignores_ops():
    w = flat_world()
    c = controller([json.dumps(GOOD)], memory_chars=0)
    out = c.act(w.observe(), w)
    assert "memory" not in out and out["memory_chars_used"] == 0 and c.memory_limit == 0
    sys_prompt, user, _ = c.client.calls[0]
    assert "memory" not in sys_prompt.lower() and "memory file" not in user


def test_wipe_on_death():
    w = flat_world(on_death="respawn_wipe_memory")
    w.food, w.health = 0, 1
    c = controller([json.dumps(GOOD), json.dumps(GOOD)], on_death="respawn_wipe_memory")
    out = c.act(w.observe(), w)
    assert c.memory.text == "a"
    res = w.step({"name": "wait", "steps": 8})
    assert res.died == "hunger"
    c.on_result(res, w)
    assert c.memory.text == "" and c.deaths == 1
    out2 = c.act(w.observe(), w)
    assert out2["memory"]["ops"][0] == {"op": "wipe", "reason": "death"}
    assert out2["memory"]["text"] == "a" and out2["memory"]["accepted"]       # wiped, then this step's append


def test_keep_memory_on_death():
    w = flat_world()
    w.food, w.health = 0, 1
    c = controller([json.dumps(GOOD)])
    c.act(w.observe(), w)
    res = w.step({"name": "wait", "steps": 8})
    assert res.died
    c.on_result(res, w)
    assert c.memory.text == "a"


# ----------------------------------------------------------------- full runs through the run loop


@pytest.fixture(scope="module")
def mock_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("runs")
    world = run("mock200", "llm", seed=1, max_steps=200, runs_dir=d,
                extra_config={"model": "mock", "memory_chars": 300, "history_window": 3})
    return d / "mock200", world


def test_full_mock_run_logs_every_file(mock_run):
    folder, world = mock_run
    for name in ["config.yaml", "steps.jsonl", "world.jsonl", "memory.jsonl", "events.jsonl"]:
        assert (folder / name).exists() and (folder / name).stat().st_size > 0
    cfg = yaml.safe_load((folder / "config.yaml").read_text())
    assert cfg["controller"] == "llm" and cfg["model"] == "mock" and cfg["memory_chars"] == 300
    assert cfg["history_window"] == 3 and cfg["max_tokens"] == 1024 and cfg["provider"] == "mock"
    assert "llm_settings" in cfg and "prices_per_m" in cfg and cfg["model_id"] == "mock-sensible"

    steps = rows(folder, "steps")
    assert world.t >= 200 and [s["i"] for s in steps] == list(range(1, len(steps) + 1))
    assert all(set(s) == STEP_KEYS for s in steps)
    assert all(s["raw_reply"] and s["input_tokens"] > 0 and s["output_tokens"] > 0 for s in steps)
    assert all(s["cost_usd"] == 0.0 for s in steps)
    assert all(s["thought"].startswith("mock step") for s in steps if s["parse_ok"])
    assert steps[-1]["t_end"] == world.t

    mem = rows(folder, "memory")
    assert mem[0] == {"i": 0, "t": 0, "ops": [], "accepted": True, "over_by": 0, "text": "", "chars": 0, "limit": 300}
    assert all(set(m) == MEMORY_KEYS and m["limit"] == 300 for m in mem)
    assert all(m["chars"] == len(m["text"]) <= 300 for m in mem)
    assert all(m["ops"] for m in mem[1:])
    by_i = {s["i"]: s for s in steps}
    for m in mem[1:]:
        assert m["t"] == by_i[m["i"]]["t_start"] and by_i[m["i"]]["memory_chars_used"] == m["chars"]
    accepted = [m for m in mem[1:] if m["accepted"]]
    assert len(accepted) >= 5 and accepted[-1]["text"]

    rejected = [m for m in mem if not m["accepted"]]
    assert rejected, "the mock sends over limit edits, some must be rejected"
    for m in rejected:
        assert m["over_by"] > 0 and by_i[m["i"]]["memory_rejected"] is True
    events = rows(folder, "events")
    rej_events = [e for e in events if e["type"] == "memory_rejected"]
    assert {e["i"] for e in rej_events} == {m["i"] for m in rejected}
    for e in rej_events:
        assert e["t"] == by_i[e["i"]]["t_start"]
        assert MEMORY_REJECTED.format(n=e["detail"]["over_by"]) in by_i[e["i"] + 1]["observation"]

    fails = [s for s in steps if not s["parse_ok"]]
    assert fails, "the mock sends unreadable replies, some must be counted"
    assert len([e for e in events if e["type"] == "parse_fail"]) == len(fails)
    for s in fails:
        assert s["action"] == WAIT_ONE and s["t_end"] - s["t_start"] == 1
        assert UNREADABLE in by_i[s["i"] + 1]["observation"]

    assert world.firsts["craft"], "the sensible mock made progress"


def test_resume_llm_run_matches_unbroken_run(tmp_path):
    full = run("full", "llm", seed=3, max_steps=240, runs_dir=tmp_path / "a",
               extra_config={"model": "mock", "memory_chars": 300, "history_window": 3})
    part = run("part", "llm", seed=3, max_steps=120, runs_dir=tmp_path / "b",
               extra_config={"model": "mock", "memory_chars": 300, "history_window": 3})
    assert part.t < full.t
    # cut the last step line in half to check the trim of a half written step
    sp = tmp_path / "b" / "part" / "steps.jsonl"
    lines = sp.read_text().splitlines()
    sp.write_text("\n".join(lines[:-1]) + "\n" + lines[-1][:20])
    resumed = run("part", "llm", max_steps=240, runs_dir=tmp_path / "b", resume=True)
    assert resumed.state_hash() == full.state_hash()
    for name in ["steps", "memory", "events", "world"]:
        a, b = rows(tmp_path / "a" / "full", name), rows(tmp_path / "b" / "part", name)
        assert a == b, name
    cfg = yaml.safe_load((tmp_path / "b" / "part" / "config.yaml").read_text())
    assert cfg["max_steps"] == 120                                   # the stored config is kept on resume


def test_resume_rebuilds_memory_and_notice(tmp_path):
    """A resumed controller holds the same memory text and pending notice the live one had."""
    runs_dir = tmp_path
    run("r", "llm", seed=1, max_steps=120, runs_dir=runs_dir,
        extra_config={"model": "mock", "memory_chars": 300, "history_window": 3})
    mem = rows(runs_dir / "r", "memory")
    steps = rows(runs_dir / "r", "steps")
    c = make_llm_controller("mock", 300, 3, seed=1)
    world = make_world(1)
    from tinyworld.runner.run import RunLogger, run_loop
    logger = RunLogger(runs_dir / "r", resume=True)
    try:
        run_loop(world, c, logger, max_steps=0)                      # replay only
    finally:
        logger.close()
    assert c.i == len(steps) and c.memory.text == mem[-1]["text"]
    assert c.parse_fails == len([s for s in steps if not s["parse_ok"]])
    assert c.rejected_edits == len([m for m in mem if not m["accepted"]])
    assert c.history[-1][1] == steps[-1]["result"]


def test_alien_mode_mock_run(tmp_path):
    world = run("alien", "llm", seed=2, max_steps=60, runs_dir=tmp_path,
                world_cfg=load_world_config(names="alien", shuffle_recipes=True),
                extra_config={"model": "mock", "memory_chars": 500, "history_window": 2})
    steps = rows(tmp_path / "alien", "steps")
    assert all(s["valid"] for s in steps if s["parse_ok"]), "the mock bot speaks the shown names"
    c = make_llm_controller("mock", 500, 2, seed=2)
    assert "planks" not in c.system_prompt(world) and world.dn("dirt") in c.system_prompt(world)


def test_cli_llm_run_and_run_config(tmp_path):
    root = Path(__file__).resolve().parents[1]
    cfg = tmp_path / "run.yaml"
    cfg.write_text(yaml.safe_dump({"controller": "llm", "model": "mock", "seed": 4, "max_steps": 40,
                                   "memory_chars": 200, "history_window": 2, "runs_dir": str(tmp_path / "runs")}))
    out = subprocess.run([sys.executable, "-m", "tinyworld.runner.run", "--run-config", str(cfg), "--memory-chars", "150"],
                         capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stderr
    folder = tmp_path / "runs" / "llm_mock_seed4"
    c = yaml.safe_load((folder / "config.yaml").read_text())
    assert c["memory_chars"] == 150 and c["history_window"] == 2 and c["seed"] == 4 and c["model"] == "mock"
    assert rows(folder, "memory")[0]["limit"] == 150
    out = subprocess.run([sys.executable, "-m", "tinyworld.runner.run", "--controller", "llm", "--max-steps", "5"],
                         capture_output=True, text=True, cwd=root)
    assert out.returncode != 0 and "--model" in out.stderr
    out = subprocess.run([sys.executable, "-m", "tinyworld.runner.run", "--run-config", str(cfg), "--resume"],
                         capture_output=True, text=True, cwd=root)
    assert out.returncode == 0, out.stderr


# --- memory field coercion from real-model shapes (added after the first Haiku run) ---
from tinyworld.agent.parser import normalize_memory, parse_reply


def test_normalize_memory_list_of_strings_is_rewrite():
    ops = normalize_memory(["line a", "line b"])
    assert ops == [{"op": "rewrite", "text": "line a\nline b"}]


def test_normalize_memory_bare_string_is_rewrite():
    assert normalize_memory("notes") == [{"op": "rewrite", "text": "notes"}]


def test_normalize_memory_op_dicts_pass_through():
    ops = [{"op": "append", "text": "x"}, {"op": "rewrite", "text": "y"}]
    assert normalize_memory(ops) == ops


def test_normalize_memory_mixed_list():
    ops = normalize_memory(["note", {"op": "replace", "old": "a", "new": "b"}])
    assert ops == [{"op": "append", "text": "note"},
                   {"op": "replace", "old": "a", "new": "b"}]


def test_list_of_strings_memory_actually_lands_in_file():
    reply = ('{"thought":"t","memory":["Start (1,2,3)","Plan: gather"],'
             '"action":{"name":"wait","steps":1}}')
    p = parse_reply(reply)
    assert p.ok
    from tinyworld.agent.memory import MemoryFile
    mf = MemoryFile(limit=2000)
    res = mf.apply(p.memory_ops, step=1)
    assert res.accepted and mf.text == "Start (1,2,3)\nPlan: gather"
