# Бэкенд Ollama: основная и малая модели, эмбеддинги.
from __future__ import annotations

import json
import time
import httpx
from typing import Any

from . import base as _base
from . import lmstudio as _lms_mod

from .base import AVAIL_TTL, _SMALL_MISSING, _SMALL_SEEN, _THINK_RX, log, short_mode, strip_think, token_sink
from .lmstudio import _lmstudio_chat, _lmstudio_tools_chat, lmstudio_role
__all__ = [
    "GPU_NOTE",
    "SMALL_LAST",
    "_log_ollama_stats",
    "_ollama_probe",
    "embed",
    "embed_available",
    "evict_ollama_main",
    "local_available",
    "ollama_available",
    "ollama_chat",
    "ollama_diagnose",
    "small_chat",
    "small_check",
    "small_model_active",
    "unload_ollama",
    "warm_ollama",
]

GPU_NOTE: str | None = None   # диагностика «влезла ли модель в видеокарту» (показывается в статусе)


async def warm_ollama() -> bool:
    """Загрузить модель в память заранее (пустой запрос с keep_alive), чтобы первый ответ не ждал 5–15 с.
    Заодно смотрим, целиком ли она в видеопамяти: если нет — генерация в 5–10 раз медленнее."""
    global GPU_NOTE
    if lmstudio_role() == "main":
        # основное отвечает LM Studio — модель Ollama заранее не грузим, иначе две большие
        # модели сядут в видеопамять одновременно и всё замедлится
        return False
    try:
        async with _base._local_client(180) as c:
            r = await c.post(f"{_base.OLLAMA_URL}/api/generate", json={"model": _base.OLLAMA_MODEL, "keep_alive": _base.OLLAMA_KEEP_ALIVE, "prompt": "", "stream": False})
            if r.status_code != 200:
                return False
            try:
                ps = (await c.get(f"{_base.OLLAMA_URL}/api/ps")).json().get("models", [])
                me = next((m for m in ps if m.get("name", "").startswith(_base.OLLAMA_MODEL.split(":")[0])), None)
                if me:
                    size, vram = int(me.get("size") or 0), int(me.get("size_vram") or 0)
                    if size and vram >= size * 0.98:
                        GPU_NOTE = f"{_base.OLLAMA_MODEL}: целиком в видеокарте ({vram / 2**30:.1f} ГБ)"
                        log.info("Мозг: %s — быстро", GPU_NOTE)
                    elif size:
                        GPU_NOTE = (f"{_base.OLLAMA_MODEL}: в видеокарте только {vram / size * 100:.0f}% ({vram / 2**30:.1f} из {size / 2**30:.1f} ГБ) — "
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
        async with _base._local_client(10) as c:
            for m in {_base.OLLAMA_MODEL, _base.EMBED_MODEL}:
                await c.post(f"{_base.OLLAMA_URL}/api/generate", json={"model": m, "keep_alive": 0})
        return True
    except Exception as e:
        log.debug("unload failed: %s", e)
        return False


async def ollama_available(force: bool = False) -> bool:
    """Жива ли Ollama. Результат кэшируется на 15 с: проверку зовут перед каждым сообщением, из /api/health каждые 30 с
    и из фоновых задач — без кэша это лишний HTTP-запрос (до 5 с таймаута) на каждое действие."""
    if _base.GAME_MODE:
        return False
    ts, ok = _base._AVAIL_CACHE
    if not force and time.monotonic() - ts < AVAIL_TTL:
        return ok
    ok = await _ollama_probe()
    _base._AVAIL_CACHE = (time.monotonic(), ok)
    return ok


async def _ollama_probe() -> bool:
    try:
        async with _base._local_client(5) as c:
            r = await c.get(f"{_base.OLLAMA_URL}/api/tags")
            if r.status_code != 200:
                return False
            models = [m.get("name", "") for m in r.json().get("models", [])]
            want = _base.OLLAMA_MODEL if ":" in _base.OLLAMA_MODEL else _base.OLLAMA_MODEL + ":latest"
            if models and not any(m == want or m.startswith(_base.OLLAMA_MODEL) for m in models):
                log.warning("Ollama работает, но модели %s нет. Есть: %s. Выполни: ollama pull %s",
                            _base.OLLAMA_MODEL, ", ".join(models), _base.OLLAMA_MODEL)
            if _base.SMALL_MODEL and models:
                sw = _base.SMALL_MODEL if ":" in _base.SMALL_MODEL else _base.SMALL_MODEL + ":latest"
                if not any(m == sw or m.startswith(_base.SMALL_MODEL) for m in models):
                    if _base.SMALL_MODEL not in _SMALL_MISSING:
                        log.warning("Малой модели %s нет в Ollama — мини-задачи пойдут на основную. Выполни: ollama pull %s", _base.SMALL_MODEL, _base.SMALL_MODEL)
                    _SMALL_MISSING.add(_base.SMALL_MODEL)
                else:
                    if _base.SMALL_MODEL in _SMALL_MISSING or not _SMALL_SEEN:
                        log.info("Малая модель %s на месте: судья и подсказки пойдут на неё (в памяти %s после задачи)", _base.SMALL_MODEL, _base.SMALL_KEEP_ALIVE)
                    _SMALL_SEEN.add(_base.SMALL_MODEL)
                    _SMALL_MISSING.discard(_base.SMALL_MODEL)
            return True
    except Exception as e:
        log.debug("ollama check failed: %s", e)
        return False


async def ollama_diagnose() -> str:
    """Человеческое объяснение, почему Ollama не отвечает."""
    try:
        async with _base._local_client(5) as c:
            r = await c.get(f"{_base.OLLAMA_URL}/api/tags")
            models = [m.get("name", "") for m in r.json().get("models", [])]
            if not models:
                return f"Ollama запущена, но моделей нет. Выполни в cmd: ollama pull {_base.OLLAMA_MODEL}"
            return f"Ollama запущена, модели: {', '.join(models)}"
    except httpx.ConnectError as e:
        return (f"Нет соединения с {_base.OLLAMA_URL} ({e}). Если Ollama точно работает — проверь, что в браузере "
                f"открывается {_base.OLLAMA_URL} ; если она на другом порту, поправь brain.ollama.url в config.yaml")
    except Exception as e:
        return f"Ollama на {_base.OLLAMA_URL}: {type(e).__name__}: {e}"


def small_model_active() -> bool:
    """Малая модель настроена и есть в Ollama (проверяется в ollama_available)."""
    return bool(_base.SMALL_MODEL) and _base.SMALL_MODEL not in _SMALL_MISSING


async def local_available() -> bool:
    """Есть ли хоть один локальный движок: LM Studio (если включён) или Ollama.
    Использовать везде, где раньше спрашивали только Ollama, — иначе при основном
    на LM Studio код думал, что локально никого нет."""
    if _base.LMSTUDIO_ENABLED and await _lms_mod.lmstudio_available():
        return True
    return await ollama_available()


def evict_ollama_main() -> bool:
    """Синхронно выгрузить основную модель Ollama из видеопамяти (keep_alive=0).
    Вызывается при переключении основного на LM Studio — чтобы две большие модели
    не сидели в памяти одновременно. Малая модель и эмбеддинги не трогаются."""
    try:
        with httpx.Client(timeout=10, trust_env=False) as c:
            r = c.post(f"{_base.OLLAMA_URL}/api/generate",
                       json={"model": _base.OLLAMA_MODEL, "keep_alive": 0, "prompt": "", "stream": False})
            ok = r.status_code == 200
        if ok:
            log.info("Ollama %s выгружена из видеопамяти (основное — на LM Studio)", _base.OLLAMA_MODEL)
        return ok
    except Exception as e:
        log.debug("evict failed: %s", e)
        return False


async def small_chat(system: str, user: str, json_mode: bool = True, num_predict: int = 200) -> str:
    """Мини-задача на маленькой локальной модели: короткий контекст (2048), без инструментов, выгружается через
    small_keep_alive. Если малая модель не задана или не скачана — та же задача на основной модели."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if lmstudio_role() in ("main", "small") and await _lms_mod.lmstudio_available():
        # мини-задачи отданы LM Studio (роль small — или main, где LM Studio делает вообще всё локальное)
        try:
            out = await _lmstudio_chat(messages, temperature=0.1, json_mode=json_mode,
                                       num_predict=num_predict, model=_base.LMSTUDIO_SMALL_MODEL)
            SMALL_LAST.update({"at": time.time(), "task": (system[:40] + "…") if len(system) > 40 else system})
            return out.get("content") or ""
        except Exception as e:
            log.warning("LM Studio не ответил (%s) — мини-задача идёт в Ollama", str(e)[:120])
    if not small_model_active():
        out = await ollama_chat(messages, temperature=0.1, json_mode=json_mode)
        return strip_think(out.get("content") or "")
    est = (len(system) + len(user)) // 3 + 100
    num_ctx = 2048
    while est + num_predict > num_ctx and num_ctx < 8192:
        num_ctx *= 2
    payload: dict[str, Any] = {"model": _base.SMALL_MODEL, "messages": messages, "stream": False, "keep_alive": _base.SMALL_KEEP_ALIVE,
                               "options": {"temperature": 0.1, "num_ctx": num_ctx, "num_predict": num_predict}}
    if json_mode:
        payload["format"] = "json"
    if _THINK_RX.search(_base.SMALL_MODEL):
        payload["think"] = False
        payload["options"]["stop"] = ["<think>"]
    t0 = time.monotonic()
    async with _base._local_client(90) as c:
        r = await c.post(f"{_base.OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        out = strip_think((r.json().get("message") or {}).get("content") or "")
        _p, _c = _base.tokens_ollama(r.json())
        _base.usage_note(_base.SMALL_MODEL or "ollama", _p, _c)
    log.info("малая модель %s ответила за %.1f с", _base.SMALL_MODEL, time.monotonic() - t0)
    SMALL_LAST.update({"at": time.time(), "seconds": round(time.monotonic() - t0, 1), "task": (system[:40] + "…") if len(system) > 40 else system})
    return out


SMALL_LAST: dict = {}   # последняя мини-задача на малой модели: когда, сколько секунд, что за задача — для карточки в настройках


async def small_check() -> dict:
    """Живая проверка малой модели для настроек: настроена ли, скачана ли, отвечает ли и за сколько."""
    if not _base.SMALL_MODEL:
        return {"configured": False, "ok": False, "detail": "не задана — мини-задачи (судья, подколы) идут на основную модель",
                "hint": "brain.ollama.small_model: qwen2.5:1.5b  +  в cmd: ollama pull qwen2.5:1.5b"}
    if not await ollama_available(force=True):
        return {"configured": True, "model": _base.SMALL_MODEL, "ok": False, "detail": "Ollama не отвечает"}
    if not small_model_active():
        return {"configured": True, "model": _base.SMALL_MODEL, "ok": False, "detail": f"в Ollama нет модели {_base.SMALL_MODEL}", "hint": f"в cmd: ollama pull {_base.SMALL_MODEL}"}
    t0 = time.monotonic()
    try:
        out = await small_chat("Ответь строго JSON вида {\"ok\": true}.", "Проверка связи.", json_mode=True, num_predict=20)
        dt = time.monotonic() - t0
        return {"configured": True, "model": _base.SMALL_MODEL, "ok": '"ok"' in out or "ok" in out.lower(), "seconds": round(dt, 1),
                "detail": f"ответила за {dt:.1f} с · живёт в видеопамяти {_base.SMALL_KEEP_ALIVE} после задачи"}
    except Exception as e:
        return {"configured": True, "model": _base.SMALL_MODEL, "ok": False, "detail": f"ошибка: {str(e)[:120]}"}


def _log_ollama_stats(d: dict, with_tools: bool) -> None:
    """Одна строка: куда ушло время. Ollama отдаёт наносекунды: загрузка модели / чтение промпта / генерация.
    Если prompt_eval_count каждый раз ≈ полный промпт — кэш не работает (промпт меняется в начале); если маленький — работает."""
    if not d or "total_duration" not in d:
        return
    ns = 1e9
    log.info("Ollama %s: всего %.1f с · загрузка %.1f с · промпт %d ток. за %.1f с · ответ %d ток. за %.1f с",
             "с инструментами" if with_tools else "без инструментов", d.get("total_duration", 0) / ns, d.get("load_duration", 0) / ns,
             d.get("prompt_eval_count", 0), d.get("prompt_eval_duration", 0) / ns, d.get("eval_count", 0), d.get("eval_duration", 0) / ns)


async def ollama_chat(messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.3,
                      json_mode: bool = False) -> dict:
    """Возвращает {'content': str, 'tool_calls': [{'name','arguments'}]}."""
    sink = token_sink.get()
    stream = bool(sink) and not json_mode
    num_predict = 160 if short_mode.get() else 512
    if lmstudio_role() == "main" and await _lms_mod.lmstudio_available():
        # основное на LM Studio: ответы, мини-задачи и вызовы функций — Ollama не трогается
        try:
            if tools:
                out = await _lmstudio_tools_chat(messages, tools, temperature=temperature)
            else:
                out = await _lmstudio_chat(messages, temperature=temperature, json_mode=json_mode, num_predict=num_predict)
            if sink and out.get("content"):
                try:
                    await sink(out["content"])   # стрим кусками здесь нет — отдаём ответ целиком
                except Exception:  # pragma: no cover
                    pass
            return out
        except Exception as e:
            log.warning("LM Studio не ответил (%s) — иду в Ollama", str(e)[:120])
    # оценка размера запроса: если не влезает в num_ctx, Ollama молча отрежет начало (системный промпт!) и оборвёт ответ.
    # Лучше один раз перезагрузить модель с окном побольше, чем получить «Сэр,» вместо ответа.
    est = (sum(len(str(m.get("content") or "")) for m in messages) + (len(json.dumps(tools, ensure_ascii=False)) if tools else 0)) // 3 + 200
    num_ctx = _base.OLLAMA_NUM_CTX
    while est + num_predict > num_ctx and num_ctx < 32768:
        num_ctx *= 2
    if num_ctx != _base.OLLAMA_NUM_CTX:
        log.warning("Запрос ≈%d токенов не влезает в num_ctx=%d — на этот раз беру %d (модель перезагрузится, +10–15 с; на 6 ГБ видеокарте "
                    "часть модели уедет в оперативку и промпт будет читаться в разы дольше). Это аварийный путь: в норме история и память "
                    "ужимаются заранее — если видите это часто, напишите в чат «отчёт о себе» и пришлите лог.", est, _base.OLLAMA_NUM_CTX, num_ctx)
    payload: dict[str, Any] = {"model": _base.OLLAMA_MODEL, "messages": messages, "stream": stream,
                               # основное на LM Studio — модель Ollama в памяти не держим: запасной путь
                               # подгружает её разово и сразу отпускает, иначе две большие модели делят 6 ГБ
                               "keep_alive": ("0" if lmstudio_role() == "main" else _base.OLLAMA_KEEP_ALIVE),
                               "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": num_predict}}
    if tools:
        payload["tools"] = tools
    if json_mode:
        payload["format"] = "json"
    if _THINK_RX.search(_base.OLLAMA_MODEL):
        payload["think"] = False      # qwen3/gemma4/deepseek-r1: без «размышлений» — ответ за секунды, а не за минуту
        payload["options"]["stop"] = ["<think>"]   # на случай, если модель всё равно попробует «подумать» в тексте
    stats: dict = {}
    async with _base._local_client(180) as c:
        if not stream:
            r = await c.post(f"{_base.OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            msg = data.get("message", {})
            stats = data
        else:
            # потоковый режим: текст отдаём по кусочкам, tool_calls собираем целиком
            msg = {"content": "", "tool_calls": []}
            async with c.stream("POST", f"{_base.OLLAMA_URL}/api/chat", json=payload) as r:
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
                        stats = chunk
                        break
    _log_ollama_stats(stats, bool(tools))
    # учёт токенов: локальная модель бесплатна, но число токенов показываем хозяину (объём, скорость)
    _p, _c = _base.tokens_ollama(stats)
    _base.usage_note(_base.OLLAMA_MODEL or "ollama", _p, _c)
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
    """Локальные эмбеддинги. Сначала LM Studio (если там настроена embed-модель), иначе Ollama.
    None — модели нет ни там, ни там.

    Раньше эмбеддинги были единственной причиной держать поднятой Ollama, даже когда вся
    остальная локальная работа ушла в LM Studio. Теперь второй движок не обязателен: у кого
    `brain.lmstudio.embed_model` задан, тот считает векторы в LM Studio и Ollama может быть
    не запущена вовсе. У кого не задан — поведение прежнее, лишних обращений к LM Studio нет.

    В игровом режиме — всегда None: иначе фоновая индексация памяти подгрузит модель
    эмбеддингов в видеокарту прямо во время игры."""
    if not texts:
        return []
    if _base.GAME_MODE:
        return None
    try:
        from . import lmstudio as _lms
        got = await _lms.lmstudio_embed(texts)
        if got:
            return got
    except Exception as e:  # pragma: no cover — не роняем память из-за LM Studio
        log.debug("lmstudio embed path failed: %s", e)
    try:
        async with _base._local_client(120) as c:
            r = await c.post(f"{_base.OLLAMA_URL}/api/embed", json={"model": _base.EMBED_MODEL, "input": texts})
            if r.status_code != 200:
                log.debug("embed failed: %s %s", r.status_code, r.text[:200])
                return None
            return r.json().get("embeddings")
    except Exception as e:
        log.debug("embed error: %s", e)
        return None


async def embed_available() -> bool:
    """Есть ли где-то локально модель эмбеддингов: в LM Studio или в Ollama."""
    if _base.GAME_MODE:
        return False
    try:
        from . import lmstudio as _lms
        if await _lms.lmstudio_embed_model():
            return True
    except Exception:  # pragma: no cover
        pass
    try:
        async with _base._local_client(5) as c:
            r = await c.get(f"{_base.OLLAMA_URL}/api/tags")
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return any(m.startswith(_base.EMBED_MODEL) for m in models)
    except Exception:
        return False
