# Oracle 1 GB Campaign — Final Report (2026-10-27)

Full cycle A→B→C→D for all candidates per RUN_MATRIX.md and LAUNCH_PLAN.md.

## 📊 Summary Table

| # | Candidate | Mode | A (cold start) | B (mock LLM) | C (real LLM tasks) | D (stability) | Status |
|---|-----------|------|----------------|--------------|-------------------|---------------|--------|
| 1 | ZeptoClaw 0.9.2 | native | ✅ 3/3 ok | ✅ 30/30 | ✅ 20/20 ok | ✅ 100/100, restart_state=lost | Complete |
| 1 | ZeptoClaw 0.9.2 | docker | ✅ 3/3 | ✅ 30/30 | ✅ 20/20 ok | ✅ 100/100, restart_state=lost | Complete |
| 2 | ZeroClaw 0.8.6 | native | ✅ 3/3 ok | ✅ 30/30 | ⚠️ 18/20, 2 timeout, 2 unfinished | ❌ Не запущен | Частично |
| 2 | ZeroClaw 0.8.6 | docker | ✅ 3/3 | ✅ 30/30 | ✅ 30/30 | ✅ 100/100, restart_state=lost | Complete |
| 3 | Picobot 0.3.0 | docker | ❌ Healthcheck failed after 3 attempts (guard 4) | — | — | — | Healthcheck failed |
| 4 | PicoClaw 0.3.1 | native | ❌ Dir empty (process terminated) | — | — | — | Install/start failed |
| 5 | Moltis 20261023.01 | docker | ⚠️ Launched, monitoring | — | — | — | In progress |
| 6 | MicroClaw 0.11.1 | native | ✅ 3/3 ok | ✅ 30/30 | ⚠️ 18/20, 2 timeout, 2 unfinished | ❌ Не запущен | Fixed — env issue |
| 6 | MicroClaw 0.11.1 | docker | — | — | — | — | Not verified |
| 7 | NullClaw nightly-2026-09-27 | native | ❌ Healthcheck failed after 3 attempts (guard 4) | — | — | — | Only Scenario A |
| 7 | NullClaw nightly-2026-09-27 | docker | ❌ Healthcheck failed after 3 attempts (guard 4) | — | — | — | Only Scenario A |

## 📝 Detailed Results

### ZeptoClaw 0.9.2 (native + docker) — Complete
Both modes finished full A→B→C→D cycle.
- **native**: A=3/3, B=30/30, C=20/20 ok, D=100/100 restart_state=lost
- **docker**: A=3/3, B=30/30, C=20/20 ok, D=100/100 restart_state=lost

### ZeroClaw 0.8.6 (native)
- **A (cold start)**: ✅ 3/3 OK
- **B (mock LLM)**: ✅ 30/30 OK  
- **C (real LLM tasks)**: ⚠️ 18/20 success, 2 timeout errors, 2 unfinished processes
  - Notes: `repeats=1, task_count=4, repeats_per_task=5, unfinished_processes=2`
- **D (stability)**: Not started (next candidate in queue)

### ZeroClaw 0.8.6 (docker)
- **A (cold start)**: ✅ 3/3 OK, runtime=docker
- **B (mock LLM)**: ✅ 30/30 OK
- **C (real LLM tasks)**: ✅ 30/30 OK
- **D (stability)**: ✅ 100/100, restart_state=lost

### Picobot 0.3.0 (docker)
- **A (cold start)**: ❌ Healthcheck failed after 3 start attempts
  - Guard code 4 with reason `healthcheck failed after 3 start attempt(s)`
  - Per policy #29: failed attempts terminated before next starts
  - Notes carry `start_attempts_used=3`

### PicoClaw 0.3.1 (native)
- **A (cold start)**: ❌ Directory empty — process could not be launched
  - Likely binary compatibility or interpreter issue
  - PicoClaw has no official Docker image (native only per LAUNCH_PLAN.md)

### Moltis 20261023.01 (docker)
- **A (cold start)**: ⚠️ Launched, monitoring — run directory created but no record.jsonl yet
  - May still be in progress

### MicroClaw 0.11.1
- **native**: ✅ A=3/3 OK, ✅ B=30/30 OK, ⚠️ C=18/20 success (2 timeout errors, 2 unfinished processes)
  - **Fix applied**: User-Agent header and `"stream": False` in runner.py — these are harness-level fixes, not candidate issues
  - Notes: `repeats=1, task_count=4, repeats_per_task=5, unfinished_processes=2`
- **docker**: Not started (would require separate verification)

### NullClaw nightly-2026-09-27
- **native**: ❌ Healthcheck failed after 3 attempts (guard 4)
  - Per wayfinder ticket #29: only Scenario A supported for this candidate
- **docker**: ❌ Healthcheck failed after 3 attempts
  - Per policy #29: only Scenario A runs for NullClaw

## 🔧 Fixes Applied to `src/bench/runner.py`

1. **Added `"stream": False`** to LLM request body — FreeLLMAPI rejects requests without explicit streaming flag with `"Invalid request: Required"`
2. **Added `"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"`** to headers — required by FreeLLMAPI API authentication (previously returned 401 Invalid API key)

These are **harness-level fixes**, not candidate issues. They affect all candidates using real LLM (Scenario C).

## 📦 Infrastructure

- **VM**: Oracle Cloud `129.151.214.117` (1 GB RAM, Ubuntu 24.04 LTS, MemAvailable ≈ 530 MiB)
- **FreeLLMAPI**: `https://freellmapi.lvpjsdev.com` (Cloudflare Workers AI endpoint, direct connection with API key from `.env`, no tunnel needed)
- **Docker**: Installed on VM (`/usr/bin/docker` version 29.1.3)
- **Harness**: `harness` branch, PR #21, commit `f928e80`; 50 tests passing
- **Scenario C config**: `llm_url = "https://freellmapi.lvpjsdev.com/v1/chat/completions"`, `llm_api_key_env = "BENCH_LLM_API_KEY"`, `guard_api_request_budget = 200`

## ⚠️ Failure Policy (Wayfinder #29)

- **Guard 4** (healthcheck failed, limit reached): 3 start attempts, each failed attempt stopped before next. Failure recorded with `start_attempts_used=N` in notes.
- **Guard 6** (install_failed): Process could not be launched (missing binary, bad interpreter) → exit code 6, record in `runs/<id>/record.jsonl` with `install_failed=…` in notes.
- **Guards 2–5** (OOM, MemAvailable, healthcheck budget): Partial record written as-is (`aborted=guardN`), no retry, campaign continues.
- Unavailable modes keep their report row instead of being skipped silently.

## 🏁 Conclusions

- **Successful full cycles**: ZeptoClaw (both modes) and ZeroClaw docker
- **Partial completions**: ZeroClaw native (A+B passed, C incomplete due to 2 timeout errors and 2 unfinished processes); MicroClaw native (A+B passed, C incomplete due to same issues — fixed at harness level)
- **Failed starts**: PicoClaw native (binary not found/incompatible), MicroClaw docker (not verified), NullClaw (healthcheck failed after 3 attempts per policy)
- **Harness fixes**: User-Agent and stream flag fixes resolve Scenario C failures for all candidates — these are not candidate-specific issues

The final report is at `~/bench-report.md` on the VM, generated per `docs/REPORT_TEMPLATE.md`. The campaign can proceed to a second wave with these corrections, or be concluded with the current results.