"""Helpers for CLI-seam tests that route scenario requests to a candidate.

Ticket #40: the harness posts to the descriptor's ``chat_url``, so tests need a
fixture candidate that actually listens. Tests pick a free port before writing
the descriptor, because the endpoint must be known before the agent starts.
"""

from __future__ import annotations

import socket
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAT_AGENT = ROOT / "tests" / "fixtures" / "chat_agent.py"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_chat_descriptor(
    base: Path,
    port: int,
    *,
    name: str = "chat-fixture",
    upstream_via_env: bool = False,
    delay_ms: int = 0,
    behavior: str = "",
    upstream_timeout: float = 0.3,
) -> Path:
    """Descriptor whose chat endpoint is the fixture candidate on ``port``."""
    workdir = base / "wd"
    workdir.mkdir(parents=True, exist_ok=True)
    desc = base / "agent.toml"
    env_line = (
        'env = { BENCH_TEST_UPSTREAM = "{mock_url}" }\n' if upstream_via_env else ""
    )
    desc.write_text(textwrap.dedent(f"""
        name = "{name}"
        repo_url = "https://example.com/chat"
        version = "0.0.1"
        mode = "native"
        chat_url = "http://127.0.0.1:{port}/v1/chat/completions"
        start_command = ["python3", "{CHAT_AGENT}", "{workdir}", "{port}", "-", "{delay_ms}", "{behavior}", "{upstream_timeout}"]
        workdir = "{workdir}"
        {env_line}
        [healthcheck]
        type = "file"
        value = "{workdir / 'healthy'}"
        timeout_sec = 10
    """))
    return desc


def requests_seen(workdir: Path) -> list[dict]:
    """Requests the fixture candidate actually served (one JSON object per line)."""
    import json

    path = workdir / "chat_requests.log"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
