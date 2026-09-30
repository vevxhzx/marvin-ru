"""Единое окно Marvin для Windows: запускает локальное ядро и показывает тот же сайт.
PyWebView используется, если установлен; при его отсутствии открывается запасное окно браузера.
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
PORT = int(os.getenv("ASSISTANT_PORT", "8765"))
URL = f"http://127.0.0.1:{PORT}/"


def healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}api/health", timeout=0.7) as r:
            return r.status == 200
    except Exception:
        return False


def wait_ready(proc: subprocess.Popen, timeout: float = 45) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if healthy():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.35)
    return False


def main() -> int:
    env = os.environ.copy()
    env.setdefault("ASSISTANT_NO_BROWSER", "1")
    proc = subprocess.Popen([sys.executable, str(ROOT / "run.py")], cwd=ROOT, env=env)
    try:
        if not wait_ready(proc):
            return proc.returncode or 1
        try:
            import webview
        except ImportError:
            webbrowser.open(URL)
            return proc.wait()
        webview.create_window("Marvin", URL, width=1280, height=860, min_size=(720, 520), text_select=True)
        webview.start()
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
