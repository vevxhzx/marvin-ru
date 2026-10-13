# База llm: конфиг, константы, общее состояние и мелкие помощники.
from __future__ import annotations

import contextvars
import logging
import os
import re
import time
from dataclasses import dataclass, field, replace
import httpx
from typing import Awaitable, Callable
from ...config import cfg

log = logging.getLogger("jarvis.llm")
__all__ = [
    "AVAIL_TTL",
    "CLOUD_BASE_URL",
    "CLOUD_KEY",
    "CLOUD_MODEL",
    "CLOUD_PERSONAL",
    "CLOUD_PROVIDER",
    "CLOUD_PROXY",
    "CLOUD_VISION_MODELS",
    "CLOUD_VOICE_MODEL",
    "EMBED_MODEL",
    "GAME_MODE",
    "GEMINI_AUTO",
    "GEMINI_KEY",
    "GEMINI_MODEL",
    "GEMINI_PROXY",
    "GROQ_TOOLS_PREFER",
    "LAST_CLOUD_ERROR",
    "LAST_GEMINI_ERROR",
    "LMSTUDIO_BASE",
    "LMSTUDIO_ENABLED",
    "LMSTUDIO_MODEL",
    "LMSTUDIO_USE",
    "MARK_SOURCE",
    "MODE",
    "OLLAMA_KEEP_ALIVE",
    "OLLAMA_MODEL",
    "OLLAMA_NUM_CTX",
    "OLLAMA_URL",
    "PROVIDERS",
    "SMALL_KEEP_ALIVE",
    "SMALL_MODEL",
    "VISION_CLOUD_OK",
    "VISION_MODEL",
    "VISION_WHERE",
    "_ANON_HINT",
    "_AVAIL_CACHE",
    "_CLOUD_RESOLVED",
    "_CLOUD_ROUTE_OK",
    "_CLOUD_VISION_GOOD",
    "_GROQ_TOOLS_MODEL",
    "_LMS_LAST_ERROR",
    "_LMS_MODELS_CACHE",
    "_NO_THINK_HINT",
    "_OR_AVOID",
    "_OR_AVOID_RUNTIME",
    "_OR_PREFER",
    "_PII",
    "_PREFERRED",
    "_REASON_VALUES",
    "_RESOLVED_MODEL",
    "_SECRET_KEY_RX",
    "_SECRET_VAL_RX",
    "_SMALL_MISSING",
    "_SMALL_SEEN",
    "_THINK_BLOCK_RX",
    "_THINK_EN_RX",
    "_THINK_OPEN_RX",
    "_THINK_RX",
    "_USER_ACTIVE_AT",
    "_VISION_LOCAL_OK",
    "_VOICE_MODEL_BAD",
    "_cloud_base_url",
    "_cloud_cfg",
    "_cloud_model",
    "_cloud_setting",
    "_hide_secrets",
    "_known_names",
    "_lms",
    "_lms_fail",
    "_lms_ok",
    "_local_client",
    "_local_only_refuse",
    "_names_cache",
    "_norm_lms_base",
    "_reasoning_body",
    "_vision_cfg",
    "anonymize",
    "cfg",
    "cloud_enabled",
    "cloud_max_tokens",
    "cloud_personal_tools",
    "cloud_timeout",
    "cloud_title",
    "cost_usd",
    "pricing_ready",
    "gemini_enabled",
    "lms_last_error",
    "local_only",
    "log",
    "mark_user_active",
    "pricing_for",
    "reasoning_mode",
    "reload_cloud_settings",
    "reload_lmstudio_settings",
    "reload_small_settings",
    "set_game_mode",
    "short_mode",
    "strip_think",
    "token_sink",
    "tokens_gemini",
    "Usage",
    "tokens_ollama",
    "tokens_openai",
    "usage_note",
    "usage_now",
    "usage_reset",
    "user_recent",
]

# localhost на Windows часто резолвится в ::1 (IPv6), а Ollama слушает 127.0.0.1 — ходим по IPv4 напрямую
OLLAMA_URL = cfg.brain.ollama.url.rstrip("/").replace("://localhost", "://127.0.0.1")


def _local_client(timeout: float) -> httpx.AsyncClient:
    """Клиент для локальной Ollama: без системного прокси/VPN (trust_env=False)."""
    return httpx.AsyncClient(timeout=timeout, trust_env=False)
OLLAMA_MODEL = cfg.brain.ollama.model
# держать модель в видеопамяти между запросами (иначе Ollama выгружает через 5 мин и первый ответ ждёт 5–15 с)
OLLAMA_KEEP_ALIVE = str(getattr(cfg.brain.ollama, "keep_alive", "2h") or "2h")
OLLAMA_NUM_CTX = int(getattr(cfg.brain.ollama, "num_ctx", 8192) or 8192)
# маленькая модель для мини-задач (судья «трата или заказ?», «оставить или в архив», проактивные фразы): 0.6–1.7B,
# грузится по требованию и сама выгружается через small_keep_alive — не сидит в видеопамяти рядом с играми/рендером
SMALL_MODEL = str(getattr(cfg.brain.ollama, "small_model", "") or "").strip()
SMALL_KEEP_ALIVE = str(getattr(cfg.brain.ollama, "small_keep_alive", "5m") or "5m")
# Второй локальный движок — LM Studio (OpenAI-совместимый /chat/completions). Работает одновременно
# с Ollama: малая модель и эмбеддинги остаются там, а сюда отдаётся выбранное в brain.lmstudio.use
# (main — основные ответы вместо модели Ollama, small — мини-задачи вместо малой модели).
_lms = getattr(cfg.brain, "lmstudio", None)


