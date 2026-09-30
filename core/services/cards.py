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

log = logging.getLogger("jarvis.cards")

W = 1080
PAD = 56                       # внешний отступ
CW = W - 2 * PAD               # ширина контента
# Светлая тема — как «утренний дайджест» на сайте (эталон Jarvis Bento V7) и как тема сайта по умолчанию.
BG = (243, 245, 249)
SURFACE = (255, 255, 255)
SURFACE_2 = (240, 241, 246)
INK = (16, 17, 20)
INK_2 = (93, 96, 104)
INK_3 = (154, 157, 166)
LINE = (231, 233, 239)
ACCENT = (10, 60, 255)         # #0a3cff — фирменный синий
ACCENT_2 = (138, 92, 255)      # светлее для градиента (синий → фиолетовый, как на сайте)
GREEN = (25, 179, 74)
RED = (255, 59, 92)
ORANGE = (245, 168, 0)
# Пастель для bento-плиток (акцентные суммы/категории) — светлые заливки
PASTEL = {
    "blue": (236, 233, 255), "green": (227, 247, 234), "orange": (255, 244, 224),
    "red": (255, 235, 238), "violet": (236, 233, 255),
}

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

    # фирменный знак (split-asterisk: 8 лучей из центра) и градиентная шапка
    def asterisk(self, cx: int, cy: int, r: int, color=ACCENT, width: int = 4):
        import math
        for k in range(4):
            a = math.pi * k / 4
            dx, dy = math.cos(a) * r, math.sin(a) * r
            self.d.line((cx - dx, cy - dy, cx + dx, cy + dy), fill=color, width=width)

    def header(self, badge: str, color=ACCENT):
        """Тонкая градиентная полоса сверху + пилюля с бейджем и временем — как .report-card/.report-tag на сайте."""
        from PIL import Image
        h = 4
        grad = Image.new("RGB", (W, h))
        px = grad.load()
        stops = [ACCENT, ACCENT_2, GREEN]
        for x in range(W):
            t = x / max(1, W - 1) * (len(stops) - 1)
            i = min(int(t), len(stops) - 2)
            fr = t - i
            a, b = stops[i], stops[i + 1]
            col = (int(a[0] + (b[0] - a[0]) * fr), int(a[1] + (b[1] - a[1]) * fr), int(a[2] + (b[2] - a[2]) * fr))
            for yy in range(h):
                px[x, yy] = col
        self.img.paste(grad, (0, 0))
        self.y = PAD + 6
        f = _font(21)
        txt = badge.upper()
        w = self.tw(txt, f) + 64
        self.d.rounded_rectangle((PAD, self.y, PAD + w, self.y + 42), radius=21, fill=SURFACE_2)
        self.asterisk(PAD + 27, self.y + 21, 9, color, width=3)
        self.d.text((PAD + 46, self.y + 11), txt, font=f, fill=INK_2)
        ts = datetime.now().strftime("%H:%M")
        f2 = _font(21)
        self.d.text((W - PAD - self.tw(ts, f2), self.y + 11), ts, font=f2, fill=INK_3)
        self.y += 42

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
        """Строка-пилюля: левая колонка (время/дата), текст с обрезкой, значение прижато вправо."""
        f_left, f_text, f_right = _font(27), _font(27, False), _font(24)
        h = 58
        self.d.rounded_rectangle((PAD, self.y, W - PAD, self.y + h), radius=18, fill=SURFACE)
        cy = self.y + h // 2
        self.d.text((PAD + 22, cy - 15), left, font=f_left, fill=left_color)
        right_w = (self.tw(right, f_right) + 40) if right else 0
        text = self.ellipsis(text, f_text, CW - left_w - right_w)
        self.d.text((PAD + left_w, cy - 15), text, font=f_text, fill=INK_3 if muted else INK)
        if right:
            self.d.text((W - PAD - 22 - self.tw(right, f_right), cy - 12), right, font=f_right, fill=right_color)
        self.y += h + 8

    def check_row(self, text: str, right: str | None = None, right_color=INK_2, done: bool = False, urgent: bool = False):
        f_text, f_right = _font(27, False), _font(24)
        h = 58
        self.d.rounded_rectangle((PAD, self.y, W - PAD, self.y + h), radius=18, fill=SURFACE)
        cy = self.y + h // 2
        if done:
            self.d.ellipse((PAD + 20, cy - 12, PAD + 44, cy + 12), fill=GREEN)
            self.d.line((PAD + 26, cy, PAD + 30, cy + 5), fill=(255, 255, 255), width=3)
            self.d.line((PAD + 30, cy + 5, PAD + 38, cy - 5), fill=(255, 255, 255), width=3)
        else:
            self.d.ellipse((PAD + 20, cy - 12, PAD + 44, cy + 12), outline=RED if urgent else INK_3, width=2)
        right_w = (self.tw(right, f_right) + 40) if right else 0
        self.d.text((PAD + 60, cy - 15), self.ellipsis(text, f_text, CW - 60 - right_w), font=f_text, fill=INK_3 if done else INK)
        if right:
            self.d.text((W - PAD - 22 - self.tw(right, f_right), cy - 12), right, font=f_right, fill=right_color)
        self.y += h + 8

    def empty(self, text: str):
        self.d.text((PAD, self.y + 10), text, font=_font(26, False), fill=INK_3)
        self.y += 50

    def stats(self, items: list[tuple[str, str, tuple]]):
        """Ряд bento-плиток: первая — hero-градиент (синий→фиолетовый), остальные — пастель по цвету значения."""
        self.y += 24
        n = len(items)
        gap = 14
        cw = (CW - gap * (n - 1)) // n
        h = 128
        for i, (label, value, color) in enumerate(items):
            x = PAD + i * (cw + gap)
            box = (x, self.y, x + cw, self.y + h)
            if i == 0:
                _grad_round(self.img, box, 24, ACCENT, ACCENT_2, vertical=True)
                lc, vc = (226, 230, 255), (255, 255, 255)
            else:
                self.d.rounded_rectangle(box, radius=24, fill=PASTEL.get(_kind_of(color), SURFACE))
                lc, vc = INK_2, color
            self.d.text((x + 22, self.y + 18), label, font=_font(21, False), fill=lc)
            size = 44
            while size > 24 and self.tw(value, _font(size)) > cw - 44:
                size -= 2
            self.d.text((x + 22, self.y + h - 22 - size), value, font=_font(size), fill=vc)
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
def morning_card(path: Path | None = None, badge: str = "утренний дайджест", title: str | None = None) -> Path | None:
    try:
        now = datetime.now()
        evs = calendar.events_today()[:6]
        ts = tasks.list_tasks(limit=6)
        pays = finance.upcoming_payments(3)[:4]
        s = finance.summary(1)
        safe = s.get("safe") or {}
        c = _Canvas()
        c.header(badge)
        c.title(title or f"доброе утро, {_address()}", f"{_weekday(now)}, {now.day} {_month(now)}")

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


