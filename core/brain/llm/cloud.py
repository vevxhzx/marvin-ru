# Облако: сменный OpenAI-совместимый провайдер + Gemini.
from __future__ import annotations

import json
import time
import httpx
from ...config import cfg

from . import base as _base

from .base import PROVIDERS, GROQ_TOOLS_PREFER, _ANON_HINT, _NO_THINK_HINT, _OR_AVOID, _OR_AVOID_RUNTIME, _OR_PREFER, _PREFERRED, _THINK_RX, _VOICE_MODEL_BAD, _cloud_base_url, _cloud_model, _local_only_refuse, _reasoning_body, cloud_max_tokens, cloud_timeout, cloud_title, log, short_mode, strip_think, token_sink
__all__ = [
    "LAST_CLOUD_MODEL",
    "_cloud_client",
    "_cloud_post",
    "_cloud_routes",
    "_cloud_stream",
    "_explain_cloud_error",
    "_explain_gemini_error",
    "_gemini_client",
    "cloud_chat",
    "cloud_check",
    "cloud_tools_chat",
    "gemini_chat",
    "gemini_check",
    "gemini_models",
    "groq_tools_model",
    "list_cloud_models",
    "resolve_cloud_model",
    "resolve_gemini_model",
]

LAST_CLOUD_MODEL: str = ""          # модель, которая реально ответила в последний раз (после фолбэков) — показываем в настройках


def _note_cloud_usage(data: dict, model: str = "") -> None:
    """Отметить токены одного ответа облака (см. base.usage_note). Повторы тоже считаются:
    провайдер списывает деньги за КАЖДЫЙ принятый запрос, поэтому честно считаем все."""
    try:
        p, c = _base.tokens_openai(data)
        _base.usage_note(model or _cloud_model(), p, c)
    except Exception as e:  # pragma: no cover — счётчик токенов не имеет права ломать ответ
        log.debug("usage cloud: %s", e)


async def resolve_cloud_model(force: bool = False) -> str:
    """Для «auto» у OpenRouter — выбрать живую бесплатную модель. Для остальных — как в настройках."""
    want = _base.CLOUD_MODEL or PROVIDERS.get(_base.CLOUD_PROVIDER, {}).get("model", "")
    if want != "auto":
        return want
    if _base._CLOUD_RESOLVED and not force:
        return _base._CLOUD_RESOLVED
    ids: list[str] = []
    for name, proxy in _cloud_routes():
        try:
            async with _cloud_client(20, proxy) as c:
                r = await c.get(f"{_cloud_base_url()}/models", headers={"Authorization": f"Bearer {_base.CLOUD_KEY}"})
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
    _base._CLOUD_RESOLVED = pick or (free[0] if free else "openrouter/auto")
    log.info("%s: выбрана бесплатная модель %s", cloud_title(), _base._CLOUD_RESOLVED)
    return _base._CLOUD_RESOLVED


def _cloud_routes() -> list[tuple[str, str | None]]:
    """Как ходить в облако, по порядку: (название, прокси). Первое, что сработает, запоминается.
    1) явный прокси из настроек облака; 2) напрямую; 3) прокси Telegram (тот же VPN); 4) системный прокси Windows."""
    routes: list[tuple[str, str | None]] = []
    if _base.CLOUD_PROXY:
        routes.append(("прокси облака", _base.CLOUD_PROXY))
    routes.append(("напрямую", None))
    tg_proxy = (getattr(cfg.telegram, "proxy", "") or "").strip()
    if tg_proxy and tg_proxy != _base.CLOUD_PROXY:
        routes.append(("прокси Telegram", tg_proxy))
    routes.append(("системный прокси", "env"))
    return routes


def _cloud_client(timeout: float, proxy: str | None = None) -> httpx.AsyncClient:
    kw: dict = {"timeout": httpx.Timeout(timeout, connect=10), "trust_env": False}
    if proxy == "env":
        kw["trust_env"] = True
    elif proxy:
        kw["proxy"] = proxy
    return httpx.AsyncClient(**kw)


