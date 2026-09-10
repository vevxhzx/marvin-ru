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

---

## Локальный запуск

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest
python -m pytest tests -q                         # 94 теста, без сети
python run.py --no-tg                             # ядро без Telegram, сайт на :8765
cd web && npm ci && npm run dev                   # фронт с hot reload на :5173 (проксирует /api на :8765)
```

Дизайн-система сайта — [`web/DESIGN.md`](../web/DESIGN.md). Архитектура — [`ARCHITECTURE.md`](../ARCHITECTURE.md). Планы — [`ROADMAP.md`](../ROADMAP.md).

Стек: Python 3.11+ · FastAPI · SQLite (SQLModel) · aiogram 3 · APScheduler · Ollama · faster-whisper · Vosk · Silero/edge-tts · React + Vite + Tailwind.

Лицензия — [MIT](../LICENSE). Pull request'ы приветствуются — особенно новые фразы-шаблоны в `core/brain/quick.py` и тесты к ним.
