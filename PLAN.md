# Agent Benchmark 1GB — Implementation Plan

Status: design confirmed, implementation not started.

Companion documents: [CONTEXT.md](CONTEXT.md) for the vocabulary and [docs/adr](docs/adr/) for the decisions this plan executes.

## 1. Goal

Ship a public, reproducible benchmark that answers one question:

> Which lightweight agent runtimes can solve real Python repository issues when the image, dependencies, workspace and produced artifacts must all fit inside a 1 GB disk envelope?

The first release compares six agents on 300 public tasks and reports pass@1 plus efficiency metrics. Results live in this repository; there is no hosted leaderboard.

## 2. Non-goals

- Training or fine-tuning models.
- A private holdout or a hosted submission service.
- Languages other than Python in v1.
- Comparing model quality; the model is held fixed per release.
- Benchmarking agent scaffolds that the benchmark itself implements.
- Redistributing third-party agent images or task repositories.

## 3. Fixed decisions

| Area | Decision | Record |
|---|---|---|
| Unit under test | Complete agents, evaluated as black boxes through an OCI image contract | [ADR 0001](docs/adr/0001-black-box-oci-agents.md) |
| Envelope | 1 GiB of disk per run: image + dependencies + workspace + artifacts | [ADR 0002](docs/adr/0002-disk-envelope.md) |
| Network | Sealed run; the model gateway is the only egress | [ADR 0003](docs/adr/0003-sealed-runs.md) |
| Task set | Public, no holdout, frozen within a version; v2 is a new set | [ADR 0004](docs/adr/0004-public-task-set.md) |
| Niche | 1 GB envelope + Claw focus; Python-only v1 | [ADR 0005](docs/adr/0005-envelope-niche.md) |
| Model | One fixed model per release; pilot on a free model first | [ADR 0006](docs/adr/0006-fixed-model.md) |
| Task distribution | Manifests + local build; no prebuilt task images | [ADR 0007](docs/adr/0007-task-manifests.md) |

Other fixed parameters:

- Tasks: 300, Python only, drawn from real merged PRs in permissively licensed repositories.
- Agents: ZeroClaw, ZeptoClaw, PicoClaw, Picobot, PennyClaw, Moltis.
- Scoring: binary pass@1; a task counts only when all hidden tests pass and the envelope is respected.
- Time budget: 60 minutes of wall-clock per run.
- Memory budget: 4 GiB of RAM per run.
- CPUs: 4 per run (fixed so timing is comparable).
- Task cache: workspace target ≤700 MiB, leaving room for the agent image and writable layer.
- Harness: Python 3.12, managed with `uv`.
- Harness license: MIT. Task sources: permissive licenses only (MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause), with attribution.

## 4. System overview

```text
bench run
  ├─ load task manifest
  ├─ ensure setup workspace in .bench/cache/<task_id>
  ├─ copy workspace to .bench/runs/<run_id>/workspace
  ├─ start model gateway (container, internal network + egress network)
  ├─ start agent container (agent image, internal network only,
  │   4 GiB RAM, 4 CPUs, workspace + task.json + logs mounted)
  ├─ driver inside the image runs the agent against the task
  ├─ capture git diff, logs, tokens, disk, time; kill on budget breach
  ├─ apply diff to a clean workspace
  ├─ run hidden tests in a clean task container (no network)
  └─ write result JSON; update summary
```

Components:

| Component | Responsibility |
|---|---|
| `bench` CLI | Setup, validation, agent builds, runs, pilots, reports |
| Task registry | Manifests, issues, hidden tests, gold patches, index |
| Setup builder | Builds a task workspace and venv in a Linux container |
| Sandbox | Docker/Podman lifecycle, limits, network isolation, measurement |
| Model gateway | OpenAI-compatible proxy, model pinning, key injection, token accounting |
| Agent images | One OCI image per agent, containing the agent and its driver |
| Evaluator | Applies the diff and runs hidden tests in a clean container |
| Results store | Per-run JSON, summary CSV, Markdown table |

