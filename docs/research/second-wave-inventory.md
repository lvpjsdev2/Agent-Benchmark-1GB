# Инвентаризация кандидатов второй волны: NullClaw и MicroClaw (#28)

Данные собраны 2026-10-27 из первичных источников (GitHub API, README и docs репозиториев, реестр GHCR). Формат и контекст — как в [инвентаризации первой волны](https://github.com/lvpjsdev2/Agent-Benchmark-1GB/blob/research/candidate-inventory/docs/research/candidate-inventory.md): испытания на Linux VM с 1 GB RAM, замена кандидата PennyClaw (7 месяцев без движения).

## Сводная таблица

| Кандидат | Репозиторий | Язык | Лицензия | Последний релиз | Последний коммит | Stars | Активность |
|---|---|---|---|---|---|---|---|
| NullClaw | [nullclaw/nullclaw](https://github.com/nullclaw/nullclaw) | Zig | MIT | v2026.5.29 (2026-05-29; nightly-канал жив) | `5f1cade05c` (2026-10-05; push 2026-10-08) | 8 133 | активный, но стабильный тег устарел (~5 мес.) |
| MicroClaw | [microclaw/microclaw](https://github.com/microclaw/microclaw) | Rust | MIT | v0.11.1 (2026-10-27, security-патч) | `3c1b14eb28` (2026-10-27) | 748 | очень активный (релиз и коммит в день сбора данных) |

Оба проекта не архивированы (`archived: false`). Омонимы и как их не путать — см. раздел «Осторожно: омонимы» ниже.

## Детали по кандидатам

### 1. NullClaw

- **URL**: https://github.com/nullclaw/nullclaw (сайт: https://nullclaw.io, документация: https://nullclaw.github.io). Организация `nullclaw` владеет всей экосистемой: nullhub (консоль управления, 1 808 stars), nullboiler, nullwatch, nulltickets.
- **Что это**: «Fastest, smallest, and fully autonomous AI assistant infrastructure» — статический бинарник на Zig: 19 встроенных каналов (CLI, Telegram, Signal, Discord, Slack, iMessage, Matrix, WhatsApp, Webhook, IRC, Lark/Feishu, OneBot, Line, DingTalk, Email, Nostr, QQ, MaixCam, Mattermost), 50+ LLM-провайдеров, 35+ инструментов, 10 memory-движков, песочницы (landlock, firejail, bubblewrap, docker), MCP, подагенты, стриминг. Есть `nullclaw migrate openclaw` — миграция конфигов с OpenClaw.
- **Лицензия**: MIT.
- **Релиз**: стабильный v2026.5.29 (2026-05-29) — **~5 месяцев без стабильного релиза**; параллельно живой nightly-канал (релиз «nightly» постоянно обновляется, билд от 2026-09-27, ассеты с `.sha256` и манифестами). Коммит: `5f1cade05c`, 2026-10-05 (push 2026-10-08). 8 133 stars, 946 forks, 100 открытых issues.
- **Linux x86-64 / arm64**: да — статические бинарники `nullclaw-linux-x86_64.bin` (~5,5 MB) и `nullclaw-linux-aarch64.bin` (~4,4 MB), плюс arm32 (gnu/musl), riscv64, android; ноль runtime-зависимостей («nothing but libc», на практике — даже без неё: static).
- **Установка**: `brew install nullclaw` (рекомендованный путь); готовые `.bin` из GitHub Releases; Docker `ghcr.io/nullclaw/nullclaw:latest` (манифест-digest на 2026-10-27: `sha256:c866ee2e1bddc93ac027ddcea5e028f2ebef8bd1ed61874596ca6f9de487d410` — зафиксировать при установке) + docker-compose в репозитории (профили `agent`/`gateway`, gateway на `127.0.0.1:3210` внутри контейнера); из исходников — **только Zig 0.16.0, другие версии не поддерживаются** (`zig build -Doptimize=ReleaseSmall`).
- **OpenAI-совместимый бэкенд**: да — README: «No lock-in: OpenAI-compatible provider support + pluggable custom endpoints»; в конфиге `models.providers.<name>` с `base_url` (для OpenAI-совместимых — база с `/v1`), `api_mode: chat_completions|responses`; штатные провайдеры openrouter/openai/anthropic/groq/nearai и др.; отдельная опция для кастомных vLLM/Qwen endpoint'ов.
- **Заявленный RAM**: ~1 MB peak RSS, бинарник 678 KB, старт <2 ms (Apple Silicon) / <8 ms (0,8 GHz edge-ядро). README приводит свою benchmark-таблицу против OpenClaw (>1 GB), NanoBot (>100 MB), PicoClaw (<10 MB), ZeroClaw (<5 MB). Воспроизведение: `zig build -Doptimize=ReleaseSmall && /usr/bin/time -l …`. Как всегда — заявления авторов, фактический замер на 1 GB VM за методологией.
- **Активность**: активная разработка (пуш 2026-10-08, 5 300+ тестов), но **стабильный релизный тег не обновлялся с 2026-05-29** — при фиксации версии придётся брать либо старый тег v2026.5.29, либо nightly-билд. Основные контрибьюторы: DonPrus (1 899 коммитов), manelsen (349).
- **Официальность**: явного предупреждения о самозванцах в README не найдено; поиск по GitHub показывает, что все заметные `nullclaw/*` репозитории принадлежат организации. Канонический репозиторий — `nullclaw/nullclaw`.

### 2. MicroClaw

- **URL**: https://github.com/microclaw/microclaw (сайт: https://microclaw.org). Происхождение: переписанный на Rust « NanoClaw»-подобный ассистент (статья автора «Building MicroClaw», Medium, everettjf).
- **Что это**: self-hosted Rust-платформа агентов: **MicroClaw Server** (always-on: чат-каналы, Web UI на `127.0.0.1:10961`, HTTP/SSE/WebSocket API, планировщик, автоматизация) + нативный десктоп **MicroClaw Work** (GPUI; официально только Apple Silicon macOS, Linux/Windows — portable-превью) + встраиваемый **`microclaw-sdk`** (крейты `microclaw-core`, `microclaw-engine`, `microclaw-sdk` на crates.io). Возобновляемые сессии, чекпоинты, durable-доставка, SQLite-память без внешней векторной БД, skills, MCP, хуки, Docker-песочница. Каждый релиз публикует `SHA256SUMS.txt` и machine-readable reliability scorecard.
- **Лицензия**: MIT.
- **Релиз**: v0.11.1 (2026-10-27) — security-патч (исправление `tool_policy.allow_tools`, advisory GHSA-xww5-ccxc-48jj); предыдущий v0.11.0 (2026-10-25). Коммит: `3c1b14eb28`, 2026-10-27. 748 stars, 137 forks, 2 открытых issues. README: для production использовать ветку `stable`, `main` движется быстро с ломающими изменениями.
- **Linux x86-64 / arm64**: да — Server: `microclaw-0.11.1-x86_64-linux-gnu.tar.gz` (~32 MB) и `microclaw-0.11.1-aarch64-linux-gnu.tar.gz` (~31 MB), плюс варианты `full` (~44 MB, с Matrix) и `work`; есть `.sha256`-сводка. **Требование: glibc ≥ 2.39 и OpenSSL 3** (Ubuntu 24.04+, Debian 13+, Fedora 40+, RHEL 10+); на старых дистрибутивах — сборка из исходников или контейнер.
- **Установка**: `curl -fsSL https://microclaw.org/install.sh | bash` (Windows — install.ps1); Homebrew `brew tap microclaw/tap && brew install microclaw`; Docker `ghcr.io/microclaw/microclaw:latest` (манифест-digest на 2026-10-27: `sha256:f91f92bfadadeb5a584ba959e49615cb447d55a7eda1e6a78c384eb6d0da89dc` — зафиксировать при установке); из исходников `cargo build --release`; Rust SDK — крейты на crates.io. После установки: `microclaw doctor`, `microclaw setup`, `microclaw start`.
- **OpenAI-совместимый бэкенд**: да — нативный Anthropic + «OpenAI, OpenAI Codex, OpenRouter, Ollama, Google, DeepSeek, local servers, and many other services use the shared OpenAI-compatible path»; сгенерированная матрица провайдеров (`docs/generated/provider-matrix.md`) — источник истины. В SDK: `FullRuntimeConfig::new("openai", …)` как базовый сценарий.
- **Заявленный RAM**: **официальной цифры нет**. Качественные заявления: «Operable on modest infrastructure» (Rust-сервис + embedded SQLite, без отдельной векторной БД и service mesh). Бинарные tar.gz ~30 MB — на порядок тяжелее NullClaw. Ожидаемо десятки МБ RAM; требует замера на 1 GB VM.
- **Активность**: очень активная — релиз и коммит в день сбора данных (2026-10-27), security-advisory публикуются, reliability scorecard к каждому релизу, дисциплинированный процесс (заметно влияние AI-ассистированной разработки: контрибьютор `claude` в топе). Основной автор: everettjf (1 079 коммитов).
- **Официальность**: канонический репозиторий — `microclaw/microclaw` (организация `microclaw`). Имя сильно замусорено омонимами — см. ниже.

## Осторожно: омонимы (проверено поиском по GitHub, 2026-10-27)

- **MicroClaw**: по крайней мере четыре посторонних проекта с тем же именем: `Clawland-AI/microclaw` (C/C++ micro AI agent для ESP32/MCU, <1 MB RAM — другой проект, не наш кандидат), `OlegYurchik/MicroClaw` (Python, календари/задачи), `microsofthackathons/MicroClaw` (TypeScript, one-click установщик OpenClaw на Windows), `Micro-Claw/microclaw` (управление микроскопом), `milo-ally-open/microclaw`, `fabiopacificicom/microclaw` (voice-агент на Gemma). Канонический — только `microclaw/microclaw`.
- **NullClaw**: самозванцев не обнаружено; организация `nullclaw` владеет экосистемой (nullhub, nullboiler, nullwatch, nulltickets). Отдельные «вдохновлённые» проекты (`rayclaw/rayclaw`, ThinkOffApp/ClawWatch) — не омонимы.

## Выводы

1. **Оба кандидата найдены, однозначно идентифицированы и живы.** Установка на Linux x86-64 и arm64 возможна у обоих: готовые бинарники в релизах + официальный Docker-образ (digests зафиксированы выше на 2026-10-27, перепроверить при установке) + brew. Пакета pip/cargo для CLI-агента нет ни у одного (у MicroClaw — Rust SDK на crates.io, но это для встраивания, не для установки агента).
2. **OpenAI-совместимый LLM-бэкенд подтверждён у обоих** — сценарий C с OpenAI-совместимым mock-сервером применим к обоим кандидатам без доработок.
3. **MicroClaw — более сильная замена PennyClaw по совокупности**: очень активная разработка (релиз в день проверки против 7 месяцев тишины у PennyClaw), свежий security-патч с публичным advisory, воспроизводимые релизы (SHA256SUMS + reliability scorecard), развитая документация. Риски: требование glibc ≥ 2.39 (проверить ОС на 1 GB VM — если там Debian 12/Ubuntu 22.04, придётся собирать из исходников или брать контейнер) и незаявленный RAM (замерить; вероятно десятки МБ — всё ещё с запасом на 1 GB VM).
4. **NullClaw — экстремум минимализма** (заявлено ~1 MB RAM, бинарник <1 MB) — идеально ложится в сценарий 1 GB VM и даёт самую яркую точку в спектре кандидатов. Риск: стабильный релиз v2026.5.29 устарел (~5 мес.); для прогонов брать свежий nightly-билд (с `.sha256`) с фиксацией SHA, либо собрать из исходников (Zig 0.16.0 строго).
5. **Рекомендация**: включить в матрицу обоих — MicroClaw как основную замену PennyClaw (активность и зрелость процессов), NullClaw как второго кандидата второй волны (уникальный профиль ресурса). Если брать только одного — MicroClaw: для бенчмарка важнее живой проект с предсказуемым релизным процессом, чем самый маленький, но с устаревшим стабильным тегом. RAM-заявления обоих (особенно ~1 MB у NullClaw) подлежат обязательному фактическому замеру по METHODOLOGY.md.
