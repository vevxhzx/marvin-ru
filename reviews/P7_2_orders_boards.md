# ФАЗА 7, шаг 7.2 — ПЕРЕНОС ГРУПП ORDERS + BOARDS в `core/api/routers/`

**Статус шага: выполнен.** Перенесено **39 роутов** (`orders` 22 + `boards` 17), поведение API
не изменилось (сверка маршрутов 1:1, 225 = 225), тесты зелёные.

Ветка `overnight-crm`. Родительский коммит `373f9b1` (тег `checkpoint-7-1`), этот шаг — тег
`checkpoint-7-2`.

> Правило фазы 7: только **механический** перенос. Ни одна строка логики, ни один путь, ни один
> код ответа не менялись. Перенос сделан **скриптом** (блоки строк вырезаны из `app.py` и склеены в
> новые файлы дословно), а не руками.

---

## 1. Что перенесено (39 роутов)

| Модуль | Строк | Роутов |
|---|---|---|
| `core/api/routers/orders.py` | 209 | **22** — все `/api/orders*` |
| `core/api/routers/boards.py` | 220 | **17** — все `/api/boards*` |

### `orders.py` (22) — `/api/orders*`

`suggest` (стоял отдельно, ст. ~404 в `app.py`), `clients` GET/POST/PUT/DELETE,
`/api/orders`, `stats`, `timer` GET/POST/DELETE, `pomodoro` GET/PUT,
`freelance` GET/PUT, `pulse`, `POST /api/orders`,
`{oid}` GET/PUT/DELETE, `{oid}/time`, `{oid}/time/from-screen`, `{oid}/payments`.

Вместе с роутами ушёл **хелпер `_order_or_404`** (7 вызовов) — он использовался **только**
заказами, в `app.py` больше не нужен (§5.2 отчёта 7.0). В `_shared.py` ничего не выносилось.

### `boards.py` (17) — `/api/boards*`

`GET/POST /api/boards`, `search`, `for-order/{oid}`, `{bid}` GET/PUT/DELETE, `{bid}/text`,
`{bid}/items` POST/PUT, `{bid}/items/{iid}` PUT, `{bid}/items/delete` POST, `{bid}/frame`,
`{bid}/renumber`, `{bid}/sync` PUT, `{bid}/asset`, `{bid}/image`.

### Порядок роутов

Внутри модулей порядок = порядок в `app.py` на шаге 7.0 (таблица §3 `reviews/P7_refactor.md`),
поэтому `git diff` читается как перенос строк. Блоки вырезаны скриптом по **проверенным
якорям** (скрипт падает, если строка-ориентир сдвинулась — он и так отработал `anchors OK`).

### Регистрация

```python
router = APIRouter()          # БЕЗ prefix, БЕЗ dependencies

def register(app) -> None:
    app.include_router(router)
```

Полный путь остался в декораторе (`@router.get("/api/orders")`), поэтому ничего не сдвинулось.
`core/api/routers/__init__.py::register()` теперь:

```python
from . import boards, finance, orders

finance.register(app)
orders.register(app)
boards.register(app)
```

Порядок вызовов = §2.2 отчёта 7.0 (finance → orders → boards). Сам `_register_routers(app)` в
`app.py` **не перемещался** — он по-прежнему строго между `app.include_router(_crm_router)`
(строка 44) и `web_dist = …` / `app.mount("/assets")` / catch-all `/{path:path}`.

### Импорты

`orders.py`:
```python
from typing import Optional
from fastapi import APIRouter, HTTPException
from ...services import finance, orders, pulse
from .._shared import broadcast
from ..schemas import (ClientIn, FreelanceIn, ManualTimeIn, OrderIn, OrderPatch, PaymentIn,
                       PomoSettingsIn, ScreenImportIn, TimerIn)
```

`boards.py`:
```python
from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from ...services import brain_notes
from ..schemas import BoardBulk, BoardIds, BoardIn, BoardItemIn, BoardItemPatch, BoardPatch, BoardSync
```

Пояснения:
* `finance` в `orders.py` нужен для `except (orders.OrderError, finance.FinanceError)` в
  `POST /api/orders/{oid}/payments` — импорт **не** переносится в `boards.py` и не дублируется.
* `File/Form/UploadFile` в `boards.py` — вычисляются FastAPI **в момент декорирования**, поэтому
  обязаны быть модульными (как были в `app.py`).
