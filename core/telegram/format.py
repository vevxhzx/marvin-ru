"""Единый форматтер всех исходящих сообщений Telegram.

Telegram НЕ умеет: заголовки (#), таблицы (markdown), вложенные списки, hr.
Умеет (parse_mode=HTML): b/strong, i/em, u/ins, s/strike/del, tg-spoiler,
code, pre (с language-*), a href, blockquote (+ expandable).

Всё исходящее идёт через to_html()/split_html()/to_caption():
вход — markdown/обычный текст (и старый HTML — пропускаем белым списком),
выход — валидный HTML. При отказе Telegram — чистый текст (to_plain),
сбой всегда логируется вызывающим кодом, молча не падаем.

Стиль дома: первая строка-заголовок, короткие абзацы, ключевые факты —
цитатой, цифры/суммы — моноширинным. Маркер источника (⚡/🧠/☁️) —
тихой последней строкой курсивом (with_source).
"""

from __future__ import annotations

import html as _html
import re as _re

MESSAGE_LIMIT = 4096
MESSAGE_SAFE = 4000  # запас под теги/эмодзи: режем чуть раньше лимита
CAPTION_LIMIT = 1024
CAPTION_SAFE = 1000

HEADING_EMOJI = {1: "📌", 2: "🔹", 3: "▪️", 4: "▪️", 5: "▪️", 6: "▪️"}

SOURCE_LABELS = {
    "rules": ("⚡", "правила"),
    "ollama": ("🧠", "локально"),
    "gemini": ("☁️", "облако"),
}

_TAG_RE = _re.compile(
    r"</?(b|strong|i|em|u|ins|s|strike|del|code|pre|a|blockquote|tg-spoiler|span)"
    r"(?:\s[^<>]*)?>",
    _re.I,
)

# белый список сквозного HTML (остальное экранируется)
_PASSTHROUGH_RE = _re.compile(
    r"<br\s*/?>|"
    r"</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|tg-spoiler)\s*>|"
    r"</?span\s+class=\"tg-spoiler\"\s*>|"
    r"</?blockquote(?:\s+expandable)?\s*>|"
    r"<a\s+href=\"[^\"]*\"\s*>|</a>|"
    r"<code\s+class=\"language-[\w+-]+\"\s*>",
    _re.I,
)

_FENCE_RE = _re.compile(r"```(\w[\w+-]*)?\n?(.*?)```", _re.S)
_INLINE_CODE_RE = _re.compile(r"`([^`\n]+?)`")
_IMG_RE = _re.compile(r"!\[([^\]\n]*)\]\((https?://[^)\s]+)\)")
_LINK_RE = _re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BARE_URL_RE = _re.compile(r"https?://[^\s<\"]+")
_A_SPLIT_RE = _re.compile(r"(<a\s+href=\"[^\"]*\">.*?</a>)", _re.S)
_BOLD_STAR_RE = _re.compile(r"\*\*([^\n]+?)\*\*")
_BOLD_UNDER_RE = _re.compile(r"__([^\n]+?)__")
_STRIKE_RE = _re.compile(r"~~([^~\n]+?)~~")
_SPOILER_RE = _re.compile(r"\|\|([^|\n]+?)\|\|")
_UNDERLINE_RE = _re.compile(r"\+\+([^+\n]+?)\+\+")
_ITAL_STAR_RE = _re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_ITAL_UNDER_RE = _re.compile(r"(?<!\w)_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)")
_HEADING_RE = _re.compile(r"^#{1,6}\s+(.+)$", _re.M)
_BULLET_RE = _re.compile(r"^[ \t]*[•\-\*][ \t]+", _re.M)
_ORDERED_RE = _re.compile(r"^[ \t]*(\d+)[.)][ \t]+", _re.M)
_HR_RE = _re.compile(r"^[ \t]*[-*_]{3,}[ \t]*$", _re.M)
_TAG_STRIP_RE = _re.compile(r"<[^>]+>")
_WS_RE = _re.compile(r"\n{3,}")
_AMP = "&amp;"  # во что html.escape превращает & в URL — в href возвращаем обратно &


