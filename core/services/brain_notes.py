"""Второй мозг: заметки, ссылки, память."""
from __future__ import annotations

import html as _html
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from sqlmodel import select

from ..config import DATA_DIR
from ..db import icontains, Link, Memory, Note, remember, session, log_action

URL_RE = re.compile(r"https?://[^\s<>\"']+")


def extract_urls(text: str) -> list[str]:
    return URL_RE.findall(text or "")


MEDIA_DIR = DATA_DIR / "media"


def save_image(raw: bytes, ext: str = "jpg") -> str:
    """Сохранить картинку в data/media/ГГГГ-ММ/… и вернуть относительный путь (хранится в Note.image).
    Большие фото ужимаем до 1600px — мозгу хватит, а диск не распухнет."""
    import hashlib, io
    from datetime import datetime as _dt
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
        if max(im.size) > 1600:
            im.thumbnail((1600, 1600))
        out = io.BytesIO(); im.save(out, "JPEG", quality=86, optimize=True); raw = out.getvalue(); ext = "jpg"
    except Exception:
        pass
    sub = MEDIA_DIR / _dt.now().strftime("%Y-%m")
    sub.mkdir(parents=True, exist_ok=True)
    name = f"{_dt.now():%d_%H%M%S}_{hashlib.sha1(raw).hexdigest()[:8]}.{ext}"
    (sub / name).write_bytes(raw)
    return f"{sub.name}/{name}"


def add_note(text: str, tags: list[str] | None = None, source: str = "tg", image: str | None = None,
             polish: bool = True) -> Note:
    text = (text or "").strip()
    with session() as s:
        n = Note(text=text, raw=text, tags=",".join(tags or []), source=source, image=image, polished=not polish)
        s.add(n)
        s.commit()
        s.refresh(n)
        remember(s, "note", ("Мысль: " if not image else "Мысль с фото: ") + text[:120], "note", n.id, source)
        log_action(s, "add_note", "note", n.id, text[:80], source)
        s.commit()
    if polish:
        _schedule_polish("note", n.id)
    return n


def _schedule_polish(kind: str, obj_id: int) -> None:
    """Причесать запись через LLM в фоне (не блокируя ответ пользователю)."""
    import asyncio
    from . import polish

    async def run():
        ok = await (polish.polish_note(obj_id) if kind == "note" else polish.polish_link(obj_id))
        if ok:
            # обновляем текст в ленте памяти на аккуратный вариант
            with session() as s:
                if kind == "note":
                    n = s.get(Note, obj_id)
                    label = f"Мысль: {n.title or n.text[:100]}"
                else:
                    l = s.get(Link, obj_id)
                    label = f"Ссылка: {l.title or l.url}"
                for m in s.exec(select(Memory).where(Memory.ref_table == kind, Memory.ref_id == obj_id)):
                    m.text = label
                    s.add(m)
                s.commit()

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(run())
    except RuntimeError:
        pass  # нет event loop (тесты/скрипты) — обработает фоновая задача планировщика


def list_notes(limit: int = 50, query: str | None = None) -> list[Note]:
    with session() as s:
        q = select(Note)
        if query:
            q = q.where(icontains(Note.text, query) | icontains(Note.tags, query) | icontains(Note.title, query) | icontains(Note.raw, query))
        return list(s.exec(q.order_by(Note.created_at.desc()).limit(limit)))


def find_note(query: str) -> Note | None:
    notes = list_notes(1, query)
    return notes[0] if notes else None


def delete_note(nid: int) -> bool:
    with session() as s:
        n = s.get(Note, nid)
        if not n:
            return False
        img = n.image
        s.delete(n); s.commit()
    if img:
        try:
            (MEDIA_DIR / img).unlink(missing_ok=True)
        except Exception:
            pass
    return True


