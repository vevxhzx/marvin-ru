# ФАЗА 7, шаг 7.6 — ФИНАЛЬНЫЙ: перенос 32 системных роутов в `core/api/routers/system.py`

**Статус шага: выполнен.** Перенесено **32 системных роута** из `core/api/app.py` в новый модуль
`core/api/routers/system.py`, поведение API не изменилось: сверка маршрутов **1:1, 225 = 225**
(MISSING `[]`, ADDED `[]`, вывод чекера **байт-в-байт идентичен** до/после), тесты зелёные
(**598 passed, 2 warnings** — ровно baseline), эмпирические проверки SSE и статики — зелёные (§4).

Ветка `overnight-crm`. Родительский коммит `6f93e03` (тег `checkpoint-7-5b`), этот шаг — тег
**`checkpoint-7`** (конец фазы).

> Правило фазы 7: только **механический** перенос. Перенос сделан одноразовым скриптом
> `reviews/_p7_6_move.py` (якоря по строкам, **удалён** после переноса): блоки вырезаны из `app.py`
> и склеены в новый файл дословно. Изменения в телах — **только** `@app.` → `@router.` (32 шт.),
> +1 точка у относительных импортов в телах функций (`..brain` → `...brain`, `.auth` → `..auth` —
> `routers/` лежит на уровень глубже `core/api/`) и **одна** добавленная строка
> `from ..app import app` внутри `status()` (там используется `app.state`, объекта `app` в модуле
> нет — локальный импорт из `core.api.app`, как и предписывалось заданием).
> `git diff --numstat core/api/app.py` = **+5 / −467** (−463 — вырезанные роуты, +5/−4 —
> обновлённый 4-строчный комментарий про SSE, см. §2).

---

## 1. Что перенесено (32 роута → `core/api/routers/system.py`, 506 строк)

| # | Метод | Путь |
|---|---|---|
| 1 | `GET` | `/api/health` |
| 2 | `GET` | `/api/dashboard` |
| 3 | `GET` | `/api/state` |
| 4 | `GET` | `/api/presence/events` |
| 5 | `GET` | `/api/diagnose` |
| 6 | `GET` | `/api/ui-prefs` |
| 7 | `PUT` | `/api/ui-prefs` |
| 8 | `GET` | `/api/edition` |
| 9 | `POST` | `/api/edition` |
| 10 | `GET` | `/api/client/info` |
| 11 | `GET` | `/api/llm` |
| 12 | `GET` | `/api/settings` |
| 13 | `PUT` | `/api/settings` |
| 14 | `GET` | `/api/status` |
| 15 | `GET` | `/api/phone` |
| 16 | `GET` | `/api/runs` |
| 17 | `GET` | `/api/runs/report` |
| 18 | `POST` | `/api/phone/rotate` |
| 19 | `POST` | `/api/tg/login` |
| 20 | `POST` | `/api/tg/logout` |
| 21 | `GET` | `/api/tg/miniapp` |
| 22 | `POST` | `/api/game` |
| 23 | `POST` | `/api/status/small` |
| 24 | `POST` | `/api/status/gemini` |
| 25 | `GET` | `/api/google/status` |
| 26 | `GET` | `/api/google/connect` |
| 27 | `GET` | `/api/google/callback` |
| 28 | `POST` | `/api/google/sync` |
| 29 | `POST` | `/api/google/disconnect` |
| 30 | `POST` | `/api/backup` |
| 31 | `GET` | `/api/backups` |
| 32 | `POST` | `/api/backups/restore` |

Порядок в модуле = порядок в `app.py` до переноса (скрипт-якорь вырезал два непрерывных
блока: строки 134–203 и 219–611 старого `app.py`). Состав совпал с заданием 1:1
(плюс 3 хелпера, уехавшие **вместя со своими роутами**, §1.1).

### 1.1 Хелперы переехали вместе с роутами (инструкция 7.5a §8)

* `_edition_payload` — только `/api/edition` GET/POST → уехал в `system.py`.
* `_voice_status` — только `/api/status` → уехал.
* `_gcal_reload` — `/api/settings` PUT + все `/api/google/*` (7 роутов) — **все в `system.py`**,
  grep до/посли подтвердил: других читателей в `app.py` не осталось.
* `_card_for` — **остался в `app.py`** (нужен `chat_stream`, который остаётся; в `mind.py` —
  локальный импорт из `core.api.app`, как было со 7.5a). В `_shared.py` НЕ выносился —
  задание запрещает плодить изменения в `_shared` на финальном шаге.

