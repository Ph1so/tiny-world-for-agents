"""The long-term file and lineages: prompt, parsing, controller, and runs that hand the file on
from one generation to the next. All with the mock model, no network."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tinyworld.agent.controller import LONGTERM_REJECTED, make_llm_controller
from tinyworld.agent.lineage import Lineage, LineageError
from tinyworld.agent.parser import parse_reflection, parse_reply
from tinyworld.agent.prompt import build_system_prompt, build_user_message
from tinyworld.llm.mock import MockClient
from tinyworld.runner.run import STOP_FILE, run
from tinyworld.sim import World, load_world_config

BANNED = ["goal", "should", "try to", "survive", "danger", "tip", "hint", "recipe"]


def world():
    return World(load_world_config(), seed=1)


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def run_gen(tmp_path, gen, lineage="lin", steps=90, longterm=200, **kw):
    extra = {"model": "mock", "memory_chars": 400, "history_window": 3, "longterm_chars": longterm,
             "lineage": lineage, "lineages_dir": str(tmp_path / "lineages")}
    return run(f"{lineage}_g{gen}", "llm", seed=gen, max_steps=steps, runs_dir=tmp_path / "runs",
               extra_config=extra, **kw)


# ------------------------------------------------------------------ prompt and parser

def test_prompt_is_unchanged_with_the_long_term_file_off():
    w = world()
    assert build_system_prompt(w, 3, 2000, 0) == build_system_prompt(w, 3, 2000)
    assert "long-term" not in build_system_prompt(w, 3, 2000)
    assert build_user_message("m", 2000, [], 3, "obs") == build_user_message("m", 2000, [], 3, "obs", None, 0)


def test_prompt_with_the_long_term_file():
    w = world()
    p = build_system_prompt(w, 3, 2000, 800)
    assert "Your long-term file holds at most 800 characters." in p
    assert "Your memory file starts empty in every run." in p
    assert '"longterm": [...]' in p
    assert not any(re.search(rf"\b{b}", p, re.I) for b in BANNED)
    alone = build_system_prompt(w, 3, 0, 800)
    assert "memory file" not in alone and '"memory"' not in alone and '"longterm": [...]' in alone
    u = build_user_message("world notes", 2000, [], 3, "obs", "lessons", 800)
    assert u.index("long-term file (7 of 800 characters used)") < u.index("memory file (11 of 2000")


def test_parser_reads_longterm_ops():
    p = parse_reply('{"thought": "", "memory": [], "longterm": ["eat early"], "action": {"name": "wait", "steps": 1}}')
    assert p.ok and p.longterm_ops == [{"op": "rewrite", "text": "eat early"}]
    assert parse_reply('{"action": {"name": "wait"}}').longterm_ops == []


def test_parse_reflection():
    r = parse_reflection('ok:\n```json\n{"thought": "done", "longterm": [{"op": "append", "text": "x"}]}\n```')
    assert r.ok and r.thought == "done" and r.longterm_ops == [{"op": "append", "text": "x"}]
    assert parse_reflection('{"thought": "nothing to add"}').longterm_ops == []
    assert not parse_reflection("no json here").ok


# ------------------------------------------------------------------ controller

def controller(script, longterm=50, start=""):
    return make_llm_controller("mock", 200, 3, client=MockClient(script), longterm_chars=longterm, longterm_start=start)


def test_controller_applies_and_rejects_longterm_edits():
    w = world()
    c = controller(['{"memory": [], "longterm": [{"op": "append", "text": "lesson"}], "action": {"name": "wait", "steps": 1}}',
                    '{"memory": [], "longterm": [{"op": "append", "text": "' + "x" * 60 + '"}], "action": {"name": "wait", "steps": 1}}'],
                   start="old")
    out = c.act(w.observe(), w)
    assert c.longterm.text == "old\nlesson" and out["longterm"]["accepted"]
    w.step(out["action"])
    out = c.act(w.observe(), w)
    assert out["longterm_rejected"] and c.longterm.text == "old\nlesson" and c.rejected_longterm == 1
    assert LONGTERM_REJECTED.format(n=out["longterm"]["over_by"]) in w.observe()


def test_both_rejections_are_reported_together():
    w = world()
    c = make_llm_controller("mock", 5, 3, longterm_chars=5, client=MockClient(
        ['{"memory": ["toolongmemory"], "longterm": ["toolonglongterm"], "action": {"name": "wait", "steps": 1}}']))
    c.act(w.observe(), w)
    obs = w.observe()
    assert "Memory edit rejected" in obs and "Long-term edit rejected" in obs


def test_finish_makes_one_reflection_call():
    w = world()
    c = controller(['{"thought": "summing up", "longterm": [{"op": "append", "text": "eat before 5 food"}]}'], start="a")
    rec = c.finish(w)
    assert rec["reflection"] and rec["accepted"] and rec["thought"] == "summing up"
    assert c.longterm.text == "a\neat before 5 food"
    system, user, _ = c.client.calls[-1]
    assert "The run is over." in user and "long-term file (1 of 50 characters used)" in user
    assert controller([], longterm=0).finish(w) is None


# ------------------------------------------------------------------ lineages and runs

def test_off_by_default_writes_no_longterm_file(tmp_path):
    run("plain", "llm", max_steps=20, runs_dir=tmp_path, extra_config={"model": "mock", "memory_chars": 100})
    assert not (tmp_path / "plain" / "longterm.jsonl").exists()


def test_generations_hand_the_file_on(tmp_path):
    run_gen(tmp_path, 1)
    lin = Lineage("lin", tmp_path / "lineages")
    g1 = lin.text()
    assert g1 and "run ended" in g1                    # the reflection wrote to it
    first = rows(tmp_path / "runs/lin_g1/longterm.jsonl")
    assert first[0]["i"] == 0 and first[0]["text"] == "" and first[-1]["reflection"]

    run_gen(tmp_path, 2)
    second = rows(tmp_path / "runs/lin_g2/longterm.jsonl")
    assert second[0]["text"] == g1                     # generation 2 starts where 1 ended
    assert lin.text().startswith(g1) and lin.text() != g1
    h = lin.history()
    assert [x["generation"] for x in h] == [1, 2] and [x["run_id"] for x in h] == ["lin_g1", "lin_g2"]
    assert h[1]["start_chars"] == len(g1) and h[1]["end_chars"] == len(lin.text())
    cfg = (tmp_path / "runs/lin_g2/config.yaml").read_text()
    assert "generation: 2" in cfg and "lineage: lin" in cfg and "longterm_chars: 200" in cfg
    assert not (lin.dir / "lock.json").exists()


def test_an_unfinished_run_holds_the_lineage(tmp_path):
    def stop_early(rec):
        if rec["i"] == 5:
            (tmp_path / "runs/lin_g1" / STOP_FILE).touch()
    run_gen(tmp_path, 1, on_step=stop_early)
    assert not (tmp_path / "runs/lin_g1/summary.json").exists()
    with pytest.raises(LineageError, match="held by the unfinished run lin_g1"):
        run_gen(tmp_path, 2)
    assert Lineage("lin", tmp_path / "lineages").history() == []


def test_resume_gives_the_same_file_as_an_uninterrupted_run(tmp_path):
    run_gen(tmp_path, 1, lineage="straight")

    def stop_early(rec):
        if rec["i"] == 30:
            (tmp_path / "runs/split_g1" / STOP_FILE).touch()
    run_gen(tmp_path, 1, lineage="split", on_step=stop_early)
    extra = {"model": "mock"}
    run("split_g1", "llm", max_steps=0, runs_dir=tmp_path / "runs", resume=True, extra_config=extra)
    a, b = Lineage("straight", tmp_path / "lineages"), Lineage("split", tmp_path / "lineages")
    assert a.text() == b.text() and len(b.history()) == 1


def test_a_lineage_file_over_the_limit_is_refused(tmp_path):
    lin = Lineage("big", tmp_path / "lineages")
    lin.dir.mkdir(parents=True)
    lin.text_path.write_text("x" * 300)
    with pytest.raises(LineageError, match="over longterm_chars 200"):
        run_gen(tmp_path, 1, lineage="big")


def test_bad_lineage_names_are_refused(tmp_path):
    for bad in ("", "../up", "a/b"):
        with pytest.raises(LineageError):
            Lineage(bad, tmp_path)