## 5. Repository layout

```text
.
├── CONTEXT.md
├── PLAN.md
├── README.md
├── LICENSE
├── ATTRIBUTION.md
├── pyproject.toml
├── uv.lock
├── bench.toml
├── bench/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py          # pydantic schemas
│   ├── tasks.py           # manifest loading, index
│   ├── setup.py           # workspace builder
│   ├── sandbox.py         # docker lifecycle, limits, measurement
│   ├── gateway.py         # model gateway process/container control
│   ├── runners.py         # agent run orchestration
│   ├── evaluate.py        # diff application, hidden tests
│   ├── results.py         # JSON/CSV/Markdown aggregation
│   └── agents.py          # image build and smoke tests
├── docker/
│   ├── task-builder.Dockerfile
│   ├── gateway.Dockerfile
│   └── base.Dockerfile
├── agents/
│   ├── zeroclaw/
│   │   ├── Dockerfile
│   │   ├── driver.py
│   │   └── VERSION
│   ├── zeptoclaw/
│   ├── picoclaw/
│   ├── picobot/
│   ├── pennyclaw/
│   └── moltis/
├── tasks/
│   ├── v1/
│   │   ├── index.json
│   │   └── <task_id>/
│   │       ├── task.yaml
│   │       ├── issue.md
│   │       ├── gold.patch
│   │       └── tests/
│   └── README.md
├── results/
│   └── v1/
│       ├── README.md
│       ├── summary.csv
│       └── <agent>/<task_id>.json
├── docs/
│   └── adr/
└── tests/
    ├── fixtures/
    ├── test_manifest.py
    ├── test_envelope.py
    ├── test_gateway.py
    ├── test_evaluate.py
    └── test_end_to_end.py
```

`.bench/` is git-ignored: workspace cache, run directories, logs, Docker volumes.

## 6. Task model

### 6.1 Manifest

`tasks/v1/<task_id>/task.yaml`:

```yaml
id: pallets__flask-1234
version: 1
repo:
  url: https://github.com/pallets/flask
  base_commit: 0123456789abcdef0123456789abcdef01234567
  license: BSD-3-Clause
issue:
  title: "Short issue title"
  body_file: issue.md
  url: https://github.com/pallets/flask/issues/1234
tests:
  hidden_dir: tests
  command: "python -m pytest -q /tests"
  timeout_seconds: 900
gold_patch: gold.patch
environment:
  python: "3.12"
  install: "python -m pip install -r requirements.txt"
  test_install: "python -m pip install pytest"
metadata:
  pr_url: https://github.com/pallets/flask/pull/1235
  merged_at: "2026-03-14T12:00:00Z"
  files_changed: 4
  lines_changed: 87
  workspace_bytes: 412000000
  difficulty: medium
```

Rules:

- `id` is `owner__repo-prnumber`, lowercase, filesystem-safe.
- `issue.md` contains only the issue title/body the agent sees. Do not include the PR link, test names or gold patch.
- `tests/` is public in this repository but is **not mounted** during the agent phase.
- `gold.patch` is public but is **not mounted** during the agent phase.
- `environment.install` runs during setup, with network allowed.
- `environment.test_install` runs during setup; hidden-test dependencies live in the workspace venv and count against the envelope.
- `workspace_bytes` is recorded by setup; the run fails fast if it cannot fit.

`tasks/v1/index.json` is a list of the same metadata without test contents, used for filtering and reporting.

### 6.2 Task selection

Mine candidates with the GitHub API (token required, cached responses):