async def _cloud_post(path: str, body: dict, headers: dict, timeout: float | None = None) -> "httpx.Response":
    """POST в облако с перебором маршрутов при сетевых ошибках (ответ сервера, даже 4xx, — не повод менять маршрут).

    Повтор по маршруту НЕ удваивает оплату: тело запроса одно и то же, поэтому при гонке двух
    ответов берётся первый успешный, а не суммируется ничего. Если провайдер успел списать токены,
    а ответ не дошёл, повтор — это повтор, а не две оплаты за одну работу."""
    if timeout is None:
        timeout = cloud_timeout()   # brain.cloud.timeout: по умолчанию 45, поднимается под длинные ответы
    if _local_only_refuse():
        raise httpx.ConnectError("режим local: облако выключено")
    # Groq: у reasoning-моделей (qwen3.x, gpt-oss) просим спрятать «размышления», иначе <think> прилетает в текст
    if _base.CLOUD_PROVIDER == "groq" and path.endswith("/chat/completions") and _THINK_RX.search(str(body.get("model", ""))):
        if "reasoning_format" not in body and "include_reasoning" not in body:
            body["reasoning_format"] = "hidden"
        if body.get("model", "").startswith("qwen/") and "reasoning_effort" not in body:
            body["reasoning_effort"] = "none"
        if "gpt-oss" in body.get("model", "") and "reasoning_effort" not in body:
            body["reasoning_effort"] = "low"   # gpt-oss думает всегда; на «medium» размышления съедают весь max_tokens короткого ответа
        if "tools" in body or body.get("response_format"):
            body.pop("reasoning_format", None)   # с tools/JSON «raw»/«hidden» не дружат — оставляем parsed по умолчанию
    routes = _cloud_routes()
    if _base._CLOUD_ROUTE_OK in routes:
        routes = [_base._CLOUD_ROUTE_OK] + [r for r in routes if r != _base._CLOUD_ROUTE_OK]
    last: Exception | None = None
    for name, proxy in routes:
        try:
            async with _cloud_client(timeout, proxy) as c:
                r = await c.post(f"{_cloud_base_url()}{path}", json=body, headers=headers)
            if _base._CLOUD_ROUTE_OK != (name, proxy):
                log.info("%s: маршрут — %s", cloud_title(), name)
            _base._CLOUD_ROUTE_OK = (name, proxy)
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
    if _local_only_refuse():
        return None
    routes = _cloud_routes()
    if _base._CLOUD_ROUTE_OK in routes:
        routes = [_base._CLOUD_ROUTE_OK] + [r for r in routes if r != _base._CLOUD_ROUTE_OK]
    # usage в стриме приезжает последним куском, только если провайдеру сказано его прислать
    stream_body = {**body, "stream": True}
    if _base.CLOUD_PROVIDER == "openrouter":
        stream_body["usage"] = {"include": True}
    elif _base.CLOUD_PROVIDER == "groq":
        stream_body["stream_options"] = {"include_usage": True}
    for name, proxy in routes:
        text = ""
        try:
            async with _cloud_client(45, proxy) as c:
                async with c.stream("POST", f"{_cloud_base_url()}/chat/completions", json=stream_body, headers=headers) as r:
                    if r.status_code != 200:
                        _base._CLOUD_ROUTE_OK = (name, proxy)
                        body_txt = (await r.aread())[:200].decode("utf-8", "ignore")
                        log.warning("%s: стрим ответил %s (%s) — повторяю обычным запросом", cloud_title(), r.status_code, body_txt)
                        return None
                    if _base._CLOUD_ROUTE_OK != (name, proxy):
                        log.info("%s: маршрут — %s", cloud_title(), name)
                    _base._CLOUD_ROUTE_OK = (name, proxy)
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except Exception:
                            continue
                        # последний кучек стрима несёт usage (если провайдер его присылает)
                        if isinstance(chunk, dict) and chunk.get("usage"):
                            _note_cloud_usage(chunk, str(chunk.get("model") or body.get("model", "")))
                        try:
                            delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
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


