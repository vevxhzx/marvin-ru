"""ПК-клиент, зрение, превью облака и голос (ФАЗА 7, шаг 7.5b).

Перенос механический из core/api/app.py: логику, пути, методы, тела функций
и коды ответов не менял — только @app.x -> @router.x и уровень точек у локальных
импортов в телах роутов (.. -> ..., .auth -> ..auth). Докстринги и комментарии
перенесены дословно.
"""
from __future__ import annotations

import json as _json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from ...brain import agent
from ...services import brain_notes, pc
from .._shared import broadcast, log
from ..schemas import (CloudPreviewIn, PcAck, PcClip, PcLaunch, PcPing, PcResult,
                       VisionIn, VoicePick)

router = APIRouter()


def register(app) -> None:
    app.include_router(router)


PC_ORGANIZE_LOG: list[dict] = []
PC_ORGANIZE_PREVIEW: dict | None = None


# ---------------- ПК-клиент (voice.bat): пульс, состояние, результаты команд, зрение ----------------
@router.post("/api/pc/ping")
def pc_ping(p: PcPing):
    """Голосовой клиент раз в 20 с сообщает, что жив и что делает (idle/listening/thinking/speaking/off).
    Тот же пульс кормит экранное время (screen) и состояние присутствия (state): сел/отошёл/что открыто/долго ли."""
    from ...services import pc, state
    was = pc.STATE.get("mode")
    pc.seen({"mode": p.mode, "text": p.text})
    if was != p.mode:
        broadcast("pc_state", {"mode": p.mode, "text": p.text})
    try:
        if p.screen:
            from ...services import screen
            screen.record(p.app, p.title, p.idle_sec)
            name, sub, cat = screen.classify(p.app, p.title, screen._GAMES)
            state.tick(name, sub, cat, p.idle_sec)
        else:
            state.tick()
    except Exception as e:  # pragma: no cover
        log.warning("pc ping state: %s", e)
    # Возвращаем клиенту актуальное значение «экранное время»: включение настройки применяется на лету (в течение пульса),
    # а не после перезапуска voice.bat — раньше это была причина «включено, но данных нет».
    want_screen = False
    try:
        from ...services import screen
        want_screen = screen.enabled()
    except Exception:  # pragma: no cover
        pass
    return {"ok": True, "screen": want_screen}


@router.get("/api/screen")
def screen_report(day: str | None = None, days: int = 1):
    """Экранное время: сводка за день (карточка на «Сегодня») или за несколько дней."""
    from ...services import screen
    d = datetime.fromisoformat(day) if day else None
    n = max(1, min(days, 31))
    r = screen.summary(d, n)
    return {**r, "first": r["first"].isoformat() if r["first"] else None, "last": r["last"].isoformat() if r["last"] else None,
            "sessions": [[a.isoformat(), b.isoformat()] for a, b in r["sessions"]], "idle_min_setting": screen.idle_min(),
            "pc_alive": pc.alive(), "projects": screen.project_sessions(d, n), "text": screen.text(d, n)}


@router.post("/api/pc/ack")
def pc_ack(a: PcAck):
    """ПК подтверждает: команду из SSE получил и выполняет (чтобы «Смотрю, что лежит…» не оставалось без продолжения)."""
    from ...services import pc
    pc.seen(); pc.ack(a.action)
    return {"ok": True}


@router.get("/api/pc/state")
def pc_state():
    from ...services import pc
    return {"alive": pc.alive(), "seen": pc.last_seen_iso(), "age_sec": pc.age_sec(), **pc.STATE}


@router.post("/api/pc/launch")
def pc_launch(p: PcLaunch, request: Request):
    """Открыть voice.bat из настроек. Только с самого компьютера — запуск процессов с телефона запрещён."""
    from ..auth import is_local as _is_local
    if not _is_local(request):
        raise HTTPException(403, "Запуск голосового клиента доступен только с самого компьютера")
    from ...pc import launcher
    return launcher.launch(restart=bool(p.restart))


@router.get("/api/pc/organize/log")
def pc_organize_log():
    """Последние операции организации файлов, включая список перемещений."""
    return list(reversed(PC_ORGANIZE_LOG))


@router.get("/api/pc/organize/preview")
def pc_organize_preview():
    """Последний план, присланный Windows-клиентом, чтобы сайт не зависел от чата."""
    return PC_ORGANIZE_PREVIEW or {"status": "empty"}


