#!/usr/bin/env python3
"""Fixture candidate with its own chat endpoint (ticket #40).

The harness must send scenario requests to the candidate, not to the mock.
This fixture is a minimal candidate: it serves POST /v1/chat/completions,
optionally forwards the request to an upstream LLM (the mock server) and
returns the upstream status, so injected 429/500/timeout errors propagate
through the candidate exactly as they would through a real agent.

argv: workdir port upstream_url|- delay_ms behavior upstream_timeout_sec
Every request is appended to <workdir>/chat_requests.log, so tests can assert
that the harness reached the candidate and how many times.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKDIR = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
UPSTREAM = sys.argv[3] if len(sys.argv) > 3 else "-"
# Ticket #40: the harness passes the mock address via the descriptor's env map.
if UPSTREAM in ("", "-"):
    UPSTREAM = os.environ.get("BENCH_TEST_UPSTREAM", "")
DELAY_MS = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
BEHAVIOR = sys.argv[5] if len(sys.argv) > 5 else ""
UPSTREAM_TIMEOUT = float(sys.argv[6]) if len(sys.argv) > 6 else 0.3
REQUESTS_LOG = WORKDIR / "chat_requests.log"
STATE_FILE = WORKDIR / "test_state.json"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        if DELAY_MS:
            time.sleep(DELAY_MS / 1000.0)
        with open(REQUESTS_LOG, "a") as fh:
            fh.write(json.dumps({"path": self.path, "body": json.loads(body or b"{}")}) + "\n")
        # Keep request count in the state file, which survives a restart.
        state = _read_state()
        state["requests_handled"] = int(state.get("requests_handled", 0)) + 1
        _write_state(state)

        status, payload = 200, json.dumps({
            "id": "chatcmpl-fixture",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "fixture ok"}}],
        }).encode()
        if UPSTREAM and UPSTREAM != "-":
            req = urllib.request.Request(
                UPSTREAM, method="POST", data=body, headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as resp:
                    status = resp.status
                    payload = resp.read()
            except urllib.error.HTTPError as exc:
                status = exc.code
                payload = json.dumps({"error": {"message": str(exc.code)}}).encode()
            except Exception as exc:  # timeout / connection refused
                status = 500
                payload = json.dumps({"error": {"message": str(exc)}}).encode()

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _read_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def main() -> None:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    state = _read_state()
    started = state.get("start_time")
    state["start_time"] = started if started is not None else time.time()
    _write_state(state)
    if BEHAVIOR == "spawn_hung_child":
        import subprocess

        subprocess.Popen(["sleep", "300"])

    # A scenario-D restart may race the previous socket's teardown; retry the
    # bind briefly instead of dying, which would look like a failed candidate.
    deadline = time.time() + 5.0
    while True:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
            break
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.1)
    (WORKDIR / "healthy").write_text("ok")
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        try:
            (WORKDIR / "fixture_error.log").write_text(traceback.format_exc())
        finally:
            raise
