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

Трюк команды (не убирать!): `from tests.test_core import fresh_db` в тестовом файле —
pytest подхватывает ИМПОРТИРОВАННУЮ autouse-фикстуру, и весь файл идёт на временной БД.
Без этого импорта тесты с записью ходят в БОЕВУЮ data/jarvis.db.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

# Тесты НЕ ДОЛЖНЫ трогать боевую data/jarvis.db.
#
# Что случилось: `core/config.py` читает JARVIS_DB_PATH при ИМПОРТЕ, то есть раньше любой
# фикстуры. Тест, который забыл про `fresh_db`, писал прямо в живую базу. Одна ночная
# сессия тестов добавила туда 8 событий («Зубной», «Встреча с Ваней»), 5 задач, 11 заметок,
# 25 строк памяти и трату 700 ₽, которая ушла с реального счёта. Всё это потом пришлось
# вычищать вручную — тестовые строки стоили пользователю реальных данных.
#
# Поэтому путь к БД задаётся здесь, на импорте conftest, ДО того как тесты увидят `core`:
# тесты получают отдельную пустую базу во временной папке и физически не могут достать
# до боевой. `setdefault` — если разработчик задал путь сам, уважаем его.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="marvin-test-db-")
os.environ.setdefault("JARVIS_DB_PATH", str(Path(_TEST_DB_DIR) / "jarvis.db"))


@atexit.register
def _drop_test_db() -> None:
    shutil.rmtree(_TEST_DB_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _assistant_test_env():
    """ASSISTANT_TEST=1 для каждого теста: правила работают без моделей и внешних звонков."""
    os.environ.setdefault("ASSISTANT_TEST", "1")
    yield


@pytest.fixture(scope="session", autouse=True)
def _config_file_isolated(tmp_path_factory):
    """Ни один тест не пишет в `config.yaml` разработчика — и его содержимое не влияет на тесты.

    Зачем. `core/config.py::_config_file()` читает `JARVIS_CONFIG` при каждом вызове, а запись
    конфига идёт через неё (`write_settings`). Раньше тесты, которые пишут конфиг, полагались на
    то, что нужный путь подменён их собственной фикстурой. Стоило одному из них остаться без
    подмены — он создавал настоящий `config.yaml` в корне репозитория, и со второго прогона
    весь набор читал его вместо `config.example.yaml`.

    Наблюдалось как три «загадочных» падения: тесты зрения читали `brain.mode` из подсунутого
    файла (`local` вместо `hybrid` в примере) и падали на `local_only()`. То есть результат
    прогона зависел от того, что осталось в папке от прошлого раза, — для одиночной машины
    и для CI это разные миры.

    Что делаем. На всю сессию уводим `JARVIS_CONFIG` во временную папку:
      * если настоящий `config.yaml` есть — копируем его (тесты видят ровно те настройки,
        к которым привыкли, но менять могут только копию);
      * если его нет — указываем на несуществующий путь, чтобы `setup_done()` остался `False`
        (на него завязаны тесты мастера установки и проверки редиректа).
    Тесты с собственной подменой пути (`monkeypatch.setenv`) перекрывают её внутри теста —
    как и раньше.

    Фикстура сессионная: `monkeypatch` на этом уровне недоступен, поэтому переменную среды
    ставим и снимаем вручную.
    """
    import shutil
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    real = root / "config.yaml"
    target = tmp_path_factory.mktemp("marvin-config") / "config.yaml"
    if real.exists():
        shutil.copy(real, target)
    previous = os.environ.get("JARVIS_CONFIG") or os.environ.get("ASSISTANT_CONFIG")
    key = "JARVIS_CONFIG" if os.environ.get("JARVIS_CONFIG") or not os.environ.get("ASSISTANT_CONFIG") else "ASSISTANT_CONFIG"
    os.environ["JARVIS_CONFIG"] = str(target)
    yield
    if previous is None:
        os.environ.pop("JARVIS_CONFIG", None)
        os.environ.pop("ASSISTANT_CONFIG", None)
    else:
        os.environ[key] = previous


@pytest.fixture(autouse=True)
def _lmstudio_off(monkeypatch):
    """LM Studio в тестах выключен: иначе на машине с включённым LM Studio тесты
    ходили бы в живой сервер (маршрутизация читает настоящий config.yaml).
    Тесты самого LM Studio включают его явно внутри теста (после фикстур)."""
    try:
        from core.brain import llm
    except Exception:
        return
    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", False, raising=False)


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
