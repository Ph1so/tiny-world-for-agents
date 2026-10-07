"""Sweep runner: grid expansion, naming, cost estimate, end to end smoke sweep, resume, budget stop."""
import json
import shutil
from pathlib import Path

import pytest
import yaml

from tinyworld.analysis.replay import read_jsonl
from tinyworld.runner import sweep as S

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "configs" / "sweeps" / "smoke.yaml"


def test_expand_names_and_order():
    cfg = S.SweepConfig.from_dict({"name": "x", "seeds": [1, 2], "max_steps": 100, "models": ["a", "org/b:1"],
                                   "memory_chars": [0, 500], "history_window": [3]})
    assert cfg.controllers == ["llm"] and cfg.budget_usd == 0 and cfg.parallel_runs == 1
    specs = S.expand(cfg)
    assert len(specs) == 2 * 2 * 2
    assert specs[0].name == "a_m0_k3_s1" and specs[0].run_id == "x/a_m0_k3_s1"
    assert specs[1].name == "a_m0_k3_s2" and specs[2].name == "a_m500_k3_s1"
    assert specs[-1].name == "org-b-1_m500_k3_s2"
    assert len({s.name for s in specs}) == len(specs)
    argv = specs[0].argv(Path("runs"))
    assert "--controller" in argv and argv[argv.index("--controller") + 1] == "llm"
    assert argv[argv.index("--model") + 1] == "a" and argv[argv.index("--memory-chars") + 1] == "0"
    assert argv[argv.index("--history-window") + 1] == "3" and "--resume" in argv

    bots = S.SweepConfig.load(SMOKE)
    bspecs = S.expand(bots)
    assert [s.name for s in bspecs] == ["random_bot_m0_k0_s1", "random_bot_m0_k0_s2",
                                        "sensible_bot_m0_k0_s1", "sensible_bot_m0_k0_s2"]
    assert "--model" not in bspecs[0].argv(Path("runs"))

    mixed = S.SweepConfig.from_dict({"controller": ["sensible_bot", "llm"], "models": ["a"], "memory_chars": [0, 100]})
    assert [s.name for s in S.expand(mixed)] == ["sensible_bot_m0_k0_s1", "a_m0_k3_s1", "a_m100_k3_s1"]


def test_memory_sweep_config_matches_plan():
    cfg = S.SweepConfig.load(ROOT / "configs" / "sweeps" / "memory_sweep.yaml")
    assert cfg.seeds == [1, 2, 3] and cfg.memory_chars == [0, 500, 2000, 8000, 32000]
    assert cfg.budget_usd == 25 and cfg.parallel_runs == 4 and len(S.expand(cfg)) == 30


def test_prices_and_estimate(tmp_path):
    y = tmp_path / "models.yaml"
    y.write_text(yaml.safe_dump({"models": {
        "a": {"id": "vendor/a-1", "input_per_mtok": 3.0, "output_per_mtok": 15.0},
        "b": {"price": {"input": 1.0, "output": 2.0}, "cache_input": 0.1},
    }}))
    prices = S.load_prices(y)
    assert prices["a"] == (3.0, 15.0) and prices["vendor/a-1"] == (3.0, 15.0) and prices["b"] == (1.0, 2.0)
    assert S.load_prices(tmp_path / "missing.yaml") == {}
    y.write_text(yaml.safe_dump([{"name": "c", "input_usd_per_million": 2, "output_usd_per_million": 4}]))
    assert S.load_prices(y)["c"] == (2.0, 4.0)

    spec = S.RunSpec("n", "x/n", "llm", "a", 2000, 3, 1, 1500, "familiar", "respawn_keep_memory", False)
    calls, usd = S.estimate(spec, {"a": (3.0, 15.0)})
    assert calls == 750
    assert usd == pytest.approx(750 * ((900 + 500) * 3.0 + 150 * 15.0) / 1e6)
    assert S.estimate(spec, {}) == (750, 0.0)
    bot = S.RunSpec("n", "x/n", "sensible_bot", None, 0, 0, 1, 1500, "familiar", "respawn_keep_memory", False)
    assert S.estimate(bot, {"a": (3.0, 15.0)}) == (0, 0.0)