* `brain_notes` в `boards.py` — единственный вызов `brain_notes.save_image(raw)` в
  `POST /api/boards/{bid}/image`.
* Всё остальное — **локальные импорты внутри тел роутов, оставленные как были** (приём проекта:
  быстрый старт, обход циклов). У них ровно на одна точка больше: `from ..services import boards` →
  `from ...services import boards` (все 17 досок), `from ..services import pulse` → `...` и т.п.
  Модульных `from .auth` / `from .tg_auth` в этих двух группах нет, «пропущенная точка» §6.3
  не потребовалась.
* `socket`/`subprocess` в таймере **не понадобились**: в текущей версии `/api/orders/timer*`
  чисто сервисный (`orders.start_session/stop_session/timer_state`). Прогноз из инструкции 7.1
  не подтвердился — ничего не «причесывал».
* Вайлд-импортов нет. Циклических импортов нет: `register()` вызывается в самом конце `app.py`,
  к этому моменту `core.services.*` уже импортированы; `core.api.routers.orders` /
  `.boards` никто не импортирует из `core.services` / `core.db` / `core.crm`.

---

## 2. Что осталось в `core/api/app.py` и почему

`app.py`: 1902 → **1537** строк (`git diff --numstat`: **+2 / −366**; +2 — правка устаревшего
комментария «Шаг 7.1: подключён routers/finance.py»). Осталось **114 роутов** из 195
(grep `^\s*@app\.(get|post|put|patch|delete)\(`: было **153** → стало **114** = ровно −39).

| Что осталось | Роутов | Почему |
|---|---|---|
| `app = FastAPI(...)`, CORS, `AuthMiddleware`, `app.include_router(_crm_router)` | — | инвариант §4.2 п. 2–3, не трогаем |
| `@app.exception_handler(finance.FinanceError)` (`_fin_err`) | — | регистрация обработчика **не зависит** от порядка роутов; `FinanceError` бросают и другие модули |
| `_register_routers(app)` | — | точка подключения роутов по доменам, инвариант §4.2 п. 1 |
| `/api/edition` GET, POST | **2** | **НЕ про заказы.** Это профиль издания (`marvin`/`jarvis`) + хелпер `_edition_payload`, §3 отчёта 7.0 относит его к **system.py** (шаг 7.6). Переносить в `orders.py` было бы и логической ошибкой, и переносом чужого роута — оставлено в `app.py` |
| `/media/{path:path}`, `/manifest.json`, `/{path:path}` SPA, `/` | 4 | статика и catch-all **последними** (§3) |
| `people` (15), `tasks` (15), `mind` (27), `pc` (13), `system` (44 − 2 edition) | ~112 | шаги 7.3–7.6 |
| `agent.on_change = broadcast`, реэкспорт `broadcast`/`_subscribers`/`_pc_streams`/`_ev_out` | — | `core/crm/router.py:23` делает `from ..api.app import broadcast` — ломать нельзя |

**Острых роутов, оставленных в `app.py` из-за проблем переноса, НЕТ.** Все 39 перенесены.

### Неиспользуемые после переноса импорты в `app.py` — НЕ убраны

Согласно §2.3 п. 5 отчёта 7.0, лишние имена в `app.py` безвредны, чистка — отдельный шаг после
7.6. Теперь «осиротевшие» (нужны были только orders/boards):

* из `.schemas`: `ClientIn, OrderIn, OrderPatch, PaymentIn, TimerIn, ManualTimeIn, ScreenImportIn,
  PomoSettingsIn, FreelanceIn, BoardIn, BoardPatch, BoardItemIn, BoardItemPatch, BoardBulk,
  BoardIds, BoardSync`
* из `..services`: `pulse` (все вызовы ушли в orders.py)
* `File, Form, UploadFile` — в `app.py` всё ещё нужны (`/api/notes/photo`), не трогаем.
* `orders`, `finance`, `brain_notes` — всё ещё нужны (`/api/dashboard`, `/api/events`, `/media`).

---

## 3. CRM-роутер заказов — НЕ тронут, пересечений нет

