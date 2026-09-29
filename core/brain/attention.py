"""Модель поведения: одно место, где решается «сказать сейчас / отложить / промолчать / голосом».

До 0.10 это были четыре независимых проверки: тихие часы в scheduler._quiet_now, лимит в proactive._today_count,
«человек в чате» в llm.user_recent, голос в persona.choose_channel. Они не знали друг о друге и ничего не знали о том,
чем человек занят. Теперь всё, что хочет заговорить само (инициативы, реакции на события, фон), спрашивает здесь:

    d = attention.decide(kind="heavy_job_finished", importance=2)
    d.verdict ∈ {"now", "later", "silent"}, d.channel ∈ {"text", "voice"}, d.why — почему (в лог и статус)

Факторы (все — из state.snapshot() и настроек, ничего нового не собирается):
• тихие часы → later (urgent=True — исключение: напоминания, которые человек сам поставил)
• бюджет дня (notifications.proactive_per_day, общий для инициатив И реакций) → silent
• игра / тяжёлая программа в фокусе (interruption cost высок) → later, если importance < 3
• человек прямо сейчас пишет/говорит (≤ 90 с) → later на минуту, а не поверх его реплики
• человек отошёл (idle/away/offline) → later: отдать, когда вернётся (user_back), кроме importance 3 — в TG сразу
• только что сел (< 2 мин) → later 2 мин: дать открыть почту, не встречать у двери
• важность: 1 — можно и промолчать (шутка, наблюдение), 2 — полезно (закончился рендер, веха), 3 — важно (упал фон,
  дедлайн сегодня, платёж). importance 1 при любом сомнении → silent.

Отложенные лежат в очереди (Setting "attention.queue", JSON, ≤ 10, TTL 6 ч) и отдаются при user_back / следующем тике.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..config import cfg
from ..db import get_setting, set_setting

log = logging.getLogger("marvin.attention")

QUEUE_KEY = "attention.queue"
COUNT_KEY = "proactive.count"    # тот же счётчик, что у proactive — бюджет один на всех
QUEUE_MAX = 10
QUEUE_TTL_H = 6


@dataclass
class Decision:
    verdict: str          # now / later / silent
    channel: str = "text" # text / voice
    why: str = ""
    delay_min: int = 0    # для later: через сколько попробовать (0 — при возврате человека)

    @property
    def ok(self) -> bool:
        return self.verdict == "now"


# ----------------------------------------------------------------- факторы
def quiet_hours(now: datetime | None = None) -> bool:
    n = getattr(cfg, "notifications", None)
    try:
        start = int(getattr(n, "quiet_from", 23) if getattr(n, "quiet_from", 23) is not None else 23) % 24
        end = int(getattr(n, "quiet_to", 8) if getattr(n, "quiet_to", 8) is not None else 8) % 24
    except (TypeError, ValueError):
        start, end = 23, 8
    h = (now or datetime.now()).hour
    if start == end:
        return False
    return (h >= start or h < end) if start > end else (start <= h < end)


def budget_left(now: datetime | None = None) -> int:
    n = getattr(cfg, "notifications", None)
    try:
        per_day = max(0, int(getattr(n, "proactive_per_day", 5) or 5)) if n is not None else 5
    except (TypeError, ValueError):
        per_day = 5
    raw = get_setting(COUNT_KEY, "") or ""
    d, _, cnt = raw.partition("|")
    used = int(cnt) if d == (now or datetime.now()).strftime("%Y-%m-%d") and cnt.isdigit() else 0
    return max(0, per_day - used)


def spend(now: datetime | None = None) -> None:
    now = now or datetime.now()
    raw = get_setting(COUNT_KEY, "") or ""
    d, _, cnt = raw.partition("|")
    used = int(cnt) if d == now.strftime("%Y-%m-%d") and cnt.isdigit() else 0
    set_setting(COUNT_KEY, f"{now:%Y-%m-%d}|{used + 1}")


def _busy_app() -> str:
    """Игра или тяжёлая программа в фокусе — перебивать дорого."""
    try:
        from ..services import state
        from ..brain import llm
        sn = state.snapshot()
        if getattr(llm, "GAME_MODE", False):
            return "игровой режим"
        if sn["presence"] == "active" and sn["cat"] == "игра":
            return sn["app"] or "игра"
        if sn["heavy"]:
            return "рендер: " + ", ".join(sn["heavy"])
        return ""
    except Exception:  # pragma: no cover
        return ""


# ----------------------------------------------------------------- решение
def decide(kind: str, importance: int = 2, urgent: bool = False, now: datetime | None = None, text: str = "") -> Decision:
    now = now or datetime.now()
    importance = max(1, min(3, int(importance)))
    if urgent:
        return Decision("now", "text", "срочное — всегда сразу")
    if quiet_hours(now):
        return Decision("later" if importance >= 2 else "silent", "text", "тихие часы")
    left = budget_left(now)
    if left <= 0 and importance < 3:
        return Decision("silent", "text", "бюджет инициатив на сегодня исчерпан")
    try:
        from ..brain import llm
        if llm.user_recent(90):
            return Decision("later", "text", "человек сейчас пишет", delay_min=1)
    except Exception:  # pragma: no cover
        pass
    busy = _busy_app()
    if busy and importance < 3:
        return Decision("later", "text", f"занят: {busy}")
    try:
        from ..services import state
        sn = state.snapshot(now)
    except Exception:  # pragma: no cover
        sn = {"presence": "offline", "presence_min": None, "session_min": None}
    p = sn["presence"]
    try:
        if p != "active" and state.talking(now):
            p = "chat"   # ПК-клиента нет или человек отошёл от ПК, но пишет с телефона — он рядом
    except Exception:  # pragma: no cover
        pass
    if p in ("idle", "away") and importance < 3:
        return Decision("later", "text", "человека нет за ПК — скажу, когда вернётся")
    if p == "active" and (sn.get("session_min") or 0) < 2 and importance < 3 and kind not in ("user_arrived", "restart"):
        return Decision("later", "text", "только сел — дам минуту", delay_min=2)
    if importance == 1 and (left <= 1 or p not in ("active", "chat")):
        return Decision("silent", "text", "мелочь, а бюджет/момент не располагают")
    # канал: голос — только акцент (итоги дня, «разнос»), решает persona
    channel = "text"
    try:
        from ..brain import persona
        channel = persona.choose_channel(kind, text, urgent)
    except Exception:  # pragma: no cover
        pass
    return Decision("now", channel, "момент подходящий")


# ----------------------------------------------------------------- очередь отложенных
def _load() -> list[dict]:
    try:
        q = json.loads(get_setting(QUEUE_KEY, "") or "[]")
        cutoff = datetime.now() - timedelta(hours=QUEUE_TTL_H)
        return [i for i in q if datetime.fromisoformat(i["at"]) >= cutoff]
    except (ValueError, TypeError, KeyError):
        return []


def _save(q: list[dict]) -> None:
    set_setting(QUEUE_KEY, json.dumps(q[-QUEUE_MAX:], ensure_ascii=False))


def defer(kind: str, text: str, importance: int = 2, buttons: list | None = None, key: str = "", not_before: datetime | None = None) -> None:
    """Отложить сообщение до подходящего момента. Тот же key заменяет старое (не копим «вернулся» ×5)."""
    q = [i for i in _load() if not key or i.get("key") != key]
    q.append({"kind": kind, "text": text, "importance": importance, "buttons": buttons or [], "key": key,
              "at": datetime.now().isoformat(), "not_before": not_before.isoformat() if not_before else None})
    _save(q)


def due(now: datetime | None = None) -> list[dict]:
    """Отложенные, которые пора попробовать отдать (not_before прошёл). Снимает их с очереди — вызывающий решает через decide()."""
    now = now or datetime.now()
    q = _load()
    ready, rest = [], []
    for i in q:
        nb = i.get("not_before")
        (ready if not nb or datetime.fromisoformat(nb) <= now else rest).append(i)
    _save(rest)
    return ready


def queue_size() -> int:
    return len(_load())


def clear() -> None:
    set_setting(QUEUE_KEY, "[]")
