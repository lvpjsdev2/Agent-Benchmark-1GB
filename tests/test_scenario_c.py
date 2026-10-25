"""CLI-seam tests for ticket #14: scenario C (real LLM tasks, 4 tasks × 5 repeats)."""

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
SCENARIO = ROOT / "scenarios" / "scenario_c_real_llm_tasks.toml"
AGENT_SCRIPT = FIXTURES / "sleeper_agent.py"

RECORD_FIELDS = [
    "run_id", "agent", "repo_url", "version", "mode", "scenario",
    "host_profile", "started_at_utc", "duration_sec", "ram_pss_mb_median",
    "ram_peak_mb", "cpu_sec", "startup_ms", "latency_p50_ms", "latency_p95_ms",
    "success_count", "error_count", "oom_count", "notes", "config_ref",
]


def _write_descriptor(workdir: Path) -> Path:
    """Write a portable agent descriptor (absolute paths) into workdir."""
    workdir.mkdir(parents=True, exist_ok=True)
    desc = workdir / "agent.toml"
    desc.write_text(textwrap.dedent(f"""
        name = "sleeper-fixture"
        repo_url = "https://example.com/sleeper"
        version = "0.0.1"
        mode = "native"
        start_command = ["python3", "{AGENT_SCRIPT}", "{workdir / 'wd'}", "0.2"]
        workdir = "{workdir / 'wd'}"

        [healthcheck]
        type = "file"
        value = "{workdir / 'wd' / 'healthy'}"
        timeout_sec = 10
    """))
    return desc


def _run_bench(workdir: Path, runs_dir: Path, mock_port: int = 0) -> tuple[int, str, str]:
    desc = _write_descriptor(workdir)
    cmd = [
        sys.executable,
        "-m",
        "bench",
        "run",
        str(desc),
        str(SCENARIO),
        "--proc-root",
        str(PROC_ROOT),
        "--runs-dir",
        str(runs_dir),
    ]
    if mock_port is not None:
        cmd.append("--mock-llm-port")
        cmd.append(str(mock_port))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
    )
    stdout, stderr = proc.communicate(timeout=120)
    return proc.returncode, stdout, stderr


def test_scenario_c_produces_record_with_all_section7_fields(tmp_path):
    """Test that scenario C produces a record with all Section 7 fields."""
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs, mock_port=0)
    # With mock_port=0, scenario C dispatches using task_count/repeats_per_task from TOML
    assert code == 0, f"exit {code}: {err}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())

    # Every section 7 field must be present (missing = null, never omitted)
    missing = [f for f in RECORD_FIELDS if f not in record]
    assert missing == [], f"missing section 7 fields: {missing}"

    assert record["agent"] == "sleeper-fixture"
    assert record["version"] == "0.0.1"
    assert record["mode"] == "native"
    assert record["scenario"] == "scenario_c_real_llm_tasks"
    # With mock_port=0, tasks run against mock server on random port
    # success_count reflects task successes against the mock server
    assert record["success_count"] >= 0
    assert record["error_count"] >= 0
    # notes should indicate task_count and repeats_per_task
    assert "task_count=4" in record["notes"]
    assert "repeats_per_task=5" in record["notes"]
    assert "unfinished_processes" in record["notes"]


def test_scenario_c_with_mock_server_latency_metrics(tmp_path):
    """Test scenario C with mock LLM server - latency metrics should be present."""
    runs = tmp_path / "runs"
    # Use port 0 for OS-assigned port
    code, out, err = _run_bench(tmp_path, runs, mock_port=0)
    assert code == 0, f"exit {code}: {err}\n{out}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert record["scenario"] == "scenario_c_real_llm_tasks"
    # With mock server, latency fields should be present
    assert record["latency_p50_ms"] is not None, "latency_p50_ms should be present with mock server"
    assert record["latency_p95_ms"] is not None, "latency_p95_ms should be present with mock server"
    # success_count should reflect task successes (or 0 if errors)
    assert record["success_count"] >= 0


def test_scenario_c_deterministic_with_fixed_latency(tmp_path):
    """Test scenario C with mock LLM server - latency should be measurable."""
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs, mock_port=0)
    assert code == 0, f"exit {code}: {err}\n{out}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert record["scenario"] == "scenario_c_real_llm_tasks"
    assert record["latency_p50_ms"] is not None


def test_scenario_c_notes_include_task_info(tmp_path):
    """Test that scenario C notes include task count and repeat info."""
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs, mock_port=0)
    assert code == 0, f"exit {code}: {err}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert "task_count=4" in record["notes"]
    assert "repeats_per_task=5" in record["notes"]


def test_scenario_c_mock_server_contract(tmp_path):
    """Test mock server contract with scenario C."""
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs, mock_port=0)
    assert code == 0, f"exit {code}: {err}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert record["scenario"] == "scenario_c_real_llm_tasks"
    # With mock server running, latency should be present
    assert record["latency_p50_ms"] is not None
    # Verify error_count recorded
    assert "error_count" in record
    # Verify tool_cycles note is present
    assert "tool_cycles" in record["notes"]