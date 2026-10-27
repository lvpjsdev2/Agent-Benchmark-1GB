"""Генератор отчёта по docs/REPORT_TEMPLATE.md (тикет #17/#19).

Собирает markdown из накопленных run records. Правила:
- отсутствующие значения (null) рендерятся прочерком «—»;
- величины, которые харнес не собирает (например, Disk MB), помечаются
  «unsupported», а не нулём;
- native и docker прогоны одного кандидата попадают в разные строки
  (строка ключуется парой (agent, mode));
- одинаковый набор записей даёт одинаковый отчёт (нет меток времени генерации);
- провалы старта из notes попадают в «Ограничения результата» (ticket #29);
- весь вывод прогоняется через санитайзер — секретов в отчёте нет.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from bench.sanitize import sanitize_text


def load_records(runs_dir: str | Path) -> list[dict]:
    """Читает все runs/<id>/record.jsonl; сортирует детерминированно."""
    records: list[dict] = []
    for path in sorted(Path(runs_dir).glob("*/record.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
    records.sort(
        key=lambda r: (
            str(r.get("agent") or ""),
            str(r.get("mode") or ""),
            str(r.get("scenario") or ""),
            str(r.get("started_at_utc") or ""),
            str(r.get("run_id") or ""),
        )
    )
    return records


def _fmt(value, unsupported: bool = False) -> str:
    if unsupported:
        return "unsupported"
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def _join(values: list[str]) -> str:
    """Comma-joined unique values, or a dash when nothing was recorded."""
    return ", ".join(values) if values else "—"


def _median_of(profiles: list[dict], key: str) -> float | None:
    """Median of one host-profile field across records (ticket #37).

    The passport renders a single value per line, and it must not depend on how
    many runs contributed: a median keeps the line deterministic.
    """
    values = [p.get(key) for p in profiles if p.get(key) is not None]
    return statistics.median(values) if values else None


_DOCKER_IMAGE_RE = re.compile(r"docker_image=(\S+)")


def _version_line(record: dict) -> str:
    """Agent / mode / version, plus the pinned digest when one was recorded."""
    line = f"{record.get('agent')} {record.get('mode')} {record.get('version')}"
    notes = " ".join(str(record.get("notes") or "").split())
    image = _DOCKER_IMAGE_RE.search(notes)
    if image:
        line += f" ({image.group(1)})"
    return line


def _deviation_summary(records: list[dict]) -> str:
    """Passport line derived from records, never hardcoded (ticket #37).

    A run deviates from the full plan when a guard aborted it, when the candidate
    never started, or when it left unfinished (orphaned) processes behind.
    """
    deviating = 0
    for r in records:
        notes = " ".join(str(r.get("notes") or "").split())
        unfinished = re.search(r"unfinished_processes=(\d+)", notes)
        if (
            "aborted=" in notes
            or "install_failed=" in notes
            or (unfinished is not None and int(unfinished.group(1)) > 0)
        ):
            deviating += 1
    if not deviating:
        return "нет"
    return f"есть: {deviating} из {len(records)} прогонов — см. «Ограничения результата»"


# Start failures the runner records in notes (ticket #29). Notes are joined with
# ", " and a reason may itself contain commas, so a value runs until the next
# "<key>=" field. Only "the candidate never came up" counts here: a guard that
# trips mid-run (OOM, MemAvailable, API budget, health lost) is not a start
# failure and stays out of the «не запустились» bullet.
_ABORTED_RE = re.compile(r"aborted=guard(?P<code>\d+):(?P<reason>.*?)(?:, [a-z0-9_]+=|$)", re.S)
_INSTALL_FAILED_RE = re.compile(r"(?:^|, )install_failed=(?P<reason>.*?)(?:, [a-z0-9_]+=|$)", re.S)
_START_FAILURE_MARKERS = ("install_failed=", "start attempt(s)")


def _start_failure_reason(notes: str) -> str | None:
    """Build the reason for a run whose candidate did not start, else None."""
    aborted = _ABORTED_RE.search(notes)
    if aborted:
        reason = aborted.group("reason")
        if any(marker in reason for marker in _START_FAILURE_MARKERS):
            return f"{reason} (guard {aborted.group('code')})"
        return None
    install = _INSTALL_FAILED_RE.search(notes)
    if install:
        return f"install_failed={install.group('reason')} (guard 6)"
    return None


def _start_failures(records: list[dict]) -> list[str]:
    """One bullet per run the candidate could not be started for (ticket #29).

    Deterministic: `records` is already sorted by load_records(). Whitespace in a
    reason is collapsed so a multi-line stderr cannot break the markdown list.
    """
    bullets: list[str] = []
    for r in records:
        notes = " ".join(str(r.get("notes") or "").split())
        reason = _start_failure_reason(notes)
        if not reason:
            continue
        bullets.append(
            f"  - {r.get('agent')} ({r.get('mode')}, run {r.get('run_id')}, "
            f"{r.get('scenario')}): {reason}"
        )
    return bullets


def generate_report(records: list[dict]) -> str:
    """Генерирует markdown-отчёт (структура docs/REPORT_TEMPLATE.md)."""
    lines: list[str] = []
    lines.append("# Итоговый отчёт — Agent Benchmark 1GB")
    lines.append("")

    # --- Паспорт эксперимента -------------------------------------------
    stamps = [r.get("started_at_utc") for r in records if r.get("started_at_utc")]
    period = f"{min(stamps)} — {max(stamps)}" if stamps else "—"
    # An unavailable record (ticket #29) has no host_profile: a missing profile
    # renders as a dash, it never aborts report generation.
    profiles = [r.get("host_profile") or {} for r in records if r.get("host_profile")]
    os_names = _join(sorted({str(p["os"]) for p in profiles if p.get("os")}))
    kernels = _join(sorted({str(p["kernel"]) for p in profiles if p.get("kernel")}))
    cpus = _join([
        str(c) for c in sorted({p.get("cpu_count") for p in profiles if p.get("cpu_count") is not None})
    ])
    ram_total_mb = _median_of(profiles, "ram_total_mb")
    swap_total_mb = _median_of(profiles, "swap_total_mb")
    swap_free_mb = _median_of(profiles, "swap_free_mb")
    baselines = [p.get("mem_available_mb_baseline") for p in profiles]
    baselines = [b for b in baselines if b is not None]
    versions = sorted({_version_line(r) for r in records}) or ["—"]
    swap_text = _fmt(swap_total_mb)
    if swap_free_mb is not None:
        swap_text += f" (free {_fmt(swap_free_mb)})"

    lines.append("## Паспорт эксперимента")
    lines.append("")
    lines.append(f"- UTC-период: {period}")
    lines.append(f"- ОС хоста, ядро, CPU: {os_names}, {kernels}, {cpus}")
    lines.append(
        "- RAM / swap / MemAvailable до тестов (MB): "
        f"{_fmt(ram_total_mb)} / {swap_text} / {_fmt(statistics.median(baselines) if baselines else None)}"
    )
    lines.append(f"- Версии агентов (имя / режим / версия / digest): {', '.join(versions)}")
    lines.append("- Реальный провайдер и модель (без ключей): —")
    lines.append(f"- Отклонения от методики: {_deviation_summary(records)}")
    lines.append("")

    # --- Результаты ресурсов ---------------------------------------------
    lines.append("## Результаты ресурсов")
    lines.append("")
    lines.append("| Агент | Режим | Idle PSS MB (median) | Peak MB (full stack) | CPU-s | Startup p50 ms | Disk MB | OOM |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    rows = sorted({(str(r.get("agent")), str(r.get("mode"))) for r in records})
    if rows:
        for agent, mode in rows:
            group = [r for r in records if str(r.get("agent")) == agent and str(r.get("mode")) == mode]
            primary = next((r for r in group if r.get("ram_pss_mb_median") is not None), group[0])
            lines.append(
                "| {agent} | {mode} | {pss} | {peak} | {cpu} | {startup} | {disk} | {oom} |".format(
                    agent=agent,
                    mode=mode,
                    pss=_fmt(primary.get("ram_pss_mb_median")),
                    peak=_fmt(primary.get("ram_peak_mb")),
                    cpu=_fmt(primary.get("cpu_sec")),
                    startup=_fmt(primary.get("startup_ms")),
                    disk=_fmt(None, unsupported="disk_mb" not in primary),
                    oom=_fmt(primary.get("oom_count")),
                )
            )
    else:
        lines.append("| — | — | — | — | — | — | — | — |")
    lines.append("")

    # --- Функции и качество ----------------------------------------------
    lines.append("## Функции и качество")
    lines.append("")
    lines.append("| Агент | Базовый чат | Работа с файлами | Безопасный shell | MCP | Память | Cron | Telegram | Примечание |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    if rows:
        for agent, mode in rows:
            lines.append(f"| {agent} ({mode}) | — | — | — | — | — | — | — | — |")
    else:
        lines.append("| — | — | — | — | — | — | — | — | — |")
    lines.append("")

    # --- Статистика сценариев --------------------------------------------
    lines.append("## Статистика сценариев")
    lines.append("")
    scenarios = sorted({str(r.get("scenario")) for r in records if r.get("scenario")})
    if scenarios:
        for name in scenarios:
            group = [r for r in records if str(r.get("scenario")) == name]
            success = sum(int(r.get("success_count") or 0) for r in group)
            errors = sum(int(r.get("error_count") or 0) for r in group)
            p50s = [r.get("latency_p50_ms") for r in group if r.get("latency_p50_ms") is not None]
            p95s = [r.get("latency_p95_ms") for r in group if r.get("latency_p95_ms") is not None]
            lines.append(
                f"- {name}: записей={len(group)}, success={success}, errors={errors}, "
                f"latency p50={_fmt(statistics.median(p50s) if p50s else None)} мс, "
                f"p95={_fmt(statistics.median(p95s) if p95s else None)} мс"
            )
    else:
        lines.append("- —")
    lines.append("")

    # --- Ограничения результата -------------------------------------------
    lines.append("## Ограничения результата")
    lines.append("")
    lines.append("- Какие функции оказались недоступны и по какой причине: —")
    lines.append("- Какие результаты искажены соседними процессами, swap или сетевой задержкой: —")
    failures = _start_failures(records)
    if failures:
        lines.append("- Какие проекты не запустились и почему:")
        lines.extend(failures)
    else:
        lines.append("- Какие проекты не запустились и почему: —")
    lines.append("- Какие измерения повторить: —")
    lines.append("")

    # --- Выводы ------------------------------------------------------------
    lines.append("## Выводы")
    lines.append("")
    lines.append("- Минимальные накладные расходы: —")
    lines.append("- Лучший функциональный компромисс: —")
    lines.append("- Лучший для круглосуточной эксплуатации: —")
    lines.append("- Итоговый рекомендуемый вариант и безопасная конфигурация: —")
    lines.append("- Следующее решение пользователя: —")
    lines.append("")

    return sanitize_text("\n".join(lines))
