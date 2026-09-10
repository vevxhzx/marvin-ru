"""Клиенты LLM: Ollama (локально) и Gemini (облако, через анонимайзер)."""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable

import httpx

from ..config import cfg

log = logging.getLogger("assistant.llm")

# localhost на Windows часто резолвится в ::1 (IPv6), а Ollama слушает 127.0.0.1 — ходим по IPv4 напрямую
OLLAMA_URL = cfg.brain.ollama.url.rstrip("/").replace("://localhost", "://127.0.0.1")


def _local_client(timeout: float) -> httpx.AsyncClient:
    """Клиент для локальной Ollama: без системного прокси/VPN (trust_env=False)."""
    return httpx.AsyncClient(timeout=timeout, trust_env=False)
OLLAMA_MODEL = cfg.brain.ollama.model
# держать модель в видеопамяти между запросами (иначе Ollama выгружает через 5 мин и первый ответ ждёт 5–15 с)
OLLAMA_KEEP_ALIVE = str(getattr(cfg.brain.ollama, "keep_alive", "2h") or "2h")
OLLAMA_NUM_CTX = int(getattr(cfg.brain.ollama, "num_ctx", 8192) or 8192)   # 4096 не хватало: схемы инструментов + промпт + история ≈ 4.5–5k токенов → Ollama резала промпт и обрывала ответ
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


GPU_NOTE: str | None = None   # диагностика «влезла ли модель в видеокарту» (показывается в статусе)


async def warm_ollama() -> bool:
    """Загрузить модель в память заранее (пустой запрос с keep_alive), чтобы первый ответ не ждал 5–15 с.
    Заодно смотрим, целиком ли она в видеопамяти: если нет — генерация в 5–10 раз медленнее."""
    global GPU_NOTE
    try:
        async with _local_client(180) as c:
            r = await c.post(f"{OLLAMA_URL}/api/generate", json={"model": OLLAMA_MODEL, "keep_alive": OLLAMA_KEEP_ALIVE, "prompt": "", "stream": False})
            if r.status_code != 200:
                return False
            try:
                ps = (await c.get(f"{OLLAMA_URL}/api/ps")).json().get("models", [])
                me = next((m for m in ps if m.get("name", "").startswith(OLLAMA_MODEL.split(":")[0])), None)
                if me:
                    size, vram = int(me.get("size") or 0), int(me.get("size_vram") or 0)
                    if size and vram >= size * 0.98:
                        GPU_NOTE = f"{OLLAMA_MODEL}: целиком в видеокарте ({vram / 2**30:.1f} ГБ)"
                        log.info("Мозг: %s — быстро", GPU_NOTE)
                    elif size:
                        GPU_NOTE = (f"{OLLAMA_MODEL}: в видеокарте только {vram / size * 100:.0f}% ({vram / 2**30:.1f} из {size / 2**30:.1f} ГБ) — "
                                    "остальное на процессоре, ответы медленные. Поставьте модель поменьше (ollama pull qwen2.5:3b и model: qwen2.5:3b в config.yaml).")
                        log.warning("Мозг: %s", GPU_NOTE)
            except Exception:
                pass
            return True
    except Exception as e:
        log.debug("warm failed: %s", e)
        return False


async def unload_ollama() -> bool:
    """Выгрузить модель из видеопамяти прямо сейчас (keep_alive=0). Не убивает Ollama."""
    try:
        async with _local_client(10) as c:
            for m in {OLLAMA_MODEL, EMBED_MODEL}:
                await c.post(f"{OLLAMA_URL}/api/generate", json={"model": m, "keep_alive": 0})
        return True
    except Exception as e:
        log.debug("unload failed: %s", e)
        return False


async def set_game_mode(on: bool) -> str:
    global GAME_MODE, _AVAIL_CACHE
    GAME_MODE = on
    _AVAIL_CACHE = (0.0, False)   # сбросить кэш доступности: после «игра окончена» модель должна вернуться сразу
    if on:
        freed = await unload_ollama()
        return ("Игровой режим: локальная модель выгружена из видеопамяти, до отмены отвечаю только через облако "
                "(команды-шаблоны работают как обычно). «Игра окончена» — вернуть.") if freed else \
               "Игровой режим включён (Ollama не отвечала — выгружать нечего). Всё в облако, сэр."
    return "Игровой режим выключен, локальный мозг снова в деле. Как сыграли, сэр?"
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
# Готовые пресеты: адрес + бесплатная модель по умолчанию. Все — OpenAI-совместимый /chat/completions.
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
_AVAIL_CACHE: tuple[float, bool] = (0.0, False)
AVAIL_TTL = 15.0


async def ollama_available(force: bool = False) -> bool:
    """Жива ли Ollama. Результат кэшируется на 15 с: проверку зовут перед каждым сообщением, из /api/health каждые 30 с
    и из фоновых задач — без кэша это лишний HTTP-запрос (до 5 с таймаута) на каждое действие."""
    global _AVAIL_CACHE
    if GAME_MODE:
        return False
    ts, ok = _AVAIL_CACHE
    if not force and time.monotonic() - ts < AVAIL_TTL:
        return ok
    ok = await _ollama_probe()
    _AVAIL_CACHE = (time.monotonic(), ok)
    return ok


async def _ollama_probe() -> bool:
    try:
        async with _local_client(5) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code != 200:
                return False
            models = [m.get("name", "") for m in r.json().get("models", [])]
            want = OLLAMA_MODEL if ":" in OLLAMA_MODEL else OLLAMA_MODEL + ":latest"
            if models and not any(m == want or m.startswith(OLLAMA_MODEL) for m in models):
                log.warning("Ollama работает, но модели %s нет. Есть: %s. Выполни: ollama pull %s",
                            OLLAMA_MODEL, ", ".join(models), OLLAMA_MODEL)
            return True
    except Exception as e:
        log.debug("ollama check failed: %s", e)
        return False