1. Repository license in the allowlist: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause.
2. Merged PR in the 12 months before the v1 cutoff, with a linked issue.
3. PR changes tests and non-test code.
4. Diff size 5–300 changed lines across 1–15 files; no generated, vendored or binary files.
5. Python 3.12 compatible; no GPU, service dependency, submodule or private package.
6. Package manager is pip or uv; Poetry/Pipenv-only repositories are out of scope for v1.
7. The repository's tests run offline after dependencies are installed.
8. The workspace with venv targets ≤700 MiB.
9. The issue text is understandable without the PR and contains no secrets or personal data.

Collect 600–900 candidates for a 300-task release.

### 6.3 Validation

For every candidate:

1. Clone at `base_commit`; build the workspace in the task builder.
2. Apply `gold.patch`; run the hidden tests; they must pass.
3. Revert the patch; run the hidden tests; at least one must fail.
4. Repeat the gold run three times; reject flaky tests.
5. Run the hidden tests with networking disabled.
6. Measure workspace bytes and record the checksum.
7. Store the manifest, issue, tests, gold patch and metadata.

`bench validate --task <id>` performs these steps; `bench validate --all` must be green before a release is frozen.

### 6.4 Calibration

The task set should discriminate, not floor or ceiling. After the pilot:

- Run a strong and a weak baseline agent on a stratified sample.
- Keep tasks where the strong agent passes roughly 40–70% and the weak agent roughly 5–30%.
- Balance by repository, diff size and test count.
- Target 300 tasks; if the candidate pool cannot support the target, relax the size window before relaxing licensing or test quality.

Difficulty labels in manifests are advisory; the pilot numbers are the source of truth.

## 7. Setup and workspace

### 7.1 Builder

`docker/task-builder.Dockerfile`:

- Base: `python:3.12-slim`.
- Tools: `git`, `curl`, `ca-certificates`, `build-essential`, `python3-venv`, `pip`, `uv`.
- No model keys, no agent code.

Setup runs in Linux so the workspace venv is usable inside the agent image. The host may be macOS; the venv must never be built on the host.

### 7.2 Setup steps

```text
bench setup --task <id>
  ├─ clone repo at base_commit into .bench/cache/<task_id>/workspace
  ├─ create .venv with Python 3.12
  ├─ run environment.install and environment.test_install
  ├─ initialize git repo at base_commit, clean tree
  ├─ run a smoke import/pytest collection
  ├─ measure workspace bytes
  └─ write .bench/cache/<task_id>/setup.json
```

The cache is reusable. `--force` rebuilds it. If the build fails, the task is rejected, not patched by hand.

### 7.3 Per-run workspace

Each run gets a copy-on-write clone of the cached workspace when the filesystem supports it (`cp -c` on APFS, `cp --reflink=auto` on Linux). Fall back to `cp -a`. The evaluator uses a second clean copy plus the agent's diff; it never trusts the agent's working tree.

## 8. Agent contract

### 8.1 Image

Each agent is built from source in a multi-stage Dockerfile and copied into a common runtime base:

- Runtime base: `python:3.12-slim` + `git`, `bash`, `curl`, `ca-certificates`, `tini`.
- The agent binary/CLI is copied from the build stage.
- The driver is copied to `/bench/driver.py`.
- No API keys, no task data, no hidden tests in the image.
- Images are pinned by digest in `agents/<name>/VERSION` and in results.

Building from source avoids relying on a vendor image's base OS and gives one Python/glibc baseline for the workspace venv. Record the upstream commit/tag for each agent.

### 8.2 Runtime interface

The harness sets:

| Variable | Meaning |
|---|---|
| `BENCH_TASK_FILE` | `/bench/task.json` |
| `BENCH_WORKSPACE` | `/workspace` |
| `BENCH_MODEL_BASE_URL` | `http://gateway:8080/v1` |
| `BENCH_MODEL_API_KEY` | Dummy token; the gateway injects the real key |
| `BENCH_MODEL_NAME` | Pinned model ID |
| `BENCH_TIME_BUDGET_SECONDS` | `3600` |
| `BENCH_RUN_ID` | Unique run identifier |

`/bench/task.json`:

