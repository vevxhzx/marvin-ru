# Зрение: describe_image (локально -> LM Studio -> облако).
from __future__ import annotations

import re
import time

from . import base as _base
from . import lmstudio as _lms_mod
from . import cloud as _cloud_mod

from .base import CLOUD_VISION_MODELS, _CLOUD_VISION_GOOD, cloud_title, log, strip_think
__all__ = [
    "_VISION_CHECKED_AT",
    "_img_mime",
    "_lms_cached_models",
    "_local_vision_available",
    "describe_image",
    "vision_hint",
    "vision_status",
]

_VISION_CHECKED_AT = 0.0


async def _local_vision_available() -> bool:
    """Есть ли локальная модель зрения. Отрицательный ответ перепроверяем раз в минуту —
    Ollama могли поднять или модель докачать уже после старта ассистента."""
    global _VISION_CHECKED_AT
    if not _base.VISION_MODEL or _base.GAME_MODE:
        return False
    import time as _t
    if _base._VISION_LOCAL_OK is None or (not _base._VISION_LOCAL_OK and _t.monotonic() - _VISION_CHECKED_AT > 60):
        _VISION_CHECKED_AT = _t.monotonic()
        try:
            async with _base._local_client(5) as c:
                models = [m.get("name", "") for m in (await c.get(f"{_base.OLLAMA_URL}/api/tags")).json().get("models", [])]
                want = _base.VISION_MODEL.split(":")[0]
                _base._VISION_LOCAL_OK = any(m == _base.VISION_MODEL or m.split(":")[0] == want for m in models)
        except Exception:
            _base._VISION_LOCAL_OK = False
    return bool(_base._VISION_LOCAL_OK)


def _img_mime(image_b64: str) -> str:
    """MIME по магическим байтам (LM Studio нужен точный data-URL: PNG как image/png)."""
    try:
        import base64 as _b64
        head = _b64.b64decode((image_b64 or "")[:24])
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if head[:2] == b"\xff\xd8":
            return "image/jpeg"
        if head[:4] in (b"GIF8",):
            return "image/gif"
        if head[:4] == b"RIFF":
            return "image/webp"
    except Exception:
        pass
    return "image/jpeg"


def _lms_cached_models() -> list[str]:
    """Модели LM Studio из свежего кэша (без сети — для синхронных мест вроде vision_status)."""
    ts, ids = _base._LMS_MODELS_CACHE
    if time.monotonic() - ts < 60 and ids:
        return list(ids)
    return []


def vision_hint() -> str:
    """Что сделать, чтобы зрение заработало — одной фразой для пользователя."""
    if _base.VISION_WHERE == "cloud" and not (_base.cloud_enabled() and _base.CLOUD_PROVIDER in CLOUD_VISION_MODELS):
        return "Выбрано смотреть картинки через облако, но провайдер не умеет зрение или ключ не задан (нужен groq / openrouter / nvidia)."
    if _base.VISION_WHERE == "cloud" and _base.LAST_CLOUD_ERROR:
        return _base.LAST_CLOUD_ERROR
    if _base.GAME_MODE and _base.VISION_WHERE != "cloud":
        return "Игровой режим — мозг выгружен. Скажите «игра окончена» или переключите зрение на облако в настройках."
    if _base.LMSTUDIO_ENABLED and not _lms_cached_models():
        return (f"LM Studio не отвечает или модель не загружена ({_base.LMSTUDIO_BASE}). "
                "Запустите сервер и загрузите зрячую модель — отвечает уже загруженная, название сверять не нужно.")
    if not _base.VISION_MODEL:
        return ("Модель зрения не задана. Проще всего перейти на qwen3.5:4b — она сама видит картинки "
                "(ollama pull qwen3.5:4b и указать её в Настройки → мозг → модель).")
    if _base.VISION_MODEL == _base.OLLAMA_MODEL:
        return f"Ollama не отвечает или модель {_base.VISION_MODEL} не скачана (ollama pull {_base.VISION_MODEL})."
    return f"Модель зрения {_base.VISION_MODEL} не найдена в Ollama: ollama pull {_base.VISION_MODEL} — или очистите поле «модель зрения», если основная модель qwen3.5/gemma сама видит картинки."


