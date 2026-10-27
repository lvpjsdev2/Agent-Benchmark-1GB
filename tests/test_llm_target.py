"""Tests for the request the harness sends to the candidate (ticket #40).

The harness posts to the descriptor's ``chat_url``, not to the candidate's LLM
endpoint. These tests run a strict OpenAI-like server as the *candidate* and
assert the payload and bearer token it receives: a model, a non-empty message,
and the token named by ``chat_api_key_env`` (never written to disk).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PROC_ROOT = FIXTURES / "proc"
AGENT_SCRIPT = FIXTURES / "sleeper_agent.py"

TOKEN = "test-token-123"


class _StrictHandler(BaseHTTPRequestHandler):
    """400 on empty messages or missing model, 401 without bearer token."""

    seen: list[dict] = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw or b"{}")
        type(self).seen.append({"body": body, "auth": self.headers.get("Authorization")})

        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return
        if not body.get("messages"):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"messages: Array must contain at least 1 element(s)"}')
            return
        if not body.get("model"):
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"model is required"}')
            return

        payload = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _serve_strict():
    handler_cls = type("StrictHandler", (_StrictHandler,), {"seen": []})
    httpd = HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1], handler_cls


def _descriptor(tmp_path: Path, chat_port: int) -> Path:
    workdir = tmp_path / "wd"
    workdir.mkdir(parents=True, exist_ok=True)
    desc = tmp_path / "agent.toml"
    desc.write_text(textwrap.dedent(f"""
        name = "sleeper-fixture"
        repo_url = "https://example.com/sleeper"
        version = "0.0.1"
        mode = "native"
        chat_url = "http://127.0.0.1:{chat_port}/v1/chat/completions"
        chat_api_key_env = "BENCH_CHAT_KEY"
        start_command = ["python3", "{AGENT_SCRIPT}", "{workdir}", "0.1"]
        workdir = "{workdir}"

        [healthcheck]
        type = "file"
        value = "{workdir / 'healthy'}"
        timeout_sec = 10
    """))
    return desc


def _scenario(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "scenario.toml"
    path.write_text(textwrap.dedent(body))
    return path


def _run(desc: Path, scenario: Path, runs_dir: Path, env: dict | None = None):
    cmd = [
        sys.executable, "-m", "bench", "run",
        str(desc), str(scenario),
        "--proc-root", str(PROC_ROOT),
        "--runs-dir", str(runs_dir),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, **(env or {})}, timeout=120,
    )
    return proc


IMPLICIT = """
    name = "scenario_b_mock_llm_controlled"
    requests = 5
    warmup_requests = 0
    repeats = 1
    mock_latency_ms = 0
"""

SCENARIO_C = """
    name = "scenario_c_real_llm_tasks"
    task_count = 2
    repeats_per_task = 1
    repeats = 1
    mock_latency_ms = 0
"""


def test_chat_request_carries_model_message_and_bearer_token(tmp_path):
    httpd, port, handler = _serve_strict()
    try:
        scenario = _scenario(tmp_path, IMPLICIT + """
    llm_model = "test-model"
    llm_prompt = "say ok"
""")
        runs = tmp_path / "runs"
        proc = _run(_descriptor(tmp_path, port), scenario, runs, env={"BENCH_CHAT_KEY": TOKEN})
        assert proc.returncode == 0, proc.stderr
        record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
        assert record["success_count"] == 5
        assert record["error_count"] == 0
        assert handler.seen[0]["auth"] == f"Bearer {TOKEN}"
        assert handler.seen[0]["body"]["model"] == "test-model"
        assert handler.seen[0]["body"]["messages"][0]["content"] == "say ok"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_chat_request_always_sends_a_model(tmp_path):
    """The legacy empty payload is gone: the candidate always gets a model."""
    httpd, port, handler = _serve_strict()
    try:
        scenario = _scenario(tmp_path, IMPLICIT)
        runs = tmp_path / "runs"
        proc = _run(_descriptor(tmp_path, port), scenario, runs, env={"BENCH_CHAT_KEY": TOKEN})
        assert proc.returncode == 0, proc.stderr
        record = json.loads(list(runs.glob("*/record.jsonl"))[0].read_text())
        assert record["success_count"] == 5
        assert handler.seen[0]["body"]["model"] == "bench-model"
        assert handler.seen[0]["body"]["messages"][0]["content"] == "Reply with OK."
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_scenario_c_cycles_llm_prompts_through_the_candidate(tmp_path):
    httpd, port, handler = _serve_strict()
    try:
        scenario = _scenario(tmp_path, SCENARIO_C + """
    llm_prompts = ["task one", "task two"]
""")
        runs = tmp_path / "runs"
        proc = _run(_descriptor(tmp_path, port), scenario, runs, env={"BENCH_CHAT_KEY": TOKEN})
        assert proc.returncode == 0, proc.stderr
        prompts = [s["body"]["messages"][0]["content"] for s in handler.seen]
        assert prompts == ["task one", "task two"]
    finally:
        httpd.shutdown()
        httpd.server_close()
