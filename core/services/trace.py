"""Журнал работы ассистента: что он сделал с каждой фразой и чем это кончилось.

Зачем. До этого «почему он записал это как трату», «почему ответ шёл 14 секунд» и «какой инструмент чаще падает»
можно было выяснить только чтением лога процесса — а лог перезаписывается и в него никто не смотрит. Теперь каждый
разговорный ход — строка в базе (db.Run): путь (правила / локальная модель / облако), модель, вызванные инструменты
с пометкой упавших, число кругов «модель → инструмент → модель», время, переспросил ли, исправил ли его хозяин следом.

Что это даёт сразу:
  • «отчёт о себе» в чате и на сайте — ассистент честно докладывает, где тупит;
  • блок в воскресном дайджесте — раз в неделю сам, без просьбы;
  • route_stats() — реальная цена и надёжность каждого маршрута: основа для умного выбора модели,
    вместо «если сложность > 5 — большая модель».

Журнал ничего не выполняет и ни на что не влияет — только пишет и считает. Любой сбой внутри проглатывается:
сломанный журнал не должен ломать ответ хозяину.

Приватность: живёт в той же data/assistant.db, что и переписка; текст реплики режется до TEXT_MAX знаков и
проходит тот же фильтр секретов, что и память. Выключается trace.enabled: false — тогда не пишется ничего.
Хранится trace.keep_days дней (по умолчанию 60), дальше ночная уборка удаляет.
"""
from __future__ import annotations

import contextvars
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import select

from ..config import cfg
from ..db import Run, session

log = logging.getLogger("assistant.trace")

TEXT_MAX = 200          # сколько знаков реплики храним (для «почему он так решил» хватает начала)
KEEP_DAYS_DEFAULT = 60
SLOW_MS = 8000          # дольше этого — «медленно», попадает в отчёт
ROUTE_RU = {"rules": "правила", "ollama": "локальная модель", "gemini": "облако", "none": "не понял"}


def enabled() -> bool:
    t = getattr(cfg, "trace", None)
    return bool(getattr(t, "enabled", True)) if t is not None else True


def keep_days() -> int:
    t = getattr(cfg, "trace", None)
    try:
        return max(1, int(getattr(t, "keep_days", KEEP_DAYS_DEFAULT) or KEEP_DAYS_DEFAULT)) if t is not None else KEEP_DAYS_DEFAULT
    except (TypeError, ValueError):
        return KEEP_DAYS_DEFAULT


# ---------------------------------------------------------------- текущий ход
@dataclass
class _Current:
    text: str
    channel: str
    t0: float = field(default_factory=time.monotonic)
    tools: list[str] = field(default_factory=list)
    steps: int = 0
    model: str = ""


_cur: contextvars.ContextVar[_Current | None] = contextvars.ContextVar("trace_current", default=None)


def _key(t: str) -> str:
    """Фраза к сравнимому виду: урок хранит её подчищенной, журнал — как сказал хозяин."""
    import re
    return re.sub(r"\s+", " ", (t or "").strip(" .!,;:—-")).lower()


def start(text: str, channel: str) -> None:
    """Начало обработки фразы. Вызывается один раз из agent.handle()."""
    if not enabled():
        return
    try:
        from ..brain import llm
        _cur.set(_Current(text=llm._hide_secrets(text or "")[:TEXT_MAX], channel=channel))
    except Exception as e:  # pragma: no cover — журнал не имеет права ломать ответ
        log.debug("trace.start: %s", e)


def tool(name: str, ok: bool = True) -> None:
    """Инструмент отработал. Вызывается из registry.run_tool — поэтому в журнал попадают и падения,
    которые модель прячет в текст ответа («Ошибка инструмента: …»)."""
    c = _cur.get()
    if c is not None and name:
        c.tools.append(name + ("" if ok else "!"))


def step(model: str = "") -> None:
    """Ещё один круг «модель → инструмент → модель»."""
    c = _cur.get()
    if c is not None:
        c.steps += 1
        if model:
            c.model = model


