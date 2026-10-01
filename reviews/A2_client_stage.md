# A2 — Стадия КЛИЕНТА (backend)

ЧАСТЬ 1Б, пункт 1. Ветка `overnight-crm`. Новый модуль `core/crm/client_stages.py`,
миграция схемы **v3**, эндпоинты в `core/crm/router.py`, тесты `tests/test_review_client_stage.py`.
Воронка заказов (`core/crm/stages.py`, 9 стадий) **не тронута** — это вторая, независимая сущность.

## 1. Стадии клиента

| ключ | подпись | когда (авто) |
|---|---|---|
| `lead` | лид | по умолчанию (заказов/оплат нет) |
| `negotiation` | переговоры | вручную (авто-сигнала нет) |
| `client` | клиент | ≥1 оплаченный заказ |
| `permanent` | постоянный | ≥2 оплаченных заказа |
| `asleep` | спит/ушёл | нет активности ≥ 90 дней |

## 2. Авто-логика — чистая функция `client_stages.auto_stage(paid_orders, last_activity, now_dt=None, sleep_days=90)`

```python
if paid_orders >= 2: return "permanent"
if paid_orders >= 1: return "client"
if last_activity and (now - last_activity).days >= 90: return "asleep"
return None            # авто-сигнала нет → текущее значение НЕ перетирается
```

* Порядок приоритетов: **постоянный → клиент → спит/ушёл → нет сигнала** (по ТЗ).
  Оплата важнее «спит»: клиент с 2 оплаченными заказами остаётся «постоянным», даже если заказов давно нет.
* «Оплаченный заказ» = `status == "paid"` **или** `paid_at` заполнен **или** оплачена вся сумма заказа
  (по `Transaction` с `order_id`, `kind="income"`, с допуском 0.5 ₽ — как в `orders.add_payment`).
* «Последняя активность» = максимум из: `order.paid_at/done_at/last_contact_at/created_at/deadline`
  и `client.last_contact_at` (иначе `client.created_at`). Граница 90 дней включается: ровно 90 → «спит».
* Константы: `PERMANENT_PAID_ORDERS = 2`, `SLEEP_DAYS = 90` (верх модуля, легко поменять).

## 3. Ручное значение приоритетнее

* `PUT .../stage` пишет `client.stage` **и** `client.stage_manual = True` → авто-логика `stage` больше
  не перетирает (на `recalc` обновляется только `stage_auto`, в ответе `note = "ручная стадия — авто не перетирает"`).
* `DELETE .../stage/manual` снимает ручной режим и сразу пересчитывает по заказам («вернуть авто»).
* Нюанс: если авто-сигнала нет (нет оплат, всё свежее), после снятия ручного режима значение
  сохраняется (правило «не переопределять текущее значение») — `note = "авто-сигнала нет, значение сохранено"`.
  Чтобы задать конкретную стадию — снова `PUT` (он снова включит ручной режим).

## 4. Схема БД (миграция v3, только аддитивно и идемпотентно)

`core/migrations.py::_v3_client_stage` → `client.stage VARCHAR DEFAULT ''` (`ix_client_stage`),
`client.stage_manual BOOLEAN DEFAULT 0`, `client.stage_auto VARCHAR DEFAULT ''`, `client.stage_updated_at DATETIME`.
Новых таблиц нет (лента событий — уже существующая `crmactivity`). Нет `DROP`/переименований, авто-бэкап
(встроенный, `backups/pre-migration-*.db`) не тронут, версия в `schema_version` → 3.
Записи, созданные до миграции, читаются через авто-логику (`stage` пуст) — обратная совместимость.

## 5. API (префикс `/api/crm`, все пути новые; существующие не переименованы)

| метод | путь | назначение |
|---|---|---|
| GET | `/api/crm/client-stages` | справочник стадий + пороги |
| GET | `/api/crm/clients/{cid}/stage` | прочитать стадию (read-only, БД не меняет) |
| PUT | `/api/crm/clients/{cid}/stage` | поставить стадию **вручную** (тело `{"stage": "client"}`) |
| DELETE | `/api/crm/clients/{cid}/stage/manual` | снять ручной режим («вернуть авто») |
| POST | `/api/crm/clients/{cid}/stage/recalc` | пересчитать авто по заказам одного клиента |
| POST | `/api/crm/client-stages/recalc` | пересчитать авто по всем клиентам |