def _norm_lms_base(raw: object) -> str:
    """Адрес LM Studio к виду под OpenAI-запросы: голый хост без пути сам
    дополняется до /v1 (LM Studio слушает именно там), хвосты /api и /api/v1
    тоже чистятся в /v1. Чужой путь не трогаем."""
    from urllib.parse import urlsplit
    b = (str(raw or "") or "").strip().rstrip("/") or "http://127.0.0.1:1234/v1"
    low = b.lower()
    if low.endswith("/api/v1"):
        b = b[: -len("/api/v1")] + "/v1"
    elif low.endswith("/api"):
        b = b[: -len("/api")] + "/v1"
    else:
        try:
            if not urlsplit(b).path.strip("/"):
                b += "/v1"
        except Exception:
            pass
    return b


_LMS_LAST_ERROR: str | None = None   # почему LM Studio не ответил в последний раз — для честных логов


def _lms_fail(why: str) -> None:
    global _LMS_LAST_ERROR
    _LMS_LAST_ERROR = why
    log.debug("LM Studio: %s", why)


def _lms_ok() -> None:
    global _LMS_LAST_ERROR
    _LMS_LAST_ERROR = None


def lms_last_error() -> str:
    """Причина последнего сбоя LM Studio (пусто — сбоев не было)."""
    return _LMS_LAST_ERROR or ""


LMSTUDIO_ENABLED = bool(getattr(_lms, "enabled", False))
LMSTUDIO_BASE = _norm_lms_base(getattr(_lms, "base_url", ""))
LMSTUDIO_MODEL = (str(getattr(_lms, "model", "") or "") or "google/gemma-4-e4b").strip()
LMSTUDIO_USE = (str(getattr(_lms, "use", "") or "") or "main").strip().lower()
if LMSTUDIO_USE not in ("main", "small"):
    LMSTUDIO_USE = "main"
_LMS_MODELS_CACHE: tuple[float, list[str]] = (0.0, [])   # модели, загруженные в LM Studio (кэш 60 с)
_SMALL_MISSING: set[str] = set()   # модели, которых нет в Ollama — не долбить каждый раз
_SMALL_SEEN: set[str] = set()      # чтобы «на месте» написать один раз, а не при каждой проверке   # 4096 не хватало: схемы инструментов + промпт + история ≈ 4.5–5k токенов → Ollama резала промпт и обрывала ответ
# режим короткого ответа (голос): ограничение длины генерации — для TTS и восприятия на слух
short_mode: contextvars.ContextVar[bool] = contextvars.ContextVar("short_mode", default=False)
GEMINI_KEY = (cfg.brain.gemini.api_key or "").strip()
GEMINI_MODEL = (str(cfg.brain.gemini.model or "auto")).strip().lower().replace("models/", "") or "auto"
if not GEMINI_MODEL.startswith("gemini"):
    GEMINI_MODEL = "auto"   # «auto», «авто», опечатка — что угодно, кроме имени модели, значит «выбери сам»
# предпочтения при автоподборе: новее и «flash» — в приоритете, preview — только если нет стабильной
_PREFERRED = ["gemini-3.5-flash", "gemini-3.1-flash", "gemini-3-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite",
              "gemini-3-flash-preview", "gemini-2.5-pro"]
_RESOLVED_MODEL: str | None = None
MODE = cfg.brain.mode  # local / hybrid / cloud
GAME_MODE = False      # «игровой режим»: локальную модель не трогаем, всё в облако (см. set_game_mode)


async def set_game_mode(on: bool) -> str:
    from .lmstudio import reload_lmstudio
    from .ollama import unload_ollama, warm_ollama
    global GAME_MODE, _AVAIL_CACHE
    GAME_MODE = on
    _AVAIL_CACHE = (0.0, False)   # сбросить кэш доступности: после «игра окончена» модель должна вернуться сразу
    if on:
        freed = await unload_ollama()
        try:
            from ...voice import stt as _stt
            whisper_freed = _stt.unload_stt()
        except Exception as e:  # pragma: no cover
            log.debug("whisper unload failed: %s", e)
            whisper_freed = False
        tail = " + whisper выгружен из видеопамяти" if whisper_freed else ""
        return ("Игровой режим: локальная модель выгружена из видеопамяти" + tail + ", до отмены отвечаю только через облако "
                "(команды-шаблоны работают как обычно). «Игра окончена» — вернуть.") if freed else \
               "Игровой режим включён (Ollama не отвечала — выгружать нечего). Всё в облако, сэр."
    # выход из игры: модель грузим обратно СЕЙЧАС, в фоне (3–4 ГБ с диска в видеокарту — 5–15 с), а не при первой команде,
    # иначе первый ответ после катки ждал бы загрузку целиком
    import asyncio
    asyncio.get_running_loop().create_task(warm_ollama())
    asyncio.get_running_loop().create_task(reload_lmstudio())
    return "Игровой режим выключен, локальный мозг прогревается — через несколько секунд в строю. Как сыграли, сэр?"
EMBED_MODEL = getattr(cfg.brain.ollama, "embed_model", None) or "nomic-embed-text"

# Куда отдавать токены по мере генерации (ставит /api/chat/stream или TG-бот). None — не стримим.
token_sink: contextvars.ContextVar[Callable[[str], Awaitable[None]] | None] = contextvars.ContextVar("token_sink", default=None)
GEMINI_AUTO = bool(getattr(cfg.brain.gemini, "auto", True))

