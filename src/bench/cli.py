"""CLI entry point for bench harness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bench.runner import cmd_run
from bench.report import generate_report, load_records

EXIT_CODE_DOC = """\
exit codes:
  0  ok
  1  usage/setup error (missing descriptor/scenario, bad TOML)
  2  guard: OOM counter reached threshold
  3  guard: MemAvailable below minimum
  4  guard: health lost (failed healthchecks reached limit)
  5  guard: API budget exceeded (requests/tokens)
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bench",
        description="Agent benchmark harness",
        epilog=EXIT_CODE_DOC,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run a benchmark scenario against an agent", epilog=EXIT_CODE_DOC,
                           formatter_class=argparse.RawDescriptionHelpFormatter)
    run_p.add_argument("agent", help="Path to agent descriptor TOML file")
    run_p.add_argument("scenario", help="Path to scenario definition TOML file")
    run_p.add_argument("--proc-root", default="/proc", help="Root path for /proc (default: /proc)")
    run_p.add_argument("--cgroup-root", default="/sys/fs/cgroup", help="Root path for cgroup v2 sysfs")
    run_p.add_argument("--runs-dir", default="runs", help="Directory for run output (default: runs)")
    run_p.add_argument("--mock-llm-port", type=int, help="Start mock LLM server on this port (OpenAI compatible)")
    run_p.add_argument("--dry-run", action="store_true", help="Print execution plan without running anything")
    run_p.add_argument("--docker-bin", default="docker", help="Docker CLI binary (or fixture stub) for mode=docker descriptors")

    report_p = sub.add_parser("report", help="Generate markdown report from accumulated run records")
    report_p.add_argument("--runs-dir", default="runs", help="Directory with run outputs (default: runs)")
    report_p.add_argument("--output", default="report.md", help="Output markdown file (default: report.md)")

    return parser


def cmd_report(args) -> int:
    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"Error: runs directory not found: {runs_dir}", file=sys.stderr)
        return 1
    records = load_records(runs_dir)
    if not records:
        print(f"Error: no run records found under {runs_dir}", file=sys.stderr)
        return 1
    report = generate_report(records)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report)
    print(json.dumps({"status": "ok", "records": len(records), "report_path": str(output)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(sys.stderr)
        return 1

    if args.command == "run":
        rc = cmd_run(args)
        sys.exit(rc)

    if args.command == "report":
        sys.exit(cmd_report(args))

    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
