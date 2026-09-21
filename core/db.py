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
    # событие можно «сделать», как задачу: галочка в календаре и в «Делах» — одна запись
    done: bool = Field(default=False, index=True)
    done_at: Optional[datetime] = None
    done_dates: str = ""               # для повторов: какие именно разы отмечены "2026-09-10,2026-09-17"


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
    aim_id: Optional[int] = Field(default=None, index=True)        # 0.10: задача двигает долгосрочную цель (Aim)
    milestone_id: Optional[int] = Field(default=None, index=True)  # …и конкретную веху в ней
    blocked_by: str = ""                                            # что мешает («жду исходники от клиента») — пусто = не заблокирована


# ---------- Цели (долгосрочные; денежные конверты — Goal ниже) ----------
class Aim(SQLModel, table=True):
    """Долгосрочная цель: «устойчивая карьера монтажёра», «переехать», «выучить After Effects».
    Три уровня, а не семь: цель → веха (Milestone) → задача (Task.milestone_id). Прогресс считается по вехам,
    а если вех нет — по задачам с aim_id; поле progress — ручная поправка, когда считать не по чему."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    why: str = ""                      # зачем — одна фраза; Марвин напоминает её, когда цель буксует
    status: str = Field(default="active", index=True)   # active / paused / done / dropped
    priority: int = 2                  # 1 главная сейчас, 2 обычная, 3 фоновая
    due: Optional[datetime] = None
    progress: float = 0.0              # 0..1, ручная (если нет вех/задач)
    created_at: datetime = Field(default_factory=now)
    done_at: Optional[datetime] = None
    last_touch: Optional[datetime] = None   # когда по цели последний раз что-то закрывали (для «давно не возвращался»)


class Milestone(SQLModel, table=True):
    """Веха цели: «шоурил», «горизонтальный бизнес-ролик для портфолио». Это и есть «проект» в терминах ТЗ.
    Может быть привязана к заказу (order_id) — тогда прогресс заказа двигает цель."""
    id: Optional[int] = Field(default=None, primary_key=True)
    aim_id: int = Field(index=True)
    title: str
    status: str = Field(default="open", index=True)     # open / done / dropped
    order: int = 0                     # порядок в цели
    due: Optional[datetime] = None
    order_id: Optional[int] = Field(default=None, index=True)   # веха = заказ (фриланс)
    notes: str = ""
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
    bucket: str = ""                   # 50/30/20: need (обязательное) / want (хотелки) / save (накопления); '' — не размечена


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
    order_id: Optional[int] = Field(default=None, index=True)      # оплата/аванс по заказу (фриланс)
    goal_id: Optional[int] = Field(default=None, index=True)       # перевод в конверт-накопление


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


# ---------- Заказы (фриланс): клиенты, заказы, рабочие сессии (помодоро), цели-накопления ----------
class Client(SQLModel, table=True):
    """Человек или компания: клиент по заказам либо просто «свой» (мама, Ваня). Карточка собирается из всей базы
    по упоминаниям имени (people.py) — здесь только то, что нельзя вывести."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    contact: Optional[str] = None      # телега / почта / телефон — одной строкой
    notes: Optional[str] = None
    kind: str = Field(default="client", index=True)   # client (по заказам) / person (близкие, друзья, подрядчики)
    aliases: str = ""                  # другие имена через запятую: «Ваня, Иван Петров, @ivan»
    birthday: Optional[str] = None     # «12.03» или «12.03.1990»
    tags: str = ""                     # через запятую: «монтаж, друг, подрядчик»
    pay_mode: str = "each"             # как платит: each — за каждый заказ · batch — пачкой раз в pay_every дней · monthly — по числам pay_days
    pay_every: int = 14                # batch: период в днях (считается от последней оплаты)
    pay_days: str = ""                 # monthly: числа месяца через запятую («10,25»)
    created_at: datetime = Field(default_factory=now)


