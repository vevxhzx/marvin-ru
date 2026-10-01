# ФАЗА 7, шаг 7.4 — ПЕРЕНОС ГРУППЫ TASKS (`/api/events*`, `/api/tasks*`, `/api/focus`, `/api/timeline`) в `core/api/routers/tasks.py`

**Статус шага: выполнен.** Перенесено **15 роутов** (таблица `reviews/P7_refactor.md` §3, домен
`tasks`, `core/api/routers/tasks.py`), поведение API не изменилось: сверка маршрутов **1:1,
225 = 225**, порядок регистрации домена **побайтово тот же**, тесты зелёные (**598 passed**).

Ветка `overnight-crm`. Родительский коммит `2b79b27` (тег `checkpoint-7-3`), этот шаг — тег
`checkpoint-7-4`.

> Правило фазы 7: только **механический** перенос. Ни одна строка логики, ни один путь, ни один
> код ответа не менялись. Перенос сделан **одноразовым скриптом** (`reviews/_p7_4_move.py`,
> отработал `anchors OK`, удалён после переноса): блоки строк вырезаны из `app.py` по
> **проверенным строкам-якорям** и склеены в новый файл дословно. Изменялись только `@app.` →
> `@router.` (15 шт.) и уровень точек у локальных импортов `..` → `...` (3 шт.).

---

## 1. Что перенесено (15 роутов)

| Модуль | Строк | Роутов |
|---|---|---|
| `core/api/routers/tasks.py` | 287 | **15** |

| Метод | Путь | Было в `app.py` (после 7.3) |
|---|---|---|
| `GET` | `/api/events` | 410 |
| `POST` | `/api/events` | 433 |
| `PUT` | `/api/events/{event_id}` | 440 |
| `POST` | `/api/events/{event_id}/done` | 450 |
| `POST` | `/api/events/{event_id}/skip` | 509 |
| `DELETE` | `/api/events/{event_id}` | 518 |
| `GET` | `/api/tasks` | 533 |
| `GET` | `/api/tasks/{task_id}` | 546 |
| `POST` | `/api/tasks` | 555 |
| `PUT` | `/api/tasks/{task_id}` | 560 |
| `POST` | `/api/tasks/{task_id}/undone` | 583 |
| `POST` | `/api/tasks/{task_id}/done` | 592 |
| `DELETE` | `/api/tasks/{task_id}` | 600 |
| `GET` | `/api/focus` | 607 |
| `GET` | `/api/timeline` | 635 |

Таблица §3 `reviews/P7_refactor.md` совпала с grep'ом по `app.py` **1:1** — ни одного лишнего
и ни одного пропущенного роута. Скрипт переноса дополнительно сверял список
`(метод, путь)` в новом файле с ожидаемым — 15/15 в том же порядке.

### Порядок роутов

Внутри модуля порядок = порядок в `app.py` до переноса (проверено сравнением с эталонным
коммитом, §4):

```
/api/events/stream   (SSE — остаётся в app.py, см. §3)
/api/events          GET
/api/events          POST
/api/events/{event_id}        PUT
/api/events/{event_id}/done   POST
/api/events/{event_id}/skip   POST
/api/events/{event_id}        DELETE
/api/tasks           GET
/api/tasks/{task_id} GET
/api/tasks           POST
/api/tasks/{task_id} PUT
/api/tasks/{task_id}/undone  POST
/api/tasks/{task_id}/done    POST
/api/tasks/{task_id} DELETE
/api/focus
/api/timeline
```

Литералы по-прежнему выигрывают у параметрических (`/api/tasks` раньше `/api/tasks/{task_id}`).
Проверяется 15 новыми параметризациями `test_route_matches`.

### Регистрация

```python
router = APIRouter()          # БЕЗ prefix, БЕЗ dependencies

def register(app) -> None:
    app.include_router(router)
```

Полный путь остался в декораторе (`@router.get("/api/events")`), поэтому ничего не сдвинулось.
`core/api/routers/__init__.py::register()` теперь:

