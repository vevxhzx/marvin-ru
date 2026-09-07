"""Одна база данных (SQLite) для всего: календарь, задачи, финансы, заметки, память."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

from sqlalchemy import event
from sqlmodel import Field, Session, SQLModel, create_engine, select

from .config import DB_PATH


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


# ---------- Календарь ----------
class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    start: datetime = Field(index=True)
    end: Optional[datetime] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    remind_minutes: int = 30
    reminded: bool = False
    source: str = "tg"                 # voice / tg / web
    google_id: Optional[str] = None    # для будущей синхронизации с Google
    created_at: datetime = Field(default_factory=now)
    # повторы: repeat = daily / weekly / monthly / yearly / '' ; repeat_days = "0,2,4" (пн,ср,пт) для weekly
    repeat: str = Field(default="", index=True)
    repeat_days: str = ""
    repeat_until: Optional[datetime] = None
    skip_dates: str = ""               # даты пропущенных повторов "2026-09-10,2026-09-17"
    reminded_for: str = ""             # для повторов: дата последнего напомненного повтора


# ---------- Задачи ----------
class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    done: bool = Field(default=False, index=True)
    priority: int = 2                  # 1 высокий, 2 обычный, 3 низкий
    due: Optional[datetime] = None
    project: Optional[str] = None
    source: str = "tg"
    remind_stage: int = 0              # 0 — не напоминали, 1 — утром в день дедлайна, 2 — за час
    created_at: datetime = Field(default_factory=now)
    done_at: Optional[datetime] = None


# ---------- Финансы ----------
class Account(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    kind: str = "bank"                 # bank / cash / debt_only
    balance: float = 0.0
    is_main: bool = False
    currency: str = "RUB"


class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    kind: str = "expense"              # expense / income
    icon: str = "•"
    keywords: str = ""                 # через запятую, для авто-категоризации
    budget: float = 0.0                # лимит в месяц, 0 = без лимита
    custom: bool = False               # создана пользователем


class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    amount: float                      # всегда положительное
    kind: str = Field(index=True)      # expense / income / transfer
    category: Optional[str] = Field(default=None, index=True)
    account: Optional[str] = None
    to_account: Optional[str] = None   # для переводов
    note: Optional[str] = None
    date: datetime = Field(default_factory=now, index=True)
    source: str = "tg"
    import_hash: Optional[str] = Field(default=None, unique=True)  # дедупликация при импорте выписок
    debt_id: Optional[int] = Field(default=None, index=True)       # если это платёж по долгу — чтобы откат был честным


class Recurring(SQLModel, table=True):
    """Регулярные платежи: подписки, аренда, платежи по кредитам."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    amount: float
    kind: str = "expense"              # expense / income
    category: Optional[str] = None
    account: Optional[str] = None
    period: str = "monthly"            # monthly / weekly / yearly
    day: int = 1                       # день месяца (или недели 0-6)
    next_date: datetime
    active: bool = True
    debt_id: Optional[int] = None      # если это платёж по долгу


class Debt(SQLModel, table=True):
    """Долги/кредиты: сколько, кому, платёж, когда закроется."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str                         # "Сбер кредит", "Долг Ване"
    creditor: Optional[str] = None
    total: float                       # изначальная сумма
    remaining: float                   # остаток
    rate: float = 0.0                  # годовая ставка, %
    payment: float = 0.0               # ежемесячный платёж
    pay_day: int = 1                   # день месяца
    closed: bool = False
    created_at: datetime = Field(default_factory=now)


# ---------- Второй мозг ----------
class Note(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str                          # приведённый к аккуратному виду текст
    title: Optional[str] = None        # короткий заголовок (делает LLM)
    raw: Optional[str] = None          # оригинал, как написал пользователь
    tags: str = ""                     # через запятую
    polished: bool = Field(default=False, index=True)
    image: Optional[str] = None        # картинка к мысли: относительный путь в data/media (фото из TG / с сайта)
    source: str = "tg"
    created_at: datetime = Field(default_factory=now, index=True)


class Link(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str
    polished: bool = Field(default=False, index=True)
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    domain: Optional[str] = None
    tags: str = ""
    comment: Optional[str] = None
    summary: Optional[str] = None      # выжимка страницы в 5 строк (локальная LLM)
    excerpt: Optional[str] = None      # первые ~4000 знаков текста страницы — сырьё для выжимки
    source: str = "tg"
    created_at: datetime = Field(default_factory=now, index=True)


class Memory(SQLModel, table=True):
    """Журнал: всё, что происходило. Лента «second brain»."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(index=True)      # event / task / finance / note / link / chat / system
    text: str
    ref_table: Optional[str] = None
    ref_id: Optional[int] = None
    channel: str = "tg"                # tg / voice / web / system
    created_at: datetime = Field(default_factory=now, index=True)


class Setting(SQLModel, table=True):
    """Ключ-значение: ожидающие уточнения, служебные флаги."""
    key: str = Field(primary_key=True)
    value: str = ""
    updated_at: datetime = Field(default_factory=now)


