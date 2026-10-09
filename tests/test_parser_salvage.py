"""The parser recovers replies that drift out of plain JSON. The fixture holds the 50 real
unreadable replies from a 519-step Haiku run (samples/haiku_night). Two causes were found:
replies cut off at the 1024 token cap (fixed by a bigger cap, not here) and function-calling
style wrapping (fixed here). The rate below is a floor; do not let it regress."""
import json
from pathlib import Path

from tinyworld.agent.parser import parse_reply

FIX = Path(__file__).parent / "fixtures" / "bad_replies.jsonl"


def _rows():
    return [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]


def test_real_bad_replies_recovery_floor():
    rows = _rows()
    ok = sum(parse_reply(r["raw"]).ok for r in rows)
    assert ok >= 30, f"recovered only {ok}/{len(rows)}"


def test_recovered_actions_are_well_formed():
    for r in _rows():
        p = parse_reply(r["raw"])
        if p.ok:
            assert isinstance(p.action.get("name"), str) and p.action["name"] in {
                "move", "mine", "place", "craft", "eat", "attack", "wait"}


def test_split_parameter_tags_become_an_action():
    raw = '<invoke> <parameter name="name">mine</parameter> <parameter name="x">33</parameter> ' \
          '<parameter name="y">8</parameter> <parameter name="z">32</parameter> </invoke>'
    p = parse_reply(raw)
    assert p.ok and p.action == {"name": "mine", "x": 33, "y": 8, "z": 32}


def test_bare_action_object_is_wrapped():
    p = parse_reply('<invoke: {"name": "move", "dir": "west", "steps": 1} Wait, JSON only.')
    assert p.ok and p.action == {"name": "move", "dir": "west", "steps": 1}


def test_key_with_stray_whitespace():
    p = parse_reply('{"thought":"t","memory":["a"]," action":{"name":"wait","steps":1}}')
    assert p.ok and p.action["name"] == "wait"


def test_param_tag_holding_action_under_other_key():
    p = parse_reply('<parameter="mine">{"name": "mine", "x": 1, "y": 2, "z": 3}</parameter> </invoke>')
    assert p.ok and p.action["name"] == "mine"


def test_empty_invoke_is_still_unreadable():
    assert not parse_reply("<invoke/>").ok


def test_invoke_named_after_the_action():
    raw = ('<invoke name="move">\n<parameter name="dir">west</parameter>\n<parameter name="steps">1</parameter>\n'
           '</invoke>\n\n<invoke name="move">\n<parameter name="dir">east</parameter>\n</invoke>')
    p = parse_reply(raw)
    assert p.ok and p.action == {"name": "move", "dir": "west", "steps": 1}
    p = parse_reply('<invoke name="craft"> <parameter name="items">{"log": 1}</parameter> </invoke> room')
    assert p.ok and p.action == {"name": "craft", "items": {"log": 1}}
    p = parse_reply('<invoke name="say"><parameter name="text">hello there</parameter></invoke>')
    assert p.ok and p.action == {"name": "say", "text": "hello there"}
    assert parse_reply('<invoke name="sleep">\n</invoke>').action == {"name": "sleep"}


def test_invoke_with_nothing_in_it_or_no_action_name_stays_unreadable():
    assert not parse_reply('<invoke name="mine">\n</invoke>\n\n<invoke name="mine">\n</invoke>').ok
    assert not parse_reply('<invoke name="reply">\n</invoke>\n<invoke name="x">\n</invoke>').ok
    assert not parse_reply('<invoke name="bash">\n</invoke>\n_placeholder').ok


def test_an_action_without_a_name_does_not_hide_a_real_one():
    raw = ('<invoke name="craft"> <parameter name="items">{"log": 1}</parameter> </invoke>\n'
           '```json\n{"thought":"","memory":[],"action":{}}\n```')
    p = parse_reply(raw)
    assert p.ok and p.action == {"name": "craft", "items": {"log": 1}}
