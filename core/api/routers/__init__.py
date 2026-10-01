"""Роутеры HTTP API (ФАЗА 7, шаг 7.0 — подготовка).

Здесь живёт код из `core/api/app.py`, разложенный по доменам:
`finance`, `orders`, `boards`, `people`, `tasks`, `mind`, `pc`, `system`.

Состояние на шаг 7.6 (финальный): перенесены `finance` (42 роута из 195),
`orders` (22), `boards` (17), `people` (15), `tasks` (15), `mind` (32),
`pc` (14) и `system` (32) — итого 189 роутов; в `core/api/app.py` остались
только 6 роутов: оба SSE (`/api/events/stream`, `/api/chat/stream`) — они
регистрируются ДО всех роутеров, чтобы литерал `stream` выигрывал у
`/api/events/{event_id}` (иначе 422 вместо SSE), — и статика/SPA
(`/media/*`, `/manifest.json`, `/{path:path}`, `/`).

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
   `/api/events/{event_id}`. Решение шага 7.6: SSE **не переносились** и
   остались в `core/api/app.py`, где регистрируются ДО всех роутеров, —
   поэтому литерал гарантированно выигрывает. `system.py` подключается
   последним (ПОСЛЕ `tasks`); если SSE когда-либо всё же переносить —
   только отдельным модулем, подключаемым ПЕРЫМ до `finance`
   (см. `reviews/P7_6_system.md`). Остальные пути уникальны
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
    Шаг 7.5a: подключён `mind` (32 роута: `/api/notes*`, `/api/links*`,
    `/api/facts*`, `/api/lessons*`, `/api/memory`, `/api/graph*`,
    `/api/search/*`, `/api/cards/{name}`, `/api/chat` POST, `/api/undo`,
    `/api/chat/history`; SSE `/api/chat/stream` и `/api/events/stream`
    остаются в `core/api/app.py` до шага 7.6).
    Шаг 7.5b: подключён `pc` (14 роутов: `/api/pc/*`, `/api/screen`,
    `/api/vision/ask`, `/api/cloud/preview`, `/api/voice/*`).
    Шаг 7.6 (финальный): подключён `system` (32 системных роута:
    `/api/health`, `/api/dashboard`, `/api/state`, `/api/presence/events`,
    `/api/diagnose`, `/api/ui-prefs`, `/api/edition`, `/api/client/info`,
    `/api/llm`, `/api/settings`, `/api/status*`, `/api/phone*`, `/api/runs*`,
    `/api/tg/*`, `/api/game`, `/api/google/*`, `/api/backup*`).
    Оба SSE (`/api/events/stream`, `/api/chat/stream`) и статика/SPA остаются
    в `core/api/app.py` — см. докстринг модуля.
    Порядок вызовов = порядок модулей из `reviews/P7_refactor.md` §2.2 —
    он влияет на разрешение конфликтующих путей, менять без проверки тестов нельзя.

    Вызывается из `core/api/app.py` ДО регистрации статики и SPA-catch-all.
    """
    from . import boards, finance, mind, orders, pc, people, system, tasks

    finance.register(app)
    orders.register(app)
    boards.register(app)
    people.register(app)
    tasks.register(app)
    mind.register(app)
    pc.register(app)
    system.register(app)  # ← ПОСЛЕДНИМ: статика/SPA в app.py регистрируются ещё позже