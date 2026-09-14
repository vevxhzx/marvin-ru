"""Картинки-«открытки» для Telegram: утренний дашборд, вечерний итог, недельный/месячный отчёт. Pillow, без внешних сервисов.

Стиль как у сайта (тёмная тема): почти чёрный фон, карточки-поверхности, один акцент, строчные заголовки.
Высота картинки считается по содержимому — сначала измеряем блоки, потом рисуем, поэтому ничего не наезжает друг на друга.
Шрифт: Windows — Segoe UI (есть всегда), Linux — DejaVu; при отсутствии — встроенный.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from ..config import DATA_DIR, cfg
from . import calendar, finance, tasks
from .finance import money

log = logging.getLogger("assistant.cards")

W = 1080
PAD = 56                       # внешний отступ
CW = W - 2 * PAD               # ширина контента
BG = (14, 14, 13)
SURFACE = (27, 27, 26)
SURFACE_2 = (36, 36, 35)
INK = (243, 243, 240)
INK_2 = (160, 160, 156)
INK_3 = (110, 110, 106)
LINE = (44, 44, 43)
ACCENT = (59, 91, 255)
GREEN = (52, 199, 120)
RED = (255, 92, 92)
ORANGE = (240, 160, 40)

_BOLD = [
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
_REG = [
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
]
_cache: dict[tuple[int, bool], object] = {}


def _font(size: int, bold: bool = True):
    key = (size, bold)
    if key in _cache:
        return _cache[key]
    from PIL import ImageFont
    f = None
    for p in (_BOLD if bold else _REG) + (_REG if bold else _BOLD):
        if Path(p).exists():
            try:
                f = ImageFont.truetype(p, size)
                break
            except Exception:
                continue
    if f is None:
        f = ImageFont.load_default()
    _cache[key] = f
    return f


def _address() -> str:
    try:
        return (cfg.owner.name or "сэр").strip().lower()
    except Exception:
        return "сэр"


def _weekday(d: datetime) -> str:
    return ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][d.weekday()]


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


# ---------------------------------------------------------------- примитивы
class _Canvas:
    """Рисуем сверху вниз: каждый метод двигает курсор y и возвращает его. Высота холста — с запасом, в конце обрезаем."""

    def __init__(self, max_h: int = 2600):
        from PIL import Image, ImageDraw
        self.img = Image.new("RGB", (W, max_h), BG)
        self.d = ImageDraw.Draw(self.img)
        self.y = PAD

    # измерения
    def tw(self, text: str, font) -> float:
        return self.d.textlength(text, font=font)

    def ellipsis(self, text: str, font, max_w: float) -> str:
        if self.tw(text, font) <= max_w:
            return text
        while text and self.tw(text + "…", font) > max_w:
            text = text[:-1]
        return text.rstrip() + "…"

    # блоки
    def title(self, text: str, sub: str | None = None):
        self.d.text((PAD, self.y), text, font=_font(64), fill=INK)
        self.y += 78
        if sub:
            self.d.text((PAD + 2, self.y), sub, font=_font(26, False), fill=INK_2)
            self.y += 40
        self.y += 18

    def label(self, text: str, count: int | None = None):
        """Подпись раздела маленькими капителями + счётчик акцентом (как на сайте)."""
        self.y += 30
        f = _font(21)
        self.d.text((PAD, self.y), text.upper(), font=f, fill=INK_3)
        if count:
            self.d.text((PAD + self.tw(text.upper(), f) + 14, self.y - 1), str(count), font=_font(21), fill=ACCENT)
        self.y += 36
        self.d.line((PAD, self.y, W - PAD, self.y), fill=LINE, width=1)
        self.y += 10

    def row(self, left: str, text: str, right: str | None = None, left_color=INK, right_color=INK_2, left_w: int = 118, muted: bool = False):
        """Строка списка: левая колонка фиксированной ширины (время/дата), текст с обрезкой, правая колонка прижата вправо."""
        f_left, f_text, f_right = _font(28), _font(28, False), _font(24)
        h = 54
        right_w = (self.tw(right, f_right) + 28) if right else 0
        self.d.text((PAD, self.y + 12), left, font=f_left, fill=left_color)
        text_x = PAD + left_w
        text = self.ellipsis(text, f_text, CW - left_w - right_w)
        self.d.text((text_x, self.y + 12), text, font=f_text, fill=INK_2 if muted else INK)
        if right:
            self.d.text((W - PAD - self.tw(right, f_right), self.y + 15), right, font=f_right, fill=right_color)
        self.y += h
        self.d.line((PAD, self.y, W - PAD, self.y), fill=LINE, width=1)

    def check_row(self, text: str, right: str | None = None, right_color=INK_2, done: bool = False, urgent: bool = False):
        f_text, f_right = _font(28, False), _font(24)
        right_w = (self.tw(right, f_right) + 28) if right else 0
        cy = self.y + 27
        if done:
            self.d.ellipse((PAD, cy - 12, PAD + 24, cy + 12), fill=ACCENT)
            self.d.line((PAD + 6, cy, PAD + 10, cy + 5), fill=INK, width=3)
            self.d.line((PAD + 10, cy + 5, PAD + 18, cy - 5), fill=INK, width=3)
        else:
            self.d.ellipse((PAD, cy - 12, PAD + 24, cy + 12), outline=RED if urgent else INK_3, width=2)
        self.d.text((PAD + 44, self.y + 12), self.ellipsis(text, f_text, CW - 44 - right_w), font=f_text, fill=INK_3 if done else INK)
        if right:
            self.d.text((W - PAD - self.tw(right, f_right), self.y + 15), right, font=f_right, fill=right_color)
        self.y += 54
        self.d.line((PAD, self.y, W - PAD, self.y), fill=LINE, width=1)

    def empty(self, text: str):
        self.d.text((PAD, self.y + 10), text, font=_font(26, False), fill=INK_3)
        self.y += 50

    def stats(self, items: list[tuple[str, str, tuple]]):
        """Ряд карточек «подпись / значение». Ширина делится поровну; значение ужимается, чтобы не вылезти."""
        self.y += 22
        n = len(items)
        gap = 14
        cw = (CW - gap * (n - 1)) // n
        h = 124
        for i, (label, value, color) in enumerate(items):
            x = PAD + i * (cw + gap)
            self.d.rounded_rectangle((x, self.y, x + cw, self.y + h), radius=24, fill=SURFACE)
            self.d.text((x + 24, self.y + 18), label, font=_font(21, False), fill=INK_2)
            size = 44
            while size > 26 and self.tw(value, _font(size)) > cw - 48:
                size -= 2
            self.d.text((x + 24, self.y + h - 24 - size), value, font=_font(size), fill=color)
        self.y += h

    def bar(self, frac: float, color, h: int = 8):
        self.d.rounded_rectangle((PAD, self.y, W - PAD, self.y + h), radius=h // 2, fill=SURFACE_2)
        if frac > 0:
            self.d.rounded_rectangle((PAD, self.y, PAD + max(h, int(CW * min(1.0, frac))), self.y + h), radius=h // 2, fill=color)
        self.y += h

    def pills(self, items: list[tuple[str, tuple | None]]):
        self.y += 8
        x = PAD
        f = _font(24)
        for text, bg in items:
            w = self.tw(text, f) + 30
            if x + w > W - PAD:
                x = PAD
                self.y += 54
            self.d.rounded_rectangle((x, self.y, x + w, self.y + 44), radius=22, fill=bg or SURFACE_2)
            self.d.text((x + 15, self.y + 8), text, font=f, fill=INK if bg is None else INK)
            x += w + 12
        self.y += 44

    def note(self, text: str):
        self.y += 18
        f = _font(24, False)
        # перенос по словам
        words, lines, cur = text.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if self.tw(t, f) <= CW:
                cur = t
            else:
                lines.append(cur); cur = w
        if cur:
            lines.append(cur)
        for ln in lines[:3]:
            self.d.text((PAD, self.y), ln, font=f, fill=INK_2)
            self.y += 34

    def finish(self, path: Path) -> Path:
        from .. import identity
        self.y += 36
        f, fb = _font(20, False), _font(20)
        self.d.text((PAD, self.y), identity.NAME.lower(), font=fb, fill=INK_3)
        stamp = datetime.now().strftime("%d.%m.%Y · %H:%M")
        self.d.text((W - PAD - self.tw(stamp, f), self.y), stamp, font=f, fill=INK_3)
        self.y += 24 + PAD
        img = self.img.crop((0, 0, W, self.y))
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, "PNG", optimize=True)
        return path


def _out(name: str, path: Path | None) -> Path:
    return path or (DATA_DIR / "tmp" / name)


# ---------------------------------------------------------------- утро
def morning_card(path: Path | None = None) -> Path | None:
    try:
        now = datetime.now()
        evs = calendar.events_today()[:6]
        ts = tasks.list_tasks(limit=6)
        pays = finance.upcoming_payments(3)[:4]
        s = finance.summary(1)
        safe = s.get("safe") or {}
        c = _Canvas()
        c.title(f"доброе утро, {_address()}", f"{_weekday(now)}, {now.day} {_month(now)}")

        c.label("сегодня", len(evs))
        if evs:
            for e in evs:
                past = e.end and e.end < now
                c.row(f"{e.start:%H:%M}", e.title + (f" · {e.location}" if e.location else ""), left_color=INK_3 if past else ACCENT, muted=bool(past))
        else:
            c.empty("встреч нет — день ваш")

        c.label("задачи", len(ts))
        if ts:
            for t in ts:
                urgent = bool(t.due and t.due.date() <= now.date())
                right = None
                if t.due:
                    if t.due.date() < now.date():
                        right = f"просрочено · {t.due:%d.%m}"
                    elif t.due.date() == now.date():
                        right = f"до {t.due:%H:%M}"
                    else:
                        right = f"{t.due:%d.%m}"
                c.check_row(t.title, right, right_color=RED if urgent else INK_2, urgent=urgent)
        else:
            c.empty("задач нет. подозрительно.")

        if pays:
            c.label("платежи на днях", len(pays))
            for p in pays:
                when = "сегодня" if p.next_date.date() == now.date() else "завтра" if p.next_date.date() == (now + timedelta(days=1)).date() else f"{p.next_date:%d.%m}"
                c.row(when, p.title, money(p.amount), left_color=INK_2 if when not in ("сегодня",) else ORANGE, right_color=INK, left_w=140)

        per_day = safe.get("per_day")
        items = [("баланс", money(s["total_balance"]), INK)]
        if per_day is not None:
            items.append(("можно тратить в день", money(per_day), GREEN if per_day > 0 else RED))
        if safe.get("reserved"):
            items.append(("отложено на платежи", money(safe["reserved"]), INK_2))
        c.stats(items[:3])
        return c.finish(_out("morning.png", path))
    except Exception as e:
        log.warning("morning card failed: %s", e)
        return None


def _month(d: datetime) -> str:
    return ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"][d.month - 1]


# ---------------------------------------------------------------- вечер
def evening_data() -> dict:
    """Что было за день — одним словарём (для карточки и для короткого текста)."""
    now = datetime.now()
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from ..db import Task, session
    from sqlmodel import select
    with session() as db:
        done = list(db.exec(select(Task).where(Task.done == True, Task.done_at != None, Task.done_at >= d0).order_by(Task.done_at)))  # noqa: E711,E712
    due = tasks.evening_review()
    txs = [t for t in finance.list_transactions(1, 1000) if t.date >= d0]
    spent = sum(t.amount for t in txs if t.kind == "expense")
    earned = sum(t.amount for t in txs if t.kind == "income")
    by_cat: dict[str, float] = {}
    for t in txs:
        if t.kind == "expense":
            by_cat[t.category or "Другое"] = by_cat.get(t.category or "Другое", 0) + t.amount
    top = sorted(by_cat.items(), key=lambda kv: -kv[1])[:1]
    tomorrow = calendar.list_events(d0 + timedelta(days=1), d0 + timedelta(days=2), limit=4)
    s = finance.summary(1)
    safe = s.get("safe") or {}
    return {"now": now, "done": done, "due": due, "spent": spent, "earned": earned, "top": top[0] if top else None,
            "tomorrow": tomorrow, "balance": s["total_balance"], "per_day": safe.get("per_day")}


def evening_text(data: dict | None = None) -> str:
    """Короткий вечерний итог — 3–4 строки, без воды."""
    d = data or evening_data()
    addr = _address()
    parts = [f"🌙 Вечер, {addr}."]
    n_done, n_due = len(d["done"]), len(d["due"])
    if n_done or n_due:
        bits = []
        if n_done:
            bits.append(f"закрыто {n_done} {_plural(n_done, 'задача', 'задачи', 'задач')}")
        if n_due:
            bits.append(f"осталось {n_due} с дедлайном")
        parts.append("✅ " + ", ".join(bits) + ".")
    if d["spent"] or d["earned"]:
        m = f"💸 За день −{money(d['spent'])}"
        if d["top"] and d["spent"]:
            m += f" (больше всего — {d['top'][0].lower()})"
        if d["earned"]:
            m += f", +{money(d['earned'])}"
        parts.append(m + ".")
    if d["tomorrow"]:
        e = d["tomorrow"][0]
        more = f" и ещё {len(d['tomorrow']) - 1}" if len(d["tomorrow"]) > 1 else ""
        parts.append(f"📅 Завтра: {e.start:%H:%M} — {e.title}{more}.")
    else:
        parts.append("📅 Завтра свободно.")
    return "\n".join(parts)


def evening_card(path: Path | None = None, data: dict | None = None) -> Path | None:
    try:
        d = data or evening_data()
        now = d["now"]
        c = _Canvas()
        c.title(f"итоги дня, {_address()}", f"{_weekday(now)}, {now.day} {_month(now)}")

        n_done, n_due = len(d["done"]), len(d["due"])
        c.stats([
            ("закрыто задач", str(n_done), GREEN if n_done else INK_2),
            ("потрачено", money(d["spent"]) if d["spent"] else "0 ₽", INK if d["spent"] else INK_2),
            ("баланс", money(d["balance"]), INK),
        ])

        if d["done"] or d["due"]:
            c.label("задачи")
            for t in d["done"][:4]:
                c.check_row(t.title, f"{t.done_at:%H:%M}", done=True)
            for t in d["due"][:3]:
                c.check_row(t.title, "не закрыта", right_color=RED, urgent=True)
            rest = max(0, n_done - 4) + max(0, n_due - 3)
            if rest:
                c.empty(f"…и ещё {rest}")

        c.label("завтра", len(d["tomorrow"]))
        if d["tomorrow"]:
            for e in d["tomorrow"]:
                c.row(f"{e.start:%H:%M}", e.title + (f" · {e.location}" if e.location else ""), left_color=ACCENT)
        else:
            c.empty("свободно. редкость — берегите.")

        if d["top"] and d["spent"]:
            c.note(f"Больше всего за день ушло на «{d['top'][0]}» — {money(d['top'][1])}.")
        return c.finish(_out("evening.png", path))
    except Exception as e:
        log.warning("evening card failed: %s", e)
        return None


# ---------------------------------------------------------------- отчёт за неделю / месяц
def report_card(days: int = 7, path: Path | None = None) -> Path | None:
    try:
        from ..db import Memory, Note, Task, session
        from sqlmodel import select
        s = finance.summary(days)
        prev_txs = [t for t in finance.list_transactions(days * 2, 100_000) if t.date < datetime.now() - timedelta(days=days)]
        prev_spent = sum(t.amount for t in prev_txs if t.kind == "expense")
        cats = sorted(s["by_category"].items(), key=lambda kv: -kv[1])[:5]
        since = datetime.now() - timedelta(days=days)
        with session() as db:
            done = db.exec(select(Task).where(Task.done == True, Task.done_at != None, Task.done_at >= since)).all()  # noqa: E711,E712
            notes = db.exec(select(Note).where(Note.created_at >= since)).all()
            active_days = len({m.created_at.date() for m in db.exec(select(Memory).where(Memory.created_at >= since, Memory.channel != "system"))})
        c = _Canvas()
        c.title("итоги недели" if days <= 7 else "итоги месяца", f"{since:%d.%m} — {datetime.now():%d.%m.%Y}")

        spent_label = "потрачено"
        if prev_spent:
            diff = (s["spent"] - prev_spent) / prev_spent * 100
            spent_label += f"  ·  {'+' if diff > 0 else ''}{diff:.0f}% к прошлому"
        c.stats([(spent_label, money(s["spent"]), INK), ("заработано", money(s["earned"]), GREEN if s["earned"] else INK_2)])

        c.label("куда ушло", len(cats))
        mx = max((v for _, v in cats), default=1)
        if cats:
            for name, v in cats:
                c.d.text((PAD, c.y + 12), c.ellipsis(name, _font(28, False), CW - 220), font=_font(28, False), fill=INK)
                c.d.text((W - PAD - c.tw(money(v), _font(26)), c.y + 14), money(v), font=_font(26), fill=INK)
                c.y += 52
                c.bar(v / mx, ACCENT)
                c.y += 16
        else:
            c.empty("трат не было. или вы их не записывали.")

        c.label("дела")
        c.pills([(f"✓ {len(done)} {_plural(len(done), 'задача', 'задачи', 'задач')} закрыто", None),
                 (f"✎ {len(notes)} {_plural(len(notes), 'заметка', 'заметки', 'заметок')}", None),
                 (f"● {active_days} из {days} дней с записями", ACCENT)])

        over = [b for b in s.get("budgets", []) if b["pct"] >= 0.8][:3]
        if over:
            c.label("лимиты", len(over))
            for b in over:
                color = RED if b["pct"] >= 1 else ORANGE
                c.d.text((PAD, c.y + 12), b["name"], font=_font(28, False), fill=INK)
                txt = f"{b['pct'] * 100:.0f}%"
                c.d.text((W - PAD - c.tw(txt, _font(26)), c.y + 14), txt, font=_font(26), fill=color)
                c.y += 52
                c.bar(b["pct"], color)
                c.y += 16

        items = [("баланс сейчас", money(s["total_balance"]), INK)]
        if s.get("debts_total"):
            items.append(("долги", money(s["debts_total"]), INK_2))
        c.stats(items)
        return c.finish(_out(f"report_{days}.png", path))
    except Exception as e:
        log.warning("report card failed: %s", e)
        return None
