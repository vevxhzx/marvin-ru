"""Событийный слой: одно место, куда всё в ядре сообщает «случилось X», и откуда реагируют подписчики.

Зачем: раньше «случилось» существовало только как broadcast() во вкладки сайта. Реакций не было — пульс ПК писал
экранное время, планировщик слал напоминания, и они друг о друге не знали. Теперь:

    events.emit("user_back", key="back", minutes=25)          # источник: state.tick()
    events.on("user_back", fn)                                 # подписчик: attention / proactive / сайт

Правила:
• Дедуп: тот же kind+key в окне dedup_sec игнорируется (простой с зависшим пульсом не шлёт «отошёл» 40 раз).
• Журнал: каждое принятое событие — строка Memory(kind="presence", text=…, channel="system") — это и есть лента (timeline.py).
  Тихие события (quiet=True: смена окна, пульс) в журнал не пишутся, только подписчикам.
• Подписчик падает — логируем, остальные получают событие; эмиттер никогда не бросает.
• Всё синхронно и в процессе ядра. Очередь/брокер не нужны: одно приложение, один человек.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

log = logging.getLogger("marvin.events")

# kind → человеческое описание для журнала (что писать в ленту). Нет в словаре — пишем kind как есть.
LABELS = {
    "user_arrived": "сел за компьютер",
    "user_idle": "отошёл от компьютера",
    "user_back": "вернулся за компьютер",
    "user_away": "давно нет за компьютером",
    "long_session": "без перерыва {hours} ч",
    "heavy_job_started": "запущена тяжёлая работа: {app}",
    "heavy_job_finished": "тяжёлая работа завершена: {app} ({minutes} мин)",
    "app_focus": "переключился: {app}",
    "task_done": "закрыта задача «{title}»",
    "goal_step_done": "шаг к цели «{aim}»: «{title}»",
    "milestone_done": "веха «{milestone}» цели «{aim}» закрыта",
    "aim_ready": "все вехи цели «{aim}» закрыты",
    "aim_done": "цель «{aim}» достигнута",
    "aim_dropped": "цель «{aim}» снята",
    "health_bad": "самопроверка: есть проблемы",
    "health_ok": "самопроверка: снова всё в порядке",
    "deadline_soon": "дедлайн скоро: «{title}»",
    "background_started": "фон: {job} запущен",
    "background_done": "фон: {job} завершён",
    "background_failed": "фон: {job} упал — {error}",
    "assistant_notified": "Марвин написал: {what}",
    "restart": "ядро перезапущено",
}

Handler = Callable[["Event"], None]


@dataclass
class Event:
    kind: str
    key: str = ""
    data: dict = field(default_factory=dict)
    at: datetime = field(default_factory=datetime.now)
    quiet: bool = False

    @property
    def text(self) -> str:
        tpl = LABELS.get(self.kind, self.kind)
        try:
            return tpl.format(**self.data)
        except (KeyError, IndexError, ValueError):
            return tpl


_handlers: dict[str, list[Handler]] = {}
_any: list[Handler] = []
_recent: dict[tuple[str, str], float] = {}     # (kind, key) → time.time() последнего принятого
_last: list[Event] = []                        # последние N в памяти (для статуса и тестов)
KEEP = 200


def on(kind: str, fn: Handler) -> None:
    """Подписаться. kind="*" — на всё."""
    (_any if kind == "*" else _handlers.setdefault(kind, [])).append(fn)


def off(kind: str, fn: Handler) -> None:
    lst = _any if kind == "*" else _handlers.get(kind, [])
    if fn in lst:
        lst.remove(fn)


def emit(kind: str, key: str = "", dedup_sec: float = 0, quiet: bool = False, journal: bool = True, **data) -> Event | None:
    """Принять событие. Возвращает Event или None, если это дубль."""
    k = (kind, key or "")
    now = time.time()
    if dedup_sec and now - _recent.get(k, 0) < dedup_sec:
        return None
    _recent[k] = now
    if len(_recent) > 2000:   # не даём словарю расти вечно
        for kk in sorted(_recent, key=_recent.get)[:1000]:
            _recent.pop(kk, None)
    ev = Event(kind=kind, key=key or "", data=data, quiet=quiet)
    _last.append(ev)
    del _last[:-KEEP]
    if journal and not quiet:
        try:
            from ..db import Memory, session
            with session() as s:
                s.add(Memory(kind="presence", text=ev.text, ref_table="presence", ref_id=None, channel="system"))
                s.commit()
        except Exception as e:  # pragma: no cover — журнал не должен ронять источник события
            log.debug("event journal: %s", e)
    for fn in list(_handlers.get(kind, [])) + list(_any):
        try:
            fn(ev)
        except Exception as e:
            log.warning("подписчик %s на %s упал: %s", getattr(fn, "__name__", fn), kind, e)
    return ev


def recent(limit: int = 20, kinds: tuple[str, ...] | None = None) -> list[Event]:
    out = [e for e in _last if not kinds or e.kind in kinds]
    return out[-limit:]


def reset() -> None:
    """Для тестов: снять подписчиков и забыть дедуп."""
    _handlers.clear(); _any.clear(); _recent.clear(); _last.clear()