def finish(route: str = "none", actions: list[str] | None = None, ok: bool = True, error: str = "") -> int | None:
    """Конец обработки: пишем строку. Возвращает id (или None, если журнал выключен)."""
    c = _cur.get()
    _cur.set(None)
    if c is None:
        return None
    acts = list(actions or [])
    try:
        row = Run(text=c.text, channel=c.channel, route=route or "none", model=c.model,
                  tools=",".join(c.tools)[:500], actions=",".join(acts)[:300], steps=c.steps,
                  ms=int((time.monotonic() - c.t0) * 1000),
                  ok=bool(ok) and route != "none", asked="clarify" in acts, error=(error or "")[:300])
        with session() as s:
            s.add(row)
            s.commit()
            return row.id
    except Exception as e:  # pragma: no cover
        log.debug("trace.finish: %s", e)
        return None


def mark_corrected(channel: str | None = None, text: str | None = None, within_min: int = 60) -> None:
    """Хозяин отменил запись («отмени») или поправил тип («это заказ») — значит, тот ход был неверным.

    Если известна сама фраза (урок судьи знает её точно) — ищем ход именно по ней. Если нет («отмени» не говорит,
    что отменяем) — берём последний ход, который что-то записал. Не нашли — молчим: лучше недосчитать исправление,
    чем повесить чужую ошибку на невинную строку.
    """
    if not enabled():
        return
    try:
        since = datetime.now() - timedelta(minutes=within_min)
        key = _key(text) if text else None
        with session() as s:
            q = select(Run).where(Run.created_at >= since, Run.corrected == False)  # noqa: E712
            if channel:
                q = q.where(Run.channel == channel)
            rows = list(s.exec(q.order_by(Run.id.desc()).limit(20)))
            if key:
                target = next((r for r in rows if _key(r.text) == key or _key(r.text).startswith(key)), None)
            else:
                target = next((r for r in rows if r.actions or r.tools), None)
            if target:
                target.corrected = True
                s.add(target)
                s.commit()
    except Exception as e:  # pragma: no cover
        log.debug("trace.mark_corrected: %s", e)


# ---------------------------------------------------------------- чтение
def recent(limit: int = 50, channel: str | None = None, only_bad: bool = False) -> list[dict]:
    """Последние ходы для сайта: что спросили, куда пошёл, что вызвал, сколько занял."""
    with session() as s:
        q = select(Run)
        if channel:
            q = q.where(Run.channel == channel)
        if only_bad:
            q = q.where((Run.ok == False) | (Run.corrected == True) | (Run.asked == True))  # noqa: E712
        rows = list(s.exec(q.order_by(Run.id.desc()).limit(max(1, min(limit, 500)))))
    return [{"id": r.id, "at": r.created_at.isoformat(), "text": r.text, "channel": r.channel,
             "route": r.route, "route_ru": ROUTE_RU.get(r.route, r.route), "model": r.model,
             "tools": [t for t in r.tools.split(",") if t], "actions": [a for a in r.actions.split(",") if a],
             "steps": r.steps, "ms": r.ms, "ok": r.ok, "asked": r.asked, "corrected": r.corrected,
             "error": r.error} for r in rows]


def route_stats(days: int = 14) -> dict[str, dict]:
    """Сколько стоит и насколько надёжен каждый маршрут: {route: {n, ms_avg, ms_p90, fail, corrected}}.
    Это те цифры, на которых можно строить выбор модели — измеренные на этом ПК, а не угаданные."""
    since = datetime.now() - timedelta(days=days)
    with session() as s:
        rows = list(s.exec(select(Run).where(Run.created_at >= since)))
    out: dict[str, dict] = {}
    for r in rows:
        d = out.setdefault(r.route, {"n": 0, "ms": [], "fail": 0, "corrected": 0, "asked": 0})
        d["n"] += 1
        d["ms"].append(r.ms)
        d["fail"] += 0 if r.ok else 1
        d["corrected"] += 1 if r.corrected else 0
        d["asked"] += 1 if r.asked else 0
    for d in out.values():
        ms = sorted(d.pop("ms")) or [0]
        d["ms_avg"] = int(sum(ms) / len(ms))
        d["ms_p90"] = ms[min(len(ms) - 1, int(len(ms) * 0.9))]
    return out


