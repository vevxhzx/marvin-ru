"""Характер: градация тона по humor_level, фолбэк без облака не казённый, голос — акцент, секреты не уходят."""
import asyncio
import os

import pytest

os.environ["ASSISTANT_TEST"] = "1"

from core import db  # noqa: E402
from core.brain import persona  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def test_character_block_scales_with_humor(monkeypatch):
    monkeypatch.setattr(persona, "STYLE", "swag")
    monkeypatch.setattr(persona, "OWNER", "Вова")
    monkeypatch.setattr(persona, "NICKNAMES", ["Вовчик", "шеф"])
    monkeypatch.setattr(persona, "HUMOR", 8)
    b = persona.character_block()
    assert "ГРАДАЦИЯ." in b and "ЗАПРЕЩЕНО" in b and "«Вовчик»" in b and "Напоминаю, что" in b.replace("…", "")
    monkeypatch.setattr(persona, "HUMOR", 10)
    assert "без тормозов" in persona.character_block()
    monkeypatch.setattr(persona, "HUMOR", 4)
    assert "мягкий" in persona.character_block().lower()
    monkeypatch.setattr(persona, "HUMOR", 0)
    b0 = persona.character_block()
    assert "без шуток" in b0 and "Вовчик" not in b0 and "сарказм" not in b0.lower()
    # нейтральный стиль — тоже без подколов, что бы ни стояло в humor
    monkeypatch.setattr(persona, "STYLE", "neutral"); monkeypatch.setattr(persona, "HUMOR", 10)
    assert "без шуток" in persona.character_block()


def test_system_prompt_contains_character():
    p = persona.system_prompt()
    assert ("ХАРАКТЕР." in p) and ("БЕЗОПАСНОСТЬ." in p)


def test_fallback_is_short_and_not_bureaucratic(monkeypatch):
    monkeypatch.setattr(persona, "STYLE", "swag"); monkeypatch.setattr(persona, "HUMOR", 8); monkeypatch.setattr(persona, "OWNER", "Вова")
    for kind, kw in [("stale_task", {"title": "разобрать архив футажей", "days": 3}),
                     ("late_pay", {"who": "Headway", "money": "25 000 ₽", "title": "ролик", "days": 9}),
                     ("today_task", {"title": "рендер"}), ("health", {"text": "болит горло"}), ("plan", {"text": "надо съездить в Стрельцы"})]:
        t = persona.nudge_fallback(kind, **kw)
        assert 10 < len(t) < 200, t
        assert not persona._BAD_NUDGE_RX.search(t), t
        key = kw.get("title") or kw.get("who") or kw.get("text")
        assert key in t, (key, t)
    # neutral — свои шаблоны, без подколов
    monkeypatch.setattr(persona, "HUMOR", 0)
    t = persona.nudge_fallback("stale_task", title="архив", days=3)
    assert "архив" in t and "рассосётся" not in t


def test_nudge_uses_cloud_and_rejects_bureaucratic(monkeypatch):
    from core.brain import llm
    monkeypatch.setattr(persona, "STYLE", "swag"); monkeypatch.setattr(persona, "HUMOR", 8); monkeypatch.setattr(persona, "WHERE", "cloud")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    sent = {}

    async def fake_cloud(system, user, history=None, **kw):
        sent["system"], sent["user"] = system, user
        return "Напоминаю, что задача «архив» просрочена."     # казённо — должно отвергнуться

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "cloud_chat", fake_cloud)
    monkeypatch.setattr(llm, "ollama_available", no_ollama)
    fact = {"kind": "stale_task", "title": "разобрать архив футажей", "days": 3, "urgency": "low", "note": "пароль qwerty123"}
    out = asyncio.run(persona.nudge(fact, "ФОЛБЭК"))
    assert out == "ФОЛБЭК"
    assert "ХАРАКТЕР" in sent["system"] and "архив футажей" in sent["user"]
    assert "qwerty123" not in sent["user"]          # секреты в облако не уходят

    async def good_cloud(system, user, history=None, **kw):
        return "«Архив футажей» третий день лежит. Он сам себя не разберёт, шеф."
    monkeypatch.setattr(llm, "cloud_chat", good_cloud)
    assert "третий день" in asyncio.run(persona.nudge(fact, "ФОЛБЭК"))


def test_nudge_local_only_never_calls_cloud(monkeypatch):
    from core.brain import llm
    monkeypatch.setattr(persona, "STYLE", "swag"); monkeypatch.setattr(persona, "HUMOR", 8); monkeypatch.setattr(persona, "WHERE", "local")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    called = []

    async def cloud(*a, **k):
        called.append(1); return "x"

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "cloud_chat", cloud); monkeypatch.setattr(llm, "ollama_available", no_ollama)
    assert asyncio.run(persona.nudge({"kind": "stale_task", "title": "а", "days": 3}, "ФОЛБЭК")) == "ФОЛБЭК"
    assert not called


