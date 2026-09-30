# Разработка и структура проекта

Как предложить правку — в [CONTRIBUTING.md](../CONTRIBUTING.md). Устройство ядра — [ARCHITECTURE.md](ARCHITECTURE.md). Настройки — [CONFIGURATION.md](CONFIGURATION.md).

## Где что лежит

```
├─ install.bat / install.sh              установка (.venv, зависимости, config.yaml)
├─ start.bat / start.sh                  запуск ядра (окно держать открытым)
├─ update.bat / update.command           обновление пакетов после распаковки новой версии
├─ install_voice.bat / voice.bat         голосовой аддон и его запуск
├─ doctor.bat / doctor.sh                проверка окружения
├─ build_web.bat                         пересборка сайта (нужен Node.js)
├─ autostart.bat / phone.bat / funnel.bat
├─ run.py                                ядро: API + сайт + Telegram + планировщик
├─ voice_client.py                       голосовой клиент ПК
├─ setup.py / doctor.py                  установка и диагностика
├─ config.example.yaml → config.yaml     настройки (мастер и сайт пишут сюда сами)
├─ data/assistant.db                     вся база; data/backups/, data/media/
├─ core/                                 мозг (brain/), инструменты (tools/), сервисы, api/, telegram/, voice/, pc/
├─ web/                                  сайт (React + Vite); собранный — web/site/
├─ tests/                                pytest
├─ docs/                                 документация
└─ Dockerfile, docker-compose.yml
```

`web/site` (собранный сайт) лежит в репозитории — Node.js для запуска не нужен. Если менял фронт — `build_web.bat` (нужен [Node.js](https://nodejs.org)) или `cd web && npm install && npm run build`.

## Локальный запуск

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt              # pytest, pytest-timeout, ruff
python -m pytest tests -q                         # офлайн-тесты, без сети
python run.py --no-tg                             # ядро без Telegram, сайт на :8765
cd web && npm install && npm run dev              # фронт с hot reload на :5173 (проксирует /api на :8765)
```

Дизайн-система сайта — [`web/DESIGN.md`](../web/DESIGN.md). Планы — [`docs/ROADMAP.md`](ROADMAP.md).

## Тесты

```bash
python -m pytest tests -q                         # Python: ядро, API, сервисы, безопасность
npm test                                          # Node-стенд: API-тесты на :3999
```

Python-тесты офлайн: поднимают временную SQLite через fixture и не ходят в сеть. Не запускай `npm test` рядом с работающим стендом на :3000 — тесты занимают :3999.

## Стенд на Node (тот же сайт без Python)

```bash
npm install && npx tsx server.ts     # сайт на :3000, своё состояние в data/server-state.json
npm test                             # API-тесты на :3999
```

Чат этого стенда умеет ходить в настоящую модель: ключ кладётся в `.env` в корне (файл в `.gitignore`, новых зависимостей не нужно — запрос уходит обычным `fetch`).

```bash
LLM_API_KEY=sk-...                                   # или OPENAI_API_KEY / DASHSCOPE_API_KEY
LLM_URL=https://api.openai.com/v1/chat/completions    # любой OpenAI-совместимый адрес
LLM_MODEL=gpt-4o-mini                                # модель; по умолчанию gpt-4o-mini
```

С ключом ответы в чате помечены ☁️ облако, без него — ⚡ правила; если модель не ответила, чат честно отвечает по правилам, а не молчит. Проверить: `GET /api/llm` → `{"enabled":true,"model":"…"}` — то же видно в ⚙ Настройках → система → состояние.

> Эти переменные (`PORT`, `HOST`, `ALLOWED_ORIGINS`, `LLM_*`) использует только Node-стенд `server.ts`. Python-ядро их не читает.

## Публикация релизов

`publish.bat` вместо ручного «залить архив, потом ещё раз, потом тег»:

1. Один раз: поставить [git](https://git-scm.com/download/win) и [GitHub CLI](https://cli.github.com), выполнить `gh auth login`.
2. Поднять версию в `core/__init__.py` и дописать раздел `## X.Y.Z` в начало `CHANGELOG.md` — он и станет текстом релиза. Первой строкой раздела — `**Коротко:** …`: из этих строк собирается сводка «что изменилось» в шапке релиза.
3. Запустить `publish.bat`. Он соберёт сайт (если есть `web/node_modules`), закоммитит, запушит в ветку, поставит тег `vX.Y.Z`, соберёт архив **из git** (только то, что не в `.gitignore` — без `config.yaml`, `data/`, `.venv`) и создаст релиз.

Текст релиза — все разделы `CHANGELOG.md` от текущей версии до предыдущего опубликованного тега. Тот же тег два раза не публикуется — подними версию. Переписать заметки уже опубликованного релиза: `tools\fix_release_notes.bat 0.10.1`.

## Стек

Python 3.11+ · FastAPI · SQLite (SQLModel) · aiogram 3 · APScheduler · Ollama · faster-whisper · Vosk · Silero/edge-tts · React + Vite + Tailwind.

Лицензия — [Apache 2.0](../LICENSE): свободное использование и форки, с сохранением авторства (`NOTICE`, ссылка на оригинал) и пометкой изменённых файлов. Особенно приветствуются новые фразы-шаблоны в `core/brain/quick.py` и тесты к ним.
