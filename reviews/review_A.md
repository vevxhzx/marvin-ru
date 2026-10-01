# Ревью A — «API и безопасность»

Область: `core/api/app.py` + `core/api/routers/*.py` (разбиение после шага 7.0),
`core/api/auth.py`, `core/api/schemas.py`. Эталон сверки — `git show 643132d:core/api/app.py`.

Тесты: `tests/test_review_a_access.py`, `tests/test_review_a_contract.py`
(только временная БД через `fresh_db`, конфиг подменяется через `JARVIS_CONFIG`).

## Находки

| Приор. | Место | Что не так | Как проявляется | Предложение |
|---|---|---|---|---|
| **P0** | `core/api/app.py:203-205` (`spa()`) | Catch-all `f = web_dist / path; if path and f.is_file(): FileResponse(f)` — путь не нормализуется и не проверяется `resolve()` | Сырой `GET /../../config.example.yaml` (curl `--path-as-is`; uvicorn делает только `unquote`, `..` не схлопывает — `httptools_impl.py:256-264`) → `web/site/../../config.example.yaml` → **200 с содержимым файла корня репозитория**. Путь не начинается на `/api/` → `auth.py:176` считает его публичным, ключ не нужен (проверено снаружи, `192.168.1.50`). То же и для `/../../data/api_token`. Это **не регрессия фазы 7** — так было и в `app.py` до разбиения | Перед отдачей: `f = (web_dist / path).resolve()` + `assert f.is_file() and str(f).startswith(str(web_dist.resolve()))` — как уже сделано в `media()` (`app.py:143-145`). Плюс закрыть `..` на входе в middleware |
| **P1** | `core/api/schemas.py:280` (`PaymentIn`) | У схемы платежа нет `idem_key`, хотя `transaction.idem_key` есть в БД (`core/db.py:131`) и сервис его читает (`core/services/orders.py:215`) | `POST /api/orders/{id}/payments` дважды с одинаковым телом → **два дохода**. Соседний `core/crm/router.py:39` поле принимает — паритет нарушен | Добавить `idem_key: str \| None = None` в `PaymentIn` и прокинуть в `service.payment(...)` |
| **P1** | `core/api/routers/mind.py:215` vs `:256` | `PUT /api/facts/{fid}` зарегистрирован раньше литерала `PUT /api/facts/style` → перекрывает его | `web/src/lib/api.js:189` (`setStyle`) получает **422** (`fid="style"` не проходит валидацию `int`). Регистрация `POST /api/facts/style` (`:249`) цела — баг только у PUT. Противоречит `reviews/P7_5a_mind.md:71` vs `:332` | Перенести оба литерала `style` **выше** `/{fid}` в том же роутере (порядок регистрации решает и там, и там) |
| **P2** | `core/api/routers/finance.py:168,185,222,258,281` | `PUT` несуществующей сущности падает в `FinanceError` → 400, а `DELETE` того же ресурса — 404 | 5 путей: `transactions/999`, `categories/999`, `accounts/999`, `debts/999`, `recurring/999` → 400. Клиент не отличает «нет такого» от ошибки валидации | В обработчике `finance.FinanceError` (`app.py:135-137`) различать «не найдено» (404) и валидацию (400) — например, отдельный `NotFoundError` |
| **P2** | `core/api/routers/finance.py:253` | `GET /api/finance/debts/{debt_id}/payments` не проверяет существование долга | Несуществующий долг → **200 []** вместо 404 (для `DELETE .../debts/999` тест ожидает 404 и он проходит) | Проверять долг до чтения платежей |
| **P2** | `core/api/app.py:193-206` (catch-all) + `auth.py:176` | Неизвестный `GET /api/*` не отдаёт 404: роуты не матчатся, ловит SPA catch-all | `GET /api/nonexistent` → **200 с HTML** вместо 404. Клиент по коду 200 решает, что запрос прошёл | Catch-all не должен отвечать на `path.startswith("api")` → `JSONResponse(404, {"detail": "Not Found"})` (тот же приём уже применён для `/assets/...` → 404) |
| **P2** | `core/api/routers/boards.py:58` | `GET /api/boards/for-order/{oid}?create=true` создаёт доску | GET с побочным эффектом: предпросмотр ссылки/прокси/кэш создают мусорную доску | `create` перенести в `POST` (или ограничить `create=false` на GET) |
| **P3** | `core/api/routers/orders.py` (`GET /api/orders/freelance`) | Чтение пишет настройку `freelance` / `pulse.auto_enable_if_used` | GET мутирует БД; повторный заход меняет состояние | Вынести запись в отдельный POST или писать лениво при первом изменении |
| **P3** | `core/api/routers/system.py` (`GET /api/diagnose`) | Диагностика пишет `health.last_ok/at` и порождает событие | GET мутирует состояние; кэш/повторный GET — разная история в БД | Писать результат только при фоновом прогоне, не в GET |