def test_neutral_style_skips_llm_entirely(monkeypatch):
    from core.brain import llm
    monkeypatch.setattr(persona, "STYLE", "neutral")
    called = []

    async def cloud(*a, **k):
        called.append(1); return "x"
    monkeypatch.setattr(llm, "cloud_chat", cloud)
    assert asyncio.run(persona.nudge({"kind": "stale_task", "title": "а", "days": 3}, "F")) == "F"
    assert asyncio.run(persona.opener({"when": "утро"}, "F")) == "F"
    assert not called


def test_choose_channel_is_an_accent(monkeypatch):
    from core.voice import tts
    monkeypatch.setattr(persona, "STYLE", "swag"); monkeypatch.setattr(persona, "HUMOR", 8)
    long = "«Архив футажей» лежит третий день, а вечер вы провели за сериалом. Итог дня: закрыто ноль, потрачено много."
    monkeypatch.setattr(persona, "VOICE_ACCENTS", False)
    assert persona.choose_channel("evening", long) == "text"          # выключено по умолчанию
    monkeypatch.setattr(persona, "VOICE_ACCENTS", True)
    monkeypatch.setattr(tts, "ENGINE", "silero"); monkeypatch.setattr(tts, "REPLY_VOICE", "voice")
    assert persona.choose_channel("evening", long) == "voice"
    assert persona.choose_channel("evening", long, urgent=True) == "text"   # срочное — только текст
    assert persona.choose_channel("today_task", long) == "text"             # не тот повод
    assert persona.choose_channel("evening", "коротко") == "text"           # слишком коротко для голоса
    persona.mark_voice_used()
    assert persona.choose_channel("evening", long) == "text"                # раз в день
    monkeypatch.setattr(tts, "REPLY_VOICE", "never")
    db.set_setting(persona.VOICE_KEY, "")
    assert persona.choose_channel("evening", long) == "text"                # /voice never — уважаем


def test_proactive_candidates_carry_facts(monkeypatch):
    from datetime import datetime, timedelta
    from core.services import proactive, tasks
    from core import db as _db
    t = tasks.add_task("разобрать архив футажей")
    with _db.session() as s:
        row = s.get(_db.Task, t.id); row.created_at = datetime.now() - timedelta(days=6); s.add(row); s.commit()
    c = [x for x in proactive.candidates() if x["key"].startswith("stale:")]
    assert c and c[0]["fact"]["kind"] == "stale_task" and c[0]["fact"]["title"] == "разобрать архив футажей" and c[0]["fact"]["days"] == 6
    assert "архив футажей" in c[0]["text"] and not persona._BAD_NUDGE_RX.search(c[0]["text"])


def test_vibe_candidate_only_when_quiet_and_daytime(monkeypatch):
    from datetime import datetime
    from core.services import proactive
    from core.brain import agent
    monkeypatch.setattr(proactive, "vibe_enabled", lambda: True)
    day = datetime.now().replace(hour=15, minute=0)
    # чат пуст → «тихо давно» → повод есть, с фактом kind=vibe и без нотаций
    c = proactive.candidates(day)
    assert len(c) == 1 and c[0]["fact"]["kind"] == "vibe" and not persona._BAD_NUDGE_RX.search(c[0]["text"])
    # ночью/утром — нет
    assert not [x for x in proactive.candidates(day.replace(hour=22)) if x["key"].startswith("vibe")]
    # недавно переписывались — нет
    from datetime import timedelta
    agent._log_chat("user", "привет", "web")
    monkeypatch.setattr(proactive, "_last_chat_at", lambda: day - timedelta(hours=1))
    assert not [x for x in proactive.candidates(day) if x["key"].startswith("vibe")]
    monkeypatch.setattr(proactive, "_last_chat_at", lambda: day - timedelta(hours=6))
    assert [x for x in proactive.candidates(day) if x["key"].startswith("vibe")]
    # выключено — нет
    monkeypatch.setattr(proactive, "vibe_enabled", lambda: False)
    monkeypatch.setattr(proactive, "_last_chat_at", lambda: None)
    assert not [x for x in proactive.candidates(day) if x["key"].startswith("vibe")]


def test_character_prompt_has_examples_and_bans_lectures():
    b = persona.character_block()
    assert "ОБРАЗЦЫ ТОНА" in b and "АНТИОБРАЗЦЫ" in b and "Подкол + плечо" in b
    assert "Давай поставим срок" in b and "можешь отдохнуть" in b     # именно те провалы, что видели вживую


