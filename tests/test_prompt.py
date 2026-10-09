"""The system prompt is PLAN.md section 7 word for word, and nothing the agent reads has advice in it."""
import re
from pathlib import Path

import pytest

from tinyworld.agent.prompt import action_lines, build_system_prompt, build_user_message
from tinyworld.agent.controller import MEMORY_REJECTED
from tinyworld.agent.parser import UNREADABLE
from tinyworld.sim import text as T
from tinyworld.sim import observe
from tinyworld.sim.defs import ALL_NAMES

from conftest import make_world

BANNED = ["goal", "should", "try to", "survive", "danger", "tip", "hint", "recipe"]
ROOT = Path(__file__).resolve().parents[1]


def banned_in(s: str) -> list[str]:
    """Whole word, case insensitive. 'danger' also catches 'dangerous', 'tip' catches 'tips'."""
    found = []
    for w in BANNED:
        if re.search(rf"\b{re.escape(w)}", s, re.I):
            found.append(w)
    return found


def plan_prompt_block() -> str:
    """The fixed text between the ``` fences right after 'Use this text exactly' in PLAN.md."""
    plan = (ROOT / "PLAN.md").read_text()
    after = plan.split("Use this text exactly.", 1)[1]
    return after.split("```", 2)[1].strip("\n")


def test_system_prompt_matches_plan_word_for_word():
    world = make_world(1)
    prompt = build_system_prompt(world, history_window=3, memory_chars=2000)
    expected = (plan_prompt_block().replace("{K}", "3").replace("{N}", "2000")
                .replace("{one line per action with its arguments, mechanical wording only}", action_lines(world)))
    assert prompt == expected


def test_system_prompt_without_memory():
    world = make_world(1)
    prompt = build_system_prompt(world, 3, 0)
    assert "memory" not in prompt.lower()
    assert '{"thought": "...", "action": {...}}' in prompt
    assert "your last 3 actions" in prompt


def test_action_lines_use_display_names():
    fam = make_world(1)
    alien = make_world(1, names="alien")
    a_fam, a_alien = action_lines(fam), action_lines(alien)
    assert a_fam != a_alien
    for name in ALL_NAMES:
        if name != "air":
            assert not re.search(rf"\b{name}\b", a_alien), name
    assert alien.dn("dirt") in a_alien and alien.dn("sand") in a_alien
    for act in ["move", "mine", "place", "craft", "eat", "attack", "wait"]:
        assert f'"name": "{act}"' in a_fam
    assert "within 3 cells" in a_fam and "within 2 cells" in a_fam


def test_banned_words_absent_everywhere_the_agent_reads():
    world = make_world(1)
    for mem in (0, 2000):
        assert banned_in(build_system_prompt(world, 3, mem)) == []
    for tpl in T.TEMPLATES:
        assert banned_in(tpl) == [], tpl
    # string literals inside observe.py (anything quoted) must be clean too
    literals = re.findall(r'"([^"\n]*)"|\'([^\'\n]*)\'', Path(observe.__file__).read_text())
    for a, b in literals:
        assert banned_in(a or b) == [], (a or b)
    assert banned_in(MEMORY_REJECTED) == [] and banned_in(UNREADABLE) == []
    assert banned_in(build_user_message("", 10, [], 3, world.observe())) == []
    for seed in (1, 2, 3):
        assert banned_in(make_world(seed).observe()) == []
        assert banned_in(make_world(seed, names="alien").observe()) == []


def test_user_message_layout():
    msg = build_user_message("a\nb", 2000, [("x", "r1"), ("y", "r2"), ("z", "r3"), ("w", "r4")], 3, "OBS")
    lines = msg.splitlines()
    assert lines[0] == "memory file (3 of 2000 characters used)"
    assert lines[1:3] == ["a", "b"]
    assert "last 3 actions:" in lines
    assert "2. y -> r2" in lines and "4. w -> r4" in lines and "1. x -> r1" not in lines
    assert lines[-2:] == ["observation:", "OBS"]
    none = build_user_message(None, 0, [], 3, "OBS")
    assert "memory file" not in none and "none yet" in none


def test_recipe_book_off_by_default_and_lists_every_craft_when_on():
    assert "can be made" not in build_system_prompt(make_world(1), 3, 2000)
    world = make_world(1, recipe_book=True)
    prompt = build_system_prompt(world, 3, 2000)
    assert banned_in(prompt) == []
    book = prompt.split(T.BOOK_HEADER, 1)[1]
    assert len([l for l in book.splitlines() if " -> " in l]) == len(world.recipes)
    assert "3 iron ingot -> 1 iron helmet (with a workbench within 2 cells)" in book
    assert "1 iron ore + 1 coal or planks -> 1 iron ingot (with a furnace within 2 cells)" in book
    assert "1 log -> 4 planks\n" in book


def test_recipe_book_follows_alien_names_and_shuffled_recipes():
    world = make_world(4, recipe_book=True, names="alien", shuffle_recipes=True)
    prompt = build_system_prompt(world, 3, 2000, longterm_chars=500)
    for name in ALL_NAMES:
        if name != "air":
            assert not re.search(rf"\b{name}\b", prompt.split(T.BOOK_HEADER, 1)[1]), name
    for r in world.recipes:
        if "fuel" not in r.items():
            inputs = " + ".join(f"{n} {world.dn(i)}" for i, n in r.inputs)
            assert f"{inputs} -> {r.count} {world.dn(r.output)}" in prompt
