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
import re
from datetime import datetime, timedelta

from sqlmodel import select

from ..brain import llm
from ..db import Fact, get_setting, log_action, session, set_setting

log = logging.getLogger("assistant.memory")

CATEGORIES = ("о человеке", "предпочтение", "здоровье", "работа", "быт", "отношения", "привычка")
CTX_MAX = 6              # сколько релевантных фактов подтягиваем
CTX_MIN_SCORE = 0.45
CORE_MAX = 6             # ядерных — всегда
DEDUP_SCORE = 0.9
UNUSED_DAYS = 60         # long-факт, ни разу не пригодившийся за 60 дней (и не ядро) → архив
PORTRAIT_KEY = "user.portrait"
PORTRAIT_AT_KEY = "user.portrait_at"

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
        return f


def forget(fid: int, reason: str = "забыл по просьбе") -> Fact | None:
    with session() as s:
        f = s.get(Fact, fid)
        if not f:
            return None
        f.layer, f.archive_reason, f.updated_at = "archive", reason, datetime.now()
        s.add(f); s.commit(); s.refresh(f)
        return f


def restore(fid: int) -> Fact | None:
    with session() as s:
        f = s.get(Fact, fid)
        if not f:
            return None
        f.layer, f.archive_reason, f.replaced_by, f.updated_at = "long", "", None, datetime.now()
        s.add(f); s.commit(); s.refresh(f)
        return f


def list_facts(layer: str | None = None, limit: int = 500) -> list[Fact]:
    with session() as s:
        q = select(Fact)
        if layer:
            q = q.where(Fact.layer == layer)
        return list(s.exec(q.order_by(Fact.core.desc(), Fact.updated_at.desc()).limit(limit)))


def find_fact(query: str) -> Fact | None:
    """По подстроке среди живых фактов («забудь, что у меня кот» → факт про кота)."""
    q = _norm(query).lower()
    words = [w for w in re.findall(r"[а-яёa-z0-9]+", q) if len(w) >= 3]
    if not words:
        return None
    with session() as s:
        live = list(s.exec(select(Fact).where(Fact.layer != "archive")))
    best, best_n = None, 0
    for f in live:
        t = f.text.lower()
        n = sum(1 for w in words if (w[:-1] if len(w) > 4 else w) in t)
        if n > best_n:
            best, best_n = f, n
    return best if best_n >= max(1, len(words) // 2) else None


# ---------------------------------------------------------------- контекст для модели
async def recall(text: str, limit: int = CTX_MAX) -> list[Fact]:
    """Факты, близкие по смыслу к реплике (эмбеддинги, локально). Без эмбеддингов — по словам."""
    with session() as s:
        live = list(s.exec(select(Fact).where(Fact.layer != "archive")))
    if not live:
        return []
    vecs = await _embed([text])
    if vecs:
        scored = sorted(((_cos(vecs[0], _vec(f.vector)), f) for f in live if f.vector), key=lambda x: -x[0])
        return [f for sc, f in scored if sc >= CTX_MIN_SCORE][:limit]
    words = {w[:-1] if len(w) > 4 else w for w in re.findall(r"[а-яёa-z]{3,}", text.lower())}
    scored = sorted(((sum(1 for w in words if w in f.text.lower()), f) for f in live), key=lambda x: -x[0])
    return [f for n, f in scored if n >= 1][:limit]


async def context(text: str) -> str:
    """Блок для системного промпта: портрет + ядро + релевантное. Пусто — если памяти нет или выключена."""
    if not enabled():
        return ""
    core = [f for f in list_facts() if f.core and f.layer != "archive"][:CORE_MAX]
    rel = await recall(text)
    seen = {f.id for f in core}
    rel = [f for f in rel if f.id not in seen]
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


async def nightly() -> dict:
    """Уборка: short старше N дней → long/archive (нейронка; без неё — long, если факт всплывал повторно, иначе archive);
    long без единого использования за 60 дней и не ядро → archive; портрет раз в неделю."""
    if not enabled():
        return {}
    await index_pending()
    cutoff = datetime.now() - timedelta(days=short_days())
    with session() as s:
        old_short = list(s.exec(select(Fact).where(Fact.layer == "short", Fact.created_at < cutoff)))
    promoted = archived = 0
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
                    row.layer, row.archive_reason = "archive", "устарело"; archived += 1
                row.updated_at = datetime.now(); s.add(row)
            s.commit()
    stale = datetime.now() - timedelta(days=UNUSED_DAYS)
    with session() as s:
        for f in s.exec(select(Fact).where(Fact.layer == "long", Fact.core == False, Fact.created_at < stale)):  # noqa: E712
            if not f.last_used and f.uses == 0:
                f.layer, f.archive_reason, f.updated_at = "archive", "не пригодился", datetime.now(); s.add(f); archived += 1
        s.commit()
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
    """«Что ты обо мне знаешь?» — портрет + ядро + немного long."""
    st = stats()
    facts = [f for f in list_facts() if f.layer != "archive"]
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
