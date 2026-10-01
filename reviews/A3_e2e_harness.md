# A3 — E2E-стенд на Playwright: инструкция для субагентов

Стенд нужен, чтобы проверять интерфейс (UX заказов, ревью фронтенда) **на демо-данных**, не поднимая
живого ассистента и не касаясь настоящей `data/jarvis.db`.

- Конфиг: `web/playwright.config.js`
- Демо-данные: `tests/e2e/demo_db.py`
- Сервер стенда: `tests/e2e/serve.py`
- Хелперы: `tests/e2e/helpers/`
- Тесты: `tests/e2e/specs/`
- Скриншоты: `tests/e2e/screens/`

---

## 1. Запуск

Один раз после клона/обновления (качает Chromium, ~120 МБ):

```bat
cd web
npm install
npm run test:e2e:install
```

Прогон всего:

```bat
cd web
npm run test:e2e
```

Чаще всего нужен один проект или один файл:

```bat
npm run test:e2e:desktop
npm run test:e2e:mobile
npx playwright test tests/e2e/specs/orders.spec.js
npx playwright test --project=desktop --headed --debug
```

Отчёт после прогона: `cd web && npm run test:e2e:report` (HTML-отчёт Playwright).
Если порт 8917 занят — `set E2E_PORT=8918 && npm run test:e2e` (только PowerShell: `$env:E2E_PORT=8918`).

Что происходит при `npx playwright test`:

1. `tests/e2e/serve.py` создаёт **чистую демо-БД** во временной папке
   `%TEMP%\jarvis-e2e-playwright\jarvis.db` (+ свой `config.yaml` рядом) и насыпает данные.
2. Поднимает FastAPI на `127.0.0.1:8917`. Сайт раздаёт сам FastAPI из `web/site` — отдельный
   `vite preview` не нужен, но если `web/site` пуст, сначала сделайте `cd web && npm run build`.
3. Playwright ждёт `http://127.0.0.1:8917/api/health` и только потом начинает тесты.
4. После прогона сервер гасится, демо-БД остаётся во временной папке (можно смотреть sqlite-файл).

Ручной стенд без Playwright (удобно смотреть глазами):

```bat
.venv\Scripts\python.exe tests\e2e\serve.py --port 8917
:: открыть http://127.0.0.1:8917
```

---

## 2. Как добавить свой тест

Создайте файл в `tests/e2e/specs/`, имя с `.spec.js`:

```js
// tests/e2e/specs/tasks.spec.js
import { test, expect, watch, shot, openTab, expectText, clickText } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]

test('задачи: открываются и видны демо-задачи', async ({ page }, testInfo) => {
  const diag = watch(page, { ignore: IGNORE })
  page.__e2eProject = testInfo.project          // префикс скриншотов

  await openTab(page, 'tasks', { testInfo })
  await expectText(page, 'Отдать первую версию')

  await shot(page, 'tasks-list', { testInfo })
  await diag.expectClean('задачи')              // упадёт, если в консоли/сети есть ошибки
})
```

Обязательные правила:

- **`workers: 1`** (уже в конфиге): БД одна на весь прогон, тесты делят состояние. Не включайте
  `fullyParallel` и не задавайте `workers > 1`, если не сделали изоляцию по БД.
- Если тест только для desktop: `test.skip(testInfo.project.name !== 'desktop', 'причина')`.
- Не завязывайтесь на точные суммы/даты «сегодня» — демо-данные пересоздаются каждый прогон.
- Скриншот всегда через `shot(page, имя, { testInfo })` → `tests/e2e/screens/<проект>-<имя>.png`.

---

## 3. API хелперов (`tests/e2e/helpers/index.js`)

Импортировать **всегда оттуда**, а не от `@playwright/test` напрямую: тесты лежат вне `web/`,
а пакет установлен в `web/node_modules`. Мост — `helpers/playwright.js`.

### Навигация и ожидания

