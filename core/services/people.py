"""Люди: карточка человека/клиента собирается из всей базы по упоминаниям имени.

Ничего не дублируем: заказы, оплаты, долги, встречи, задачи, заметки — уже лежат в своих таблицах, здесь только
поиск связей по имени (и псевдонимам) плюс триггеры: «Иванов — с ним у вас…» когда человек всплывает в разговоре
или в календаре на сегодня.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Client, Debt, Event, Link, Note, Order, Task, Transaction, session
from .match import stem, tokens

# ---------------------------------------------------------------- имена и совпадения
_WORD_RX = re.compile(r"[а-яёa-z0-9@_]+", re.I)


def names_of(c: Client) -> list[str]:
    """Основное имя + псевдонимы, без пустых."""
    out = [c.name] + [a.strip() for a in (c.aliases or "").split(",")]
    return [n for n in dict.fromkeys(x.strip(" «»\"'") for x in out) if n]


def _name_stems(name: str) -> list[str]:
    """«Иван Петров» → ['иван', 'петров']; «@ivan» → ['@ivan']; короткие («Ваня») — режем аккуратно, чтобы «ван» не ловил «Ванну»."""
    parts = []
    for w in _WORD_RX.findall(name.lower().replace("ё", "е")):
        if w.startswith("@") or len(w) <= 3:
            parts.append(w)
        else:
            parts.append(stem(w))
    return parts


def mentions(text: str | None, c: Client) -> bool:
    """Упоминается ли человек в тексте: все слова имени (или любого псевдонима) должны найтись основами.
    Односложные имена типа «Ваня» проверяем по границе слова с падежами: ваня/вани/ване/ваню/ваней."""
    if not text:
        return False
    low = text.lower().replace("ё", "е")
    words = set(_WORD_RX.findall(low))
    word_stems = {stem(w) if len(w) > 3 else w for w in words}
    for name in names_of(c):
        st = _name_stems(name)
        if not st:
            continue
        # «Иван Петров»: хватит одного имени («созвон с Иваном») или фамилии — но не коротких («Ли», «Ян»)
        variants = [st] + ([[st[0]] if len(st[0]) >= 4 else []] if len(st) > 1 else []) + ([[st[-1]] if len(st[-1]) >= 5 else []] if len(st) > 1 else [])
        if any(_match_parts(v, words, word_stems) for v in variants if v):
            return True
    return False


def _match_parts(st: list[str], words: set[str], word_stems: set[str]) -> bool:
    if True:
        ok = True
        for p in st:
            if p.startswith("@"):
                if p not in words:
                    ok = False; break
            elif len(p) <= 3:
                # короткое имя: точная форма или падеж (ваня→ван+я/и/е/ю/ей)
                base = p[:-1] if p[-1] in "аяй" and len(p) > 2 else p
                if not any(w == p or (w.startswith(base) and len(w) <= len(base) + 2 and w[len(base):] in ("", "а", "я", "и", "е", "у", "ю", "ей", "ой", "ем", "ом")) for w in words):
                    ok = False; break
            elif not any(ws == p or (ws.startswith(p) and ws[len(p):] in _CASE_TAILS) for ws in word_stems):
                ok = False; break
        return ok


# что остаётся после грубого стемминга у падежных форм: Иваном → «иваном» = иван + ом. «Иванов»/«Ивановка» — другие люди/места
_CASE_TAILS = {"", "ом", "ем", "ём", "ым", "им", "ой", "ей", "ах", "ям", "ами", "ями", "ах", "ях"}


def find_person(query: str) -> Client | None:
    """Кто имеется в виду: «ваня», «Иванов», «@ivan», «пятёрочка»."""
    q = (query or "").strip(" «»\"'?.!,")
    if not q:
        return None
    with session() as s:
        people = list(s.exec(select(Client)))
    ql = q.lower().replace("ё", "е")
    for c in people:
        if any(n.lower().replace("ё", "е") == ql for n in names_of(c)):
            return c
    qs = tokens(q)
    if not qs:
        return None
    best, best_n = None, 0
    for c in people:
        for name in names_of(c):
            ns = _name_stems(name)
            hit = sum(1 for t in qs if any(t == n or (len(t) >= 3 and (n.startswith(t) or t.startswith(n))) for n in ns))
            if hit and hit == len(qs) and hit > best_n:
                best, best_n = c, hit
    return best


def people_in_text(text: str) -> list[Client]:
    """Все известные люди, упомянутые в тексте (для триггеров в чате)."""
    if not text or len(text) < 3:
        return []
    with session() as s:
        people = list(s.exec(select(Client)))
    return [c for c in people if mentions(text, c)]


# ---------------------------------------------------------------- карточка
def _order_row(o: Order, paid: float) -> dict:
    from .orders import STATUS_LABEL, OPEN, UNPAID
    return {"id": o.id, "title": o.title, "price": o.price, "paid": paid, "left": max(0.0, o.price - paid) if o.status in UNPAID else 0.0, "status": o.status,
            "status_label": STATUS_LABEL.get(o.status, o.status), "deadline": o.deadline, "created_at": o.created_at,
            "open": o.status in OPEN, "unpaid": o.status in UNPAID and o.price - paid > 0}


def _next_payday(c: Client):
    from . import pulse
    d = pulse.next_payday(c)
    return d.isoformat() if d else None


def card(c: Client, limit: int = 8) -> dict:
    """Всё про человека: заказы (и деньги по ним), долги, встречи (прошлые/будущие), задачи, заметки, ссылки, последний контакт."""
    now = datetime.now()
    with session() as s:
        orders = list(s.exec(select(Order).where(Order.client_id == c.id).order_by(Order.created_at.desc())))
        paid = {}
        if orders:
            for t in s.exec(select(Transaction).where(Transaction.order_id.in_([o.id for o in orders]), Transaction.kind == "income")):  # type: ignore[union-attr]
                paid[t.order_id] = paid.get(t.order_id, 0.0) + t.amount
        debts = [d for d in s.exec(select(Debt)) if mentions(d.title, c) or mentions(d.creditor, c)]
        events = [e for e in s.exec(select(Event).where(Event.start >= now - timedelta(days=365)).order_by(Event.start.desc()).limit(1500)) if mentions(e.title, c) or mentions(e.notes, c)]
        tasks = [t for t in s.exec(select(Task).where(Task.done == False).order_by(Task.priority, Task.due)) if mentions(t.title, c)]  # noqa: E712
        notes = [n for n in s.exec(select(Note).order_by(Note.created_at.desc()).limit(1500)) if mentions(n.text, c) or mentions(n.title, c) or mentions(n.tags, c)]
        links = [l for l in s.exec(select(Link).order_by(Link.created_at.desc()).limit(800)) if mentions(l.title, c) or mentions(l.comment, c) or mentions(l.tags, c)]
        tx_notes = [t for t in s.exec(select(Transaction).where(Transaction.order_id == None).order_by(Transaction.date.desc()).limit(1500)) if mentions(t.note, c)]  # noqa: E711
    rows = [_order_row(o, paid.get(o.id, 0.0)) for o in orders]
    upcoming = sorted([e for e in events if e.start >= now], key=lambda e: e.start)
    past = [e for e in events if e.start < now]
    stamps = [x for x in [
        max((o.created_at for o in orders), default=None), max((e.start for e in past), default=None),
        max((n.created_at for n in notes), default=None), max((t.date for t in tx_notes), default=None),
    ] if x]
    total_paid = sum(paid.values())
    return {
        "id": c.id, "name": c.name, "kind": c.kind, "kind_label": KIND_LABEL.get(c.kind, c.kind), "contact": c.contact, "about": c.notes, "aliases": c.aliases, "birthday": c.birthday,
        "pay_mode": c.pay_mode or "each", "pay_every": c.pay_every or 14, "pay_days": c.pay_days or "", "next_payday": _next_payday(c),
        "tags": [t.strip() for t in (c.tags or "").split(",") if t.strip()],
        "orders": rows[:limit], "orders_total": len(rows),
        "money": {"paid": round(total_paid), "unpaid": round(sum(r["left"] for r in rows if r["unpaid"])), "open": sum(1 for r in rows if r["open"])},
        "debts": [{"id": d.id, "title": d.title, "remaining": d.remaining, "total": d.total, "closed": d.closed, "creditor": d.creditor} for d in debts if not d.closed][:limit],
        "upcoming": [{"id": e.id, "title": e.title, "start": e.start, "location": e.location, "created_at": e.created_at} for e in upcoming[:limit]],
        "past_events": [{"id": e.id, "title": e.title, "start": e.start} for e in past[:limit]],
        "tasks": [{"id": t.id, "title": t.title, "due": t.due, "priority": t.priority, "created_at": t.created_at} for t in tasks[:limit]],
        "notes": [{"id": n.id, "title": n.title, "text": n.text[:200], "created_at": n.created_at, "image": n.image} for n in notes[:limit]],
        "links": [{"id": l.id, "title": l.title or l.domain, "url": l.url, "created_at": l.created_at} for l in links[:limit]],
        "transactions": [{"id": t.id, "amount": t.amount, "kind": t.kind, "note": t.note, "date": t.date} for t in tx_notes[:limit]],
        "last_contact": max(stamps) if stamps else None,
        "counts": {"orders": len(rows), "debts": len([d for d in debts if not d.closed]), "events": len(events), "tasks": len(tasks), "notes": len(notes), "links": len(links)},
    }


def list_people() -> list[dict]:
    """Список людей с краткой сводкой (для страницы и палитры): открытые заказы, неоплачено, последний контакт."""
    with session() as s:
        people = list(s.exec(select(Client).order_by(Client.name)))
        orders = list(s.exec(select(Order)))
        paid = {}
        for t in s.exec(select(Transaction).where(Transaction.order_id != None, Transaction.kind == "income")):  # noqa: E711
            paid[t.order_id] = paid.get(t.order_id, 0.0) + t.amount
    from .orders import OPEN, UNPAID
    out = []
    for c in people:
        mine = [o for o in orders if o.client_id == c.id]
        out.append({"id": c.id, "name": c.name, "kind": c.kind, "kind_label": KIND_LABEL.get(c.kind, c.kind), "contact": c.contact, "tags": [t.strip() for t in (c.tags or "").split(",") if t.strip()],
                    "birthday": c.birthday, "aliases": c.aliases,
                    "orders": len(mine), "open": sum(1 for o in mine if o.status in OPEN),
                    "unpaid": round(sum(max(0.0, o.price - paid.get(o.id, 0.0)) for o in mine if o.status in UNPAID)),
                    "paid": round(sum(paid.get(o.id, 0.0) for o in mine)),
                    "last_order": max((o.created_at for o in mine), default=None)})
    return out


# Кто это. Встроенные типы + свои (хранятся в настройке people.kinds через запятую: «врач, сосед»).
# person — «просто человек», тип не определён. Раньше все создавались как client — отсюда «все клиенты».
KINDS = ("person", "family", "friend", "client", "company")
KIND_LABEL = {"person": "человек", "family": "семья", "friend": "друг", "client": "клиент", "company": "компания"}
FAMILY_WORDS = {"мама", "мам", "мать", "папа", "пап", "отец", "батя", "брат", "братик", "сестра", "сестрёнка", "сестренка", "жена", "муж",
                "бабушка", "бабуля", "дедушка", "дед", "деда", "сын", "дочь", "дочка", "тётя", "тетя", "дядя", "племянник", "племянница",
                "тёща", "теща", "тесть", "свекровь", "свёкор", "свекор", "кузен", "кузина", "родители", "семья", "родственник", "родственница"}
FRIEND_WORDS = {"друг", "подруга", "друган", "кореш", "бро", "приятель", "приятельница", "лучший друг", "лучшая подруга", "однокурсник", "одноклассник", "сосед", "соседка"}
COMPANY_WORDS = ("ооо", "оао", "зао", "ип ", "компания", "фирма", "студия", "агентство", "бюро", "продакшн", "продакшен", "prod", "production", "studio", "agency", "llc", "inc", "media", "медиа")


def custom_kinds() -> list[str]:
    from ..db import get_setting
    return [k.strip().lower() for k in (get_setting("people.kinds") or "").split(",") if k.strip()]


def all_kinds() -> list[dict]:
    """Для сайта/палитры: встроенные + свои, с подписями."""
    return [{"id": k, "label": KIND_LABEL[k], "custom": False} for k in KINDS] + [{"id": k, "label": k, "custom": True} for k in custom_kinds()]


def normalize_kind(kind: str | None) -> str | None:
    """Принять тип: встроенный id, русская подпись («семья»), или свой (заводится сам, до 30 символов). None — не менять."""
    k = (kind or "").strip().lower()
    if not k:
        return None
    if k in KINDS:
        return k
    for kid, lab in KIND_LABEL.items():
        if k == lab:
            return kid
    if k in ("родня", "родственник", "родственники", "семейный", "свои"):
        return "family"
    if k in ("друзья", "подруга", "приятель"):
        return "friend"
    if k in ("заказчик", "заказчица", "клиентка"):
        return "client"
    if k in ("фирма", "организация", "ооо", "студия", "агентство"):
        return "company"
    if len(k) > 30:
        return None
    if k not in custom_kinds():
        from ..db import set_setting
        set_setting("people.kinds", ", ".join(custom_kinds() + [k]))
    return k


def remove_custom_kind(kind: str) -> int:
    """Убрать свой тип: людям с ним — «человек». Возвращает, скольких переназначили."""
    from ..db import set_setting
    k = (kind or "").strip().lower()
    if not k or k in KINDS:
        return 0
    set_setting("people.kinds", ", ".join(x for x in custom_kinds() if x != k))
    with session() as s:
        rows = s.exec(select(Client).where(Client.kind == k)).all()
        for c in rows:
            c.kind = "person"; s.add(c)
        s.commit()
        return len(rows)


def guess_kind(name: str, notes: str | None = None) -> str:
    """Тип по имени и подписи, когда явно не сказали: «мама» → семья, «Ваня, друг» → друг, «ООО Ромашка» → компания.
    Ни на что не похоже — «человек» (не клиент: клиентом делает только заказ)."""
    low = f"{name} {notes or ''}".lower()
    words = set(re.findall(r"[а-яёa-z]+", low))
    if words & FAMILY_WORDS:
        return "family"
    if words & FRIEND_WORDS or any(w in low for w in ("друг", "подруг")):
        return "friend"
    if any(w in name.lower() for w in COMPANY_WORDS) or any(w in low for w in ("компания", "фирма", "ооо ")):
        return "company"
    if any(w in low for w in ("клиент", "заказчик")):
        return "client"
    return "person"


def add_person(name: str, kind: str | None = "person", contact: str | None = None, notes: str | None = None,
               aliases: str | None = None, birthday: str | None = None, tags: str | None = None) -> Client:
    """kind=None или "person" при создании — угадать по имени/подписи; у существующего человека «person» тип не сбрасывает."""
    from .orders import get_or_create_client
    existed = find_person(name) is not None
    c = get_or_create_client(name, kind="person")
    assert c is not None
    with session() as s:
        row = s.get(Client, c.id)
        k = normalize_kind(kind)
        if k and k != "person":
            row.kind = k
        elif not existed or row.kind == "person":
            row.kind = guess_kind(name, notes)
        birthday = _clean_birthday(birthday)
        for k, v in (("contact", contact), ("notes", notes), ("aliases", aliases), ("birthday", birthday), ("tags", tags)):
            if v is not None:
                setattr(row, k, str(v).strip() or ("" if k in ("aliases", "tags") else None))
        s.add(row); s.commit(); s.refresh(row)
        return row


def _clean_birthday(v) -> str | None:
    """«12.03», «12.03.1990», «1990-03-12» → «ДД.ММ[.ГГГГ]»; невозможная дата (99.99) — пусто, а не мусор в базе."""
    import re as _re
    t = str(v or "").strip()
    if not t:
        return None
    m = _re.fullmatch(r"(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{4}))?", t) or None
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = _re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
        if not m:
            return None
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{d:02d}.{mo:02d}" + (f".{y}" if y else "")


def update_person(cid: int, **fields) -> Client | None:
    with session() as s:
        c = s.get(Client, cid)
        if not c:
            return None
        for k, v in fields.items():
            if v is None:
                continue
            if k == "name":
                c.name = str(v).strip() or c.name
            elif k == "kind":
                nk = normalize_kind(v)
                if nk:
                    c.kind = nk
            elif k == "birthday":
                c.birthday = _clean_birthday(v)
            elif k in ("contact", "notes"):
                setattr(c, k, str(v).strip() or None)
            elif k in ("aliases", "tags"):
                setattr(c, k, ", ".join(x.strip() for x in str(v).split(",") if x.strip()))
            elif k == "pay_mode":
                if v in ("each", "batch", "monthly"):
                    c.pay_mode = v
            elif k == "pay_every":
                try:
                    c.pay_every = max(1, min(120, int(v)))
                except (TypeError, ValueError):
                    pass
            elif k == "pay_days":
                import re as _re
                c.pay_days = ",".join(sorted({x for x in _re.findall(r"\d{1,2}", str(v)) if 1 <= int(x) <= 31}, key=int))
        s.add(c); s.commit(); s.refresh(c)
        return c


# ---------------------------------------------------------------- текст для чата / голоса
def card_text(d: dict, short: bool = False) -> str:
    from .calendar import fmt_dt
    from .finance import money
    head = f"👤 {d['name']}" + (f" · {d['contact']}" if d.get("contact") else "") + (f" · {', '.join(d['tags'])}" if d.get("tags") else "")
    lines = [head]
    m = d["money"]
    if d["orders_total"]:
        s = f"Заказов {d['orders_total']}, оплачено {money(m['paid'])}"
        if m["unpaid"]:
            s += f", **ждёт оплаты {money(m['unpaid'])}**"
        if m["open"]:
            s += f", в работе {m['open']}"
        npd = f", ближайшая выплата {fmt_dt(datetime.fromisoformat(d['next_payday'])).split(' в ')[0]}" if d.get("next_payday") else ""
        if d.get("pay_mode") == "batch":
            s += f"; платит пачкой раз в {d['pay_every']} дн.{npd}"
        elif d.get("pay_mode") == "monthly":
            days = (d["pay_days"] or "1").split(",")
            s += f"; платит {(', '.join(days[:-1]) + ' и ' + days[-1]) if len(days) > 1 else days[0]} числа{npd}"
        lines.append(s + ".")
        for o in d["orders"][:3 if short else 6]:
            tail = (" — " + fmt_dt(o["deadline"])) if o["deadline"] and o["open"] else ""
            lines.append(f"• #{o['id']} {o['title']} · {o['status_label']} · {money(o['price'])}" + (f" (осталось {money(o['left'])})" if o["unpaid"] else "") + tail)
    for dd in d["debts"]:
        lines.append(f"💳 {dd['title']}: осталось {money(dd['remaining'])}")
    if d["upcoming"]:
        e = d["upcoming"][0]
        lines.append(f"📅 Ближайшее: «{e['title']}» {fmt_dt(e['start'])}" + (f", {e['location']}" if e.get("location") else ""))
    if d["tasks"]:
        lines.append("☑️ Задачи: " + "; ".join(t["title"] for t in d["tasks"][:3]) + (f" … ещё {len(d['tasks']) - 3}" if len(d["tasks"]) > 3 else ""))
    if d["notes"] and not short:
        lines.append("🧠 Заметки: " + "; ".join((n["title"] or n["text"][:50]) for n in d["notes"][:3]))
    if d["notes"] and short:
        lines.append(f"🧠 Заметок: {d['counts']['notes']}")
    if d.get("birthday"):
        lines.append(f"🎂 {d['birthday']}")
    if d.get("about"):
        lines.append(d["about"])
    if d["last_contact"]:
        days = (datetime.now() - d["last_contact"]).days
        lines.append("Последний след: " + ("сегодня" if days == 0 else f"{days} дн. назад"))
    if len(lines) == 1:
        lines.append("Пока ничего не связано — упомяните имя в заказе, задаче или заметке, и оно появится здесь.")
    return "\n".join(lines)


def trigger_line(c: Client, fresh_sec: int = 90) -> str | None:
    """Одна строка-подсказка, когда человек всплыл в разговоре: только важное (долг, неоплата, ближайшая встреча).
    То, что создано только что (эта же реплика), не повторяем — человек и так это видит."""
    d = card(c, limit=3)
    cut = datetime.now() - timedelta(seconds=fresh_sec)
    d["orders"] = [o for o in d["orders"] if o["created_at"] < cut]
    d["money"]["open"] = sum(1 for o in d["orders"] if o["open"])
    d["money"]["unpaid"] = round(sum(o["left"] for o in d["orders"] if o["unpaid"]))
    d["tasks"] = [t for t in d["tasks"] if t.get("created_at") is None or t["created_at"] < cut]
    d["upcoming"] = [e for e in d["upcoming"] if e.get("created_at") is None or e["created_at"] < cut]
    from .calendar import fmt_dt
    from .finance import money
    bits = []
    if d["money"]["unpaid"]:
        bits.append(f"не оплачено {money(d['money']['unpaid'])}")
    if d["money"]["open"]:
        o = next((x for x in d["orders"] if x["open"]), None)
        if o:
            bits.append(f"в работе «{o['title']}»" + (f" до {fmt_dt(o['deadline'])}" if o["deadline"] else ""))
    for dd in d["debts"][:1]:
        bits.append(f"долг «{dd['title']}» {money(dd['remaining'])}")
    if d["upcoming"] and d["upcoming"][0]["start"] <= datetime.now() + timedelta(days=7):
        e = d["upcoming"][0]
        bits.append(f"встреча {fmt_dt(e['start'])}")
    due = [t for t in d["tasks"] if t.get("due") and t["due"] <= datetime.now().replace(hour=23, minute=59)]
    if due:
        bits.append(f"задача «{due[0]['title']}» {'горит' if due[0]['due'] < datetime.now() else 'сегодня'}")
    if not bits:
        return None
    return f"👤 {c.name}: " + ", ".join(bits) + "."


def hint_once(c: Client, cooldown_h: int = 3) -> str | None:
    """trigger_line, но не чаще раза в cooldown_h на человека — чтобы не бубнить одно и то же под каждой репликой."""
    from ..db import get_setting, set_setting
    key = f"people_hint:{c.id}"
    raw = get_setting(key)
    if raw:
        try:
            if datetime.now() - datetime.fromisoformat(raw) < timedelta(hours=cooldown_h):
                return None
        except ValueError:
            pass
    line = trigger_line(c)
    if line:
        set_setting(key, datetime.now().isoformat())
    return line


def people_today() -> list[dict]:
    """Кто сегодня в календаре — для «Сегодня» и утреннего дайджеста: имя + одна строка контекста."""
    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    from .calendar import list_events
    out, seen = [], set()
    with session() as s:
        people = list(s.exec(select(Client)))
    for e in list_events(now, now + timedelta(days=1), limit=50):
        for c in people:
            if c.id in seen or not (mentions(e.title, c) or mentions(e.notes, c)):
                continue
            seen.add(c.id)
            out.append({"id": c.id, "name": c.name, "event": e.title, "at": e.start, "hint": trigger_line(c)})
    return out
