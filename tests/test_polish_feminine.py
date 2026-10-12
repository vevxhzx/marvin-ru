# -*- coding: utf-8 -*-
"""Женский голос — женский род («записала», а не «записал»). TDD: сначала красные."""
import asyncio
import os

os.environ.setdefault("ASSISTANT_TEST", "1")



def test_voice_is_feminine(monkeypatch):
    from core.voice import tts
    monkeypatch.setattr(tts, "ENGINE", "piper", raising=False)
    monkeypatch.setattr(tts, "PIPER_VOICE", "ru_RU-irina-medium", raising=False)
    assert tts.voice_is_feminine() is True
    monkeypatch.setattr(tts, "PIPER_VOICE", "ru_RU-denis-medium", raising=False)
    assert tts.voice_is_feminine() is False
    monkeypatch.setattr(tts, "ENGINE", "silero", raising=False)
    monkeypatch.setattr(tts, "SPEAKER", "baya", raising=False)
    assert tts.voice_is_feminine() is True
    monkeypatch.setattr(tts, "SPEAKER", "eugene", raising=False)
    assert tts.voice_is_feminine() is False


def test_feminize_basics():
    from core.brain.persona import feminize
    assert feminize("Записал: 700 ₽ · Такси.") == "Записала: 700 ₽ · Такси."
    assert feminize("Понял, без напоминания.") == "Поняла, без напоминания."
    assert feminize("Не записал: нет суммы.") == "Не записала: нет суммы."
    assert feminize("Готово. Баланс 1000.") == "Готово. Баланс 1000."


def test_feminize_keeps_quotes():
    """Чужие слова в кавычках не трогаем: «вернул залог» — не наше «я»."""
    from core.brain.persona import feminize
    assert feminize("Отменил трату «вернул залог»") == "Отменила трату «вернул залог»"
    assert feminize("«Ваня должен мне» — запомнил.") == "«Ваня должен мне» — запомнила."


def test_handle_feminine_end_to_end(fresh_db, monkeypatch):
    from core.brain import agent
    from core.voice import tts
    monkeypatch.setattr(tts, "ENGINE", "piper", raising=False)
    monkeypatch.setattr(tts, "PIPER_VOICE", "ru_RU-irina-medium", raising=False)
    r = asyncio.run(agent.handle("потратил 700 на такси", "tg"))
    assert "add_expense" in r.actions
    assert "записал" not in r.text.lower() or "записала" in r.text.lower()


def test_handle_masculine_untouched(fresh_db, monkeypatch):
    from core.brain import agent
    from core.voice import tts
    monkeypatch.setattr(tts, "ENGINE", "silero", raising=False)
    monkeypatch.setattr(tts, "SPEAKER", "eugene", raising=False)
    r = asyncio.run(agent.handle("потратил 700 на такси", "tg"))
    assert "add_expense" in r.actions
    assert "записала" not in r.text.lower()


def test_system_prompt_feminine_hint(monkeypatch):
    from core.brain import persona
    from core.voice import tts
    monkeypatch.setattr(tts, "ENGINE", "piper", raising=False)
    monkeypatch.setattr(tts, "PIPER_VOICE", "ru_RU-irina-medium", raising=False)
    assert "женском роде" in persona.system_prompt()
    monkeypatch.setattr(tts, "PIPER_VOICE", "ru_RU-denis-medium", raising=False)
    assert "женском роде" not in persona.system_prompt()
