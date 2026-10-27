"""CLI-seam tests for ticket #13: scenario B controlled requests.

Ticket #40: the 30 requests (plus warmup) go to the candidate's own chat
endpoint; the candidate, not the harness, talks to its upstream. These tests
therefore use the fixture chat candidate and assert on ITS request count.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PROC_ROOT = FIXTURES / "proc"
SCENARIO = ROOT / "scenarios" / "mock_llm_controlled_requests.toml"

from chat_agent_utils import free_port, requests_seen, write_chat_descriptor

RECORD_FIELDS = [
    "run_id", "agent", "repo_url", "version", "mode", "scenario",
    "host_profile", "started_at_utc", "duration_sec", "ram_pss_mb_median",
    "ram_peak_mb", "cpu_sec", "startup_ms", "latency_p50_ms", "latency_p95_ms",
    "success_count", "error_count", "oom_count", "notes", "config_ref",
]


def _run_bench(workdir: Path, runs_dir: Path, mock_port: int = 0, delay_ms: int = 0) -> tuple[int, str, str]:
    desc = write_chat_descriptor(workdir, free_port(), delay_ms=delay_ms)
    cmd = [
        sys.executable, "-m", "bench", "run",
        str(desc), str(SCENARIO),
        "--proc-root", str(PROC_ROOT),
        "--runs-dir", str(runs_dir),
    ]
    if mock_port is not None:
        cmd += ["--mock-llm-port", str(mock_port)]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
    )
    stdout, stderr = proc.communicate(timeout=120)
    return proc.returncode, stdout, stderr


def test_scenario_b_produces_latency_metrics(tmp_path):
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs, mock_port=0)
    assert code == 0, f"exit {code}: {err}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    missing = [f for f in RECORD_FIELDS if f not in record]
    assert missing == []
    assert record["scenario"] == "scenario_b_mock_llm_controlled"
    assert record["latency_p50_ms"] is not None
    # 30 measured requests + 5 warmup were served by the candidate.
    assert record["success_count"] == 30
    assert len(requests_seen(tmp_path / "wd")) == 35


def test_scenario_b_with_mock_latency_deterministic(tmp_path):
    runs = tmp_path / "runs"
    # The candidate's own response delay is what the harness now measures.
    code, out, err = _run_bench(tmp_path, runs, mock_port=18765, delay_ms=60)
    assert code == 0, f"exit {code}: {err}\n{out}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert record["scenario"] == "scenario_b_mock_llm_controlled"
    assert record["latency_p50_ms"] is not None
    assert 20 < record["latency_p50_ms"] < 500
    assert record["latency_p95_ms"] is not None
    assert record["success_count"] == 30
    assert "tool_cycles=N/A" in record["notes"]


def test_scenario_b_requests_reach_candidate_with_zero_errors(tmp_path):
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs, mock_port=18766)
    assert code == 0
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert record["latency_p50_ms"] is not None
    assert record["error_count"] == 0
    assert record["success_count"] == 30
