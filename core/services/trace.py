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
from .plural import days as _days_word

log = logging.getLogger("jarvis.trace")

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
    # счётчик токенов обнуляем ВСЕГДА, даже когда журнал выключен: иначе выключенный trace
    # копил бы вызовы в памяти контекста запроса, а читать их всё равно некому.
    try:
        from ..brain import llm
        llm.usage_reset()
    except Exception:  # pragma: no cover
        pass
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
    """Конец обработки: пишем строку. Возвращает id (или None, если журнал выключен).

    Токены и деньги подтягиваются из счётчика провайдера (brain/llm/base.py). За ход модель
    зовётся обычно один раз, но в цикле «модель → инструмент → модель» — два-четыре: накопленное
    уже суммировано, поэтому просто забираем. Цена считается по модели КАЖДОГО вызова — локальная
    бесплатна, облако платное, и в одном ходе они чередуются."""
    c = _cur.get()
    _cur.set(None)
    if c is None:
        return None
    acts = list(actions or [])
    try:
        last_model = _last_model()          # ДО сброса счётчика: usage_now() его обнулит
        prompt, completion, cost = _usage_of()
        row = Run(text=c.text, channel=c.channel, route=route or "none", model=c.model or last_model,
                  tools=",".join(c.tools)[:500], actions=",".join(acts)[:300], steps=c.steps,
                  ms=int((time.monotonic() - c.t0) * 1000),
                  ok=bool(ok) and route != "none", asked="clarify" in acts, error=(error or "")[:300],
                  prompt_tokens=prompt, completion_tokens=completion, cost_usd=cost)
        with session() as s:
            s.add(row)
            s.commit()
            return row.id
    except Exception as e:  # pragma: no cover
        log.debug("trace.finish: %s", e)
        return None


def _usage_of() -> tuple[int, int, float]:
    """(prompt, completion, доллары) за текущий ход; счётчик обнуляется. Любой сбой — честные нули."""
    try:
        from ..brain.llm import base as llm_base
        u = llm_base.usage_now()
        llm_base.usage_reset()
        cost, _priced = u.cost()
        return (u.prompt_tokens, u.completion_tokens, cost)
    except Exception as e:  # pragma: no cover
        log.debug("trace.usage: %s", e)
        return (0, 0, 0.0)


def _last_model() -> str:
    """Модель, которая ответила последней, — если trace.step() её не назвал (бывает: локальный
    путь не зовёт step). Иначе в разбивке «по моделям» половина строк была бы без модели."""
    try:
        from ..brain.llm import base as llm_base
        models = llm_base.usage_now().models
        return models[-1] if models else ""
    except Exception:  # pragma: no cover
        return ""


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
                # последний ход, который что-то записал: голые уточнения («календарь или задача?»,
                # «отменить …? да/нет») пропускаем — иначе помечаем сам вопрос, а не неверную запись
                def _did(r) -> bool:
                    acts = [a for a in (r.actions or "").split(",") if a]
                    return bool((acts and any(a != "clarify" for a in acts)) or (r.tools or "").strip())
                target = next((r for r in rows if _did(r)), None)
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
             "error": r.error,
             "prompt_tokens": r.prompt_tokens or 0, "completion_tokens": r.completion_tokens or 0,
             "tokens": (r.prompt_tokens or 0) + (r.completion_tokens or 0),
             "cost_usd": round(float(r.cost_usd or 0.0), 6),
             "priced": _is_priced(r)}
            for r in rows]


def _is_priced(r) -> bool:
    """Стоимость этого хода ИЗВЕСТНА — можно ли показывать деньги?

    Три случая, и их надо различать (иначе хозяин видит неправду):
      • cost_usd > 0 — деньги посчитаны и записаны. Правда даже если цену с тех пор убрали:
        деньги-то потрачены, отменить их удалением настройки нельзя;
      • цена есть в brain.pricing и равна нулю — модель бесплатная, $0.00 — это правда;
      • ни того, ни другого — цену не задавали, стоимость 0 означает «не знаю», а не «бесплатно»."""
    if float(r.cost_usd or 0.0) > 0:
        return True
    try:
        from ..brain.llm import base as llm_base
        return bool(llm_base.pricing_for(r.model))
    except Exception:  # pragma: no cover
        return False


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


