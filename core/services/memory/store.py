"""Память о хозяине: хранение фактов (CRUD), настройки, эмбеддинги, затухание."""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime

from sqlalchemy import text
from sqlmodel import select

from ...brain import llm
from ...db import Fact, get_setting, icontains, log_action, session, set_setting


log = logging.getLogger("jarvis.memory")
_META_COLS: bool | None = None   # кэш проверки колонок v5

CATEGORIES = ("о человеке", "предпочтение", "здоровье", "работа", "быт", "отношения", "привычка")
CTX_MAX = 6              # сколько релевантных фактов подтягиваем
CTX_MIN_SCORE = 0.45
CORE_MAX = 6             # ядерных — всегда
DEDUP_SCORE = 0.9
UNUSED_DAYS = 60         # long-факт, ни разу не пригодившийся за 60 дней (и не ядро) → архив
FADE_SUMMARY = 0.25      # затухание ниже этого → факт не идёт в сводки («что ты обо мне знаешь»), только в ответ на прямой вопрос
DECAY_PENALTY = 0.35     # насколько полное затухание режет релевантность в recall(): score -= (1-decay)*штраф
DISMISSED_KEY = "memory.dismissed"   # JSON-список фраз, которые хозяин отклонил («нет» в тосте) — не предлагаем и не сохраняем
PORTRAIT_KEY = "user.portrait"
PORTRAIT_AT_KEY = "user.portrait_at"
STYLE_LINE_MAX = 400     # профиль стиля — одна строка в system prompt, не длиннее

SECRET_RX = re.compile(r"парол|password|пин\b|pin\b|cvv|cvc|код\s+(?:из\s+)?смс|токен|api[- ]?key|\[скрыто\]|\[ключ\]|\[карта\]", re.I)
# что точно не факт о человеке: команды ассистенту, вопросы, короткие реплики
COMMAND_RX = re.compile(r"^\s*(поставь|добавь|запиши|напомни|удали|убери|отмени|перенеси|покажи|найди|открой|включи|выключи|сколько|что|где|когда|кто|как|почему|"
                        r"потратил\w*|купил\w*\s+.*\d|заплатил\w*|перевед\w*|встреча|созвон|задача|таск|мысль|заметка|облако|локально|игра)\b", re.I)

EXTRACT_PROMPT = """Ты — память личного ассистента. Дана РЕПЛИКА хозяина и список УЖЕ ИЗВЕСТНЫХ фактов о нём по теме.
Реши, что стоит запомнить о САМОМ ХОЗЯИНЕ: его семья, питомцы, работа, здоровье, привычки, предпочтения, планы на ближайшие дни,
как он любит, чтобы с ним общались. Не запоминай: разовые команды («поставь встречу», «потратил 700»), вопросы, факты о посторонних
без связи с хозяином, то, что и так очевидно, пароли и любые коды.
Каждый факт — одна короткая фраза в третьем лице («У него кот Барсик», «Не любит созвоны утром», «На этой неделе делает ролик для Пятёрочки»).
layer: "short" — актуально дни-недели (планы, самочувствие, текущая работа); "long" — устойчивое (семья, питомцы, вкусы, здоровье хроническое, привычки).
Если новый факт ПРОТИВОРЕЧИТ или УТОЧНЯЕТ известный — верни update с его id и новым текстом.
Отдельно remind: если хозяин между делом упомянул, что ему НАДО что-то сделать («надо бы на неделе маме позвонить», «не забыть
продлить домен»), но не попросил это записать — предложи одно напоминание: {"title": "Позвонить маме", "when": "YYYY-MM-DD HH:MM" или null}.
Не предлагай remind для того, что уже сделано, для желаний без действия и для явных команд.
Ответ строго JSON: {"add": [{"text": "...", "layer": "short|long", "category": "о человеке|предпочтение|здоровье|работа|быт|отношения|привычка"}],
"update": [{"id": <id>, "text": "..."}], "remind": null или {"title": "...", "when": "..."}}. Если запоминать нечего — {"add": [], "update": [], "remind": null}."""

