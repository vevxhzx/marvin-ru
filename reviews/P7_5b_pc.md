# ФАЗА 7, шаг 7.5b — ПЕРЕНОС ГРУППЫ PC в `core/api/routers/pc.py`

**Статус шага: выполнен.** Перенесено **14 роутов** из `core/api/app.py` в новый модуль
`core/api/routers/pc.py`, поведение API не изменилось: сверка маршрутов **1:1, 225 = 225**
(MISSING `[]`, ADDED `[]`), тесты зелёные (**598 passed, 2 warnings** — ровно baseline).

Ветка `overnight-crm`. Родительский коммит `b769139` (тег `checkpoint-7-5a`), этот шаг — тег
`checkpoint-7-5b`.

> Правило фазы 7: только **механический** перенос. Ни одна строка логики, ни один путь, ни один
> метод, ни один код ответа не менялись. Перенос сделан одноразовым скриптом
> `reviews/_p7_5b_move.py` (якоря по строкам, удалён после переноса): блоки вырезаны из `app.py`
> и склеены в новый файл дословно. Изменения в телах — **только** `@app.` → `@router.` (14 шт.)
> и уровень точек у локальных импортов в телах роутов (`..` → `...` для `core.*`,
> `.auth` → `..auth` для `core.api.auth`). Докстринги и комментарии перенесены слово в слово.

---

## 1. Что перенесено (14 роутов)

| Модуль | Строк | Роутов |
|---|---|---|
| `core/api/routers/pc.py` | 257 | **14** |

| # | Метод | Путь | Было в `app.py` (строка до переноса) |
|---|---|---|---|
| 1 | `POST` | `/api/pc/ping` | 137 |
| 2 | `GET` | `/api/screen` | 167 |
| 3 | `POST` | `/api/pc/ack` | 179 |
| 4 | `GET` | `/api/pc/state` | 187 |
| 5 | `POST` | `/api/pc/launch` | 193 |
| 6 | `GET` | `/api/pc/organize/log` | 203 |
| 7 | `GET` | `/api/pc/organize/preview` | 209 |
| 8 | `POST` | `/api/pc/result` | 215 |
| 9 | `POST` | `/api/pc/clipboard` | 240 |
| 10 | `POST` | `/api/vision/ask` | 260 |
| 11 | `POST` | `/api/cloud/preview` | 277 |
| 12 | `GET` | `/api/voice/voices` | 679 |
| 13 | `GET` | `/api/voice/demo` | 686 |
| 14 | `POST` | `/api/voice/pick` | 716 |

Порядок в модуле = порядок в `app.py` до переноса (проверено скриптом-якорем: все 14 блоков
в исходной последовательности). Состав совпал с заданием 1:1 (8 pc + screen + vision + cloud + 3 voice).

**Константы переехали вместе со своими роутами** (инструкция 7.5a §8, п. 1–2 — выполнено):

* `PC_ORGANIZE_LOG` / `PC_ORGANIZE_PREVIEW` — теперь в `pc.py`, **вместе** с `pc/organize/log`,
  `pc/organize/preview` и `pc/result` (последний пишет их через `global`). Grep до переноса
  подтвердил: после 7.5a их читали/писали **только эти 3 роута** в `app.py`, ни один другой модуль
  и ни один тест их не импортирует. Молчаливой «сломанной записи» нет — общие объекты.
* `VOICES` / `DEMO_TEXT` — переехали **вместе** с 3 голосовыми роутами; grep: других читателей нет.
  `import edge_tts` (локальный, в `voice_demo`) остался локальным — приоритет демо-озвучки сохранён.

### Секурно-острые роуты — дословно, без «улучшений»

| Роут | Что сохранено |
|---|---|
| `POST /api/pc/launch` | `from ..auth import is_local as _is_local` + `if not _is_local(request): 403` — проверка loopback перенесена как есть (уровень точек `.auth` → `..auth` — §6.3 отчёта 7.0) |
| `POST /api/vision/ask` | Фаза 6: `llm.describe_image(..., private=True)`, докстринг про `brain.vision.where = cloud`, тексты ошибок — дословно |
| `POST /api/cloud/preview` | Фаза 6: только чтение, `anonymize`, `will_send`, `personal_tools`, `note` — дословно, ни одной строки логики не тронуто |
| `POST /api/pc/result` | `global PC_ORGANIZE_PREVIEW`, `_json.dumps`-подтверждение, `agent.notify`, `broadcast` — дословно |
| `GET /api/cards/{name}` | Не наш — остался в `mind.py` (7.5a) |