class ActionLog(SQLModel, table=True):
    """Что ассистент сделал по команде — чтобы «отмени» работало для чего угодно и переживало перезапуск."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str                          # add_event / add_task / add_expense / add_income / add_debt / add_note / add_link / add_recurring / pay_debt
    ref_table: str
    ref_id: int
    title: str = ""
    channel: str = "tg"
    undone: bool = False
    created_at: datetime = Field(default_factory=now, index=True)


class Embedding(SQLModel, table=True):
    """Векторы для смыслового поиска по заметкам/ссылкам (локальная модель через Ollama)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    ref_table: str = Field(index=True)
    ref_id: int = Field(index=True)
    model: str = ""
    vector: str = ""       # JSON-список чисел (раньше bytes — в SQLite это TEXT в любом случае)
    text_hash: str = ""


class ChatMessage(SQLModel, table=True):
    """История диалога (для контекста мозга)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    role: str                          # user / assistant
    text: str
    channel: str = "tg"
    created_at: datetime = Field(default_factory=now, index=True)


# ---------- Движок ----------
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
    # SQLite не умеет lower() для кириллицы — добавляем свою функцию
    dbapi_conn.create_function("ulower", 1, lambda v: v.lower() if isinstance(v, str) else v)


def icontains(column, query: str):
    """Регистронезависимый поиск подстроки (работает с кириллицей)."""
    from sqlalchemy import func
    return func.ulower(column).contains((query or "").lower())


DEFAULT_CATEGORIES = [
    ("Еда", "expense", "🍔", "еда,продукты,кафе,ресторан,обед,ужин,завтрак,кофе,доставка,пятёрочка,перекрёсток,вкусвилл,магнит"),
    ("Транспорт", "expense", "🚕", "такси,метро,автобус,бензин,заправка,яндекс go,каршеринг,проезд,парковка"),
    ("Жильё", "expense", "🏠", "аренда,квартира,коммуналка,жкх,свет,вода,интернет"),
    ("Подписки", "expense", "📱", "подписка,spotify,youtube,яндекс плюс,netflix,telegram premium,icloud"),
    ("Здоровье", "expense", "💊", "аптека,врач,лекарства,клиника,стоматолог,анализы"),
    ("Развлечения", "expense", "🎮", "кино,игра,бар,клуб,концерт,steam"),
    ("Одежда", "expense", "👕", "одежда,обувь,кроссовки,куртка,футболка"),
    ("Техника", "expense", "💻", "техника,телефон,ноутбук,наушники,ozon,wildberries,dns"),
    ("Долги", "expense", "💳", "кредит,долг,платёж,ипотека,рассрочка"),
    ("Другое", "expense", "📦", ""),
    ("Зарплата", "income", "💰", "зарплата,зп,аванс,оклад"),
    ("Фриланс", "income", "🧑‍💻", "фриланс,заказ,проект,клиент"),
    ("Прочий доход", "income", "🎁", "подарок,вернули,кэшбэк,кешбэк,возврат"),
]


def _migrate() -> None:
    """Добавляем новые колонки в старую базу, не теряя данные."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    wanted = {
        "note": {"title": "VARCHAR", "raw": "VARCHAR", "polished": "BOOLEAN DEFAULT 0", "image": "VARCHAR"},
        "link": {"polished": "BOOLEAN DEFAULT 0", "summary": "VARCHAR", "excerpt": "VARCHAR"},
        "transaction": {"debt_id": "INTEGER"},
        "event": {"repeat": "VARCHAR DEFAULT ''", "repeat_days": "VARCHAR DEFAULT ''", "repeat_until": "DATETIME",
                  "skip_dates": "VARCHAR DEFAULT ''", "reminded_for": "VARCHAR DEFAULT ''"},
        "task": {"remind_stage": "INTEGER DEFAULT 0"},
        "category": {"budget": "FLOAT DEFAULT 0", "custom": "BOOLEAN DEFAULT 0"},
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if table not in insp.get_table_names():
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for col, typ in cols.items():
                if col not in have:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {col} {typ}'))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate()
    from .config import cfg
    with Session(engine, expire_on_commit=False) as s:
        if s.exec(select(Category)).first() is None:
            for name, kind, icon, kw in DEFAULT_CATEGORIES:
                s.add(Category(name=name, kind=kind, icon=icon, keywords=kw))
        if s.exec(select(Account)).first() is None:
            main = str(getattr(getattr(cfg, "finance", None), "main_account", "") or "Основной")
            s.add(Account(name=main, kind="bank", is_main=True))
            s.add(Account(name="Наличные", kind="cash"))
        s.commit()


@contextmanager
def session() -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
        yield s


def remember(s: Session, kind: str, text: str, ref_table: str | None = None,
             ref_id: int | None = None, channel: str = "tg") -> None:
    s.add(Memory(kind=kind, text=text, ref_table=ref_table, ref_id=ref_id, channel=channel))


def get_setting(key: str, default: str | None = None) -> str | None:
    with Session(engine, expire_on_commit=False) as s:
        row = s.get(Setting, key)
        return row.value if row else default


def set_setting(key: str, value: str | None) -> None:
    with Session(engine, expire_on_commit=False) as s:
        row = s.get(Setting, key)
        if value is None:
            if row:
                s.delete(row)
        else:
            if not row:
                row = Setting(key=key)
            row.value = value
            row.updated_at = now()
            s.add(row)
        s.commit()


def log_action(s: Session, kind: str, ref_table: str, ref_id: int, title: str = "", channel: str = "tg") -> None:
    s.add(ActionLog(kind=kind, ref_table=ref_table, ref_id=ref_id, title=title, channel=channel))
