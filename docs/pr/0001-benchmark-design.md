# PR — Agent-Benchmark-1GB initial design

## Summary

```
 benchmark-repo/
 ├── README.md          # Entry point — a one-page README becomes the project landing page
 ├── CONTEXT.md         # New — project vocabulary (Benchmark, Agent, Task, Manifest, Envelope…)
 ├── PLAN.md            # New — architecture, agent contract, sandbox, gateway, milestones M0–M6
 └── docs/
      ├── adr/          # New — 7 design decisions (black-box OCI, 1 GB envelope, sealed runs…)
      └── pr/
           └── 0001-benchmark-design.md   # New — this PR body
```

This PR freezes the **design phase** of the agent benchmark: six lightweight Claw agents, 300 public Python tasks from real merged PRs, pass@1, evaluated inside a 1 GiB disk envelope with 4 GiB RAM and a 60-minute wall clock, using a sealed-run model gateway and one fixed model per release.

No harness code yet. The implementation plan is in [PLAN.md](../PLAN.md); the vocabulary is in [CONTEXT.md](../CONTEXT.md); the decisions are in [docs/adr](../docs/adr/).

## Evidence

- **Before:** project was a single-line README, no vocabulary, no plan, no decisions.

  ```text
  # Agent-Benchmark-1GB
  ```

- **After:** the README becomes a navigable landing page and the repo gains a design skeleton.

  ```diff
   # Agent-Benchmark-1GB
  + A public benchmark for lightweight agents solving real Python repository issues
  + inside a 1 GB disk envelope.
  +
  + **Status:** design phase. The implementation plan is in [PLAN.md](PLAN.md);
  + no harness code exists yet.
  +
  + ## What it measures
  + - Six agents: ZeroClaw, ZeptoClaw, PicoClaw, Picobot, PennyClaw and Moltis.
  + - 300 public tasks derived from real merged PRs, Python only, scored as pass@1.
  + - 1 GiB of disk per run (image, dependencies, workspace and artifacts), 4 GiB RAM,
  +   60 minutes.
  + - Sealed runs: the model gateway is the only network egress.
  + - One fixed model per release; results live in this repository, with no hosted
  +   leaderboard.
  +
  + ## Why another benchmark
  + Claw-SWE-Bench already covers 350 real issues across eight languages without a disk
  + envelope. This benchmark fixes the envelope at 1 GiB and asks which lightweight agents
  + still work when the environment itself is the constraint.
  +
  + ## Documents
  + - [CONTEXT.md](CONTEXT.md) — the project vocabulary.
  + - [PLAN.md](PLAN.md) — architecture, task pipeline, agent contract, milestones.
  + - [docs/adr](docs/adr/) — the decisions behind the design.
  ```

  Same contents that shipped in the chat are now on disk:
  - [CONTEXT.md](../CONTEXT.md) — vocabulary.
  - [PLAN.md](../PLAN.md) — full plan, including M0–M6, risks, and definition of done.
  - [docs/adr/0001-black-box-oci-agents.md](../docs/adr/0001-black-box-oci-agents.md)
  - [docs/adr/0002-disk-envelope.md](../docs/adr/0002-disk-envelope.md)
  - [docs/adr/0003-sealed-runs.md](../docs/adr/0003-sealed-runs.md)
  - [docs/adr/0004-public-task-set.md](../docs/adr/0004-public-task-set.md)
  - [docs/adr/0005-envelope-niche.md](../docs/adr/0005-envelope-niche.md)
  - [docs/adr/0006-fixed-model.md](../docs/adr/0006-fixed-model.md)
  - [docs/adr/0007-task-manifests.md](../docs/adr/0007-task-manifests.md)

## Merge Danger

**Door:** one-way, but low-cost to reverse before implementation starts.

The design locks several choices that are cheap now and painful later: the 1 GiB envelope, sealed runs with a model gateway, one fixed model per release, the public-and-frozen v1 task set, and black-box OCI agents. None of this is irreversible — we can rewrite the plan and ADRs in a follow-up PR — but the next implementation step (M0 harness skeleton, agent driver spikes, and the pilot task set) will be written against these exact constraints, so merging the design is the point where the project becomes real rather than exploratory.

**Blast Radius:** design-radius.

No runtime code, no Docker images, no API keys, no benchmark results yet. The risk is not that something breaks — it is that we commit to a direction. The good direction is the one we spent the whole session narrowing down, with six agents researched, a prior-art scan (Claw-SWE-Bench), and a model-cost scan (free tiers vs GLM 5.1 vs Qwen 3.6). The body captures that reasoning so a future reviewer does not have to re-grill the same questions.

### Todo before merge

- [x] Grilling session finished and user confirmed the common understanding.
- [x] PLAN.md, CONTEXT.md, all ADRs, and the README update written to disk.
- [ ] M0 harness skeleton (next PR or branch).
- [ ] Agent driver spikes for PennyClaw and Moltis (next phase).

---

*Generated with Codebuff 🤖 agent session.*
