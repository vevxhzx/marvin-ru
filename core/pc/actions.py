"""Действия на ПК (выполняет voice_client.py на Windows): открыть сайт/программу/файл, найти файл,
медиа-клавиши, скриншот, буфер обмена, статус железа, блокировка/выключение.

Правило безопасности: ассистент НИКОГДА ничего не удаляет. Максимум — открывает и показывает.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

log = logging.getLogger("assistant.pc")
IS_WIN = sys.platform.startswith("win")

# ---------------------------------------------------------------- открыть
def open_url(url: str, api: str = "") -> str:
    if url == "__self__":
        url = api or "http://127.0.0.1:8765"
    webbrowser.open(url)
    return ""


def _start_menu_apps() -> dict[str, Path]:
    """Ярлыки из меню «Пуск» (свой и общий): имя в нижнем регистре → путь к .lnk."""
    out: dict[str, Path] = {}
    roots = [Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
             Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
             Path.home() / "Desktop", Path(os.environ.get("PUBLIC", "")) / "Desktop"]
    for r in roots:
        if r.exists():
            for p in r.rglob("*.lnk"):
                out.setdefault(p.stem.lower(), p)
    return out


_APPS_CACHE: tuple[float, dict[str, Path]] = (0.0, {})


def open_app(name: str) -> str:
    """Запустить программу: по имени exe/команды, иначе ищем ярлык в «Пуске» по подстроке."""
    global _APPS_CACHE
    name = name.strip()
    if name == "__browser__":
        webbrowser.open("about:blank"); return ""
    if name.startswith(("shell:", "ms-settings:")):
        if IS_WIN:
            os.startfile(name)  # type: ignore[attr-defined]
        return ""
    # 1) прямой запуск (calc, notepad, code, chrome…)
    try:
        if IS_WIN:
            subprocess.Popen(f'start "" "{name}"', shell=True)
            time.sleep(0.6)
            # start "" "xyz" при неизвестной программе показывает окно ошибки — проверяем ярлыки заранее ниже
        else:
            subprocess.Popen([name])
        # если это известная команда — на этом всё
        if IS_WIN and _which(name):
            return ""
    except Exception:
        pass
    # 2) ярлыки меню «Пуск»
    if time.time() - _APPS_CACHE[0] > 300:
        _APPS_CACHE = (time.time(), _start_menu_apps())
    apps = _APPS_CACHE[1]
    low = name.lower()
    cands = [k for k in apps if low in k] or [k for k in apps if all(w in k for w in low.split())]
    if cands:
        best = sorted(cands, key=len)[0]
        os.startfile(str(apps[best]))  # type: ignore[attr-defined]
        return f"Запустил {apps[best].stem}."
    if not _which(name):
        return f"Не нашёл программу «{name}» ни в системе, ни в меню «Пуск», сэр."
    return ""


def _which(name: str) -> bool:
    import shutil
    return bool(shutil.which(name) or shutil.which(name + ".exe"))


def open_path(path: str) -> str:
    p = Path(os.path.expandvars(os.path.expanduser(path)))
    if not p.exists():
        return f"Такого пути нет: {path}"
    if IS_WIN:
        os.startfile(str(p))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(p)])
    return ""


# ---------------------------------------------------------------- найти файл
SEARCH_ROOTS = None   # заполняется из config (files.index_dirs) или по умолчанию: пользовательские папки
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "AppData", "$Recycle.Bin", "Windows", "Program Files", "Program Files (x86)", ".venv", "venv", ".cache"}


def _roots() -> list[Path]:
    if SEARCH_ROOTS:
        return [Path(r) for r in SEARCH_ROOTS if Path(r).exists()]
    home = Path.home()
    roots = [home / d for d in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music")]
    roots += [Path(f"{d}:/") for d in "DEF" if Path(f"{d}:/").exists()]
    return [r for r in roots if r.exists()]


def _everything(query: str, limit: int) -> list[Path] | None:
    """Если установлен Everything (voidtools) с es.exe — поиск мгновенный по всему диску."""
    import shutil
    es = shutil.which("es") or shutil.which("es.exe")
    if not es:
        return None
    try:
        out = subprocess.run([es, "-n", str(limit), "-sort", "dm", query], capture_output=True, text=True, timeout=5, encoding="utf-8", errors="ignore")
        return [Path(l) for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        return None


def find_files(query: str, limit: int = 8) -> list[Path]:
    q = query.lower().strip()
    words = [w for w in re.split(r"\s+", q) if w]
    res = _everything(query, limit)
    if res is not None:
        return res
    found: list[tuple[float, Path]] = []
    deadline = time.time() + 6
    for root in _roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames + dirnames:
                low = fn.lower()
                if all(w in low for w in words):
                    p = Path(dirpath) / fn
                    try:
                        found.append((p.stat().st_mtime, p))
                    except OSError:
                        pass
            if time.time() > deadline or len(found) > 200:
                break
        if time.time() > deadline:
            break
    found.sort(key=lambda x: -x[0])
    return [p for _, p in found[:limit]]


def find_and_report(query: str) -> tuple[str, list[str]]:
    """Текст для озвучки + список путей (для чата). Если нашёл ровно один файл — открываем папку с ним."""
    files = find_files(query)
    if not files:
        return f"Ничего похожего на «{query}» не нашёл, сэр.", []
    if len(files) == 1:
        _reveal(files[0])
        return f"Нашёл один файл: {files[0].name}. Открыл папку.", [str(files[0])]
    names = ", ".join(p.name for p in files[:3])
    _reveal(files[0])
    return f"Нашёл {len(files)}: {names}{'…' if len(files) > 3 else ''}. Самый свежий показал в проводнике, список — в чате.", [str(p) for p in files]


def _reveal(p: Path) -> None:
    try:
        if IS_WIN:
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
    except Exception:
        pass


# ---------------------------------------------------------------- медиа-клавиши
_VK = {"pause": 0xB3, "next": 0xB0, "prev": 0xB1, "vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD}


def media(action: str) -> str:
    if not IS_WIN:
        return "Медиа-клавиши доступны только на Windows."
    import ctypes
    vk = _VK.get(action)
    if not vk:
        return ""
    times = 3 if action in ("vol_up", "vol_down") else 1
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.03)
    return ""


# ---------------------------------------------------------------- скриншот / буфер
def screenshot(path: Path) -> Path | None:
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        img.thumbnail((1600, 1600))
        img.save(path, "JPEG", quality=80)
        return path
    except Exception as e:
        log.warning("screenshot failed: %s", e)
        return None


def clipboard_text() -> str:
    if IS_WIN:
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True, text=True, timeout=5, encoding="utf-8", errors="ignore")
            return out.stdout.strip()
        except Exception:
            return ""
    try:
        return subprocess.run(["xclip", "-o", "-selection", "clipboard"], capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------- статус железа («статус костюма»)
def system_status() -> str:
    parts = []
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        parts.append(f"процессор {cpu:.0f}%")
        parts.append(f"память {mem.percent:.0f}% из {mem.total / 2**30:.0f} гигабайт")
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                t = max((x.current for v in temps.values() for x in v if x.current), default=None)
                if t:
                    parts.append(f"температура {t:.0f} градусов")
        except Exception:
            pass
        for d in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(d.mountpoint)
                if u.total > 20 * 2**30:
                    parts.append(f"диск {d.device.rstrip(chr(92))} свободно {u.free / 2**30:.0f} гигабайт")
            except Exception:
                pass
        parts.append(f"работает {int((time.time() - psutil.boot_time()) // 3600)} часов")
    except ImportError:
        parts.append("psutil не установлен — запустите update.bat")
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=4)
        if out.returncode == 0 and out.stdout.strip():
            u, t, mu, mt = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
            parts.append(f"видеокарта {u}%, {t} градусов, видеопамять {int(mu) / 1024:.1f} из {int(mt) / 1024:.0f} гигабайт")
    except Exception:
        pass
    return "Все системы в норме, сэр: " + ", ".join(parts) + "." if parts else "Не смог опросить системы."


def power(kind: str) -> str:
    if not IS_WIN:
        return "Только на Windows."
    import ctypes
    if kind == "lock":
        ctypes.windll.user32.LockWorkStation()
    elif kind == "shutdown":
        subprocess.Popen(["shutdown", "/s", "/t", "30"])
    elif kind == "reboot":
        subprocess.Popen(["shutdown", "/r", "/t", "30"])
    elif kind == "abort":
        subprocess.Popen(["shutdown", "/a"])
    elif kind == "sleep":
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return ""


def running_processes() -> set[str]:
    try:
        import psutil
        return {p.info["name"].lower() for p in psutil.process_iter(["name"]) if p.info.get("name")}
    except Exception:
        return set()


def idle_seconds() -> float:
    """Сколько секунд пользователь не трогал мышь/клавиатуру (Windows)."""
    if not IS_WIN:
        return 0.0
    import ctypes
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    lii = LASTINPUTINFO(); lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
