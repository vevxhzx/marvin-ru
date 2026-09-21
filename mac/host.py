#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Меню-бар / «приложение» для macOS (и Linux): ядро без чёрного окна.

Запуск: из Marvin.app или  .venv/bin/python mac/host.py
· поднимает run.py в фоне
· иконка в строке меню: сайт · статус · перезапуск · выход
· браузер сам при первом старте / если ещё не открыт
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

LOG = ROOT / "data" / "host.log"
LOG.parent.mkdir(parents=True, exist_ok=True)

# без GUI-диалогов setup/browser из run.py — ими рулит host
os.environ.setdefault("ASSISTANT_NO_BROWSER", "1")
os.environ.setdefault("PYTHONUNBUFFERED", "1")


def _log(msg: str) -> None:
    line = time.strftime("%H:%M:%S ") + msg
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def _venv_python() -> Path:
    return ROOT / ".venv" / "bin" / "python"


def _ensure_venv() -> Path:
    py = _venv_python()
    if py.exists():
        return py
    _log("нет .venv — ставлю (первый запуск, 2–5 мин)…")
    # системный python3
    base = sys.executable
    r = subprocess.call([base, str(ROOT / "setup.py")])
    if r != 0 or not py.exists():
        _notify("Ассистент", "Установка не вышла. Смотри data/host.log")
        sys.exit(1)
    _log("установка ок")
    return py


def _port() -> int:
    try:
        from core.config import cfg
        return int(getattr(getattr(cfg, "server", None), "port", 8765) or 8765)
    except Exception:
        return 8765


def _title() -> str:
    try:
        from core import identity
        return identity.title()
    except Exception:
        return "Марвин"