```python
from . import boards, finance, orders, people, tasks

finance.register(app)
orders.register(app)
boards.register(app)
people.register(app)
tasks.register(app)
```

Порядок вызовов = §2.2 отчёта 7.0 (`finance → orders → boards → people → tasks → mind → pc →
system`). Сам `_register_routers(app)` в `app.py` **не перемещался** — он по-прежнему строго
между `app.include_router(_crm_router)` (строка 44) и `web_dist = …` / `app.mount("/assets")` /
catch-all `/{path:path}`.

### Импорты

`tasks.py` (только нужное, без вайлд-импортов):

```python
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from ...db import Aim, Event, Milestone, Task, session
from ...services import calendar, orders, tasks
from .._shared import _ev_out
from ..schemas import EventDoneIn, EventIn, SkipIn, TaskIn, TaskPatch
```

Пояснения:

* `session` — уровня модуля, как был в `app.py`: `GET /api/tasks/{task_id}` и
  `GET /api/events` (ветка `tasks_too`) открывают сессию БД.
* `Task` — нужен в `GET /api/events` (`select(Task)`) и в каскаде `POST /api/events/{id}/done`.
* `Event` — только для аннотации `_event_as_task(e: Event)`; оставлен дословно, как в `app.py`.
* `Aim`, `Milestone` — `PUT /api/tasks/{task_id}` (проверка «чужой/несуществующий id → 404»
  и `aims.link_task(..., milestone=…)`). В `app.py` эти два имени **осиротели** (см. §5).
* `calendar`, `orders`, `tasks` — уровня модуля: `calendar.list_events/add_event/update_event/
  set_done/skip_occurrence/delete_event`, `orders.list_orders/get_order/update_order`,
  `tasks.list_tasks/add_task/update_task/complete_task/delete_task` обращаются к сервисам
  **без локального импорта** (как было в `app.py`).
* `_ev_out` — из `.._shared` (тот же объект, что и в `app.py`; он же нужен `/api/dashboard`).
* Модели `EventIn`, `EventDoneIn`, `SkipIn`, `TaskIn`, `TaskPatch` — из `..schemas`
  (реэкспорт из `app.py` оставлен, ничего не ломается).
* Локальные импорты в перенесённых телах (3 шт.): `from ...services import aims` (2 —
  `PUT /api/tasks/{task_id}`, `GET /api/focus`) и `from ...services import timeline`
  (1 — `GET /api/timeline`) — у них ровно на одну точку больше, т.к. модуль лежит уровнем
  ниже. Уровень точек у *модульных* импортов в `app.py` не трогался вообще.
* Модульных `from .auth` / `from .tg_auth` в этой группе нет — «пропущенная точка» §6.3
  отчёта 7.0 не потребовалась.
* Циклических импортов нет: `register()` вызывается в самом конце `app.py`, к этому моменту
  `core.services.*` уже импортированы; `core.api.routers.tasks` никто не импортирует из
  `core.services` / `core.db` / `core.crm`. Имя модуля `tasks` совпадает с сервисом
  `core.services.tasks`, но это разные пространства имён (`__package__`-резолвинг), коллизии нет.

### Хелперы, уехавшие вместе с роутами

| Хелпер | Был | Стал | Вызовы |
|---|---|---|---|
| `_task_as_event(t: Task)` | `app.py:399` | `tasks.py` | 1 — `GET /api/events` (`tasks_too`) |
| `_event_as_task(e: Event)` | `app.py:526` | `tasks.py` | 1 — `GET /api/tasks` (`events_too`) |

Единственные пользователи обоих были в этом домене → в `_shared.py` **не** выносить (как и
планировалось в §5.2 отчёта 7.0). Grep по `app.py` их больше не находит.

---

## 2. SSE `/api/events/stream` — НАМЕРЕННО ОСТАВЛЕН В `app.py` (не 16-й роут)

Это единственное отступление от формулировки задания, и оно сделано **не из-за ошибки
переноса**, а по плану Фазы 7. Обоснование — приоритет рабочих документов, которые задание
просило прочитать первыми:

