"""Unit tests for the proc-fs sampler against fixture trees.

These tests assert on the values baked into tests/fixtures/proc, which is the
mechanism by which the CLI-seam tests can check that PSS/RSS/MemAvailable are
read correctly from an injectable proc root.
"""

from __future__ import annotations

from pathlib import Path

from bench.sampler import (
    kb_to_mb,
    read_mem_available_kb,
    read_meminfo_kb,
    read_pss_kb,
    read_rss_kb,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROC_ROOT = FIXTURES / "proc"
PID = 1000


def test_read_pss_from_fixture_smaps_rollup():
    assert read_pss_kb(PROC_ROOT, PID) == 15360.0
    assert kb_to_mb(read_pss_kb(PROC_ROOT, PID)) == 15.0


def test_read_rss_from_fixture_status():
    assert read_rss_kb(PROC_ROOT, PID) == 20480.0
    assert kb_to_mb(read_rss_kb(PROC_ROOT, PID)) == 20.0


def test_read_mem_available_from_fixture_meminfo():
    assert read_mem_available_kb(PROC_ROOT) == 524288.0
    assert kb_to_mb(read_mem_available_kb(PROC_ROOT)) == 512.0


def test_read_meminfo_reads_ram_and_swap_from_fixture():
    """Ticket #37: the passport needs RAM and swap, not only MemAvailable."""
    meminfo = read_meminfo_kb(PROC_ROOT)
    assert meminfo is not None
    assert meminfo["MemTotal"] == 1048576.0
    assert meminfo["MemAvailable"] == 524288.0
    assert meminfo["SwapTotal"] == 1048576.0
    assert meminfo["SwapFree"] == 524288.0


def test_missing_proc_files_return_none(tmp_path):
    assert read_pss_kb(tmp_path, 999999) is None
    assert read_rss_kb(tmp_path, 999999) is None
    assert read_mem_available_kb(tmp_path) is None
    assert read_meminfo_kb(tmp_path) is None


def test_proc_permission_errors_return_none(monkeypatch, tmp_path):
    """Container PIDs may be visible while smaps/status are ptrace-protected."""
    original = Path.read_text

    def denied(self, *args, **kwargs):
        if str(self).endswith(("smaps_rollup", "status")):
            raise PermissionError("ptrace scope")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    (tmp_path / "1000").mkdir()
    (tmp_path / "1000" / "smaps_rollup").touch()
    (tmp_path / "1000" / "status").touch()
    assert read_pss_kb(tmp_path, 1000) is None
    assert read_rss_kb(tmp_path, 1000) is None
