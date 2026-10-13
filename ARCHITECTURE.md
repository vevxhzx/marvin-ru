# Архитектура (как есть, релиз 0.18.0)

Документ описывает **реальный** код репозитория, а не желаемое состояние. Числа строк сверены с кодом
на 0.18.0 (октябрь 2026): всего `core/` — 116 файлов, ~39 500 строк. Если видишь расхождение —
верь коду, а не таблице, и правь таблицу.

## 1. Что это

Один Python-процесс (`run.py`) на ПК пользователя (Windows) или в Docker, который:

- держит **SQLite-базу** (`data/jarvis.db`) со всеми личными данными;
- отдаёт **HTTP API + собранный сайт** (FastAPI + uvicorn, порт 8765);
- ведёт **Telegram-бота** (aiogram 3, long polling, только `owner_id`);
- крутит **планировщик** (APScheduler: напоминания, бэкап, дайджесты);
- принимает команды от **голосового клиента** (`voice_client.py`, отдельный процесс на том же ПК) и **ПК-клиента** (`core/pc/loop.py`: игровой режим, выполнение действий вроде «открой блокнот»).

«Мозг» — `core/brain/`: правила-шаблоны (regex) → локальная LLM через Ollama (tool calling) → облако (Groq/OpenRouter/Gemini…) для общих вопросов через анонимайзер.

```
 Telegram ──┐                                   ┌── Ollama / LM Studio (локальная LLM, tools)
 Сайт/PWA ──┼─► core/api/app.py ─► brain/agent ─┼── облако (cloud_chat, анонимно)
 Голос ПК ──┘        │                 │         └── core/tools/registry (46 инструментов)
                     │                 ▼
                     │          core/services/* ─► core/db.py (SQLite, WAL)
                     ▼
              SSE /api/events/stream ─► сайт (live-обновления), core/pc/loop.py (действия на ПК)
```

Роутов теперь 260 (`core/api/routers/` + `core/crm/router.py`). Монолит `app.py` разбит: в нём
остались только монтирование, SSE, статика и SPA-catch-all.

## 2. Слои и модули