async def describe_image(image_b64: str, question: str, private: bool = False, short: bool = True) -> str | None:
    """Картинка (base64 JPEG/PNG) + вопрос → текст. private=True — только локально (чеки, документы)."""
    hint = " Отвечай по-русски, кратко." + (" 1–3 предложения." if short else "")
    # local-first: в режиме local картинка (это скриншот/фото хозяина) в облако не уходит НИКОГДА,
    # даже если в настройках стоит vision.where=cloud и есть ключ — иначе «local» перестал быть local
    cloud_possible = _base.VISION_CLOUD_OK and not _base.local_only() and _base.cloud_enabled() and _base.CLOUD_PROVIDER in CLOUD_VISION_MODELS
    # LM Studio первым: включён — значит, выбран основным движком; отвечает уже загруженная
    # модель, название сверять не нужно. В игровом режиме пропускаем, как и Ollama.
    if _base.VISION_WHERE != "cloud" and not _base.GAME_MODE and await _lms_mod.lmstudio_available():
        try:
            model = await _lms_mod.lmstudio_active_model()
            async with _base._local_client(180) as c:
                r = await c.post(f"{_base.LMSTUDIO_BASE}/chat/completions", json={
                    "model": model, "stream": False, "temperature": 0.2,
                    "max_tokens": 300 if short else 800, "reasoning_effort": "none",
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": question + hint},
                        {"type": "image_url", "image_url": {"url": f"data:{_img_mime(image_b64)};base64,{image_b64}"}}]}]})
                r.raise_for_status()
                msg = (r.json().get("choices") or [{}])[0].get("message") or {}
                txt = strip_think(str(msg.get("content") or "")).strip()
                if txt:
                    log.info("LM Studio %s: картинка разобрана", model)
                    return txt
                log.warning("LM Studio %s: пустой ответ на картинку — пробую дальше", model)
        except Exception as e:
            log.warning("LM Studio vision failed (%s) — %s", type(e).__name__, "пробую Ollama" if _base.VISION_WHERE != "cloud" else "пробую облако")
    # где: cloud — сразу в облако; auto — локально, но если облако доступно, ждём локальную не дольше 40 с
    try_local = _base.VISION_WHERE != "cloud" and await _local_vision_available()
    if try_local:
        try:
            async with _base._local_client(40 if (cloud_possible and _base.VISION_WHERE == "auto") else 180) as c:
                r = await c.post(f"{_base.OLLAMA_URL}/api/chat", json={
                    "model": _base.VISION_MODEL, "stream": False, "keep_alive": _base.OLLAMA_KEEP_ALIVE,
                    "messages": [{"role": "user", "content": question + hint, "images": [image_b64]}],
                    "options": {"temperature": 0.2, "num_predict": 300 if short else 800}})
                if r.status_code == 200:
                    txt = strip_think((r.json().get("message") or {}).get("content", ""))
                    if txt:
                        return txt
        except Exception as e:
            log.warning("local vision failed (%s) — %s", type(e).__name__, "пробую облако" if cloud_possible else "облако недоступно")
    # private (чек/документ) в облако — только если пользователь явно выбрал vision.where = cloud
    if _base.VISION_WHERE == "local" or not cloud_possible or (private and _base.VISION_WHERE != "cloud"):
        return None
    models = CLOUD_VISION_MODELS[_base.CLOUD_PROVIDER]
    good = _CLOUD_VISION_GOOD.get(_base.CLOUD_PROVIDER)
    order = ([good] + [m for m in models if m != good]) if good else list(models)
    headers = {"Authorization": f"Bearer {_base.CLOUD_KEY}", "Content-Type": "application/json"}
    last = ""
    for model in order:
        body = {"model": model, "temperature": 0.2, "max_tokens": 400 if short else 900,
                "messages": [{"role": "user", "content": [{"type": "text", "text": question + hint},
                                                           {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}]}
        if _base.CLOUD_PROVIDER == "openrouter":
            # думающим моделям (dots, nemotron) запрещаем размышления: иначе весь max_tokens
            # уходит в поле reasoning, а в content приезжает пустота
            body["reasoning"] = {"effort": "none", "exclude": True}
        try:
            r = await _cloud_mod._cloud_post("/chat/completions", body, headers, timeout=60)
            if r.status_code in (400, 404, 410, 422) and re.search(r"decommission|not found|does not exist|no endpoints found|deprecated|unsupported|invalid model", r.text, re.I):
                last = f"{model}: снята с поддержки"; continue
            r.raise_for_status()
            msg = (r.json().get("choices") or [{}])[0].get("message") or {}
            txt = strip_think(msg.get("content") or "")
            if txt:
                _CLOUD_VISION_GOOD[_base.CLOUD_PROVIDER] = model
                _base.LAST_CLOUD_ERROR = None
                return txt
            last = f"{model}: пустой ответ"
        except Exception as e:
            last = f"{model}: {str(e)[:100]}"
            if "429" in last:
                continue   # лимит на эту модель — следующая
    _base.LAST_CLOUD_ERROR = f"{cloud_title()} (зрение): {last}"
    log.warning("cloud vision failed: %s", _base.LAST_CLOUD_ERROR)
    return None


def vision_status() -> str:
    cloud = _base.VISION_CLOUD_OK and _base.cloud_enabled() and _base.CLOUD_PROVIDER in CLOUD_VISION_MODELS
    cm = _CLOUD_VISION_GOOD.get(_base.CLOUD_PROVIDER) or (CLOUD_VISION_MODELS.get(_base.CLOUD_PROVIDER) or ["?"])[0]
    if _base.VISION_WHERE == "cloud":
        return f"через {cloud_title()} ({cm})" if cloud else "облако выбрано, но провайдер без зрения или ключ не задан"
    if _base.VISION_WHERE != "cloud" and _base.LMSTUDIO_ENABLED and _lms_cached_models():
        ids = _lms_cached_models()
        active = _base.LMSTUDIO_MODEL if _base.LMSTUDIO_MODEL in ids else ids[0]
        return f"локально (LM Studio: {active})" + (f", запасной путь {cloud_title()}" if cloud and _base.VISION_WHERE == "auto" else "")
    if _base.VISION_MODEL and _base._VISION_LOCAL_OK:
        return f"локально ({_base.VISION_MODEL})" + (f", запасной путь {cloud_title()}" if cloud and _base.VISION_WHERE == "auto" else "")
    if cloud and _base.VISION_WHERE == "auto":
        return f"через {cloud_title()} ({cm})" + (f" · локальная {_base.VISION_MODEL} не отвечает" if _base.VISION_MODEL else "")
    return "выключено"