PORTRAIT_PROMPT = """Ниже — факты, которые ассистент знает о своём хозяине. Собери из них портрет: 5–8 коротких строк по-русски,
в третьем лице, только то, что есть в фактах, самое важное для общения и помощи (кто он, семья/питомцы, чем занимается,
что любит и не любит, здоровье, как с ним говорить). Без вступлений и заголовков, каждая строка с новой строки."""

STYLE_KEY = "user.style"
STYLE_AT_KEY = "user.style_at"
STYLE_PROMPT = """Ниже реплики одного человека своему ассистенту. Опиши в 3–5 коротких строках, КАК он пишет: длина фраз, тон (сухо / с юмором /
мат), эмодзи, любимые слова и сокращения, как называет вещи (например «мопс» = конкретный человек или встреча), что раздражает
(длинные ответы, лишние вопросы). Только про стиль, без пересказа содержания. Ответ — строки, каждая с «— »."""

PROMOTE_PROMPT = """Ниже факты о хозяине, записанные как временные («сейчас») больше недели назад. Для каждого реши:
"long" — это устойчивое и стоит помнить дальше; "archive" — было актуально пару дней и уже нет. Ответ строго JSON:
{"keep": [<id>, ...]} — id тех, что оставить надолго. Остальные уйдут в архив."""

IMPORTANCE_PROMPT = """Ниже — то, что ассистент знает о хозяине (id и текст). Выбери самое важное и устойчивое —
то, что определяет человека и общение с ним годами: характер и стиль общения, вкусы и предпочтения,
семья и близкие, здоровье, работа и устойчивые привычки. НЕ выбирай разовые эпизоды, временные
состояния («простудился», «делаю ролик для X») и мелкий быт. Ответ строго JSON: {{"core": [<id>, ...]}} —
id самых важных, не больше {n}. Если такого нет — {{"core": []}}."""


# ---------------------------------------------------------------- настройки
def enabled() -> bool:
    from ... import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return bool(getattr(node, "enabled", True)) if node is not None else True


def where() -> str:
    from ... import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    w = str(getattr(node, "where", "cloud") or "cloud").lower()
    return w if w in ("cloud", "local", "auto") else "cloud"


def short_days() -> int:
    from ... import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    try:
        return max(1, int(getattr(node, "short_days", 7) or 7))
    except (TypeError, ValueError):
        return 7


def _num(node, name: str, default: float, lo: float, hi: float) -> float:
    """Числовая настройка brain.memory.* с границами — кривой yaml не должен ронять память."""
    try:
        v = float(getattr(node, name, default))
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, v))


# ---------------------------------------------------------------- затухание (decay)
def decay_half_life() -> float:
    """Полу-период затухания неподтверждённых фактов, дней: exp(-Δt / half_life)."""
    from ... import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return _num(node, "decay_half_life_days", 90.0, 1.0, 3650.0)


def decay_days() -> int:
    """Через столько дней неподтверждённый и почти не упоминавшийся факт уходит в архив (ночью)."""
    from ... import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return int(_num(node, "decay_days", 365.0, 1.0, 36500.0))


def decay_max_mentions() -> int:
    """Сколько упоминаний нужно факту, чтобы он НЕ счищался по decay_days («пельмени» сказали дважды — значит, живой)."""
    from ... import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return int(_num(node, "decay_max_mentions", 2.0, 0.0, 100.0))


# ---------------------------------------------------------------- предложения фактов (тост «Запомнить?»)
def suggest_enabled() -> bool:
    """Предлагать новые факты из разговора в ответе чата (кнопки «да/нет» на сайте).

    Батч 4: по умолчанию ВЫКЛЮЧЕНО — память работает молча (extract пишет факты
    без тостов). Включить — явно: brain.memory.suggest: true. Список отклонённых
    фраз (memory.dismissed) при этом живёт независимо и дальше фильтрует extract."""
    from ... import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return bool(getattr(node, "suggest", False))