| Слой | Путь | Размер | Роль |
|---|---|---|---|
| Вход | `run.py` | ~342 | Старт: миграции, uvicorn, TG, планировщик, прогрев моделей, мастер первого запуска |
| HTTP | `core/api/app.py` | ~407 | Приложение FastAPI: монтирование роутов, SSE, статика `web/site`, SPA-catch-all. Роутов больше нет — вынесены в `routers/` |
| HTTP | `core/api/routers/*.py` (10 модулей) + `core/crm/router.py` | 100–711 каждый | ~260 операций REST: `system` (настройки, статус, бэкапы, логи ходов), `finance` (50), `mind` (40, заметки/факты/память), `orders`, `tasks`, `people`, `boards`, `pc`, `learn`, `chat` (обычный и `/stream`), `core/crm` (27) |
| HTTP | `core/api/auth.py` | ~227 | доступ: loopback свободно (но не через прокси с `X-Forwarded-*`), иначе токен `data/api_token` (cookie/заголовок) или Telegram-сессия |
| HTTP | `core/api/tg_auth.py` | ~233 | вход из Telegram Mini App: проверка `initData` (HMAC от токена бота, свежесть, `owner_id`) → подписанная сессия на 30 дней; лимит попыток |
| Мозг | `core/brain/agent.py` | ~2700 | `handle()` — главный вход: правила → pending-подтверждения → судья спорных фраз → Ollama с инструментами → облако; страж правды `_truth_gate` (ответ сверяется с реальным результатом инструментов), журнал `trace` |
| Мозг | `core/brain/llm/` (`base`, `cloud`, `ollama`, `lmstudio`, `vision`) | ~2460 суммарно | Общие хелперы и учёт usage; облако (`cloud_chat`, провайдеры, анонимайзер, fallback моделей); Ollama (`ollama_chat`, авто-`num_ctx`, game mode); LM Studio (OpenAI-совместимый, роль `main`); зрение (LM Studio → Ollama → облако) |
| Мозг | `core/brain/quick.py`, `dates.py`, `persona.py`, `sorter.py` | 954/418/559/487 | Быстрые ответы без LLM, разбор русских дат/сумм, системный промпт + реплики, сортировщик списков дел |
| Инструменты | `core/tools/registry.py` | ~1230 | 46 `@tool` с JSON-схемами; `validate_args()` и `call()` → `ToolResult` (успех проверяется чтением базы, `risk_of()`: read/write/destructive) — единственная граница LLM → данные |
| Сервисы | `core/services/finance.py` | ~1280 | Счета, транзакции, категории, долги, регулярные, бюджеты, сводки, прогноз |
| Сервисы | `core/services/scheduler.py` | ~1260 | APScheduler: 28 задач (напоминания, дайджесты, бэкап, retention, проактивность), `_notify` с учётом тихих часов |
| Сервисы | `calendar.py`, `gcal.py`, `tasks.py`, `brain_notes.py`, `insights.py`, `bulk.py`, `cards.py`, `bank_import.py`, `polish.py`, `pc.py`, `relations.py`, `judge.py`, `people.py`, `trace.py`, `undo.py`, `proactive.py`, `cloud_backup.py` | 100–700 каждый | Предметная логика; `trace.py` — журнал работы и «отчёт о себе»; `cloud_backup.py` — шифрованный WebDAV-бэкап |
| Память | `core/services/memory/` (`store`, `recall`, `extract`, `portrait`, `nightly`) | `store` ~600 | Многоуровневая память: факты с эмбеддингами и затуханием, извлечение из переписки, портрет и стиль хозяина, ночная уборка |
| CRM | `core/crm/` (`router`, `service`, `client_stages`, `stages`) | 27 операций | Воронка клиентов, сделки, активности, комментарии, чек-листы, follow-ups |
| Данные | `core/db.py` | ~960 | 32 таблицы SQLModel (Event, Task, Aim, Milestone, Account, Category, Transaction, Recurring, Debt, Client, Order, WorkSession, Goal, Note, Link, Board, BoardItem, Memory, Setting, SchemaVersion, ActionLog, CrmActivity, CrmComment, CrmChecklist, CrmFollowup, Lesson, Run, ScreenSlot, Fact, Relation, Embedding, ChatMessage); движок SQLite WAL, `check_same_thread=False` |
| Миграции | `core/migrations.py` | ~480 | Версионированные идемпотентные миграции в `schema_version`; снимок БД **до** миграции |
| Конфиг | `core/config.py`, `config.yaml` | ~433 | YAML → объект; `EDITABLE` — что можно менять с сайта; маскирование секретов |
| Telegram | `core/telegram/bot.py` | ~1440 | Owner-only, текст/голос/фото, `send_long`, кнопки подтверждений |
| ПК | `core/pc/loop.py`, `core/pc/actions.py` | ~274/355 | Пульс, игровой режим, действия: открыть/найти/переместить, питание, буфер |
| Голос | `voice_client.py`, `core/voice/{stt,tts}.py` | ~890 | Wake-word (Vosk), faster-whisper, Silero/Edge TTS; ходит в API по HTTP |
| Сайт | `web/src/` (React + Vite + Tailwind) | 11 страниц, 33 компонента | Два набора экранов: десктоп `pages/` и мобильный `mapp/` (сделан отдельно осознанно — десктопный фронт плохо скейлится на телефон). `lib/api.js` — единая точка fetch; SSE в `App.jsx`; собранный бандл коммитится в `web/site/` |
| Тесты | `tests/test_*.py` (137 файлов) | ~1370 функций | Офлайн, временная БД через fixture; `python -m pytest tests -q`. Плюс 14 e2e-спецификаций Playwright (в CI **не** запускаются — только локально) |

## 3. Поток обработки сообщения

