"""CLI-seam tests for ticket #29 — the candidate failure policy from map #22.

Agreed policy (wayfinder ticket #29):
- a candidate that does not come up gets three start attempts before its failure
  is recorded, and each failed attempt is stopped before the next one starts;
- a candidate that cannot be launched at all is an install failure: exit code 6,
  ``install_failed`` in notes, and a record so the report keeps its row;
- an unpullable docker image is recorded the same way instead of exiting with a
  stderr message and no artifact.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PROC_ROOT = FIXTURES / "proc"
COUNTER_AGENT = FIXTURES / "start_counter_agent.py"


def _write_descriptor(
    workdir: Path,
    counter: Path,
    healthy_from: int,
    timeout_sec: int = 1,
    start_command: list[str] | None = None,
    mode: str = "native",
    image: str | None = None,
) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    wd = workdir / "wd"
    wd.mkdir(parents=True, exist_ok=True)
    hc = str(wd / "healthy")
    start = start_command or [
        sys.executable, str(COUNTER_AGENT), str(counter), hc, str(healthy_from),
    ]
    lines = [
        'name = "start-policy-fixture"',
        'repo_url = "https://example.com/start-policy"',
        'version = "0.0.1"',
        f'mode = "{mode}"',
    ]
    if image:
        lines.append(f'image = "{image}"')
    lines += [
        f"start_command = {json.dumps(start)}",
        f'workdir = "{wd}"',
        "",
        "[healthcheck]",
        'type = "file"',
        f'value = "{hc}"',
        f"timeout_sec = {timeout_sec}",
    ]
    desc = workdir / "agent.toml"
    desc.write_text("\n".join(lines) + "\n")
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


def _run_bench(desc: Path, scenario: Path, runs: Path, *extra: str) -> tuple[int, str, str]:
    cmd = [
        sys.executable, "-m", "bench", "run", str(desc), str(scenario),
        "--proc-root", str(PROC_ROOT),
        "--cgroup-root", str(FIXTURES / "cgroup"),
        "--runs-dir", str(runs),
        *extra,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=180)
    return p.returncode, p.stdout, p.stderr


def _record(runs: Path) -> dict:
    return json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())


def _repeats(runs: Path) -> list[dict]:
    path = list(runs.glob("*/repeats.jsonl"))[0]
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- three start attempts ----------------------------------------------------

def test_default_three_start_attempts_then_health_guard(tmp_path):
    runs = tmp_path / "runs"
    counter = tmp_path / "starts.log"
    # healthy_from=99: the fixture never becomes healthy (healthcheck times out)
    desc = _write_descriptor(tmp_path, counter, healthy_from=99)
    scenario = _write_scenario(tmp_path)
    code, out, err = _run_bench(desc, scenario, runs)
    assert code == 4, f"exit {code}: {err}"
    summary = json.loads(out)
    assert summary["guard"]["code"] == 4
    # Exactly three attempts were launched, one per start attempt
    assert counter.read_text().splitlines() == ["start"] * 3
    record = _record(runs)
    assert "healthcheck failed after 3 start attempt(s)" in record["notes"]
    assert "start_attempts_used=3" in record["notes"]
    assert _repeats(runs)[0]["start_attempts_used"] == 3


def test_start_attempts_stop_once_the_candidate_is_healthy(tmp_path):
    runs = tmp_path / "runs"
    counter = tmp_path / "starts.log"
    desc = _write_descriptor(tmp_path, counter, healthy_from=2)
    scenario = _write_scenario(tmp_path)
    code, out, err = _run_bench(desc, scenario, runs)
    assert code == 0, f"exit {code}: {err}"
    assert counter.read_text().splitlines() == ["start", "start"]
    record = _record(runs)
    assert "start_attempts_used=2" in record["notes"]
    assert record["success_count"] == 1


def test_scenario_can_lower_start_attempts(tmp_path):
    runs = tmp_path / "runs"
    counter = tmp_path / "starts.log"
    desc = _write_descriptor(tmp_path, counter, healthy_from=99)
    scenario = _write_scenario(tmp_path, start_attempts=2)
    code, out, err = _run_bench(desc, scenario, runs)
    assert code == 4, f"exit {code}: {err}"
    assert counter.read_text().splitlines() == ["start", "start"]
    assert "healthcheck failed after 2 start attempt(s)" in _record(runs)["notes"]


# --- install_failed ----------------------------------------------------------

def test_unlaunchable_candidate_is_install_failed(tmp_path):
    runs = tmp_path / "runs"
    counter = tmp_path / "starts.log"
    desc = _write_descriptor(
        tmp_path, counter, healthy_from=1,
        start_command=["/nonexistent/bench-candidate-binary", "--serve"],
    )
    scenario = _write_scenario(tmp_path)
    code, out, err = _run_bench(desc, scenario, runs)
    assert code == 6, f"exit {code}: {err}"
    summary = json.loads(out)
    assert summary["status"] == "unavailable"
    assert summary["guard"]["code"] == 6
    # The failure is a record, not just a stderr message
    record = _record(runs)
    assert "install_failed=" in record["notes"]
    assert record["success_count"] == 0
    assert not counter.exists()  # the missing binary never ran


def test_docker_pull_failure_writes_install_failed_record(tmp_path):
    runs = tmp_path / "runs"
    stub = tmp_path / "docker_stub.sh"
    stub.write_text("#!/bin/bash\necho 'pull failed: manifest unknown' >&2\nexit 1\n")
    stub.chmod(0o755)
    desc = _write_descriptor(
        tmp_path, tmp_path / "starts.log", healthy_from=1, mode="docker",
        image="ghcr.io/example/agent@sha256:" + "a" * 64,
    )
    scenario = _write_scenario(tmp_path)
    code, out, err = _run_bench(desc, scenario, runs, "--docker-bin", str(stub))
    assert code == 6, f"exit {code}: {err}"
    summary = json.loads(out)
    assert summary["status"] == "unavailable"
    record = _record(runs)
    assert record["mode"] == "docker"
    assert "install_failed=docker_pull_failed" in record["notes"]
    assert "docker_image=ghcr.io/example/agent@sha256:" in record["notes"]
