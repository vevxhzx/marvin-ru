# ФАЗА 7, шаг 7.5a — ПЕРЕНОС ГРУППЫ MIND в `core/api/routers/mind.py`

**Статус шага: выполнен.** Перенесено **32 роута** из заданных 33 (33-й — `POST /api/chat/stream` —
сознательно оставлен в `core/api/app.py`, он SSE, см. §2), поведение API не изменилось: сверка
маршрутов **1:1, 225 = 225** (MISSING `[]`, ADDED `[]`), тесты зелёные (**598 passed, 2 warnings** —
ровно baseline).

Ветка `overnight-crm`. Родительский коммит `edcdc53` (тег `checkpoint-7-4`), этот шаг — тег
`checkpoint-7-5a`.

> Правило фазы 7: только **механический** перенос. Ни одна строка логики, ни один путь, ни один
> код ответа не менялись. Перенос сделан одноразовым скриптом `reviews/_p7_5a_move.py`
> (отработал `anchors OK: 32 блоков`, удалён после переноса): блоки строк вырезаны из `app.py` по
> **проверенным строкам-якорям** и склеены в новый файл дословно. Изменения в телах роутов —
> только `@app.` → `@router.` (32 шт.), уровень точек у локальных импортов `..` → `...` и одна
> добавленная строка `from ..app import _card_for` в `POST /api/chat` (§4).

---

## 1. Что перенесено (32 роута)

| Модуль | Строк | Роутов |
|---|---|---|
| `core/api/routers/mind.py` | 302 | **32** |

| Метод | Путь | Было в `app.py` (после 7.4) |
|---|---|---|
| `GET` | `/api/cards/{name}` | 102 |
| `POST` | `/api/chat` | 117 |
| `POST` | `/api/undo` | 158 |
| `GET` | `/api/chat/history` | 166 |
| `GET` | `/api/notes/{nid}/related` | 335 |
| `GET` | `/api/links/{lid}/related` | 341 |
| `GET` | `/api/graph` | 425 |
| `GET` | `/api/graph/backlinks/{kind}/{ref_id}` | 431 |
| `GET` | `/api/notes` | 440 |
| `POST` | `/api/notes` | 445 |
| `POST` | `/api/notes/photo` | 450 |
| `POST` | `/api/notes/{nid}/polish` | 481 |
| `PUT` | `/api/notes/{nid}` | 490 |
| `DELETE` | `/api/notes/{nid}` | 499 |
| `GET` | `/api/links` | 510 |
| `POST` | `/api/links` | 515 |
| `PUT` | `/api/links/{lid}` | 520 |
| `DELETE` | `/api/links/{lid}` | 538 |
| `GET` | `/api/facts` | 550 |
| `POST` | `/api/facts` | 557 |
| `PUT` | `/api/facts/{fid}` | 566 |
| `POST` | `/api/facts/{fid}/forget` | 575 |
| `POST` | `/api/facts/{fid}/restore` | 584 |
| `POST` | `/api/facts/portrait` | 593 |
| `POST` | `/api/facts/style` | 600 |
| `PUT` | `/api/facts/style` | 607 |
| `GET` | `/api/lessons` | 616 |
| `DELETE` | `/api/lessons/{lid}` | 622 |
| `POST` | `/api/facts/nightly` | 630 |
| `GET` | `/api/memory` | 637 |
| `GET` | `/api/search/semantic` | 1105 |
| `POST` | `/api/search/reindex` | 1111 |

Состав группы совпал с заданием **1:1** (notes 7, links 5, facts 9, lessons 2, memory/graph 3,
search 2, cards 1, chat/undo 3 из 4) — проверено grep'ом по `core/api/app.py` до и после.

### Порядок роутов

Внутри модуля порядок = порядок в `app.py` до переноса (скрипт сверял со списком
`EXPECTED` — 32/32 в том же порядке). Важные сохранённые пары:

```
PUT /api/facts/{fid}     (idx 21 в модуле) — раньше, чем
PUT /api/facts/style     (idx 25 в модуле)   ← литерал style и раньше «выигрывал»
                                              у {fid}: порядок как в app.py, поведение 1:1
POST /api/notes/photo    — раньше PUT/DELETE /api/notes/{nid}
GET  /api/notes         — раньше POST /api/notes и /api/notes/photo
```

Конкурентов у этих путей в других модулях нет (grep: `/api/facts|notes|links|lessons|graph|memory|
search|cards|chat|undo` есть только в `mind.py` и в оставшихся в `app.py` `chat/stream` + SSE).

