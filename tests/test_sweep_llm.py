"""The M6 acceptance sweep: 2 models x 2 memory sizes x 2 seeds x 200 steps with the mock adapter."""
import json
from pathlib import Path

import pytest

from tinyworld.runner import sweep as S

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "configs" / "sweeps" / "mock.yaml"
pytestmark = pytest.mark.skipif(not (ROOT / "tinyworld" / "agent").is_dir(), reason="llm controller not built yet")


def test_mock_llm_sweep(tmp_path, capsys):
    cfg = S.SweepConfig.load(MOCK)
    specs = S.expand(cfg)
    assert len(specs) == 8 and specs[0].name == "mock_m0_k3_s1"
    assert "--model" in specs[0].argv(tmp_path)
    assert S.main([str(MOCK), "--yes", "--runs-dir", str(tmp_path)]) == 0
    sweep = tmp_path / "mock"
    status = json.loads((sweep / "sweep_status.json").read_text())
    assert all(r["status"] == "done" for r in status["runs"].values()) and len(status["runs"]) == 8
    s = json.loads((sweep / "mock_m500_k3_s1" / "summary.json").read_text())
    assert s["controller"] == "llm" and s["model"] == "mock" and s["memory_chars"] == 500 and s["history_window"] == 3
    assert s["world_steps"] >= 200 and s["tokens_total"] > 0 and s["memory_edits"] > 0
    assert s["memory_lines_created"] > 0 and s["memory_chars_max"] <= 500
    s0 = json.loads((sweep / "mock_m0_k3_s1" / "summary.json").read_text())
    assert s0["memory_edits"] == 0 and s0["memory_chars_max"] == 0
    html = (sweep / "report.html").read_text()
    assert "Memory size over time" in html and "?run=mock_m500_k3_s1" in html
