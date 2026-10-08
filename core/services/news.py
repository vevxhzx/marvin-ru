"""Новости: RSS-дайджест по выбранным лентам.

Всё входящее — никаких платных API и ключей: RSS есть почти у каждого издания.
Ленты задаются в настройках (news.feeds, по строке «Название | URL»), забираются
через httpx напрямую, разбираются стандартной библиотекой (никаких новых зависимостей).

Как устроено:
  • news.enabled — выключено по умолчанию, ничего не качает и не присылает;
  • news.time — «ЧЧ:ММ» для утренней отправки планировщиком (пусто — только вручную);
  • /api/news и /news в Telegram — чистое чтение, прочитанное не отмечают;
  • планировщик отмечает показанное (settings: news.seen, TTL 7 дней), повторы не шлёт;
  • описания — как даёт лента (обычно 1–2 предложения), режем до 180 символов,
    HTML-теги вычищаем. Выжимка нейронкой — следующим шагом, если понадобится.

Прокси — тот же, что у Telegram (news из России часть лент без него не отвечает).
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

import httpx

from ..config import cfg
from ..db import get_setting, set_setting

log = logging.getLogger("jarvis.news")

UA = "MarvinRSS/1.0 (+local assistant)"
SEEN_KEY = "news.seen"
SEEN_TTL_DAYS = 7
FETCH_TIMEOUT = 20.0


# ---------------------------------------------------------------- настройки
def _n():
    return getattr(cfg, "news", None)


def enabled() -> bool:
    n = _n()
    return bool(n and getattr(n, "enabled", False))


def digest_time() -> str | None:
    """«ЧЧ:ММ» для автоотправки; None — только вручную."""
    n = _n()
    raw = str(getattr(n, "time", "") or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", raw):
        return None
    return raw


def feed_list() -> list[tuple[str, str]]:
    """Строки «Название | URL» (голый URL — название из адреса). Мусор пропускаем молча."""
    n = _n()
    raw = str(getattr(n, "feeds", "") or "")
    out: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            name, _, url = line.partition("|")
            name, url = name.strip(), url.strip()
        else:
            url, name = line, ""
        if not re.match(r"https?://", url):
            continue
        out.append((name or re.sub(r"^www\.", "", url.split("/")[2]), url))
    return out


def configured() -> bool:
    return bool(enabled() and feed_list())


def proxy() -> str | None:
    tg = str(getattr(cfg.telegram, "proxy", "") or "").strip()
    return tg or None


def _client() -> httpx.AsyncClient:
    kw: dict[str, Any] = {"timeout": FETCH_TIMEOUT, "trust_env": False, "follow_redirects": True,
                          "headers": {"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}}
    if proxy():
        kw["proxy"] = proxy()
    return httpx.AsyncClient(**kw)


# ---------------------------------------------------------------- разбор ленты
_TAG_RX = re.compile(r"<[^>]+>")


def _clean(text: str, limit: int = 180) -> str:
    text = html.unescape(_TAG_RX.sub("", text or "")).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip(" ,;:.") + ("…" if len(text) > limit else "")


def _bare_link(url: str) -> str:
    """Ссылка без utm-хвостов (ленты любят приклеивать utm_source=rss — в дайджесте мусор)."""
    try:
        p = urlsplit(url.strip())
        q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")]
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))
    except Exception:
        return url


def parse_feed(data: bytes, source: str = "") -> list[dict]:
    """RSS 2.0 (channel/item) и Atom (feed/entry) → [{title, link, desc}]."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        log.warning("новости: %s — битый XML (%s)", source or "лента", e)
        return []
    tag = root.tag
    items: list[dict] = []
    if tag == "rss" or root.find("channel") is not None:
        for it in root.findall("./channel/item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = it.findtext("description") or ""
            if not title or not link:
                continue
            items.append({"title": _clean(title, 200), "link": _bare_link(link), "desc": _clean(desc)})
    elif tag.endswith("feed"):
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for it in root.findall("a:entry", ns):
            title = (it.findtext("a:title", "", ns) or "").strip()
            href = it.find("a:link[@rel='alternate']", ns)
            if href is None:
                href = it.find("a:link", ns)
            link = (href.get("href", "") if href is not None else "").strip()
            desc = it.findtext("a:summary", "", ns) or it.findtext("a:content", "", ns) or ""
            if not title or not link:
                continue
            items.append({"title": _clean(title, 200), "link": _bare_link(link), "desc": _clean(desc)})
    else:
        log.warning("новости: %s — неизвестный формат (%s)", source or "лента", tag)
    return items


async def _fetch_one(client: httpx.AsyncClient, name: str, url: str) -> tuple[list[dict], str | None]:
    try:
        r = await client.get(url)
        r.raise_for_status()
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:120]}"
        log.warning("новости: %s не забралась (%s)", name, err)
        return [], err
    return parse_feed(r.content, name), None