### Регистрация

```python
router = APIRouter()          # БЕЗ prefix, БЕЗ dependencies

def register(app) -> None:
    app.include_router(router)
```

Полный путь остался в декораторе (`@router.get("/api/notes")`), поэтому ничего не сдвинулось.
`core/api/routers/__init__.py::register()` теперь:

```python
from . import boards, finance, mind, orders, people, tasks

finance.register(app)
orders.register(app)
boards.register(app)
people.register(app)
tasks.register(app)
mind.register(app)
```

Порядок вызовов = §2.2 отчёта 7.0 (`finance → orders → boards → people → tasks → mind → pc →
system`). Сам `_register_routers(app)` в `app.py` **не перемещался** — он по-прежнему строго между
`app.include_router(_crm_router)` и `web_dist = …` / `app.mount("/assets")` / catch-all.

### Импорты `mind.py` (только нужные, без вайлд-импортов)

```python
from __future__ import annotations

import asyncio
import asyncio as _asyncio
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ...brain import agent
from ...db import Link, Note, session
from ...services import brain_notes, relations
from .._shared import broadcast
from ..schemas import (ChatIn, FactIn, FactPatch, LinkEdit, LinkIn, NoteEdit, NoteIn, StyleIn)
```

Пояснения:

* `asyncio` + `asyncio as _asyncio` — в перенесённых телах используются **оба** имени
  (`asyncio.wait_for` в `POST /api/notes/photo`, `_asyncio.to_thread` в `POST /api/chat`),
  оба — один и тот же модуль, тела дословно не тронуты.
* `File`, `Form`, `UploadFile` — уровня модуля: в сигнатуре `POST /api/notes/photo`
  (`File(...)`/`Form("")` вычисляются при определении функции, отложенный аннотации не спасут).
* `session`, `Note`, `Link` — уровня модуля, как было в `app.py` (`note_polish`, `note_del`,
  `link_edit`, `link_del`, `chat_history`).
* `brain_notes`, `relations` — уровня модуля (`notes/links/memory`, `related/forget`).
* `agent` — только `POST /api/chat`.
* `broadcast` — из `.._shared` (тот же объект, что и в `app.py`).
* Модели `ChatIn`, `NoteIn`, `NoteEdit`, `LinkIn`, `LinkEdit`, `FactIn`, `FactPatch`, `StyleIn` —
  **уже были** в `core/api/schemas.py` (63 класса, шаг 7.0) — новых моделей не создавал,
  в `_shared.py` ничего не добавлял.
* Локальные импорты в телах (~20 шт.) подняты на один уровень точек: `from ...services`
  (insights, graph, polish, memory, judge, semantic, undo), `from ...brain` (llm),
  `from ...db` (ChatMessage, set_setting), `from ...config` (DATA_DIR). Уровень точек у
  *модульных* импортов `app.py` не трогался.
* Модульных `from .auth` / `from .tg_auth` в этой группе нет — «пропущенная точка» §6.3
  отчёта 7.0 не потребовалась.
* Циклических импортов нет: `mind` импортируется в `register()` в конце `app.py`;
  `core.api.routers.mind` не импортирует `core.api.app` на уровне модуля (только локально в
  `chat`, §4).

---

## 2. `POST /api/chat/stream` — НАМЕРЕННО ОСТАЛСЯ В `app.py` (это 33-й роут задания)

Тело функции (стр. 124–155 старого `app.py`) — **настоящий SSE**:

