#!/usr/bin/env python3
"""Fixture agent: sleeps briefly then creates a healthcheck file to signal readiness."""
import sys
import time
from pathlib import Path

def main():
    workdir = sys.argv[1] if len(sys.argv) > 1 else "."
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    health_file = Path(workdir) / "healthy"
    time.sleep(delay)
    health_file.write_text("ok")
    # Stay alive for sampling
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
