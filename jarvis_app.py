"""Единое окно Джарвиса для Windows: поднимает локальное ядро (если оно ещё не запущено)
и показывает тот же сайт из web/site. Если ядро уже работает (например, запущено start.bat) —
второй процесс НЕ поднимаем: порт и токен Telegram должны быть одни.

PyWebView используется, если установлен; без него окно открывается в браузере.
Диагностика без запуска: python jarvis_app.py --check
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _config_port() -> int:
    """Порт — из config.yaml (server.port), иначе из ASSISTANT_PORT, иначе 8765.
    Так окно не стучится «не в ту дверь», если порт в настройках меняли."""
    env = os.getenv("ASSISTANT_PORT", "")
    if env.isdigit():
        return int(env)
    try:
        import yaml
        with open(ROOT / "config.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        port = (data.get("server") or {}).get("port")
        if port:
            return int(port)
    except Exception:
        pass
    return 8765


PORT = _config_port()
URL = f"http://127.0.0.1:{PORT}/"


def _title() -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from core import identity
        return identity.title()
    except Exception:
        return "Джарвис"


def healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}api/health", timeout=0.7) as r:
            return r.status == 200
    except Exception:
        return False


def wait_ready(proc: subprocess.Popen | None, timeout: float = 60) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if healthy():
            return True
        if proc is not None and proc.poll() is not None:
            return healthy()   # run.py мог выйти с «порт занят» (3) — но ядро уже отвечает
        time.sleep(0.35)
    return False


def check() -> int:
    """Проверка без запуска: порт, ядро, движок окна, собранный сайт, run.py."""
    import importlib.util
    print(f"папка:     {ROOT}")
    print(f"python:    {sys.executable}")
    print(f"порт:      {PORT}")
    print(f"ядро:      {'уже работает' if healthy() else 'не запущено'}")
    print(f"pywebview: {'есть' if importlib.util.find_spec('webview') else 'нет (окно откроется в браузере)'}")
    print(f"сайт:      {'собран (web/site)' if (ROOT / 'web' / 'site' / 'index.html').exists() else 'НЕ СОБРАН — нужен npm run build в web'}")
    print(f"run.py:    {'есть' if (ROOT / 'run.py').exists() else 'НЕТ'}")
    return 0


def main() -> int:
    if "--check" in sys.argv:
        return check()
    # остальные аргументы уходят в run.py (например --no-tg: поднять ядро без Telegram — удобно для проверки)
    extra = [a for a in sys.argv[1:] if a != "--check"]
    spawned: subprocess.Popen | None = None
    if healthy():
        print(f"Ядро уже работает на {URL} — подключаюсь к нему, второй экземпляр не поднимаю.")
    else:
        env = os.environ.copy()
        env.setdefault("ASSISTANT_NO_BROWSER", "1")
        spawned = subprocess.Popen([sys.executable, str(ROOT / "run.py"), *extra], cwd=ROOT, env=env)
        if not wait_ready(spawned):
            print("Не удалось поднять ядро. Что именно не так:  %s jarvis_app.py --check" % sys.executable)
            print("Если проект ставился впервые — сначала install.bat, затем start.bat.")
            return spawned.returncode or 1
    try:
        try:
            import webview
        except ImportError:
            print("pywebview не установлен — открываю сайт в браузере.")
            print("Отдельное окно: pip install -r requirements-windows.txt")
            webbrowser.open(URL)
            if spawned is not None:
                return spawned.wait()
            return 0
        webview.create_window(_title(), URL, width=1280, height=860, min_size=(720, 520), text_select=True)
        webview.start()
        return 0
    finally:
        # гасим ядро только если подняли его сами; чужой запущенный процесс не трогаем
        if spawned is not None and spawned.poll() is None:
            spawned.terminate()
            try:
                spawned.wait(timeout=8)
            except subprocess.TimeoutExpired:
                spawned.kill()


if __name__ == "__main__":
    raise SystemExit(main())
