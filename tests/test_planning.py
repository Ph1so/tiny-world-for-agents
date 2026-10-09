"""planning "action" and "triggers": the plan slot, the plan action, and conditions the agent sets."""
import json

import pytest
import yaml

from tinyworld.agent.controller import LLMController
from tinyworld.agent.plan import PLAN_NONE, Plan, parse_condition
from tinyworld.agent.prompt import PLAN_ACTION_LINE, build_system_prompt
from tinyworld.llm import ModelSpec
from tinyworld.llm.mock import MockClient
from tinyworld.runner.multi import run_multi
from tinyworld.runner.run import run

from conftest import flat_world

SPEC = ModelSpec(name="mock", provider="mock", model="mock", input_per_m=1.0, output_per_m=1.0)
WAIT = json.dumps({"thought": "", "memory": [], "action": {"name": "wait", "steps": 1}})
CHOOSE = json.dumps({"thought": "I want a plan", "memory": [], "action": {"name": "plan"}})


def plan_reply(goal="a bed", steps=("get wool", "craft"), when=None):
    d = {"thought": "planning", "goal": goal, "steps": list(steps)}
    if when is not None:
        d["replan_when"] = when
    return json.dumps(d)


def controller(script, planning="action", **kw):
    return LLMController(MockClient(script), SPEC, memory_chars=500, planning=planning, **kw)


def step(c, w):
    out = c.act(w.observe(), w)
    res = w.step(out["action"])
    c.on_result(res, w)
    return out, res


def test_off_leaves_prompt_and_message_alone():
    w = flat_world()
    off = build_system_prompt(w, 3, 500, memory_plain="append")
    assert "plan" not in off.split("Actions:")[0] and PLAN_ACTION_LINE not in off
    c = controller([WAIT], planning="off")
    assert "plan" not in c.user_message(w.observe(), w.t).split("observation:")[0]
    out, _ = step(c, w)
    assert "plan" not in out and len(c.client.calls) == 1


def test_prompt_names_the_mechanism_only():
    w = flat_world()
    a = build_system_prompt(w, 3, 500, memory_plain="append", planning="action", plan_chars=600)
    t = build_system_prompt(w, 3, 500, memory_plain="append", planning="triggers", plan_chars=600)
    assert PLAN_ACTION_LINE in a and "at most 600 characters" in a and "conditions" not in a
    assert "health, food, air, step, steps_since_plan, deaths" in t and '"steps_since_plan >= 50"' in t
    # the action list keeps its order, with the plan line last
    lines = a.split("Actions:\n")[1].split("\n\n")[0].split("\n")
    assert lines[-1] == PLAN_ACTION_LINE and lines[0].startswith("move:")


