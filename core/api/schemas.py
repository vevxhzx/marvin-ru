"""Pydantic-модели запросов API (вынесены из `core/api/app.py`, ФАЗА 7 шаг 7.0).

Все модели — общие для нескольких роутов и для роутов будущих модулей
`core/api/routers/*`. Имена классов НЕ менялись: `core/api/app.py` реэкспортирует их
обратно (`from .schemas import ...`), поэтому существующие импорты продолжают работать.

Перенос механический: тела классов скопированы из app.py без изменений.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ChatIn(BaseModel):
    text: str = Field(..., max_length=20000)
    channel: str = Field("web", max_length=20)


class PcPing(BaseModel):
    mode: str = Field("idle", max_length=20)
    text: str = Field("", max_length=500)
    pending_results: bool = False
    screen: bool = False          # ПК-клиент шлёт активное окно (voice.pc.screen_time.enabled)
    app: str = Field("", max_length=80)
    title: str = Field("", max_length=200)
    idle_sec: int = Field(0, ge=0, le=7 * 24 * 3600)


class PcAck(BaseModel):
    action: str = ""


class PcLaunch(BaseModel):
    restart: bool = False


class PcResult(BaseModel):
    text: str
    channel: str = "voice"
    kind: str = "result"          # result / find / screen / clipboard / status / tidy_plan / tidy_done / tidy_undo / organize_plan
    extra: dict = {}


class PcClip(BaseModel):
    text: str
    channel: str = "voice"


class VisionIn(BaseModel):
    image_b64: str
    question: str = "Что на картинке?"
    private: bool = False
    channel: str = "voice"


class CloudPreviewIn(BaseModel):
    text: str = Field("", max_length=8000)


class RelationIn(BaseModel):
    status: str      # yes — подтвердить / no — убрать (крестик) / auto — вернуть


class EventIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    start: datetime
    duration_min: int = Field(60, ge=0, le=24 * 60 * 14)
    location: Optional[str] = Field(None, max_length=300)
    notes: Optional[str] = Field(None, max_length=4000)
    remind_minutes: int = Field(30, ge=0, le=60 * 24 * 30)
    repeat: str = ""                       # "" / daily / weekly / monthly / yearly
    repeat_days: list[int] = []            # для weekly: 0=пн … 6=вс
    repeat_until: Optional[datetime] = None
    task_id: Optional[int] = None          # привязать встречу к задаче — галочка закроет и её
    order_id: Optional[int] = None         # привязать к заказу — галочка закроет заказ

    @field_validator("title")
    @classmethod
    def _t(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("пустое название")
        return v

    @field_validator("repeat_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        return sorted({d for d in v if 0 <= d <= 6})


class SkipIn(BaseModel):
    date: datetime


class EventDoneIn(BaseModel):
    done: bool = True
    date: Optional[datetime] = None     # для повторов: какой именно раз


class TaskIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    due: Optional[datetime] = None
    priority: int = Field(2, ge=1, le=3)
    project: Optional[str] = Field(None, max_length=120)

    @field_validator("title")
    @classmethod
    def _t(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("пустое название")
        return v


class TaskPatch(BaseModel):
    title: Optional[str] = None
    due: Optional[datetime] = None
    clear_due: bool = False
    priority: Optional[int] = None
    project: Optional[str] = None
    blocked_by: Optional[str] = None      # "" — снять блокировку
    aim_id: Optional[int] = None          # 0 — отвязать
    milestone_id: Optional[int] = None


class AimIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    why: str = Field("", max_length=300)
    due: Optional[datetime] = None
    priority: int = Field(2, ge=1, le=3)


class AimPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=120)
    why: Optional[str] = Field(None, max_length=300)
    due: Optional[datetime] = None
    clear_due: bool = False
    priority: Optional[int] = Field(None, ge=1, le=3)
    status: Optional[str] = Field(None, pattern="^(active|done|paused|dropped)$")


class MilestoneIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    due: Optional[datetime] = None
    order_id: Optional[int] = None
    notes: str = Field("", max_length=500)


class TxIn(BaseModel):
    amount: float
    kind: str = "expense"
    category: Optional[str] = None
    note: Optional[str] = None
    account: Optional[str] = None
    to_account: Optional[str] = None
    date: Optional[datetime] = None


class TxPatch(BaseModel):
    amount: Optional[float] = None
    kind: Optional[str] = None
    category: Optional[str] = None
    note: Optional[str] = None
    account: Optional[str] = None
    to_account: Optional[str] = None
    date: Optional[datetime] = None


class CategoryIn(BaseModel):
    name: str
    kind: str = "expense"
    icon: str = "•"
    keywords: str = ""
    budget: float = 0
    bucket: str = ""


class CategoryPatch(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    keywords: Optional[str] = None
    budget: Optional[float] = None
    bucket: Optional[str] = None


class BalanceIn(BaseModel):
    name: str
    balance: float


class AccountIn(BaseModel):
    name: str
    kind: str = "bank"
    balance: float = 0


class AccountPatch(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    balance: Optional[float] = None
    is_main: Optional[bool] = None


class DebtIn(BaseModel):
    title: str
    total: float
    remaining: Optional[float] = None
    payment: float = 0
    rate: float = 0
    pay_day: int = 1
    creditor: Optional[str] = None


class PayIn(BaseModel):
    amount: float
    account: Optional[str] = None
    date: Optional[datetime] = None


class DebtPatch(BaseModel):
    title: Optional[str] = None
    creditor: Optional[str] = None
    total: Optional[float] = None
    remaining: Optional[float] = None
    payment: Optional[float] = None
    rate: Optional[float] = None
    pay_day: Optional[int] = None
    closed: Optional[bool] = None


class RecurringIn(BaseModel):
    title: str
    amount: float
    day: int = 1
    kind: str = "expense"
    category: Optional[str] = None
    period: str = "monthly"


class RecurringPatch(BaseModel):
    title: Optional[str] = None
    amount: Optional[float] = None
    day: Optional[int] = None
    kind: Optional[str] = None
    category: Optional[str] = None
    period: Optional[str] = None
    account: Optional[str] = None
    active: Optional[bool] = None


class ClientIn(BaseModel):
    name: str
    contact: Optional[str] = None
    notes: Optional[str] = None


class OrderIn(BaseModel):
    title: str
    price: float = 0
    client: Optional[str] = None
    deadline: Optional[datetime] = None
    notes: Optional[str] = None
    estimate_h: float = 0
    status: str = "work"


class OrderPatch(BaseModel):
    title: Optional[str] = None
    price: Optional[float] = None
    client: Optional[str] = None
    deadline: Optional[datetime] = None
    notes: Optional[str] = None
    estimate_h: Optional[float] = None
    status: Optional[str] = None


class PaymentIn(BaseModel):
    amount: float
    note: Optional[str] = None
    account: Optional[str] = None
    date: Optional[datetime] = None   # когда пришли деньги (старые заказы задним числом)


class TimerIn(BaseModel):
    order_id: Optional[int] = None
    minutes: Optional[int] = None      # пусто — из настроек помодоро
    kind: str = "focus"


class ManualTimeIn(BaseModel):
    minutes: int = Field(..., ge=1, le=24 * 60 * 7)
    started_at: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=500)


class ScreenImportIn(BaseModel):
    minutes: int = Field(..., ge=1, le=24 * 60 * 7)
    app: str = Field(..., min_length=1, max_length=80)
    project: str = Field(default="", max_length=160)


class PersonIn(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    contact: Optional[str] = None
    notes: Optional[str] = None
    aliases: Optional[str] = None
    birthday: Optional[str] = None
    tags: Optional[str] = None
    pay_mode: Optional[str] = None     # each / batch / monthly — как клиент платит
    pay_every: Optional[int] = None
    pay_days: Optional[str] = None


class PomoSettingsIn(BaseModel):
    focus: Optional[int] = None
    short: Optional[int] = None
    long: Optional[int] = None
    long_every: Optional[int] = None
    auto_break: Optional[bool] = None
    sound: Optional[str] = None
    voice: Optional[bool] = None
    volume: Optional[float] = None


class FreelanceIn(BaseModel):
    enabled: Optional[bool] = None
    late_days: Optional[int] = None
    late_nudge: Optional[bool] = None
    rate_check: Optional[bool] = None
    rate_tolerance: Optional[int] = None
    tax_percent: Optional[int] = None
    weekly: Optional[bool] = None


class GoalIn(BaseModel):
    title: str
    target: float
    due: Optional[datetime] = None
    saved: float = 0
    icon: str = "🎯"


class GoalPatch(BaseModel):
    title: Optional[str] = None
    target: Optional[float] = None
    due: Optional[datetime] = None
    saved: Optional[float] = None
    icon: Optional[str] = None
    closed: Optional[bool] = None


class GoalPut(BaseModel):
    amount: float
    account: Optional[str] = None
    record_tx: bool = True


class NoteIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)
    tags: list[str] = []

    @field_validator("text")
    @classmethod
    def _t(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("пустая заметка")
        return v


class LinkIn(BaseModel):
    url: str
    comment: Optional[str] = None
    tags: list[str] = []


class BoardIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    kind: str = "free"
    order_id: Optional[int] = None
    aim_id: Optional[int] = None
    frames: int = Field(0, ge=0, le=60)
    ratio: str = "16:9"


class BoardPatch(BaseModel):
    title: Optional[str] = Field(None, max_length=120)
    kind: Optional[str] = None
    view: Optional[dict] = None
    archived: Optional[bool] = None
    order_id: Optional[int] = None
    aim_id: Optional[int] = None


class BoardItemIn(BaseModel):
    type: str
    x: float = 0
    y: float = 0
    w: Optional[float] = None
    h: Optional[float] = None
    z: Optional[int] = None
    rot: float = 0
    data: dict = {}
    note_id: Optional[int] = None
    link_id: Optional[int] = None


class BoardItemPatch(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    z: Optional[int] = None
    rot: Optional[float] = None
    data: Optional[dict] = None


class BoardBulk(BaseModel):
    items: list[dict] = []


class BoardIds(BaseModel):
    ids: list[int] = []


class BoardSync(BaseModel):
    revision: int = Field(..., ge=0)
    token: str = Field(..., min_length=8, max_length=100)
    items: list[dict] = []


class NoteEdit(BaseModel):
    text: Optional[str] = None
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    append: Optional[str] = None


class LinkEdit(BaseModel):
    title: Optional[str] = None
    comment: Optional[str] = None
    tags: Optional[list[str]] = None


class FactIn(BaseModel):
    text: str
    layer: str = "long"
    category: str = "быт"
    core: bool = False


class FactPatch(BaseModel):
    text: Optional[str] = None
    layer: Optional[str] = None
    category: Optional[str] = None
    core: Optional[bool] = None


class StyleIn(BaseModel):
    text: str


class UiPrefsIn(BaseModel):
    prefs: dict


class EditionIn(BaseModel):
    edition: str


class SettingsIn(BaseModel):
    changes: dict


class TgLogin(BaseModel):
    init_data: str


class VoicePick(BaseModel):
    engine: str
    voice: str


class GameBody(BaseModel):
    on: bool = True


class BackupRestoreIn(BaseModel):
    name: str = Field(..., min_length=8, max_length=80)