### Регистрация

```python
router = APIRouter()          # БЕЗ prefix, БЕЗ dependencies

def register(app) -> None:
    app.include_router(router)
```

Полный путь остался в декораторе (`@router.post("/api/pc/ping")`). `core/api/routers/__init__.py::register()`:

```python
from . import boards, finance, mind, orders, pc, people, tasks

finance.register(app)
orders.register(app)
boards.register(app)
people.register(app)
tasks.register(app)
mind.register(app)
pc.register(app)      # ← позиция: ПОСЛЕ mind, ДО system (7.6)
```

Порядок вызовов = §2.2 отчёта 7.0 (`finance → orders → boards → people → tasks → mind → pc →
system`). Сам `_register_routers(app)` в `app.py` **не перемещался** — он по-прежнему строго между
`app.include_router(_crm_router)` и `web_dist = …` / `app.mount("/assets")` / catch-all.
Докстринг `routers/__init__.py` обновлён (статус шага 7.5b, 157 перенесённых, ~38 оставшихся).

### Импорты `pc.py` (только нужные)

```python
from __future__ import annotations

import json as _json            # pc_result: "confirm|" + _json.dumps(...)
from datetime import datetime   # screen_report, pc_result

from fastapi import APIRouter, HTTPException, Request

from ...brain import agent      # pc_result, pc_clipboard, vision_ask
from ...services import brain_notes, pc   # clipboard; pc.alive() в /api/screen
from .._shared import broadcast, log      # тот же объект, что и в app.py
from ..schemas import (CloudPreviewIn, PcAck, PcClip, PcLaunch, PcPing, PcResult,
                       VisionIn, VoicePick)
```

* `pc` — модульный импорт: `screen_report` зовёт `pc.alive()` **без** локального импорта
  (внутри остальных роутов локальные `from ...services import pc` — как было, просто точки +1).
* `log` — из `.._shared` (логгер `jarvis.api`, тот же объект, что и `app.log`), дубликата нет.
* Локальные импорты в телах (~18 шт.): `..services` → `...services`, `..brain` → `...brain`,
  `..config` → `...config`, `..voice` → `...voice`, `..pc` (launcher) → `...pc`,
  `.auth` → `..auth`. `File`/`Form`/`UploadFile` в этой группе не используются.
* Модели `PcPing, PcAck, PcLaunch, PcResult, PcClip, VisionIn, CloudPreviewIn, VoicePick` —
  **уже были** в `core/api/schemas.py` (шаг 7.0) — новых моделей не создавал.
* **`_shared.py` и `schemas.py` на этом шаге не менялись** — локального импорта из
  `core.api.app` тоже не потребовалось (хелперы этой группы свои: `PC_ORGANIZE_*`, `VOICES`,
  `DEMO_TEXT` — все переехали в `pc.py`).
* Циклических импортов нет: `pc` импортируется в `register()` в `app.py`, на уровне модуля
  `core.api.routers.pc` не импортирует `core.api.app`.

---

## 2. Что осталось в `core/api/app.py` и почему

`app.py`: 903 → **674** строки (`git diff --numstat`: **+0 / −229** — чистые удаления).

Осталось **38 роутов** из 52 (grep `^\s*@app\.(get|post|put|patch|delete)\(`: было **52** → стало
**38** = ровно −14). Grep по `app.py` не находит ни одного `/api/pc/`, `/api/screen`,
`/api/vision/`, `/api/cloud/preview`, `/api/voice/`, `VOICES`, `DEMO_TEXT`, `PC_ORGANIZE`.

| Что осталось | Роутов | Почему |
|---|---|---|
| `app = FastAPI(...)`, CORS, `AuthMiddleware`, `app.include_router(_crm_router)` | — | инвариант §4.2 п. 2–3, не трогаем |
| `@app.exception_handler(finance.FinanceError)` (`_fin_err`) | — | регистрация не зависит от порядка роутов |
| `_register_routers(app)` | — | точка подключения роутов, инвариант §4.2 п. 1 |
| `GET /api/events/stream` (SSE) | 1 | **НЕ трогали** — задание: оба SSE остаются до 7.6 (idx **30**, не сдвинулся) |
| `POST /api/chat/stream` (POST-SSE) | 1 | то же (idx **31**, не сдвинулся) |
| `/media/{path:path}` | 1 | НЕ переносить (статика, §3 P7_refactor) |
| `/manifest.json`, `/{path:path}` SPA, `/` | 3 | статика и catch-all **последними** |
| Системные (health, dashboard, state, presence, diagnose, ui-prefs, edition, client/info, llm, settings, status, phone, runs, tg, game, google, backup) | 32 | шаг **7.6** (system.py) |

