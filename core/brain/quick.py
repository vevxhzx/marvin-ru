"""Быстрые правила без LLM: справки («сколько потратил на еду за неделю», «что у меня завтра», «какие долги»),
деньги («переведи 5000 на сбер», «снял 3000 наличных», «заплатил Диме 2000», «вернули долг 5000», «закрой долг Диме»,
«подписка яндекс плюс 399 25-го», «лимит на еду 20000», «отмени подписку яндекс»), режим жизни
(«я уезжаю в армию 28 октября», «вернулся», «удали режим») и короткие реплики («спасибо», «ок»).

Всё работает мгновенно и офлайн — это то, что «настоящий ассистент» обязан понимать даже когда мозг спит.
Каждая функция возвращает (text, actions) или None.
"""
from __future__ import annotations

import json
import random
import re

from .. import identity
from datetime import datetime, timedelta

from ..db import get_setting, set_setting
from ..services import calendar, finance, regime, tasks
from ..services.calendar import fmt_dt
from ..services.finance import money
from ..services.plural import days as _days_word
from .dates import is_all_day, parse_amount, parse_datetime

Result = tuple[str, list[str]]

# ------------------------------------------------------------------ короткие реплики
THANKS_RX = re.compile(r"^\s*(спасибо|спс|благодарю|пасиб\w*|thanks?|thx|красавчик|молодец|отлично|супер|класс|огонь|топ|👍|🔥|❤️)\W*(сэр|" + identity.NAME_RX_SRC + r"|бро)?\W*$", re.I)
OK_RX = re.compile(r"^\s*(ок|окей|ok|окей " + identity.NAME_RX_SRC + r"|понял|понятно|ясно|принято|ага|угу|хорошо|ладно|норм|👌)\W*$", re.I)
BYE_RX = re.compile(r"^\s*(пока|бай|до связи|до завтра|отбой на сегодня|хватит|всё|все|достаточно|свободен)\W*$", re.I)
NAME_RX = re.compile(r"^\s*(" + identity.NAME_RX_SRC + r"|эй|ау|ты тут)\W*$", re.I)
YESNO_LONE_RX = re.compile(r"^\s*(да|нет|не|неа)\W*$", re.I)

_THANKS = ["Всегда пожалуйста, сэр.", "Не за что. Для этого и существую.", "Обращайтесь. Сарказм — бесплатно.",
           "Пожалуйста. Это было несложно — в отличие от вашего расписания."]
_OK = ["Принято.", "Есть, сэр.", "Так точно.", "Хорошо."]
_BYE = ["До связи, сэр. Я тут, если что.", "Ухожу в фоновый режим. Буду следить за календарём и балансом.",
        "Отбой. Не забудьте про завтра — я напомню."]
_NAME = ["Слушаю, сэр.", "Да, сэр?", "Я здесь. Что делаем?", "На связи."]


# «привет» / «че как дела» / «что как делиша»: раньше такие фразы уходили в облако и отвечали там
# чем попало (эхо вопроса, «запускаю мозги»). Теперь это локально, мгновенно и с цифрами дня.
GREET_RX = re.compile(r"^\s*(?:привет|здравствуй\w*|здаров\w*|здорово|хай|йо|ку|салют|доброе\s+утро|добрый\s+(?:день|вечер)|доброй\s+ночи|го)\W*(?:"
                      + identity.NAME_RX_SRC + r"|сэр|бро|брат|джарвис)?[!.…]*\s*$", re.I)
HOW_RX = re.compile(r"^\s*(?:что\s+|ну\s+|че\s+|чё\s+|короче\s+)*как\s+(?:у\s+тебя\s+)?(?:дела|дел\w*|делиша\w*|делишки|жизнь|настроение|ты|сам|самочувствие|"
                    r"как\s+ты)|^\s*(?:че|чё|ну)\s+там\s*[?!]*$|^\s*ну\s+и?\s*как\s*\??$", re.I)


def _day_status() -> str:
    """Короткий статус дня для «как дела»: живые цифры вместо болтовни из головы."""
    evs = calendar.events_today()
    ts = tasks.list_tasks(limit=100)
    s = finance.summary(1)
    bits = []
    if evs:
        bits.append(f"встреч {len(evs)} (первая в {evs[0].start:%H:%M})" if len(evs) > 1 else f"встреча в {evs[0].start:%H:%M}")
    else:
        bits.append("встреч нет — день мой")
    bits.append(f"открытых задач {len(ts)}" if ts else "задач нет")
    money_bits = []
    if s.get("spent"):
        money_bits.append(f"за сегодня −{money(s['spent'])}")
    bal = s.get("total_balance")
    if bal is not None:
        money_bits.append(f"баланс {money(bal)}")
    return " · ".join(bits + money_bits)


_HOW_REPLIES = [
    "Держусь, {addr}: {status}. Ваша очередь — что делаем?",
    "В норме. По сегодняшнему дню: {status}. Чем помочь?",
    "Работаю. По дню: {status}. Что на повестке?",
]


def smalltalk(text: str) -> Result | None:
    if GREET_RX.match(text):
        return _greet(), ["greet"]
    if HOW_RX.match(text):
        return random.choice(_HOW_REPLIES).format(addr=_addr(), status=_day_status()), ["smalltalk"]
    if THANKS_RX.match(text):
        return random.choice(_THANKS), ["smalltalk"]
    if OK_RX.match(text):
        return random.choice(_OK), ["smalltalk"]
    if BYE_RX.match(text):
        return random.choice(_BYE), ["smalltalk"]
    if NAME_RX.match(text):
        return random.choice(_NAME), ["smalltalk"]
    if YESNO_LONE_RX.match(text):
        return "Это ответ на что-то, сэр, но я не задавал вопроса. Уточните.", ["smalltalk"]
    return None


def _addr() -> str:
    try:
        from ..config import cfg
        return (getattr(getattr(cfg, "owner", None), "name", None) or "сэр").strip() or "сэр"
    except Exception:  # pragma: no cover
        return "сэр"