async def cloud_chat(system: str, user_text: str, history: list[dict] | None = None, _force_model: str | None = None,
                     temperature: float = 0.7) -> str | None:
    """Единая точка входа в облако. Провайдер — из настроек; Gemini — частный случай."""
    global LAST_CLOUD_MODEL
    history_retry = _force_model is not None
    system = system + _NO_THINK_HINT   # для всех путей в облако (чат, голос, инициативные фразы, сортировка)
    if not _base.CLOUD_PROVIDER or _base.CLOUD_PROVIDER == "gemini":
        ans = await gemini_chat(system, user_text, history)
        _base.LAST_CLOUD_ERROR = None if ans else _base.LAST_GEMINI_ERROR
        if ans:
            LAST_CLOUD_MODEL = f"gemini:{_base._RESOLVED_MODEL or _base.GEMINI_MODEL}"
        return ans
    if not _base.cloud_enabled():
        return None
    # анонимайзер общий для любого облака и любого режима. Он включён по умолчанию (см. core/config.py)
    # и выключается только явным `brain.gemini.anonymize: false`; раньше в режиме cloud его принудительно
    # выключали — тогда личные данные уходили в облако открытым текстом, как только personal_tools
    # оставался выключенным. history_retry (повтор на другой модели) оставляем как было: там текст уже
    # уходил и «[скрыто]» вместо прежнего варианта ломал повтор.
    if cfg.brain.gemini.anonymize and not history_retry:
        user_text = _base.anonymize(user_text)
        history = [{**h, "text": _base.anonymize(h["text"])} for h in (history or [])]
        system = system + _ANON_HINT
    messages = [{"role": "system", "content": system}]
    messages += [{"role": "user" if h["role"] == "user" else "assistant", "content": h["text"]} for h in (history or [])]
    messages.append({"role": "user", "content": user_text})
    headers = {"Authorization": f"Bearer {_base.CLOUD_KEY}", "Content-Type": "application/json"}
    if _base.CLOUD_PROVIDER == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/local-assistant"; headers["X-Title"] = "Local Assistant"
    model = _force_model or await resolve_cloud_model()
    _t0 = time.monotonic()
    main_model = model
    if short_mode.get() and not _force_model and model not in _VOICE_MODEL_BAD:
        if _base.CLOUD_VOICE_MODEL:
            model = _base.CLOUD_VOICE_MODEL
        elif _base.CLOUD_PROVIDER == "groq" and "compound" in model:
            model = "openai/gpt-oss-20b"   # compound ходит в интернет и думает 3–8 с; для голоса — быстрая
    # reasoning-модели тратят max_tokens и на скрытые размышления: 220 на голосовой ответ для gpt-oss/qwen3 — это пустой content
    short_max = 700 if _THINK_RX.search(model) else 220
    body = {"model": model, "messages": messages, "temperature": temperature,
            "max_tokens": short_max if short_mode.get() else cloud_max_tokens()}
    if _base.CLOUD_PROVIDER == "openrouter":
        # auto — effort=minimal (мыслим коротко, ~10% max_tokens, иначе content остаётся пустым) и
        # exclude (готовые мысли не возвращаем); brain.cloud.reasoning: off — effort=none, не думаем
        # совсем, явный уровень (low/medium/high) — как задан. Если провайдер не принял параметр
        # (400) — убираем его и повторяем один раз, см. ниже.
        body["reasoning"] = _reasoning_body("chat")
    r = None
    sink = token_sink.get()
    if sink is not None:
        streamed = await _cloud_stream(body, headers, sink)
        if streamed:
            _base.LAST_CLOUD_ERROR = None
            LAST_CLOUD_MODEL = body.get("model", "")
            log.info("облако %s: %s — %.1f с (стрим, %s)", cloud_title(), LAST_CLOUD_MODEL,
                     time.monotonic() - _t0, (_base._CLOUD_ROUTE_OK or ("?",))[0])
            return streamed
        # стрим не удался — обычный запрос ниже
    try:
        r = await _cloud_post("/chat/completions", body, headers)
        if r is None:   # защита: ни один маршрут не ответил — дальше по коду ждали бы r.status_code
            raise httpx.ConnectError("провайдер не ответил ни одним маршрутом")
        if r.status_code == 400 and "reasoning" in body:
            # модель/провайдер не принял параметр reasoning — убираем и повторяем один раз, иначе чат молчит
            log.warning("%s: параметр reasoning не принят (%s) — повторяю запрос без него", cloud_title(), r.text[:160])
            body.pop("reasoning", None)
            r = await _cloud_post("/chat/completions", body, headers)
        if r.status_code == 400 and "temperature" in body and "temperature" in (r.text or ""):
            # deepseek-reasoner и часть reasoning-моделей отвергают temperature («does not support the parameter») —
            # убираем и повторяем один раз, иначе ответ уходит локальной модели без причины
            log.warning("%s: параметр temperature не принят (%s) — повторяю запрос без него", cloud_title(), r.text[:160])
            body.pop("temperature", None)
            r = await _cloud_post("/chat/completions", body, headers)
        if r.status_code in (400, 404) and model != main_model:
            # голосовую модель убрали/переименовали — запоминаем и идём основной
            log.warning("%s: голосовая модель %s не принята (%s) — использую %s", cloud_title(), model, r.status_code, main_model)
            _VOICE_MODEL_BAD.add(model)
            body["model"] = main_model
            r = await _cloud_post("/chat/completions", body, headers)
        if r.status_code == 413 and history:
            # «Request Entity Too Large» на запросе в пару тысяч токенов — это не лимит модели, а шлюз/прокси по дороге.
            # Пишем, каким маршрутом шли и что ответили, и один раз повторяем напрямую без истории, прежде чем сдаться.
            log.warning("%s: 413 по маршруту «%s», тело %d байт, ответ: %s — повторяю напрямую без истории", cloud_title(),
                        (_base._CLOUD_ROUTE_OK or ("?",))[0], len(json.dumps(body, ensure_ascii=False).encode()), r.text[:200])
            body["messages"] = [messages[0], messages[-1]]
            async with _cloud_client(45, None) as c:
                r = await c.post(f"{_cloud_base_url()}/chat/completions", json=body, headers=headers)
        if True:
            r.raise_for_status()
            data = r.json()
            _note_cloud_usage(data, body.get("model", ""))
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            text = strip_think(msg.get("content") or "")
            # Пустой content при заполненном reasoning НИКОГДА не отдаём как ответ: раньше тут стоял
            # фолбэк на msg["reasoning"]/reasoning_content — в чат приходил сплошной поток мыслей,
            # обрезанный по max_tokens (без единой финальной реплики). Уходит фолбэком на локальную модель.
            _reasoning_only = not text and bool((msg.get("reasoning") or msg.get("reasoning_content") or "").strip())
            if _reasoning_only:
                log.warning("%s: content пуст, reasoning заполнен (finish_reason=%s) — рассуждения в чат не отдаю, "
                            "ответит локальная модель", cloud_title(),
                            (data.get("choices") or [{}])[0].get("finish_reason"))
            if not text and body["model"] != main_model:
                # быстрая голосовая модель промолчала (обычно finish_reason=length: всё ушло в размышления) — один раз основной
                fin = (data.get("choices") or [{}])[0].get("finish_reason")
                log.warning("%s: %s вернула пустой ответ (finish_reason=%s) — повторяю основной моделью %s", cloud_title(), body["model"], fin, main_model)
                body["model"] = main_model
                body["max_tokens"] = cloud_max_tokens()
                body.pop("reasoning_effort", None)
                r = await _cloud_post("/chat/completions", body, headers)
                r.raise_for_status()
                data = r.json()
                _note_cloud_usage(data, body.get("model", ""))
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                text = strip_think(msg.get("content") or "")
                _reasoning_only = not text and bool((msg.get("reasoning") or msg.get("reasoning_content") or "").strip())
            if (data.get("choices") or [{}])[0].get("finish_reason") == "length" and body["max_tokens"] < 4096:
                # Обрезка по лимиту. Два вида: либо reasoning-модель съела ВЕСЬ бюджет на скрытые мысли
                # (живой случай: 988 из 1024 токенов, content пуст), либо ответ просто длинный и оборван
                # — пачку «разбей на задачи» рвать нельзя. Один раз даём лимит покрупнее.
                log.warning("%s: ответ оборван по max_tokens (%s, content %s) — повторяю с лимитом 4096",
                            cloud_title(), "всё ушло в размышления" if not text else "длинный ответ",
                            "пустой" if not text else "частичный")
                body["max_tokens"] = 4096
                r = await _cloud_post("/chat/completions", body, headers)
                r.raise_for_status()
                data = r.json()
                _note_cloud_usage(data, body.get("model", ""))
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                text = strip_think(msg.get("content") or "")
                _reasoning_only = not text and bool((msg.get("reasoning") or msg.get("reasoning_content") or "").strip())
            if not text:
                _base.LAST_CLOUD_ERROR = (f"{cloud_title()}: пустой ответ (модель вернула только рассуждения)."
                                    if _reasoning_only else f"{cloud_title()}: пустой ответ.")
                return None
            _base.LAST_CLOUD_ERROR = None
            LAST_CLOUD_MODEL = body.get("model", "")
            log.info("облако %s: %s — %.1f с, %s", cloud_title(), LAST_CLOUD_MODEL,
                     time.monotonic() - _t0, (_base._CLOUD_ROUTE_OK or ("?",))[0])
            return text
    except Exception as e:
        if r is not None and r.status_code in (404, 429) and (_base.CLOUD_MODEL or PROVIDERS.get(_base.CLOUD_PROVIDER, {}).get("model")) == "auto" and _base._CLOUD_RESOLVED:
            # бесплатную модель убрали или она перегружена — переподбираем один раз
            prev = _base._CLOUD_RESOLVED
            _OR_AVOID_RUNTIME.add(prev)
            new = await resolve_cloud_model(force=True)
            if new != prev:
                return await cloud_chat(system, user_text, history)
        # модель, вписанная руками, не существует/не поддерживается → один раз пробуем стандартную у провайдера
        default_model = PROVIDERS.get(_base.CLOUD_PROVIDER, {}).get("model", "")
        if (r is not None and r.status_code in (400, 404) and _base.CLOUD_MODEL and default_model and default_model != "auto"
                and model != default_model and not history_retry):
            log.warning("%s: модель «%s» отвергнута (%s) — пробую стандартную %s", cloud_title(), model, r.status_code, default_model)
            return await cloud_chat(system, user_text, history, _force_model=default_model)
        _base.LAST_CLOUD_ERROR = _explain_cloud_error(e, r if r is not None and r.status_code >= 400 else None)
        log.warning("облако %s: сбой за %.1f с (%s) — %s", cloud_title(), time.monotonic() - _t0,
                    (_base._CLOUD_ROUTE_OK or ("?",))[0], _base.LAST_CLOUD_ERROR)
        return None


