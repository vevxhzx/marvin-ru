# -*- coding: utf-8 -*-
"""SLIM-сборка для облака (mom): без torch/faster-whisper/av/numpy/pdfplumber/openpyxl/psutil
ядро обязано импортироваться (все тяжёлые импорты в коде ленивые)."""
import os
import sys

os.environ.setdefault("ASSISTANT_TEST", "1")

BLOCKED = ("torch", "faster_whisper", "ctranslate2", "av", "numpy",
           "pdfplumber", "pypdfium2", "openpyxl", "psutil")


class _Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError(f"slim: {name} запрещён")
        return None


def test_wsgi_imports_without_heavy_deps(fresh_db):
    assert "core.api.app" not in sys.modules
    bl = _Blocker()
    sys.meta_path.insert(0, bl)
    try:
        import wsgi
        assert wsgi.application is not None
    finally:
        if bl in sys.meta_path:
            sys.meta_path.remove(bl)


def test_health_without_heavy_deps(fresh_db):
    from fastapi.testclient import TestClient

    bl = _Blocker()
    sys.meta_path.insert(0, bl)
    try:
        from core.api.app import app
        r = TestClient(app, raise_server_exceptions=False).get("/api/health")
        assert r.status_code == 200, r.text
    finally:
        if bl in sys.meta_path:
            sys.meta_path.remove(bl)
