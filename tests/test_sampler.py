"""Unit tests for the proc-fs sampler against fixture trees.

These tests assert on the values baked into tests/fixtures/proc, which is the
mechanism by which the CLI-seam tests can check that PSS/RSS/MemAvailable are
read correctly from an injectable proc root.
"""

from __future__ import annotations

from pathlib import Path

from bench.sampler import kb_to_mb, read_mem_available_kb, read_pss_kb, read_rss_kb

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


def test_missing_proc_files_return_none(tmp_path):
    assert read_pss_kb(tmp_path, 999999) is None
    assert read_rss_kb(tmp_path, 999999) is None
    assert read_mem_available_kb(tmp_path) is None