def tool_stats(days: int = 14) -> list[dict]:
    """Какие инструменты вызываются и какие из них падают — отсортировано по числу падений."""
    since = datetime.now() - timedelta(days=days)
    with session() as s:
        rows = list(s.exec(select(Run).where(Run.created_at >= since)))
    agg: dict[str, dict] = {}
    for r in rows:
        for t in r.tools.split(","):
            if not t:
                continue
            name, bad = (t[:-1], True) if t.endswith("!") else (t, False)
            d = agg.setdefault(name, {"name": name, "n": 0, "fail": 0})
            d["n"] += 1
            d["fail"] += 1 if bad else 0
    return sorted(agg.values(), key=lambda d: (-d["fail"], -d["n"]))


def report(days: int = 7) -> dict:
    """Сводка за период — то, из чего собирается человеческий отчёт и что отдаётся сайту."""
    since = datetime.now() - timedelta(days=days)
    with session() as s:
        rows = list(s.exec(select(Run).where(Run.created_at >= since)))
    n = len(rows)
    slow = sorted([r for r in rows if r.ms >= SLOW_MS], key=lambda r: -r.ms)
    return {
        "days": days, "n": n,
        "failed": sum(1 for r in rows if not r.ok),
        "asked": sum(1 for r in rows if r.asked),
        "corrected": sum(1 for r in rows if r.corrected),
        "slow": len(slow),
        "slowest": [{"text": r.text, "route": r.route, "ms": r.ms} for r in slow[:3]],
        "routes": route_stats(days),
        "tools": tool_stats(days)[:8],
        "corrections": [{"text": r.text, "actions": [a for a in r.actions.split(",") if a]}
                        for r in rows if r.corrected][-5:],
        "errors": [{"text": r.text, "error": r.error} for r in rows if r.error][-5:],
    }


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def report_text(days: int = 7) -> str:
    """Отчёт словами — для чата и Telegram. Пустая строка, если говорить не о чем."""
    d = report(days)
    if not d["n"]:
        return ""
    lines = [f"🧾 Как я работал за {days} дн.: {d['n']} обращений."]
    routes = sorted(d["routes"].items(), key=lambda kv: -kv[1]["n"])
    parts = [f"{ROUTE_RU.get(k, k)} {v['n']} ({v['ms_avg'] / 1000:.1f} с)" for k, v in routes if v["n"]]
    if parts:
        lines.append("Пути: " + " · ".join(parts) + ".")
    if d["failed"]:
        lines.append(f"Не справился: {d['failed']} раз ({_pct(d['failed'], d['n'])}%).")
    if d["asked"]:
        lines.append(f"Переспрашивал: {d['asked']}.")
    if d["corrected"]:
        ex = "; ".join(f"«{c['text'][:40]}»" for c in d["corrections"][-2:])
        lines.append(f"Вы меня поправили: {d['corrected']} раз" + (f" — например, {ex}." if ex else "."))
    bad_tools = [t for t in d["tools"] if t["fail"]]
    if bad_tools:
        lines.append("Падали инструменты: " + ", ".join(f"{t['name']} ({t['fail']} из {t['n']})" for t in bad_tools[:3]) + ".")
    if d["slow"]:
        s0 = d["slowest"][0]
        lines.append(f"Медленнее {SLOW_MS // 1000} с: {d['slow']} раз, дольше всего — «{s0['text'][:40]}» ({s0['ms'] / 1000:.0f} с).")
    if len(lines) == 2 and not d["failed"] and not d["corrected"]:
        lines.append("Жалоб нет, сэр.")
    return "\n".join(lines)


def weekly_block(days: int = 7) -> list[str]:
    """Хвост для воскресного дайджеста — как pulse.weekly_block(). Молчим, если неделя была спокойной."""
    d = report(days)
    if d["n"] < 5 or not (d["failed"] or d["corrected"] or d["slow"] or any(t["fail"] for t in d["tools"])):
        return []
    return ["", report_text(days)]


def cleanup(days: int | None = None) -> int:
    """Ночная уборка: строки старше keep_days удаляются. Возвращает, сколько удалено."""
    limit = datetime.now() - timedelta(days=days if days is not None else keep_days())
    with session() as s:
        rows = list(s.exec(select(Run).where(Run.created_at < limit)))
        for r in rows:
            s.delete(r)
        s.commit()
    return len(rows)