## Что проверено и как

**1. Паритет разбиения (регрессия фазы 7).** Сняты все пары `(method, path)` и имена функций
из `git show 643132d:core/api/app.py` и из текущего `app.py + routers/*.py` (собрано скриптом
обхода модулей): **195 = 195**, множества идентичны; с `crm` — 225 = 195 + 30.
Копипасты `@router.post` вместо `@router.get` при переносе **не найдены**.
Замороженные таблицы методов для mind/pc/system — в `MIND_ROUTES` / `PC_ROUTES` / `SYSTEM_ROUTES`
(`test_review_a_contract.py`), сверка поэлементно; finance/orders/boards/people/tasks покрыты
существующим `tests/test_p7_routers_registration.py`. Плюс отдельные тесты: SSE `/api/events/stream`
остался в `app.py`, литерал `stream` зарегистрирован раньше `/api/events/{event_id}`, дубликатов
`(method, path)` в приложении нет.

**2. Доступ (`access`).** Через `TestClient(app, client=("192.168.1.50", …))` (чужой хост)
прогнаны таблицы: 24 чувствительных GET → **401**, 12 меняющих POST/PUT → **401**;
4 маршрута «только с этого компьютера» (`/api/phone`, `/api/phone/rotate`, `/api/setup/state`, `/setup`)
→ **403 даже с валидным ключом**; публично без ключа только `/api/health` и `manifest.json`
(`/api/tasks`, `/media/x.png` снаружи закрыты). Loopback (`127.0.0.1`) без ключа работает.

**3. Секреты в ответах.** Во временный `tmp_path/config.yaml` записаны заведомые значения
(`telegram.token`, `google.client_secret`, `brain.cloud.api_key`, `brain.gemini.api_key`);
настоящий `config.yaml` не открывался. Проверено, что ни одно значение целиком не попадает в
`GET /api/settings` (там маска `xxxx…yyy`), `/api/status`, `/api/llm`, `/api/diagnose`,
`/api/export/transactions.json`; отправка маски обратно (`PUT /api/settings`) не стирает ключ.

**4. Обходы каталога.** `TestClient`/httpx нормализует `..` в URL, поэтому traversal проверен
**прямыми ASGI-вызовами** с сырым `scope["path"]` (`_raw_get()` в `test_review_a_access.py`) —
ровно так, как его формирует uvicorn (декодирование `%2f`, без нормализации dot-сегментов).
Итог: `/media/../…` и `/media/../../…` → **404** (обработчик `app.py:143-145` резолвит и проверяет
`MEDIA_DIR` — эталон защиты, снаружи ещё и 401); `/api/cards/../../…`, `..%2f…`, `%2e%2e%2f…` →
файл не отдаётся (404 от роута либо index.html как SPA fallback). Уязвим **только** catch-all:
`/../../config.example.yaml` → 200 с содержимым (P0).

**5. Коды ответов.** 30 несуществующих ресурсов → 404; 11 кривых тел → 422;
невалидный JSON → 422; пустое имя → 400 по контракту; неизвестный `GET /api/*` → 200 HTML (P2).

**6. Идемпотентность и побочные эффекты GET.** Служебный `core/crm/router.py` с `idem_key`
повторяет платеж один раз (тест проходит) — в отличие от `/api/orders/{id}/payments` (P1).
Обычные чтения (tasks/events/notes) состояние не меняют — контрольный тест проходит;
нарушения — P2 (`boards?create=true`) и P3 (freelance, diagnose).

**7. Что не проверялось.** Нагрузка, реальный сетевой доступ через uvicorn, TLS/прокси,
e2e/фронт (`npm` не запускался), полный `pytest tests`.

## Итог

```
100 passed, 13 xfailed, 0 failed  (2 warnings)   .venv\Scripts\python.exe -m pytest tests/test_review_a_*.py -q
```

- **P0 — 1**: обход каталога в SPA catch-all без ключа (`core/api/app.py:203`).
- **P1 — 2**: нет `idem_key` у платежа (`schemas.py:280`), перекрытие `PUT /api/facts/style` (`routers/mind.py:215`).
- **P2 — 4**, **P3 — 2**.
- Все находки оформлены `@pytest.mark.xfail(strict=False)` → сейчас дают `xfail`,
  после исправления станут `xpass` и подтвердят закрытие. Упавших тестов нет.