# ---------------------------------------------------------------- прочитанное
def _seen_load() -> dict:
    try:
        return json.loads(get_setting(SEEN_KEY) or "{}")
    except ValueError:
        return {}


def _seen_save(seen: dict) -> None:
    try:
        set_setting(SEEN_KEY, json.dumps(seen, ensure_ascii=False))
    except Exception as e:  # pragma: no cover — запись настроек не должна ронять дайджест
        log.warning("новости: не сохранил прочитанное (%s)", e)


def _key(item: dict) -> str:
    return hashlib.sha1((item.get("link") or item.get("title", "")).encode()).hexdigest()[:16]


def mark_seen(items: list[dict]) -> None:
    seen = _seen_load()
    now = datetime.now().isoformat(timespec="seconds")
    for it in items:
        seen[_key(it)] = now
    cutoff = (datetime.now() - timedelta(days=SEEN_TTL_DAYS)).isoformat()
    _seen_save({k: v for k, v in seen.items() if v >= cutoff})


def _only_new(items: list[dict]) -> list[dict]:
    seen = _seen_load()
    return [it for it in items if _key(it) not in seen]


# ---------------------------------------------------------------- дайджест
async def fetch_digest(topic: str | None = None, max_per: int = 5, mark: bool = False) -> dict:
    """Собрать дайджест. topic — подстрока названия ленты (пусто — все). mark — отметить показанное."""
    max_per = max(1, min(max_per or 5, 10))
    feeds = feed_list()
    if topic:
        low = topic.strip().lower()
        feeds = [(n, u) for n, u in feeds if low in n.lower() or low in u.lower()]
        if not feeds:
            return {"ok": False, "text": f"Ленты «{topic.strip()}» у меня нет, сэр. Ленты задаются в настройках.",
                    "feeds": [], "errors": {}, "total": 0}
    if not feeds:
        return {"ok": False, "text": "Ленты не заданы: добавьте их в настройках (интеграции → новости).",
                "feeds": [], "errors": {}, "total": 0}
    out, errors = [], {}
    async with _client() as client:
        for name, url in feeds:
            items, err = await _fetch_one(client, name, url)
            if err:
                errors[name] = err
                continue
            if mark:
                fresh = _only_new(items)
                items = fresh if fresh else items[:0]
            out.append({"name": name, "url": url, "items": items[:max_per]})
    shown = [it for f in out for it in f["items"]]
    if mark and shown:
        mark_seen(shown)
    total = len(shown)
    if not total and errors and not mark:
        first = next(iter(errors.values()))
        return {"ok": False, "text": f"Ленты не ответили, сэр ({first}). Проверьте сеть/прокси.",
                "feeds": out, "errors": errors, "total": 0}
    if not total:
        return {"ok": True, "text": "Нового нет, сэр — всё уже показывал.", "feeds": out, "errors": errors, "total": 0}
    lines = [f"📰 **НОВОСТИ** · {datetime.now():%d.%m %H:%M}"]
    for f in out:
        if not f["items"]:
            continue
        lines.append(f"\n**{f['name']}**")
        for it in f["items"]:
            lines.append(f"— {it['title']}")
            if it["desc"]:
                lines.append(f"  {it['desc']}")
            lines.append(f"  {it['link']}")
    if errors:
        lines.append(f"\n_Не ответили: {', '.join(errors)}_")
    return {"ok": True, "text": "\n".join(lines), "feeds": out, "errors": errors, "total": total}
