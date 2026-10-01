"""Роутеры HTTP API (ФАЗА 7, шаг 7.0 — подготовка).

Здесь живёт код из `core/api/app.py`, разложенный по доменам:
`finance`, `orders`, `boards`, `people`, `tasks`, `mind`, `pc`, `system`.

Состояние на шаг 7.4: перенесены `finance` (42 роута из 195), `orders` (22),
`boards` (17), `people` (15) и `tasks` (15) — итого 111 роутов; остальные ~84
роутов пока остаются в `core/api/app.py`.

ИНВАРИАНТЫ РЕГИСТРАЦИИ (обязательны для шагов 7.1–7.6, см. `reviews/P7_refactor.md`):

1. `register(app)` вызывается из `core/api/app.py` ПОСЛЕ создания `app`,
   добавления middleware и `app.include_router(_crm_router)`, но ДО блока
   «раздаём собранную статику» (`app.mount("/assets", ...)` и catch-all-роут
   SPA с путём `{path:path}`). Статика и SPA-catch-all регистрируются
   ПОСЛЕДНИМИ — иначе catch-all перехватит все `/api/*` и сайт перестанет
   открываться.
2. Порядок вызовов `register_*` внутри `register()` влияет на разрешение
   конфликтующих путей. Единственный потенциально конфликтующий путь —
   `/api/events/stream` (SSE): литерал `stream` против параметрического
   `/api/events/{event_id}`. На шаге 7.4 SSE остаётся в `core/api/app.py` и
   регистрируется первым из всех `/api/*`, поэтому порядок безопасен;
   на шаге 7.6 `/api/events/stream` уедет в `system.py` — тогда нужно
   проверить, что он по-прежнему регистрируется раньше `/api/events/{event_id}`
   (см. `reviews/P7_4_tasks.md`, §7). Остальные пути уникальны
   (проверено в шаге 7.0), но порядок модулей всё равно фиксируем явно
   и не меняем без проверки тестов.
3. Middleware (`AuthMiddleware`, CORS), lifespan/startup, exception handlers
   и CORS-конфиг остаются в `core/api/app.py` — их не трогаем.
4. `include_router` для CRM (`core/crm/router.py`) уже есть в `app.py` — не дублировать.
"""
from __future__ import annotations

__all__ = ["register"]


def register(app) -> None:
    """Подключить роутеры доменов к `app`.

    Шаг 7.4: подключены `finance` (42 роута: `/api/finance*`, `/api/insights*`,
    `/api/missed`, `/api/snapshot/*`, `/api/export/*`), `orders` (22 роута:
    `/api/orders*`), `boards` (17 роутов: `/api/boards*`), `people` (15 роутов:
    `/api/people*`, `/api/relations/*`, `/api/aims*`, `/api/milestones/*`) и
    `tasks` (15 роутов: `/api/events*` без SSE, `/api/tasks*`, `/api/focus`,
    `/api/timeline`).
    Порядок вызовов = порядок модулей из `reviews/P7_refactor.md` §2.2 —
    он влияет на разрешение конфликтующих путей, менять без проверки тестов нельзя.

    Вызывается из `core/api/app.py` ДО регистрации статики и SPA-catch-all.
    """
    from . import boards, finance, orders, people, tasks

    finance.register(app)
    orders.register(app)
    boards.register(app)
    people.register(app)
    tasks.register(app)