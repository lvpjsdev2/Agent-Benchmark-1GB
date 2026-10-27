"""OpenAI-compatible mock LLM HTTP server with scripted responses.

Error injection (ticket #38): `error_on_call` limits the injected error to one
call number; without it every call is affected. A `timeout` error hangs the
targeted call for `timeout_sleep_sec` and leaves its neighbours untouched.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

DEFAULT_LATENCY_MS = 50
DEFAULT_RESPONSE = {
    "id": "chatcmpl-mock-1",
    "object": "chat.completion",
    "created": int(time.time()),
    "model": "mock-llm",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "mock response"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
}


class MockConfig:
    def __init__(
        self,
        latency_ms: int = DEFAULT_LATENCY_MS,
        response: Dict[str, Any] | None = None,
        error_mode: str | None = None,  # None, "429", "500", "timeout"
        error_on_call: int | None = None,
        timeout_sleep_sec: float = 10.0,
    ):
        self.latency_ms = latency_ms
        self.response = response or DEFAULT_RESPONSE
        self.error_mode = error_mode
        self.error_on_call = error_on_call
        # How long a "timeout" call hangs; must exceed the client's request
        # timeout, so a scenario can shorten both for fast tests.
        self.timeout_sleep_sec = timeout_sleep_sec


class _Handler(BaseHTTPRequestHandler):
    config: MockConfig
    counter: int
    lock: threading.Lock

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b""
        # We don't validate body, just accept.

        # counter is a class attribute shared by per-request handler instances;
        # mutate it via the class or each request would read the initial 0.
        with self.lock:
            type(self).counter += 1
            call_no = type(self).counter

        cfg = self.config
        # Simulate latency
        time.sleep(cfg.latency_ms / 1000.0)

        # Error injection. With `error_on_call` only that call is affected;
        # without it every call is (ticket #38). A timeout hangs the targeted
        # call — before the fix the target received HTTP 500 and every other
        # call hung, i.e. the injection was inverted.
        targeted = cfg.error_on_call is None or call_no == cfg.error_on_call
        if cfg.error_mode and targeted:
            if cfg.error_mode == "timeout":
                time.sleep(cfg.timeout_sleep_sec)
                return
            status = 429 if cfg.error_mode == "429" else 500
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": cfg.error_mode}}).encode())
            return

        # Normal response
        resp_body = json.dumps(cfg.response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)


class MockLLMServer:
    """OpenAI-compatible mock on a threaded server.

    Threaded since ticket #38: a hung `timeout` call must not block the requests
    that follow it (the single-threaded server serialized the whole campaign).
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0, config: MockConfig | None = None):
        self.host = host
        self.port = port
        self.config = config or MockConfig()
        self.httpd: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._started = threading.Event()
        self._handler_cls: type | None = None

    def start(self) -> int:
        handler_cls = type(
            "DynamicHandler",
            (_Handler,),
            {"config": self.config, "counter": 0, "lock": threading.Lock()},
        )
        self._handler_cls = handler_cls
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self._started.wait(timeout=1.0)
        return self.port

    @property
    def request_count(self) -> int:
        """Calls the mock has answered (ticket #40 diagnostic and tests)."""
        return int(getattr(self._handler_cls, "counter", 0)) if self._handler_cls else 0

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


def start_mock_server(port: int = 0, latency_ms: int = 50, error_mode: str | None = None) -> tuple[MockLLMServer, int]:
    cfg = MockConfig(latency_ms=latency_ms, error_mode=error_mode)
    srv = MockLLMServer(port=port, config=cfg)
    actual_port = srv.start()
    return srv, actual_port
