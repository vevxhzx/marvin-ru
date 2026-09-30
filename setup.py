# -*- coding: utf-8 -*-
"""Установка Джарвиса. Запускается из install.bat. Только стандартная библиотека Python."""
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


def step(n, text):
    print(f"\n  [{n}/4] {text}")


def main():
    print("\n  ================================================")
    print("    J.A.R.V.I.S.  —  установка")
    print("  ================================================")
    if sys.version_info < (3, 10):
        print(f"\n  [!] Нужен Python 3.10+, у тебя {sys.version.split()[0]}.")
        print("      Скачай: https://www.python.org/downloads/  (галочка 'Add python.exe to PATH')")
        return 1

    step(1, "Создаю виртуальное окружение...")
    if not PY.exists():
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    print("        ок")

    step(2, "Устанавливаю библиотеки (1–3 минуты)...")
    subprocess.check_call([str(PY), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    r = subprocess.call([str(PY), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"), "-q"])
    if r != 0:
        print("  [!] Ошибка установки библиотек. Проверь интернет и запусти install.bat ещё раз.")
        return 1
    print("        ок")

    step(3, "Проверяю настройки...")
    cfg = ROOT / "config.yaml"
    created = False
    if not cfg.exists():
        shutil.copy(ROOT / "config.example.yaml", cfg)
        created = True
        print("        Создан config.yaml")
    else:
        print("        config.yaml уже есть — ок")

    step(4, "Проверяю Ollama (локальный мозг)...")
    if shutil.which("ollama"):
        print("        Ollama найдена. Скачиваю модель qwen2.5:7b (~4.7 ГБ, один раз)...")
        subprocess.call(["ollama", "pull", "qwen2.5:7b"])
    else:
        print("        Ollama не найдена. Для этапа 1 НЕ обязательна.")
        print("        Для умных ответов: https://ollama.com/download , затем в cmd:  ollama pull qwen2.5:7b")

    print("\n  ================================================")
    if created:
        print("    Сейчас откроется config.yaml в Блокноте. Заполни:")
        print("      telegram.token     — токен от @BotFather")
        print("      telegram.owner_id  — твой ID (узнать: бот @userinfobot)")
        print("    Сохрани (Ctrl+S), закрой Блокнот, затем запусти start.bat")
    else:
        print("    Готово! Запускай start.bat")
    print("  ================================================\n")
    if created and sys.platform == "win32":
        os.startfile(str(cfg))  # откроется в программе по умолчанию для .yaml (обычно Блокнот)
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except subprocess.CalledProcessError as e:
        print(f"\n  [!] Команда завершилась с ошибкой: {e}")
        code = 1
    except KeyboardInterrupt:
        code = 1
    input("\n  Нажми Enter, чтобы закрыть...")
    sys.exit(code)
