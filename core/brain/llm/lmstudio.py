# Бэкенд LM Studio (OpenAI-совместимый /chat/completions).
from __future__ import annotations

import json
import re
import time
from typing import Any

from . import base as _base

from .base import _lms_fail, _lms_ok, log, strip_think
__all__ = [
    "_lms_why",
    "_lmstudio_chat",
    "_lmstudio_tools_chat",
    "_text_tool_call",
    "lmstudio_active_model",
    "lmstudio_available",
    "lmstudio_check",
    "lmstudio_models",
    "lmstudio_role",
    "reload_lmstudio",
]

async def reload_lmstudio() -> bool:
    """После игры: если модель LM Studio выгружена (TTL/игра) — поднять обратно через API.
    Уже загружена — ничего не делаем: повторный load плодит дубли-инстансы в видеопамяти."""
    if not _base.LMSTUDIO_ENABLED:
        return False
    try:
        import httpx
        root = _base.LMSTUDIO_BASE[:-len("/v1")] if _base.LMSTUDIO_BASE.lower().endswith("/v1") else _base.LMSTUDIO_BASE
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{root}/api/v0/models")
            states = {m.get("id"): m.get("state") for m in (r.json().get("data") or []) if isinstance(m, dict)}
        if states.get(_base.LMSTUDIO_MODEL) == "loaded":
            return True
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(f"{root}/api/v1/models/load",
                             json={"model": _base.LMSTUDIO_MODEL, "context_length": 8192})
            ok = r.status_code == 200
        log.info("LM Studio: модель %s %s", _base.LMSTUDIO_MODEL, "поднята обратно" if ok else f"не поднялась ({r.status_code})")
        return ok
    except Exception as e:
        log.debug("lmstudio reload failed: %s", e)
        return False


def lmstudio_role() -> str:
    """Какую работу отдать LM Studio: 'main', 'small' или '' (выключен)."""
    if not _base.LMSTUDIO_ENABLED:
        return ""
    return _base.LMSTUDIO_USE if _base.LMSTUDIO_USE in ("main", "small") else ""


async def lmstudio_available(force: bool = False) -> bool:
    """LM Studio отвечает и в нём загружена хоть одна модель (кэш 60 с)."""
    if not _base.LMSTUDIO_ENABLED:
        return False
    return bool(await lmstudio_models(force=force))


async def lmstudio_models(force: bool = False) -> list[str]:
    """Модели, загруженные в LM Studio прямо сейчас (кэш 60 с)."""
    ts, ids = _base._LMS_MODELS_CACHE
    if not force and time.monotonic() - ts < 60 and ids:
        return ids
    ids = []
    try:
        async with _base._local_client(5) as c:
            r = await c.get(f"{_base.LMSTUDIO_BASE}/models")
            if r.status_code == 200:
                ids = [str(d.get("id", "")) for d in (r.json().get("data") or []) if d.get("id")]
            else:
                _lms_fail(f"{_base.LMSTUDIO_BASE}/models: http {r.status_code}")
    except Exception as e:
        _lms_fail(_lms_why(e, _base.LMSTUDIO_BASE))
    _base._LMS_MODELS_CACHE = (time.monotonic(), ids)
    if ids:
        _lms_ok()
    return ids


def _lms_why(e: Exception, base: str) -> str:
    """Человеческая причина сбоя: отказ соединения (сервер рестартует) / таймаут (модель грузится) / прочее."""
    s = f"{type(e).__name__}: {e}".lower()
    if "refused" in s or "connecterror" in s or "connect" in s:
        return f"нет соединения с {base} — сервер LM Studio закрыт или перезапускается (смена модели)"
    if "timeout" in s:
        return f"{base} не ответил за таймаут — модель грузится или занят другим запросом"
    return f"{base}: {str(e)[:120]}"


async def lmstudio_active_model() -> str:
    """Какая модель реально ответит: настроенная, если загружена, иначе уже загруженная.
    Сверять название с загруженным не нужно — отвечает та, что в памяти."""
    try:
        ids = await lmstudio_models()
    except Exception:
        ids = []
    if _base.LMSTUDIO_MODEL and _base.LMSTUDIO_MODEL in ids:
        return _base.LMSTUDIO_MODEL
    if ids:
        if _base.LMSTUDIO_MODEL:
            log.warning("Модели %s нет в LM Studio — отвечаю загруженной %s", _base.LMSTUDIO_MODEL, ids[0])
        return ids[0]
    return _base.LMSTUDIO_MODEL


async def _lmstudio_chat(messages: list[dict], temperature: float = 0.3,
                         json_mode: bool = False, num_predict: int = 512) -> dict:
    """Запрос в LM Studio (OpenAI-формат /chat/completions).
    Возврат — как у ollama_chat: {'content', 'tool_calls': []}. Модель берётся
    загруженная (см. lmstudio_active_model) — сверять название не нужно."""
    model = await lmstudio_active_model()
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False,
                               "temperature": temperature, "max_tokens": num_predict,
                               # без «размышлений»: иначе думающие модели (qwen3/gemma) тратят лимит
                               # на reasoning_content, а в content приходит пустота
                               "reasoning_effort": "none"}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    t0 = time.monotonic()
    async with _base._local_client(180) as c:
        try:
            r = await c.post(f"{_base.LMSTUDIO_BASE}/chat/completions", json=payload)
            if r.status_code == 400 and json_mode and "response_format" in r.text:
                # свежий LM Studio не принимает json_object (только json_schema/text) —
                # повторяем обычным текстом: в системном промпте и так «строго JSON»
                del payload["response_format"]
                r = await c.post(f"{_base.LMSTUDIO_BASE}/chat/completions", json=payload)
            r.raise_for_status()
        except Exception as e:
            _lms_fail(_lms_why(e, _base.LMSTUDIO_BASE))
            raise
        msg = ((r.json().get("choices") or [{}])[0].get("message") or {})
        content = msg.get("content") or ""
        if isinstance(content, list):  # content-блоки — склеиваем текст
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    log.info("LM Studio %s ответил за %.1f с", _base.LMSTUDIO_MODEL, time.monotonic() - t0)
    _lms_ok()
    return {"content": strip_think(str(content)).strip(), "tool_calls": []}


