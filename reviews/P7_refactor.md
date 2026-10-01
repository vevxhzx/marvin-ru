# ФАЗА 7, шаг 7.0 — ПОДГОТОВКА к разбиению `core/api/app.py`

**Статус шага: выполнен.** Роуты ещё НЕ перенесены — подготовлена база, инвентаризация и инструкции.
**Проверка:** `.venv\Scripts\python.exe -m pytest tests -q` → **460 passed, 2 warnings** (столько же, сколько
до шага 7.0). `npm run build` в `web/` → **успешно**, `✓ built in 8.50s`. Число роутов не изменилось: **195 → 195**.

Ветка `overnight-crm`. Коммит этого шага помечен тегом `checkpoint-7-0`.

> **Правило фазы 7 (из `OVERNIGHT.md`):** только МЕХАНИЧЕСКИЙ перенос роутов в отдельные модули, БЕЗ изменения
> логики. Если после переноса хоть один тест падает и не чинится за 2 попытки — откатывается ВСЯ фаза.

---

## 1. Что сделано в шаге 7.0 (и что НЕ сделано)

| # | Действие | Результат |
|---|---|---|
| 1 | Полная инвентаризация роутов `core/api/app.py` | 195 роутов (`@app.get/post/put/patch/delete`), таблица в §3 |
| 2 | Pydantic-модели запросов вынесены в `core/api/schemas.py` | 63 класса, **реэкспорт** из `app.py` — импорты не сломаны (§5) |
| 3 | Общее состояние вынесено в `core/api/_shared.py` | `broadcast`, `_subscribers`, `_pc_streams`, `_ev_out`, `log`; **реэкспорт** из `app.py` |
| 4 | Создан пакет `core/api/routers/` | `__init__.py` с `register(app)` — **no-op**, роутеры подключаются в 7.1–7.6 |
| 5 | Инварианты регистрации зафиксированы | §4 (в коде — комментарий в `app.py` и докстринг `routers/__init__.py`) |
| 6 | Острые роуты найдены заранее | §6 |
| — | **Роуты НЕ переносились** | `app.py` содержит все 195 роутов, поведение не изменилось |

### Что появилось в репозитории

```
core/api/schemas.py          63 Pydantic-модели запросов (перенесены из app.py)
core/api/_shared.py          broadcast / SSE-состояние / _ev_out / log
core/api/routers/__init__.py register(app) — no-op + инварианты в докстринге
```

`core/api/app.py` похудел на ~490 строк (2727 → 2250), количество роутов и их порядок регистрации — **1:1**.

---

## 2. Инструкция-шаблон для шага 7.N (перенос одного модуля)

Каждый следующий субагент берёт **один** модуль из таблицы §3 и делает ровно это. Ничего больше.

### 2.1 Перед началом

1. Прочитать `OVERNIGHT.md` (ЖЁСТКИЕ ПРАВИЛА + РЕЖИМ РАБОТЫ) и этот файл целиком.
2. Запомнить baseline: **460 passed**. Если до тебя что-то уже падает — записать в `PROGRESS.md` и не чинить.
3. Не менять ветку. Не трогать `config.yaml`, `.env`, `data/`, `vendor/`.

### 2.2 Порядок переноса модулей (рекомендуемый)

Порядок важен из-за общего состояния: сначала модули, которые только читают `_shared`,
затем те, которые его пишут.

| Шаг | Модуль | Роутов | Почему в этом порядке |
|---|---|---|---|
| 7.1 | `finance.py` | 42 | Не зависит ни от чего нового; самый большой и самый покрытый тестами |
| 7.2 | `orders.py` | 22 | Тоже финансы/БД |
| 7.3 | `boards.py` | 17 | Свой сервис `core/services/boards.py` |
| 7.4 | `people.py` | 15 | Свой сервис `people.py` + `relations` |
| 7.5 | `tasks.py` | 15 | Календарь/задачи |
| 7.6 | `mind.py` + `pc.py` + `system.py` | 27 + 13 + 44 | `system.py` — **последним**: там статика и catch-all |

Если времени хватит только на часть — остановиться после `orders.py`, сделать коммит и тег `checkpoint-7-2`.

### 2.3 Как переносить (механика, без исключений)

1. Создать `core/api/routers/<name>.py`.
2. В шапке модуля:
   ```python
   """<домен> (ФАЗА 7, шаг 7.N). Перенос механический из core/api/app.py, логика не менялась."""
   from __future__ import annotations
   from fastapi import APIRouter
   from ..schemas import ...      # нужные модели из core/api/schemas.py
   from .._shared import broadcast, ...   # что реально нужно этому модулю
   from ...db import ...          # что реально нужно
   from ...services import ...    # что реально нужно

   router = APIRouter()

   def register(app) -> None:
       app.include_router(router)
   ```
   **Именно `register(app)`, а не `include_router` на уровне модуля.** Иначе при импорте
   `core.api.routers.<name>` роут попадёт в `app` до того, как `app.py` вызвал `register()`,
   и порядок регистрации станет непредсказуемым. Образец — `core/crm/router.py`
   (там `router = APIRouter(prefix=..., tags=...)` + подключение в `app.py`).
3. Перенести роуты **в том же порядке, в каком они идут в `app.py`** (строки из §3 отсортированы
   именно так). Порядок важен: он определяет разрешение конфликтующих путей.