```json
{
  "id": "pallets__flask-1234",
  "issue": "Issue title and body...",
  "workspace": "/workspace",
  "time_budget_seconds": 3600
}
```

The driver:

1. Reads the task and configures the agent to use the gateway as an OpenAI-compatible provider.
2. Runs the agent with `/workspace` as its working directory.
3. Writes logs to `/bench/logs/`.
4. Exits 0 when the agent is done; any non-zero exit is a run failure.

The harness does **not** know how to drive an individual agent. Server-style agents (PennyClaw, Moltis) ship their own driver that starts the server, submits the task, waits and exits.

### 8.3 Diff capture

After the driver exits:

```text
git -C /workspace add -A
git -C /workspace diff --cached --binary > agent.patch
git -C /workspace status --porcelain > status.txt
```

`.bench/` inside the workspace is git-ignored and excluded from the diff. If `.git` is missing or corrupted, fall back to a file-tree diff against the cached base workspace; the run is marked `diff_recovered`.

### 8.4 Agent integrations

| Agent | Upstream | Build | Headless invocation / driver | Notes |
|---|---|---|---|---|
| ZeroClaw | `github.com/zeroclaw-labs/zeroclaw` | Rust, MIT OR Apache-2.0 | `zeroclaw agent -a <alias> -m "<task>"` | Configure provider to gateway; set the risk policy so unattended file edits are allowed. |
| ZeptoClaw | `github.com/qhkm/zeptoclaw` | Rust, Apache-2.0 | `zeptoclaw agent -m "<task>" --template coder` | Configure provider; verify the approval policy does not block unattended edits. |
| PicoClaw | `github.com/sipeed/picoclaw` | Go, MIT | `picoclaw agent -m "<task>"` | Set workspace to `/workspace`; configure `.security.yml`/provider. |
| Picobot | `github.com/louisho5/picobot` | Go, MIT | `picobot agent -m "<task>"` | OpenAI-compatible base URL; workspace config. |
| PennyClaw | `github.com/mandarl/pennyclaw` | Go, MIT | Driver starts `pennyclaw`, POSTs `/api/chat`, waits, exits | No one-shot CLI and no official image; build from source. |
| Moltis | `github.com/moltis-org/moltis` | Rust, MIT | Driver starts `moltis` and uses ACP stdio or its HTTP API | No one-shot prompt CLI; spike the ACP/HTTP path before building the full matrix. |

Upstream details above are as of October 2026. Re-verify each repository, license, build command and headless path before M2 and pin the exact commit/tag in `agents/<name>/VERSION`.

Each agent gets a smoke task: a tiny repository where the agent must create a file or fix an obvious bug. A smoke run proves the driver, gateway and diff capture before any benchmark task is used.

## 9. Sandbox and envelope

### 9.1 Docker networks

- `bench-internal`: `internal=true`, no external route.
- `bench-egress`: normal bridge network.
- The model gateway attaches to both.
- The agent container attaches only to `bench-internal`; it can resolve `gateway` and nothing else.

No Docker socket is mounted into the agent container. No host home directory is mounted.

### 9.2 Agent container

```text
docker run --rm \
  --name bench-<run_id> \
  --network bench-internal \
  --memory 4g --memory-swap 4g \
  --cpus 4 --pids-limit 512 \
  --security-opt no-new-privileges \
  --init \
  -v <workspace>:/workspace \
  -v <logs>:/bench/logs \
  -v <task.json>:/bench/task.json:ro \
  -e BENCH_TASK_FILE=/bench/task.json \
  -e BENCH_WORKSPACE=/workspace \
  -e BENCH_MODEL_BASE_URL=http://gateway:8080/v1 \
  -e BENCH_MODEL_API_KEY=bench-dummy \
  -e BENCH_MODEL_NAME=<pinned> \
  -e BENCH_TIME_BUDGET_SECONDS=3600 \
  <agent-image>
```

