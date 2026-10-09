"""memory_layout "sections": GOAL / LESSONS / NOTES, with lessons a rewrite cannot remove."""
import json

import yaml

from tinyworld.agent.controller import LLMController, make_llm_controller
from tinyworld.agent.memory import GOAL_CHARS, SectionedMemory, parse_sections
from tinyworld.agent.prompt import SECTIONS_PARAGRAPH, build_system_prompt
from tinyworld.llm import ModelSpec
from tinyworld.llm.mock import MockClient
from tinyworld.runner.run import run

from conftest import flat_world


def sections(goal="", lessons=(), notes=""):
    m = SectionedMemory(4000)
    m.goal, m.lessons, m.notes = goal, list(lessons), notes
    return m


def test_empty_file_shows_the_three_parts():
    assert SectionedMemory(4000).text == "GOAL: (not set)\nLESSONS: (none yet)\nNOTES:"


def test_goal_lesson_and_append_ops():
    m = SectionedMemory(4000)
    r = m.apply([{"op": "goal", "text": "a bed by the farm\nsecond line dropped"},
                 {"op": "lesson", "text": "- craft takes 1 log at a time"},
                 {"op": "lesson", "text": "Craft takes 1 log at a time"},          # same lesson, skipped
                 {"op": "append", "text": "[step 3] logs at (1,2,3)"},
                 {"op": "append", "text": "[step 3] LESSON: seeds are not food"},
                 {"op": "append", "text": "[step 3] GOAL: iron sword"}], step=1)
    assert r.accepted and r.applied == 6
    assert m.goal == "iron sword"
    assert m.lessons == ["craft takes 1 log at a time", "seeds are not food"]
    assert m.notes == "[step 3] logs at (1,2,3)"
    assert m.apply([{"op": "goal", "text": "x" * 500}], 2).accepted and len(m.goal) == GOAL_CHARS


def test_rewrite_replaces_notes_but_keeps_goal_and_lessons():
    m = sections("bed", ["rain doubles food drain"], "old notes")
    m.apply([{"op": "rewrite", "text": "new notes"}], 1)
    assert (m.goal, m.lessons, m.notes) == ("bed", ["rain doubles food drain"], "new notes")


def test_rewrite_of_whole_file_keeps_lessons_and_adds_new_ones():
    """A model that sends the file back as a snapshot, dropping one lesson and adding another."""
    m = sections("bed", ["rain doubles food drain", "seeds are not food"], "a")
    m.apply([{"op": "rewrite", "text": "GOAL: chest\nLESSONS:\n- seeds are not food\n- torches stop zombies\nNOTES:\nb"}], 1)
    assert m.goal == "chest" and m.notes == "b"
    assert m.lessons == ["rain doubles food drain", "seeds are not food", "torches stop zombies"]


def test_replace_edits_or_removes_a_lesson():
    m = sections("", ["eat when food < 10", "seeds are not food"], "food 12")
    m.apply([{"op": "replace", "old": "food < 10", "new": "food < 12"}], 1)
    assert m.lessons[0] == "eat when food < 12"
    m.apply([{"op": "replace", "old": "food 12", "new": "food 9"}], 2)          # notes first
    assert m.notes == "food 9" and m.lessons[0] == "eat when food < 12"
    m.apply([{"op": "replace", "old": "- seeds are not food", "new": ""}], 3)
    assert m.lessons == ["eat when food < 12"]


def test_limit_is_all_or_nothing_and_counts_every_part():
    m = SectionedMemory(60)
    r = m.apply([{"op": "lesson", "text": "x" * 40}, {"op": "append", "text": "note"}], 1)
    assert not r.accepted and r.over_by > 0 and m.lessons == [] and m.notes == ""


def test_parse_round_trip_and_plain_text():
    m = sections("bed", ["a", "b"], "n1\nn2")
    assert parse_sections(m.text) == ("bed", ["a", "b"], "n1\nn2", True)
    assert parse_sections("just notes\nmore") == ("", [], "just notes\nmore", False)
    other = SectionedMemory(4000)
    other.set(m.text, 1)
    assert other.text == m.text


def controller(script, layout="sections"):
    spec = ModelSpec(provider="mock", model="m", input_per_m=1.0, output_per_m=2.0)
    return LLMController(MockClient(script), spec, 4000, 3, memory_plain="append", memory_layout=layout)


def test_controller_stamps_notes_and_keeps_lessons_through_a_rewrite():
    w = flat_world()
    reply = lambda mem: json.dumps({"memory": mem, "action": {"name": "wait", "steps": 2}})
    c = controller([reply([{"op": "lesson", "text": "craft takes 1 log at a time"}, "logs at (1,2,3)"]),
                    reply([{"op": "rewrite", "text": "fresh notes"}])])
    c.act(w.observe(), w)
    w.step({"name": "wait", "steps": 2})
    assert c.memory.lessons == ["craft takes 1 log at a time"] and c.memory.notes == "[step 0] logs at (1,2,3)"
    c.act(w.observe(), w)
    assert c.memory.lessons == ["craft takes 1 log at a time"] and c.memory.notes == "fresh notes"
    assert c.user_message(w.observe()).startswith("memory file (")
    assert "LESSONS:\n- craft takes 1 log at a time" in c.user_message(w.observe())


def test_prompt_only_changes_with_sections_on():
    w = flat_world()
    plain = build_system_prompt(w, 3, 4000, 0, "append")
    on = build_system_prompt(w, 3, 4000, 0, "append", memory_layout="sections")
    assert build_system_prompt(w, 3, 4000, 0, "append", memory_layout="plain") == plain
    assert "LESSONS" not in plain
    assert "A rewrite never removes the goal or a lesson." in on and '{"op": "lesson"' in on
    assert "add a lesson, so you do not make the same mistake again" in on
    assert SECTIONS_PARAGRAPH.split("\n")[1][:40] in on


def test_run_with_sections_logs_layout_and_resumes(tmp_path):
    full = run("full", "llm", seed=2, max_steps=120, runs_dir=tmp_path / "a",
               extra_config={"model": "mock", "memory_chars": 600, "history_window": 3, "memory_layout": "sections"})
    part = run("part", "llm", seed=2, max_steps=60, runs_dir=tmp_path / "b",
               extra_config={"model": "mock", "memory_chars": 600, "history_window": 3, "memory_layout": "sections"})
    resumed = run("part", "llm", max_steps=120, runs_dir=tmp_path / "b", resume=True)
    assert part.t < full.t and resumed.state_hash() == full.state_hash()
    cfg = yaml.safe_load((tmp_path / "a" / "full" / "config.yaml").read_text())
    assert cfg["memory_layout"] == "sections"
    mem = [json.loads(x) for x in (tmp_path / "a" / "full" / "memory.jsonl").read_text().splitlines()]
    assert all(m["text"].startswith("GOAL:") for m in mem if m["text"])
    c = make_llm_controller("mock", 600, memory_layout="sections")
    assert c.config_extras()["memory_layout"] == "sections"
