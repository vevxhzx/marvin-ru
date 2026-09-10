"""Инструменты, которые может вызывать мозг (LLM) — с описанием для function calling."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Callable

from ..brain.dates import parse_datetime
from ..services import brain_notes, calendar, finance, tasks
from ..services.calendar import fmt_dt
from ..services.finance import money

TOOLS: dict[str, dict[str, Any]] = {}
FUNCS: dict[str, Callable] = {}


def tool(name: str, description: str, params: dict[str, Any], required: list[str] | None = None):
    def deco(fn: Callable):
        TOOLS[name] = {
            "type": "function",
            "function": {"name": name, "description": description,
                         "parameters": {"type": "object", "properties": params, "required": required or []}},
        }
        FUNCS[name] = fn
        return fn
    return deco


def _dt(value: str | None) -> datetime | None:
    """ISO-строка или русская фраза → datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        dt, _ = parse_datetime(value)
        return dt


# ---------------- Календарь ----------------
@tool("add_event", "Добавить встречу/событие в календарь. Для повторяющихся укажи repeat.",
      {"title": {"type": "string", "description": "Название события"},
       "start": {"type": "string", "description": "Дата и время начала в ISO 8601 (YYYY-MM-DDTHH:MM)"},
       "duration_min": {"type": "integer", "description": "Длительность в минутах, по умолчанию 60"},
       "location": {"type": "string"},
       "repeat": {"type": "string", "description": "Повтор: daily, weekly, monthly, yearly или пусто"},
       "repeat_days": {"type": "array", "items": {"type": "integer"}, "description": "Для weekly: дни недели 0=пн … 6=вс"}}, ["title", "start"])
def add_event(title: str, start: str, duration_min: int = 60, location: str | None = None, repeat: str = "",
              repeat_days: list[int] | None = None, _channel: str = "tg") -> str:
    dt = _dt(start)
    if not dt:
        return "Не понял дату/время."
    ev = calendar.add_event(title, dt, duration_min or 60, location, source=_channel, repeat=repeat or "", repeat_days=repeat_days)
    rep = f", {calendar.fmt_repeat(ev)}" if ev.repeat else ""
    return f"Событие #{ev.id} «{ev.title}» добавлено: {fmt_dt(ev.start)}{rep}"


@tool("move_event", "Перенести событие на другое время или переименовать.",
      {"query": {"type": "string", "description": "id или часть названия события"},
       "start": {"type": "string", "description": "Новое время ISO 8601 (необязательно)"},
       "title": {"type": "string", "description": "Новое название (необязательно)"}}, ["query"])
def move_event(query: str, start: str | None = None, title: str | None = None, **_) -> str:
    ev = calendar.find_event(query)
    if not ev:
        return "Не нашёл такое событие."
    dt = _dt(start) if start else None
    ev = calendar.update_event(ev.id, start=dt, title=title)
    return f"Готово: «{ev.title}» — {fmt_dt(ev.start)}"


@tool("undo_last", "Отменить последнее действие (событие, задачу, трату, заметку — что угодно).", {})
def undo_last(**_) -> str:
    from ..services import undo
    return undo.undo_last() or "Отменять нечего."


@tool("list_events", "Показать события календаря за период.",
      {"days": {"type": "integer", "description": "На сколько дней вперёд (по умолчанию 7)"}})
def list_events(days: int = 7, **_) -> str:
    start = datetime.now().replace(hour=0, minute=0, second=0)
    evs = calendar.list_events(start, start + timedelta(days=days or 7))
    if not evs:
        return "Событий нет."
    return f"📅 **Ближайшие {days or 7} дн.**\n" + "\n".join(f"— **{fmt_dt(e.start)}** {e.title}" + (f" · {e.location}" if e.location else "") for e in evs)


@tool("delete_event", "Удалить/отменить событие по id или названию.",
      {"query": {"type": "string", "description": "id или часть названия"}}, ["query"])
def delete_event(query: str, **_) -> str:
    if str(query).isdigit():
        return "Отменено." if calendar.delete_event(int(query)) else "Не нашёл такое событие."
    found = calendar.find_events(query)
    if not found:
        return "Не нашёл такое событие."
    calendar.delete_event(found[0].id)
    return f"Отменено: «{found[0].title}» {fmt_dt(found[0].start)}"


