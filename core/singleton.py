"""Один экземпляр ядра: файл-блокировка data/.db.lock (JSON: pid + started_at).

Порт-проба в run.py ловит «второе окно» только когда порт уже занят; блокировка
ловит раньше и точнее — второй процесс вообще не трогает базу (ни init_db, ни
Telegram-сессию не отбирает). Новая зависимость не нужна: на Windows — ctypes
OpenProcess для проверки чужого PID + msvcrt.locking на файле, на POSIX —
os.kill(pid, 0) + fcntl.flock.

Протокол: acquire() держит открытый файл (модульный глобал) до release().
Чужой живой PID (или неубираемая OS-блокировка) → отказ, мёртвый → stale,
перезаписываем. data/ уже в .gitignore, отдельно .db.lock добавлять не надо.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

LOCK_NAME = ".db.lock"

_held = None  # файловый объект удерживаемой блокировки (in-process guard)


def lock_path():
    from .config import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / LOCK_NAME


def pid_alive(pid) -> bool:
    """Жив ли чужой процесс. Неизвестность = считаем живым (безопасное направление)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            try:
                # Зомби с открытыми хендлами (тест-харнесс держит Popen): процесс
                # уже завершён, но OpenProcess его ещё «видит» — смотрим код выхода.
                code = ctypes.c_ulong()
                if k.GetExitCodeProcess(h, ctypes.byref(code)) and int(code.value) != 259:
                    return False  # STILL_ACTIVE=259 — всё остальное значит «мёртв»
            finally:
                k.CloseHandle(h)
            return True
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _proc_started_at(pid: int):
    """Время старта чужого процесса (ISO) — защита от переиспользования PID.

    Windows агрессивно выдаёт PID погибших процессов новым: один PID в лок-файле
    ещё не значит, что держит его тот же запуск. Сверяем со started_at из файла.
    Не удалось узнать — None (тогда решает эвристика по mtime, см. acquire)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0 or pid == os.getpid():
        return None
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class _FT(ctypes.Structure):
            _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        try:
            created, _e, _k, _u = _FT(), _FT(), _FT(), _FT()
            if not k.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(_e),
                                     ctypes.byref(_k), ctypes.byref(_u)):
                return None
            ticks = (created.high << 32) + created.low  # 100нс с 1601-01-01
            unix = ticks / 10_000_000 - 11_644_473_600
            return datetime.fromtimestamp(unix).isoformat(timespec="seconds")
        finally:
            k.CloseHandle(h)
    except Exception:
        return None


def _parse_lock(raw: str) -> dict:
    try:
        d = json.loads(raw.lstrip("\x00 ").strip() or "{}")
        return {"pid": int(d.get("pid", 0) or 0), "started_at": str(d.get("started_at", "") or "")}
    except Exception:
        return {"pid": 0, "started_at": ""}


def _read_pid(path) -> int:
    """Best-effort чтение чужого PID (под OS-блокировкой на Windows может не открыться — тогда 0)."""
    try:
        return _parse_lock(path.read_text(encoding="utf-8"))["pid"]
    except Exception:
        return 0


def _same_startup(old_pid: int, old_started: str) -> bool | None:
    """Тот же ли запуск держит файл: False — точно чужой/переиспользованный PID,
    True — похоже тот же, None — неизвестно (решает mtime-эвристика)."""
    if not old_pid or old_pid == os.getpid():
        return False
    if not pid_alive(old_pid):
        return False  # процесса уже нет — файл точно stale
    proc_started = _proc_started_at(old_pid)
    if not proc_started or not old_started:
        return None
    try:
        skew = abs((datetime.fromisoformat(proc_started) -
                    datetime.fromisoformat(old_started)).total_seconds())
    except ValueError:
        return True
    return skew <= 60


def acquire() -> str | None:
    """Занять блокировку. None — ок; иначе текст причины (второй экземпляр — отказ)."""
    global _held
    if _held is not None:
        return "блокировка уже удерживается этим процессом"
    p = lock_path()
    try:
        if not p.exists() or p.stat().st_size == 0:
            p.write_bytes(b"\x00")
    except OSError:
        return f"нет доступа к {p}"
    f = open(p, "r+b")
    try:
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                f.close()
                return f"другой экземпляр держит {p} (pid {_read_pid(p) or '?'})"
        else:
            try:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.close()
                return f"другой экземпляр держит {p} (pid {_read_pid(p) or '?'})"
    except ImportError:
        pass  # нет msvcrt/fcntl — остаётся только проверка PID ниже
    # Читаем/пишем через ТОТ ЖЕ handle: на Windows чужая (и даже своя вторая)
    # OS-блокировка не даёт открыть файл повторно — второй open упал бы с PermissionError.
    try:
        f.seek(0)
        old = _parse_lock(f.read().decode("utf-8", "replace"))
    except OSError:
        old = {"pid": 0, "started_at": ""}
    same = _same_startup(old["pid"], old["started_at"])
    if same is None:
        # Время старта неизвестно: эвристика — свежий файл + живой PID считаем
        # чужим запуском (покрывает старый код без OS-блокировок), остальное stale.
        try:
            fresh = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() < 120
        except OSError:
            fresh = False
        same = bool(old["pid"]) and fresh and pid_alive(old["pid"])
    if same:
        # Живой чужой процесс (например, старый запуск без OS-блокировки) — не перезаписываем.
        try:
            f.close()
        except Exception:
            pass
        return f"уже запущен (pid {old['pid']})"
    try:
        f.seek(0)
        f.truncate()
        f.write(json.dumps({"pid": os.getpid(),
                            "started_at": datetime.now().isoformat(timespec="seconds")}).encode("utf-8"))
        f.flush()
    except OSError:
        try:
            f.close()
        except Exception:
            pass
        return f"не удалось записать {p}"
    _held = f
    return None


def release() -> None:
    """Отпустить блокировку (best effort — вызывается из finally при остановке)."""
    global _held
    f, _held = _held, None
    if f is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            try:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    except ImportError:
        pass
    finally:
        try:
            f.close()
        except Exception:
            pass
    try:
        lock_path().unlink(missing_ok=True)
    except OSError:
        pass
