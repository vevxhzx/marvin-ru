# ФАЗА 7, шаг 7.1 — ПЕРЕНОС ГРУППЫ FINANCE в `core/api/routers/finance.py`

**Статус шага: выполнен.** Перенесено **42 роута**, поведение API не изменилось (сверка маршрутов 1:1),
тесты зелёные.

Ветка `overnight-crm`. Родительский коммит `643132d` (тег `checkpoint-7-0`), этот шаг — тег `checkpoint-7-1`.

> Правило фазы 7: только **механический** перенос. Ни одна строка логики, ни один путь, ни один код
> ответа не менялись. Перенос сделан скриптом (блоки строк вырезаны из `app.py` и склеены в новый
> файл дословно), а не руками.

---

## 1. Что перенесено (42 роута)

Модуль: `core/api/routers/finance.py` (386 строк). Порядок роутов = порядок в `app.py` на шаге 7.0
(таблица §3 отчёта 7.0), поэтому `git diff` читается как перенос строк.

| Группа | Роутов | Что именно |
|---|---|---|
| `/api/finance/*` | **34** | `import`, `summary`, `daily`, `forecast`, `transactions` (GET/POST/PUT/DELETE), `categories` (GET/POST/PUT/DELETE), `budgets`, `accounts` (GET/POST/PUT/DELETE) + `accounts/balance`, `debts` (GET/POST/PUT/DELETE) + `debts/{id}/pay` + `debts/{id}/payments`, `recurring` (GET/POST/PUT/DELETE), `goals` (GET/POST/PUT/DELETE) + `goals/{id}/put`, `techniques` |
| `/api/insights/*` | **5** | `forecast`, `subscriptions`, `streak`, `birthdays`, `weekly` |
| `/api/missed` | **1** | «что я упускаю», read-only |
| `/api/snapshot/*` | **1** | `month.png` (`include_in_schema=False`) |
| `/api/export/*` | **1** | `{what}.{fmt}` |
| **Итого** | **42** | |

`include_in_schema=False` у `month.png` сохранён. Имена функций-обработчиков сохранены
(`finance_import`, `fin_summary`, `goals_put`, `export` …), чтобы diff читался как перенос.

### Регистрация

```python
router = APIRouter()          # БЕЗ prefix, БЕЗ dependencies

def register(app) -> None:
    app.include_router(router)
```

Полный путь остался в декораторе (`@router.get("/api/finance/summary")`), поэтому ничего не сдвинулось.

`core/api/routers/__init__.py::register()` теперь вызывает `finance.register(app)`; сам
`_register_routers(app)` в `app.py` **не перемещался** — он и на 7.0 стоял строго между
`app.include_router(_crm_router)` (строка 44) и `web_dist = …` / `app.mount("/assets")` /
catch-all `/{path:path}` (строки ~1872+). Инвариант соблюдён и теперь проверяется тестом.

### Импорты `finance.py` (только нужные, без вайлдов)

```python
from ...brain import agent                                    # agent._log_chat в /api/finance/import
from ...db import Debt, Event, Link, Note, Recurring, Task, Transaction, session
from ...services import finance, goals, insights
from .._shared import broadcast
from ..schemas import (TxIn, TxPatch, CategoryIn, CategoryPatch, BalanceIn, AccountIn, AccountPatch,
                       DebtIn, PayIn, DebtPatch, RecurringIn, RecurringPatch, GoalIn, GoalPatch, GoalPut)
```

Всё остальное — **локальные импорты внутри тел роутов, оставленные как были** (приём проекта:
быстрый старт, обход циклов). У них ровно на одну точку больше, т.к. модуль лежит на уровне
`core/api/routers/`, а не `core/api/`:

| было в `app.py` | стало в `finance.py` |
|---|---|
| `from ..services import bank_import` | `from ...services import bank_import` |
| `from ..services import insights` (×5) | `from ...services import insights` |
| `from ..services import missed as _missed` | `from ...services import missed as _missed` |
| `from ..services import cards` | `from ...services import cards` |
| `from ..db import Account, Client, Goal, Order, WorkSession` | `from ...db import …` |

Модульных импортов `from .auth` / `from .tg_auth` в этой группе нет, так что «пропущенная точка»
из §6.3 отчёта 7.0 здесь не потребовалась. Импорт `from .. import VERSION, BUILD` (ловушка для
`/api/health`) тоже не трогал — он остался в `app.py` до шага 7.6.