def _footer(d: datetime) -> str:
    """Подвал карточки — как на сайте: «джарвис · ср 30сен»."""
    from . import scheduler
    return scheduler._card_footer(d)


def evening_text(data: dict | None = None, first: str | None = None) -> str:
    """Вечерний итог — карточка в том же стиле, что утренний: заголовок, секции с количеством
    и теми же пустыми строками, футер. first — живая первая строка от персоны (иначе нейтральная)."""
    d = data or evening_data()
    now = datetime.now()
    out = [f"🌙 **ИТОГИ ДНЯ** · {now:%H:%M}"]
    out.append("**" + first.strip() + "**" if first else f"**вечер, {_address()}**")
    out.append(f"{_weekday(now)}, {now.day} {_month(now)}")

    n_done, n_due = len(d["done"]), len(d["due"])
    out.append("")
    out.append(f"✅ **ЗАКРЫТО** · {n_done}")
    if n_done:
        out += [f"— {t.title}" + (f" · {t.done_at:%H:%M}" if t.done_at else "") for t in d["done"][:5]]
        if n_done > 5:
            out.append(f"…и ещё {n_done - 5}")
    else:
        out.append("ничего не закрыто — подозрительно наоборот.")

    out.append("")
    out.append(f"💸 **РАСХОДЫ ЗА ДЕНЬ** · {money(d['spent'])}")
    if d["spent"] and d["top"]:
        out.append(f"больше всего — {d['top'][0].lower()}")
    if d["earned"]:
        out.append(f"поступило +{money(d['earned'])}")
    if not d["spent"] and not d["earned"]:
        out.append("денег не трогали — редкий день.")

    if n_due:
        out.append("")
        out.append(f"⏰ **ОСТАЛОСЬ** · {n_due}")
        out += [f"— {t.title} · " + ("сегодня" if t.due and t.due.date() == now.date() else f"{t.due:%d.%m}")
                for t in d["due"][:4] if t.due]
        if n_due > 4:
            out.append(f"…и ещё {n_due - 4}")
    try:
        from . import screen
        sl = screen.evening_line(d.get("now"))
        if sl:
            out.append("")
            out.append(sl)
    except Exception:  # pragma: no cover
        pass

    out.append("")
    if d["tomorrow"]:
        out.append(f"📅 **ЗАВТРА** · {len(d['tomorrow'])}")
        out += [f"— **{e.start:%H:%M}** {e.title}" for e in d["tomorrow"][:3]]
    else:
        out.append("📅 завтра свободно.")
    out.append("")
    out.append(f"———\n{_footer(now)}")
    return "\n".join(out)