# ---------------- Задачи ----------------
@tool("add_task", "Добавить задачу в список дел.",
      {"title": {"type": "string"}, "due": {"type": "string", "description": "Дедлайн ISO 8601 (необязательно)"},
       "priority": {"type": "integer", "description": "1 высокий, 2 обычный, 3 низкий"}}, ["title"])
def add_task(title: str, due: str | None = None, priority: int = 2, _channel: str = "tg") -> str:
    t = tasks.add_task(title, _dt(due), priority or 2, source=_channel)
    return f"Задача #{t.id} «{t.title}» добавлена" + (f", дедлайн {fmt_dt(t.due)}" if t.due else "")


@tool("list_tasks", "Показать открытые задачи.", {})
def list_tasks(**_) -> str:
    ts = tasks.list_tasks()
    if not ts:
        return "Открытых задач нет."
    pr = {1: "‼️ ", 2: "", 3: ""}
    head = f"✅ **Задачи** · {len(ts)}"
    return head + "\n" + "\n".join(f"— {pr.get(t.priority, '')}{t.title}" + (f" · до **{fmt_dt(t.due)}**" if t.due else "") for t in ts)


@tool("complete_task", "Отметить задачу выполненной по id или названию.",
      {"query": {"type": "string"}}, ["query"])
def complete_task(query: str, **_) -> str:
    t = tasks.complete_task(query)
    return f"Выполнено: «{t.title}»" if t else "Не нашёл такую задачу."


# ---------------- Финансы ----------------
@tool("add_expense", "Записать трату (расход денег).",
      {"amount": {"type": "number"}, "note": {"type": "string", "description": "На что потрачено"},
       "category": {"type": "string", "description": "Категория (необязательно, определится сама)"},
       "account": {"type": "string", "description": "Счёт (необязательно)"}}, ["amount"])
def add_expense(amount: float, note: str | None = None, category: str | None = None, account: str | None = None, _channel: str = "tg") -> str:
    t = finance.add_transaction(amount, "expense", category, note, account, source=_channel)
    s = finance.summary(1)
    return f"Трата {money(t.amount)} · {t.category} записана. Баланс {money(s['total_balance'])}"


@tool("add_income", "Записать доход (поступление денег).",
      {"amount": {"type": "number"}, "note": {"type": "string"}, "category": {"type": "string"},
       "account": {"type": "string"}}, ["amount"])
def add_income(amount: float, note: str | None = None, category: str | None = None, account: str | None = None, _channel: str = "tg") -> str:
    t = finance.add_transaction(amount, "income", category, note, account, source=_channel)
    s = finance.summary(1)
    return f"Доход {money(t.amount)} · {t.category} записан. Баланс {money(s['total_balance'])}"


@tool("finance_summary", "Сводка по финансам: баланс, траты за период, категории, долги.",
      {"days": {"type": "integer", "description": "Период в днях (по умолчанию 30)"}})
def finance_summary(days: int = 30, **_) -> str:
    s = finance.summary(days or 30)
    lines = [f"💰 **Баланс {money(s['total_balance'])}**",
             f"За {s['days']} дн.: −**{money(s['spent'])}** · +**{money(s['earned'])}**"]
    if s["by_category"]:
        lines.append("")
        lines.append("**Куда ушло**")
        lines += [f"— {k} · {money(v)}" for k, v in list(s["by_category"].items())[:6]]
    tail = []
    if s["debts_total"]:
        tail.append(f"долги **{money(s['debts_total'])}** ({money(s['monthly_debt_payments'])}/мес)")
    if s["recurring_monthly"]:
        tail.append(f"регулярные **{money(s['recurring_monthly'])}**/мес")
    if tail:
        lines.append("")
        lines.append("Обязательства: " + ", ".join(tail))
    return "\n".join(lines)


@tool("spent", "Сколько потрачено (или заработано) за период и/или по категории. Используй для вопросов «сколько ушло на еду за неделю».",
      {"category": {"type": "string", "description": "Категория или слово из неё (еда, такси…), пусто — все"},
       "days": {"type": "integer", "description": "За сколько последних дней (по умолчанию с начала месяца)"},
       "kind": {"type": "string", "enum": ["expense", "income"]}})
