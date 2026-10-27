"""Run command implementation: orchestrates agent start, sampling, and record writing."""

import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.request
import urllib.error

from bench.sanitize import sanitize_record, SANITIZER_NOTE
from bench.sampler import (
    read_pss_kb,
    read_rss_kb,
    read_mem_available_kb,
    read_meminfo_kb,
    kb_to_mb,
    read_memory_peak_bytes,
    read_cgroup_cpu_stat,
    read_cgroup_memory_events,
    read_cgroup_path_from_proc,
    bytes_to_mb,
    cpu_sec_from_cgroup,
)

# All fields from METHODOLOGY.md section 7 — never omit, use null for missing
RECORD_FIELDS = [
    "run_id",
    "agent",
    "repo_url",
    "version",
    "mode",
    "scenario",
    "host_profile",
    "started_at_utc",
    "duration_sec",
    "ram_pss_mb_median",
    "ram_peak_mb",
    "cpu_sec",
    "startup_ms",
    "latency_p50_ms",
    "latency_p95_ms",
    "success_count",
    "error_count",
    "oom_count",
    "notes",
    "config_ref",
]


def _empty_record() -> dict[str, Any]:
    return {f: None for f in RECORD_FIELDS}


def _load_toml(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _wait_for_healthcheck(
    hc_type: str,
    hc_value: str,
    timeout_s: float,
    interval_s: float = 0.1,
) -> bool:
    """Poll healthcheck until success or timeout. Returns True if healthy."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if hc_type == "tcp":
            host, port_str = hc_value.rsplit(":", 1)
            port = int(port_str)
            import socket
            try:
                with socket.create_connection((host, port), timeout=1.0):
                    return True
            except (OSError, ConnectionRefusedError):
                pass
        elif hc_type == "http":
            import urllib.request
            import urllib.error
            try:
                req = urllib.request.Request(hc_value, method="GET")
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    if resp.status == 200:
                        return True
            except (urllib.error.URLError, OSError, Exception):
                pass
        elif hc_type == "file":
            if Path(hc_value).exists():
                return True
        time.sleep(interval_s)
    return False


def _cleanup_workdir(workdir: str | Path) -> None:
    """Remove and recreate working directory between repeats."""
    p = Path(workdir)
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)


def _resolve_env(
    agent_desc: dict, scenario_def: dict, mock_port: int | None
) -> dict[str, str]:
    """Environment for the candidate process, with harness placeholders resolved.

    Ticket #40: the harness sends its requests to the candidate, so the candidate
    is what must talk to the mock (or the real provider). A descriptor declares
    the env vars its agent honours and the harness fills the addresses in, e.g.
    ``env = { OPENAI_BASE_URL = "{mock_base_url}" }``. That keeps the dynamically
    chosen mock port out of static agent configs.
    """
    raw = agent_desc.get("env") or {}
    if not isinstance(raw, dict):
        raise ValueError("descriptor 'env' must be a table")
    mock_base = f"http://127.0.0.1:{mock_port}/v1" if mock_port is not None else ""
    mock_url = f"{mock_base}/chat/completions" if mock_base else ""
    llm_url = str(scenario_def.get("llm_url") or scenario_def.get("mock_llm_url") or "")
    llm_base = (
        llm_url.rsplit("/chat/completions", 1)[0]
        if llm_url.endswith("/chat/completions")
        else llm_url
    )
    key_env = scenario_def.get("llm_api_key_env")
    values = {
        "mock_base_url": mock_base,
        "mock_url": mock_url,
        "llm_url": llm_url,
        "llm_base_url": llm_base,
        # Copied from the harness environment into the candidate's env only; it
        # is never written to a descriptor, scenario or record.
        "llm_api_key": os.environ.get(key_env, "") if key_env else "",
    }
    resolved: dict[str, str] = {}
    for key, value in raw.items():
        text = str(value)
        for name, replacement in values.items():
            token = "{" + name + "}"
            if token not in text:
                continue
            if not replacement:
                raise ValueError(
                    f"env {key} uses {token} but no value is available for it"
                )
            text = text.replace(token, replacement)
        resolved[str(key)] = text
    return resolved


def _agent_target(
    agent_desc: dict, scenario_def: dict, task_index: int | None = None
) -> tuple[str, bytes, dict[str, str]]:
    """The candidate's own chat endpoint, request body and headers (ticket #40).

    Scenarios B-D drive the candidate, not its LLM: the harness POSTs here and
    the candidate calls its configured upstream (the mock or the real provider).
    ``chat_url`` is required; ``chat_api_key_env`` optionally supplies a bearer
    token for the candidate's own API, read from the environment and never from
    a descriptor or record.
    """
    url = agent_desc.get("chat_url")
    if not url:
        raise ValueError(
            "descriptor has no 'chat_url': scenarios B-D need the candidate's "
            "chat endpoint, not its LLM endpoint"
        )
    prompts = scenario_def.get("llm_prompts") or []
    if prompts and task_index is not None:
        prompt = prompts[task_index % len(prompts)]
    else:
        prompt = scenario_def.get("llm_prompt", "Reply with OK.")
    body: dict[str, Any] = {
        "model": scenario_def.get("llm_model") or "bench-model",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": int(scenario_def.get("llm_max_tokens", 16)),
    }
    headers = {"Content-Type": "application/json"}
    key_env = agent_desc.get("chat_api_key_env")
    if key_env:
        key = os.environ.get(key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
    headers.update(agent_desc.get("chat_headers") or {})
    return str(url), json.dumps(body).encode(), headers


def _scenario_requires_chat(scenario_def: dict) -> bool:
    """True for scenarios that send requests to the candidate (B, C, D)."""
    name = str(scenario_def.get("name", "")).lower()
    return (
        "scenario_b" in name
        or "scenario_c" in name
        or "scenario_d" in name
        or scenario_def.get("requests") is not None
        or scenario_def.get("restart_after_requests") is not None
        or (
            scenario_def.get("task_count") is not None
            and scenario_def.get("repeats_per_task") is not None
        )
    )


def _validate_chat_descriptor(agent_desc: dict, scenario_def: dict) -> str | None:
    """Fail fast when a request scenario has no candidate endpoint (ticket #40)."""
    if not _scenario_requires_chat(scenario_def):
        return None
    chat_url = agent_desc.get("chat_url")
    if not chat_url:
        return (
            "descriptor has no 'chat_url': scenarios B-D send requests to the "
            "candidate, so it needs its chat endpoint"
        )
    if not str(chat_url).startswith(("http://", "https://")):
        return f"chat_url must be an http(s) URL, got {chat_url!r}"
    return None


def _docker_container_pid(docker_bin: str, name: str) -> int | None:
    """PID of a running container, asked from the docker daemon.

    In docker mode the harness's child is the docker CLI, not the agent, so
    sampling it would measure the client. The container name is deterministic
    (``bench-<run_id>``) and is set by the harness when composing ``docker run``.
    """
    try:
        out = subprocess.run(
            [docker_bin, "inspect", "--format", "{{.State.Pid}}", name],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    try:
        pid = int(out.stdout.strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def _cgroup_path_for(proc_root: str, pid: int, explicit: str | None) -> str:
    """Cgroup path for the sampled PID.

    An explicit path (scenario/descriptor, used by fixtures) wins. On a real
    host the path is read from ``/proc/<pid>/cgroup``: there is no fixed
    ``agent`` cgroup, so a hardcoded literal silently yields null peak/CPU/OOM.
    """
    if explicit:
        return explicit
    return read_cgroup_path_from_proc(proc_root, pid) or "agent"


def _sample_target(
    proc: subprocess.Popen,
    agent_desc: dict,
    proc_root: str,
    proc_pid_override: Any,
    explicit_cgroup_path: str | None = None,
) -> tuple[int, str]:
    """PID to sample and its cgroup path (fixture override wins, then docker)."""
    if proc_pid_override:
        pid = int(proc_pid_override)
    elif agent_desc.get("container_name"):
        pid = _docker_container_pid(
            agent_desc.get("docker_bin", "docker"), agent_desc["container_name"]
        ) or proc.pid
    else:
        pid = proc.pid
    return pid, _cgroup_path_for(proc_root, pid, explicit_cgroup_path)


def _percentile(data: list[float], p: float) -> float:
    """Linear-interpolated percentile of a sorted-able list, 0..100."""
    data_sorted = sorted(data)
    k = (len(data_sorted) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(data_sorted) - 1)
    if f == c:
        return data_sorted[int(k)]
    return data_sorted[f] * (c - k) + data_sorted[c] * (k - f)


# Guard exit codes (ticket #16, extended by #29): distinct codes so an AFK run can be
# triaged without a human. 0 ok, 1 usage/setup, 2 OOM, 3 MemAvailable, 4 health,
# 5 API budget, 6 candidate unavailable (install_failed: never launchable in this mode).
GUARD_EXIT_CODES = {
    "oom": 2,
    "memavailable": 3,
    "health": 4,
    "api_budget": 5,
    "unavailable": 6,
}


def _evaluate_guards(
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    cgroup_path: str,
) -> dict | None:
    """Return {"code", "reason"} when a configured guard threshold trips, else None.

    Thresholds come from the scenario TOML (ticket #16):
    guard_oom_threshold, guard_memavailable_min_mb. Health (4) and API budget (5)
    guards are evaluated at their call sites.
    """
    oom_threshold = scenario_def.get("guard_oom_threshold")
    if oom_threshold is not None:
        events = read_cgroup_memory_events(cgroup_root, cgroup_path) or {}
        oom = events.get("oom") or 0
        if oom >= int(oom_threshold):
            return {
                "code": GUARD_EXIT_CODES["oom"],
                "reason": f"oom_count={oom}>=guard_oom_threshold={oom_threshold}",
            }
    min_avail = scenario_def.get("guard_memavailable_min_mb")
    if min_avail is not None:
        avail_kb = read_mem_available_kb(proc_root)
        if avail_kb is not None:
            avail_mb = kb_to_mb(avail_kb)
            if avail_mb < float(min_avail):
                return {
                    "code": GUARD_EXIT_CODES["memavailable"],
                    "reason": (
                        f"memavailable_mb={avail_mb:.0f}<guard_memavailable_min_mb={min_avail}"
                    ),
                }
    return None


def _health_guard(reason: str = "healthcheck failed (limit reached)") -> dict:
    return {
        "code": GUARD_EXIT_CODES["health"],
        "reason": reason,
    }


def _unavailable_guard(reason: str) -> dict:
    """Guard 6: the candidate could not be launched in this mode (ticket #29).

    A missing binary, a bad interpreter or an unpullable image is an install
    failure, not a measurement: it is recorded, and the campaign moves on.
    """
    return {
        "code": GUARD_EXIT_CODES["unavailable"],
        "reason": f"install_failed={reason}",
    }


def _start_failure_guard(launch_error: str | None, attempts_used: int) -> dict:
    """Guard for a start that never became healthy (ticket #29).

    A launch error on the last attempt means the candidate could not be launched
    at all (install failure, code 6). A candidate that ran but never answered its
    healthcheck is a health failure (code 4) after `attempts_used` attempts.
    """
    if launch_error:
        return _unavailable_guard(launch_error)
    return _health_guard(
        reason=f"healthcheck failed after {attempts_used} start attempt(s)"
    )


def _start_process_with_attempts(
    start_cmd: Any,
    workdir: str,
    hc_type: str,
    hc_value: str,
    hc_timeout: float,
    attempts: int = 1,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Start the candidate and wait for its healthcheck, up to `attempts` times.

    Ticket #29: a candidate that does not come up gets three start attempts before
    its failure is recorded, and every failed attempt is stopped before the next
    one begins, so no half-dead process is measured or left behind. Returns the
    successful attempt's process and timings; when every attempt failed it returns
    "proc": None plus the last launch error (an OSError means the command could not
    even be executed: missing binary, wrong architecture, bad loader).
    """
    attempts = max(1, int(attempts))
    launch_error: str | None = None
    t_start = time.monotonic()
    started_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for attempt_idx in range(attempts):
        t_start = time.monotonic()
        started_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        # A file healthcheck from the previous process must not make a process
        # that has not started yet look healthy (found with scenario D restarts).
        _clear_health_signal(hc_type, hc_value)
        try:
            proc = subprocess.Popen(
                start_cmd,
                shell=isinstance(start_cmd, str),
                cwd=workdir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # Candidate env, e.g. the mock/provider base URL (ticket #40).
                env={**os.environ, **env} if env else None,
            )
        except OSError as exc:
            launch_error = f"{type(exc).__name__}: {exc}"
            continue
        launch_error = None
        healthy = _wait_for_healthcheck(hc_type, hc_value, hc_timeout)
        if healthy:
            return {
                "proc": proc,
                "pid": proc.pid,
                "healthy": True,
                "startup_ms": (time.monotonic() - t_start) * 1000.0,
                "started_at_utc": started_at_utc,
                "t_start": t_start,
                "attempts_used": attempt_idx + 1,
                "launch_error": None,
            }
        # Unhealthy attempt: stop it before the next one (no orphans, no leaks).
        _terminate_proc(proc)
    return {
        "proc": None,
        "pid": None,
        "healthy": False,
        "startup_ms": None,
        "started_at_utc": started_at_utc,
        "t_start": t_start,
        "attempts_used": attempts,
        "launch_error": launch_error,
    }


def _clear_health_signal(hc_type: str, hc_value: str) -> None:
    """Drop a stale file healthcheck before a (re)start."""
    if hc_type == "file" and hc_value:
        try:
            Path(hc_value).unlink()
        except OSError:
            pass


def _budget_guard(budget: int, issued: int) -> dict:
    return {
        "code": GUARD_EXIT_CODES["api_budget"],
        "reason": f"api_requests={issued}>=guard_api_request_budget={budget}",
    }


def _meminfo_mb(meminfo: dict[str, float], key: str) -> float | None:
    """A kB value from /proc/meminfo as MB, or None when the field is absent."""
    return kb_to_mb(meminfo[key]) if key in meminfo else None


def _prepare_candidate(
    agent_desc: dict, scenario_def: dict, proc_root: str, mock_port: int | None = None
) -> dict[str, Any]:
    """Resolve everything one repeat needs to start a candidate (ticket #36).

    Healthcheck parameters, absolute workdir, resolved start command, proc PID
    override and the RAM baseline. Before this helper the same block was copied
    into all four scenario runners, so every start-policy change had to be made
    four times (and the failure stubs had already drifted apart).
    """
    hc = agent_desc.get("healthcheck", {})
    hc_type = hc.get("type", "file")
    hc_value = hc.get("value", "")
    workdir = agent_desc.get("workdir", "/tmp/bench-agent-workdir")

    # Resolve relative paths against the harness cwd so descriptors are portable
    # and healthcheck files land where the agent writes them. The agent is started
    # from the workdir and receives workdir as an argument, so the healthcheck
    # path and the agent's own workdir argument must be the same absolute path.
    workdir_abs = str(Path(workdir).resolve())
    if hc_type == "file" and hc_value:
        hc_value = str(Path(hc_value).resolve())

    start_cmd = _resolve_start_cmd(agent_desc["start_command"], workdir, workdir_abs)

    # Fixture-only override: sample proc files under a fixed PID (e.g. a fixture
    # proc tree keyed to PID 1000) instead of the real child PID, so CLI tests can
    # assert on known values. Never set for real agents.
    proc_pid_override = scenario_def.get("proc_pid_override") or agent_desc.get("proc_pid_override")

    # Clean workdir before this repeat, then capture the RAM baseline
    _cleanup_workdir(workdir_abs)
    mem_avail_kb = read_mem_available_kb(proc_root)
    ram_baseline_mb = kb_to_mb(mem_avail_kb) if mem_avail_kb is not None else None

    # Ticket #40: the candidate must talk to the mock/provider, so its address
    # is resolved into the descriptor's declared env vars before the start.
    candidate_env = _resolve_env(agent_desc, scenario_def, mock_port)

    return {
        "hc_type": hc_type,
        "hc_value": hc_value,
        "hc_timeout": hc.get("timeout_sec", 30),
        "workdir": workdir,
        "workdir_abs": workdir_abs,
        "start_cmd": start_cmd,
        "proc_pid_override": proc_pid_override,
        "ram_baseline_mb": ram_baseline_mb,
        "env": candidate_env,
    }


def _start_candidate(prepared: dict, start_attempts: int) -> dict[str, Any]:
    """Start the candidate, stopping a process that never answered (ticket #29/#36).

    Failed attempts are already stopped inside `_start_process_with_attempts`; a
    process that came up but stayed unhealthy is stopped here too, so a repeat
    either measures a healthy process or records a failed start.
    """
    started = _start_process_with_attempts(
        prepared["start_cmd"],
        prepared["workdir"],
        prepared["hc_type"],
        prepared["hc_value"],
        prepared["hc_timeout"],
        start_attempts,
        env=prepared.get("env"),
    )
    if started["proc"] is not None and not started["healthy"]:
        _terminate_proc(started["proc"])
        started = {**started, "proc": None}
    return started


def _failed_start_result(
    repeat_idx: int,
    started: dict[str, Any],
    ram_baseline_mb: float | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Repeat result for a candidate that never came up (ticket #29/#36).

    `extra` carries the keys the owning scenario returns on success, so a failed
    start keeps the result shape of its scenario (the aggregate record and the
    report read those keys).
    """
    result: dict[str, Any] = {
        "repeat": repeat_idx,
        "startup_ms": None,
        "ram_pss_mb_median": None,
        "ram_peak_mb": None,
        "ram_baseline_mb": ram_baseline_mb,
        "duration_sec": 0.0,
        "started_at_utc": started["started_at_utc"],
        "success": False,
        "pss_samples": [],
        "rss_samples": [],
        "start_attempts_used": started["attempts_used"],
        "guard": _start_failure_guard(started["launch_error"], started["attempts_used"]),
    }
    if extra:
        result.update(extra)
    return result


def _run_single_repeat_scenario_a(
    agent_desc: dict,
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    repeat_idx: int,
    start_attempts: int = 1,
) -> dict[str, Any]:
    """Execute one repeat of scenario A (cold start / idle). Returns metrics dict."""
    # Cgroup path for agent; scenario/descriptor may define it for fixtures
    explicit_cgroup = scenario_def.get("cgroup_path") or agent_desc.get("cgroup_path")
    duration_s = scenario_def.get("duration_sec", 10)
    sample_interval = scenario_def.get("sample_interval_sec", 1)
    prepared = _prepare_candidate(agent_desc, scenario_def, proc_root)
    proc_pid_override = prepared["proc_pid_override"]
    ram_baseline_mb = prepared["ram_baseline_mb"]

    # Start process (ticket #29): up to start_attempts starts before the start is
    # recorded as failed; the process of the successful attempt is the measured one.
    started = _start_candidate(prepared, start_attempts)
    proc = started["proc"]
    t_start = started["t_start"]
    started_at_utc = started["started_at_utc"]
    healthy = started["healthy"]
    startup_ms = started["startup_ms"]
    if proc is None:
        # Never launched in this mode: install failure, nothing to measure.
        return _failed_start_result(
            repeat_idx, started, ram_baseline_mb,
            extra={"cpu_sec": None, "oom_count": None},
        )
    sample_pid, cgroup_path = _sample_target(
        proc, agent_desc, proc_root, proc_pid_override, explicit_cgroup
    )
    guard = None
    if not healthy:
        guard = _start_failure_guard(started["launch_error"], started["attempts_used"])

    # Sample PSS/RSS at 1-second intervals
    pss_samples: list[float] = []
    rss_samples: list[float] = []
    sample_deadline = t_start + duration_s

    while time.monotonic() < sample_deadline:
        if proc.poll() is not None:
            break
        pss = read_pss_kb(proc_root, sample_pid)
        rss = read_rss_kb(proc_root, sample_pid)
        if pss is not None:
            pss_samples.append(kb_to_mb(pss))
        if rss is not None:
            rss_samples.append(kb_to_mb(rss))
        loop_guard = _evaluate_guards(scenario_def, proc_root, cgroup_root, cgroup_path)
        if loop_guard:
            guard = loop_guard
            break
        time.sleep(sample_interval)

    t_end = time.monotonic()
    duration_actual = t_end - t_start

    # Terminate agent
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    # Compute metrics
    pss_median = statistics.median(pss_samples) if pss_samples else None
    rss_peak = max(rss_samples) if rss_samples else None

    # Service RAM peak via cgroup memory.peak (full stack)
    mem_peak_bytes = read_memory_peak_bytes(cgroup_root, cgroup_path)
    mem_peak_mb = bytes_to_mb(mem_peak_bytes) if mem_peak_bytes is not None else None

    # Prefer cgroup peak over proc RSS peak
    ram_peak = mem_peak_mb
    if ram_peak is None:
        ram_peak = max((pss_median or 0), (rss_peak or 0)) or None

    # CPU seconds from cgroup
    cpu_stat = read_cgroup_cpu_stat(cgroup_root, cgroup_path)
    cpu_sec = cpu_sec_from_cgroup(cpu_stat)

    # OOM counters from cgroup memory.events
    mem_events = read_cgroup_memory_events(cgroup_root, cgroup_path)
    oom_count = mem_events.get("oom") if mem_events else None

    return {
        "repeat": repeat_idx,
        "startup_ms": startup_ms,
        "ram_pss_mb_median": pss_median,
        "ram_peak_mb": ram_peak,
        "ram_baseline_mb": ram_baseline_mb,
        "duration_sec": round(duration_actual, 3),
        "started_at_utc": started_at_utc,
        "success": healthy,
        "pss_samples": pss_samples,
        "rss_samples": rss_samples,
        "cpu_sec": cpu_sec,
        "oom_count": oom_count,
        "cgroup_mem_peak_mb": mem_peak_mb,
        "cgroup_path": cgroup_path,
        "start_attempts_used": started["attempts_used"],
        "guard": guard,
    }


def _run_single_repeat_scenario_b(
    agent_desc: dict,
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    repeat_idx: int,
    mock_port: int | None,
    start_attempts: int = 1,
) -> dict[str, Any]:
    """Execute one repeat of scenario B: controlled requests through the candidate.

    Ticket #40: the requests go to the candidate's ``chat_url`` and the candidate
    calls its configured upstream (mock server when one is up). Before the fix the
    harness called the mock directly and the candidate only idled.
    """
    duration_s = 0
    sample_interval = 1
    prepared = _prepare_candidate(agent_desc, scenario_def, proc_root, mock_port)
    proc_pid_override = prepared["proc_pid_override"]
    ram_baseline_mb = prepared["ram_baseline_mb"]

    # Start process (ticket #29): up to start_attempts starts before the failure.
    started = _start_candidate(prepared, start_attempts)
    proc = started["proc"]
    t_start = started["t_start"]
    started_at_utc = started["started_at_utc"]
    healthy = started["healthy"]
    if proc is None:
        return _failed_start_result(
            repeat_idx, started, ram_baseline_mb,
            extra={
                "latencies_ms": [], "success_count": 0, "error_count": 0,
                "tool_cycles": None,
            },
        )

    startup_ms = started["startup_ms"]
    sample_pid, _cgroup = _sample_target(
        proc, agent_desc, proc_root, proc_pid_override,
        scenario_def.get("cgroup_path") or agent_desc.get("cgroup_path"),
    )

    # Sampling during requests (scenario B measures during execution)
    pss_samples: list[float] = []
    rss_samples: list[float] = []

    # Scenario B parameters
    warmup = int(scenario_def.get("warmup_requests", 5))
    total_requests = int(scenario_def.get("requests", 30))
    latency_p50_ms = None
    latency_p95_ms = None
    success_count = 0
    error_count = 0
    latencies_ms: list[float] = []

    agent_url, request_payload, request_headers = _agent_target(agent_desc, scenario_def)
    request_timeout = float(scenario_def.get("request_timeout_sec", 5.0))

    # Tool cycles flag
    tool_cycles_flag = scenario_def.get("tool_cycles")
    tool_cycles_executed = None

    # API budget guard (ticket #16): counted (non-warmup) requests cap
    api_budget = scenario_def.get("guard_api_request_budget")
    guard = None

    # Simple request loop via urllib (fixture agents will be the process, we simulate latency by querying mock)
    for i in range(warmup + total_requests):
        if proc.poll() is not None:
            guard = _health_guard()
            break
        sample_start = time.monotonic()
        # Poll memory sample during warmup/requests
        pss = read_pss_kb(proc_root, sample_pid)
        rss = read_rss_kb(proc_root, sample_pid)
        if pss is not None:
            pss_samples.append(kb_to_mb(pss))
        if rss is not None:
            rss_samples.append(kb_to_mb(rss))

        try:
            req = urllib.request.Request(
                agent_url, method="POST", data=request_payload, headers=request_headers
            )
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                _ = resp.read()
                ok = resp.status == 200
        except Exception:
            ok = False

        elapsed_ms = (time.monotonic() - sample_start) * 1000.0

        if i >= warmup:
            latencies_ms.append(elapsed_ms)
            if ok:
                success_count += 1
            else:
                error_count += 1
            if api_budget is not None and success_count + error_count >= int(api_budget):
                guard = _budget_guard(int(api_budget), success_count + error_count)
                break
        else:
            # Warmup: don't count, but still track
            pass

        # Small pause to avoid hammering
        time.sleep(0.01)

    # Compute latency percentiles
    if latencies_ms:
        latency_p50_ms = float(_percentile(latencies_ms, 50))
        latency_p95_ms = float(_percentile(latencies_ms, 95))

    t_end = time.monotonic()
    duration_actual = t_end - t_start

    # Tool cycles
    if tool_cycles_flag is not None:
        # If scenario defines tool_cycles, note it as N/A for fixture;
        # real implementation would invoke agent and count cycles.
        tool_cycles_executed = None
    else:
        tool_cycles_executed = None

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    pss_median = statistics.median(pss_samples) if pss_samples else None
    rss_peak = max(rss_samples) if rss_samples else None
    ram_peak = max((pss_median or 0), (rss_peak or 0)) or None

    return {
        "repeat": repeat_idx,
        "startup_ms": startup_ms,
        "ram_pss_mb_median": pss_median,
        "ram_peak_mb": ram_peak,
        "ram_baseline_mb": ram_baseline_mb,
        "duration_sec": round(duration_actual, 3),
        "started_at_utc": started_at_utc,
        "success": healthy,
        "pss_samples": pss_samples,
        "rss_samples": rss_samples,
        "latencies_ms": latencies_ms,
        "latency_p50_ms": latency_p50_ms,
        "latency_p95_ms": latency_p95_ms,
        "success_count": success_count,
        "error_count": error_count,
        "tool_cycles": tool_cycles_executed,
        "start_attempts_used": started["attempts_used"],
        "guard": guard,
    }


def _resolve_start_cmd(start_cmd: Any, workdir: str, workdir_abs: str) -> Any:
    """Resolve the script path and workdir argument to absolute paths (list commands only)."""
    if not isinstance(start_cmd, list):
        return start_cmd
    cmd_cwd = Path.cwd()
    resolved_cmd: list[str] = []
    for part in start_cmd:
        if part == workdir:
            resolved_cmd.append(workdir_abs)
        else:
            cand = cmd_cwd / part
            resolved_cmd.append(str(cand) if cand.exists() else part)
    return resolved_cmd


def _run_single_repeat_scenario_c(
    agent_desc: dict,
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    repeat_idx: int,
    mock_port: int | None,
    start_attempts: int = 1,
) -> dict[str, Any]:
    """Execute one repeat of scenario C: the candidate performs the tasks.

    Ticket #40: every task request goes to the candidate's chat endpoint; the
    candidate talks to the mock or the real provider. Without a candidate
    endpoint the run is rejected before it starts (see `_validate_chat_descriptor`).
    The harness measures request success and latency; answer and artefact
    correctness stay out of scope (METHODOLOGY §3 C, scenario comments).
    """
    task_count = int(scenario_def.get("task_count", 0))
    repeats_per_task = int(scenario_def.get("repeats_per_task", 0))
    total_tasks = task_count * repeats_per_task

    prepared = _prepare_candidate(agent_desc, scenario_def, proc_root, mock_port)
    proc_pid_override = prepared["proc_pid_override"]
    ram_baseline_mb = prepared["ram_baseline_mb"]

    # Start process (ticket #29): up to start_attempts starts before the failure.
    started = _start_candidate(prepared, start_attempts)
    proc = started["proc"]
    t_start = started["t_start"]
    started_at_utc = started["started_at_utc"]
    healthy = started["healthy"]
    if proc is None:
        return _failed_start_result(
            repeat_idx, started, ram_baseline_mb,
            extra={
                "latencies_ms": [], "latency_p50_ms": None, "latency_p95_ms": None,
                "success_count": 0, "error_count": 0,
                "unfinished_processes": total_tasks,
            },
        )

    startup_ms = started["startup_ms"]
    sample_pid = int(proc_pid_override) if proc_pid_override else proc.pid
    sample_pid, _cgroup = _sample_target(
        proc, agent_desc, proc_root, proc_pid_override,
        scenario_def.get("cgroup_path") or agent_desc.get("cgroup_path"),
    )

    pss_samples: list[float] = []
    rss_samples: list[float] = []
    latencies_ms: list[float] = []
    success_count = 0
    error_count = 0
    api_budget = scenario_def.get("guard_api_request_budget")
    guard = None

    request_timeout = float(scenario_def.get("request_timeout_sec", 5.0))
    for task in range(total_tasks):
        if proc.poll() is not None:
            guard = _health_guard()
            break
        agent_url, task_payload, task_headers = _agent_target(agent_desc, scenario_def, task)
        pss = read_pss_kb(proc_root, sample_pid)
        rss = read_rss_kb(proc_root, sample_pid)
        if pss is not None:
            pss_samples.append(kb_to_mb(pss))
        if rss is not None:
            rss_samples.append(kb_to_mb(rss))

        req_start = time.monotonic()
        try:
            req = urllib.request.Request(
                agent_url, method="POST", data=task_payload,
                headers=task_headers,
            )
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                _ = resp.read()
                ok = resp.status == 200
        except Exception:
            ok = False
        latencies_ms.append((time.monotonic() - req_start) * 1000.0)
        if ok:
            success_count += 1
        else:
            error_count += 1
        if api_budget is not None and success_count + error_count >= int(api_budget):
            guard = _budget_guard(int(api_budget), success_count + error_count)
            break
        time.sleep(0.01)

    unfinished = total_tasks - success_count

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    duration_actual = time.monotonic() - t_start
    pss_median = statistics.median(pss_samples) if pss_samples else None
    rss_peak = max(rss_samples) if rss_samples else None
    ram_peak = max((pss_median or 0), (rss_peak or 0)) or None
    latency_p50_ms = float(_percentile(latencies_ms, 50)) if latencies_ms else None
    latency_p95_ms = float(_percentile(latencies_ms, 95)) if latencies_ms else None

    return {
        "repeat": repeat_idx,
        "startup_ms": startup_ms,
        "ram_pss_mb_median": pss_median,
        "ram_peak_mb": ram_peak,
        "ram_baseline_mb": ram_baseline_mb,
        "duration_sec": round(duration_actual, 3),
        "started_at_utc": started_at_utc,
        "success": healthy,
        "pss_samples": pss_samples,
        "rss_samples": rss_samples,
        "latencies_ms": latencies_ms,
        "latency_p50_ms": latency_p50_ms,
        "latency_p95_ms": latency_p95_ms,
        "success_count": success_count,
        "error_count": error_count,
        "unfinished_processes": unfinished,
        "start_attempts_used": started["attempts_used"],
        "guard": guard,
    }


def _child_pids(pid: int) -> list[int]:
    """Direct children of pid via `ps` (works on macOS and Linux)."""
    try:
        out = subprocess.run(
            ["ps", "-ax", "-o", "pid=,ppid="],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []
    children: list[int] = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) == pid:
            children.append(int(parts[0]))
    return children


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _terminate_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _run_single_repeat_scenario_d(
    agent_desc: dict,
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    repeat_idx: int,
    mock_port: int | None,
    start_attempts: int = 1,
) -> dict[str, Any]:
    """Execute one repeat of scenario D: stability and recovery (ticket #15).

    - 100 (configurable) sequential mock requests with a small pause: success/error
      counts and RSS growth over the series (leak indicator);
    - agent restart mid-series with test-state preservation check;
    - error injection (429/500/timeout via mock modes) is recorded, no retries
      are issued by the harness, timeouts bounded by request_timeout_sec.
    """
    total_requests = int(scenario_def.get("requests", 100))
    pause_ms = float(scenario_def.get("pause_between_ms", 10))
    restart_after = scenario_def.get("restart_after_requests")
    test_state_file = scenario_def.get("test_state_file")
    rss_leak_threshold_mb = float(scenario_def.get("rss_growth_threshold_mb", 1.0))
    request_timeout = float(scenario_def.get("request_timeout_sec", 5.0))
    api_budget = scenario_def.get("guard_api_request_budget")

    prepared = _prepare_candidate(agent_desc, scenario_def, proc_root, mock_port)
    workdir = prepared["workdir"]
    workdir_abs = prepared["workdir_abs"]
    start_cmd = prepared["start_cmd"]
    hc_type = prepared["hc_type"]
    hc_value = prepared["hc_value"]
    hc_timeout = prepared["hc_timeout"]
    proc_pid_override = prepared["proc_pid_override"]
    ram_baseline_mb = prepared["ram_baseline_mb"]

    # Start process (ticket #29): up to start_attempts starts before the failure.
    started = _start_candidate(prepared, start_attempts)
    proc = started["proc"]
    t_start = started["t_start"]
    started_at_utc = started["started_at_utc"]
    healthy = started["healthy"]
    if proc is None:
        return _failed_start_result(
            repeat_idx, started, ram_baseline_mb,
            extra={
                "latencies_ms": [], "latency_p50_ms": None, "latency_p95_ms": None,
                "success_count": 0, "error_count": 0,
                "unfinished_processes": 0, "extra_notes": [],
            },
        )

    startup_ms = started["startup_ms"]
    sample_pid = int(proc_pid_override) if proc_pid_override else proc.pid
    sample_pid, _cgroup = _sample_target(
        proc, agent_desc, proc_root, proc_pid_override,
        scenario_def.get("cgroup_path") or agent_desc.get("cgroup_path"),
    )

    rss_start_kb = read_rss_kb(proc_root, sample_pid)
    success_count = 0
    error_count = 0
    latencies_ms: list[float] = []
    restart_state: str | None = None
    guard = None
    # Children spawned by any agent instance of this repeat; a child orphaned
    # by the mid-series restart is just as unfinished as one left at the end.
    seen_children: set[int] = set()

    # Ticket #40: the series is driven through the candidate, so injected
    # upstream errors (429/500/timeout) reach the candidate and its handling
    # is what gets recorded.
    agent_url, request_payload, request_headers = _agent_target(agent_desc, scenario_def)

    for i in range(total_requests):
        if proc.poll() is not None:
            guard = _health_guard()
            break
        req_start = time.monotonic()
        ok = False
        try:
            req = urllib.request.Request(
                agent_url, method="POST", data=request_payload,
                headers=request_headers,
            )
            with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                _ = resp.read()
                ok = resp.status == 200
        except Exception:
            ok = False
        latencies_ms.append((time.monotonic() - req_start) * 1000.0)
        if ok:
            success_count += 1
        else:
            error_count += 1

        # API budget guard (ticket #16 semantics apply to D too)
        if api_budget is not None and success_count + error_count >= int(api_budget):
            guard = _budget_guard(int(api_budget), success_count + error_count)
            break

        # Mid-series restart with test-state preservation check (ticket #15)
        if restart_after is not None and (i + 1) == int(restart_after) and test_state_file:
            state_path = Path(workdir_abs) / test_state_file
            state_before = None
            if state_path.exists():
                try:
                    state_before = json.loads(state_path.read_text())
                except Exception:
                    state_before = None
            seen_children.update(_child_pids(proc.pid))
            _terminate_proc(proc)
            _clear_health_signal(hc_type, hc_value)
            proc = subprocess.Popen(
                start_cmd,
                shell=isinstance(start_cmd, str),
                cwd=workdir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=(
                    {**os.environ, **prepared["env"]}
                    if prepared.get("env")
                    else None
                ),
            )
            healthy_again = _wait_for_healthcheck(hc_type, hc_value, hc_timeout)
            restart_state = "lost"
            if healthy_again and state_path.exists():
                try:
                    state_after = json.loads(state_path.read_text())
                    # start_time is loaded from the existing file by the fixture,
                    # so equality means the state survived the restart
                    if state_before is None or state_after.get("start_time") == state_before.get("start_time"):
                        restart_state = "preserved"
                except Exception:
                    restart_state = "lost"
            if not healthy_again:
                guard = _health_guard()
                break

        time.sleep(pause_ms / 1000.0)

    rss_end_kb = read_rss_kb(proc_root, sample_pid)
    rss_growth_mb = None
    if rss_start_kb is not None and rss_end_kb is not None:
        rss_growth_mb = round(kb_to_mb(rss_end_kb) - kb_to_mb(rss_start_kb), 3)

    # Detect unfinished (orphaned) child processes: alive while an agent
    # instance ran, still alive after the last agent was terminated.
    seen_children.update(_child_pids(proc.pid))
    _terminate_proc(proc)
    unfinished_pids = sorted(p for p in seen_children if _pid_alive(p))
    # Hygiene for real runs: don't leave hung children behind
    for p in unfinished_pids:
        try:
            os.kill(p, 9)
        except OSError:
            pass

    duration_actual = time.monotonic() - t_start
    latency_p50_ms = float(_percentile(latencies_ms, 50)) if latencies_ms else None
    latency_p95_ms = float(_percentile(latencies_ms, 95)) if latencies_ms else None

    extra_notes: list[str] = []
    if rss_growth_mb is not None:
        extra_notes.append(f"rss_growth_mb={rss_growth_mb}")
        extra_notes.append(f"rss_leak={'true' if rss_growth_mb > rss_leak_threshold_mb else 'false'}")
    if restart_state is not None:
        extra_notes.append(f"restart_state={restart_state}")
    extra_notes.append(f"mock_error_mode={scenario_def.get('mock_error_mode')}")
    extra_notes.append(f"unfinished_processes={len(unfinished_pids)}")
    if unfinished_pids:
        extra_notes.append("unfinished_pids=" + ",".join(str(p) for p in unfinished_pids))

    return {
        "repeat": repeat_idx,
        "startup_ms": startup_ms,
        "ram_pss_mb_median": None,
        "ram_peak_mb": None,
        "ram_baseline_mb": ram_baseline_mb,
        "duration_sec": round(duration_actual, 3),
        "started_at_utc": started_at_utc,
        "success": guard is None,
        "pss_samples": [],
        "rss_samples": [],
        "latencies_ms": latencies_ms,
        "latency_p50_ms": latency_p50_ms,
        "latency_p95_ms": latency_p95_ms,
        "success_count": success_count,
        "error_count": error_count,
        "unfinished_processes": len(unfinished_pids),
        "extra_notes": extra_notes,
        "start_attempts_used": started["attempts_used"],
        "guard": guard,
    }


def _run_single_repeat(
    agent_desc: dict,
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    repeat_idx: int,
    mock_port: int | None,
    start_attempts: int = 1,
) -> dict[str, Any]:
    """Execute one repeat, dispatching to B, C, D or A based on scenario definition."""
    scenario_name = scenario_def.get("name", "")
    # Scenario D: stability/recovery is identified before B (it also has "requests")
    if "scenario_d" in scenario_name.lower() or scenario_def.get("restart_after_requests"):
        return _run_single_repeat_scenario_d(
            agent_desc, scenario_def, proc_root, cgroup_root, repeat_idx, mock_port,
            start_attempts,
        )
    if "scenario_b" in scenario_name.lower() or scenario_def.get("requests"):
        return _run_single_repeat_scenario_b(
            agent_desc, scenario_def, proc_root, cgroup_root, repeat_idx, mock_port,
            start_attempts,
        )
    # Scenario C is identified by task_count + repeats_per_task (ticket #14)
    if scenario_def.get("task_count") is not None and scenario_def.get("repeats_per_task") is not None:
        return _run_single_repeat_scenario_c(
            agent_desc, scenario_def, proc_root, cgroup_root, repeat_idx, mock_port,
            start_attempts,
        )
    return _run_single_repeat_scenario_a(
        agent_desc, scenario_def, proc_root, cgroup_root, repeat_idx, start_attempts
    )


def _build_run_plan(
    agent_path: Path,
    scenario_path: Path,
    agent_desc: dict,
    scenario_def: dict,
    args: Any,
) -> dict:
    """Execution plan for --dry-run: everything that would run, nothing executed."""
    plan = {
        "dry_run": True,
        "agent": agent_desc.get("name", agent_path.stem),
        "agent_descriptor": str(agent_path),
        "mode": agent_desc.get("mode", None),
        "start_command": agent_desc.get("start_command"),
        "workdir": agent_desc.get("workdir"),
        "healthcheck": agent_desc.get("healthcheck"),
        "chat_url": agent_desc.get("chat_url"),
        "agent_env": _resolve_env(
            agent_desc, scenario_def, getattr(args, "mock_llm_port", None)
        ),
        "scenario": scenario_def.get("name", scenario_path.stem),
        "scenario_definition": str(scenario_path),
        "repeats": scenario_def.get("repeats", 3),
        "start_attempts": _resolve_start_attempts(agent_desc, scenario_def, args),
        "requests": scenario_def.get("requests"),
        "warmup_requests": scenario_def.get("warmup_requests"),
        "task_count": scenario_def.get("task_count"),
        "repeats_per_task": scenario_def.get("repeats_per_task"),
        "mock_llm": {
            "requested": getattr(args, "mock_llm_port", None) is not None,
            "port": getattr(args, "mock_llm_port", None),
            "latency_ms": scenario_def.get("mock_latency_ms"),
            "error_mode": scenario_def.get("mock_error_mode"),
        },
        "guards": {
            "oom_threshold": scenario_def.get("guard_oom_threshold"),
            "memavailable_min_mb": scenario_def.get("guard_memavailable_min_mb"),
            "api_request_budget": scenario_def.get("guard_api_request_budget"),
        },
        "proc_root": args.proc_root,
        "cgroup_root": args.cgroup_root,
        "runs_dir": str(args.runs_dir),
        "docker_bin": getattr(args, "docker_bin", None),
        "docker_image": agent_desc.get("image") if agent_desc.get("mode") == "docker" else None,
        "docker_memory_limit": scenario_def.get("docker_memory_limit"),
        "docker_cpu_limit": scenario_def.get("docker_cpu_limit"),
    }
    return plan


def _validate_docker_descriptor(agent_desc: dict) -> str | None:
    """Validate a mode=docker descriptor (ticket #20). None when OK / not docker."""
    if agent_desc.get("mode") != "docker":
        return None
    image = agent_desc.get("image")
    if not image:
        return "docker descriptor requires 'image'"
    if "@sha256:" not in str(image):
        return "docker image must be digest-pinned (repo@sha256:digest)"
    for a in agent_desc.get("docker_args", []) or []:
        if "--privileged" in str(a):
            return "privileged containers are not allowed"
        if "docker.sock" in str(a):
            return "mounting docker.sock is not allowed"
        if str(a) in ("--network", "--net"):
            return "use --network=<value> form; host network is not allowed"
        if str(a) in ("--network=host", "--net=host"):
            return "host network is not allowed"
    return None


def _docker_run_flags(
    scenario_def: dict,
    run_id: str,
    agent_desc: dict,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Uniform, hardened docker run flags (identical limits for all candidates).

    ``env`` carries the address of the mock/provider into the container (ticket
    #40); it is resolved by the harness and never contains a secret read from a
    descriptor.
    """
    flags = [
        "--rm",
        f"--name=bench-{run_id}",
        "--network=bridge",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=256",
    ]
    mem = scenario_def.get("docker_memory_limit")
    if mem:
        flags.append(f"--memory={mem}")
    cpus = scenario_def.get("docker_cpu_limit")
    if cpus:
        flags.append(f"--cpus={cpus}")
    for key, value in (env or {}).items():
        flags.extend(["-e", f"{key}={value}"])
    flags.extend(agent_desc.get("docker_args", []) or [])
    return flags


def _resolve_start_attempts(agent_desc: dict, scenario_def: dict, args: Any) -> int:
    """Start attempts for one run (ticket #29): scenario, then descriptor, then CLI."""
    raw = (
        scenario_def.get("start_attempts")
        or agent_desc.get("start_attempts")
        or getattr(args, "start_attempts", None)
        or 3
    )
    return max(1, int(raw))


def _write_unavailable_record(
    run_dir: Path,
    run_id: str,
    agent_path: Path,
    agent_desc: dict,
    scenario_def: dict,
    scenario_path: Path,
    reason: str,
) -> dict:
    """Record a candidate that could not be installed in this mode (ticket #29).

    An unavailable mode is written as an install failure instead of being skipped
    silently, so the report keeps its row and the campaign can tell "we ran it and
    it failed" from "we never tried it".
    """
    record = _empty_record()
    record["run_id"] = run_id
    record["agent"] = agent_desc.get("name", agent_path.stem)
    record["repo_url"] = agent_desc.get("repo_url")
    record["version"] = agent_desc.get("version")
    record["mode"] = agent_desc.get("mode")
    record["scenario"] = scenario_def.get("name", scenario_path.stem)
    record["started_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    record["duration_sec"] = 0.0
    record["success_count"] = 0
    record["error_count"] = 0
    record["oom_count"] = 0
    notes = [f"install_failed={reason}"]
    if agent_desc.get("mode") == "docker":
        notes.append("runtime=docker")
        notes.append(f"docker_image={agent_desc.get('image')}")
    record["notes"] = ", ".join(notes)
    record["config_ref"] = str(scenario_path)
    record, redacted = sanitize_record(record)
    if redacted:
        record["notes"] = ", ".join(filter(None, [record["notes"], SANITIZER_NOTE]))
    with open(run_dir / "record.jsonl", "w") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def cmd_run(args: Any) -> int:
    """Execute the 'run' subcommand."""
    agent_path = Path(args.agent)
    scenario_path = Path(args.scenario)

    if not agent_path.exists():
        print(f"Error: agent descriptor not found: {agent_path}", file=sys.stderr)
        return 1
    if not scenario_path.exists():
        print(f"Error: scenario definition not found: {scenario_path}", file=sys.stderr)
        return 1

    agent_desc = _load_toml(agent_path)
    scenario_def = _load_toml(scenario_path)
    # Ticket #29: how many times a start may be attempted before the failure is
    # recorded (scenario/descriptor override the CLI default of three).
    start_attempts = _resolve_start_attempts(agent_desc, scenario_def, args)

    docker_error = _validate_docker_descriptor(agent_desc)
    if docker_error:
        print(f"Error: {docker_error}", file=sys.stderr)
        return 1

    # Ticket #40: B-D drive the candidate, so a descriptor without its own chat
    # endpoint is rejected before anything is started or written.
    chat_error = _validate_chat_descriptor(agent_desc, scenario_def)
    if chat_error:
        print(f"Error: {chat_error}", file=sys.stderr)
        return 1

    # Dry-run (ticket #16): print the plan, spawn nothing, write nothing.
    if getattr(args, "dry_run", False):
        print(json.dumps(_build_run_plan(agent_path, scenario_path, agent_desc, scenario_def, args), indent=2))
        return 0

    proc_root = args.proc_root
    cgroup_root = args.cgroup_root
    runs_dir = Path(args.runs_dir)
    mock_port_arg = getattr(args, "mock_llm_port", None)

    run_id = str(uuid.uuid4())[:8]
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Start mock LLM server if requested (port 0 = OS-assigned)
    mock_server = None
    mock_port_num = None
    if mock_port_arg is not None:
        from bench.mock.server import MockLLMServer, MockConfig
        latency_ms = int(scenario_def.get("mock_latency_ms", 50))
        error_mode = scenario_def.get("mock_error_mode")
        cfg = MockConfig(
            latency_ms=latency_ms,
            error_mode=error_mode,
            error_on_call=scenario_def.get("error_on_call"),
            # Ticket #38: how long a "timeout" injection hangs the targeted call.
            timeout_sleep_sec=float(scenario_def.get("mock_timeout_sleep_sec", 10.0)),
        )
        mock_server = MockLLMServer(port=mock_port_arg, config=cfg)
        mock_port_num = mock_server.start()

    try:
        # Docker mode (ticket #20): image preload is a separate phase before
        # timing, so it never enters startup_ms; the container command is the
        # descriptor's start_command appended after the digest-pinned image.
        docker_image = None
        if agent_desc.get("mode") == "docker":
            docker_bin = getattr(args, "docker_bin", "docker")
            docker_image = agent_desc["image"]
            pull = subprocess.run(
                [docker_bin, "pull", docker_image],
                capture_output=True, text=True, timeout=600,
            )
            if pull.returncode != 0:
                # Ticket #29: an unpullable image is an install failure for this
                # mode. It is recorded, not skipped, and the campaign moves on.
                cause = pull.stderr.strip() or f"docker pull exit {pull.returncode}"
                print(f"Error: install_failed: docker pull failed for {docker_image}: {cause}", file=sys.stderr)
                _write_unavailable_record(
                    run_dir=run_dir,
                    run_id=run_id,
                    agent_path=agent_path,
                    agent_desc=agent_desc,
                    scenario_def=scenario_def,
                    scenario_path=scenario_path,
                    reason=f"docker_pull_failed: {cause}",
                )
                print(json.dumps({
                    "run_id": run_id,
                    "status": "unavailable",
                    "guard": _unavailable_guard(cause),
                    "record_path": str(run_dir / "record.jsonl"),
                }, indent=2))
                return GUARD_EXIT_CODES["unavailable"]
            container_env = _resolve_env(agent_desc, scenario_def, mock_port_num)
            run_flags = _docker_run_flags(scenario_def, run_id, agent_desc, container_env)
            agent_desc = {
                **agent_desc,
                "container_name": f"bench-{run_id}",
                "docker_bin": docker_bin,
                "start_command": [docker_bin, "run", *run_flags, docker_image, *agent_desc["start_command"]],
            }

        num_repeats = scenario_def.get("repeats", 3)
        scenario_name = scenario_def.get("name", scenario_path.stem)

        repeat_results: list[dict] = []
        aborted_guard = None
        for i in range(num_repeats):
            result = _run_single_repeat(
                agent_desc=agent_desc,
                scenario_def=scenario_def,
                proc_root=proc_root,
                cgroup_root=cgroup_root,
                repeat_idx=i,
                mock_port=mock_port_num,
                start_attempts=start_attempts,
            )
            repeat_results.append(result)
            if result.get("guard"):
                # Guard trip (ticket #16): stop the run, keep collected records
                aborted_guard = result["guard"]
                break

        # Build summary
        startup_values = [r["startup_ms"] for r in repeat_results if r["startup_ms"] is not None]
        pss_values = [r["ram_pss_mb_median"] for r in repeat_results if r["ram_pss_mb_median"] is not None]
        latency_p50_vals = [r.get("latency_p50_ms") for r in repeat_results if r.get("latency_p50_ms") is not None]
        latency_p95_vals = [r.get("latency_p95_ms") for r in repeat_results if r.get("latency_p95_ms") is not None]

        startup_variance = statistics.variance(startup_values) if len(startup_values) >= 2 else None
        pss_variance = statistics.variance(pss_values) if len(pss_values) >= 2 else None

        primary = repeat_results[-1]
        for r in repeat_results:
            if r["success"]:
                primary = r
                break

        baseline_mb = repeat_results[0]["ram_baseline_mb"]

        # Aggregate success/error counts across repeats for scenario B
        total_success = sum(r.get("success_count", 0) for r in repeat_results)
        total_errors = sum(r.get("error_count", 0) for r in repeat_results)
        # For scenario A (no latency fields), success_count is per repeat health
        if not latency_p50_vals:
            total_success = sum(1 for r in repeat_results if r["success"])
            total_errors = sum(1 for r in repeat_results if not r["success"])

        record = _empty_record()
        record["run_id"] = run_id
        record["agent"] = agent_desc.get("name", agent_path.stem)
        record["repo_url"] = agent_desc.get("repo_url", None)
        record["version"] = agent_desc.get("version", None)
        record["mode"] = agent_desc.get("mode", None)
        record["scenario"] = scenario_name
        # Experiment passport (ticket #37): record what the harness can observe
        # about the host, so `bench report` fills the template lines from data
        # instead of printing dashes and hardcoded claims. Everything unreadable
        # stays None and renders as a dash.
        meminfo = read_meminfo_kb(proc_root) or {}
        record["host_profile"] = {
            "os": sys.platform,
            "kernel": os.uname().release if hasattr(os, "uname") else None,
            "cpu_count": os.cpu_count(),
            "ram_total_mb": _meminfo_mb(meminfo, "MemTotal"),
            "swap_total_mb": _meminfo_mb(meminfo, "SwapTotal"),
            "swap_free_mb": _meminfo_mb(meminfo, "SwapFree"),
            "mem_available_mb_baseline": baseline_mb,
        }
        record["started_at_utc"] = primary["started_at_utc"]
        record["duration_sec"] = primary["duration_sec"]
        record["ram_pss_mb_median"] = primary["ram_pss_mb_median"]
        record["ram_peak_mb"] = primary["ram_peak_mb"]
        record["cpu_sec"] = primary.get("cpu_sec")
        record["startup_ms"] = primary["startup_ms"]
        # Latency fields: use median across repeats if scenario B
        if latency_p50_vals:
            record["latency_p50_ms"] = statistics.median(latency_p50_vals)
            record["latency_p95_ms"] = statistics.median(latency_p95_vals) if latency_p95_vals else None
        else:
            record["latency_p50_ms"] = None
            record["latency_p95_ms"] = None
        record["success_count"] = total_success
        record["error_count"] = total_errors
        # Aggregate OOM count from cgroup memory.events across repeats
        oom_values = [r.get("oom_count") for r in repeat_results if r.get("oom_count") is not None]
        record["oom_count"] = sum(oom_values) if oom_values else 0
        notes_parts = [
            f"repeats={num_repeats}",
        ]
        # Ticket #29: surface how many start attempts the run needed (only when the
        # candidate did not come up on the first try), so flaky starts stay visible.
        start_attempts_used = max((r.get("start_attempts_used") or 1) for r in repeat_results)
        if start_attempts_used > 1:
            notes_parts.append(f"start_attempts_used={start_attempts_used}")
        if "task_count" in scenario_def:
            notes_parts.append(f"task_count={scenario_def['task_count']}")
        if "repeats_per_task" in scenario_def:
            notes_parts.append(f"repeats_per_task={scenario_def['repeats_per_task']}")
        if "task_count" in scenario_def:
            # Scenario C: unfinished tasks are counted explicitly, even when 0
            unfinished = sum(int(r.get("unfinished_processes") or 0) for r in repeat_results)
            notes_parts.append(f"unfinished_processes={unfinished}")
        else:
            unfinished = sum(1 for r in repeat_results if not r.get("success", True))
            if unfinished > 0:
                notes_parts.append(f"unfinished_processes={unfinished}")
        if startup_variance is not None:
            notes_parts.append(f"startup_ms_variance={startup_variance}")
        if pss_variance is not None:
            notes_parts.append(f"pss_mb_variance={pss_variance}")
        # Tool cycles note
        tool_note = None
        for r in repeat_results:
            tc = r.get("tool_cycles")
            if tc is not None:
                tool_note = f"tool_cycles={tc}"
                break
        if tool_note:
            notes_parts.append(tool_note)
        else:
            # Check scenario flag
            if scenario_def.get("tool_cycles") is not None:
                notes_parts.append("tool_cycles=N/A")
        # Scenario-specific notes (e.g. scenario D: rss growth, restart state)
        for r in repeat_results:
            notes_parts.extend(r.get("extra_notes") or [])
        # Ticket #40 diagnostic: how many calls landed on the mock. With requests
        # routed through the candidate this is the candidate's upstream traffic;
        # zero next to non-zero success means the candidate ignored the mock.
        if mock_server is not None:
            notes_parts.append(f"mock_requests={mock_server.request_count}")
        if docker_image:
            notes_parts.append(f"runtime=docker")
            notes_parts.append(f"docker_image={docker_image}")
        # Ticket #12 extra metrics: cgroup identity and not-yet-collected values.
        # Missing values are null, never omitted (METHODOLOGY.md §7).
        if primary.get("cgroup_path"):
            notes_parts.append(f"cgroup_path={primary['cgroup_path']}")
        if aborted_guard:
            notes_parts.append(f"aborted=guard{aborted_guard['code']}:{aborted_guard['reason']}")
        notes_parts.extend([
            "disk_one_time_mb=null",
            "disk_growth_mb=null",
            "swap_in_pages=null",
            "swap_out_pages=null",
            "monitor_self_cost_ram_peak_mb=null",
            "monitor_self_cost_cpu_sec=null",
        ])
        record["notes"] = ", ".join(notes_parts)
        record["config_ref"] = str(scenario_path)

        # Sanitize all disk-write paths (ticket #16): no secret reaches
        # record.jsonl or repeats.jsonl raw.
        record, record_redacted = sanitize_record(record)
        if record_redacted:
            record["notes"] = ", ".join(filter(None, [record["notes"], SANITIZER_NOTE]))

        record_path = run_dir / "record.jsonl"
        with open(record_path, "w") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        repeats_path = run_dir / "repeats.jsonl"
        with open(repeats_path, "w") as f:
            for r in repeat_results:
                row = {k: v for k, v in r.items() if k not in ("pss_samples", "rss_samples", "latencies_ms")}
                row, _ = sanitize_record(row)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        if aborted_guard and aborted_guard["code"] == GUARD_EXIT_CODES["unavailable"]:
            status = "unavailable"
        elif aborted_guard:
            status = "aborted"
        elif any(r["success"] for r in repeat_results):
            status = "ok"
        else:
            status = "failed"

        print(json.dumps({
            "run_id": run_id,
            "status": status,
            "guard": aborted_guard,
            "repeats": len(repeat_results),
            "startup_ms_median": statistics.median(startup_values) if startup_values else None,
            "startup_ms_variance": startup_variance,
            "ram_pss_mb_median": statistics.median(pss_values) if pss_values else None,
            "ram_pss_mb_variance": pss_variance,
            "latency_p50_ms": record["latency_p50_ms"],
            "latency_p95_ms": record["latency_p95_ms"],
            "success_count": total_success,
            "error_count": total_errors,
            "record_path": str(record_path),
        }, indent=2))
        return aborted_guard["code"] if aborted_guard else 0
    finally:
        if mock_server:
            mock_server.stop()
