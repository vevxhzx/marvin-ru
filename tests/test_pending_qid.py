"""Привязка подтверждений к вопросу (I25): qid, one-shot, TTL."""
import pytest

from core.brain import agent
from core.db import set_setting

CH = "test_qid"


@pytest.fixture(autouse=True)
def _clean(fresh_db):  # noqa: ARG001 — fresh_db обязателен: _pending_* и set_setting пишут в setting
    """Чистый слот до и после. БД — временная: без fresh_db эти вызовы писали
    в настоящую data/jarvis.db (ключ pending:test_qid)."""
    agent._pending_clear(CH)
    yield
    agent._pending_clear(CH)


def test_wrong_qid_rejected_slot_intact():
    qid = agent._pending_set(CH, "confirm|{\"a\": 1}")
    assert qid and len(qid) == 6
    assert agent._pending_consume(CH, qid="000000") is None  # чужой qid — отказ
    assert agent._pending_get(CH) is not None  # слот НЕ тронут
    got = agent._pending_consume(CH, qid=qid)  # свой — ок
    assert got is not None and got[0] == "confirm|{\"a\": 1}"


def test_replay_rejected_one_shot():
    qid = agent._pending_set(CH, "bulk|x")
    assert agent._pending_consume(CH, qid=qid) is not None
    assert agent._pending_consume(CH, qid=qid) is None  # повтор — отказ
    assert agent._pending_consume(CH) is None  # и без qid — пусто


def test_chat_path_plain_yes_still_one_shot():
    agent._pending_set(CH, "confirm|{\"a\": 1}")
    assert agent._pending_consume(CH) is not None  # «да» без кода — прежний UX
    assert agent._pending_consume(CH) is None  # повтор — отказ


def test_ttl_expiry_rejected_and_cleared(monkeypatch):
    agent._pending_set(CH, "confirm|x")
    monkeypatch.setattr(agent, "PENDING_TTL_SEC", -1)  # всё просрочено
    assert agent._pending_consume(CH) is None
    assert agent._pending_get(CH) is None  # просрочка вычищена


def test_legacy_format_still_readable():
    set_setting(f"pending:{CH}", "2000-01-01T00:00:00|confirm|legacy")
    p = agent._pending_get(CH)
    assert p is not None and p[0] == "confirm|legacy"


def test_prefix_guard_keeps_foreign_slot():
    agent._pending_set(CH, "judge|сайт 15000")
    assert agent._pending_consume(CH, prefix="confirm|") is None  # чужой слот цел
    assert agent._pending_get(CH) is not None