def suggest_timeout() -> float:
    """Сколько секунд ждать извлечение фактов ради тоста; дольше — уходим в фон, как раньше."""
    from ... import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return _num(node, "suggest_timeout", 20.0, 1.0, 120.0)


# ---------------------------------------------------------------- эмбеддинги
def _vec(raw: str) -> list[float]:
    try:
        return json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return []


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def _embed(texts: list[str]) -> list[list[float]] | None:
    if not texts or not await llm.embed_available():
        return None
    try:
        return await llm.embed(texts)
    except Exception as e:  # pragma: no cover
        log.warning("memory embed: %s", e)
        return None


async def index_pending(limit: int = 50) -> int:
    """Досчитать эмбеддинги фактам без вектора (например, добавленным, когда Ollama спала)."""
    with session() as s:
        rows = list(s.exec(select(Fact).where(Fact.vector == "", Fact.layer != "archive").limit(limit)))
    if not rows:
        return 0
    vecs = await _embed([r.text for r in rows])
    if not vecs:
        return 0
    with session() as s:
        for r, v in zip(rows, vecs):
            f = s.get(Fact, r.id)
            if f:
                f.vector = json.dumps([round(x, 6) for x in v]); s.add(f)
        s.commit()
    return len(rows)


# ---------------------------------------------------------------- CRUD
def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip().rstrip(".")).strip()


def _extract_due(text_: str) -> str | None:
    """Дата-метка факта из текста (ISO-строка или None). Переиспользуем парсер дат
    мозга — тот же, что разбирает «завтра в 10» в задачах. Календарный эвент
    по ней НЕ создаём: это лишь метка для экрана «Память»."""
    try:
        from ...brain.dates import parse_datetime
        dt, _rest = parse_datetime(text_ or "")
        return dt.isoformat() if dt else None
    except Exception:
        return None


async def add_fact(text: str, layer: str = "long", category: str = "быт", core: bool = False, source_msg: int | None = None,
                   source_ref: str | None = None, confidence: float = 0.7) -> Fact | None:
    """Добавить факт. Секреты — никогда. Дубль (тот же текст или близость ≥0.9 в том же слое) — не плодим, обновляем дату.
    source_msg — строго ChatMessage.id; source_ref — ссылка моста «Мозг → Память» ("note:{id}" / "link:{id}")."""
    text = _norm(text)
    if len(text) < 4 or SECRET_RX.search(text):
        return None
    layer = layer if layer in ("short", "long", "archive") else "short"
    category = category if category in CATEGORIES else "быт"
    vecs = await _embed([text])
    vec = vecs[0] if vecs else None
    due = _extract_due(text)
    with session() as s:
        live = list(s.exec(select(Fact).where(Fact.layer != "archive")))
        for f in live:
            same = f.text.lower() == text.lower() or (vec and _cos(vec, _vec(f.vector)) >= DEDUP_SCORE)
            if same:
                f.updated_at = datetime.now()
                if layer == "long" and f.layer == "short":
                    f.layer = "long"          # сказали ещё раз → устойчивое
                f.core = f.core or core
                if due and not f.due:
                    f.due = due
                s.add(f); s.commit(); s.refresh(f)
                set_fact_meta(f.id, last_seen=datetime.now())   # хозяин повторил факт в реплике — затухание заново
                return f
        f = Fact(text=text, layer=layer, category=category, core=core, source_msg=source_msg, source_ref=source_ref,
                 confidence=confidence, due=due, vector=json.dumps([round(x, 6) for x in vec]) if vec else "")
        s.add(f); s.commit(); s.refresh(f)
        log_action(s, "add_fact", "fact", f.id, text[:80], "memory"); s.commit()
        return f


