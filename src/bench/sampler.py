"""Proc filesystem sampler — reads PSS, RSS, MemAvailable from injectable roots."""

from pathlib import Path
import re


def read_pss_kb(proc_root: str | Path, pid: int) -> float | None:
    """Read PSS in kB from smaps_rollup for a given PID under proc_root."""
    path = Path(proc_root) / str(pid) / "smaps_rollup"
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    match = re.search(r"^Pss:\s+(\d+)\s+kB", text, re.MULTILINE)
    if match:
        return float(match.group(1))
    return None


def read_rss_kb(proc_root: str | Path, pid: int) -> float | None:
    """Read VmRSS in kB from status for a given PID under proc_root."""
    path = Path(proc_root) / str(pid) / "status"
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    match = re.search(r"^VmRSS:\s+(\d+)\s+kB", text, re.MULTILINE)
    if match:
        return float(match.group(1))
    return None


def read_mem_available_kb(proc_root: str | Path) -> float | None:
    """Read MemAvailable in kB from /proc/meminfo under proc_root."""
    meminfo = read_meminfo_kb(proc_root)
    return meminfo.get("MemAvailable") if meminfo else None


def read_meminfo_kb(proc_root: str | Path) -> dict[str, float] | None:
    """Read every `Key: <n> kB` field of /proc/meminfo under proc_root (ticket #37).

    The experiment passport needs more than MemAvailable: total RAM and swap are
    part of it. Returns None when meminfo is absent; fields without a kB unit are
    skipped, so a partial fixture is fine.
    """
    path = Path(proc_root) / "meminfo"
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    data: dict[str, float] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "kB":
            try:
                data[parts[0].rstrip(":")] = float(parts[1])
            except ValueError:
                continue
    return data or None


def kb_to_mb(kb: float) -> float:
    return kb / 1024.0


def read_cgroup_file(cgroup_root: str | Path, cgroup_path: str, filename: str) -> str | None:
    p = Path(cgroup_root) / cgroup_path / filename
    if not p.exists():
        return None
    try:
        return p.read_text().strip()
    except Exception:
        return None


def read_memory_peak_bytes(cgroup_root: str | Path, cgroup_path: str) -> int | None:
    text = read_cgroup_file(cgroup_root, cgroup_path, "memory.peak")
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def read_cgroup_cpu_stat(cgroup_root: str | Path, cgroup_path: str) -> dict[str, int] | None:
    text = read_cgroup_file(cgroup_root, cgroup_path, "cpu.stat")
    if text is None:
        return None
    data: dict[str, int] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.strip().split()
        if len(parts) >= 2:
            key, val = parts[0], parts[1]
            try:
                data[key] = int(val)
            except ValueError:
                continue
    return data if data else None


def read_cgroup_memory_events(cgroup_root: str | Path, cgroup_path: str) -> dict[str, int] | None:
    text = read_cgroup_file(cgroup_root, cgroup_path, "memory.events")
    if text is None:
        return None
    data: dict[str, int] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.strip().split()
        if len(parts) >= 2:
            key, val = parts[0], parts[1]
            try:
                data[key] = int(val)
            except ValueError:
                continue
    return data if data else None


def bytes_to_mb(b: int) -> float:
    return b / (1024.0 * 1024.0)


def cpu_sec_from_cgroup(cpu_stat: dict[str, int] | None) -> float | None:
    if cpu_stat is None:
        return None
    usage_usec = cpu_stat.get("usage_usec")
    if usage_usec is None:
        return None
    # Convert microseconds to seconds
    return usage_usec / 1_000_000.0


def read_cgroup_path_from_proc(proc_root: str | Path, pid: int) -> str | None:
    path = Path(proc_root) / str(pid) / "cgroup"
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except Exception:
        return None
    # Parse unified cgroup v2: "0::/path" or legacy "hierarchy:controllers:path"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(':')
        if len(parts) >= 3:
            cgroup_path = parts[2]
            # Strip leading slash for path joining
            return cgroup_path.lstrip('/')
    return None


def read_swap_counters(cgroup_root: str | Path, cgroup_path: str) -> tuple[int | None, int | None]:
    # Attempt to read swap in/out counters; these files may not exist
    # cgroup v2 does not expose swap-in/out counters directly; return None
    # Placeholder for future implementation
    return None, None
