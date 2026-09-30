# PROGRESS — объединение Jarvis + Marvin

Ветка: `merge-marvin` (в репо jarvis-main, remote убран — локально ничего не уходит)
Базовый коммит: `364475a` — «chore: baseline jarvis state before merge with marvin»

## Шаг 0 — Подготовка — ВЫПОЛНЕНО
- [x] Remote `origin` (github.com/vevxhzx/marvin-ru.git) убран из jarvis-main
- [x] Базовый коммит текущего состояния jarvis-main (245 файлов)
- [x] Создана ветка `merge-marvin`
- [x] PROGRESS.md создан

## Шаг 1 — Изучение — ВЫПОЛНЕНО
- [x] Изучены README/структура/точки входа обоих проектов (2 explore + механический дифф: SAME 80 / DIFF 123 / ONLY_J 44 / ONLY_M 88)
- [x] Создан FEATURES.md

## Шаг 2 — Объединение — ВЫПОЛНЕНО (`ef17aaf`)
- [x] Резервная копия БД: `data/backups/jarvis-premerge-20260930-0428.db` (sqlite3 backup API)
- [x] Код ядра взят из Marvin (новее), поверх — личные фичи Jarvis; скрипты/доки/docker/CI
- [x] Веб-интерфейс и дизайн Marvin перенесены в `web/`, сайт пересобран (`web/site`)
- [x] Данные и логика Jarvis не тронуты: путь БД `data/jarvis.db`, команды/сценарии/интеграции на месте
- [x] Пересоздания БД не было — только штатные миграции `core/db.py` (`event.task_id`, `event.order_id`)
- [x] Имя ассистента «Джарвис», мастер setup помечен пройденным (`setup.done: true`)

## Шаг 3 — Порядок в папках — ВЫПОЛНЕНО (`101e05d`)
- [x] `.gitignore` переписан: `data/`, `*.db*`, `*.sqlite*`, `.env`, `config.yaml`, `_archive/`, бэкапы, `node_modules/`, `dist/`, кэши
- [x] Из индекса сняты `node_modules/` (10184 файла), `dist/`, `_archive/` — на диске остались (в индексе 264 файла вместо 10530)
- [x] В `_archive/` перенесено (ничего не удалено): `web/site-jarvis-old/`, `web/root-vite-duplicate/`, `web/glass.css`, `releases-marvin/`
- [x] README.md: разделы «Как запускать» и «Структура проекта»
- [x] `.env.example` переписан (без значений, `ASSISTANT_*` + `JARVIS_*`)
- [x] `start.bat` проверен
- [x] `vite.config.ts` → единый источник `web/src`; сборка из корня и из `web/` идентична

## Шаг 4 — Проверка на реальных данных — ВЫПОЛНЕНО (`0f30418`)
- [x] `python -m pytest tests -q` → **338 passed** (было 5 failed, починены: судья vs точные правила, restore бэкапа на Windows)
- [x] `npm test` → **17 passed**
- [x] Запуск бэкенда `python run.py --no-tg`, `/api/health` ok, сайт `http://localhost:8765` отрисован, 0 ошибок консоли
- [x] Быстрые команды и сценарии: деньги, календарь, задачи, заказы, заметки, «что сегодня», «мои цели», «хватит ли до зарплаты»
- [x] Запросы к LLM: Ollama `qwen3.5:4b` ответил (21 с), личные вопросы закрываются правилами мгновенно; облако Groq настроено
- [x] Добавлены недостающие роуты `/api/edition`, `/api/client/info`, `/api/llm` (их был только в server.ts)
- [x] Тестовые записи откачены «отменой»: баланс до = после = 15 161 ₽, хвостов нет
- [x] Второй экземпляр бота НЕ поднимался (`--no-tg`); что проверить в Telegram руками — в REPORT.md §5

## Шаг 5 — Отчёт — ВЫПОЛНЕНО
- [x] REPORT.md (что объединено, конфликты и решения, что починено, архив, запуск, ограничения)
- [x] requirements-dev.txt (pytest) + ссылка в README

---
Итог: шаги 0–5 выполнены. Ручная проверка Telegram — по инструкции в REPORT.md §5.