async def ollama_diagnose() -> str:
    """Человеческое объяснение, почему Ollama не отвечает."""
    try:
        async with _local_client(5) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            models = [m.get("name", "") for m in r.json().get("models", [])]
            if not models:
                return f"Ollama запущена, но моделей нет. Выполни в cmd: ollama pull {OLLAMA_MODEL}"
            return f"Ollama запущена, модели: {', '.join(models)}"
    except httpx.ConnectError as e:
        return (f"Нет соединения с {OLLAMA_URL} ({e}). Если Ollama точно работает — проверь, что в браузере "
                f"открывается {OLLAMA_URL} ; если она на другом порту, поправь brain.ollama.url в config.yaml")
    except Exception as e:
        return f"Ollama на {OLLAMA_URL}: {type(e).__name__}: {e}"


_THINK_RX = re.compile(r"qwen3|gemma4|deepseek-r1|gpt-oss|magistral|phi4-reasoning", re.I)
_THINK_BLOCK_RX = re.compile(r"<think>.*?</think>\s*", re.S | re.I)
_THINK_OPEN_RX = re.compile(r"^\s*<think>", re.I)


def strip_think(text: str | None) -> str:
    """Убрать «размышления» reasoning-моделей из ответа. Иногда qwen3/gpt-oss всё равно кладут <think>…</think>
    прямо в content — пользователь должен видеть только ответ."""
    if not text:
        return ""
    t = _THINK_BLOCK_RX.sub("", text)
    if _THINK_OPEN_RX.match(t):
        # незакрытый <think>: модель не успела ответить — берём последний абзац, который похож на ответ
        body = t.split("<think>", 1)[1]
        paras = [x.strip() for x in re.split(r"\n{2,}", body) if x.strip()]
        t = paras[-1] if paras else ""
        t = re.sub(r"^(\*\*)?(Option|Вариант|Draft|Черновик)[^:]*:\s*(\*\*)?", "", t, flags=re.I)
    return t.strip()


