from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_shadow_evaluation_passes_all_contextual_interview_gates(tmp_path):
    output = tmp_path / "summary.json"
    result = subprocess.run(
        [
            sys.executable,
            "backend/scripts/eval_interview_graph.py",
            "--cases",
            "backend/tests/fixtures/interview_graph_cases.json",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["case_count"] == 5
    assert summary["gates"]["all_pass"] is True
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["gates"]["all_pass"] is True