The container runs the image's entrypoint; the harness does not override the command.

### 9.3 Enforcement

- **Time:** kill the container at 3600 seconds; record `timed_out`.
- **Memory:** Docker `--memory`; read `State.OOMKilled`; record `oom_killed`.
- **Disk:** measure `image_size + workspace_bytes + container_writable_bytes`.
  - `image_size`: uncompressed `docker image inspect` size.
  - `workspace_bytes`: `du -sb` on the workspace.
  - `container_writable_bytes`: Docker's container `SizeRw`, captured before the container is removed.
  - A watchdog polls every 30 seconds; if the total exceeds 1 GiB, kill the run and mark `envelope_exceeded`.
  - The run fails if the final total exceeds 1 GiB even when the watchdog missed it.
- **Envelope constant:** 1 GiB = 1,073,741,824 bytes. The prose says "1 GB"; the code uses the binary budget and reports bytes.
- **CPU:** `--cpus 4`; record the host's CPU count and fail the run if the host cannot provide 4 CPUs.

### 9.4 Why not a hard disk quota

Docker's writable-layer quota is not portable across storage drivers and does not cover bind-mounted workspaces. The benchmark measures image + workspace + writable layer and enforces the cap with a watchdog plus a final check. This is less strict than a kernel quota but portable and transparent.

## 10. Model gateway

### 10.1 Protocol

- OpenAI-compatible `POST /v1/chat/completions` and `GET /v1/models`.
- Accepts `Authorization: Bearer bench-dummy` from the agent.
- Injects the real provider key; the agent never sees it.
- Rejects requests whose `model` is not the pinned model; forwards the exact pinned ID upstream.
- Supports streaming and non-streaming responses; forwards SSE chunks.
- Applies a per-request timeout and bounded retries for 429/5xx.
- Logs request metadata to `/logs/usage.jsonl`: run ID, model, prompt/completion tokens, cache tokens, latency, status. No prompt or completion content by default.

### 10.2 Configuration

`bench.toml`:

```toml
[model]
id = "recursive/flint-v1.0:free"
provider = "openrouter"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
temperature = 0
max_output_tokens = 8192

[pricing]
input_per_mtok = 0.0
output_per_mtok = 0.0

[sandbox]
memory = "4g"
cpus = 4
time_seconds = 3600
envelope_bytes = 1073741824
```

Secrets come from the environment or a local `.env` that is git-ignored. No key is written into an image, a result or a log.

### 10.3 Model choice

- **Pilot:** `recursive/flint-v1.0:free` on OpenRouter. Smoke-test tool calling first. If it fails, fall back to `thinkingmachines/inkling-small:free` or `nvidia/nemotron-3-ultra-550b-a55b:free`.
- **Free-tier limits:** OpenRouter reports 20 requests/minute and 50 requests/day, or 1,000/day after at least $10 in credits. At 50 requests/day a 90-run pilot can stretch to weeks; the one-time $10 credit is the practical path, or reduce the first pass to 10 tasks × 3 agents.
- **Release gate:** after the pilot, estimate tokens/cost from real runs. Choose GLM 5.1 (paid, $1.40/$4.40 per million input/output tokens at the time of writing) or a free model. The release model is pinned in `bench.toml` and recorded in every result.
- **ChatGPT subscriptions do not include API access.** The benchmark needs an API key; Codex plan usage is not a substitute. If the owner has OpenAI API credits, the gateway can use OpenAI as the provider.

## 11. Evaluation

1. Take the agent's `agent.patch` and a clean copy of the task workspace.
2. Apply with `git apply --3way`; fail the run if it does not apply.
3. Mount the hidden tests read-only at `/tests`.
4. Run `tests.command` with cwd `/workspace` in a clean task container (task builder image, no network, clean workspace copy and its verified venv).
5. Pass only if the command exits 0 and all tests pass.
6. Record exit code, duration and a truncated log tail.

