#!/usr/bin/env python3
"""Fixture agent for tool calls: sleeps then signals readiness."""
import sys
import time
from pathlib import Path

def main():
    workdir = sys.argv[1] if len(sys.argv) > 1 else "."
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2
    health_file = Path(workdir) / "healthy"
    time.sleep(delay)
    health_file.write_text("ok")
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