def test_spend_meter(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    p = d / "steps.jsonl"
    p.write_text('{"i":1,"cost_usd":0.5}\n{"i":2,"cost_usd":0.25}\n{"i":3,"cost_')
    m = S.SpendMeter()
    assert m.update([d]) == 0.75
    with open(p, "a") as f:
        f.write('usd":1.0}\n')
    assert m.update([d]) == 1.75 and m.of(d) == 1.75
    assert m.update([d]) == 1.75


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    runs = tmp_path_factory.mktemp("runs")
    rc = S.main([str(SMOKE), "--yes", "--runs-dir", str(runs)])
    assert rc == 0
    return runs / "smoke"


def test_smoke_sweep_end_to_end(smoke):
    names = ["random_bot_m0_k0_s1", "random_bot_m0_k0_s2", "sensible_bot_m0_k0_s1", "sensible_bot_m0_k0_s2"]
    for n in names:
        s = json.loads((smoke / n / "summary.json").read_text())
        assert s["world_steps"] >= 200 and s["finished"] and s["run_id"] == f"smoke/{n}"
        assert s["wall_clock_s"] > 0
    status = json.loads((smoke / "sweep_status.json").read_text())
    assert status["stopped"] is None and status["spent_usd"] == 0
    assert {n: r["status"] for n, r in status["runs"].items()} == {n: "done" for n in names}
    assert yaml.safe_load((smoke / "sweep.yaml").read_text())["seeds"] == [1, 2]
    html = (smoke / "report.html").read_text()
    assert html.count('class="plotly-graph-div"') > 10
    assert "localhost:8000/?run=smoke%2Frandom_bot_m0_k0_s1" in html
    assert "Activity share over time" in html and "Survival" in html


def test_dry_run_and_nothing_to_do(smoke, capsys):
    assert S.main([str(SMOKE), "--dry-run", "--runs-dir", str(smoke.parent)]) == 0
    out = capsys.readouterr().out
    assert "4 done" in out and "runs: 4" in out
    assert S.main([str(SMOKE), "--yes", "--runs-dir", str(smoke.parent), "--no-report"]) == 0
    assert "nothing to run" in capsys.readouterr().out


def test_stopped_sweep_resumes_without_redoing_finished_runs(smoke, tmp_path):
    runs = tmp_path / "runs"
    shutil.copytree(smoke.parent, runs)
    sweep = runs / "smoke"
    before = {n: (sweep / n / "steps.jsonl").read_text() for n in
              ["random_bot_m0_k0_s1", "random_bot_m0_k0_s2", "sensible_bot_m0_k0_s1", "sensible_bot_m0_k0_s2"]}
    # One finished run lost its summary, one run was cut off after 20 agent steps.
    (sweep / "random_bot_m0_k0_s2" / "summary.json").unlink()
    partial = sweep / "sensible_bot_m0_k0_s1"
    lines = (partial / "steps.jsonl").read_text().splitlines(keepends=True)
    (partial / "steps.jsonl").write_text("".join(lines[:20]) + '{"i": 21, "t_start')
    (partial / "summary.json").unlink()
    (partial / "report_marker").write_text("")
    (sweep / "report.html").unlink()

    rc = S.main([str(SMOKE), "--yes", "--runs-dir", str(runs)])
    assert rc == 0
    status = json.loads((sweep / "sweep_status.json").read_text())
    launched = {n for n, r in status["runs"].items() if "pid" in r}
    assert launched == {"random_bot_m0_k0_s2", "sensible_bot_m0_k0_s1"}
    assert all(r["status"] == "done" for r in status["runs"].values())
    for n, text in before.items():
        assert (sweep / n / "steps.jsonl").read_text() == text, n       # resumed run matches the unbroken one
        assert (sweep / n / "summary.json").exists()
    assert len(read_jsonl(partial / "steps.jsonl")) > 20
    assert (sweep / "report.html").exists()


def test_budget_stops_before_launching(tmp_path, capsys):
    runs = tmp_path / "runs"
    cfg = S.SweepConfig.from_dict({"name": "b", "controller": ["random_bot"], "seeds": [1], "max_steps": 50,
                                   "budget_usd": 1.0})
    # A run that was cut off earlier after spending more than the budget.
    d = runs / "b" / "random_bot_m0_k0_s1"
    d.mkdir(parents=True)
    (d / "steps.jsonl").write_text('{"i":1,"t_start":0,"t_end":1,"cost_usd":0.7}\n{"i":2,"t_start":1,"t_end":2,"cost_usd":0.6}\n')
    status = S.Sweep(cfg, runs).execute()
    assert status["stopped"].startswith("budget reached")
    assert status["spent_usd"] == pytest.approx(1.3)
    assert status["runs"]["random_bot_m0_k0_s1"]["status"] == "partial"
    assert not (d / "summary.json").exists()
