# Инвентаризация шести кандидатов (#23)

Данные собраны 2026-10-26 из первичных источников (GitHub API, README репозиториев, официальные сайты). Исполняет контекст: испытания на Linux VM с 1 GB RAM (см. README, «Кандидаты»).

## Сводная таблица

| Кандидат | Репозиторий | Язык | Лицензия | Последний релиз | Последний коммит | Stars | Активность |
|---|---|---|---|---|---|---|---|
| ZeptoClaw | [qhkm/zeptoclaw](https://github.com/qhkm/zeptoclaw) | Rust | Apache-2.0 | v0.9.2 (2026-04-07) | `8ff579b5f7` (2026-10-18) | 650 | живой |
| ZeroClaw | [zeroclaw-labs/zeroclaw](https://github.com/zeroclaw-labs/zeroclaw) | Rust | MIT OR Apache-2.0 | v0.8.6 (2026-10-18) | `5d4b18d335` (2026-10-24) | 33 044 | очень активный |
| Picobot | [louisho5/picobot](https://github.com/louisho5/picobot) | Go | MIT | v0.3.0 (2026-09-17) | `fedd7f2e0c` (2026-09-17) | 1 344 | умеренная |
| PicoClaw | [sipeed/picoclaw](https://github.com/sipeed/picoclaw) | Go | MIT | v0.3.1 (2026-07-03) | `bbf6893ca7` (2026-08-19; push 2026-10-15) | 30 078 | активный, раннее развитие |
| PennyClaw | [mandarl/pennyclaw](https://github.com/mandarl/pennyclaw) | Go | MIT | v0.5.0 (2026-03-17) | `d41a755865` (2026-03-17) | 23 | **под вопросом (7 мес. без движения)** |
| Moltis | [moltis-org/moltis](https://github.com/moltis-org/moltis) | Rust | MIT | 20261023.01 (2026-10-23) | `8a12400dc1` (2026-10-23) | 2 911 | очень активный |

Ни один проект не архивирован (`archived: false` у всех шести).

## Детали по кандидатам

### 1. ZeptoClaw

- **URL**: https://github.com/qhkm/zeptoclaw (сайт: https://zeptoclaw.com)
- **Что это**: «personal AI assistant infrastructure» — один Rust-бинарник: инструменты, память, каналы (Telegram, Slack, Discord, WhatsApp, Lark, Email, Webhook, Serial, ACP), 18 LLM-провайдеров, песочница.
- **Лицензия**: Apache-2.0.
- **Релиз**: v0.9.2 (2026-04-07). Коммит: `8ff579b5f7`, 2026-10-18. 650 stars.
- **Linux x86-64 / arm64**: да — ассеты релиза `zeptoclaw-linux-x86_64(.sha256)` и `zeptoclaw-linux-aarch64(.sha256)`, плюс macOS.
- **Установка**: `curl -fsSL https://raw.githubusercontent.com/qhkm/zeptoclaw/main/install.sh | sh`; Homebrew `brew install qhkm/tap/zeptoclaw`; Docker `ghcr.io/qhkm/zeptoclaw:latest` (манифест-digest на 2026-10-26: `sha256:e32bce5650aae597a2d2ebda3d4c3d5cf2349f9354934691d263ac7414a6b86a` — зафиксировать при установке); `cargo install zeptoclaw --git https://github.com/qhkm/zeptoclaw`.
- **OpenAI-совместимый бэкенд**: да, явно: «All OpenAI-compatible endpoints work out of the box», любой base URL переопределяется через `api_base` (включая Ollama, vLLM).
- **Заявленный RAM**: ~6 MB RAM, бинарник ~6 MB, старт ~50 ms (бейджи README; также «~6MB RAM each» для multi-tenant на одном VPS).
- **Активность**: живой; пуш 2026-10-18; сопровождается (Aisar Labs), 3 900+ тестов.

### 2. ZeroClaw

- **URL**: https://github.com/zeroclaw-labs/zeroclaw (сайт: https://www.zeroclaw.com). README прямо предупреждает: это единственный официальный репозиторий, остальные — самозванцы.
- **Что это**: «agent runtime» — один Rust-бинарник; 30+ каналов (Telegram, Discord, Matrix, email, voice, webhooks), провайдеры подключаемые; TOML-конфиг `~/.zeroclaw/config.toml`; systemd/launchctl service.
- **Лицензия**: двойная MIT OR Apache-2.0 (GitHub API показывает Apache-2.0).
- **Релиз**: v0.8.6 (2026-10-18). Коммит: `5d4b18d335`, 2026-10-24. 33 044 stars. Есть SBOM (CycloneDX/SPDX).
- **Linux x86-64 / arm64**: да — ассеты `zeroclaw-x86_64-unknown-linux-gnu/musl.tar.gz`, `zeroclaw-aarch64-unknown-linux-gnu/musl.tar.gz`, `.deb` (amd64), `.AppImage` (x86_64), armv6/armv7, даже android; Raspberry Pi/SBC поддерживаются явно.
- **Установка**: `curl -fsSL https://raw.githubusercontent.com/zeroclaw-labs/zeroclaw/master/install.sh | sh`; Homebrew `brew install zeroclaw`; Nix flake; из исходников cargo. Docker описан в `docs/book/src/setup/container.md`.
- **OpenAI-совместимый бэкенд**: да — секция `[providers.models.openai.<alias>]` с кастомным `uri` для «any OpenAI-compatible gateway or endpoint»; 70+ провайдеров (сайт): Ollama, LM Studio, llama.cpp, vLLM, OpenAI, Anthropic и др.
- **Заявленный RAM**: точная цифра в README отсутствует; официальный сайт — «less memory than a browser tab»; вторичные обзоры приводят «<5 MB RAM». Холодный старт ~12 ms. Требует замера в рамках методологии.
- **Активность**: очень активная (push 2026-10-26, тысячи issues/PR).

### 3. Picobot

- **URL**: https://github.com/louisho5/picobot
- **Что это**: self-hosted AI-агент в одном Go-бинарнике ~9 MB: постоянная память, tool calling, skills, каналы Telegram/Discord/Slack/WhatsApp, MCP-серверы. Позиционируется «runs anywhere — even on a $5 VPS».
- **Лицензия**: MIT.
- **Релиз**: v0.3.0 (2026-09-17). Коммит: `fedd7f2e0c`, 2026-09-17. 1 344 stars.
- **Linux x86-64 / arm64**: да — ассеты `picobot_linux_amd64(_lite)`, `picobot_linux_arm64(_lite)`; чистый Go без CGO, сборка `GOARCH=amd64|arm64 CGO_ENABLED=0`.
- **Установка**: Docker `louisho5/picobot:latest` (манифест-digest на 2026-10-26: `sha256:8210fbfbcf86a929a692b11cd0f4bbf7d0ed16388652dd481c4486dc63c32b0d`), docker compose; готовые бинарники из GitHub Releases; из исходников `go build -o picobot ./cmd/picobot`. Публикуемого пакета (pip/cargo/brew) нет.
- **OpenAI-совместимый бэкенд**: да — единственный тип провайдера: «Supports any OpenAI-compatible API (OpenAI, OpenRouter, Ollama, etc.)» через `OPENAI_API_BASE` / `config.json`.
- **Заявленный RAM**: ~10 MB в простое; Docker-образ ~29 MB (Alpine); «Works on any Linux with 256MB RAM».
- **Активность**: умеренная — последний коммит совпадает с релизом v0.3.0 (2026-09-17, ~5 недель). Есть одноимённые клоны (например `keny032/picobot`, 2 stars) — не путать, канонический именно `louisho5/picobot`.

### 4. PicoClaw

- **URL**: https://github.com/sipeed/picoclaw (сайт: https://picoclaw.io, только он официальный; прочие домены — скам-предупреждение в README). Компания Sipeed.
- **Что это**: ультралёгкий AI-ассистент на Go, «вдохновлён NanoBot», не форк OpenClaw; целевая платформа — железо за $10; WebUI-launcher, 16+ каналов (Telegram и др.), MCP, model routing.
- **Лицензия**: MIT.
- **Релиз**: v0.3.1 (2026-07-03). Коммит: `bbf6893ca7` (2026-08-19), push ветки 2026-10-15. 30 078 stars.
- **Linux x86-64 / arm64**: да — `picoclaw_Linux_x86_64.tar.gz`, `picoclaw_Linux_arm64.tar.gz`, плюс armv6/7, riscv64, mipsle, loong64, s390x; .deb/.rpm.
- **Установка**: бинарник с https://picoclaw.io (автоопределение платформы) или GitHub Releases; Docker Compose; из исходников (Go 1.25+, Node 22+ для WebUI). Официальный Docker-образ в README не назван.
- **OpenAI-совместимый бэкенд**: да — 30+ провайдеров через `model_list` в формате `protocol/model`: `openai/`, `vllm/`, `litellm/`, `nearai/` (OpenAI-compatible), Azure, Bedrock и др.
- **Заявленный RAM**: <10 MB ядро (заявление); README-предупреждение: свежие сборки могут занимать 10–20 MB, оптимизация запланирована. Старт <1 s.
- **Активность**: активная, но README честно предупреждает: «early rapid development… Do not deploy to production before v1.0».

### 5. PennyClaw

- **URL**: https://github.com/mandarl/pennyclaw
- **Что это**: личный AI-агент на Go, спроектирован под бесплатную GCP `e2-micro` (1 GB RAM, 2 vCPU): Web UI, Telegram-бот (long-polling), webhook, knowledge graph с «забыванием» по Эббингаузу, MCP-клиент, ~16 MB бинарник, встроенный SQLite.
- **Лицензия**: MIT.
- **Релиз**: v0.5.0 (2026-03-17). Коммит: `d41a755865`, 2026-03-17. 23 stars.
- **Linux x86-64 / arm64**: да — ассеты `pennyclaw-linux-amd64.tar.gz`, `pennyclaw-linux-arm64.tar.gz`.
- **Установка**: из исходников (`git clone && make run`); Docker — только локальная сборка из репозитория (`docker build`), публичного образа в реестре нет; готовые tar.gz из релизов. Пакетного менеджера нет.
- **OpenAI-совместимый бэкенд**: да — «OpenAI, Anthropic, Google Gemini, OpenRouter, and any OpenAI-compatible API».
- **Заявленный RAM**: <50 MB в простое; целевой сценарий — VM с 1 GB RAM + swap до ~1.5 GB.
- **Активность**: **сомнительная** — последний коммит и релиз 2026-03-17, то есть ~7 месяцев без движения; 23 stars; один автор. Имена-омонимы: `jaspertan10/PennyClaw` (C++, 0 stars) — не то. Это единственный кандидат из шестёрки, который может оказаться фактически заброшенным.

### 6. Moltis

- **URL**: https://github.com/moltis-org/moltis (сайт: https://moltis.org, документация: https://docs.moltis.org)
- **Что это**: «secure persistent personal agent server» — один Rust-бинарник (~270K LoC, 59 крейтов): Web UI, память SQLite+вектора, голос, каналы Telegram/Signal/Discord/Teams/Matrix/Slack/Nostr, MCP (stdio+HTTP/SSE), песочницы Docker/Podman/Apple Container/WASM; недавно на первой странице Hacker News.
- **Лицензия**: MIT.
- **Релиз**: `20261023.01` (дата-теги, 2026-10-23). Коммит: `8a12400dc1`, 2026-10-23. 2 911 stars. Релизы подписаны (Sigstore/GPG), есть attestation (`gh attestation verify`) и SBOM.
- **Linux x86-64 / arm64**: да — tar.gz `x86_64-unknown-linux-gnu` и `aarch64-unknown-linux-gnu`, `.deb` (amd64/arm64), `.rpm`, `.pkg.tar.zst` (Arch), AppImage, snap; Docker-образ multi-arch amd64/arm64.
- **Установка**: `curl -fsSL https://www.moltis.org/install.sh | sh`; `brew install moltis-org/tap/moltis`; Docker `ghcr.io/moltis-org/moltis:latest` (манифест-digest на 2026-10-26: `sha256:17cdb294521954ca0c4af37531018f79058138bdfc7b1bd5382a7a3027b3b4fd`); `cargo install moltis --git https://github.com/moltis-org/moltis`; нативные пакеты.
- **OpenAI-совместимый бэкенд**: да — «Any OpenAI-compatible» endpoint, плюс OpenRouter, Ollama, LM Studio, локальные GGUF/MLX, OAuth-провайдеры (OpenAI Codex, GitHub Copilot).
- **Заявленный RAM**: официальной цифры нет. Для constrained-устройств (Raspberry Pi) предусмотрен профиль сборки `--no-default-features --features lightweight`. Требует замера на 1 GB VM.
- **Активность**: очень активная (релиз 2026-10-23, push 2026-10-23).

## Выводы

1. **Все шесть кандидатов найдены и однозначно идентифицированы**; ни один не архивирован. Установка на Linux x86-64 и arm64 сегодня возможна для всех шести (готовые бинарники в релизах у всех; у пяти из шести есть официальный Docker-образ, у PennyClaw — только локальная сборка).
2. **Уверенно ставятся и живы**: ZeroClaw (самый активный, 33k stars, полные ассеты включая .deb/.AppImage/musl), ZeptoClaw, Moltis (подписанные релизы, много форматов пакетов), PicoClaw (активный, но раннее развитие и предупреждение «не для production до v1.0»).
3. **Под вопросом — PennyClaw**: 7 месяцев без коммитов, 23 stars, нет публичного Docker-образа. Проект не мёртв формально (не архивирован), но признаков поддержки нет. Решение — включать в испытания «как есть» с фиксацией SHA `d41a755865` или заменить кандидатом второй волны (NullClaw/MicroClaw/Hermes Agent).
4. **Picobot** — умеренная активность (последний коммит = релиз v0.3.0, 2026-09-17), один мейнтейнер; для теста пригоден, канонический репозиторий — `louisho5/picobot` (есть одноимённые клоны).
5. **Заявления о RAM у всех скромные** (~6–10 MB у ZeptoClaw/ZeroClaw/Picobot/PicoClaw, <50 MB у PennyClaw; у Moltis цифры нет) — но это заявления авторов; фактический замер на 1 GB VM остаётся задачей методологии (METHODOLOGY.md).
6. **OpenAI-совместимый LLM-бэкенд подтверждён у всех шести** — сценарий C с OpenAI-совместимым mock-сервером применим ко всем кандидатам.
7. Digests Docker-образов в этом документе зафиксированы на дату составления (2026-10-26) и должны быть перепроверены в момент установки.