async def groq_tools_model(force: bool = False) -> str:
    """Живая модель Groq для инструментов: первая из GROQ_TOOLS_PREFER, которая есть в /models. Кэш до перезапуска."""
    if _base._GROQ_TOOLS_MODEL and not force:
        return _base._GROQ_TOOLS_MODEL
    ids = await list_cloud_models()
    pick = next((m for m in GROQ_TOOLS_PREFER if m in ids), None)
    if not pick:
        # ничего из известного — любая чат-модель, кроме систем/классификаторов/аудио
        chat = [i for i in ids if not any(x in i for x in ("compound", "guard", "whisper", "orpheus", "tts", "safeguard"))]
        pick = chat[0] if chat else GROQ_TOOLS_PREFER[0]
    _base._GROQ_TOOLS_MODEL = pick
    log.info("Groq: модель для инструментов — %s", pick)
    return pick


async def list_cloud_models() -> list[str]:
    """GET /models у текущего провайдера. Пустой список — не достучались (ошибка в логе, не исключение)."""
    for name, proxy in _cloud_routes():
        try:
            async with _cloud_client(20, proxy) as c:
                r = await c.get(f"{_cloud_base_url()}/models", headers={"Authorization": f"Bearer {_base.CLOUD_KEY}"})
                r.raise_for_status()
                return [m.get("id", "") for m in r.json().get("data", [])]
        except Exception as e:
            log.debug("cloud models via %s failed: %s", name, e)
    return []


