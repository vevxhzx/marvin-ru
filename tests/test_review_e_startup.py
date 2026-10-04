"""Ревью E «Надёжность» — часть 4: старт/остановка `run.py`.

Сценарии (каждый — реальный подпроцесс `<текущий интерпретатор> run.py --no-tg`,
свободный порт, всё в tmp: JARVIS_CONFIG / JARVIS_DATA_DIR / JARVIS_DB_PATH):

  * занятый порт → процесс завершается с кодом 3 и внятным сообщением, а не висит;
  * битый файл БД → процесс завершается (не висит) с сообщением об ошибке;
  * нет config.yaml → откат на config.example.yaml, мастер первого запуска;
  * нормальный старт → /api/health отвечает; второй экземпляр отклоняется;
  * повторный запуск на той же базе → поднимается заново (миграции идемпотентны).

Гарантия очистки: фикстура `spawned` гасит все подпроцессы в teardown.
Настоящие config.yaml / data/jarvis.db не изменяются.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("ASSISTANT_TEST", "1")

import httpx  # noqa: E402
import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# Интерпретатор ТОГО ЖЕ окружения, в котором идёт pytest: в venv локально это .venv/Scripts/python.exe
# (или .venv/bin/python на mac), а в CI — системный python с установленными requirements.
# Хардкод .venv/Scripts не работал ни на Linux, ни на macOS (FileNotFoundError).
PY = sys.executable
EXAMPLE_CONFIG = ROOT / "config.example.yaml"


# ---------------------------------------------------------------- helpers
def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _write_config(path: Path, port: int) -> Path:
    """config.example.yaml c нашим портом и пройденным мастером (setup.done)."""
    txt = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    txt, n = re.subn(r"(\n  port: )\d+", r"\g<1>%d" % port, txt, count=1)
    assert n == 1, "в config.example.yaml не нашлась строка `port:`"
    cfg = path / "config.yaml"
    cfg.write_text(txt + "\nsetup:\n  done: true\n", encoding="utf-8")
    return cfg


def _env(tmp_path: Path, config: Path) -> dict:
    env = dict(os.environ)
    data = tmp_path / "data"
    env.update({
        "JARVIS_CONFIG": str(config),
        "JARVIS_DATA_DIR": str(data),
        "JARVIS_DB_PATH": str(data / "jarvis.db"),
        "ASSISTANT_NO_BROWSER": "1",
        "JARVIS_NO_BROWSER": "1",
        "ASSISTANT_NO_VOICE_WARMUP": "1",
        "JARVIS_NO_VOICE_WARMUP": "1",
        # stderr у подпроцесса перенаправлен в pipe: без этого кириллица в логах
        # превращается в \uXXXX-эскейпы (run.py перекодирует только stdout — см. отчёт, P3)
        "PYTHONIOENCODING": "utf-8",
    })
    return env


@pytest.fixture()
def spawned():
    """Все дочерние процессы гасятся в teardown — даже при падении теста."""
    procs: list[subprocess.Popen] = []
    yield procs
    for p in procs:
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=15)


def _start(env: dict, procs: list) -> tuple[subprocess.Popen, callable]:
    """Запустить run.py и вернуть (процесс, функцию выдачи накопленного вывода)."""
    buf: list[str] = []
    p = subprocess.Popen([str(PY), "run.py", "--no-tg"], cwd=str(ROOT), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         encoding="utf-8", errors="replace")
    procs.append(p)

    def reader():
        try:
            for line in p.stdout:
                buf.append(line)
        except Exception:
            pass

    threading.Thread(target=reader, daemon=True).start()
    return p, lambda: "".join(buf)


def _wait_exit(p: subprocess.Popen, timeout: float) -> int | None:
    try:
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def _healthy(port: int) -> bool:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _wait_healthy(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _healthy(port):
            return True
        time.sleep(0.4)
    return False


# ---------------------------------------------------------------- 1. занятый порт
@pytest.mark.timeout(180)
def test_busy_port_exits_with_code_3_and_message(tmp_path, spawned):
    port = _free_port()
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("0.0.0.0", port))
    holder.listen(1)
    try:
        p, out = _start(_env(tmp_path, _write_config(tmp_path, port)), spawned)
        rc = _wait_exit(p, 120)
        text = out()
    finally:
        holder.close()

    assert rc == 3, f"занятый порт → код {rc}, а не 3; вывод:\n{text[-2000:]}"
    assert re.search(r"порт .*(занят|уже)", text, re.I) or "занят" in text, \
        f"нет внятного сообщения о занятом порте; вывод:\n{text[-2000:]}"
    assert "Traceback" not in text, "падение с трейсбеком вместо сообщения"


# ---------------------------------------------------------------- 2. битая база
@pytest.mark.timeout(240)
def test_broken_db_fails_instead_of_hanging(tmp_path, spawned):
    port = _free_port()
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "jarvis.db").write_bytes(b"this is definitely not a sqlite database\x00" * 64)

    p, out = _start(_env(tmp_path, _write_config(tmp_path, port)), spawned)
    rc = _wait_exit(p, 200)
    text = out()

    assert rc is not None, f"битая БД → процесс завис (не завершился за 200 с); вывод:\n{text[-2000:]}"
    assert rc != 0, "битая БД не должна завершаться успешно"
    assert not _healthy(port), "сервер не должен был подняться на битой базе"
    # сообщение: ожидаем хоть какое-то объяснение (трейсбек SQLite)
    assert re.search(r"not a database|DatabaseError|sqlite3|unable to open", text, re.I), \
        f"нет сообщения о причине падения; вывод:\n{text[-3000:]}"


# ---------------------------------------------------------------- 3. нет config.yaml
@pytest.mark.timeout(180)
def test_missing_config_falls_back_to_example(tmp_path):
    missing = tmp_path / "no-such-config.yaml"
    env = _env(tmp_path, missing)
    code = ("from core.config import _config_src, setup_done, cfg, DB_PATH; "
            "print(_config_src()); print(setup_done()); print(cfg.brain.mode); print(DB_PATH)")
    r = subprocess.run([str(PY), "-c", code], cwd=str(ROOT), env=env, capture_output=True,
                       timeout=150, encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"откат на config.example.yaml упал:\n{out[-2000:]}"
    lines = r.stdout.splitlines()
    assert "config.example.yaml" in lines[0], f"взят не тот файл настроек: {lines}"
    assert lines[1] == "False", "мастер первого запуска должен считаться непройденным"
    assert str(tmp_path) in lines[3], "БД ушла не во временный каталог"


@pytest.mark.timeout(180)
def test_missing_config_starts_setup_wizard(tmp_path, spawned):
    """run.py без config.yaml: доходит до мастера первого запуска (или честно сообщает о занятом порте)."""
    p, out = _start(_env(tmp_path, tmp_path / "no-such-config.yaml"), spawned)
    deadline = time.time() + 120
    text = ""
    while time.time() < deadline:
        text = out()
        if "Первый запуск" in text or p.poll() is not None:
            break
        time.sleep(0.3)
    text = out()

    assert "Первый запуск" in text or "занят" in text, \
        f"ни мастер первого запуска, ни сообщение о занятом порте; вывод:\n{text[-3000:]}"
    assert "Traceback" not in text, f"откат на config.example.yaml упал с трейсбеком:\n{text[-3000:]}"


@pytest.mark.xfail(reason="FINDING P3: run.py перекодирует в UTF-8 только stdout; stderr (в него пишет "
                          "logging) остаётся в ANSI-коде — при перенаправлении в файл/pipe кириллица "
                          "превращается в \\uXXXX-эскейпы (воспроизведено при этом ревью)", strict=False)
def test_entry_point_reconfigures_stderr_to_utf8():
    src = (ROOT / "run.py").read_text(encoding="utf-8")
    assert re.search(r"sys\.stderr\.reconfigure", src), "sys.stderr не перекодирован в UTF-8"


# ---------------------------------------------------------------- 4. нормальный старт + второй экземпляр
@pytest.mark.timeout(300)
def test_health_after_start_and_second_instance_rejected(tmp_path, spawned):
    port = _free_port()
    env = _env(tmp_path, _write_config(tmp_path, port))

    p1, o1 = _start(env, spawned)
    assert _wait_healthy(port, 120), f"сервер не поднялся за 120 с; вывод:\n{o1()[-3000:]}"
    assert "Traceback" not in o1(), f"старт с трейсбеком:\n{o1()[-3000:]}"

    # второй экземпляр на том же порту — должен отказаться кодом 3
    p2, o2 = _start(env, spawned)
    rc2 = _wait_exit(p2, 90)
    assert rc2 == 3, f"второй экземпляр → код {rc2}; вывод:\n{o2()[-2000:]}"
    # I24: отказ теперь от файл-блокировки (.db.lock), а не от порта —
    # сообщение «УЖЕ ЗАПУЩЕН» вместо старого «порт занят»
    assert ("занят" in o2() or "УЖЕ ЗАПУЩЕН" in o2()), f"нет сообщения об отказе второго экземпляра:\n{o2()[-2000:]}"

    # первый жив и отвечает после попытки второго старта
    assert _healthy(port), "первый экземпляр умер после попытки второго старта"


# ---------------------------------------------------------------- 5. повторный запуск той же базы
@pytest.mark.timeout(300)
def test_restart_on_same_db_starts_cleanly(tmp_path, spawned):
    port = _free_port()
    env = _env(tmp_path, _write_config(tmp_path, port))

    p1, o1 = _start(env, spawned)
    assert _wait_healthy(port, 120), f"первый старт не удался:\n{o1()[-3000:]}"
    p1.terminate()
    assert _wait_exit(p1, 30) is not None, "первый экземпляр не остановился по terminate"
    deadline = time.time() + 20
    while _healthy(port) and time.time() < deadline:
        time.sleep(0.3)
    assert not _healthy(port), "порт не освободился после остановки"

    # та же база, тот же config — стартует заново
    p2, o2 = _start(env, spawned)
    assert _wait_healthy(port, 120), f"повторный старт не удался:\n{o2()[-3000:]}"
    assert "Traceback" not in o2(), f"повторный старт с трейсбеком:\n{o2()[-3000:]}"
    assert not re.search(r"миграции не применены", o2()), f"миграции упали на втором старте:\n{o2()[-2000:]}"
    p2.terminate()
    assert _wait_exit(p2, 30) is not None, "второй экземпляр не остановился"
