"""Проверка WSGI-приложения в лоб: вызвать application() напрямую, без uWSGI.

Зачем: на PythonAnywhere запросы висели по 300 секунд до harakiri, а локально всё
летало. Этот скрипт отвечает на вопрос «виснет в нашем коде или в транспорте»:
запускается в консоли PA одной командой, без кавычек и длинных строк:

    cd ~/mom-marvin && timeout 120 .venv/bin/python tools/pa_probe.py

Исходы:
- мгновенно `STATUS: 200 BYTES: ...` — приложение невиновно, виснет транспорт uWSGI;
- тишина 50 секунд + простыня стека — виснет код, и в стеке точная строка.

Планировщик здесь не стартуем (ASSISTANT_WSGI_SCHEDULER=0): проверяем именно путь
запроса, а не фоновые задачи.
"""
import faulthandler
import io
import os
import sys
import time

faulthandler.dump_traceback_later(50, exit=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

os.environ["ASSISTANT_TEST"] = "1"  # чужой БД и живой планировщик в пробе не нужны

from wsgi import application  # noqa: E402

env = {
    "REQUEST_METHOD": "GET",
    "PATH_INFO": "/",
    "QUERY_STRING": "",
    "SERVER_NAME": "x",
    "SERVER_PORT": "443",
    "wsgi.url_scheme": "https",
    "CONTENT_LENGTH": "",
    "wsgi.input": io.BytesIO(b""),
    "wsgi.errors": sys.stderr,
    "wsgi.version": (1, 0),
    "wsgi.multithread": False,
    "wsgi.multiprocess": False,
    "wsgi.run_once": False,
}

seen = {}


def _start_response(status, headers, exc_info=None):
    seen["status"] = status


t0 = time.monotonic()
body = b"".join(application(env, _start_response))
dt = time.monotonic() - t0
print(f"STATUS: {seen.get('status')} BYTES: {len(body)} TIME: {dt:.1f}s", flush=True)