4. Всё, что роут использует помимо локальных импортов, — **перенести вместе с ним**:
   хелперы (`_order_or_404`, `_gcal_reload`, `_voice_status`, `_edition_payload`, `_card_for`,
   `_task_as_event`, `_event_as_task`), константы (`VOICES`, `DEMO_TEXT`, `PC_ORGANIZE_*`).
   Если хелпер нужен **двум и более** модулям — положить в `core/api/_shared.py` и реэкспортировать
   из `app.py` (как уже сделано для `_ev_out`), **не** дублировать.
5. Удалить перенесённый блок из `app.py` (роут + его тело + хелперы, которые ушли с ним).
   Больше неиспользуемый импорт из `app.py` **не трогать на этом шаге** — можно убрать позже,
   отдельным шагом, когда закончим все модули. Лишний импорт не ломает тесты.
6. Подключить модуль в `core/api/routers/__init__.py`:
   ```python
   def register(app) -> None:
       from . import finance
       finance.register(app)
   ```
   Порядок вызовов = порядок из §2.2.

### 2.4 Чем проверять (после каждого модуля)

```bat
cd C:\Users\vevxhzx\Desktop\project\jarvis-main
.venv\Scripts\python.exe -m pytest tests -q          :q
```
и (раз в конце фазы, не каждый шаг):
```bat
cd web && npm run build
```

Плюс **обязательная** проверка, что поведение не изменилось (30 секунд, ловит 90 % ошибок):

```python
# .venv\Scripts\python.exe -c  — выполнить из корня репозитория
import core.api.app as a
print(len(a.app.routes))          # ДО переноса и ПОСЛЕ должно совпадать
```

и сравнение списка роутов до/после (порядок + пути + методы) — это делает скрипт из §7.

**Критерий готовности шага:** `460 passed`, `len(app.routes)` не изменился, список роутов
идентичен, `git diff --stat` показывает только перенос (перемещение строк), коммит + тег.

### 2.5 Когда откатывать (правило из OVERNIGHT.md, пункт 7)

- Тест упал **не из-за переноса** (был красным до тебя) → записать в `PROGRESS.md`, идти дальше.
- Тест упал **из-за переноса** → одна попытка починить.
- Вторая попытка не помогла → **откатить весь шаг 7.N**:
  `git revert <commit>` (не `git checkout` — так сохраняется история) → записать причину в
  `PROGRESS.md` → перейти к следующему модулю или закончить фазу.
- **Откатывается шаг, не вся фаза.** Всю фазу откатываем только если после неё красные тесты
  и починить не удалось за 2 попытки на модуль.

---

## 3. ПОЛНАЯ ТАБЛИЦА РОУТОВ → ЦЕЛЕВЫЕ МодуЛИ

Номера строк — в `core/api/app.py` **после шага 7.0** (если шаг 7.N что-то перенёс, номера сдвинутся;
ориентироваться на путь, а не на номер).

#### `core/api/routers/finance.py` — **42** роутов

Деньги: `/api/finance/*`, `/api/insights/*`, `/api/missed`, `/api/snapshot/*`, `/api/export/*`.

| app.py (после 7.0) | метод | путь |
|---|---|---|
| 335 | `POST` | `/api/finance/import` |
| 354 | `GET` | `/api/insights/forecast` |
| 360 | `GET` | `/api/insights/subscriptions` |
| 366 | `GET` | `/api/insights/streak` |
| 372 | `GET` | `/api/insights/birthdays` |
| 401 | `GET` | `/api/insights/weekly` |
| 453 | `GET` | `/api/missed` |
| 460 | `GET` | `/api/snapshot/month.png` ·  include_in_schema=False |
| 798 | `GET` | `/api/finance/summary` |
| 803 | `GET` | `/api/finance/daily` |
| 808 | `GET` | `/api/finance/forecast` |
| 852 | `GET` | `/api/finance/transactions` |
| 857 | `POST` | `/api/finance/transactions` |
| 862 | `PUT` | `/api/finance/transactions/{tx_id}` |
| 867 | `DELETE` | `/api/finance/transactions/{tx_id}` |
| 874 | `POST` | `/api/finance/categories` |
| 879 | `PUT` | `/api/finance/categories/{cid}` |
| 884 | `DELETE` | `/api/finance/categories/{cid}` |
| 891 | `GET` | `/api/finance/budgets` |
| 896 | `GET` | `/api/finance/categories` |
| 901 | `GET` | `/api/finance/accounts` |
| 906 | `POST` | `/api/finance/accounts/balance` |
| 911 | `POST` | `/api/finance/accounts` |
| 916 | `PUT` | `/api/finance/accounts/{aid}` |
| 921 | `DELETE` | `/api/finance/accounts/{aid}` |
| 928 | `GET` | `/api/finance/debts` |
| 933 | `POST` | `/api/finance/debts` |
| 939 | `POST` | `/api/finance/debts/{debt_id}/pay` |
| 947 | `GET` | `/api/finance/debts/{debt_id}/payments` |
| 952 | `PUT` | `/api/finance/debts/{debt_id}` |
| 958 | `DELETE` | `/api/finance/debts/{debt_id}` |
| 965 | `GET` | `/api/finance/recurring` |
| 970 | `POST` | `/api/finance/recurring` |
| 975 | `PUT` | `/api/finance/recurring/{rid}` |
| 980 | `DELETE` | `/api/finance/recurring/{rid}` |
| 1241 | `GET` | `/api/finance/goals` |
| 1246 | `POST` | `/api/finance/goals` |
| 1255 | `PUT` | `/api/finance/goals/{gid}` |
| 1263 | `DELETE` | `/api/finance/goals/{gid}` |
| 1270 | `POST` | `/api/finance/goals/{gid}/put` |
| 1280 | `GET` | `/api/finance/techniques` |
| 2141 | `GET` | `/api/export/{what}.{fmt}` |