async def ollama_chat(messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.3,
                      json_mode: bool = False) -> dict:
    """Возвращает {'content': str, 'tool_calls': [{'name','arguments'}]}."""
    sink = token_sink.get()
    stream = bool(sink) and not json_mode
    num_predict = 160 if short_mode.get() else 512
    # оценка размера запроса: если не влезает в num_ctx, Ollama молча отрежет начало (системный промпт!) и оборвёт ответ.
    # Лучше один раз перезагрузить модель с окном побольше, чем получить «Сэр,» вместо ответа.
    est = (sum(len(str(m.get("content") or "")) for m in messages) + (len(json.dumps(tools, ensure_ascii=False)) if tools else 0)) // 3 + 200
    num_ctx = OLLAMA_NUM_CTX
    while est + num_predict > num_ctx and num_ctx < 32768:
        num_ctx *= 2
    if num_ctx != OLLAMA_NUM_CTX:
        log.warning("Запрос ≈%d токенов не влезает в num_ctx=%d — на этот раз беру %d (модель перезагрузится, +несколько секунд). "
                    "Поставьте brain.ollama.num_ctx: %d в настройках, чтобы так было всегда.", est, OLLAMA_NUM_CTX, num_ctx, num_ctx)
    payload: dict[str, Any] = {"model": OLLAMA_MODEL, "messages": messages, "stream": stream, "keep_alive": OLLAMA_KEEP_ALIVE,
                               "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": num_predict}}
    if tools:
        payload["tools"] = tools
    if json_mode:
        payload["format"] = "json"
    if _THINK_RX.search(OLLAMA_MODEL):
        payload["think"] = False      # qwen3/gemma4/deepseek-r1: без «размышлений» — ответ за секунды, а не за минуту
        payload["options"]["stop"] = ["<think>"]   # на случай, если модель всё равно попробует «подумать» в тексте
    async with _local_client(180) as c:
        if not stream:
            r = await c.post(f"{OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            msg = r.json().get("message", {})
        else:
            # потоковый режим: текст отдаём по кусочкам, tool_calls собираем целиком
            msg = {"content": "", "tool_calls": []}
            async with c.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    m = chunk.get("message") or {}
                    if m.get("tool_calls"):
                        msg["tool_calls"].extend(m["tool_calls"])
                    piece = m.get("content") or ""
                    if piece:
                        msg["content"] += piece
                        if not msg["tool_calls"]:
                            try:
                                await sink(piece)
                            except Exception:  # pragma: no cover
                                pass
                    if chunk.get("done"):
                        break
    calls = []
    for tc in msg.get("tool_calls", []) or []:
        f = tc.get("function", {})
        args = f.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append({"name": f.get("name"), "arguments": args})
    return {"content": (msg.get("content") or "").strip(), "tool_calls": calls}


async def embed(texts: list[str]) -> list[list[float]] | None:
    """Локальные эмбеддинги через Ollama (модель EMBED_MODEL). None — если модели/Ollama нет."""
    if not texts:
        return []
    try:
        async with _local_client(120) as c:
            r = await c.post(f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": texts})
            if r.status_code != 200:
                log.debug("embed failed: %s %s", r.status_code, r.text[:200])
                return None
            return r.json().get("embeddings")
    except Exception as e:
        log.debug("embed error: %s", e)
        return None


async def embed_available() -> bool:
    try:
        async with _local_client(5) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return any(m.startswith(EMBED_MODEL) for m in models)
    except Exception:
        return False


# ---------------- Gemini ----------------
# Анонимайзер: убираем то, что похоже на личные данные, перед отправкой в облако.
_PII = [
    (re.compile(r"\+?\d[\d\s\-()]{9,}\d"), "[телефон]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b"), "[карта]"),
    (re.compile(r"\b\d[\d\s]*(?:[.,]\d+)?\s*(?:₽|руб\w*|тыс\w*|к\b|млн)"), "[сумма]"),
    (re.compile(r"\b(?:[А-ЯЁ][а-яё]+\s+)?[А-ЯЁ][а-яё]+(?:ович|евич|овна|евна|ична)\b"), "[имя]"),  # Иван Петрович
]


def anonymize(text: str) -> str:
    for rx, repl in _PII:
        text = rx.sub(repl, text)
    # имена людей, которые уже фигурируют в твоей базе (события «встреча с Ваней», долги «Ване»)
    for name in _known_names():
        text = re.sub(rf"\b{re.escape(name)}\w*", "[имя]", text, flags=re.I)
    return text


_names_cache: tuple[float, list[str]] = (0.0, [])


def _known_names() -> list[str]:
    """Собираем имена собственные из базы (слова с заглавной буквы в названиях событий/долгов)."""
    import time
    global _names_cache
    if time.time() - _names_cache[0] < 300:
        return _names_cache[1]
    names: set[str] = set()
    try:
        from sqlmodel import select
        from ..db import Debt, Event, session
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
    except Exception:
        pass
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


def _cloud_model() -> str:
    m = CLOUD_MODEL or PROVIDERS.get(CLOUD_PROVIDER, {}).get("model", "")
    if m == "auto":
        return _CLOUD_RESOLVED or "auto"
    return m


async def resolve_cloud_model(force: bool = False) -> str:
    """Для «auto» у OpenRouter — выбрать живую бесплатную модель. Для остальных — как в настройках."""
    global _CLOUD_RESOLVED
    want = CLOUD_MODEL or PROVIDERS.get(CLOUD_PROVIDER, {}).get("model", "")
    if want != "auto":
        return want
    if _CLOUD_RESOLVED and not force:
        return _CLOUD_RESOLVED
    ids: list[str] = []
    for name, proxy in _cloud_routes():
        try:
            async with _cloud_client(20, proxy) as c:
                r = await c.get(f"{_cloud_base_url()}/models", headers={"Authorization": f"Bearer {CLOUD_KEY}"})
                r.raise_for_status()
                ids = [m.get("id", "") for m in r.json().get("data", [])]
            break
        except Exception as e:
            log.debug("cloud models via %s failed: %s", name, e)
    free = [i for i in ids if i.endswith(":free") and not any(a in i.lower() for a in _OR_AVOID) and i not in _OR_AVOID_RUNTIME]
    pick = None
    for pref in _OR_PREFER:
        cands = sorted((i for i in free if pref in i.lower()), reverse=True)
        if cands:
            pick = cands[0]
            break
    _CLOUD_RESOLVED = pick or (free[0] if free else "openrouter/auto")
    log.info("%s: выбрана бесплатная модель %s", cloud_title(), _CLOUD_RESOLVED)
    return _CLOUD_RESOLVED


def _cloud_routes() -> list[tuple[str, str | None]]:
    """Как ходить в облако, по порядку: (название, прокси). Первое, что сработает, запоминается.
    1) явный прокси из настроек облака; 2) напрямую; 3) прокси Telegram (тот же VPN); 4) системный прокси Windows."""
    routes: list[tuple[str, str | None]] = []
    if CLOUD_PROXY:
        routes.append(("прокси облака", CLOUD_PROXY))
    routes.append(("напрямую", None))
    tg_proxy = (getattr(cfg.telegram, "proxy", "") or "").strip()
    if tg_proxy and tg_proxy != CLOUD_PROXY:
        routes.append(("прокси Telegram", tg_proxy))
    routes.append(("системный прокси", "env"))
    return routes


_CLOUD_ROUTE_OK: tuple[str, str | None] | None = None   # маршрут, который последний раз сработал


def reload_cloud_settings() -> str:
    """Перечитать brain.cloud.* из config.yaml без перезапуска и сбросить кэш (модель/маршрут/ошибку)."""
    global CLOUD_PROVIDER, CLOUD_KEY, CLOUD_MODEL, CLOUD_BASE_URL, CLOUD_PROXY, MODE, GEMINI_AUTO
    global _CLOUD_RESOLVED, _CLOUD_ROUTE_OK, LAST_CLOUD_ERROR
    import importlib
    from .. import config as _c
    importlib.reload(_c)
    cc = getattr(_c.cfg.brain, "cloud", None)
    CLOUD_PROVIDER = (str(getattr(cc, "provider", "") or "") or ("gemini" if (_c.cfg.brain.gemini.api_key or "").strip() else "")).strip().lower()
    CLOUD_KEY = (str(getattr(cc, "api_key", "") or "")).strip()
    CLOUD_MODEL = (str(getattr(cc, "model", "") or "")).strip()
    CLOUD_BASE_URL = (str(getattr(cc, "base_url", "") or "")).strip().rstrip("/")
    CLOUD_PROXY = (str(getattr(cc, "proxy", "") or "")).strip() or None
    MODE = _c.cfg.brain.mode
    GEMINI_AUTO = bool(getattr(_c.cfg.brain.gemini, "auto", True))
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
    VISION_CLOUD_OK = bool(getattr(_vc, "allow_cloud", True))
    _VISION_LOCAL_OK = None
    _CLOUD_RESOLVED = None
    _CLOUD_ROUTE_OK = None
    _OR_AVOID_RUNTIME.clear()
    LAST_CLOUD_ERROR = None
    log.info("Облако перечитано: %s, модель %s, ключ %s, режим %s", cloud_title(), _cloud_model() or "по умолчанию",
             ("…" + CLOUD_KEY[-4:]) if CLOUD_KEY else "НЕ ЗАДАН", MODE)
    return f"{cloud_title()} · модель {_cloud_model() or 'по умолчанию'} · ключ {('…' + CLOUD_KEY[-4:]) if CLOUD_KEY else 'не задан'} · режим {MODE}"


def _cloud_client(timeout: float, proxy: str | None = None) -> httpx.AsyncClient:
    kw: dict = {"timeout": httpx.Timeout(timeout, connect=10), "trust_env": False}
    if proxy == "env":
        kw["trust_env"] = True
    elif proxy:
        kw["proxy"] = proxy
    return httpx.AsyncClient(**kw)


async def _cloud_post(path: str, body: dict, headers: dict, timeout: float = 45) -> "httpx.Response":
    """POST в облако с перебором маршрутов при сетевых ошибках (ответ сервера, даже 4xx, — не повод менять маршрут)."""
    global _CLOUD_ROUTE_OK
    # Groq: у reasoning-моделей (qwen3.x, gpt-oss) просим спрятать «размышления», иначе <think> прилетает в текст
    if CLOUD_PROVIDER == "groq" and path.endswith("/chat/completions") and _THINK_RX.search(str(body.get("model", ""))):
        if "reasoning_format" not in body and "include_reasoning" not in body:
            body["reasoning_format"] = "hidden"
        if body.get("model", "").startswith("qwen/") and "reasoning_effort" not in body:
            body["reasoning_effort"] = "none"
        if "tools" in body or body.get("response_format"):
            body.pop("reasoning_format", None)   # с tools/JSON «raw»/«hidden» не дружат — оставляем parsed по умолчанию
    routes = _cloud_routes()
    if _CLOUD_ROUTE_OK in routes:
        routes = [_CLOUD_ROUTE_OK] + [r for r in routes if r != _CLOUD_ROUTE_OK]
    last: Exception | None = None
    for name, proxy in routes:
        try:
            async with _cloud_client(timeout, proxy) as c:
                r = await c.post(f"{_cloud_base_url()}{path}", json=body, headers=headers)
            if _CLOUD_ROUTE_OK != (name, proxy):
                log.info("%s: маршрут — %s", cloud_title(), name)
            _CLOUD_ROUTE_OK = (name, proxy)
            return r
        except (httpx.ConnectError, httpx.ProxyError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
            log.warning("%s: %s не сработал (%s: %s) — пробую следующий маршрут", cloud_title(), name, type(e).__name__, str(e)[:80])
            last = e
        except ImportError as e:   # нет socksio для socks-прокси
            log.warning("%s: %s недоступен (%s)", cloud_title(), name, e)
            last = e
    raise last or httpx.ConnectError("нет маршрута")


async def _cloud_stream(body: dict, headers: dict, sink) -> str | None:
    """Потоковый ответ облака (SSE OpenAI-формата): токены — в sink, вернуть весь текст. None — не вышло.
    Маршруты перебираются как в _cloud_post; ответ сервера не-200 → None (дальше обычный запрос покажет причину)."""
    global _CLOUD_ROUTE_OK
    routes = _cloud_routes()
    if _CLOUD_ROUTE_OK in routes:
        routes = [_CLOUD_ROUTE_OK] + [r for r in routes if r != _CLOUD_ROUTE_OK]
    for name, proxy in routes:
        text = ""
        try:
            async with _cloud_client(45, proxy) as c:
                async with c.stream("POST", f"{_cloud_base_url()}/chat/completions", json={**body, "stream": True}, headers=headers) as r:
                    if r.status_code != 200:
                        _CLOUD_ROUTE_OK = (name, proxy)
                        body_txt = (await r.aread())[:200].decode("utf-8", "ignore")
                        log.warning("%s: стрим ответил %s (%s) — повторяю обычным запросом", cloud_title(), r.status_code, body_txt)
                        return None
                    if _CLOUD_ROUTE_OK != (name, proxy):
                        log.info("%s: маршрут — %s", cloud_title(), name)
                    _CLOUD_ROUTE_OK = (name, proxy)
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            delta = ((json.loads(data).get("choices") or [{}])[0].get("delta") or {})
                        except Exception:
                            continue
                        piece = delta.get("content") or ""
                        if piece:
                            text += piece
                            try:
                                await sink(piece)
                            except Exception:  # pragma: no cover
                                pass
            return text.strip() or None
        except (httpx.ConnectError, httpx.ProxyError, httpx.TimeoutException, httpx.RemoteProtocolError, ImportError) as e:
            if text:                       # оборвалось на середине — отдаём, что есть
                return text.strip()
            log.warning("%s: %s не сработал (%s: %s) — пробую следующий маршрут", cloud_title(), name, type(e).__name__, str(e)[:80])
        except Exception as e:
            log.debug("cloud stream failed: %s", e)
            return text.strip() or None
    return None


def _explain_cloud_error(e: Exception, r: "httpx.Response | None") -> str:
    name = cloud_title()
    if r is not None:
        try:
            msg = (r.json().get("error") or {}).get("message") or r.text[:200]
        except Exception:
            msg = r.text[:200]
        if r.status_code in (401, 403):
            return f"{name}: ключ не принят ({r.status_code}): {msg}"
        if r.status_code == 404:
            return f"{name}: модель «{_cloud_model()}» не найдена (404). Поменяйте модель в настройках → облако."
        if r.status_code == 429:
            return f"{name}: лимит бесплатных запросов исчерпан (429). Подождите или смените модель/провайдера."
        if r.status_code == 402:
            return f"{name}: закончились кредиты (402)."
        return f"{name} ответил {r.status_code}: {msg}"
    if isinstance(e, (httpx.ConnectError, httpx.ProxyError, httpx.TimeoutException, httpx.RemoteProtocolError)):
        host = _cloud_base_url().split("/")[2] if "//" in _cloud_base_url() else _cloud_base_url()
        return (f"{name}: не достучался до {host} ни напрямую, ни через прокси ({type(e).__name__}). "
                "Включите VPN или укажите прокси в настройках → облако (например тот же, что у Telegram).")
    return f"{name}: {type(e).__name__}: {e}"


async def cloud_chat(system: str, user_text: str, history: list[dict] | None = None, _force_model: str | None = None) -> str | None:
    """Единая точка входа в облако. Провайдер — из настроек; Gemini — частный случай."""
    global LAST_CLOUD_ERROR, _CLOUD_RESOLVED
    history_retry = _force_model is not None
    if not CLOUD_PROVIDER or CLOUD_PROVIDER == "gemini":
        ans = await gemini_chat(system, user_text, history)
        LAST_CLOUD_ERROR = None if ans else LAST_GEMINI_ERROR
        return ans
    if not cloud_enabled():
        return None
    if cfg.brain.gemini.anonymize and not history_retry:  # анонимайзер общий для любого облака
        user_text = anonymize(user_text)
        history = [{**h, "text": anonymize(h["text"])} for h in (history or [])]
    messages = [{"role": "system", "content": system}]
    messages += [{"role": "user" if h["role"] == "user" else "assistant", "content": h["text"]} for h in (history or [])]
    messages.append({"role": "user", "content": user_text})
    headers = {"Authorization": f"Bearer {CLOUD_KEY}", "Content-Type": "application/json"}
    if CLOUD_PROVIDER == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/local-assistant"; headers["X-Title"] = "Local Assistant"
    model = _force_model or await resolve_cloud_model()
    main_model = model
    if short_mode.get() and not _force_model and model not in _VOICE_MODEL_BAD:
        if CLOUD_VOICE_MODEL:
            model = CLOUD_VOICE_MODEL
        elif CLOUD_PROVIDER == "groq" and "compound" in model:
            model = "openai/gpt-oss-20b"   # compound ходит в интернет и думает 3–8 с; для голоса — быстрая
    body = {"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 220 if short_mode.get() else 1024}
    r = None
    sink = token_sink.get()
    if sink is not None:
        streamed = await _cloud_stream(body, headers, sink)
        if streamed:
            LAST_CLOUD_ERROR = None
            return streamed
        # стрим не удался — обычный запрос ниже
    try:
        r = await _cloud_post("/chat/completions", body, headers)
        if r.status_code in (400, 404) and model != main_model:
            # голосовую модель убрали/переименовали — запоминаем и идём основной
            log.warning("%s: голосовая модель %s не принята (%s) — использую %s", cloud_title(), model, r.status_code, main_model)
            _VOICE_MODEL_BAD.add(model)
            body["model"] = main_model
            r = await _cloud_post("/chat/completions", body, headers)
        if True:
            r.raise_for_status()
            data = r.json()
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            text = strip_think(msg.get("content") or "")
            # reasoning-модели (deepseek-r1) иногда кладут ответ в reasoning, а content пустой
            if not text:
                text = strip_think(msg.get("reasoning") or msg.get("reasoning_content") or "")
            if not text:
                LAST_CLOUD_ERROR = f"{cloud_title()}: пустой ответ."
                return None
            LAST_CLOUD_ERROR = None
            return text
    except Exception as e:
        if r is not None and r.status_code in (404, 429) and (CLOUD_MODEL or PROVIDERS.get(CLOUD_PROVIDER, {}).get("model")) == "auto" and _CLOUD_RESOLVED:
            # бесплатную модель убрали или она перегружена — переподбираем один раз
            prev = _CLOUD_RESOLVED
            _OR_AVOID_RUNTIME.add(prev)
            new = await resolve_cloud_model(force=True)
            if new != prev:
                return await cloud_chat(system, user_text, history)
        # модель, вписанная руками, не существует/не поддерживается → один раз пробуем стандартную у провайдера
        default_model = PROVIDERS.get(CLOUD_PROVIDER, {}).get("model", "")
        if (r is not None and r.status_code in (400, 404) and CLOUD_MODEL and default_model and default_model != "auto"
                and model != default_model and not history_retry):
            log.warning("%s: модель «%s» отвергнута (%s) — пробую стандартную %s", cloud_title(), model, r.status_code, default_model)
            return await cloud_chat(system, user_text, history, _force_model=default_model)
        LAST_CLOUD_ERROR = _explain_cloud_error(e, r if r is not None and r.status_code >= 400 else None)
        log.warning("cloud error: %s", LAST_CLOUD_ERROR)
        return None


async def cloud_check() -> dict:
    if not CLOUD_PROVIDER or CLOUD_PROVIDER == "gemini":
        res = await gemini_check()
        return {**res, "provider": "gemini", "title": "Gemini"}
    if not CLOUD_KEY:
        return {"ok": False, "detail": "Ключ не задан.", "provider": CLOUD_PROVIDER, "title": cloud_title()}
    if MODE == "local":
        return {"ok": False, "detail": "brain.mode = local — облако выключено.", "provider": CLOUD_PROVIDER, "title": cloud_title()}
    ans = await cloud_chat("Отвечай одним словом.", "Скажи «ок».")
    return {"ok": bool(ans), "detail": ans or LAST_CLOUD_ERROR or "нет ответа", "provider": CLOUD_PROVIDER,
            "title": cloud_title(), "model": _cloud_model()}


GEMINI_PROXY = (getattr(cfg.brain.gemini, "proxy", "") or "").strip() or None
LAST_GEMINI_ERROR: str | None = None   # человекочитаемая причина последнего сбоя (показываем в чате и в настройках)


def _gemini_client(timeout: float) -> httpx.AsyncClient:
    """Клиент для Gemini. Прокси: brain.gemini.proxy → иначе telegram.proxy (тот же VPN) → иначе напрямую."""
    proxy = GEMINI_PROXY or ((getattr(cfg.telegram, "proxy", "") or "").strip() or None)
    kw: dict = {"timeout": timeout}
    if proxy:
        kw["proxy"] = proxy
    try:
        return httpx.AsyncClient(**kw)
    except ImportError:
        # socks5:// требует пакет socksio. Он лежит в vendor/ — подключим и попробуем ещё раз
        import sys
        from ..config import ROOT
        vend = str(ROOT / "vendor")
        if vend not in sys.path:
            sys.path.append(vend)
            try:
                return httpx.AsyncClient(**kw)
            except ImportError:
                pass
        raise RuntimeError(f"Прокси {proxy} требует пакет socksio, а его нет. Запустите update.bat или используйте http-прокси.")


def _explain_gemini_error(e: Exception, r: "httpx.Response | None" = None) -> str:
    if r is not None:
        try:
            msg = r.json().get("error", {}).get("message", "") or r.text[:200]
        except Exception:
            msg = r.text[:200]
        if r.status_code in (400, 403) and ("location" in msg.lower() or "not supported" in msg.lower()):
            used = GEMINI_PROXY or ((getattr(cfg.telegram, "proxy", "") or "").strip() or None)
            if used:
                return (f"Google не обслуживает Gemini API из вашего региона, хотя запрос шёл через прокси {used}. "
                        "Значит, у VPN сейчас российский/неподходящий выход — переключите сервер в VPN-клиенте на другую страну (не РФ, не Беларусь).")
            return ("Google не обслуживает Gemini API из вашего региона, а прокси не задан. Укажите в настройках «Прокси для Gemini» "
                    "тот же адрес, что для Telegram (например socks5://127.0.0.1:10808), или включите VPN на весь компьютер.")
        if r.status_code in (400, 401, 403) and ("api key" in msg.lower() or "api_key" in msg.lower() or "permission" in msg.lower()):
            return f"Ключ Gemini не принят ({r.status_code}): {msg}. Проверьте ключ в настройках → мозг."
        if r.status_code == 404:
            return (f"Модель «{_RESOLVED_MODEL or GEMINI_MODEL}» отключена Google (404), а другой доступной по этому ключу не нашлось. "
                    f"Поставьте в настройках «Модель Gemini» = auto или проверьте ключ в Google AI Studio.")
        if r.status_code == 429:
            return "Лимит запросов Gemini исчерпан (429). Подождите минуту или проверьте квоту в Google AI Studio."
        if r.status_code >= 500:
            return f"Gemini временно недоступен ({r.status_code}). Попробуйте позже."
        return f"Gemini ответил {r.status_code}: {msg}"
    if isinstance(e, RuntimeError) and "socksio" in str(e):
        return str(e)
    used = GEMINI_PROXY or ((getattr(cfg.telegram, "proxy", "") or "").strip() or None)
    if isinstance(e, (httpx.ConnectError, httpx.ProxyError)) and used:
        return (f"Не удалось подключиться через прокси {used} ({type(e).__name__}). Проверьте, что VPN-клиент запущен и его локальный прокси "
                "включён на этом порту (в v2rayN/Nekoray это «Local socks port»).")
    if isinstance(e, httpx.ConnectError):
        return "Нет соединения с generativelanguage.googleapis.com — сеть или блокировка. Укажите прокси для Gemini в настройках или включите VPN."
    if isinstance(e, httpx.TimeoutException):
        return "Gemini не ответил за 40 секунд (таймаут). Сеть медленная или заблокирована."
    if isinstance(e, (KeyError, IndexError)):
        return "Gemini вернул пустой ответ (сработал фильтр безопасности или ответ обрезан)."
    return f"Ошибка Gemini: {type(e).__name__}: {e}"


async def gemini_models() -> list[str]:
    """Список моделей, доступных по этому ключу (только те, что умеют generateContent)."""
    try:
        async with _gemini_client(20) as c:
            r = await c.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": GEMINI_KEY})
            r.raise_for_status()
            out = []
            for m in r.json().get("models", []):
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    out.append(m.get("name", "").replace("models/", ""))
            return out
    except Exception as e:
        log.debug("gemini models failed: %s", e)
        return []


async def resolve_gemini_model(force: bool = False) -> str | None:
    """Какую модель реально использовать. Кэшируется до перезапуска или до 404."""
    global _RESOLVED_MODEL, LAST_GEMINI_ERROR
    if _RESOLVED_MODEL and not force:
        return _RESOLVED_MODEL
    available = await gemini_models()
    if not available:
        # список не получили (сеть/регион) — идём с тем, что указано, или с разумным дефолтом
        _RESOLVED_MODEL = GEMINI_MODEL if GEMINI_MODEL != "auto" else "gemini-2.5-flash"
        return _RESOLVED_MODEL
    if GEMINI_MODEL != "auto" and GEMINI_MODEL in available:
        _RESOLVED_MODEL = GEMINI_MODEL
        return _RESOLVED_MODEL
    for want in _PREFERRED:
        if want in available:
            _RESOLVED_MODEL = want
            break
    else:
        flash = sorted((m for m in available if "flash" in m and "tts" not in m and "image" not in m and "live" not in m), reverse=True)
        _RESOLVED_MODEL = flash[0] if flash else available[0]
    if GEMINI_MODEL != "auto":
        log.warning("Модель %s недоступна — использую %s. Поставьте brain.gemini.model: auto, чтобы не думать об этом.", GEMINI_MODEL, _RESOLVED_MODEL)
    else:
        log.info("Gemini: выбрана модель %s", _RESOLVED_MODEL)
    return _RESOLVED_MODEL


async def gemini_chat(system: str, user_text: str, history: list[dict] | None = None, _retry: bool = True) -> str | None:
    global LAST_GEMINI_ERROR, _RESOLVED_MODEL
    if not gemini_enabled():
        return None
    model = await resolve_gemini_model()
    if cfg.brain.gemini.anonymize:
        user_text = anonymize(user_text)
        history = [{**h, "text": anonymize(h["text"])} for h in (history or [])]
    contents = [{"role": "user" if h["role"] == "user" else "model", "parts": [{"text": h["text"]}]} for h in (history or [])]
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    if not model or not model.startswith("gemini"):
        model = "gemini-2.5-flash"   # страховка: в URL никогда не уйдёт «auto»
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"system_instruction": {"parts": [{"text": system}]}, "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024}}
    r = None
    try:
        async with _gemini_client(40) as c:
            r = await c.post(url, json=body, headers={"x-goog-api-key": GEMINI_KEY})
            r.raise_for_status()
            data = r.json()
            cand = (data.get("candidates") or [{}])[0]
            parts = cand.get("content", {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts).strip()
            if not text:
                reason = cand.get("finishReason") or data.get("promptFeedback", {}).get("blockReason") or "пусто"
                LAST_GEMINI_ERROR = f"Gemini вернул пустой ответ ({reason})."
                log.warning("Gemini empty: %s", data)
                return None
            LAST_GEMINI_ERROR = None
            return text
    except Exception as e:
        if r is not None and r.status_code == 404 and _retry:
            # модель отключили — переподбираем и пробуем ещё раз
            _RESOLVED_MODEL = None
            new = await resolve_gemini_model(force=True)
            if new and new != model:
                return await gemini_chat(system, user_text, history, _retry=False)
        LAST_GEMINI_ERROR = _explain_gemini_error(e, r if r is not None and r.status_code >= 400 else None)
        log.warning("Gemini error: %s", LAST_GEMINI_ERROR)
        return None


async def gemini_check() -> dict:
    """Проверка Gemini для страницы настроек: {'ok': bool, 'detail': str}."""
    if not GEMINI_KEY:
        return {"ok": False, "detail": "Ключ не задан."}
    if MODE == "local":
        return {"ok": False, "detail": "brain.mode = local — облако выключено."}
    ans = await gemini_chat("Отвечай одним словом.", "Скажи «ок».")
    return {"ok": bool(ans), "detail": ans or LAST_GEMINI_ERROR or "нет ответа", "model": _RESOLVED_MODEL,
            "available": (await gemini_models())[:30]}


# ---- Зрение: скриншот экрана, фото чека. Сначала локальная vision-модель Ollama, иначе облако (если разрешено).
VISION_MODEL = str(getattr(cfg.brain.ollama, "vision_model", "") or "")           # например qwen2.5vl:3b / llava / moondream
if not VISION_MODEL and re.search(r"qwen3\.5|qwen3\.6|gemma3|gemma4|llava|minicpm-v|qwen2\.5vl|moondream|llama3\.2-vision", OLLAMA_MODEL, re.I):
    VISION_MODEL = OLLAMA_MODEL    # основная модель сама видит картинки — отдельная не нужна
_vision_cfg = getattr(cfg.brain, "vision", None)
VISION_CLOUD_OK = bool(getattr(_vision_cfg, "allow_cloud", True))                  # можно ли слать картинку в облако
# где смотреть картинки: auto — локально, а если нет/не отвечает → облако; cloud — всегда облако (быстро, но фото уходят наружу); local — только ПК
VISION_WHERE = str(getattr(_vision_cfg, "where", "auto") or "auto").lower()
if VISION_WHERE not in ("auto", "cloud", "local"):
    VISION_WHERE = "auto"
# Провайдеры отключают модели зрения каждые полгода — держим список, пробуем по очереди, рабочую запоминаем
CLOUD_VISION_MODELS = {"groq": ["qwen/qwen3.6-27b", "qwen/qwen3.8-27b", "meta-llama/llama-4-scout-17b-16e-instruct", "meta-llama/llama-4-maverick-17b-128e-instruct"],
                       "openrouter": ["qwen/qwen2.5-vl-72b-instruct:free", "google/gemma-3-27b-it:free", "meta-llama/llama-4-scout:free"],
                       "nvidia": ["meta/llama-4-scout-17b-16e-instruct", "qwen/qwen2.5-vl-72b-instruct"]}
_CLOUD_VISION_GOOD: dict[str, str] = {}
_VISION_LOCAL_OK: bool | None = None


_VISION_CHECKED_AT = 0.0


async def _local_vision_available() -> bool:
    """Есть ли локальная модель зрения. Отрицательный ответ перепроверяем раз в минуту —
    Ollama могли поднять или модель докачать уже после старта ассистента."""
    global _VISION_LOCAL_OK, _VISION_CHECKED_AT
    if not VISION_MODEL or GAME_MODE:
        return False
    import time as _t
    if _VISION_LOCAL_OK is None or (not _VISION_LOCAL_OK and _t.monotonic() - _VISION_CHECKED_AT > 60):
        _VISION_CHECKED_AT = _t.monotonic()
        try:
            async with _local_client(5) as c:
                models = [m.get("name", "") for m in (await c.get(f"{OLLAMA_URL}/api/tags")).json().get("models", [])]
                want = VISION_MODEL.split(":")[0]
                _VISION_LOCAL_OK = any(m == VISION_MODEL or m.split(":")[0] == want for m in models)
        except Exception:
            _VISION_LOCAL_OK = False
    return bool(_VISION_LOCAL_OK)


def vision_hint() -> str:
    """Что сделать, чтобы зрение заработало — одной фразой для пользователя."""
    if VISION_WHERE == "cloud" and not (cloud_enabled() and CLOUD_PROVIDER in CLOUD_VISION_MODELS):
        return "Выбрано смотреть картинки через облако, но провайдер не умеет зрение или ключ не задан (нужен groq / openrouter / nvidia)."
    if VISION_WHERE == "cloud" and LAST_CLOUD_ERROR:
        return LAST_CLOUD_ERROR
    if GAME_MODE and VISION_WHERE != "cloud":
        return "Игровой режим — мозг выгружен. Скажите «игра окончена» или переключите зрение на облако в настройках."
    if not VISION_MODEL:
        return ("Модель зрения не задана. Проще всего перейти на qwen3.5:4b — она сама видит картинки "
                "(ollama pull qwen3.5:4b и указать её в Настройки → мозг → модель).")
    if VISION_MODEL == OLLAMA_MODEL:
        return f"Ollama не отвечает или модель {VISION_MODEL} не скачана (ollama pull {VISION_MODEL})."
    return f"Модель зрения {VISION_MODEL} не найдена в Ollama: ollama pull {VISION_MODEL} — или очистите поле «модель зрения», если основная модель qwen3.5/gemma сама видит картинки."


async def describe_image(image_b64: str, question: str, private: bool = False, short: bool = True) -> str | None:
    """Картинка (base64 JPEG/PNG) + вопрос → текст. private=True — только локально (чеки, документы)."""
    global LAST_CLOUD_ERROR
    hint = " Отвечай по-русски, кратко." + (" 1–3 предложения." if short else "")
    cloud_possible = VISION_CLOUD_OK and cloud_enabled() and CLOUD_PROVIDER in CLOUD_VISION_MODELS
    # где: cloud — сразу в облако; auto — локально, но если облако доступно, ждём локальную не дольше 40 с
    try_local = VISION_WHERE != "cloud" and await _local_vision_available()
    if try_local:
        try:
            async with _local_client(40 if (cloud_possible and VISION_WHERE == "auto") else 180) as c:
                r = await c.post(f"{OLLAMA_URL}/api/chat", json={
                    "model": VISION_MODEL, "stream": False, "keep_alive": OLLAMA_KEEP_ALIVE,
                    "messages": [{"role": "user", "content": question + hint, "images": [image_b64]}],
                    "options": {"temperature": 0.2, "num_predict": 300 if short else 800}})
                if r.status_code == 200:
                    txt = strip_think((r.json().get("message") or {}).get("content", ""))
                    if txt:
                        return txt
        except Exception as e:
            log.warning("local vision failed (%s) — %s", type(e).__name__, "пробую облако" if cloud_possible else "облако недоступно")
    # private (чек/документ) в облако — только если пользователь явно выбрал vision.where = cloud
    if VISION_WHERE == "local" or not cloud_possible or (private and VISION_WHERE != "cloud"):
        return None
    models = CLOUD_VISION_MODELS[CLOUD_PROVIDER]
    good = _CLOUD_VISION_GOOD.get(CLOUD_PROVIDER)
    order = ([good] + [m for m in models if m != good]) if good else list(models)
    headers = {"Authorization": f"Bearer {CLOUD_KEY}", "Content-Type": "application/json"}
    last = ""
    for model in order:
        body = {"model": model, "temperature": 0.2, "max_tokens": 400 if short else 900,
                "messages": [{"role": "user", "content": [{"type": "text", "text": question + hint},
                                                           {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}]}
        try:
            r = await _cloud_post("/chat/completions", body, headers, timeout=60)
            if r.status_code in (400, 404, 410, 422) and re.search(r"decommission|not found|does not exist|deprecated|unsupported|invalid model", r.text, re.I):
                last = f"{model}: снята с поддержки"; continue
            r.raise_for_status()
            msg = (r.json().get("choices") or [{}])[0].get("message") or {}
            txt = strip_think(msg.get("content") or "")
            if txt:
                _CLOUD_VISION_GOOD[CLOUD_PROVIDER] = model
                LAST_CLOUD_ERROR = None
                return txt
            last = f"{model}: пустой ответ"
        except Exception as e:
            last = f"{model}: {str(e)[:100]}"
            if "429" in last:
                continue   # лимит на эту модель — следующая
    LAST_CLOUD_ERROR = f"{cloud_title()} (зрение): {last}"
    log.warning("cloud vision failed: %s", LAST_CLOUD_ERROR)
    return None


def vision_status() -> str:
    cloud = VISION_CLOUD_OK and cloud_enabled() and CLOUD_PROVIDER in CLOUD_VISION_MODELS
    cm = _CLOUD_VISION_GOOD.get(CLOUD_PROVIDER) or (CLOUD_VISION_MODELS.get(CLOUD_PROVIDER) or ["?"])[0]
    if VISION_WHERE == "cloud":
        return f"через {cloud_title()} ({cm})" if cloud else "облако выбрано, но провайдер без зрения или ключ не задан"
    if VISION_MODEL and _VISION_LOCAL_OK:
        return f"локально ({VISION_MODEL})" + (f", запасной путь {cloud_title()}" if cloud and VISION_WHERE == "auto" else "")
    if cloud and VISION_WHERE == "auto":
        return f"через {cloud_title()} ({cm})" + (f" · локальная {VISION_MODEL} не отвечает" if VISION_MODEL else "")
    return "выключено"