def add_fact_sync(text: str, layer: str = "long", category: str = "быт", core: bool = False, confidence: float = 0.9) -> Fact | None:
    """То же, что add_fact, но из синхронного кода (правила чата, инструмент модели): без эмбеддинга — дубль ловим по тексту,
    вектор досчитает index_pending при ближайшем проходе планировщика."""
    text = _norm(text)
    if len(text) < 4 or SECRET_RX.search(text):
        return None
    layer = layer if layer in ("short", "long", "archive") else "short"
    category = category if category in CATEGORIES else "быт"
    due = _extract_due(text)
    with session() as s:
        for f in s.exec(select(Fact).where(Fact.layer != "archive")):
            if f.text.lower() == text.lower():
                f.updated_at = datetime.now(); f.core = f.core or core
                if layer == "long":
                    f.layer = "long"
                if due and not f.due:
                    f.due = due
                s.add(f); s.commit(); s.refresh(f)
                set_fact_meta(f.id, last_seen=datetime.now())
                return f
        f = Fact(text=text, layer=layer, category=category, core=core, confidence=confidence, due=due)
        s.add(f); s.commit(); s.refresh(f)
        log_action(s, "add_fact", "fact", f.id, text[:80], "chat"); s.commit()
        return f


async def update_fact(fid: int, text: str | None = None, layer: str | None = None, category: str | None = None,
                      core: bool | None = None, is_private: bool | None = None, reason: str = "заменён") -> Fact | None:
    """Правка. Смена текста = новая версия: старая уходит в архив с ссылкой replaced_by, чтобы история не терялась."""
    with session() as s:
        f = s.get(Fact, fid)
        if not f:
            return None
        if text is not None and _norm(text) and _norm(text).lower() != f.text.lower():
            new_text = _norm(text)
            if SECRET_RX.search(new_text):
                return None
            vecs = await _embed([new_text])
            nf = Fact(text=new_text, layer=layer or f.layer, category=category or f.category, core=f.core if core is None else core,
                      source_msg=f.source_msg, confidence=f.confidence, vector=json.dumps([round(x, 6) for x in vecs[0]]) if vecs else "",
                      uses=f.uses, last_used=f.last_used, due=_extract_due(new_text),
                      is_private=f.is_private if is_private is None else is_private)
            s.add(nf); s.commit(); s.refresh(nf)
            f.layer, f.replaced_by, f.archive_reason, f.updated_at = "archive", nf.id, reason, datetime.now()
            s.add(f); s.commit()
            set_fact_meta(f.id, archived=datetime.now())
            return nf
        if layer in ("short", "long", "archive"):
            f.layer = layer
            if layer == "archive":
                f.archive_reason = reason
        if category in CATEGORIES:
            f.category = category
        if core is not None:
            f.core = core
        if is_private is not None:
            f.is_private = is_private
        f.updated_at = datetime.now()
        s.add(f); s.commit(); s.refresh(f)
        if layer == "archive":
            set_fact_meta(f.id, archived=datetime.now())
        return f


def forget(fid: int, reason: str = "забыл по просьбе") -> Fact | None:
    with session() as s:
        f = s.get(Fact, fid)
        if not f:
            return None
        f.layer, f.archive_reason, f.updated_at = "archive", reason, datetime.now()
        s.add(f); s.commit(); s.refresh(f)
    set_fact_meta(fid, archived=datetime.now())
    return f


def confirm_fact(fid: int) -> Fact | None:
    """Подтверждение актуальности с экрана: confirmed_at=now (факт больше не затухает),
    updated_at=now (снимает бейдж stale «возможно устарело»). Слой не меняем."""
    now = datetime.now()
    with session() as s:
        f = s.get(Fact, fid)
        if not f:
            return None
        f.updated_at = now
        s.add(f); s.commit(); s.refresh(f)
    set_fact_meta(fid, confirmed=now, last_seen=now)
    with session() as s:
        return s.get(Fact, fid)