# ---- Облако: сменный провайдер. brain.cloud.provider = gemini | openrouter | groq | deepseek | nvidia | custom
_cloud_cfg = getattr(cfg.brain, "cloud", None)
CLOUD_PROVIDER = (str(getattr(_cloud_cfg, "provider", "") or "") or ("gemini" if (cfg.brain.gemini.api_key or "").strip() else "")).strip().lower()
CLOUD_KEY = (str(getattr(_cloud_cfg, "api_key", "") or "")).strip()
CLOUD_MODEL = (str(getattr(_cloud_cfg, "model", "") or "")).strip()
CLOUD_BASE_URL = (str(getattr(_cloud_cfg, "base_url", "") or "")).strip().rstrip("/")
CLOUD_PROXY = (str(getattr(_cloud_cfg, "proxy", "") or "")).strip() or None
# модель для голосовых ответов (пусто = та же). У Groq «compound» ходит в интернет и думает 3–8 с — для голоса берём обычную быструю.
CLOUD_VOICE_MODEL = (str(getattr(_cloud_cfg, "voice_model", "") or "")).strip()
# ФАЗА 6: brain.cloud.personal_tools — согласие отдавать облачной модели личные данные (заметки/память/люди/сводки).
# Дефолт False: в режиме brain.mode=cloud облако получает инструменты записи, но не видит личных данных.
CLOUD_PERSONAL = bool(getattr(_cloud_cfg, "personal_tools", False))


def cloud_personal_tools() -> bool:
    """Можно ли облачной модели (режим brain.mode=cloud) отдавать личные данные. Дефолт — нет."""
    return CLOUD_PERSONAL

# Готовые пресеты: адрес + бесплатная модель по умолчанию. Все — OpenAI-совместимый /chat/completions.
# Режим cloud + инструменты у Groq: модель берём из живого списка /models (Groq часто выводит модели из оборота:
# llama-4-scout и qwen3-32b исчезли летом 2026, llama-3.x ушли в Enterprise). Порядок — предпочтение.
GROQ_TOOLS_PREFER = ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "meta-llama/llama-4-scout-17b-16e-instruct",
                     "qwen/qwen3-32b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant")
_GROQ_TOOLS_MODEL: str | None = None
PROVIDERS: dict[str, dict] = {
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "auto",
                   "title": "OpenRouter", "free": True, "ru_ok": True, "key_url": "https://openrouter.ai/keys"},
    "groq":       {"base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b",   # llama-3.3-70b отключена 16.08.2026
                   "title": "Groq", "free": True, "ru_ok": True, "key_url": "https://console.groq.com/keys"},
    "nvidia":     {"base_url": "https://integrate.api.nvidia.com/v1", "model": "deepseek-ai/deepseek-v3.1",
                   "title": "NVIDIA NIM", "free": True, "ru_ok": True, "key_url": "https://build.nvidia.com/"},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
                   "title": "DeepSeek (платно, копейки)", "free": False, "ru_ok": True, "key_url": "https://platform.deepseek.com/api_keys"},
    "custom":     {"base_url": "", "model": "", "title": "Свой OpenAI-совместимый", "free": None, "ru_ok": None, "key_url": ""},
}
LAST_CLOUD_ERROR: str | None = None
_CLOUD_RESOLVED: str | None = None
_VOICE_MODEL_BAD: set[str] = set()   # голосовые модели, которые провайдер отверг (404) — больше не пробуем
# для OpenRouter «auto» = самая толковая бесплатная модель из живого списка (список меняется каждый месяц)
_OR_PREFER = ["deepseek", "qwen", "glm", "kimi", "minimax", "gpt-oss", "llama", "gemma", "nemotron-3-super", "nemotron-3-ultra", "mistral"]
_OR_AVOID = ("safety", "code", "fin", "sante", "note", "vision", "audio", "embed", "guard")
_OR_AVOID_RUNTIME: set[str] = set()   # модели, отвалившиеся в этой сессии
MARK_SOURCE = bool(getattr(cfg.brain.gemini, "mark_source", True))


# ---------------- Ollama ----------------
# Ollama обрабатывает запросы по одному: фоновая уборка заметок/связей, влезшая перед репликой пользователя, задерживает его
# ответ на весь свой прогон (5–20 с). Пользователь в чате → фон ждёт.
_USER_ACTIVE_AT = 0.0


def mark_user_active() -> None:
    global _USER_ACTIVE_AT
    _USER_ACTIVE_AT = time.monotonic()


def user_recent(seconds: float = 90) -> bool:
    """Пользователь писал/говорил недавно — фоновым задачам на локальной модели лучше подождать следующего прохода."""
    return time.monotonic() - _USER_ACTIVE_AT < seconds


_AVAIL_CACHE: tuple[float, bool] = (0.0, False)
AVAIL_TTL = 15.0


_THINK_RX = re.compile(r"qwen3|gemma4|deepseek-r1|deepseek-reasoner|gpt-oss|magistral|phi4-reasoning", re.I)
_THINK_BLOCK_RX = re.compile(r"<think>.*?</think>\s*", re.S | re.I)
_THINK_OPEN_RX = re.compile(r"^\s*<think>", re.I)
# Модель вываливает свои «мысли» в content английскими (без маркера), обычно обрезанные по лимиту:
# «Here’s a thinking process: 1. Analyze User Input…». Это не ответ — раньше уходило человеку как есть.
_THINK_EN_RX = re.compile(r"^\s*(?:here'?s\s+(?:a\s+|my\s+|the\s+)?thinking\s+process|thinking\s*:|"
                          r"let(?:'|’)?s\s+(?:think|start\s+by|begin)|first[,\s]+let\s+(?:me\s+)?think|"
                          r"the\s+user\s+(?:wants|asks|is\s+asking|needs)|i\s+(?:need|should)\s+to\s+(?:analyze|consider|think))\b", re.I)


