#!/usr/bin/env python3
"""Fixture agent that calls mock LLM endpoint and signals readiness."""
import sys
import time
import urllib.request
from pathlib import Path

def main():
    workdir = sys.argv[1] if len(sys.argv) > 1 else "."
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2
    mock_url = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8000/v1/chat/completions"
    health_file = Path(workdir) / "healthy"
    time.sleep(delay)
    health_file.write_text("ok")
    # Stay alive
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
