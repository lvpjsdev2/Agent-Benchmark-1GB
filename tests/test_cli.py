"""CLI-seam tests for ticket #11: scenario A (cold start / idle).

Tests drive the harness as a black box: `bench run` as a subprocess, then assert
on the produced run records, exit codes, and stdout. Never reads the real /proc.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PROC_ROOT = FIXTURES / "proc"
AGENT_SCRIPT = FIXTURES / "sleeper_agent.py"
SCENARIO = ROOT / "scenarios" / "cold_start.toml"

# All 20 fields from METHODOLOGY.md section 7 — the record must never omit them.
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


def _run_bench(workdir: Path, runs_dir: Path) -> tuple[int, str, str]:
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
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
    )
    stdout, stderr = proc.communicate(timeout=120)
    return proc.returncode, stdout, stderr


def test_run_produces_record_with_all_section7_fields(tmp_path):
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs)
    assert code == 0, f"exit {code}: {err}"
    assert "status" in out and '"ok"' in out

    record_files = list(runs.glob("*/record.jsonl"))
    assert len(record_files) == 1, f"expected one record file, got {record_files}"
    record = json.loads(record_files[0].read_text())

    # Every section 7 field must be present (missing = null, never omitted)
    missing = [f for f in RECORD_FIELDS if f not in record]
    assert missing == [], f"missing section 7 fields: {missing}"

    assert record["agent"] == "sleeper-fixture"
    assert record["version"] == "0.0.1"
    assert record["mode"] == "native"
    assert record["scenario"] == "scenario_a_cold_start"
    assert record["success_count"] == 3
    assert record["error_count"] == 0
    assert record["oom_count"] == 0
    assert record["ram_pss_mb_median"] == 15.0
    assert record["ram_peak_mb"] == 20.0
    assert record["host_profile"]["mem_available_mb_baseline"] == 512.0
    assert record["startup_ms"] is not None and record["startup_ms"] > 0
    assert "variance" in record["notes"]


def test_repeats_and_variance_recorded(tmp_path):
    runs = tmp_path / "runs"
    code, _, err = _run_bench(tmp_path, runs)
    assert code == 0, err

    repeats = list(runs.glob("*/repeats.jsonl"))
    assert len(repeats) == 1
    rows = [json.loads(line) for line in repeats[0].read_text().splitlines() if line.strip()]
    assert len(rows) == 3, f"expected 3 repeats, got {len(rows)}"
    assert all(r["success"] for r in rows)
    assert all(r["startup_ms"] is not None for r in rows)
    assert all(r["ram_pss_mb_median"] == 15.0 for r in rows)


def test_startup_measured_from_process_start_to_healthcheck(tmp_path):
    runs = tmp_path / "runs"
    code, _, err = _run_bench(tmp_path, runs)
    assert code == 0, err

    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    # The fixture sleeps 0.2 s before writing the health file, so startup must
    # be well above the sleep and below the scenario duration + healthcheck timeout.
    assert 200.0 < record["startup_ms"] < 10000.0


def test_missing_agent_descriptor_returns_exit_code_1(tmp_path):
    cmd = [
        sys.executable, "-m", "bench", "run",
        "does-not-exist.toml", str(SCENARIO),
        "--proc-root", str(PROC_ROOT),
        "--runs-dir", str(tmp_path / "runs"),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT)
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 1
    assert "not found" in err.lower()


def test_missing_scenario_returns_exit_code_1(tmp_path):
    desc = _write_descriptor(tmp_path)
    cmd = [
        sys.executable, "-m", "bench", "run",
        str(desc), "does-not-exist.toml",
        "--proc-root", str(PROC_ROOT),
        "--runs-dir", str(tmp_path / "runs"),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT)
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 1
    assert "not found" in err.lower()


def test_cli_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "bench", "--help"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0
    assert "run" in proc.stdout