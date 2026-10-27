# FreeLLMAPI Research Check (#24)

## Executive Summary

**FreeLLMAPI** is a real, open-source project (GitHub: `tashfeenahmed/freellmapi`) that provides a unified OpenAI-compatible API gateway aggregating free tiers from ~34 LLM providers, offering ~635 free model endpoints. It is actively maintained and serves as a router/proxy layer, not a direct model provider.

**Can Llama 3.1 8B be used through FreeLLMAPI?** Yes — Llama 3.1 8B instruct is available through Cloudflare Workers AI (`@cf/meta/llama-3.1-8b-instruct-fp8`) and potentially other providers in the FreeLLMAPI ecosystem.

---

## Findings

### 1. Is "FreeLLMAPI" a real, currently-working public API endpoint?

- **Yes, it is real.** The project is on GitHub with 42,358 stars (as of Oct 2026), actively maintained with recent commits (Oct 27, 2026).
- **URL**: The project homepage is `https://freellmapi.co`, with a self-hosted router running on `http://localhost:3001`.
- **Not a hosted public API** — it is open-source software you install locally (Docker: `curl -fsSL https://freellmapi.co/install.sh | bash`).
- The repository at `https://github.com/tashfeenahmed/freellmapi` has 58 open issues and is actively developed.

### 2. Does it serve Llama 3.1 8B specifically? What models does it offer? Is it free?

- **Llama 3.1 8B is available**: `@cf/meta/llama-3.1-8b-instruct-fp8` is listed on Cloudflare Workers AI, one of the 12+ providers FreeLLMAPI aggregates.
- **Free tier**: FreeLLMAPI aggregates ~7.4 billion tokens/month across 474 model families / 635 free endpoints from 34+ providers. The Llama models are served free by: AI Horde, Aion Labs, Api.Airforce, Cloudflare Workers AI, DreamPrompting, ElectronHub, Groq, NVIDIA NIM, OVH AI Endpoints, Ollama Cloud, SEA-LION, Septor Labs.
- **Cost**: Free to use (no credit card required), but each provider has their own rate limits. FreeLLMAPI tracks per-key usage to keep you under free-tier caps.
- **Model catalog**: Full list at `https://freellmapi.co/models.html` with 600+ models; per-model rate limits, context windows, and free-token budgets are published.

### 3. Is it OpenAI-compatible (POST /v1/chat/completions with standard request/response format)?

- **Yes, fully OpenAI-compatible.** FreeLLMAPI provides an OpenAI-compatible endpoint at `http://localhost:3001/v1/`.
- Supported surfaces: `/v1/chat/completions`, `/v1/completions`, `/v1/models`, `/v1/embeddings`, `/v1/images/generations`, `/v1/audio/speech`, `/v1/audio/transcriptions`, `/v1/videos/generations`, `/v1/messages` (Anthropic format).
- Works with any OpenAI SDK: `openai.ChatCompletion.create()`, Anthropic SDK, Gemini CLI, etc.
- Also supports MCP (`/mcp` endpoint) for ChatGPT integration.

### 4. Known issues: rate limits, timeouts, quality, privacy

- **Rate limits**: Per-model RPM/RPD/TPM/TPD counters enforced by FreeLLMAPI router. Each provider's free tier caps are tracked individually. Automatic failover to next provider when rate-limited.
- **Timeouts**: Not explicitly documented, but standard OpenAI client timeouts apply. Router has cooldowns and key rotation on 429/5xx.
- **Quality**: Models come from various providers with different quality levels. FreeLLMAPI's "smart routing" ranks models by speed/capability/reliability scores.
- **Privacy**: Key concern — "Don't expose this proxy publicly" (from footer). Provider keys are AES-256-GCM encrypted in SQLite, decrypted in-memory per request. FreeLLMAPI itself does not store prompts/responses, but individual providers' ToS apply.
- **Per the disclaimer**: "Built for personal use only. Each provider's ToS applies. Don't expose this proxy publicly."

### 5. Comparison with realistic alternatives for this benchmark (1 GB RAM VM)

| Alternative | Fit for 1 GB VM | Cost | Notes |
|------------|-----------------|------|-------|
| **FreeLLMAPI + local router** | ✅ **Fits** (router is ~40 MB RSS at idle) | Free (aggregated free tiers) | Routes across providers; need to add provider keys. Llama 3.1 8B via Cloudflare Workers AI. |
| OpenAI gpt-4o-mini | ✅ Fits (API-only) | $0.15/1K input, $0.60/1K output | Reliable, but costs money; not "free" for extensive benchmarking. |
| Anthropic claude-3-haiku | ✅ Fits (API-only) | $0.25/1M input, $1.25/1M output | Good quality, paid. |
| OpenRouter | ✅ Fits (API-only) | Variable, typically ~$0.10-0.50/1K input | Aggregates many providers, paid. |
| **Ollama llama3.1:8b** | ❌ **Does NOT fit** (needs ~4.7 GB RAM) | Free locally | Requires 4.7 GB RAM minimum — exceeds 1 GB VM limit by ~4.7×. |

**Recommendation for scenario C (1 GB VM):**

**Use FreeLLMAPI with Cloudflare Workers AI's `@cf/meta/llama-3.1-8b-instruct-fp8` model.**

**Why:**
- Fits within 1 GB RAM (router only ~40 MB; model runs on Cloudflare's infrastructure, not locally)
- Free to use (Cloudflare Workers AI free tier)
- OpenAI-compatible — works with existing benchmark code
- Automatic failover if Cloudflare provider rates out
- Part of the FreeLLMAPI ecosystem already designed for exactly this use case

**Key risks:**
1. Provider rate limits may throttle during extended benchmark runs — FreeLLMAPI handles failover but tasks may be delayed
2. Cloudflare Workers AI free tier has per-day limits (Neurons) — need to check current quotas
3. Network dependency — router must reach `freellmapi.co` for catalog updates
4. Privacy: provider ToS vary; some may log prompts

**Setup for benchmark:**
```bash
# 1. Install FreeLLMAPI Docker
curl -fsSL https://freellmapi.co/install.sh | bash

# 2. Start it (runs on localhost:3001)
# 3. Add free key for Cloudflare Workers AI (no card required)
# 4. Point benchmark at http://localhost:3001/v1 with unified key
# 5. Use model: @cf/meta/llama-3.1-8b-instruct-fp8
```

---

## Source Citations

- GitHub repository: `https://github.com/tashfeenahmed/freellmapi` (42,358 stars, 58 open issues, active Oct 2026 commits)
- Model catalog: `https://freellmapi.co/models.html` — lists `@cf/meta/llama-3.1-8b-instruct-fp8` on Cloudflare Workers AI
- Free Llama API page: `https://freellmapi.co/free-llama-api` — 40 free Llama models across 12 providers
- Disclaimer on `freellmapi.co`: "Built for personal use only. Each provider's ToS applies. Don't expose this proxy publicly."
- Feature comparison table from README and feature pages
- Router RSS: "~40 MB RSS at idle behind PM2 / systemd / whatever supervisor you prefer" (from README)
- 7.4B tokens/month aggregate: From README header and model catalog page