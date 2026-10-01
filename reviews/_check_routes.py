r"""Контрольный скрипт для шагов ФАЗЫ 7 (см. `reviews/P7_refactor.md` §7).

Запуск (из корня репозитория):
    .venv\Scripts\python.exe reviews\_check_routes.py > before.json
    .venv\Scripts\python.exe reviews\_check_routes.py > after.json

Печатает ОТСОРТИРОВАННЫЙ список `[path, [методы...]]` по всем роутам приложения.
Роутеры, подключённые через `include_router` (CRM, `core/api/routers/*`), в
FastAPI 0.141 лежат как вложенные `_IncludedRouter`, поэтому обход рекурсивный —
иначе список «до» и «после» несопоставим.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.api.app as a  # noqa: E402


def walk(routes, out):
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":
            walk(r.original_router.routes, out)
            continue
        p = getattr(r, "path", None)
        if p is None:
            continue
        out.append([p, sorted(getattr(r, "methods", []) or [])])


out = []
walk(a.app.router.routes, out)
out.sort()
print(json.dumps(out, ensure_ascii=False, indent=1))
print(f"# top-level entries on app.router.routes: {len(a.app.router.routes)}", file=sys.stderr)
print(f"# flat routes: {len(out)}", file=sys.stderr)
