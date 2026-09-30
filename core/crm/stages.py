"""Воронка статусов CRM (фаза 4).

Новые стадии — аддитивны: колонка `order.stage`. Старый `order.status` остаётся
источником правды для финансов/прогноза/просрочки, поэтому стадии и старые статусы
всегда синхронизированы (без потери данных: существующие заказы получают стадию
из своего статуса, миграция v2).

Порядок воронки:
    лид → переговоры → ТЗ согласовано → в работе → на правках → сдан → ждёт оплаты → оплачен
                                                                    ↘ потерян
"""
from __future__ import annotations

# (stage, русская подпись, старый status, которая стадия соответствует)
STAGES: tuple[tuple[str, str, str], ...] = (
    ("lead", "лид", "new"),
    ("negotiation", "переговоры", "new"),
    ("spec", "ТЗ согласовано", "new"),
    ("in_work", "в работе", "work"),
    ("revisions", "на правках", "review"),
    ("delivered", "сдан", "done"),
    ("awaiting_payment", "ждёт оплаты", "done"),
    ("paid", "оплачен", "paid"),
    ("lost", "потерян", "cancelled"),
)

STAGE_ORDER: dict[str, int] = {k: i for i, (k, _, _) in enumerate(STAGES)}
STAGE_LABEL: dict[str, str] = {k: label for k, label, _ in STAGES}
STAGE_TO_STATUS: dict[str, str] = {k: st for k, _, st in STAGES}

# Старый статус → стадия по умолчанию (для существующих заказов без stage).
STATUS_TO_STAGE: dict[str, str] = {
    "new": "lead",
    "work": "in_work",
    "review": "revisions",
    "done": "delivered",
    "paid": "paid",
    "cancelled": "lost",
}

# что считаем «открытым»/«выигранным»/«проигранным» по стадиям
OPEN_STAGES = ("lead", "negotiation", "spec", "in_work", "revisions", "delivered", "awaiting_payment")
WON_STAGES = ("paid",)
LOST_STAGES = ("lost",)


def is_stage(value: str) -> bool:
    return value in STAGE_ORDER


def stage_of(order) -> str:
    """Эффективная стадия заказа: явная колонка, иначе — из старого статуса."""
    st = getattr(order, "stage", "") or ""
    if st in STAGE_ORDER:
        return st
    return STATUS_TO_STAGE.get(getattr(order, "status", "") or "", "lead")


def status_for(stage: str) -> str:
    """Старый статус, соответствующий стадии (для совместимости с финансами/прогнозом)."""
    return STAGE_TO_STATUS.get(stage, "new")


def label(stage: str) -> str:
    return STAGE_LABEL.get(stage, stage)


def status_to_stage(status: str) -> str:
    return STATUS_TO_STAGE.get(status, "lead")
