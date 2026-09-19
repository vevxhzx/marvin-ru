# Архитектура (как есть, сентябрь 2026)

Документ описывает **реальный** код репозитория, а не желаемое состояние. Числа строк — ориентир на 0.9.15 (сентябрь 2026).

## 1. Что это

Один Python-процесс (`run.py`) на ПК пользователя (Windows) или в Docker, который:

- держит **SQLite-базу** (`data/assistant.db`) со всеми личными данными;
- отдаёт **HTTP API + собранный сайт** (FastAPI + uvicorn, порт 8765);
- ведёт **Telegram-бота** (aiogram 3, long polling, только `owner_id`);
- крутит **планировщик** (APScheduler: напоминания, бэкап, дайджесты);
- принимает команды от **голосового клиента** (`voice_client.py`, отдельный процесс на том же ПК) и **ПК-клиента** (`core/pc/loop.py`: игровой режим, выполнение действий вроде «открой блокнот»).

«Мозг» — `core/brain/`: правила-шаблоны (regex) → локальная LLM через Ollama (tool calling) → облако (Groq/OpenRouter/Gemini…) для общих вопросов через анонимайзер.

```
 Telegram ──┐                                   ┌── Ollama (локальная LLM, tools)
 Сайт/PWA ──┼─► core/api/app.py ─► brain/agent ─┼── облако (cloud_chat, анонимно)
 Голос ПК ──┘        │                 │         └── core/tools/registry (26 инструментов)
                     │                 ▼
                     │          core/services/* ─► core/db.py (SQLite, WAL)
                     ▼
              SSE /api/events/stream ─► сайт (live-обновления), core/pc/loop.py (действия на ПК)
```

## 2. Слои и модули

| Слой | Путь | Размер | Роль |
|---|---|---|---|
| Вход | `run.py` | ~170 | Старт: миграции, uvicorn, TG, планировщик, прогрев моделей, мастер первого запуска |
| HTTP | `core/api/app.py` | ~2050, 157 роутов | REST для сайта, SSE, настройки, Google OAuth, мастер `/setup`, статика `web/site` |
| HTTP | `core/api/auth.py` | ~200 | доступ: loopback свободно (но не через прокси с `X-Forwarded-*`), иначе токен `data/api_token` (cookie/заголовок) или Telegram-сессия |
| HTTP | `core/api/tg_auth.py` | ~180 | вход из Telegram Mini App: проверка `initData` (HMAC от токена бота, свежесть, `owner_id`) → подписанная сессия на 30 дней; лимит попыток |
| Мозг | `core/brain/agent.py` | ~1800 | `handle()` — главный вход: правила → pending-подтверждения → судья спорных фраз → Ollama с инструментами → облако; страж правды `_truth_gate` (ответ сверяется с реальным результатом инструментов), журнал `trace` |
| Мозг | `core/brain/llm.py` | ~1140 | Ollama (`ollama_chat`, авто-`num_ctx`, game mode) и облако (`cloud_chat`, провайдеры, анонимайзер, fallback моделей) |
| Мозг | `core/brain/quick.py`, `dates.py`, `persona.py`, `sorter.py` | 432/343/~100/409 | Быстрые ответы без LLM, разбор русских дат/сумм, системный промпт + реплики |
| Инструменты | `core/tools/registry.py` | ~1030 | 39 `@tool` с JSON-схемами; `validate_args()` и `call()` → `ToolResult` (успех проверяется чтением базы, `risk_of()`: read/write/destructive) — единственная граница LLM → данные |
| Сервисы | `core/services/finance.py` | ~870 | Счета, транзакции, категории, долги, регулярные, бюджеты, сводки |
| Сервисы | `calendar.py`, `gcal.py`, `tasks.py`, `brain_notes.py`, `insights.py`, `bulk.py`, `cards.py`, `bank_import.py`, `polish.py`, `pc.py`, `scheduler.py`, `memory.py`, `relations.py`, `judge.py`, `people.py`, `trace.py`, `undo.py` | 100–600 каждый | Предметная логика; `scheduler.py` — cron-задачи и бэкап; `memory.py` — многоуровневая память; `trace.py` — журнал работы и «отчёт о себе» |
| Данные | `core/db.py` | ~460 | 22 таблицы SQLModel (Event, Task, Account, Category, Transaction, Recurring, Debt, Client, Order, WorkSession, Goal, Note, Link, Memory, Fact, Relation, Setting, ActionLog, Lesson, Run, Embedding, ChatMessage); движок SQLite WAL, `check_same_thread=False` |
| Конфиг | `core/config.py`, `config.yaml` | 245 | YAML → объект; `EDITABLE` — что можно менять с сайта; маскирование секретов |
| Telegram | `core/telegram/bot.py` | ~800 | Owner-only, текст/голос/фото, `send_long`, кнопки подтверждений |
| ПК | `core/pc/loop.py`, `core/pc/actions.py` | ~200/312 | Пульс, игровой режим, действия: открыть/найти/переместить, питание, буфер |
| Голос | `voice_client.py`, `core/voice/{stt,tts}.py` | ~890 | Wake-word (Vosk), faster-whisper, Silero/Edge TTS; ходит в API по HTTP |
| Сайт | `web/src/` (React + Vite + Tailwind) | 9 страниц, 9 компонентов | `lib/api.js` — единая точка fetch; SSE в `App.jsx`; собранный бандл коммитится в `web/site/` |
| Тесты | `tests/test_*.py` (13 файлов) | ~260 | Офлайн, временная БД через fixture; `python -m pytest tests -q` |

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
| Личное → облако | `is_personal` + анонимайзер (имена/суммы/телефоны); режимы `local`/`hybrid`/`cloud` | `agent.py`, `llm.py` |

## 5. Данные и их жизненный цикл

- `data/assistant.db` — всё; WAL; бэкап через `sqlite3.backup()` ежедневно в `backups/` (+ `extra_dir`), хранение `keep_days`.
- `data/media/` — фото заметок и чеков; зеркалируется в `backups/media/` инкрементально.
- `data/api_token` — ключ доступа с других устройств (создаётся при старте, права 600 вне Windows).
- `config.yaml` — настройки и секреты (TG-токен, ключи облака, Google OAuth). В API отдаются маскированными. Не в git.
- Удаление пользовательских файлов ассистент **не делает** никогда (переносит в отдельную папку).

## 6. Известные архитектурные ограничения (не баги, но надо знать)

- **Одиночный монолит `app.py` (~2050 строк) и `agent.py` (~1800)** — работает, тестируется точечно, но правки требуют внимания. Разбивать «ради красоты» не стали (осознанно: разбивать при следующей крупной фиче, см. ROADMAP).
- **SQLite + `check_same_thread=False`** — нормально для одного пользователя; при переезде на VPS с несколькими клиентами держать в уме.
- **История чата для LLM — 6 сообщений / 600 символов** — осознанный компромисс под `num_ctx` маленьких моделей.
- **Собранный фронт коммитится в `web/site/`** — чтобы пользователю без Node ничего не собирать; после правок `web/src` нужен `build_web.bat`.
- **Один процесс = один пользователь.** Многопользовательность не предусмотрена нигде (нет `user_id` в таблицах).
- **Планировщик in-memory** — при перезапуске напоминания пересчитываются от данных, что нормально; `misfire_grace_time=3600` покрывает сон ПК.
