# Разработка и структура проекта

## Где что лежит


```
├─ install.bat / start.bat / update.bat     ← установка, запуск (держать открытым), обновление пакетов
├─ install_voice.bat / voice.bat            ← голосовой аддон и его запуск
├─ autostart.bat / phone.bat / build_web.bat
├─ config.example.yaml → config.yaml        ← настройки (мастер и сайт пишут сюда сами)
├─ data/assistant.db                        ← ВСЯ база; data/backups/, data/media/
├─ run.py                                   ← ядро: API + сайт + Telegram + планировщик
├─ voice_client.py                          ← голосовой клиент ПК
├─ core/                                    ← мозг (brain/), инструменты (tools/), сервисы, API, Telegram, голос, setup_wizard.py
├─ web/                                     ← сайт (React + Vite); собранный сайт — web/site/
├─ tests/                                   ← pytest
└─ Dockerfile, docker-compose.yml
```

`web/site` (собранный сайт) лежит в репозитории — Node.js для запуска не нужен. Если меняли фронт — `build_web.bat` (нужен [Node.js](https://nodejs.org)) или `cd web && npm ci && npm run build`.

---

## Публикация на GitHub одной командой

`publish.bat` — вместо ручного «залить архив, потом ещё раз, потом тег»:

1. Один раз: поставить [git](https://git-scm.com/download/win) и [GitHub CLI](https://cli.github.com), выполнить `gh auth login`.
2. Поднять версию в `core/__init__.py` и дописать раздел `## X.Y.Z` в начало `CHANGELOG.md` — он и станет текстом релиза.
   Первой строкой раздела — `**Коротко:** …` (одно-два предложения): из этих строк собирается сводка «Что изменилось, коротко»
   в шапке релиза на GitHub.
3. Запустить `publish.bat`. Первый запуск спросит адрес **существующего** репозитория (`https://github.com/вы/marvin-ru.git`)
   и сядет на его историю (Enter — создаст новый); имя/почта для git берутся из аккаунта GitHub сами. Дальше он: соберёт
   сайт (если есть `web/node_modules`), закоммитит всё, запушит в ветку репозитория (main или master), поставит тег `vX.Y.Z`,
   соберёт архив **из git** (только то, что не в `.gitignore` — без `config.yaml`, `data/`, `.venv`) и создаст релиз с этим
   архивом и текстом из `CHANGELOG.md`.

Текст релиза — **все** разделы `CHANGELOG.md` от текущей версии до предыдущего опубликованного тега (если между
релизами прошло несколько версий, в заметки попадут они все, с пометкой «изменения с vA по vB»). Если GitHub успел уйти
вперёд (правили README на сайте, публиковали из другой папки) — `publish.bat` сам подтянет и сольёт эти изменения,
файлы из папки при конфликте побеждают.

Тот же тег второй раз не публикуется — поднимите версию. Скачавшим достаточно распаковать архив релиза поверх папки.
Переписать текст уже опубликованного релиза: `tools\fix_release_notes.bat 0.10.1` (второй аргумент — с какого тега считать,
например `v0.9.15`; без него берётся предыдущий тег).

## Локальный запуск

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest
python -m pytest tests -q                         # ~320 тестов, без сети
python run.py --no-tg                             # ядро без Telegram, сайт на :8765
cd web && npm ci && npm run dev                   # фронт с hot reload на :5173 (проксирует /api на :8765)
```

Дизайн-система сайта — [`web/DESIGN.md`](../web/DESIGN.md). Архитектура — [`ARCHITECTURE.md`](../ARCHITECTURE.md). Планы — [`ROADMAP.md`](../ROADMAP.md).

Стек: Python 3.11+ · FastAPI · SQLite (SQLModel) · aiogram 3 · APScheduler · Ollama · faster-whisper · Vosk · Silero/edge-tts · React + Vite + Tailwind.

Лицензия — [MIT](../LICENSE). Pull request'ы приветствуются — особенно новые фразы-шаблоны в `core/brain/quick.py` и тесты к ним.
