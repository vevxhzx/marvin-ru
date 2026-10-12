"""PythonAnywhere free умеет только WSGI, а ядро — FastAPI (ASGI).
wsgi.application обязан быть WSGI-каллабл (environ, start_response),
а не голый FastAPI (у него __call__(scope, receive, send)).
"""
import inspect
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_mom_requirements_include_a2wsgi():
    text = (ROOT / "requirements-mom.txt").read_text(encoding="utf-8")
    assert "a2wsgi" in text, "requirements-mom.txt обязан тянуть a2wsgi (ASGI->WSGI мост)"


def test_wsgi_wraps_asgi_for_pythonanywhere():
    src = (ROOT / "wsgi.py").read_text(encoding="utf-8")
    assert "ASGIMiddleware" in src, "wsgi.py обязан заворачивать FastAPI в ASGIMiddleware"
    assert "from core.api.app import app as application" not in src, (
        "голый FastAPI как application роняет PythonAnywhere: "
        "TypeError FastAPI.__call__() missing 'send'"
    )


def test_wsgi_application_is_wsgi_callable():
    try:
        import a2wsgi  # noqa: F401
    except ImportError:
        import pytest

        pytest.skip("a2wsgi не стоит локально (на PythonAnywhere ставится из requirements-mom.txt)")
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
