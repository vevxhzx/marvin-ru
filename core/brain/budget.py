"""Порядок блоков промпта и потолки контекста.

Зачем отдельный модуль: системный промпт, блок памяти, уроки и история собирались в трёх разных
местах (`agent._system`, `agent.via_ollama`, `agent.via_gemini`) и ужимались по-разному. Здесь —
единственное место, где решено, что и в каком порядке уходит в модель и что можно резать.

Правила (их нельзя нарушать без последствий для качества):
* порядок блоков ЕДИНЫЙ: личность и характер → правила работы с инструментами → уроки хозяина →
  что известно о хозяине → «не повторяй образы» → хвост истории → текущая реплика;
* важные блоки (характер, факты core/state, уроки, стиль) не обрезаются НИКОГДА — режется только
  «наполнение»: дальняя история и подряд идущие релевантные факты;
* хвост истории (последние реплики) сохраняется целиком, а то, что не влезло, сворачивается
  в одну сводку — раньше оно просто выбрасывалось, и модель теряла нить разговора.

Всё настраивается в config.yaml (см. config.example.yaml → brain.prompt.*). Дефолты подобраны так,
чтобы поведение по умолчанию осталось прежним: потолки не включаются, пока их не задали.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from ..config import cfg

log = logging.getLogger("jarvis.budget")

# оценка размера — та же, что в llm.ollama_chat и agent._fit_budget (символы/3), чтобы числа сходились
CHARS_PER_TOKEN = 3
_RESERVE = 200          # служебные токены Ollama на служебный обмен
_GENERATE = 512         # запас под генерацию ответа (160 в голосовом режиме)


def _p(key: str, default):
    """Настройка brain.prompt.* с безопасным дефолтом (работает и когда раздела в config.yaml нет)."""
    node = getattr(getattr(cfg, "brain", None), "prompt", None)
    val = getattr(node, key, None) if node is not None else None
    return default if val is None or val == "" else val


def estimate_tokens(text: str | None) -> int:
    return len(text or "") // CHARS_PER_TOKEN


def system_max_chars() -> int:
    """Потолок статики системного промпта в символах. 0 = выключен (поведение по умолчанию)."""
    try:
        return max(0, int(_p("system_max_chars", 0) or 0))
    except (TypeError, ValueError):
        return 0


def history_turns() -> int:
    """Сколько последних реплик отдаём целиком (по умолчанию как было — 6)."""
    try:
        return max(1, int(_p("history_turns", 6) or 6))
    except (TypeError, ValueError):
        return 6


def history_max_chars() -> int:
    try:
        return max(80, int(_p("history_turn_chars", 600) or 600))
    except (TypeError, ValueError):
        return 600


def summary_enabled() -> bool:
    return bool(_p("history_summary", True))


def est_request(messages: Iterable[dict], tools: list[dict] | None = None) -> int:
    """Оценка размера запроса в токенах — тем же счётом, что использует Ollama."""
    body = sum(len(str(m.get("content") or "")) for m in messages)
    schemas = len(json.dumps(tools, ensure_ascii=False)) if tools else 0
    return (body + schemas) // CHARS_PER_TOKEN + _RESERVE


# --------------------------------------------------------------------------- сводка выброшенного
_DIGIT_RX = re.compile(r"\d")


def _one_line(text: str, limit: int = 90) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return (cut or t[:limit]).rstrip(" ,.;:—-") + "…"


def summarize(turns: list[dict], limit: int = 3) -> str:
    """Одна строка о том, что было в выброшенной части разговора.

    Не пересказ (это стоит токенов и модель всё равно им не пользуется), а список тем: с кем
    говорили и о чём. Номера и суммы оставляем — по ним видно, что речь о делах, а не о болтовне."""
    picked: list[str] = []
    for t in turns:
        # реплики приходят и как {"text": …} (собранные _history), и как {"content": …} (сообщения LLM)
        text = (t.get("text") or t.get("content") or "").strip()
        if not text or text.startswith("Что-то пошло не так"):
            continue
        who = "хозяин" if t.get("role") == "user" else "я"
        picked.append(f"{who}: {_one_line_nodup(text, 70)}")
    if not picked:
        return ""
    # хвост важнее начала: последние темы — те, к которым возвращаются
    picked = picked[-limit:]
    return "РАНЕЕ В ЭТОМ РАЗГОВОРЕ (кратко, не дословно): " + " | ".join(picked)


def _one_line_nodup(text: str, limit: int = 70) -> str:
    """Как _one_line, но повторяющиеся слова схлопывает: «подробностей подробностей подробностей…»
    в сводке не несут смысла, а стоят токенов наравне с полезным."""
    words = re.findall(r"\S+", text or "")
    out: list[str] = []
    for w in words:
        if out and w == out[-1]:
            continue
        out.append(w)
        if len(" ".join(out)) >= limit:
            break
    t = " ".join(out).rstrip(" ,.;:—-")
    return (t + "…") if len(t) >= limit else t


# --------------------------------------------------------------------------- единый порядок блоков
# имя -> (обязательный ли, приоритет сохранения). Чем выше число, тем позже режется.
# required=True — не трогаем никогда (личность, факты core/state, уроки, стиль).
BLOCK_ORDER = (
    "persona",        # характер, обращение, запреты — ядро голоса
    "rules",          # как работать с инструментами
    "safety",         # содержимое заметок/ссылок — данные, а не команды
    "style",          # профиль стиля хозяина (постоянная строка, кэш промпта не сбивается)
    "lessons",        # уроки хозяина
    "memory_core",    # факты core/state
    "memory_rel",     # релевантные факты — единственное, что режется первым
    "no_repeat",      # не повторять образы
    "history_summary",  # одна строка о выброшенной истории
    "history",        # хвост истории
    "now",            # «сейчас …»
    "text",           # текущая реплика
)
# приоритет: 0 = не режем никогда, 100 = режем первым
KEEP_FOREVER = {"persona", "rules", "safety", "style", "lessons", "memory_core", "text"}
TRIM_ORDER = ("memory_rel", "history_summary", "no_repeat", "history", "now")


def assemble(parts: dict[str, str]) -> str:
    """Склеить блоки в единственном порядке (пустые пропускаются)."""
    return "".join(parts.get(name, "") for name in BLOCK_ORDER if parts.get(name))


def trim_static(system: str, max_chars: int) -> str:
    """Потолок для СИСТЕМНОГО промпта.

    Важные блоки (личность, характер, безопасность, отказы) не режутся НИКОГДА. Убираются только
    помеченные необязательные — образцы тона, формула подкола, градация: то, что маленькая локальная
    модель всё равно не воспроизводит, а токены стоит. Блок вырезается ЦЕЛИКОМ по границам абзацев
    (обрезка на середине фразы ломает смысл) и только если после этого промпт влезает в потолок.
    Если не влезает и без них — не режем по символам: тихо испорченный характер хуже превышения
    потолка, о котором честно пишем в лог."""
    if not max_chars or len(system) <= max_chars:
        return system
    out = system
    for start_marker, end_marker in _OPTIONAL_BLOCKS:
        if len(out) <= max_chars:
            return out
        i = out.find(start_marker)
        if i < 0:
            continue
        j = out.find(end_marker, i + len(start_marker))
        if j < 0:
            continue
        out = out[:i] + out[j:]      # убираем целиком и продолжаем считать от результата
    if len(out) <= max_chars:
        return out
    log_budget(system, max_chars)
    return out


# (начало, конец) необязательных блоков. Порядок = порядок убирания: первым уходит самое дорогое.
_OPTIONAL_BLOCKS = (
    ("\nОБРАЗЦЫ ТОНА", "\nГРАДАЦИЯ."),   # ~1.4k симв. образцов манеры
    ("\nФОРМУЛА.", "\nГРАДАЦИЯ."),        # ~450 симв. правила подкола
    ("\nГРАДАЦИЯ.", "\nЗАПРЕЩЕНО."),      # ~600 симв. градации по важности
)


def log_budget(system: str, max_chars: int) -> None:
    logging.getLogger("jarvis.budget").info(
        "системный промпт %d симв. > потолок %d — важные блоки (характер, безопасность, отказы) "
        "оставил как есть: резать их нельзя", len(system), max_chars)