def restore(fid: int) -> Fact | None:
    """Вернуть факт из архива. Восстановление — явное решение хозяина, значит фактически подтверждение."""
    with session() as s:
        f = s.get(Fact, fid)
        if not f:
            return None
        f.layer, f.archive_reason, f.replaced_by, f.updated_at = "long", "", None, datetime.now()
        s.add(f); s.commit(); s.refresh(f)
    set_fact_meta(fid, clear_archived=True, confirmed=datetime.now(), last_seen=datetime.now())
    return f


def list_facts(layer: str | None = None, limit: int = 500, q: str | None = None) -> list[Fact]:
    with session() as s:
        qq = select(Fact)
        if layer:
            qq = qq.where(Fact.layer == layer)
        if q and q.strip():
            qq = qq.where(icontains(Fact.text, q.strip()))
        return list(s.exec(qq.order_by(Fact.core.desc(), Fact.updated_at.desc()).limit(limit)))


def fact_source(f: Fact) -> str:
    """Источник факта для экрана доверия: «мозг» (запись по кнопке «Запомнить»),
    «сайт» (реплика с web), «тг» (telegram), иначе «чат». Смотрим source_ref,
    затем канал ChatMessage, на который ссылается Fact.source_msg."""
    try:
        if (getattr(f, "source_ref", None) or "").startswith(("note:", "link:")):
            return "мозг"
        if getattr(f, "source_msg", None):
            with session() as s:
                from ...db import ChatMessage
                m = s.get(ChatMessage, int(f.source_msg))
                if m is not None:
                    ch = (m.channel or "").lower()
                    if ch == "web":
                        return "сайт"
                    if ch.startswith("tg"):
                        return "тг"
    except Exception:
        pass
    return "чат"