def _text_tool_call(content: str, tools: list[dict]) -> dict | None:
    """Вызов, написанный текстом: слабые модели (Gemma) вместо tool_calls отвечают
    `finance_summary{}` прямо в content — и команда утекает в чат. Распознаём строго:
    весь ответ — известное имя + JSON-аргументы (или пусто). Иначе None."""
    names = {t.get("function", {}).get("name") for t in tools or []}
    m = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*(\((\{.*\})?\)|\{(.*)\})?\s*", content or "", re.S)
    if not m or m.group(1) not in names:
        return None
    raw_args = m.group(3) if m.group(3) is not None else m.group(4)
    args: dict = {}
    if raw_args:
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            return None
    return {"name": m.group(1), "arguments": args if isinstance(args, dict) else {}}


async def _lmstudio_tools_chat(messages: list[dict], tools: list[dict],
                               temperature: float = 0.2, num_predict: int = 700) -> dict:
    """Вызовы функций через LM Studio (OpenAI-формат — тот же, что cloud_tools_chat).
    Возврат — как у ollama_chat: {'content', 'tool_calls': [{'name','arguments'}]}.
    Нужно, чтобы при основном на LM Studio модель Ollama не сидела в памяти ради
    инструментов: иначе две большие модели делят 6 ГБ и всё замедляется в разы."""
    model = await lmstudio_active_model()
    msgs = []
    for m in messages:
        mm = {"role": m["role"], "content": m.get("content") or ""}
        if m.get("tool_calls"):
            mm["tool_calls"] = [{"id": f"call_{i}", "type": "function",
                                 "function": {"name": (tc.get("function") or tc).get("name"),
                                              "arguments": json.dumps(((tc.get("function") or tc).get("arguments")) or {}, ensure_ascii=False)}}
                                for i, tc in enumerate(m["tool_calls"])]
            mm["content"] = mm["content"] or None
        msgs.append(mm)
    # ответы инструментов: OpenAI-формат требует tool_call_id — сопоставляем по порядку
    pending: list[str] = []
    for mm in msgs:
        if mm["role"] == "assistant" and mm.get("tool_calls"):
            pending = [tc["id"] for tc in mm["tool_calls"]]
        elif mm["role"] == "tool":
            mm["tool_call_id"] = pending.pop(0) if pending else "call_0"
    body = {"model": model, "messages": msgs, "tools": tools, "tool_choice": "auto",
            "temperature": temperature, "max_tokens": num_predict, "reasoning_effort": "none"}
    t0 = time.monotonic()
    async with _base._local_client(180) as c:
        try:
            r = await c.post(f"{_base.LMSTUDIO_BASE}/chat/completions", json=body)
            r.raise_for_status()
        except Exception as e:
            _lms_fail(_lms_why(e, _base.LMSTUDIO_BASE))
            raise
        msg = (r.json().get("choices") or [{}])[0].get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            f = tc.get("function") or {}
            args = f.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append({"name": f.get("name"), "arguments": args})
        content = strip_think(str(msg.get("content") or "")).strip()
        if not calls:
            pseudo = _text_tool_call(content, tools)
            if pseudo:
                log.info("LM Studio %s: вызов текстом — понял как %s", model, pseudo["name"])
                calls = [pseudo]
                content = ""
    log.info("LM Studio %s: инструменты %s за %.1f с", model, "вызваны" if calls else "не вызваны", time.monotonic() - t0)
    _lms_ok()
    return {"content": content, "tool_calls": calls}


async def lmstudio_check() -> dict:
    """Живая проверка LM Studio для настроек: включён ли, отвечает ли, за сколько."""
    if not _base.LMSTUDIO_ENABLED:
        return {"configured": False, "ok": False, "detail": "выключен — локальные ответы идут через Ollama",
                "hint": "brain.lmstudio.enabled: true"}
    models = await lmstudio_models(force=True)
    if not models:
        return {"configured": True, "model": _base.LMSTUDIO_MODEL, "ok": False,
                "detail": f"LM Studio не отвечает или модель не загружена ({_base.LMSTUDIO_BASE})",
                "hint": "запустите сервер в LM Studio (Start Server) и загрузите модель"}
    model = _base.LMSTUDIO_MODEL if _base.LMSTUDIO_MODEL in models else models[0]
    t0 = time.monotonic()
    try:
        out = await _lmstudio_chat([{"role": "user", "content": "Ответь строго: ok"}], temperature=0.1, num_predict=20)
        dt = time.monotonic() - t0
        ok = bool(out.get("content"))
        return {"configured": True, "model": model, "ok": ok, "seconds": round(dt, 1),
                "detail": f"{model}: ответил за {dt:.1f} с" if ok else "пустой ответ"}
    except Exception as e:
        return {"configured": True, "model": model, "ok": False, "detail": f"ошибка: {str(e)[:120]}"}
