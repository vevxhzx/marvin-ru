"""Демо-данные для первого запуска: пустая база → правдоподобный пример, который можно стереть целиком.

Зачем
-----
Новичок ставит Marvin, открывает сайт — а база пустая: задач нет, денег нет, календарь пуст,
бот отвечает «не нашёл данных», и ценность продукта не видна. Фича: одна кнопка «загрузить
пример данных» кладёт в базу связный правдоподобный мир (счёт с деньгами, три недели трат,
задачи — включая просроченную, события на сегодня и завтра, клиенты с заказами, долг,
две цели, пара мыслей), рядом — кнопка «очистить и начать с нуля».

Безопасность — главное свойство модуля
--------------------------------------
Демо и реальные данные обязаны быть НЕРАЗДЕЛИМЫ ПОСЛЕ СЛИЯНИЯ, а очистка не должна съесть
реальное. Поэтому принадлежность к демо определяется МАРКЕРОМ, а не догадкой «похоже на
заголовок»:

1. **Колонка `source`.** Там, где она есть (transaction, task, event, order, note), каждая
   демо-строка записана с `source = "demo"` — это ровно то же поле, которым помечается канал
   («tg»/«web»/«voice»/«system»), поэтому демо проходит через обычные сервисы и не выделяется.
2. **Манифест в `setting`.** Ключ `demo:manifest` (JSON) хранит, ЧТО и с какими id создано.
   Таблицы без колонки `source` (account, client, debt, goal) в манифесте лежат как
   `{id, точное имя}` — сверка по точному равенству, а не по похожести заголовка.
3. **Правило удаления — конъюнкция:** строка удаляется, только если её `id` есть в манифесте
   И маркер совпал (`source == "demo"` либо точное имя из манифеста). Двойная проверка
   специально: id в SQLite переиспользуются, поэтому одной проверки «id в манифесте»
   было бы мало — если демо-строку удалили руками, её номер мог бы достаться новой записи.
4. **Охрана ссылок.** Счёт/долг/цель/клиент не удаляются, если на них ссылаются НЕ-демо
   строки (например, пользователь завёл свою трату на демо-счёте) — счёт останется, очистка
   скажет об этом в `kept`, данные целы.
5. **Балансы.** Деньги заводятся только демо-операциями, а не прямым `set_balance`: удаление
   операции через `finance.delete_transaction` откатывает сдвиг баланса ровно на ту же сумму,
   поэтому реальные счета после очистки имеют ровно те балансы, что до неё.
6. **Откат частичного сида.** Если посреди загрузки что-то упало, всё, что успело создаться,
   тут же удаляется через тот же `clear_demo` — полупустой «демо» не остаётся.
7. **Идемпотентность.** `clear_demo()` на пустой базе, без манифеста и после ручного удаления
   части демо — не ошибка; повторный вызов не удаляет ничего лишнего. `seed_demo()` при уже
   загруженном демо тоже ничего не пишет (кнопку можно жать дважды).

Что НЕ делается и почему
------------------------
* **Регулярные платежи (Recurring) не создаются.** Их проводит планировщик
  `finance.process_due_recurring()` с `source="system"` — вне нашего маркера. Через месяц-два
  такие авто-платежи пережили бы очистку и остались бы в базе «призраками». Планы платежей
  показываем через `finance.update_debt(payment=…)` — цифра есть, регулярки нет.
* **Категории не создаются** — берём стандартные из `init_db` (`category.name` unique,
  дубль всё равно не прошёл бы, но лишняя проверка не нужна). `account.name` тоже unique,
  поэтому демо-счёт создаётся один раз и переиспользуется при повторном сиде.
* **Никаких сырых INSERT в таблицы.** Всё создаётся сервисами (`finance`, `tasks`,
  `calendar`, `orders`, `goals`, `brain_notes`), поэтому демо проходит ту же проверку и ту же
  логику, что и живые данные, и не разойдётся с ними при будущих изменениях.

Публичный API
-------------
* `seed_demo() -> dict`   — загрузить пример; возвращает сводку «что создано».
* `clear_demo() -> dict`  — удалить ТОЛЬКО демо; возвращает, что удалено и что оставлено.
* `demo_status() -> dict` — состояние базы (`empty` / `demo` / `mixed` / `own`) для UI.

HTTP: `core/api/routers/demo.py` (`POST /api/demo/seed`, `POST /api/demo/clear`,
`GET /api/demo/status`). Авторизация — общая (`core/api/auth.py`).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from ..db import (
    Account,
    ActionLog,
    Client,
    Debt,
    Event,
    Goal,
    Memory,
    Note,
    Order,
    Task,
    Transaction,
    get_setting,
    now,
    session,
    set_setting,
)
from ..db import select
from . import brain_notes, calendar as cal, finance, goals, orders, tasks

log = logging.getLogger("jarvis.demo")

# ------------------------------------------------------------------ маркеры и настройки
DEMO_SOURCE = "demo"            # значение колонки source у всех демо-строк
MANIFEST_KEY = "demo:manifest"  # ключ в setting: что именно мы создали
MANIFEST_VERSION = 1
DEMO_ACCOUNT = "Демо-карта"     # видимая пометка: счёт с демо-деньгами называется прямо так

# таблицы, у которых есть колонка source — принадлежность проверяется по ней
SOURCE_TABLES = ("transaction", "task", "event", "order", "note")
# таблицы без source — принадлежность проверяется по точному имени из манифеста
NAME_TABLES = {"client": "name", "account": "name", "debt": "title", "goal": "title"}
# по чему решаем, «база пустая или нет». Счета и категории, которые завёл сам `init_db`
# (основной счёт, «Наличные», справочник категорий), данными пользователя не считаются.
CONTENT_TABLES = ("transaction", "task", "event", "order", "client", "goal", "debt", "note")

MODELS = {
    "transaction": Transaction, "task": Task, "event": Event, "order": Order, "note": Note,
    "client": Client, "account": Account, "debt": Debt, "goal": Goal,
}
# падежи для сводок и подписей: (одна, несколько, много)
TABLE_FORMS = {
    "transaction": ("операция", "операции", "операций"),
    "task": ("задача", "задачи", "задач"),
    "event": ("встреча", "встречи", "встреч"),
    "client": ("клиент", "клиента", "клиентов"),
    "order": ("заказ", "заказа", "заказов"),
    "goal": ("цель", "цели", "целей"),
    "debt": ("долг", "долга", "долгов"),
    "note": ("мысль", "мысли", "мыслей"),
    "account": ("счёт", "счёта", "счетов"),
}


# ------------------------------------------------------------------ манифест
def _manifest() -> dict | None:
    """Разобранный манифест демо (None — демо не загружали)."""
    raw = get_setting(MANIFEST_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("манифест демо битый — считаем, что демо нет")
        return None
    if not isinstance(data, dict) or data.get("version") != MANIFEST_VERSION:
        return None
    data.setdefault("rows", {})
    return data


def _save_manifest(m: dict) -> None:
    set_setting(MANIFEST_KEY, json.dumps(m, ensure_ascii=False))


def _drop_manifest() -> None:
    set_setting(MANIFEST_KEY, None)


def _rec(m: dict, table: str, row_id: int | None, **extra) -> None:
    """Запомнить созданную строку в манифесте."""
    if row_id is None:
        return
    m["rows"].setdefault(table, []).append({"id": int(row_id), **extra})


def _rows_of(m: dict, table: str) -> list[dict]:
    return [r for r in m.get("rows", {}).get(table, []) if isinstance(r, dict) and "id" in r]


# ------------------------------------------------------------------ принадлежность к демо
def _is_demo_row(table: str, row_id: int, rec: dict) -> bool:
    """Маркер совпал? Обе проверки обязательны: id в манифесте И признак demo."""
    model = MODELS.get(table)
    if model is None:
        return False
    with session() as s:
        obj = s.get(model, row_id)
        if obj is None:
            return False
        if table in SOURCE_TABLES:
            return getattr(obj, "source", "") == DEMO_SOURCE
        field = NAME_TABLES.get(table)
        return bool(field) and (getattr(obj, field, None) or "") == rec.get(field, "\0нет")


def _present(m: dict) -> set[tuple[str, int]]:
    """Какие демо-строки ещё живы (остальное пользователь удалил руками)."""
    out: set[tuple[str, int]] = set()
    for table in MODELS:
        for rec in _rows_of(m, table):
            if _is_demo_row(table, rec["id"], rec):
                out.add((table, rec["id"]))
    return out


def _real_counts() -> dict[str, int]:
    """Сколько строк в базе НЕ демо (то, что принадлежит человеку)."""
    m = _manifest()
    demo_ids: dict[str, set[int]] = {}
    for table in MODELS:
        demo_ids[table] = {rec["id"] for rec in _rows_of(m or {}, table)}
    out = {}
    for table, model in MODELS.items():
        with session() as s:
            rows = list(s.exec(select(model)).all())
        if table == "debt":
            # мягко удалённый долг — уже не «мои данные», он просто ждёт возврата
            rows = [r for r in rows if getattr(r, "deleted_at", None) is None]
        out[table] = sum(1 for row in rows if row.id not in demo_ids[table])
    return out


# ------------------------------------------------------------------ очистка
def _delete_transactions(ids: list[int]) -> None:
    for tx_id in ids:
        try:
            finance.delete_transaction(tx_id)
        except Exception as e:  # pragma: no cover — вернуть деньги не получилось, строку всё равно убираем
            log.warning("демо-операция %s не удалилась: %s", tx_id, e)
            with session() as s:
                t = s.get(Transaction, tx_id)
                if t is not None:
                    s.delete(t)
                    s.commit()


def _foreign_refs(table: str, row_id: int, rec: dict) -> str | None:
    """На демо-строку ссылаются чужие (не-демо) записи? → вернуть причину, иначе None."""
    if table == "account":
        name = rec.get("name", "")
        with session() as s:
            for t in s.exec(select(Transaction)).all():
                if t.source == DEMO_SOURCE:
                    continue
                if t.account == name or t.to_account == name:
                    return f"на счёте «{name}» есть ваши операции"
    elif table == "debt":
        with session() as s:
            for t in s.exec(select(Transaction)).all():
                if t.source != DEMO_SOURCE and t.debt_id == row_id:
                    return "по долгу есть ваши платежи"
            if any(a.debt_id == row_id for a in s.exec(select(Account)).all()):
                return "долг привязан к вашему счёту"
    elif table == "goal":
        with session() as s:
            if any(t.source != DEMO_SOURCE and t.goal_id == row_id for t in s.exec(select(Transaction)).all()):
                return "в конверт уже клали свои деньги"
    elif table == "client":
        with session() as s:
            if any(o.source != DEMO_SOURCE and o.client_id == row_id for o in s.exec(select(Order)).all()):
                return "у клиента есть ваши заказы"
    return None


def _clean_journal(m: dict, seeded_at: str | None) -> int:
    """Убрать записи журнала/отмен, которые ссылаются на демо-строки.

    Отсечка по времени сида: чужую строку журнала (пользователь что-то сделал со своей записью)
    это не заденет — у неё другой ref_id.
    """
    pairs: list[tuple[str, int]] = []
    for table in MODELS:
        for rec in _rows_of(m, table):
            pairs.append((table, rec["id"]))
    if not pairs:
        return 0
    n = 0
    with session() as s:
        for table, row_id in pairs:
            for mem in s.exec(select(Memory).where(Memory.ref_table == table, Memory.ref_id == row_id)).all():
                if seeded_at and mem.created_at.isoformat() < seeded_at:
                    continue
                s.delete(mem)
                n += 1
        for table, row_id in pairs:
            for al in s.exec(select(ActionLog).where(ActionLog.ref_table == table, ActionLog.ref_id == row_id)).all():
                if seeded_at and al.created_at.isoformat() < seeded_at:
                    continue
                s.delete(al)
                n += 1
        s.commit()
    return n


def clear_demo() -> dict:
    """Удалить ТОЛЬКО демо-данные. Идемпотентно и безопасно на любой базе.

    Возвращает:
      ok       — True (ошибок быть не может: чистим по манифесту и по маркеру);
      removed  — {"transaction": 14, …}: сколько строк снято по таблицам;
      kept     — список строк: что НЕ удалили и почему (например, счёт с вашими тратами);
      message  — короткая строка для UI.
    """
    m = _manifest()
    if not m:
        return {"ok": True, "removed": {}, "kept": [], "message": "Демо-данных в базе нет — удалять нечего."}

    seeded_at = m.get("seeded_at")
    removed: dict[str, int] = {}
    kept: list[str] = []

    def _bump(table: str) -> None:
        removed[table] = removed.get(table, 0) + 1

    # 1) операции — первыми: их удаление возвращает деньги на счета и снимает связи с долгом/целью/заказом
    for rec in _rows_of(m, "transaction"):
        if _is_demo_row("transaction", rec["id"], rec):
            _delete_transactions([rec["id"]])
            if not _exists("transaction", rec["id"]):
                _bump("transaction")
    # 2) прочее, что можно снести безусловно
    for table, deleter in (("task", tasks.delete_task), ("event", cal.delete_event),
                           ("order", orders.delete_order), ("note", brain_notes.delete_note)):
        for rec in _rows_of(m, table):
            if not _is_demo_row(table, rec["id"], rec):
                continue
            try:
                deleter(rec["id"])
            except Exception as e:  # pragma: no cover
                log.warning("демо-%s %s не удалился: %s", table, rec["id"], e)
            if not _exists(table, rec["id"]):
                _bump(table)
    # 3) сущности без колонки source — только если на них никто не ссылается
    for table in ("debt", "goal", "client", "account"):
        for rec in _rows_of(m, table):
            if not _is_demo_row(table, rec["id"], rec):
                continue
            reason = _foreign_refs(table, rec["id"], rec)
            if reason:
                one = TABLE_FORMS.get(table, (table,))[0]
                kept.append(f"{one} «{_name_of(table, rec)}» — {reason}")
                continue
            deleter = {"debt": lambda i: finance.delete_debt(i, soft=False), "goal": goals.delete_goal,
                       "client": orders.delete_client, "account": finance.delete_account}[table]
            try:
                deleter(rec["id"])
            except Exception as e:  # pragma: no cover
                log.warning("демо-%s %s не удалился: %s", table, rec["id"], e)
            if not _exists(table, rec["id"]):
                _bump(table)

    journal = _clean_journal(m, seeded_at)
    if journal:
        removed["журнал"] = journal
    _drop_manifest()

    total = sum(v for k, v in removed.items() if k != "журнал")
    message = (f"Демо-данные удалены: {total} записей. Ваши данные не тронуты."
               if total else "Демо-данных в базе уже не было.")
    if kept:
        message += " Оставлено: " + "; ".join(kept) + "."
    return {"ok": True, "removed": removed, "kept": kept, "message": message}


def _exists(table: str, row_id: int) -> bool:
    model = MODELS.get(table)
    if model is None:
        return False
    with session() as s:
        return s.get(model, row_id) is not None


def _name_of(table: str, rec: dict) -> str:
    field = NAME_TABLES.get(table, "title")
    return rec.get(field) or rec.get("name") or rec.get("title") or "?"


# ------------------------------------------------------------------ демо-мир
DEMO_SPEND = (
    # (дней назад, "ЧЧ:ММ", сумма, категория, заметка)
    (18, "15:00", 1_500, "Транспорт", "Парковка у клиента"),
    (14, "09:30", 7_800, "Транспорт", "Шиномонтаж"),
    (12, "20:15", 1_240, "Еда", "Ужин с Настей"),
    (9, "11:00", 3_990, "Одежда", "Кроссовки на смену"),
    (7, "16:20", 2_450, "Здоровье", "Аптека: витамины и бинты"),
    (5, "10:05", 299, "Подписки", "Подписка на музыку"),
    (4, "21:00", 599, "Развлечения", "Кино с Димой"),
    (3, "12:30", 890, "Еда", "Обед с командой"),
    (2, "19:45", 1_180, "Транспорт", "Такси до клиента"),
    (1, "13:20", 640, "Еда", "Продукты — ВкусВилл"),
    (1, "09:10", 320, "Еда", "Кофе с собой"),
)
DEMO_INCOME = (
    (21, "10:00", 85_000, "Зарплата", "Аванс за месяц"),
)
DEMO_CLIENTS = (
    # (клиент, заказ, цена, статус, срок через N дней, часов, заметка, оплачен ли)
    ("Пятёрочка", "Ролик для полки «Пекарня»", 65_000, "work", 3, 18.0,
     "Второй круг правок, срок горит — макеты придут завтра", False),
    ("Лампа", "Айдентика: ролик на тридцать секунд", 45_000, "done", -6, 12.0, "Сдано, ждём оплату", True),
    ("ВкусВилл", "Серия карточек для приложения", 30_000, "new", 9, 8.0, "ТЗ пришло, смету ещё не считали", False),
)
DEMO_DEBT = ("Кредит на технику", 144_000, 72_000, 14.9, "Т-Банк")
DEMO_GOALS = (
    # (название, цель, отложено, срок через N дней, иконка)
    ("Подушка на четыре месяца", 300_000, 96_000, 150, "🛟"),
    ("Новый монитор для монтажа", 45_000, 18_000, 45, "🖥"),
)
DEMO_NOTES = (
    ("Это демо-данные: счёт, траты, задачи, встречи, клиенты и цели — всё выдумано, "
     "чтобы было видно, как Marvin считает деньги и держит дела. "
     "Кнопка «очистить и начать с нуля» удалит только их — ваши записи останутся целы.",
     ["демо"]),
    ("Идея ролика для Пятёрочки: тёплый свет, хлеб крупным планом, без единого слова — "
     "только байка за тридцать секунд.", ["работа"]),
)


def _at(ref: datetime, days: int, hhmm: str, past: bool = True) -> datetime:
    hh, mm = (int(x) for x in hhmm.split(":"))
    base = ref - timedelta(days=days) if past else ref + timedelta(days=days)
    return base.replace(hour=hh, minute=mm, second=0, microsecond=0)


def _today_slot(ref: datetime, hhmm: str, bump: int = 0) -> datetime:
    """Сегодня в указанное время; если время уже прошло — сдвигаем на час вперёд, чтобы встреча была в сегодняшнем дне."""
    dt = _at(ref, 0, hhmm)
    if dt < ref:
        dt = ref + timedelta(hours=1, minutes=15 * bump)
    return dt.replace(second=0, microsecond=0)


# ------------------------------------------------------------------ сид по доменам
def _seed_account(m: dict) -> str:
    """Демо-деньги всегда живут на отдельном счёте — так их не спутать со своими деньгами.

    Ищем ТОЧНЫМ совпадением имени, а не через `finance.find_account`: тот ищет нечётко
    («демо-карта» нашёл бы счёт «Демо»), и демо-траты уехали бы в чужой счёт.
    В манифест попадает только созданный нами счёт: чужой «Демо-карта» переживёт очистку,
    демо просто поживёт на нём и уйдёт вместе со своими операциями.
    """
    accounts = finance.list_accounts()
    existed = {a.name for a in accounts}
    acc = next((a for a in accounts if a.name == DEMO_ACCOUNT), None)
    if acc is None:
        acc = finance.add_account(DEMO_ACCOUNT, "bank", 0)
    if acc.name == DEMO_ACCOUNT and DEMO_ACCOUNT not in existed:
        _rec(m, "account", acc.id, name=acc.name)
    return acc.name


def _seed_clients_orders(m: dict, ref: datetime) -> list[int]:
    """Клиенты и заказы. Возвращает id заказов, по которым уже пришли деньги (оплаченные)."""
    paid: list[int] = []
    for name, title, price, status, deadline_days, hours, notes, got_paid in DEMO_CLIENTS:
        existed = {c.name for c in orders.list_clients()}
        c = orders.get_or_create_client(name, kind="client")
        # в манифест — только клиент, которого завели мы (точное имя + его не было до сида):
        # чужого «Пятёрочку» удалять при очистке нельзя
        if c is not None and c.name == name and name not in existed:
            _rec(m, "client", c.id, name=c.name)
        o = orders.add_order(title, price, client=name, deadline=_at(ref, deadline_days, "18:00", past=deadline_days > 0),
                             notes=notes, estimate_h=hours, status=status, source=DEMO_SOURCE)
        _rec(m, "order", o.id)
        if got_paid:
            paid.append(o.id)
    return paid


def _seed_finance(m: dict, account: str, paid_orders: list[int], ref: datetime) -> None:
    for days, hhmm, amount, category, note in DEMO_INCOME:
        t = finance.add_transaction(amount, "income", category, note, account=account,
                                    date=_at(ref, days, hhmm), source=DEMO_SOURCE)
        _rec(m, "transaction", t.id)
    for oid in paid_orders:                      # оплата сданного заказа — доход, привязанный к заказу
        o = orders.get_order(oid)
        t = orders.add_payment(oid, o.price, account=account, source=DEMO_SOURCE, date=_at(ref, 6, "12:00"))
        _rec(m, "transaction", t.id)
    for days, hhmm, amount, category, note in DEMO_SPEND:
        t = finance.add_transaction(amount, "expense", category, note, account=account,
                                    date=_at(ref, days, hhmm), source=DEMO_SOURCE)
        _rec(m, "transaction", t.id)


def _seed_debt(m: dict, account: str, ref: datetime) -> None:
    """Долг: остаток меньше изначальной суммы + состоявшийся платёж — видно, как считается долг.

    Плана платежей сознательно нет: `add_debt(payment=…)` и `update_debt(payment=…)` заводят
    `Recurring`, а её потом проводит планировщик с `source="system"` — вне нашего маркера, и такие
    авто-платежи пережили бы очистку. Цифры остатка вполне хватает, чтобы демо было живым.
    """
    title, total, remaining, rate, creditor = DEMO_DEBT
    d = finance.add_debt(title, total, payment=0, rate=rate, creditor=creditor, remaining=remaining,
                         source=DEMO_SOURCE)
    _rec(m, "debt", d.id, title=d.title)
    finance.pay_debt(d.id, 12_000, account=account, source=DEMO_SOURCE, date=_at(ref, 10, "09:00"))
    with session() as s:   # платёж создаётся внутри pay_debt — забираем его в манифест
        for t in s.exec(select(Transaction).where(Transaction.debt_id == d.id)).all():
            if t.source == DEMO_SOURCE:
                _rec(m, "transaction", t.id)


def _seed_goals(m: dict, ref: datetime) -> None:
    for title, target, saved, due_days, icon in DEMO_GOALS:
        g = goals.add_goal(title, target, due=_at(ref, due_days, "12:00", past=False),
                           saved=saved, icon=icon, source=DEMO_SOURCE)
        _rec(m, "goal", g.id, title=g.title)


def _seed_tasks(m: dict, ref: datetime) -> None:
    plan = (
        # (название, срок, приоритет, проект, закрыта ли сразу)
        ("Забрать макеты у дизайнера", _at(ref, 3, "17:00"), 1, "Работа", False),
        ("Скинуть черновик ролика для Пятёрочки", _today_slot(ref, "18:00"), 1, "Работа", False),
        ("Оплатить интернет и продлить домен", _at(ref, 1, "10:00", past=False), 2, "", False),
        ("Посчитать смету на серию карточек", _at(ref, 2, "15:00", past=False), 2, "Работа", False),
        ("Отправить счёт за прошлый заказ", _at(ref, 6, "12:00"), 2, "", True),
        ("Обновить портфолио на Behance", None, 3, "", False),
    )
    for title, due, priority, project, done in plan:
        t = tasks.add_task(title, due=due, priority=priority, project=project or None, source=DEMO_SOURCE)
        _rec(m, "task", t.id)
        if done:
            tasks.update_task(t.id, done=True)


def _seed_calendar(m: dict, ref: datetime) -> None:
    plan = (
        # (название, начало, минут, место, повтор)
        ("Созвон с Пятёрочкой — правки по ролику", _today_slot(ref, "12:00"), 45, "Зум", ""),
        ("Тренировка", _today_slot(ref, "19:30", bump=1), 60, "Спортзал на Лесной", "weekly"),
        ("Сдача ролика «Лампа»", _at(ref, 1, "11:00", past=False), 60, None, ""),
        ("Встреча с ВкусВиллом по макетам", _at(ref, 4, "15:00", past=False), 90, "Кафе на Пятницкой", ""),
    )
    for title, start, minutes, location, repeat in plan:
        ev = cal.add_event(title, start, duration_min=minutes, location=location,
                           remind_minutes=30, source=DEMO_SOURCE, repeat=repeat)
        _rec(m, "event", ev.id)


def _seed_mind(m: dict) -> None:
    for text, tags in DEMO_NOTES:
        n = brain_notes.add_note(text, tags=tags, source=DEMO_SOURCE, polish=False)
        _rec(m, "note", n.id)


# ------------------------------------------------------------------ публичное API
def seed_demo() -> dict:
    """Загрузить пример данных в пустую (или почти пустую) базу.

    Возвращает:
      ok       — True/False;
      already  — демо было загружено раньше, ничего не писали;
      account  — счёт, на котором живут демо-деньги;
      created  — {"transaction": 14, "task": 6, …};
      total    — всего строк;
      message  — короткая строка для UI.
    """
    m = _manifest()
    if m and _present(m):
        counts = _counts(m)
        return {"ok": True, "already": True, "account": _demo_account_name(),
                "created": counts, "total": sum(counts.values()),
                "message": "Пример данных уже загружен — ничего не добавлял."}

    m = {"version": MANIFEST_VERSION, "seeded_at": now().isoformat(), "rows": {}}
    ref = now()
    try:
        account = _seed_account(m)
        paid_orders = _seed_clients_orders(m, ref)
        _seed_finance(m, account, paid_orders, ref)
        _seed_debt(m, account, ref)
        _seed_goals(m, ref)
        _seed_tasks(m, ref)
        _seed_calendar(m, ref)
        _seed_mind(m)
    except Exception as e:
        log.error("демо-данные не загрузились — откатываем то, что успели", exc_info=True)
        _save_manifest(m)          # чтобы clear_demo знал, что чистить
        try:
            clear_demo()
        except Exception:  # pragma: no cover
            log.error("откат демо не удался", exc_info=True)
            _drop_manifest()
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "message": "Не получилось загрузить пример данных. База осталась как была."}

    _save_manifest(m)
    counts = _counts(m)
    total = sum(counts.values())
    return {"ok": True, "already": False, "account": account,
            "created": counts, "total": total,
            "message": f"Пример данных загружен: {_phrase(counts)}. "
                       f"Это демо — можно стереть одной кнопкой."}


def _counts(m: dict) -> dict[str, int]:
    """Сколько строк создано (только те, что ещё живы)."""
    alive = _present(m)
    out: dict[str, int] = {}
    for table in MODELS:
        n = sum(1 for t, _i in alive if t == table)
        if n:
            out[table] = n
    return out


def _phrase(counts: dict[str, int]) -> str:
    """«14 операций, 6 задач, 4 встречи» — для сводок и подсказок UI."""
    from .plural import plural

    parts = []
    for table, words in TABLE_FORMS.items():
        n = counts.get(table, 0)
        if n:
            parts.append(f"{n} {plural(n, *words)}")
    return ", ".join(parts) or "ничего"


def _demo_account_name() -> str:
    """На каком счёте лежат демо-деньги (пусто — если счёт с таким именем был пользовательский)."""
    with session() as s:
        return DEMO_ACCOUNT if s.exec(select(Account).where(Account.name == DEMO_ACCOUNT)).first() else ""


def demo_status() -> dict:
    """Что сейчас в базе: пусто / демо / смешанное / свои данные. Нужно UI, чтобы решить, что показать."""
    m = _manifest()
    demo = _counts(m) if m else {}
    own = _real_counts()
    has_demo = bool(demo)
    own_total = sum(own.get(t, 0) for t in CONTENT_TABLES)
    if has_demo and own_total:
        state = "mixed"
        label = "Демо-данные и ваши записи"
    elif has_demo:
        state = "demo"
        label = "Загружены демо-данные"
    elif own_total:
        state = "own"
        label = "В базе ваши данные"
    else:
        state = "empty"
        label = "База пока пустая"
    return {
        "state": state,
        "has_demo": has_demo,
        "label": label,
        "seeded_at": (m or {}).get("seeded_at", ""),
        "demo": demo,
        "own": own,
        "total": sum(demo.values()) + sum(own.get(t, 0) for t in CONTENT_TABLES),
        "message": _status_message(state, demo, own),
    }


def _status_message(state: str, demo: dict, own: dict) -> str:
    if state == "empty":
        return "База пустая — загрузите пример данных, чтобы посмотреть, как всё работает."
    if state == "demo":
        return f"Сейчас в базе {_phrase(demo)} — это демо, а не ваши данные. Их можно очистить одной кнопкой."
    if state == "mixed":
        return (f"В базе {_phrase(demo)} (демо) и ваши записи. "
                "Кнопка очистки удалит только демо.")
    return "В базе ваши данные, демо не загружено."


def summary_text() -> str:
    """Строка для кнопки/подсказки в UI: что сейчас в базе."""
    return demo_status()["message"]