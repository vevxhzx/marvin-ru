# AGENTS.md — памятка для агентов и разработчиков

Коротко: как устроен проект, где что лежит и что нельзя ломать. Полная архитектура — `ARCHITECTURE.md`.

## Запуск

```bat
install.bat        :: один раз — зависимости и config.yaml
start.bat          :: ядро + Telegram + сайт http://localhost:8765
install_voice.bat  :: один раз — распознавание и офлайн-озвучка
voice.bat          :: голосовой клиент ПК (отдельный процесс)
build_web.bat      :: пересобрать сайт после правок в web/src
```

- без Telegram: `python run.py --no-tg`
- тесты: `python -m pytest tests -q` (офлайн, ~1580 шт. в 71 файле) · `npm test` (Node-стенд, порт 3999)
- Python — из `.venv` (`.venv\Scripts\python.exe`).

## Где что лежит

| Область | Путь | Комментарий |
|---|---|---|
| Точка входа ядра | `run.py` | миграции, uvicorn, Telegram, планировщик |
| HTTP API + SSE | `core/api/app.py` + `core/api/routers/` (10 модулей) | ~240 операций (~190 путей), статика `web/site` |
| CRM | `core/crm/router.py` (`/api/crm/*`) | подключается в `app.py` отдельно от `routers/` |
| Мозг | `core/brain/agent.py`, `llm.py`, `quick.py`, `persona.py`, `dates.py`, `sorter.py` | правила → Ollama → облако |
| Инструменты LLM | `core/tools/registry.py` | единственная граница «LLM → данные» |
| Предметная логика | `core/services/*` | finance, calendar, tasks, cards, scheduler… |
| БД | `core/db.py`, `data/jarvis.db` | SQLModel, SQLite WAL, один файл |
| Telegram | `core/telegram/bot.py` | только `owner_id` |
| ПК-клиент | `voice_client.py`, `core/pc/*`, `core/voice/*` | пульс, действия, STT/TTS |
| Сайт | `web/src/` (React+Vite+Tailwind) | собранный бандл — `web/site/` |
| Настройки и секреты | `config.yaml` (в `.gitignore`) | секреты только тут и в `.env` |

## Правила (неприкосновенное)

- **Local-first.** Режимы `local` / `hybrid` / `cloud`. В `local` в облако не уходит ничего.
- ~40 команд работают **офлайн и без LLM** (`core/brain/quick.py`, `rules()` в `agent.py`) — не тормозить их.
- Персона: сухая, язвительная, по-дружески (`core/brain/persona.py`; включается `persona.style: swag` + `humor_level`).
- Секреты — только из `.env`/`config.yaml`, не логировать, не коммитить.
- **Данные пользователя не удалять.** Перед миграцией БД — копия в `backups/`.
- Новая фича — за настройкой, по умолчанию поведение не меняет, тесты не ломает.
- Морделлинг `agent.py`/`app.py` не рефакторить «ради красоты».

## Перед изменениями

1. Ветка (не `main`), бэкап БД (`sqlite3.backup()` в `backups/`).
2. После правки — `python -m pytest tests -q`, проверка старта API, коммит с понятным сообщением.
3. Обновить `PROGRESS.md` (что сделано / что дальше).

## После пуша в main — CI до зелёного (обязательно)

1. Проверить прогон: `gh run list --branch main --limit 1`, затем при failure — `gh run view <id> --log-failed`.
2. Красное чинить сразу новой веткой: корень — по логам CI, а не гаданием. Типовые грабли:
   - тест зелёный локально, красный на CI → зависимость от локального `config.yaml`/сида/часового пояса/текущего времени (пример: сид мейна «Кубышка» vs «Основной», вторничный флейк golden 066);
   - рандом в ответах (`random.choice` реплик) → ассерты только регистронезависимо/содержательно;
   - `requirements.lock` / `requirements-mac.txt` забыли после правки `requirements.txt`.
3. Пре-existing красным считать только то, что падает на чистом дереве (проверено через `git stash`), остальное — чинить.
4. Пуш фикса → снова п.1, пока workflow не зелёный. Молча красным main не оставлять.

## Теги

- Теги релизов — только `vX.Y.Z` (например `v0.13.0`). Форматы `checkpoint-*` и голые `0.9.5` не использовать и не пушить. Удаление/пуш тегов — только явно, здесь этого не делаем.
