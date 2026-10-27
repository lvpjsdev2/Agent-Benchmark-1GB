"""Secret sanitizer — scans records and logs before they are written to disk.

Ticket #16: попадание секрета блокирует сохранение сырого текста, оставляя
пометку [REDACTED]. Все пути записи (record.jsonl, repeats.jsonl, отчёт)
проходят через этот модуль.
"""

from __future__ import annotations

import re

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-подобные ключи
    re.compile(r"bearer\s+[A-Za-z0-9._~+/-]{10,}", re.IGNORECASE),  # bearer-токены
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),  # IP-адреса
    re.compile(r"gh[op]_[A-Za-z0-9]{36}"),  # GitHub-токены
]

SANITIZER_MARKER = "[REDACTED]"
# Ключ заметки в записи, когда санитайзер что-то заменил.
SANITIZER_NOTE = "sanitizer_triggered=true"


def sanitize_text(text: str) -> str:
    """Заменяет обнаруженные секреты на [REDACTED]."""
    if not text:
        return text
    sanitized = text
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub(SANITIZER_MARKER, sanitized)
    return sanitized


def sanitize_value(value):
    """Рекурсивно санитизирует строки внутри dict/list/скаляров.

    Возвращает (новое_значение, было_ли_что_то_заменено).
    """
    if isinstance(value, str):
        sanitized = sanitize_text(value)
        return sanitized, sanitized != value
    if isinstance(value, dict):
        out = {}
        redacted = False
        for k, v in value.items():
            new_v, hit = sanitize_value(v)
            out[k] = new_v
            redacted = redacted or hit
        return out, redacted
    if isinstance(value, list):
        out = []
        redacted = False
        for item in value:
            new_item, hit = sanitize_value(item)
            out.append(new_item)
            redacted = redacted or hit
        return out, redacted
    return value, False


def sanitize_record(record: dict) -> tuple[dict, bool]:
    """Возвращает санитизированную копию записи и флаг срабатывания."""
    return sanitize_value(record)