`core/crm/router.py` — `APIRouter(prefix="/api/crm", tags=["crm"])`, 26 роутов:
`/api/crm/stages`, `/api/crm/board`, `/api/crm/orders/{oid}/card|stage|payments|activity|comments|checklist`,
`/api/crm/clients/{cid}/card`, `/api/crm/followups*`, `/api/crm/templates`, `/api/crm/analytics`,
`/api/crm/client-stages*`, `/api/crm/checklist/{cid}`.

**Пересечений с `/api/orders*` из `app.py` нет ни по путям, ни по смыслу:** CRM обслуживает
воронку/активность/комментарии под префиксом `/api/crm`, `app.py` — классический CRUD заказов,
таймер, фриланс, пульс и оплаты. Ближайшая пара — `POST /api/orders/{oid}/payments` (app.py) и
`POST /api/crm/orders/{oid}/payments` (CRM) — **разные пути, разные функции, не объединялись**.

CRM-роутер остался подключённым **до** `_register_routers(app)` (строка 44), поведение не
изменилось, `core/api/routers/` его не импортирует. Дубликатов `(метод, путь)` после шага — **0**
(это проверяет `test_no_duplicate_method_and_path`).

---

## 4. Сверка маршрутов ДО / ПОСЛЕ (обязательная проверка)

Скрипт: **`reviews/_check_routes.py`** (рекурсивный обход `_IncludedRouter`, уже поправлен в 7.1).

```bat
cd C:\Users\vevxhzx\Desktop\project\jarvis-main
:: ДО — снято на коммите 373f9b1 (HEAD на момент начала шага), рабочее дерево не менялось
.venv\Scripts\python.exe reviews\_check_routes.py > before_routes.json
:: ПОСЛЕ
.venv\Scripts\python.exe reviews\_check_routes.py > after_routes.json
```

Сравнение множеств `(path, methods)`:

```
# flat routes: 225                      # после
# flat routes: 225                      # до
top-level entries on app.router.routes: 159  ->  122

flat routes: 225 / unique 225
MISSING (было, нет): []
ADDED   (стало, нет): []
SETS EQUAL: True
SORTED LISTS IDENTICAL: True
```

**Совпало 1:1** — ни один путь/метод не потерян и не появился. 39 перенесённых путей в списке
«после» присутствуют ровно те же (проверено, что в «до» было 39 записей с префиксами
`/api/orders` или `/api/boards`, и в «после» — те же 39).

`len(app.router.routes)` уменьшился 159 → 122, потому что в FastAPI 0.141 `include_router`
кладёт вложенный `_IncludedRouter` (одна запись вместо N). Так же подключается и CRM-роутер
(он такой же вложенный объект). Плоский список — 225 и до, и после.

### Про порядок регистрации

Роуты orders и boards теперь регистрируются единым блоком **после** 114 оставшихся, а не
вперемешку с ними. Безопасно: конфликтующих путей нет (§4.2 п. 5 отчёта 7.0) — ни один
параметрический путь с первым сегментом `orders` или `boards` не совпадает по регистру с
литеральным. Важно, что `/api/orders/{oid}` (параметрический) идёт **после**
`/api/orders/stats`, `/api/orders/timer`, `/api/orders/pomodoro`, `/api/orders/freelance`,
`/api/orders/pulse` — порядок внутри модуля сохранён, литералы по-прежнему выигрывают.
То же для досок: `/api/boards/search` и `/api/boards/for-order/{oid}` идут **до**
`/api/boards/{bid}`. Это же проверяется тестами `test_route_matches` (§6).
Catch-all `/{path:path}` по-прежнему регистрируется последним.

---

## 5. Тесты

```
.venv\Scripts\python.exe -m pytest tests -q
→ 562 passed, 2 warnings in 156.35s
```

Расклад по шагу 7.2:

| | тестов |
|---|---|
| на шаге 7.1 (baseline) | **506** |
| + новых в `test_p7_routers_registration.py` на этом шаге | **+43** |
| + чужих (незакоммиченный `tests/test_review_cash_chart.py`, параллельный агент) | **+13** |
| **итог** | **562** |

`506 + 43 = 549` — это ровно моё добавление; 13 тестов — файл другого агента, который лежит в
рабочем дереве незакоммиченным и в мой коммит **не входит**.

Ни один старый тест не сломан и не пропущен. Предупреждения — только baseline
(`StarletteDeprecationWarning` httpx, `anyio BlockingPortal`).

Веб-сборку **не запускал**, `web/**` **не трогал** (параллельно работают другие агенты).

