# -*- coding: utf-8 -*-
"""Роутер инструментов: вместо 46 схем модели отдаём ядро + 1–3 тематические группы.

Зачем: полный набор — ~18k символов (~5.6k токенов); на 6 ГБ одно только чтение
занимает около минуты. Роутер оставляет 6–19 инструментов (12–39% размера).

Использование (только локальный путь via_ollama; облако ходит полным набором):
    tools, groups = select_tools(text, prev_groups=recall(channel), with_cloud=...)
    remember(channel, groups)

Группы прошлого хода — для коротких реплик-продолжений («да», «на пятницу»).
Если ничего не совпало — ядро + search_notes и today_briefing (безопасный минимум,
а не пустота: модель иначе пишет «готово» без вызова).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ALL = {t["function"]["name"]: t for t in
       json.loads((Path(__file__).with_name("schemas_compact.json")).read_text(encoding="utf-8"))}

# всегда в запросе (порядок фиксирован -> стабильный префикс для кэша)
CORE = ["add_note", "remember_fact", "undo_last", "ask_cloud"]

GROUPS = {
    "calendar": ["add_event", "move_event", "delete_event", "list_events", "add_task",
                 "list_tasks", "complete_task", "agenda", "today_briefing"],
    "money":    ["add_expense", "add_income", "spent", "finance_summary", "transfer",
                 "set_balance", "set_budget"],
    "debts":    ["add_debt", "pay_debt", "list_debts", "add_recurring", "stop_recurring",
                 "find_subscriptions", "cash_forecast", "finance_report"],
    "goals":    ["add_aim", "list_aims", "link_task_to_aim", "focus_today", "add_goal", "save_to_goal"],
    "orders":   ["add_order", "update_order", "order_payment", "list_orders", "late_payments",
                 "pomodoro", "person_card"],
    "notes":    ["search_notes", "edit_note", "board_note", "board_show", "person_card", "add_person"],
}

# сильные признаки — решают сами
KW = {
    "calendar": r"встреч|событи|календар|созвон|звонок|перенес|напомн|задач|список дел|расписан|план на|на неделю|что у меня|что сегодня",
    "money":    r"трат|потрат|купил|заплатил|расход|доход|получил|зарплат|перевод|перевёл|снял|налич|баланс|сводк|сколько (ушло|потрат|заработ)",
    "debts":    r"долг|кредит|ипотек|подписк|регулярн|платёж|платеж|прогноз|хватит|отчёт|отчет|финанс|минус|лимит|бюджет|списани",
    "goals":    r"\bцел[иьюе]|копил|накоп|конверт|подушк|отложил|копилк|фокус|вех[аи]|что (мне )?делать",
    "orders":   r"заказ|клиент|монтаж|аванс|оплат|задерж|должен|дедлайн|помодоро|таймер|проект|сдал|ставк|кто такой|что по [а-яё]|карточк",
    "notes":    r"замет|мысль|идея|найди|поищи|вспомни|что я (говорил|писал|записывал)|когда я|доск|сториборд|раскадров|стикер|исправь|дополни|человек|контакт|день рождения|сестр|брат",
}
# слабые признаки — работают, только если сильных нет (дни недели, время, суммы, «ролик»)
WEAK = {
    "calendar": r"завтра|сегодня|послезавтра|понедельн|вторник|сред[ау]|четверг|пятниц|суббот|воскресен|\b\d{1,2}[:.]\d{2}\b|сделат|выполн",
    "money":    r"₽|руб|\d\s?(к|тыс)\b|\d{3,}",
    "orders":   r"ролик|правки",
}
KW = {g: re.compile(p, re.I) for g, p in KW.items()}
WEAK = {g: re.compile(p, re.I) for g, p in WEAK.items()}

FALLBACK = ["search_notes", "today_briefing"]   # если ничего не совпало (болтовня / «ок»)
MAX_GROUPS = 3

# группы прошлого хода по каналам — короткие реплики («да», «на пятницу») наследуют контекст.
# Каналов — единицы (tg/web/voice…), чистим самые старые, чтобы не росло.
_LAST: dict[str, tuple[list[str], float]] = {}
_LAST_MAX = 32


def recall(channel: str) -> list[str]:
    """Группы прошлого хода этого канала (для select_tools)."""
    import time
    item = _LAST.get(channel or "")
    if not item:
        return []
    groups, _ = item
    return list(groups)


def remember(channel: str, groups: list[str]) -> None:
    """Запомнить группы хода (пустые тоже — «не совпало» тоже контекст)."""
    import time
    if not channel:
        return
    _LAST[channel] = (list(groups), time.monotonic())
    while len(_LAST) > _LAST_MAX:
        oldest = min(_LAST, key=lambda k: _LAST[k][1])
        del _LAST[oldest]


def select_tools(text: str, prev_groups: tuple | list = (), with_cloud: bool = True) -> tuple[list[dict], list[str]]:
    """Подобрать инструменты под фразу. Возвращает (схемы, группы)."""
    t = (text or "").lower()
    hit = [g for g, rx in KW.items() if rx.search(t)]
    if not hit:
        hit = [g for g, rx in WEAK.items() if rx.search(t)]
    # короткие реплики-продолжения («да», «на 5», «в пятницу») — липнем к прошлым группам
    if not hit and len(t) < 40:
        hit = list(prev_groups)
    hit = hit[:MAX_GROUPS]
    names = list(CORE)
    for g in hit:
        names += [n for n in GROUPS[g] if n not in names]
    if not hit:
        names += FALLBACK
    if not with_cloud:
        names = [n for n in names if n != "ask_cloud"]
    return [ALL[n] for n in names], hit