def find_fact(query: str, include_archived: bool = False) -> Fact | None:
    """По подстроке среди живых фактов («забудь, что у меня кот» → факт про кота).
    include_archived=True — ищем и в архиве (восстановление затухшего/забытого факта)."""
    q = _norm(query).lower()
    words = [w for w in re.findall(r"[а-яёa-z0-9]+", q) if len(w) >= 3]
    if not words:
        return None
    with session() as s:
        qq = select(Fact) if include_archived else select(Fact).where(Fact.layer != "archive")
        live = list(s.exec(qq))
    best, best_n = None, 0
    for f in live:
        t = f.text.lower()
        n = sum(1 for w in words if (w[:-1] if len(w) > 4 else w) in t)
        if n > best_n:
            best, best_n = f, n
    return best if best_n >= max(1, len(words) // 2) else None


def get_fact_by_source_ref(ref: str) -> Fact | None:
    """Живой факт-мост с таким source_ref ("note:{id}" / "link:{id}") — или None.

    Вынесено из mind.py (_remembered_fact): дедуп кнопки «Запомнить»,
    повторный вызов возвращает существующий факт, а не плодит дубль.
    """
    if not (ref or "").strip():
        return None
    with session() as s:
        rows = list(s.exec(select(Fact).where(Fact.source_ref == ref).limit(2)))
    live = [f for f in rows if f.layer != "archive"]
    return live[0] if live else None


# ---------------------------------------------------------------- колонки затухания (миграция v5)
# Их нет в модели Fact (core/db.py не редактируем), поэтому читаем и пишем их отдельным SQL.
def _dt(v) -> datetime | None:
    """Значение DATETIME из SQLite (обычно строка) → datetime; пусто или кривое → None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).replace("T", " ").split("+")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _meta_columns() -> bool:
    """Есть ли в БД колонки v5 (last_seen_at/confirmed_at/archived_at).

    На боевой базе они всегда есть (миграция v5), но демо/тестовые базы и копии,
    снятые до миграции, могут быть без них. Тогда затухание молча выключается,
    а не роняет ночную задачу.
    """
    global _META_COLS
    if _META_COLS is None:
        try:
            with session() as s:
                cols = {r[1] for r in s.exec(text("PRAGMA table_info(fact)")).all()}
            _META_COLS = {"last_seen_at", "confirmed_at", "archived_at"} <= cols
        except Exception as e:  # pragma: no cover - БД недоступна
            log.warning("память: не удалось проверить колонки затухания — %s", e)
            _META_COLS = False
    return _META_COLS


def fact_meta(fact_ids: set[int] | None = None) -> dict[int, dict]:
    """{fact_id: {"last_seen", "confirmed", "archived"}} по колонкам v5. Без аргумента — по всем фактам."""
    empty = {"last_seen": None, "confirmed": None, "archived": None}
    if not _meta_columns():
        return {i: dict(empty) for i in fact_ids} if fact_ids is not None else {}
    with session() as s:
        rows = s.exec(text("SELECT id, last_seen_at, confirmed_at, archived_at FROM fact")).all()
    out = {int(r[0]): {"last_seen": _dt(r[1]), "confirmed": _dt(r[2]), "archived": _dt(r[3])} for r in rows}
    if fact_ids is None:
        return out
    return {i: out.get(i, dict(empty)) for i in fact_ids}


def set_fact_meta(fid: int, last_seen: datetime | None = None, confirmed: datetime | None = None,
                  archived: datetime | None = None, clear_archived: bool = False) -> None:
    """Одна UPDATE по колонкам v5. None в аргументе = не трогать; clear_archived — снять archived_at (восстановление)."""
    if not _meta_columns():
        log.warning("память: колонки затухания отсутствуют (миграция v5 не применена) — пропускаю")
        return
    sets, params = [], {"fid": int(fid)}
    if last_seen is not None:
        sets.append("last_seen_at = :ls"); params["ls"] = last_seen
    if confirmed is not None:
        sets.append("confirmed_at = :cf"); params["cf"] = confirmed
    if archived is not None:
        sets.append("archived_at = :ar"); params["ar"] = archived
    if clear_archived:
        sets.append("archived_at = NULL")
    if not sets:
        return
    with session() as s:
        s.exec(text(f"UPDATE fact SET {', '.join(sets)} WHERE id = :fid"), params=params)
        s.commit()


def decay(core: bool, confirmed: datetime | None, ref: datetime | None, now: datetime | None = None) -> float:
    """exp(-Δt/half_life) — 1.0 для ядра и подтверждённых фактов (они не гаснут). ref — last_seen_at или created_at."""
    if core or confirmed is not None or ref is None:
        return 1.0
    days = max(0.0, ((now or datetime.now()) - ref).total_seconds() / 86400.0)
    return math.exp(-days / decay_half_life())


def _faded(core: bool, confirmed: datetime | None, ref: datetime | None) -> bool:
    """Сильно затухший (ниже FADE_SUMMARY) — в сводки не идёт, всплывает только на прямой релевантный вопрос."""
    return decay(core, confirmed, ref) < FADE_SUMMARY


def _dedupe(facts: list[Fact]) -> list[Fact]:
    """Схлопнуть дубли: одинаковый текст и «короткий внутри длинного» («пельмени» ⊂ «любит пельмени с мясом»)."""
    out: list[Fact] = []
    seen: set[str] = set()
    for f in facts:
        key = _norm(f.text).lower()
        if not key or key in seen:
            continue
        if any(key in k or k in key for k in seen if k):
            continue
        seen.add(key)
        out.append(f)
    return out


def _dismissed() -> set[str]:
    try:
        raw = json.loads(get_setting(DISMISSED_KEY, "[]") or "[]")
    except (TypeError, json.JSONDecodeError):
        return set()
    return {str(x).lower() for x in raw if isinstance(x, (str, int))}


def _remember_dismiss(text_: str) -> None:
    """Запомнить отказ («нет» в тосте): такую фразу больше не предлагаем и не сохраняем."""
    key = _norm(text_).lower()
    if not key:
        return
    items = [x for x in _dismissed() if x]
    if key in items:
        return
    items.append(key)
    set_setting(DISMISSED_KEY, json.dumps(items[-200:], ensure_ascii=False))


def confirm(fact_id: int | None = None, fact_text: str | None = None, category: str | None = None) -> Fact | None:
    """«Да, запомни»: факт подтверждён (confirmed_at) — он больше не затухает и не архивируется по decay_days.
    Если факта ещё нет (предложение пришло без записи) — сохраняем как long-факт сразу подтверждённым."""
    now = datetime.now()
    f = None
    if fact_id:
        with session() as s:
            f = s.get(Fact, fact_id)
    if f is None and _norm(fact_text or ""):
        f = add_fact_sync(_norm(fact_text), layer="long", category=category or "быт", confidence=1.0)
    if f is None:
        return None
    set_fact_meta(f.id, confirmed=now, last_seen=now, clear_archived=True)
    with session() as s:
        row = s.get(Fact, f.id)
        if row and row.layer == "archive":
            row.layer, row.archive_reason, row.updated_at = "long", "", now
            s.add(row); s.commit()
    return f


def dismiss(fact_id: int | None = None, fact_text: str | None = None) -> bool:
    """«Нет»: убрать предложенный факт (в архив) и запомнить отказ, чтобы не предлагать снова."""
    t = _norm(fact_text or "")
    if t:
        _remember_dismiss(t)
    f = None
    if fact_id:
        with session() as s:
            f = s.get(Fact, fact_id)
    if f is None and t:
        f = find_fact(t, include_archived=True)
    if f is None:
        return bool(t)
    if f.layer != "archive":
        forget(f.id, reason="не подтвердил (тост)")
        set_fact_meta(f.id, archived=datetime.now())
    return True


def stats() -> dict:
    with session() as s:
        rows = list(s.exec(select(Fact)))
    return {"short": sum(r.layer == "short" for r in rows), "long": sum(r.layer == "long" for r in rows),
            "archive": sum(r.layer == "archive" for r in rows), "core": sum(r.core and r.layer != "archive" for r in rows),
            "portrait": get_setting(PORTRAIT_KEY, "") or "", "portrait_at": get_setting(PORTRAIT_AT_KEY, "") or "",
            "style": get_setting(STYLE_KEY, "") or "", "style_at": get_setting(STYLE_AT_KEY, "") or ""}


def about_me_text() -> str:
    """«Что ты обо мне знаешь?» — портрет + ядро + немного long.
    Архивные сюда не идут, затухшие (decay < FADE_SUMMARY) и дубли тоже — сводка должна быть живой, а не хроникой."""
    st = stats()
    meta = fact_meta()

    def keep(f: Fact) -> bool:
        m = meta.get(f.id) or {}
        return not _faded(bool(f.core), m.get("confirmed"), m.get("last_seen") or f.created_at)

    facts = _dedupe([f for f in list_facts() if f.layer != "archive" and keep(f)])
    if not facts and not st["portrait"]:
        return "Пока почти ничего, сэр: вы мне о себе не рассказывали. Скажите «запомни, что …» — или просто общайтесь, я запоминаю сам."
    lines = ["🧠 **Что я о вас знаю**"]
    if st["portrait"]:
        lines.append(st["portrait"])
        lines.append("")
    core = [f for f in facts if f.core][:CORE_MAX]
    rest = [f for f in facts if not f.core][:8]
    for f in core + rest:
        lines.append(f"— {f.text}" + (" · сейчас" if f.layer == "short" else ""))
    more = len(facts) - len(core) - len(rest)
    if more > 0:
        lines.append(f"… и ещё {more} — всё на странице «память».")
    return "\n".join(lines)