The evaluator never runs inside the agent container. The agent cannot modify the tests, the venv used for evaluation, or the test command.

Flakiness is handled at task-validation time (three gold runs). Evaluation runs once; retries are not used to turn a failure into a pass.

Failure reasons (one per result):

- `timeout`
- `oom`
- `envelope_exceeded`
- `agent_error` (driver non-zero)
- `diff_missing`
- `diff_apply_failed`
- `tests_failed`
- `harness_error`

## 12. Results

### 12.1 Per-run JSON

`results/v1/<agent>/<task_id>.json`:

```json
{
  "run_id": "2026-10-25T12-00-00Z-zeroclaw-pallets__flask-1234",
  "agent": "zeroclaw",
  "agent_version": "v0.8.6",
  "agent_image_digest": "sha256:...",
  "task_id": "pallets__flask-1234",
  "model": {"id": "recursive/flint-v1.0:free", "provider": "openrouter"},
  "started_at": "2026-10-25T12:00:00Z",
  "duration_seconds": 1432,
  "timed_out": false,
  "oom_killed": false,
  "envelope": {
    "image_bytes": 214000000,
    "workspace_bytes": 412000000,
    "writable_bytes": 12000000,
    "total_bytes": 638000000
  },
  "tokens": {"input": 182000, "output": 14000, "cached": 0},
  "cost_usd": 0.0,
  "diff_bytes": 4210,
  "tests": {"passed": true, "exit_code": 0, "duration_seconds": 41},
  "pass": true,
  "failure_reason": null
}
```

### 12.2 Summary

`results/v1/summary.csv` columns:

`agent, tasks, pass_at_1, ci95_low, ci95_high, median_duration_s, p95_duration_s, median_total_disk_mb, max_total_disk_mb, total_input_tokens, total_output_tokens, total_cost_usd, timeouts, ooms, envelope_failures, agent_error, diff_failures, test_failures, model, task_set_hash, platform`.

`results/v1/README.md` contains the Markdown table, the methodology, the model, the agent versions/digests, the task-set hash, the platform and the caveats.

### 12.3 Publication

Results are committed to the repository. There is no hosted leaderboard. A third party can reproduce a row by cloning the repo, setting the API key, running `bench setup`, building the agent images and running the matrix. Results submitted by others are accepted as pull requests only with the raw JSON and logs necessary to verify them.

## 13. CLI

```text
bench doctor                      # Python, Docker, disk, API key, CPU/RAM
bench setup --task <id>           # build one workspace
bench setup --all                 # build all cached workspaces
bench validate --task <id>        # gold/base/flaky/size checks
bench validate --all
bench agents build --agent <name> # build one agent image
bench agents build --all
bench agents smoke --agent <name> # tiny task, no benchmark task
bench run --agent <name> --task <id>
bench run --agent <name> --all
bench matrix --agents all --tasks all
bench pilot --tasks 30 --agents zeroclaw,picoclaw,moltis
bench report --results results/v1
```

Global options: `--config bench.toml`, `--results-dir`, `--dry-run`, `--verbose`.

`bench doctor` is the first command in the README; it should fail with an actionable message if Docker, the API key, 4 CPUs or enough disk is missing.

## 14. Milestones

| Milestone | Scope | Acceptance |
|---|---|---|
| M0 — Skeleton | Package, CLI, config, manifest schema, fixtures, dummy task, dummy agent, evaluator, results | `bench run` on the dummy task passes without a model |
| M1 — Sandbox + gateway | Docker networks, limits, watchdog, gateway, token accounting | One real task, one agent, one model call; sealed network verified |
| M2 — Agent images | Six multi-stage Dockerfiles + drivers + smoke task | All six build and pass smoke; per-agent notes documented |
| M3 — Task pipeline | GitHub miner, validator, manifests, 30-task pilot set | `bench validate --all` green; workspace ≤700 MiB |
| M4 — Free pilot | 30 tasks × 3 agents on the free model | Results table, token/cost report, harness fixes; release-model decision |
| M5 — v1 task set | 300 validated, calibrated tasks; frozen index + hash | Task-set hash recorded; `bench setup --all` reproducible |
| M6 — Full matrix | 6 agents × 300 tasks; results, README, LICENSE, attribution | `bench report` matches raw JSON; clean-clone reproduction works |