def strip_think(text: str | None) -> str:
    """Убрать «размышления» reasoning-моделей из ответа. Иногда qwen3/gpt-oss всё равно кладут <think>…</think>
    прямо в content — пользователь должен видеть только ответ."""
    if not text:
        return ""
    t = _THINK_BLOCK_RX.sub("", text)
    if _THINK_EN_RX.match(t):
        # сплошные мысли английским в content: отдавать человеку такое нельзя — пусть ответит другой путь
        return ""
    if _THINK_OPEN_RX.match(t):
        # незакрытый <think>: модель не успела ответить — берём последний абзац, который похож на ответ
        body = t.split("<think>", 1)[1]
        paras = [x.strip() for x in re.split(r"\n{2,}", body) if x.strip()]
        t = paras[-1] if paras else ""
        t = re.sub(r"^(\*\*)?(Option|Вариант|Draft|Черновик)[^:]*:\s*(\*\*)?", "", t, flags=re.I)
    return t.strip()


def reload_lmstudio_settings() -> None:
    """LM Studio меняется с сайта без перезапуска: перечитать адрес, модель и роль."""
    global LMSTUDIO_ENABLED, LMSTUDIO_BASE, LMSTUDIO_MODEL, LMSTUDIO_USE, _LMS_MODELS_CACHE
    from ... import config as _c
    _c.refresh()
    lms = getattr(_c.cfg.brain, "lmstudio", None)
    LMSTUDIO_ENABLED = bool(getattr(lms, "enabled", False))
    LMSTUDIO_BASE = _norm_lms_base(getattr(lms, "base_url", ""))
    LMSTUDIO_MODEL = (str(getattr(lms, "model", "") or "") or "google/gemma-4-e4b").strip()
    LMSTUDIO_USE = (str(getattr(lms, "use", "") or "") or "main").strip().lower()
    if LMSTUDIO_USE not in ("main", "small"):
        LMSTUDIO_USE = "main"
    _LMS_MODELS_CACHE = (0.0, [])


# ---------------- Gemini ----------------
# Анонимайзер: убираем то, что похоже на личные данные, перед отправкой в облако.
_PII = [
    (re.compile(r"\+?\d[\d\s\-()]{9,}\d"), "[телефон]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b"), "[карта]"),
    (re.compile(r"\b\d[\d\s]*(?:[.,]\d+)?\s*(?:₽|руб\w*|тыс\w*|к\b|млн)"), "[сумма]"),
    (re.compile(r"\b(?:[А-ЯЁ][а-яё]+\s+)?[А-ЯЁ][а-яё]+(?:ович|евич|овна|евна|ична)\b"), "[имя]"),  # Иван Петрович
    # секреты: «пароль от вайфая qwerty123», «пин 4821», «код из смс 384712», «cvv 123», ключи API — в облако не уходят никогда
    (re.compile(r"\b(?:sk|gsk|xai|sk-or|ghp|AIza)[-_][A-Za-z0-9_\-]{16,}"), "[ключ]"),
]
# «пароль от вайфая qwerty123», «пин карты 4821», «код из смс 384712», «password: hunter2» — после ключевого слова
# скрываем ближайший токен, похожий на секрет (латиница/цифры/символы, не русское слово)
_SECRET_KEY_RX = re.compile(r"(парол[ьяюе]\w*|pass(?:word|wd)?|пин(?:-код)?|pin|cvv|cvc|код\s+(?:из\s+)?(?:смс|sms|подтверждени\w*|от\s+[а-яё]+|доступа)|секретн?\w*\s+(?:слово|ключ|код)|api[- ]?key|токен\w*|token)\b", re.I)
# между словом и значением — до трёх русских слов («от вайфая», «карты», «бота в телеге»); значение — не русское слово
_SECRET_VAL_RX = re.compile(r"[:=—\-]?\s*(?:[а-яё«»\"'\-]+\s+){0,3}[:=—\-]?\s*((?=\S*[A-Za-z0-9])[^\s,;]{3,})")


def _hide_secrets(text: str) -> str:
    out, pos = [], 0
    for m in _SECRET_KEY_RX.finditer(text):
        if m.start() < pos:
            continue
        v = _SECRET_VAL_RX.match(text, m.end())
        if not v:
            continue
        out.append(text[pos:v.start(1)]); out.append("[скрыто]"); pos = v.end(1)
    out.append(text[pos:])
    return "".join(out)


def anonymize(text: str) -> str:
    text = _hide_secrets(text)
    for rx, repl in _PII:
        text = rx.sub(repl, text)
    # имена людей, которые уже фигурируют в твоей базе (события «встреча с Ваней», долги «Ване»)
    for name in _known_names():
        text = re.sub(rf"\b{re.escape(name)}\w*", "[имя]", text, flags=re.I)
    return text


# Обезличенный текст уходит в облако, и модель в ответе повторяла плейсхолдер («Тратил пока [сумма]»).
# Говорим прямо: скобки в ответ не тащить, а про цифру — молчать или сказать без конкретики.
# Значения мы ей всё равно не показываем — приватность не страдает, а мусор в ответе пропадает.
_ANON_HINT = ("\n\nВажно: в переданном тебе тексте часть данных скрыта плейсхолдерами — "
              "[сумма], [имя], [телефон], [email], [карта], [ключ], [скрыто]. "
              "Никогда не повторяй такие скобки в ответе (не пиши «[сумма]» и подобное). "
              "Если для ответа нужно скрытое значение — обойдись без конкретной цифры "
              "(«некоторая сумма», «один из контактов») или не упоминай это место.")


_names_cache: tuple[float, list[str]] = (0.0, [])


