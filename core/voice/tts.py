"""Синтез речи. Основной — Silero v4 (офлайн, русский, голос «eugene»), новее — Piper
(офлайн, CPU, естественнее Silero, голос «denis»), запасной — Edge TTS (Microsoft, онлайн).

Silero: одна модель ~40 МБ (data/models/v4_ru.pt), качается сама при первом запуске. Работает на CPU,
10 секунд речи ≈ 2–3 с. Piper: голос ~60 МБ (data/models/piper/*.onnx + .json), качается сам
при первом запуске, синтез через `python -m piper` (пакет piper-tts + onnxruntime, только CPU),
wav 22050 Гц → ресемпл в SAMPLE_RATE. Текст подготавливается: числа → слова, ₽ → рублей,
эмодзи/markdown вырезаются. Выход — ogg/opus (то, что Telegram показывает как голосовое) или wav.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
from pathlib import Path

from .. import identity
from ..config import DATA_DIR, cfg

log = logging.getLogger("jarvis.voice")

_VOICE = getattr(cfg, "voice", None)
_TTS = getattr(_VOICE, "tts", None)
ENGINE = str(getattr(_TTS, "engine", "silero") or "silero")          # silero / edge / off
SPEAKER = str(getattr(_TTS, "speaker", "eugene") or "eugene")        # silero: aidar, baya, kseniya, xenia, eugene
EDGE_VOICE = str(getattr(_TTS, "edge_voice", "ru-RU-DmitryNeural") or "ru-RU-DmitryNeural")
PIPER_VOICE = str(getattr(_TTS, "piper_voice", "ru_RU-denis-medium") or "ru_RU-denis-medium")  # piper: ru_RU-denis/dmitri/irina/ruslan-medium
PIPER_MODEL = str(getattr(_TTS, "piper_model", "") or "")  # свой .onnx; пусто — data/models/piper/<голос>.onnx
PIPER_LENGTH = float(getattr(_TTS, "piper_length", 1.0) or 1.0)  # темп: 1.0 норма, 1.15–1.3 медленнее и чётче (ударения medium-голосов)
PIPER_NOISE = getattr(_TTS, "piper_noise", None)                 # выразительность: None — дефолт модели
PIPER_NOISE_W = getattr(_TTS, "piper_noise_w", None)             # разброс длительностей: None — дефолт модели
PIPER_TAIL_SEC = 0.3  # пауза в конце фразы: Piper отдаёт звук встык (0 мс тишины) — без неё кодек/плеер подъедают последний слог

# Голоса, за которыми — «она»: тексты бота о себе идут в женском роде («записала»).
# Список по VOICES (routers/pc.py): piper denis/dmitri — м, irina — ж, ruslan — м.
FEMININE_IDS = frozenset({
    "ru_RU-irina-medium", "baya", "kseniya", "xenia", "ru-RU-SvetlanaNeural",
})


def voice_is_feminine() -> bool:
    """Текущий голос женский? ENGINE/SPEAKER/PIPER_VOICE читаем живьём (выбор с сайта применяется без перезапуска)."""
    try:
        eng = resolve_engine()
        if eng == "piper":
            return PIPER_VOICE in FEMININE_IDS
        if eng == "silero":
            return SPEAKER in FEMININE_IDS
        return EDGE_VOICE in FEMININE_IDS
    except Exception:
        return False
REPLY_VOICE = str(getattr(_TTS, "reply_in_telegram", "voice") or "voice")  # never — только текст · voice — голосом на голосовые (по умолчанию) · always — на всё

MODEL_URL = "https://models.silero.ai/models/tts/ru/v4_ru.pt"
MODEL_PATH = DATA_DIR / "models" / "v4_ru.pt"
SAMPLE_RATE = int(getattr(_TTS, "sample_rate", 24000) or 24000)   # 24000 — вдвое быстрее 48000, на слух то же

_model = None
_lock = threading.Lock()
LAST_ERROR: str | None = None

# в local-режиме edge-движок молча гнал бы текст в Microsoft — предупреждаем один раз за процесс
_LOCAL_EDGE_NOTICE_DONE = False


def _brain_mode() -> str:
    """Режим мозга (local / hybrid / cloud) — читаем живьём из cfg, а не кэшируем:
    настройка меняется с сайта без перезапуска."""
    try:
        return str(getattr(getattr(cfg, "brain", None), "mode", "") or "").strip().lower()
    except Exception:
        return ""


def resolve_engine(configured: str | None = None) -> str:
    """Какой движок озвучки реально использовать.

    В `local`-режиме `edge` запрещён молча уходить в облако: принудительно `silero`
    (офлайн; если torch нет — порядок fallback в speak_to_file всё равно попробует edge,
    но уже с предупреждением в логе). `hybrid`/`cloud` не трогаем. `off` остаётся `off`.
    `piper` — офлайн (CPU), поэтому в `local` НЕ форсится и остаётся `piper`.
    """
    global _LOCAL_EDGE_NOTICE_DONE
    eng = (configured if configured is not None else ENGINE).strip().lower() or "silero"
    if eng == "edge" and _brain_mode() == "local":
        eng = "silero"
        if not _LOCAL_EDGE_NOTICE_DONE:
            _LOCAL_EDGE_NOTICE_DONE = True
            log.warning("TTS: brain.mode=local — движок edge отправлял бы текст в Microsoft, использую silero (офлайн)")
    return eng


# ------------------------------------------------------------------ подготовка текста
_EMOJI_RX = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\u2B50\u2B06\u2934\u2935\u3030\u303D\u3297\u3299\uFE0F\u200D]+")
_MD_RX = re.compile(r"[*_`#>|]+")
_URL_RX = re.compile(r"https?://\S+")
_NUM_RX = re.compile(r"(?<![\w.,])(-?)(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,](\d+))?")

_REPL = [
    (re.compile(r"₽"), " рублей"), (re.compile(r"\bруб(?![а-яё])\.?"), " рублей"), (re.compile(r"\bтыс(?![а-яё])\.?"), " тысяч"),
    (re.compile(r"\bмлн(?![а-яё])\.?"), " миллионов"), (re.compile(r"[−](?=\s*\d)"), "минус "), (re.compile(r"(?<=\s)-(?=\d)"), "минус "), (re.compile(r"[()\[\]\"«»]"), " "), (re.compile(r"\bт\.к\."), "так как"), (re.compile(r"\bт\.е\."), "то есть"),
    (re.compile(r"\bнапр\."), "например"), (re.compile(r"(\d)%"), r"\1 процентов"), (re.compile(r"\+"), " плюс "),
    (re.compile(r"[—–]"), ","), (re.compile(r"·"), ","), (re.compile(r"\bТ-Банк\w*"), "Ти-Банк"),
    (re.compile(r"\bJ\.?A\.?R\.?V\.?I\.?S\.?", re.I), identity.NAME), (re.compile(r"\bOllama\b", re.I), "Оллама"),
    (re.compile(r"\bGroq\b", re.I), "Грок"), (re.compile(r"\bTelegram\b", re.I), "Телеграм"), (re.compile(r"\bOK\b", re.I), "окей"),
]


def _num_words(m: re.Match) -> str:
    try:
        from num2words import num2words
    except ImportError:
        return m.group(0)
    sign, whole, frac = m.group(1), m.group(2).replace(" ", "").replace("\u00a0", ""), m.group(3)
    try:
        n = int(whole)
        if len(whole) > 12:
            return m.group(0)
        s = num2words(n, lang="ru")
        if frac and frac.strip("0"):
            s += " и " + num2words(int(frac[:2]), lang="ru")
        return ("минус " if sign else "") + s
    except Exception:
        return m.group(0)


_TIME_RX = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_DATE_RX = re.compile(r"\b(\d{1,2})\.(\d{2})(?:\.(\d{4}))?\b")
_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _time_words(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    try:
        from num2words import num2words
        s = num2words(h, lang="ru")
        return s + (f" {num2words(mi, lang='ru')}" if mi else " ноль ноль")
    except Exception:
        return m.group(0)


def _date_words(m: re.Match) -> str:
    d, mo = int(m.group(1)), int(m.group(2))
    if not 1 <= mo <= 12 or not 1 <= d <= 31:
        return m.group(0)
    try:
        from num2words import num2words
        day = num2words(d, lang="ru", to="ordinal")
        # «пятое» → средний род
        day = re.sub(r"(ый|ий|ой)$", "ое", day)
        return f"{day} {_MONTHS[mo - 1]}"
    except Exception:
        return m.group(0)


def prepare(text: str) -> str:
    """Текст ответа → то, что можно озвучить: без эмодзи/markdown/ссылок, числа словами."""
    t = _URL_RX.sub(" ссылка ", text)
    t = _EMOJI_RX.sub(" ", t)
    t = _MD_RX.sub(" ", t)
    for rx, rep in _REPL:
        t = rx.sub(rep, t)
    t = _TIME_RX.sub(_time_words, t)
    t = _DATE_RX.sub(_date_words, t)
    t = _NUM_RX.sub(_num_words, t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    return t[:1500]


# ------------------------------------------------------------------ Silero
def _download_model() -> None:
    import httpx
    from .fetch import verify_file
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODEL_PATH.with_suffix(".part")
    log.info("Скачиваю голос Silero v4 (40 МБ) → %s", MODEL_PATH)
    with httpx.Client(timeout=120, follow_redirects=True) as c, c.stream("GET", MODEL_URL) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
    try:
        verify_file(tmp, MODEL_URL)   # mismatch — ValueError, битый файл не подменяет модель
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(MODEL_PATH)


def _load_silero():
    global _model, LAST_ERROR
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            import torch
        except ImportError:
            LAST_ERROR = "Пакет torch не установлен — запустите install_voice.bat (пункт Silero)."
            raise RuntimeError(LAST_ERROR)
        if not MODEL_PATH.exists():
            _download_model()
        import os as _os
        torch.set_num_threads(max(1, min(6, (_os.cpu_count() or 4))))
        imp = torch.package.PackageImporter(str(MODEL_PATH))
        m = imp.load_pickle("tts_models", "model")
        m.to(torch.device("cpu"))
        _model = m
        LAST_ERROR = None
        log.info("Голос Silero готов (%s)", SPEAKER)
        return _model


def silero_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def _silero_wave(text: str):
    import numpy as np
    model = _load_silero()
    speaker = SPEAKER if SPEAKER in getattr(model, "speakers", [SPEAKER]) else "eugene"
    # Silero держит ~1000 символов за раз — режем по предложениям
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if len(cur) + len(sent) > 800 and cur:
            parts.append(cur); cur = sent
        else:
            cur = (cur + " " + sent).strip()
    if cur:
        parts.append(cur)
    def _say(t: str):
        """Одна попытка озвучить кусок; None — не вышло. Silero кидает IndexError('tuple index out of range')
        на тексте, где после его внутренней очистки не остаётся ни одного читаемого слова (тире, эмодзи, латиница)."""
        t = t.replace("—", ",").replace("–", ",").replace("«", "").replace("»", "").replace("…", ".")
        t = re.sub(r"\s+", " ", t).strip(" ,;:")
        if not re.search(r"[а-яА-ЯёЁ0-9]", t):
            return None
        for attempt, txt in enumerate((t, re.sub(r"[^а-яА-ЯёЁ0-9 ,.!?\-]", " ", t))):
            txt = re.sub(r"\s+", " ", txt).strip()
            if not txt or not re.search(r"[а-яА-ЯёЁ0-9]", txt):
                continue
            if not re.search(r"[.!?]$", txt):
                txt += "."
            try:
                return model.apply_tts(text=txt, speaker=speaker, sample_rate=SAMPLE_RATE, put_accent=attempt == 0, put_yo=attempt == 0).numpy()
            except Exception as e:
                log.debug("silero: %r не озвучилось (%s)", txt[:40], e)
        return None

    chunks = []
    for p in parts:
        w = _say(p)
        if w is None:
            # кусок целиком не пошёл — по предложениям, битые пропускаем
            for sent in re.split(r"(?<=[.!?])\s+", p):
                w2 = _say(sent)
                if w2 is not None:
                    chunks.append(w2)
        else:
            chunks.append(w)
    if not chunks:
        raise RuntimeError("Silero не смог озвучить текст")
    pause = np.zeros(int(SAMPLE_RATE * 0.25), dtype=np.float32)
    out = chunks[0]
    for c in chunks[1:]:
        out = np.concatenate([out, pause, c])
    return out.astype(np.float32)


def _write_audio(wave, path: Path) -> None:
    """float32 mono → ogg/opus (для Telegram) или wav."""
    import numpy as np
    if path.suffix.lower() == ".wav":
        import wave as wavmod
        pcm = (np.clip(wave, -1, 1) * 32767).astype(np.int16)
        with wavmod.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(pcm.tobytes())
        return
    import av
    out = av.open(str(path), "w", format="ogg")
    st = out.add_stream("libopus", rate=SAMPLE_RATE)
    st.bit_rate = 40000
    st.layout = "mono"
    frame = av.AudioFrame.from_ndarray(wave.reshape(1, -1), format="fltp", layout="mono")
    frame.sample_rate = SAMPLE_RATE
    for p in st.encode(frame):
        out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close()


def _silero_to_file(text: str, path: Path) -> Path:
    _write_audio(_silero_wave(text), path)
    return path


# ------------------------------------------------------------------ Piper (офлайн, CPU)
# Голос — два файла: <голос>.onnx + <голос>.onnx.json в DATA_DIR/models/piper/.
# Качаются с HuggingFace (rhasspy/piper-voices) при первом запуске, как модель Silero.
PIPER_DIR = DATA_DIR / "models" / "piper"
PIPER_SR = 22050  # частота, на которой поют русские голоса Piper
_PIPER_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU"


def _piper_parts(voice: str) -> tuple[str, str]:
    """ru_RU-denis-medium → (denis, medium)."""
    bits = str(voice or "").split("-")
    speaker = bits[1] if len(bits) > 1 and bits[1] else "denis"
    quality = bits[2] if len(bits) > 2 and bits[2] else "medium"
    return speaker, quality


def _piper_model_paths() -> tuple[Path, Path]:
    """Пара (onnx, json). PIPER_MODEL задан — берём его (json рядом, с суффиксом .json)."""
    if PIPER_MODEL:
        onnx = Path(PIPER_MODEL)
        return onnx, Path(str(onnx) + ".json")
    name = PIPER_VOICE
    return PIPER_DIR / f"{name}.onnx", PIPER_DIR / f"{name}.onnx.json"


def _download_piper_model() -> None:
    import httpx
    from .fetch import verify_file
    onnx, js = _piper_model_paths()
    if onnx.exists() and js.exists():
        return
    speaker, quality = _piper_parts(PIPER_VOICE)
    onnx.parent.mkdir(parents=True, exist_ok=True)
    for dest in (onnx, js):
        if dest.exists():
            continue
        url = f"{_PIPER_HF}/{speaker}/{quality}/{dest.name}"
        if PIPER_MODEL:  # свой путь задан, но файла нет — качать нечего, честно падаем
            raise RuntimeError(f"модель Piper не найдена: {dest}")
        tmp = dest.with_suffix(dest.suffix + ".part")
        log.info("Скачиваю голос Piper %s (~60 МБ) → %s", dest.name, dest)
        with httpx.Client(timeout=300, follow_redirects=True) as c, c.stream("GET", url) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
        try:
            verify_file(tmp, url)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(dest)


def _piper_available() -> bool:
    """Пакет piper-tts стоит (модуль `piper`) или бинарь `piper` в PATH."""
    try:
        import importlib.util as _ilu
        if _ilu.find_spec("piper") is not None:
            return True
    except Exception:
        pass
    import shutil
    return shutil.which("piper") is not None


_PIPER_VOICES: dict[str, object] = {}  # onnx-путь → загруженный PiperVoice (модель ~60 МБ, грузим раз)


def _clamp_length(x) -> float:
    """Темп в разумных рамках: медленнее 2.0 — зануда, быстрее 0.5 — скороговорка."""
    try:
        return min(2.0, max(0.5, float(x)))
    except (TypeError, ValueError):
        return 1.0


try:
    from piper.config import SynthesisConfig
except ImportError:  # piper-tts не стоит (CI, облачный инстанс): конфиг-шим тех же полей
    from dataclasses import dataclass

    @dataclass
    class SynthesisConfig:
        speaker_id: object = None
        length_scale: object = None
        noise_scale: object = None
        noise_w_scale: object = None
        normalize_audio: bool = True
        volume: float = 1.0


def _piper_syn_config():
    """SynthesisConfig из настроек (темп/выразительность) или None — тогда дефолт модели."""
    length = _clamp_length(PIPER_LENGTH)
    kw = {}
    if abs(length - 1.0) > 1e-9:
        kw["length_scale"] = length
    for key, attr in (("noise_scale", PIPER_NOISE), ("noise_w_scale", PIPER_NOISE_W)):
        try:
            kw[key] = float(attr) if attr is not None else None
        except (TypeError, ValueError):
            kw[key] = None
        if kw[key] is None:
            del kw[key]
    if not kw:
        return None
    return SynthesisConfig(**kw)


def _piper_voice():
    """Загруженный голос (кэш на процесс). CLI `python -m piper` больше не используем:
    на Windows он молча отдавал пустой wav (wave.Error: channels not specified)."""
    from piper.voice import PiperVoice

    _download_piper_model()
    onnx, _ = _piper_model_paths()
    key = str(onnx)
    v = _PIPER_VOICES.get(key)
    if v is None:
        with _lock:
            v = _PIPER_VOICES.get(key)
            if v is None:
                v = PiperVoice.load(key)
                _PIPER_VOICES[key] = v
                log.info("Голос Piper готов (%s)", PIPER_VOICE)
    return v


def _piper_wave(text: str):
    """Текст → float32 mono на SAMPLE_RATE через PiperVoice.synthesize_wav (CPU, без cuda-флагов)."""
    import tempfile
    import wave as wavmod
    import numpy as np
    voice = _piper_voice()
    syn_config = _piper_syn_config()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = tmp.name
    try:
        with wavmod.open(tmp_wav, "wb") as w:
            voice.synthesize_wav(text, w, syn_config=syn_config)
        with wavmod.open(tmp_wav, "rb") as w:
            n, sw, ch, sr = w.getnframes(), w.getsampwidth(), w.getnchannels(), w.getframerate()
            if n == 0:
                raise RuntimeError("piper отдал пустой wav — не озвучилось")
            raw = w.readframes(n)
        if sw == 2:
            wave = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sw == 4:
            wave = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise RuntimeError(f"piper отдал wav с разрядностью {sw * 8} бит — не умею")
        if ch > 1:
            wave = wave.reshape(-1, ch).mean(axis=1).astype(np.float32)
        if sr != SAMPLE_RATE:  # 22050 → SAMPLE_RATE линейной интерполяцией (без scipy)
            idx = np.linspace(0, len(wave) - 1, int(round(len(wave) * SAMPLE_RATE / sr)))
            wave = np.interp(idx, np.arange(len(wave)), wave).astype(np.float32)
        tail = np.zeros(int(round(SAMPLE_RATE * PIPER_TAIL_SEC)), dtype=np.float32)
        wave = np.concatenate([wave, tail])
        return wave
    finally:
        Path(tmp_wav).unlink(missing_ok=True)


def _piper_to_file(text: str, path: Path) -> Path:
    _write_audio(_piper_wave(text), path)
    return path


# ------------------------------------------------------------------ Edge TTS (запасной, онлайн)
async def _edge_to_file(text: str, path: Path) -> Path:
    import edge_tts
    tmp_mp3 = path.with_suffix(".mp3")
    await edge_tts.Communicate(text, EDGE_VOICE, rate="+5%").save(str(tmp_mp3))
    if path.suffix.lower() == ".mp3":
        return tmp_mp3
    # mp3 → ogg/opus через av (Telegram голосовые — только opus)
    import av
    inp = av.open(str(tmp_mp3))
    out = av.open(str(path), "w", format="ogg")
    st = out.add_stream("libopus", rate=48000); st.bit_rate = 40000; st.layout = "mono"
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=48000)
    for frame in inp.decode(audio=0):
        for f in resampler.resample(frame):
            for p in st.encode(f):
                out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close(); inp.close()
    tmp_mp3.unlink(missing_ok=True)
    return path


# ------------------------------------------------------------------ публичное
def enabled() -> bool:
    return resolve_engine() != "off"


CACHE_DIR = DATA_DIR / "voice_cache"   # одинаковые фразы («готово», приветствие, напоминания) не синтезируем дважды
CACHE_KEEP = 400                        # последние N файлов; старые чистим, чтобы папка не росла бесконечно
_CACHE_VERSION = "v2"                   # v1 отравлен: упавший piper кэшировал чужой (мужской silero) звук под piper-ключом


def _cache_path(spoken: str, suffix: str, engine: str | None = None) -> Path:
    import hashlib
    eng = resolve_engine(engine)  # local+edge → silero: кэш не должен отдавать чужой движок
    tune = f"{PIPER_LENGTH}|{PIPER_NOISE}|{PIPER_NOISE_W}" if eng == "piper" else ""
    key = f"{_CACHE_VERSION}|{eng}|{SPEAKER}|{EDGE_VOICE}|{PIPER_VOICE}|{PIPER_MODEL}|{tune}|{SAMPLE_RATE}|{suffix}|{spoken}".encode("utf-8")
    return CACHE_DIR / (hashlib.sha1(key).hexdigest()[:20] + (suffix or ".ogg"))


def _ensure_cache_version() -> None:
    """Одноразовая чистка отравленного v1-кэша (файлы без маркера версии). Сам кэш — expendable."""
    try:
        marker = CACHE_DIR / ".cache_v2"
        if marker.exists():
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        for old in CACHE_DIR.glob("*"):
            if old.is_file() and not old.name.startswith("."):
                old.unlink(missing_ok=True)
        marker.write_text("v2", encoding="utf-8")
    except Exception:  # pragma: no cover
        pass


def _cache_prune() -> None:
    try:
        files = sorted(CACHE_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[CACHE_KEEP:]:
            old.unlink(missing_ok=True)
    except Exception:  # pragma: no cover
        pass


async def speak_to_file(text: str, path: str | Path) -> Path | None:
    """Озвучить текст в файл (.ogg для Telegram, .wav/.mp3 для ПК). None — не вышло (причина в LAST_ERROR).
    Одинаковые фразы берутся из кэша data/voice_cache — озвучка типовых ответов мгновенная и без сети."""
    global LAST_ERROR
    if resolve_engine() == "off":
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    spoken = prepare(text)
    if not spoken:
        return None
    _ensure_cache_version()
    suffix = path.suffix or ".ogg"
    eng_resolved = resolve_engine()
    if eng_resolved == "piper":
        order = ["piper", "silero", "edge"]
    else:
        order = ["silero", "edge"] if eng_resolved == "silero" else ["edge", "silero"]
    import shutil
    result = None
    for eng in order:
        # кэш — строго своего движка: чужой звук под чужим ключом (баг v1) больше не оседает
        hit = _cache_path(spoken, suffix, eng)
        if hit.exists() and hit.stat().st_size > 0:
            try:
                shutil.copyfile(hit, path)   # копию отдаём вызывающему: он вправе её удалить, кэш остаётся
                return path
            except Exception as e:  # pragma: no cover
                log.debug("tts cache read: %s", e)
        try:
            if eng == "piper":
                if not _piper_available():
                    continue
                result = await asyncio.to_thread(_piper_to_file, spoken, path)
            elif eng == "silero":
                if not silero_available():
                    continue
                result = await asyncio.to_thread(_silero_to_file, spoken, path)
            else:
                result = await _edge_to_file(spoken, path)
        except Exception as e:
            LAST_ERROR = f"{eng}: {e}"
            log.warning("TTS %s не сработал: %s", eng, e)
            continue
        try:
            dest = _cache_path(spoken, suffix, eng)
            if not dest.exists() or dest.stat().st_size == 0:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
                _cache_prune()
        except Exception as e:  # pragma: no cover
            log.debug("tts cache write: %s", e)
        break
    if not result:
        return None
    return result


def warmup() -> None:
    if ENGINE == "silero" and silero_available():
        threading.Thread(target=lambda: _safe(), daemon=True, name="silero-warmup").start()
    elif ENGINE == "piper" and _piper_available():
        threading.Thread(target=lambda: _safe_piper(), daemon=True, name="piper-warmup").start()


def _safe_piper():
    try:
        _download_piper_model()  # только докачать голос заранее; синтез — по факту (CLI, CPU)
    except Exception as e:  # pragma: no cover
        log.warning("Прогрев Piper не удался: %s", e)


def _safe():
    try:
        _load_silero()
    except Exception as e:  # pragma: no cover
        log.warning("Прогрев Silero не удался: %s", e)
