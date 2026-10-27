"""CLI-seam tests for ticket #20: docker mode via a docker CLI stub.

The stub (tests/fixtures/docker_stub.sh) emulates `pull` and `run`; `run`
execs the container command. Tests are deterministic on macOS — no real
docker daemon is needed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PROC_ROOT = FIXTURES / "proc"
AGENT_SCRIPT = FIXTURES / "sleeper_agent.py"
DOCKER_STUB = FIXTURES / "docker_stub.sh"
SCENARIO = ROOT / "scenarios" / "cold_start.toml"
DIGEST = "sha256:" + "ab" * 32

RECORD_FIELDS = [
    "run_id", "agent", "repo_url", "version", "mode", "scenario",
    "host_profile", "started_at_utc", "duration_sec", "ram_pss_mb_median",
    "ram_peak_mb", "cpu_sec", "startup_ms", "latency_p50_ms", "latency_p95_ms",
    "success_count", "error_count", "oom_count", "notes", "config_ref",
]


def _write_descriptor(workdir: Path, image: str | None = None, docker_args: list[str] | None = None) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    desc = workdir / "agent.toml"
    extra = ""
    if docker_args is not None:
        args = ", ".join(f'"{a}"' for a in docker_args)
        extra = f"docker_args = [{args}]\n"
    desc.write_text(textwrap.dedent(f"""
        name = "docker-fixture"
        repo_url = "https://example.com/docker-fixture"
        version = "0.0.1"
        mode = "docker"
        image = "{image or f'example/fixture-agent@{DIGEST}'}"
        start_command = ["python3", "{AGENT_SCRIPT}", "{workdir / 'wd'}", "0.2"]
        workdir = "{workdir / 'wd'}"
        {extra}
        [healthcheck]
        type = "file"
        value = "{workdir / 'wd' / 'healthy'}"
        timeout_sec = 10
    """))
    return desc


def _run_bench(workdir: Path, runs_dir: Path, desc: Path, scenario: Path | None = None,
               extra_env: dict | None = None) -> tuple[int, str, str, Path]:
    stub_log = workdir / "docker_stub.log"
    env = dict(os.environ, DOCKER_STUB_LOG=str(stub_log), **(extra_env or {}))
    cmd = [
        sys.executable, "-m", "bench", "run",
        str(desc), str(scenario or SCENARIO),
        "--proc-root", str(PROC_ROOT),
        "--cgroup-root", str(FIXTURES / "cgroup"),
        "--runs-dir", str(runs_dir),
        "--docker-bin", str(DOCKER_STUB),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, env=env, timeout=120)
    return p.returncode, p.stdout, p.stderr, stub_log


def _write_scenario(workdir: Path, **over) -> Path:
    defaults = {
        "name": "scenario_a_cold_start",
        "duration_sec": 2,
        "sample_interval_sec": 1,
        "repeats": 1,
        "proc_pid_override": 1000,
        "cgroup_path": "v2/agent",
        "docker_memory_limit": "64m",
        "docker_cpu_limit": "0.5",
    }
    defaults.update(over)
    lines = [f"{k} = {v}" if not isinstance(v, str) else f'{k} = "{v}"' for k, v in defaults.items()]
    path = workdir / "scenario.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_docker_mode_runs_via_stub_and_records_mode(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path)
    desc = _write_descriptor(tmp_path)
    code, out, err, _ = _run_bench(tmp_path, runs, desc, scenario)
    assert code == 0, f"exit {code}: {err}"
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    missing = [f for f in RECORD_FIELDS if f not in record]
    assert missing == [], f"missing section 7 fields: {missing}"
    assert record["mode"] == "docker"
    assert record["success_count"] == 1
    assert "runtime=docker" in record["notes"]
    assert f"docker_image=example/fixture-agent@{DIGEST}" in record["notes"]


def test_docker_pull_is_separate_phase_before_run(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path)
    desc = _write_descriptor(tmp_path)
    code, _, err, stub_log = _run_bench(tmp_path, runs, desc, scenario)
    assert code == 0, err
    lines = stub_log.read_text().splitlines()
    # Preload happens once, before the container run, never inside it
    assert lines[0].startswith("pull ")
    assert lines[1].startswith("run ")
    assert not [l for l in lines[2:] if l.startswith("pull ")]


def test_docker_run_flags_hardened_and_limited(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path)
    desc = _write_descriptor(tmp_path)
    code, _, err, stub_log = _run_bench(tmp_path, runs, desc, scenario)
    assert code == 0, err
    run_line = next(l for l in stub_log.read_text().splitlines() if l.startswith("run "))
    assert "--network=bridge" in run_line
    assert "--memory=64m" in run_line
    assert "--cpus=0.5" in run_line
    assert "--cap-drop=ALL" in run_line
    assert "privileged" not in run_line
    assert "docker.sock" not in run_line
    assert "host" not in run_line


def test_docker_descriptor_privileged_rejected(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path)
    desc = _write_descriptor(tmp_path, docker_args=["--privileged"])
    code, _, err, _ = _run_bench(tmp_path, runs, desc, scenario)
    assert code == 1
    assert "privileged" in err.lower()


def test_docker_descriptor_docker_sock_rejected(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path)
    desc = _write_descriptor(tmp_path, docker_args=["-v", "/var/run/docker.sock:/var/run/docker.sock"])
    code, _, err, _ = _run_bench(tmp_path, runs, desc, scenario)
    assert code == 1
    assert "docker.sock" in err.lower()


def test_docker_descriptor_not_digest_pinned_rejected(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path)
    desc = _write_descriptor(tmp_path, image="example/fixture-agent:latest")
    code, _, err, _ = _run_bench(tmp_path, runs, desc, scenario)
    assert code == 1
    assert "digest" in err.lower()


def test_docker_metrics_from_container_cgroup_fixture(tmp_path):
    runs = tmp_path / "runs"
    scenario = _write_scenario(tmp_path)
    desc = _write_descriptor(tmp_path)
    code, _, err, _ = _run_bench(tmp_path, runs, desc, scenario)
    assert code == 0, err
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    # Container cgroup metrics come from the scenario cgroup_path fixture:
    # memory.peak 20971520 bytes = 20 MiB, cpu.stat usage_usec 5000000 = 5 sec
    assert record["ram_peak_mb"] == 20.0
    assert record["cpu_sec"] == 5.0


def test_docker_container_pid_and_cgroup_resolved(tmp_path):
    """Without fixture overrides the harness asks docker for the container PID
    and reads the cgroup path from /proc/<pid>/cgroup (stub reports PID 1000)."""
    runs = tmp_path / "runs"
    scenario = tmp_path / "scenario_real.toml"
    scenario.write_text(
        'name = "scenario_a_cold_start"\n'
        'duration_sec = 2\n'
        'sample_interval_sec = 1\n'
        'repeats = 1\n'
    )
    desc = _write_descriptor(tmp_path)
    code, _, err, stub_log = _run_bench(
        tmp_path, runs, desc, scenario, extra_env={"DOCKER_STUB_PID": "1000"},
    )
    assert code == 0, err
    assert any(l.startswith("inspect ") for l in stub_log.read_text().splitlines())
    record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
    # Sampled from tests/fixtures/proc/1000: Pss 15360 kB = 15 MiB
    assert record["ram_pss_mb_median"] == 15.0
    # Cgroup read from /proc/1000/cgroup -> v2/agent: memory.peak = 20 MiB
    assert record["ram_peak_mb"] == 20.0
    assert record["cpu_sec"] == 5.0
    assert "cgroup_path=v2/agent" in record["notes"]