| Источник | Что там сказано |
|---|---|
| `reviews/P7_refactor.md` §3, таблица `system.py` | `GET /api/events/stream` (стр. 62) → **system.py**; §3 «Решения по спорным путям»: *«→ **system.py**, не tasks.py. Это живой канал для **всех** модулей, а не календарь. Работает поверх `broadcast`/`_subscribers` из `_shared.py`. Кладём рядом с `/api/chat/stream`, который отдаёт тот же поток событий.»* |
| `reviews/P7_refactor.md` §3, таблица `tasks.py` | 15 роутов, `stream` в списке **нет**; в шапке блока: *«Календарь и дела: `/api/events*` (**кроме SSE**), `/api/tasks/*`, `/api/focus`, `/api/timeline`»* |
| `reviews/P7_refactor.md` §6.1 | `/api/events/stream` (SSE) — критический роут, `app.py:62` → **system.py** |
| `reviews/P7_3_people.md` §8.3 | *«Префикс домена для `tasks` — `/api/events`, потому что `/api/events/stream` (SSE) уедет в **system.py** только на 7.6»* |
| `reviews/P7_3_people.md` §8.6 | *«**На 7.4 это не трогай**, просто имей в виду»* — и там же описан риск: порядок `tasks → system` даст `/api/events/{event_id}` раньше `/api/events/stream` |

Задание шага само указывает: *«ТОЧНЫЕ пути — в таблице `reviews/P7_refactor.md`, перепроверь
grep'ом»*. Таблица говорит `system.py` (7.6). Пока он лежит в `app.py` — **инвариант из задания
выполнен буквально**: SSE зарегистрирован, и его позиция в порядке регистрации **не изменилась
совсем** (см. §4: idx 30 и до, и после).

Оставлен **не как «острый роут»** (перенос не вызвал проблем), а как сознательное решение по
плану. На 7.6 его нужно перенести в `system.py` — инструкции в §7.

---

## 3. Что осталось в `core/api/app.py` и почему

`app.py`: 1408 → **1178** строк (`git diff --numstat core/api/app.py`: **+7 / −237**; все 7
добавленных строк — комментарий о шаге 7.4 и оставленном SSE, см. §2). Всё остальное — **чистые
удаления** (проверено: `git diff core/api/app.py | grep '^+[^+]'` даёт только эти 7 строк).

Осталось **84 роута** из 195 (grep `^\s*@app\.(get|post|put|patch|delete)\(`: было **99** →
стало **84** = ровно −15). Grep по `app.py` не находит ни одного `@app.…("/api/events` (кроме
`stream`), `/api/tasks`, `/api/focus`, `/api/timeline`.

| Что осталось | Роутов | Почему |
|---|---|---|
| `app = FastAPI(...)`, CORS, `AuthMiddleware`, `app.include_router(_crm_router)` | — | инвариант §4.2 п. 2–3, не трогаем |
| `@app.exception_handler(finance.FinanceError)` (`_fin_err`) | — | регистрация обработчика **не зависит** от порядка роутов; `FinanceError` бросают и другие модули |
| `_register_routers(app)` | — | точка подключения роутов по доменам, инвариант §4.2 п. 1 |
| `GET /api/events/stream` (SSE) + его `_asyncio`/`StreamingResponse` | 1 | §2 выше: **system.py на 7.6** |
| `GET /api/state`, `GET /api/presence/events` | 2 | §3 отчёта 7.0 относит их к **system.py**; стояли в блоке «присутствие» между focus и timeline, поэтому разъехались с соседями |
| `/api/edition` GET, POST | 2 | профиль издания (`marvin`/`jarvis`) → **system.py** (7.6) |
| `/media/{path:path}`, `/manifest.json`, `/{path:path}` SPA, `/` | 4 | статика и catch-all **последними** (§3) |
| `graph` (2), `notes`/`links`/`related` (2), `mind` (27), `pc` (13), `system` (44 − 3) | ~75 | шаги 7.5–7.6 |

