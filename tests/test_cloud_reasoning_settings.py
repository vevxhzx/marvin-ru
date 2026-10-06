# -*- coding: utf-8 -*-
"""Настройки облака: размышления, потолок ответа и таймаут.

Живой сбой, из-за которого всё это появилось: модель думала дольше лимита — «всё ушло в
размышления», повтор с 4096, а в Telegram — «Завис на этом вопросе». Теперь это лечится
настройкой (`brain.cloud.reasoning: off`), а поведение ПО УМОЛЧАНИЮ не изменилось:
auto = ровно то, что было до появления ключа.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def _set_cloud(monkeypatch, **kw):
    """Подменить секцию brain.cloud в конфиге (после теста возвращается как была)."""
    from core.brain import llm
    monkeypatch.setattr(llm.cfg.brain, "cloud", SimpleNamespace(**kw), raising=False)
    return llm


# ---------------------------------------------------------------- режим reasoning
def test_defaults_are_exactly_the_old_behaviour():
    """Пустая настройка = прежние параметры запроса, ничего не поменялось само собой."""
    from core.brain import llm

    assert llm.reasoning_mode() == "auto"
    assert llm._reasoning_body("chat") == {"effort": "minimal", "exclude": True}
    assert llm._reasoning_body("tools") == {"exclude": True}
    assert llm.cloud_max_tokens() == 1024
    assert llm.cloud_timeout() == 45


def test_off_disables_thinking_in_chat_and_tools(monkeypatch):
    """off → effort=none по всем путям: мысли больше не списываются как вывод."""
    llm = _set_cloud(monkeypatch, reasoning="off")
    assert llm.reasoning_mode() == "off"
    assert llm._reasoning_body("chat") == {"effort": "none", "exclude": True}
    assert llm._reasoning_body("tools") == {"effort": "none", "exclude": True}


@pytest.mark.parametrize("level", ["minimal", "low", "medium", "high"])
def test_explicit_effort_reaches_both_paths(level, monkeypatch):
    """Явная глубина действует и на ответы, и на вызовы инструментов — не на пол-пути."""
    llm = _set_cloud(monkeypatch, reasoning=level)
    assert llm._reasoning_body("chat")["effort"] == level
    assert llm._reasoning_body("tools")["effort"] == level
    # мысли всё равно не отдаём — показанный разбор в чат не попадает ни при каком уровне
    assert llm._reasoning_body("chat")["exclude"] is True


@pytest.mark.parametrize("junk", ["чушь", "OFF!", "", None])
def test_junk_mode_falls_back_to_auto(junk, monkeypatch):
    """Опечатка в настройке не должна молча выключить облако — возвращаемся к auto."""
    llm = _set_cloud(monkeypatch, reasoning=junk)
    assert llm.reasoning_mode() == "auto"
    assert llm._reasoning_body("chat") == {"effort": "minimal", "exclude": True}


# ---------------------------------------------------------------- лимиты
def test_limits_are_read_from_settings(monkeypatch):
    llm = _set_cloud(monkeypatch, max_tokens=4096, timeout=90)
    assert llm.cloud_max_tokens() == 4096
    assert llm.cloud_timeout() == 90


@pytest.mark.parametrize("junk", [0, "", None, "abc"])
def test_zero_or_junk_limits_fall_back_to_defaults(junk, monkeypatch):
    """Ноль и мусор в числовых полях = значение по умолчанию, а не «лимит 0» (молчание)."""
    llm = _set_cloud(monkeypatch, max_tokens=junk, timeout=junk)
    assert llm.cloud_max_tokens() == 1024
    assert llm.cloud_timeout() == 45


def test_settings_page_offers_the_new_keys():
    """Ключи видны в ⚙ Настройки (там рендерится весь EDITABLE) и показывают действующие значения."""
    from core.config import EDITABLE, SETTINGS_DEFAULTS

    assert EDITABLE["brain.cloud.reasoning"][0] == "str"
    assert EDITABLE["brain.cloud.max_tokens"][0] == "int"
    assert EDITABLE["brain.cloud.timeout"][0] == "int"
    # иначе в UI стоял бы 0 вместо реально действующих 1024/45
    assert SETTINGS_DEFAULTS["brain.cloud.max_tokens"] == 1024
    assert SETTINGS_DEFAULTS["brain.cloud.timeout"] == 45


def test_tg_watchdog_grows_with_cloud_timeout(monkeypatch):
    """Подняли таймаут облака → Telegram ждёт вдвое дольше, а не режет запрос своим лимитом."""
    from core.telegram import bot

    monkeypatch.setattr(bot.cfg.brain, "cloud", SimpleNamespace(timeout=90), raising=False)
    assert bot.handle_timeout() == 180
    monkeypatch.setattr(bot.cfg.brain, "cloud", SimpleNamespace(), raising=False)
    assert bot.handle_timeout() == 120
    monkeypatch.setattr(bot.cfg.brain, "cloud", SimpleNamespace(timeout="мусор"), raising=False)
    assert bot.handle_timeout() == 120


# ---------------------------------------------------------------- длинные ответы
class _Resp:
    status_code = 200
    text = ""

    def __init__(self, finish, content, reasoning=""):
        self._d = {"choices": [{"finish_reason": finish,
                                "message": {"content": content, "reasoning": reasoning}}]}

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def _cloud_harness(monkeypatch, replies):
    """Вернуть (seen, run): cloud_chat с подменённым провайдером, ответы — из списка."""
    from core.brain import llm

    seen: list[dict] = []
    calls = {"n": 0}

    async def fake_post(path, body, headers, timeout=None):
        calls["n"] += 1
        seen.append(dict(body))
        return replies[min(calls["n"], len(replies)) - 1]

    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "CLOUD_KEY", "k")
    monkeypatch.setattr(llm, "anonymize", lambda t: t)
    monkeypatch.setattr(llm, "resolve_cloud_model",
                        lambda force=False: asyncio.sleep(0, result="deepseek/deepseek-v4-pro"))
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    return seen, lambda: asyncio.run(llm.cloud_chat("system", "разбери список", None))


def test_long_answer_is_retried_instead_of_being_cut(monkeypatch):
    """Длинный ответ оборван по лимиту (finish=length, текст ЕСТЬ) → один повтор с 4096.

    Обрыв посреди фразы — тот же сбой, что и пустой ответ: пачку «разбей на задачи» нельзя
    обрезать молча. Раньше повтор делался только при пустом content."""
    partial = "1) завтра заняться документами, 2) разобраться с остальным"
    seen, run = _cloud_harness(monkeypatch, [_Resp("length", partial), _Resp("stop", partial + ", 3) не пытаться всё за день")])
    out = run()
    assert len(seen) == 2, "должен быть один повтор с увеличенным лимитом"
    assert seen[0]["max_tokens"] == 1024 and seen[1]["max_tokens"] == 4096
    assert out and out.startswith("1) завтра"), out


def test_off_mode_reaches_the_wire(monkeypatch):
    """Конец в конец: reasoning=off в конфиге → в теле запроса effort=none, а не «minimal»."""
    _set_cloud(monkeypatch, reasoning="off")
    seen, run = _cloud_harness(monkeypatch, [_Resp("stop", "Готово.")])
    out = run()
    assert out == "Готово."
    assert seen[0].get("reasoning") == {"effort": "none", "exclude": True}
    assert seen[0]["max_tokens"] == 1024          # потолок ответа тоже из настройки (здесь — дефолт)
