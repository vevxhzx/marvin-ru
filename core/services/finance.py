"""Финансы: траты, доходы, счета, регулярные платежи, долги."""
from __future__ import annotations

import re

import math
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta
from sqlmodel import select
from starlette.exceptions import HTTPException as _HTTPException

from ..db import cached, icontains, Account, Category, Debt, Recurring, Transaction, log_action, remember, session
from . import regime


class FinanceError(ValueError):
    """Понятная человеку ошибка ввода (сумма больше остатка и т.п.). API отдаёт её как 400."""


class FinanceNotFound(_HTTPException, FinanceError):
    """Сущность не найдена: API отдаёт 404, а не 400 — «нет такого» ≠ ошибка валидации (P2 ревью A).

    Наследуемся и от HTTPException (роут отвечает 404, DELETE того же ресурса уже так отвечал),
    и от FinanceError — все существующие `except FinanceError` в правилах/инструментах
    ловили такие ошибки раньше и ловят теперь, с тем же текстом.
    """

    def __init__(self, detail: str = "Не найдено"):
        super().__init__(404, detail)       # по MRO — HTTPException.__init__

    def __str__(self) -> str:
        return str(self.detail)             # текст для чат-правил без префикса «404: »


def _num(x, name: str = "Сумма", min_: float | None = 0, max_: float | None = None, strict_min: bool = False) -> float:
    try:
        v = float(str(x).replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except (TypeError, ValueError):
        raise FinanceError(f"{name}: введите число")
    if math.isnan(v) or math.isinf(v):
        raise FinanceError(f"{name}: введите число")
    if min_ is not None and (v < min_ or (strict_min and v <= min_)):
        raise FinanceError(f"{name} должна быть {'больше' if strict_min else 'не меньше'} {money(min_)}")
    if max_ is not None and v > max_:
        raise FinanceError(f"{name} не может быть больше {money(max_)}")
    if abs(v) > 1e9:
        raise FinanceError(f"{name}: {money(v)} — неправдоподобно много. Если это не опечатка, разбейте на части.")
    return round(v, 2)


def _day(x) -> int:
    try:
        d = int(x)
    except (TypeError, ValueError):
        raise FinanceError("День месяца: число от 1 до 31")
    if not 1 <= d <= 31:
        raise FinanceError("День месяца: число от 1 до 31")
    return d


def _rate(x) -> float:
    return _num(x if x not in (None, "") else 0, "Ставка", 0, 1000)


def _title(x, name: str = "Название") -> str:
    t = (x or "").strip()
    if not t:
        raise FinanceError(f"{name} не может быть пустым")
    return t[:120]


def money(x: float) -> str:
    """Рубли с копейками: копейки показываем, только если дробная часть ненулевая.

    Округление — HALF_UP до 2 знаков через Decimal(str(x)), симметрично с JS
    (fmtMoney/money): Python round() — half-even, JS Math.round — half-up,
    одно и то же значение рендерилось по-разному. Группировка пробелами как раньше.
    """
    d = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if d == d.to_integral_value():
        return f"{int(d):,}".replace(",", " ") + " ₽"
    return f"{d:,.2f}".replace(",", " ") + " ₽"


# ---------- категории ----------
def guess_category(text: str, kind: str = "expense") -> str:
    text = (text or "").lower().replace("ё", "е")
    from .match import same
    words = re.findall(r"[а-яa-z0-9]+", text)
    with session() as s:
        cats = s.exec(select(Category).where(Category.kind == kind)).all()
        for c in cats:
            for kw in filter(None, c.keywords.replace("ё", "е").split(",")):
                kw = kw.strip()
                if kw and kw in text:
                    return c.name
        # падежи: «на еду» → еда, «продуктов» → продукты
        for c in cats:
            for kw in filter(None, c.keywords.replace("ё", "е").split(",")):
                kw = kw.strip()
                if kw and " " not in kw and len(kw) >= 3 and any(same(w, kw) for w in words if len(w) >= 3):
                    return c.name
        return "Другое" if kind == "expense" else "Прочий доход"


def add_category(name: str, kind: str = "expense", icon: str = "•", keywords: str = "", budget: float = 0, bucket: str = "") -> Category:
    name = _title(name, "Категория")
    if kind not in ("expense", "income"):
        kind = "expense"
    with session() as s:
        if s.exec(select(Category).where(Category.name == name)).first():
            raise FinanceError(f"Категория «{name}» уже есть")
        c = Category(name=name, kind=kind, icon=(icon or "•")[:4], keywords=(keywords or "").lower(), budget=_num(budget or 0, "Лимит", 0), custom=True,
                     bucket=bucket if bucket in ("need", "want", "save") else "")
        s.add(c); s.commit(); s.refresh(c)
        return c


def update_category(cid: int, **fields) -> Category:
    with session() as s:
        c = s.get(Category, cid)
        if not c:
            raise FinanceNotFound("Категория не найдена")
        if fields.get("name") is not None and fields["name"].strip() != c.name:
            new = _title(fields["name"], "Категория")
            if s.exec(select(Category).where(Category.name == new)).first():
                raise FinanceError(f"Категория «{new}» уже есть")
            for t in s.exec(select(Transaction).where(Transaction.category == c.name)).all():
                t.category = new; s.add(t)
            for r in s.exec(select(Recurring).where(Recurring.category == c.name)).all():
                r.category = new; s.add(r)
            c.name = new
        if fields.get("icon") is not None:
            c.icon = (fields["icon"] or "•")[:4]
        if fields.get("keywords") is not None:
            c.keywords = fields["keywords"].lower()
        if fields.get("budget") is not None:
            c.budget = _num(fields["budget"] or 0, "Лимит", 0)
        if fields.get("bucket") is not None:
            if fields["bucket"] not in ("", "need", "want", "save"):
                raise FinanceError("Корзина: need / want / save или пусто")
            c.bucket = fields["bucket"]
        s.add(c); s.commit(); s.refresh(c)
        return c


def delete_category(cid: int) -> bool:
    with session() as s:
        c = s.get(Category, cid)
        if not c:
            return False
        if c.name in ("Другое", "Долги", "Прочий доход"):
            raise FinanceError("Эту категорию удалить нельзя")
        fallback = "Другое" if c.kind == "expense" else "Прочий доход"
        for t in s.exec(select(Transaction).where(Transaction.category == c.name)).all():
            t.category = fallback; s.add(t)
        for r in s.exec(select(Recurring).where(Recurring.category == c.name)).all():
            r.category = fallback; s.add(r)
        s.delete(c); s.commit()
        return True


def budgets() -> list[dict]:
    """Лимиты по категориям за текущий календарный месяц."""
    now = datetime.now()
    m0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with session() as s:
        cats = [c for c in s.exec(select(Category).where(Category.kind == "expense")) if c.budget > 0]
        # только две колонки: годятся категория и сумма, а текст заметки и прочее тянуть не нужно
        txs = s.exec(select(Transaction.category, Transaction.amount)
                     .where(Transaction.kind == "expense", Transaction.date >= m0)).all()
    out = []
    days_in_month = ((m0 + relativedelta(months=1)) - m0).days
    for c in cats:
        spent = sum(amount for cat, amount in txs if cat == c.name)
        pct = spent / c.budget if c.budget else 0
        out.append({"id": c.id, "name": c.name, "icon": c.icon, "budget": c.budget, "spent": spent, "left": c.budget - spent,
                    "pct": pct, "pace": (now.day / days_in_month),  # где «должны» быть по времени
                    "status": "over" if pct >= 1 else "warn" if pct >= 0.8 else "ok"})
    out.sort(key=lambda b: -b["pct"])
    return out


def safe_to_spend(recurring: list[Recurring] | None = None, accounts: list[Account] | None = None) -> dict:
    """Сколько можно тратить в день до следующей зарплаты, чтобы хватило на обязательные платежи.

    recurring/accounts можно передать готовыми, когда они уже прочитаны (сводка читает их
    один раз и переиспользует) — цифры от этого не меняются.

    `avg_daily` — фактические траты в день по окну расчёта: с началом режима жизни, если он
    считается (services/regime.py), иначе за последние 30 дней. Раньше этого поля не было —
    «в среднем в день» показывали только прогноз и сводка.
    """
    now = datetime.now()
    rec = list_recurring() if recurring is None else recurring
    incomes = [r for r in rec if r.kind == "income"]
    if incomes:
        next_income = min(r.next_date for r in incomes)
    else:
        next_income = (now.replace(day=1) + relativedelta(months=1))
    days_left = max(1, (next_income.date() - now.date()).days)
    balance = total_balance(accounts)
    # обязательные платежи до зарплаты: регулярные расходы (в т.ч. по долгам), чья дата раньше зарплаты
    upcoming = [r for r in rec if r.kind == "expense" and r.next_date < next_income]
    reserved = sum(r.amount for r in upcoming)
    free = balance - reserved
    cw = regime.count_window(30)
    if cw:
        rows = _spent_rows(cw[0], cw[1])
        avg_daily = round(sum(a for _dt, a in rows) / cw[2])
    else:
        rows = _spent_rows(now - timedelta(days=30))
        avg_daily = round(sum(a for _dt, a in rows) / 30)
    return {"balance": balance, "reserved": reserved, "free": free, "days_left": days_left,
            "per_day": free / days_left, "next_income": next_income.isoformat(),
            "upcoming": [{"title": r.title, "amount": r.amount, "date": r.next_date.isoformat()} for r in upcoming],
            "spent_today": sum(t.amount for t in list_transactions(1, 1000) if t.kind == "expense" and t.date.date() == now.date()),
            "avg_daily": avg_daily, "regime": regime.info()}


def list_categories(kind: str | None = None) -> list[Category]:
    with session() as s:
        q = select(Category)
        if kind:
            q = q.where(Category.kind == kind)
        return list(s.exec(q))


# ---------- счета ----------
def main_account_name() -> str:
    with session() as s:
        a = s.exec(select(Account).where(Account.is_main == True)).first()  # noqa: E712
        return a.name if a else "Основной"


def list_accounts() -> list[Account]:
    with session() as s:
        return list(s.exec(select(Account)))


def total_balance(accounts: list[Account] | None = None) -> float:
    """Единый источник «баланса»: сумма по всем счетам, кроме чисто долговых.

    Главная и «финансы» обязаны показывать одно и то же число — любое место,
    где нужен баланс, должно звать эту функцию, а не суммировать счета заново.
    Список счетов можно передать готовым, если он уже прочитан.
    """
    accs = list_accounts() if accounts is None else accounts
    return sum(a.balance for a in accs if a.kind != "debt_only")


def set_balance(name: str, balance: float) -> Account:
    balance = _num(balance, "Баланс", min_=None)
    name = _title(name, "Счёт")
    with session() as s:
        a = s.exec(select(Account).where(Account.name == name)).first()
        if not a:
            a = Account(name=name)
        a.balance = balance
        s.add(a)
        remember(s, "finance", f"Баланс «{name}» установлен: {money(balance)}", "account", a.id)
        s.commit()
        s.refresh(a)
        return a


def add_account(name: str, kind: str = "bank", balance: float = 0) -> Account:
    name = _title(name, "Счёт")
    if kind not in ("bank", "cash", "debt_only"):
        kind = "bank"
    with session() as s:
        if s.exec(select(Account).where(Account.name == name)).first():
            raise FinanceError(f"Счёт «{name}» уже есть")
        a = Account(name=name, kind=kind, balance=_num(balance, "Баланс", min_=None))
        s.add(a); s.commit(); s.refresh(a)
        remember(s, "finance", f"Новый счёт «{name}» ({money(a.balance)})", "account", a.id)
        s.commit()
        return a


def update_account(account_id: int, name: str | None = None, balance=None, kind: str | None = None, is_main: bool | None = None) -> Account:
    with session() as s:
        a = s.get(Account, account_id)
        if not a:
            raise FinanceNotFound("Счёт не найден")
        if name is not None and name.strip() != a.name:
            new = _title(name, "Счёт")
            if s.exec(select(Account).where(Account.name == new)).first():
                raise FinanceError(f"Счёт «{new}» уже есть")
            # переименовываем и в операциях/регулярных, чтобы история не потерялась
            for t in s.exec(select(Transaction).where(Transaction.account == a.name)).all():
                t.account = new; s.add(t)
            for t in s.exec(select(Transaction).where(Transaction.to_account == a.name)).all():
                t.to_account = new; s.add(t)
            for r in s.exec(select(Recurring).where(Recurring.account == a.name)).all():
                r.account = new; s.add(r)
            a.name = new
        if balance is not None:
            a.balance = _num(balance, "Баланс", min_=None)
        if kind in ("bank", "cash", "debt_only"):
            a.kind = kind
        if is_main:
            for other in s.exec(select(Account)).all():
                other.is_main = False; s.add(other)
            a.is_main = True
        s.add(a)
        remember(s, "finance", f"Счёт «{a.name}»: {money(a.balance)}", "account", a.id)
        s.commit(); s.refresh(a)
        return a


def delete_account(account_id: int) -> bool:
    with session() as s:
        a = s.get(Account, account_id)
        if not a:
            return False
        if a.is_main:
            raise FinanceError("Основной счёт удалить нельзя — сначала назначьте основным другой")
        if s.exec(select(Transaction).where((Transaction.account == a.name) | (Transaction.to_account == a.name))).first():
            raise FinanceError("По счёту есть операции — удалить нельзя. Можно обнулить баланс")
        s.delete(a); s.commit()
        return True


def _shift_balance(s, name: str | None, delta: float) -> None:
    if not name:
        return
    a = s.exec(select(Account).where(Account.name == name)).first()
    if a:
        a.balance += delta
        s.add(a)


# ---------- операции ----------
def _account_exists(s, name: str | None) -> None:
    if name and not s.exec(select(Account).where(Account.name == name)).first():
        raise FinanceError(f"Счёта «{name}» нет")


def add_transaction(amount: float, kind: str = "expense", category: str | None = None,
                    note: str | None = None, account: str | None = None,
                    to_account: str | None = None, date: datetime | None = None,
                    source: str = "tg", import_hash: str | None = None, debt_id: int | None = None,
                    order_id: int | None = None, goal_id: int | None = None, idem_key: str | None = None) -> Transaction:
    amount = _num(abs(float(amount)) if isinstance(amount, (int, float)) else amount, "Сумма", 0, strict_min=True)
    if kind not in ("expense", "income", "transfer"):
        raise FinanceError("Тип операции: expense / income / transfer")
    account = (account or "").strip() or main_account_name()
    if kind == "transfer":
        to_account = (to_account or "").strip()
        if not to_account:
            raise FinanceError("Для перевода укажите счёт-получатель")
        if to_account == account:
            raise FinanceError("Перевод на тот же счёт не имеет смысла")
        category = None
    if not category and kind != "transfer":
        category = guess_category(note or "", kind)
    if date and date > datetime.now() + timedelta(days=1):
        raise FinanceError("Операция из будущего? Дата не может быть позже завтрашнего дня")
    with session() as s:
        _account_exists(s, account)
        if kind == "transfer":
            _account_exists(s, to_account)
        t = Transaction(amount=amount, kind=kind, category=category, note=(note or None), account=account,
                        to_account=to_account, date=date or datetime.now(), source=source,
                        import_hash=import_hash, debt_id=debt_id, order_id=order_id, goal_id=goal_id, idem_key=idem_key)
        s.add(t)
        if kind == "expense":
            _shift_balance(s, account, -amount)
            txt = f"Трата {money(amount)} · {category}" + (f" · {note}" if note else "")
        elif kind == "income":
            _shift_balance(s, account, +amount)
            txt = f"Доход {money(amount)} · {category}" + (f" · {note}" if note else "")
        else:
            _shift_balance(s, account, -amount)
            _shift_balance(s, to_account, +amount)
            txt = f"Перевод {money(amount)}: {account} → {to_account}"
        s.commit()
        s.refresh(t)
        remember(s, "finance", txt, "transaction", t.id, source)
        if source != "system":
            log_action(s, "pay_debt" if debt_id else ("add_income" if kind == "income" else "add_expense"), "transaction", t.id, txt, source)
        s.commit()
        return t


def _apply(s, t: Transaction, sign: int) -> None:
    """sign=+1 — провести операцию по балансам, −1 — откатить."""
    if t.kind == "expense":
        _shift_balance(s, t.account, -sign * t.amount)
    elif t.kind == "income":
        _shift_balance(s, t.account, +sign * t.amount)
    else:
        _shift_balance(s, t.account, -sign * t.amount)
        _shift_balance(s, t.to_account, +sign * t.amount)


def delete_transaction(tx_id: int) -> bool:
    with session() as s:
        t = s.get(Transaction, tx_id)
        if not t:
            return False
        _apply(s, t, -1)
        if t.debt_id:  # платёж по долгу — возвращаем остаток долга
            d = s.get(Debt, t.debt_id)
            if d:
                d.remaining = min(d.total, d.remaining + t.amount)
                d.closed = d.remaining <= 0
                s.add(d)
                remember(s, "finance", f"Отменён платёж {money(t.amount)} по «{d.title}», остаток {money(d.remaining)}", "debt", d.id)
        if getattr(t, "goal_id", None):  # перевод в конверт — возвращаем «отложено» назад
            from ..db import Goal
            g = s.get(Goal, t.goal_id)
            if g:
                g.saved = max(0.0, g.saved - t.amount if t.kind == "expense" else g.saved + t.amount)
                if g.closed and g.saved < g.target - 0.5:
                    g.closed = False
                s.add(g)
        if getattr(t, "order_id", None) and t.kind == "income":  # оплата по заказу — заказ снова «ждёт оплату»
            from ..db import Order
            o = s.get(Order, t.order_id)
            if o and o.status == "paid":
                o.status = "done"; o.paid_at = None; s.add(o)
        s.delete(t)
        s.commit()
        return True


def _category_conflicts(s, name: str | None, kind: str) -> bool:
    """Категория не подходит типу операции: доход не должен числиться в «Еда» (P2 ревью B).

    Пользовательская категория не теряется без причины: конфликт — только когда её тип
    (expense/income) расходится с новым типом операции; совместимая категория остаётся.
    """
    if not name or kind not in ("expense", "income"):
        return False
    c = s.exec(select(Category).where(Category.name == name)).first()
    if c is not None:
        return c.kind != kind
    # категории уже нет в справочнике: «Прочий доход» — доходная, остальное исторически расходное
    return name != "Прочий доход" if kind == "income" else name == "Прочий доход"


def update_transaction(tx_id: int, **fields) -> Transaction:
    """Правка операции: балансы пересчитываются (старая откатывается, новая проводится)."""
    with session() as s:
        t = s.get(Transaction, tx_id)
        if not t:
            raise FinanceNotFound("Операция не найдена")
        if t.debt_id and "amount" in fields and fields["amount"] is not None:
            d = s.get(Debt, t.debt_id)
            new_amt = _num(fields["amount"], "Сумма", 0, strict_min=True)
            if d:
                # остаток долга пересчитываем: вернуть старый платёж, списать новый
                back = min(d.total, d.remaining + t.amount)
                if new_amt > back:
                    raise FinanceError(f"Платёж не может быть больше остатка долга ({money(back)})")
                d.remaining = round(back - new_amt, 2)
                d.closed = d.remaining <= 0
                s.add(d)
        _apply(s, t, -1)
        if fields.get("amount") is not None:
            t.amount = _num(fields["amount"], "Сумма", 0, strict_min=True)
        kind_changed = fields.get("kind") in ("expense", "income", "transfer") and fields["kind"] != t.kind
        if fields.get("kind") in ("expense", "income", "transfer"):
            t.kind = fields["kind"]
        if "category" in fields and t.kind != "transfer":
            t.category = (fields["category"] or "").strip() or guess_category(fields.get("note") or t.note or "", t.kind)
        elif kind_changed and t.kind != "transfer" and _category_conflicts(s, t.category, t.kind):
            # смена типа: категория чужого типа («Еда» у дохода) не должна переехать в новый
            # тип вместе с операцией — подбираем подходящую по названию (P2 ревью B)
            t.category = guess_category(fields.get("note") or t.note or "", t.kind)
        if "note" in fields:
            t.note = (fields["note"] or "").strip() or None
        if fields.get("account"):
            _account_exists(s, fields["account"]); t.account = fields["account"]
        if "to_account" in fields:
            t.to_account = fields["to_account"] or None
        if fields.get("date"):
            dt = fields["date"] if isinstance(fields["date"], datetime) else datetime.fromisoformat(str(fields["date"]))
            if dt > datetime.now() + timedelta(days=1):
                raise FinanceError("Дата не может быть в будущем")
            t.date = dt
        if t.kind == "transfer":
            if not t.to_account or t.to_account == t.account:
                raise FinanceError("Для перевода нужен другой счёт-получатель")
            t.category = None
        _apply(s, t, +1)
        s.add(t)
        remember(s, "finance", f"Исправлена операция #{t.id}: {money(t.amount)} · {t.category or t.kind}", "transaction", t.id)
        s.commit(); s.refresh(t)
        return t


def last_transaction() -> Transaction | None:
    with session() as s:
        return s.exec(select(Transaction).order_by(Transaction.id.desc())).first()


def list_transactions(days: int = 30, limit: int = 200) -> list[Transaction]:
    since = datetime.now() - timedelta(days=days)
    with session() as s:
        return list(s.exec(select(Transaction).where(Transaction.date >= since)
                           .order_by(Transaction.date.desc()).limit(limit)))


def list_transactions_between(since: datetime, until: datetime | None = None, limit: int = 100_000) -> list[Transaction]:
    """Операции за конкретный интервал [since, until) — окно «режима жизни».

    Отдельная функция (а не фильтр поверх list_transactions) нужна, потому что окно режима
    может начинаться РАНЬше, чем «последние N дней»: чтобы среднее считалось по всему режиму,
    историю надо тянуть с его начала, а не с границы периода.
    """
    with session() as s:
        q = select(Transaction).where(Transaction.date >= since)
        if until:
            q = q.where(Transaction.date < until)
        return list(s.exec(q.order_by(Transaction.date.desc()).limit(limit)))


def _period_txs(days: int, limit: int = 100_000) -> tuple[list[Transaction], int]:
    """Операции для средних: окно режима, если он считается, иначе последние `days` дней.

    Возвращает (операции, дней в окне) — знаменатель для «в среднем в день». Без режима
    знаменатель равен `days`, поведение прежнее.
    """
    cw = regime.count_window(days)
    if cw:
        return list_transactions_between(cw[0], cw[1], limit), cw[2]
    return list_transactions(days, limit), max(1, int(days or 30))


def _spent_rows(since: datetime, until: datetime | None = None) -> list[tuple[datetime, float]]:
    """Только (дата, сумма) трат за интервал — для средних, где больше ничего не нужно."""
    with session() as s:
        q = (select(Transaction.date, Transaction.amount)
             .where(Transaction.date >= since, Transaction.kind == "expense"))
        if until:
            q = q.where(Transaction.date < until)
        return [(d, float(a)) for d, a in s.exec(q.order_by(Transaction.date.desc()).limit(100_000)).all()]


def cashflow(recurring: list[Recurring] | None = None, txs: list[Transaction] | None = None) -> dict:
    """Месячный поток: доход − регулярные − платежи по долгам = свободно.

    recurring/txs можно передать готовыми (сводка читает регулярные один раз).

    Средние переменные траты и «средний нерегулярный доход» считаются по окну расчёта:
    с началом режима жизни, если он считается (services/regime.py), иначе как раньше — за
    последние 90 дней. Регулярные платежи и долги остаются общими: это планы, а не средние.
    """
    rec = list_recurring() if recurring is None else recurring
    rec_income = sum(r.amount for r in rec if r.kind == "income")
    rec_income_cats = {r.category for r in rec if r.kind == "income"}
    rec_expense = sum(r.amount for r in rec if r.kind == "expense" and not r.debt_id)
    debt_pay = sum(d.payment for d in list_debts() if not d.closed)

    win_days = None
    if txs is None:
        all_txs, win_days = _period_txs(90)
    else:
        all_txs = txs
    real = [t for t in all_txs if "(авто)" not in (t.note or "")]

    def span_months(items: list) -> float:
        # режим жизни: окно и есть период наблюдения (5 дней режима — это 1/6 месяца, а не месяц)
        if win_days:
            return max(1.0 / 30, min(3.0, win_days / 30.0))
        if not items:
            return 1.0
        first = min(t.date for t in items)
        return max(1.0, min(3.0, (datetime.now() - first).days / 30))

    # доход: регулярный + средний нерегулярный (категории регулярного дохода не дублируем)
    extra = [t for t in real if t.kind == "income" and (not rec_income or t.category not in rec_income_cats)]
    avg_extra = sum(t.amount for t in extra) / span_months(real) if extra else 0.0
    income = rec_income + avg_extra

    # средние переменные траты (без авто-платежей и долгов)
    var_tx = [t for t in real if t.kind == "expense" and t.category != "Долги"]
    avg_variable = sum(t.amount for t in var_tx) / span_months(real) if var_tx else 0.0

    free = income - rec_expense - debt_pay
    return {
        "income": income, "recurring": rec_expense, "debt_payments": debt_pay,
        "free": free, "avg_variable": avg_variable, "left_after_all": free - avg_variable,
        "income_is_estimate": not rec_income,
        "regime": regime.info(),
    }


def daily_series(days: int = 30) -> list[dict]:
    """Траты и доходы по дням для графика."""
    txs = list_transactions(days, 100_000)
    out: dict[str, dict] = {}
    for i in range(days - 1, -1, -1):
        d = (datetime.now() - timedelta(days=i)).date().isoformat()
        out[d] = {"date": d, "expense": 0.0, "income": 0.0, "count": 0, "top": None, "_cats": {}}
    for t in txs:
        k = t.date.date().isoformat()
        if k in out and t.kind in ("expense", "income"):
            out[k][t.kind] += t.amount
            out[k]["count"] += 1
            if t.kind == "expense":
                c = out[k]["_cats"]; c[t.category or "Другое"] = c.get(t.category or "Другое", 0) + t.amount
    for v in out.values():
        cats = v.pop("_cats")
        if cats:
            name, amt = max(cats.items(), key=lambda kv: kv[1])
            v["top"] = {"name": name, "amount": amt}
    return list(out.values())


def summary(days: int = 30) -> dict:
    """Сводка: траты/доходы за период, по категориям, балансы, долги.

    Считается по всей базе, поэтому результат кэшируется на пару секунд (core.db.cached):
    главная и дашборд зовут сводку по several раз. Любая запись в базу кэш сразу сбрасывает.
    """
    return cached(f"summary:{int(days or 30)}", lambda: _summary(days))


def _summary(days: int = 30) -> dict:
    # Окно расчёта: если режим жизни считается (services/regime.py) — операции только внутри
    # него, иначе поведение прежнее (последние `days` дней). Знаменатель среднего — дни окна.
    cw = regime.count_window(days)
    if cw:
        txs = list_transactions_between(cw[0], cw[1], limit=10_000)
        avg_days = cw[2]
    else:
        txs = list_transactions(days, limit=10_000)
        avg_days = None
    spent = sum(t.amount for t in txs if t.kind == "expense")
    earned = sum(t.amount for t in txs if t.kind == "income")
    by_cat: dict[str, float] = {}
    for t in txs:
        if t.kind == "expense":
            by_cat[t.category or "Другое"] = by_cat.get(t.category or "Другое", 0) + t.amount
    by_cat = dict(sorted(by_cat.items(), key=lambda kv: -kv[1]))
    # счета и регулярные платежи читаем ОДИН раз на всю сводку: раньше каждая из вложенных
    # функций (баланс, поток, безопасная трата) ходила в базу за ними сама — 4 лишних запроса
    accounts = list_accounts()
    debts = list_debts()
    rec = list_recurring()
    balance = total_balance(accounts)

    # Столбики для главной («траты» по дням недели и по дням месяца) — из реальных
    # операций текущего календарного месяца. Раньше этих полей в сводке не было и
    # фронт подставлял захардкоженные высоты.
    weekday = [0] * 7
    month_days = [0] * 7
    edges = [4, 9, 14, 19, 24, 29, 31]
    today = datetime.now()
    spent_month = 0.0
    for t in txs:
        if t.kind != "expense" or t.date is None:
            continue
        if t.date.year != today.year or t.date.month != today.month:
            continue
        weekday[t.date.weekday()] += t.amount
        month_days[next((i for i, e in enumerate(edges) if t.date.day <= e), 6)] += t.amount
        spent_month += t.amount

    # «в среднем в день»: с режимом жизни — по его окну (честный знаменатель в днях),
    # без режима — как раньше, по текущему календарному месяцу.
    if avg_days:
        avg_daily = round(spent / avg_days)
    else:
        avg_daily = round(spent_month / today.day) if today.day else 0
    return {
        "days": days,
        "spent": spent,
        "earned": earned,
        "by_category": by_cat,
        "total_balance": balance,
        # алиасы, которые читает Today.jsx (иначе страница подставляла выдуманные числа)
        "balance": balance,
        "avg_daily": avg_daily,
        "avg_days": avg_days or today.day,
        "runway_days": math.floor(balance / avg_daily) if avg_daily else None,
        "weekday": weekday,
        "month_days": month_days,
        "accounts": [{"name": a.name, "balance": a.balance, "is_main": a.is_main} for a in accounts],
        "debts_total": sum(d.remaining for d in debts if not d.closed),
        "monthly_debt_payments": sum(d.payment for d in debts if not d.closed),
        "recurring_monthly": sum(r.amount for r in rec if r.kind == "expense"),
        "cashflow": cashflow(rec),
        "budgets": budgets(),
        "safe": safe_to_spend(rec, accounts),
        "regime": regime.info(),
    }


# ---------- регулярные ----------
def add_recurring(title: str, amount: float, day: int = 1, kind: str = "expense",
                  category: str | None = None, period: str = "monthly", debt_id: int | None = None) -> Recurring:
    title = _title(title)
    amount = _num(amount, "Сумма", 0, strict_min=True)
    day = _day(day)
    if kind not in ("expense", "income"):
        raise FinanceError("Тип: expense / income")
    if period not in ("monthly", "weekly", "yearly"):
        period = "monthly"
    with session() as s:
        r = Recurring(title=title, amount=amount, kind=kind, category=category or guess_category(title, kind),
                      period=period, day=day, next_date=_next_date(day, period), debt_id=debt_id)
        s.add(r)
        s.commit()
        s.refresh(r)
        remember(s, "finance", f"Регулярный платёж: «{title}» {money(amount)} каждое {day}-е", "recurring", r.id)
        if not debt_id:
            log_action(s, "add_recurring", "recurring", r.id, title)
        s.commit()
        return r


def update_recurring(rid: int, **fields) -> Recurring:
    with session() as s:
        r = s.get(Recurring, rid)
        if not r:
            raise FinanceNotFound("Регулярный платёж не найден")
        if fields.get("title") is not None:
            r.title = _title(fields["title"])
        if fields.get("amount") is not None:
            r.amount = _num(fields["amount"], "Сумма", 0, strict_min=True)
        if fields.get("day") is not None or fields.get("period"):
            if fields.get("period") in ("monthly", "weekly", "yearly"):
                r.period = fields["period"]
            if fields.get("day") is not None:
                r.day = _day(fields["day"])
            r.next_date = _next_date(r.day, r.period)
        if fields.get("kind") in ("expense", "income") and not r.debt_id:
            r.kind = fields["kind"]
        if "category" in fields and not r.debt_id:
            r.category = (fields["category"] or "").strip() or guess_category(r.title, r.kind)
        if fields.get("account") is not None:
            r.account = fields["account"] or None
        if fields.get("active") is not None:
            r.active = bool(fields["active"])
        s.add(r)
        # платёж по долгу — держим долг в синхроне
        if r.debt_id:
            d = s.get(Debt, r.debt_id)
            if d:
                d.payment = r.amount; d.pay_day = r.day; s.add(d)
        remember(s, "finance", f"Регулярный платёж «{r.title}»: {money(r.amount)} каждое {r.day}-е", "recurring", r.id)
        s.commit(); s.refresh(r)
        return r


def find_recurring(query: str | int) -> Recurring | None:
    """Регулярный платёж по id или названию («яндекс плюс», «интернет»)."""
    with session() as s:
        if isinstance(query, int) or str(query).isdigit():
            return s.get(Recurring, int(query))
        r = s.exec(select(Recurring).where(Recurring.active == True, icontains(Recurring.title, str(query)))).first()  # noqa: E712
        if r:
            return r
        from .match import best
        return best(s.exec(select(Recurring).where(Recurring.active == True)).all(), str(query), min_score=0.66)  # noqa: E712


def stop_recurring(rid: int) -> Recurring | None:
    with session() as s:
        r = s.get(Recurring, rid)
        if not r:
            return None
        r.active = False
        s.add(r)
        remember(s, "finance", f"Регулярный платёж «{r.title}» остановлен", "recurring", r.id)
        s.commit(); s.refresh(r)
        return r


def find_account(query: str) -> Account | None:
    """«сбер» → «Сбер», «наличка/кэш» → «Наличные», «основной/главный» → основной счёт."""
    q = (query or "").strip().lower()
    if not q:
        return None
    with session() as s:
        accs = list(s.exec(select(Account)))
    if q in ("основной", "главный", "основную", "главную", "карта", "карту"):
        return next((a for a in accs if a.is_main), None)
    if q in ("наличные", "наличка", "налички", "наличными", "кэш", "кеш", "нал", "cash"):
        return next((a for a in accs if a.kind == "cash"), None)
    for a in accs:
        if a.name.lower() == q:
            return a
    for a in accs:
        if q in a.name.lower() or a.name.lower() in q:
            return a
    from .match import best
    return best(accs, q, key=lambda a: a.name, min_score=0.66)


def spent_by(category: str | None = None, days: int | None = None, since: datetime | None = None, until: datetime | None = None) -> dict:
    """Сколько потрачено: по категории и/или за период. Возвращает {"total", "count", "by_category", "days"}."""
    now_ = datetime.now()
    if since is None:
        since = now_ - timedelta(days=days or 30)
    with session() as s:
        q = select(Transaction).where(Transaction.kind == "expense", Transaction.date >= since)
        if until:
            q = q.where(Transaction.date < until)
        txs = list(s.exec(q))
    if category:
        cat_l = category.lower()
        txs = [t for t in txs if (t.category or "").lower() == cat_l]
    by_cat: dict[str, float] = {}
    for t in txs:
        by_cat[t.category or "Другое"] = by_cat.get(t.category or "Другое", 0) + t.amount
    return {"total": sum(t.amount for t in txs), "count": len(txs),
            "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])), "since": since, "until": until}


def category_by_word(word: str, kind: str = "expense") -> Category | None:
    """«еда/еду/продукты/такси» → категория (по имени или ключевым словам)."""
    w = (word or "").strip().lower().replace("ё", "е")
    if len(w) < 3:
        return None
    from .match import same
    with session() as s:
        cats = list(s.exec(select(Category).where(Category.kind == kind)))
    for c in cats:
        if c.name.lower().replace("ё", "е") == w:
            return c
    for c in cats:
        if same(c.name, w):
            return c
    for c in cats:
        for kw in filter(None, (c.keywords or "").lower().replace("ё", "е").split(",")):
            kw = kw.strip()
            if kw and (kw == w or (" " not in kw and len(kw) >= 3 and same(kw, w))):
                return c
    return None


def list_recurring(active_only: bool = True) -> list[Recurring]:
    with session() as s:
        q = select(Recurring)
        if active_only:
            q = q.where(Recurring.active == True)  # noqa: E712
        return list(s.exec(q.order_by(Recurring.next_date)))


def _next_date(day: int, period: str, after: datetime | None = None) -> datetime:
    base = (after or datetime.now()).replace(hour=10, minute=0, second=0, microsecond=0)
    if period == "weekly":
        delta = (day - base.weekday()) % 7 or 7
        return base + timedelta(days=delta)
    if period == "yearly":
        cand = base.replace(day=min(day, 28))
        return cand if cand > base else cand + relativedelta(years=1)
    # monthly
    last_day = (base.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).day
    cand = base.replace(day=min(day, last_day))
    if cand <= base:
        nxt = base + relativedelta(months=1)
        last_day = (nxt.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).day
        cand = nxt.replace(day=min(day, last_day))
    return cand


def upcoming_payments(days: int = 7) -> list[Recurring]:
    until = datetime.now() + timedelta(days=days)
    return [r for r in list_recurring() if r.next_date <= until]


def process_due_recurring() -> list[Recurring]:
    """Провести регулярные платежи, у которых наступила дата."""
    done: list[Recurring] = []
    with session() as s:
        for r in s.exec(select(Recurring).where(Recurring.active == True, Recurring.next_date <= datetime.now())).all():  # noqa: E712
            if r.debt_id:
                try:
                    pay_debt(r.debt_id, r.amount, auto=True, account=r.account)
                except FinanceError:
                    pass  # долг уже закрыт — просто гасим регулярный
            else:
                add_transaction(r.amount, r.kind, r.category, f"{r.title} (авто)", r.account, source="system")
            r.next_date = _next_date(r.day, r.period, r.next_date)
            s.add(r)
            done.append(r)
        s.commit()
    return done


# ---------- долги ----------
def add_debt(title: str, total: float, payment: float = 0, rate: float = 0, pay_day: int = 1,
             creditor: str | None = None, remaining: float | None = None) -> Debt:
    title = _title(title)
    total = _num(total, "Сумма долга", 0, strict_min=True)
    remaining = total if remaining in (None, "") else _num(remaining, "Остаток", 0, total)
    payment = _num(payment or 0, "Платёж", 0)
    if payment > total:
        raise FinanceError(f"Платёж {money(payment)} больше самого долга {money(total)}")
    rate = _rate(rate)
    pay_day = _day(pay_day)
    with session() as s:
        d = Debt(title=title, creditor=creditor, total=total, remaining=remaining,
                 payment=payment, rate=rate, pay_day=pay_day)
        s.add(d)
        s.commit()
        s.refresh(d)
        remember(s, "finance", f"Долг: «{title}» {money(d.remaining)}" + (f", платёж {money(payment)}/мес" if payment else ""), "debt", d.id)
        log_action(s, "add_debt", "debt", d.id, title)
        s.commit()
    if payment:
        add_recurring(f"Платёж: {title}", payment, pay_day, "expense", "Долги", debt_id=d.id)
    return d


def list_debts(include_closed: bool = False) -> list[Debt]:
    with session() as s:
        q = select(Debt)
        if not include_closed:
            q = q.where(Debt.closed == False)  # noqa: E712
        return list(s.exec(q))


def find_debt(debt_id_or_title: int | str) -> Debt | None:
    with session() as s:
        if isinstance(debt_id_or_title, int) or str(debt_id_or_title).isdigit():
            return s.get(Debt, int(debt_id_or_title))
        d = s.exec(select(Debt).where(Debt.closed == False, icontains(Debt.title, debt_id_or_title))).first()  # noqa: E712
        if d:
            return d
        from .match import best
        return best(s.exec(select(Debt).where(Debt.closed == False)).all(), str(debt_id_or_title), min_score=0.66)  # noqa: E712


def pay_debt(debt_id_or_title: int | str, amount: float, auto: bool = False,
             account: str | None = None, source: str = "tg", date: datetime | None = None) -> Debt | None:
    """Платёж по долгу: уменьшает остаток И создаёт трату «Долги» (одна операция, связанная с долгом).
    Нельзя внести больше остатка и нельзя платить по закрытому долгу."""
    d = find_debt(debt_id_or_title)
    if not d:
        return None
    if d.closed or d.remaining <= 0:
        raise FinanceError(f"Долг «{d.title}» уже закрыт")
    if auto:
        amount = min(float(amount), d.remaining)  # финальный платёж бывает меньше обычного
    amount = _num(amount, "Платёж", 0, max_=d.remaining, strict_min=True)
    add_transaction(amount, "expense", "Долги", f"Платёж: {d.title}" + (" (авто)" if auto else ""),
                    account, source="system" if auto else source, date=date, debt_id=d.id)
    with session() as s:
        d = s.get(Debt, d.id)
        d.remaining = round(max(0.0, d.remaining - amount), 2)
        if d.remaining == 0:
            d.closed = True
            for r in s.exec(select(Recurring).where(Recurring.debt_id == d.id)).all():
                r.active = False; s.add(r)
        s.add(d)
        remember(s, "finance", f"Платёж по долгу «{d.title}»: {money(amount)}, остаток {money(d.remaining)}" + (" · закрыт 🎉" if d.closed else ""), "debt", d.id)
        s.commit()
        s.refresh(d)
        return d


def debt_payments(debt_id: int) -> list[Transaction]:
    with session() as s:
        return list(s.exec(select(Transaction).where(Transaction.debt_id == debt_id).order_by(Transaction.date.desc())))


def update_debt(debt_id: int, **fields) -> Debt:
    """Правка долга с проверками: остаток ≤ суммы, платёж ≤ остатка, день 1–31. Связанный регулярный платёж обновляется."""
    with session() as s:
        d = s.get(Debt, debt_id)
        if not d:
            raise FinanceNotFound("Долг не найден")
        if fields.get("title") is not None:
            d.title = _title(fields["title"])
        if fields.get("creditor") is not None:
            d.creditor = fields["creditor"].strip() or None
        if fields.get("total") is not None:
            d.total = _num(fields["total"], "Сумма долга", 0, strict_min=True)
        if fields.get("remaining") is not None:
            d.remaining = _num(fields["remaining"], "Остаток", 0, d.total)
        elif d.remaining > d.total:
            raise FinanceError(f"Остаток {money(d.remaining)} больше новой суммы долга — сначала поправьте остаток")
        if fields.get("payment") is not None:
            d.payment = _num(fields["payment"], "Платёж", 0)
        if fields.get("rate") is not None:
            d.rate = _rate(fields["rate"])
        if fields.get("pay_day") is not None:
            d.pay_day = _day(fields["pay_day"])
        if d.payment > d.total:
            raise FinanceError(f"Платёж {money(d.payment)} больше самого долга {money(d.total)}")
        if fields.get("closed") is not None:
            d.closed = bool(fields["closed"])
            if d.closed:
                d.remaining = 0.0
        if d.remaining <= 0:
            d.closed = True
        elif fields.get("closed") is None:
            d.closed = False
        s.add(d)
        # синхронизируем регулярный платёж
        rec = s.exec(select(Recurring).where(Recurring.debt_id == d.id)).first()
        if d.payment > 0 and not d.closed:
            if rec:
                rec.amount = d.payment; rec.day = d.pay_day; rec.title = f"Платёж: {d.title}"; rec.active = True
                rec.next_date = _next_date(d.pay_day, "monthly")
                s.add(rec)
            else:
                s.add(Recurring(title=f"Платёж: {d.title}", amount=d.payment, kind="expense", category="Долги",
                                period="monthly", day=d.pay_day, next_date=_next_date(d.pay_day, "monthly"), debt_id=d.id))
        elif rec:
            rec.active = False; s.add(rec)
        remember(s, "finance", f"Долг «{d.title}» обновлён: остаток {money(d.remaining)}, платёж {money(d.payment)}", "debt", d.id)
        s.commit(); s.refresh(d)
        return d


def delete_debt(debt_id: int) -> bool:
    """Удаляет долг и его регулярный платёж. Проведённые платежи (операции) остаются в истории."""
    with session() as s:
        d = s.get(Debt, debt_id)
        if not d:
            return False
        for r in s.exec(select(Recurring).where(Recurring.debt_id == d.id)).all():
            s.delete(r)
        for t in s.exec(select(Transaction).where(Transaction.debt_id == d.id)).all():
            t.debt_id = None; s.add(t)
        remember(s, "finance", f"Долг «{d.title}» удалён", "debt", d.id)
        s.delete(d); s.commit()
        return True


def debt_forecast(d: Debt) -> dict:
    """Через сколько месяцев закроется и сколько переплата."""
    paid = max(0.0, d.total - d.remaining)
    if d.remaining <= 0:
        return {"months": 0, "close_date": None, "overpay": 0, "progress": 1.0, "paid": paid}
    if d.payment <= 0:
        return {"months": None, "close_date": None, "overpay": None, "progress": 1 - d.remaining / d.total if d.total else 0, "paid": paid}
    r = d.rate / 100 / 12
    if r > 0:
        if d.payment <= d.remaining * r:
            return {"months": None, "close_date": None, "overpay": None, "progress": 1 - d.remaining / d.total, "paid": paid,
                    "warning": "Платёж меньше процентов — долг не уменьшается"}
        months = math.ceil(-math.log(1 - d.remaining * r / d.payment) / math.log(1 + r))
    else:
        months = math.ceil(d.remaining / d.payment)
    close = datetime.now() + relativedelta(months=months)
    return {"months": months, "close_date": close.strftime("%d.%m.%Y"),
            "overpay": max(0.0, months * d.payment - d.remaining), "paid": paid,
            "progress": 1 - d.remaining / d.total if d.total else 0}