class Order(SQLModel, table=True):
    """Заказ: что монтируем, для кого, за сколько, к какому сроку и на какой стадии.
    Оплаты — обычные транзакции (Transaction.order_id), так что доход по заказу и баланс — одна правда."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    client_id: Optional[int] = Field(default=None, index=True)
    price: float = 0.0                 # договорённая сумма
    status: str = Field(default="new", index=True)   # new / work / review / done / paid / cancelled
    deadline: Optional[datetime] = Field(default=None, index=True)
    notes: Optional[str] = None        # ТЗ, ссылки на исходники, правки
    estimate_h: float = 0.0            # оценка часов (0 — не оценивал)
    source: str = "web"
    created_at: datetime = Field(default_factory=now)
    done_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None


class WorkSession(SQLModel, table=True):
    """Помодоро/таймер: отрезок работы над заказом. Из них — реальные часы и ставка ₽/час."""
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: Optional[int] = Field(default=None, index=True)
    kind: str = "focus"                # focus / break
    started_at: datetime = Field(default_factory=now, index=True)
    planned_min: int = 25
    ended_at: Optional[datetime] = None
    note: Optional[str] = None
    source: str = "web"


class Goal(SQLModel, table=True):
    """Конверт/накопление: «подушка 300к к марту», «на камеру 120к»."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    target: float
    saved: float = 0.0
    due: Optional[datetime] = None
    icon: str = "🎯"
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


class Board(SQLModel, table=True):
    """Доска: бесконечный лист под раскадровку/сценарий/раскладку мыслей. Объекты — в BoardItem."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    kind: str = "free"                 # free / storyboard / script — только пресет при создании и подсказки UI
    order_id: Optional[int] = Field(default=None, index=True)   # доска заказа
    aim_id: Optional[int] = Field(default=None, index=True)     # доска цели
    revision: int = 0                  # версия содержимого для атомарного сохранения
    last_sync: str = "{}"              # подтверждение последнего сохранения (повтор запроса не создаёт дубли)
    view: str = "{}"                   # {x, y, k} — где человек оставил камеру
    archived: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=now, index=True)
    updated_at: datetime = Field(default_factory=now, index=True)


class BoardItem(SQLModel, table=True):
    """Объект на доске. type: sticky / text / frame / image / arrow / ink. Геометрия в координатах холста.
    data — JSON под тип: sticky {text,color} · text {text,size} · frame {label,ratio,image,seconds,n}
    · image {src} · arrow {from,to,label} (id объектов или точки) · ink {points:[[x,y,p]…],color,width}."""
    id: Optional[int] = Field(default=None, primary_key=True)
    board_id: int = Field(index=True)
    type: str = Field(index=True)
    x: float = 0
    y: float = 0
    w: float = 200
    h: float = 120
    z: int = 0
    rot: float = 0
    data: str = "{}"
    note_id: Optional[int] = None      # объект — ссылка на мысль из «мозга» (не копия)
    link_id: Optional[int] = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


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


class Lesson(SQLModel, table=True):
    """Урок из исправления: «сайт 15000» → был записан как трата, хозяин сказал «это заказ». Похожая фраза в следующий раз
    сразу идёт нужным типом (эмбеддинги локально; без них — по словам). kind="mute" — тема, про которую просили не напоминать."""
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str                          # исходная фраза хозяина
    kind: str = Field(index=True)      # что это на самом деле: task / event / expense / income / debt / note / order / mute
    wrong: str = ""                    # как понял ассистент до исправления
    vector: str = ""                   # эмбеддинг фразы (JSON), пусто — ещё не посчитан
    uses: int = 0
    created_at: datetime = Field(default_factory=now)


class Run(SQLModel, table=True):
    """Журнал работы: один разговорный ход — одна строка. Каким путём пошёл, что вызвал, сколько занял,
    переспросил ли, исправил ли его хозяин следом. Нужен, чтобы «почему он так решил» и «почему так долго»
    можно было ответить по базе, а не по текстовому логу процесса (см. services/trace.py)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str = ""                                     # реплика хозяина, обрезанная до trace.TEXT_MAX
    channel: str = Field(default="tg", index=True)     # tg / web / voice / …
    route: str = Field(default="none", index=True)     # rules / ollama / gemini(=облако) / none — откуда пришёл ответ
    model: str = ""                                    # какая модель отвечала (имя из Ollama или облачной)
    tools: str = ""                                    # инструменты через запятую; упавший помечен «!»: "add_order,spent!"
    actions: str = ""                                  # Reply.actions — что было сделано (в т.ч. путём правил)
    steps: int = 0                                     # кругов «модель → инструмент → модель»
    ms: int = 0                                        # сколько заняло всё вместе
    ok: bool = Field(default=True, index=True)         # ответ получен (не «не понял» и не сбой)
    asked: bool = False                                # переспросил вместо того, чтобы сделать
    corrected: bool = Field(default=False, index=True) # хозяин следом отменил или поправил тип записи
    error: str = ""                                    # причина сбоя, если был
    created_at: datetime = Field(default_factory=now, index=True)