def spent(category: str | None = None, days: int | None = None, kind: str = "expense", **_) -> str:
    now = datetime.now()
    since = now - timedelta(days=days) if days else now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    label = f"за {days} дн." if days else "с начала месяца"
    cat = finance.category_by_word(category, kind) if category else None
    if kind == "income":
        txs = [t for t in finance.list_transactions(400, 100_000) if t.kind == "income" and t.date >= since and (not cat or t.category == cat.name)]
        return f"Доход {label}" + (f" ({cat.name})" if cat else "") + f": {money(sum(t.amount for t in txs))}, операций {len(txs)}"
    r = finance.spent_by(cat.name if cat else None, since=since)
    if cat:
        return f"«{cat.name}» {label}: {money(r['total'])}, операций {r['count']}" + (f", лимит {money(cat.budget)}" if cat.budget else "")
    top = ", ".join(f"{k} {money(v)}" for k, v in list(r["by_category"].items())[:6])
    return f"Траты {label}: {money(r['total'])}" + (f" — {top}" if top else "")


@tool("transfer", "Перевод между своими счетами или снятие наличных (to_account = Наличные).",
      {"amount": {"type": "number"}, "to_account": {"type": "string"}, "from_account": {"type": "string"}}, ["amount", "to_account"])
def transfer(amount: float, to_account: str, from_account: str | None = None, _channel: str = "tg") -> str:
    to = finance.find_account(to_account)
    if not to:
        return f"Счёта «{to_account}» нет. Есть: " + ", ".join(a.name for a in finance.list_accounts())
    src = finance.find_account(from_account) if from_account else None
    try:
        finance.add_transaction(amount, "transfer", None, None, src.name if src else None, to.name, source=_channel)
    except finance.FinanceError as e:
        return f"Не получилось: {e}."
    return f"Перевод {money(amount)} → {to.name} записан"


@tool("agenda", "Что запланировано на конкретный день или период: события, дедлайны задач, платежи.",
      {"date": {"type": "string", "description": "Дата YYYY-MM-DD или слово: сегодня/завтра/пятница"},
       "days": {"type": "integer", "description": "Сколько дней показать начиная с date (по умолчанию 1)"}}, ["date"])
def agenda(date: str, days: int = 1, **_) -> str:
    start = _dt(date)
    if not start:
        return "Не понял дату."
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=max(1, days or 1))
    evs = calendar.list_events(start, end, limit=50)
    due = [t for t in tasks.list_tasks(limit=200) if t.due and start <= t.due < end]
    pays = [r for r in finance.list_recurring() if start <= r.next_date < end]
    if not evs and not due and not pays:
        return f"{start:%d.%m}: ничего не запланировано"
    out = [f"{fmt_dt(e.start)} — {e.title}" for e in evs] + [f"задача «{t.title}» до {fmt_dt(t.due)}" for t in due] + \
          [f"платёж {p.title} {money(p.amount)} {p.next_date:%d.%m}" for p in pays]
    return "; ".join(out)


@tool("stop_recurring", "Остановить подписку / регулярный платёж по названию.", {"query": {"type": "string"}}, ["query"])
def stop_recurring(query: str, **_) -> str:
    r = finance.find_recurring(query)
    if not r:
        return f"Регулярного платежа «{query}» нет"
    if r.debt_id:
        return f"«{r.title}» — платёж по долгу, его нельзя просто отключить"
    finance.stop_recurring(r.id)
    return f"«{r.title}» ({money(r.amount)}/мес) остановлен"


@tool("set_budget", "Установить месячный лимит на категорию трат (0 — снять лимит).",
      {"category": {"type": "string"}, "amount": {"type": "number"}}, ["category", "amount"])
def set_budget(category: str, amount: float, **_) -> str:
    c = finance.category_by_word(category)
    if not c:
        return f"Категории «{category}» нет. Есть: " + ", ".join(x.name for x in finance.list_categories("expense"))
    finance.update_category(c.id, budget=amount)
    return f"Лимит «{c.name}»: {money(amount)} в месяц" if amount else f"Лимит «{c.name}» снят"


@tool("set_balance", "Установить точный баланс счёта (например после сверки с банком).",
      {"account": {"type": "string"}, "balance": {"type": "number"}}, ["account", "balance"])
def set_balance(account: str, balance: float, **_) -> str:
    a = finance.set_balance(account, balance)
    return f"Баланс «{a.name}»: {money(a.balance)}"


