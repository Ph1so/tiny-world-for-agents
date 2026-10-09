"""The multi-agent engine: one agent through it matches World.step(); the rules between agents."""
import numpy as np

from tinyworld.bots.sensible_bot import SensibleBot
from tinyworld.sim import text as T
from tinyworld.sim.engine import Engine

from conftest import flat_world, make_world


def run_lockstep(eng: Engine, agent: int, action: dict, limit: int = 400):
    """Submit, tick until it finishes, return the Result."""
    eng.submit(agent, action)
    for _ in range(limit):
        results, _, _ = eng.tick()
        for r in results:
            if r.agent == agent:
                return r
    raise AssertionError("action did not finish")


def test_one_agent_through_the_engine_matches_world_step():
    a, b = make_world(2), make_world(2)
    eng = Engine(b)
    me = eng.add_agent("solo")
    bot_a, bot_b = SensibleBot(2), SensibleBot(2)
    while a.t < 700:
        ra = a.step(bot_a.act("", a))
        b.me = b.body(me)
        rb = run_lockstep(eng, me, bot_b.act("", b))
        assert (ra.text.split(" #")[0], ra.valid, a.t) == (rb.text.split(" #")[0], rb.valid, rb.t_end)
        assert (a.pos, a.inv, a.health, a.food, a.weather) == (b.pos, b.inv, b.health, b.food, b.weather)
        assert (a.blocks == b.blocks).all()
        assert [c["pos"] for c in a.creatures] == [c["pos"] for c in b.creatures]


def two(seed=1):
    w = flat_world(seed)
    w.cfg.weather.enabled = False
    eng = Engine(w)
    a, b = eng.add_agent("A"), eng.add_agent("B")
    w.body(a).pos, w.body(b).pos = [32, 10, 32], [34, 10, 32]
    return w, eng, a, b


def tick_until_idle(eng, *agents, limit=100):
    out = []
    for _ in range(limit):
        out += eng.tick()[0]
        if all(eng.idle(i) for i in agents):
            return out
    raise AssertionError("still busy")


def test_agents_block_each_other_and_swap_when_walking_into_each_other():
    w, eng, a, b = two()
    w.body(b).pos = [33, 10, 32]
    r = run_lockstep(eng, a, {"name": "move", "dir": "east", "steps": 1})
    assert r.text == f"You did not move. Blocked by agent #{b}." and w.body(a).pos == [32, 10, 32]
    eng.submit(a, {"name": "move", "dir": "east", "steps": 1})
    eng.submit(b, {"name": "move", "dir": "west", "steps": 1})
    res = {r.agent: r.text for r in tick_until_idle(eng, a, b)}
    assert res == {a: "Moved 1 cell east.", b: "Moved 1 cell west."}
    assert w.body(a).pos == [33, 10, 32] and w.body(b).pos == [32, 10, 32]


def test_mutual_attacks_land_together_and_armor_counts():
    w, eng, a, b = two()
    w.body(b).pos = [33, 10, 32]
    w.body(a).health = w.body(b).health = 2
    w.body(b).inv["iron helmet"] = 1
    w.body(b).tools["iron helmet"] = 30
    eng.submit(a, {"name": "attack", "id": b})
    eng.submit(b, {"name": "attack", "id": a})
    res = {r.agent: r for r in tick_until_idle(eng, a, b)}
    assert res[a].text.startswith(f"Hit agent #{b}.") and f"Agent #{b} at (33, 10, 32) hit you." in res[a].text
    assert res[a].died == "agent"                       # 2 damage, no armor: dead
    assert w.body(b).deaths == 0 and w.body(b).health == 1   # 2 - 1 for the helmet
    w2, eng2, a2, b2 = two()
    w2.body(b2).pos = [33, 10, 32]
    w2.body(b2).health = 1
    eng2.submit(a2, {"name": "attack", "id": b2})
    _, _, events = eng2.tick()
    assert {"t": 1, "type": "kill", "detail": {"kind": "agent", "id": b2, "agent": a2}} in events
    assert any(e["type"] == "death" and e["detail"]["agent"] == b2 and e["detail"]["cause"] == "agent" for e in events)


def test_say_reaches_agents_in_range_once():
    w, eng, a, b = two()
    c = eng.add_agent("C")
    w.body(c).pos = [60, 10, 60]
    r = run_lockstep(eng, a, {"name": "say", "text": "  hello   there "})
    assert r.text == f'Said "hello there". Heard by agent #{b}.'
    obs = eng.observe(b)
    assert f"you are agent #{b}" in obs
    assert f'  agent #{a} at (32,10,32) said: "hello there"' in obs
    assert "said" not in eng.observe(b) and "said" not in eng.observe(c)
    assert f"  agent #{a} at (32,10,32)" in obs                  # in the creatures list too


def test_give_moves_items_and_tool_wear():
    w, eng, a, b = two()
    w.body(b).pos = [33, 10, 32]
    A, B = w.body(a), w.body(b)
    A.inv.update({"planks": 5, "stone pickaxe": 1})
    A.tools["stone pickaxe"] = 17
    r = run_lockstep(eng, a, {"name": "give", "id": b, "items": {"planks": 2, "stone pickaxe": 1}})
    assert r.text == f"Gave planks x2, stone pickaxe x1 to agent #{b}."
    assert A.inv == {"planks": 3} and B.inv == {"planks": 2, "stone pickaxe": 1} and B.tools == {"stone pickaxe": 17}
    assert f"agent #{a} at (32,10,32) gave you planks x2, stone pickaxe x1" in eng.observe(b)
    w.body(b).pos = [40, 10, 32]
    r = run_lockstep(eng, a, {"name": "give", "id": b, "items": {"planks": 1}})
    assert r.text == f"No agent #{b} within 3 cells." and not r.valid


def test_zombies_chase_the_nearest_agent():
    w, eng, a, b = two()
    w.body(a).pos, w.body(b).pos = [20, 10, 32], [44, 10, 32]
    w.t = 210                                           # night: zombies stay out
    w._spawn("zombie", (40, 10, 32))
    w.cfg.creatures.zombie_step_every = 1
    for _ in range(3):
        eng.tick()
    assert w.creatures[0]["pos"][0] == 43


def test_end_run_takes_one_agent_out_and_the_rest_go_on():
    w, eng, a, b = two()
    w.cfg.on_death = "end_run"
    w.body(a).health = 1
    w.me = w.body(a)
    w._damage(1, "hunger")
    eng.tick()
    assert not w.body(a).alive and w.body(b).alive and not w.done and eng.alive() == [b]
    w.body(b).health = 1
    w.me = w.body(b)
    w._damage(1, "hunger")
    eng.tick()
    assert w.done


def test_a_new_action_cuts_the_running_one_short():
    w, eng, a, b = two()
    eng.submit(a, {"name": "wait", "steps": 8})
    eng.tick()
    eng.submit(a, {"name": "wait", "steps": 1})
    res = [r.text for r in eng.tick()[0] if r.agent == a]
    assert res == ["Cut short by your next action.", "Waited 1 step."]


def test_deltas_list_every_agent():
    w, eng, a, b = two()
    _, deltas, _ = eng.tick()
    ids = [x["id"] for x in deltas[0]["agents"]]
    assert ids == [a, b] and deltas[0]["agents"][1]["name"] == "B"