class ScreenSlot(SQLModel, table=True):
    """Экранное время: одна строка = непрерывный отрезок в одной программе/сайте (ПК-клиент шлёт пульс раз в 20 с,
    ядро склеивает соседние пульсы с тем же окном). Только имя программы и сайт/заголовок — никакого содержимого."""
    id: Optional[int] = Field(default=None, primary_key=True)
    start: datetime = Field(index=True)
    end: datetime
    app: str = Field(index=True)       # premiere pro.exe → «Premiere Pro»
    title: str = ""                    # сайт для браузера (youtube.com) или заголовок окна (обрезан)
    category: str = "прочее"           # работа / браузер / общение / игра / медиа / прочее
    idle: bool = False                 # True — отошёл от ПК (простой ≥ idle_min): «сел/ушёл» считаются по этим отрезкам


class Fact(SQLModel, table=True):
    """Что ассистент знает о хозяине. Слои: short (последние дни: «болит спина», «делаю ролик для Пятёрочки»),
    long (устойчивое: «кот Барсик», «не любит созвоны утром»), archive (устарело/забыто — не удаляется, в контекст не идёт).
    Эпизоды живут в Memory, знания — в Note/Link/Relation, разговор — в ChatMessage."""
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str
    layer: str = Field(default="short", index=True)     # short / long / archive
    category: str = Field(default="быт", index=True)    # о человеке / предпочтение / здоровье / работа / быт / отношения / привычка
    core: bool = False                                  # ядро портрета: всегда в промпте
    confidence: float = 0.7
    source_msg: Optional[int] = None                    # ChatMessage.id, откуда взято
    replaced_by: Optional[int] = None                   # факт устарел — какой его заменил
    archive_reason: str = ""                            # заменён / забыл по просьбе / не пригодился / устарел
    vector: str = ""                                    # эмбеддинг (JSON), для подтягивания по смыслу
    uses: int = 0                                       # сколько раз попадал в контекст
    last_used: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now, index=True)
    updated_at: datetime = Field(default_factory=now)


class Relation(SQLModel, table=True):
    """Смысловая связь между двумя записями («note:12» ↔ «link:7»). Раньше связи считались на лету по эмбеддингам и
    их нельзя было убрать; теперь связь — запись: auto (предложила нейронка) / yes (человек перешёл по ней) / no (крестик —
    больше не предлагать). a < b лексикографически, чтобы пара хранилась один раз."""
    id: Optional[int] = Field(default=None, primary_key=True)
    a: str = Field(index=True)
    b: str = Field(index=True)
    score: float = 0.0             # близость эмбеддингов на момент решения
    status: str = Field(default="auto", index=True)   # auto / yes / no
    why: str = ""                  # пояснение нейронки одной строкой («оба про сайт для мамы»)
    via: str = ""                  # кто решил: cloud / ollama / embed (без модели, жёсткий порог)
    created_at: datetime = Field(default_factory=now)


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


DEFAULT_BUCKETS = {"Еда": "need", "Транспорт": "need", "Жильё": "need", "Здоровье": "need", "Долги": "need",
                   "Подписки": "want", "Развлечения": "want", "Одежда": "want", "Техника": "want", "Другое": "want"}