def _store(ph: dict[str, str], snippet: str) -> str:
    key = f"\x00TG{len(ph)}\x00"
    ph[key] = snippet
    return key


def escape(text: str) -> str:
    return _html.escape(text or "", quote=False)


def to_plain(html_or_text: str) -> str:
    """Чистый текст без тегов — fallback при отказе разметки."""
    t = _TAG_STRIP_RE.sub("", html_or_text or "")
    t = _html.unescape(t)
    t = t.replace("\x00", "")
    t = _re.sub(r"[ \t]+\n", "\n", t)
    return _re.sub(r"\n{3,}", "\n\n", t).strip()


def plain_len(html_or_text: str) -> int:
    return len(to_plain(html_or_text))


def _balance_tags(html_text: str) -> str:
    """Закрыть незакрытые теги, выкинуть висячие закрывающие."""
    out: list[str] = []
    stack: list[tuple[str, str]] = []
    pos = 0
    closers = {"b": "b", "strong": "strong", "i": "i", "em": "em", "u": "u",
               "ins": "ins", "s": "s", "strike": "strike", "del": "del",
               "code": "code", "pre": "pre", "a": "a", "blockquote": "blockquote",
               "tg-spoiler": "tg-spoiler", "span": "span"}
    for m in _TAG_RE.finditer(html_text or ""):
        out.append(html_text[pos:m.start()])
        pos = m.end()
        tag = m.group(0)
        name = m.group(1).lower()
        is_close = tag.startswith("</")
        cname = closers.get(name, name)
        if not is_close:
            # <pre> внутри <blockquote> Telegram не любит — чиним заранее:
            # такие вложения разворачиваем (ниже, на этапе цитат, их уже избегаем,
            # здесь — страховка от ручного HTML).
            stack.append((cname, tag))
            out.append(tag)
        else:
            idx = next((i for i in range(len(stack) - 1, -1, -1) if stack[i][0] == cname), None)
            if idx is None:
                continue  # висячий закрывающий — выкидываем
            while len(stack) > idx + 1:
                out.append(f"</{stack.pop()[0]}>")
            stack.pop()
            out.append(f"</{cname}>")
    out.append(html_text[pos:])
    while stack:
        out.append(f"</{stack.pop()[0]}>")
    return "".join(out)


def _open_stack(html_text: str) -> list[str]:
    stack: list[str] = []
    for m in _TAG_RE.finditer(html_text or ""):
        name = m.group(1).lower()
        if m.group(0).startswith("</"):
            if stack and stack[-1] == name:
                stack.pop()
            elif name in stack:
                while stack and stack[-1] != name:
                    stack.pop()
                if stack:
                    stack.pop()
        else:
            stack.append(name)
    return stack


def _linkify_bare(text: str) -> str:
    parts = _A_SPLIT_RE.split(text)
    for i in range(0, len(parts), 2):
        def _sub(m: _re.Match) -> str:
            url = m.group(0)
            trail = ""
            while url and url[-1] in ".,!?;:»»)]}":
                trail = url[-1] + trail
                url = url[:-1]
            href = url.replace("&amp;", "&")
            return f'<a href="{href}">{url}</a>{trail}'
        parts[i] = _BARE_URL_RE.sub(_sub, parts[i])
    return "".join(parts)


