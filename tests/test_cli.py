import subprocess
import sys

from tinyworld.sim.cli import parse_action


def test_short_forms():
    assert parse_action("move north 3") == {"name": "move", "dir": "north", "steps": 3}
    assert parse_action("mine 31 13 23") == {"name": "mine", "x": 31, "y": 13, "z": 23}
    assert parse_action("place berry bush 1 2 3") == {"name": "place", "item": "berry bush", "x": 1, "y": 2, "z": 3}
    assert parse_action("craft planks 3 sticks 2") == {"name": "craft", "items": {"planks": 3, "sticks": 2}}
    assert parse_action("craft raw meat 1 coal 1") == {"name": "craft", "items": {"raw meat": 1, "coal": 1}}
    assert parse_action("eat cooked meat") == {"name": "eat", "item": "cooked meat"}
    assert parse_action("attack #7") == {"name": "attack", "id": 7}
    assert parse_action("wait 4") == {"name": "wait", "steps": 4}
    assert parse_action('{"name": "wait", "steps": 2}') == {"name": "wait", "steps": 2}
    assert parse_action("dance") == {"name": "dance"}


def test_cli_session():
    out = subprocess.run([sys.executable, "-m", "tinyworld.sim.cli", "--seed", "1"],
                         input="wait 2\nmove up\nhash\nquit\n", capture_output=True, text=True, check=True).stdout
    assert "step 0 | day 1" in out and "last action: wait 2. Result: Waited 2 steps." in out
    assert "last action: move up 1. Result: You did not move." in out
