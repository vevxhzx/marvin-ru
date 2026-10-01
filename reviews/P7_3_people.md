# ФАЗА 7, шаг 7.3 — ПЕРЕНОС ГРУППЫ PEOPLE (`/api/people*`, `/api/relations*`, `/api/aims*`) в `core/api/routers/people.py`

**Статус шага: выполнен.** Перенесено **15 роутов** (таблица `reviews/P7_refactor.md` §3,
`core/api/routers/people.py`), поведение API не изменилось: сверка маршрутов **1:1, 225 = 225**,
тесты зелёные (**579 passed**).

Ветка `overnight-crm`. Родительский коммит `6ddc95c` (тег `checkpoint-7-2`), этот шаг — тег
`checkpoint-7-3`.

> Правило фазы 7: только **механический** перенос. Ни одна строка логики, ни один путь, ни один
> код ответа не менялись. Перенос сделан **скриптом** (`reviews/_p7_3_move.py`, отработал
> `anchors OK`, удалён после переноса): блоки строк вырезаны из `app.py` по **проверенным
> строкам-якорям** и склеены в новый файл дословно. Изменялись только `@app.` → `@router.`
> (15 шт.) и уровень точек у локальных импортов `..` → `...` (13 шт.).

---

## 1. Что перенесено (15 роутов)

| Модуль | Строк | Роутов |
|---|---|---|
| `core/api/routers/people.py` | 165 | **15** — все `/api/people*`, `/api/relations*`, `/api/aims*`, `/api/milestones/*` |

| Метод | Путь | Было в `app.py` (после 7.2) |
|---|---|---|
| `PUT` | `/api/relations/{rid}` | 349 |
| `GET` | `/api/aims` | 617 |
| `GET` | `/api/aims/{aim_id}` | 623 |
| `POST` | `/api/aims` | 632 |
| `PUT` | `/api/aims/{aim_id}` | 639 |
| `POST` | `/api/aims/{aim_id}/milestones` | 652 |
| `POST` | `/api/milestones/{mid}/{status}` | 661 |
| `GET` | `/api/people/batch-hints` | 726 |
| `GET` | `/api/people/kinds` | 733 |
| `DELETE` | `/api/people/kinds/{kind}` | 739 |
| `GET` | `/api/people` | 746 |
| `POST` | `/api/people` | 752 |
| `GET` | `/api/people/today` | 762 |
| `GET` | `/api/people/{cid}` | 768 |
| `PUT` | `/api/people/{cid}` | 779 |

Таблица §3 `reviews/P7_refactor.md` совпала с grep'ом по `app.py` **1:1** — ни одного лишнего
и ни одного пропущенного роута.

### Порядок роутов

Внутри модуля порядок = порядок в `app.py` до переноса: сначала `/api/relations/{rid}`, потом
блок `/api/aims*` (+ его комментарий секции `# ---------------- цели (aims) …`),
затем `/api/people*` (+ комментарий `# ---------------- люди и граф ----------------`).
Поэтому `git diff` читается как перенос строк, и литералы по-прежнему выигрывают у
параметрических:

* `/api/people/{cid}` идёт **после** `/api/people/batch-hints`, `/api/people/kinds`,
  `/api/people/today` — литералы не перехватываются параметрическим путём;
* `/api/aims/{aim_id}` идёт **после** `/api/aims`;
* `/api/people/kinds/{kind}` (DELETE) идёт **после** `/api/people/kinds` (GET).

Всё это проверяется тестом `test_route_matches` (15 новых параметризаций).

### Регистрация

```python
router = APIRouter()          # БЕЗ prefix, БЕЗ dependencies

def register(app) -> None:
    app.include_router(router)
```

Полный путь остался в декораторе (`@router.get("/api/people")`), поэтому ничего не сдвинулось.
`core/api/routers/__init__.py::register()` теперь:

```python
from . import boards, finance, orders, people

finance.register(app)
orders.register(app)
boards.register(app)
people.register(app)
```