async def cloud_tools_chat(messages: list[dict], tools: list[dict], temperature: float = 0.2) -> dict | None:
    """Облако с инструментами (режим brain.mode = cloud, когда локальной модели нет). Тот же формат ответа,
    что у ollama_chat: {'content': str, 'tool_calls': [{'name','arguments'}]}. None — облако не ответило (причина
    в LAST_CLOUD_ERROR). Анонимайзер здесь НЕ применяется: в этом режиме пользователь осознанно отдал данные провайдеру
    (иначе инструменты бесполезны — «[сумма]» не запишешь). Gemini этот путь не поддерживает — только OpenAI-совместимые."""
    if not _base.cloud_enabled() or not _base.CLOUD_PROVIDER or _base.CLOUD_PROVIDER == "gemini":
        return None
    headers = {"Authorization": f"Bearer {_base.CLOUD_KEY}", "Content-Type": "application/json"}
    if _base.CLOUD_PROVIDER == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/local-assistant"; headers["X-Title"] = "Local Assistant"
    model = await resolve_cloud_model()
    if _base.CLOUD_PROVIDER == "groq" and (not _base.CLOUD_MODEL or "compound" in model):
        model = await groq_tools_model()   # compound свои tools не принимает; явная brain.cloud.model — уважается
    msgs = []
    for m in messages:
        mm = {"role": m["role"], "content": m.get("content") or ""}
        if m.get("tool_calls"):
            mm["tool_calls"] = [{"id": f"call_{i}", "type": "function",
                                 "function": {"name": tc["function"]["name"], "arguments": json.dumps(tc["function"].get("arguments") or {}, ensure_ascii=False)}}
                                for i, tc in enumerate(m["tool_calls"])]
            mm["content"] = mm["content"] or None
        msgs.append(mm)
    # ответы инструментов: OpenAI-формат требует tool_call_id — сопоставляем по порядку с последним assistant-сообщением
    pending: list[str] = []
    for mm in msgs:
        if mm["role"] == "assistant" and mm.get("tool_calls"):
            pending = [tc["id"] for tc in mm["tool_calls"]]
        elif mm["role"] == "tool":
            mm["tool_call_id"] = pending.pop(0) if pending else "call_0"
    if msgs and msgs[0]["role"] == "system":
        # та же просьба не показывать рассуждения, что и в cloud_chat: иначе content приходит
        # сплошным разбором, а tool_calls — пустыми
        msgs[0] = {**msgs[0], "content": (msgs[0]["content"] or "") + _NO_THINK_HINT}
    body = {"model": model, "messages": msgs, "tools": tools, "tool_choice": "auto", "temperature": temperature,
            "max_tokens": 160 if short_mode.get() else max(700, cloud_max_tokens())}
    if _base.CLOUD_PROVIDER == "openrouter":
        # auto — мысли не отдаём, бюджет не режем (здесь важна точность вызовов); brain.cloud.reasoning
        # (off / minimal / low / medium / high) действует и сюда — иначе на инструментах модель думает
        # с провайдерским усилием, списывая мысли как вывод и живя по несколько секунд на вызов.
        body["reasoning"] = _reasoning_body("tools")
    r = None
    try:
        r = await _cloud_post("/chat/completions", body, headers, timeout=max(60.0, cloud_timeout()))
        if r.status_code == 400 and "reasoning" in body:
            # модель/провайдер не принял параметр (например, у mandatory-модели нельзя выключить размышления) —
            # один раз без него, иначе вызовы инструментов молчат (то же делает cloud_chat выше)
            log.warning("%s: параметр reasoning не принят (%s) — повторяю без него", cloud_title(), r.text[:160])
            body.pop("reasoning", None)
            r = await _cloud_post("/chat/completions", body, headers, timeout=max(60.0, cloud_timeout()))
        if r.status_code == 404 and _base.CLOUD_PROVIDER == "groq" and body["model"] == _base._GROQ_TOOLS_MODEL:
            # модель вывели из оборота прямо сейчас — перечитать список и повторить один раз
            body["model"] = await groq_tools_model(force=True)
            r = await _cloud_post("/chat/completions", body, headers, timeout=max(60.0, cloud_timeout()))
        r.raise_for_status()
        _note_cloud_usage(r.json(), body.get("model", ""))
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
        _base.LAST_CLOUD_ERROR = None
        return {"content": strip_think(msg.get("content") or ""), "tool_calls": calls}
    except Exception as e:
        _base.LAST_CLOUD_ERROR = _explain_cloud_error(e, r if r is not None and r.status_code >= 400 else None)
        log.warning("cloud tools error: %s", _base.LAST_CLOUD_ERROR)
        return None


