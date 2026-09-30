# -*- coding: utf-8 -*-
"""Доктор Marvin: показывает, что установлено, чего не хватает и что чинить.

Запуск:  doctor.bat  (Windows)  ·  ./doctor.sh  (Linux/macOS)  ·  python doctor.py
Только стандартная библиотека — работает даже если зависимости ещё не поставились.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN = sys.platform == "win32"
PY = ROOT / ".venv" / ("Scripts/python.exe" if IS_WIN else "bin/python")
DB = ROOT / "data" / "assistant.db"
SITE = ROOT / "web" / "site" / "index.html"

OK = "[+]"
BAD = "[!]"
WARN = "[~]"

problems: list[tuple[str, str]] = []   # (что не так, что делать)
notes: list[str] = []


def line(mark: str, text: str, hint: str = "") -> None:
    print(f"  {mark} {text}" + (f"\n      → {hint}" if hint else ""))


def fix(what: str, how: str) -> None:
    problems.append((what, how))


def _has(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def _read_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def check_python() -> None:
    print("\n  Python")
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    in_venv = Path(sys.prefix).name in (".venv", "venv")
    if v < (3, 10):
        line(BAD, f"Python {ver} — слишком старый", "нужен 3.11+ (лучше 3.11–3.13): https://www.python.org/downloads/")
        fix("старый Python", "поставить Python 3.11–3.13 и запустить install.bat")
    elif v[:2] > (3, 13):
        line(WARN, f"Python {ver} — новее проверенных (3.11–3.13), может не найтись готовых сборок",
             "если установка падает — поставьте Python 3.12 и запустите install.bat заново")
    else:
        line(OK, f"Python {ver}" + ("  (в .venv)" if in_venv else ""))
    if not in_venv and PY.exists():
        notes.append("доктор запущен обычным Python, а не из .venv — это нормально для проверки")


def check_venv() -> None:
    print("\n  Окружение")
    if PY.exists():
        line(OK, "виртуальное окружение .venv на месте")
    else:
        line(BAD, ".venv нет", "запустите install.bat (Windows) или ./install.sh (Linux/macOS)")
        fix("нет .venv", "install.bat / ./install.sh")


def check_packages() -> None:
    print("\n  Библиотеки (обязательные)")
    required = {
        "fastapi": "fastapi", "uvicorn": "uvicorn", "sqlmodel": "sqlmodel",
        "aiogram": "aiogram", "apscheduler": "apscheduler", "yaml": "pyyaml",
        "httpx": "httpx", "dateutil": "python-dateutil", "segno": "segno",
        "psutil": "psutil", "PIL": "Pillow", "multipart": "python-multipart",
    }
    missing = [pipname for mod, pipname in required.items() if not _has(mod)]
    if missing:
        line(BAD, "не хватает: " + ", ".join(missing), "запустите install.bat (он доставит зависимости)")
        fix("не хватает библиотек: " + ", ".join(missing), "install.bat / ./install.sh")
    else:
        line(OK, "все обязательные на месте")

    print("\n  Библиотеки (по желанию — голос, окно приложения)")
    optional = {"faster_whisper": "faster-whisper", "edge_tts": "edge-tts", "av": "av",
                "numpy": "numpy", "torch": "torch", "webview": "pywebview"}
    for mod, pipname in optional.items():
        if _has(mod):
            line(OK, pipname)
    if not _has("faster_whisper") and not _has("edge_tts"):
        line(WARN, "голос не установлен — это нормально, если он не нужен",
             "хочешь голос: install_voice.bat (Windows) и voice.bat")


def check_config() -> None:
    print("\n  Настройки")
    cfg_file = ROOT / "config.yaml"
    env_file = ROOT / ".env"
    if cfg_file.exists():
        line(OK, "config.yaml есть")
    else:
        line(BAD, "config.yaml нет", "запустите install.bat — он создаст из config.example.yaml")
        fix("нет config.yaml", "install.bat")
    if env_file.exists():
        line(OK, ".env есть")
    else:
        line(WARN, ".env нет", "не обязательно: всё настраивается в config.yaml или на сайте")

    cfg = _read_yaml(cfg_file) if cfg_file.exists() else {}
    token = str(cfg.get("telegram", {}).get("token") or os.getenv("ASSISTANT_TG_TOKEN") or "")
    owner = cfg.get("telegram", {}).get("owner_id") or os.getenv("ASSISTANT_TG_OWNER") or 0
    if token and int(owner or 0) > 0:
        line(OK, "Telegram настроен (токен + ваш ID)")
    else:
        line(WARN, "Telegram не настроен", "это необязательно; включить можно на сайте → настройки, или в мастере при первом запуске")

    mode = str(cfg.get("brain", {}).get("mode") or "hybrid")
    line(OK, f"режим мозга: {mode}" + ("  (в облако ничего не уходит)" if mode == "local" else ""))


def check_data() -> None:
    print("\n  Данные")
    data = ROOT / "data"
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        line(OK, "папка data/ доступна для записи")
    except Exception as e:
        line(BAD, f"папка data/ недоступна для записи ({e})", "проверьте права доступа к папке проекта")
        fix("data/ недоступна для записи", "дать права на папку проекта")
    if DB.exists():
        line(OK, f"база есть ({DB.stat().st_size / 1024:.0f} КБ)")
    else:
        line(WARN, "базы ещё нет", "создастся сама при первом запуске start.bat")


def check_site() -> None:
    print("\n  Интерфейс")
    if SITE.exists():
        line(OK, "собранная версия сайта на месте (web/site)")
    else:
        has_node = shutil.which("npm") is not None
        line(WARN, "нет сборки web/site",
             "запустите build_web.bat " + ("(Node найден)" if has_node else "(нужен Node.js: https://nodejs.org)"))
        notes.append("без web/site сайт не откроется — но Telegram и голос работать будут")


def check_ollama() -> None:
    print("\n  Локальная модель (Ollama)")
    url = os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434"
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/tags", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        models = [m.get("name", "") for m in data.get("models", [])]
        if models:
            line(OK, f"Ollama отвечает, моделей: {len(models)} ({', '.join(models[:3])}{'…' if len(models) > 3 else ''})")
        else:
            line(WARN, "Ollama отвечает, но моделей нет", "загрузите модель: ollama pull qwen2.5:3b")
    except Exception:
        line(WARN, "Ollama не отвечает", "это нормально для режима cloud; для local/hybrid поставьте https://ollama.com/download")
        notes.append("без Ollama работают режим cloud и все офлайн-команды Telegram")


def check_extras() -> None:
    print("\n  Прочее")
    if shutil.which("ffmpeg"):
        line(OK, "ffmpeg найден (нужен для некоторых голосовых форматов)")
    else:
        line(WARN, "ffmpeg не найден", "не обязателен: голос работает и без него (OGG/Opus через PyAV)")
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=2).close()
        line(OK, "интернет есть")
    except Exception:
        line(WARN, "интернета нет", "нужен только для облачной модели; локально Marvin работает без него")


def main() -> int:
    print("\n  ================================================")
    print("    Marvin  ·  доктор")
    print("  ================================================")
    check_python()
    check_venv()
    check_packages()
    check_config()
    check_data()
    check_site()
    check_ollama()
    check_extras()

    print("\n  ================================================")
    if problems:
        print("    Что починить:")
        for what, how in problems:
            print(f"      · {what}  →  {how}")
    else:
        print("    Всё, что нужно, на месте. Можно запускать start.bat")
    if notes:
        print("\n    Мелочи:")
        for n in notes:
            print(f"      · {n}")
    print("  ================================================\n")
    return 1 if problems else 0


if __name__ == "__main__":
    if IS_WIN:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
