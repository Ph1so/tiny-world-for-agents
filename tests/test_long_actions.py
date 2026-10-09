"""long_actions: goto (walk to a cell or creature) and "repeat" on any action."""
import json

from tinyworld.agent.parser import parse_reply
from tinyworld.agent.prompt import action_lines
from tinyworld.sim.defs import ID
from tinyworld.sim.engine import Engine

from conftest import flat_world, make_world


def long_world(**kw):
    w = flat_world(**kw)
    w.cfg.long_actions = True
    return w


def test_off_by_default_goto_is_unknown_and_repeat_ignored():
    w = flat_world()
    assert "goto" not in action_lines(w) and "repeat" not in action_lines(w)
    r = w.step({"name": "goto", "x": 40, "y": 10, "z": 32})
    assert not r.valid and r.text.startswith("Unknown action.")
    t0 = w.t
    w.step({"name": "wait", "steps": 1, "repeat": 5})
    assert w.t == t0 + 1


def test_prompt_lists_goto_and_repeat_when_on():
    w = long_world()
    lines = action_lines(w)
    assert 'goto: {"name": "goto", "x": X, "y": Y, "z": Z} or {"name": "goto", "id": ID}' in lines
    assert "at most 30 steps" in lines and '"repeat": 2 to 8' in lines
    p = parse_reply('<invoke name="goto"><parameter name="id">7</parameter><parameter name="repeat">2</parameter></invoke>')
    assert p.ok and p.action == {"name": "goto", "id": 7, "repeat": 2}


def test_goto_walks_to_beside_a_cell():
    w = long_world()
    r = w.step({"name": "goto", "x": 40, "y": 10, "z": 36})
    assert r.valid and r.text.startswith("Walked 10 cells. You are beside it")
    assert max(abs(w.pos[0] - 40), abs(w.pos[2] - 36)) == 1 and r.steps == 10
    r = w.step({"name": "goto", "x": 40, "y": 10, "z": 36})
    assert r.text == "You are already beside it." and r.steps == 1


def test_goto_goes_round_a_wall_and_up_a_step():
    w = long_world()
    for z in range(28, 37):                              # a wall 3 high across the straight line, with ends to walk round
        for y in (10, 11, 12):
            w.blocks[y, z, 35] = ID["stone"]
    w.blocks[10, 32, 40] = ID["stone"]                   # the target: a block to stand next to
    r = w.step({"name": "goto", "x": 40, "y": 10, "z": 32})
    assert r.valid and "You are beside it" in r.text and w.pos[0] in (39, 40, 41) and r.steps > 8
    w2 = long_world()
    w2.blocks[10, :, 34:] = ID["grass"]                  # ground one higher from x = 34 on
    r = w2.step({"name": "goto", "x": 38, "y": 11, "z": 32})
    assert "You are beside it" in r.text and w2.pos[1] == 11


def test_goto_reports_no_way_and_gets_as_near_as_it_can():
    w = long_world()
    w.blocks[10:14, :, 36] = ID["stone"]                 # a wall across the whole map
    r = w.step({"name": "goto", "x": 45, "y": 10, "z": 32})
    assert r.valid and "There is no way further on foot." in r.text and w.pos[0] == 35
    r = w.step({"name": "goto", "x": 45, "y": 10, "z": 32})
    assert r.text.startswith("Walked 0 cells") and r.steps == 1
    assert not w.step({"name": "goto", "x": "a"}).valid
    assert w.step({"name": "goto", "id": 99}).text == "No creature #99 within reach."


def test_goto_stops_at_the_step_limit():
    w = long_world()
    w.cfg.goto_max_steps = 5
    r = w.step({"name": "goto", "x": 50, "y": 10, "z": 32})
    assert "Stopped after 5 steps, not there yet." in r.text and w.pos[0] == 37


def test_goto_a_creature_then_repeat_attack():
    w = long_world()
    w.cfg.creatures.passive_move_prob = 0.0
    w.creatures = [{"id": 5, "kind": "sheep", "pos": [40, 10, 32], "hp": 6, "cd": 0}]
    r = w.step({"name": "goto", "id": 5})
    assert "You are beside it" in r.text and abs(w.pos[0] - 40) <= 1
    r = w.step({"name": "attack", "id": 5, "repeat": 5})
    assert "It is gone." in r.text and "Done 3 of 5 times." in r.text and r.valid      # 6 hp, 2 per hit by hand
    assert w.inv.get("raw meat") == 2 and not w.creatures
    r = w.step({"name": "attack", "id": 5, "repeat": 3})
    assert not r.valid and "Done 0 of 3 times." in r.text


def test_repeat_stops_when_a_try_fails():
    w = long_world()
    w.inv["bread"] = 2
    w.food = 1
    r = w.step({"name": "eat", "item": w.dn("bread"), "repeat": 4})
    assert "Done 2 of 4 times." in r.text and w.inv.get("bread", 0) == 0 and r.valid


def test_goto_in_the_engine_runs_over_ticks():
    w = make_world(seed=3)
    w.cfg.long_actions = True
    eng = Engine(w)
    a = eng.add_agent("A")
    b = w.body(a)
    start = list(b.pos)
    tgt = (start[0] + 6, start[1], start[2])
    eng.submit(a, {"name": "goto", "x": tgt[0], "y": tgt[1], "z": tgt[2]})
    out = []
    for _ in range(40):
        res, _, _ = eng.tick()
        out += res
        if out:
            break
    assert out and out[0].valid and out[0].t_end > out[0].t_start and out[0].desc.startswith("goto (")
    assert b.pos != start


def test_goto_keeps_walking_past_a_far_creature_and_stops_for_a_close_one():
    w = long_world()
    w.cfg.creatures.passive_move_prob = 0.0
    w.creatures = [{"id": 7, "kind": "sheep", "pos": [38, 10, 40], "hp": 6, "cd": 0}]      # in view on the way, 8 cells off the line
    r = w.step({"name": "goto", "x": 46, "y": 10, "z": 32})
    assert "You are beside it" in r.text and w.pos[0] == 45
    w = long_world()
    w.cfg.creatures.passive_move_prob = 0.0
    w.creatures = [{"id": 8, "kind": "sheep", "pos": [40, 10, 34], "hp": 6, "cd": 0}]      # 2 cells off the line
    r = w.step({"name": "goto", "x": 46, "y": 10, "z": 32})
    assert "Stopped: a creature came close." in r.text and w.pos[0] < 45
    assert "comes within 3 cells" in action_lines(w)