async def cloud_check() -> dict:
    if not _base.CLOUD_PROVIDER or _base.CLOUD_PROVIDER == "gemini":
        res = await gemini_check()
        return {**res, "provider": "gemini", "title": "Gemini"}
    if not _base.CLOUD_KEY:
        return {"ok": False, "detail": "Ключ не задан.", "provider": _base.CLOUD_PROVIDER, "title": cloud_title()}
    if _base.MODE == "local":
        return {"ok": False, "detail": "brain.mode = local — облако выключено.", "provider": _base.CLOUD_PROVIDER, "title": cloud_title()}
    ans = await cloud_chat("Отвечай одним словом.", "Скажи «ок».")
    return {"ok": bool(ans), "detail": ans or _base.LAST_CLOUD_ERROR or "нет ответа", "provider": _base.CLOUD_PROVIDER,
            "title": cloud_title(), "model": _cloud_model()}


def _gemini_client(timeout: float) -> httpx.AsyncClient:
    """Клиент для Gemini. Прокси: brain.gemini.proxy → иначе telegram.proxy (тот же VPN) → иначе напрямую."""
    proxy = _base.GEMINI_PROXY or ((getattr(cfg.telegram, "proxy", "") or "").strip() or None)
    kw: dict = {"timeout": timeout}
    if proxy:
        kw["proxy"] = proxy
    try:
        return httpx.AsyncClient(**kw)
    except ImportError:
        # socks5:// требует пакет socksio. Он лежит в vendor/ — подключим и попробуем ещё раз
        import sys
        from ...config import ROOT
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
            used = _base.GEMINI_PROXY or ((getattr(cfg.telegram, "proxy", "") or "").strip() or None)
            if used:
                return (f"Google не обслуживает Gemini API из вашего региона, хотя запрос шёл через прокси {used}. "
                        "Значит, у VPN сейчас российский/неподходящий выход — переключите сервер в VPN-клиенте на другую страну (не РФ, не Беларусь).")
            return ("Google не обслуживает Gemini API из вашего региона, а прокси не задан. Укажите в настройках «Прокси для Gemini» "
                    "тот же адрес, что для Telegram (например socks5://127.0.0.1:10808), или включите VPN на весь компьютер.")
        if r.status_code in (400, 401, 403) and ("api key" in msg.lower() or "api_key" in msg.lower() or "permission" in msg.lower()):
            return f"Ключ Gemini не принят ({r.status_code}): {msg}. Проверьте ключ в настройках → мозг."
        if r.status_code == 404:
            return (f"Модель «{_base._RESOLVED_MODEL or _base.GEMINI_MODEL}» отключена Google (404), а другой доступной по этому ключу не нашлось. "
                    f"Поставьте в настройках «Модель Gemini» = auto или проверьте ключ в Google AI Studio.")
        if r.status_code == 429:
            return "Лимит запросов Gemini исчерпан (429). Подождите минуту или проверьте квоту в Google AI Studio."
        if r.status_code >= 500:
            return f"Gemini временно недоступен ({r.status_code}). Попробуйте позже."
        return f"Gemini ответил {r.status_code}: {msg}"
    if isinstance(e, RuntimeError) and "socksio" in str(e):
        return str(e)
    used = _base.GEMINI_PROXY or ((getattr(cfg.telegram, "proxy", "") or "").strip() or None)
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
            r = await c.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": _base.GEMINI_KEY})
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
    if _base._RESOLVED_MODEL and not force:
        return _base._RESOLVED_MODEL
    available = await gemini_models()
    if not available:
        # список не получили (сеть/регион) — идём с тем, что указано, или с разумным дефолтом
        _base._RESOLVED_MODEL = _base.GEMINI_MODEL if _base.GEMINI_MODEL != "auto" else "gemini-2.5-flash"
        return _base._RESOLVED_MODEL
    if _base.GEMINI_MODEL != "auto" and _base.GEMINI_MODEL in available:
        _base._RESOLVED_MODEL = _base.GEMINI_MODEL
        return _base._RESOLVED_MODEL
    for want in _PREFERRED:
        if want in available:
            _base._RESOLVED_MODEL = want
            break
    else:
        flash = sorted((m for m in available if "flash" in m and "tts" not in m and "image" not in m and "live" not in m), reverse=True)
        _base._RESOLVED_MODEL = flash[0] if flash else available[0]
    if _base.GEMINI_MODEL != "auto":
        log.warning("Модель %s недоступна — использую %s. Поставьте brain.gemini.model: auto, чтобы не думать об этом.", _base.GEMINI_MODEL, _base._RESOLVED_MODEL)
    else:
        log.info("Gemini: выбрана модель %s", _base._RESOLVED_MODEL)
    return _base._RESOLVED_MODEL


