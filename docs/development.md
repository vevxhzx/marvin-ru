# Где что лежит


```
jarvis/
├─ start.bat / install.bat / autostart.bat   ← твои кнопки
├─ setup.py                                  ← логика установки (вызывается из install.bat)
├─ config.yaml                               ← настройки (токен, режим мозга, характер)
├─ data/jarvis.db                            ← ВСЯ база (один файл; скопировал = сделал бэкап)
├─ data/backups/                             ← автобэкапы
├─ run.py                                    ← точка входа
├─ core/
│  ├─ db.py            модели базы (события, задачи, финансы, долги, заметки, ссылки, память)
│  ├─ brain/           мозг: правила, даты, персона, Ollama/облако (Groq), агент
│  ├─ tools/           инструменты, которые вызывает LLM
│  ├─ services/        логика: календарь, задачи, финансы, второй мозг, планировщик
│  ├─ telegram/        бот
│  └─ api/             HTTP API (для сайта и голосового клиента)
├─ web/site/           ← собранный сайт (раздаётся ядром)
├─ web/src/            ← исходники сайта (React), build_web.bat — пересобрать
└─ tests/              ← python -m pytest tests -q
```

## Разработка

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt pytest
python -m pytest tests -q          # 94 теста, без сети
python run.py --no-tg              # ядро без Telegram, сайт на :8765
cd web && npm ci && npm run dev    # фронт с hot reload на :5173
```

Архитектура — [`ARCHITECTURE.md`](../ARCHITECTURE.md), дизайн-система сайта — [`web/DESIGN.md`](../web/DESIGN.md).