async def fetch_preview(url: str) -> dict:
    """Заголовок, описание, картинка (OpenGraph). Не падает, если сайт недоступен."""
    meta = {"title": None, "description": None, "image": None, "domain": urlparse(url).netloc.replace("www.", "")}
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 (compatible; AssistantBot/1.0)"}) as c:
            r = await c.get(url)
            html = r.text[:300_000]
    except Exception:
        return meta

    def og(prop: str) -> str | None:
        m = re.search(rf'<meta[^>]+(?:property|name)=["\'](?:og:)?{prop}["\'][^>]+content=["\']([^"\']+)', html, re.I) \
            or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:)?{prop}["\']', html, re.I)
        return m.group(1).strip() if m else None

    meta["title"] = og("title")
    if not meta["title"]:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        meta["title"] = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    meta["description"] = og("description")
    meta["image"] = og("image")
    # YouTube: заголовок через oEmbed (страница без JS его не отдаёт) + гарантированная обложка
    yt = re.search(r"(?:youtu\.be/|v=|shorts/)([\w-]{11})", url)
    if yt:
        if not meta["title"] or meta["title"].lower() in ("youtube", "- youtube"):
            try:
                async with httpx.AsyncClient(timeout=6) as c:
                    r = await c.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"})
                    j = r.json()
                    meta["title"] = j.get("title") or meta["title"]
                    meta["description"] = meta["description"] or (f"Автор: {j['author_name']}" if j.get("author_name") else None)
            except Exception:
                pass
        if not meta["image"]:
            meta["image"] = f"https://i.ytimg.com/vi/{yt.group(1)}/hqdefault.jpg"
    for k in ("title", "description"):
        if meta[k]:
            meta[k] = _html.unescape(meta[k])[:300]
    if meta["title"] and meta["title"].startswith("OS - "):  # мусорный префикс у некоторых сайтов
        meta["title"] = meta["title"][5:]
    meta["excerpt"] = _page_text(html)
    return meta


def _page_text(html: str, limit: int = 4000) -> str | None:
    """Грубо вытащить читаемый текст страницы (без скриптов/стилей/меню) — для выжимки в 5 строк."""
    if not html:
        return None
    body = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|form)[^>]*>.*?</\1>", " ", html)
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", body) or re.search(r"(?is)<main[^>]*>(.*?)</main>", body)
    if m:
        body = m.group(1)
    paras = re.findall(r"(?is)<(?:p|h1|h2|h3|li)[^>]*>(.*?)</(?:p|h1|h2|h3|li)>", body)
    text = "\n".join(re.sub(r"<[^>]+>", " ", p) for p in paras) if paras else re.sub(r"<[^>]+>", " ", body)
    text = _html.unescape(re.sub(r"[ \t\xa0]+", " ", text))
    text = "\n".join(l.strip() for l in text.splitlines() if len(l.strip()) > 30)
    return text[:limit] or None


async def add_link(url: str, comment: str | None = None, tags: list[str] | None = None, source: str = "tg") -> Link:
    meta = await fetch_preview(url)
    with session() as s:
        link = Link(url=url, comment=comment, tags=",".join(tags or []), source=source, **meta)
        s.add(link)
        s.commit()
        s.refresh(link)
        remember(s, "link", f"Ссылка: {link.title or url}", "link", link.id, source)
        log_action(s, "add_link", "link", link.id, link.title or url, source)
        s.commit()
    _schedule_polish("link", link.id)
    return link


def list_links(limit: int = 50, query: str | None = None) -> list[Link]:
    with session() as s:
        q = select(Link)
        if query:
            q = q.where(icontains(Link.title, query) | icontains(Link.tags, query) | icontains(Link.comment, query))
        return list(s.exec(q.order_by(Link.created_at.desc()).limit(limit)))


def memory_feed(days: int = 7, limit: int = 100, kind: str | None = None) -> list[Memory]:
    since = datetime.now() - timedelta(days=days)
    with session() as s:
        q = select(Memory).where(Memory.created_at >= since)
        if kind:
            q = q.where(Memory.kind == kind)
        return list(s.exec(q.order_by(Memory.created_at.desc()).limit(limit)))


def search_memory(query: str, limit: int = 20) -> list[Memory]:
    with session() as s:
        return list(s.exec(select(Memory).where(icontains(Memory.text, query))
                           .order_by(Memory.created_at.desc()).limit(limit)))
