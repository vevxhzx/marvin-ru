# -*- coding: utf-8 -*-
"""Самолечение мелочей: бот чинит сам, а не валит ошибку на юзера."""
from __future__ import annotations

from types import SimpleNamespace


def test_claimed_without_write_is_caught():
    from core.brain import agent

    assert agent._claims_saved("Готово, записал трату")
    assert agent._forced_tool("сколько у меня денег?") == ("finance_summary", {"days": 30})
    # команда с глаголом идёт правилами, а не forced tool
    assert agent._forced_tool("потратил 700 на такси") is None
    from core.tools import registry

    bad = registry.ToolResult(ok=False, text="", error="не понял дату", name="add_event", risk="write")
    out = agent._truth_gate("Готово, сэр, записал!", [bad])
    assert out.startswith("Не записал")
    assert "«" not in out or "Готово, сэр, записал!" not in out


def test_broken_markup_never_leaks():
    from core.telegram import format as f

    out = f.to_html("<b>незакрытый тег и a < b")
    assert out.count("<b>") == out.count("</b>")
    assert "a &lt; b" in out
    big = f.to_html("слово " * 3000)
    chunks = f.split_html(big)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 4000
        assert not f._open_stack(c)
    plain = f.to_plain("<b>жирно</b> и <i>курсив</i>")
    assert "<" not in plain and "жирно" in plain


def test_duplicate_update_runs_once():
    from core.telegram import bot as b

    b._VOICE_SEEN.clear()
    m = SimpleNamespace(chat=SimpleNamespace(id=1), message_id=42)
    assert b._once(m) is True
    assert b._once(m) is False
    m2 = SimpleNamespace(chat=SimpleNamespace(id=1), message_id=43)
    assert b._once(m2) is True
