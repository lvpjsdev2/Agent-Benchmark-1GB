"""CLI-seam tests for ticket #19: `bench report` markdown generator.

Also covers the record-write sanitization wiring (ticket #16): no secret from
an agent descriptor reaches record.jsonl raw.

Tests drive the harness as a black box: `bench report` / `bench run` as a
subprocess, then assert on the produced markdown / run records.
"""

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
AGENT_SCRIPT = FIXTURES / "sleeper_agent.py"
SCENARIO = ROOT / "scenarios" / "cold_start.toml"
GOLDEN = ROOT / "tests" / "goldens" / "report.md"


def _base_record(**over):
    """A fully-populated section-7 record with fixed values (deterministic)."""
    rec = {
        "run_id": "deadbeef",
        "agent": "alpha-agent",
        "repo_url": "https://example.com/alpha",
        "version": "1.0.0",
        "mode": "native",
        "scenario": "scenario_a_cold_start",
        "host_profile": {"mem_available_mb_baseline": 480.0, "os": "darwin"},
        "started_at_utc": "2026-01-01T00:00:00.000000Z",
        "duration_sec": 3.0,
        "ram_pss_mb_median": 12.5,
        "ram_peak_mb": 20.0,
        "cpu_sec": 5.0,
        "startup_ms": 250.0,
        "latency_p50_ms": None,
        "latency_p95_ms": None,
        "success_count": 3,
        "error_count": 0,
        "oom_count": 0,
        "notes": "repeats=3",
        "config_ref": "scenarios/cold_start.toml",
    }
    rec.update(over)
    return rec


def _write_record(runs_dir: Path, run_id: str, rec: dict) -> None:
    d = runs_dir / run_id
    d.mkdir(parents=True)
    (d / "record.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n")


def _run_report(runs_dir: Path, out_path: Path) -> tuple[int, str, str]:
    cmd = [
        sys.executable, "-m", "bench", "report",
        "--runs-dir", str(runs_dir),
        "--output", str(out_path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=60)
    return p.returncode, p.stdout, p.stderr


def test_report_matches_golden(tmp_path):
    """Fixed record set must produce the exact golden report (reproducible)."""
    runs = tmp_path / "runs"
    _write_record(runs, "run-a1", _base_record())
    _write_record(runs, "run-a2", _base_record(
        run_id="feedface", mode="docker",
        ram_pss_mb_median=13.0, ram_peak_mb=21.5, cpu_sec=5.2, startup_ms=300.0,
    ))
    _write_record(runs, "run-b1", _base_record(
        run_id="cafecafe", agent="beta-agent", scenario="scenario_b_mock_llm_controlled_requests",
        started_at_utc="2026-01-02T00:00:00.000000Z",
        ram_pss_mb_median=None, ram_peak_mb=None, cpu_sec=None, startup_ms=None,
        latency_p50_ms=120.0, latency_p95_ms=300.0,
        success_count=28, error_count=2,
    ))
    out = tmp_path / "report.md"
    code, stdout, stderr = _run_report(runs, out)
    assert code == 0, f"exit {code}: {stderr}"
    assert out.read_text() == GOLDEN.read_text()


def test_missing_values_render_dash_and_unsupported(tmp_path):
    runs = tmp_path / "runs"
    _write_record(runs, "run-x", _base_record(
        ram_pss_mb_median=None, ram_peak_mb=None, cpu_sec=None, startup_ms=None,
    ))
    out = tmp_path / "report.md"
    code, _, stderr = _run_report(runs, out)
    assert code == 0, stderr
    text = out.read_text()
    # The resource row renders «—» for each missing metric and «unsupported»
    # for Disk MB (not collected by the harness); OOM=0 is real data.
    assert "| alpha-agent | native | — | — | — | — | unsupported | 0 |" in text


def test_native_and_docker_rows_are_separate(tmp_path):
    runs = tmp_path / "runs"
    _write_record(runs, "run-n", _base_record(mode="native", ram_peak_mb=20.0))
    _write_record(runs, "run-d", _base_record(mode="docker", run_id="abcd1234", ram_peak_mb=45.0))
    out = tmp_path / "report.md"
    code, _, stderr = _run_report(runs, out)
    assert code == 0, stderr
    text = out.read_text()
    assert "| alpha-agent | native |" in text
    assert "| alpha-agent | docker |" in text
    # Modes never mix inside one cell/row
    native_row = next(line for line in text.splitlines() if line.startswith("| alpha-agent | native "))
    docker_row = next(line for line in text.splitlines() if line.startswith("| alpha-agent | docker "))
    assert "20" in native_row and "20" not in docker_row
    assert "45" in docker_row and "45" not in native_row


def test_report_contains_no_secrets(tmp_path):
    runs = tmp_path / "runs"
    # Poison fields the report actually renders (version appears in the
    # experiment passport); notes are not emitted by the report.
    _write_record(runs, "run-s", _base_record(
        version="1.0.0 sk-abc123def456ghi789jkl12",
        agent="leaky-agent-192.168.13.37",
    ))
    out = tmp_path / "report.md"
    code, _, stderr = _run_report(runs, out)
    assert code == 0, stderr
    text = out.read_text()
    assert "sk-abc123def456ghi789jkl12" not in text
    assert "192.168.13.37" not in text
    assert "[REDACTED]" in text


def test_report_no_runs_dir_returns_exit_code_1(tmp_path):
    code, stdout, stderr = _run_report(tmp_path / "missing", tmp_path / "report.md")
    assert code == 1
    assert "not found" in stderr.lower()


def test_report_no_records_returns_exit_code_1(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    code, stdout, stderr = _run_report(runs, tmp_path / "report.md")
    assert code == 1
    assert "no run records" in stderr.lower()


# --- Record-write sanitization (ticket #16 wiring) -------------------------

def _write_descriptor(workdir: Path, name: str) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    desc = workdir / "agent.toml"
    desc.write_text(textwrap.dedent(f"""
        name = "{name}"
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


def _run_bench(workdir: Path, runs_dir: Path, name: str) -> tuple[int, str, str]:
    desc = _write_descriptor(workdir, name)
    cmd = [
        sys.executable, "-m", "bench", "run",
        str(desc), str(SCENARIO),
        "--proc-root", str(PROC_ROOT),
        "--cgroup-root", str(FIXTURES / "cgroup"),
        "--runs-dir", str(runs_dir),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=120)
    return p.returncode, p.stdout, p.stderr


def test_run_with_poisoned_agent_name_redacts_record(tmp_path):
    runs = tmp_path / "runs"
    code, stdout, stderr = _run_bench(
        tmp_path, runs, "leaky sk-abc123def456ghi789jkl12"
    )
    assert code == 0, stderr
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert "sk-abc123def456ghi789jkl12" not in json.dumps(record, ensure_ascii=False)
    assert "[REDACTED]" in record["agent"]
    assert "sanitizer_triggered=true" in record["notes"]