def _known_names() -> list[str]:
    """Собираем имена собственные из базы (слова с заглавной буквы в названиях событий/долгов).

    Сбой БД здесь НЕЛЬЗЯ глотать молча: анонимайзер продолжит работать, но перестанет маскировать
    имена людей, и они уйдут в облако открытым текстом. Поэтому except только логирует."""
    import time
    global _names_cache
    if time.time() - _names_cache[0] < 300:
        return _names_cache[1]
    names: set[str] = set()
    try:
        from sqlmodel import select
        from ...db import Debt, Event, session
        with session() as s:
            titles = [e.title for e in s.exec(select(Event))] + \
                     [d.title for d in s.exec(select(Debt))] + [d.creditor or "" for d in s.exec(select(Debt))]
        for t in titles:
            words = t.split()
            for i, w in enumerate(words):
                # первое слово названия почти всегда просто с заглавной («Ужин с Катей») — имя ищем дальше
                if i == 0 and len(words) > 1:
                    continue
                if re.fullmatch(r"[А-ЯЁ][а-яё]{2,}", w.strip(",.!?")):
                    w = w.strip(",.!?")
                    names.add(w[:-2] if len(w) >= 5 else w[:-1])  # «Ваней» → «Ван» ловит Ваня/Ване/Ваню
    except Exception as e:
        # Тишина здесь = утечка имён. Если выборка имён из БД упала, анонимайзер продолжает
        # работать, но перестаёт маскировать людей («встреча с Ваней» → «встреча с Ваней» в облаке).
        # Ошибка не фатальна — текст всё равно уйдёт, — но обязана быть видна в логе.
        log.warning("анонимайзер: не смог собрать известные имена из базы (%s) — имена людей "
                    "могут уйти в облако без маскирования", type(e).__name__)
    _names_cache = (time.time(), sorted(names, key=len, reverse=True))
    return _names_cache[1]


def gemini_enabled() -> bool:
    return bool(GEMINI_KEY) and MODE in ("hybrid", "cloud")


def cloud_enabled() -> bool:
    """Есть ли хоть какое-то облако: выбранный OpenAI-совместимый провайдер с ключом, либо Gemini."""
    if MODE not in ("hybrid", "cloud"):
        return False
    if CLOUD_PROVIDER and CLOUD_PROVIDER != "gemini":
        return bool(CLOUD_KEY) and bool(_cloud_base_url())
    return gemini_enabled()


def cloud_title() -> str:
    if CLOUD_PROVIDER and CLOUD_PROVIDER != "gemini":
        return PROVIDERS.get(CLOUD_PROVIDER, PROVIDERS["custom"])["title"]
    return "Gemini"


def _cloud_base_url() -> str:
    return CLOUD_BASE_URL or PROVIDERS.get(CLOUD_PROVIDER, {}).get("base_url", "")


# Аварийный клапан local-first: в режиме `local` в облако не уходит НИЧЕГО. Проверка стоит в самой
# точке отправки, а не только в cloud_enabled(), — чтобы новый путь (зрение, health-check, фолбэк)
# не смог отправить данные в облако, не задев гарантию. cloud_enabled() остаётся как был.
def _local_only_refuse() -> bool:
    """True — запрос в облако запрещён режимом local. Пишет в лог (без содержимого запроса)."""
    if MODE == "local":
        log.info("облако: отказ — режим local (текст запроса не отправлялся)")
        return True
    return False


def local_only() -> bool:
    return MODE == "local"


def _cloud_model() -> str:
    m = CLOUD_MODEL or PROVIDERS.get(CLOUD_PROVIDER, {}).get("model", "")
    if m == "auto":
        return _CLOUD_RESOLVED or "auto"
    return m


_CLOUD_ROUTE_OK: tuple[str, str | None] | None = None   # маршрут, который последний раз сработал


def reload_small_settings() -> None:
    """Малая модель меняется с сайта без перезапуска: перечитать имя и keep_alive, сбросить «нет в Ollama»."""
    global SMALL_MODEL, SMALL_KEEP_ALIVE, _AVAIL_CACHE
    from ... import config as _c
    _c.refresh()
    SMALL_MODEL = str(getattr(_c.cfg.brain.ollama, "small_model", "") or "").strip()
    SMALL_KEEP_ALIVE = str(getattr(_c.cfg.brain.ollama, "small_keep_alive", "5m") or "5m")
    _SMALL_MISSING.clear(); _SMALL_SEEN.clear()
    _AVAIL_CACHE = (0.0, False)   # следующая проверка Ollama заново посмотрит, есть ли модель


