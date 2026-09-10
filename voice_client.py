"""Голосовой клиент ассистента для ПК (запуск: voice.bat).

Слушает микрофон → ждёт «ассистент» (Vosk, офлайн) → записывает команду до паузы → Whisper (офлайн) →
отправляет текст ядру (http://127.0.0.1:8765/api/chat, то же, что сайт и Telegram) → озвучивает ответ
(Silero, офлайн) в наушники. Иконка в трее: серая — сплю, синяя — слушаю, жёлтая — думаю, зелёная — говорю.

Горячая клавиша (по умолчанию Ctrl+Shift+J) — начать слушать без wake word.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

if os.name == "nt":
    os.system("chcp 65001 >nul")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_LOG_FILE = ROOT / "data" / "voice.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S",
                    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(_LOG_FILE, encoding="utf-8")])
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("assistant.pc")


def _fatal(msg: str, exc: BaseException | None = None) -> None:
    """Понятное сообщение об ошибке + полный трейс в лог. Окно не закроется — voice.bat держит его открытым."""
    log.error(msg, exc_info=exc is not None)
    print("\n  [!] " + msg)
    if exc is not None:
        print(f"      ({type(exc).__name__}: {exc})")
    print(f"      Подробности: {_LOG_FILE}")


try:
    import numpy as np
except ImportError as _e:
    _fatal("Не установлен numpy — запустите install_voice.bat.", _e)
    sys.exit(2)

try:
    from core.config import cfg, DATA_DIR
    from core import identity
except Exception as _e:
    _fatal("Не удалось прочитать config.yaml или папку core/ — проверьте, что voice.bat лежит в папке ассистента рядом с core/.", _e)
    sys.exit(2)

_V = getattr(cfg, "voice", None)
_PC = getattr(_V, "pc", None)
API = str(getattr(_PC, "api", "") or f"http://127.0.0.1:{getattr(getattr(cfg, 'server', None), 'port', 8765)}")
HOTKEY = str(getattr(_PC, "hotkey", "ctrl+shift+j") or "ctrl+shift+j")


def _api_headers() -> dict:
    """Ключ доступа к ядру: на своём ПК (127.0.0.1) не нужен; если ядро на другой машине — берём из data/api_token
    рядом (та же папка) или из voice.pc.api_token в config.yaml."""
    tok = str(getattr(_PC, "api_token", "") or "")
    if not tok:
        try:
            tok = (Path(__file__).parent / "data" / "api_token").read_text(encoding="utf-8").strip()
        except Exception:
            tok = ""
    return {"X-Auth-Token": tok} if tok else {}


API_HEADERS = _api_headers()
MIC = getattr(_PC, "mic", None) or None                     # имя/номер устройства; None = по умолчанию
SILENCE_SEC = float(getattr(_PC, "silence_sec", 1.5) or 1.5)   # пауза, после которой команда считается законченной
MAX_CMD_SEC = float(getattr(_PC, "max_command_sec", 20) or 20)
CONFIRM_SOUND = bool(getattr(_PC, "beep", True)) if _PC is not None else True
FOLLOWUP_SEC = float(getattr(_PC, "followup_sec", 6) or 6)     # после ВОПРОСА ассистента столько секунд слушаем без «ассистент»
CONVO_SEC = float(getattr(_PC, "conversation_sec", 12) or 0)    # после ЛЮБОГО ответа столько секунд можно продолжать без «ассистент» (0 — выкл)
CONVO_MODE_SEC = float(getattr(_PC, "conversation_mode_sec", 120) or 120)   # «режим беседы»: окно после каждой реплики
_CONVO_ON_RX = re.compile(r"^\W*(режим беседы|давай поболтаем|поболтаем|поговорим|режим разговора|слушай меня|не отключайся)\W*$", re.I)
_CONVO_OFF_RX = re.compile(r"^\W*(хватит болтать|конец беседы|конец разговора|отбой|свободен|спасибо,? свободен|всё,? спасибо|все,? спасибо)\W*$", re.I)
_convo_mode = False
STREAM = bool(getattr(_PC, "stream", True)) if _PC is not None else True   # озвучивать по предложениям, пока мозг ещё пишет
SPEAK_REMINDERS = bool(getattr(_PC, "speak_reminders", True)) if _PC is not None else True   # напоминания и утренний бриф — вслух
NIGHT_FROM = int(getattr(_PC, "night_from", 23) or 23)          # ночной режим: тише, без «Сэр» в напоминаниях, короткие ответы
NIGHT_TO = int(getattr(_PC, "night_to", 7) or 7)
NIGHT_VOLUME = float(getattr(_PC, "night_volume", 0.45) or 0.45)
FILLER_SEC = float(getattr(_PC, "filler_sec", 1.5) or 1.5)      # если мозг молчит дольше — «Секунду…»
MORNING_REPORT = bool(getattr(_PC, "morning_report", True)) if _PC is not None else True   # доклад вслух при первом пробуждении ПК
_g = getattr(_PC, "games", []) or []
GAMES_EXTRA = [x.strip() for x in (_g.split(",") if isinstance(_g, str) else list(_g)) if str(x).strip()]   # свои игры (exe) для авто-игрового режима
_STOP_RX = re.compile(r"^\W*(стоп|хватит|тихо|замолчи|заткнись|отбой|стой|достаточно|молчать|ладно хватит)\W*$", re.I)
_DICTATE_RX = re.compile(r"^\W*(запиши|записывай|надиктую|диктую|запиши мысль|запиши заметку|запиши идею)\W*$", re.I)
_FILLERS = ["Секунду.", "Смотрю.", "Момент.", "Сейчас.", "Проверяю."]


def _is_night() -> bool:
    h = time.localtime().tm_hour
    return h >= NIGHT_FROM or h < NIGHT_TO if NIGHT_FROM > NIGHT_TO else NIGHT_FROM <= h < NIGHT_TO

SR = 16000
CHUNK = 1600  # 100 мс


# ------------------------------------------------------------------ состояние и трей
STATE = {"mode": "idle", "text": ""}   # idle / listening / thinking / speaking / off
_tray = None
_running = True


def set_state(mode: str, text: str = "") -> None:
    STATE["mode"], STATE["text"] = mode, text
    if _tray is not None:
        try:
            _tray.icon = _icon(mode)
            _tray.title = f"{identity.title()} · {_TITLES.get(mode, mode)}" + (f" · {text[:40]}" if text else "")
        except Exception:
            pass


_TITLES = {"idle": f"жду «{identity.title()}»", "listening": "слушаю", "thinking": "думаю", "speaking": "говорю", "off": "микрофон выключен"}
_COLORS = {"idle": (142, 142, 147), "listening": (10, 132, 255), "thinking": (255, 159, 10), "speaking": (48, 209, 88), "off": (255, 69, 58)}


def _icon(mode: str):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = _COLORS.get(mode, (142, 142, 147))
    d.ellipse((4, 4, 60, 60), fill=c + (255,))
    d.ellipse((20, 20, 44, 44), outline=(255, 255, 255, 255), width=6)
    return img


def _start_tray():
    global _tray, _running
    try:
        import pystray
    except ImportError:
        log.info("pystray не установлен — без иконки в трее")
        return

    def toggle_mic(icon, item):
        set_state("idle" if STATE["mode"] == "off" else "off")

    def listen_now(icon, item):
        _wake_event.set()

    def open_site(icon, item):
        import webbrowser
        webbrowser.open(API)

    def quit_(icon, item):
        global _running
        _running = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: "Микрофон: выкл → вкл" if STATE["mode"] == "off" else "Микрофон: вкл → выкл", toggle_mic),
        pystray.MenuItem(f"Слушать сейчас ({HOTKEY})", listen_now),
        pystray.MenuItem("Открыть сайт", open_site),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_),
    )
    _tray = pystray.Icon("assistant", _icon("idle"), f"{identity.title()} · запуск", menu)
    threading.Thread(target=_tray.run, daemon=True, name="tray").start()


# ------------------------------------------------------------------ звук
_audio_q: queue.Queue = queue.Queue()
_wake_event = threading.Event()
_speaking = threading.Event()


_interrupt = threading.Event()
_stop_q: "queue.Queue[bytes]" = queue.Queue()


def _mic_callback(indata, frames, t, status):
    if status:
        log.debug("mic status: %s", status)
    if not _speaking.is_set():   # пока ассистент говорит — микрофон не слушаем (иначе услышит сам себя)
        _audio_q.put(bytes(indata))
    else:
        _stop_q.put(bytes(indata))   # …кроме слова «стоп» — его ловим отдельным лёгким детектором


class _StopWatcher:
    """Пока ассистент говорит, второй распознаватель Vosk слушает только «стоп/хватит» и поднимает _interrupt."""

    def __init__(self, wake):
        self._wake = wake
        self._th: threading.Thread | None = None
        self._run = False

    def start(self):
        import vosk
        try:
            self._rec = vosk.KaldiRecognizer(self._wake._model, SR, json.dumps(["стоп", "хватит", f"{identity.NAME.lower()} стоп", f"{identity.NAME.lower()} хватит", "тихо", "замолчи", "[unk]"], ensure_ascii=False))
        except Exception:
            self._rec = None
        while not _stop_q.empty():
            _stop_q.get_nowait()
        self._run = True
        _interrupt.clear()
        self._th = threading.Thread(target=self._loop, daemon=True, name="stopwatch")
        self._th.start()

    def stop(self):
        self._run = False

    def _loop(self):
        if self._rec is None:
            return
        while self._run:
            try:
                chunk = _stop_q.get(timeout=0.3)
            except queue.Empty:
                continue
            pcm = np.frombuffer(chunk, dtype=np.int16)
            if _rms(pcm) < 400:      # тихо — не тратим CPU (динамики обычно дают меньше, чем голос рядом с микрофоном)
                continue
            try:
                if self._rec.AcceptWaveform(chunk):
                    txt = json.loads(self._rec.Result()).get("text", "")
                else:
                    txt = json.loads(self._rec.PartialResult()).get("partial", "")
            except Exception:
                continue
            if txt and re.search(r"\b(стоп|хватит|тихо|замолчи)\b", txt):
                log.info("Прервали: %r", txt)
                _interrupt.set()
                try:
                    import sounddevice as sd
                    sd.stop()
                except Exception:
                    pass
                return


def _beep(freq: int = 880, ms: int = 120) -> None:
    if not CONFIRM_SOUND:
        return
    try:
        import sounddevice as sd
        t = np.linspace(0, ms / 1000, int(48000 * ms / 1000), False)
        tone = (np.sin(2 * np.pi * freq * t) * 0.2 * np.hanning(len(t))).astype(np.float32)
        sd.play(tone, 48000, blocking=True)
    except Exception:
        pass


def _drain_mic() -> None:
    while not _audio_q.empty():
        try:
            _audio_q.get_nowait()
        except queue.Empty:
            break


def _play_wave(wave: np.ndarray, sr: int) -> None:
    import sounddevice as sd
    _speaking.set()
    try:
        sd.play(wave, sr, blocking=True)
    finally:
        time.sleep(0.15)   # хвост, чтобы эхо из колонок не попало в микрофон
        _drain_mic()
        _speaking.clear()


def _synth(text: str):
    """Текст → (wave, sr) или None. Silero офлайн, при сбое — голос Microsoft (edge)."""
    from core.voice import tts
    spoken = tts.prepare(text)
    if not spoken:
        return None
    if tts.silero_available() and tts.ENGINE == "silero":
        try:
            w = tts._silero_wave(spoken)
            if w is not None and len(w):
                return w, tts.SAMPLE_RATE
        except Exception as e:
            log.warning("Silero не озвучил (%s) — говорю голосом Microsoft", e)
    try:
        out = DATA_DIR / "tmp" / f"pc_out_{threading.get_ident()}.mp3"
        out.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(tts._edge_to_file(spoken, out))
        import av
        cont = av.open(str(out)); frames = [f.to_ndarray().mean(axis=0) for f in cont.decode(audio=0)]
        sr = cont.streams.audio[0].rate; cont.close()
        return np.concatenate(frames).astype(np.float32), sr
    except Exception as e:
        log.warning("Озвучка не удалась: %s", e)
        return None


class _Speaker:
    """Конвейер озвучки: предложения → синтез (в фоне, по очереди) → воспроизведение по порядку.
    Пока играет первая фраза, вторая уже синтезируется — ответ начинает звучать через ~1 с после первого слова мозга."""

    def __init__(self):
        from concurrent.futures import ThreadPoolExecutor
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self.first_audio_at: float | None = None
        self.spoke = False

    def start(self) -> None:
        _speaking.set()
        self.first_audio_at, self.spoke = None, False
        self._thread = threading.Thread(target=self._run, daemon=True, name="play")
        self._thread.start()

    def say(self, text: str) -> None:
        if text and text.strip() and not _interrupt.is_set():
            self._q.put(self._pool.submit(_synth, text.strip()))

    def say_now(self, text: str) -> None:
        """Озвучить немедленно вне очереди (заглушка «Секунду», пока мозг думает)."""
        self.say(text)

    def finish(self) -> None:
        self._q.put(None)
        if self._thread:
            self._thread.join()
        time.sleep(0.15)
        _drain_mic()
        _speaking.clear()

    def _run(self) -> None:
        import sounddevice as sd
        while True:
            fut = self._q.get()
            if fut is None:
                return
            try:
                res = fut.result()
            except Exception as e:
                log.warning("Синтез не удался: %s", e); continue
            if not res:
                continue
            wave_, sr = res
            if _interrupt.is_set():
                continue            # прервали — остаток ответа не озвучиваем
            if self.first_audio_at is None:
                self.first_audio_at = time.time()
            self.spoke = True
            try:
                if _is_night():
                    wave_ = (np.asarray(wave_, dtype=np.float32) * NIGHT_VOLUME)
                sd.play(wave_, sr, blocking=True)
            except Exception as e:
                log.warning("Не смог проиграть: %s", e)


_SENT_RX = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z0-9«\"(])")


def _split_ready(buf: str) -> tuple[list[str], str]:
    """Из накопленного текста вынуть законченные предложения; хвост вернуть обратно."""
    parts = _SENT_RX.split(buf)
    if len(parts) <= 1:
        return [], buf
    return parts[:-1], parts[-1]


def _rms(pcm: np.ndarray) -> float:
    return float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if len(pcm) else 0.0


def _record_command(prefix_pcm: bytes = b"", noise_floor: float = 300.0, silence_sec: float | None = None, max_sec: float | None = None) -> np.ndarray | None:
    """Пишем после wake word до паузы SILENCE_SEC (или MAX_CMD_SEC). None — тишина, ничего не сказали."""
    SILENCE_SEC_ = silence_sec or SILENCE_SEC
    MAX_CMD_SEC_ = max_sec or MAX_CMD_SEC
    buf = [np.frombuffer(prefix_pcm, dtype=np.int16)] if prefix_pcm else []
    started = time.time()
    last_voice = None
    # порог «это голос»: в 3 раза громче фона, но не ниже 220 — у USB-гарнитур речь бывает тихой (RMS 300–600)
    thresh = max(noise_floor * 3.0, 220.0)
    peak = 0.0
    while time.time() - started < MAX_CMD_SEC_:
        try:
            chunk = _audio_q.get(timeout=0.5)
        except queue.Empty:
            continue
        pcm = np.frombuffer(chunk, dtype=np.int16)
        buf.append(pcm)
        lvl = _rms(pcm)
        peak = max(peak, lvl)
        if lvl > thresh:
            last_voice = time.time()
        elif last_voice is None and time.time() - started > 4.0:
            break   # 4 секунды тишины после «ассистент» — передумали
        elif last_voice is not None and time.time() - last_voice > SILENCE_SEC_:
            break
    if last_voice is None:
        log.info("Тишина после «ассистент»: макс. громкость %.0f при пороге %.0f%s", peak, thresh,
                 " — микрофон очень тихий: в Windows → Звук → Ввод поднимите уровень до 80–100%" if 0 < peak < thresh else "")
        return None
    return np.concatenate(buf) if buf else None


def _write_wav(pcm: np.ndarray, path: Path) -> None:
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------ ядро
def _ask_core(text: str) -> str:
    import httpx
    try:
        with httpx.Client(timeout=150, trust_env=False, headers=API_HEADERS) as c:
            r = c.post(f"{API}/api/chat", json={"text": text, "channel": "voice"})
            r.raise_for_status()
            return r.json().get("text") or "Готово, сэр."
    except httpx.ConnectError:
        return "Ядро не запущено, сэр. Запустите start.bat."
    except Exception as e:
        log.warning("core error: %s", e)
        return "Что-то пошло не так на стороне ядра, сэр."


LAST_VIA = ""   # кто ответил в последний раз: шаблон / облако / локальная модель


def _ask_core_stream(text: str, on_sentence) -> tuple[str, float | None]:
    """Тот же вопрос ядру, но ответ приходит по словам: законченные предложения сразу отдаём в on_sentence.
    Возвращает (полный текст ответа, момент первого слова)."""
    import httpx
    global LAST_VIA
    buf, spoken, first_at, final = "", "", None, None
    LAST_VIA = ""
    try:
        with httpx.Client(timeout=httpx.Timeout(150, connect=5), trust_env=False, headers=API_HEADERS) as c:
            with c.stream("POST", f"{API}/api/chat/stream", json={"text": text, "channel": "voice"}) as r:
                r.raise_for_status()
                kind = ""
                for line in r.iter_lines():
                    if line.startswith("event:"):
                        kind = line[6:].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[5:].strip() or "null")
                        if kind == "token" and isinstance(data, str):
                            if first_at is None:
                                first_at = time.time()
                            buf += data
                            ready, buf = _split_ready(buf)
                            for sent in ready:
                                spoken += sent + " "; on_sentence(sent)
                        elif kind == "done" and isinstance(data, dict):
                            final = data.get("text") or ""
                            LAST_VIA = {"gemini": "облако", "ollama": "локальная модель", "rules": "шаблон"}.get(data.get("via"), data.get("via") or "")
                            break
    except httpx.ConnectError:
        return "Ядро не запущено, сэр. Запустите start.bat.", None
    except Exception as e:
        log.warning("core stream error: %s — обычный запрос", e)
        if not spoken:
            return _ask_core(text), None
        final = (spoken + buf).strip()
    final = final if final is not None else (spoken + buf).strip()
    # остаток: то, что мозг дописал после последней законченной фразы (или весь ответ, если он пришёл без стрима — шаблоны ⚡)
    plain = re.sub(r"\s*[⚡🧠☁️]+\s*$", "", final).strip()
    if not spoken:
        on_sentence(plain)
    elif plain.startswith(spoken.strip()):
        on_sentence(plain[len(spoken.strip()):].strip())
    else:
        on_sentence(buf.strip())   # ядро переписало ответ после стрима — договариваем то, что слышали
    return final or "Готово, сэр.", first_at


_say_q: queue.Queue = queue.Queue()   # фразы, которые ассистент говорит сам (напоминания из ядра)


def _reminder_listener() -> None:
    """Слушаем события ядра (SSE /api/events/stream): напоминания о встречах/задачах кладём в очередь озвучки.
    Голосовой клиент их произнесёт, как только освободится микрофон: «Сэр, через 10 минут созвон»."""
    import httpx
    seen: set[str] = set()
    while _running:
        try:
            with httpx.Client(timeout=httpx.Timeout(None, connect=5), trust_env=False, headers=API_HEADERS) as c:
                with c.stream("GET", f"{API}/api/events/stream") as r:
                    for line in r.iter_lines():
                        if not _running:
                            return
                        if not line.startswith("data:"):
                            continue
                        try:
                            ev = json.loads(line[5:].strip() or "{}")
                        except Exception:
                            continue
                        if ev.get("kind") == "pc":
                            from core.pc import loop as pcloop
                            threading.Thread(target=pcloop.run_command, args=(ev, _say_q.put), daemon=True, name="pc-cmd").start()
                            continue
                        if ev.get("kind") != "reminder" or not ev.get("text"):
                            continue
                        key = str(ev.get("id") or ev["text"])
                        if key in seen:
                            continue
                        seen.add(key)
                        if len(seen) > 500:
                            seen.clear()
                        if _is_night() and "🚨" not in ev["text"] and "⏰" not in ev["text"] and "⏳" not in ev["text"]:
                            continue     # ночью вслух только напоминания о встречах/дедлайнах, остальное подождёт утра
                        _say_q.put(("Сэр, " if not ev["text"].lower().startswith(("сэр", "напомина")) else "") + ev["text"])
        except Exception as e:
            log.debug("reminder stream: %s", e)
        time.sleep(5)   # ядро перезапустилось / сеть — переподключаемся


def _speak_pending() -> None:
    """Проговорить накопившиеся напоминания (вызывается из главного цикла, когда не идёт диалог)."""
    if _say_q.empty() or STATE["mode"] not in ("idle", "off"):
        return
    prev = STATE["mode"]
    sp = _Speaker()
    sp.start()
    set_state("speaking", "напоминание")
    try:
        while not _say_q.empty():
            text = _say_q.get_nowait()
            log.info("Напоминаю вслух: %s", text[:100])
            sp.say(text)
    finally:
        sp.finish()
        set_state(prev)


def _core_alive() -> bool:
    import httpx
    try:
        with httpx.Client(timeout=3, trust_env=False, headers=API_HEADERS) as c:
            return c.get(f"{API}/api/health").status_code == 200
    except Exception:
        return False


# ------------------------------------------------------------------ главный цикл
def main() -> None:
    import sounddevice as sd
    from core.voice import stt, tts
    from core.voice.wake import WakeDetector

    print(f"  {identity.title()} — голосовой клиент. Скажите «{identity.title()}, …» или нажмите", HOTKEY)
    _start_tray()
    set_state("thinking", "загрузка моделей")

    log.info("Загружаю wake word (Vosk)…")
    try:
        wake = WakeDetector()
    except Exception as e:
        _fatal("Не удалось загрузить модель wake word (Vosk). Обычно это нет интернета при первом запуске "
               "(модель качается один раз, 45 МБ) или антивирус заблокировал data\\models. Удалите папку data\\models\\vosk-model-small-ru-0.22 и запустите снова.", e)
        return
    log.info("Скорость: whisper-%s на %s%s · пауза %.1f с · озвучка %s", stt.STT_MODEL, stt.STT_DEVICE.upper(),
             " (быстрый режим)" if stt.STT_FAST else "", SILENCE_SEC, "по предложениям (стрим)" if STREAM else "после полного ответа")
    if stt.STT_DEVICE == "cpu":
        log.info("Подсказка: распознавание на видеокарте NVIDIA в 5–10 раз быстрее — запустите gpu.bat один раз")
    log.info("Прогреваю Whisper и голос…")
    try:
        stt._load()
    except Exception as e:
        _fatal("Не удалось загрузить распознавание речи (Whisper). Первый запуск качает модель (~500 МБ) — нужен интернет. "
               "Если места мало, в config.yaml поставьте voice.stt.model: base", e)
        return
    try:
        tts._load_silero()
    except Exception as e:
        log.warning("Silero не загрузился (%s) — озвучка через Microsoft, нужен интернет", e)

    if not _core_alive():
        log.warning("Ядро %s не отвечает — запустите start.bat. Слушать всё равно буду.", API)
    threading.Thread(target=_reminder_listener, daemon=True, name="reminders").start()
    if SPEAK_REMINDERS:
        log.info("Напоминания ядра (встречи, задачи) буду произносить вслух")
    from core.pc import loop as pcloop
    pcloop.setup(API, DATA_DIR, GAMES_EXTRA)
    threading.Thread(target=pcloop.heartbeat_loop, args=(lambda: STATE, lambda: _running), daemon=True, name="heartbeat").start()
    log.info("Управление ПК включено: «открой ютуб», «найди файл …», «что на экране», «пауза», «статус костюма». Игровой режим — автоматически по запущенным играм.")
    stop_watcher = _StopWatcher(wake)
    last_morning_check = 0.0

    # горячая клавиша
    try:
        import keyboard
        keyboard.add_hotkey(HOTKEY, lambda: _wake_event.set())
        log.info("Горячая клавиша: %s", HOTKEY)
    except Exception as e:
        log.info("Горячая клавиша недоступна (%s)", e)

    dev = MIC
    if isinstance(dev, str) and dev.isdigit():
        dev = int(dev)
    try:
        info = sd.query_devices(dev, "input") if dev is not None else sd.query_devices(kind="input")
        log.info("Микрофон: %s", info["name"])
    except Exception as e:
        log.error("Микрофон не найден: %s. Список устройств: python voice_client.py --mics", e)
        return

    # оценка фонового шума первые 1.5 с
    noise = 300.0
    tmp_dir = DATA_DIR / "voice_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    with sd.RawInputStream(samplerate=SR, blocksize=CHUNK, dtype="int16", channels=1, device=dev, callback=_mic_callback):
        set_state("idle")
        log.info("Готов. Жду «%s»…", identity.title())
        followup_until = 0.0
        noise_samples: list[float] = []
        while _running:
            if MORNING_REPORT and time.time() - last_morning_check > 5:
                last_morning_check = time.time()
                try:
                    pcloop.morning_check(_say_q.put)
                except Exception as e:
                    log.debug("morning check: %s", e)
            if not _say_q.empty() and not _wake_event.is_set():
                _speak_pending()          # напоминания говорим даже с выключенным микрофоном
                _drain_mic()
                continue
            if STATE["mode"] == "off":
                time.sleep(0.2)
                while not _audio_q.empty():
                    _audio_q.get_nowait()
                continue
            try:
                chunk = _audio_q.get(timeout=0.3)
            except queue.Empty:
                if _wake_event.is_set():
                    chunk = None
                else:
                    continue

            tail = None
            prefix = b""
            if _wake_event.is_set():
                _wake_event.clear()
                wake.reset()
                tail = ""
            elif chunk is not None:
                pcm = np.frombuffer(chunk, dtype=np.int16)
                if len(noise_samples) < 15:
                    noise_samples.append(_rms(pcm))
                    if len(noise_samples) == 15:
                        noise = max(60.0, float(np.median(noise_samples)))
                        log.info("Фоновый шум: %.0f%s", noise, " (тихо — если ассистент вас не слышит, поднимите уровень микрофона в Windows)" if noise < 80 else "")
                if time.time() < followup_until and _rms(pcm) > max(noise * 2.5, 500.0):
                    tail = ""          # продолжение разговора без «ассистент»
                    prefix = chunk
                else:
                    tail = wake.feed(chunk)
                    prefix = b""
            if tail is None:
                continue

            # --- услышали «ассистент» ---
            followup_until = 0.0
            set_state("listening")
            _beep(880, 90)
            pcm = _record_command(prefix, noise)
            if (pcm is None or len(pcm) < SR * 0.4) and not tail:
                set_state("idle")
                continue
            set_state("thinking")
            text = ""
            t0 = time.time()
            if pcm is not None and len(pcm) >= SR * 0.4:
                text = stt.transcribe_pcm(pcm)
                log.info("Услышал (%.1f с): %r", time.time() - t0, text)
            if not text and tail:
                text = tail
            if not text:
                set_state("idle")
                _beep(440, 120)
                continue

            from core.brain.agent import normalize_spoken
            text = normalize_spoken(text)
            if _STOP_RX.match(text):
                wake.reset(); set_state("idle"); continue          # «ассистент, стоп» в тишине — просто молчим
            global _convo_mode
            if _CONVO_ON_RX.match(text) or _CONVO_OFF_RX.match(text):
                _convo_mode = bool(_CONVO_ON_RX.match(text))
                sp = _Speaker(); sp.start()
                sp.say("Слушаю вас, сэр. Говорите без обращения — я на связи." if _convo_mode else "Как скажете. Позовёте — откликнусь.")
                sp.finish(); wake.reset()
                followup_until = time.time() + CONVO_MODE_SEC if _convo_mode else 0.0
                set_state("idle", "режим беседы" if _convo_mode else ""); continue
            if _DICTATE_RX.match(text):
                # «ассистент, запиши мысль» → говорим до минуты, пауза 2.5 с завершает
                sp = _Speaker(); sp.start(); sp.say("Слушаю, диктуйте."); sp.finish()
                set_state("listening", "диктовка")
                _beep(660, 80)
                pcm = _record_command(b"", noise, silence_sec=2.5, max_sec=60.0)
                set_state("thinking", "распознаю диктовку")
                note = stt.transcribe_pcm(pcm) if pcm is not None and len(pcm) >= SR * 0.4 else ""
                if not note:
                    sp = _Speaker(); sp.start(); sp.say("Ничего не расслышал, сэр."); sp.finish()
                    set_state("idle"); continue
                text = "мысль: " + note
                log.info("Диктовка: %r", note[:120])
            t_stt = time.time() - t0 if pcm is not None and len(pcm) >= SR * 0.4 else 0.0
            t1 = time.time()
            speaker = _Speaker()
            speaker.start()
            stop_watcher.start()
            set_state("speaking")
            # заглушка «Секунду…», если мозг молчит дольше FILLER_SEC (только для не-мгновенных ответов)
            filler_timer = None
            if FILLER_SEC > 0:
                import random as _rnd
                filler_timer = threading.Timer(FILLER_SEC, lambda: (speaker.first_audio_at is None and not speaker.spoke) and speaker.say_now(_rnd.choice(_FILLERS)))
                filler_timer.daemon = True
                filler_timer.start()
            try:
                if STREAM:
                    answer, first_at = _ask_core_stream(text, speaker.say)
                else:
                    answer, first_at = _ask_core(text), None
                    speaker.say(answer)
                if filler_timer:
                    filler_timer.cancel()
                t_brain = time.time() - t1
                set_state("speaking", answer[:40])
            finally:
                if filler_timer:
                    filler_timer.cancel()
                speaker.finish()
                stop_watcher.stop()
                if _interrupt.is_set():
                    log.info("Ответ прерван по команде «стоп»")
                    _interrupt.clear()
            log.info("Ответ: %s", answer[:120].replace("\n", " "))
            log.info("⏱ распознавание %.1f с · мозг %.1f с (первое слово через %.1f с, ответил: %s) · голос зазвучал через %.1f с после команды",
                     t_stt, t_brain, (first_at - t1) if first_at else t_brain, LAST_VIA or "?",
                     (speaker.first_audio_at - t0) if speaker.first_audio_at else 0.0)
            if t_brain > 8 and LAST_VIA == "локальная модель":
                log.info("   → медленно: локальная модель. Смотрите окно start.bat: если «в видеокарте только N%» — поставьте qwen2.5:3b (см. README, «Быстрый режим»)")
            elif t_brain > 8 and LAST_VIA == "облако":
                log.info("   → медленно: облако. В окне start.bat смотрите строки ОБЛАКО/маршрут — возможно, Groq не отвечает напрямую и перебираются маршруты")
            wake.reset()
            asked = re.sub(r"[\s⚡🧠☁️]+$", "", answer).endswith("?")
            window = CONVO_MODE_SEC if _convo_mode else max(CONVO_SEC, FOLLOWUP_SEC if asked else 0.0)
            followup_until = time.time() + window if window > 0 else 0.0
            set_state("idle", "режим беседы" if _convo_mode else "")


def self_check() -> int:
    """Проверка всего, что нужно голосу, с понятными подсказками. 0 — всё ок, 1 — что-то FAIL."""
    ok = True

    def line(name, good, hint=""):
        nonlocal ok
        print(f"        {'ok  ' if good else 'FAIL'}  {name}" + ("" if good or not hint else f"\n              → {hint}"))
        ok = ok and good

    print(f"        python {sys.version.split()[0]}")
    for mod, hint in (("vosk", "pip: vosk"), ("sounddevice", "pip: sounddevice"), ("faster_whisper", "pip: faster-whisper"),
                      ("torch", "pip: torch (голос Silero; без него будет Microsoft-голос через интернет)"),
                      ("pystray", "иконка в трее (необязательно)"), ("keyboard", "горячая клавиша (необязательно)"),
                      ("httpx", "pip: httpx")):
        try:
            __import__(mod)
            line(f"пакет {mod}", True)
        except Exception as e:
            optional = mod in ("pystray", "keyboard", "torch")
            print(f"        {'warn' if optional else 'FAIL'}  пакет {mod}: {type(e).__name__}: {str(e)[:80]}\n              → {hint}")
            ok = ok and optional
    # микрофон
    try:
        import sounddevice as sd
        dev = MIC
        if isinstance(dev, str) and dev.isdigit():
            dev = int(dev)
        info = sd.query_devices(dev, "input") if dev is not None else sd.query_devices(kind="input")
        line(f"микрофон: {info['name']}", True)
    except Exception as e:
        line("микрофон", False, f"{e}. Проверьте, что микрофон подключён и разрешён в Windows: Параметры → Конфиденциальность → Микрофон. "
                                 "Список устройств: voice.bat --mics")
    # видеокарта для whisper
    try:
        from core.voice import stt as _stt
        g = _stt.cuda_ok()
        print(f"        {'ok  ' if g else 'info'}  whisper на {'видеокарте (cuda)' if _stt.STT_DEVICE != 'cpu' and g else 'процессоре'}"
              + ("" if g or _stt.STT_DEVICE == "cpu" else "  → в config.yaml стоит cuda, но GPU не виден: запустите gpu.bat или верните device: cpu")
              + ("  → быстрее: gpu.bat" if not g else ""))
    except Exception:
        pass
    # ядро
    alive = _core_alive()
    print(f"        {'ok  ' if alive else 'warn'}  ядро {API}" + ("" if alive else "  → не отвечает: запустите start.bat (слушать всё равно буду)"))
    # модели (только наличие/место; скачивание — при старте)
    try:
        from core.voice.wake import MODEL_DIR
        have = (MODEL_DIR / "am").exists()
        print(f"        {'ok  ' if have else 'info'}  модель wake word Vosk" + ("" if have else "  → скачается при первом запуске (45 МБ)"))
    except Exception as e:
        line("модуль wake word", False, str(e))
    print()
    return 0 if ok else 1


if __name__ == "__main__":
    if "--deps" in sys.argv:
        missing = []
        for _m in ("vosk", "sounddevice", "pystray", "keyboard", "numpy", "faster_whisper", "httpx"):
            try:
                __import__(_m)
            except Exception:
                missing.append(_m)
        print("missing: " + ", ".join(missing) if missing else "all voice packages present")
        sys.exit(1 if missing else 0)
    if "--gpu-on" in sys.argv:
        # gpu.bat: проверить, что ctranslate2 видит видеокарту, и включить voice.stt.device: cuda в config.yaml
        from core.voice import stt as _stt
        if _stt.cuda_ok():
            from core.config import write_settings
            write_settings({"voice.stt.device": "cuda"})
            print("GPU OK: whisper will run on CUDA (voice.stt.device: cuda)")
            sys.exit(0)
        print("GPU not visible to ctranslate2")
        sys.exit(1)
    if "--mics" in sys.argv:
        import sounddevice as sd
        print(sd.query_devices())
        sys.exit(0)
    if "--check" in sys.argv:
        try:
            sys.exit(self_check())
        except Exception as e:
            _fatal("Самопроверка упала", e)
            sys.exit(1)
    try:
        main()
    except KeyboardInterrupt:
        pass
    except SystemExit:
        raise
    except Exception as e:
        _fatal("Голосовой клиент упал", e)
        sys.exit(1)