#### `core/api/routers/orders.py` — **22** роутов

Заказы, таймер, помодоро, фриланс, клиенты заказов: `/api/orders/*`.

| app.py (после 7.0) | метод | путь |
|---|---|---|
| 471 | `GET` | `/api/orders/suggest` |
| 999 | `GET` | `/api/orders/clients` |
| 1004 | `POST` | `/api/orders/clients` |
| 1014 | `PUT` | `/api/orders/clients/{cid}` |
| 1022 | `DELETE` | `/api/orders/clients/{cid}` |
| 1107 | `GET` | `/api/orders` |
| 1112 | `GET` | `/api/orders/stats` |
| 1117 | `GET` | `/api/orders/timer` |
| 1122 | `GET` | `/api/orders/pomodoro` |
| 1127 | `GET` | `/api/orders/freelance` |
| 1133 | `PUT` | `/api/orders/freelance` |
| 1140 | `GET` | `/api/orders/pulse` |
| 1149 | `PUT` | `/api/orders/pomodoro` |
| 1156 | `POST` | `/api/orders/timer` |
| 1165 | `DELETE` | `/api/orders/timer` |
| 1172 | `POST` | `/api/orders` |
| 1182 | `GET` | `/api/orders/{oid}` |
| 1189 | `POST` | `/api/orders/{oid}/time` |
| 1199 | `POST` | `/api/orders/{oid}/time/from-screen` |
| 1210 | `PUT` | `/api/orders/{oid}` |
| 1221 | `DELETE` | `/api/orders/{oid}` |
| 1229 | `POST` | `/api/orders/{oid}/payments` |

#### `core/api/routers/boards.py` — **17** роутов

Доски заказов (макеты): `/api/boards/*`.

| app.py (после 7.0) | метод | путь |
|---|---|---|
| 1321 | `GET` | `/api/boards` |
| 1327 | `POST` | `/api/boards` |
| 1337 | `GET` | `/api/boards/search` |
| 1343 | `GET` | `/api/boards/for-order/{oid}` |
| 1352 | `GET` | `/api/boards/{bid}` |
| 1361 | `GET` | `/api/boards/{bid}/text` |
| 1370 | `PUT` | `/api/boards/{bid}` |
| 1382 | `DELETE` | `/api/boards/{bid}` |
| 1390 | `POST` | `/api/boards/{bid}/items` |
| 1400 | `POST` | `/api/boards/{bid}/frame` |
| 1412 | `POST` | `/api/boards/{bid}/renumber` |
| 1420 | `PUT` | `/api/boards/{bid}/items` |
| 1431 | `PUT` | `/api/boards/{bid}/items/{iid}` |
| 1443 | `POST` | `/api/boards/{bid}/items/delete` |
| 1451 | `PUT` | `/api/boards/{bid}/sync` |
| 1465 | `POST` | `/api/boards/{bid}/asset` |
| 1478 | `POST` | `/api/boards/{bid}/image` |

#### `core/api/routers/people.py` — **15** роутов

Люди, связи (`/api/relations/*`), цели-aims (`/api/aims/*`, `/api/milestones/*`).

| app.py (после 7.0) | метод | путь |
|---|---|---|
| 392 | `PUT` | `/api/relations/{rid}` |
| 690 | `GET` | `/api/aims` |
| 696 | `GET` | `/api/aims/{aim_id}` |
| 705 | `POST` | `/api/aims` |
| 712 | `PUT` | `/api/aims/{aim_id}` |
| 725 | `POST` | `/api/aims/{aim_id}/milestones` |
| 734 | `POST` | `/api/milestones/{mid}/{status}` |
| 1030 | `GET` | `/api/people/batch-hints` |
| 1037 | `GET` | `/api/people/kinds` |
| 1043 | `DELETE` | `/api/people/kinds/{kind}` |
| 1050 | `GET` | `/api/people` |
| 1056 | `POST` | `/api/people` |
| 1066 | `GET` | `/api/people/today` |
| 1072 | `GET` | `/api/people/{cid}` |
| 1083 | `PUT` | `/api/people/{cid}` |

#### `core/api/routers/tasks.py` — **15** роутов

Календарь и дела: `/api/events*` (кроме SSE), `/api/tasks/*`, `/api/focus`, `/api/timeline`.

| app.py (после 7.0) | метод | путь |
|---|---|---|
| 492 | `GET` | `/api/events` |
| 515 | `POST` | `/api/events` |
| 522 | `PUT` | `/api/events/{event_id}` |
| 532 | `POST` | `/api/events/{event_id}/done` |
| 591 | `POST` | `/api/events/{event_id}/skip` |
| 600 | `DELETE` | `/api/events/{event_id}` |
| 615 | `GET` | `/api/tasks` |
| 628 | `GET` | `/api/tasks/{task_id}` |
| 637 | `POST` | `/api/tasks` |
| 642 | `PUT` | `/api/tasks/{task_id}` |
| 665 | `POST` | `/api/tasks/{task_id}/undone` |
| 674 | `POST` | `/api/tasks/{task_id}/done` |
| 682 | `DELETE` | `/api/tasks/{task_id}` |
| 745 | `GET` | `/api/focus` |
| 773 | `GET` | `/api/timeline` |

