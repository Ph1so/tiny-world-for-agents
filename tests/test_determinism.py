"""Same seed and same actions give the same world, in one process and across processes."""
import json
import subprocess
import sys

from conftest import make_world

from tinyworld.bots.random_bot import RandomBot

SCRIPT = """
import json, sys
from tinyworld.sim import World, load_world_config
w = World(load_world_config(), seed=7)
hashes = [w.state_hash()]
for a in json.loads(sys.stdin.read()):
    w.step(a)
hashes.append(w.state_hash())
hashes.append(w.observe())
print(json.dumps(hashes))
"""


def actions(seed: int, n: int) -> list[dict]:
    w, bot, out = make_world(seed), RandomBot(seed), []
    for _ in range(n):
        a = bot.act("", w)
        out.append(a)
        w.step(a)
    return out


def test_same_seed_same_actions_same_hash():
    acts = actions(7, 400)
    runs = []
    for _ in range(2):
        w = make_world(7)
        for a in acts:
            w.step(a)
        runs.append((w.state_hash(), w.observe(), w.t))
    assert runs[0] == runs[1] and runs[0][2] > 400


def test_different_seeds_differ():
    assert make_world(1).state_hash() != make_world(2).state_hash()


def test_hash_changes_with_state():
    w = make_world(1)
    h = w.state_hash()
    w.step({"name": "wait", "steps": 1})
    assert w.state_hash() != h


def test_two_fresh_processes_agree():
    acts = json.dumps(actions(7, 300))
    outs = [subprocess.run([sys.executable, "-c", SCRIPT], input=acts, capture_output=True, text=True, check=True).stdout
            for _ in range(2)]
    assert outs[0] == outs[1]
    a = json.loads(outs[0])
    assert a[0] == make_world(7).state_hash() and a[0] != a[1]


def test_sim_imports_no_other_tinyworld_package():
    code = ("import sys, tinyworld.sim, tinyworld.sim.cli; "
            "print([m for m in sys.modules if m.startswith('tinyworld.') and not m.startswith('tinyworld.sim')])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"