---

## 6. Что поправил в тестах

Файл: **`tests/test_p7_routers_registration.py`** (89 тестов, было 46). Это правка **инварианта
регистрации**, а не логики роутов.

### 6.1 `test_registered_before_spa_catchall` — главная правка

Было: искался индекс `_IncludedRouter` c путями, начинающимися на `/api/finance`, и
утверждалось «после finance нет ни одного `/api/*`-роута». После 7.2 это **враньё**: finance
перестал быть последним подключённым роутером, и условие проверяло не то.

Стало: находится **каждый** доменный роутер (`finance`, `orders`, `boards`) по его префиксу,
берётся **максимальный** из их индексов и проверяется, что **после последнего подключённого
роутера доменов** нет ни одного `/api/*`-роута и что `/{path:path}` / `/` / `/assets` стоят
после. Это ровно инвариант §4.2 п. 1, и он продолжит работать на шагах 7.3–7.6 без правок —
достаточно дописать домен в `DOMAINS`.

```python
DOMAINS = (("finance", "/api/finance"), ("orders", "/api/orders"), ("boards", "/api/boards"))
...
last = max(idx.values())
after = [getattr(r, "path", "") for r in routes[last + 1:]]
assert not [p for p in after if p.startswith("/api/")], ...
assert any(p in ("/{path:path}", "/") for p in after) or any(p == "/assets" for p in after), ...
```

### 6.2 Новые блоки и тесты

| Что | Роутов | Зачем |
|---|---|---|
| `ORDERS_ROUTES` + 22 параметризации `test_route_matches` | 22 | первый матч по пути — наш роут, а не catch-all SPA (иначе на GET прилетел бы HTML вместо JSON) |
| `BOARDS_ROUTES` + 17 параметризаций `test_route_matches` | 17 | то же |
| `test_orders_router_has_exactly_22_routes` | — | в роутере ровно 22 роута с теми же путями и методами (ловит задвоение/потерю) |
| `test_boards_router_has_exactly_17_routes` | — | то же |
| `test_orders_routes_registered_on_app` | — | роуты реально попали в `app` (забытый `register(app)`) |
| `test_boards_routes_registered_on_app` | — | то же |
| `DOMAIN_ROUTES = FINANCE + ORDERS + BOARDS`, `DOMAINS`, хелпер `_router_routes()` | — | общая скобка на 81 роут |

`test_route_matches` теперь подставляет `{oid}`/`{bid}`/`{iid}` → `1` (для досок
`/api/boards/search` и `/api/boards/for-order/{oid}` не подставляется — там литеральный путь).
`test_no_duplicate_method_and_path` и `test_finance_*` не менялись.

---

## 7. Острые роуты шага 7.2

| Роут | Что было не так | Как разрешено |
|---|---|---|
| `POST /api/orders/{oid}/payments` | §5.2 отчёта 7.1: ловит `finance.FinanceError` → 400, а `_fin_err` остаётся в `app.py` | работает: exception handlers регистрируются по типу исключения, порядок роутов на них не влияет. `finance` импортирован в шапке `orders.py` |
| `GET /api/orders/suggest` | §7 отчёта 7.1: «стоит в другом месте файла — не забудь его» (стр. ~404, до календаря) | перенесён первым в `orders.py`; скрипт переноса проверял якорь и упал бы, если бы строка сдвинулась |
| `POST /api/boards/{bid}/image` | §6.2: тянет `io` + `PIL.Image` — тяжёлый импорт, держим локальным; `brain_notes.save_image` | `import io` / `from PIL import Image` остались **внутри тела** роута; `brain_notes` добавлен в шапку `boards.py` |
| `POST /api/boards/{bid}/asset` | §6.2: `UploadFile` + запись на диск | `UploadFile`/`File` в шапке модуля (вычисляются при декорировании), `boards` локально |
| `POST /api/boards/{bid}/sync` | отдаёт **409** при конфликте ревизии, **404** при `LookupError`, **400** при `ValueError` | тела и коды ответа перенесены дословно |
| `GET /api/boards/{bid}` vs `GET /api/boards/search` / `/for-order/{oid}` | литералы должны выигрывать у параметрического `{bid}` | порядок внутри модуля сохранён (литералы раньше), `include_router` даёт тот же порядок; проверяется `test_route_matches` |
| `_order_or_404` | 7 вызовов, только orders | ушёл в `orders.py` вместе с роутами; в `_shared.py` **не** выносился (единственный пользователь) |
| `/api/edition` GET/POST | формально «рядом» с заказами в задании | **НЕ про заказы** (профиль издания marvin/jarvis) → остаётся в `app.py` под шаг 7.6, см. §2 |