def spend_stats(days: int = 7) -> dict:
    """Сколько токенов и денег ушло за период. Главное для хозяина: он платит облаку.

    Честность вместо удобства: `uncpriced` — ходы, где токены были, а стоимость НЕИЗВЕСТНА
    (цены модели в brain.pricing нет и записывать было нечего). Их стоимость НЕ приравнивается
    к нулю молча — видно, сколько ещё не посчитано, и настройка цены это закрывает.
    Обратный случай тоже честный: ход, посчитанный по цене, остаётся посчитанным, даже если цену
    потом убрали из настроек — деньги-то потрачены."""
    since = datetime.now() - timedelta(days=days)
    with session() as s:
        rows = list(s.exec(select(Run).where(Run.created_at >= since)))
    total = 0.0
    tok_in = tok_out = uncpriced = priced_n = 0
    by_route: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    for r in rows:
        p, c = int(r.prompt_tokens or 0), int(r.completion_tokens or 0)
        usd = round(float(r.cost_usd or 0.0), 8)
        is_priced = _is_priced(r)
        tok_in += p
        tok_out += c
        total += usd
        if p or c:
            priced_n += 1 if is_priced else 0
            uncpriced += 1 if not is_priced else 0
        key = r.route or "none"
        dr = by_route.setdefault(key, {"ru": ROUTE_RU.get(key, key), "n": 0, "usd": 0.0,
                                       "tokens_in": 0, "tokens_out": 0, "uncpriced": 0})
        dr["n"] += 1
        dr["usd"] = round(dr["usd"] + usd, 8)
        dr["tokens_in"] += p
        dr["tokens_out"] += c
        dr["uncpriced"] += 1 if (p or c) and not is_priced else 0
        mk = r.model or "—"
        dm = by_model.setdefault(mk, {"n": 0, "usd": 0.0, "tokens_in": 0, "tokens_out": 0, "uncpriced": 0})
        dm["n"] += 1
        dm["usd"] = round(dm["usd"] + usd, 8)
        dm["tokens_in"] += p
        dm["tokens_out"] += c
        dm["uncpriced"] += 1 if (p or c) and not is_priced else 0
    try:
        from ..brain.llm import base as llm_base
        configured = llm_base.pricing_ready()
    except Exception:  # pragma: no cover
        configured = bool(total)
    return {"days": days, "total_usd": round(total, 6), "tokens_in": tok_in, "tokens_out": tok_out,
            "runs": len(rows),
            # priced — цена настроена СЕЙЧАС (по этому флагу сайт зовёт «задайте цену»).
            # counted — стоимость хотя бы части ходов известна (записана раньше или посчитана
            # по явному нулю «бесплатно»). Два флага, потому что одно не выводится из другого:
            # цену могли посчитать вчера и убрать сегодня — деньги потрачены, а настройки нет.
            "priced": configured, "counted": bool(total) or priced_n > 0,
            "priced_runs": priced_n, "uncpriced": uncpriced,
            "by_route": by_route, "by_model": by_model}


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
        "spend": spend_stats(days),
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
    lines = [f"🧾 Как я работал за {days} {_days_word(days)}: {d['n']} обращений."]
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
    sp = d.get("spend") or {}
    # Деньги — только когда они посчитаны. Молчание о цене честнее «$0.00»: это значит
    # «не знаю», а не «бесплатно», и хозяин пойдёт вписывать цену модели в настройки.
    # Если часть ходов посчитана, а часть — нет, говорим и то и то: сумма честная,
    # но неполная, и молчать про «не знаю» было бы враньём.
    if sp.get("total_usd"):
        tail = (f" Не посчитал ещё {sp['uncpriced']} ходов — цены их моделей нет."
                if sp.get("uncpriced") else "")
        lines.append(f"Потрачено на модели: ${sp['total_usd']:.4f} "
                     f"({sp['tokens_in']} ток. вход + {sp['tokens_out']} выход).{tail}")
    elif sp.get("uncpriced"):
        lines.append(f"Токенов: {sp['tokens_in']} вход + {sp['tokens_out']} выход. "
                     f"Сколько это в деньгах — не знаю: цены моделей не заданы (настройки → мозг → облако).")
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
