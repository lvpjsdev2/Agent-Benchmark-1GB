#!/usr/bin/env python3
"""Fixture agent for the start-attempts policy (ticket #29).

Each launch appends one line to <counter_file>, so a test can count how many
start attempts the harness actually made, and writes <health_file> once the
attempt number reaches <healthy_from>. With healthy_from above the attempt
budget the candidate never comes up — the "did not start" case — while
healthy_from=2 models a candidate that needs a second attempt.

Usage: start_counter_agent.py <counter_file> <health_file> <healthy_from>
"""
import sys
import time
from pathlib import Path


def main():
    counter_file = Path(sys.argv[1])
    health_file = Path(sys.argv[2])
    healthy_from = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    counter_file.parent.mkdir(parents=True, exist_ok=True)
    prior = len(counter_file.read_text().splitlines()) if counter_file.exists() else 0
    with counter_file.open("a") as fh:
        fh.write("start\n")
    attempt = prior + 1

    if attempt >= healthy_from:
        health_file.parent.mkdir(parents=True, exist_ok=True)
        health_file.write_text("ok")

    while True:
        time.sleep(0.1)


if __name__ == "__main__":
    main()
