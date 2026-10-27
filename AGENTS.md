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

## Added by wayfinder ticket #29 (2026-10-27)

- Start attempts: `bench run --start-attempts N` (default 3; a scenario or descriptor key `start_attempts` overrides it, and `--dry-run` prints the resolved value). A candidate that does not answer its healthcheck is launched N times (`_start_process_with_attempts`), every failed attempt is terminated before the next starts, and only then is the start recorded as failed — guard 4 with reason `healthcheck failed after N start attempt(s)`.
- Notes carry `start_attempts_used=N` (aggregate record and each `repeats.jsonl` row) whenever the candidate needed more than one attempt; a start that succeeds on the first try is not annotated.
- Exit code 6 = candidate unavailable / `install_failed`: the process could not be launched at all (missing binary, bad interpreter: `OSError` on every attempt) or a `mode = "docker"` image could not be pulled. Both paths write `runs/<id>/record.jsonl` with `install_failed=…` in notes and print `"status": "unavailable"`, so an unavailable mode keeps its report row instead of being skipped silently.
- Fixture `tests/fixtures/start_counter_agent.py` counts its own launches; CLI-seam tests for this policy live in `tests/test_start_policy.py`.
- `bench report` puts recorded start failures into «Ограничения результата» → «Какие проекты не запустились и почему»: a bullet per run (agent, mode, run_id, scenario) with the reason from notes — `install_failed=…` (guard 6) or `healthcheck failed after N start attempt(s)` (guard 4). Mid-run guards and healthy runs are not listed; a missing `host_profile` (install_failed records) renders as a dash instead of aborting the report. Test: `tests/test_report.py::test_start_failures_render_in_limitations_section`.

## Added by review-fix tickets #36–#38 (2026-10-27)

- One start path in `runner.py` (#36): `_prepare_candidate` (healthcheck parameters, absolute workdir, `_resolve_start_cmd`, PID override, workdir cleanup, RAM baseline), `_start_candidate` (start attempts plus termination of a process that never answered) and `_failed_start_result` (shared failed-start stub; scenario-specific keys are passed as `extra`). All four scenario runners use them, A and B included — the inline start-command resolution is gone.
- Experiment passport (#37): `host_profile` carries `os`, `kernel`, `cpu_count`, `ram_total_mb`, `swap_total_mb`, `swap_free_mb` and `mem_available_mb_baseline` (`read_meminfo_kb` over the injectable proc root; unreadable fields stay `None` and render as dashes). `bench report` prints them in the passport, appends the pinned `docker_image` digest to the version line, and derives «Отклонения от методики» from notes (`aborted=`, `install_failed=`, `unfinished_processes>0`) instead of hardcoding «нет». Golden `tests/goldens/report.md` updated.
- Mock timeout mode (#38): with `mock_error_mode = "timeout"` only the call named by `error_on_call` hangs (every call when it is unset), for `mock_timeout_sleep_sec` seconds (default 10, shortened in tests); the mock server is threaded, so a hung call no longer blocks the others. Direct tests in `tests/test_mock_server.py`, CLI-seam test in `tests/test_scenario_d.py`.

## Added by ticket #40 (2026-10-27)

- Scenarios B–D now POST each request to the **candidate** (`descriptor.chat_url`), not to the mock or `scenario.llm_url`. Before this, the harness called the mock itself, so latency/success described the harness and the candidate only idled; C never touched files or tools. A request scenario without `chat_url` fails before start with exit 1, and `--dry-run` prints `chat_url`/`agent_env`.
- The candidate reaches its upstream through descriptor `env`, resolved per run: `{mock_url}`, `{mock_base_url}`, `{llm_url}`, `{llm_base_url}`, `{llm_api_key}` (the last read from the env var named by scenario `llm_api_key_env`, never written to disk). In docker mode the same map becomes `-e KEY=VALUE` flags. Optional `chat_api_key_env`/`chat_headers` authenticate the harness to the candidate's own API.
- Records note `mock_requests=N` when a mock server is up. Zero next to non-zero success means the candidate ignored the mock — a misconfiguration, not a healthy run.
- Restart fix found by the new tests: a file healthcheck left by the previous process was treated as healthy after a scenario-D restart, so requests hit a process that had not started. The stale signal is removed before every start attempt.
- Fixture `tests/fixtures/chat_agent.py` (counts served requests, optionally proxies to the mock, supports restart state and hung children); tests in `tests/test_chat_routing.py`; B/C/D tests and the guard-budget test now assert on the candidate's request count.
