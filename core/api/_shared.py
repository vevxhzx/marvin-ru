"""Общее состояние уровня модуля для роутов `core/api/routers/*` (ФАЗА 7, шаг 7.0).

Сюда вынесено ТОЛЬКО то, что реально нужно нескольким роутерам:

* `broadcast` — рассылка SSE всем открытым вкладкам. Её зовут роуты почти всех
  модулей, и её же импортирует `core/crm/router.py` (`from ..api.app import broadcast`),
  поэтому в `app.py` она реэкспортируется — старые импорты продолжают работать.
* `_subscribers` / `_pc_streams` — подписчики SSE (`/api/events/stream`) и счётчик
  подключений ПК-клиента. Изменяемое состояние, общее для `broadcast` и стрима.
* `_ev_out` — сериализация события календаря. Нужна и `/api/dashboard`, и `/api/events*`.
* `log` — общий логгер API (`jarvis.api`), чтобы в роутерах не дублировать.

Что здесь быть НЕ должно (проверено): `PC_ORGANIZE_LOG` / `PC_ORGANIZE_PREVIEW`
(только роуты ПК), `_order_or_404` (только заказы), `_gcal_reload`/`_voice_status`/
`_edition_payload`/`_card_for`/`_task_as_event`/`_event_as_task` (по одному модулю),
`web_dist` и SPA-catch-all (остаются в `app.py` — см. инварианты регистрации).
"""
from __future__ import annotations

import asyncio as _asyncio
import json as _json
import logging

from ..brain import agent  # noqa: F401  (используется в app.py для agent.on_change)
from ..db import Event
from ..services import calendar

log = logging.getLogger("jarvis.api")

# --- живые обновления (SSE) ---
_subscribers: set[_asyncio.Queue] = set()
_pc_streams: set[int] = set()


def broadcast(kind: str, payload: dict | None = None) -> None:
    """Сообщить всем открытым вкладкам сайта, что данные изменились."""
    msg = _json.dumps({"kind": kind, **(payload or {})}, ensure_ascii=False)
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except Exception:
            _subscribers.discard(q)


def _ev_out(e: Event) -> dict:
    """Общий формат события календаря для дашборда и списка событий."""
    d = e.model_dump()
    d["repeat_label"] = calendar.fmt_repeat(e)
    d["repeat_anchor"] = getattr(e, "_anchor", e.start)
    d["done"] = calendar.is_done(e) if e.repeat else bool(e.done)
    return d