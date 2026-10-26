# AGENTS.md

## Agent skills

### Issue tracker

GitHub Issues in this repo, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Added by ticket #14

- Scenario C supports 4 real LLM tasks × 5 repeats each:
  1) Short verifiable question without tools
  2) Read a created test file and extract three given values
  3) Create a JSON summary file in a temp directory with automatic schema validation
  4) Call a local harmless echo/add tool as a separate functional test (MCP)
- TOML scenario definition: `scenarios/scenario_c_real_llm_tasks.toml` with fields `task_count`, `repeats_per_task`, `repeats`, `mock_latency_ms`, `tool_cycles`
- Record fields per METHODOLOGY.md §7: `run_id`, `agent`, `repo_url`, `version`, `mode`, `scenario`, `host_profile`, `started_at_utc`, `duration_sec`, `ram_pss_mb_median`, `ram_peak_mb`, `cpu_sec`, `startup_ms`, `latency_p50_ms`, `latency_p95_ms`, `success_count`, `error_count`, `oom_count`, `notes`, `config_ref`
- When `--mock-llm-port` is provided (including 0 for OS-assigned), scenario C uses the mock LLM server for task execution
- Without mock server, tasks are marked as unfinished with `unfinished_processes` note
- Dispatch logic in `_run_single_repeat()` checks for `task_count` and `repeats_per_task` fields to identify scenario C
- Test file: `tests/test_scenario_c.py` with 5 CLI-seam tests verifying record fields, latency metrics, and notes content

## Added by tickets #19, #16, #15, #20 (2026-10-26)

- `bench report --runs-dir <dir> --output <file>`: deterministic markdown report from `runs/*/record.jsonl` per `docs/REPORT_TEMPLATE.md`; missing values render «—», uncollected metrics render "unsupported", native/docker rows keyed by (agent, mode), output passes the secret sanitizer. Golden test: `tests/test_report.py` + `tests/goldens/report.md`
- Secret sanitizer `src/bench/sanitize.py` is wired into all disk-write paths: `record.jsonl`, `repeats.jsonl` (in `runner.py`) and the report; hits are redacted to `[REDACTED]` and marked `sanitizer_triggered=true` in notes
- `--dry-run` prints the full execution plan (commands, healthcheck, limits, mock, guards) and spawns nothing
- Guard auto-stop with distinct exit codes (documented in `bench run --help`): 2 = OOM counter ≥ `guard_oom_threshold`, 3 = MemAvailable < `guard_memavailable_min_mb`, 4 = healthcheck failed, 5 = issued requests ≥ `guard_api_request_budget`. On a trip the repeats loop stops, collected records are saved, notes get `aborted=guard<code>:<reason>`
- Scenario D (`_run_single_repeat_scenario_d`, dispatch on `restart_after_requests` or name `scenario_d`): request series with `pause_between_ms`, RSS growth over the series (`rss_growth_mb`, `rss_leak` notes), mid-series agent restart at `restart_after_requests` with test-state check (`restart_state=preserved|lost`), unfinished (orphaned child) process detection via `ps` (`unfinished_processes`, `unfinished_pids`), error injection 429/500/timeout recorded without retries; `error_on_call` reaches MockConfig (per-call counter fixed)
- Docker mode: descriptor `mode = "docker"` with digest-pinned `image` (`repo@sha256:…`); `--privileged`, docker.sock mounts and host network are rejected (exit 1); harness composes hardened `docker run` flags with uniform limits from scenario (`docker_memory_limit`, `docker_cpu_limit`); image preload is a separate `pull` phase excluded from `startup_ms`; metrics come from the container cgroup path; notes add `runtime=docker`, `docker_image=…`; tests use `tests/fixtures/docker_stub.sh` via `--docker-bin`