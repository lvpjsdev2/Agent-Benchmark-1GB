"""Proc filesystem sampler — reads PSS, RSS, MemAvailable from injectable roots."""

from pathlib import Path
import re


def read_pss_kb(proc_root: str | Path, pid: int) -> float | None:
    """Read PSS in kB from smaps_rollup for a given PID under proc_root."""
    path = Path(proc_root) / str(pid) / "smaps_rollup"
    if not path.exists():
        return None
    text = path.read_text()
    match = re.search(r"^Pss:\s+(\d+)\s+kB", text, re.MULTILINE)
    if match:
        return float(match.group(1))
    return None


def read_rss_kb(proc_root: str | Path, pid: int) -> float | None:
    """Read VmRSS in kB from status for a given PID under proc_root."""
    path = Path(proc_root) / str(pid) / "status"
    if not path.exists():
        return None
    text = path.read_text()
    match = re.search(r"^VmRSS:\s+(\d+)\s+kB", text, re.MULTILINE)
    if match:
        return float(match.group(1))
    return None


def read_mem_available_kb(proc_root: str | Path) -> float | None:
    """Read MemAvailable in kB from /proc/meminfo under proc_root."""
    path = Path(proc_root) / "meminfo"
    if not path.exists():
        return None
    text = path.read_text()
    match = re.search(r"^MemAvailable:\s+(\d+)\s+kB", text, re.MULTILINE)
    if match:
        return float(match.group(1))
    return None


def kb_to_mb(kb: float) -> float:
    return kb / 1024.0
