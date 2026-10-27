"""Ticket #40: scenarios B-D must drive the candidate, not its mock.

The regression these tests lock: before the fix the harness posted every request
straight to the mock/provider while the candidate idled, so success and latency
described the harness's own calls. A fixture candidate now counts the requests
it actually served, and the mock exposes its own counter, so the two paths can
be told apart.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from bench import runner

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PROC_ROOT = FIXTURES / "proc"
SLEEPER = FIXTURES / "sleeper_agent.py"

from chat_agent_utils import free_port, requests_seen, write_chat_descriptor


def _scenario(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "scenario.toml"
    path.write_text(textwrap.dedent(body))
    return path


def _run(desc: Path, scenario: Path, runs: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, "-m", "bench", "run",
            str(desc), str(scenario),
            "--proc-root", str(PROC_ROOT),
            "--runs-dir", str(runs),
            "--mock-llm-port", "0",
        ],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )


def _record(runs: Path) -> dict:
    return json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())


B = """
    name = "scenario_b_mock_llm_controlled"
    requests = 5
    warmup_requests = 1
    repeats = 1
    mock_latency_ms = 0
"""


def test_scenario_b_requests_reach_the_candidate_not_the_mock(tmp_path):
    port = free_port()
    desc = write_chat_descriptor(tmp_path, port)
    scenario = _scenario(tmp_path, B)
    runs = tmp_path / "runs"
    proc = _run(desc, scenario, runs)
    assert proc.returncode == 0, proc.stderr
    record = _record(runs)
    assert record["success_count"] == 5
    assert record["error_count"] == 0
    # 5 measured + 1 warmup, served by the candidate itself.
    assert len(requests_seen(tmp_path / "wd")) == 6
    # The candidate did not proxy anywhere, so the harness must not have hit
    # the mock directly either: the mock counter stays at zero.
    assert "mock_requests=0" in record["notes"]


def test_request_scenario_without_chat_url_is_rejected_before_start(tmp_path):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    desc = tmp_path / "agent.toml"
    desc.write_text(textwrap.dedent(f"""
        name = "sleeper-fixture"
        repo_url = "https://example.com/sleeper"
        version = "0.0.1"
        mode = "native"
        start_command = ["python3", "{SLEEPER}", "{workdir}", "0.1"]
        workdir = "{workdir}"

        [healthcheck]
        type = "file"
        value = "{workdir / 'healthy'}"
        timeout_sec = 10
    """))
    runs = tmp_path / "runs"
    proc = _run(desc, _scenario(tmp_path, B), runs)
    assert proc.returncode == 1
    assert "chat_url" in proc.stderr
    assert not list(runs.glob("*/record.jsonl"))


def test_descriptor_env_points_the_candidate_at_the_mock(tmp_path):
    port = free_port()
    desc = write_chat_descriptor(tmp_path, port, upstream_via_env=True)
    scenario = _scenario(tmp_path, B.replace("requests = 5", "requests = 3").replace("warmup_requests = 1", "warmup_requests = 0"))
    runs = tmp_path / "runs"
    proc = _run(desc, scenario, runs)
    assert proc.returncode == 0, proc.stderr
    record = _record(runs)
    assert record["success_count"] == 3
    # The candidate forwarded each request to the mock resolved from {mock_url}.
    assert "mock_requests=3" in record["notes"]
    assert len(requests_seen(tmp_path / "wd")) == 3


def test_scenario_c_runs_each_task_through_the_candidate(tmp_path):
    port = free_port()
    desc = write_chat_descriptor(tmp_path, port)
    scenario = _scenario(tmp_path, """
        name = "scenario_c_real_llm_tasks"
        task_count = 2
        repeats_per_task = 2
        repeats = 1
        mock_latency_ms = 0
        llm_prompts = ["task one", "task two"]
    """)
    runs = tmp_path / "runs"
    proc = _run(desc, scenario, runs)
    assert proc.returncode == 0, proc.stderr
    record = _record(runs)
    assert record["success_count"] == 4
    seen = requests_seen(tmp_path / "wd")
    assert len(seen) == 4
    prompts = [s["body"]["messages"][0]["content"] for s in seen]
    assert prompts == ["task one", "task two", "task one", "task two"]


def test_env_placeholder_without_value_is_an_error():
    with pytest.raises(ValueError, match="mock_url"):
        runner._resolve_env(
            {"env": {"OPENAI_BASE_URL": "{mock_url}"}},
            {"name": "scenario_b_mock_llm_controlled"},
            None,
        )


def test_llm_api_key_placeholder_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("BENCH_TEST_KEY", "sekret")
    env = runner._resolve_env(
        {"env": {"OPENAI_API_KEY": "{llm_api_key}"}},
        {
            "name": "scenario_c_real_llm_tasks",
            "llm_api_key_env": "BENCH_TEST_KEY",
        },
        None,
    )
    assert env == {"OPENAI_API_KEY": "sekret"}


def test_docker_flags_carry_the_resolved_env():
    flags = runner._docker_run_flags(
        {"docker_memory_limit": "256m"},
        "abc12345",
        {"docker_args": []},
        {"OPENAI_BASE_URL": "http://127.0.0.1:1234/v1"},
    )
    assert "-e" in flags
    assert "OPENAI_BASE_URL=http://127.0.0.1:1234/v1" in flags
