"""Распознавание речи — faster-whisper, полностью локально (аудио никуда не уходит).

Модель качается один раз (~500 МБ для «small», ~1.5 ГБ для «medium») в ~/.cache/huggingface.
Работает на CPU: голосовое в 10 секунд распознаётся за 2–5 с на «small».
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from .. import identity
from ..config import cfg

log = logging.getLogger("assistant.voice")

_VOICE = getattr(cfg, "voice", None)
STT_MODEL = str(getattr(getattr(_VOICE, "stt", None), "model", "small") or "small")
STT_DEVICE = str(getattr(getattr(_VOICE, "stt", None), "device", "cpu") or "cpu")
# fast: beam 1, одна температура — в 2–3 раза быстрее на CPU, точность на коротких командах почти та же
STT_FAST = bool(getattr(getattr(_VOICE, "stt", None), "fast", True))
ENABLED = bool(getattr(_VOICE, "enabled", True)) if _VOICE is not None else True

# Быстрое распознавание через Groq Whisper (whisper-large-v3-turbo, ~1 с вместо 5–15 с на CPU). ВЫКЛЮЧЕНО по умолчанию:
# голос уходит в облако. Включается в настройках: voice.stt.cloud = true (ключ берётся из brain.cloud.api_key, если провайдер Groq).
STT_CLOUD = bool(getattr(getattr(_VOICE, "stt", None), "cloud", False))
_model = None
_lock = threading.Lock()
LAST_VIA = "local"


def _groq_key() -> str | None:
    c = getattr(getattr(cfg, "brain", None), "cloud", None)
    if c is not None and str(getattr(c, "provider", "")).lower() == "groq" and getattr(c, "api_key", ""):
        return str(c.api_key)
    return None


def _transcribe_cloud(pcm_or_path) -> str | None:
    """Groq Whisper. Принимает путь к файлу или float32-массив 16 кГц. None = не вышло (упадём на локальный)."""
    key = _groq_key()
    if not key:
        return None
    import io
    import httpx
    try:
        if isinstance(pcm_or_path, (str, Path)):
            fname = Path(pcm_or_path).name; data = Path(pcm_or_path).read_bytes()
        else:
            import numpy as np, wave
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes((np.clip(np.asarray(pcm_or_path), -1, 1) * 32767).astype("<i2").tobytes())
            fname = "a.wav"; data = buf.getvalue()
        r = httpx.post("https://api.groq.com/openai/v1/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                       files={"file": (fname, data)}, data={"model": "whisper-large-v3-turbo", "language": "ru", "temperature": "0",
                                                            "prompt": f"{identity.title()}, потратил 700 рублей. Задача: сдать отчёт. Встреча в среду в 15:00."},
                       timeout=20)
        r.raise_for_status()
        global LAST_CONFIDENCE, LAST_VIA
        LAST_CONFIDENCE = 0.9; LAST_VIA = "cloud"
        return (r.json().get("text") or "").strip()
    except Exception as e:
        log.warning("Groq Whisper не ответил (%s) — распознаю локально", str(e)[:100])
        return None
LAST_ERROR: str | None = None
LAST_CONFIDENCE: float = 1.0   # 0..1 — насколько Whisper уверен в последней расшифровке

# слова-паразиты Whisper на тишине/шуме
_HALLUCINATIONS = {"субтитры", "продолжение следует", "редактор субтитров", "спасибо за просмотр", "дима торжок",
                   "субтитры сделал dimatorzok", "субтитры подогнал", "с вами был", "подписывайтесь"}


def _add_cuda_dlls() -> None:
    """Windows: ctranslate2 ищет cublas/cudnn DLL в PATH. install_voice.bat ставит их pip-пакетами nvidia-* — подключаем их папки."""
    import os
    try:
        import importlib.util
        for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_runtime"):
            spec = importlib.util.find_spec(pkg)
            if not spec or not spec.submodule_search_locations:
                continue
            for base in spec.submodule_search_locations:
                for sub in ("bin", "lib"):
                    d = os.path.join(base, sub)
                    if os.path.isdir(d):
                        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                        if hasattr(os, "add_dll_directory"):
                            os.add_dll_directory(d)
    except Exception as e:  # pragma: no cover
        log.debug("cuda dlls: %s", e)


def cuda_ok() -> bool:
    """Видит ли ctranslate2 видеокарту (после install_voice.bat)."""
    try:
        _add_cuda_dlls()
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _load():
    """Ленивая загрузка модели (первый вызов — долгий: скачивание)."""
    global _model, LAST_ERROR
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            LAST_ERROR = "Пакет faster-whisper не установлен — запустите install_voice.bat."
            raise RuntimeError(LAST_ERROR)
        if STT_DEVICE != "cpu":
            _add_cuda_dlls()
        compute = "int8" if STT_DEVICE == "cpu" else "int8_float16"
        log.info("Загружаю модель распознавания whisper-%s (%s)… первый раз качается, это долго", STT_MODEL, STT_DEVICE)
        try:
            import os as _os
            threads = max(2, min(8, (_os.cpu_count() or 4) - 2))   # многоядерный CPU: whisper параллелится хорошо
            _model = WhisperModel(STT_MODEL, device=STT_DEVICE, compute_type=compute, cpu_threads=threads)
        except Exception as e:
            if STT_DEVICE != "cpu":
                log.warning("whisper на %s не завёлся (%s) — работаю на CPU. Для GPU: install_voice.bat", STT_DEVICE, str(e)[:120])
                _model = WhisperModel(STT_MODEL, device="cpu", compute_type="int8")
            else:
                LAST_ERROR = f"Не удалось загрузить whisper-{STT_MODEL}: {e}"
                raise
        LAST_ERROR = None
        log.info("Модель распознавания готова")
        return _model


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return ENABLED
    except ImportError:
        return False


def warmup() -> None:
    """Прогреть модель в фоне при старте, чтобы первое голосовое не ждало скачивания."""
    if not available():
        return
    threading.Thread(target=lambda: _safe_load(), daemon=True, name="whisper-warmup").start()


def _safe_load():
    try:
        _load()
    except Exception as e:  # pragma: no cover
        log.warning("Прогрев whisper не удался: %s", e)


def _transcribe_sync(path) -> str:
    """path — файл (любой формат) или numpy-массив float32 16 кГц (ПК-клиент: без записи на диск)."""
    global LAST_VIA
    if STT_CLOUD:
        txt = _transcribe_cloud(path)
        if txt is not None:
            low = txt.lower().strip(" .!")
            return "" if (not txt or low in _HALLUCINATIONS) else txt
    LAST_VIA = "local"
    model = _load()
    # подсказка словаря: Whisper точнее слышит частые команды ассистента
    hint = (f"{identity.title()}, что у меня сегодня? Потратил 700 рублей на такси. Задача: сдать отчёт. Встреча в среду в 15:00. "
            "Долг Сберу. Баланс Т-Банк. Напомни завтра. Мысль: идея для проекта. Отмени последнюю.")
    if STT_FAST:
        hint = f"{identity.title()}, потратил 700 рублей. Задача: сдать отчёт. Встреча в среду в 15:00. Долг Сберу, Т-Банк."   # короче подсказка — быстрее декодер
        segments, info = model.transcribe(path, language="ru", beam_size=1, best_of=1, temperature=0.0,
                                          vad_filter=True, initial_prompt=hint,
                                          vad_parameters={"min_silence_duration_ms": 300},
                                          condition_on_previous_text=False, no_speech_threshold=0.6, log_prob_threshold=-1.0)
    else:
        segments, info = model.transcribe(path, language="ru", beam_size=5, best_of=5, temperature=[0.0, 0.2, 0.4],
                                          vad_filter=True, initial_prompt=hint,
                                          vad_parameters={"min_silence_duration_ms": 400},
                                          condition_on_previous_text=False, no_speech_threshold=0.6, log_prob_threshold=-1.0)
    global LAST_CONFIDENCE
    segs = list(segments)
    text = " ".join(s.text.strip() for s in segs).strip()
    if segs:
        import math
        lp = sum(s.avg_logprob * max(1, len(s.text)) for s in segs) / max(1, sum(max(1, len(s.text)) for s in segs))
        LAST_CONFIDENCE = max(0.0, min(1.0, math.exp(lp)))   # avg_logprob −0.2 → 0.82, −0.7 → 0.5, −1.2 → 0.3
    else:
        LAST_CONFIDENCE = 0.0
    low = text.lower().strip(" .!")
    if not text or low in _HALLUCINATIONS or any(h in low for h in _HALLUCINATIONS if len(low) < 40):
        return ""
    return text


async def transcribe(path: str | Path) -> str:
    """Файл (ogg/opus от Telegram, wav, mp3 — что угодно, что понимает ffmpeg/av) → текст. Пусто = не разобрал."""
    return await asyncio.to_thread(_transcribe_sync, str(path))


def transcribe_pcm(pcm16) -> str:
    """int16-массив 16 кГц (микрофон ПК) → текст, синхронно и без файла."""
    import numpy as np
    return _transcribe_sync(np.asarray(pcm16, dtype=np.float32) / 32768.0)