@router.post("/api/pc/result")
async def pc_result(r: PcResult):
    """Результат команды с ПК (список найденных файлов, статус железа, план уборки) — в общий чат, чтобы было видно
    на сайте/в TG. План уборки ждёт «да» тем же механизмом подтверждения, что крупные суммы и выключение ПК."""
    from ...services import pc
    pc.seen()
    global PC_ORGANIZE_PREVIEW
    if r.kind == "organize_plan":
        PC_ORGANIZE_PREVIEW = {"status": "ready", "at": datetime.now().isoformat(timespec="seconds"), **r.extra, "text": r.text}
    if r.kind in ("tidy_plan", "organize_plan") and r.extra.get("plan_id") and r.extra.get("total"):
        key = "tidy" if r.kind == "tidy_plan" else "organize"
        agent._pending_set(r.channel, "confirm|" + _json.dumps({key: r.extra["plan_id"]}))
    agent._log_chat("assistant", r.text, r.channel)
    if r.kind in ("organize_done", "organize_undo"):
        PC_ORGANIZE_LOG.append({"at": datetime.now().isoformat(timespec="seconds"), "kind": r.kind, "text": r.text, "log": r.extra.get("log", {})})
        del PC_ORGANIZE_LOG[:-100]
    broadcast("chat", {"channel": r.channel, "actions": [f"pc_{r.kind}"]})
    if (r.channel.startswith("tg") or r.channel == "system") and agent.notify:   # system — ночная уборка: отчёт утром в Telegram
        try:
            await agent.notify(r.text)
        except Exception as e:  # pragma: no cover
            log.warning("pc_result → telegram: %s", e)
    return {"ok": True}


@router.post("/api/pc/clipboard")
async def pc_clipboard(c: PcClip):
    """«Запомни это»: содержимое буфера обмена → заметка или ссылка в Мозг."""
    txt = (c.text or "").strip()
    if not txt:
        return {"ok": False, "text": "В буфере обмена пусто, сэр."}
    urls = brain_notes.extract_urls(txt)
    if urls and len(txt) < 300:
        l = await brain_notes.add_link(urls[0], txt.replace(urls[0], "").strip() or None, source=c.channel)
        msg = f"Ссылка сохранена: {l.title or l.domain}."
        acts = ["add_link"]
    else:
        brain_notes.add_note(txt[:4000], source=c.channel)
        msg = f"Записал в Мозг: «{txt[:60]}{'…' if len(txt) > 60 else ''}»."
        acts = ["add_note"]
    agent._log_chat("assistant", msg, c.channel)
    broadcast("chat", {"channel": c.channel, "actions": acts})
    return {"ok": True, "text": msg}


@router.post("/api/vision/ask")
async def vision_ask(v: VisionIn):
    """Скриншот экрана с ПК → описание/перевод. Экран — приватный контент (как чеки): в облако он уходит
    только если пользователь явно выбрал brain.vision.where = cloud (а не «запасным путём» в auto).
    В local и в auto с недоступной локальной моделью — в облако НЕ отправляется (ФАЗА 6)."""
    from ...brain import llm
    ans = await llm.describe_image(v.image_b64, v.question, private=True)
    if not ans:
        st = llm.vision_status()
        ans = ("Зрение сейчас недоступно, сэр. " + ("Поставьте локальную vision-модель: ollama pull qwen2.5vl:3b и vision_model в настройках мозга."
                                                    if st == "выключено" else f"({st}) — не ответило, смотрите лог."))
    agent._log_chat("user", f"[скриншот] {v.question}", v.channel)
    agent._log_chat("assistant", ans, v.channel)
    broadcast("chat", {"channel": v.channel, "actions": ["vision"]})
    return {"text": ans}


