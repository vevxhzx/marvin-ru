"""Память о хозяине: что запоминать, что подтягивать в ответ, что забывать.

Слои (см. db.Fact):
  short   — контекст последних дней («болит спина», «делаю ролик для Пятёрочки»);
  long    — устойчивое («кот Барсик», «мама живёт в Туле», «не любит созвоны утром»);
  archive — устарело / забыто по просьбе / не пригодилось. Не удаляется — просто не попадает в контекст.
Разговор — ChatMessage (рабочая память), эпизоды — Memory, знания — Note/Link/Relation.

Три процесса:
  extract()  — после ответа, в фоне: нейронка смотрит на реплику хозяина и известные по теме факты → add / update / nothing.
  context()  — перед LLM-ответом: ядро портрета + факты, близкие по смыслу к реплике (эмбеддинги, только ПК).
  nightly()  — уборка: short старше N дней → long или archive; дубли схлопываются; портрет пересобирается раз в неделю.
Секреты (пароли, PIN, коды) не запоминаются никогда: фильтр до нейронки и проверка после.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlmodel import select

from ..brain import llm
from ..db import Fact, get_setting, log_action, session, set_setting

log = logging.getLogger("jarvis.memory")

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


# ---------------------------------------------------------------- настройки
def enabled() -> bool:
    from .. import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return bool(getattr(node, "enabled", True)) if node is not None else True


def where() -> str:
    from .. import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    w = str(getattr(node, "where", "cloud") or "cloud").lower()
    return w if w in ("cloud", "local", "auto") else "cloud"


def short_days() -> int:
    from .. import config as _c
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
    from .. import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return _num(node, "decay_half_life_days", 90.0, 1.0, 3650.0)


def decay_days() -> int:
    """Через столько дней неподтверждённый и почти не упоминавшийся факт уходит в архив (ночью)."""
    from .. import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return int(_num(node, "decay_days", 365.0, 1.0, 36500.0))


def decay_max_mentions() -> int:
    """Сколько упоминаний нужно факту, чтобы он НЕ счищался по decay_days («пельмени» сказали дважды — значит, живой)."""
    from .. import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return int(_num(node, "decay_max_mentions", 2.0, 0.0, 100.0))


# ---------------------------------------------------------------- предложения фактов (тост «Запомнить?»)
def suggest_enabled() -> bool:
    """Предлагать новые факты из разговора в ответе чата (кнопки «да/нет» на сайте)."""
    from .. import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return bool(getattr(node, "suggest", True))


def suggest_timeout() -> float:
    """Сколько секунд ждать извлечение фактов ради тоста; дольше — уходим в фон, как раньше."""
    from .. import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "memory", None)
    return _num(node, "suggest_timeout", 20.0, 1.0, 120.0)


# ---------------------------------------------------------------- модель
def _parse(raw: str) -> dict | None:
    raw = llm.strip_think(raw or "").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


async def _ask(system: str, user: str) -> tuple[dict | None, str]:
    """Маршрут cloud / auto / local (как у сортировщика и связей). Текст в облако проходит анонимайзер в cloud_chat."""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    w = where()
    cloud_ok, local_ok = llm.cloud_enabled(), await llm.ollama_available()

    async def cloud():
        return _parse(await llm.cloud_chat(system + "\nТолько JSON, без markdown.", user) or ""), "cloud"

    async def local():
        out = await llm.ollama_chat(msgs, temperature=0.1, json_mode=True)
        return _parse(out.get("content") or ""), "ollama"

    if w == "cloud":
        order = ([cloud] if cloud_ok else []) + ([local] if local_ok else [])
    elif w == "auto":
        order = ([local] if local_ok else []) + ([cloud] if cloud_ok else [])
    else:
        order = [local] if local_ok else []
    for fn in order:
        try:
            res, via = await fn()
        except Exception as e:
            log.warning("memory via %s failed: %s", fn.__name__, e)
            continue
        if res is not None:
            return res, via
    return None, "none"


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


async def add_fact(text: str, layer: str = "long", category: str = "быт", core: bool = False, source_msg: int | None = None,
                   confidence: float = 0.7) -> Fact | None:
    """Добавить факт. Секреты — никогда. Дубль (тот же текст или близость ≥0.9 в том же слое) — не плодим, обновляем дату."""
    text = _norm(text)
    if len(text) < 4 or SECRET_RX.search(text):
        return None
    layer = layer if layer in ("short", "long", "archive") else "short"
    category = category if category in CATEGORIES else "быт"
    vecs = await _embed([text])
    vec = vecs[0] if vecs else None
    with session() as s:
        live = list(s.exec(select(Fact).where(Fact.layer != "archive")))
        for f in live:
            same = f.text.lower() == text.lower() or (vec and _cos(vec, _vec(f.vector)) >= DEDUP_SCORE)
            if same:
                f.updated_at = datetime.now()
                if layer == "long" and f.layer == "short":
                    f.layer = "long"          # сказали ещё раз → устойчивое
                f.core = f.core or core
                s.add(f); s.commit(); s.refresh(f)
                set_fact_meta(f.id, last_seen=datetime.now())   # хозяин повторил факт в реплике — затухание заново
                return f
        f = Fact(text=text, layer=layer, category=category, core=core, source_msg=source_msg, confidence=confidence,
                 vector=json.dumps([round(x, 6) for x in vec]) if vec else "")
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
    with session() as s:
        for f in s.exec(select(Fact).where(Fact.layer != "archive")):
            if f.text.lower() == text.lower():
                f.updated_at = datetime.now(); f.core = f.core or core
                if layer == "long":
                    f.layer = "long"
                s.add(f); s.commit(); s.refresh(f)
                set_fact_meta(f.id, last_seen=datetime.now())
                return f
        f = Fact(text=text, layer=layer, category=category, core=core, confidence=confidence)
        s.add(f); s.commit(); s.refresh(f)
        log_action(s, "add_fact", "fact", f.id, text[:80], "chat"); s.commit()
        return f


async def update_fact(fid: int, text: str | None = None, layer: str | None = None, category: str | None = None,
                      core: bool | None = None, reason: str = "заменён") -> Fact | None:
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
                      uses=f.uses, last_used=f.last_used)
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


def list_facts(layer: str | None = None, limit: int = 500) -> list[Fact]:
    with session() as s:
        q = select(Fact)
        if layer:
            q = q.where(Fact.layer == layer)
        return list(s.exec(q.order_by(Fact.core.desc(), Fact.updated_at.desc()).limit(limit)))


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


def fact_meta(fact_ids: set[int] | None = None) -> dict[int, dict]:
    """{fact_id: {"last_seen", "confirmed", "archived"}} по колонкам v5. Без аргумента — по всем фактам."""
    with session() as s:
        rows = s.exec(text("SELECT id, last_seen_at, confirmed_at, archived_at FROM fact")).all()
    out = {int(r[0]): {"last_seen": _dt(r[1]), "confirmed": _dt(r[2]), "archived": _dt(r[3])} for r in rows}
    if fact_ids is None:
        return out
    empty = {"last_seen": None, "confirmed": None, "archived": None}
    return {i: out.get(i, empty) for i in fact_ids}


def set_fact_meta(fid: int, last_seen: datetime | None = None, confirmed: datetime | None = None,
                  archived: datetime | None = None, clear_archived: bool = False) -> None:
    """Одна UPDATE по колонкам v5. None в аргументе = не трогать; clear_archived — снять archived_at (восстановление)."""
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


# ---------------------------------------------------------------- предложения фактов (тост «Запомнить?»)
# Последнее предложение для текущего хода чата: Reply.suggest_fact дублирует его, а роутер-инжектор
# вшивает в JSON /api/chat и в SSE-событие done (эти два роута живут в чужих файлах — правим их ответы здесь).
_SUGGEST: dict = {}


def set_suggest(payload: dict | None, channel: str = "") -> None:
    _SUGGEST.clear()
    if payload:
        _SUGGEST.update({"fact": payload, "channel": channel, "at": datetime.now()})


def pop_suggest(max_age: float = 60.0) -> dict | None:
    """Забрать предложение для вшивания в ответ (не старше max_age секунд)."""
    item = dict(_SUGGEST) if _SUGGEST else None
    _SUGGEST.clear()
    if not item:
        return None
    at = item.get("at")
    if not isinstance(at, datetime) or (datetime.now() - at).total_seconds() > max_age:
        return None
    return item.get("fact")


def clear_suggest() -> None:
    _SUGGEST.clear()


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


# ---------------------------------------------------------------- контекст для модели
async def recall(text: str, limit: int = CTX_MAX, include_archived: bool = False) -> list[Fact]:
    """Факты, близкие по смыслу к реплике (эмбеддинги, локально). Без эмбеддингов — по словам.

    Затухание: у неподтверждённых фактов счёт режется на (1-decay)*DECAY_PENALTY, где
    decay = exp(-Δt/half_life). Старый неподтверждённый «пельмени» всплывает только на прямой
    вопрос (почти точное совпадение), а в фоне больше не тащится в каждый ответ.
    include_archived=True — ищем и среди архивных (восстановление забытого по прямому запросу)."""
    with session() as s:
        q = select(Fact) if include_archived else select(Fact).where(Fact.layer != "archive")
        live = list(s.exec(q))
    if not live:
        return []
    now = datetime.now()
    meta = fact_meta()
    # счёт затухания: ядро и подтверждённые не гаснут, у остальных референс — последнее упоминание в реплике
    def _decayed(f: Fact, sc: float) -> float:
        m = meta.get(f.id) or {}
        d = decay(bool(f.core), m.get("confirmed"), m.get("last_seen") or f.created_at, now)
        return sc - (1.0 - d) * DECAY_PENALTY
    vecs = await _embed([text])
    if vecs:
        scored = sorted(((_decayed(f, _cos(vecs[0], _vec(f.vector))), f) for f in live if f.vector), key=lambda x: -x[0])
        return [f for sc, f in scored if sc >= CTX_MIN_SCORE][:limit]
    words = {w[:-1] if len(w) > 4 else w for w in re.findall(r"[а-яёa-z]{3,}", text.lower())}
    # без эмбеддингов score = число совпавших слов; штраф затухания влияет только на порядок,
    # а порог — «хотя бы одно слово»: вычитать дробный штраф из 1 и сравнивать с 1 нельзя
    # (1 − ε < 1 — и одиночные совпадения пропадали бы, exp никогда не даёт ровно 1.0)
    scored: list[tuple[float, Fact]] = []
    for f in live:
        base = float(sum(1 for w in words if w in f.text.lower()))
        if base < 1:
            continue
        m = meta.get(f.id) or {}
        d = decay(bool(f.core), m.get("confirmed"), m.get("last_seen") or f.created_at, now)
        scored.append((base - (1.0 - d) * DECAY_PENALTY, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _sc, f in scored[:limit]]


async def context(text: str) -> str:
    """Блок для промпта: портрет + ядро + релевантное + стиль. Пусто — если памяти нет или выключена.
    Профиль стиля продублирован одной строкой и в system prompt (см. agent._system) — там он постоянен
    и не зависит от реплики, а блок «КАК ОН ПИШЕТ» ниже остаётся прежним контрактом (tests/test_judge)."""
    if not enabled():
        return ""
    core = [f for f in list_facts() if f.core and f.layer != "archive"][:CORE_MAX]
    rel = await recall(text)
    seen = {f.id for f in core}
    rel = [f for f in rel if f.id not in seen]
    # дубли схлопываем и в ядре, и в релевантном — «пельмени» дважды в промпте не нужны
    picked = _dedupe(core + rel)
    core = [f for f in picked if f.core]
    rel = [f for f in picked if not f.core]
    portrait = get_setting(PORTRAIT_KEY, "") or ""
    style = get_setting(STYLE_KEY, "") or ""
    if not core and not rel and not portrait and not style:
        return ""
    if core or rel:
        with session() as s:
            for f in core + rel:
                row = s.get(Fact, f.id)
                if row:
                    row.uses += 1; row.last_used = datetime.now(); s.add(row)
            s.commit()
    lines = ["ЧТО ТЫ ЗНАЕШЬ О ХОЗЯИНЕ (фон, а не материал для шуток: НЕ упоминай эти факты и имена, если реплика не о них — "
             "кот/семья/привычки в каждом ответе раздражают):"]
    if portrait:
        lines.append(portrait.strip())
    for f in core + rel:
        tag = " (сейчас)" if f.layer == "short" else ""
        lines.append(f"— {f.text}{tag}")
    if style:
        lines.append("КАК ОН ПИШЕТ (подстраивай тон и длину ответа, слова понимай по его словарю):")
        lines.append(style.strip())
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- извлечение из реплики
def worth_extracting(text: str, actions: list[str] | None = None) -> bool:
    """Стоит ли вообще звать нейронку: не команда-шаблон, не вопрос, не короткая реплика, не секрет."""
    t = (text or "").strip()
    if len(t.split()) < 4 or len(t) > 1500:
        return False
    if SECRET_RX.search(t):
        return False
    if t.endswith("?") or COMMAND_RX.match(t):
        return False
    # правило уже что-то записало (трата/событие/задача) — там факта о человеке нет; заметка и разговор — есть
    if actions and any(a in actions for a in ("add_expense", "add_income", "add_event", "add_task", "pay_debt", "transfer", "complete_task", "undo", "clarify")):
        return False
    return True


async def extract(text: str, msg_id: int | None = None) -> dict:
    """Нейронка решает, что запомнить из реплики. Возвращает {'added': [...], 'updated': [...], 'via': ...}."""
    if not enabled() or not worth_extracting(text):
        return {"added": [], "updated": [], "via": "skip"}
    known = await recall(text, limit=10)
    core = [f for f in list_facts() if f.core and f.layer != "archive"][:CORE_MAX]
    seen, ctx = set(), []
    for f in core + known:
        if f.id not in seen:
            seen.add(f.id); ctx.append(f)
    user = "РЕПЛИКА:\n" + llm._hide_secrets(text) + "\n\nИЗВЕСТНО:\n" + ("\n".join(f"[{f.id}] {f.text}" for f in ctx) or "(пока ничего)")
    d, via = await _ask(EXTRACT_PROMPT, user)
    if d is None:
        return {"added": [], "updated": [], "via": via}
    added, updated = [], []
    dismissed = _dismissed()   # «нет» в тосте: такую фразу хозяин просил не запоминать — молча не сохраняем
    ids_ok = {f.id for f in ctx}
    for u in (d.get("update") or [])[:5]:
        if not isinstance(u, dict):
            continue
        try:
            fid = int(str(u.get("id", "")).strip("[] "))
        except ValueError:
            continue
        if fid in ids_ok and _norm(str(u.get("text") or "")):
            f = await update_fact(fid, text=str(u["text"]), reason="уточнено из разговора")
            if f:
                updated.append(f)
    for a in (d.get("add") or [])[:5]:
        if not isinstance(a, dict) or not _norm(str(a.get("text") or "")):
            continue
        if _norm(str(a["text"])).lower() in dismissed:
            continue
        f = await add_fact(str(a["text"]), layer=str(a.get("layer") or "short"), category=str(a.get("category") or "быт"),
                           source_msg=msg_id, confidence=0.6)
        if f and f.created_at >= datetime.now() - timedelta(seconds=5):
            added.append(f)
    remind = None
    rm = d.get("remind")
    if isinstance(rm, dict) and _norm(str(rm.get("title") or "")):
        remind = _suggest_task(str(rm["title"]), rm.get("when"))
    if added or updated or remind:
        log.info("память: +%d / ~%d фактов%s via %s", len(added), len(updated), " + напоминание" if remind else "", via)
    return {"added": added, "updated": updated, "remind": remind, "via": via}


def _suggest_task(title: str, when) -> dict | None:
    """Напоминание, которое ассистент предложил сам: задача с источником proactive (ActionLog → «отмени» работает)."""
    from . import tasks
    title = _norm(title)[:120]
    title = title[0].upper() + title[1:]
    due = None
    if when:
        try:
            due = datetime.fromisoformat(str(when).replace(" ", "T"))
        except ValueError:
            due = None
        if due and due < datetime.now():
            due = None
    with session() as s:
        from ..db import Task
        for t in s.exec(select(Task).where(Task.done == False)):  # noqa: E712
            if t.title.strip().lower() == title.lower():
                return None   # такая уже есть — не дублируем и не сообщаем
    t = tasks.add_task(title, due, source="proactive")
    return {"id": t.id, "title": t.title, "due": t.due}


# ---------------------------------------------------------------- портрет и уборка
async def rebuild_portrait(force: bool = False) -> str | None:
    """Раз в неделю (или по кнопке): long-факты → 5–8 строк «кто мой хозяин»."""
    if not enabled():
        return None
    if not force:
        at = get_setting(PORTRAIT_AT_KEY, "")
        try:
            if at and datetime.fromisoformat(at) > datetime.now() - timedelta(days=7):
                return get_setting(PORTRAIT_KEY, "")
        except ValueError:
            pass
    facts = [f for f in list_facts("long")][:80]
    if len(facts) < 3:
        return get_setting(PORTRAIT_KEY, "")
    user = "\n".join(f"— {f.text}" for f in facts)
    w = where()
    cloud_ok, local_ok = llm.cloud_enabled(), await llm.ollama_available()
    text = None
    order = []
    if w == "cloud":
        order = (["cloud"] if cloud_ok else []) + (["local"] if local_ok else [])
    elif w == "auto":
        order = (["local"] if local_ok else []) + (["cloud"] if cloud_ok else [])
    else:
        order = ["local"] if local_ok else []
    for how in order:
        try:
            if how == "cloud":
                text = await llm.cloud_chat(PORTRAIT_PROMPT, user)
            else:
                out = await llm.ollama_chat([{"role": "system", "content": PORTRAIT_PROMPT}, {"role": "user", "content": user}], temperature=0.2)
                text = llm.strip_think(out.get("content") or "")
        except Exception as e:
            log.warning("portrait via %s: %s", how, e)
            text = None
        if text and text.strip():
            break
    if not text or not text.strip():
        return get_setting(PORTRAIT_KEY, "")
    text = "\n".join(l.strip() for l in text.strip().splitlines() if l.strip())[:1200]
    set_setting(PORTRAIT_KEY, text)
    set_setting(PORTRAIT_AT_KEY, datetime.now().isoformat())
    return text


async def rebuild_style(force: bool = False) -> str | None:
    """Раз в неделю (или по кнопке): последние ~200 реплик хозяина → 3–5 строк «как он пишет». Идёт в системный промпт рядом
    с портретом. В облако — через анонимайзер cloud_chat; секреты скрыты заранее."""
    if not enabled():
        return None
    if not force:
        at = get_setting(STYLE_AT_KEY, "")
        try:
            if at and datetime.fromisoformat(at) > datetime.now() - timedelta(days=7):
                return get_setting(STYLE_KEY, "")
        except ValueError:
            pass
    from ..db import ChatMessage
    with session() as s:
        rows = s.exec(select(ChatMessage).where(ChatMessage.role == "user").order_by(ChatMessage.id.desc()).limit(200)).all()
    lines = [llm._hide_secrets(r.text.strip())[:200] for r in reversed(rows) if r.text and len(r.text.strip()) >= 3]
    if len(lines) < 20:
        return get_setting(STYLE_KEY, "")
    user = "\n".join(lines)
    w = where()
    cloud_ok, local_ok = llm.cloud_enabled(), await llm.ollama_available()
    order = ((["cloud"] if cloud_ok else []) + (["local"] if local_ok else [])) if w == "cloud" else \
            ((["local"] if local_ok else []) + (["cloud"] if cloud_ok else [])) if w == "auto" else (["local"] if local_ok else [])
    text = None
    for how in order:
        try:
            if how == "cloud":
                text = await llm.cloud_chat(STYLE_PROMPT, user)
            else:
                out = await llm.ollama_chat([{"role": "system", "content": STYLE_PROMPT}, {"role": "user", "content": user}], temperature=0.2)
                text = llm.strip_think(out.get("content") or "")
        except Exception as e:
            log.warning("style via %s: %s", how, e)
            text = None
        if text and text.strip():
            break
    if not text or not text.strip():
        return get_setting(STYLE_KEY, "")
    text = "\n".join(l.strip() for l in text.strip().splitlines() if l.strip())[:800]
    set_setting(STYLE_KEY, text)
    set_setting(STYLE_AT_KEY, datetime.now().isoformat())
    return text


def style_line() -> str:
    """Профиль стиля хозяина ОДНОЙ строкой — идёт в system prompt (см. agent._system).
    Одна строка, не зависящая от реплики: не портит кэш промпта и не дублирует многострочный блок в каждом сообщении."""
    raw = get_setting(STYLE_KEY, "") or ""
    if not raw.strip():
        return ""
    out, used = [], 0
    for l in raw.splitlines():
        line = re.sub(r"^[\s—•\-–]+", "", l).strip()
        if not line:
            continue
        if used + len(line) > STYLE_LINE_MAX:
            break
        out.append(line)
        used += len(line) + 3
    return " · ".join(out)


async def nightly() -> dict:
    """Уборка: short старше N дней → long/archive (нейронка; без неё — long, если факт всплывал повторно, иначе archive);
    long без единого использования за 60 дней и не ядро → archive; портрет раз в неделю.
    Плюс затухание: неподтверждённые, старше decay_days и почти не упоминавшиеся → archive («затухло»)."""
    if not enabled():
        return {}
    await index_pending()
    cutoff = datetime.now() - timedelta(days=short_days())
    with session() as s:
        old_short = list(s.exec(select(Fact).where(Fact.layer == "short", Fact.created_at < cutoff)))
    promoted = archived = 0
    stamp_archived: list[int] = []   # id, которым проставим archived_at ПОСЛЕ коммита (вложенная сессия — это deadlock)
    if old_short:
        d, via = await _ask(PROMOTE_PROMPT, "\n".join(f"[{f.id}] {f.text}" for f in old_short))
        keep: set[int] = set()
        if d is not None:
            for x in d.get("keep") or []:
                try:
                    keep.add(int(str(x).strip("[] ")))
                except ValueError:
                    pass
        else:
            keep = {f.id for f in old_short if f.uses >= 2 or f.updated_at > f.created_at + timedelta(hours=1)}
        with session() as s:
            for f in old_short:
                row = s.get(Fact, f.id)
                if not row:
                    continue
                if row.id in keep:
                    row.layer = "long"; promoted += 1
                else:
                    row.layer, row.archive_reason = "archive", "устарело"; archived += 1; stamp_archived.append(row.id)
                row.updated_at = datetime.now(); s.add(row)
            s.commit()
    stale = datetime.now() - timedelta(days=UNUSED_DAYS)
    with session() as s:
        for f in s.exec(select(Fact).where(Fact.layer == "long", Fact.core == False, Fact.created_at < stale)):  # noqa: E712
            if not f.last_used and f.uses == 0:
                f.layer, f.archive_reason, f.updated_at = "archive", "не пригодился", datetime.now()
                s.add(f); archived += 1; stamp_archived.append(f.id)
        s.commit()
    # --- затухание: неподтверждённый факт, который за год почти не вспоминали, уходит в архив
    now = datetime.now()
    fade_cut = now - timedelta(days=decay_days())
    max_mentions = decay_max_mentions()
    with session() as s:
        live = list(s.exec(select(Fact).where(Fact.layer != "archive", Fact.core == False)))
    meta = fact_meta()
    faded = 0
    for f in live:
        m = meta.get(f.id) or {}
        if m.get("confirmed") is not None:
            continue                       # подтверждён («да» в тосте / восстановление) — не гаснет
        ref = m.get("last_seen") or f.created_at
        if ref <= fade_cut and f.uses < max_mentions:
            with session() as s:
                row = s.get(Fact, f.id)
                if row and row.layer != "archive":
                    row.layer, row.archive_reason, row.updated_at = "archive", "затухло", now
                    s.add(row); s.commit()
                    archived += 1; faded += 1; stamp_archived.append(f.id)
    for fid in dict.fromkeys(stamp_archived):   # без дублей: факт мог попасть в два прохода
        set_fact_meta(fid, archived=now)
    await rebuild_portrait()
    await rebuild_style()
    return {"promoted": promoted, "archived": archived}


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
