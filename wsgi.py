"""WSGI-вход для обычного хостинга (PythonAnywhere free): только сайт+API, без Telegram.

Использование на PythonAnywhere (вкладка Web → Add a new web app → Manual → Python 3.x):
  Source code: путь к копии проекта (git clone).
  Virtualenv: окружение с `pip install -r requirements.txt` (без voice/gpu — лёгкий набор).
  WSGI file: указать этот файл.
  Static files: /assets/ → <проект>/web/site/assets (остальное отдаёт сам FastAPI).

Первый запуск: откроется мастер? Нет — мастер только локальный. Перед заливкой заполните
config.yaml (brain.mode=cloud, brain.cloud.*, server.password, owner.*) — см. docs/mom-deploy.md.
Переменные окружения вместо секретов в файле: ASSISTANT_CLOUD_KEY, ASSISTANT_PASSWORD.
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

from core.api.app import app as application  # noqa: E402,F401


@application.on_event("startup")
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
