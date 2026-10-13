"""Перезапуск ядра (после мастра первого запуска, руками из настроек, автоперезапуск).

Почему отдельный модуль, а не код в `core/api/routers/setup.py`:

* `tests/test_review_e_errors.py::test_no_time_sleep_in_api_package` запрещает
  `time.sleep` где-либо в `core/api` — event loop не должен стоять на паузе. Здесь,
  наоборот, пауза и есть задача: дождаться, пока старый процесс освободит порт,
  и только потом поднимать новый.
* Работа с процессами (родительский скрипт, `os._exit`, DETACHED_PROCESS) — не
  «роутер», и в API-пакете ей не место.

Как это работает:

1. **Есть надзиратель** (`start.bat` / `start.command` / `mac/launcher.sh`) — он сам
   перезапускает ядро до трёх раз. Достаточно выйти из процесса, второй экземпляр
   не нужен (иначе новый стартует раньше, чем старый освободит порт).
2. **Надзирателя нет** — поднимаем отдельный процесс-помощник: он ждёт наш PID,
   потом запускает `run.py` в том же интерпретаторе с теми же флагами.
3. **Запуск не через `run.py`** (uvicorn/wsgi/стенд) или тесты — честно отвечаем
   «перезапустите вручную»: изображать перезапуск нельзя, настройки-то уже сохранены.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from ..config import ROOT

log = logging.getLogger("jarvis.restart")

# Сколько ждём ответа браузеру, прежде чем уйти (страница сразу шлёт /api/health).
EXIT_DELAY = 1.2
# Скрипты, которые сами поднимают ядро заново.
SUPERVISORS = ("start.bat", "start.command", "start.sh", "launcher.sh", "launchd")


def is_test_run() -> bool:
    """Тесты и внешние стенды: ядро не перезапускаем — иначе pytest просто умрёт."""
    return bool(os.getenv("ASSISTANT_TEST") or os.getenv("JARVIS_TEST"))


def supervisor() -> Optional[str]:
    """Есть ли скрипт-надзиратель, который перезапустит нас сам (start.bat и т.п.)."""
    try:
        import psutil
        cmd = " ".join(psutil.Process(os.getppid()).cmdline() or [])
    except Exception:
        return None
    low = (cmd or "").lower()
    for marker in SUPERVISORS:
        if marker in low:
            return marker
    return None


def relaunch_argv() -> Optional[list[str]]:
    """Команда, которой можно поднять это же ядро снова: тот же интерпретатор и тот же run.py.

    None — процесс запущен не через run.py (uvicorn/wsgi/тест), и перезапуск себе не вернуть.
    """
    entry = ROOT / "run.py"
    if not entry.exists() or Path(sys.argv[0] or "").name not in ("run.py", "run.pyc"):
        return None
    flags = [a for a in sys.argv[1:] if a == "--no-tg"]   # сохраняем только флаги запуска
    return [sys.executable, str(entry), *flags]


def spawn_relauncher(argv: list[str]) -> bool:
    """Поднять новое ядро отдельным процессом.

    Сначала запускаем помощника, который ждёт наш PID (иначе новое ядро стартует,
    пока порт ещё занят, и увидит «порт занят» вместо «я перезапустился»), а тот уже
    запускает `run.py`. На Windows помощник получает своё окно консоли — лог ядра
    видно в нём; на macOS/Linux — своя сессия, чтобы не умереть вместе с терминалом.
    """
    code = ("import os,subprocess,sys,time\n"
            "pid,root=int(sys.argv[1]),sys.argv[2]\n"
            "for _ in range(240):\n"
            "    try: os.kill(pid,0)\n"
            "    except OSError: break\n"
            "    time.sleep(0.25)\n"
            "subprocess.Popen(sys.argv[3:],cwd=root)\n")
    kw: dict = {"cwd": str(ROOT), "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kw["start_new_session"] = True
    subprocess.Popen([sys.executable, "-c", code, str(os.getpid()), str(ROOT), *argv], **kw)
    return True


def schedule_exit(delay: float = EXIT_DELAY) -> None:
    """Выйти из процесса, дав ответу уйти браузеру.

    `os._exit`, а не `sys.exit`: иначе uvicorn успевает закрыть сокеты и повиснуть
    на finally (см. shutdown в run.py). Поток демон — на случай, если до этого дойдёт
    не очередь: процесс всё равно умрёт вместе с нами.
    """
    threading.Timer(delay, lambda: os._exit(0)).start()


def plan() -> dict:
    """Что реально можно сделать, ничего не делая. Честность важнее удобства:
    если надёжно нельзя — так и говорим «перезапустите вручную»."""
    if is_test_run():
        return {"ok": False, "manual": True, "how": "test",
                "detail": "тестовый запуск — ядро не перезапускаю"}
    sup = supervisor()
    if sup:
        return {"ok": True, "manual": False, "how": "supervisor", "detail": f"Перезапускаю через {sup}."}
    if relaunch_argv() is None:
        return {"ok": False, "manual": True, "how": "unknown",
                "detail": "Ядро запущено не через run.py — перезапустите его вручную (start.bat), "
                          "настройки уже сохранены."}
    return {"ok": True, "manual": False, "how": "spawn", "detail": "Перезапускаю ядро в новом окне."}