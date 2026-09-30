# Откат (rollback) — как вернуться назад одной командой

Готово перед этапом 1 (доводка v0.13.0).

## Где лежат бэкапы

| Что | Путь |
|---|---|
| Файл базы (перед стартом работ) | `backups/jarvis-20260930-1414.db` |
| Файл базы (перед каждой миграцией) | `backups/jarvis-<дата-время>.db` |
| Полная копия проекта (без `node_modules`, `.venv`) | `..\marvin-backup-20260930-1414\` |
| Штатные ночные бэкапы | `data/backups/jarvis-YYYYMMDD-0300.db` |

Копии проекта/БД в git не коммитятся — путь `backups/` и `data/` в `.gitignore`.

## Откат — одной командой

**Код** (вся ветка `polish-v0.13` — на состояние «до доводки»):

```bat
git checkout merge-marvin
```

Отдельный коммит: `git revert <hash>`.

**База** — сначала остановите ядро (закройте `start.bat`), затем:

```bat
copy /Y backups\jarvis-20260930-1414.db data\jarvis.db
```

(`.db-wal`/`.db-shm` удалить, если остались: `del data\jarvis.db-wal data\jarvis.db-shm`.)

**Вся папка целиком**: закройте Jarvis и замените `jarvis-main\` на `..\marvin-backup-20260930-1414\` (та же структура).

## Правило на будущее

Перед любой правкой схемы БД или миграцией — сначала копия файла базы:

```bat
.venv\Scripts\python.exe -c "import sqlite3,datetime;p='backups/jarvis-'+datetime.datetime.now():%Y%m%d-%H%M+'.db';s=sqlite3.connect('data/jarvis.db');d=sqlite3.connect(p);s.backup(d);d.close();s.close();print(p)"
```