### Неиспользуемые после переноса импорты в `app.py` — НЕ убраны

Согласно §2.3 п. 5 отчёта 7.0, лишние имена в `app.py` безвредны, чистка — отдельный шаг после
7.6. Теперь «осиротевшие»:

* из `..db`: **`Aim`, `Milestone`** — после 7.4 осиротели (единственные вызовы были в
  `PUT /api/tasks/{task_id}`). `Event` и `Task` **ещё нужны** — `/api/status` (стр. 766)
  делает `select(Event)` / `select(Task)`. **Не убирать `Event`/`Task`.**
* из `..services`: `calendar` — проверь заново на 7.5 (`/api/notes/*` и mind его ещё зовут,
  не убирать без grep'а); `tasks` и `orders` — `tasks` точно осиротел (последний вызов
  `tasks.` был в `DELETE /api/tasks/{task_id}`), `orders` **ещё нужен** (`/api/orders/*` уже
  перенесены, но CRM `core/crm/router.py` работает через БД; проверь grep'ом перед чисткой).
* из `.schemas`: `EventIn`, `EventDoneIn`, `SkipIn`, `TaskIn`, `TaskPatch` — кандидаты на
  чистку после 7.6.

---

## 4. Сверка маршрутов ДО / ПОСЛЕ + проверка порядка SSE (обязательные проверки)

### 4.1 Множество `(path, method)` — 1:1

Скрипт: **`reviews/_check_routes.py`**.

```bat
cd C:\Users\vevxhzx\Desktop\project\jarvis-main
:: ДО — снято на коммите 2b79b27 (HEAD на момент начала шага), рабочее дерево не менялось
.venv\Scripts\python.exe reviews\_check_routes.py 1> %TEMP%\opencode\before74_routes.json
:: ПОСЛЕ
.venv\Scripts\python.exe reviews\_check_routes.py 1> %TEMP%\opencode\after74_routes.json
```

```
flat routes: 225 -> 225 | unique: 225 225
SETS EQUAL: True
SORTED LISTS IDENTICAL: True
MISSING (было, нет): []
ADDED   (стало, нет): []
```

`len(app.router.routes)`: 108 → **94** (по 14 записей на каждый `include_router`: в FastAPI
0.141 вложенный роутер — одна запись `_IncludedRouter` вместо N). Плоский список — **225 и до,
и после**. Служебные 4 маршрута FastAPI (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`,
`/redoc`) и mount `/assets` на месте.

### 4.2 Порядок в пределах `/api/events`, `/api/tasks` — сравнение с ЭТАЛОНОМ

Отсортированный список не ловит перестановку, поэтому эталон снят не из рабочего дерева, а из
**git-worktree на коммите `2b79b27`** (`.venv\Scripts\python.exe` запускался с разными
`sys.path`, один и тот же интерпретатор и одна и та же БД-логика):

```bat
git worktree add --detach %TEMP%\opencode\wt74 2b79b27
.venv\Scripts\python.exe %TEMP%\opencode\_p7_4_order.py %TEMP%\opencode\wt74              %TEMP%\opencode\ref74_order.json
.venv\Scripts\python.exe %TEMP%\opencode\_p7_4_order.py C:\...\jarvis-main                %TEMP%\opencode\new74_order.json
.venv\Scripts\python.exe %TEMP%\opencode\_p7_4_cmp.py
git worktree remove --force %TEMP%\opencode\wt74
```

Результат:

```
flat: 225 -> 225
МНОЖЕСТВО (path, methods) ОДИНАКОВО: True
ПОРЯДОК ДОМЕНА ИДЕНТИЧЕН: True
SSE /api/events/stream: ref idx 30 | new idx 30
                          ref < {event_id}: True | new < {event_id}: True | new < catch-all: True
ВСЕ МАТЧИНГИ СОВПАЛИ: True        (0 DIFF из 31 проверки)
```

**SSE `/api/events/stream` стоит на индексе 30 и ДО, и ПОСЛЕ** — он и в эталоне
`2b79b27`, и после переноса идёт сразу за 26 роутами CRM + 4 служебными, а до всего
остального. Ничего не «сдвинулось»: SSE не переезжал, а блок из 15 роутов уехал в конец
списка доменных роутеров.

Относительный порядок 15 перенесённых + SSE (16 позиций) — **побайтово совпадает** с эталоном
(см. §1). `/api/events/{event_id}` теперь на индексе 210–213, `/api/tasks*` — 214–220,
`/api/focus` — 221, `/api/timeline` — 222, catch-all `/{path:path}` — 223.

### 4.3 Фактический матчинг (`starlette.routing.Match.FULL`) — 31 кейс, 0 расхождений

Снят список ВСЕХ роутов, дающих FULL-match, для каждого `(метод, путь)`. Сравнение
`ref` против `new` — **полное совпадение по всем 31 кейсам**, включая:

```
OK  GET    /api/events/stream        ref=['/api/events/stream','/{path:path}']  new=то же
OK  GET    /api/events/stream/       ref=['/{path:path}']                      new=то же
OK  GET    /api/events               ref=['/api/events','/{path:path}']        new=то же
OK  GET    /api/events/1             ref=['/{path:path}']                      new=то же
OK  PUT    /api/events/1             ref=['/api/events/{event_id}']            new=то же
OK  POST   /api/events/1/done        ref=['/api/events/{event_id}/done']       new=то же
OK  POST   /api/events/1/skip        ref=['/api/events/{event_id}/skip']       new=то же
OK  DELETE /api/events/1             ref=['/api/events/{event_id}']            new=то же
OK  GET    /api/tasks/1              ref=['/api/tasks/{task_id}','/{path:path}'] new=то же
OK  GET    /api/focus  /api/timeline /api/presence/events /api/state
OK  GET    /api/people/today         ref=['/api/people/today','/api/people/{cid}','/{path:path}']
OK  GET    /api/finance/summary /api/boards/1 /api/orders/1 /api/dashboard /api/health
OK  GET    /api/notes/1 /api/crm/clients / /nonexistent-page
```

Два наблюдения, полезные для 7.5–7.6:

* **`GET /api/events/1` отдаёт SPA (`/{path:path}`), а не 405** — так было и в эталоне: роута
  `GET /api/events/{event_id}` в проекте НЕТ (есть только PUT/DELETE), поэтому GET даёт
  PARTIAL-match и его перехватывает catch-all. Поведение **не изменилось** (проверено
  сравнением). Не «чинить» — это за пределами фазы.
* **173 роута из 225 сменили абсолютный индекс** (блок уехал в конец доменных роутеров). Это
  ровно тот же эффект, что дали шаги 7.1–7.3, и он безопасен: конфликтующих путей нет
  (§4.2 п. 5 отчёта 7.0), а пункт 4.3 выше доказывает, что победитель матчинга не поменялся
  ни для одного проверяемого пути.

---

## 5. CRM-роутер — НЕ тронут, пересечений нет

`core/crm/router.py` — `APIRouter(prefix="/api/crm", tags=["crm"])`, 26 роутов, подключён
`app.include_router(_crm_router)` на строке 44, **до** `_register_routers(app)`. Все его пути
под префиксом `/api/crm`; в `tasks.py` только `/api/events*`, `/api/tasks*`, `/api/focus`,
`/api/timeline`. Пересечений нет, дубликатов `(метод, путь)` после шага — **0**
(проверяет `test_no_duplicate_method_and_path`).

---

## 6. Тесты

```
.venv\Scripts\python.exe -m pytest tests -q
→ 598 passed, 2 warnings in 133.32s
```

Расклад по шагу 7.4:

| | тестов |
|---|---|
| на шаге 7.3 (итог) | **579** |
| + новых в `tests/test_p7_routers_registration.py` на этом шаге | **+19** |
| **итог** | **598** |

Мои +19: 15 параметризаций `test_route_matches` (по одной на роут tasks) +
`test_tasks_router_has_exactly_15_routes` + `test_tasks_routes_registered_on_app` +
`test_events_stream_still_in_app` + `test_events_stream_registered_before_event_id_and_catchall`.

Ни один старый тест не сломан и не пропущен. Предупреждения — только baseline
(`StarletteDeprecationWarning` httpx, `anyio BlockingPortal`).

⚠️ В дереве есть **чужие незакоммиченные** файлы (`tests/test_review_cash_chart.py`,
`tests/e2e/specs/*`, `web/**`, `core/services/insights.py`) от параллельных агентов. Они входят
в 598, в мой коммит **не входят** и мной не правились.

Веб-сборку **не запускал**, `web/**` **не трогал**.

---

## 7. Что поправил в тестах

Файл: **`tests/test_p7_routers_registration.py`** (+87 / −7). Это правка **скелета регистрации**,
не логики роутов.

| Что | Роутов | Зачем |
|---|---|---|
| `TASKS_ROUTES` + 15 параметризаций `test_route_matches` | 15 | первый матч по пути — наш роут, а не catch-all SPA |
| `test_tasks_router_has_exactly_15_routes` | — | в роутере ровно 15 роутов с теми же путями и методами (ловит задвоение/потерю) |
| `test_tasks_routes_registered_on_app` | — | роуты реально попали в `app` (забытый `register(app)`) |
| `DOMAIN_ROUTES` += `TASKS_ROUTES` (111 роутов) | — | общая скобка |
| `DOMAINS` += `("tasks", "/api/events")` | — | инвариант §4.2 п. 1; префикс `/api/events` — единственный, указывающий на `tasks.py` прямо сейчас |
| `test_events_stream_still_in_app` | — | SSE зарегистрирован и **не** в `tasks.py` (иначе 7.6 его потеряет) |
| `test_events_stream_registered_before_event_id_and_catchall` | — | «забор» на 7.6: SSE раньше `/api/events/{event_id}` и раньше catch-all + фактический FULL-match |
| `test_route_matches`: подстановки `{event_id}` → `1`, `{task_id}` → `1` | — | остальные уже были |
| Шапка/докстринги: «шаги 7.1–7.4», «на шаг 7.4 последним идёт `tasks`» | — | точность описания |

`test_no_duplicate_method_and_path`, `test_finance_*`, `test_orders_*`, `test_boards_*`,
`test_people_*`, `test_registered_before_spa_catchall` не менялись (последний правок не потребовал
— он берёт `max()` по всем доменам).

---

## 8. Острые роуты шага 7.4

| Роут | Что было не так | Как разрешено |
|---|---|---|
| `GET /api/events/stream` (SSE) | `StreamingResponse`, `_subscribers`/`_pc_streams`, `?client=pc` от `voice.bat`; литерал vs параметрический `/api/events/{event_id}` | Оставлен в `app.py` (не из-за ошибки, а по §2/§3 плана). Проверено: idx 30 и до, и после; раньше `{event_id}` и раньше catch-all; FULL-match `GET /api/events/stream` → SSE. Закреплено тестом `test_events_stream_registered_before_event_id_and_catchall` |
| `GET /api/focus` | Жил в `app.py` в блоке aims, комментарий секции уехал в `people.py` на 7.3 | Перенесён в `tasks.py` (по §3 отчёта 7.0), локальный `from ...services import aims` |
| `PUT /api/tasks/{task_id}` | `clear_due` (`fields.pop("clear_due")`), валидация чужих `milestone_id`/`aim_id` → 404, `aims.link_task(..., milestone=…)` | Тело перенесено дословно, `Aim`/`Milestone` взяты модульным импортом |
| `POST /api/events/{event_id}/done` | Каскад в 3 направления: заказ (id ≤ −100000), задача (id < 0), событие (+ веха/заказ). `HTTPException(404)` в трёх местах, `HTTPException(404, "…")` | Дословно; возвращаемый словарь `{"ok": True, "linked": [...]}` не тронут |
| `GET /api/events` | `tasks_too=True` → `select(Task).where(Task.due != None)` (**`# noqa: E711` сохранён**), `limit=1000)`, плюс дедлайны заказов (`kind='order'`, id ≤ −100000) | Дословно; `_task_as_event` уехал с роутом |
| `GET /api/tasks` | `events_too=True` → «сегодня по календарю» (вчерашние несделанные не теряются), `limit=200`, `limit=500` для дел | Дословно; `_event_as_task` уехал с роутом |
| `GET /api/timeline` | `datetime.fromisoformat(day)` → `HTTPException(422, "day: дата в формате ГГГГ-ММ-ДД")`; `i["at"].isoformat()`, `i["end"]` может быть `None` | Дословно, локальный `from ...services import timeline` |
| `GET /api/presence/events` | Похожий путь (`/api/presence/events`), НО это другой домен | Остался в `app.py` (§3 → system.py), в `tasks.py` не попал. Проверено: в `tasks.py` 15 роутов, лишних нет |

**Ни один роут не остался в `app.py` «острым» по причинам переноса.** Единственное, что не
перенесено, — SSE, и это сознательное решение по плану (§2), а не проблема.

---

## 9. Инструкции для шага 7.5 (`mind.py`, 27 роутов)

> В плане §2.2 отчёта 7.0 шаг 7.5 — `mind.py` (27 роутов). Следующий по плану.

1. **Эталон маршрутов снят:** «после» этого шага — **225** плоских маршрутов, порядок
   зафиксирован в `%TEMP%\opencode\ref74_order.json` / `new74_order.json`. Если `%TEMP%`
   очистился — пересними `.venv\Scripts\python.exe reviews\_check_routes.py`, эталон = 225
   **в этом порядке** (важно: 7.4 сдвинул 15 роутов в конец, 173 индекса изменились, но
   порядок домена tasks и позиция SSE сохранены).
2. **Порядок §2.2 сохраняем:** `finance → orders → boards → people → tasks → mind → pc → system`.
   Дописать в `core/api/routers/__init__.py::register()`:
   ```python
   from . import boards, finance, mind, orders, people, tasks

   finance.register(app)
   orders.register(app)
   boards.register(app)
   people.register(app)
   tasks.register(app)
   mind.register(app)
   ```
3. **Скелет тестов расширить:** добавить `MIND_ROUTES` (27) и кортеж
   `("mind", "/api/notes")` в `DOMAINS` в `tests/test_p7_routers_registration.py`.
   Префикс домена `mind` — `/api/notes` (уникален; `/api/cards/{name}` и `/api/graph*` тоже
   уходят в mind, но `/api/notes` — самая большая группа). `test_registered_before_spa_catchall`
   правок не требует.
   ⚠️ `test_route_matches` понадобятся подстановки: `{name}` → `a.png` (для `/api/cards/{name}`,
   если добавишь в `MIND_ROUTES`), `{kind}`/`{ref_id}` уже есть, `{nid}`/`{fid}`/`{lid}` — **новые**
   (`{lid}` → `1`), `{what}.{fmt}` есть.
4. **Роуты mind** (строки §3 `reviews/P7_refactor.md`, ориентироваться на путь):
   `/api/cards/{name}` GET, `/api/notes/{nid}/related` GET,
   `/api/links/{lid}/related` GET, `/api/graph` GET,
   `/api/graph/backlinks/{kind}/{ref_id}` GET, `/api/notes` GET/POST,
   `/api/notes/photo` POST, `/api/notes/{nid}/polish` POST, `/api/notes/{nid}` PUT/DELETE,
   `/api/links` GET/POST, `/api/links/{lid}` PUT/DELETE, `/api/facts` GET/POST,
   `/api/facts/{fid}` PUT, `/api/facts/{fid}/forget` POST, `/api/facts/{fid}/restore` POST,
   `/api/facts/portrait` POST, `/api/facts/style` POST/PUT, `/api/facts/nightly` POST,
   `/api/memory` GET, `/api/search/semantic` GET, `/api/search/reindex` POST.
   **Итого 27.**
5. **Хелпер mind:** `_card_for` (р. 89 `app.py`) — общий для `/api/chat`, `/api/chat/stream`
   (оба → system.py) и `/api/cards/{name}` (→ mind.py) **и для `/api/events/stream`**
   (SSE, остаётся в app.py до 7.6). Итого 4 пользователя в 3 разных модулях.
   `core/api/routers/__init__.py` §5.2 планировал: **на 7.6** вынести `_card_for` в
   `core/api/_shared.py` и реэкспортировать из `app.py`. На 7.5 можно оставить как есть
   (не ломать), но тогда mind.py не сможет его импортировать → **либо** вынеси в `_shared.py`
   уже на 7.5 с реэкспортом (безопасно, объект один и тот же), **либо** оставь `/api/cards/{name}`
   в `app.py` и перенеси на 7.6. Рекомендую первое.
6. **Модели mind:** `NoteIn`, `NoteEdit`, `LinkIn`, `LinkEdit`, `FactIn`, `FactPatch`, `StyleIn`
   из `..schemas`. **Сервис:** `insights` (для `*_related`, `graph`), `brain_notes` (для
   `/api/notes`, `/api/notes/photo`, `/api/notes/{nid}/polish`), `cards` (для `/api/cards/{name}`),
   `graph` (для `/api/graph*`), `search`/семантика (для `/api/search/*`).
   ⚠️ В `app.py` `insights` и `relations` сейчас **нужны** — `relations.forget(...)` в
   `/api/notes/{nid}` и `/api/links/{lid}` тоже уезжают в mind на 7.5, так что после 7.5 оба
   осиротеют. `brain_notes`, `cards`, `graph` проверь grep'ом перед чисткой.
7. **Острые роуты mind:** `/api/notes/photo` (`UploadFile`/`Form`, запись на диск),
   `/api/cards/{name}` (защита от обхода каталога через `re.fullmatch(r"[A-Za-z0-9_\-]+\.png")`
   — **не «улучшать»**), `/api/notes/{nid}/polish`, `/api/backups/restore` (нет, он system).
   `/media/{path:path}` — **НЕ переносить**, остаётся в `app.py` (§3).
8. **Не трогай порядок SSE.** `test_events_stream_registered_before_event_id_and_catchall`
   специально поставлен так, чтобы **упасть** на 7.6, если `/api/events/stream` переедет в
   `system.py` (регистрируемого после `tasks`) и начнёт проигрывать `/api/events/{event_id}`.
9. **Отчёт шага:** `reviews/P7_5_mind.md`. Коммит только своих путей + тег `checkpoint-7-5`.

---

## 10. Контрольный чек-лист шага

- [x] 15 роутов перенесены дословно, `git diff --numstat core/api/app.py` = `+7 / −237`
- [x] Ничего не добавлено в `app.py`, кроме 7 строк комментария; остальное — чистые удаления
- [x] `app.py`: 1408 → 1171 строк; роутов в `app.py` 99 → 84 (ровно −15)
- [x] `router = APIRouter()` без prefix/dependencies, полный путь в декораторе
- [x] Порядок регистрации: `_register_routers(app)` между CRM и статикой, catch-all последний
- [x] `/api/events/stream` (SSE) **не тронут**: idx 30 и до, и после (§4.2)
- [x] CRM-роутер не тронут, пересечений нет, дубликатов `(метод, путь)` — 0
- [x] Сверка маршрутов до/после: 225 = 225, множества равны, отсортированные списки идентичны
- [x] Сверка **порядка** с эталоном `2b79b27` (git worktree): порядок домена идентичен,
      31/31 FULL-match совпали, SSE раньше `{event_id}` и раньше catch-all
- [x] Инвариант «после последнего доменного роутера нет `/api/*`» — проходит
- [x] `pytest tests -q` → **598 passed** (579 → 598, +19), предупреждения только baseline
- [x] Коммит только своих путей, тег `checkpoint-7-4`
- [ ] `npm run build` в `web/` — **не запускался на этом шаге** (по условию задачи); проверить в конце фазы