#### `core/api/routers/mind.py` — **27** роутов

Мозг: заметки, ссылки, факты, память, поиск, граф, карточки.

| app.py (после 7.0) | метод | путь |
|---|---|---|
| 102 | `GET` | `/api/cards/{name}` |
| 378 | `GET` | `/api/notes/{nid}/related` |
| 384 | `GET` | `/api/links/{lid}/related` |
| 1093 | `GET` | `/api/graph` |
| 1099 | `GET` | `/api/graph/backlinks/{kind}/{ref_id}` |
| 1288 | `GET` | `/api/notes` |
| 1293 | `POST` | `/api/notes` |
| 1298 | `POST` | `/api/notes/photo` |
| 1517 | `POST` | `/api/notes/{nid}/polish` |
| 1526 | `PUT` | `/api/notes/{nid}` |
| 1535 | `DELETE` | `/api/notes/{nid}` |
| 1546 | `GET` | `/api/links` |
| 1551 | `POST` | `/api/links` |
| 1556 | `PUT` | `/api/links/{lid}` |
| 1574 | `DELETE` | `/api/links/{lid}` |
| 1586 | `GET` | `/api/facts` |
| 1593 | `POST` | `/api/facts` |
| 1602 | `PUT` | `/api/facts/{fid}` |
| 1611 | `POST` | `/api/facts/{fid}/forget` |
| 1620 | `POST` | `/api/facts/{fid}/restore` |
| 1629 | `POST` | `/api/facts/portrait` |
| 1636 | `POST` | `/api/facts/style` |
| 1643 | `PUT` | `/api/facts/style` |
| 1666 | `POST` | `/api/facts/nightly` |
| 1673 | `GET` | `/api/memory` |
| 2184 | `GET` | `/api/search/semantic` |
| 2190 | `POST` | `/api/search/reindex` |

#### `core/api/routers/pc.py` — **13** роутов

ПК-клиент и голос: `/api/pc/*`, `/api/screen`, `/api/vision/*`, `/api/voice/*`.

| app.py (после 7.0) | метод | путь |
|---|---|---|
| 177 | `POST` | `/api/pc/ping` |
| 207 | `GET` | `/api/screen` |
| 219 | `POST` | `/api/pc/ack` |
| 227 | `GET` | `/api/pc/state` |
| 233 | `POST` | `/api/pc/launch` |
| 243 | `GET` | `/api/pc/organize/log` |
| 249 | `GET` | `/api/pc/organize/preview` |
| 255 | `POST` | `/api/pc/result` |
| 280 | `POST` | `/api/pc/clipboard` |
| 300 | `POST` | `/api/vision/ask` |
| 1979 | `GET` | `/api/voice/voices` |
| 1986 | `GET` | `/api/voice/demo` |
| 2016 | `POST` | `/api/voice/pick` |

#### `core/api/routers/system.py` — **44** роутов

Системное: чат/SSE, статус, настройки, доступ,Tg, Google, бэкапы, статика, catch-all.

| app.py (после 7.0) | метод | путь |
|---|---|---|
| 62 | `GET` | `/api/events/stream` |
| 117 | `POST` | `/api/chat` |
| 124 | `POST` | `/api/chat/stream` |
| 158 | `POST` | `/api/undo` |
| 166 | `GET` | `/api/chat/history` |
| 317 | `POST` | `/api/cloud/preview` |
| 407 | `GET` | `/api/health` |
| 417 | `GET` | `/api/dashboard` |
| 757 | `GET` | `/api/state` |
| 766 | `GET` | `/api/presence/events` |
| 784 | `GET` | `/api/diagnose` |
| 1508 | `GET` | `/media/{path:path}` ·  include_in_schema=False |
| 1652 | `GET` | `/api/lessons` |
| 1658 | `DELETE` | `/api/lessons/{lid}` |
| 1682 | `GET` | `/api/ui-prefs` |
| 1692 | `PUT` | `/api/ui-prefs` |
| 1714 | `GET` | `/api/edition` |
| 1720 | `POST` | `/api/edition` |
| 1729 | `GET` | `/api/client/info` |
| 1739 | `GET` | `/api/llm` |
| 1750 | `GET` | `/api/settings` |
| 1756 | `PUT` | `/api/settings` |
| 1787 | `GET` | `/api/status` |
| 1832 | `GET` | `/api/phone` |
| 1887 | `GET` | `/api/runs` |
| 1894 | `GET` | `/api/runs/report` |
| 1901 | `POST` | `/api/phone/rotate` |
| 1911 | `POST` | `/api/tg/login` |
| 1930 | `POST` | `/api/tg/logout` |
| 1937 | `GET` | `/api/tg/miniapp` |
| 2035 | `POST` | `/api/game` |
| 2041 | `POST` | `/api/status/small` |
| 2048 | `POST` | `/api/status/gemini` |
| 2065 | `GET` | `/api/google/status` |
| 2070 | `GET` | `/api/google/connect` |
| 2079 | `GET` | `/api/google/callback` ·  response_class=HTMLResponse |
| 2098 | `POST` | `/api/google/sync` |
| 2106 | `POST` | `/api/google/disconnect` |
| 2115 | `POST` | `/api/backup` |
| 2123 | `GET` | `/api/backups` |
| 2129 | `POST` | `/api/backups/restore` |
| 2196 | `GET` | `/manifest.json` ·  include_in_schema=False |
| 2231 | `GET` | `/{path:path}` ·  include_in_schema=False |
| 2248 | `GET` | `/` ·  response_class=HTMLResponse, include_in_schema=False |