Итого: 2 (SSE) + 1 (`/media`) + 3 (статика/catch-all) + 32 (системные) = **38** — ровно grep-счёт
`app.py`. Полный список system-роутов в `reviews/P7_refactor.md` §3, номера строк уже другие —
ориентироваться на путь. `_card_for`, `broadcast`-реэкспорт, `agent.on_change = broadcast` — **на месте**.

### Неиспользуемые после переноса импорты в `app.py` — НЕ убраны

По §2.3 п. 5 отчёта 7.0 чистка — отдельный шаг после 7.6. Кандидаты (проверять grep'ом перед
чисткой): `File/Form/UploadFile`?, `UploadFile` — проверить (`notes/photo` уехал в mind, но в
`app.py` `File/Form/UploadFile` уже были после 7.5a — значит, остатки от других роутов),
`PcPing/PcAck/PcLaunch/PcResult/PcClip/VisionIn/CloudPreviewIn/VoicePick` — после 7.5b в `app.py`
наверняка не используются, **но не убирать по памяти — только grep'ом и отдельным шагом.**
Также `pc`/`brain_notes`/`pulse` и пр. ещё нужны оставшимся роутам (`/media`, `/api/dashboard`).

---

## 3. Сверка маршрутов ДО / ПОСЛЕ (обязательная проверка)

Скрипт-эталон: **`reviews/_check_routes.py`** (в задании назван `check_routes.py` — в репозитории
файл называется с подчёркиванием).

```bat
cd C:\Users\vevxhzx\Desktop\project\jarvis-main
:: ДО  — на чистом b769139 (рабочее дерево не менялось)
.venv\Scripts\python.exe reviews\_check_routes.py 1> %TEMP%\opencode\before75b_routes.txt
:: ПОСЛЕ
.venv\Scripts\python.exe reviews\_check_routes.py 1> %TEMP%\opencode\after75b_routes.txt
```

```
# top-level entries on app.router.routes: 63  ->  50      (−14 вырезанных app-роутов +1 _IncludedRouter pc)
# flat routes: 225 -> 225
Compare-Object before after  →  0 строк различия   ⇒  множества (path, method) идентичны:
MISSING (было, нет): []   ADDED (стало, нет): []
```

**225 = 225, множества совпали полностью.**

### Фактический порядок/индексы (проверено на реальном `app.router.routes`)

```
flat total: 225
SSE /api/events/stream = 30   (не сдвинулся, как на 7.4/7.5a)
POST /api/chat/stream  = 31   (не сдвинулся)
pc/ping = 209, screen = 210, vision/ask = 218, cloud/preview = 219, voice/pick = 222
/media = 37, /manifest.json = 65, catch-all /{path:path} = 224 (последний)
```

`test_events_stream_registered_before_event_id_and_catchall` и
`test_registered_before_spa_catchall` — зелёные (входят в 598).

### Живой смоук (TestClient, base_url=http://localhost)

```
GET  /api/screen                -> 200   GET /api/pc/state            -> 200
GET  /api/pc/organize/log       -> 200 [] GET /api/pc/organize/preview -> 200 {'status': 'empty'}
GET  /api/voice/voices          -> 200   POST /api/pc/ping            -> 200 {'ok': True, 'screen': True}
POST /api/pc/ack                -> 200   GET  /manifest.json          -> 200
GET  /api/health                -> 200
```

Все 14 путей матчатся, ответы и коды как раньше.

---

## 4. Тесты

```
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
→ 598 passed, 2 warnings in 135.45s
```

Ровно baseline **598 passed** (столько же было на 7.5a), предупреждения — только 2 известных
baseline (`StarletteDeprecationWarning` httpx, `anyio BlockingPortal`). Скелет
`tests/test_p7_routers_registration.py` на этом шаге НЕ менялся. Откат не потребовался.

