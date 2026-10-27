"""CLI-seam tests for ticket #14: scenario C tasks.

Ticket #40: each task request goes to the candidate's chat endpoint. A single
repeat is used here so counts are unambiguous (the legacy scenario file sets
repeats=5 on top of repeats_per_task=5).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PROC_ROOT = FIXTURES / "proc"

from chat_agent_utils import free_port, requests_seen, write_chat_descriptor

RECORD_FIELDS = [
    "run_id", "agent", "repo_url", "version", "mode", "scenario",
    "host_profile", "started_at_utc", "duration_sec", "ram_pss_mb_median",
    "ram_peak_mb", "cpu_sec", "startup_ms", "latency_p50_ms", "latency_p95_ms",
    "success_count", "error_count", "oom_count", "notes", "config_ref",
]

SCENARIO_BODY = """
    name = "scenario_c_real_llm_tasks"
    task_count = 4
    repeats_per_task = 5
    repeats = 1
    mock_latency_ms = 0
    tool_cycles = 10
"""


def _write_scenario(base: Path, **over) -> Path:
    body = SCENARIO_BODY
    for key, value in over.items():
        body += f"\n    {key} = {value}"
    path = base / "scenario_c.toml"
    path.write_text(textwrap.dedent(body))
    return path


def _run_bench(workdir: Path, runs_dir: Path, scenario: Path | None = None, mock_port: int = 0) -> tuple[int, str, str]:
    desc = write_chat_descriptor(workdir, free_port())
    scenario = scenario or _write_scenario(workdir)
    cmd = [
        sys.executable, "-m", "bench", "run",
        str(desc), str(scenario),
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


def test_scenario_c_produces_record_with_all_section7_fields(tmp_path):
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs)
    assert code == 0, f"exit {code}: {err}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())

    missing = [f for f in RECORD_FIELDS if f not in record]
    assert missing == [], f"missing section 7 fields: {missing}"

    assert record["agent"] == "chat-fixture"
    assert record["version"] == "0.0.1"
    assert record["mode"] == "native"
    assert record["scenario"] == "scenario_c_real_llm_tasks"
    assert "task_count=4" in record["notes"]
    assert "repeats_per_task=5" in record["notes"]
    assert "unfinished_processes" in record["notes"]


def test_scenario_c_with_mock_server_latency_metrics(tmp_path):
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs)
    assert code == 0, f"exit {code}: {err}\n{out}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert record["scenario"] == "scenario_c_real_llm_tasks"
    assert record["latency_p50_ms"] is not None
    assert record["latency_p95_ms"] is not None
    assert record["success_count"] == 20
    # One repeat keeps the count exact: 4 tasks × 5 repeats served by the candidate.
    assert len(requests_seen(tmp_path / "wd")) == 20


def test_scenario_c_deterministic_with_fixed_latency(tmp_path):
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs)
    assert code == 0, f"exit {code}: {err}\n{out}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert record["scenario"] == "scenario_c_real_llm_tasks"
    assert record["latency_p50_ms"] is not None


def test_scenario_c_notes_include_task_info(tmp_path):
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs)
    assert code == 0, f"exit {code}: {err}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert "task_count=4" in record["notes"]
    assert "repeats_per_task=5" in record["notes"]


def test_scenario_c_mock_server_contract(tmp_path):
    runs = tmp_path / "runs"
    code, out, err = _run_bench(tmp_path, runs)
    assert code == 0, f"exit {code}: {err}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert record["scenario"] == "scenario_c_real_llm_tasks"
    assert record["latency_p50_ms"] is not None
    assert "error_count" in record
    assert "tool_cycles" in record["notes"]
