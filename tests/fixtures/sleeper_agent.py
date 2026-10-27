#!/usr/bin/env python3
"""Fixture agent for scenario D: stability and recovery.

Supports configurable behavior:
- Slow response (delay before each response)
- Hung child process (blocks indefinitely unless killed)
- Memory growth between requests (allocates memory incrementally)
- Test state saving/loading
"""
import sys
import time
import json
import os
import signal
import threading
from pathlib import Path


def main():
    workdir = sys.argv[1] if len(sys.argv) > 1 else "."
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    delay_ms = float(sys.argv[2]) if len(sys.argv) > 2 else 0  # response delay in ms
    mem_growth_kb = float(sys.argv[3]) if len(sys.argv) > 3 else 0  # memory growth per request in kB
    test_state_file = sys.argv[4] if len(sys.argv) > 4 else "test_state.json"
    health_file = wd / "healthy"
    # Delay before becoming healthy
    initial_delay = float(sys.argv[5]) if len(sys.argv) > 5 else 0.2
    time.sleep(initial_delay)
    health_file.write_text("ok")

    # Track test state
    state = {"start_time": time.time(), "requests_handled": 0, "memory_allocated": 0}
    state_path = wd / test_state_file
    if state_path.exists():
        try:
            existing = json.loads(state_path.read_text())
            state.update(existing)
        except Exception:
            pass
    state_path.write_text(json.dumps(state))

    # Optional behaviors selected by argv[6] (ticket #15 fixture matrix)
    behavior = sys.argv[6] if len(sys.argv) > 6 else ""
    if behavior == "spawn_hung_child":
        # Detached child that outlives the agent unless killed explicitly
        import subprocess as _sp
        _sp.Popen(["sleep", "300"])

    # Keep track of child processes
    child_pids = []

    # Main loop: handle requests and potentially grow memory
    while True:
        try:
            # Check for test state file updates from harness
            if state_path.exists():
                try:
                    existing = json.loads(state_path.read_text())
                    state.update(existing)
                    # Save back so harness can read it
                    state_path.write_text(json.dumps(state))
                except Exception:
                    pass

            # Simulate request handling with optional delay
            time.sleep(max(0, delay_ms / 1000.0))

            # Memory growth: allocate a small amount if requested
            if mem_growth_kb > 0:
                # Simulate memory allocation by writing data
                alloc_size = int(mem_growth_kb * 1024)
                try:
                    buf = b"0" * alloc_size
                    state["memory_allocated"] += alloc_size
                    state_path.write_text(json.dumps(state))
                except MemoryError:
                    pass

            state["requests_handled"] += 1
            state_path.write_text(json.dumps(state))

            # Sleep to keep agent alive
            time.sleep(0.1)

        except KeyboardInterrupt:
            # Clean shutdown
            state["shutdown"] = time.time()
            state_path.write_text(json.dumps(state))
            break
        except Exception:
            time.sleep(0.5)


if __name__ == "__main__":
    main()