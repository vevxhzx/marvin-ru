"""Роутеры HTTP API (ФАЗА 7, шаг 7.0 — подготовка).

Здесь живёт код из `core/api/app.py`, разложенный по доменам:
`finance`, `orders`, `boards`, `people`, `tasks`, `mind`, `pc`, `system`.

Состояние на шаг 7.1: перенесён `finance` (42 роута из 195), остальные ~153 роута
пока остаются в `core/api/app.py`.

ИНВАРИАНТЫ РЕГИСТРАЦИИ (обязательны для шагов 7.1–7.6, см. `reviews/P7_refactor.md`):

1. `register(app)` вызывается из `core/api/app.py` ПОСЛЕ создания `app`,
   добавления middleware и `app.include_router(_crm_router)`, но ДО блока
   «раздаём собранную статику» (`app.mount("/assets", ...)` и catch-all-роут
   SPA с путём `{path:path}`). Статика и SPA-catch-all регистрируются
   ПОСЛЕДНИМИ — иначе catch-all перехватит все `/api/*` и сайт перестанет
   открываться.
2. Порядок вызовов `register_*` внутри `register()` влияет на разрешение
   конфликтующих путей. Один совпадающий путь есть: `/api/events/stream`
   (SSE) должен регистрироваться раньше `/api/events/{event_id}`. Все
   остальные пути уникальны (проверено в шаге 7.0), но порядок модулей
   всё равно фиксируем явно и не меняем без проверки тестов.
3. Middleware (`AuthMiddleware`, CORS), lifespan/startup, exception handlers
   и CORS-конфиг остаются в `core/api/app.py` — их не трогаем.
4. `include_router` для CRM (`core/crm/router.py`) уже есть в `app.py` — не дублировать.
"""
from __future__ import annotations

__all__ = ["register"]


def register(app) -> None:
    """Подключить роутеры доменов к `app`.

    Шаг 7.1: подключён `finance` (42 роута: `/api/finance*`, `/api/insights*`,
    `/api/missed`, `/api/snapshot/*`, `/api/export/*`).
    Порядок вызовов = порядок модулей из `reviews/P7_refactor.md` §2.2 —
    он влияет на разрешение конфликтующих путей, менять без проверки тестов нельзя.

    Вызывается из `core/api/app.py` ДО регистрации статики и SPA-catch-all.
    """
    from . import finance

    finance.register(app)