def _health_ok(port: int, timeout: float = 0.6) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _notify(title: str, text: str) -> None:
    if sys.platform != "darwin":
        return
    # экранируем для AppleScript
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.Popen(
        ["osascript", "-e", f'display notification "{esc(text)}" with title "{esc(title)}"'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class Core:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.py = _ensure_venv()
        self.port = _port()
        self.name = _title()
        self._lock = threading.Lock()

    def running(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        return _health_ok(self.port)

    def start(self) -> None:
        with self._lock:
            if _health_ok(self.port):
                _log(f"ядро уже на :{self.port}")
                return
            if self.proc and self.proc.poll() is None:
                return
            logf = (ROOT / "data" / "core.log").open("a", encoding="utf-8")
            env = os.environ.copy()
            env["ASSISTANT_NO_BROWSER"] = "1"
            self.proc = subprocess.Popen(
                [str(self.py), str(ROOT / "run.py")],
                cwd=str(ROOT),
                env=env,
                stdout=logf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            _log(f"ядро pid={self.proc.pid}")

    def stop(self) -> None:
        with self._lock:
            # свой потомок
            if self.proc and self.proc.poll() is None:
                try:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                except Exception:
                    self.proc.terminate()
                try:
                    self.proc.wait(timeout=8)
                except Exception:
                    try:
                        os.killpg(self.proc.pid, signal.SIGKILL)
                    except Exception:
                        pass
                self.proc = None
            # чужой (автозапуск / старый start.command) — по порту
            try:
                out = subprocess.check_output(
                    ["lsof", f"-tiTCP:{self.port}", "-sTCP:LISTEN"],
                    text=True, stderr=subprocess.DEVNULL,
                ).strip()
                for pid in out.split():
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(0.4)

    def restart(self) -> None:
        self.stop()
        time.sleep(0.6)
        self.start()
        self.wait_ready(25)

    def wait_ready(self, sec: float = 30) -> bool:
        t0 = time.time()
        while time.time() - t0 < sec:
            if _health_ok(self.port):
                return True
            if self.proc and self.proc.poll() is not None:
                _log(f"ядро вышло с кодом {self.proc.returncode}")
                return False
            time.sleep(0.4)
        return False

    def open_site(self) -> None:
        url = f"http://127.0.0.1:{self.port}/"
        try:
            from core.config import setup_done
            if not setup_done():
                url = f"http://127.0.0.1:{self.port}/setup"
        except Exception:
            pass
        webbrowser.open(url)


def _icon_image():
    """Иконка для трея: web/public/icon-512.png → маленький RGBA."""
    try:
        from PIL import Image
    except ImportError:
        return None
    for p in (ROOT / "web" / "site" / "icon-512.png", ROOT / "web" / "public" / "icon-512.png"):
        if p.exists():
            im = Image.open(p).convert("RGBA")
            im = im.resize((64, 64), Image.Resampling.LANCZOS)
            return im
    # запасная точка
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((8, 8, 56, 56), fill=(59, 91, 255, 255))
    return im


def _ensure_pystray(py: Path) -> bool:
    try:
        import pystray  # noqa: F401
        return True
    except ImportError:
        _log("ставлю pystray + pillow…")
        r = subprocess.call([str(py), "-m", "pip", "install", "pystray", "pillow", "-q",
                             "--disable-pip-version-check"])
        if r != 0:
            return False
        try:
            import pystray  # noqa: F401
            return True
        except ImportError:
            return False


def run_tray(core: Core) -> None:
    import pystray
    from pystray import MenuItem as Item

    state = {"mode": "start"}  # start / ok / down

    def set_mode(m: str) -> None:
        state["mode"] = m
        try:
            icon.title = f"{core.name} · " + {"ok": "онлайн", "down": "нет связи", "start": "запуск…"}[m]
            # лёгкая смена вида — перерисовать
            if icon.icon:
                icon.icon = icon.icon
        except Exception:
            pass

    def open_site(icon=None, item=None):
        if not core.running():
            core.start()
            core.wait_ready(20)
        core.open_site()

    def do_restart(icon=None, item=None):
        set_mode("start")
        _notify(core.name, "Перезапускаю…")
        threading.Thread(target=lambda: (core.restart(), set_mode("ok" if core.running() else "down"),
                                         _notify(core.name, "Готово" if core.running() else "Не поднялся — data/core.log")),
                         daemon=True).start()

    def open_data(icon=None, item=None):
        path = ROOT / "data"
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def quit_(icon=None, item=None):
        _log("выход")
        try:
            icon.stop()
        except Exception:
            pass
        core.stop()
        os._exit(0)

    def status_text(item=None):
        if state["mode"] == "ok" or core.running():
            return f"● онлайн  :{core.port}"
        if state["mode"] == "start":
            return "○ запуск…"
        return "○ нет связи"

    menu = pystray.Menu(
        Item(lambda item: f"{core.name}", None, enabled=False),
        Item(status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        Item("Открыть сайт", open_site, default=True),
        Item("Перезапустить", do_restart),
        Item("Папка данных", open_data),
        pystray.Menu.SEPARATOR,
        Item("Выйти", quit_),
    )

    img = _icon_image()
    icon = pystray.Icon("marvin", img, f"{core.name} · запуск", menu)

    def boot():
        core.start()
        ok = core.wait_ready(45)
        set_mode("ok" if ok else "down")
        if ok:
            _notify(core.name, "Работает. Кликни иконку → «Открыть сайт».")
            # первый раз / setup — сразу браузер
            try:
                from core.config import setup_done
                first = not setup_done()
            except Exception:
                first = True
            if first or os.environ.get("MARVIN_OPEN") == "1":
                core.open_site()
        else:
            _notify(core.name, "Не запустился. data/core.log и data/host.log")

        while True:
            time.sleep(8)
            if not icon.visible:
                break
            alive = core.running()
            set_mode("ok" if alive else "down")

    threading.Thread(target=boot, daemon=True).start()
    icon.run()


def run_headless(core: Core) -> None:
    """Без pystray — только фон + браузер (хуже, но хоть как-то)."""
    _log("pystray недоступен — режим без меню")
    core.start()
    if core.wait_ready(45):
        core.open_site()
        _notify(core.name, f"Сайт http://127.0.0.1:{core.port}/  · стоп: kill в Мониторинге системы")
    else:
        _notify(core.name, "Не запустился — data/core.log")
        sys.exit(1)
    try:
        while core.running():
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    core.stop()


def main() -> int:
    _log(f"host start · root={ROOT}")
    core = Core()
    if _ensure_pystray(core.py):
        try:
            run_tray(core)
            return 0
        except Exception as e:
            _log(f"tray fail: {e}")
    run_headless(core)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except SystemExit:
        raise
    except Exception as e:
        _log(f"fatal: {e}")
        _notify("Ассистент", f"Ошибка: {e}")
        sys.exit(1)
