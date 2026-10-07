"""Metrics and grid replay on the two sample runs in samples/ (real 1500 step bot runs)."""
import json
import shutil
from pathlib import Path

import pytest

from tinyworld.analysis import metrics as M
from tinyworld.analysis.replay import Grid, RunFiles, final_grid, replay_grid

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
SENSIBLE, RANDOM = SAMPLES / "sensible_seed1", SAMPLES / "random_seed1"


@pytest.fixture(scope="module")
def sensible():
    return M.compute_metrics(SENSIBLE)


@pytest.fixture(scope="module")
def random_run():
    return M.compute_metrics(RANDOM)


def test_sensible_bot_sample(sensible):
    s = sensible
    assert s["run_id"] == "sensible_seed1" and s["controller"] == "sensible_bot" and s["seed"] == 1
    assert s["model"] is None and s["memory_chars"] == 0 and s["names"] == "familiar"
    assert s["world_steps"] == 1500 and s["agent_steps"] == 466 and s["finished"] is True
    assert s["deaths"] == 0 and s["death_causes"] == [] and s["first_death_t"] is None
    assert s["life_steps"] == [1500] and s["life_steps_mean"] == 1500
    assert s["recipes_found"] == 13 and s["items_crafted_distinct"] == 13
    assert s["deepest_tool_tier"] == 3 and s["craft_fails"] == 0
    assert s["blocks_mined_distinct"] >= 7
    assert s["nights"] == 5 and s["night_steps"] == 500
    assert s["night_enclosed_share"] > 0.9          # it walls itself in every night
    assert s["blocks_placed"] > 10 and s["largest_placed_group_26"] >= 4
    assert s["cells_visited"] > 50
    assert s["unreadable_replies"] == 0 and s["invalid_actions"] == 0
    assert s["tokens_total"] == 0 and s["cost_usd_total"] == 0


def test_random_bot_sample(random_run):
    s = random_run
    assert s["controller"] == "random_bot"
    assert s["deaths"] >= 1
    assert len(s["death_causes"]) == s["deaths"] == sum(s[f"deaths_{c}"] for c in M.DEATH_CAUSES)
    assert len(s["life_steps"]) == s["deaths"] + 1 and sum(s["life_steps"]) == 1500
    assert s["first_death_t"] == s["life_steps"][0]
    assert s["recipes_found"] < 13
    assert s["night_open_share"] > 0.5             # it does not shelter
    assert 0 < s["action_entropy_50"] <= 3


@pytest.mark.parametrize("folder", [SENSIBLE, RANDOM])
def test_shares_and_flat_keys(folder):
    s = M.compute_metrics(folder)
    assert abs(sum(s[f"share_{a}"] for a in M.ACTIONS) + s["share_unknown"] - 1) < 1e-6
    assert abs(sum(s[f"agent_share_{a}"] for a in M.ACTIONS) - 1) < 1e-6
    assert abs(s["night_enclosed_share"] + s["night_torch_share"] + s["night_open_share"] - 1) < 1e-6
    for k, v in s.items():
        assert not isinstance(v, dict), k
        if isinstance(v, list):
            assert all(not isinstance(x, (dict, list)) for x in v), k
    json.dumps(s)


def test_replay_applies_every_step():
    run = RunFiles(SENSIBLE)
    n = 0
    grid = None
    for line, grid, changes in replay_grid(run):
        n += 1
        assert line["t"] == n
        assert len(changes) == len(line["blocks"])
    assert n == 1500
    assert grid is not None and grid.get(0, 0, 0) in grid.palette
    assert final_grid(run).blocks.tobytes() == grid.blocks.tobytes()
    assert not grid.in_bounds(64, 0, 0) and grid.get(64, 0, 0) == "air"
    assert Grid(run.snapshot).as_array().shape == (32, 64, 64)


def test_largest_group():
    cells = {(0, 0, 0), (1, 0, 0), (2, 0, 0), (5, 5, 5), (5, 6, 5), (1, 1, 1)}
    assert M.largest_group(cells) == 3
    assert M.largest_group(cells, M.NEIGHBOURS_26) == 4      # (1,1,1) touches the row by a corner
    assert M.largest_group(set()) == 0


def test_line_survival():
    versions = [(0, ""), (3, "a\nb"), (5, "a\nb\nc"), (9, "a\nc"), (12, "a\nd")]
    out = M.line_survival(versions, last_i=20)
    assert out["memory_lines_created"] == 4
    assert out["memory_lines_alive_end"] == 2                      # a and d
    assert out["memory_line_survival_mean"] == pytest.approx((6 + 7) / 2)   # b: 3->9, c: 5->12
    assert out["memory_line_survival_mean_censored"] == pytest.approx((6 + 7 + 17 + 8) / 4)


def test_memory_metrics_from_memory_file(tmp_path):
    d = tmp_path / "m"
    shutil.copytree(SENSIBLE, d)
    mem = [{"i": 0, "t": 0, "ops": [], "accepted": True, "over_by": 0, "text": "", "chars": 0, "limit": 100},
           {"i": 2, "t": 3, "ops": [{"op": "append", "text": "lake at 29,12,25"}], "accepted": True, "over_by": 0,
            "text": "lake at 29,12,25", "chars": 16, "limit": 100},
           {"i": 4, "t": 6, "ops": [{"op": "rewrite", "text": "x" * 200}], "accepted": False, "over_by": 100,
            "text": "lake at 29,12,25", "chars": 16, "limit": 100},
           {"i": 6, "t": 9, "ops": [{"op": "replace", "old": "lake", "new": "water"}], "accepted": True, "over_by": 0,
            "text": "water at 29,12,25", "chars": 17, "limit": 100}]
    (d / "memory.jsonl").write_text("".join(json.dumps(m) + "\n" for m in mem))
    s = M.compute_metrics(d)
    assert s["memory_edits"] == 2 and s["memory_edits_append"] == 1 and s["memory_edits_replace"] == 1
    assert s["memory_edits_rewrite"] == 0 and s["memory_rejected"] == 1
    assert s["memory_lines_created"] == 2 and s["memory_lines_alive_end"] == 1
    assert s["memory_line_survival_mean"] == 4                     # "lake..." born at 2, gone at 6
    assert s["memory_chars_changed_per_edit"] > 0


def test_cli_writes_summary(tmp_path):
    d = tmp_path / "r"
    shutil.copytree(RANDOM, d)
    M.main([str(d)])
    s = json.loads((d / "summary.json").read_text())
    assert s["deaths"] >= 1 and s["run_id"] == "random_seed1"
    assert M.write_summary(d, wall_clock_s=12.5)["wall_clock_s"] == 12.5