def test_plan_action_makes_a_second_call_and_sets_the_plan():
    w = flat_world()
    c = controller([CHOOSE, plan_reply(), WAIT])
    assert PLAN_NONE in c.user_message(w.observe(), w.t)
    out, res = step(c, w)
    assert len(c.client.calls) == 2 and "Write your plan now." in c.client.calls[1][1]
    assert out["action"] == {"name": "wait", "steps": 1} and res.valid
    p = out["plan"]
    assert p["cause"] == "action" and p["accepted"] and p["goal"] == "a bed" and p["steps"] == ["get wool", "craft"]
    assert p["set_t"] == 0 and p["before"] is None and p["replan_when"] == []
    assert out["events"][-1]["type"] == "plan" and out["thought"] == "I want a plan"
    assert out["input_tokens"] == sum(max(1, (len(s) + len(u)) // 4) for s, u, _ in c.client.calls)
    msg = c.user_message(w.observe(), w.t)
    assert "plan (written at step 0, 1 steps ago):\ngoal: a bed\n1. get wool\n2. craft\n" in msg
    assert c.history[-1][0] == '{"name": "plan"}' and c.history[-1][1].startswith("Plan written.")
    step(c, w)                                       # an ordinary step leaves the plan alone
    assert c.plan.goal == "a bed" and len(c.client.calls) == 3 and c.plans_written == 1


def test_plan_wait_sets_how_long_a_planning_turn_takes():
    w = flat_world()
    c = controller([CHOOSE, plan_reply()], plan_wait=4)
    out, _ = step(c, w)
    assert out["action"] == {"name": "wait", "steps": 4} and w.t == 4


def test_bad_plans_leave_the_old_one():
    w = flat_world()
    c = controller([CHOOSE, plan_reply(), CHOOSE, plan_reply(goal="x" * 700), CHOOSE, "no json here",
                    CHOOSE, json.dumps({"steps": ["a"]}), WAIT], plan_chars=600)
    step(c, w)
    out, _ = step(c, w)
    assert not out["plan"]["accepted"] and out["plan"]["error"] == "over limit" and out["plan"]["over_by"] > 0
    assert "Plan rejected." in w.observe()
    out, _ = step(c, w)
    assert not out["plan"]["accepted"] and out["plan"]["error"] == "unreadable"
    out, _ = step(c, w)
    assert out["plan"]["error"] == "no goal"
    assert c.plan.goal == "a bed" and c.plans_written == 1
    assert c.history[-1] == ('{"name": "plan"}', c.history[-1][1]) and c.history[-1][1].startswith("No plan was written.")


def test_conditions_parse():
    assert parse_condition("food < 8").text == "food < 8"
    assert parse_condition("Raw  Meat>=2").text == "raw meat >= 2"
    assert parse_condition("steps since plan = 50").text == "steps_since_plan == 50"
    assert parse_condition({"name": "health", "op": "<=", "value": 5}).text == "health <= 5"
    assert parse_condition("when hungry") is None and parse_condition(7) is None


def test_action_mode_ignores_conditions():
    w = flat_world()
    c = controller([CHOOSE, plan_reply(when=["step >= 2"]), WAIT])
    out, _ = step(c, w)
    assert out["plan"]["replan_when"] == []
    for _ in range(4):
        step(c, w)
    assert c.plans_written == 1


def test_a_condition_fires_once_when_it_turns_true():
    w = flat_world()
    c = controller([CHOOSE, plan_reply(when=["steps_since_plan >= 3", "nonsense", "bread < 1"]),
                    WAIT, WAIT, plan_reply(goal="second", when=["steps_since_plan >= 100"]), WAIT, WAIT],
                   planning="triggers")
    out, _ = step(c, w)                               # t 0 -> 1
    assert out["plan"]["replan_when"] == ["steps_since_plan >= 3", "bread < 1"]
    assert "Not understood, left out: nonsense" in w.observe()
    assert "replan when: steps_since_plan >= 3; bread < 1" in c.user_message(w.observe(), w.t)
    step(c, w)
    step(c, w)                                        # t 3: steps_since_plan is 3 at the next look
    n = len(c.client.calls)
    out, _ = step(c, w)
    assert len(c.client.calls) == n + 1               # the planner call alone, no action call
    assert "A condition you set is true now: steps_since_plan >= 3." in c.client.calls[-1][1]
    p = out["plan"]
    assert p["cause"] == "condition" and p["fired"] == "steps_since_plan >= 3" and p["goal"] == "second"
    assert p["before"]["goal"] == "a bed" and out["action"]["name"] == "wait"
    step(c, w)
    step(c, w)
    assert c.plans_written == 2                       # "bread < 1" was true from the start: never armed


def test_item_and_vital_conditions_use_shown_names():
    w = flat_world()
    w.inv["bread"] = 2
    plan = Plan(600, triggers=True)
    from tinyworld.agent.plan import values
    assert plan.write({"goal": "g", "replan_when": ["bread < 1", "food < 19", "health < 5"]}, w.t, values(w, plan, 0)).accepted
    assert plan.fired(values(w, plan, 0)) is None
    w.inv["bread"] = 0
    assert plan.fired(values(w, plan, 0)).text == "bread < 1"
    w.inv["bread"] = 2
    w.food = 18
    assert plan.fired(values(w, plan, 0)).text == "food < 19"


def test_single_run_logs_and_resumes_the_plan(tmp_path):
    def script(system, user):
        if "Write your plan now." in user:
            return plan_reply(goal=f"goal {user.count('goal: ')}", when=["steps_since_plan >= 6"])
        return CHOOSE if "plan: none" in user else WAIT
    extra = {"model": "mock", "memory_chars": 500, "history_window": 3, "planning": "triggers"}
    mk = lambda: LLMController(MockClient(script), SPEC, memory_chars=500, planning="triggers")
    run("p", "llm", seed=1, max_steps=10, runs_dir=tmp_path, controller=mk(), extra_config=extra)
    d = tmp_path / "p"
    cfg = yaml.safe_load((d / "config.yaml").read_text())
    assert cfg["planning"] == "triggers" and cfg["plan_chars"] == 1000
    steps = [json.loads(l) for l in (d / "steps.jsonl").read_text().splitlines()]
    plans = [s for s in steps if "plan" in s]
    assert [p["plan"]["cause"] for p in plans] == ["action", "condition"]
    assert plans[1]["plan"]["fired"] == "steps_since_plan >= 6" and plans[1]["t_start"] == 6
    assert [e["type"] for e in map(json.loads, (d / "events.jsonl").read_text().splitlines())].count("plan") == 2
    assert "plan: " in json.loads((d / "prompts.json").read_text())["system"]["0"]
    c2 = mk()
    run("p", "llm", seed=1, max_steps=14, runs_dir=tmp_path, controller=c2, resume=True)
    steps = [json.loads(l) for l in (d / "steps.jsonl").read_text().splitlines()]
    plans = [s for s in steps if "plan" in s]
    assert [p["t_start"] for p in plans] == [0, 6, 12] and c2.plans_written == 3
    assert c2.plan.set_t == 12 and c2.plan.goal == plans[2]["plan"]["goal"]
    assert [h[0] for h in c2.history].count('{"name": "plan"}') == 3


@pytest.mark.parametrize("planning", ["action", "triggers"])
def test_multi_run_with_planning_and_resume(tmp_path, planning):
    agents = [{"name": "Ada", "controller": "llm", "model": "mock", "memory_chars": 500, "planning": planning},
              {"name": "Bo", "controller": "llm", "model": "mock", "memory_chars": 500}]
    from tinyworld.llm.mock import SensibleMockClient
    run_multi("m", agents, seed=2, max_steps=120, runs_dir=tmp_path, clock="lockstep",
              clients={0: SensibleMockClient(seed=2, plan_every=15)})
    d = tmp_path / "m"
    cfg = yaml.safe_load((d / "config.yaml").read_text())
    ada, bo = cfg["agents"][0]["id"], cfg["agents"][1]["id"]
    assert cfg["agents"][0]["planning"] == planning and "planning" not in cfg["agents"][1]
    steps = [json.loads(l) for l in (d / "steps.jsonl").read_text().splitlines()]
    plans = [s for s in steps if "plan" in s]
    assert plans and {s["agent"] for s in plans} == {ada} and all(s["action"]["name"] == "wait" for s in plans)
    causes = {s["plan"]["cause"] for s in plans}
    assert causes == ({"action", "condition"} if planning == "triggers" else {"action"})
    prompts = json.loads((d / "prompts.json").read_text())["system"]
    assert PLAN_ACTION_LINE in prompts[str(ada)] and PLAN_ACTION_LINE not in prompts[str(bo)]
    s = json.loads((d / "summary.json").read_text())
    assert s["agents"][0]["plans_written"] == len([p for p in plans if p["plan"]["accepted"]])
    assert "plans_written" not in s["agents"][1]
    w = run_multi("m", max_steps=200, runs_dir=tmp_path, resume=True, clients={0: SensibleMockClient(seed=2, plan_every=15)})
    steps = [json.loads(l) for l in (d / "steps.jsonl").read_text().splitlines()]
    assert w.t >= 200 and len([s for s in steps if "plan" in s]) > len(plans)
