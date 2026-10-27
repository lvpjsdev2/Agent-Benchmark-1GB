"""Descriptor contract: every shipped descriptor parses and plans a real run.

Descriptors under ``descriptors/`` are the ones used on the VM. A typo in a
descriptor only surfaces after an install on the host, so this test drives
``bench run --dry-run`` for each descriptor against a real-run scenario.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DESCRIPTORS = sorted((ROOT / "descriptors").glob("*.toml"))
SCENARIO = ROOT / "scenarios" / "real" / "a_cold_start.toml"


def test_descriptors_exist():
    names = {p.stem for p in DESCRIPTORS}
    assert {"zeptoclaw", "zeroclaw", "picoclaw", "microclaw", "nullclaw"} <= names
    assert {"picobot_docker", "moltis_docker"} <= names


@pytest.mark.parametrize("desc", DESCRIPTORS, ids=lambda p: p.stem)
def test_descriptor_plans_a_run(desc: Path, tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "bench", "run", str(desc), str(SCENARIO),
         "--dry-run", "--runs-dir", str(tmp_path / "runs")],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    assert proc.returncode == 0, f"{desc.name}: {proc.stderr}"
    plan = json.loads(proc.stdout)
    assert plan["scenario"] == "scenario_a_cold_start"
    assert plan["repeats"] == 3
    assert plan["start_command"]
    assert plan["healthcheck"]["type"] in {"http", "tcp", "file"}
    if desc.stem.endswith("_docker"):
        assert plan["mode"] == "docker"
        assert "@sha256:" in plan["docker_image"]
        assert plan["docker_memory_limit"] == "512m"


def test_native_descriptors_do_not_pin_a_docker_image():
    for desc in DESCRIPTORS:
        if desc.stem.endswith("_docker"):
            continue
        proc = subprocess.run(
            [sys.executable, "-m", "bench", "run", str(desc), str(SCENARIO),
             "--dry-run", "--runs-dir", "/tmp/unused"],
            capture_output=True, text=True, cwd=ROOT, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["docker_image"] is None
