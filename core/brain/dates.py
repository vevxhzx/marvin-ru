"""Понимание русских дат и времени в свободной форме.

Примеры: «в среду в 15:00», «завтра в 10», «через 2 часа», «25 сентября в 19», «сегодня вечером», «в пт».
Возвращает (datetime | None, текст_без_даты).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

WEEKDAYS = {
    "понедельник": 0, "понедельника": 0, "пн": 0, "вторник": 1, "вторника": 1, "вт": 1,
    "среда": 2, "среду": 2, "среды": 2, "ср": 2, "четверг": 3, "четверга": 3, "чт": 3,
    "пятница": 4, "пятницу": 4, "пятницы": 4, "пт": 4, "суббота": 5, "субботу": 5, "субботы": 5, "сб": 5,
    "воскресенье": 6, "воскресенья": 6, "вс": 6,
}
MONTHS = {
    "янв": 1, "фев": 2, "мар": 3, "апр": 4, "ма": 5, "июн": 6, "июл": 7,
    "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12,
}
PARTS_OF_DAY = {"утром": 9, "днём": 13, "днем": 13, "вечером": 19, "ночью": 23, "в обед": 13, "после обеда": 14,
                "в полдень": 12, "полдень": 12, "в полночь": 0, "перед сном": 22, "к вечеру": 18, "с утра": 9}
UNITS = {
    "минут": "minutes", "мин": "minutes", "час": "hours", "ч": "hours",
    "дн": "days", "ден": "days", "нед": "weeks", "мес": "months",
}
NUM_WORDS = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
             "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "пол": 0.5, "полтора": 1.5}


def _clean(text: str) -> str:
    return re.sub(r"\s{2,}", " ", text.replace("\x00", " ")).strip(" ,.-—:")


class _Text(str):
    """Строка в нижнем регистре, которая помнит оригинал и умеет «вырезать» куски, сохраняя регистр."""
    __slots__ = ("orig",)

    def __new__(cls, orig: str):
        obj = super().__new__(cls, orig.lower())
        obj.orig = orig
        return obj

    def replace(self, old: str, new: str = " ", count: int = -1) -> "_Text":  # type: ignore[override]
        i = str.find(self, old)
        if i < 0:
            return self
        n = len(old)
        low = str(self)[:i] + "\x00" * n + str(self)[i + n:]
        orig = self.orig[:i] + "\x00" * n + self.orig[i + n:]
        res = str.__new__(_Text, low)
        res.orig = orig
        return res

    def final(self) -> str:
        return _clean(self.orig)


def parse_datetime(text: str, now: datetime | None = None) -> tuple[datetime | None, str]:
    now = now or datetime.now()
    t = _Text(" " + text + " ")
    date: datetime | None = None
    time_set = False
    hour, minute = 10, 0

    # --- «через N единиц» ---
    m = re.search(r"через\s+(\d+(?:[.,]\d+)?|[а-я]+)?\s*(минут\w*|мин|час\w*|ч|дн\w*|ден\w*|нед\w*|мес\w*)", t)
    if m:
        raw = m.group(1)
        n = 1.0
        if raw:
            n = NUM_WORDS.get(raw, None)
            if n is None:
                try:
                    n = float(raw.replace(",", "."))
                except ValueError:
                    n = 1.0
        unit = next((v for k, v in UNITS.items() if m.group(2).startswith(k)), "hours")
        if unit == "months":
            date = now + relativedelta(months=int(n))
        else:
            date = now + timedelta(**{unit: n})
        t = t.replace(m.group(0), " ")
        return date.replace(second=0, microsecond=0), t.final()

    # --- время: 15:00, 15.30, «в 15», «в 3 часа дня», «в пол третьего» (упрощённо) ---
    m = re.search(r"(?:в|на|к)\s+(\d{1,2})[:.](\d{2})", t) or re.search(r"\b(\d{1,2})[:](\d{2})\b", t)
    if m:
        hour, minute, time_set = int(m.group(1)), int(m.group(2)), True
        t = t.replace(m.group(0), " ")
    else:
        m = re.search(r"(?:в|на|к)\s+(\d{1,2})(?:\s*(?:час\w*|ч\b))?(?!\s*(?:сентябр|октябр|ноябр|декабр|январ|феврал|март|апрел|ма[йя]|июн|июл|август|числ|минут|тыс|руб|к\b|₽|%|-го|го\b))\s*(утра|дня|вечера|ночи)?", t) \
            or re.search(r"\b(\d{1,2})(?:\s*(?:час\w*|ч\b))?\s+(утра|дня|вечера|ночи)\b", t)
        if m and 0 <= int(m.group(1)) <= 23:
            hour, time_set = int(m.group(1)), True
            suffix = m.group(2) or ""
            if suffix in ("дня", "вечера") and hour < 12:
                hour += 12
            elif not suffix and 1 <= hour <= 7:  # «в 3» скорее всего 15:00
                hour += 12
            t = t.replace(m.group(0), " ")
    for word, h in PARTS_OF_DAY.items():
        if word in t:
            if not time_set:
                hour, time_set = h, True
            t = t.replace(word, " ")

    # --- дедлайн: «до пятницы / до завтра / до 25.09 / до конца недели» → конец того дня ---
    deadline = False
    m = re.search(r"\bдо\s+(конца\s+(?:недели|месяца|дня)|завтра|послезавтра|" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r"|\d{1,2}(?:\s+[а-я]+|[./]\d{1,2}(?:[./]\d{2,4})?|[- ]?го)?)\b", t)
    if m and not time_set:
        deadline = True
        what = m.group(1)
        if what.startswith("конца"):
            if "недели" in what:
                date = now + timedelta(days=6 - now.weekday())
            elif "месяца" in what:
                date = (now.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
            else:
                date = now
            t = t.replace(m.group(0), " ")
        elif what in WEEKDAYS:
            date = now + timedelta(days=((WEEKDAYS[what] - now.weekday()) % 7) or 7)
            t = t.replace(m.group(0), " ")
        else:
            t = t.replace(" до ", " ", 1)  # дальше разберёт обычный парсер даты
    # --- дата ---
    if "на выходных" in t or "в выходные" in t:
        delta = (5 - now.weekday()) % 7
        date = now + timedelta(days=delta or 7 if now.weekday() >= 5 else delta)
        t = t.replace("на выходных", " ").replace("в выходные", " ")
    elif "на следующей неделе" in t or "на след неделе" in t:
        date = now + timedelta(days=(7 - now.weekday()))
        t = t.replace("на следующей неделе", " ").replace("на след неделе", " ")
    elif "позавчера" in t:
        date = now - timedelta(days=2); t = t.replace("позавчера", " ")
    elif "вчера" in t:
        date = now - timedelta(days=1); t = t.replace("вчера", " ")
    elif "послезавтра" in t:
        date = now + timedelta(days=2); t = t.replace("послезавтра", " ")
    elif "завтра" in t:
        date = now + timedelta(days=1); t = t.replace("завтра", " ")
    elif "сегодня" in t:
        date = now; t = t.replace("сегодня", " ")
    else:
        m = re.search(r"(?:в|во)\s+(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\b", t) \
            or re.search(r"\b(" + "|".join(k for k in WEEKDAYS if len(k) > 2) + r")\b", t)
        if m:
            wd = WEEKDAYS[m.group(1)]
            delta = (wd - now.weekday()) % 7
            if delta == 0 and (time_set and (hour, minute) <= (now.hour, now.minute) or not time_set and now.hour >= 20):
                delta = 7
            date = now + timedelta(days=delta)
            t = t.replace(m.group(0), " ")
        else:
            # «25 сентября», «25.09», «25-го»
            m = re.search(r"\b(\d{1,2})\s+(янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек)\w*", t)
            if m:
                mon = MONTHS["ма" if m.group(2) in ("май", "мая") else m.group(2)[:3]]
                try:
                    date = now.replace(month=mon, day=int(m.group(1)))
                except ValueError:
                    date = now.replace(month=mon, day=28)
                if (now.date() - date.date()).days > 14:
                    date += relativedelta(years=1)   # давно прошло → следующий год; неделю назад → это была та дата
                t = t.replace(m.group(0), " ")
            else:
                m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", t)
                if m:
                    y = int(m.group(3)) if m.group(3) else now.year
                    y = y + 2000 if y < 100 else y
                    try:
                        date = now.replace(year=y, month=int(m.group(2)), day=int(m.group(1)))
                        t = t.replace(m.group(0), " ")
                    except ValueError:
                        date = None
                else:
                    # «25-го», «12 числа», «12-е число» — день этого месяца (или следующего, если уже прошёл)
                    m = re.search(r"\b(\d{1,2})(?:[- ]?го|[- ]?е)?\s*(?:числа|число)\b", t) or re.search(r"\b(\d{1,2})[- ]?го\b", t)
                    if m:
                        d = int(m.group(1))
                        base = now if d >= now.day else now + relativedelta(months=1)
                        last = (base.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).day
                        date = base.replace(day=min(d, last))
                        t = t.replace(m.group(0), " ")

    if date is None and time_set:
        date = now
        if (hour, minute) <= (now.hour, now.minute):
            date += timedelta(days=1)   # «в 9 утра», а уже 14:00 → завтра
    if date is None:
        return None, t.final()
    if deadline and not time_set:
        hour, minute = 23, 59
    dt = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return dt, t.final()


def parse_amount(text: str) -> tuple[float | None, str]:
    """«700», «1.5к», «120 тыс», «2 500 руб» → сумма и текст без неё."""
    t = text.lower().replace("₽", " руб ")
    m = re.search(r"(\d[\d\s]*(?:[.,]\d+)?)\s*(к|k|тыс\w*|т\.?р\.?|млн)?(?![а-яёa-z])\s*(руб\w*|р\.?|рублей)?(?![а-яёa-z\d])", t)
    if m and re.search(r"\d\s+\d", m.group(1)):
        # «1200 5-го» / «5000 25 сентября» — это два разных числа, а не «1 200»: разряды — строго по 3 цифры
        parts = m.group(1).split()
        if not all(len(x) == 3 and x.isdigit() for x in parts[1:]):
            first = re.match(r"\d+(?:[.,]\d+)?", m.group(1)).group(0)
            m = re.search(r"(" + re.escape(first) + r")(?!\d)\s*(к|k|тыс\w*|т\.?р\.?|млн)?(?![а-яёa-z])\s*(руб\w*|р\.?|рублей)?(?![а-яёa-z\d])", t)
    if not m:
        return None, text
    raw = m.group(1).replace(" ", "").replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        return None, text
    mult = m.group(2) or ""
    if mult in ("к", "k") or mult.startswith("тыс") or mult.startswith("т"):
        val *= 1000
    elif mult == "млн":
        val *= 1_000_000
    rest = (t[:m.start()] + " " + t[m.end():])
    return val, _clean(rest)


# ---------------------------------------------------------------- повторы
_WD_ALT = "|".join(sorted(WEEKDAYS, key=len, reverse=True))


def parse_repeat(text: str, now: datetime | None = None) -> tuple[dict | None, str]:
    """«каждый пн ср пт в 19», «каждый день в 8», «раз в год 14 марта», «ежемесячно 25-го».

    Возвращает ({"repeat": ..., "days": [...], "anchor": datetime|None}, текст_без_повтора).
    В anchor лежит первая дата (для weekly — ближайший из дней, время берётся из остатка текста парсером дат).
    """
    now = now or datetime.now()
    t = _Text(" " + text + " ")
    rule: dict | None = None

    m = re.search(r"\b(?:каждый\s+день|ежедневно|каждое\s+утро|каждый\s+вечер)\b", t)
    if m:
        rule = {"repeat": "daily", "days": []}
        if "утро" in m.group(0):
            rule["hour"] = 9
        elif "вечер" in m.group(0):
            rule["hour"] = 19
        t = t.replace(m.group(0), " ")
    if rule is None:
        m = re.search(r"\b(?:каждую\s+неделю|еженедельно|раз\s+в\s+неделю)\b", t)
        if m:
            rule = {"repeat": "weekly", "days": []}
            t = t.replace(m.group(0), " ")
    if rule is None:
        m = re.search(r"\b(?:каждый\s+месяц|ежемесячно|раз\s+в\s+месяц)\b", t)
        if m:
            rule = {"repeat": "monthly", "days": []}
            t = t.replace(m.group(0), " ")
    if rule is None:
        m = re.search(r"\b(?:каждый\s+год|ежегодно|раз\s+в\s+год)\b", t)
        if m:
            rule = {"repeat": "yearly", "days": []}
            t = t.replace(m.group(0), " ")
    # «каждый пн ср пт», «по понедельникам и средам», «каждую субботу»
    if rule is None or rule["repeat"] == "weekly":
        m = re.search(r"\b(?:кажд(?:ый|ую|ое|ые)|по)\s+((?:(?:" + _WD_ALT + r")\w*[\s,]*(?:и\s+)?)+)", t)
        if m:
            days = []
            for w in re.findall(r"[а-яё]+", m.group(1)):
                for key in sorted(WEEKDAYS, key=len, reverse=True):
                    if w.startswith(key) and (len(key) > 2 or w == key):
                        days.append(WEEKDAYS[key]); break
            if days:
                rule = {"repeat": "weekly", "days": sorted(set(days))}
                t = t.replace(m.group(0), " ")
    if rule is None:
        return None, text
    # «до конца года / до декабря» — пока не парсим, дата окончания задаётся на сайте
    rest = t.final()
    return rule, rest


def first_occurrence(rule: dict, when: datetime | None, now: datetime | None = None) -> datetime:
    """Первая дата повтора. when — то, что распарсил parse_datetime из остатка (может быть None)."""
    now = now or datetime.now()
    base = when or now.replace(hour=rule.get("hour", 10), minute=0, second=0, microsecond=0)
    if when is None and rule.get("hour") is None and rule["repeat"] != "weekly":
        base = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if rule["repeat"] == "weekly" and rule["days"]:
        # ближайший из указанных дней (сегодня подходит, если время ещё впереди)
        for delta in range(0, 8):
            d = base + timedelta(days=delta)
            if d.weekday() in rule["days"] and (delta > 0 or d > now or when is not None and when.date() > now.date()):
                return d.replace(second=0, microsecond=0)
    if base <= now and rule["repeat"] == "daily":
        base += timedelta(days=1)
    return base.replace(second=0, microsecond=0)
