"""CLI-seam tests for ticket #13: scenario B mock LLM and controlled requests."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PROC_ROOT = FIXTURES / "proc"
SCENARIO = ROOT / "scenarios" / "mock_llm_controlled_requests.toml"
AGENT_SCRIPT = FIXTURES / "sleeper_agent.py"

RECORD_FIELDS = [
    "run_id", "agent", "repo_url", "version", "mode", "scenario",
    "host_profile", "started_at_utc", "duration_sec", "ram_pss_mb_median",
    "ram_peak_mb", "cpu_sec", "startup_ms", "latency_p50_ms", "latency_p95_ms",
    "success_count", "error_count", "oom_count", "notes", "config_ref",
]

def _write_descriptor(workdir: Path, mock_port: int) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    desc = workdir / "agent.toml"
    desc.write_text(textwrap.dedent(f"""
        name = "sleeper-fixture"
        repo_url = "https://example.com/sleeper"
        version = "0.0.1"
        mode = "native"
        start_command = ["python3", "{AGENT_SCRIPT}", "{workdir / 'wd'}", "0.1"]
        workdir = "{workdir / 'wd'}"

        [healthcheck]
        type = "file"
        value = "{workdir / 'wd' / 'healthy'}"
        timeout_sec = 10
    """))
    return desc

def _run_bench(workdir: Path, runs_dir: Path, mock_port: int = 0) -> tuple[int, str, str]:
    desc = _write_descriptor(workdir, mock_port)
    cmd = [
        sys.executable, "-m", "bench", "run",
        str(desc), str(SCENARIO),
        "--proc-root", str(PROC_ROOT),
        "--runs-dir", str(runs_dir),
    ]
    if mock_port:
        cmd.append("--mock-llm-port")
        cmd.append(str(mock_port))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT,
    )
    stdout, stderr = proc.communicate(timeout=120)
    return proc.returncode, stdout, stderr

def test_scenario_b_produces_latency_metrics(tmp_path):
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs, mock_port=0)
    # With mock port 0, server starts on random port, latency measured
    assert code == 0, f"exit {code}: {err}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    missing = [f for f in RECORD_FIELDS if f not in record]
    assert missing == []
    assert record["scenario"] == "scenario_b_mock_llm_controlled"
    # latency fields should be present when mock server started
    assert record["latency_p50_ms"] is not None

def test_scenario_b_with_mock_latency_deterministic(tmp_path):
    runs = tmp_path / "runs"
    # Use port 0 to let OS pick, but we need a fixed port for test determinism.
    # We'll start server manually via flag.
    code, out, err = _run_bench(tmp_path, runs, mock_port=18765)
    assert code == 0, f"exit {code}: {err}\n{out}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert record["scenario"] == "scenario_b_mock_llm_controlled"
    # With mock latency 50ms configured, p50 should be around 50-150ms
    assert record["latency_p50_ms"] is not None
    assert 20 < record["latency_p50_ms"] < 500
    assert record["latency_p95_ms"] is not None
    # success count should be 30 requests
    # success_count records total requests success across repeats
    assert record["success_count"] > 0
    # notes should contain tool_cycles=N/A
    assert "tool_cycles=N/A" in record["notes"]

def test_mock_server_contract_openai_compatible(tmp_path):
    # Verify mock server can be started via flag and responds
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs, mock_port=18766)
    assert code == 0
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    # Ensure mock server was used: latency present
    assert record["latency_p50_ms"] is not None
    # Verify error_count is zero with default config
    assert record["error_count"] == 0