def _migrate() -> None:
    """Добавляем новые колонки в старую базу, не теряя данные."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    wanted = {
        "board": {"revision": "INTEGER DEFAULT 0", "last_sync": "VARCHAR DEFAULT '{}'"},
        "note": {"title": "VARCHAR", "raw": "VARCHAR", "polished": "BOOLEAN DEFAULT 0", "image": "VARCHAR"},
        "link": {"polished": "BOOLEAN DEFAULT 0", "summary": "VARCHAR", "excerpt": "VARCHAR"},
        "transaction": {"debt_id": "INTEGER", "order_id": "INTEGER", "goal_id": "INTEGER"},
        "category": {"budget": "FLOAT DEFAULT 0", "custom": "BOOLEAN DEFAULT 0", "bucket": "VARCHAR DEFAULT ''"},
        "event": {"repeat": "VARCHAR DEFAULT ''", "repeat_days": "VARCHAR DEFAULT ''", "repeat_until": "DATETIME",
                  "skip_dates": "VARCHAR DEFAULT ''", "reminded_for": "VARCHAR DEFAULT ''",
                  "done": "BOOLEAN DEFAULT 0", "done_at": "DATETIME", "done_dates": "VARCHAR DEFAULT ''"},
        "task": {"remind_stage": "INTEGER DEFAULT 0", "aim_id": "INTEGER", "milestone_id": "INTEGER", "blocked_by": "VARCHAR DEFAULT ''"},
        "client": {"kind": "VARCHAR DEFAULT 'client'", "aliases": "VARCHAR DEFAULT ''", "birthday": "VARCHAR", "tags": "VARCHAR DEFAULT ''",
                   "pay_mode": "VARCHAR DEFAULT 'each'", "pay_every": "INTEGER DEFAULT 14", "pay_days": "VARCHAR DEFAULT ''"},
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
        # 50/30/20: стандартным категориям — корзина по умолчанию (только тем, у кого она ещё не задана)
        for c in s.exec(select(Category).where(Category.kind == "expense")).all():
            if not c.bucket and c.name in DEFAULT_BUCKETS:
                c.bucket = DEFAULT_BUCKETS[c.name]; s.add(c)
        if s.exec(select(Account)).first() is None:
            main = str(getattr(getattr(cfg, "finance", None), "main_account", "") or "Основной")
            s.add(Account(name=main, kind="bank", is_main=True))
            s.add(Account(name="Наличные", kind="cash"))
        s.commit()
        # 0.9.9: раньше любой новый человек заводился как «клиент». Клиент без единого заказа — не клиент:
        # угадываем тип по имени/подписи (мама → семья, Ваня, друг → друг), иначе просто «человек». Один раз.
        if not s.exec(select(Setting).where(Setting.key == "migr.people_kinds")).first():
            from .services.people import guess_kind
            with_orders = {o.client_id for o in s.exec(select(Order)).all() if o.client_id}
            for c in s.exec(select(Client).where(Client.kind.in_(("client", "person")))).all():   # type: ignore[attr-defined]
                if c.id not in with_orders:
                    g = guess_kind(c.name, c.notes)
                    if c.kind == "client" or g != "person":   # «человека» повышаем только до семьи/друга/компании, не трогаем зря
                        c.kind = g; s.add(c)
            s.add(Setting(key="migr.people_kinds", value="1")); s.commit()


@contextmanager
def session() -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as s:
        yield s


def remember(s: Session, kind: str, text: str, ref_table: str | None = None,
             ref_id: int | None = None, channel: str = "tg") -> None:
    s.add(Memory(kind=kind, text=text, ref_table=ref_table, ref_id=ref_id, channel=channel))


def diff_text(before: dict, after: dict, labels: dict[str, str] | None = None, width: int = 60) -> str:
    """Что именно поменялось: «текст: «было…» → «стало…»; срок: 17.09 → 18.09». Пусто, если ничего.
    Нужен журналу: строка «Правка мысли: <заголовок>» без самой правки бесполезна — по ней не понять, что случилось."""
    labels = labels or {}
    parts = []
    for k, a in after.items():
        b = before.get(k)
        if (a or None) == (b or None):
            continue
        def cut(v):
            return "«" + (v if len(v) <= width else v[:width - 1] + "…") + "»"

        def fmt(v):
            if v is None or v == "":
                return "—"
            if isinstance(v, datetime):
                return f"{v:%d.%m %H:%M}"
            return cut(" ".join(str(v).split()))
        if isinstance(a, str) and isinstance(b, str) and b and a:
            # длинный текст: показываем не два одинаковых начала, а сам изменённый кусок
            an, bn = " ".join(a.split()), " ".join(b.split())
            if an.startswith(bn):
                parts.append(f"{labels.get(k, k)}: дописано {cut(an[len(bn):].strip())}")
                continue
            i = 0
            while i < min(len(an), len(bn)) and an[i] == bn[i]:
                i += 1
            j = 0
            while j < min(len(an), len(bn)) - i and an[-1 - j] == bn[-1 - j]:
                j += 1
            if i > 12 or j > 12:   # общее начало/конец есть — показываем только середину, где разошлось
                lo = max(0, i - 8)
                pre = "…" if lo else ""
                b_mid = pre + bn[lo:len(bn) - j] + ("…" if j else "")
                a_mid = pre + an[lo:len(an) - j] + ("…" if j else "")
                parts.append(f"{labels.get(k, k)}: {cut(b_mid.strip())} → {cut(a_mid.strip())}")
                continue
        parts.append(f"{labels.get(k, k)}: {fmt(b)} → {fmt(a)}")
    return "; ".join(parts)


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