### 1.2 Секурно-острые роуты — дословно, без «улучшений»

| Роут | Что сохранено |
|---|---|
| `POST /api/phone/rotate` | `from ..auth import rotate, is_local as _is_lb` + `if not _is_lb(request): 403` — дословно (уровень точек `.auth` → `..auth`) |
| `GET /api/phone` | `from ..auth import token as _tok, is_local as _is_lb`, `if not _is_lb(request): 403`, QR/`segno`, tail-токен — дословно |
| `POST /api/backups/restore` | `restore_backup`, ветки `LookupError→404`, `ValueError→400` — дословно |
| `GET/PUT /api/settings` | 5 локальных импортов, `write_settings`, `_gcal_reload()`, `persona.reload_persona()`, `broadcast("settings", …)`, `needs_restart` — дословно |
| `POST /api/tg/login` | HMAC-проверка `tg_auth.login`, cookie `SameSite=None+Secure` — дословно |
| `GET /api/google/callback` | `response_class=HTMLResponse`, state-куки, редиректы, `create_task(gcal.sync_all())` — дословно |
| `GET /api/status` | Единственная сознательная вставка: `from ..app import app  # нужен для app.state` — тела строк не менялись, `getattr(app.state, …)` работает с тем же объектом |

### 1.3 Регистрация

```python
router = APIRouter()          # БЕЗ prefix

def register(app) -> None:
    app.include_router(router)
```

`core/api/routers/__init__.py::register()`: finance → orders → boards → people → tasks → mind → pc →
**system (последним)**. `_register_routers(app)` в `app.py` **не перемещался** — по-прежнему строго
между CRM и блоком статики.

### 1.4 Импорты `system.py` (только нужные)

`asyncio as _asyncio` (to_thread/get_running_loop), `json as _json` (ui-prefs), `datetime/timedelta`,
`Optional`, `APIRouter/HTTPException/Request`, `HTMLResponse/JSONResponse` (google-callback, tg),
`...db`: session/Event/Task/Note/Link/Transaction/get_setting/set_setting,
`...services`: brain_notes/calendar/finance/goals/insights/orders/pc/pulse/screen/tasks,
`...services.scheduler.morning_digest_text`, `.._shared`: `_ev_out/broadcast`,
`..schemas`: UiPrefsIn/EditionIn/SettingsIn/TgLogin/GameBody/BackupRestoreIn.
Циклических импортов нет: на уровне модуля `system.py` не импортирует `core.api.app`
(единственный импорт `..app` — локальный, внутри `status()`, в момент запроса).

---

## 2. Что осталось в `core/api/app.py` — 212 строк, **6 роутов**

`app.py`: 674 → **212** строки.

| Что осталось | Строки (новый `app.py`) | Роутов | Почему |
|---|---|---|---|
| `app = FastAPI(...)`, CORS, `AuthMiddleware`, `include_router(_crm_router)` | 34–44 | — | инварианты §4.2 п. 2–3 P7_refactor |
| `GET /api/events/stream` (SSE) | **60** | 1 | **См. §4 — решение по SSE** |
| `POST /api/chat/stream` (POST-SSE) | **100** | 1 | то же |
| `_card_for` (хелпер chat) | 87 | — | нужен `chat_stream`; локальный импорт из `mind.py` |
| `@app.exception_handler(finance.FinanceError)` | 135 | — | регистрация не зависит от порядка роутов |
| `GET /media/{path:path}` | 140 | 1 | статика — НЕ переносить (§3 задания) |
| `GET /manifest.json` | 149 | 1 | статика |
| `GET /{path:path}` (SPA catch-all) | 193 | 1 | **последним** |
| `GET /` (preview/index) | 210 | 1 | статика |
| `_register_routers(app)` | 181 | — | между CRM (44) и статикой (184+) — **порядок сохранён** |

**Фактический порядок в `app.py` (проверен):** CRM (44) → SSE (60) → chat/stream (100) →
исключение-хендлер (135) → media (140) → manifest (149) → **`_register_routers(app)` (181)** →
`web_dist` (185) + `app.mount("/assets")` (191) → catch-all (193) → `/` (210).
`system.register(app)` выполняется **внутри** `_register_routers` (181), т.е. ДО блока статики —
как и требует инвариант §4.2 п. 1. Catch-all — последний роут.

Комментарий 174–178 в `app.py` обновлён (4 → 5 строк): теперь он фиксирует решение 7.6 —
SSE остаются в `app.py` **постоянно**, переносить их в `system.py` нельзя.

