# -*- coding: utf-8 -*-
"""Установка ассистента. Запускается из install.bat (или `python setup.py` на Linux/Mac).
Только стандартная библиотека Python — работает до установки чего-либо.

Что делает: создаёт .venv, ставит пакеты из requirements.txt, создаёт config.yaml из примера.
Модель и всё остальное выбирается позже в мастере первого запуска (браузер) — здесь ничего не качаем.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    os.system("chcp 65001 >nul")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
STEPS = 3


def _pick_python() -> str:
    """Каким Python создавать .venv. Предпочитаем 3.10–3.14 (под них точно есть все сборки);
    если запущены на более новом — ищем через лаунчер `py` другой установленный, иначе пробуем текущий."""
    v = sys.version_info
    if (3, 10) <= v[:2] <= (3, 14):
        return sys.executable
    if sys.platform == "win32":
        for tag in ("3.14", "3.13", "3.12", "3.11"):
            try:
                out = subprocess.run(["py", f"-{tag}", "-c", "import sys;print(sys.executable)"],
                                     capture_output=True, text=True, timeout=15)
                exe = out.stdout.strip()
                if out.returncode == 0 and exe and Path(exe).exists():
                    print(f"\n  Текущий Python {sys.version.split()[0]} слишком новый — беру найденный Python {tag}: {exe}")
                    return exe
            except Exception:
                pass
    print(f"\n  [i] Python {sys.version.split()[0]} новее проверенных (3.10–3.14). Пробую с ним — обычно работает.")
    return sys.executable


def step(n, text):
    print(f"\n  [{n}/{STEPS}] {text}")


def main():
    print("\n  ================================================")
    print("    Ассистент  —  установка")
    print("  ================================================")
    if sys.version_info < (3, 10):
        print(f"\n  [!] Нужен Python 3.10 или новее, у вас {sys.version.split()[0]}.")
        print("      Скачайте: https://www.python.org/downloads/  (галочка 'Add python.exe to PATH')")
        return 1
    if sys.version_info >= (3, 15):
        # В Python 3.15 удаляют устаревший sqlite3-адаптер datetime — хранение дат
        # (события, задачи, операции) может молча сломаться. Дальше — только осознанно.
        if os.getenv("ASSISTANT_ALLOW_PY315") != "1":
            print(f"\n  [!] Python {sys.version.split()[0]} слишком новый: дальше Python 3.14 не проверяли,")
            print("      а в Python 3.15 удаляют устаревший sqlite3-адаптер datetime — даты могут")
            print("      записаться так, что обратно не прочитаются.")
            print("      Поставьте рядом Python 3.12 (https://www.python.org/downloads/release/python-3120/ , галочка 'Add to PATH'),")
            print("      удалите папку .venv и запустите install.bat ещё раз — либо продолжите на свой")
            print("      риск: set ASSISTANT_ALLOW_PY315=1  и снова python setup.py")
            return 1
        print(f"\n  [!] Python {sys.version.split()[0]} + ASSISTANT_ALLOW_PY315=1: продолжаю на ваш риск —")
        print("      следите за датами (события/задачи/операции) после установки.")
    base = _pick_python()

    step(1, "Создаю виртуальное окружение (.venv)...")
    if not PY.exists():
        subprocess.check_call([base, "-m", "venv", str(VENV)])
    print("        ок")

    # На macOS базовый requirements тянет torch (нужен только для офлайн-озвучки), а у torch
    # на mac нет колёс для Intel и для macOS 13 — установка уходила в сборку из исходников.
    # Поэтому на маке ставим облегчённый набор, а сам torch — отдельным аддоном (install_voice).
    req_name = "requirements-mac.txt" if sys.platform == "darwin" else "requirements.txt"
    if os.getenv("JARVIS_REQUIREMENTS"):
        req_name = os.getenv("JARVIS_REQUIREMENTS")
    step(2, "Устанавливаю библиотеки (2–5 минут, ~300 МБ)...")
    subprocess.call([str(PY), "-m", "pip", "install", "--upgrade", "pip", "-q", "--disable-pip-version-check"])
    r = subprocess.call([str(PY), "-m", "pip", "install", "-r", str(ROOT / req_name), "-q", "--disable-pip-version-check"])
    if r != 0:
        print("  [!] Ошибка установки библиотек.")
        if sys.version_info >= (3, 14) and base == sys.executable:
            print(f"      Скорее всего, дело в слишком новом Python {sys.version.split()[0]}: не под все библиотеки есть готовые сборки.")
            print("      Поставьте рядом Python 3.12 (https://www.python.org/downloads/release/python-3120/ , галочка 'Add to PATH'),")
            print("      удалите папку .venv и запустите install.bat ещё раз — установщик сам выберет 3.12.")
        else:
            print("      Проверьте интернет (иногда нужен VPN для pypi.org) и запустите install.bat ещё раз.")
        return 1
    print("        ок")

    step(3, "Создаю файл настроек...")
    cfg = ROOT / "config.yaml"
    if not cfg.exists():
        shutil.copy(ROOT / "config.example.yaml", cfg)
        print("        Создан config.yaml — заполнять руками не нужно.")
    else:
        print("        config.yaml уже есть — ок")

    print("\n  ================================================")
    print("    Готово! Запустите start.bat — откроется браузер")
    print("    с мастером настройки: имя, мозг под ваше железо, Telegram.")
    print("    Ollama (если хотите локальную модель): https://ollama.com/download")
    print("  ================================================\n")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except subprocess.CalledProcessError as e:
        print(f"\n  [!] Команда завершилась с ошибкой: {e}")
        code = 1
    except KeyboardInterrupt:
        code = 1
    if sys.platform == "win32":
        input("\n  Нажмите Enter, чтобы закрыть...")
    sys.exit(code)