**Всего роутов: 195** · finance 42 · orders 22 · boards 17 · people 15 · tasks 15 · mind 27 · pc 13 · system 44

Плюс отдельно, **не переносится** (остаётся в `core/api/app.py`):

- `app = FastAPI(...)` — создание приложения.
- `app.add_middleware(CORSMiddleware, ...)` и `app.add_middleware(AuthMiddleware)`.
- `app.include_router(_crm_router)` — CRM-роутер из `core/crm/router.py` (не трогаем).
- `@app.exception_handler(finance.FinanceError)` (`_fin_err`).
- `web_dist` + блок `app.mount("/assets", StaticFiles(...))` и catch-all SPA — **последними**.

### Решения по спорным путям (почему так)

| Путь | Решение | Причина |
|---|---|---|
| `/api/events/stream` (SSE) | → **system.py**, не tasks.py | Это живой канал для **всех** модулей, а не календарь. Работает поверх `broadcast`/`_subscribers` из `_shared.py`. Кладём рядом с `/api/chat/stream`, который отдаёт тот же поток событий. |
| `/api/cards/{name}` | → mind.py | Картинки-ответы (`core/services/cards.py`) — это mind-контент, приходит из `/api/chat` и `/api/snapshot`. Хелпер `_card_for` нужен и chat (system), и mind → **остаётся в `app.py` до шага 7.6**, потом уходит в `_shared.py`. |
| `/api/notes/{nid}/related`, `/api/links/{lid}/related` | → mind.py | Хелпер один на оба (`insights.related`), логически — mind. |
| `/api/graph`, `/api/graph/backlinks/*` | → mind.py | Граф связей строится по заметкам/ссылкам/людям (`core/services/graph.py`). Отдельный модуль не заводим — 2 роута, у mind.py уже есть соседи. |
| `/api/insights/*`, `/api/missed` | → finance.py | Прогноз, подписки, серия, дни рождения, «что я упускаю» — всё про деньги/аналитику (задании так и сказано). |
| `/api/snapshot/month.png` | → finance.py | По заданию. Картинка рисуется из финансов. |
| `/api/export/{what}.{fmt}` | → finance.py | Экспорт таблиц БД; в основном финансы/заказы. |
| `/api/aims/*`, `/api/milestones/*` | → people.py | Задание относит aims к people. |
| `/api/relations/{rid}` | → people.py | Задание относит relations к people. |
| `/api/lessons/*` | → system.py | Задание относит lessons к system. |
| `/api/edition`, `/api/ui-prefs`, `/api/client/info` | → system.py | Настройки/служебное. |
| `/media/{path:path}` | → **НЕ переносим**, оставить в `app.py` | Отдача файлов. Стоит рядом со статикой; перенос ничего не даёт и добавляет риск порядка. |

**Итого: 195 роутов → 8 модулей.** Ничего не «не влезло» — отдельный девятый модуль не нужен.

---

## 4. ИНВАРИАНТЫ РЕГИСТРАЦИИ (обязательны для 7.1–7.6)

Продублированы комментарием в `core/api/app.py` (рядом с вызовом `_register_routers(app)`)
и докстрингом `core/api/routers/__init__.py`.

### 4.1 Фактический порядок в `app.py` СЕЙЧАС (проверено)

| строка | что | комментарий |
|---|---|---|
| 34 | `app = FastAPI(title=..., version="0.1")` | создание приложения |
| 36-37 | `app.add_middleware(CORSMiddleware, ...)` | **остаётся в app.py** |
| 39-40 | `from .auth import AuthMiddleware` → `app.add_middleware(AuthMiddleware)` | **остаётся в app.py** |
| 43-44 | `from ..crm.router import router as _crm_router` → `app.include_router(_crm_router)` | **не ломать**, CRM-роутер подключён ДО всех наших роутов |
| 62-2192 | 195 роутов `@app.get/post/put/patch/delete` | именно в этом порядке |
| 2217-2219 | `from .routers import register as _register_routers` → `_register_routers(app)` | ← **точка подключения роутов** |
| 2222-2224 | `web_dist = ROOT / "web" / "site"` (fallback `web/dist`) | остаётся |
| 2229 | `app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")` | **ПОСЛЕДНИМ** |
| 2231-2244 | `@app.get("/{path:path}")` → `def spa(...)` (catch-all SPA) | **ПОСЛЕДНИМ** |
| 2245-2250 | `else:` → `@app.get("/")` → `preview.html` (если site не собран) | **ПОСЛЕДНИМ** |
| 805-807 | `@app.exception_handler(finance.FinanceError)` (`_fin_err`) | остаётся в app.py (регистрация независима от порядка) |

### 4.2 Правила

1. **Статика и catch-all — ПОСЛЕДНИЕ.** `app.mount("/assets", …)` и catch-all `{path:path}`
   регистрируются в самом конце `app.py`. Если `_register_routers(app)` окажется **ниже** них,
   catch-all `GET /{path:path}` перехватит **все** `GET /api/*` (он матчится первым), сайт
   перестанет открываться, а тесты, бьющие по `GET`, начнут получать HTML вместо JSON.
   → Точка подключения роутов строго между `include_router(_crm_router)` и `web_dist = …`.
2. **`include_router` для CRM уже есть** (строка 44) — не дублировать, не переносить в
   `core/api/routers/`. CRM остаётся подключённым ДО наших роутов; это текущее поведение.