### Неиспользуемые импорты в `app.py` — НЕ удалялись (правило задания D)

Остались как были: `File/Form/UploadFile`, `BaseModel/Field/field_validator`, `select`,
`Debt/Recurring/Aim/Milestone`, `calendar/goals/insights/orders/pulse/people/relations/tasks/screen`
(частично используются оставшимися кодом, частично нет), `redirect` и т.п. Чистка — отдельным
последним шагом по grep (`§2.3 п.5` P7_refactor), в рамках 7.6 не трогались.

---

## 3. Решение по SSE (ЗАДАЧА B) — оба SSE ОСТАЛИСЬ в `core/api/app.py`

**Принято предпочтительное (п. 1) и самое безопасное решение:** `GET /api/events/stream`
(`app.py:60`) и `POST /api/chat/stream` (`app.py:100`) **не переносились**.

**Почему (порядок регистрации):** `system.register(app)` вызывается **ПОСЛЕ** `tasks.register(app)`,
а в `tasks.py` живёт параметрический `GET /api/events/{event_id}`. Если бы `/api/events/stream`
уехал в `system.py`, литерал `stream` зарегистрировался бы **после** `{event_id}` → Starlette
выбрал бы первое совпадение (`{event_id}`) → Pydantic не собрал бы int из `"stream"` → **422
вместо живого SSE** для сайта и `voice.bat`. Оба SSE стоят в `app.py` **выше**
`_register_routers(app)` (строки 60/100 против 181), т.е. литерал гарантированно выигрывает
и у `{event_id}`, и у catch-all. Альтернатива (п. 2: отдельный `sse.py`, подключаемый ПЕРЫМ
до finance) — отклонена как более рискованная без выигрыша. **В `system.py` SSE НЕТ** (п. 3) —
grep подтверждает: ни `/api/events/stream`, ни `/api/chat/stream` в модуле нет.

Зафиксировано в комментарии `app.py:174-178` и докстринге `routers/__init__.py` (инвариант 2).

### Эмпирическая проверка SSE (`reviews/_check_7_6.py`, запуск из корня)

```
OK   GET /api/events/stream -> 200 content-type='text/event-stream; charset=utf-8'
OK   routing GET /api/events/stream -> ['/api/events/stream', '/{path:path}']   (первый FULL-match — сам)
OK   POST /api/chat/stream -> status=200 matched=['/api/chat/stream']
OK   GET / -> 200 content-type='text/html; charset=utf-8' len=1287
OK   GET /manifest.json -> 200 content-type='application/json'
OK   GET /api/health -> 200
OK   GET /api/ui-prefs -> 200
OK   GET /api/edition -> 200
ALL OK
```

Методика: для бесконечного SSE использован прямой ASGI-probe (ловим только
`http.response.start`, тело не читаем — TestClient буферизует бесконечный поток и «вечность»);
**статус 200, НЕ 422/404**, content-type `text/event-stream`. `POST /api/chat/stream` —
живой POST с валидным телом → **200** (не 404/405/422).

---

## 4. Результаты ВСЕХ проверок

### 4.1 Сверка маршрутов ДО/ПОСЛЕ — `reviews/_check_routes.py` (канонический)

```bat
:: ДО  (на чистом 6f93e03)                    :: ПОСЛЕ
# top-level entries on app.router.routes: 50  # top-level entries on app.router.routes: 19
# flat routes: 225                             # flat routes: 225
Get-FileHash before76 = Get-FileHash after76  :: 1354 строк каждый, Compare-Object = 0 различий
```

**225 = 225, выводы байт-в-байт идентичны: MISSING `[]`, ADDED `[]`.** Top-level 50 → 19
(−32 вырезанных app-роутов +1 `_IncludedRouter system`).

Фактические индексы плоского списка (проверено):
```
flat: 225
sse = 30   event_id = 132   chat/stream = 31   media = 32   manifest = 33
health (system, первый) = 191   catch-all = 224 (последний)
order ok: sse(30) < event_id(132) < catch-all(224)  → True
```
Индексы SSE **не сдвинулись** (30/31 — как на 7.4/7.5a/7.5b).

### 4.2 Эмпирическая проверка SSE + статика — §3 выше, все OK (200, event-stream, HTML, JSON)

Дополнительно вживую (TestClient, base_url=localhost): `GET /api/status → 200` (проверяет
`from ..app import app` + `app.state`), `/api/settings` GET → 200, `/api/runs` → 200,
`/api/presence/events` → 200, `/api/google/status` → 200, `/api/backups` → 200.

