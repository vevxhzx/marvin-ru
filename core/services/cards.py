"""Картинки-«открытки» для Telegram: утренний дашборд, недельный/месячный отчёт. Рисуем Pillow, без внешних сервисов.

Стиль как у сайта: тёплый серый фон, огромные строчные заголовки, синий акцент, пилюли.
Шрифт: Windows — Segoe UI (есть всегда), Linux — DejaVu; при отсутствии — встроенный.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from ..config import DATA_DIR
from . import calendar, finance, tasks
from .finance import money

log = logging.getLogger("assistant.cards")

W = 1080
BG = (243, 241, 238)
INK = (28, 28, 30)
MUTED = (120, 118, 114)
BLUE = (10, 110, 255)
GREEN = (36, 160, 90)
RED = (220, 60, 60)
CARD = (255, 255, 255)
LINE = (226, 223, 218)

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
_REG_CANDIDATES = ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def _font(size: int, bold: bool = True):
    from PIL import ImageFont
    for p in (_FONT_CANDIDATES if bold else _REG_CANDIDATES + _FONT_CANDIDATES):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _ellipsis(draw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _pill(draw, x, y, text, font, fg=INK, bg=(232, 230, 226)):
    w = draw.textlength(text, font=font) + 28
    h = font.size + 16
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=bg)
    draw.text((x + 14, y + 7), text, font=font, fill=fg)
    return w


def _bar(draw, x, y, w, h, frac, color):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=(228, 226, 222))
    if frac > 0:
        draw.rounded_rectangle((x, y, x + max(h, int(w * min(1.0, frac))), y + h), radius=h // 2, fill=color)


def _new(height: int):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, height), BG)
    return img, ImageDraw.Draw(img)


def _footer(draw, h: int):
    f = _font(22, False)
    from .. import identity
    draw.text((56, h - 52), identity.NAME.lower(), font=_font(24), fill=MUTED)
    txt = datetime.now().strftime("%d.%m.%Y %H:%M")
    draw.text((W - 56 - draw.textlength(txt, font=f), h - 50), txt, font=f, fill=MUTED)


# ---------------------------------------------------------------- утренний дашборд
def morning_card(path: Path | None = None) -> Path | None:
    try:
        now = datetime.now()
        evs = calendar.events_today()[:5]
        ts = tasks.list_tasks(limit=5)
        pays = finance.upcoming_payments(3)[:3]
        s = finance.summary(1)
        safe = s.get("safe") or {}
        h = 300 + 70 * max(1, len(evs)) + 60 * max(1, len(ts)) + (70 + 50 * len(pays) if pays else 0) + 200
        img, d = _new(h)
        wd = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][now.weekday()]
        d.text((56, 48), "доброе утро, сэр", font=_font(72), fill=INK)
        d.text((58, 140), f"{wd}, {now:%d.%m}", font=_font(30, False), fill=MUTED)
        y = 210
        d.text((56, y), "сегодня", font=_font(40), fill=INK); y += 62
        if evs:
            for e in evs:
                d.text((56, y), f"{e.start:%H:%M}", font=_font(30), fill=BLUE)
                d.text((170, y), _ellipsis(d, e.title + (f" · {e.location}" if e.location else ""), _font(30, False), W - 230), font=_font(30, False), fill=INK)
                y += 56
        else:
            d.text((56, y), "встреч нет — день ваш", font=_font(30, False), fill=MUTED); y += 56
        y += 30
        d.text((56, y), "задачи", font=_font(40), fill=INK); y += 62
        if ts:
            for t in ts:
                d.ellipse((60, y + 10, 78, y + 28), outline=INK, width=3)
                d.text((100, y), _ellipsis(d, t.title, _font(30, False), W - 200), font=_font(30, False), fill=INK)
                if t.due and t.due.date() == now.date():
                    d.text((W - 56 - d.textlength(f"до {t.due:%H:%M}", font=_font(26)), y + 4), f"до {t.due:%H:%M}", font=_font(26), fill=RED)
                y += 52
        else:
            d.text((56, y), "задач нет. подозрительно.", font=_font(30, False), fill=MUTED); y += 52
        if pays:
            y += 30
            d.text((56, y), "платежи", font=_font(40), fill=INK); y += 62
            for p in pays:
                d.text((56, y), f"{p.next_date:%d.%m}", font=_font(28), fill=MUTED)
                d.text((150, y), _ellipsis(d, p.title, _font(28, False), 600), font=_font(28, False), fill=INK)
                d.text((W - 56 - d.textlength(money(p.amount), font=_font(28)), y), money(p.amount), font=_font(28), fill=INK)
                y += 46
        y += 40
        d.rounded_rectangle((56, y, W - 56, y + 120), radius=28, fill=CARD)
        d.text((84, y + 16), "баланс", font=_font(24, False), fill=MUTED)
        d.text((84, y + 48), money(s["total_balance"]), font=_font(48), fill=INK)
        if safe.get("per_day") is not None:
            txt = f"{money(safe['per_day'])} / день"
            d.text((W - 84 - d.textlength(txt, font=_font(36)), y + 52), txt, font=_font(36), fill=GREEN if safe["per_day"] > 0 else RED)
            d.text((W - 84 - d.textlength("можно тратить", font=_font(24, False)), y + 16), "можно тратить", font=_font(24, False), fill=MUTED)
        _footer(d, h)
        out = path or (DATA_DIR / "tmp" / "morning.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "PNG")
        return out
    except Exception as e:
        log.warning("morning card failed: %s", e)
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
        title = "итоги недели" if days <= 7 else "итоги месяца"
        h = 900 + 64 * len(cats)
        img, d = _new(h)
        d.text((56, 48), title, font=_font(72), fill=INK)
        d.text((58, 140), f"{since:%d.%m} — {datetime.now():%d.%m.%Y}", font=_font(30, False), fill=MUTED)
        y = 210
        # две карточки: потрачено / заработано
        for i, (label, val, color) in enumerate((("потрачено", s["spent"], INK), ("заработано", s["earned"], GREEN))):
            x = 56 + i * ((W - 112) // 2 + 12)
            cw = (W - 112) // 2 - 12
            d.rounded_rectangle((x, y, x + cw, y + 150), radius=28, fill=CARD)
            d.text((x + 28, y + 20), label, font=_font(24, False), fill=MUTED)
            d.text((x + 28, y + 60), money(val), font=_font(52), fill=color)
            if i == 0 and prev_spent:
                diff = (s["spent"] - prev_spent) / prev_spent * 100
                txt = f"{'+' if diff > 0 else ''}{diff:.0f}% к прошл."
                d.text((x + cw - 28 - d.textlength(txt, font=_font(22)), y + 24), txt, font=_font(22), fill=RED if diff > 10 else GREEN if diff < -10 else MUTED)
        y += 190
        d.text((56, y), "куда ушло", font=_font(40), fill=INK); y += 62
        mx = max((v for _, v in cats), default=1)
        for name, v in cats:
            d.text((56, y), _ellipsis(d, name, _font(28, False), 380), font=_font(28, False), fill=INK)
            d.text((W - 56 - d.textlength(money(v), font=_font(28)), y), money(v), font=_font(28), fill=INK)
            _bar(d, 56, y + 42, W - 112, 10, v / mx, BLUE)
            y += 64
        if not cats:
            d.text((56, y), "трат не было. или вы их не записывали.", font=_font(28, False), fill=MUTED); y += 64
        y += 30
        d.text((56, y), "дела", font=_font(40), fill=INK); y += 66
        x = 56
        x += _pill(d, x, y, f"✓ {len(done)} задач закрыто", _font(26)) + 14
        x += _pill(d, x, y, f"✎ {len(notes)} заметок", _font(26)) + 14
        _pill(d, x, y, f"● {active_days} из {days} дней с записями", _font(26), fg=(255, 255, 255), bg=BLUE)
        y += 90
        # лимиты
        over = [b for b in s.get("budgets", []) if b["pct"] >= 0.8][:3]
        if over:
            d.text((56, y), "лимиты", font=_font(40), fill=INK); y += 62
            for b in over:
                d.text((56, y), b["name"], font=_font(28, False), fill=INK)
                txt = f"{b['pct'] * 100:.0f}%"
                d.text((W - 56 - d.textlength(txt, font=_font(28)), y), txt, font=_font(28), fill=RED if b["pct"] >= 1 else (230, 150, 20))
                _bar(d, 56, y + 42, W - 112, 10, b["pct"], RED if b["pct"] >= 1 else (230, 150, 20))
                y += 64
        # баланс
        y += 20
        d.rounded_rectangle((56, y, W - 56, y + 120), radius=28, fill=CARD)
        d.text((84, y + 16), "баланс сейчас", font=_font(24, False), fill=MUTED)
        d.text((84, y + 48), money(s["total_balance"]), font=_font(48), fill=INK)
        if s.get("debts_total"):
            txt = f"долги {money(s['debts_total'])}"
            d.text((W - 84 - d.textlength(txt, font=_font(30)), y + 56), txt, font=_font(30), fill=MUTED)
        y += 140
        img = img.crop((0, 0, W, min(h, y + 80)))
        from PIL import ImageDraw
        _footer(ImageDraw.Draw(img), img.height)
        out = path or (DATA_DIR / "tmp" / f"report_{days}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "PNG")
        return out
    except Exception as e:
        log.warning("report card failed: %s", e)
        return None