Порядок вызовов = §2.2 отчёта 7.0 (`finance → orders → boards → people → tasks → mind → pc →
system`). Сам `_register_routers(app)` в `app.py` **не перемещался** — он по-прежнему строго
между `app.include_router(_crm_router)` (строка 44) и `web_dist = …` / `app.mount("/assets")` /
catch-all `/{path:path}`.

### Импорты

`people.py` (только нужное, без вайлд-импортов):

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...db import session
from ...services import people, relations
from .._shared import broadcast
from ..schemas import AimIn, AimPatch, MilestoneIn, PersonIn, RelationIn
```

Пояснения:

* `session` — уровня модуля, как был в `app.py`: `GET /api/people/{cid}` открывает сессию БД
  (`with session() as s: s.get(Client, cid)`), а `Client` импортируется локально в теле роута.
* `people`, `relations` — уровня модуля: `people_kinds()` / `people_kind_delete()` и
  `relation_set()` обращаются к сервису **без локального импорта** (как было в `app.py`).
  Остальные 5 роутов людей сохранили свои локальные `from ..services import people` (приём
  проекта) — теперь `from ...services import people`.
* `broadcast` — из `.._shared` (тот же объект, что и в `app.py`; `agent.on_change = broadcast`
  в `app.py` не тронут).
* Модели `RelationIn, AimIn, AimPatch, MilestoneIn, PersonIn` — из `..schemas` (реэкспорт из
  `app.py` оставлен, ничего не ломается).
* Локальные импорты в перенесённых телах (13 шт.): `from ...services import aims` (7),
  `from ...services import people` (5), `from ...db import Client` (1) — у них ровно на одну
  точку больше, т.к. модуль лежит уровнем ниже. Уровень точек у *модульных* импортов в `app.py`
  не трогался вообще.
* Модульных `from .auth` / `from .tg_auth` в этой группе нет — «пропущенная точка» §6.3
  отчёта 7.0 не потребовалась.
* Циклических импортов нет: `register()` вызывается в самом конце `app.py`, к этому моменту
  `core.services.*` уже импортированы; `core.api.routers.people` никто не импортирует из
  `core.services` / `core.db` / `core.crm`. Имя модуля `people` совпадает с сервисом
  `core.services.people`, но это разные пространства имён (`__package__`-резолвинг), коллизии нет.

---

## 2. Что осталось в `core/api/app.py` и почему

`app.py`: 1537 → **1408** строк (`git diff --numstat core/api/app.py`: **+2 / −131**; +2 —
правка устаревшего комментария «Шаг 7.2: подключены routers/finance.py (42)…»). Всё
остальное — **чистые удаления** (проверено: в диффе всего две добавленные строки, обе —
комментарий).

Осталось **99 роутов** из 195 (grep `^\s*@app\.(get|post|put|patch|delete)\(`: было **114** →
стало **99** = ровно −15). Grep по `app.py` не находит ни одного `/api/people`,
`/api/relations`, `/api/aims`, `/api/milestones`.

| Что осталось | Роутов | Почему |
|---|---|---|
| `app = FastAPI(...)`, CORS, `AuthMiddleware`, `app.include_router(_crm_router)` | — | инвариант §4.2 п. 2–3, не трогаем |
| `@app.exception_handler(finance.FinanceError)` (`_fin_err`) | — | регистрация обработчика **не зависит** от порядка роутов; `FinanceError` бросают и другие модули |
| `_register_routers(app)` | — | точка подключения роутов по доменам, инвариант §4.2 п. 1 |
| `/api/edition` GET, POST | 2 | профиль издания (`marvin`/`jarvis`) → **system.py** (шаг 7.6) |
| `/media/{path:path}`, `/manifest.json`, `/{path:path}` SPA, `/` | 4 | статика и catch-all **последними** (§3) |
| `graph` (2), `notes`/`links`/`related` (2), `tasks` (15), `mind` (27), `pc` (13), `system` (44 − 2 edition) | ~97 | шаги 7.4–7.6 |
| `agent.on_change = broadcast`, реэкспорт `broadcast`/`_subscribers`/`_pc_streams`/`_ev_out` | — | `core/crm/router.py:23` делает `from ..api.app import broadcast` — ломать нельзя |

**Острых роутов, оставленных в `app.py` из-за проблем переноса, НЕТ. Все 15 перенесены.**

### Сознательно НЕ перенесено (пересечения по смыслу, а не из-за ошибки)

| Роут | Где остался | Почему |
|---|---|---|
| `GET /api/focus` | `app.py` | Стоял в блоке aims (комментарий секции «цели (aims): цель → вехи → задачи; **фокус дня**»), но §3 отчёта 7.0 относит его к **tasks.py** (шаг 7.4). Переносить его в `people.py` было бы ошибкой. Комментарий секции уехал вместе с aims, `/api/focus` остался в `app.py` без своего заголовка — косметика, поведение не менялось |
| `GET /api/graph`, `GET /api/graph/backlinks/{kind}/{ref_id}` | `app.py` | Стояли в блоке «люди и граф», но §3 относит их к **mind.py** (шаг 7.5) |

### Неиспользуемые после переноса импорты в `app.py` — НЕ убраны

Согласно §2.3 п. 5 отчёта 7.0, лишние имена в `app.py` безвредны, чистка — отдельный шаг после
7.6. Теперь «осиротевшие» (нужны были только людям/целям):

* из `..services`: **`people`** (после переноса в `app.py` не осталось ни одного
  `people.` — последние 9 вызовов ушли в `people.py`). `relations` **ещё нужен** —
  `/api/notes/{nid}` (стр. 741) и `/api/links/{lid}` (стр. 780) вызывают `relations.forget(...)`,
  а `/api/links/{lid}/related` и `/api/notes/{nid}/related` (строки 344–346) — `enabled/pending/
  compute/related`. **Не убирать.**
* из `..db`: `Aim`, `Milestone` — **ещё нужны**: `POST /api/tasks` (строки 570–575) проверяет
  `s.get(Milestone, …)` и `s.get(Aim, …)` и зовёт `aims.link_task(…, milestone=…)`. **Не убирать.**
* из `.schemas`: `RelationIn`, `AimIn`, `AimPatch`, `MilestoneIn`, `PersonIn` (в `app.py` больше
  не используются — кандидаты на чистку после 7.6).

---

## 3. CRM-роутер — НЕ тронут, пересечений нет

`core/crm/router.py` — `APIRouter(prefix="/api/crm", tags=["crm"])`, 26 роутов, включая
`GET /api/crm/clients/{cid}/card`, `PUT /api/crm/clients/{cid}`,
`GET/PUT/DELETE/POST /api/crm/clients/{cid}/stage*`.

**Пересечений по путям нет ни с одним из 15 перенесённых роутов** — все они под префиксом
`/api/crm`, а в `people.py` только `/api/people*`, `/api/relations/*`, `/api/aims*`,
`/api/milestones/*`. Ничего не дублировалось, `core/api/routers/` CRM не импортирует, роутер
остался подключённым **до** `_register_routers(app)` (строка 44). Дубликатов `(метод, путь)`
после шага — **0** (проверяет `test_no_duplicate_method_and_path`).

Логически CRM-карточка клиента (`/api/crm/clients/{cid}/card`) и `GET /api/people/{cid}` — разные
ответы: первая про воронку/стадию, вторая про `people.card(c, limit=20)`. Не объединялись.

---

## 4. Сверка маршрутов ДО / ПОСЛЕ (обязательная проверка)

Скрипт: **`reviews/_check_routes.py`** (рекурсивный обход `_IncludedRouter`).

```bat
cd C:\Users\vevxhzx\Desktop\project\jarvis-main
:: ДО — снято на коммите 6ddc95c (HEAD на момент начала шага), рабочее дерево не менялось
.venv\Scripts\python.exe reviews\_check_routes.py > before73_routes.json
:: ПОСЛЕ
.venv\Scripts\python.exe reviews\_check_routes.py > after73_routes.json
```

Сравнение множеств `(path, methods)`:

```
flat routes: 225 -> 225 | unique: 225 225
MISSING (было, нет): []
ADDED   (стало, нет): []
SETS EQUAL: True
SORTED LISTS IDENTICAL: True
people-domain routes after: 15
```

**Совпало 1:1** — ни один путь/метод не потерян и не появился. Все 15 перенесённых путей
присутствуют в списке «после» ровно те же.

`len(app.router.routes)`: 122 → **108** (по 14 записей на каждый `include_router`: в FastAPI
0.141 вложенный роутер — одна запись `_IncludedRouter` вместо N). Плоский список — **225 и до,
и после**. Служебные 4 маршрута FastAPI (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`,
`/redoc`) и mount `/assets` на месте.

### Про порядок регистрации

Роуты людей теперь регистрируются единым блоком **после** 99 оставшихся, а не вперемешку с ними.
Безопасно: конфликтующих путей нет (§4.2 п. 5 отчёта 7.0) — ни один параметрический путь с
первым сегментом `people` / `relations` / `aims` / `milestones` не совпадает по регистру с
литеральным. Внутри модуля порядок сохранён (см. §1). Catch-all `/{path:path}` по-прежнему
регистрируется последним.

### Инвариант «после последнего доменного роутера нет `/api/*`»

`test_registered_before_spa_catchall` **правок не потребовал**: он уже берёт `max()` по всем
доменам из `DOMAINS`, куда добавлено `("people", "/api/people")`. Тест проходит.

---

## 5. Тесты

```
.venv\Scripts\python.exe -m pytest tests -q
→ 579 passed, 2 warnings in 140.36s
```

Расклад по шагу 7.3:

| | тестов |
|---|---|
| на шаге 7.2 (итог) | **562** |
| + новых в `tests/test_p7_routers_registration.py` на этом шаге | **+17** |
| **итог** | **579** |

Мои +17: 15 параметризаций `test_route_matches` (по одной на роут people) +
`test_people_router_has_exactly_15_routes` + `test_people_routes_registered_on_app`.
Из них 13 «чужих» тестов (`tests/test_review_cash_chart.py`, параллельный агент) входят в 562 и
в мой коммит **не входят** — файл лежит в рабочем дереве незакоммиченным, я его не правил.

Ни один старый тест не сломан и не пропущен. Предупреждения — только baseline
(`StarletteDeprecationWarning` httpx, `anyio BlockingPortal`).

Веб-сборку **не запускал**, `web/**` **не трогал** (параллельно работают другие агенты).

---

## 6. Что поправил в тестах

Файл: **`tests/test_p7_routers_registration.py`** (+43 / −6). Это правка **скелета регистрации**,
не логики роутов.

| Что | Роутов | Зачем |
|---|---|---|
| `PEOPLE_ROUTES` + 15 параметризаций `test_route_matches` | 15 | первый матч по пути — наш роут, а не catch-all SPA (иначе на GET прилетел бы HTML) |
| `test_people_router_has_exactly_15_routes` | — | в роутере ровно 15 роутов с теми же путями и методами (ловит задвоение/потерю) |
| `test_people_routes_registered_on_app` | — | роуты реально попали в `app` (забытый `register(app)`) |
| `DOMAIN_ROUTES` += `PEOPLE_ROUTES` (96 роутов), `DOMAINS` += `("people", "/api/people")` | — | общая скобка + инвариант §4.2 п. 1 |
| `test_route_matches`: добавлены подстановки `{aim_id}` → `1`, `{mid}` → `1`, `{status}` → `done`, `{kind}` → `client` | — | `{cid}` и `{rid}` уже были |
| Шапка/докстринги: «шаги 7.1–7.3», «на шаг 7.3 последним идёт `people`» | — | точность описания |

`test_registered_before_spa_catchall` не менялся; `test_no_duplicate_method_and_path`,
`test_finance_*`, `test_orders_*`, `test_boards_*` не менялись.

---

## 7. Острые роуты шага 7.3

| Роут | Что было не так | Как разрешено |
|---|---|---|
| `GET /api/people/{cid}` | литералы `batch-hints`, `kinds`, `today` должны выигрывать у параметрического `{cid}` | порядок внутри модуля сохранён (литералы раньше); `include_router` даёт тот же порядок; проверяется `test_route_matches` (15 параметризаций) |
| `DELETE /api/people/kinds/{kind}` | `DELETE /api/people/kinds/{kind}` vs `GET /api/people/kinds` — **разные методы**, конфликта нет; `{kind}` не должен перехватывать `batch-hints`/`today` (разные сегменты) | порядок сохранён, дубликатов `(метод, путь)` — 0 |
| `POST /api/milestones/{mid}/{status}` | `status` — не `int`; `HTTPException(400, "status: done | open | dropped")` при мусоре, `404` при ненайденной вехе | тело и коды ответа перенесены дословно, валидация `status not in ("done","open","dropped")` не тронута |
| `PUT /api/aims/{aim_id}` | `clear_due`-логика: `fields.pop("clear_due")`, при `clear_due` пишет `due=None, clear_due=True` | перенесено дословно |
| `PUT /api/relations/{rid}` | 1 из 2 роутов `/api/relations*` (второй — локальные `/api/notes|links/{id}/related`, они остаются в `app.py` под шаг 7.5, т.к. это mind) | `relations` взят **модульным** импортом — в `app.py` он остался в силе для оставшихся 4 вызовов |
| `GET /api/people/batch-hints` | §3 отчёта 7.2 относит `/api/people*` к people; внутри зовёт `pulse.guess_batch_clients()` | `pulse` остался **локальным** импортом (`from ...services import pulse`) — в `app.py` имя `pulse` осиротело после шага 7.2, здесь оно нужно |
| `POST /api/people` / `PUT /api/people/{cid}` | шлют `broadcast("chat", {"channel": "web", "actions": [...]})` | `broadcast` взят из `.._shared` — **тот же объект**, что и в `app.py` (это критично для SSE и для `agent.on_change = broadcast` в `app.py`) |
| `/api/crm/clients/{cid}*` (CRM) | §задания: не дублировать | CRM не тронут, пути не пересекаются, §3 |

**Ни один роут не остался в `app.py` «острым» по причинам переноса.**

---

## 8. Инструкции для шага 7.4 (`people.py` сделан → следующий `tasks.py`, 15 роутов)

> В плане §2.2 отчёта 7.0 шаг 7.4 — `people.py` (15). **Он выполнен в этом шаге.**
> Следующий по плану — `tasks.py` (15 роутов).

1. **Эталон маршрутов снят:** «после» этого шага — **225** плоских маршрутов
   (`%TEMP%\opencode\after73_routes.json`; если `%TEMP%` очистился — просто пересними
   `.venv\Scripts\python.exe reviews\_check_routes.py`, эталон = 225).
2. **Порядок §2.2 сохраняем:** `finance → orders → boards → people → tasks → mind → pc → system`.
   Дописать в `core/api/routers/__init__.py::register()`:
   ```python
   from . import boards, finance, orders, people, tasks

   finance.register(app)
   orders.register(app)
   boards.register(app)
   people.register(app)
   tasks.register(app)
   ```
3. **Тест-скелет расширяется:** добавить `TASKS_ROUTES` (15) и кортеж
   `("tasks", "/api/events")` в `DOMAINS` в `tests/test_p7_routers_registration.py`.
   `test_registered_before_spa_catchall` **правки не требует** (берёт `max()` по всем доменам).
   `test_route_matches` понадобится подстановка `{event_id}` → `1` (остальные уже есть).
   ⚠️ Префикс домена для `tasks` — `/api/events`, потому что `/api/events/stream` (SSE) уедет
   в **system.py** только на 7.6: на 7.4 первый сегмент задач — `events`, и `find`-скелет ищет
   `_IncludedRouter` с путями, начинающимися с префикса. Убедись, что префикс уникален для
   `tasks.py` (у `system.py` потом будет `/api/events` **и** `/api/chat` — тогда префикс
   придётся брать по `/api/chat`, см. п. 6).
4. **Роуты tasks** (строки §3 `reviews/P7_refactor.md`, ориентироваться на путь, не на номер):
   `/api/events` GET/POST, `/api/events/{event_id}` PUT/DELETE,
   `/api/events/{event_id}/done` POST, `/api/events/{event_id}/skip` POST,
   `/api/tasks` GET/POST, `/api/tasks/{task_id}` GET/PUT/DELETE,
   `/api/tasks/{task_id}/undone` POST, `/api/tasks/{task_id}/done` POST,
   `/api/focus` GET, `/api/timeline` GET. **Итого 15.**
   ⚠️ `/api/focus` живёт в `app.py` в блоке aims — переноси его в `tasks.py` (комментарий секции
   «цели (aims) … фокус дня» уже уехал в `people.py`, см. §2 «сознательно НЕ перенесено»).
   Модели — `EventIn`, `EventDoneIn`, `SkipIn`, `TaskIn`, `TaskPatch` из `..schemas`;
   `broadcast`/`_ev_out` — из `.._shared`.
5. **Хелперы tasks:** `_task_as_event` (2 роута календаря) и `_event_as_task` (2 роута задач) —
   оба уезжают в `tasks.py` вместе с роутами (единственные пользователи, в `_shared.py` **не**
   выносить). Проверь, что оба больше не нужны в `app.py`.
6. **⚠️ Главная тонкость 7.4 + 7.6:** `/api/events/stream` (SSE) и `/api/tasks/{task_id}` в
   разных модулях (`system.py` на 7.6 и `tasks.py` на 7.4). Конфликта путей нет
   (`stream` литерал против `{event_id}` параметрического), **но** SSE должен регистрироваться
   раньше `/api/events/{event_id}` (§4.2 п. 2). Порядок вызовов `finance → … → tasks → … →
   system` даёт tasks раньше system, т.е. `/api/events/{event_id}` зарегистрируется **раньше**
   `/api/events/stream` — литерал может проиграть. Проверь это на 7.6 отдельным тестом
   (`.venv\Scripts\python.exe reviews\_check_routes.py` + ручной матч `GET /api/events/stream`
   через `starlette.routing.Match`), и если понадобится — не переставляй модули, а оставь
   `/api/events/stream` в `app.py` либо заведи для `system.py` точечную регистрацию раньше
   `tasks`. **На 7.4 это не трогай**, просто имей в виду.
7. **Порядок внутри `tasks.py`:** `/api/events/{event_id}*` литералов не имеет, но
   `/api/events/stream` (если бы остался) должен идти раньше; `/api/tasks/{task_id}` идёт после
   `/api/tasks` — сохраняй порядок из `app.py`.
8. **Неиспользуемые импорты в `app.py` после 7.4:** `EventIn`, `EventDoneIn`, `SkipIn`, `TaskIn`,
   `TaskPatch` осиротеют; `Aim`, `Milestone` — **проверь заново**: на шаге 7.3 они были нужны
   `POST /api/tasks` (стр. 570–575), который уедет на 7.4, так что после 7.4 оба становятся
   кандидатами на чистку. `relations` остаётся нужен (`/api/notes/{nid}`, `/api/links/{lid}`).
   `people` — кандидат на удаление из `..services` (§2).
9. **Отчёт шага:** `reviews/P7_4_tasks.md`. Коммит только своих путей + тег `checkpoint-7-4`.

---

## 9. Контрольный чек-лист шага

- [x] 15 роутов перенесены дословно, `git diff --numstat core/api/app.py` = `+2 / −131`
- [x] Ничего не добавлено в `app.py`, кроме двух строк комментария; остальное — чистые удаления
- [x] `app.py`: 1537 → 1408 строк; роутов в `app.py` 114 → 99 (ровно −15)
- [x] `router = APIRouter()` без prefix/dependencies, полный путь в декораторе
- [x] Порядок регистрации: `_register_routers(app)` между CRM и статикой, catch-all последний
- [x] CRM-роутер не тронут, пересечений нет, дубликатов `(метод, путь)` — 0
- [x] Сверка маршрутов до/после: 225 = 225, `SETS EQUAL: True`, `SORTED LISTS IDENTICAL: True`
- [x] Инвариант «после последнего доменного роутера нет `/api/*`» — `test_registered_before_spa_catchall` проходит без правок
- [x] `pytest tests -q` → **579 passed** (мой вклад: 562 → 579, из них 13 — чужой незакоммиченный файл), предупреждения только baseline
- [x] Коммит только своих путей, тег `checkpoint-7-3`
- [ ] `npm run build` в `web/` — **не запускался на этом шаге** (по условию задачи); проверить в конце фазы
