"""Запись по просьбе: «распредели это на задачи», жалоба «ничего не записалось», ложь «записал».

Регресс к реальному сценарию: человек прислал длинное сообщение с делами, попросил разобрать его на задачи —
модель ответила красивым планом текстом, ни один инструмент не вызван, в базе пусто, а на жалобу «никаких задач
не записалось» приходило «Записал в память» (жалоба сохранялась заметкой). Здесь проверяем, что:
1) команда «распредели это на задачи» уходит в сортировщик по прошлой реплике и пишет записи;
2) жалоба «ничего не записалось» — тоже повод доделать запись, а не повод сделать заметку;
3) на длинном сообщении модель больше не может соврать «записал» — ответ честно поправляется;
4) просьба записать без вызова инструментов получает один жёсткий повтор с указанием;
5) «в этот момент» в середине нормального ответа не считается водой (двойной вызов облака).
"""
import asyncio
import os

import pytest

os.environ["ASSISTANT_TEST"] = "1"

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


PRIOR = ("Задачи на завтра: оформить карту Газпромбанка в МФЦ и подать заявление на паспорт (порядок важен, "
         "иначе время потеряно), позвонить в деревню, уточнить у арендаторов про интернет, заказать доставку еды, "
         "поднять облачную версию бота")


def _say_history(text: str, channel: str = "t-rec") -> None:
    from core.db import ChatMessage, session
    with session() as s:
        s.add(ChatMessage(role="user", text=text, channel=channel))
        s.commit()


def _mock_sorter(monkeypatch, items=None, via="gemini"):
    from core.brain import llm, sorter

    async def fake(_text):
        return items if items is not None else [{"kind": "task", "title": "Оформить карту Газпромбанка"},
                                                 {"kind": "task", "title": "Позвонить в деревню"}], via

    async def no_ollama(force=False):
        return False

    monkeypatch.setattr(sorter, "_ask_llm", fake)
    monkeypatch.setattr(llm, "ollama_available", no_ollama)
    monkeypatch.setattr(llm, "MODE", "cloud")


def test_split_cmd_sorts_previous_message(monkeypatch):
    """«распредели это на задачи» → сортировщик разбирает ПРОШЛУЮ длинную реплику, а не отвечает планом."""
    from core.brain import agent, sorter
    from core.services import tasks

    _say_history(PRIOR)
    _mock_sorter(monkeypatch)
    seen: list[str] = []
    real = sorter.sort

    async def spy(text, channel, confirm_amount=100_000):
        seen.append(text)
        return await real(text, channel, confirm_amount)

    monkeypatch.setattr(sorter, "sort", spy)
    r = asyncio.run(agent.handle("распредели это на задачи", "t-rec"))
    assert seen == [PRIOR], seen
    assert "Разобрал твоё сообщение выше" in r.text, r.text
    assert {t.title for t in tasks.list_tasks()} >= {"Оформить карту Газпромбанка", "Позвонить в деревню"}


def test_complaint_is_recorded_not_answered_with_ack(monkeypatch):
    """«никаких задач не записалось» → доделываем запись; жалоба НЕ становится заметкой."""
    from core.brain import agent, sorter
    from core.services import brain_notes, tasks

    _say_history(PRIOR)
    _mock_sorter(monkeypatch)
    seen: list[str] = []
    real = sorter.sort

    async def spy(text, channel, confirm_amount=100_000):
        seen.append(text)
        return await real(text, channel, confirm_amount)

    monkeypatch.setattr(sorter, "sort", spy)
    r = asyncio.run(agent.handle("никаких задач не записалось", "t-rec"))
    assert seen == [PRIOR], seen
    assert "Разобрал" in r.text and "Записал в память" not in r.text, r.text
    assert len(tasks.list_tasks()) == 2
    assert not brain_notes.list_notes(10), "жалоба не должна ложиться в заметки"


def test_complaint_without_context_does_not_create_note(monkeypatch):
    """Не нашли, что разбирать, — честный ответ вместо заметки из жалобы."""
    from core.brain import agent
    from core.services import brain_notes

    _mock_sorter(monkeypatch, items=[])
    r = asyncio.run(agent.handle("никаких задач не записалось", "t-rec2"))
    assert "Записал в память" not in r.text, r.text
    assert not brain_notes.list_notes(10), "жалоба не должна ложиться в заметки"