def _table_block_to_html(rows: list[list[str]]) -> str:
    cells = [[_TAG_STRIP_RE.sub("", c).strip() for c in r] for r in rows]
    cells = [[_re.sub(r"\s+", " ", c)[:34] for c in r] for r in cells]
    ncols = max(len(r) for r in cells)
    cells = [r + [""] * (ncols - len(r)) for r in cells]
    if ncols > 5 or len(cells) > 20:
        lines = ["• " + " — ".join(c for c in r if c) for r in cells]
        return "\n".join(lines)
    widths = [max(len(r[i]) for r in cells) for i in range(ncols)]
    lines = []
    for ri, r in enumerate(cells):
        lines.append(" | ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip())
        if ri == 0 and len(cells) > 1:
            lines.append("-+-".join("-" * w for w in widths))
    return "<pre>" + _html.escape("\n".join(lines), quote=False) + "</pre>"


def _convert_tables(text: str, ph: dict[str, str]) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if "|" in lines[i]:
            j = i
            while j < len(lines) and "|" in lines[j]:
                j += 1
            group = lines[i:j]
            if len(group) >= 2:
                rows: list[list[str]] = []
                for ln in group:
                    s = ln.strip()
                    if _re.fullmatch(r"[:|\-\s]+", s) and "-" in s:
                        continue  # разделитель | --- | --- |
                    s = s.strip()
                    if s.startswith("|"):
                        s = s[1:]
                    if s.endswith("|"):
                        s = s[:-1]
                    rows.append([c.strip() for c in s.split("|")])
                if rows and max(len(r) for r in rows) >= 2:
                    out.append(_store(ph, _table_block_to_html(rows)))
                    i = j
                    continue
            out.append(lines[i])
            i += 1
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _convert_quotes(text: str) -> str:
    parts = _re.split(r"(<pre>.*?</pre>)", text, flags=_re.S)
    for i in range(0, len(parts), 2):
        lines = parts[i].split("\n")
        out, buf = [], []
        for ln in lines:
            m = _re.match(r"^&gt;[ \t]?(.*)$", ln)
            if m:
                inner = m.group(1)
                inner = _re.sub(r"^[•\-\*][ \t]+", "• ", inner)
                inner = _re.sub(r"^(\d+)[.)][ \t]+", r"\1. ", inner)
                buf.append(inner)
            else:
                if buf:
                    out.append(_wrap_quote(buf))
                    buf = []
                out.append(ln)
        if buf:
            out.append(_wrap_quote(buf))
        parts[i] = "\n".join(out)
    return "".join(parts)


def _wrap_quote(buf: list[str]) -> str:
    inner = "\n".join(buf).strip()
    if not inner:
        return ""
    plain = to_plain(inner)
    expand = " expandable" if (len(plain) > 180 or len(buf) >= 4) else ""
    return f"<blockquote{expand}>{inner}</blockquote>"


def to_html(text: str | None) -> str:
    """Markdown/текст (или старый HTML) → валидный Telegram HTML."""
    if not text:
        return ""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\t", "  ")
    t = _re.sub(r"<br\s*/?>", "\n", t, flags=_re.I)
    ph: dict[str, str] = {}

    # код — первым, в плейсхолдеры (не трогаем внутри)
    def _fence(m: _re.Match) -> str:
        lang = (m.group(1) or "").strip()
        code = _html.escape(m.group(2), quote=False)
        if lang:
            return _store(ph, f'<pre><code class="language-{lang}">{code}</code></pre>')
        return _store(ph, f"<pre>{code}</pre>")
    t = _FENCE_RE.sub(_fence, t)
    t = _INLINE_CODE_RE.sub(lambda m: _store(ph, f"<code>{_html.escape(m.group(1), quote=False)}</code>"), t)

    # старый валидный HTML — прячем, остальное экранируем
    t = _PASSTHROUGH_RE.sub(lambda m: _store(ph, m.group(0)), t)
    t = _html.escape(t, quote=False)

    # заголовки → болд с эмодзи (Telegram не умеет #)
    def _head(m: _re.Match) -> str:
        hashes = m.group(0).split(" ", 1)[0]
        level = min(len(hashes), 6)
        return f"{HEADING_EMOJI.get(level, '▪️')} <b>{m.group(1).strip()}</b>"
    t = _HEADING_RE.sub(_head, t)

    # картинки/ссылки
    t = _IMG_RE.sub(lambda m: f'<a href="{m.group(2).replace(_AMP, "&")}">{m.group(1)}</a>', t)
    t = _LINK_RE.sub(lambda m: f'<a href="{m.group(2).replace(_AMP, "&")}">{m.group(1)}</a>', t)

    # спойлер/зачёрк/подчёрк/жирный раньше курсива (вложенность **→* работает)
    t = _SPOILER_RE.sub(r"<tg-spoiler>\1</tg-spoiler>", t)
    t = _STRIKE_RE.sub(r"<s>\1</s>", t)
    t = _UNDERLINE_RE.sub(r"<u>\1</u>", t)
    t = _BOLD_STAR_RE.sub(r"<b>\1</b>", t)
    t = _BOLD_UNDER_RE.sub(r"<b>\1</b>", t)
    t = _ITAL_STAR_RE.sub(r"<i>\1</i>", t)
    t = _ITAL_UNDER_RE.sub(r"<i>\1</i>", t)
    t = _linkify_bare(t)

    # таблицы → моноширинный блок или буллеты
    t = _convert_tables(t, ph)

    # списки: плоские (вложенных TG не умеет), hr — выкинуть
    t = _BULLET_RE.sub("• ", t)
    t = _ORDERED_RE.sub(r"\1. ", t)
    t = _HR_RE.sub("", t)

    # цитаты (> …), длинные — раскрываемыми
    t = _convert_quotes(t)

    t = _WS_RE.sub("\n\n", t).strip()

    for key, val in ph.items():
        t = t.replace(key, val)
    # плейсхолдеры не должны утекать наружу
    t = t.replace("\x00", "")
    return _balance_tags(t)


def split_html(html_text: str, limit: int = MESSAGE_SAFE) -> list[str]:
    """Режем на куски ≤limit по границам абзацев, не рвём теги (<pre> — атомарно)."""
    html_text = (html_text or "").strip()
    if not html_text:
        return []
    if len(html_text) <= limit and plain_len(html_text) <= MESSAGE_LIMIT:
        return [_balance_tags(html_text)]
    tokens = _re.split(r"(<pre>.*?</pre>)", html_text, flags=_re.S)
    chunks: list[str] = []
    cur = ""

    def _flush() -> None:
        nonlocal cur
        if cur.strip():
            chunks.append(_balance_tags(cur.strip()))
        cur = ""

    def _push(piece: str) -> None:
        nonlocal cur
        if len(cur) + len(piece) <= limit and plain_len(cur + piece) <= MESSAGE_LIMIT:
            cur = (cur + piece) if not cur else cur + piece
            return
        _flush()
        if len(piece) <= limit and plain_len(piece) <= MESSAGE_LIMIT:
            cur = piece
            return
        for part in _hard_split(piece, limit):
            if len(cur) + len(part) <= limit and plain_len(cur + part) <= MESSAGE_LIMIT:
                cur = part if not cur else cur + part
            else:
                _flush()
                cur = part
        _flush()

    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("<pre>"):
            if len(tok) <= limit:
                _push(tok if not cur else "\n\n" + tok)
            else:
                _flush()
                inner = _re.sub(r"^<pre>(.*)</pre>$", r"\1", tok, flags=_re.S)
                inner = _html.unescape(inner)
                while inner:
                    cut = inner[:limit - 20]
                    chunks.append(f"<pre>{_html.escape(cut, quote=False)}</pre>")
                    inner = inner[len(cut):]
            continue
        paras = _re.split(r"(\n\n+)", tok)
        for p in paras:
            if not p:
                continue
            if p.strip() == "":
                if cur and not cur.endswith("\n\n"):
                    cur += "\n\n"
                continue
            _push(p if not cur else (p if cur.endswith("\n\n") or p.startswith("\n") else "\n\n" + p))
    _flush()
    return [c for c in chunks if c.strip()]


def _hard_split(piece: str, limit: int) -> list[str]:
    """Жёсткая нарезка длинного абзаца с переоткрытием тегов."""
    parts: list[str] = []
    rest = piece
    reopen: list[str] = []
    while rest:
        if len(rest) <= limit and plain_len("".join(f"<{t}>" for t in reopen) + rest) <= MESSAGE_LIMIT:
            parts.append("".join(f"<{t}>" for t in reopen) + rest)
            break
        prefix = "".join(f"<{t}>" for t in reopen)
        budget = limit - len(prefix) - 32
        cut = budget if budget > 100 else limit // 2
        chunk = rest[:cut]
        # не рвём тег <...>
        lt = chunk.rfind("<")
        gt = chunk.rfind(">")
        if lt > gt:
            chunk = chunk[:lt]
        # не рвём слово в идеале
        if len(rest) > len(chunk) and chunk and not chunk[-1].isspace() and not rest[len(chunk):len(chunk) + 1].isspace():
            sp = chunk.rfind(" ")
            if sp > len(chunk) * 0.5:
                chunk = chunk[:sp]
        if not chunk.strip():
            chunk = rest[:cut]
        full = prefix + chunk
        balanced = _balance_tags(full)
        parts.append(balanced)
        stack = _open_stack(full)
        reopen = [t for t in stack if t != "pre"]
        rest = rest[len(chunk):].lstrip()
        if reopen:
            pass
    return parts


def truncate_html(html_text: str, limit: int = CAPTION_SAFE) -> str:
    """Обрезать HTML до limit с закрытием тегов (для подписей)."""
    html_text = (html_text or "").strip()
    if len(html_text) <= limit and plain_len(html_text) <= CAPTION_LIMIT:
        return _balance_tags(html_text)
    cut = html_text[: max(0, limit - 1)]
    cut = _re.sub(r"<[^>]*$", "", cut)
    stack = _open_stack(cut)
    closers = "".join(f"</{t}>" for t in reversed(stack))
    # многоточие — внутрь последнего тега, чтобы не висело снаружи болда
    return (cut.rstrip() + "…" + closers).strip()


def to_caption(text: str | None, limit: int = CAPTION_SAFE) -> str:
    return truncate_html(to_html(text), limit)


def fits_caption(html_text: str, limit: int = CAPTION_SAFE) -> bool:
    return bool(html_text) and len(html_text) <= limit and plain_len(html_text) <= CAPTION_LIMIT


def short_caption(html_text: str, limit: int = 300) -> str:
    """Короткая подпись к фото, когда полный текст не влез: первая строка."""
    html_text = (html_text or "").strip()
    if not html_text:
        return ""
    first = _re.split(r"\n\n|\n", html_text, maxsplit=1)[0].strip()
    first = _re.sub(r"<pre>.*?</pre>", "", first, flags=_re.S).strip()
    if not first:
        first = html_text
    return truncate_html(first, limit)


def strip_source(html_text: str) -> str:
    # NOTE: ☁️ = U+2601 + VS16 (U+FE0F), поэтому после эмодзи допускаем \uFE0F?
    t = _re.sub(r"[ \t]+[⚡🧠☁]\uFE0F?\s*$", "", html_text or "").rstrip()
    t = _re.sub(r"\n\n<i>\s*[⚡🧠☁]\uFE0F?(?:\s*[^<>]*)?</i>\s*$", "", t).rstrip()
    # тихая строка обычным текстом («☁️ облако» от _mark) — тоже снимаем, вернём курсивом
    return _re.sub(r"\n\n[⚡🧠☁]\uFE0F?(?:\s+[а-яёa-z]+\s*)?$", "", t).rstrip()


def with_source(html_text: str, via: str | None, mark: bool = True) -> str:
    """Тихая последняя строка с источником вместо инлайнового значка."""
    t = strip_source(html_text or "")
    if not mark or via not in SOURCE_LABELS:
        return t
    emoji, label = SOURCE_LABELS[via]
    return f"{t}\n\n<i>{emoji} {label}</i>" if t else f"<i>{emoji} {label}</i>"


def finalize(text: str | None, via: str | None = None, mark: bool = True) -> str:
    """Весь исходящий текст — через это: markdown→HTML + тихий источник."""
    return with_source(to_html(text), via, mark)