def reload_cloud_settings() -> str:
    """Перечитать brain.cloud.* из config.yaml без перезапуска и сбросить кэш (модель/маршрут/ошибку)."""
    global CLOUD_PROVIDER, CLOUD_KEY, CLOUD_MODEL, CLOUD_BASE_URL, CLOUD_PROXY, MODE, GEMINI_AUTO
    global _CLOUD_RESOLVED, _CLOUD_ROUTE_OK, LAST_CLOUD_ERROR
    global GEMINI_KEY, GEMINI_MODEL, GEMINI_PROXY, MARK_SOURCE, _RESOLVED_MODEL, LAST_GEMINI_ERROR
    from ... import config as _c
    _c.refresh()
    cc = getattr(_c.cfg.brain, "cloud", None)
    CLOUD_PROVIDER = (str(getattr(cc, "provider", "") or "") or ("gemini" if (_c.cfg.brain.gemini.api_key or "").strip() else "")).strip().lower()
    CLOUD_KEY = (str(getattr(cc, "api_key", "") or "")).strip()
    CLOUD_MODEL = (str(getattr(cc, "model", "") or "")).strip()
    CLOUD_BASE_URL = (str(getattr(cc, "base_url", "") or "")).strip().rstrip("/")
    CLOUD_PROXY = (str(getattr(cc, "proxy", "") or "")).strip() or None
    global CLOUD_PERSONAL
    CLOUD_PERSONAL = bool(getattr(cc, "personal_tools", False))
    MODE = _c.cfg.brain.mode
    GEMINI_AUTO = bool(getattr(_c.cfg.brain.gemini, "auto", True))
    # ключ/модель Gemini тоже меняются с сайта — без этого смена ключа требовала перезапуска
    GEMINI_KEY = (_c.cfg.brain.gemini.api_key or "").strip()
    GEMINI_MODEL = (str(_c.cfg.brain.gemini.model or "auto")).strip().lower().replace("models/", "") or "auto"
    if not GEMINI_MODEL.startswith("gemini"):
        GEMINI_MODEL = "auto"
    GEMINI_PROXY = (getattr(_c.cfg.brain.gemini, "proxy", "") or "").strip() or None
    MARK_SOURCE = bool(getattr(_c.cfg.brain.gemini, "mark_source", True))
    _RESOLVED_MODEL = None
    LAST_GEMINI_ERROR = None
    global OLLAMA_MODEL, OLLAMA_URL, VISION_MODEL
    OLLAMA_MODEL = str(_c.cfg.brain.ollama.model or "")
    OLLAMA_URL = str(os.getenv("OLLAMA_URL") or _c.cfg.brain.ollama.url or OLLAMA_URL).rstrip("/").replace("://localhost", "://127.0.0.1")
    VISION_MODEL = str(getattr(_c.cfg.brain.ollama, "vision_model", "") or "")
    if not VISION_MODEL and re.search(r"qwen3\.5|qwen3\.6|gemma3|gemma4|llava|minicpm-v|qwen2\.5vl|moondream|llama3\.2-vision", OLLAMA_MODEL, re.I):
        VISION_MODEL = OLLAMA_MODEL
    global VISION_WHERE, VISION_CLOUD_OK, _VISION_LOCAL_OK
    _vc = getattr(_c.cfg.brain, "vision", None)
    VISION_WHERE = str(getattr(_vc, "where", "auto") or "auto").lower()
    VISION_WHERE = VISION_WHERE if VISION_WHERE in ("auto", "cloud", "local") else "auto"
    # ФАЗА 6: по умолчанию в облако картинки НЕ уходят — нужен явный brain.vision.allow_cloud: true
    # (дефолт совпадает с описанием настройки в core/config.py; старые config.yaml с allow_cloud: true не затронуты)
    VISION_CLOUD_OK = bool(getattr(_vc, "allow_cloud", False))
    _VISION_LOCAL_OK = None
    _CLOUD_RESOLVED = None
    _CLOUD_ROUTE_OK = None
    global _GROQ_TOOLS_MODEL
    _GROQ_TOOLS_MODEL = None
    _OR_AVOID_RUNTIME.clear()
    LAST_CLOUD_ERROR = None
    log.info("Облако перечитано: %s, модель %s, ключ %s, режим %s", cloud_title(), _cloud_model() or "по умолчанию",
             "задан" if CLOUD_KEY else "НЕ ЗАДАН", MODE)
    return f"{cloud_title()} · модель {_cloud_model() or 'по умолчанию'} · ключ {'задан' if CLOUD_KEY else 'не задан'} · режим {MODE}"


# Облако не должно отдавать свои «мысли»: reasoning-модели (deepseek-r1, qwen3, gpt-oss) думают
# отдельным потоком, и часть провайдеров кладёт эти мысли прямо в content — тогда в чат приходит
# сплошной разбор («Хорошо, пользователь просит шутку… Сначала смотрю на данные…») вместо ответа.
# Подсказка в системный промпт + параметры запроса (см. body["reasoning"] ниже) + разбор ответа
# (пустой content при заполненном reasoning → НЕ отдаём его как ответ).
_NO_THINK_HINT = ("\nРАССУЖДЕНИЯ. Думай молча и отвечай только готовым результатом: не выводи в текст свой разбор, "
                  "план, перебор вариантов, самокритику и реплики вроде «хорошо, пользователь просит…», "
                  "«сначала посмотрю на данные…», «проверяю историю…». Если вопрос сложный — разберись внутри "
                  "и сразу отдай итог, одним ответом для хозяина.")


# ------------------------------------------------------- настройки облака (читаются на каждый вызов
# после смены на сайте работают без перезапуска; ключи объявлены в core/config.py → EDITABLE).
#   brain.cloud.reasoning: auto | off | minimal | low | medium | high
#     auto — как раньше (в чате effort=minimal + exclude, в инструментах только exclude);
#     off  — effort=none, модель не думает вообще. Мысли у OpenRouter списываются как вывод и
#            попадают в max_tokens: из-за них и получается «всё ушло в размышления» + повтор
#            с лимитом 4096, а также многосекундное молчание на больших запросах.
#   brain.cloud.max_tokens — потолок ответа (по умолчанию 1024), brain.cloud.timeout — ожидание (45 с).
_REASON_VALUES = ("auto", "off", "none", "minimal", "low", "medium", "high")


def _cloud_setting(key: str):
    return getattr(getattr(getattr(cfg, "brain", None), "cloud", None), key, None)


def reasoning_mode() -> str:
    """Что просим у облака про «размышления»: auto / off / minimal / low / medium / high."""
    v = str(_cloud_setting("reasoning") or "auto").strip().lower()
    return v if v in _REASON_VALUES else "auto"