def _greet() -> str:
    """Приветствие: готовая реплика персоны (учитывает стиль и обращение), без вызова LLM."""
    from . import persona
    try:
        return persona.say("greet")
    except Exception:  # pragma: no cover
        return "На связи. Пишите как удобно: трату, дело, встречу, мысль — или просто спросите."


# ------------------------------------------------------------------ периоды
def _period(low: str) -> tuple[datetime, datetime | None, str] | None:
    """«за неделю / за месяц / сегодня / вчера / за 3 дня / в сентябре» → (since, until, подпись)."""
    now = datetime.now()
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\bсегодня\b|за день\b", low):
        return d0, None, "сегодня"
    if re.search(r"\bвчера\b", low):
        return d0 - timedelta(days=1), d0, "вчера"
    if re.search(r"за\s+(эту\s+)?неделю|на\s+(этой\s+)?неделе|за\s+7\s+дн", low):
        return d0 - timedelta(days=now.weekday()), None, "с понедельника"
    if re.search(r"за\s+(прошл|предыдущ)\w*\s+неделю", low):
        st = d0 - timedelta(days=now.weekday() + 7)
        return st, st + timedelta(days=7), "за прошлую неделю"
    if re.search(r"за\s+(этот\s+)?месяц|в\s+этом\s+месяце|за\s+30\s+дн", low):
        return d0.replace(day=1), None, f"с 1 {_MONTHS_GEN[now.month - 1]}"
    if re.search(r"за\s+(прошл|предыдущ)\w*\s+месяц", low):
        first = d0.replace(day=1)
        prev = (first - timedelta(days=1)).replace(day=1)
        return prev, first, f"за {_MONTHS_ACC[prev.month - 1]}"
    if re.search(r"за\s+год|в\s+этом\s+году", low):
        return d0.replace(month=1, day=1), None, "с начала года"
    m = re.search(r"за\s+(\d+)\s*(дн|ден|день|дня|дней)", low)
    if m:
        n = int(m.group(1))
        return d0 - timedelta(days=n - 1), None, f"за {n} {_days_word(n)}"
    m = re.search(r"\b(?:в|за)\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*", low)
    if m:
        idx = next(i for i, x in enumerate(("янв", "фев", "мар", "апр", "ма", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")) if m.group(1).startswith(x))
        year = now.year if idx + 1 <= now.month else now.year - 1
        st = d0.replace(year=year, month=idx + 1, day=1)
        en = (st + timedelta(days=32)).replace(day=1)
        return st, en, f"за {_MONTHS_ACC[idx]}"
    return None


_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
_MONTHS_ACC = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


# ------------------------------------------------------------------ справки по деньгам
SPENT_RX = re.compile(r"^\s*(?:сколько|скок|че|что)\s+(?:я\s+|мы\s+)?(?:потратил\w*|ушло|улетело|слил\w*|спустил\w*|трат\w*|расход\w*)\b(.*)$|"
                      r"^\s*(?:траты|расходы)\s+(.+)$|^\s*(?:сколько|скок)\s+(?:ушло|потрачено)\s+(.+)$|"
                      r"^\s*(?:куда\s+(?:ушли|делись|утекли|деваются)\s+(?:деньги|бабки|всё|все)|на\s+что\s+(?:я\s+)?(?:трачу|потратил\w*)|статистика\s+трат|отчёт\s+по\s+тратам|отчет\s+по\s+тратам)\b(.*)$", re.I)
EARNED_RX = re.compile(r"^\s*(?:сколько|скок)\s+(?:я\s+)?(?:заработал\w*|получил\w*|пришло|доход\w*)\b(.*)$|^\s*доходы\s+(.+)$", re.I)


def spent(text: str) -> Result | None:
    low = text.lower().strip(" ?!.")
    m = SPENT_RX.match(low)
    kind = "expense"
    if not m:
        m = EARNED_RX.match(low)
        kind = "income"
    if not m:
        return None
    tail = next((g for g in m.groups() if g), "") or ""
    per = _period(low)
    since, until, label = per if per else (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).replace(day=1), None, f"с 1 {_MONTHS_GEN[datetime.now().month - 1]}")
    # категория: «на еду», «на такси», «в кафе»
    cat = None
    skip = {"неделю", "неделе", "месяц", "месяце", "год", "году", "день", "дня", "дней", "сегодня", "вчера", "всего", "итого",
            "прошлую", "прошлый", "этот", "эту", "этом", "этой", "меня", "денег", "деньги", "рублей", "руб"}
    words = [w for w in re.findall(r"[а-яё]+", tail) if len(w) >= 3 and w not in skip and w not in _MONTHS_GEN and w not in _MONTHS_ACC
             and not any(w.startswith(mm[:5]) for mm in _MONTHS_ACC)]
    for w in words:
        c = finance.category_by_word(w, kind)
        if c:
            cat = c
            break
    if kind == "income":
        txs = [t for t in finance.list_transactions(400, 100_000) if t.kind == "income" and t.date >= since and (not until or t.date < until)]
        if cat:
            txs = [t for t in txs if t.category == cat.name]
        total = sum(t.amount for t in txs)
        what = f" ({cat.name})" if cat else ""
        return (f"Доход {label}{what}: **{money(total)}**" + (f", {len(txs)} поступлени{_end(len(txs))}." if txs else ". Пусто, сэр.")), ["query_income"]
    r = finance.spent_by(cat.name if cat else None, since=since, until=until)
    if cat:
        txt = f"На «{cat.name}» {label}: **{money(r['total'])}**"
        if r["count"]:
            txt += f" ({r['count']} операци{_end(r['count'])}, в среднем {money(r['total'] / r['count'])})"
        if cat.budget:
            left = cat.budget - r["total"] if not until and since.day == 1 else None
            if left is not None:
                txt += f". Лимит {money(cat.budget)} — " + (f"осталось {money(left)}" if left >= 0 else f"превышен на {money(-left)} 🚨")
        return txt + ".", ["query_spent"]
    txt = f"Траты {label}: **{money(r['total'])}**"
    if r["by_category"]:
        top = list(r["by_category"].items())[:4]
        txt += " — " + ", ".join(f"{k} {money(v)}" for k, v in top)
    return txt + ".", ["query_spent"]


def _end(n: int) -> str:
    a, b = n % 100, n % 10
    if 10 < a < 20:
        return "й"
    return "я" if b == 1 else "и" if 1 < b < 5 else "й"


# ------------------------------------------------------------------ «что у меня завтра / в пятницу / на выходных»
AGENDA_RX = re.compile(r"^\s*(?:что|чё|че|дайджест\w*|бриф\w*|план\w*|расписание|дела|какие\s+(?:планы|дела|встречи|события))"
                       r"\s*(?:,\s*(?:что|чё|че)\s*)*"                       # «что, что сегодня але»
                       r"\s*(?:у\s+меня|по\s+плану|запланировано|в\s+планах|планы)?\s*(?:на|в|во)?\s*(.+?)\s*\??$", re.I)
# слова-вода, которые люди пишут в запросе дня, но которые не про дату: «что там на сегодня», «че там сегодня але»
_AG_FILLER = re.compile(r"\b(там|ну|вообще|же|але|ух|го|короче|слушай|пожалуйста|дай|дайте|расскажи|покажи|скажи|"
                        r"напомни|посмотри|у\s+меня|мне|что|чё|че|дай)\b", re.I)


def agenda(text: str) -> Result | None:
    low = text.lower().strip(" ?!.")
    if not re.match(r"^(что|чё|че|какие|дайджест|бриф|план\w*|расписание|дела)\b", low):
        return None
    if re.search(r"\b(потратил|ушло|доход|заработал|долг|баланс|денег|деньг\w*|финанс\w*|задач\w*|такое|значит|делать|нового|умеешь|делаешь)\b", low):
        return None
    m = AGENDA_RX.match(low)
    if not m:
        return None
    # «там на сегодня» → «на сегодня»: убираем воду, иначе парсер даты видит мусор и отвечает отказом
    when = re.sub(r"[«»\"',;:!?()]+", " ", m.group(1))
    when = _AG_FILLER.sub(" ", when)
    when = re.sub(r"\s+", " ", when).strip()
    if not when:
        when = "сегодня"
    now = datetime.now()
    d0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\bвыходн", when):
        sat = d0 + timedelta(days=(5 - now.weekday()) % 7)
        start, end, label = sat, sat + timedelta(days=2), "на выходных"
    elif re.search(r"след\w*\s+неделе", when):
        mon = d0 + timedelta(days=7 - now.weekday())
        start, end, label = mon, mon + timedelta(days=7), "на следующей неделе"
    elif re.search(r"\bнеделе\b|\bнеделю\b", when):
        start, end, label = d0, d0 + timedelta(days=7 - now.weekday()), "до конца недели"
    elif re.search(r"\bсегодня\b|\bсегодняшн", when):
        start, end, label = d0, d0 + timedelta(days=1), "сегодня"
    elif re.search(r"\bзавтра\b|\bназавтра\b", when):
        start = d0 + timedelta(days=1)
        start, end, label = start, start + timedelta(days=1), "завтра"
    else:
        dt, rest = parse_datetime(when, now)
        if not dt or re.search(r"[а-яё]{3,}", rest or ""):
            return None
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        label = "сегодня" if start == d0 else "завтра" if start == d0 + timedelta(days=1) else f"{calendar.WD_SHORT[start.weekday()]} {start:%d.%m}"
    evs = calendar.list_events(start, end, limit=50)
    due = [t for t in tasks.list_tasks(limit=200) if t.due and start <= t.due < end]
    pays = [r for r in finance.list_recurring() if start <= r.next_date < end]
    if not evs and not due and not pays:
        return f"{label.capitalize()} — пусто, сэр. Ни встреч, ни дедлайнов. Наслаждайтесь или займите чем-нибудь.", ["agenda"]
    lines = [f"📅 **{label.capitalize()}**"]
    multi = (end - start).days > 1
    for e in evs:
        lines.append(f"— **{fmt_dt(e.start) if multi else e.start.strftime('%H:%M')}** {'✓ ' if calendar.is_done(e) else ''}{e.title}" + (f" · {e.location}" if e.location else ""))
    for t in due:
        tail = fmt_dt(t.due) if multi else ('' if is_all_day(t.due) else t.due.strftime('%H:%M'))
        lines.append(f"— ✅ {t.title}" + (f" · до {tail}" if tail else ""))
    for p in pays:
        lines.append(f"— 💳 {p.title} {money(p.amount)}" + (f" · {p.next_date:%d.%m}" if multi else ""))
    return "\n".join(lines), ["agenda"]


# ------------------------------------------------------------------ долги: справка, платёж, возврат, закрытие
DEBTS_Q_RX = re.compile(r"^\s*(?:какие|что\s+по|покажи|сколько)\s+(?:у\s+меня\s+)?(?:долг\w*|кредит\w*|я\s+должен|должен)\W*$|^\s*(?:кому|сколько)\s+я\s+(?:должен|должна)\W*$", re.I)
PAY_DEBT_RX = re.compile(r"^\s*(?:заплатил\w*|оплатил\w*|отдал\w*|вернул\w*|погасил\w*|внес\w*|внёс\w*|платеж|платёж)\s+(?:по\s+)?(?:долг\w*\s+)?(.+)$", re.I)
CLOSE_DEBT_RX = re.compile(r"^\s*(?:закрой|закрыл\w*|погаси|погасил\w*|списать|спиши|удали|отдал\s+весь|вернул\s+весь)\s+(?:долг\w*|кредит\w*)\s+(.+?)\s*(?:полностью|целиком|весь)?\s*$", re.I)
GOT_BACK_RX = re.compile(r"^\s*(?:мне\s+)?(?:вернул\w*|отдал\w*)\s+(?:мне\s+)?(?:долг\w*)?\s*(.+)$", re.I)


def debts(text: str, channel: str) -> Result | None:
    low = text.lower().strip(" ?!.")
    if DEBTS_Q_RX.match(low):
        from ..tools import registry
        return registry.list_debts(), ["list_debts"]

    m = CLOSE_DEBT_RX.match(text)
    if m:
        d = finance.find_debt(m.group(1).strip(" .«»\""))
        if not d:
            return f"Долг «{m.group(1).strip()}» не нашёл, сэр. Скажите «долги» — покажу список.", []
        last = d.remaining
        try:
            d = finance.pay_debt(d.id, last, source=channel)
        except finance.FinanceError as e:
            return f"Не вышло: {e}.", []
        return f"Долг «{d.title}» закрыт полностью 🎉 Списал последние {money(last)} как платёж. Свободнее дышится, сэр.", ["pay_debt"]

    # «вернули долг 5000» / «ваня вернул 5000» — это доход (нам вернули), а не наш платёж
    if re.match(r"^\s*(?:мне\s+)?вернул[аи]\b|^\s*[а-яё]+\s+вернул\w*\b(?!\s+долг\s+[а-яё]+у\b)", low) and not re.match(r"^\s*вернул\s+", low):
        amount, rest = parse_amount(text)
        if amount is None:
            return None
        who = re.sub(r"\b(мне|долг\w*|вернул\w*|деньги|обратно|назад)\b", " ", rest, flags=re.I).strip(" ,.-—:") or "возврат"
        tx = finance.add_transaction(amount, "income", "Прочий доход", f"Вернули: {who}", source=channel)
        return f"Плюс {money(tx.amount)} — вернули ({who}). Редкое и приятное событие, сэр.", ["add_income"]

    m = PAY_DEBT_RX.match(text)
    if m:
        body = m.group(1)
        amount, rest = parse_amount(body)
        if amount is None:
            return None
        who = re.sub(r"\b(по|за|долг\w*|кредит\w*|платеж\w*|платёж\w*|часть|ещё|еще)\b", " ", rest, flags=re.I).strip(" ,.-—:")
        d = finance.find_debt(who) if who else None
        if not d and who:
            # «Ване» → долг «Ваня»/«Долг Ване»: пробуем по основе имени
            from ..services.match import stem
            for dd in finance.list_debts():
                if any(stem(w) in dd.title.lower().replace("ё", "е") for w in who.lower().split() if len(w) >= 3):
                    d = dd
                    break
        if not d:
            verb = low.split()[0]
            if not verb.startswith(("вернул", "погасил")) or not who:
                return None   # «заплатил 2000 за интернет», «отдал 500 за парковку» — обычная трата, разберёт EXPENSE_RX
            return (f"Записать {money(amount)} как платёж по долгу — но долга «{who}» у меня нет, сэр. "
                    f"Скажите «долг {who} <сумма>», чтобы завести, или «потратил {int(amount)} {who}», если это просто трата."), []
        try:
            d = finance.pay_debt(d.id, amount, source=channel)
        except finance.FinanceError as e:
            return f"Не записал: {e}.", []
        if d.closed:
            return f"Платёж {money(amount)} по «{d.title}» — и долг закрыт полностью 🎉 Поздравляю, сэр.", ["pay_debt"]
        f = finance.debt_forecast(d)
        tail = f" Закроется через {f['months']} мес." if f.get("months") else ""
        return f"Платёж {money(amount)} по «{d.title}». Остаток **{money(d.remaining)}**.{tail}", ["pay_debt"]
    return None


# ------------------------------------------------------------------ переводы, наличные
TRANSFER_RX = re.compile(r"^\s*(?:перевел\w*|перевёл|перевод|переведи|перекинул\w*|перекинь|закинул\w*|положил\w*|пополнил\w*)\s+(.+)$", re.I)
CASH_RX = re.compile(r"^\s*(?:снял\w*|обналичил\w*|снять)\s+(.+)$", re.I)


def transfers(text: str, channel: str) -> Result | None:
    m = CASH_RX.match(text)
    if m:
        amount, rest = parse_amount(m.group(1))
        if amount is None:
            return None
        src_name = None
        sm = re.search(r"\b(?:с|со|из)\s+([а-яёa-z\- ]+?)(?:\s+нал\w*|\s+в\s+банкомат\w*|$)", rest, re.I)
        if sm:
            src_name = sm.group(1).strip()
        src = finance.find_account(src_name) if src_name else None
        cash = finance.find_account("наличные")
        if not cash:
            cash = finance.add_account("Наличные", "cash", 0)
        try:
            finance.add_transaction(amount, "transfer", None, "Снятие наличных", src.name if src else None, cash.name, source=channel)
        except finance.FinanceError as e:
            return f"Не записал: {e}.", []
        return f"Снятие {money(amount)} → «{cash.name}». Баланс общий не изменился, просто часть теперь шуршит в кармане, сэр.", ["add_transfer"]

    m = TRANSFER_RX.match(text)
    if m:
        body = m.group(1)
        amount, rest = parse_amount(body)
        if amount is None:
            return None
        to_name = src_name = None
        tm = re.search(r"\b(?:на|в|во)\s+([а-яёa-z0-9\- ]+?)(?=\s+(?:с|со|из)\s+|$)", rest, re.I)
        sm = re.search(r"\b(?:с|со|из)\s+([а-яёa-z0-9\- ]+?)(?=\s+(?:на|в|во)\s+|$)", rest, re.I)
        if tm:
            to_name = tm.group(1).strip()
        if sm:
            src_name = sm.group(1).strip()
        if not to_name:
            # «перевёл 5000 маме» / «перевёл Ване 2000» — перевод человеку: это трата (или платёж по долгу, если долг есть)
            who = re.sub(r"\b(руб\w*|р)\b", " ", rest).strip(" ,.-—:")
            if re.match(r"^\s*(переведи|перекинь)\b", text, re.I):
                return (f"Переводить деньги я не умею, сэр, — только вести учёт. Если уже перевели, скажите «перевёл {int(amount)} {who or 'на сбер'}»."), []
            if not who:
                return None
            d = finance.find_debt(who)
            if d:
                try:
                    d = finance.pay_debt(d.id, amount, source=channel)
                except finance.FinanceError as e:
                    return f"Не записал: {e}.", []
                return f"Платёж {money(amount)} по «{d.title}». Остаток **{money(d.remaining)}**." + (" Долг закрыт 🎉" if d.closed else ""), ["pay_debt"]
            tx = finance.add_transaction(amount, "expense", None, f"Перевод: {who}", source=channel)
            return f"Перевод {money(tx.amount)} ({who}) записал как трату · {tx.category}. Если это был долг — скажите «долг {who} …».", ["add_expense"]
        to = finance.find_account(to_name)
        if not to:
            if not re.search(r"\b(сч[её]т|карт|банк|сбер|тинь|т-банк|тбанк|альфа|втб|наличн|кэш|кеш|вклад|копилк|накоп)", to_name, re.I):
                return None   # «переведи 5000 на подарок» — не счёт: ниже разберём как трату
            to = finance.add_account(to_name.title(), "bank", 0)
        src = finance.find_account(src_name) if src_name else None
        if src and src.id == to.id:
            return "Перевод на тот же счёт — деньги устанут, сэр.", []
        try:
            finance.add_transaction(amount, "transfer", None, None, src.name if src else None, to.name, source=channel)
        except finance.FinanceError as e:
            return f"Не записал: {e}.", []
        src_lbl = src.name if src else finance.main_account_name()
        return f"Перевод {money(amount)}: {src_lbl} → {to.name}. Общий баланс тот же, сэр.", ["add_transfer"]
    return None


# ------------------------------------------------------------------ подписки, регулярные, лимиты
SUB_RX = re.compile(r"^\s*(?:подписка|подписку|регулярн\w*|аренда|ежемесячно|каждый\s+месяц|абонемент|платёж|платеж)\s*[:\-—]?\s*(.+)$", re.I)
SUB_CANCEL_RX = re.compile(r"^\s*(?:отмени|отключи|убери|удали|останови|стоп|закрой)\s+(?:подписк\w*|регулярн\w*|платёж|платеж|автоплат\w*)\s*(?:на\s+)?(.*)$", re.I)
LIMIT_RX = re.compile(r"^\s*(?:лимит|бюджет|потолок)\s+(?:на|по|для)?\s*([а-яё]+(?:\s+[а-яё]+)?)\s*[:\-—]?\s*(.+)$", re.I)
LIMIT_OFF_RX = re.compile(r"^\s*(?:убери|сними|отмени|удали)\s+(?:лимит|бюджет)\s+(?:на|по|с)?\s*([а-яё]+(?:\s+[а-яё]+)?)\s*$", re.I)
# «каждый месяц с 5-го плачу 3000 за интернет» → после вырезания даты и «каждый месяц» остаётся
# «с  -го плачу за интернет» — обрывки служебных слов в начале. Раньше такой платёж назывался
# «С -го плачу 3000 за интернет», и в списке регулярных платежей это было нечитаемо.
_REC_NOISE_RX = re.compile(r"^(?:с|со|за|от|для|по|на|и)\b\s*|^(?:плачу|платит|платим|платить|взят|беру|берём|выплач\w*)\b\s*",
                           re.I | re.U)


def _rec_title(rest: str) -> str:
    """Название регулярного платежа: срезать обрывки служебных слов в начале («с … плачу за …» → «интернет»)."""
    t = (rest or "").strip(" ,.-—:")
    for _ in range(4):          # «с плачу за интернет» → «интернет»: три слоя шума
        new = _REC_NOISE_RX.sub("", t, count=1).lstrip(" ,.-—:")
        if new == t:
            break
        t = new
    if not t:
        return ""
    # остался обрывок окончания даты («-го») — отбрасываем, названия из одного огрызка не делаем
    if len(t) <= 3 and not re.search(r"\w{4}", t):
        return ""
    return t[0].upper() + t[1:]


def subscriptions(text: str, channel: str) -> Result | None:
    m = SUB_CANCEL_RX.match(text)
    if m:
        what = m.group(1).strip(" .«»\"")
        if not what:
            return "Какую подписку остановить, сэр? Скажите «подписки» — покажу список.", []
        r = finance.find_recurring(what)
        if not r:
            return f"Регулярного платежа «{what}» не нашёл. «Подписки» — покажу, что есть.", []
        if r.debt_id:
            return f"«{r.title}» — это платёж по долгу. Долги так просто не отменяются, сэр. Скажите «закрой долг …», если он выплачен.", []
        finance.stop_recurring(r.id)
        return f"«{r.title}» ({money(r.amount)}/мес) остановлен. Минус одно тихое списание — плюс {money(r.amount)} в месяц.", ["stop_recurring"]

    m = LIMIT_OFF_RX.match(text)
    if m:
        c = finance.category_by_word(m.group(1))
        if not c:
            return f"Категорию «{m.group(1)}» не знаю, сэр.", []
        finance.update_category(c.id, budget=0)
        return f"Лимит на «{c.name}» снят. Живём без тормозов.", ["set_budget"]

    m = LIMIT_RX.match(text)
    if m:
        amount, _ = parse_amount(m.group(2))
        c = finance.category_by_word(m.group(1))
        if amount is None:
            return None
        if not c:
            return f"Категорию «{m.group(1)}» не знаю, сэр. Есть: " + ", ".join(x.name for x in finance.list_categories("expense")) + ".", []
        finance.update_category(c.id, budget=amount)
        b = next((x for x in finance.budgets() if x["id"] == c.id), None)
        tail = f" В этом месяце уже потрачено {money(b['spent'])}." if b and b["spent"] else ""
        return f"Лимит «{c.name}» — {money(amount)} в месяц. Предупрежу на 80% и при превышении.{tail}", ["set_budget"]

    m = SUB_RX.match(text)
    if m:
        body = m.group(1)
        amount, rest = parse_amount(body)
        if amount is None:
            return None
        day = datetime.now().day
        dm = re.search(r"(\d{1,2})[- ]?(?:го|числа|-е|е\b)", rest)
        if dm:
            day = int(dm.group(1)); rest = rest.replace(dm.group(0), " ")
        kind = "income" if re.search(r"\b(зарплат|зп|доход|аванс|приход)", body, re.I) else "expense"
        title = re.sub(r"\b(каждый|каждое|месяц|в месяц|ежемесячно|раз в месяц|числа|подписка|на)\b", " ", rest, flags=re.I).strip(" ,.-—:")
        title = _rec_title(title)
        if not title:
            return None
        title = title[0].upper() + title[1:]
        r = finance.add_recurring(title, amount, day, kind, None, "monthly")
        return f"Регулярный {'доход' if kind == 'income' else 'платёж'} «{r.title}» — {money(r.amount)} каждое {r.day}-е ({r.category}). Ближайшее {r.next_date:%d.%m}. Спишу автоматически, сэр.", ["add_recurring"]
    return None


# ------------------------------------------------------------------ баланс счёта / сколько на счёте
BAL_Q_RX = re.compile(r"^\s*(?:сколько\s+(?:у\s+меня\s+)?(?:денег\s+)?(?:на|в)|баланс|что\s+на|остаток\s+(?:на|по))\s+(?:сч[её]те\s+|карте\s+|счёту\s+)?([а-яёa-z\- ]+?)\W*$", re.I)


def balance_q(text: str) -> Result | None:
    low = text.lower().strip(" ?!.")
    if re.match(r"^сколько\s+(у\s+меня\s+)?денег\W*$|^баланс\W*$", low):
        s = finance.summary(1)
        accs = ", ".join(f"{a['name']} {money(a['balance'])}" for a in s["accounts"] if a["balance"] or a["is_main"])
        return f"Всего **{money(s['total_balance'])}** ({accs}). Безопасно тратить ~{money(s['safe']['per_day'])} в день, сэр.", ["balance"]
    m = BAL_Q_RX.match(low)
    if not m:
        return None
    a = finance.find_account(m.group(1))
    if not a:
        return None
    return f"На «{a.name}» — **{money(a.balance)}**.", ["balance"]


# ------------------------------------------------------------------ режим жизни
# «я уезжаю в армию 28 октября», «с 28 октября в армии», «уехал в командировку до 5 ноября»,
# «больничный с 3 по 10», «вернулся», «армия закончилась», «поменяй режим на …», «удали режим».
# Всё офлайн и без LLM. Перед записью — вопрос «да/нет» (как у других записей в чате);
# пока не сказано «да», ничего не пишется. Подтверждение живёт в отдельной настройке
# `regime_pending:<канал>` и 5 минут, после чего забывается.
_PENDING_KEY = "regime_pending:{ch}"

# Название режима берём из узнаваемых слов; если такого нет — саму фразу (обрезанную).
# `\b` в начале обязателен: без него «развлечения» попадало в «лечени\w*».
_REGIME_WORDS = (
    ("армия", r"\b(?:арм\w*|служб\w*|воинск\w*)|в\s+части"),
    ("командировка", r"\bкомандировк\w*"),
    ("больничный", r"\bбольнич\w*"),
    ("учёба", r"\bуч[её]б\w*|\bобучени\w*|\bучит\w*"),
    ("отпуск", r"\bотпуск\w*|\bотдых\w*|\bотдохн\w*"),
    ("декрет", r"\bдекрет\w*"),
    ("сессия", r"\bсесси\w*"),
    ("лечение", r"\bлеч\w*|\bоздоровлени\w*|\bреабилитац\w*"),
    ("пропускной", r"\bпропускн\w*"),
    ("вакансия", r"\bваканс\w*|\bмежсезонь\w*"),
)
_REGIME_ANY_RX = re.compile("|".join(rx for _t, rx in _REGIME_WORDS), re.I)
# Сильные глаголы: сами по себе (или с датой) означают «начался режим» —
# «уезжаю 28 октября», «начал учиться».
_REGIME_GO_RX = re.compile(r"(?:уезжаю|уехал|уезжал|уезжаем|уезжали|уеду|уезжает|поеду|поехал|поехали|улетаю|улетел|улетает|"
                           r"летим|улечу|начал[аио]?|начну|начинаю|завожу|зав[её]л|завела|пош[её]л|пошла|"
                           r"уш[её]л|ушла)\b", re.I)
# Слабые глаголы («иду», «работаю») — только вместе со словом режима: «иду на др 12 числа»
# это день рождения, а не режим.
_REGIME_MAYBE_RX = re.compile(r"(?:\bиду\b|\bид[её]шь\b|\bнахожусь\b|\bработаю\b|\bслужу\b|\bустроил\w*)\b", re.I)
# Фразы про календарь/задачи/дни рождения — режимом жизни быть не могут.
_NOT_REGIME_RX = re.compile(r"\b(?:событи\w*|календар\w*|встреч\w*|напомн\w*|задач\w*|др\b|днюх\w*|"
                            r"день\s+рождени\w*|билет\w*|подписк\w*|долг\w*|кредит\w*)\b", re.I)
_REGIME_DEL_RX = re.compile(r"^\s*(?:удали|убери|сотри|забудь|удали-ка)\s+(?:жизненный\s+)?режим\w*\s*$", re.I)
_REGIME_SET_RX = re.compile(r"^\s*(?:поменяй|смени|замени|переименуй|установи)\s+(?:жизненный\s+)?режим\s+на\s+(.+?)\s*$", re.I)
_REGIME_APPLY_RX = re.compile(r"^\s*(?:не\s+)?счита[йе]\w*\s+по\s+режиму\s*(вкл(?:юч\w*)?|выкл(?:юч\w*)?|отключ\w*)?\s*[.!]*$", re.I)
_REGIME_BACK_RX = re.compile(r"^\s*(?:(?:я\s+)?(?:вернулся|вернулась|вернулись|вернулось|уже\s+вернулся|вернулся\s+домой)"
                            r"(?:\s+.+?)?|(?:[\wё]+)\s+(?:закончил\w*|закончилась|закончилось|окончил\w*|завершил\w*))\s*$", re.I)
_REGIME_YES_RX = re.compile(r"^\s*(да|давай|ага|угу|подтверждаю|конечно|точно|yes|ок|окей|делай|вот|всё|все)\s*[.!]*\s*$", re.I)
_REGIME_NO_RX = re.compile(r"^\s*(нет|не надо|отмена|отбой|стоп|неа|передумал|оставь|no)\s*[.!]*\s*$", re.I)
# дата названа прямо («28 октября», «сегодня») — иначе фразу про режим не разбираем
_DATE_HINT_RX = re.compile(r"\d|сегодня|завтра|послезавтра|понедельник|вторник|сред[ау]|четверг|пятниц|суббот|воскресень|"
                          r"январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр", re.I)


def _pending_get(channel: str) -> tuple[str, datetime] | None:
    raw = get_setting(_PENDING_KEY.format(ch=channel)) or ""
    if "|" not in raw:
        return None
    ts, payload = raw.split("|", 1)
    try:
        return payload, datetime.fromisoformat(ts)
    except ValueError:
        return None


def _pending_set(channel: str, payload: str) -> None:
    set_setting(_PENDING_KEY.format(ch=channel), f"{datetime.now().isoformat()}|{payload}")


def _pending_clear(channel: str) -> None:
    set_setting(_PENDING_KEY.format(ch=channel), "")


_MONTHS_RU = ("янв", "фев", "мар", "апр", "ма", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
_MONTH_DAY_RX = re.compile(r"\b(\d{1,2})\s*(янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек)\w*", re.I)


def _dom(d: int, mon: str | None = None) -> datetime | None:
    """«28 октября» / «с 3» → начало дня. Месяц — ЭТОГО года: в режиме жизни «1 мая» значит
    «1 мая этого года» (человек описывает период, в котором жил), а не «следующей весны».
    День ограничен 28-м, чтобы «с 30» не уехало в короткий месяц."""
    now = datetime.now()
    if mon:
        low = mon.lower().replace("ё", "е")[:3]
        idx = next((i + 1 for i, x in enumerate(_MONTHS_RU) if low.startswith(x)), 0)
        if not idx:
            return None
        return now.replace(month=idx, day=min(max(1, int(d)), 28), hour=0, minute=0, second=0, microsecond=0)
    return now.replace(day=min(max(1, int(d)), 28), hour=0, minute=0, second=0, microsecond=0)


def _date_from(frag: str) -> datetime | None:
    """Дата из куска фразы режима: «28 октября», «28.10», «28.10.2026», «завтра», «в пятницу»."""
    m = _MONTH_DAY_RX.search(frag or "")
    if m:
        return _dom(int(m.group(1)), m.group(2))
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", frag or "")
    if m:
        y = int(m.group(3) or datetime.now().year)
        y = y + 2000 if y < 100 else y
        try:
            return datetime(y, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    dt = parse_datetime(frag or "")[0]
    return dt.replace(hour=0, minute=0, second=0, microsecond=0) if dt else None


def _regime_dates(text: str) -> tuple[datetime | None, datetime | None, str]:
    """(начало, конец, текст без дат) из «с 28 октября», «до 5 ноября», «с 3 по 10»."""
    rest = text
    start = end = None
    m = re.search(r"\b(?:с\s+)?(\d{1,2})\s*(?:по|-|–|—)\s*(\d{1,2})\b(?:\s*([а-яё]{3,12}))?", rest, re.I)
    if m:   # «больничный с 3 по 10» — оба числа в одном месяце
        start, end = _dom(int(m.group(1)), m.group(3)), _dom(int(m.group(2)), m.group(3))
        if start and end and end < start:   # «с 28 по 3» — конец в следующем месяце
            try:
                end = end.replace(year=end.year + 1, month=1) if end.month == 12 else end.replace(month=end.month + 1)
            except ValueError:
                end = None
        return start, end, rest[:m.start()] + " " + rest[m.end():]
    m = re.search(r"\bдо\b\s*(.+)$", rest, re.I)     # «до 5 ноября» — конец режима
    if m:
        end = _date_from(m.group(1))
        if end:
            rest = rest[:m.start()]
    m = re.search(r"\b(?:с|начиная)\b\s*(.+)$", rest, re.I)   # «с 28 октября» — начало
    if m:
        dt = _date_from(m.group(1))
        if dt:
            start = dt
            rest = rest[:m.start()]
    if end is None:                                  # «1 мая по 10 мая» / «с 28 октября по 5 ноября»
        m = re.search(r"\bпо\s+([^,]{2,30})$", rest, re.I)
        if m and re.search(r"\d", m.group(1)):
            end = _date_from(m.group(1))
            if end:
                rest = rest[:m.start()]
    if start is None and _DATE_HINT_RX.search(rest):
        dt = _date_from(rest)     # «я уезжаю в армию 28 октября» — дата без предлога
        if dt:
            start = dt
    return start, end, rest


def _regime_title(text: str) -> str:
    """Название режима: узнаваемое слово («армия», «больничный») или сама фраза, обрезанная."""
    for title, rx in _REGIME_WORDS:
        if re.search(rx, text, re.I):
            return title
    t = re.sub(r"^\s*(?:я\s+)?(?:уезжаю|уехал|уеду|уезжал|уезжаем|уезжали|поеду|поехал|улетаю|улетел|улетает|"
               r"летим|начал[аио]?|начну|начинаю|завожу|зав[её]л|завела|иду|ид[её]шь|пош[её]л|пошла|"
               r"уш[её]л|ушла|нахожусь|работаю|служу|устроился|устроилась|начался|началась)\b", " ", text, flags=re.I)
    t = re.sub(r"\b(?:в|на|до|с|по)\b", " ", t, flags=re.I)
    t = " ".join(t.split(" ,.-—:?!"))
    return (t[:60] or "новый режим").strip().lower()


def _regime_confirm(text: str, channel: str) -> Result | None:
    """Ответ на «да/нет» по отложенному режиму (своя настройка — чужие pending не трогаем)."""
    p = _pending_get(channel)
    if not p:
        return None
    payload, ts = p
    if (datetime.now() - ts).total_seconds() > regime.PENDING_TTL_SEC:
        _pending_clear(channel)
        return None
    if _REGIME_YES_RX.match(text):
        _pending_clear(channel)
        return _regime_apply(payload, channel)
    if _REGIME_NO_RX.match(text):
        _pending_clear(channel)
        return "Отбой, режим не трогаю — цифры считаю как раньше.", []
    _pending_clear(channel)   # заговорили о другом — вопрос снимается
    return None


def _regime_apply(payload: str, channel: str) -> Result | None:
    """Собственно запись из подтверждения. payload — json: {op, …}."""
    try:
        d = json.loads(payload)
    except json.JSONDecodeError:
        return None
    op = d.get("op")
    try:
        if op == "add":
            r = regime.add(d["title"], d.get("start"), d.get("end"), d.get("note") or "", channel)
            regime.set_apply(True)      # режим завели — сразу включаем влияние на цифры
            when = f"с {r['from_short']}" if r.get("from_short") else "с сегодня"
            if r.get("to_short"):
                when = f"с {r['from_short']} по {r['to_short']}"
            return (f"Завёл режим **{r['title']}** {when}. Теперь средние и прогноз считаю по нему, "
                    f"а не по всей истории — пока не закроете режим или не выключите переключатель.", ["set_regime"])
        if op == "close":
            cur = regime.active()
            r = regime.close(cur["id"], d.get("when"), channel) if cur else None
            if not r:
                return "Открытого режима нет, сэр — считаю как раньше.", []
            return (f"Режим **{r['title']}** закрыт {r['to_short']}. Средние теперь считаются по его периоду "
                    f"({r['from_short']}–{r['to_short']}) — можно завести новый режим или выключить влияние.", ["set_regime"])
        if op == "rename":
            cur = regime.active()
            if cur:
                r = regime.update(cur["id"], title=d["title"])
                return f"Переименовал режим: теперь он «{r['title']}». Средние считаются по нему.", ["set_regime"]
            r = regime.add(d["title"], None, None, "", channel)
            regime.set_apply(True)
            return f"Завёл режим **{r['title']}** с {r['from_short']} и включил подсчёт по нему.", ["set_regime"]
        if op == "delete":
            cur = regime.active()
            if cur and not regime.delete(cur["id"], channel):
                return "Не нашёл, что удалять.", []
            regime.set_apply(False)
            return "Режим удалён, считаю по всем данным как раньше.", ["set_regime"]
    except regime.RegimeError as e:
        return f"Не записал: {e}.", []
    return None


def regimes(text: str, channel: str) -> Result | None:
    """Фразы о режиме жизни: завести/закрыть/переименовать/удалить/включить-выключить."""
    t = text.strip(" .?!,")
    if not t:
        return None

    if _REGIME_DEL_RX.match(t):
        cur = regime.active()
        if not cur:
            return "Удалять нечего: открытого режима нет, сэр.", []
        _pending_set(channel, json.dumps({"op": "delete"}, ensure_ascii=False))
        return f"Удалить режим **{cur['title']}** (с {cur['from_short']})? Цифры вернутся к общим. — да/нет", ["clarify"]

    if _REGIME_APPLY_RX.match(t):
        off = bool(re.search(r"\bне\b|выкл|отключ", t, re.I))
        regime.set_apply(not off)
        cur = regime.current()
        if off:
            return "Выключил: считаю по всем данным, сэр. Режим в истории останется.", ["set_regime"]
        if not cur:
            return ("Включил, но режима пока нет — цифры считаю как раньше. "
                    "Скажите «я уезжаю в армию 28 октября», и заведу."), ["set_regime"]
        return f"Включил: {regime.label(cur)} — пока режим не закроете, цифры будут по нему.", ["set_regime"]

    m = _REGIME_SET_RX.match(t)
    if m:
        raw = m.group(1).strip(" .«»\"")
        if not raw:
            return "На что поменять режим, сэр? Например: «поменяй режим на командировку».", []
        # «на командировку» → каноническое «командировка»; своё название оставляем как сказали
        title = next((canon for canon, rx in _REGIME_WORDS if re.search(rx, raw, re.I)), raw[:60])
        _pending_set(channel, json.dumps({"op": "rename", "title": title}, ensure_ascii=False))
        cur = regime.active()
        tail = f" (сейчас он «{cur['title']}»)" if cur else " (режима ещё нет — заведу новый)"
        return f"Поменять режим на **{title}**{tail}? — да/нет", ["clarify"]

    if _NOT_REGIME_RX.search(t):
        return None   # календарь, задачи, дни рождения, подписки, долги — это не режим жизни

    if _REGIME_BACK_RX.match(t) and not re.search(r"вернул\w*\s+долг", t, re.I) \
            and (re.search(r"вернул", t, re.I) or _REGIME_ANY_RX.search(t)):
        cur = regime.active()
        if not cur:
            return "Открытого режима нет, сэр — считаю как раньше.", []
        when, _end, _rest = _regime_dates(t)
        _pending_set(channel, json.dumps({"op": "close", "when": when.isoformat() if when else None}, ensure_ascii=False))
        dd = f" {when:%d.%m}" if when else " сегодня"
        return f"Закрыть режим **{cur['title']}**{dd}? Средние будут считаться по его периоду. — да/нет", ["clarify"]

# ---- завести новый режим: нужно либо узнаваемое слово режима, либо дата рядом с глаголом
    start, end, rest = _regime_dates(t)
    has_word = bool(_REGIME_ANY_RX.search(t))
    has_go = bool(_REGIME_GO_RX.search(t)) or (has_word and bool(_REGIME_MAYBE_RX.search(t)))
    if not has_word and not (has_go and (start or end)):
        return None
    title = _regime_title(rest or t)
    if not title or (title == "новый режим" and not (start or end)):
        return None
    _pending_set(channel, json.dumps({"op": "add", "title": title,
                                      "start": start.date().isoformat() if start else None,
                                      "end": end.date().isoformat() if end else None}, ensure_ascii=False))
    when = f"с {start:%d.%m.%Y}" if start else "с сегодня"
    tail = f" по {end:%d.%m.%Y}. — да/нет" if end else ", до? — да/нет"
    return f"Заведу режим **{title}** {when}{tail}", ["clarify"]


# ------------------------------------------------------------------ вход
def run(text: str, channel: str) -> Result | None:
    t = text.strip()
    if not t or len(t) > 200:
        return None
    r = _regime_confirm(t, channel)   # «да/нет» по отложенному режиму
    if r:
        return r
    r = regimes(t, channel)
    if r:
        return r
    for fn in (smalltalk, balance_q, spent, agenda):
        r = fn(t)
        if r:
            return r
    for fn in (debts, transfers, subscriptions):
        r = fn(t, channel)
        if r:
            return r
    return None
