"""Запуск и перезапуск голосового клиента (voice.bat) со стороны ядра — для кнопок в настройках.

Почему отдельный модуль: ядро и голосовой клиент — разные процессы; раньше voice.bat не запускался из приложения
вообще, и в настройках статус «не запущен» нельзя было исправить одним нажатием. Здесь только Windows и только
свой компьютер (проверка is_local — в app.py). Ничего не удаляем, только открываем новое окно консоли.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("assistant.pc")

ROOT = Path(__file__).resolve().parents[2]
BAT = ROOT / "voice.bat"


def _py_exe() -> Path:
    """Предпочитаем интерпретатор .venv (там стоят голосовые пакеты), иначе текущий."""
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    return venv if venv.exists() else Path(sys.executable)


def running_pids() -> list[int]:
    """PID процессов voice_client.py (наши собственные), чтобы перезапуск не плодил копии и не дрался за микрофон."""
    try:
        import psutil
    except ImportError:
        return []
    me = os.getpid()
    out: list[int] = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if p.info["pid"] == me:
                continue
            cmd = " ".join(p.info.get("cmdline") or [])
            if "voice_client.py" in cmd:
                out.append(p.info["pid"])
        except Exception:  # процесс мог умереть между iter и info
            continue
    return out


def _spawn_detached(args: list[str]) -> None:
    """Открыть отдельное окно консоли, не привязанное к жизни ядра."""
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(args, cwd=str(ROOT), creationflags=flags, close_fds=True)


def stop(wait: float = 5.0) -> dict:
    """Погасить запущенные клиенты. Возвращает, сколько погасили."""
    pids = running_pids()
    if not pids:
        return {"stopped": 0, "pids": []}
    try:
        import psutil
        procs = [psutil.Process(pid) for pid in pids]
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        gone, alive = psutil.wait_procs(procs, timeout=wait)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
        log.info("Голосовой клиент остановлен: %d процесс(ов)", len(pids))
        return {"stopped": len(pids), "pids": pids}
    except Exception as e:  # pragma: no cover
        log.warning("Не удалось остановить голосовой клиент: %s", e)
        return {"stopped": 0, "pids": pids, "error": str(e)[:120]}


def launch(restart: bool = False) -> dict:
    """Открыть voice.bat в новом окне. restart=True — сначала гасим старые копии.
    Возвращает {ok, restarted, stopped, already, error}."""
    if os.name != "nt":
        return {"ok": False, "error": "кнопка работает только на Windows — запустите voice.bat вручную", "restarted": False}
    if not BAT.exists():
        return {"ok": False, "error": f"не нашёл {BAT.name} рядом с ядром", "restarted": False}
    pids = running_pids()
    if pids and not restart:
        return {"ok": True, "already": True, "pids": pids, "restarted": False,
                "message": "голосовой клиент уже запущен — используйте «перезапустить», если он не отвечает"}
    stopped = stop() if (restart and pids) else {"stopped": 0, "pids": []}
    # voice.bat сам перезапускается и берёт .venv-питон; вызываем через cmd start, чтобы окно жило отдельно
    _spawn_detached(["cmd", "/c", "start", "Marvin Voice", str(BAT)])
    log.info("Запускаю голосовой клиент: %s (restart=%s, погашено=%s)", BAT.name, restart, stopped.get("stopped"))
    time.sleep(0.6)   # дать окну появиться, чтобы пульс успел прийти к первому же опросу статуса
    return {"ok": True, "restarted": bool(restart), "stopped": stopped.get("stopped", 0),
            "message": "перезапускаю голосовой клиент" if restart else "запускаю голосовой клиент"}
