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
    """Ссылка без мусорных хвостов (utm_* и from=rss — в дайджесте мусор)."""
    try:
        p = urlsplit(url.strip())
        q = [(k, v) for k, v in parse_qsl(p.query)
             if not k.lower().startswith("utm_") and not (k.lower() == "from" and v.lower() == "rss")]
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))
    except Exception:
        return url


_STOPWORDS = frozenset("это как так уже всего самый новый время год после между который можно "
                      "россии российский российская российские сегодня вчера завтра просто очень "
                      "будет было есть нет да для при без под над".split())


def _story_words(title: str) -> frozenset:
    """Значимые основы слов заголовка (первая находка дублей: одна история разными словами)."""
    words = re.findall(r"[а-яёa-z0-9]{4,}", (title or "").lower().replace("ё", "е"))
    out = set()
    for w in words:
        if w in _STOPWORDS:
            continue
        out.add(w if len(w) <= 5 else w[:6])
    return frozenset(out)


def dedupe_stories(items: list[dict]) -> list[dict]:
    """Склейка дублей: одна история в разных лентах — остаётся первая, остальные выкидываем.
    Считаем дублем ≥4 общих основы при жаккаре ≥0.22 (проверено на паре «сбой Яндекса»:
    общие {бпла, дата, центр, яндекс, работе} — жаккар 0.28)."""
    kept: list[dict] = []
    for it in items:
        words = _story_words(it.get("title", ""))
        dupe = False
        for k in kept:
            inter = words & k["_words"]
            union = words | k["_words"]
            if len(inter) >= 4 and union and len(inter) / len(union) >= 0.22:
                dupe = True
                break
        if not dupe:
            it = dict(it)
            it["_words"] = words
            kept.append(it)
    for it in kept:
        it.pop("_words", None)
    if len(kept) != len(items):
        log.info("новости: склеил дублей %d", len(items) - len(kept))
    return kept


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


# ---------------------------------------------------------------- умный отбор
CAND_PER_FEED = 5  # сколько тянем с ленты как кандидатов (показываем меньше — топ)

_SELECT_SYSTEM = ("Ты — редактор утреннего дайджеста. Отбери самое важное для человека, "
    "который следит за ИИ, технологиями и деньгами: прорывы, деньги, то, что влияет на жизнь. "
    "Проходняк и рекламу выкидывай. ЖЕЛЕЗНОЕ ПРАВИЛО: одно событие — один пункт. Если две новости "
    "про одно и то же (совпадают место, компания или суть — хоть и разными словами), оставь ОДНУ "
    "с самой понятной формулировкой, вторую выкинь. "
    "Верни СТРОГО JSON: {\"picks\": [{\"i\": номер новости, \"line\": \"суть одной строкой по-русски\"}]}.")


def top_n() -> int:
    n = _n()
    try:
        return max(3, min(int(getattr(n, "top", 7) or 7), 12))
    except (TypeError, ValueError):
        return 7


async def select_top(cands: list[dict], top: int) -> list[dict]:
    """Топ важных из кандидатов: спрашиваем малую локальную модель, наружу ничего не уходит.
    Не вышло (нет модели, битый JSON) — по кругу из разных лент, чтобы не было 7 новостей с одного Хабра."""
    if len(cands) <= top:
        return cands
    numbered = "\n".join(f"{k + 1}. [{c['feed']}] {c['title'][:100]} — {c.get('desc', '')[:100]}"
                         for k, c in enumerate(cands))
    try:
        from ..brain import llm as _llm
        raw = await _llm.small_chat(_SELECT_SYSTEM, f"Новостей: {len(cands)}, отобрать {top}:\n{numbered}",
                                    json_mode=True, num_predict=600)
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        picks, seen = [], set()
        for p in (data.get("picks") or [])[:top]:
            i = int(p.get("i", 0)) - 1
            line = str(p.get("line") or "").strip()
            if 0 <= i < len(cands) and i not in seen and line:
                seen.add(i)
                picks.append({**cands[i], "line": line[:200]})
        if picks:
            log.info("новости: отобрал %d из %d", len(picks), len(cands))
            return picks
        log.warning("новости: модель вернула пустой отбор — даю первые")
    except Exception as e:
        log.warning("новости: отбор не сработал (%s) — даю первые", str(e)[:100])
    by_feed: dict[str, list[dict]] = {}
    for c in cands:
        by_feed.setdefault(c["feed"], []).append(c)
    out: list[dict] = []
    for row in zip(*by_feed.values()):
        out.extend(row)
        if len(out) >= top:
            break
    return out[:top]


# ---------------------------------------------------------------- дайджест
async def fetch_digest(topic: str | None = None, limit: int = 7, mark: bool = False,
                     header: str | None = None) -> dict:
    """Собрать дайджест. topic — подстрока названия ленты (пусто — все). limit — максимум новостей
    (умный отбор топа, см. select_top). mark — отметить показанное. header — строка верхом (погода)."""
    limit = max(1, min(limit or 7, 12))
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
            for it in items[:CAND_PER_FEED]:
                it["feed"] = name
            out.append({"name": name, "url": url, "items": items[:CAND_PER_FEED]})
    cands = dedupe_stories([it for f in out for it in f["items"]])
    shown = await select_top(cands, limit)
    if mark and shown:
        mark_seen(shown)
    total = len(shown)
    if not total and errors and not mark:
        first = next(iter(errors.values()))
        return {"ok": False, "text": f"Ленты не ответили, сэр ({first}). Проверьте сеть/прокси.",
                "feeds": out, "errors": errors, "total": 0}
    if not total:
        return {"ok": True, "text": "Нового нет, сэр — всё уже показывал.", "feeds": out, "errors": errors, "total": 0}
    lines = [f"📰 **НОВОСТИ · ТОП-{total}** · {datetime.now():%d.%m %H:%M}"]
    if header:
        lines.append(header)
    cur_feed = None
    for it in shown:
        if it["feed"] != cur_feed:
            cur_feed = it["feed"]
            lines.append(f"\n**{cur_feed}**")
        lines.append(f"— {it.get('line') or it['title']}")
        if not it.get("line") and it["desc"]:
            lines.append(f"  {it['desc']}")
        lines.append(f"  {it['link']}")
    if errors:
        lines.append(f"\n_Не ответили: {', '.join(errors)}_")
    return {"ok": True, "text": "\n".join(lines), "feeds": out, "errors": errors, "total": total}
