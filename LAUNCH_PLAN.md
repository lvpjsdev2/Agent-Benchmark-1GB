# Launch Plan: Oracle VM Benchmark Run

**Source**: Wayfinder map [#22](https://github.com/lvpjsdev2/Agent-Benchmark-1GB/issues/22) — all decisions finalized.
**Harness**: `harness` branch (PR #21), commit `f928e80`, 50 tests passing.
**Date**: 2026-10-27

---

## 1. Infrastructure & Host

| Parameter | Value |
|---|---|
| **VM** | `e2-micro-zeptoclaw` (Oracle Cloud, `eu-stockholm-1`) |
| **Public IP** | `129.151.214.117` |
| **Private IP** | `10.0.0.168` |
| **OS** | Ubuntu 24.04 LTS (Canonical-Ubuntu-24.04-2026.09.18-0) |
| **Shape** | VM.Standard.E2.1.Micro (1 GB RAM, 2 vCPU / 1 OCPU) |
| **RAM** | 954 MiB total, **MemAvailable = 530 MiB** |
| **Swap** | 4 GiB |
| **Disk** | 48 GB (38 GB free) |
| **SSH** | `ubuntu@129.151.214.117` (ed25519 key `~/.ssh/id_ed25519`) |
| **Docker** | Not installed — will install via `apt install -y docker.io` |
| **Existing process** | `zeptoclaw` on port 9091 (pid 21730) — will stop before tests |

---

## 2. Candidates (7 total)

| # | Candidate | Mode | Repo | Version | Docker Digest | Health Endpoint |
|---|---|---|---|---|---|---|
| 1 | ZeptoClaw | native + docker | qhkm/zeptoclaw | 0.9.2 | `ghcr.io/qhkm/zeptoclaw@sha256:e32bce5650aae597a2d2ebda3d4c3d5cf2349f9354934691d263ac7414a6b86a` | `http://localhost:9090/healthz` |
| 2 | ZeroClaw | native + docker | zeroclaw-labs/zeroclaw | 0.8.6 | `ghcr.io/zeroclaw-labs/zeroclaw@sha256:e44308c7120a32f1089e3bc2881159bfdf462e1281d2be40920f15de9202f752` | `http://localhost:8080/health` |
| 3 | Picobot | docker | louisho5/picobot | 0.3.0 | `louisho5/picobot@sha256:8210fbfbcf86a929a692b11cd0f4bbf7d0ed16388652dd481c4486dc63c32b0d` | `http://localhost:18790/health` |
| 4 | PicoClaw | native | sipeed/picoclaw | 0.3.1 | — (no official image) | `http://localhost:18790/health` |
| 5 | Moltis | docker | moltis-org/moltis | 20261023.01 | `ghcr.io/moltis-org/moltis@sha256:17cdb294521954ca0c4af37531018f79058138bdfc7b1bd5382a7a3027b3b4fd` | — |
| 6 | MicroClaw | native + docker | microclaw/microclaw | 0.11.1 | `ghcr.io/microclaw/microclaw@sha256:f91f92bfadadeb5a584ba959e49615cb447d55a7eda1e6a78c384eb6d0da89dc` | `http://localhost:10961/health` |
| 7 | NullClaw | native + docker (partial) | nullclaw/nullclaw | nightly-2026-09-27 | `ghcr.io/nullclaw/nullclaw@sha256:c866ee2e1bddc93ac027ddcea5e028f2ebef8bd1ed61874596ca6f9de487d410` | `http://localhost:8080/health` |

**Notes**:
- **PicoClaw**: no official Docker image → native only.
- **NullClaw**: partial run — only Scenario A (cold start) in both modes, marked "частичный прогон" in report.
- **MicroClaw native**: install via `tar.gz` from GitHub Releases (`microclaw-0.11.1-x86_64-linux-gnu.tar.gz`); glibc ≥ 2.39 satisfied on Ubuntu 24.04.

---

## 3. LLM Setup (Scenario C)

**Provider**: FreeLLMAPI (self-hosted router) + Cloudflare Workers AI
**Model**: `@cf/meta/llama-3.1-8b-instruct-fp8`
**Endpoint**: `http://localhost:3001/v1` (OpenAI-compatible)

### On Mac (before VM tests):
```bash
# 1. Start FreeLLMAPI router
docker run -d --name freellmapi -p 3001:3001 freellmapi/freellmapi

# 2. Add Cloudflare Workers AI key via UI
open http://localhost:3001  # Settings → Providers → Cloudflare Workers AI → API Token
```

### On VM (SSH tunnel from Mac):
```bash
# On Mac, in background (persistent):
ssh -f -N -L 3001:localhost:3001 ubuntu@129.151.214.117

# On VM, verify:
curl http://localhost:3001/v1/models
```

---

## 4. Guard Thresholds (harness auto-stop)

| Guard | Threshold | Exit Code |
|---|---|---|
| OOM counter | ≥ 1 | 2 |
| MemAvailable | < 100 MB | 3 |
| Health check failed | limit reached | 4 |
| API request budget | ≥ 200 requests | 5 |

---

## 5. Execution Order & Flow

### Per Candidate (full cycle A→B→C→D):
1. **Stop any existing candidate process** (`pkill -f <candidate>`)
2. **Cleanup**: `docker rm -f $(docker ps -aq)`, `rm -rf /tmp/bench-*`
3. **Memory drop**: `sync && echo 3 | sudo tee /proc/sys/vm/drop_caches`
4. **Pause 60 sec**
5. **Scenario A (Cold Start)**: 3 repeats, 30 sec pause between
6. **Scenario B (Mock LLM)**: 1 run, 30 requests + 5 warmup, FreeLLMAPI via `localhost:3001`
7. **Scenario C (Real LLM)**: 4 tasks × 5 repeats = 20 runs, FreeLLMAPI
8. **Scenario D (Stability)**: 1 run, 100 requests, restart at 50, error injection
9. **Full cleanup** before next candidate

### Candidate Order:
1. ZeptoClaw (native + docker)
2. ZeroClaw (native + docker)
3. Picobot (docker only)
4. PicoClaw (native only)
5. Moltis (docker only)
6. MicroClaw (native + docker) — **install Docker first** (`apt update && apt install -y docker.io`)
7. NullClaw (native + docker, **Scenario A only**)

---

## 6. Pre-Flight Checklist (before first candidate)

```bash
# On VM (as ubuntu):
# 1. Install Docker
apt update && apt install -y docker.io

# 2. Stop existing zeptoclaw on port 9091
pkill -f zeptoclaw

# 3. Verify FreeLLMAPI tunnel from Mac
curl http://localhost:3001/v1/models

# 4. Create benchmark working directory
mkdir -p /home/ubuntu/bench-runs
```

```bash
# On Mac (in separate terminal):
# 1. Start FreeLLMAPI
docker run -d --name freellmapi -p 3001:3001 freellmapi/freellmapi
# Add Cloudflare Workers AI key at http://localhost:3001

# 2. Start SSH tunnel (persistent)
ssh -f -N -L 3001:localhost:3001 ubuntu@129.151.214.117

# 3. Verify tunnel from VM
ssh ubuntu@129.151.214.117 "curl -s http://localhost:3001/v1/models | jq ."
```

---

## 7. Descriptors & Running

Descriptors prepared in `/tmp/bench-descriptors/*.toml` (to be committed). Example run:

```bash
# On VM, for each candidate:
cd /home/ubuntu/bench-runs

# Native mode
uv run --project /path/to/Agent-Benchmark-1GB python -m bench run \
  /path/to/descriptors/zeptoclaw.toml \
  /path/to/scenarios/cold_start.toml \
  --proc-root /proc \
  --cgroup-root /sys/fs/cgroup \
  --runs-dir ./runs \
  --mock-llm-port 0

# Docker mode (where applicable)
uv run --project /path/to/Agent-Benchmark-1GB python -m bench run \
  /path/to/descriptors/zeptoclaw_docker.toml \
  /path/to/scenarios/cold_start.toml \
  --proc-root /proc \
  --cgroup-root /sys/fs/cgroup \
  --runs-dir ./runs \
  --mock-llm-port 0 \
  --docker-bin docker
```

> **Note**: Scenario C uses `--mock-llm-port 0` (OS-assigned) because FreeLLMAPI tunnel makes it look like a local mock server on `localhost:3001`. The harness will connect to `http://localhost:3001/v1/chat/completions` via the SSH tunnel.

---

## 8. Report Generation

After all candidates complete:

```bash
uv run --project /path/to/Agent-Benchmark-1GB python -m bench report \
  --runs-dir /home/ubuntu/bench-runs \
  --output /home/ubuntu/bench-report.md
```

Output: two tables (native / docker), per-candidate rows, latency percentiles, resource metrics, scenario stats, limitations, conclusions template.

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| FreeLLMAPI rate limits (Cloudflare daily Neurons) | Monitor `bench report` error counts; FreeLLMAPI auto-failover to next provider |
| MicroClaw native glibc issue | Ubuntu 24.04 has glibc 2.39 — verified OK |
| VM port conflict (zeptoclaw on 9091) | `pkill -f zeptoclaw` before start |
| MemAvailable drops below 100 MB | Guard exit code 3 triggers auto-stop, partial records saved |
| SSH tunnel drops | Use `autossh` or `screen`/`tmux` on Mac; verify before each candidate |
| OOM on VM | Guard code 2 auto-stop; swap 4 GiB provides buffer |

### Failure policy (wayfinder ticket #29)

| Situation | What happens |
|---|---|
| Candidate never answers its healthcheck | Three start attempts (`--start-attempts 3`, the default); each failed attempt is stopped before the next starts. Still down → guard 4 with `start_attempts_used=3`, failure recorded, next candidate. |
| Command cannot be launched at all (missing binary, glibc mismatch) | `install_failed` record, exit 6, no measurements; campaign continues. |
| `docker pull` fails | `install_failed=docker_pull_failed` record, exit 6; the candidate's other mode still runs (#29 Q2). |
| Guard trip mid-scenario (codes 2–5) | Partial record written as-is (`aborted=guardN`), **no retry**, campaign moves on. |
| A scenario failed but the candidate is alive | Remaining scenarios still run; each failure is noted separately. |
| SSH/VM unavailable, disk full | Campaign stops, state recorded; resume only on an explicit human "go". |
| Candidate failed completely | `bench report` lists it under «Ограничения результата» → «Какие проекты не запустились и почему» with its recorded reason (`install_failed=…` or `healthcheck failed after N start attempt(s)`); never substituted — the second wave (Hermes Agent) stays out of this effort. |

---

## 10. Post-Run

1. Collect `bench-report.md` from VM
2. Archive `runs/*/record.jsonl` and `runs/*/repeats.jsonl`
3. Fill conclusions section of report (overhead, functionality, 24/7 suitability)
4. Human decision on winner

---

## References

- Wayfinder map: [#22](https://github.com/lvpjsdev2/Agent-Benchmark-1GB/issues/22)
- Harness PR: [#21](https://github.com/lvpjsdev2/Agent-Benchmark-1GB/pull/21)
- Methodology: `docs/METHODOLOGY.md`
- Safety: `docs/SAFETY_AND_SETUP.md`
- Report template: `docs/REPORT_TEMPLATE.md`
- Descriptors: `/tmp/bench-descriptors/*.toml` (to commit)
- Research: `docs/research/candidate-inventory.md`, `docs/research/second-wave-inventory.md`, `docs/research/FreeLLMAPI-check.md`