| Вызов | Что делает |
|---|---|
| `openApp(page, { testInfo })` | открыть `/`, дождаться монтирования, проверить, что не белый экран |
| `openTab(page, 'orders' \| '/orders', { testInfo })` | открыть вкладку и проверить рендер |
| `waitApp(page, { timeout })` | ждёт `#root` с непустым текстом + `document.fonts.ready` |
| `expectRendered(page, note)` | бросает ошибку, если «страница сломалась» / пустой `#root` / нулевая высота |
| `clickTab(page, 'finance')` | клик по пункту сайдбара (только desktop — на мобильном сайдбар скрыт) |
| `TABS` | массив всех вкладок: `{ key, path, title }` — можно обходить циклом |

### Клики и ввод

| Вызов | Что делает |
|---|---|
| `clickText(page, 'карточка', { exact, index, timeout })` | клик по элементу с видимым текстом (`index` — какой по счёту) |
| `clickButton(page, 'заказ')` | клик по кнопке по имени (`getByRole('button', { name })`) |
| `fillField(page, 'Сумма', '5000')` | ввод по подписи, иначе по placeholder |

### Модалки и drawer

Сайт рисует их порталом в `body`: `.sheet-backdrop > .sheet` (см. `web/src/components/ui.jsx`, компонент `Sheet`).

| Вызов | Что делает |
|---|---|
| `expectSheet(page)` | дождаться верхней модалки, вернёт локатор |
| `sheetTitle(page)` | заголовок открытой модалки |
| `closeSheet(page)` | закрыть: крестик → Esc → клик по подложке |

### Диагностика

| Вызов | Что делает |
|---|---|
| `watch(page, { ignore })` | подписывается на `pageerror`, `console.error`, `requestfailed` и ответы `>= 400`; возвращает сборщик |
| `diag.expectClean('задачи')` | упасть с перечнем ошибок, если они были. `note` — что проверяли |
| `diag.list()` | вернуть список строкой (лог, мягкая проверка) |
| `diag.clear()` | сбросить между вкладками в одном тесте |

В `ignore` обязательно кладите `[/\/api\/events\/stream/, /favicon/i]` — SSE живёт вечно и даёт
«незакрытый запрос», favicon в dev-режиме шумит.

### Скриншоты и текст

| Вызов | Что делает |
|---|---|
| `shot(page, 'name', { fullPage = true, testInfo })` | PNG в `tests/e2e/screens/<проект>-name.png` + вложение в отчёт; анимации выключены |
| `pageText(page)` | весь видимый текст `#root` |
| `hasText(page, 'текст')` | есть ли текст (без ожидания) |
| `expectText(page, 'текст', { timeout, note })` | дождаться текста; при неудаче показывает, что было на странице |

---

## 4. Скриншоты

`tests/e2e/screens/<проект>-<имя>.png`, поимённо, с префиксом проекта:

```
desktop-smoke-today.png     desktop-smoke-orders.png   … (10 вкладок)
mobile-smoke-today.png      mobile-smoke-orders.png    … (10 вкладок)
desktop-orders-card.png     desktop-orders-list.png
```

Папка в `.gitignore` (артефакты прогона, не код). Скриншоты и HTML-отчёт — то, что нужно
приложить к ревью: их достаточно, чтобы судить о вёрстке без запуска у себя.

---

## 5. Безопасность стенда (почему реальная БД недостижима)

1. `core/config.py` (точечная правка): `DATA_DIR`, `DB_PATH` и путь к настройкам берутся из
   `JARVIS_DATA_DIR` / `JARVIS_DB_PATH` / `JARVIS_CONFIG`, если эти переменные заданы.
   Без переменных поведение прежнее — живой ассистент работает как раньше.
2. `demo_db.prepare_env()` ставит эти переменные **до** первого `import core.*` — иначе импортировался
   бы настоящий `data/jarvis.db`.
