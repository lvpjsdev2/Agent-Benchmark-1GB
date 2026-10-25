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


def _run_single_repeat(
    agent_desc: dict,
    scenario_def: dict,
    proc_root: str,
    cgroup_root: str,
    repeat_idx: int,
) -> dict[str, Any]:
    """Execute one repeat of scenario A. Returns metrics dict."""
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

    # Wait for healthcheck
    healthy = _wait_for_healthcheck(hc_type, hc_value, hc_timeout)
    t_healthy = time.monotonic()
    startup_ms = (t_healthy - t_start) * 1000.0 if healthy else None

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
    }


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

    proc_root = args.proc_root
    cgroup_root = args.cgroup_root
    runs_dir = Path(args.runs_dir)

    run_id = str(uuid.uuid4())[:8]
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    num_repeats = scenario_def.get("repeats", 3)
    scenario_name = scenario_def.get("name", scenario_path.stem)

    repeat_results: list[dict] = []
    for i in range(num_repeats):
        result = _run_single_repeat(
            agent_desc=agent_desc,
            scenario_def=scenario_def,
            proc_root=proc_root,
            cgroup_root=cgroup_root,
            repeat_idx=i,
        )
        repeat_results.append(result)

    # Build summary with variance across repeats
    startup_values = [r["startup_ms"] for r in repeat_results if r["startup_ms"] is not None]
    pss_values = [r["ram_pss_mb_median"] for r in repeat_results if r["ram_pss_mb_median"] is not None]

    startup_variance = statistics.variance(startup_values) if len(startup_values) >= 2 else None
    pss_variance = statistics.variance(pss_values) if len(pss_values) >= 2 else None

    # Use first successful repeat's timing for the record, or last repeat
    primary = repeat_results[-1]
    for r in repeat_results:
        if r["success"]:
            primary = r
            break

    # Baseline from first repeat
    baseline_mb = repeat_results[0]["ram_baseline_mb"]

    # Build JSONL record with all section 7 fields
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
    record["latency_p50_ms"] = None  # Scenario A has no requests
    record["latency_p95_ms"] = None
    record["success_count"] = sum(1 for r in repeat_results if r["success"])
    record["error_count"] = sum(1 for r in repeat_results if not r["success"])

    # Aggregate OOM count from repeats
    oom_values = [r.get("oom_count") for r in repeat_results if r.get("oom_count") is not None]
    record["oom_count"] = sum(oom_values) if oom_values else 0

    # Build machine-readable notes block with extra metrics
    extra_notes = []
    if primary.get("cgroup_path"):
        extra_notes.append(f"cgroup_path={primary['cgroup_path']}")
    # Disk metrics placeholder - not implemented yet, leave null
    extra_notes.append("disk_one_time_mb=null")
    extra_notes.append("disk_growth_mb=null")
    extra_notes.append("swap_in_pages=null")
    extra_notes.append("swap_out_pages=null")
    # Monitor self-cost recorded separately via notes
    extra_notes.append("monitor_self_cost_ram_peak_mb=null")
    extra_notes.append("monitor_self_cost_cpu_sec=null")

    record["notes"] = (
        f"repeats={num_repeats}, "
        f"startup_ms_variance={startup_variance}, "
        f"pss_mb_variance={pss_variance}, "
        f"{'; '.join(extra_notes)}"
    )
    record["config_ref"] = str(scenario_path)

    # Write JSONL record
    record_path = run_dir / "record.jsonl"
    with open(record_path, "w") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Write per-repeat details
    repeats_path = run_dir / "repeats.jsonl"
    with open(repeats_path, "w") as f:
        for r in repeat_results:
            row = {k: v for k, v in r.items() if k not in ("pss_samples", "rss_samples")}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Print summary to stdout
    print(json.dumps({
        "run_id": run_id,
        "status": "ok" if any(r["success"] for r in repeat_results) else "failed",
        "repeats": num_repeats,
        "startup_ms_median": statistics.median(startup_values) if startup_values else None,
        "startup_ms_variance": startup_variance,
        "ram_pss_mb_median": statistics.median(pss_values) if pss_values else None,
        "ram_pss_mb_variance": pss_variance,
        "record_path": str(record_path),
    }, indent=2))

    return 0