**Ни один роут не остался в `app.py` «острым» по причинам переноса.**

---

## 8. Инструкции для шага 7.3 (`boards.py` уже сделан → следующий `people.py`, 15 роутов)

> В плане §2.2 отчёта 7.0 шаг 7.3 — `boards.py` (17). **Он уже выполнен в этом шаге.**
> Следующий по плану — `people.py` (15 роутов).

1. **Эталон маршрутов снят:** «после» этого шага — 225 маршрутов, файл
   `%TEMP%\after72_routes.json` (если `%TEMP%` очистился — просто пересними
   `.venv\Scripts\python.exe reviews\_check_routes.py`, эталон = 225 плоских маршрутов).
2. **Порядок §2.2 сохраняем:** `finance → orders → boards → people → tasks → mind → pc → system`.
   Дописывать в `core/api/routers/__init__.py::register()` так же:
   ```python
   from . import boards, finance, orders, people

   finance.register(app)
   orders.register(app)
   boards.register(app)
   people.register(app)
   ```
3. **Тест-скелет расширяется:** добавить `PEOPLE_ROUTES` (15) и кортеж
   `("people", "/api/people")` в `DOMAINS` в `tests/test_p7_routers_registration.py`.
   `test_registered_before_spa_catchall` **правки не требует** — он уже берёт `max()` по всем
   доменам. `test_route_matches` понадобится подстановка `{cid}` (уже есть) и `{aim_id}`,
   `{rid}`, `{mid}` — дописать в `.replace(...)`.
4. **Роуты people** (строки §3 `reviews/P7_refactor.md`, ориентироваться на путь, не на номер):
   `/api/relations/{rid}` PUT, `/api/aims` GET/POST, `/api/aims/{aim_id}` GET/PUT,
   `/api/aims/{aim_id}/milestones` POST, `/api/milestones/{mid}/{status}` POST,
   `/api/people/batch-hints`, `/api/people/kinds` GET, `/api/people/kinds/{kind}` DELETE,
   `/api/people` GET/POST, `/api/people/today`, `/api/people/{cid}` GET/PUT.
   Модели — `PersonIn`, `AimIn`, `AimPatch`, `MilestoneIn`, `RelationIn` из `..schemas`;
   `broadcast` — из `.._shared`; `relations`/`people` сервисы — точечнее на `...services`.
5. **Хелперы people:** своих нет. `_order_or_404` в `app.py` уже не нужен — не ищи его.
   `insights.related` нужен mind'у (шаг 7.5), не people.
6. **Осторожно с порядком:** `/api/people/{cid}` (параметрический) должен идти **после**
   `/api/people/batch-hints`, `/api/people/kinds`, `/api/people/today` — сохраняй порядок
   из `app.py`, иначе литералы перестанут выигрывать (это ловит `test_route_matches`).
7. **Отчёт шага:** `reviews/P7_3_people.md`. Коммит только своих путей + тег `checkpoint-7-3`.

---

## 9. Контрольный чек-лист шага

- [x] 39 роутов перенесены дословно, `git diff --numstat core/api/app.py` = `+2 / −366`
- [x] Ничего не добавлено в `app.py`, кроме двух строк комментария; остальное — чистые удаления
- [x] Сверка маршрутов до/после: 225 = 225, множества совпали, `SORTED LISTS IDENTICAL: True`
- [x] `router = APIRouter()` без prefix/dependencies, полный путь в декораторе
- [x] Порядок регистрации: `_register_routers(app)` между CRM и статикой, catch-all последний
- [x] CRM-роутер не тронут, пересечений нет, дубликатов `(метод, путь)` — 0
- [x] `pytest tests -q` → **562 passed** (мой вклад: 506 → 549, +13 чужого файла), предупреждения только baseline
- [x] Коммит только своих путей, тег `checkpoint-7-2`
- [ ] `npm run build` в `web/` — **не запускался на этом шаге** (по условию задачи); проверить в конце фазы