@tool("add_debt", "Добавить долг или кредит.",
      {"title": {"type": "string", "description": "Название: 'Сбер кредит', 'долг Ване'"},
       "total": {"type": "number", "description": "Сумма долга"},
       "payment": {"type": "number", "description": "Ежемесячный платёж"},
       "pay_day": {"type": "integer", "description": "День месяца платежа"},
       "rate": {"type": "number", "description": "Годовая ставка %, если известна"}}, ["title", "total"])
def add_debt(title: str, total: float, payment: float = 0, pay_day: int = 1, rate: float = 0, **_) -> str:
    d = finance.add_debt(title, total, payment, rate, pay_day)
    f = finance.debt_forecast(d)
    txt = f"Долг «{d.title}» {money(d.remaining)} добавлен."
    if f["months"]:
        txt += f" При платеже {money(d.payment)} закроется через {f['months']} мес. ({f['close_date']})."
    return txt


@tool("pay_debt", "Внести платёж по долгу.",
      {"debt": {"type": "string", "description": "название или id долга"}, "amount": {"type": "number"}}, ["debt", "amount"])
def pay_debt(debt: str, amount: float, _channel: str = "tg") -> str:
    try:
        d = finance.pay_debt(debt, amount, source=_channel)
    except finance.FinanceError as e:
        return f"Не получилось: {e}."
    if not d:
        return "Не нашёл такой долг."
    return f"Платёж {money(amount)} по «{d.title}». Остаток {money(d.remaining)}" + (" — закрыт 🎉" if d.closed else "")


@tool("list_debts", "Показать долги и прогноз закрытия.", {})
def list_debts(**_) -> str:
    ds = finance.list_debts()
    if not ds:
        return "Долгов нет. Свободный человек."
    out = [f"💳 **Долги** · {money(sum(d.remaining for d in ds))}"]
    for d in ds:
        f = finance.debt_forecast(d)
        line = f"— {d.title}: **{money(d.remaining)}** из {money(d.total)}"
        if f["months"]:
            line += f" · закроется через {f['months']} мес. ({f['close_date']})"
        out.append(line)
    return "\n".join(out)


@tool("add_recurring", "Добавить регулярный платёж (подписка, аренда).",
      {"title": {"type": "string"}, "amount": {"type": "number"}, "day": {"type": "integer", "description": "День месяца"}},
      ["title", "amount"])
def add_recurring(title: str, amount: float, day: int = 1, **_) -> str:
    r = finance.add_recurring(title, amount, day or 1)
    return f"Регулярный платёж «{r.title}» {money(r.amount)} каждое {r.day}-е. Следующий: {r.next_date.strftime('%d.%m')}"


# ---------------- Второй мозг ----------------
@tool("add_note", "Сохранить мысль, идею, наблюдение, план или факт во «второй мозг». Вызывай, когда пользователь чем-то делится, а не спрашивает. Текст передавай как есть — редактор приведёт его в порядок сам.",
      {"text": {"type": "string", "description": "Текст заметки дословно"}, "tags": {"type": "array", "items": {"type": "string"}}}, ["text"])
def add_note(text: str, tags: list[str] | None = None, _channel: str = "tg") -> str:
    n = brain_notes.add_note(text, tags, source=_channel)
    return f"Заметка #{n.id} сохранена."


@tool("search_notes", "Найти заметки/ссылки/события в памяти по слову.", {"query": {"type": "string"}}, ["query"])
def search_notes(query: str, **_) -> str:
    notes = brain_notes.list_notes(10, query)
    links = brain_notes.list_links(10, query)
    mem = brain_notes.search_memory(query, 10)
    out = [f"📝 {n.created_at:%d.%m} {n.text[:100]}" for n in notes]
    out += [f"🔗 {l.created_at:%d.%m} {l.title or l.url}" for l in links]
    out += [f"🧠 {m.created_at:%d.%m} {m.text[:100]}" for m in mem]
    return "\n".join(out[:15]) or "Ничего не нашёл."


