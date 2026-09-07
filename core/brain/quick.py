"""Быстрые правила без LLM: справки («сколько потратил на еду за неделю», «что у меня завтра», «какие долги»),
деньги («переведи 5000 на сбер», «снял 3000 наличных», «заплатил Диме 2000», «вернули долг 5000», «закрой долг Диме»,
«подписка яндекс плюс 399 25-го», «лимит на еду 20000», «отмени подписку яндекс») и короткие реплики («спасибо», «ок»).

Всё работает мгновенно и офлайн — это то, что «настоящий ассистент» обязан понимать даже когда мозг спит.
Каждая функция возвращает (text, actions) или None.
"""
from __future__ import annotations

import random
import re

from .. import identity
from datetime import datetime, timedelta

from ..services import calendar, finance, tasks
from ..services.calendar import fmt_dt
from ..services.finance import money
from .dates import parse_amount, parse_datetime

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


def smalltalk(text: str) -> Result | None:
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
        return d0 - timedelta(days=n - 1), None, f"за {n} дн."
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
AGENDA_RX = re.compile(r"^\s*(?:что|чё|че|какие\s+(?:планы|дела|встречи|события))\s*(?:у\s+меня|по\s+плану|запланировано|в\s+планах|планы)?\s*(?:на|в|во)?\s*(.+?)\s*\??$", re.I)


def agenda(text: str) -> Result | None:
    low = text.lower().strip(" ?!.")
    if not re.match(r"^(что|чё|че|какие)\b", low):
        return None
    if re.search(r"\b(потратил|ушло|доход|заработал|долг|баланс|денег|такое|значит|делать|нового|умеешь|делаешь)\b", low):
        return None
    m = AGENDA_RX.match(low)
    if not m:
        return None
    when = m.group(1)
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
        lines.append(f"— **{fmt_dt(e.start) if multi else e.start.strftime('%H:%M')}** {e.title}" + (f" · {e.location}" if e.location else ""))
    for t in due:
        lines.append(f"— ✅ {t.title} · до {fmt_dt(t.due) if multi else t.due.strftime('%H:%M')}")
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


# ------------------------------------------------------------------ вход
def run(text: str, channel: str) -> Result | None:
    t = text.strip()
    if not t or len(t) > 200:
        return None
    for fn in (smalltalk, balance_q, spent, agenda):
        r = fn(t)
        if r:
            return r
    for fn in (debts, transfers, subscriptions):
        r = fn(t, channel)
        if r:
            return r
    return None