Ошибки: неизвестная стадия → **400**, неизвестный клиент → **404**.

### Ответ (единый формат для всех эндпоинтов стадии)

```jsonc
{
  "client_id": 12, "name": "Пятёрочка",
  "stage": "client",          // эффективная стадия (то, что показываем)
  "label": "клиент",
  "manual": false,            // ручной режим (в БД client.stage_manual)
  "stage_manual": false,      // синоним manual
  "auto": "client",           // последний авто-сигнал; "" — сигнала нет
  "auto_label": "клиент",
  "stored": "client",         // что реально лежит в client.stage
  "changed": false,           // в GET: stored != stage; в recalc: значение в БД изменилось
  "updated_at": "2026-10-01T03:20:00",   // когда меняли стадию
  "paid_orders": 2, "orders_count": 3, "paid_total": 55000,
  "last_activity": "2026-09-28T12:00:00", "days_since": 3
}
```

`PUT` дополнительно: `before` (стадия до ручной установки). `DELETE .../manual` и `.../recalc` дополнительно:
`was_manual`, `before`, `note` (`"ручная стадия — авто не перетирает"` / `"авто-сигнала нет, значение сохранено"` /
`"пересчитано по заказам"` / `"выставлено вручную, авто не перетирает"`).

`GET /api/crm/client-stages`:

```json
{"stages": [{"stage": "lead", "label": "лид", "order": 0}, ...],
 "order": ["lead", "negotiation", "client", "permanent", "asleep"],
 "sleeper_days": 90, "permanent_paid_orders": 2}
```

`POST /api/crm/client-stages/recalc` → `{"total": 6, "updated": 2, "manual_skipped": 1,
"clients": [{"client_id": 3, "name": "Ромашка", "stage": "permanent", "label": "постоянный"}]}`

### Дополнительно (аддитивно, для фронтенда)

* `GET /api/crm/clients/{cid}/card` теперь содержит **новое** поле `stage` (объект того же формата, read-only).
* Авто-пересчёт происходит сам после оплаты заказа (`core/crm/service.py::payment`, best-effort, ошибки не ломают оплату),
  плюс есть массовый `POST /api/crm/client-stages/recalc`.
* События смены стадии пишутся в ленту клиента (`crmactivity`, `kind="client_stage"`, текст «X → Y (вручную|авто)»).

## 6. Тесты (`tests/test_review_client_stage.py`, 12 шт.)

* чистая функция `auto_stage` (все правила, граница 89/90 дней, приоритет оплаты), `resolve` для старых записей;
* авто-переходы: оплаченный → `клиент`, 2 оплаченных → `постоянный`, 120 дней без активности → `спит/ушёл`;
* приоритет manual: `recalc` не перетирает ручную стадию, `stage_auto` обновляется; снятие manual → возврат к авто;
* «вернуть авто» без авто-сигнала сохраняет значение; неизвестная стадия → ошибка;
* обратная совместимость: запись с пустым `stage` (эмуляция «до миграции») читается по авто-логике, чтение БД не меняет,
  пересчёт дописывает авто-стадию, данные клиента целы;
* миграция v3 на **временной** копии БД в `tmp_path`: новые колонки с дефолтами, старые данные целы,
  бэкап только в tmp, повторный запуск — no-op без бэкапа, `schema_version = 3`; миграция не падает без таблицы `client`;
  `mtime` реальной `data/jarvis.db` не меняется (реальная БД не открывается);
* API: все 6 эндпоинтов, 400/404, старые `/api/crm/stages` (9 стадий) и `/api/orders` на месте.
* Обновлены ожидания версии схемы в существующих тестах фаз 2 и 4 (1,2 → 1,2,3) — это и есть новая миграция.

## 7. Проверка

`.venv\Scripts\python.exe -m pytest tests -q` → **460 passed, 2 warnings** (baseline-предупреждения: httpx/starlette, anyio).
Новых падений нет. Новых зависимостей нет; `config.yaml`, `.env`, `data/`, `vendor/` не трогались.
