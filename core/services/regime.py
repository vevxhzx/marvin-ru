"""Режим жизни: период с датой начала и (необязательной) датой конца + название и заметка.

Зачем. «Я уезжаю в армию 28 октября» — после этой фразы обычные средние («в среднем трачу
в день 2 000 ₽») становятся обманом: они усредняют и старую жизнь, и новую, а это разные
жизни. Поэтому, когда есть активный режим И включён переключатель, ВСЕ средние и прогнозы
считаются только по операциям внутри окна режима (с даты начала по «сегодня», а если режим
закрыт — по дату конца включительно).

Что НЕ меняется: режимов нет или переключатель выключен — все цифры считаются ровно так же,
как раньше, по всем данным. По умолчанию режим выключен, пока его не создали из чата или руками.

Хранение — в настройках (таблица `Setting`), без новой таблицы и без миграции схемы:
  `regime:list`    — JSON-список режимов: [{id, title, note, start, end, auto_closed, created}]
  `regime:current` — id активного режима (у него есть начало и нет конца)
  `regime:apply`   — «1»/«0»: считать ли средние по режиму (по умолчанию ВЫКЛ)

Активный режим ровно один: новый режим закрывает предыдущий автоматически, но с явной
пометкой `auto_closed` и строкой в журнале — чтобы в истории было видно, где закончилось
прошлое и с какой даты началось новое.

Модуль ничего не знает про finance/insights (только `core.db`), поэтому его можно звать и из
сервисов, и из роутов, и из чата без риска циклических импортов.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta

from ..db import get_setting, log_action, session, set_setting

KEY_LIST = "regime:list"
KEY_CURRENT = "regime:current"
KEY_APPLY = "regime:apply"

MAX_TITLE = 60
MAX_NOTE = 200

# Сколько максимум живёт незакрытое подтверждение в чате («заведу режим… — да/нет»).
PENDING_TTL_SEC = 300


class RegimeError(ValueError):
    """Понятная человеку ошибка ввода (как finance.FinanceError): чат отдаёт её текстом, API — 400."""


class RegimeNotFound(RegimeError):
    """Режим не найден: API отдаёт 404, а не 400 — «нет такого» ≠ ошибка ввода (как в finance)."""


# ------------------------------------------------------------------ разбор дат
def _today() -> date:
    return datetime.now().date()


def _d(x) -> date:
    """'2026-10-28', '2026-10-28T00:00:00', '28.10', '28.10.2026', date/datetime → date.

    Даты без года («28.10») — ближайшая такая: сегодня или следующий год. Полный год всегда
    оставляем как есть: «уехал в командировку до 5 ноября 2025» не должен превращаться в 2026.
    """
    if x in (None, ""):
        return _today()
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    txt = str(x).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", txt)      # ISO, хоть с временем
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            raise RegimeError("Такой даты не бывает: " + txt)
    m = re.match(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?$", txt)   # «28.10», «28.10.2026»
    if m:
        day, mon = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else _today().year
        try:
            d = date(year, mon, min(day, 28 if not m.group(3) else 31))
        except ValueError:
            raise RegimeError("Такой даты не бывает: " + txt)
        if not m.group(3) and d < _today() - timedelta(days=180):
            d = date(d.year + 1, mon, min(day, 28))       # «28.10» в октябре — это следующий
        return d
    raise RegimeError("Дата режима: напишите как 28.10 или 2026-10-28")


def _fmt(d: date) -> str:
    return d.isoformat()


def _short(d: str | None) -> str | None:
    """'2026-10-28' → '28.10' — для подписей в чате и на сайте."""
    if not d:
        return None
    try:
        return f"{date.fromisoformat(str(d)[:10]):%d.%m}"
    except ValueError:
        return None


# ------------------------------------------------------------------ хранение
def _save(items: list[dict], current: int | None = None) -> None:
    set_setting(KEY_LIST, json.dumps(items, ensure_ascii=False))
    set_setting(KEY_CURRENT, str(current) if current else "")


def list_regimes() -> list[dict]:
    """Все режимы: новые первыми (по дате начала), закрытые — в хвосте."""
    raw = get_setting(KEY_LIST) or ""
    try:
        items = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    out = [x for x in items if isinstance(x, dict) and x.get("title")]
    out.sort(key=lambda x: (str(x.get("start") or ""), int(x.get("id") or 0)), reverse=True)
    return [_public(x) for x in out]


def _public(x: dict) -> dict:
    """То, что отдаём наружу: даты в ISO + короткие подписи + «открыт ли режим»."""
    start = str(x.get("start") or "")[:10] or None
    end = str(x.get("end") or "")[:10] or None
    days = None
    if start:
        try:
            days = max(0, ((date.fromisoformat(end) if end else _today()) - date.fromisoformat(start)).days + 1)
        except ValueError:
            days = None
    return {"id": int(x.get("id") or 0), "title": str(x.get("title") or ""), "note": str(x.get("note") or ""),
            "start": start, "end": end, "from_short": _short(start), "to_short": _short(end),
            "days": days, "open": bool(start and not end), "auto_closed": bool(x.get("auto_closed")),
            "created": x.get("created") or None}


def get_regime(rid: int | str) -> dict | None:
    try:
        want = int(rid)
    except (TypeError, ValueError):
        return None
    return next((r for r in list_regimes() if r["id"] == want), None)


def active() -> dict | None:
    """Активный режим: есть начало и нет конца (не более одного)."""
    items = list_regimes()
    cur = get_setting(KEY_CURRENT) or ""
    if cur.isdigit():
        for r in items:
            if r["id"] == int(cur) and r["open"]:
                return r
    return next((r for r in items if r["open"]), None)   # самовосстановление после правки руками


def current() -> dict | None:
    """Режим, по которому сейчас считаем: открытый, а если его нет — последний закрытый.

    Нужен для закрытых режимов: «уехал в командировку до 5 ноября» — режим уже с концом, но
    средние всё равно должны считаться по нему, а не по всей истории. Новый режим всегда
    становится текущим, поэтому последовательность «армия → вернулся → отпуск» работает.
    """
    return active() or next(iter(list_regimes()), None)


def _next_id(items: list[dict]) -> int:
    return max([int(x.get("id") or 0) for x in items] + [0]) + 1


def _title(x: str) -> str:
    t = " ".join(str(x or "").split())
    if not t:
        raise RegimeError("Название режима не может быть пустым")
    return t[:MAX_TITLE]


# ------------------------------------------------------------------ переключатель
def apply_enabled() -> bool:
    """Считать ли средние по режиму. По умолчанию ВЫКЛ — поведение не меняется."""
    return (get_setting(KEY_APPLY) or "") == "1"


def set_apply(on: bool) -> bool:
    set_setting(KEY_APPLY, "1" if on else "0")
    return apply_enabled()


# ------------------------------------------------------------------ окно расчёта
def window() -> tuple[datetime, datetime] | None:
    """Окно режима для расчёта: (с 00:00 начала, по 00:00 дня ПОСЛЕ конца) либо None.

    None — считаем по всем данным: режима нет, он выключен переключателем, ещё не начался
    или у него нет даты начала.
    """
    if not apply_enabled():
        return None
    r = current()
    if not r or not r["start"]:
        return None
    try:
        start_d = date.fromisoformat(r["start"])
        end_d = date.fromisoformat(r["end"]) if r["end"] else _today()
    except ValueError:
        return None
    start = datetime.combine(start_d, time.min)
    until = datetime.combine(end_d + timedelta(days=1), time.min)
    if start > datetime.now():
        return None   # режим в будущем — усреднять пока нечего
    return start, until


def counted() -> bool:
    """Считаются ли сейчас цифры по режиму (а не по всем данным)."""
    return window() is not None


def count_window(days: int = 30) -> tuple[datetime, datetime, int] | None:
    """Окно расчёта с учётом режима: (с, по, дней) либо None — считаем по всем данным.

    `с` — не раньше режима и не раньше запрошенного периода, `по` — конец режима включительно
    (для открытого — конец сегодняшнего дня). Дней — целых в пересечении, чтобы среднее
    делилось на честный знаменатель, а не на 30 «лишних».
    """
    win = window()
    if not win:
        return None
    since = max(datetime.now() - timedelta(days=max(1, int(days or 30))), win[0])
    until = win[1]
    n = max(1, int((until - since).total_seconds() // 86400))
    return since, until, n


def label(r: dict | None = None) -> str:
    """Подпись для чата: «считаем по режиму: армия с 28.10»."""
    r = r or current()
    if not r:
        return ""
    if r.get("to_short"):
        return f"считаем по режиму: {r['title']} {r['from_short']}–{r['to_short']}"
    tail = f" с {r['from_short']}" if r.get("from_short") else ""
    return f"считаем по режиму: {r['title']}{tail}"


def info() -> dict:
    """Честный блок для API: режим, переключатель и считаем ли мы по нему прямо сейчас."""
    r = current()
    win = window()
    return {
        "active": active(),
        "current": r,
        "apply": apply_enabled(),
        "counted": win is not None,
        "since": win[0].date().isoformat() if win else None,
        "until": (win[1].date() - timedelta(days=1)).isoformat() if win else None,
        "days": (int((win[1] - win[0]).total_seconds() // 86400) if win else None),
        "label": label(r) if win else "",
    }


# ------------------------------------------------------------------ создание/правка/закрытие
def add(title: str, start: date | datetime | str | None = None, end: date | datetime | str | None = None,
        note: str = "", channel: str = "") -> dict:
    """Новый режим. Активный (если есть) закрывается автоматически — с пометкой в истории."""
    title = _title(title)
    start_d, end_d = _d(start), (_d(end) if end not in (None, "") else None)
    if end_d and end_d < start_d:
        raise RegimeError("Дата конца раньше даты начала — проверьте, сэр")
    raw = get_setting(KEY_LIST) or ""
    try:
        items = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        items = []
    if not isinstance(items, list):
        items = []
    prev = active()
    if prev:
        end_prev = start_d if start_d > _d(prev["start"]) else _d(prev["start"])
        for x in items:
            if int(x.get("id") or 0) == prev["id"]:
                x["end"] = _fmt(end_prev)      # конец предыдущего = начало нового
                x["auto_closed"] = True        # явная пометка в истории
                x["note"] = ((x.get("note") or "") + f" · закрыт автоматически: начался «{title}»").strip(" ·")[:MAX_NOTE]
    item = {"id": _next_id(items), "title": title, "note": (note or "").strip()[:MAX_NOTE],
            "start": _fmt(start_d), "end": _fmt(end_d) if end_d else None,
            "auto_closed": False, "created": datetime.now().isoformat()}
    items.append(item)
    _save(items, int(item["id"]) if not end_d else None)
    with session() as s:
        if prev:
            log_action(s, "set_regime", "regime", prev["id"],
                       f"Режим «{prev['title']}» закрыт автоматически: начался «{title}» ({start_d:%d.%m.%Y})", channel or "tg")
        log_action(s, "set_regime", "regime", int(item["id"]),
                   f"Режим «{title}»: с {start_d:%d.%m.%Y}" + (f" по {end_d:%d.%m.%Y}" if end_d else ""), channel or "tg")
    return _public(item)


def update(rid: int | str, **fields) -> dict:
    """Правка режима (название/заметка/даты). Активность не трогает — для этого close()."""
    raw = get_setting(KEY_LIST) or ""
    try:
        items = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        items = []
    if not isinstance(items, list):
        items = []
    rid_i = int(rid)
    item = next((x for x in items if int(x.get("id") or 0) == rid_i), None)
    if item is None:
        raise RegimeNotFound("Режим не найден")
    if fields.get("title") is not None:
        item["title"] = _title(fields["title"])
    if "note" in fields:
        item["note"] = (fields.get("note") or "").strip()[:MAX_NOTE]
    if fields.get("start") is not None:
        item["start"] = _fmt(_d(fields["start"]))
    if "end" in fields:
        end = fields.get("end")
        item["end"] = _fmt(_d(end)) if end not in (None, "") else None
    s_d, e_d = _d(item.get("start")), (_d(item.get("end")) if item.get("end") else None)
    if e_d and e_d < s_d:
        raise RegimeError("Дата конца раньше даты начала — проверьте, сэр")
    _save(items, int(item["id"]) if not item.get("end") else None)
    return _public(item)


def close(rid: int | str | None = None, when: date | datetime | str | None = None,
           channel: str = "") -> dict | None:
    """Закрыть режим (по умолчанию активный) датой `when` (по умолчанию сегодня)."""
    r = get_regime(rid) if rid not in (None, "") else active()
    if not r:
        return None
    end_d = _d(when)
    start_d = _d(r["start"]) if r["start"] else end_d
    if end_d < start_d:
        end_d = start_d     # «вернулся» раньше, чем «уехал» — не даём отрицательную длительность
    return _close_with(r["id"], end_d, channel)


def _close_with(rid: int, end_d: date, channel: str) -> dict:
    raw = get_setting(KEY_LIST) or ""
    try:
        items = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        items = []
    if not isinstance(items, list):
        items = []
    item = next((x for x in items if int(x.get("id") or 0) == int(rid)), None)
    if item is None:
        raise RegimeNotFound("Режим не найден")
    item["end"] = _fmt(end_d)
    _save(items, None)
    with session() as s:
        log_action(s, "set_regime", "regime", int(rid),
                   f"Режим «{item.get('title')}» закрыт {end_d:%d.%m.%Y}", channel or "tg")
    return _public(item)


def delete(rid: int | str, channel: str = "") -> bool:
    raw = get_setting(KEY_LIST) or ""
    try:
        items = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        items = []
    if not isinstance(items, list):
        items = []
    rid_i = int(rid)
    left = [x for x in items if int(x.get("id") or 0) != rid_i]
    if len(left) == len(items):
        return False
    title = next((x.get("title") for x in items if int(x.get("id") or 0) == rid_i), "")
    _save(left, None)
    with session() as s:
        log_action(s, "set_regime", "regime", rid_i, f"Режим «{title}» удалён", channel or "tg")
    return True