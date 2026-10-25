# Agent-Benchmark-1GB

A public benchmark for lightweight agents solving real Python repository issues inside a 1 GB disk envelope.

**Status:** design phase. The implementation plan is in [PLAN.md](PLAN.md); no harness code exists yet.

## What it measures

- Six agents: ZeroClaw, ZeptoClaw, PicoClaw, Picobot, PennyClaw and Moltis.
- 300 public tasks derived from real merged PRs, Python only, scored as pass@1.
- 1 GiB of disk per run (image, dependencies, workspace and artifacts), 4 GiB RAM, 60 minutes.
- Sealed runs: the model gateway is the only network egress.
- One fixed model per release; results live in this repository, with no hosted leaderboard.

## Why another benchmark

Claw-SWE-Bench already covers 350 real issues across eight languages without a disk envelope. This benchmark fixes the envelope at 1 GiB and asks which lightweight agents still work when the environment itself is the constraint.

## Documents

- [CONTEXT.md](CONTEXT.md) — the project vocabulary.
- [PLAN.md](PLAN.md) — architecture, task pipeline, agent contract, milestones.
- [docs/adr](docs/adr/) — the decisions behind the design.
