# Run Matrix — Oracle 1 GB Campaign (2026-10-27)

Порядок и чек-лист по LAUNCH_PLAN.md. Каждый кандидат — полный цикл A→B→C→D
(кроме PicoClaw: только native; NullClaw: только Scenario A), между кандидатами —
полная очистка + drop_caches + пауза 60 сек.

Правила при сбоях — см. LAUNCH_PLAN.md §9 (failure policy #29):
`install_failed`/guard 4 → строка в «Ограничения результата», кампания идёт дальше.
Среда: `ssh ubuntu@129.151.214.117`, прогоны в `~/bench-runs`, харнес `~/bench`.

## Матрица

| # | Кандидат | Mode | A (cold start) | B (mock LLM) | C (real LLM) | D (stability) | Статус | Run ID / заметки |
|---|---|---|---|---|---|---|---|---|
| 1 | ZeptoClaw 0.9.2 | native | ☑ | ☑ | ☑ | ☑ | готов | A `1c1aa4d8` 3/3 ok; B `96d71e68` 30/30 p50=52мс; C `2ba9c95c` 20/20 ok; D `3f954b3f` 100/100, restart_state=lost |
| 1 | ZeptoClaw 0.9.2 | docker | ☑ | ☑ | ☑ | ☑ | готов | A `cb3e1ee8` 3/3; B `d1007348` 30/30; C `4e630b06` 20/20; D `e11fb11a` 100/100, restart_state=lost (после фикса харнеса: docker rm -f при рестарте) |
| 2 | ZeroClaw 0.8.6 | native | ☐ | ☐ | ☐ | ☐ | не начат | |
| 2 | ZeroClaw 0.8.6 | docker | ☐ | ☐ | ☐ | ☐ | не начат | |
| 3 | Picobot 0.3.0 | docker | ☐ | ☐ | ☐ | ☐ | не начат | |
| 4 | PicoClaw 0.3.1 | native | ☐ | ☐ | ☐ | ☐ | не начат | |
| 5 | Moltis 20261023.01 | docker | ☐ | ☐ | ☐ | ☐ | не начат | |
| 6 | MicroClaw 0.11.1 | native | ☐ | ☐ | ☐ | ☐ | не начат | |
| 6 | MicroClaw 0.11.1 | docker | ☐ | ☐ | ☐ | ☐ | не начат | |
| 7 | NullClaw nightly-2026-09-27 | native | ☐ (только A) | — | — | — | не начат | |
| 7 | NullClaw nightly-2026-09-27 | docker | ☐ (только A) | — | — | — | не начат | |

## Команда на прогон (шаблон)

```bash
ssh ubuntu@129.151.214.117
cd ~/bench-runs
uv run --project ~/bench python -m bench run \
  ~/bench/descriptors/<name>.toml \
  ~/bench/scenarios/<scenario>.toml \
  --proc-root /proc --cgroup-root /sys/fs/cgroup \
  --runs-dir ./runs --mock-llm-port 0
# docker-дескрипторы: + --docker-bin docker
```

Сценарии: A `a_cold_start.toml`, B `b_mock_llm.toml`, C `c_real_llm.toml`
(4 задачи × 5 повторов), D `d_stability.toml`.

## Pre-flight

- ☐ Docker на VM (уже установлен: /usr/bin/docker)
- ☐ Старый zeptoclaw на 9091 остановлен (pid отсутствует — проверено 2026-10-27)
- ☐ Харнес на VM обновлён до #29 (commit 21d4ec1)
- ☐ FreeLLMAPI запущен на Mac (:3001)
- ☐ Cloudflare Workers AI ключ добавлен в FreeLLMAPI UI (нужно руками)
- ☐ SSH-туннель 3001 Mac→VM поднят
- ☐ `curl http://localhost:3001/v1/models` с VM отвечает
- ☐ `~/bench-runs` создан
