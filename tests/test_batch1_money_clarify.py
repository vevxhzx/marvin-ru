"""Батч 1: денежные неоднозначности — TDD.

a) «отдал Ване 2000» → clarify, а не запись
b) «перевёл 5000» без счетов → clarify про счета
c) «пришёл аванс 10к за ролик» → clarify про заказ/доход
d) сумма >=50000 → pending confirm (да/нет)
e) ответ «долг/трата/доход» после clarify → запись + урок
"""
import asyncio
import os

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def _offline(monkeypatch):
    """Выключить LLM полностью: поведение только правил (детерминировано)."""
    from core.brain import llm
    from core.services import judge as _judge

    async def _no_false(*a, **k):
        return False

    async def _no_none(*a, **k):
        return None

    async def _no_empty(*a, **k):
        return ""

    # judge выключен? Нет — для батча судья должен быть доступен как фолбэк,
    # но без модели решать некому (via none). Оставляем enabled=True,
    # модели недоступны → _judge_disputed должен сам спросить для денег.
    monkeypatch.setattr(_judge, "enabled", lambda: True)
    monkeypatch.setattr(llm, "ollama_available", _no_false)
    monkeypatch.setattr(llm, "embed_available", _no_false)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "ollama_chat", _no_none)
    monkeypatch.setattr(llm, "cloud_chat", _no_none)
    monkeypatch.setattr(llm, "small_chat", _no_empty)


def _handle(text, ch):
    from core.brain import agent
    return asyncio.run(agent.handle(text, ch))


# a) денежные неоднозначности — всегда clarify, записи нет
@pytest.mark.parametrize("phrase", ["отдал Ване 2000", "дал маме 5к", "занял у Пети 3000"])
def test_a_money_ambiguous_asks_not_writes(monkeypatch, phrase):
    _offline(monkeypatch)
    ch = f"b1-a-{phrase[:4]}"
    r = _handle(phrase, ch)
    assert "clarify" in r.actions, (phrase, r.actions, r.text)
    assert any(w in r.text.lower() for w in ("трата", "долг", "доход")), r.text
    with db.session() as s:
        assert s.exec(db.select(db.Transaction)).all() == []
        assert s.exec(db.select(db.Debt)).all() == []


# b) перевод без счетов — спросить «с какого на какой»
def test_b_bare_transfer_asks_accounts(monkeypatch):
    _offline(monkeypatch)
    ch = "b1-b"
    r = _handle("перевёл 5000", ch)
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "какой" in r.text.lower() and "сч" in r.text.lower(), r.text
    with db.session() as s:
        assert s.exec(db.select(db.Transaction)).all() == []


def test_b_explicit_transfer_still_works(monkeypatch):
    """Явные шаблоны не ломаем: «снял 3000 наличных» — как раньше transfer."""
    _offline(monkeypatch)
    r = _handle("снял 3000 наличных", "b1-b2")
    assert "add_transfer" in r.actions, (r.actions, r.text)


def test_b_explicit_expense_still_works(monkeypatch):
    _offline(monkeypatch)
    r = _handle("потратил 700", "b1-b3")
    assert "add_expense" in r.actions, (r.actions, r.text)


# c) аванс/получил — всегда clarify заказ/доход, не выдумывать заказ
def test_c_advance_asks_order_or_income(monkeypatch):
    from core.services import orders
    _offline(monkeypatch)
    orders.add_order("Ролик", 25000, "Пятёрочка")
    r = _handle("пришёл аванс 10к за ролик", "b1-c")
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "заказ" in r.text.lower() and "доход" in r.text.lower(), r.text
    # ничего не записано до ответа
    with db.session() as s:
        assert s.exec(db.select(db.Transaction)).all() == []


def test_c_bare_received_asks(monkeypatch):
    _offline(monkeypatch)
    r = _handle("получил 15000", "b1-c2")
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "заказ" in r.text.lower() and "доход" in r.text.lower(), r.text
    with db.session() as s:
        assert s.exec(db.select(db.Transaction)).all() == []


def test_c_unknown_order_is_honest(monkeypatch):
    """Заказ не найден — честно сказать, не выдумывать."""
    _offline(monkeypatch)
    r = _handle("пришёл аванс 10к за несуществующийзаказххх", "b1-c3")
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "не наш" in r.text.lower(), r.text


# d) крупные суммы — через pending «да/нет»
def test_d_confirm_threshold_is_50k():
    from core.brain import agent
    assert agent.CONFIRM_AMOUNT == 50_000, agent.CONFIRM_AMOUNT
    assert agent._needs_confirm("add_expense", {"amount": 60_000}) is not None
    assert agent._needs_confirm("add_expense", {"amount": 49_999}) is None
    assert agent._needs_confirm("transfer", {"amount": 50_000}) is not None
    assert agent._needs_confirm("pay_debt", {"amount": 75_000}) is not None
    assert agent._needs_confirm("set_balance", {"balance": 50_000}) is not None


def test_d_big_tool_call_waits_for_yes(monkeypatch):
    """Модель позвала add_expense 60000 → вопрос + pending confirm|, записи нет."""
    from core.brain import agent, llm
    _offline(monkeypatch)

    async def _up(force=False):
        return True
    monkeypatch.setattr(llm, "ollama_available", _up)

    async def fake_chat(messages, tools=None, **kw):
        return {"content": "пишу", "tool_calls": [
            {"name": "add_expense", "arguments": {"amount": 60000, "note": "тест"}}]}
    monkeypatch.setattr(agent, "_chat", fake_chat)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    monkeypatch.setattr(agent, "_turn_context", lambda t, with_lessons=True: __import__("asyncio").sleep(0, result=("", "")))

    r = asyncio.run(agent.via_ollama("потрать 60000 на тест", "b1-d"))
    assert r is not None and "clarify" in r.actions, (r.actions if r else None, r.text if r else None)
    assert "да" in r.text.lower() and "нет" in r.text.lower(), r.text
    with db.session() as s:
        assert s.exec(db.select(db.Transaction)).all() == []
    # pending висит
    p = agent._pending_get("b1-d")
    assert p is not None and p[0].startswith("confirm|"), p


# e) ответ одним словом после clarify → запись + урок
@pytest.mark.parametrize("answer, kind, check", [
    ("долг", "debt", "debt"),
    ("трата", "expense", "expense"),
    ("доход", "income", "income"),
])
def test_e_answer_after_clarify_writes_and_lessons(monkeypatch, answer, kind, check):
    _offline(monkeypatch)
    ch = f"b1-e-{answer}"
    r1 = _handle("отдал Ване 2000", ch)
    assert "clarify" in r1.actions, (r1.actions, r1.text)
    r2 = _handle(answer, ch)
    assert f"add_{check}" in r2.actions, (answer, r2.actions, r2.text)
    assert "lesson" in r2.actions, (r2.actions, r2.text)
    with db.session() as s:
        if check == "debt":
            d = s.exec(db.select(db.Debt)).all()
            assert len(d) == 1 and d[0].remaining == 2000
        else:
            tx = s.exec(db.select(db.Transaction)).all()
            assert len(tx) == 1 and tx[0].kind == check and tx[0].amount == 2000
        lessons = s.exec(db.select(db.Lesson)).all()
        assert any(l.kind == kind for l in lessons), [(l.kind, l.text) for l in lessons]
