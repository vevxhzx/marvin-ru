"""Подъём ядра FastAPI на ВРЕМЕННОЙ демо-БД для e2e-стенда (Playwright).

Что делает:
    1. создаёт (или переиспользует) демо-БД из tests/e2e/demo_db.py — в своей папке;
    2. проверяет, что путь БД не может быть настоящим data/jarvis.db (assert_safe);
    3. поднимает uvicorn на свободном порту (--port 0 → свободный) и раздаёт собранный сайт web/site.

Чего НЕ делает (и не должен): Telegram, планировщик, бэкапы, прогрев голоса, Ollama/облако.
Только HTTP API + статика сайта — этого хватает e2e-тестам.

Запуск (обычно это делает web/playwright.config.js через webServer):
    .venv\\Scripts\\python.exe tests\\e2e\\serve.py --port 8900
    .venv\\Scripts\\python.exe tests\\e2e\\serve.py --port 0            # порт выберется сам
    E2E_WORKDIR=%TEMP%\\demo .venv\\Scripts\\python.exe tests\\e2e\\serve.py --port 8900
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import demo_db  # noqa: E402  (рядом, без установки пакета)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="E2E-сервер: FastAPI на демо-БД")
    ap.add_argument("--host", default=os.getenv("E2E_HOST", "127.0.0.1"), help="адрес (по умолчанию 127.0.0.1 — наружу не слушаем)")
    ap.add_argument("--port", type=int, default=int(os.getenv("E2E_PORT", "0")), help="порт; 0 — выбрать свободный")
    ap.add_argument("--workdir", default=os.getenv("E2E_WORKDIR", ""), help="папка стенда (демо-БД и config.yaml)")
    ap.add_argument("--db", default=os.getenv("E2E_DB_PATH", ""), help="файл демо-БД")
    ap.add_argument("--fresh", action="store_true", help="пересоздать демо-БД заново (по умолчанию: если её нет)")
    ap.add_argument("--keep", action="store_true", help="не удалять папку стенда на выходе")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workdir = Path(args.workdir) if args.workdir else demo_db.default_workdir()
    db_path = Path(args.db) if args.db else workdir / "jarvis.db"

    if args.fresh or not db_path.exists():
        demo_db.seed_demo(workdir=workdir, db_path=db_path, fresh=True)
    else:
        # БД уже есть — всё равно уводим ядро на неё и проверяем безопасность
        demo_db.prepare_env(workdir, db_path)
        demo_db.assert_safe(workdir, db_path)
    demo_db.assert_safe(workdir, db_path)

    from core.config import DB_PATH, DATA_DIR, ROOT, setup_done
    if Path(DB_PATH).resolve() == demo_db.REAL_DB.resolve():
        print("[e2e] ОТКАЗ: ядро собралось с настоящей БД — стенд не запускается", file=sys.stderr)
        return 2
    print(f"[e2e] ядро: БД={DB_PATH} · данные={DATA_DIR} · проект={ROOT.name}", file=sys.stderr, flush=True)

    from core import config as core_config
    if not setup_done():
        # на демо-стенде мастер всегда пройден (см. demo_db.make_demo_config); если config.yaml неожиданно
        # не даёт setup.done — не редиректим сайт на /setup, чтобы тесты видели приложение
        core_config.setup_done = lambda: True
        print("[e2e] setup.done=false → для стенда считаем мастер пройденным", file=sys.stderr, flush=True)

    import uvicorn
    from core.api.app import app

    print(f"[e2e] uvicorn: http://{args.host}:{args.port} (Ctrl+C — остановить)", file=sys.stderr, flush=True)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    except OSError as e:      # порт занят — понятное сообщение вместо трейса
        print(f"[e2e] не удалось занять порт {args.port}: {e}. Задайте другой: E2E_PORT=8901", file=sys.stderr)
        return 3
    finally:
        if not args.keep and not os.getenv("E2E_WORKDIR"):
            print(f"[e2e] демо-данные оставлены в {workdir} (E2E_WORKDIR не задан — не удаляю)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())