@tool("today_briefing", "Что сегодня: события, задачи, платежи, баланс.", {})
def today_briefing(**_) -> str:
    evs = calendar.events_today()
    ts = tasks.list_tasks(limit=10)
    pays = finance.upcoming_payments(3)
    s = finance.summary(1)
    now = datetime.now()
    lines = [f"**{_DAYS_RU[now.weekday()]}, {now.day} {_MONTHS_RU[now.month - 1]}**", ""]
    if evs:
        lines.append("📅 **Сегодня**")
        lines += [f"— **{e.start:%H:%M}** {e.title}" + (f" · {e.location}" if e.location else "") for e in evs]
    else:
        lines.append("📅 Встреч нет — день ваш.")
    lines.append("")
    if ts:
        lines.append(f"✅ **Задачи** · {len(ts)}")
        lines += [f"— {t.title}" + (f" · до **{t.due:%H:%M}**" if t.due and t.due.date() == now.date() else "") for t in ts[:5]]
        if len(ts) > 5:
            lines.append(f"…и ещё {len(ts) - 5}")
    else:
        lines.append("✅ Задач нет. Подозрительно.")
    if pays:
        lines.append("")
        lines.append("💳 **Платежи в ближайшие дни**")
        lines += [f"— {p.title} · **{money(p.amount)}** · {p.next_date:%d.%m}" for p in pays]
    lines.append("")
    lines.append(f"Баланс **{money(s['total_balance'])}**" + (f", за сегодня −**{money(s['spent'])}**" if s.get("spent") else ""))
    return "\n".join(lines)


@tool("cash_forecast", "Прогноз денег на 30 дней: хватит ли до зарплаты, сколько безопасно тратить в день, когда возможен минус.", {})
def cash_forecast(**_) -> str:
    from ..services import insights
    return insights.cash_forecast_text()


@tool("find_subscriptions", "Найти подписки и повторяющиеся ежемесячные списания, которых нет в регулярных платежах.", {})
def find_subscriptions(**_) -> str:
    from ..services import insights
    subs = insights.detect_subscriptions()
    if not subs:
        return "Повторяющихся списаний, похожих на подписки, не нашёл."
    return "Похоже на подписки: " + "; ".join(f"{x['name']} {money(x['amount'])}/мес ({x['times']} раз)" for x in subs[:8])


_DAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
_MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


# ---------------- Облако ----------------
# Инструмент-маркер: локальная модель вызывает его, когда вопрос общий и не требует личных данных.
# Сам вызов облака делает agent.py (асинхронно) — здесь только описание для LLM.
CLOUD_TOOL = "ask_cloud"
TOOLS[CLOUD_TOOL] = {
    "type": "function",
    "function": {
        "name": CLOUD_TOOL,
        "description": (
            "Передать ОБЩИЙ вопрос более мощной облачной модели. Используй, когда пользователь просит объяснить, "
            "написать текст, придумать, сравнить, посоветовать, рассказать факты — и для ответа НЕ нужны его личные "
            "данные (финансы, календарь, задачи, заметки, файлы). НЕ используй для команд «запиши/добавь/покажи» "
            "и для вопросов о его деньгах, встречах и планах."
        ),
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "Вопрос своими словами, без имён и личных деталей"}},
            "required": ["question"]},
    },
}


# ---------------- Валидация аргументов от LLM ----------------
# Модель (особенно маленькая локальная) присылает что угодно: отрицательные суммы, days=-5, пустые названия,
# строки вместо чисел, лишние поля. Без проверки это тихо ломало данные: add_expense(-700) записывался как трата 700,
# add_task("   ") создавал задачу без названия. Здесь — единая граница, по схеме инструмента + здравый смысл.
MAX_AMOUNT = 1_000_000_000      # 1 млрд ₽ — выше этого почти наверняка ошибка распознавания
MAX_DAYS = 3650                 # периоды/горизонты: до 10 лет
MAX_TITLE = 300                 # названия событий/задач/долгов
MAX_TEXT = 8000                 # заметки
_AMOUNT_KEYS = {"amount", "total", "payment", "balance"}
_DAYS_KEYS = {"days", "duration_min"}
_TITLE_KEYS = {"title", "category", "account", "to_account", "from_account", "debt", "query", "location"}
_TEXT_KEYS = {"text", "note", "question"}
_SIGNED_OK = {"set_balance"}    # баланс счёта может быть отрицательным (кредитка/овердрафт)


class ToolArgError(ValueError):
    """Понятное для LLM описание, что не так с аргументами (без трейсбека)."""