def evening_card(path: Path | None = None, data: dict | None = None) -> Path | None:
    try:
        d = data or evening_data()
        now = d["now"]
        c = _Canvas()
        c.header("итоги дня")
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
        c.header("итоги недели" if days <= 7 else "итоги месяца")
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


# ---------------------------------------------------------------- светлая bento-полоса 21:9
# Короткие карточки (трата, доход, задача, встреча, заказ, финансы) — узкий прямоугольник 21:9,
# чтобы это был не «фулл-фотка», а аккуратная плашка под текстом ответа. Стиль — как «утренний дайджест».
BW, BH = 1260, 540             # 21 : 9
LT_ACC = ACCENT
LT_ACC_2 = ACCENT_2
LT_TINT = {
    "hero": None, "blue": PASTEL["blue"], "violet": PASTEL["violet"],
    "green": PASTEL["green"], "orange": PASTEL["orange"], "red": PASTEL["red"], "plain": SURFACE,
}
# Градиенты главной (первой) плитки полосы — цвет по смыслу значения
_BAND_GRAD = {
    "green": ((25, 179, 74), (14, 165, 150)),
    "red": ((255, 59, 92), (255, 122, 61)),
    "orange": ((245, 168, 0), (238, 120, 40)),
    "blue": (ACCENT, ACCENT_2),
    "violet": (ACCENT, ACCENT_2),
    "hero": (ACCENT, ACCENT_2),
    "plain": (ACCENT, ACCENT_2),
}


def _kind_of(color) -> str:
    """Подобрать пастельную заливку плитки по цвету значения."""
    if color == ACCENT or color == ACCENT_2:
        return "blue"
    if color == GREEN:
        return "green"
    if color == RED:
        return "red"
    if color == ORANGE:
        return "orange"
    return "plain"