### 4.3 Тесты

```
.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider
→ 598 passed, 2 warnings in 141.07s
```

Ровно baseline **598 passed**, предупреждения — только 2 известных baseline
(`StarletteDeprecationWarning` httpx, `anyio BlockingPortal`). Зелёные:
`test_p7_routers_registration` (все 5 доменов + обновлённый `DOMAINS`),
`test_events_stream_still_in_app`, `test_events_stream_registered_before_event_id_and_catchall`,
`test_registered_before_spa_catchall`, `test_no_duplicate_method_and_path`,
тесты фазы 6 (секурные роуты). **Откат не потребовался** (ни одной попытки починки).

### 4.4 Единственное изменение в чужом тесте

`tests/test_p7_routers_registration.py`: в кортеж `DOMAINS` добавлен **`("system", "/api/health")`**
(префикс уникален, роутер реально подключён) — задание прямо это предписывало. Больше тест не менялся.

---

## 5. Инварианты — соблюдал ли порядок

| Инвариант | Статус |
|---|---|
| `_register_routers(app)` ПОСЛЕ CRM и ДО статики/catch-all | ✅ (CRM 44 → routers 180 → mount 190 → catch-all 192) |
| Статика (`/assets`, `/media`, `/manifest.json`, `/`, catch-all) — в `app.py`, НЕ переносилась | ✅ (задание C) |
| Catch-all — последний роут (idx 224 из 224) | ✅ |
| Порядок модулей `finance→orders→boards→people→tasks→mind→pc→system` | ✅ (system последним) |
| SSE раньше параметрического `/api/events/{event_id}` и catch-all | ✅ (idx 30 < 132 < 224; оба SSE в `app.py`, не тронуты) |
| Middleware/CORS/lifespan/exception handler — в `app.py` | ✅ (не трогали) |
| `include_router(_crm_router)` — не трогали | ✅ |
| `router = APIRouter()` без prefix, полные пути в декораторах | ✅ |
| Публичный API идентичен (пути/методы/поля/коды) | ✅ (225=225 байт-в-байт, 598 passed) |
| `_shared.py` / `schemas.py` НЕ менялись | ✅ (новых моделей/объектов нет, локального импорта из `core.api.app` хватило) |
| Логика/тела функций дословно | ✅ (скриптовый перенос; изменения только `@app.`→`@router.`, +1 точка в импортах, +1 строка-импорт в `status()`) |

---

## 6. Коммит и чек-лист

Коммит (только свои пути, без `git add -A`):
`core/api/app.py core/api/routers/system.py core/api/routers/__init__.py tests/test_p7_routers_registration.py reviews/P7_6_system.md reviews/_check_7_6.py`
→ тег **`checkpoint-7`**.

Не коммитилось (чужое/запрещённое): `core/brain/**`, `tests/test_golden_quick.py`,
`reviews/review_C.md`, `PROGRESS.md`, `README.md`, `REVIEW.md`, `web/**`.

- [x] 32 роута перенесены дословно; `system.py` = 506 строк, ровно 32 `@router.`
- [x] `app.py` 674 → **212** строк; осталось 6 роутов (2 SSE + media + manifest + catch-all + /)
- [x] Хелперы `_edition_payload`/`_voice_status`/`_gcal_reload` уехали со своими роутами
- [x] Оба SSE **не тронуты**, idx 30/31 не сдвинулись; в `system.py` их нет
- [x] Сверка: **225 = 225**, выводы байт-в-байт идентичны, MISSING `[]`, ADDED `[]`
- [x] Эмпирика SSE: `GET /api/events/stream → 200 text/event-stream` (НЕ 422/404),
      `POST /api/chat/stream → 200`
- [x] Смоук статики: `GET / → 200 HTML`, `GET /manifest.json → 200 JSON`
- [x] `pytest tests -q -p no:cacheprovider` → **598 passed, 2 warnings** (baseline)
- [x] Секур-роуты (phone/rotate, phone, backups/restore, settings, tg/login, google/callback) — дословно
- [x] Неиспользуемые импорты в `app.py` НЕ удалялись (задание D)
- [x] Одноразовый `reviews/_p7_6_move.py` удалён; чекер `reviews/_check_7_6.py` оставлен
- [ ] `npm run build` в `web/` — не запускался (`web/**` не трогал) — сделать в конце фазы/финале