async def gemini_chat(system: str, user_text: str, history: list[dict] | None = None, _retry: bool = True) -> str | None:
    if not _base.gemini_enabled() or _local_only_refuse():
        return None
    model = await resolve_gemini_model()
    if cfg.brain.gemini.anonymize:
        user_text = _base.anonymize(user_text)
        history = [{**h, "text": _base.anonymize(h["text"])} for h in (history or [])]
        system = system + _ANON_HINT
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
            r = await c.post(url, json=body, headers={"x-goog-api-key": _base.GEMINI_KEY})
            r.raise_for_status()
            data = r.json()
            cand = (data.get("candidates") or [{}])[0]
            try:
                _gp, _gc = _base.tokens_gemini(data)
                _base.usage_note(model, _gp, _gc)
            except Exception:  # pragma: no cover
                pass
            parts = cand.get("content", {}).get("parts") or []
            # у reasoning-моделей Gemini отдаёт мысли отдельными parts с флагом thought=true — их в чат не даём
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            if not text:
                reason = cand.get("finishReason") or data.get("promptFeedback", {}).get("blockReason") or "пусто"
                _base.LAST_GEMINI_ERROR = f"Gemini вернул пустой ответ ({reason})."
                log.warning("Gemini empty: %s", data)
                return None
            _base.LAST_GEMINI_ERROR = None
            return text
    except Exception as e:
        if r is not None and r.status_code == 404 and _retry:
            # модель отключили — переподбираем и пробуем ещё раз
            _base._RESOLVED_MODEL = None
            new = await resolve_gemini_model(force=True)
            if new and new != model:
                return await gemini_chat(system, user_text, history, _retry=False)
        _base.LAST_GEMINI_ERROR = _explain_gemini_error(e, r if r is not None and r.status_code >= 400 else None)
        log.warning("Gemini error: %s", _base.LAST_GEMINI_ERROR)
        return None


async def gemini_check() -> dict:
    """Проверка Gemini для страницы настроек: {'ok': bool, 'detail': str}."""
    if not _base.GEMINI_KEY:
        return {"ok": False, "detail": "Ключ не задан."}
    if _base.MODE == "local":
        return {"ok": False, "detail": "brain.mode = local — облако выключено."}
    ans = await gemini_chat("Отвечай одним словом.", "Скажи «ок».")
    return {"ok": bool(ans), "detail": ans or _base.LAST_GEMINI_ERROR or "нет ответа", "model": _base._RESOLVED_MODEL,
            "available": (await gemini_models())[:30]}