Циклических импортов нет: `register()` вызывается в самом конце `app.py`, к этому моменту
`core.services.*` и `core.db` уже импортированы. `core.api.routers.finance` никто не импортирует
из `core.services` / `core.db` / `core.crm`.

---

## 2. Что осталось в `core/api/app.py` и почему

`app.py`: 2250 → 1900 строк (`git diff --numstat`: **+2 / −351**, из них +2 — правка устаревшего
комментария «Пока register() — no-op»). Осталось **153 роута** из 195.

| Что осталось | Почему |
|---|---|
| `app = FastAPI(...)`, CORS, `AuthMiddleware`, `app.include_router(_crm_router)` | инвариант §4.2 п. 2–3, не трогаем |
| `@app.exception_handler(finance.FinanceError)` + заголовок `# ---- финансы ----` (строки ~725–728) | регистрация обработчика исключений **не зависит** от порядка роутов; `FinanceError` бросают и остальные модули (`/api/orders/{oid}/payments` ловит `finance.FinanceError`), так что хелпер нужен не только finance |
| `_register_routers(app)` | точка подключения роутов по доменам, инвариант §4.2 п. 1 |
| 153 остальных роута (`orders`, `boards`, `people`, `tasks`, `mind`, `pc`, `system`) | шаги 7.2–7.6 |
| `/media/{path:path}`, `/manifest.json`, `/{path:path}` SPA, `/` | §3 отчёта 7.0 — статика и catch-all **последними** |
| `agent.on_change = broadcast`, реэкспорт `broadcast`/`_subscribers`/`_pc_streams`/`_ev_out` из `_shared` | `core/crm/router.py:23` делает `from ..api.app import broadcast` — ломать нельзя |

### Неиспользуемые после переноса импорты в `app.py` — НЕ убраны

Согласно §2.3 п. 5 отчёта 7.0 («не трогать на этом шаге»), в `app.py` остались импорты, которые
после переноса finance больше не используются **самим app.py**, но могут понадобиться следующим
шагам, и их чистка отдельным шагом безопаснее:

* `from ..db import session, Event, Task, Note, Link, Transaction, Debt, Recurring` — `Transaction`,
  `Recurring`, `Debt`, `Event`, `Task`, `Note`, `Link` ушли в `finance.py` (экспорт); в `app.py`
  из этого списка ещё нужен `session` (в т.ч. обработчик ошибок).
* `datetime, timedelta` — по-прежнему нужны (`/api/dashboard`, `/api/health`).
* `goals`, `insights`, `finance` — по-прежнему нужны `/api/dashboard` (строки 419–449).

**Это НЕ требует действий на шаге 7.2** — просто учитывать: лишние имена в `app.py` безвредны.

### Хелперы, которые НЕ пришлось выносить в `_shared.py`

Ни один хелпер `app.py` не нужен группе finance, поэтому **ничего не дублировалось и ничего не
переносилось**. Из `app.py` на шаг 7.6 остаются (их правда трогают только другие модули):

`_order_or_404` (7.2 · orders), `_gcal_reload` + `_voice_status` (7.6 · system),
`_edition_payload` (7.6 · system), `_card_for` (7.6 · system/tasks → `_shared`),
`_task_as_event` (7.5 · tasks), `_event_as_task` (7.5 · tasks),
`PC_ORGANIZE_LOG` / `PC_ORGANIZE_PREVIEW` (7.6 · pc), `VOICES` / `DEMO_TEXT` (7.6 · pc),
`web_dist` + SPA (остаются в `app.py` навсегда).

---

## 3. Сверка маршрутов ДО / ПОСЛЕ (обязательная проверка)

Скрипт: **`reviews/_check_routes.py`** (лежит в репозитории, переиспользуется на шагах 7.2–7.6).

```bat
cd C:\Users\vevxhzx\Desktop\project\jarvis-main
:: ДО — на коммите 643132d в отдельном worktree, чтобы не снимать «до» задним числом
git worktree add --detach "%TEMP%\p7base" 643132d
copy reviews\_check_routes.py "%TEMP%\p7base\reviews\_check_routes.py"
.venv\Scripts\python.exe "%TEMP%\p7base\reviews\_check_routes.py" > "%TEMP%\before_routes.json"
:: ПОСЛЕ
.venv\Scripts\python.exe reviews\_check_routes.py > "%TEMP%\after_routes.json"
```

