"""CLI-seam tests for ticket #16: guard contour (dry-run + auto-stop thresholds).

Guards abort the run with distinct exit codes so an AFK run can be triaged
without a human: 2 OOM, 3 MemAvailable, 4 health lost, 5 API budget. On a
guard trip the already-collected records are saved and the run is marked
aborted in notes. --dry-run prints the plan and spawns nothing.
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
AGENT_SCRIPT = FIXTURES / "sleeper_agent.py"

from chat_agent_utils import free_port, write_chat_descriptor


def _write_descriptor(workdir: Path, timeout_sec: int = 10, health_value: str | None = None) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    desc = workdir / "agent.toml"
    hc = health_value or str(workdir / "wd" / "healthy")
    desc.write_text(textwrap.dedent(f"""
        name = "guard-fixture"
        repo_url = "https://example.com/guard"
        version = "0.0.1"
        mode = "native"
        start_command = ["python3", "{AGENT_SCRIPT}", "{workdir / 'wd'}", "0"]
        workdir = "{workdir / 'wd'}"

        [healthcheck]
        type = "file"
        value = "{hc}"
        timeout_sec = {timeout_sec}
    """))
    return desc


def _write_scenario(workdir: Path, **over) -> Path:
    lines = [
        'name = "scenario_a_cold_start"',
        "duration_sec = 2",
        "sample_interval_sec = 1",
        "repeats = 1",
        "proc_pid_override = 1000",
        'cgroup_path = "v2/agent"',
    ]
    lines += [f"{k} = {v}" for k, v in over.items()]
    path = workdir / "scenario.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def _run_bench(workdir: Path, runs_dir: Path, scenario: Path, *extra: str, timeout_sec: int = 10, cgroup_root: str | None = None, health_value: str | None = None, chat: bool = False) -> tuple[int, str, str]:
    if chat:
        # Ticket #40: request scenarios need the candidate's own chat endpoint.
        desc = write_chat_descriptor(workdir, free_port())
    else:
        desc = _write_descriptor(workdir, timeout_sec=timeout_sec, health_value=health_value)
    cmd = [
        sys.executable, "-m", "bench", "run",
        str(desc), str(scenario),
        "--proc-root", str(PROC_ROOT),
        "--cgroup-root", cgroup_root or str(FIXTURES / "cgroup"),
        "--runs-dir", str(runs_dir),
        *extra,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=120)
    return p.returncode, p.stdout, p.stderr


# --- dry-run ----------------------------------------------------------------

def test_dry_run_prints_plan_and_spawns_nothing(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path, guard_oom_threshold=5)
    code, out, err = _run_bench(tmp_path, runs, scenario, "--dry-run")
    assert code == 0, f"exit {code}: {err}"
    plan = json.loads(out)
    assert plan["dry_run"] is True
    # The plan names the command that would run and the guard thresholds
    assert "sleeper_agent.py" in str(plan["start_command"])
    assert plan["guards"]["oom_threshold"] == 5
    # Nothing executed: no run directory, no records
    assert not runs.exists() or not list(runs.glob("*/record.jsonl"))


def test_dry_run_missing_scenario_still_fails(tmp_path):
    runs = tmp_path / "runs"
    desc = _write_descriptor(tmp_path)
    cmd = [
        sys.executable, "-m", "bench", "run", str(desc), "missing.toml",
        "--proc-root", str(PROC_ROOT), "--runs-dir", str(runs), "--dry-run",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert p.returncode == 1


# --- guard 2: OOM -----------------------------------------------------------

def test_oom_guard_stops_run_with_exit_code_2(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path, guard_oom_threshold=1)
    # Fixture cgroup with memory.events oom=2 (>= threshold 1)
    code, out, err = _run_bench(
        tmp_path, runs, scenario,
        cgroup_root=str(FIXTURES / "cgroup_oom"),
    )
    assert code == 2, f"exit {code}: {err}"
    summary = json.loads(out)
    assert summary["status"] == "aborted"
    assert summary["guard"]["code"] == 2
    # Partial records are saved and marked aborted
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert "aborted=guard2:" in record["notes"]
    assert "oom_count=2>=guard_oom_threshold=1" in record["notes"]


def test_oom_below_threshold_does_not_abort(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path, guard_oom_threshold=10)
    code, out, err = _run_bench(tmp_path, runs, scenario)
    assert code == 0, f"exit {code}: {err}"


# --- guard 3: MemAvailable ---------------------------------------------------

def test_memavailable_guard_stops_run_with_exit_code_3(tmp_path):
    runs = tmp_path / "runs"
    # Fixture proc meminfo provides MemAvailable 524288 kB = 512 MB
    scenario = _write_scenario(tmp_path, guard_memavailable_min_mb=600)
    code, out, err = _run_bench(tmp_path, runs, scenario)
    assert code == 3, f"exit {code}: {err}"
    summary = json.loads(out)
    assert summary["guard"]["code"] == 3
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert "aborted=guard3:" in record["notes"]


def test_memavailable_above_threshold_does_not_abort(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path, guard_memavailable_min_mb=256)
    code, out, err = _run_bench(tmp_path, runs, scenario)
    assert code == 0, f"exit {code}: {err}"


# --- guard 4: health lost -----------------------------------------------------

def test_health_guard_stops_run_with_exit_code_4(tmp_path):
    runs = tmp_path / "runs"
    # Healthcheck points at a file the agent never writes: timeout trips guard 4
    scenario = _write_scenario(tmp_path)
    code, out, err = _run_bench(
        tmp_path, runs, scenario, timeout_sec=1,
        health_value=str(tmp_path / "wd" / "never_healthy"),
    )
    assert code == 4, f"exit {code}: {err}"
    summary = json.loads(out)
    assert summary["guard"]["code"] == 4
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert "aborted=guard4:" in record["notes"]


# --- guard 5: API budget ------------------------------------------------------

def _write_scenario_b(workdir: Path, **over) -> Path:
    lines = [
        'name = "scenario_b_mock_llm_controlled_requests"',
        "requests = 10",
        "warmup_requests = 0",
        "repeats = 1",
        "mock_latency_ms = 5",
        "proc_pid_override = 1000",
    ]
    lines += [f"{k} = {v}" for k, v in over.items()]
    path = workdir / "scenario_b.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_api_budget_guard_stops_run_with_exit_code_5(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario_b(tmp_path, guard_api_request_budget=3)
    code, out, err = _run_bench(tmp_path, runs, scenario, "--mock-llm-port", "0", chat=True)
    assert code == 5, f"exit {code}: {err}"
    summary = json.loads(out)
    assert summary["guard"]["code"] == 5
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    assert "aborted=guard5:" in record["notes"]
    # Partial records kept: exactly the budgeted number of requests
    assert record["success_count"] + record["error_count"] == 3


def test_api_budget_not_reached_does_not_abort(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario_b(tmp_path, guard_api_request_budget=100)
    code, out, err = _run_bench(tmp_path, runs, scenario, "--mock-llm-port", "0", chat=True)
    assert code == 0, f"exit {code}: {err}"
