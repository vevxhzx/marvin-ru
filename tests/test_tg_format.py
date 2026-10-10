"""TEP-2: единый форматтер Telegram — markdown→HTML, нарезка, подписи, тихий источник."""
from __future__ import annotations


def test_unclosed_tags_stay_plain():
    from core.telegram.format import to_html
    out = to_html("**bold without close")
    assert "<b>" not in out and "**bold" in out
    out2 = to_html("<b>ручной незакрытый")
    assert out2.count("<b>") == out2.count("</b>")


def test_lt_in_text_escaped():
    from core.telegram.format import to_html
    assert to_html("a < b & **c**") == "a &lt; b &amp; <b>c</b>"
    assert to_html("5 < 10, a>b") == "5 &lt; 10, a&gt;b"


def test_underscores_in_words_not_italic():
    from core.telegram.format import to_html
    assert to_html("my_var_name") == "my_var_name"
    assert to_html("file_name.py и snake_case_here") == "file_name.py и snake_case_here"
    assert "<i>" not in to_html("my_var_name")


def test_very_long_list_splits_balanced():
    from core.telegram import format as f
    text = "\n".join(f"— пункт номер {i} с **важным**" for i in range(200))
    chunks = f.split_html(f.to_html(text))
    assert len(chunks) > 1
    for c in chunks:
        assert f.plain_len(c) <= 4096
        assert not f._open_stack(c), f"рваный тег в куске: {c[:80]}"


def test_nested_formatting():
    from core.telegram.format import to_html
    out = to_html("**bold and *italic* inside**")
    assert out == "<b>bold and <i>italic</i> inside</b>"
    out2 = to_html("*italic with `code` inside*")
    assert "<i>italic with <code>code</code> inside</i>" in out2


def test_russian_punctuation():
    from core.telegram.format import to_html
    assert to_html("**«цитата» — да…**") == "<b>«цитата» — да…</b>"
    assert to_html("*привет, мир!*") == "<i>привет, мир!</i>"
    assert to_html("Он сказал: «привет» — и ушёл…") == "Он сказал: «привет» — и ушёл…"


def test_headings_become_bold_with_emoji():
    from core.telegram.format import to_html
    out = to_html("# Заголовок\n## Подзаголовок")
    assert "#" not in out
    assert "📌 <b>Заголовок</b>" in out
    assert "🔹 <b>Подзаголовок</b>" in out


def test_tables_become_monospace():
    from core.telegram.format import to_html
    out = to_html("| товар | сумма |\n|---|---|\n| хлеб | 100 |\n| молоко | 200 |")
    assert "<pre>" in out and "</pre>" in out
    assert "хлеб" in out and "100" in out


def test_long_quote_is_expandable():
    from core.telegram.format import to_html
    out = to_html("> " + "длинная важная мысль " * 20)
    assert "<blockquote expandable>" in out
    short = to_html("> коротко")
    assert "<blockquote>коротко</blockquote>" in short


def test_quote_not_inside_code():
    from core.telegram.format import to_html
    out = to_html("```\n> не цитата\n```\n> цитата")
    assert "<blockquote>цитата</blockquote>" in out
    assert "&gt; не цитата" in out


def test_split_never_breaks_tags():
    from core.telegram import format as f
    html_text = "<b>" + "слово " * 1500 + "</b>"
    chunks = f.split_html(html_text)
    assert len(chunks) > 1
    for c in chunks:
        assert not f._open_stack(c)
        assert f.plain_len(c) <= 4096


def test_caption_truncation_balanced():
    from core.telegram import format as f
    html_text = f.to_html("**" + "длинный заголовок " * 100 + "**")
    cap = f.truncate_html(html_text, 300)
    assert len(cap) <= 320
    assert not f._open_stack(cap)
    assert cap.rstrip().endswith("</b>")


def test_source_is_quiet_last_line():
    from core.telegram import format as f
    out = f.finalize("Готово: **дело**", via="gemini", mark=True)
    assert "<b>дело</b>" in out
    assert out.rstrip().endswith("<i>☁️ облако</i>")
    assert "  ☁️" not in out
    # повторный прогон не двоит
    assert f.finalize("Готово\n\n☁️ облако", via="gemini", mark=True).count("☁️") == 1
    assert "☁️" not in f.finalize("Готово", via="gemini", mark=False)


def test_spoiler_strike_bare_url():
    from core.telegram.format import to_html
    assert to_html("||спойлер||") == "<tg-spoiler>спойлер</tg-spoiler>"
    assert to_html("~~del~~") == "<s>del</s>"
    out = to_html("читай https://example.com/1.")
    assert '<a href="https://example.com/1">https://example.com/1</a>.' in out


def test_bot_wrappers_compat():
    from core.telegram.bot import _to_html, _to_html_cap
    assert _to_html("a < b & **c**") == "a &lt; b &amp; <b>c</b>"
    assert _to_html("**жирный** и `код`") == "<b>жирный</b> и <code>код</code>"
    cap = _to_html_cap("**" + "x" * 2000 + "**", 300)
    assert len(cap) <= 320 and cap.count("<b>") == cap.count("</b>")


def test_mark_is_quiet_line():
    from core.brain import agent
    from core.brain import llm
    old = llm.MARK_SOURCE
    llm.MARK_SOURCE = True
    try:
        r = agent.Reply("Ответ облака", [], "gemini")
        agent._mark(r)
        assert "☁️" in r.text and "  ☁️" not in r.text
        assert r.text.rstrip().endswith("☁️ облако")
    finally:
        llm.MARK_SOURCE = old
