# -*- coding: utf-8 -*-
"""SLIM-сборка для облака (mom): без torch/faster-whisper/av/numpy/pdfplumber/openpyxl/psutil
ядро обязано импортироваться (все тяжёлые импорты в коде ленивые).

Hermetic: гоняем импорт в ОТДЕЛЬНОМ процессе с заблокированными пакетами —
в общем процессе тесты соседних файлов уже могли их подтянуть.
"""
import os
import subprocess
import sys

os.environ.setdefault("ASSISTANT_TEST", "1")

BLOCKED = ("torch", "faster_whisper", "ctranslate2", "av", "numpy",
           "pdfplumber", "pypdfium2", "openpyxl", "psutil")

_PROBE = (
    "import sys\n"
    "blocked = %r\n"
    "import importlib.abc\n"
    "class B(importlib.abc.MetaPathFinder):\n"
    "    def find_spec(self, name, path=None, target=None):\n"
    "        if name.split('.')[0] in blocked:\n"
    "            raise ImportError('slim: %%s запрещён' %% name)\n"
    "        return None\n"
    "sys.meta_path.insert(0, B())\n"
    "import wsgi\n"
    "assert wsgi.application is not None\n"
    "import inspect\n"
    "sig = inspect.signature(wsgi.application.__call__)\n"
    "assert list(sig.parameters) == ['environ', 'start_response'], 'application обязан быть WSGI (a2wsgi)'\n"
    "from fastapi.testclient import TestClient\n"
    "r = TestClient(wsgi.app, raise_server_exceptions=False).get('/api/health')\n"
    "assert r.status_code == 200, r.text\n"
    "print('slim-ok')\n"
) % (list(BLOCKED),)


def _run_probe():
    env = dict(os.environ)
    env.setdefault("ASSISTANT_TEST", "1")
    return subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True,
                          cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          env=env, timeout=180)


def test_wsgi_imports_without_heavy_deps():
    p = _run_probe()
    assert "slim-ok" in p.stdout, (p.returncode, p.stdout[-2000:], p.stderr[-2000:])


def test_health_without_heavy_deps():
    p = _run_probe()
    assert "slim-ok" in p.stdout, (p.returncode, p.stdout[-2000:], p.stderr[-2000:])
