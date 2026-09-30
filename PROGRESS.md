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

## Шаг 2 — Объединение — ВЫПОЛНЕНО
- [x] Резервная копия БД: `data/backups/jarvis-premerge-20260930-0428.db` (sqlite3 backup API)
- [x] Код ядра взят из Marvin (новее), поверх — личные фичи Jarvis; скрипты/доки/docker/CI
- [x] Веб-интерфейс и дизайн Marvin перенесены в `web/`, сайт пересобран (`web/site`)
- [x] Данные и логика Jarvis не тронуты: путь БД `data/jarvis.db`, команды/сценарии/интеграции на месте
- [x] Пересоздания БД не было — только штатные миграции `core/db.py`
- [x] Имя ассистента «Джарвис», мастер setup помечен пройденным (`setup.done: true`)
- [x] Коммит: `ef17aaf` «merge: код ядра и скрипты из Marvin…»

## Шаг 3 — Порядок в папках — ВЫПОЛНЕНО
- [x] `.gitignore` переписан: `data/`, `*.db*`, `*.sqlite*`, `.env`, `config.yaml`, `_archive/`, бэкапы, `node_modules/`, `dist/`, кэши
- [x] Из индекса сняты `node_modules/` (10184 файла), `dist/`, `_archive/` — на диске остались
- [x] В `_archive/` перенесено (ничего не удалено):
  - `web/site-jarvis-old/` — старая сборка сайта Jarvis
  - `web/root-vite-duplicate/` — дубль фронта (`src/`, `index.html`, `postcss.config.js`, `tailwind.config.js`)
  - `web/glass.css` — мёртвые стили (нигде не импортируются)
  - `releases-marvin/` — RELEASE-0.9.6 … 0.12.0
- [x] README.md: добавлены разделы «Как запускать» и «Структура проекта»
- [x] `.env.example` переписан (без значений, обе ветки переменных: `ASSISTANT_*` и `JARVIS_*`)
- [x] `start.bat` на месте (проверен, заголовок «Jarvis»)
- [x] `vite.config.ts` переведён на единый источник `web/src`; `tsconfig.json` и конфиги Tailwind/PostCSS поправлены — `npm run build` из корня и из `web/` дают идентичную сборку

## Шаг 4 — Проверка на реальных данных — В РАБОТЕ
- [x] Тесты Python: `python -m pytest tests -q` — пройдены до изменений шага 3
- [ ] Запуск бэкенда и фронтенда (`python run.py --no-tg`, порт 8765 свободен)
- [ ] Быстрые команды + сценарии (деньги, календарь, задачи, заказы, заметки)
- [ ] Запросы к LLM (облачные ключи)
- [ ] `npm test` для Node-стенда (порт 3000 занят чужим процессом — на другом порту)
- [ ] Второй экземпляр бота на том же токене НЕ поднимать; что проверить в Telegram руками — в REPORT.md

## Шаг 5 — Отчёт — В РАБОТЕ
- [ ] REPORT.md

---
Обновляется по ходу работы.
