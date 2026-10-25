"""CLI entry point for bench harness."""

import argparse
import sys

from bench.runner import cmd_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bench", description="Agent benchmark harness")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run a benchmark scenario against an agent")
    run_p.add_argument("agent", help="Path to agent descriptor TOML file")
    run_p.add_argument("scenario", help="Path to scenario definition TOML file")
    run_p.add_argument("--proc-root", default="/proc", help="Root path for /proc (default: /proc)")
    run_p.add_argument("--cgroup-root", default="/sys/fs/cgroup", help="Root path for cgroup v2 sysfs")
    run_p.add_argument("--runs-dir", default="runs", help="Directory for run output (default: runs)")
    run_p.add_argument("--mock-llm-port", type=int, help="Start mock LLM server on this port (OpenAI compatible)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        return 1

    if args.command == "run":
        rc = cmd_run(args)
        sys.exit(rc)

    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
