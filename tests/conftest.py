# -*- coding: utf-8 -*-
"""Общая инфраструктура тестов: ASSISTANT_TEST=1, временная БД, TestClient.

Зачем нужно:
* `fresh_db` — временная БД в tmp_path + `db.init_db()`: раньше эту фикстуру дублировали
  15+ файлов тестов. Файлы со СВОЕЙ фикстурой с тем же именем просто перекрывают эту
  (это нормально и намеренно — локальная версия имеет приоритет), новые тесты берут её отсюда;
* `_client` — готовый TestClient к `core.api.app.app` поверх временной БД;
* `ASSISTANT_TEST=1` — выставляется и на уровне импорта conftest (тесты импортируют
  `core` на этапе сборки, до фикстур), и автосбором перед каждым тестом.

ВАЖНО: `fresh_db` НЕ autouse — тесты без временной БД продолжают работать как раньше
(никто не подменяет `db.engine` у них молча).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")


@pytest.fixture(autouse=True)
def _assistant_test_env():
    """ASSISTANT_TEST=1 для каждого теста: правила работают без моделей и внешних звонков."""
    os.environ.setdefault("ASSISTANT_TEST", "1")
    yield


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Временная БД на всё теста: db.engine подменяется ДО init_db(), data/jarvis.db не трогается."""
    from sqlalchemy import event
    from sqlmodel import create_engine

    from core import db
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


@pytest.fixture
def _client(fresh_db):
    """TestClient к HTTP API поверх временной БД (хост testserver → авторизация отключена)."""
    from fastapi.testclient import TestClient

    from core.api.app import app
    return TestClient(app, client=("127.0.0.1", 5555), base_url="http://testserver")
