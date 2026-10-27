"""CLI-seam tests for ticket #15: scenario D (stability and recovery).

Covers: sequential mock-request series with success/error counts, RSS growth
(leak) detection, mid-series agent restart with test-state preservation check,
error injection (429 / per-call) recorded without retries, and unfinished
(hung child) process detection.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
AGENT_SCRIPT = FIXTURES / "sleeper_agent.py"


def _write_descriptor(workdir: Path, behavior: str = "") -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    desc = workdir / "agent.toml"
    # sleeper_agent.py argv: workdir, delay_ms, mem_growth_kb, test_state_file,
    # initial_delay, behavior
    parts = [
        "python3", str(AGENT_SCRIPT), str(workdir / "wd"), "0",
        "0", "test_state.json", "0.2",
    ]
    if behavior:
        parts.append(behavior)
    cmd = ", ".join(f'"{p}"' for p in parts)
    desc.write_text(textwrap.dedent(f"""
        name = "d-fixture"
        repo_url = "https://example.com/d"
        version = "0.0.1"
        mode = "native"
        start_command = [{cmd}]
        workdir = "{workdir / 'wd'}"

        [healthcheck]
        type = "file"
        value = "{workdir / 'wd' / 'healthy'}"
        timeout_sec = 10
    """))
    return desc


def _write_scenario(workdir: Path, **over) -> Path:
    defaults = {
        "name": "scenario_d_stability_recovery",
        "requests": 10,
        "warmup_requests": 0,
        "repeats": 1,
        "mock_latency_ms": 5,
        "pause_between_ms": 5,
        "restart_after_requests": 5,
        "test_state_file": "test_state.json",
        "proc_pid_override": 1000,
    }
    defaults.update(over)
    lines = [f"{k} = {v}" if not isinstance(v, str) else f'{k} = "{v}"' for k, v in defaults.items()]
    path = workdir / "scenario_d.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def _run_bench(workdir: Path, runs_dir: Path, scenario: Path, *extra: str, proc_root=None, behavior: str = "") -> tuple[int, str, str]:
    desc = _write_descriptor(workdir, behavior=behavior)
    cmd = [
        sys.executable, "-m", "bench", "run",
        str(desc), str(scenario),
        "--proc-root", str(proc_root or FIXTURES / "proc"),
        "--cgroup-root", str(FIXTURES / "cgroup"),
        "--runs-dir", str(runs_dir),
        "--mock-llm-port", "0",
        *extra,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=120)
    return p.returncode, p.stdout, p.stderr


def _record(runs_dir: Path) -> dict:
    return json.loads(list(runs_dir.glob("*/record.jsonl"))[0].read_text())


def test_scenario_d_series_counts_restart_state_and_leak_flag(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path)
    code, out, err = _run_bench(tmp_path, runs, scenario)
    assert code == 0, f"exit {code}: {err}"
    record = _record(runs)
    # Full series counted
    assert record["success_count"] == 10
    assert record["error_count"] == 0
    # Latency measured against the mock
    assert record["latency_p50_ms"] is not None
    assert record["latency_p95_ms"] is not None
    notes = record["notes"]
    # Restart mid-series preserved the fixture test state
    assert "restart_state=preserved" in notes
    # Static fixture proc tree: no growth, not a leak
    assert "rss_growth_mb=0.0" in notes
    assert "rss_leak=false" in notes
    assert "unfinished_processes=0" in notes
    assert "mock_error_mode=None" in notes


def test_scenario_d_restart_state_lost(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path, test_state_file="never_written_state.json")
    code, out, err = _run_bench(tmp_path, runs, scenario)
    assert code == 0, err
    assert "restart_state=lost" in _record(runs)["notes"]


def test_scenario_d_rss_growth_detected_as_leak(tmp_path):
    runs = tmp_path / "runs"
    # Dynamic proc tree: a background updater grows Rss while the series runs
    proc_root = tmp_path / "proc"
    pid_dir = proc_root / "2000"
    pid_dir.mkdir(parents=True)
    (proc_root / "meminfo").write_text((FIXTURES / "proc" / "meminfo").read_text())

    updater = subprocess.Popen(
        [
            sys.executable, "-c",
            "import sys, time, pathlib\n"
            "target = pathlib.Path(sys.argv[1])\n"
            "base, i = 10240, 0\n"
            "deadline = time.time() + 30\n"
            "while time.time() < deadline:\n"
            "    kb = base + 2560 * i\n"
            "    target.write_text(f\"VmRSS: {kb} kB\\nVmSize: {kb} kB\\n\")\n"
            "    i += 1\n"
            "    time.sleep(0.1)\n",
            str(pid_dir / "status"),
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        scenario = _write_scenario(
            tmp_path,
            proc_pid_override=2000,
            pause_between_ms=150,
            rss_growth_threshold_mb=1.0,
        )
        code, out, err = _run_bench(tmp_path, runs, scenario, proc_root=proc_root)
        assert code == 0, f"exit {code}: {err}"
        notes = _record(runs)["notes"]
        assert "rss_leak=true" in notes
        assert "rss_growth_mb=" in notes
    finally:
        updater.kill()


def test_scenario_d_error_mode_429_all_errors_recorded(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path, mock_error_mode="429")
    code, out, err = _run_bench(tmp_path, runs, scenario)
    assert code == 0, f"exit {code}: {err}"
    record = _record(runs)
    assert record["success_count"] == 0
    assert record["error_count"] == 10
    assert "mock_error_mode=429" in record["notes"]


def test_scenario_d_error_on_single_call(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path, mock_error_mode="429", error_on_call=3)
    code, out, err = _run_bench(tmp_path, runs, scenario)
    assert code == 0, f"exit {code}: {err}"
    record = _record(runs)
    assert record["success_count"] == 9
    assert record["error_count"] == 1


def test_scenario_d_mock_timeout_on_single_call(tmp_path):
    """Ticket #38: a timeout hangs the targeted call; its neighbours answer normally."""
    runs = tmp_path / "runs"
    scenario = _write_scenario(
        tmp_path,
        mock_error_mode="timeout",
        error_on_call=3,
        request_timeout_sec=0.2,
        mock_timeout_sleep_sec=0.5,
    )
    code, out, err = _run_bench(tmp_path, runs, scenario)
    assert code == 0, f"exit {code}: {err}"
    record = _record(runs)
    assert record["success_count"] == 9
    assert record["error_count"] == 1
    assert "mock_error_mode=timeout" in record["notes"]


def test_scenario_d_hung_child_detected_as_unfinished(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path)
    code, out, err = _run_bench(tmp_path, runs, scenario, behavior="spawn_hung_child")
    assert code == 0, f"exit {code}: {err}"
    notes = _record(runs)["notes"]
    # Agent #1's child is orphaned by the mid-series restart (agent #2's child
    # spawns after the series ends given the instant healthcheck from the
    # persisted health file) — at least one unfinished process is recorded.
    assert "unfinished_processes=1" in notes or "unfinished_processes=2" in notes
    assert "unfinished_pids=" in notes
    # Harness hygiene: the hung child was killed after being recorded
    pids_part = next(n for n in notes.split(", ") if n.startswith("unfinished_pids="))
    for pid in pids_part.split("=", 1)[1].split(","):
        alive = subprocess.run(["kill", "-0", pid], capture_output=True)
        assert alive.returncode != 0, f"pid {pid} left alive"