def _grad_round(img, box, radius, c1, c2, vertical: bool = False):
    """Залить скруглённый прямоугольник горизонтальным/вертикальным градиентом (Pillow)."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    g = Image.new("RGB", (w, h))
    gp = g.load()
    for yy in range(h):
        for xx in range(w):
            t = (yy / (h - 1)) if vertical else (xx / (w - 1))
            gp[xx, yy] = (int(c1[0] + (c2[0] - c1[0]) * t),
                          int(c1[1] + (c2[1] - c1[1]) * t),
                          int(c1[2] + (c2[2] - c1[2]) * t))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    img.paste(g, (x0, y0), mask)


class _Band:
    """Светлая bento-карточка 21:9 (1260×540): бейдж, крупный заголовок, плитки, подвал."""

    def __init__(self):
        from PIL import Image, ImageDraw
        self.img = Image.new("RGB", (BW, BH), BG)
        self.d = ImageDraw.Draw(self.img)
        self.pad = 48

    def tw(self, text: str, font) -> float:
        return self.d.textlength(text, font=font)

    def ellipsis(self, text: str, font, max_w: float) -> str:
        if self.tw(text, font) <= max_w:
            return text
        while text and self.tw(text + "…", font) > max_w:
            text = text[:-1]
        return text.rstrip() + "…"

    def top(self, badge: str, color=LT_ACC):
        import math
        f = _font(22)
        w = self.tw(badge.upper(), f) + 64
        self.d.rounded_rectangle((self.pad, 40, self.pad + w, 84), radius=22, fill=SURFACE_2)
        cx, cy = self.pad + 27, 62
        for k in range(4):
            a = math.pi * k / 4
            dx, dy = math.cos(a) * 10, math.sin(a) * 10
            self.d.line((cx - dx, cy - dy, cx + dx, cy + dy), fill=color, width=3)
        self.d.text((self.pad + 48, 50), badge.upper(), font=f, fill=INK_2)
        ts = datetime.now().strftime("%H:%M")
        f2 = _font(22)
        self.d.text((BW - self.pad - self.tw(ts, f2), 50), ts, font=f2, fill=INK_3)

    def title(self, text: str, sub: str = ""):
        f = _font(58)
        self.d.text((self.pad, 116), self.ellipsis(text, f, BW - 2 * self.pad), font=f, fill=INK)
        if sub:
            self.d.text((self.pad + 2, 188), self.ellipsis(sub, _font(26, False), BW - 2 * self.pad),
                        font=_font(26, False), fill=INK_2)

    def tiles(self, items: list, y: int = 250, h: int = 168):
        """items: (label, value, color[, kind]) — kind: hero|blue|green|red|orange|plain.
        Первая плитка — градиент по смыслу значения, остальные — пастель."""
        n = max(1, len(items))
        gap = 16
        cw = (BW - 2 * self.pad - gap * (n - 1)) // n
        for i, it in enumerate(items):
            label, value, color = it[0], it[1], (it[2] if len(it) > 2 and it[2] else INK)
            kind = it[3] if len(it) > 3 and it[3] else _kind_of(color)
            x = self.pad + i * (cw + gap)
            box = (x, y, x + cw, y + h)
            if i == 0:
                g1, g2 = _BAND_GRAD.get(kind, (LT_ACC, LT_ACC_2))
                _grad_round(self.img, box, 26, g1, g2)
                lbl, val = (226, 230, 255), (255, 255, 255)
            else:
                self.d.rounded_rectangle(box, radius=26, fill=LT_TINT.get(kind, SURFACE))
                lbl, val = INK_2, color
            self.d.text((x + 24, y + 20), label, font=_font(21, False), fill=lbl)
            size = 46
            while size > 24 and self.tw(value, _font(size)) > cw - 48:
                size -= 2
            self.d.text((x + 24, y + h - 22 - size), value, font=_font(size), fill=val)

    def stroke(self, text: str, y: int = 250):
        self.d.rounded_rectangle((self.pad, y, BW - self.pad, y + 52), radius=16, fill=SURFACE)
        self.d.text((self.pad + 22, y + 12), self.ellipsis(text, _font(24, False), BW - 2 * self.pad - 44),
                    font=_font(24, False), fill=INK)

    def footer(self):
        from .. import identity
        y = BH - 40
        self.d.line((self.pad, y - 16, BW - self.pad, y - 16), fill=LINE, width=1)
        f, fb = _font(19, False), _font(19)
        self.d.text((self.pad, y), identity.NAME.lower(), font=fb, fill=INK_3)
        stamp = datetime.now().strftime("%d.%m.%Y · %H:%M")
        self.d.text((BW - self.pad - self.tw(stamp, f), y), stamp, font=f, fill=INK_3)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.img.save(path, "PNG", optimize=True)
        return path


def band_card(kind: str, title: str, sub: str = "", tiles: list | None = None, footer: str = "",
              path: Path | None = None, badge: str | None = None) -> Path | None:
    """Короткая карточка-полоса 21:9 в стиле утреннего дайджеста. Кэшируется по содержимому."""
    try:
        badge = badge or _BADGES.get(kind, kind)
        out = path or _cache_path(kind, title, sub or "", tiles or [], footer or "")
        if out.exists() and out.stat().st_size > 0:
            return out
        b = _Band()
        b.top(badge, _BADGE_COLOR.get(kind, LT_ACC))
        b.title(title, sub or "")
        if tiles:
            b.tiles(tiles[:4])
        if footer:
            b.stroke(footer)
        b.footer()
        return b.save(out)
    except Exception as e:
        log.warning("band card %s: %s", kind, e)
        return None


# ---------------------------------------------------------------- карточки действий (единый фирменный стиль)
# Режим картинок: cards.mode — always (всегда) / important (важные + короткие карточки на траты и задачи) / never.
_SECTION = getattr(cfg, "cards", None)
IMAGES_MODE = str(getattr(_SECTION, "mode", "important") or "important")
_IMPORTANT = {"digest", "evening", "week", "report", "month", "status", "backup", "payday"}
_SHORT = {"expense", "income", "task", "event", "done", "reminder", "order", "goal", "debt", "finances",
          "tasks", "events", "debts", "orders", "goals", "missed", "forecast", "today"}

# Версия внешнего вида карточек: входит в ключ кэша, чтобы после редизайна не отдавались старые картинки.
_CARD_STYLE = "v2"

_BADGES = {"expense": "расход", "income": "доход", "task": "задача", "event": "календарь", "done": "сделано",
           "reminder": "напоминание", "order": "заказ", "goal": "цель", "status": "статус", "debt": "долг",
           "finances": "финансы", "finance": "финансы"}
_BADGE_COLOR = {"expense": RED, "income": GREEN, "done": GREEN, "reminder": ORANGE, "debt": ORANGE}


def should_send(kind: str) -> bool:
    """Отправлять ли картинку для этого типа события (см. cards.mode)."""
    if IMAGES_MODE == "never":
        return False
    if IMAGES_MODE == "always":
        return True
    return kind in _IMPORTANT or kind in _SHORT


def _cache_path(kind: str, title: str, sub: str, tiles, footer: str) -> Path:
    import hashlib
    key = "|".join([_CARD_STYLE, kind, title, sub, str(tiles), footer]).encode("utf-8")
    return DATA_DIR / "card_cache" / f"{kind}-{hashlib.sha1(key).hexdigest()[:16]}.png"


def action_card(kind: str, title: str, sub: str = "", tiles: list | None = None, footer: str = "",
                path: Path | None = None, badge: str | None = None) -> Path | None:
    """Короткая карточка действия в фирменном стиле — полоса 21:9 (см. band_card). Кэшируется по содержимому."""
    return band_card(kind, title, sub, tiles, footer, path=path, badge=badge)


def expense_card(tx, balance: float, path: Path | None = None) -> Path | None:
    """Трата/доход: категория, сумма, остаток бюджета по этой категории (если задан)."""
    try:
        income = getattr(tx, "kind", "expense") == "income"
        cat = getattr(tx, "category", None) or "без категории"
        signed = ("+" if income else "−") + money(getattr(tx, "amount", 0))
        tiles = [("сумма", signed, GREEN if income else RED), ("категория", cat, INK), ("баланс", money(balance), INK)]
        for b in finance.budgets():
            if b.get("name") == cat and b.get("budget"):
                left = b.get("left", 0)
                if left < 0:
                    tiles.append(("перерасход", money(abs(left)), RED))
                else:
                    tiles.append(("остаток лимита", money(left), ORANGE if b.get("pct", 0) >= 0.8 else INK_2))
                break
        footer = (getattr(tx, "account", None) or "").strip()
        return action_card("income" if income else "expense", ("+" if income else "−") + money(getattr(tx, "amount", 0)),
                           cat + (f" · {footer}" if footer else ""), tiles[:4], path=path)
    except Exception as e:
        log.warning("expense card: %s", e)
        return None


def task_card(title: str, when: str = "", path: Path | None = None) -> Path | None:
    tiles = [("дело", title[:26], INK), ("когда", when or "без срока", INK_2)]
    return action_card("task", title, when or "без срока", tiles, path=path)


def event_card(title: str, when: str = "", path: Path | None = None) -> Path | None:
    tiles = [("встреча", title[:26], INK), ("когда", when or "—", ACCENT_2)]
    return action_card("event", title, when or "", tiles, path=path)


def done_card(title: str, path: Path | None = None) -> Path | None:
    return action_card("done", title, "закрыто", [("отлично", "✓", GREEN)], path=path)


def finances_card(path: Path | None = None, days: int = 30) -> Path | None:
    """Карточка «финансы»: баланс (hero-градиент), доход и расход за период, дневной лимит. Полоса 21:9."""
    try:
        s = finance.summary(days)
        safe = s.get("safe") or {}
        spent = s.get("spent", 0)
        tiles = [
            ("баланс", money(s.get("total_balance", 0)), INK, "hero"),
            ("доход за период", money(s.get("earned", 0)), GREEN, "green"),
            ("расход за период", money(spent), RED if spent else INK_2, "red" if spent else "plain"),
        ]
        per_day = safe.get("per_day")
        if per_day is not None:
            tiles.append(("можно тратить в день", money(per_day), GREEN if per_day > 0 else RED,
                          "green" if per_day > 0 else "red"))
        now = datetime.now()
        sub = f"за {days} {_plural(days, 'день', 'дня', 'дней')} · {now.day} {_month(now)}"
        return band_card("finances", "финансы", sub, tiles[:4], path=path, badge="финансы")
    except Exception as e:
        log.warning("finances card: %s", e)
        return None


def order_card(title: str, client: str = "", amount: float | None = None, status: str = "",
               path: Path | None = None) -> Path | None:
    """Карточка заказа: клиент, сумма, статус. Светлая полоса 21:9."""
    try:
        tiles = [("заказ", (title or "заказ")[:28], INK), ("клиент", client or "—", INK_2)]
        if amount is not None:
            tiles.append(("сумма", money(amount), GREEN if status in ("paid", "оплачен") else INK,
                          "green" if status in ("paid", "оплачен") else "plain"))
        if status:
            tiles.append(("статус", status, INK_2))
        return band_card("order", title or "заказ", client, tiles[:4], path=path)
    except Exception as e:
        log.warning("order card: %s", e)
        return None


def for_result(actions, text: str = "") -> Path | None:
    """Карточка для «важного ответа» по списку действий — одна логика и для Telegram, и для сайта.
    None, когда картинки выключены (cards.mode) или показывать нечего. Рендер синхронный (Pillow)."""
    try:
        acts = set(actions or [])
        if acts & {"add_expense", "add_income"} and should_send("expense"):
            tx = finance.last_transaction()
            if tx:
                return expense_card(tx, finance.summary(30).get("total_balance", 0))
        if "add_task" in acts and should_send("task"):
            ts = tasks.list_tasks(limit=1)
            if ts:
                t = ts[0]
                when = f"{t.due:%d.%m %H:%M}" if getattr(t, "due", None) else ""
                return task_card(t.title, when)
        if "add_event" in acts and should_send("event"):
            evs = calendar.events_today() or []
            if evs:
                e = evs[-1]
                return event_card(e.title, f"{e.start:%H:%M}" if getattr(e, "start", None) else "")
        if acts & {"complete_task", "complete_event"} and should_send("done"):
            title = (text or "").split("—")[0].strip().strip("«»").strip()[:60]
            return done_card(title or "готово")
        if acts & {"finance_summary", "summary"} and should_send("finances"):
            return finances_card()
    except Exception as e:
        log.warning("for_result: %s", e)
    return None


def month_snapshot_card(path: Path | None = None) -> Path | None:
    """Снимок «как я жил в этом месяце»: деньги, работа, привычки — одной карточкой (экспорт-итог)."""
    try:
        now = datetime.now()
        s = finance.summary(30)
        st, streak = {}, {}
        try:
            from . import insights as _ins
            from . import orders as _o
            st = _o.stats(1)
            streak = _ins.streak()
        except Exception as e:  # pragma: no cover
            log.debug("snapshot extras: %s", e)
        c = _Canvas()
        c.header("снимок месяца")
        c.title(f"как я жил в {_month(now)}", f"на {now.day} {_month(now)} {now.year}")
        c.stats([("заработал", money(s.get("earned", 0)), GREEN),
                 ("потратил", money(s.get("spent", 0)), RED),
                 ("на счетах", money(s.get("total_balance", 0)), INK)])
        c.label("работа")
        c.row("часы", "по таймеру", f"{st.get('total_hours', 0)} ч", left_w=150)
        if st.get("rate"):
            c.row("ставка", "выходит в среднем", money(st["rate"]) + " /ч", left_w=150)
        c.row("заказы", "открыто сейчас", str(st.get("open", 0)), left_w=150)
        if st.get("unpaid"):
            c.row("заказы", "ждут оплаты", money(st["unpaid"]), right_color=RED, left_w=150)
        c.label("привычки")
        c.row("подряд", "дней вели записи", str(streak.get("current", 0)), left_w=150)
        c.row("рекорд", "лучший стрик, дней", str(streak.get("best", 0)), left_w=150)
        return c.finish(_out("month_snapshot.png", path))
    except Exception as e:
        log.warning("month snapshot failed: %s", e)
        return None


# ---------------------------------------------------------------- карточки команд (/tasks, /events, /debts, …)
def _sheet(badge: str, title: str, sub: str = ""):
    c = _Canvas()
    c.header(badge)
    c.title(title, sub)
    return c


def tasks_card(path: Path | None = None) -> Path | None:
    try:
        ts = tasks.list_tasks(limit=10)
        c = _sheet("задачи", "задачи", f"{len(ts)} " + _plural(len(ts), "открытая", "открытые", "открытых") if ts else "всё закрыто")
        if ts:
            now = datetime.now()
            for t in ts:
                right, urgent = None, False
                if getattr(t, "due", None):
                    d = t.due
                    if d.date() < now.date():
                        right, urgent = f"просрочено · {d:%d.%m}", True
                    elif d.date() == now.date():
                        right = f"до {d:%H:%M}"
                    else:
                        right = f"{d:%d.%m}"
                c.check_row(t.title, right, right_color=RED if urgent else INK_2, urgent=urgent)
        else:
            c.empty("открытых задач нет. подозрительно.")
        return c.finish(_out("cmd_tasks.png", path))
    except Exception as e:
        log.warning("tasks card: %s", e)
        return None


def events_card(path: Path | None = None, days: int = 7) -> Path | None:
    try:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        evs = calendar.list_events(start, start + timedelta(days=days + 1), limit=14)
        c = _sheet("календарь", "что впереди", f"ближайшие {days} " + _plural(days, "день", "дня", "дней"))
        if evs:
            last = None
            for e in evs:
                if e.start.date() != last:
                    last = e.start.date()
                    c.label(f"{_weekday(e.start)}, {e.start.day} {_month(e.start)}")
                c.row(f"{e.start:%H:%M}", e.title + (f" · {e.location}" if e.location else ""), left_color=ACCENT)
        else:
            c.empty("встреч нет — день ваш")
        return c.finish(_out("cmd_events.png", path))
    except Exception as e:
        log.warning("events card: %s", e)
        return None


def debts_card(path: Path | None = None) -> Path | None:
    try:
        ds = finance.list_debts()
        active = [d for d in ds if not getattr(d, "closed", False)]
        total = sum((d.remaining or 0) for d in active)
        monthly = sum((d.payment or 0) for d in active)
        c = _sheet("долги", "долги", f"осталось {money(total)}" + (f" · {money(monthly)}/мес" if monthly else ""))
        if active:
            for d in active:
                right = f"{money(d.remaining)}"
                left = f"{d.pay_day:02d} число" if getattr(d, "pay_day", None) else "—"
                c.row(left, d.title + (f" · из {money(d.total)}" if d.total else ""), right, right_color=RED, left_w=150)
        else:
            c.empty("долгов нет. приятно.")
        return c.finish(_out("cmd_debts.png", path))
    except Exception as e:
        log.warning("debts card: %s", e)
        return None


def orders_card(path: Path | None = None) -> Path | None:
    try:
        from . import orders as _o
        rows = _o.list_orders()[:10]
        unpaid = sum((o.get("left") or 0) for o in rows)
        c = _sheet("заказы", "заказы в работе", f"{len(rows)} · ждут оплаты {money(unpaid)}" if rows else "пусто")
        if rows:
            for o in rows:
                right = money(o.get("left") or o.get("price") or 0)
                c.row(o.get("status_label") or (o.get("status") or ""), (o.get("title") or "") + (f" · {o['client']}" if o.get("client") else ""),
                      right, right_color=GREEN if (o.get("status") == "paid") else INK, left_w=190)
        else:
            c.empty("заказов в работе нет")
        return c.finish(_out("cmd_orders.png", path))
    except Exception as e:
        log.warning("orders card: %s", e)
        return None


def goals_card(path: Path | None = None) -> Path | None:
    try:
        from . import goals as _g
        gs = _g.list_goals()
        c = _sheet("цели", "цели и конверты", f"{len(gs)} " + _plural(len(gs), "цель", "цели", "целей") if gs else "пусто")
        if gs:
            for g in gs:
                pct = round((g.get("pct") or 0) * 100)
                c.row(f"{pct}%", g.get("title") or "", money(g.get("saved") or 0) + " / " + money(g.get("target") or 0),
                      right_color=GREEN if pct >= 100 else INK_2, left_w=90)
        else:
            c.empty("целей пока нет")
        return c.finish(_out("cmd_goals.png", path))
    except Exception as e:
        log.warning("goals card: %s", e)
        return None


def missed_card(path: Path | None = None) -> Path | None:
    try:
        from . import missed as _m
        m = _m.missed()
        c = _sheet("упущения", "что я упускаю", f"{m['count']} " + _plural(m["count"], "пункт", "пункта", "пунктов") if m["count"] else "чисто")
        if not m["count"]:
            c.note("Ничего не упускаете, сэр. Редкое и подозрительное состояние.")
        else:
            if m["unpaid"]:
                c.label("ждут оплаты", len(m["unpaid"]))
                for o in m["unpaid"][:4]:
                    c.row("оплата", (o.get("title") or "") + (f" · {o['client']}" if o.get("client") else ""),
                          money(o.get("left") or 0), right_color=RED, left_w=140)
            if m["overdue_debts"]:
                c.label("платежи по долгам", len(m["overdue_debts"]))
                for d in m["overdue_debts"][:4]:
                    c.row(f"{d.get('pay_day', 1):02d} число", d.get("title") or "", money(d.get("payment") or 0), right_color=ORANGE, left_w=140)
            if m["tasks_no_due"]:
                c.label("дела без срока", len(m["tasks_no_due"]))
                for t in m["tasks_no_due"][:4]:
                    c.check_row(t.get("title") or "")
            if m["goals_stale"]:
                c.label("цели без движения", len(m["goals_stale"]))
                for g in m["goals_stale"][:4]:
                    c.row(f"{g.get('pct', 0)}%", g.get("title") or "", money(g.get("left") or 0) if g.get("left") else "", left_w=90)
        return c.finish(_out("cmd_missed.png", path))
    except Exception as e:
        log.warning("missed card: %s", e)
        return None


def forecast_card(path: Path | None = None) -> Path | None:
    try:
        from . import insights
        f = insights.cash_forecast(30)
        cur = f["points"][0]["balance"] if f.get("points") else 0
        tiles = [("сейчас", money(cur), INK), ("в среднем в день", money(f.get("per_day") or 0), ORANGE)]
        if f.get("safe_per_day") is not None:
            tiles.append(("можно тратить", money(f["safe_per_day"]), GREEN if f["safe_per_day"] > 0 else RED))
        c = _sheet("прогноз", "прогноз кассы", "на 30 дней вперёд")
        c.stats(tiles[:3])
        if not f.get("ok"):
            d = datetime.fromisoformat(f["low_date"])
            c.label("внимание")
            c.row(f"{d:%d.%m}", "при текущем темпе уйдёте в минус", money(f["low"]), right_color=RED, left_w=120)
        if f.get("expected_income"):
            c.label("ожидается по заказам")
            c.row("доход", "уже за вычетом налога", money(f["expected_income"]), right_color=GREEN, left_w=120)
        return c.finish(_out("cmd_forecast.png", path))
    except Exception as e:
        log.warning("forecast card: %s", e)
        return None


def today_card(path: Path | None = None) -> Path | None:
    """«Сегодня» — короткая сводка дня (для /today): дневной рендер с бейджем «сегодня»."""
    try:
        return morning_card(path or (DATA_DIR / "tmp" / "today.png"), badge="сегодня", title="сегодня")
    except Exception as e:
        log.warning("today card: %s", e)
        return None

