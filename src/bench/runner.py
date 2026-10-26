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
    kb_to_mb,
    read_memory_peak_bytes,
    read_cgroup_cpu_stat,
    read_cgroup_memory_events,
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


def _percentile(data: list[float], p: float) -> float:
    """Linear-interpolated percentile of a sorted-able list, 0..100."""
    data_sorted = sorted(data)
    k = (len(data_sorted) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(data_sorted) - 1)
    if f == c:
        return data_sorted[int(k)]
    return data_sorted[f] * (c - k) + data_sorted[c] * (k - f)


# Guard exit codes (ticket #16): distinct codes so an AFK run can be triaged
# without a human. 0 ok, 1 usage/setup, 2 OOM, 3 MemAvailable, 4 health, 5 API budget.
GUARD_EXIT_CODES = {
    "oom": 2,
    "memavailable": 3,
    "health": 4,
    "api_budget": 5,
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


def _health_guard() -> dict:
    return {
        "code": GUARD_EXIT_CODES["health"],
        "reason": "healthcheck failed (limit reached)",
    }


def _budget_guard(budget: int, issued: int) -> dict:
    return {
        "code": GUARD_EXIT_CODES["api_budget"],
        "reason": f"api_requests={issued}>=guard_api_request_budget={budget}",
    }


def _run_single_repeat_scenario_a(
    agent_desc: dict,
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    repeat_idx: int,
) -> dict[str, Any]:
    """Execute one repeat of scenario A (cold start / idle). Returns metrics dict."""
    # Cgroup path for agent; scenario may define it for fixtures
    cgroup_path = scenario_def.get("cgroup_path") or agent_desc.get("cgroup_path") or "agent"
    duration_s = scenario_def.get("duration_sec", 10)
    sample_interval = scenario_def.get("sample_interval_sec", 1)
    hc = agent_desc.get("healthcheck", {})
    hc_type = hc.get("type", "file")
    hc_value = hc.get("value", "")
    hc_timeout = hc.get("timeout_sec", 30)
    workdir = agent_desc.get("workdir", "/tmp/bench-agent-workdir")
    start_cmd = agent_desc["start_command"]
    # Fixture-only override: sample proc files under a fixed PID (e.g. a fixture
    # proc tree keyed to PID 1000) instead of the real child PID, so CLI tests can
    # assert on known values. Never set for real agents.
    proc_pid_override = scenario_def.get("proc_pid_override") or agent_desc.get("proc_pid_override")

    # Resolve relative paths against the harness cwd so descriptors are portable
    # and healthcheck files land where the agent writes them. The agent is started
    # from the workdir and receives workdir as an argument, so the healthcheck
    # path and the agent's own workdir argument must be the same absolute path.
    workdir_abs = str(Path(workdir).resolve())
    if hc_type == "file" and hc_value:
        hc_value = str(Path(hc_value).resolve())

    # Start command: resolve the script path and any workdir argument to absolute
    # paths relative to the harness cwd (only for list-style commands; shell strings
    # are left untouched and resolve relative to the workdir cwd at runtime).
    if isinstance(start_cmd, list):
        cmd_cwd = Path.cwd()
        resolved_cmd: list[str] = []
        for part in start_cmd:
            if part == workdir:
                resolved_cmd.append(workdir_abs)
            else:
                cand = cmd_cwd / part
                resolved_cmd.append(str(cand) if cand.exists() else part)
        start_cmd = resolved_cmd

    # Clean workdir before this repeat
    _cleanup_workdir(workdir_abs)

    # Capture RAM baseline before starting the agent
    mem_avail_kb = read_mem_available_kb(proc_root)
    ram_baseline_mb = kb_to_mb(mem_avail_kb) if mem_avail_kb is not None else None

    # Start process
    t_start = time.monotonic()
    started_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    proc = subprocess.Popen(
        start_cmd,
        shell=isinstance(start_cmd, str),
        cwd=workdir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = proc.pid
    sample_pid = int(proc_pid_override) if proc_pid_override else pid

    # Wait for healthcheck; failure is the health guard (exit code 4)
    healthy = _wait_for_healthcheck(hc_type, hc_value, hc_timeout)
    t_healthy = time.monotonic()
    startup_ms = (t_healthy - t_start) * 1000.0 if healthy else None
    guard = None
    if not healthy:
        guard = _health_guard()

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
        "guard": guard,
    }


def _run_single_repeat_scenario_b(
    agent_desc: dict,
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    repeat_idx: int,
    mock_port: int | None,
) -> dict[str, Any]:
    """Execute one repeat of scenario B (mock LLM controlled requests)."""
    duration_s = 0
    sample_interval = 1
    hc = agent_desc.get("healthcheck", {})
    hc_type = hc.get("type", "file")
    hc_value = hc.get("value", "")
    hc_timeout = hc.get("timeout_sec", 30)
    workdir = agent_desc.get("workdir", "/tmp/bench-agent-workdir")
    start_cmd = agent_desc["start_command"]
    proc_pid_override = scenario_def.get("proc_pid_override") or agent_desc.get("proc_pid_override")

    workdir_abs = str(Path(workdir).resolve())
    if hc_type == "file" and hc_value:
        hc_value = str(Path(hc_value).resolve())

    if isinstance(start_cmd, list):
        cmd_cwd = Path.cwd()
        resolved_cmd: list[str] = []
        for part in start_cmd:
            if part == workdir:
                resolved_cmd.append(workdir_abs)
            else:
                cand = cmd_cwd / part
                resolved_cmd.append(str(cand) if cand.exists() else part)
        start_cmd = resolved_cmd

    _cleanup_workdir(workdir_abs)

    mem_avail_kb = read_mem_available_kb(proc_root)
    ram_baseline_mb = kb_to_mb(mem_avail_kb) if mem_avail_kb is not None else None

    t_start = time.monotonic()
    started_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    proc = subprocess.Popen(
        start_cmd,
        shell=isinstance(start_cmd, str),
        cwd=workdir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = proc.pid
    sample_pid = int(proc_pid_override) if proc_pid_override else pid

    healthy = _wait_for_healthcheck(hc_type, hc_value, hc_timeout)
    if not healthy:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        return {
            "repeat": repeat_idx,
            "startup_ms": None,
            "ram_pss_mb_median": None,
            "ram_peak_mb": None,
            "ram_baseline_mb": ram_baseline_mb,
            "duration_sec": 0.0,
            "started_at_utc": started_at_utc,
            "success": False,
            "pss_samples": [],
            "rss_samples": [],
            "latencies_ms": [],
            "success_count": 0,
            "error_count": 0,
            "tool_cycles": None,
            "guard": _health_guard(),
        }

    t_healthy = time.monotonic()
    startup_ms = (t_healthy - t_start) * 1000.0

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

    mock_llm_url = scenario_def.get("mock_llm_url")
    if mock_port:
        mock_llm_url = f"http://127.0.0.1:{mock_port}/v1/chat/completions"
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
            if mock_llm_url:
                req = urllib.request.Request(mock_llm_url, method="POST", data=b'{"messages":[]}', headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=request_timeout) as resp:
                    _ = resp.read()
                    ok = resp.status == 200
            else:
                # No mock, just sleep a bit
                time.sleep(0.01)
                ok = True
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
) -> dict[str, Any]:
    """Execute one repeat of scenario C (real LLM tasks, ticket #14).

    Tasks run as requests against the mock LLM server when one is up
    (mock_port includes 0 = OS-assigned). Without a mock server no request is
    issued and all tasks are marked unfinished in the result.
    """
    task_count = int(scenario_def.get("task_count", 0))
    repeats_per_task = int(scenario_def.get("repeats_per_task", 0))
    total_tasks = task_count * repeats_per_task

    hc = agent_desc.get("healthcheck", {})
    hc_type = hc.get("type", "file")
    hc_value = hc.get("value", "")
    hc_timeout = hc.get("timeout_sec", 30)
    workdir = agent_desc.get("workdir", "/tmp/bench-agent-workdir")
    start_cmd = _resolve_start_cmd(agent_desc["start_command"], workdir, str(Path(workdir).resolve()))
    proc_pid_override = scenario_def.get("proc_pid_override") or agent_desc.get("proc_pid_override")

    workdir_abs = str(Path(workdir).resolve())
    if hc_type == "file" and hc_value:
        hc_value = str(Path(hc_value).resolve())

    _cleanup_workdir(workdir_abs)

    mem_avail_kb = read_mem_available_kb(proc_root)
    ram_baseline_mb = kb_to_mb(mem_avail_kb) if mem_avail_kb is not None else None

    started_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    t_start = time.monotonic()

    proc = subprocess.Popen(
        start_cmd,
        shell=isinstance(start_cmd, str),
        cwd=workdir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sample_pid = int(proc_pid_override) if proc_pid_override else proc.pid

    healthy = _wait_for_healthcheck(hc_type, hc_value, hc_timeout)
    if not healthy:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        return {
            "repeat": repeat_idx,
            "startup_ms": None,
            "ram_pss_mb_median": None,
            "ram_peak_mb": None,
            "ram_baseline_mb": ram_baseline_mb,
            "duration_sec": 0.0,
            "started_at_utc": started_at_utc,
            "success": False,
            "pss_samples": [],
            "rss_samples": [],
            "latencies_ms": [],
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "success_count": 0,
            "error_count": 0,
            "unfinished_processes": total_tasks,
            "guard": _health_guard(),
        }

    startup_ms = (time.monotonic() - t_start) * 1000.0

    pss_samples: list[float] = []
    rss_samples: list[float] = []
    latencies_ms: list[float] = []
    success_count = 0
    error_count = 0
    api_budget = scenario_def.get("guard_api_request_budget")
    guard = None

    # With a mock server (port may be 0 = OS-assigned) tasks issue real requests
    if mock_port is not None:
        mock_llm_url = f"http://127.0.0.1:{mock_port}/v1/chat/completions"
        request_timeout = float(scenario_def.get("request_timeout_sec", 5.0))
        for task in range(total_tasks):
            if proc.poll() is not None:
                guard = _health_guard()
                break
            pss = read_pss_kb(proc_root, sample_pid)
            rss = read_rss_kb(proc_root, sample_pid)
            if pss is not None:
                pss_samples.append(kb_to_mb(pss))
            if rss is not None:
                rss_samples.append(kb_to_mb(rss))

            req_start = time.monotonic()
            try:
                req = urllib.request.Request(
                    mock_llm_url, method="POST", data=b'{"messages":[]}',
                    headers={"Content-Type": "application/json"},
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

    unfinished = total_tasks - success_count if mock_port is not None else total_tasks

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
        "guard": guard,
    }


def _run_single_repeat(
    agent_desc: dict,
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    repeat_idx: int,
    mock_port: int | None,
) -> dict[str, Any]:
    """Execute one repeat, dispatching to B, C or A based on scenario definition."""
    scenario_name = scenario_def.get("name", "")
    if "scenario_b" in scenario_name.lower() or scenario_def.get("requests"):
        return _run_single_repeat_scenario_b(
            agent_desc, scenario_def, proc_root, cgroup_root, repeat_idx, mock_port
        )
    # Scenario C is identified by task_count + repeats_per_task (ticket #14)
    if scenario_def.get("task_count") is not None and scenario_def.get("repeats_per_task") is not None:
        return _run_single_repeat_scenario_c(
            agent_desc, scenario_def, proc_root, cgroup_root, repeat_idx, mock_port
        )
    return _run_single_repeat_scenario_a(
        agent_desc, scenario_def, proc_root, cgroup_root, repeat_idx
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
        "scenario": scenario_def.get("name", scenario_path.stem),
        "scenario_definition": str(scenario_path),
        "repeats": scenario_def.get("repeats", 3),
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
    }
    return plan


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
        cfg = MockConfig(latency_ms=latency_ms, error_mode=error_mode)
        mock_server = MockLLMServer(port=mock_port_arg, config=cfg)
        mock_port_num = mock_server.start()

    try:
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
        record["host_profile"] = {
            "mem_available_mb_baseline": baseline_mb,
            "os": sys.platform,
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

        print(json.dumps({
            "run_id": run_id,
            "status": "aborted" if aborted_guard else ("ok" if any(r["success"] for r in repeat_results) else "failed"),
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