3. **Middleware, lifespan/startup, exception handlers, CORS-конфиг остаются в `app.py`.**
   В проекте **нет** `@app.on_event`, нет `lifespan=`, нет `Depends` в роутах (проверено) —
   переносить нечего, но и добавлять не надо.
4. **Порядок роутов = порядок в таблице §3.** Менять его нельзя без проверки тестов:
   он определяет, какой роут выиграет при совпадении путей.
5. **Нет конфликтующих путей** — проверено программно на реальном `app.routes`:
   ни одной пары «параметрический путь зарегистрирован раньше литерального с тем же числом
   сегментов и пересекающимся методом». Исключение — `/{path:path}` и `/`, но это и есть
   catch-all, он регистрируется последним намеренно.
   Дубликатов `(метод, путь)` — **ноль**. Пути, встречающиеся разными методами
   (`/api/tasks/{task_id}` GET/PUT, `/api/facts/style` POST/PUT, `/api/orders/timer` GET/POST/DELETE) —
   это нормально, они не конфликтуют.
6. **Имена функций-обработчиков можно не сохранять** — на них никто не ссылается
   (проверено: `core/telegram/bot.py` импортирует только `app`, тесты — только `app`).
   Но чтобы diff читался как перенос, лучше сохранить.

---

## 5. Что вынесено в `schemas.py` и `_shared.py` — и почему импорты не сломаны

### 5.1 `core/api/schemas.py` — 63 Pydantic-модели

Перенесены **все** top-level `class X(BaseModel)` из `app.py`, без исключений, без переименований.
Тела классов скопированы посимвольно (перенос делался скриптом, не руками).

Группы: чат (`ChatIn`) · ПК (`PcPing`, `PcAck`, `PcLaunch`, `PcResult`, `PcClip`) · зрение/облако
(`VisionIn`, `CloudPreviewIn`) · связи (`RelationIn`) · календарь (`EventIn`, `SkipIn`, `EventDoneIn`) ·
задачи (`TaskIn`, `TaskPatch`) · aims (`AimIn`, `AimPatch`, `MilestoneIn`) · финансы (`TxIn`, `TxPatch`,
`CategoryIn`, `CategoryPatch`, `BalanceIn`, `AccountIn`, `AccountPatch`, `DebtIn`, `PayIn`, `DebtPatch`,
`RecurringIn`, `RecurringPatch`) · заказы (`ClientIn`, `OrderIn`, `OrderPatch`, `PaymentIn`, `TimerIn`,
`ManualTimeIn`, `ScreenImportIn`, `PomoSettingsIn`, `FreelanceIn`) · цели (`GoalIn`, `GoalPatch`, `GoalPut`) ·
заметки/ссылки (`NoteIn`, `NoteEdit`, `LinkIn`, `LinkEdit`) · доски (`BoardIn`, `BoardPatch`, `BoardItemIn`,
`BoardItemPatch`, `BoardBulk`, `BoardIds`, `BoardSync`) · факты (`FactIn`, `FactPatch`, `StyleIn`) ·
настройки (`UiPrefsIn`, `EditionIn`, `SettingsIn`, `BackupRestoreIn`, `TgLogin`, `VoicePick`, `GameBody`).

**Проверка безопасности:**
- `grep` по `core/`, `tests/`, `run.py`, `voice_client.py`: **никто не импортирует эти классы из
  `core.api.app`**. Единственные внешние импорты из `core.api.app` — `app` (22 места) и
  `broadcast` (`core/crm/router.py`, ленивый импорт внутри функции).
- Поэтому реэкспорт в `app.py` (`from .schemas import (…)`, 63 имени) — страховка на будущее:
  любые существующие и будущие импорты продолжат работать.
- Проверено программно: `getattr(core.api.app, Name) is getattr(core.api.schemas, Name)` → `True`
  для всех выборочно проверенных (`ChatIn`, `EventIn`, `OrderIn`, `BoardSync`, `BackupRestoreIn`, `SettingsIn`).
- 63 класса в `app.py` не осталось: `re.findall(r"^class \w+\(BaseModel\)", app.py)` → `[]`.
- Имена моделей в OpenAPI-схеме не изменились (классы те же, `__name__` тот же) — контракт API цел.

### 5.2 `core/api/_shared.py` — общее состояние уровня модуля

Вынесено **только то, что реально нужно нескольким роутерам**:

| Объект | Кто использует | Почему в `_shared` |
|---|---|---|
| `broadcast()` | **24 роута** + `core/crm/router.py` + `agent.on_change` | Ядро живых обновлений, без него не работает SSE |
| `_subscribers` | `broadcast()` + `/api/events/stream` | Изменяемое состояние SSE, разделяемое |
| `_pc_streams` | `/api/events/stream` (счётчик `pc.SSE_CLIENTS`) | Там же |
| `_ev_out()` | 7 роутов: `/api/dashboard` + все `/api/events*` | Формат события нужен и дашборду, и календарю |
| `log` | 3 роута + весь `app.py` | Общий логгер `jarvis.api`, нечего плодить |

**Сознательно НЕ вынесено** (проверено по количеству использований — по одному модулю):

