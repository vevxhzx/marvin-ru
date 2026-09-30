"""Логика ответа (аудит 30.09): человек пишет по-разному, а день/болтовня/данные должны ловиться правилами,
а не утекать в модель. И модель не должна отдавать воду («Чё там на сегодня? Запускаю мозги 🧠»).
Без сети: модели не вызываются, проверяются только решения и детектор воды."""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from core import db  # noqa: E402
from core.brain import agent, quick  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


# ---------------------------------------------------------------- запрос дня — все варианты, а не только «что сегодня»
DAY_ASKS = [
    "что сегодня", "что там на сегодня", "что, что сегодня але", "че там сегодня", "что там",
    "что у меня сегодня", "план на сегодня", "дайджест", "бриф", "брифинг", "дай дайджест",
    "покажи дайджест", "сегодня", "расписание на сегодня",
]


@pytest.mark.parametrize("t", DAY_ASKS)
def test_day_ask_is_rule_not_llm(t):
    """Раньше ловил только точный список строк — всё остальное уходило в модель и отвечало водой."""
    r = agent.rules(t, "test")
    assert r is not None, t
    assert r.actions and r.actions[0] in ("briefing", "agenda"), (t, r.actions)
    assert len(r.text) > 40, t   # не «…» и не заглушка


@pytest.mark.parametrize("t", ["что завтра", "дайджест на завтра", "что на выходных", "что в пятницу"])
def test_day_ask_with_other_date_goes_to_agenda(t):
    r = agent.rules(t, "test")
    assert r is not None and r.actions == ["agenda"], (t, None if r is None else r.actions)


def test_week_ask_is_calendar():
    """«что на неделе» — это календарь, а не дайджест одного дня."""
    assert agent.rules("что на неделе", "test").actions == ["list_events"]


def test_day_rule_does_not_hijack_reports():
    """«что сегодня по деньгам» — деньги, «что сегодня по задачам» — задачи, а не общий день."""
    assert "finance_summary" in agent.rules("что сегодня по деньгам", "test").actions
    assert "finance_summary" in agent.rules("что там сегодня по деньгам", "test").actions
    assert "list_tasks" in agent.rules("что сегодня по задачам", "test").actions
    assert "query_spent" in agent.rules("сколько потратил сегодня", "test").actions
    assert "query_spent" in agent.rules("сколько я потратил сегодня", "test").actions


def test_agenda_parses_phrasing_with_filler():
    """«там», «але», повторяющееся «что» — водяные слова, парсер дат их ломал."""
    for t in ("что там на сегодня", "че там сегодня", "что, что сегодня але", "дайджест на завтра"):
        assert quick.agenda(t) is not None, t


# ---------------------------------------------------------------- болтовня: локально и с цифрами
def test_smalltalk_gives_facts_not_water():
    for t in ("как дела", "че как дела", "что как делиша", "ну как"):
        r = agent.rules(t, "test")
        assert r is not None and r.actions == ["smalltalk"], t
        # ответ обязан содержать факты дня, а не «Всё ок, держу форму»
        assert any(w in r.text for w in ("задач", "встреч", "баланс")), (t, r.text)


def test_greeting_is_local():
    for t in ("привет", "здравствуй", "доброе утро"):
        r = agent.rules(t, "test")
        assert r is not None and r.actions == ["greet"], t
        assert len(r.text) > 20, t


# ---------------------------------------------------------------- детектор воды
WATER = [
    ("Чё там на сегодня? Запускаю мозги. 🧠", "что там на сегодня"),
    ("Секунду, думаю.", "что там на сегодня"),
    ("…", "что там"),
    ("Готово.", "что там"),
    ("что там на сегодня", "что там на сегодня"),
]

CLEAR = [
    ("📅 **Сегодня**\n— 13:59 забрать приписное · военкомат\n\n✅ Задач нет. Подозрительно.", "что там на сегодня"),
    ("Встреч нет, задач нет, баланс 15 161 ₽. Чем займёмся?", "как дела"),
    ("Инфляция — это когда цены растут, а деньги становятся менее ценными.", "что такое инфляция"),
    ("Записал: «встреча в 15:00».", "встреча в 15:00"),
]


@pytest.mark.parametrize("ans,q", WATER, ids=range(len(WATER)))
def test_weak_answer_is_caught(ans, q):
    assert agent._weak_answer(ans, q), ans


@pytest.mark.parametrize("ans,q", CLEAR)
def test_good_answer_is_kept(ans, q):
    assert not agent._weak_answer(ans, q), ans


def test_no_water_instruction_mentions_tools():
    assert "today_briefing" in agent._NO_WATER and "не пересказывай" in agent._NO_WATER