def test_long_message_claim_is_corrected_not_lying(monkeypatch):
    """Длинная реплика: модель не вызвала инструментов, но отрапортовала «записал» — честная поправка, а не ложь."""
    from core.brain import agent
    from core.services import brain_notes, tasks

    long_text = ("Вчера думал про поездку к родителям и про то, как бы навести порядок в гараже с братом, "
                 "потом вспомнил про старые документы в шкафу и про то, что надо позвонить в страховую по полису, "
                 "а вечером хотел разобраться с фотографиями с прошлого лета")
    assert agent._too_long_for_rules(long_text)

    async def plan(messages, tools=None, **kw):
        return {"content": "Погнали, босс. Записал задачи под твои приоритеты, чтобы не спалилось к дедлайнам. "
                           "Вчера и сегодня: гараж и документы. Завтрашнее утро: страховая. Следующие дни: фотографии "
                           "и родители. Итог: сосредоточиться на документах, потом разобраться по остальному.",
                "tool_calls": []}

    monkeypatch.setattr(agent, "_chat", plan)
    monkeypatch.setattr(agent.llm, "MODE", "hybrid")
    monkeypatch.setattr(agent.llm, "ollama_available", lambda force=False: asyncio.sleep(0, result=True))
    monkeypatch.setattr(agent, "_turn_context", lambda t, with_lessons=True: asyncio.sleep(0, result=("", "")))
    r = asyncio.run(agent.via_ollama(long_text, "t-long"))
    assert "не записал" in r.text.lower(), r.text
    assert not brain_notes.list_notes(10) and not tasks.list_tasks()


def test_nudge_makes_model_call_tools(monkeypatch):
    """Просят записать, а модель отвечает текстом — один повтор с прямым указанием, после которого инструмент идёт."""
    from core.brain import agent
    from core.services import tasks

    calls: list[list[dict]] = []

    async def chat(messages, tools=None, **kw):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": "Погнали, босс. Записал задачи под твои приоритеты, чтобы не спалилось к дедлайнам. "
                               "Вчера и сегодня: коты и армия. Завтрашнее утро: документы и деревня. Следующие дни: "
                               "квартира, бот, еда и пиво. Итог: сосредоточиться на документах завтра.",
                    "tool_calls": []}
        if len(calls) == 2:
            return {"content": "", "tool_calls": [{"name": "add_task", "arguments": {"title": "Позвонить маме"}}]}
        return {"content": "Готово, добавил.", "tool_calls": []}

    monkeypatch.setattr(agent, "_chat", chat)
    monkeypatch.setattr(agent.llm, "MODE", "hybrid")
    monkeypatch.setattr(agent.llm, "ollama_available", lambda force=False: asyncio.sleep(0, result=True))
    monkeypatch.setattr(agent, "_turn_context", lambda t, with_lessons=True: asyncio.sleep(0, result=("", "")))
    r = asyncio.run(agent.via_ollama("запиши мне задачи на завтра: позвонить маме и купить корм", "t-nudge"))
    assert len(calls) >= 2, len(calls)
    assert any("НИ ОДНОГО инструмента" in (m.get("content") or "") for m in calls[1]), "нет повтора с указанием"
    assert "Позвонить маме" in [t.title for t in tasks.list_tasks()], r.text


def test_mid_sentence_moment_is_not_water():
    """«в этот момент» в нормальном ответе — не повод отбрасывать ответ и вызывать вторую нейронку."""
    from core.brain import agent

    assert not agent._weak_answer("В этот момент он зевает и думает о жизни, глядя в окно.", "мяу")
    assert agent._weak_answer("Запускаю мозги 🧠", "что там на сегодня")


def test_split_cmd_and_nudge_helpers():
    from core.brain import agent

    assert agent._is_split_cmd("распредели это на задачи")
    assert agent._is_split_cmd("запиши всё это в задачи, пожалуйста")
    assert agent._is_split_cmd("никаких задач не записалось")
    assert not agent._is_split_cmd("сколько потратил на еду за неделю?")
    assert not agent._is_split_cmd("добавь задачу купить корм")   # обычная команда, её ведёт модель
    assert agent._asks_records("запиши мне задачи на завтра")
    assert not agent._asks_records("что ты знаешь про мои задачи?")