3. `demo_db.assert_safe()` проверяет: путь БД ≠ `data/jarvis.db`, workdir не внутри `data/`,
   БД лежит внутри workdir, переменные не указывают на реальные пути. Зовётся трижды.
4. `serve.py` дополнительно сверяет `core.config.DB_PATH` с настоящей БД и **отказывается стартовать**
   (`код 2`), если совпадение есть.
5. `config.yaml`, `.env` и настоящая `data/` при разработке стенда не открывались.
6. Стенд отключает внешнее: `OLLAMA_URL=http://127.0.0.1:1`, `brain.mode=local`, облако выключено,
   бэкапы выключены, `ASSISTANT_NO_VOICE_WARMUP=1`. Telegram и планировщик не запускаются вообще.

---

## 6. Демо-данные (что можно ждать в тестах)

Клиенты: `Кофейня «Зерно»`, `Студия «Кадр»`, `Маркетинг «Вектор»`, `Анна Демо`, `Богдан Тестов` (подрядчик).
Все вымышленные, реальных персональных данных нет.

Заказы — 10 штук, **все девять стадий воронки** (`lead → negotiation → spec → in_work → revisions →
delivered → awaiting_payment → paid → lost`), у каждого клиент, цена, срок, оценка часов, следующий шаг;
часть оплачена (в т.ч. частично и просрочена — для проверки красной подсветки).

Прочее: 42 операции за 45 дней (доходы/траты, регулярные платежи, долг, цели), 10 задач
(сегодняшние, просроченная, закрытые, заблокированная), 10 событий календаря (сегодняшние, повтор,
привязка к заказу, прошедшие), 7 заметок + 4 ссылки, 2 доски с объектами, рабочие сессии за 5 дней
(ставка и часы считаются), факты о владельце (в т.ч. один в архиве — для метки «возможно устарело»),
лента CRM, комментарии, чек-листы, 4 follow-up.

Полные счётчики стенд печатает при старте:

```
[e2e] насыпано: {'clients': 5, 'orders': 10, 'transactions': 42, 'tasks': 10, 'events': 10, ...}
```

---

## 7. Известные ограничения

- **Состояние общее на прогон.** БД одна, `workers: 1`. Тест, который что-то меняет (оплата, перенос
  стадии), повлияет на следующий. Если это мешает — выносите проверку в отдельный файл и запускайте
  его отдельно, либо просите фикстуру пересоздать БД (`seed_demo(fresh=True)`).
- **Одна БД на оба проекта.** desktop и mobile видят одни и те же данные (это плюс: сравниваемо).
- **SSE и favicon** исключены из проверки ошибок — иначе тесты падают на живом потоке событий.
- **LLM-фичи не проверяются.** В demo-конфиге `brain.mode=local` и облако выключено: чат, сортировка
  списков, связи и «мозг» работают на шаблонах/пустых ответах. Для них нужен отдельный стенд с Ollama.
- **Chromium только.** firefox/webkit не устанавливались и в конфиге нет — `npx playwright test` по
  умолчанию идёт по всем установленным; браузер указан только в devDependencies-установке `chromium`.
- **`web/site` должен быть собран.** Стенд раздаёт статику оттуда; после правок фронта — `cd web && npm run build`.
- **Тёмная тема принудительно** (`colorScheme: 'dark'`), чтобы скриншоты совпадали с рабочей темой.
- **`@playwright/test` подключён через мост** `helpers/playwright.js`. Если тесты переедут внутрь `web/`,
  мост можно удалить и импортировать `@playwright/test` напрямую.

---

## 8. Проверенное состояние на момент передачи

- `npx playwright test` в `web/` → **8 passed, 2 skipped** (~42 с), 23 скриншота.
- Backend: `.venv\Scripts\python.exe -m pytest tests -q` → **460 passed, 2 warnings** (baseline-предупреждения).
- Сборка: `npm run build` в `web/` → успешно, `web/site` без изменений.