def _coerce(name: str, key: str, spec: dict, val: Any) -> Any:
    typ = spec.get("type")
    if val is None:
        return None
    if typ in ("number", "integer"):
        if isinstance(val, bool):
            raise ToolArgError(f"{key}: нужно число")
        if isinstance(val, str):
            v = val.strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
            v = "".join(ch for ch in v if ch.isdigit() or ch in ".-")
            if not v or v in ("-", "."):
                raise ToolArgError(f"{key}: нужно число, а не «{val[:40]}»")
            val = float(v)
        if not isinstance(val, (int, float)):
            raise ToolArgError(f"{key}: нужно число")
        if val != val or val in (float("inf"), float("-inf")):
            raise ToolArgError(f"{key}: нужно число")
        if typ == "integer":
            val = int(round(val))
        if key in _AMOUNT_KEYS and name not in _SIGNED_OK and not (key == "payment" and val == 0):
            if val <= 0:
                raise ToolArgError(f"{key}: сумма должна быть больше нуля (получил {val}). Для возврата денег используй add_income.")
            if val > MAX_AMOUNT:
                raise ToolArgError(f"{key}: сумма {val:,.0f} неправдоподобно велика — переспроси пользователя.")
        if key in _AMOUNT_KEYS and abs(val) > MAX_AMOUNT:
            raise ToolArgError(f"{key}: значение неправдоподобно велико — переспроси пользователя.")
        if key in _DAYS_KEYS and not (1 <= val <= MAX_DAYS if key == "days" else 1 <= val <= 60 * 24 * 14):
            raise ToolArgError(f"{key}: должно быть от 1 до {MAX_DAYS if key == 'days' else 20160}, получил {val}")
        if key in ("day", "pay_day") and not (1 <= val <= 31):
            raise ToolArgError(f"{key}: день месяца от 1 до 31, получил {val}")
        if key == "priority" and not (1 <= val <= 3):
            val = min(3, max(1, val))
        if key == "rate" and not (0 <= val <= 1000):
            raise ToolArgError(f"rate: ставка в процентах от 0 до 1000, получил {val}")
        return val
    if typ == "string":
        if not isinstance(val, str):
            val = str(val)
        val = val.strip()
        if key in _TITLE_KEYS:
            if len(val) > MAX_TITLE:
                val = val[:MAX_TITLE].rstrip()
        elif key in _TEXT_KEYS and len(val) > MAX_TEXT:
            val = val[:MAX_TEXT].rstrip()
        return val
    if typ == "array":
        if isinstance(val, str):
            val = [x.strip() for x in val.split(",") if x.strip()]
        if not isinstance(val, list):
            raise ToolArgError(f"{key}: нужен список")
        return val[:50]
    return val


def validate_args(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Приводит аргументы к схеме инструмента, отбрасывает лишние, проверяет обязательные и диапазоны.
    Бросает ToolArgError с текстом, который можно вернуть модели как результат инструмента."""
    spec = TOOLS[name]["function"]["parameters"]
    props: dict = spec.get("properties", {})
    required: list = spec.get("required", [])
    if not isinstance(args, dict):
        args = {}
    out: dict[str, Any] = {}
    for key, val in args.items():
        if key not in props:
            continue  # выдуманные моделью поля игнорируем
        out[key] = _coerce(name, key, props[key], val)
    missing = [k for k in required if out.get(k) in (None, "", [])]
    if missing:
        raise ToolArgError(f"не хватает обязательных полей: {', '.join(missing)}. Уточни у пользователя.")
    return out


def run_tool(name: str, args: dict[str, Any], channel: str = "tg") -> str:
    fn = FUNCS.get(name)
    if not fn:
        return f"Неизвестный инструмент {name}"
    try:
        args = validate_args(name, args)
    except ToolArgError as e:
        return f"Инструмент {name} не выполнен: {e}"
    try:
        return str(fn(**args, _channel=channel))
    except TypeError:
        try:
            return str(fn(**args))
        except Exception as e:  # pragma: no cover
            return f"Ошибка инструмента: {e}"
    except Exception as e:
        return f"Ошибка инструмента: {e}"


def tools_schema(with_cloud: bool = False) -> list[dict]:
    return [t for n, t in TOOLS.items() if with_cloud or n != CLOUD_TOOL]


def tools_as_text() -> str:
    return json.dumps([t["function"] for t in TOOLS.values()], ensure_ascii=False)
