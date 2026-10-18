"""PythonAnywhere free умеет только WSGI, а ядро — FastAPI (ASGI).
wsgi.application обязан быть WSGI-каллабл (environ, start_response),
а не голый FastAPI (у него __call__(scope, receive, send)).
"""
import inspect
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_hosted_requirements_include_a2wsgi():
    text = (ROOT / "requirements-hosted.txt").read_text(encoding="utf-8")
    assert "a2wsgi" in text, "requirements-hosted.txt обязан тянуть a2wsgi (ASGI->WSGI мост)"


def test_wsgi_wraps_asgi_for_pythonanywhere():
    src = (ROOT / "wsgi.py").read_text(encoding="utf-8")
    assert "ASGIMiddleware" in src, "wsgi.py обязан заворачивать FastAPI в ASGIMiddleware"
    assert "from core.api.app import app as application" not in src, (
        "голый FastAPI как application роняет PythonAnywhere: "
        "TypeError FastAPI.__call__() missing 'send'"
    )


def test_scheduler_runs_without_lifespan():
    """a2wsgi не выполняет startup-хендлеры (проверено пробой: startup executed: False),
    а планировщик без живого loop мёртв: напоминания и бэкапы в облачном инстансе не работали бы.
    Поэтому wsgi.py крутит его в отдельном демоническом потоке со своим loop."""
    import threading
    import wsgi

    started = threading.Event()

    class FakeSch:
        running = False

        def start(self):
            started.set()

    t = wsgi._start_scheduler_thread(FakeSch())
    assert started.wait(timeout=10), "планировщик не стартовал в фоне"
    assert t.daemon, "поток обязан быть демоном, иначе процесс не завершится"


def test_scheduler_thread_runs_jobs():
    """Паттерн «поток + свой loop» работает с установленной версией APScheduler:
    задача, запланированная на +1 с, реально срабатывает."""
    import threading
    import wsgi
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.date import DateTrigger
    from datetime import datetime, timedelta

    fired = threading.Event()
    sch = AsyncIOScheduler()
    # Отступ 3 с, а не 1: на CI (две параллельные копии сьюта) поток с loop стартует дольше секунды,
    # и задача с run_date «+1 с» к моменту старта считалась пропущенной — дефолтный
    # misfire_grace_time у APScheduler 1 с. С запасом по времени и длинным grace_time флейка нет.
    sch.add_job(fired.set, DateTrigger(run_date=datetime.now() + timedelta(seconds=3)),
                misfire_grace_time=120)
    wsgi._start_scheduler_thread(sch)
    try:
        assert fired.wait(timeout=30), "задача в потоке планировщика не сработала"
    finally:
        sch.shutdown(wait=False)


def test_scheduler_thread_never_raises():
    """Упавший старт планировщика не роняет воркер: воркер без напоминаний лучше,
    чем 504 на каждый запрос."""
    import wsgi

    class Boom:
        def start(self):
            raise RuntimeError("boom")

    wsgi._start_scheduler_thread(Boom())  # не должно бросить


def test_wsgi_application_is_wsgi_callable():
    try:
        import a2wsgi  # noqa: F401
    except ImportError:
        import pytest

        pytest.skip("a2wsgi не стоит локально (в облаке ставится из requirements-hosted.txt)")
    code = (
        "import inspect, wsgi; "
        "sig = inspect.signature(wsgi.application.__call__); "
        "params = list(sig.parameters); "
        "assert params == ['environ', 'start_response'], params; "
        "print('wsgi-ok')"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120,
    )
    assert "wsgi-ok" in r.stdout, (r.stdout[-2000:] + r.stderr[-2000:])