```python
return StreamingResponse(gen(), media_type="text/event-stream",
                         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

Задание предписывает в этом случае оставить роут в `app.py` либо переносить только на 7.6
с проверкой порядка («острое → на 7.6, лучше не рисковать»). Поэтому:

* `/api/chat/stream` (POST-SSE) **остался в `app.py`** вместе с `StreamingResponse`,
  `_asyncio`, `_json`, `llm.token_sink`-цепочкой — ни одна строка не тронута.
* Его позиция в порядке регистрации **не изменилась вообще**: он по-прежнему идёт раньше всех
  доменных роутеров (flat idx **31**, см. §5), т.е. раньше, чем `POST /api/chat` в `mind.py`
  (idx 192). Проверено: `POST /api/chat/stream` → первый FULL-match — сам на себя.
* Также остаётся в `app.py` `GET /api/events/stream` (SSE) — как и на 7.4 (индекс **30**,
  не сдвинулся, закреплено `test_events_stream_registered_before_event_id_and_catchall`).
* На **7.6** оба SSE уезжают в `system.py` — тогда же проверять порядок (инструкция в §7).

Итог по группе chat: `POST /api/chat`, `GET /api/chat/history`, `POST /api/undo` → **mind.py**;
`POST /api/chat/stream` → **остался в app.py**.

---

## 3. Что осталось в `core/api/app.py` и почему

`app.py`: 1178 → **903** строки (`git diff --numstat`: **+7 / −282**; 7 добавленных — обновлённый
комментарий у `_register_routers`, §1). Остальное — чистые удаления.

Осталось **52 роута** из 84 (grep `^\s*@app\.(get|post|put|patch|delete)\(`: было **84** → стало
**52** = ровно −32). Grep по `app.py` не находит ни одного `@app.…("/api/notes`, `/api/links`,
`/api/facts`, `/api/lessons`, `/api/memory`, `/api/graph`, `/api/search`, `/api/cards`,
`/api/undo`, `"/api/chat")`.

| Что осталось | Роутов | Почему |
|---|---|---|
| `app = FastAPI(...)`, CORS, `AuthMiddleware`, `app.include_router(_crm_router)` | — | инвариант §4.2 п. 2–3, не трогаем |
| `@app.exception_handler(finance.FinanceError)` (`_fin_err`) | — | регистрация не зависит от порядка роутов |
| `_register_routers(app)` | — | точка подключения роутов, инвариант §4.2 п. 1 |
| `GET /api/events/stream` (SSE) | 1 | system.py на 7.6 (как на 7.4) |
| `POST /api/chat/stream` (POST-SSE) | 1 | **§2 этого отчёта**: настоящий SSE → 7.6 |
| `/api/chat`-блок: `_card_for` (хелпер, стр. 89) | — | нужен `chat_stream` (остаётся) и перенесённому `chat` → локальный импорт из `app.py`, §4 |
| `/media/{path:path}` | 1 | НЕ переносить (статика, §3 P7_refactor) |
| `/manifest.json`, `/{path:path}` SPA, `/` | 3 | статика и catch-all **последними** |
| ПК/голос/зрение (`/api/pc/*`, `/api/screen`, `/api/vision/*`, `/api/voice/*`) | 13 | шаг **7.5b** (pc.py) |
| Системные (health, dashboard, state, presence, diagnose, cloud/preview, ui-prefs, edition, client/info, llm, settings, status*, phone*, runs, tg*, game, google*, backup*) | 33 | шаг **7.6** (system.py) |

`PC_ORGANIZE_LOG`/`PC_ORGANIZE_PREVIEW` (стр. 56–57), `VOICES`/`DEMO_TEXT` (стр. 667+),
`_card_for`, `broadcast`-реэкспорт, `agent.on_change = broadcast` — **на месте**, используются
оставшимися роутами.

### Неиспользуемые после переноса импорты в `app.py` — НЕ убраны

По §2.3 п. 5 отчёта 7.0 чистка — отдельный шаг после 7.6. Кандидаты (проверить grep'ом перед
чисткой): `Note`, `Link` (перенесены все их роуты), `brain_notes` **ещё нужен** (`/media`,
`/api/dashboard`), `relations`/`insights` — проверить (используются `/api/status` и др.),
схемы `NoteIn/NoteEdit/LinkIn/LinkEdit/FactIn/FactPatch/StyleIn/ChatIn` — `ChatIn` ещё нужен
`chat_stream`. **Не убирать ничего по памяти — только grep'ом.**

---

## 4. `_card_for` — локальный импорт из `core.api.app`, в `_shared.py` НЕ выносил

`_card_for` (стр. 89 `app.py`) нужен двум роутам в двух модулях:

* `POST /api/chat` → уехал в `mind.py`;
* `POST /api/chat/stream` → остался в `app.py` (§2).

Задание запрещает выносить в `_shared.py` («это работа 7.6») и велит сделать локальный импорт из
`core.api.app`. Сделано ровно это — **одна добавленная строка** в теле `chat`:

```python
@router.post("/api/chat")
async def chat(inp: ChatIn):
    from ..app import _card_for  # хелпер остаётся в app.py до шага 7.6
    ...
```

`from ..app` из `core/api/routers/mind.py` = `core.api.app` ✓. Импорт **ленивый** (внутри функции,
в момент первого запроса) — циклического импорта нет: `mind` подключается в конце `app.py`,
`_card_for` к тому моменту определён, а в момент вызова модуль `core.api.app` уже полностью
загружен. На **7.6** перенести `_card_for` в `_shared.py` с реэкспортом из `app.py` и заменить
оба использования (тогда локальный импорт удалить).

### schemas.py / _shared.py на этом шаге

| Файл | Действие |
|---|---|
| `core/api/schemas.py` | **ничего не добавлял** — все 8 моделей (`ChatIn`, `NoteIn`, `NoteEdit`, `LinkIn`, `LinkEdit`, `FactIn`, `FactPatch`, `StyleIn`) уже были на шаге 7.0 |
| `core/api/_shared.py` | **ничего не добавлял** — `broadcast` уже там; `_card_for` остался в `app.py` (§4) |

---

## 5. Сверка маршрутов ДО / ПОСЛЕ (обязательная проверка)

Скрипт: **`reviews/_check_routes.py`** (эталон задания).

```bat
cd C:\Users\vevxhzx\Desktop\project\jarvis-main
:: ДО — на чистом edcdc53 (рабочее дерево не менялось)
.venv\Scripts\python.exe reviews\_check_routes.py 1> %TEMP%\opencode\before75a_routes.json
:: ПОСЛЕ
.venv\Scripts\python.exe reviews\_check_routes.py 1> %TEMP%\opencode\after75a_routes.json
```

```
flat: 225 -> 225 | unique: 225 225
SETS EQUAL: True
SORTED IDENTICAL: True
MISSING (было, нет): []
ADDED   (стало, нет): []
```

**225 = 225, множества `(path, method)` совпали полностью.** `top-level entries` на
`app.router.routes`: 94 → **63** (−32 вырезанных app-роутов +1 новый `_IncludedRouter` mind).
Служебные маршруты FastAPI и mount `/assets` на месте.

### Фактический матчинг (`starlette.routing.Match.FULL`) — 18 кейсов, 0 расхождений с эталоном

```
OK  PUT    /api/facts/style      -> ['/api/facts/{fid}', '/api/facts/style']   (как и до переноса:
                                     {fid} registered раньше style — порядок внутри модуля сохранён)
OK  PUT    /api/facts/1          -> ['/api/facts/{fid}']
OK  POST   /api/notes/photo      -> ['/api/notes/photo', ...]                  (литерал раньше {nid})
OK  POST   /api/chat             -> ['/api/chat']
OK  POST   /api/chat/stream      -> ['/api/chat/stream']        (idx 31, раньше mind-роутов)
OK  GET    /api/chat/history     -> ['/api/chat/history', '/{path:path}']
OK  POST   /api/undo             -> ['/api/undo']
OK  GET    /api/memory           -> ['/api/memory', '/{path:path}']
OK  GET    /api/search/semantic  -> ['/api/search/semantic', '/{path:path}']
OK  GET    /api/lessons          -> ['/api/lessons', '/{path:path}']
OK  DELETE /api/lessons/1        -> ['/api/lessons/{lid}']
OK  GET    /api/graph/backlinks/note/1 -> ['/api/graph/backlinks/{kind}/{ref_id}', '/{path:path}']
OK  GET    /api/events/stream    -> ['/api/events/stream', '/{path:path}']
OK  GET    /api/notes/1/related  -> ['/api/notes/{nid}/related', '/{path:path}']
OK  GET    /api/links/1/related  -> ['/api/links/{lid}/related', '/{path:path}']
OK  POST   /api/facts/nightly    -> ['/api/facts/nightly']
GET /api/notes/1                 -> ['/{path:path}']   (роута GET /api/notes/{nid} НЕТ — как до
                                                        переноса, «чинить» нельзя, 7.4 §4.3)
GET /api/cards/a.png             -> ['/api/cards/{name}', '/{path:path}']     (защита от path
                                                        traversal re.fullmatch не тронута, дословно)
индексы: /api/notes GET = 199 < catch-all = 224; chat/stream = 31 < /api/chat = 192;
         SSE /api/events/stream = 30 (не сдвинулся, как на 7.4)
```

Ни один перенесённый роут не «проигрывает» чужому маршруту, ни один чужой маршрути не
перехвачен mind-роутами; mind зарегистрирован **до** manifest/статики/catch-all.

---

## 6. Тесты

```
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
→ 598 passed, 2 warnings in 140.15s
```

Ровно baseline: **598 passed** (столько же было на 7.4), предупреждения — только 2 известных
baseline (`StarletteDeprecationWarning` httpx, `anyio BlockingPortal`). Ни один старый тест не
сломан и не пропущен.

**Скелет `tests/test_p7_routers_registration.py` на этом шаге НЕ менялся** (задание требует
598 passed и в коммит не велит брать чужие тесты; см. §8 — что дополнить на 7.5b/7.6).

⚠️ В дереве работают параллельные агенты (`core/brain/**`, `tests/test_golden_quick.py`,
`web/**`, `reviews/review_C.md`) — в 598 они входят, в мой коммит **не входят** и мной не
правились. Веб-сборку не запускал, `web/**` не трогал. `PROGRESS.md` не правил (по заданию).

---

## 7. Острые роуты шага 7.5a

| Роут | Что было не так | Как разрешено |
|---|---|---|
| `POST /api/chat/stream` | Настоящий SSE (`StreamingResponse`, `text/event-stream`, очередь токенов, `finally`-отмена task) | **Оставлен в `app.py`** (§2). Позиция не изменилась (idx 31 и до, и после) |
| `GET /api/events/stream` | Тот же SSE, живой сайт + `voice.bat` | Остался в `app.py`, idx **30** — не сдвинулся (наследие 7.4) |
| `POST /api/notes/photo` | `UploadFile`/`File`/`Form` в сигнатуре, 20 МБ-лимит, запись на диск, `asyncio.wait_for(llm.describe_image…)` | Дословно; `File/Form/UploadFile` — модульный импорт (вычисляются при def) |
| `GET /api/cards/{name}` | Отдаёт файлы — path traversal | Тело **дословно**, `re.fullmatch(r"[A-Za-z0-9_\-]+\.png", name)` не тронута; проверено `GET /api/cards/a.png` → первый матч наш роут |
| `PUT /api/facts/style` vs `PUT /api/facts/{fid}` | Литерал зарегистрирован **после** параметрического (строки 607 vs 566) — выигрывает `{fid}` | Так было и до переноса; порядок внутри модуля сохранён 1:1, поведение не изменилось. **Не переставлять и на 7.6 тоже** |
| `POST /api/chat` | Использует `_card_for`, который остаётся в `app.py` | Локальный `from ..app import _card_for` в теле (§4) — единственная добавленная строка |
| `GET /api/lessons`, `DELETE /api/lessons/{lid}` | §3 P7_refactor относит их к system.py, задание этого шага — к mind | Перенесены в `mind.py` по заданию; **7.6 их НЕ трогать** (§8) |
| `/media/{path:path}` | Отдаёт пользовательские файлы | Не переносился, остался в `app.py` |

---

## 8. Инструкции для 7.5b (`pc.py`, 13 роутов) и напоминания для 7.6

### 7.5b — `core/api/routers/pc.py`, 13 роутов (§3 P7_refactor, номера строк уже другие —
ориентироваться на путь):

`POST /api/pc/ping`, `GET /api/screen`, `POST /api/pc/ack`, `GET /api/pc/state`,
`POST /api/pc/launch`, `GET /api/pc/organize/log`, `GET /api/pc/organize/preview`,
`POST /api/pc/result`, `POST /api/pc/clipboard`, `POST /api/vision/ask`,
`GET /api/voice/voices`, `GET /api/vision/ask` уже… — точный список: **pc/ping, screen, pc/ack,
pc/state, pc/launch, pc/organize/log, pc/organize/preview, pc/result, pc/clipboard, vision/ask,
voice/voices, voice/demo, voice/pick = 13**.

1. **`PC_ORGANIZE_LOG` / `PC_ORGANIZE_PREVIEW`** (сейчас `app.py:56-57`) обязаны переехать
   **вместе** с тремя роутами `pc/organize/log`, `pc/organize/preview`, `pc/result`: последний
   пишет их через `global` (стр. 221/229). Если оставить константы в `app.py`, а `pc_result`
   увезти — он начнёт писать в «свои» пустые глобалы, и лог организаций «сломается» молча
   (тесты это могут не поймать). Перед переносом grep: кто ещё читает эти имена (после 7.5a —
   только эти 3 роута в `app.py`).
2. **`VOICES` (app.py:667)** и **`DEMO_TEXT` (app.py:676)** — вместе с 3 голосовыми роутами
   (ищет их и `voice/pick`). Приоритет: демо-озвучка (`edge_tts` — локальный импорт, оставить).
3. Роуты с `is_local`/`from .auth`: **в `routers/pc.py` уровень точек меняется**
   `from .auth import …` → `from ..auth import …` (§6.3 отчёта 7.0 — «пропущенная точка»).
   `from ..services import pc` остаётся **`..`? НЕТ**: в `routers/*.py` это `...services`
   (пример7.4: `from ...services import aims`).
4. Формат тот же: скрипт с якорями, `@app.` → `@router.`, `router = APIRouter()` без prefix,
   `pc.register(app)` **после `mind.register(app)`** в `routers/__init__.py`.
5. Тесты фазы 6 (`test_overnight_fase6_security.py`) бьют по `/api/pc/*`, `/api/vision/ask` —
   это главный индикатор. `test_registered_before_spa_catchall` правок не требует (pc-роуты
   зарегистрируются после mind, до статики — ок).
6. После 7.5b в `app.py` должно остаться **39 роутов** (52 − 13); сверка `check_routes.py`
   снова **225 = 225**; pytest **598 passed**.
7. Отчёт: `reviews/P7_5b_pc.md`, тег `checkpoint-7-5b`.

### Что доработать в скелете тестов (можно на 7.5b или 7.6, отдельным коммитом)

`tests/test_p7_routers_registration.py`: добавить `MIND_ROUTES` (32) +
`("mind", "/api/notes")` в `DOMAINS` (прим.: `test_route_matches` потребуют подстановки `{nid}`→`1`,
`{fid}`→`1`, `{lid}`→`1`, `{name}`→`a.png`), `test_mind_router_has_exactly_32_routes`,
`test_mind_routes_registered_on_app`. **Не делать на 7.6 вместе с чем-то ещё — отдельно.**

### Напоминания для 7.6 (`system.py`)

* Уже **не трогать**: `/api/lessons*`, `/api/chat` POST, `/api/chat/history`, `/api/undo`,
  `/api/memory`, `/api/graph*`, `/api/search*`, `/api/cards/{name}`, `/api/notes*`,
  `/api/links*`, `/api/facts*` — всё это теперь `mind.py` (§7 таблица задания расходится с §3
  P7_refactor — побеждает задание).
* Увезти в `system.py`: оба SSE (`/api/events/stream` **и** `/api/chat/stream`) — и обязательно
  проверить, что SSE регистрируются **раньше** параметрических путей (`test_events_stream_...`
  и `test_events_stream_registered_before_event_id_and_catchall` специально упадут, если порядок
  сломан); `_card_for` вынести в `_shared.py` с реэкспортом и удалить локальный импорт из
  `mind.py::chat`.
* `register()` остаётся ПОСЛЕ CRM и ДО статики; `system.py` — последним.

---

## 9. Контрольный чек-лист шага 7.5a

- [x] 32 роута перенесены дословно, `git diff --numstat core/api/app.py` = **+7 / −282** (7 строк — комментарий)
- [x] `app.py`: 1178 → 903 строк; роутов в `app.py` 84 → 52 (ровно −32)
- [x] `mind.py`: 302 строки, ровно 32 роута, порядок = порядок в `app.py` (проверено скриптом)
- [x] `router = APIRouter()` без prefix/dependencies, полный путь в декораторе
- [x] Порядок регистрации: `mind.register(app)` после `tasks`, `_register_routers` между CRM и статикой, catch-all последний
- [x] `/api/chat/stream` и `/api/events/stream` **не тронуты**: idx 31 и 30 и до, и после
- [x] `_card_for` НЕ вынесен в `_shared` — локальный `from ..app import _card_for` в `chat`
- [x] Новых моделей в `schemas.py` и новых объектов в `_shared.py` нет
- [x] Сверка маршрутов до/после: **225 = 225**, множества равны, отсортированные списки идентичны, MISSING `[]`, ADDED `[]`
- [x] Фактический FULL-match: 18 кейсов, 0 расхождений; path-traversal-защита `/api/cards/{name}` дословна
- [x] CRM-роутер не тронут, дубликатов `(метод, путь)` — 0 (`test_no_duplicate_method_and_path`)
- [x] `pytest tests -q -p no:cacheprovider` → **598 passed, 2 warnings** (baseline)
- [x] Коммит только своих путей, тег `checkpoint-7-5a`
- [ ] `npm run build` в `web/` — не запускался (по условию задачи); проверить в конце фазы