def test_recent_images_block_repeats(monkeypatch):
    from core.brain import llm
    monkeypatch.setattr(persona, "STYLE", "swag"); monkeypatch.setattr(persona, "HUMOR", 9); monkeypatch.setattr(persona, "WHERE", "cloud")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    prompts = []

    async def cloud(system, user, history=None, **kw):
        prompts.append(user)
        return "Архив футажей ждёт, пока кот Чиназес не устроит там спальню."

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "cloud_chat", cloud); monkeypatch.setattr(llm, "ollama_available", no_ollama)
    fact = {"kind": "stale_task", "title": "разобрать архив футажей", "days": 3}
    asyncio.run(persona.nudge(fact, "F"))
    assert "НЕДАВНО" not in prompts[0]
    asyncio.run(persona.nudge(fact, "F"))
    assert "НЕДАВНО ИСПОЛЬЗОВАННЫЕ" in prompts[1] and "чиназес" in prompts[1].lower() and "спальню" in prompts[1]
    # совет вместо подкола — отбрасывается
    async def advice(system, user, history=None, **kw):
        return "Давай поставим срок до пятницы, иначе архив зарастёт."
    monkeypatch.setattr(llm, "cloud_chat", advice)
    assert asyncio.run(persona.nudge(fact, "F")) == "F"


# --- жалоба 17.09: голосовое «что взять на завтрак… как думаешь?» → сортировщик → Ollama 71 с → «субтитры Н.Новикова» ---

BREAKFAST = ("Вот думаю, что такого можно взять сейчас на завтрак. Вот через 10 минут можно будет заказать самокат. "
             "Моя любимая, кстати, доставка. Так я обычно ем колбасу с батоном. Обожаю майонез. Сладкое вообще не люблю. "
             "Особо хочется на завтрак что-то сытное, чтобы сразу спать лёг. Как думаешь, что может быть?")


def test_whisper_credits_are_stripped():
    from core.voice import stt
    assert stt.strip_credits(BREAKFAST + " Субтитры субтитров Н.Новикова.") == BREAKFAST
    assert stt.strip_credits("Купить хлеб. Редактор субтитров А. Семкин Корректор А. Егорова") == "Купить хлеб."
    assert stt.strip_credits("Записал. Субтитры сделал DimaTorzok") == "Записал."
    # настоящие субтитры и настоящий Новиков — не трогаем
    assert stt.strip_credits("надо позвонить Новикову по поводу субтитров к ролику") == "надо позвонить Новикову по поводу субтитров к ролику"


def test_opinion_question_goes_to_cloud_and_not_to_sorter():
    from core.brain import agent, sorter
    assert agent.is_personal(BREAKFAST) is False                      # цифры «10 минут» не делают вопрос личным
    assert agent.is_personal("как думаешь, стоит ли брать кредит 300000") is False
    assert agent.is_personal("запиши: позвонить маме в 15:00") is True
    assert sorter.looks_like_batch(BREAKFAST + " Субтитры субтитров Н.Новикова.") is False
    assert sorter.looks_like_batch("купить хлеб, позвонить маме, отправить инвойс Headway") is True


def test_compact_prompt_for_local_model():
    from core.brain import persona
    full, compact = persona.system_prompt(), persona.system_prompt(compact=True)
    assert "ОБРАЗЦЫ ТОНА" in full and "ОБРАЗЦЫ ТОНА" not in compact
    assert "ГРАДАЦИЯ" in compact and "ЗАПРЕЩЕНО" in compact
    assert len(compact) < len(full) - 800


def test_voice_reply_quotes_full_transcript():
    """Расшифровка голосового в ответе — целиком (сворачиваемая цитата), а не первые 140 символов."""
    import inspect
    from core.telegram import bot
    src = inspect.getsource(bot.tg_voice) if hasattr(bot, "tg_voice") else open(bot.__file__, encoding="utf-8").read()
    assert "blockquote expandable" in src and "text[:137]" not in src


def test_cloud_short_mode_gives_reasoning_models_room():
    """gpt-oss/qwen3 тратят max_tokens на скрытые размышления: 220 на голосовой ответ = пустой content."""
    from core.brain import llm
    assert llm._THINK_RX.search("openai/gpt-oss-20b") and not llm._THINK_RX.search("llama-3.3-70b")
    # _cloud_post проставляет reasoning_effort=low для gpt-oss до отправки — проверяем через исходник без сети
    import inspect
    src = inspect.getsource(llm._cloud_post)
    assert '"gpt-oss" in body.get("model", "")' in src and 'reasoning_effort"] = "low"' in src
    src2 = inspect.getsource(llm.cloud_chat)
    assert "short_max = 700 if _THINK_RX.search(model) else 220" in src2 and "повторяю основной моделью" in src2