| Объект | Использует | Решение |
|---|---|---|
| `PC_ORGANIZE_LOG`, `PC_ORGANIZE_PREVIEW` | 2 роута ПК (`/api/pc/organize/*`, `/api/pc/result`) | → `pc.py` на шаге 7.6 |
| `VOICES`, `DEMO_TEXT` | 3 роута голоса | → `pc.py` на шаге 7.6 |
| `_order_or_404` | 7 роутов заказов | → `orders.py` на шаге 7.2 |
| `_gcal_reload` | 7 роутов: `/api/settings` + все `/api/google/*` | → `system.py` на шаге 7.6 |
| `_voice_status` | `/api/status` | → `system.py` |
| `_edition_payload` | 3 роута `/api/edition` | → `system.py` |
| `_card_for` | `/api/chat`, `/api/chat/stream`, `/api/events/stream` | 2 из 3 уезжают в `system.py`, 1 в `tasks.py` → на шаге 7.6 в `_shared.py` |
| `_task_as_event` | 2 роута календаря | → `tasks.py` |
| `_event_as_task` | 2 роута задач | → `tasks.py` |
| `web_dist` | SPA + `/manifest.json` | остаётся в `app.py` |

**Реэкспорт из `app.py` (обязателен, ломать нельзя):**
```python
from ._shared import _ev_out, _pc_streams, _subscribers, broadcast  # noqa: F401  (реэкспорт)
```
- `core/crm/router.py:23` делает `from ..api.app import broadcast` — работает, проверено:
  `core.api.app.broadcast is core.api._shared.broadcast` → `True`.
- `agent.on_change = broadcast` остался в `app.py` (строка 59) — поведение не изменилось.
- `_subscribers` — **тот же объект** (`app._subscribers is _shared._subscribers` → `True`),
  т.е. подписчики SSE, зарегистрированные до и после шага 7.0, видны одинаково.

---

## 6. ОСТРЫЕ РОУТЫ (для шагов 7.1–7.6)

### 6.1 Критические — сломают сайт или безопасность

| Роут(ы) | app.py | Почему острый | Что делать при переносе |
|---|---|---|---|
| `/api/events/stream` (SSE) | 62 | Живой канал для всего сайта и для `voice.bat` (`?client=pc`). Держит `_subscribers`/`_pc_streams`, ставит `pc.SSE_CLIENTS`. Долгоживущий `StreamingResponse` с `finally`-очисткой | → `system.py`. **Возьми с собой `stream()` целиком**, включая `import asyncio as _asyncio` и `from fastapi.responses import StreamingResponse`. `_subscribers`/`_pc_streams` — из `_shared`. Порядок регистрации: **раньше** всего, что начинается с `/api/events` |
| `/api/settings` PUT | 1756 | 5 локальных импортов, меняет `config.yaml` через `write_settings`, вызывает `_gcal_reload()` (асинхронный `create_task`), `broadcast("settings", …)`, `agent.on_change`-цепочка | → `system.py`. Переносить **вместе с `_gcal_reload`** и `_voice_status` (тоже там). Не менять ни строчки логики |
| `/api/phone` GET, `/api/phone/rotate` POST | 1832, 1901 | **Безопасность.** Работают только с loopback: `from .auth import token as _tok, is_local as _is_lb`; `if not _is_lb(request): 403`. Генерируют QR (`segno`), показывают tail-токен | → `system.py`. **Обязательно** сохранить импорт `is_local as _is_lb` внутри функции и проверку. `test_security.py` это покрывает — не «улучшать» |
| `/api/tg/login`, `/api/tg/miniapp` | 1911, 1937 | Вход из Telegram Mini App: HMAC-проверка `initData`, лимит попыток, cookie на 30 дней. Зависит от `.tg_auth` и `is_https(request)` | → `system.py`, вместе с `tg_logout`. Не менять логику подписи |
| `/api/cloud/preview` | 317 | Фаза 6: превью «что уйдёт в облако». Проверяет `allow_cloud`/личные данные. `test_overnight_fase6_security.py` покрывает | → `system.py` |
| `/api/pc/launch`, `/api/vision/ask`, `/api/pc/result`, `/api/pc/clipboard` | 233, 300, 255, 280 | Фаза 6: команды ПК принимаются только из каналов владельца (`-fwd` отсекается); скриншот в облако — только при явном `allow_cloud` | → `pc.py`. Тесты фазы 6 должны остаться зелёными — это главный индикатор |
| `/api/pc/ping` | 177 | Обновляет `pc.STATE`, шлёт `broadcast("pc_state")`, пишет в лог. Самый «шумный» роут ПК | → `pc.py` |
| `/media/{path:path}` | 1508 | Отдаёт пользовательские файлы. Идёт **до** catch-all. У него `include_in_schema=False` | **Оставить в `app.py`**, не переносить |

### 6.2 Требуют внимания

