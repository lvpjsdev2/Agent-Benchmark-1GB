"""Direct tests for the mock LLM server's scripted behaviour (ticket #38).

The CLI-seam tests cover 429 through the runner; here the server is exercised
directly, because the timeout mode must hang exactly the targeted call and leave
its neighbours responsive — a property a scenario record can only show
indirectly.
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request

from bench.mock.server import MockConfig, MockLLMServer


def _start(**cfg_kwargs) -> tuple[MockLLMServer, str]:
    server = MockLLMServer(port=0, config=MockConfig(**cfg_kwargs))
    port = server.start()
    return server, f"http://127.0.0.1:{port}/v1/chat/completions"


def _post(url: str, timeout: float) -> tuple[int | None, Exception | None, float]:
    """POST once; returns (status, error, elapsed). Status is None on timeout."""
    req = urllib.request.Request(
        url, method="POST", data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            return resp.status, None, time.monotonic() - started
    except urllib.error.HTTPError as exc:
        return exc.code, exc, time.monotonic() - started
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        return None, exc, time.monotonic() - started


def test_429_without_target_errors_every_call():
    server, url = _start(error_mode="429", latency_ms=0)
    try:
        assert [_post(url, timeout=2.0)[0] for _ in range(3)] == [429, 429, 429]
    finally:
        server.stop()


def test_429_targets_only_the_configured_call():
    server, url = _start(error_mode="429", error_on_call=2, latency_ms=0)
    try:
        assert _post(url, timeout=2.0)[0] == 200
        assert _post(url, timeout=2.0)[0] == 429
        assert _post(url, timeout=2.0)[0] == 200
    finally:
        server.stop()


def test_500_targets_only_the_configured_call():
    server, url = _start(error_mode="500", error_on_call=1, latency_ms=0)
    try:
        assert _post(url, timeout=2.0)[0] == 500
        assert _post(url, timeout=2.0)[0] == 200
    finally:
        server.stop()


def test_timeout_hangs_only_the_targeted_call():
    """Ticket #38: the target times out, its neighbours answer with real latency."""
    server, url = _start(
        error_mode="timeout", error_on_call=2, latency_ms=0, timeout_sleep_sec=1.0,
    )
    try:
        status, err, _ = _post(url, timeout=0.3)
        assert status == 200 and err is None  # call 1: untouched
        status, err, elapsed = _post(url, timeout=0.3)
        assert status is None and err is not None, "targeted call must time out"
        assert elapsed < 0.9, "client must give up before the server wakes up"
        # The hung call still sleeps in its own thread: the next request must not
        # queue behind it.
        status, err, elapsed = _post(url, timeout=0.3)
        assert status == 200 and err is None
        assert elapsed < 0.3
    finally:
        server.stop()


def test_timeout_without_target_hangs_every_call_without_500():
    server, url = _start(error_mode="timeout", latency_ms=0, timeout_sleep_sec=0.5)
    try:
        for _ in range(2):
            status, err, elapsed = _post(url, timeout=0.2)
            assert status is None and err is not None, "must hang, not answer 500"
            assert elapsed < 0.45
    finally:
        server.stop()


def test_server_stays_responsive_while_a_call_is_hung():
    """A call stuck in the timeout sleep must not serialize the server."""
    server, url = _start(
        error_mode="timeout", error_on_call=1, latency_ms=0, timeout_sleep_sec=1.0,
    )
    try:
        hung = threading.Thread(target=_post, args=(url, 0.3))
        hung.start()
        time.sleep(0.05)  # the hung request is now sleeping server-side
        status, err, elapsed = _post(url, timeout=0.8)
        assert status == 200 and err is None
        assert elapsed < 0.5, "second client waited behind the hung request"
        hung.join()
    finally:
        server.stop()