⚠️ В дереве работают параллельные агенты — в мой коммит входят **только** свои пути:
`core/api/app.py`, `core/api/routers/pc.py`, `core/api/routers/__init__.py`, `reviews/P7_5b_pc.md`.
`PROGRESS.md`, `README.md`, `web/**`, `core/brain/**`, чужие тесты — не трогал и не коммитил.

---

## 5. Инструкции для 7.6 (`system.py` — последний шаг)

1. **Увезти в `system.py` оба SSE**: `GET /api/events/stream` (app.py:62) и
   `POST /api/chat/stream` (app.py:102) — и обязательно проверить, что SSE регистрируются
   **раньше** параметрических путей (`test_events_stream_registered_before_event_id_and_catchall`
   и `test_events_stream_before...` специально упадут, если порядок сломан). Сейчас их индексы
   **30** и **31** — после переноса в `system.py` (последним модулем) индексы изменятся, поэтому
   сверку порядка делать явно: `stream` раньше `/api/events/{event_id}`.
2. **`system.py` подключается последним** в `routers/__init__.py::register()` — **ПОСЛЕ `pc`**;
   `register()` в `app.py` остаётся ПОСЛЕ CRM и ДО `web_dist` / `app.mount("/assets")` /
   catch-all `/{path:path}` (иначе catch-all съест все GET /api/*).
3. **Не трогать** (ушло в другие модули): `mind.py` — notes/links/facts/lessons/memory/graph/
   search/cards/chat POST/undo/chat history; `pc.py` (шаг 7.5b) — `/api/pc/*`, `/api/screen`,
   `/api/vision/ask`, `/api/cloud/preview`, `/api/voice/*`; плюс finance/orders/boards/people/tasks.
4. **Статика НЕ переносить**: `/media/{path:path}`, `/manifest.json`, `/{path:path}`, `/` —
   остаются в `app.py` последними (либо, если задание 7.6 велит увезти в `system.py` — только с
   гарантией, что `system.register(app)` идёт последним и catch-all завершает список; safer —
   оставить в `app.py`).
5. **`_card_for`** → вынести в `_shared.py` с реэкспортом из `app.py` и удалить локальный
   `from ..app import _card_for` в `mind.py::chat` (сделан на 7.5a, §4 того отчёта).
6. **`_gcal_reload`, `_voice_status`, `_edition_payload`** — в `system.py` вместе со своими роутами.
7. Скелет `tests/test_p7_routers_registration.py`: добавить `MIND_ROUTES` (32) и `PC_ROUTES` (14)
   отдельным коммитом (можно на 7.6, но не смешивать с переносом).
8. После 7.6: `check_routes.py` → снова **225 = 225**; pytest → **598 passed**;
   `git diff` по `app.py` — только удаления/перемещения; чистка неиспользуемых импортов —
   **отдельным последним коммитом** (grep, не по памяти).

---

## 6. Контрольный чек-лист шага 7.5b

- [x] 14 роутов перенесены дословно, `git diff --numstat core/api/app.py` = **+0 / −229**
- [x] `app.py`: 903 → 674 строк; роутов в `app.py` 52 → 38 (ровно −14)
- [x] `pc.py`: 257 строк, ровно 14 роутов, порядок = порядок в `app.py` (проверено скриптом)
- [x] `PC_ORGANIZE_*`, `VOICES`, `DEMO_TEXT` переехали вместе со своими роутами (grep: других читателей нет)
- [x] `router = APIRouter()` без prefix/dependencies, полный путь в декораторе
- [x] Порядок регистрации: `pc.register(app)` после `mind`, `_register_routers` между CRM и статикой, catch-all последний
- [x] Оба SSE (`/api/events/stream` idx 30, `/api/chat/stream` idx 31) **не тронуты**
- [x] `/media`, `/manifest.json`, SPA catch-all — не переносились
- [x] Секур-роуты (`pc/launch` is_local, `vision/ask`, `cloud/preview`) — дословно, тесты фазы 6 зелёные
- [x] Новых моделей в `schemas.py` и новых объектов в `_shared.py` нет; локальных импортов из `core.api.app` не потребовалось
- [x] Сверка маршрутов до/после: **225 = 225**, Compare-Object 0 различий, MISSING `[]`, ADDED `[]`
- [x] `pytest tests -q -p no:cacheprovider` → **598 passed, 2 warnings** (baseline)
- [x] Коммит только своих путей, тег `checkpoint-7-5b`
- [ ] `npm run build` в `web/` — не запускался (по условию задачи; `web/**` не трогал) — проверить в конце фазы
