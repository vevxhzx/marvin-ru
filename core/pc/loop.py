"""Фоновые задачи ПК-клиента (voice_client.py): пульс в ядро, игровой режим по процессам,
выполнение ПК-команд из ядра («открой ютуб», «что на экране»…), утренний доклад при первом пробуждении.
"""
from __future__ import annotations

import base64
import logging
import time
from datetime import datetime
from pathlib import Path

from . import actions

log = logging.getLogger("assistant.pc")

API = ""
DATA_DIR = Path(".")
GAMES: set[str] = set()
GAME_DEFAULT = {"cs2.exe", "dota2.exe", "valorant.exe", "valorant-win64-shipping.exe", "gta5.exe", "gta5_enhanced.exe", "rdr2.exe", "cyberpunk2077.exe",
                "eldenring.exe", "witcher3.exe", "r5apex.exe", "fortniteclient-win64-shipping.exe", "overwatch.exe", "leagueoflegends.exe",
                "league of legends.exe", "rust.exe", "tarkov.exe", "escapefromtarkov.exe", "pubg.exe", "tslgame.exe", "warthunder.exe", "aces.exe",
                "wot.exe", "worldoftanks.exe", "baldursgate3.exe", "bg3.exe", "bg3_dx11.exe", "helldivers2.exe", "starfield.exe", "hogwartslegacy.exe",
                "minecraft.exe", "javaw.exe", "roblox.exe", "robloxplayerbeta.exe", "destiny2.exe", "deadlock.exe", "marvel-win64-shipping.exe",
                "palworld-win64-shipping.exe", "stalker2-win64-shipping.exe", "spacemarine2.exe", "kingdomcome.exe", "monsterhunterwilds.exe",
                # тяжёлые рабочие программы, которым нужна вся видеокарта (монтаж/графика) — тоже выгружаем модель
                "afterfx.exe", "adobe premiere pro.exe", "premiere pro.exe", "adobe media encoder.exe", "davinci resolve.exe", "resolve.exe",
                "blender.exe", "cinema 4d.exe", "unrealeditor.exe", "unity.exe"}
_game_on = False
_game_seen_at = 0.0


def setup(api: str, data_dir: Path, games: list[str] | None = None) -> None:
    global API, DATA_DIR, GAMES
    API, DATA_DIR = api, data_dir
    GAMES = {g.lower() for g in (games or [])} | GAME_DEFAULT


def _headers() -> dict:
    try:
        from ..config import DATA_DIR
        tok = (DATA_DIR / "api_token").read_text(encoding="utf-8").strip()
        return {"X-Auth-Token": tok} if tok else {}
    except Exception:
        return {}


def _post(path: str, body: dict, timeout: float = 20):
    import httpx
    with httpx.Client(timeout=timeout, trust_env=False, headers=_headers()) as c:
        return c.post(f"{API}{path}", json=body)


# ---------------------------------------------------------------- пульс + игровой режим
def heartbeat_loop(get_state, running) -> None:
    """Каждые 20 с: POST /api/pc/ping (состояние клиента) и проверка игр."""
    global _game_on, _game_seen_at
    while running():
        try:
            st = get_state()
            _post("/api/pc/ping", {"mode": st.get("mode", "idle"), "text": st.get("text", "")}, timeout=5)
        except Exception as e:
            log.debug("ping: %s", e)
        try:
            procs = actions.running_processes()
            playing = bool(procs & GAMES)
            if playing:
                _game_seen_at = time.time()
                if not _game_on:
                    _post("/api/game", {"on": True}, timeout=10)
                    _game_on = True
                    log.info("Игровой режим включён автоматически: %s", ", ".join(sorted(procs & GAMES))[:80])
            elif _game_on and time.time() - _game_seen_at > 120:
                _post("/api/game", {"on": False}, timeout=10)
                _game_on = False
                log.info("Игра закрыта — игровой режим выключен, мозг снова в видеокарте")
        except Exception as e:
            log.debug("game watch: %s", e)
        for _ in range(20):
            if not running():
                return
            time.sleep(1)


# ---------------------------------------------------------------- утренний доклад при первом пробуждении
_last_idle = 0.0
_morning_done: str | None = None


def morning_check(say) -> None:
    """Вызывать раз в несколько секунд. Если ПК простоял 6+ ч и вы вернулись утром (6–12) — доклад вслух."""
    global _last_idle, _morning_done
    idle = actions.idle_seconds()
    woke = _last_idle > 6 * 3600 and idle < 5
    _last_idle = idle
    if not woke:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    if _morning_done == today or not (6 <= datetime.now().hour < 12):
        return
    _morning_done = today
    try:
        import httpx
        with httpx.Client(timeout=15, trust_env=False, headers=_headers()) as c:
            d = c.get(f"{API}/api/dashboard").json()
        txt = (d.get("digest") or "").strip()
    except Exception as e:
        log.debug("morning: %s", e)
        return
    if txt:
        say("Доброе утро, сэр. " + txt)


# ---------------------------------------------------------------- команды от ядра
def run_command(ev: dict, say) -> None:
    """Выполнить ПК-команду из SSE (kind="pc"). say(text) — озвучить результат."""
    action, arg, extra, channel = ev.get("action"), ev.get("arg", ""), ev.get("extra") or {}, ev.get("channel", "voice")
    log.info("ПК-команда: %s %r", action, arg[:60] if isinstance(arg, str) else arg)
    try:
        if action == "open_url":
            msg = actions.open_url(arg, API)
        elif action == "open_app":
            msg = actions.open_app(arg)
        elif action == "open_path":
            msg = actions.open_path(arg)
        elif action == "media":
            msg = actions.media(arg)
        elif action == "power":
            msg = actions.power(arg)
        elif action == "find":
            msg, paths = actions.find_and_report(arg)
            if paths:
                _post("/api/pc/result", {"text": "📁 Нашёл на компьютере:\n" + "\n".join(f"• {p}" for p in paths), "channel": channel, "kind": "find"}, timeout=10)
        elif action == "status":
            msg = actions.system_status()
            if channel == "voice":
                _post("/api/pc/result", {"text": "🖥 " + msg, "channel": channel, "kind": "status"}, timeout=10)
        elif action == "clipboard":
            txt = actions.clipboard_text()
            r = _post("/api/pc/clipboard", {"text": txt, "channel": channel}, timeout=60)
            msg = r.json().get("text", "Готово.")
        elif action == "screen":
            path = DATA_DIR / "tmp" / "screen.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not actions.screenshot(path):
                msg = "Не смог сделать скриншот, сэр. Нужен пакет Pillow — запустите update.bat."
            else:
                b64 = base64.b64encode(path.read_bytes()).decode()
                r = _post("/api/vision/ask", {"image_b64": b64, "question": arg or "Что на экране?", "private": bool(extra.get("private")), "channel": channel}, timeout=180)
                msg = r.json().get("text", "Ничего не разглядел.")
                try:
                    path.unlink()
                except OSError:
                    pass
        else:
            msg = ""
    except Exception as e:
        log.warning("ПК-команда %s не удалась: %s", action, e)
        msg = f"Не получилось: {str(e)[:80]}"
    if msg and channel == "voice":
        say(msg)
    elif msg:
        try:
            _post("/api/pc/result", {"text": msg, "channel": channel, "kind": "result"}, timeout=10)
        except Exception:
            pass