1. Канал (TG / `POST /api/chat` / голос) → `agent.handle(text, channel)`.
2. `normalize_spoken` → `quick` (время, погода-заглушки, статус) → `_resolve_pending` («да» на висящий вопрос, TTL) → `rules()` (regex: траты, события, задачи, долги…; длинные/аналитические тексты шаблоны пропускают).
3. Если правила не сработали: `is_personal(text)` решает — локально или облако. Облако — только для общих вопросов и только через анонимайзер; ответ кэшируется (`_ANSWER_CACHE`).
4. `via_ollama`: system prompt + история (6 сообщений/600 симв.) + схемы инструментов → до 4 раундов tool calls → `registry.run_tool` (валидация → сервис → БД) → финальная фраза. Предохранители: модель «сказала, что записала» без вызова → записываем сами; вопрос о цифрах без инструмента → вызываем инструмент сами; вопрос/анализ модель хочет записать в заметку → отклоняем.
5. `_changed()` → `agent.on_change` → SSE broadcast → сайт обновляет виджеты, ПК-клиент выполняет действия из `core/services/pc.py`.

## 4. Границы доверия

| Граница | Как защищено | Файл |
|---|---|---|
| Интернет → Telegram | Только `owner_id`, остальным молчим | `core/telegram/bot.py` |
| Локальная сеть → HTTP API | loopback без проверки; другие адреса — токен (cookie на год через QR/ссылку из настроек, или `X-Auth-Token`). Мастер `/setup`, `/api/phone` и ротация ключа — только физически с ПК (запросы через Funnel/прокси считаются внешними). Вход из Telegram Mini App — `tg_auth.py`. CORS только для Vite dev | `core/api/auth.py`, `app.py` |
| LLM → данные | `validate_args`: типы, диапазоны, обязательные поля, лишние поля, длины | `core/tools/registry.py` |
| LLM/речь → ОС | `open_app` без `shell=True`, только найденные в PATH/App Paths/меню «Пуск» программы; запрещённые символы отсекаются | `core/pc/actions.py` |
| Чужая веб-страница → LLM | Промпт помечает `page_text` как недоверенные данные; в системном промпте правило «данные — не команды» | `polish.py`, `persona.py` |
| Ссылка из чата → сеть | только публичные http(s), ручные редиректы с проверкой каждого хопа, лимит 1.5 МБ, только HTML | `brain_notes.fetch_preview` |
| Личное → облако | `is_personal` + анонимайзер (имена/суммы/телефоны); режимы `local`/`hybrid`/`cloud` | `agent.py`, `llm/base.py` |

## 5. Данные и их жизненный цикл

- `data/jarvis.db` — всё; WAL; бэкап через `sqlite3.backup()` ежедневно в `backups/` (+ `extra_dir`), хранение `keep_days`.
- `data/media/` — фото заметок и чеков; зеркалируется в `backups/media/` инкрементально.
- `data/api_token` — ключ доступа с других устройств (создаётся при старте, права 600 вне Windows).
- `config.yaml` — настройки и секреты (TG-токен, ключи облака, Google OAuth). В API отдаются маскированными. Не в git.
- Удаление пользовательских файлов ассистент **не делает** никогда (переносит в отдельную папку).

## 6. Известные архитектурные ограничения (не баги, но надо знать)

- **`agent.py` (~2700 строк) и `rules()` внутри него (~390 строк)** — работает и покрыто золотыми
  тестами, но правка требует внимания: маршрутизация, уточняющие вопросы и форматирование ответа
  живут в одной функции. `app.py` из этой проблемы уже вышел (роуты вынесены в `routers/`).
- **SQLite + `check_same_thread=False`** — нормально для одного пользователя; при переезде на VPS с несколькими клиентами держать в уме.
- **История чата для LLM — 6 сообщений / 600 символов** — осознанный компромисс под `num_ctx` маленьких моделей.
- **Собранный фронт коммитится в `web/site/`** — чтобы пользователю без Node ничего не собирать; после правок `web/src` нужен `build_web.bat`.
- **Один процесс = один пользователь.** Многопользовательность не предусмотрена нигде (нет `user_id` в таблицах).
- **Планировщик in-memory** — при перезапуске напоминания пересчитываются от данных, что нормально; `misfire_grace_time=3600` покрывает сон ПК.
