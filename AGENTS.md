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