def _reasoning_body(kind: str) -> dict:
    """Параметр `reasoning` для OpenRouter (документация: /docs/guides/best-practices/reasoning-tokens).

    kind: "chat" — ответ хозяину, "tools" — вызовы инструментов (там точность важнее скорости,
    поэтому в auto режиме бюджет не режем — как и раньше). Явный уровень/off действует на оба пути.
    """
    mode = reasoning_mode()
    if mode in ("off", "none"):
        return {"effort": "none", "exclude": True}
    if mode != "auto":
        return {"effort": mode, "exclude": True}
    return {"effort": "minimal", "exclude": True} if kind == "chat" else {"exclude": True}


def cloud_max_tokens(default: int = 1024) -> int:
    """Потолок ответа облака:0/мусор в настройке = значение по умолчанию."""
    try:
        v = int(str(_cloud_setting("max_tokens") or "").strip() or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else default


def cloud_timeout(default: float = 45) -> float:
    """Секунд ждать один ответ облака (0/мусор = по умолчанию)."""
    try:
        v = int(str(_cloud_setting("timeout") or "").strip() or 0)
    except (TypeError, ValueError):
        v = 0
    return float(v if v > 0 else default)


GEMINI_PROXY = (getattr(cfg.brain.gemini, "proxy", "") or "").strip() or None
LAST_GEMINI_ERROR: str | None = None   # человекочитаемая причина последнего сбоя (показываем в чате и в настройках)


# ---- Зрение: скриншот экрана, фото чека. Сначала локальная vision-модель Ollama, иначе облако (если разрешено).
VISION_MODEL = str(getattr(cfg.brain.ollama, "vision_model", "") or "")           # например qwen2.5vl:3b / llava / moondream
if not VISION_MODEL and re.search(r"qwen3\.5|qwen3\.6|gemma3|gemma4|llava|minicpm-v|qwen2\.5vl|moondream|llama3\.2-vision", OLLAMA_MODEL, re.I):
    VISION_MODEL = OLLAMA_MODEL    # основная модель сама видит картинки — отдельная не нужна
_vision_cfg = getattr(cfg.brain, "vision", None)
# ФАЗА 6: дефолт False — без явного allow_cloud: true скриншот/фото в облако не уходит (совпадает с core/config.py)
VISION_CLOUD_OK = bool(getattr(_vision_cfg, "allow_cloud", False))                  # можно ли слать картинку в облако
# где смотреть картинки: auto — локально, а если нет/не отвечает → облако; cloud — всегда облако (быстро, но фото уходят наружу); local — только ПК
VISION_WHERE = str(getattr(_vision_cfg, "where", "auto") or "auto").lower()
if VISION_WHERE not in ("auto", "cloud", "local"):
    VISION_WHERE = "auto"
# Провайдеры отключают модели зрения каждые полгода — держим список, пробуем по очереди, рабочую запоминаем
CLOUD_VISION_MODELS = {"groq": ["qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"],
                       "openrouter": ["google/gemma-4-26b-a4b-it:free", "google/gemma-4-31b-it:free", "dots-studio/dots-3-note-preview:free"],
                       "nvidia": ["meta/llama-4-scout-17b-16e-instruct", "qwen/qwen2.5-vl-72b-instruct"]}
_CLOUD_VISION_GOOD: dict[str, str] = {}
_VISION_LOCAL_OK: bool | None = None


# ------------------------------------------------------- учёт токенов и денег
# Сколько токенов съела модель и сколько это стоило. Нужно хозяину: он платит
# провайдеру (OpenRouter/DeepSeek) и хочет видеть расход, а не только «ответили».
#
# ПОЧЕМУ АККУМУЛЯТОР, А НЕ ВОЗВРАТ. Три варианта были на столе:
#   1) вернуть из cloud_chat/ollama_chat кортеж (текст, prompt, completion) — ломает
#      ВСЕ вызывающие: agent.py, memory/*, persona.py, sorter.py, judge.py, quick.py.
#      Их десятки, подпись типа str | None уезжает в TypeError по всему мозгу. Отклонено;
#   2) отдельный объект Usage, который каждый вызывающий обязан прокинуть вниз и наверх —
#      то же самое, только переименованное, плюс лишний параметр в публичных функциях. Отклонено;
#   3) аккумулятор в ContextVar — провайдер САМ отмечает, сколько потратил, ничего не меняя
#      сигнатур. Читает его trace.finish() в конце хода. Выбрано.
#
# ПОЧЕМУ ContextVar, А НЕ ГЛОБАЛЬНЫЙ СЧЁТЧИК. Один asyncio-процесс обслуживает и хозяина,
# и фоновые задачи (уборка памяти, майнджер уведомлений). Общий счётчик смешал бы фоновой
# вызов с ходом. ContextVar копируется вместе с контекстом задачи: set() внутри фоновой
# задачи не виден основному ходу, поэтому лишнего не припишется.
#
# ЧЕСТНОСТЬ. Цена модели берётся из настроек хозяина (brain.pricing). Нет цены — расход 0,
# и флаг priced=False: в статистике это видно как «нет цены», а не как «потратил ноль».
@dataclass(frozen=True)
class Usage:
    """Сколько токенов накоплено за текущий ход. Неизменяемый: set() вместо мутации —
    так видна, кому принадлежит счётчик (своя копия у фоновой задачи)."""

    calls: tuple[tuple[str, int, int], ...] = field(default=())   # (модель, prompt, completion) по каждому вызову

    @property
    def n_calls(self) -> int:
        """Сколько ответов модели учтено за ход."""
        return len(self.calls)

    @property
    def prompt_tokens(self) -> int:
        return sum(c[1] for c in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c[2] for c in self.calls)

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def models(self) -> list[str]:
        """Модели, которые реально отвечали, по порядку и без повторов."""
        out: list[str] = []
        for m, _, _ in self.calls:
            if m and m not in out:
                out.append(m)
        return out

    def cost(self) -> tuple[float, bool]:
        """(доллары, посчитано ли). Каждый вызов тарифицируется по СВОЕЙ модели: в одном ходе
        локальная модель (бесплатно) и облако (платно) чередуются."""
        total, priced = 0.0, False
        for model, p, c in self.calls:
            usd, ok = cost_usd(model, p, c)
            total += usd
            priced = priced or ok
        return (round(total, 8), priced)

    def add(self, model: str, prompt: int, completion: int) -> "Usage":
        return replace(self, calls=self.calls + ((str(model or ""), int(prompt), int(completion)),))


_usage: contextvars.ContextVar[Usage] = contextvars.ContextVar("llm_usage", default=Usage())


def usage_now() -> Usage:
    """Накоплено за текущий ход (пусто — ни одного ответа модели не было)."""
    return _usage.get()


def usage_reset() -> None:
    """Обнулить счётчик. Зовёт trace.start() в начале каждого хода."""
    _usage.set(Usage())


def usage_note(model: str, prompt: int, completion: int) -> None:
    """Провайдер отметил один ответ. Мусор и нули игнорируются — вызов без счётчиков
    (LM Studio без usage) не должен превращаться в строку журнала с нулём."""
    try:
        p, c = int(prompt or 0), int(completion or 0)
    except (TypeError, ValueError):
        return
    if p <= 0 and c <= 0:
        return
    _usage.set(_usage.get().add(model, max(0, p), max(0, c)))


def _int(value) -> int:
    """Токены от провайдера: int или None. Строки, мусор и отрицательные — ноль."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def tokens_openai(data) -> tuple[int, int]:
    """OpenRouter, Groq, DeepSeek, LM Studio и любой OpenAI-совместимый: usage.prompt_tokens/completion_tokens."""
    usage = (data or {}).get("usage") or {} if isinstance(data, dict) else {}
    return _int(usage.get("prompt_tokens")), _int(usage.get("completion_tokens"))


def tokens_ollama(data) -> tuple[int, int]:
    """Ollama /api/chat: prompt_eval_count (промпт) и eval_count (ответ)."""
    d = data if isinstance(data, dict) else {}
    return _int(d.get("prompt_eval_count")), _int(d.get("eval_count"))


def tokens_gemini(data) -> tuple[int, int]:
    """Gemini: usageMetadata.promptTokenCount/candidatesTokenCount."""
    meta = (data or {}).get("usageMetadata") or {} if isinstance(data, dict) else {}
    return _int(meta.get("promptTokenCount")), _int(meta.get("candidatesTokenCount"))


def _pricing_cfg():
    return getattr(getattr(cfg, "brain", None), "pricing", None)


def _pricing_models() -> dict:
    """Карта «модель → цена» из brain.pricing.models. Пустая, если её нет.

    Ключи в YAML содержат «/» и точки, поэтому читаем словарь у _Node, а не через getattr."""
    raw = getattr(_pricing_cfg(), "models", None)
    if isinstance(raw, dict):
        return {str(k).lower(): v for k, v in raw.items()}
    if hasattr(raw, "__dict__"):
        return {str(k).lower(): getattr(raw, k) for k in vars(raw)}
    return {}


def _float(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


def _price_pair(value) -> tuple[float, float] | None:
    """Цена из настройки в любом из двух видов: {prompt, completion} или [prompt, completion]."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        a, b = _float(value[0]), _float(value[1])
    else:
        if isinstance(value, dict):
            get = value.get
        else:
            get = lambda k, d=None: getattr(value, k, d)  # noqa: E731 — _Node из config.yaml
        a, b = _float(get("prompt")), _float(get("completion"))
    return (a, b) if a is not None and b is not None else None


def pricing_for(model: str) -> tuple[float, float] | None:
    """Цена за 1 млн токенов (prompt, completion) в долларах. None — цена неизвестна.

    Порядок: точное имя модели → то же без хвоста («:free» у OpenRouter, «-latest» у Ollama) →
    самая длинная подстрока-префикс → default_prompt/default_completion. Ноль в настройке —
    честное «бесплатно», а не «нет цены»."""
    name = str(model or "").strip().lower()
    if not name:
        return None
    models = _pricing_models()
    if models:
        for cand in (name, name.split(":", 1)[0]):
            if cand in models:
                pair = _price_pair(models[cand])
                if pair:
                    return pair
        # префикс: «deepseek/deepseek-v4.1-flash» подходит и для «deepseek/deepseek-v4.1-flash:beta»
        best = ""
        for key in models:
            if key and name.startswith(key) and len(key) > len(best):
                best = key
        if best:
            pair = _price_pair(models[best])
            if pair:
                return pair
    default = _price_pair({"prompt": getattr(_pricing_cfg(), "default_prompt", ""),
                           "completion": getattr(_pricing_cfg(), "default_completion", "")})
    return default


def cost_usd(model: str, prompt: int, completion: int) -> tuple[float, bool]:
    """Стоимость одного вызова в долларах и посчитали ли мы её.

    Возвращает (0.0, False), если цены нет: выдумывать «примерную» стоимость нельзя —
    хозяин платит настоящие деньги, и неправда здесь дороже нуля."""
    price = pricing_for(model)
    if not price:
        return (0.0, False)
    usd = (max(0, _int(prompt)) / 1_000_000) * price[0] + (max(0, _int(completion)) / 1_000_000) * price[1]
    return (round(usd, 8), True)


def pricing_ready() -> bool:
    """Задана ли хоть какая-то цена — по этому флагу сайт зовёт пустое состояние «задайте цену»."""
    if _pricing_models():
        return True
    return bool(getattr(_pricing_cfg(), "default_prompt", "") or getattr(_pricing_cfg(), "default_completion", ""))