Сравнение:

```bat
.venv\Scripts\python.exe -c "import json;t=r'%TEMP%';L=lambda p:[(x[0],tuple(x[1])) for x in json.load(open(p,encoding='utf-8'))];b=L(t+r'\before_routes.json');a=L(t+r'\after_routes.json');print('before',len(b),'after',len(a));print('MISSING',sorted(set(b)-set(a)));print('ADDED',sorted(set(a)-set(b)));print('EQUAL',set(a)==set(b),'SORTED IDENTICAL',a==b)"
```

### Важная поправка к скрипту из отчёта 7.0

В FastAPI **0.141.1** `include_router` больше НЕ разворачивает роуты в `app.router.routes`,
а кладёт вложенный объект `_IncludedRouter`. Поэтому:

* `len(app.routes)` **меняется**: было **200**, стало **159** (= 200 − 42 + 1 вложенный роутер).
  Это **не** потеря роутов — так же подключается и давно существующий CRM-роутер.
* Скрипту из §7 отчёта 7.0 нужен **рекурсивный обход** (`reviews/_check_routes.py` уже поправлен):
  за `type(r).__name__ == "_IncludedRouter"` заходим в `r.original_router.routes`.
* Плоский список маршрутов (CRM + наши + служебные FastAPI + mount `/assets`) — **225 до и 225 после**.

### Результат

```
before: 225 unique 225
after : 225 unique 225
MISSING (было, нет): []
ADDED   (стало, нет): []
SETS EQUAL: True
SORTED LISTS IDENTICAL: True
```

**Совпало 1:1** — ни один путь/метод не потерян и не появился.

Про порядок регистрации: finance-роуты теперь регистрируются единым блоком **после** 153
остальных, а не вперемешку с ними. Это безопасно: конфликтующих путей нет (§4.2 п. 5 отчёта 7.0) —
ни один параметрический путь (`/api/orders/{oid}`, `/api/notes/{nid}`, `/api/tasks/{task_id}`,
`/api/people/{cid}`, `/api/boards/{bid}`, `/api/facts/{fid}`, `/api/lessons/{lid}`,
`/api/milestones/{mid}/{status}` …) не имеет первого сегмента `finance` / `insights` / `missed` /
`snapshot` / `export`, а catch-all `/{path:path}` по-прежнему регистрируется последним.
Это же проверено тестом (см. §5).

---

## 4. Тесты

```
.venv\Scripts\python.exe -m pytest tests -q
→ 506 passed, 2 warnings in 141.22s
```

Было до шага: **460 passed, 2 warnings**. Стало: **506 passed** = 460 + **46 новых** (см. §5).
Ни один старый тест не сломан и не пропущен; предупреждения — только baseline
(`StarletteDeprecationWarning` httpx, `anyio BlockingPortal`).

Веб-сборку **не запускал** и `web/**` **не трогал** (параллельно работают другие агенты) — по заданию
на шаге 7.1 достаточно pytest.

---

## 5. Новый тест `tests/test_p7_routers_registration.py` (46 тестов, только каркас)

Логику роутов не проверяет (её покрывают обычные тесты) — страхует **инварианты подключения**,
которые ломаются в первую очередь и не видны в diff:

| Тест | Что ловит |
|---|---|
| `test_finance_router_has_exactly_42_routes` | в роутере ровно 42 роута с теми же путями и методами |
| `test_finance_routes_registered_on_app` | роуты реально попали в `app` (забытый `register(app)`) |
| `test_no_duplicate_method_and_path` | задвоение при повторном подключении |
| `test_registered_before_spa_catchall` | **главный риск фазы:** после `_register_routers` не должно быть ни одного `/api/*`-роута, а `/{path:path}` / `/` / `/assets` — должны быть после |
| `test_route_matches[method,path]` × 42 | первый матч по каждому пути — наш роут, а не catch-all SPA (иначе на GET прилетел бы HTML вместо JSON) |

Работает без БД: чистый разбор `app.router.routes` + `route.matches(scope)`.

---

## 6. Острые роуты шага 7.1

