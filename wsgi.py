"""WSGI-вход для обычного хостинга (PythonAnywhere free): только сайт+API, без Telegram.

Использование на PythonAnywhere (вкладка Web → Add a new web app → Manual → Python 3.x):
  Source code: путь к копии проекта (git clone).
  Virtualenv: окружение с `pip install -r requirements-mom.txt` (лёгкий набор, уже включает a2wsgi).
  WSGI file: указать этот файл (4 строки: sys.path + from wsgi import application).
  Static files: /assets/ → <проект>/web/site/assets (остальное отдаёт сам FastAPI).

Первый запуск: откроется мастер? Нет — мастер только локальный. Перед заливкой заполните
config.yaml (brain.mode=cloud, brain.cloud.*, server.password, owner.*) — см. docs/mom-deploy.md.
Переменные окружения вместо секретов в файле: CLOUD_API_KEY, ASSISTANT_PASSWORD.
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("ASSISTANT_NO_BROWSER", "1")
os.environ.setdefault("ASSISTANT_NO_VOICE_WARMUP", "1")

from core.db import init_db  # noqa: E402

init_db()

try:  # планировщик стартует в startup-хуке ниже (нужен event loop воркера)
    from core.services import scheduler  # noqa: E402

    async def _null_notify(text: str, buttons=None) -> None:
        pass

    _sch = scheduler.build(_null_notify)
except Exception as _e:  # pragma: no cover
    import logging  # noqa: E402

    logging.getLogger("jarvis.deploy").warning("scheduler not built: %s", _e)
    _sch = None

from core.api.app import app  # noqa: E402  (ASGI; локально крутится через uvicorn в run.py)

try:  # PythonAnywhere free умеет только WSGI — заворачиваем ASGI через a2wsgi
    from a2wsgi import ASGIMiddleware  # noqa: E402

    application = ASGIMiddleware(app)  # noqa: F401  (WSGI: application(environ, start_response))
except ImportError:  # pragma: no cover — локально a2wsgi не нужен
    application = app  # type: ignore[assignment]


def _start_scheduler_thread(sch):
    """Крутить планировщик в отдельном демоническом потоке со своим event loop.

    Зачем: a2wsgi не выполняет lifespan/startup-хендлеры (проверено пробой —
    startup executed: False), а AsyncIOScheduler без живого loop мёртв. Без этого
    на копии мамы тихо не работали бы напоминания, дайджесты и бэкапы.
    Никогда не бросает: упавший старт планировщика не должен ронять воркер.
    """
    import asyncio
    import logging
    import threading

    async def _amain() -> None:
        sch.start()
        await asyncio.Event().wait()  # крутимся вечно внутри run_until_complete

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_amain())
        except Exception as e:  # pragma: no cover — воркер важнее планировщика
            logging.getLogger("jarvis.deploy").warning("scheduler thread stopped: %s", e)
        finally:
            loop.close()

    t = threading.Thread(target=_run, name="marvin-scheduler", daemon=True)
    t.start()
    return t


# Стартуем планировщик сразу, а не в lifespan: под WSGI lifespan не выполняется.
# В тестах не стартуем (ASSISTANT_TEST=1 выставляет conftest): 28 живых задач в тестовом
# процессе не нужны. Отключается и явно: ASSISTANT_WSGI_SCHEDULER=0.
_sch_thread = None
if _sch is not None and os.getenv("ASSISTANT_TEST") != "1" and os.getenv("ASSISTANT_WSGI_SCHEDULER", "1") == "1":
    _sch_thread = _start_scheduler_thread(_sch)


@app.on_event("startup")
async def _wsgi_startup() -> None:
    """Планировщик в процессе воркера (АП, бесплатный тариф без крона).
    Воркер обычно один — дубли jobs не страшны; напоминания без Telegram
    тихо гаснут в _null_notify, уборка и ролловеры работают."""
    try:
        if _sch is not None and not getattr(_sch, "running", False):
            _sch.start()
    except Exception as e:  # pragma: no cover
        import logging

        logging.getLogger("jarvis.deploy").warning("scheduler not started: %s", e)