@router.post("/api/cloud/preview")
def cloud_preview(body: CloudPreviewIn):
    """ФАЗА 6: «что именно уйдёт в облако» — ТОЛЬКО ЧТЕНИЕ. Ничего не отправляет и не пишет.
    Показывает текст так, как его увидит облако: с обезличиванием (brain.gemini.anonymize), если оно включено.
    В режиме local в облако не уходит ничего — will_send=false."""
    from ...brain import llm
    from ...config import cfg
    text = (body.text or "")[:8000]
    anonymized = bool(getattr(getattr(getattr(cfg, "brain", None), "gemini", None), "anonymize", False))
    shown = llm.anonymize(text) if anonymized else text
    cloud = llm.cloud_enabled()
    return {"text": shown, "anonymized": anonymized, "cloud_enabled": cloud, "mode": llm.MODE,
            "will_send": bool(cloud and llm.MODE in ("hybrid", "cloud") and text.strip()),
            # ФАЗА 6: в режиме cloud без brain.cloud.personal_tools облако не получает личные инструменты/память
            "personal_tools": bool(llm.cloud_personal_tools()),
            "note": "Черновик. Ничего не отправлено. В режиме local данные остаются на компьютере."}


VOICES = [
    {"engine": "silero", "id": "eugene", "name": "Евгений", "kind": "мужской · спокойный, низкий (по умолчанию)"},
    {"engine": "silero", "id": "aidar", "name": "Айдар", "kind": "мужской · чуть моложе, бодрее"},
    {"engine": "silero", "id": "baya", "name": "Бая", "kind": "женский · мягкий"},
    {"engine": "silero", "id": "kseniya", "name": "Ксения", "kind": "женский · нейтральный"},
    {"engine": "silero", "id": "xenia", "name": "Ксения-2", "kind": "женский · звонче"},
    {"engine": "edge", "id": "ru-RU-DmitryNeural", "name": "Дмитрий (Microsoft)", "kind": "мужской · онлайн, самый естественный"},
    {"engine": "edge", "id": "ru-RU-SvetlanaNeural", "name": "Светлана (Microsoft)", "kind": "женский · онлайн"},
]
DEMO_TEXT = "Доброе утро, сэр. Минус семьсот рублей на такси, записал. Сегодня две встречи, первая в десять. Постарайтесь не опоздать."


@router.get("/api/voice/voices")
async def voice_list():
    from ...voice import tts
    return {"voices": VOICES, "current": {"engine": tts.ENGINE, "speaker": tts.SPEAKER, "edge_voice": tts.EDGE_VOICE, "reply": tts.REPLY_VOICE},
            "silero": tts.silero_available()}


@router.get("/api/voice/demo")
async def voice_demo(engine: str = "silero", voice: str = "eugene"):
    """Пример голоса (кэшируется в data/voice_demo)."""
    from fastapi.responses import FileResponse
    from ...config import DATA_DIR
    from ...voice import tts
    if not any(v["engine"] == engine and v["id"] == voice for v in VOICES):
        raise HTTPException(400, "unknown voice")
    out = DATA_DIR / "voice_demo" / f"{engine}_{voice}.{'wav' if engine == 'silero' else 'mp3'}"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        if engine == "silero":
            prev = tts.SPEAKER
            tts.SPEAKER = voice
            try:
                ok = await tts.speak_to_file(DEMO_TEXT, out)
            finally:
                tts.SPEAKER = prev
        else:
            import edge_tts
            try:
                await edge_tts.Communicate(tts.prepare(DEMO_TEXT), voice, rate="+5%").save(str(out))
                ok = out
            except Exception as e:
                raise HTTPException(502, f"Голоса Microsoft недоступны: {e}")
        if not ok:
            raise HTTPException(500, tts.LAST_ERROR or "не удалось озвучить")
    return FileResponse(out, media_type="audio/wav" if out.suffix == ".wav" else "audio/mpeg")


@router.post("/api/voice/pick")
async def voice_pick(body: VoicePick):
    """Выбрать голос: применяется сразу и пишется в config.yaml."""
    from ...config import write_settings
    from ...voice import tts
    if not any(v["engine"] == body.engine and v["id"] == body.voice for v in VOICES):
        raise HTTPException(400, "unknown voice")
    tts.ENGINE = body.engine
    changes = {"voice.tts.engine": body.engine}
    if body.engine == "silero":
        tts.SPEAKER = body.voice
        changes["voice.tts.speaker"] = body.voice
    else:
        tts.EDGE_VOICE = body.voice
        changes["voice.tts.edge_voice"] = body.voice
    write_settings(changes)
    return {"ok": True, "engine": tts.ENGINE, "speaker": tts.SPEAKER, "edge_voice": tts.EDGE_VOICE}