| Роут | Что было не так | Как разрешено |
|---|---|---|
| `/api/snapshot/month.png` | использует модульный `_asyncio` из `app.py` (строка 50) | в `finance.py` добавлен `import asyncio as _asyncio` — ровно та же переменная, `await _asyncio.to_thread(...)` не тронут |
| `/api/export/{what}.{fmt}` | §6.2: «ломается легче всего — копировать дословно»; использует модульные `Transaction/Event/Task/Note/Link/Debt/Recurring`, `session`, `_json`, `datetime` и локальные `csv/io/Response/select/Account/Client/Goal/Order/WorkSession` | перенесён **дословно** скриптом; модульные имена, на которые он ссылается без локального импорта, импортированы в шапке `finance.py`; `from ..db import` внутри тела → `from ...db import` |
| `/api/finance/import` | §6.2: единственный читает сырую форму + `bank_import`; зовёт `agent._log_chat` и `broadcast` | перенесён дословно, `agent` добавлен в шапку (`from ...brain import agent`), `broadcast` — из `.._shared` |
| `/api/finance/goals/{gid}/put`, `/api/finance/goals` | ловят `finance.FinanceError` → 400; обработчик `_fin_err` остаётся в `app.py` | работает: exception handlers регистрируются по типу исключения, порядок роутов на них не влияет. Проверено тестами (`test_orders_goals.py`, `test_overnight_fase5_forecast.py`) |
| `include_in_schema=False` у `month.png` | потеря флага = роут появляется в OpenAPI | флаг сохранён дословно |

**Ни один роут не остался в `app.py` «острым» по причинам переноса.** Оставшихся «непереносимых»
роутов шага 7.1 нет.

---

## 7. Инструкции для шага 7.2 (`orders.py`, 22 роута)

1. **Эталон маршрутов уже снят:** `%TEMP%\after_routes.json` — это «до» для 7.2 (225 маршрутов).
   Пересними его тем же скриптом на своей ветке перед началом, если сомневаешься.
2. Роуты orders (строки §3 в `reviews/P7_refactor.md`) — сейчас `app.py` строки ~731+:
   `/api/orders/suggest`, `/api/orders/clients*`, `/api/orders`, `/api/orders/stats`,
   `/api/orders/timer|pomodoro|freelance|pulse`, `/api/orders/{oid}*`. Плюс **острый**:
   `_order_or_404` (строка ~732) нужен **только** orders → переноси вместе с ними.
   `orders_suggest` (строка ~404) стоит в другом месте файла — не забудь его.
3. `app.py` сейчас: `include_router(_crm_router)` — строка **44**, `_register_routers(app)` — **1869**,
   `web_dist` — **1873**, `app.mount("/assets")` — **1879**, catch-all — **1881**. Не сдвигай.
4. Подключение добавляй **в конец** `core/api/routers/__init__.py::register()`:
   ```python
   from . import finance, orders
   finance.register(app)
   orders.register(app)
   ```
5. Добавь блок `ORDERS_ROUTES` в `tests/test_p7_routers_registration.py` по образцу `FINANCE_ROUTES`
   и проверку `orders_idx` в `test_registered_before_spa_catchall` (сейчас она ищет только finance —
   после 7.2 finance будет **не последним**, и условие «после finance нет `/api/*`» начнёт врать).
   ⚠️ Это правка **теста**, не логики: заменить на «после самого последнего подключённого роутера».
6. `broadcast` брать из `.._shared`, модели — из `..schemas` (`ClientIn, OrderIn, OrderPatch,
   PaymentIn, TimerIn, ManualTimeIn, ScreenImportIn, PomoSettingsIn, FreelanceIn`), `..db`/`.services`
   — на одну точку больше. В `orders.py` понадобится `socket`/`subprocess` для таймера — **локальными
   импортами**, как сейчас.
7. Отчёт шага: `reviews/P7_2_orders.md`. Коммит только своих путей + тег `checkpoint-7-2`.

---

## 8. Контрольный чек-лист шага

- [x] 42 роута перенесены дословно, `git diff --numstat core/api/app.py` = `+2 / −351`
- [x] Сверка маршрутов до/после: 225 = 225, множества совпали, дубликатов нет
- [x] Порядок регистрации: `_register_routers(app)` между CRM и статикой, catch-all последний
- [x] `pytest tests -q` → **506 passed** (было 460 + 46 новых), предупреждения только baseline
- [x] Коммит только своих путей, тег `checkpoint-7-1`
- [ ] `npm run build` в `web/` — **не запускался на этом шаге** (по условию задачи); проверить в конце фазы