## 15. Testing and CI

- Unit tests: manifest parsing, envelope accounting, diff capture, gateway model pinning, results aggregation, Wilson intervals.
- Integration: dummy agent image on a fixture task; fake gateway with canned responses; no real model calls.
- End-to-end: `bench run` on a fixture task with the fake gateway; assert result JSON and summary.
- Lint/type: `ruff`, `mypy`.
- CI: unit and integration tests on Linux amd64; Docker smoke test with the dummy agent; no full matrix (cost).
- Release checks: `bench validate --all`, `bench agents smoke --all`, a 10-task sample matrix, result reproducibility.

## 16. Security

- API keys only in environment/local `.env`; never in images, results or logs.
- The gateway logs metadata, not prompts or completions, by default.
- No Docker socket in the agent container; no host home mount; no host network.
- Agent containers attach only to the internal network; the gateway is the only egress.
- Hidden tests and gold patches are not mounted during the agent phase.
- Evaluation runs in a clean container with a clean workspace copy and the task's verified venv.
- Task repositories and agent sources are pinned by commit and license; `ATTRIBUTION.md` records them.
- Results include image digests and task-set hashes so a reader can audit what ran.

## 17. Risks and open gates

| Risk | Mitigation |
|---|---|
| Free model cannot do tool calls or is too weak | Smoke-test tool calling; fall back to another free model; release gate decides paid GLM 5.1 |
| OpenRouter free limits make the pilot slow | Use the one-time $10 credit for 1,000 requests/day, or reduce the first pass to 10 tasks × 3 agents |
| Moltis or PennyClaw lacks a usable headless path | Spike their drivers before M2 is declared done; drop an agent only with an explicit decision |
| Python dependencies do not support arm64 | v1 targets the host platform and records it; canonical release runs on linux/amd64 |
| Workspace + venv exceeds 1 GiB | Task selection targets ≤700 MiB; run fails fast with `envelope_exceeded` |
| Docker disk measurement differs across platforms | Measure image + workspace + writable layer; document the method and platform |
| Upstream repository/commit disappears | Cache a verified git bundle for each task in a release artifact; do not commit it |
| Contamination grows within a frozen v1 | Date window and v2 reset; document in the results README |
| Task licensing/attribution is incomplete | Allowlist permissive licenses; record SPDX and source URL; legal review before release |
| Full matrix cost is higher than estimated | Pilot measures tokens/run; release gate decides the model and scope |

Open gates (must be closed before v1 is tagged):

1. Release model: free model vs GLM 5.1, based on pilot cost and quality.
2. Moltis and PennyClaw driver spikes.
3. Task-set license review and attribution file.
4. Canonical platform for the published results (linux/amd64 vs host-native arm64).
5. Final task-set hash and 300-task validation.

## 18. Definition of done for v1

- 300 tasks validated: gold passes, base fails, no flaky tests, no network, workspace ≤700 MiB.
- Six agent images build from source, pin upstream versions and pass smoke tests.
- The full 6 × 300 matrix runs on one fixed model and produces per-run JSON plus a summary table.
- A clean clone can reproduce a single result with `bench setup`, `bench agents build` and `bench run`.
- `README.md`, `CONTEXT.md`, `PLAN.md`, ADRs, `tasks/v1/README.md` and `results/v1/README.md` are current.
- `LICENSE` (MIT) and `ATTRIBUTION.md` exist; no secrets are committed.
- The results table states the model, agent versions/digests, task-set hash, platform and known limitations.