| Роут(ы) | app.py | Проблема |
|---|---|---|
| `/api/dashboard` | 417 | Зовёт **все** сервисы разом (finance, calendar, tasks, goals, insights, pc, orders, pulse, screen, brain_notes). Список импортов в `app.py` после переноса сильно похудеет — это нормально, но проверь, что всё нужное реально приехало в `system.py` |
| `/api/health` | 407 | `from .. import VERSION, BUILD` — пакетные импорты из `core/__init__.py`. В новом модуле путь станет `from ... import VERSION, BUILD` (три точки!). **Самая частая ошибка при переносе** |
| `/api/status` | 1787 | 6 локальных импортов, читает `app.state.tg_running` / `app.state.errors` (`getattr(app.state, ...)`). `app.state` — атрибут **объекта app**, а не модуля: работает из любого модуля, но проверь |
| `/api/status/small`, `/api/status/gemini` | 2041, 2048 | Ходят в облако (Gemini). Проверка ключа/режима |
| `/api/phone` GET | 1832 | `socket`, `subprocess`, `cfg` + генерация QR. Долгий, но простой |
| `/api/export/{what}.{fmt}` | 2141 | 5 локальных импортов + вложенный `_row()`, BOM для CSV, `Response` с `Content-Disposition`. Ломается легче всего — **копировать дословно** |
| `/api/notes/photo`, `/api/boards/{bid}/asset`, `/api/boards/{bid}/image` | 1298, 1465, 1478 | `UploadFile`/`Form`, запись на диск. `/api/boards/{bid}/image` тянет `io` + `PIL.Image` — тяжёлый импорт, держи его локальным |
| `/api/backups/restore` | 2129 | Перезаписывает `data/jarvis.db`. `test_backup_restore.py` работает на временной БД |
| `/api/google/callback` | 2079 | `response_class=HTMLResponse`, state-куки, редиректы. Ошибка = мёртвая авторизация |
| `/api/finance/import` | 335 | `request.form()` — единственный роут, читающий сырую форму + `bank_import` |
| `/api/pc/organize/log`, `/api/pc/organize/preview` | 243, 249 | **Читают глобальные `PC_ORGANIZE_LOG` / `PC_ORGANIZE_PREVIEW`**, а `pc_result` их пишет через `global` (строка 261). Все три обязаны попасть в `pc.py` **вместе**, иначе `pc_result` перестанет их обновлять |

### 6.3 Общие наблюдения (проверено программно)

- **`@app.on_event` — НЕТ ни одного.** Lifespan/startup в проекте не используются → переносить нечего.
- **`Depends` — НЕТ ни одного.** Ни один роут не использует зависимости FastAPI.
- **Роут, вызывающий другой роут напрямую, — НЕТ.** Зависимостей «роут → роут» нет. Есть только
  хелперы между роутами (см. §5.2).
- **Дубликатов `(метод, путь)` — НЕТ.** Конфликтующих пар «параметрический раньше литерального» — НЕТ (проверено на реальном `app.routes`).
- **101 роут из 195 делает локальные импорты внутри тела** — их нельзя «причесать» и выносить наверх:
  это осознанный приём проекта (быстрый старт, обход циклов). **Оставить как есть.**
- **Локальные импорты, спасающие от цикла:** `from .auth import is_local as _is_local` (стр. 226),
  `from ..services import pc as _pc` (стр. 65), `from .. import config as _cfg` (стр. 2073),
  `import edge_tts` (стр. 2011). При переносе менять относительный уровень точек (`..` → `...`) **нельзя** для
  `core/api/routers/*.py`: они лежат на уровне `core/api/`, как и `app.py`. То есть `from ..services import pc`
  в `routers/pc.py` означает `core.services` — **правильно, точки те же**. Внимание только к `from .. import VERSION`
  (пакетный `core/__init__.py`) — это тоже `..`, работает.
- **Исключение:** если роут лезет в `core/api/*` (`.auth`, `.tg_auth`), из `routers/*.py` это будет
  `from ..auth import ...` (одна точка пропущена) — **не забыть**.

---

## 7. Контрольный скрипт для шагов 7.1–7.6

Положить в `reviews/` при желании; здесь — содержимое, запускать из корня репозитория.

```python
# .venv\Scripts\python.exe reviews/_check_routes.py  (запускать ДО и ПОСЛЕ переноса, сравнить вывод)
import sys, json
sys.path.insert(0, r"C:\Users\vevxhzx\Desktop\project\jarvis-main")
import core.api.app as a

out = []
for r in a.app.routes:
    p = getattr(r, "path", None)
    if p is None:
        continue
    out.append([p, sorted(getattr(r, "methods", []) or [])])
print(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=False))
```
Совпало «до» и «после» — поведение API не изменилось. `len(app.routes)` = **200** (195 наших + 4 служебных
FastAPI `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc` + 1 mount `/assets`).

**Эталонные значения на конец шага 7.0:**
- `.venv\Scripts\python.exe -m pytest tests -q` → **460 passed, 2 warnings** (~137 с)
- `npm run build` (в `web/`) → успешно, `✓ built in 8.50s`; предупреждения только baseline
  (`tg.js` dynamic import, чанк > 500 kB)
- роутов на `app` — **200**, из них 195 API/статических + 5 служебных
- предупреждения pytest — только baseline (StarletteDeprecationWarning httpx, anyio BlockingPortal)

---

## 8. Чек-лист финальной проверки фазы 7 (когда 7.1–7.6 будут сделаны)

- [ ] `pytest tests -q` → 460 passed (или больше, если добавлены тесты), 0 новых предупреждений
- [ ] `npm run build` в `web/` → успешно, `web/site` в коммите (детерминированная сборка)
- [ ] `git diff --stat` показывает только перемещение строк между `core/api/app.py` и `core/api/routers/*`
- [ ] `core/api/app.py` — только: создание `app`, middleware, CRM `include_router`,
      exception handler, `_register_routers(app)`, статика + catch-all (дёшево, ~80 строк)
- [ ] Ручная проверка: открыть сайт, `/api/health`, `/api/dashboard`, чат, SSE-обновления в двух вкладках,
      запись в `/api/notes`, загрузка фото, доска заказа, бэкапы, доступ с телефона по QR
- [ ] Тег `checkpoint-7` на последнем коммите фазы