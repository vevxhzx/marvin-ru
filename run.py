"""Точка входа: поднимает API-сервер, Telegram-бота и планировщик в одном процессе.

    python run.py            — всё вместе
    python run.py --no-tg    — без Telegram (например, если токена ещё нет)
"""
from __future__ import annotations

import asyncio
import os
import logging
import sys
from pathlib import Path

# запасные чистые python-пакеты (socksio для socks-прокси) — работают даже без pip
_vendor = Path(__file__).resolve().parent / "vendor"
if _vendor.exists() and str(_vendor) not in sys.path:
    sys.path.append(str(_vendor))

import uvicorn

from core.config import cfg
from core.db import init_db
from core.services import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger("jarvis")

BANNER = r"""
     ██╗   █████╗   ██████╗  ██╗   ██╗ ██╗ ███████╗
     ██║  ██╔══██╗  ██╔══██╗ ██║   ██║ ██║ ██╔════╝
     ██║  ███████║  ██████╔╝ ██║   ██║ ██║ ███████╗
██   ██║  ██╔══██║  ██╔══██╗ ╚██╗ ██╔╝ ██║ ╚════██║
╚█████╔╝  ██║  ██║  ██║  ██║  ╚████╔╝  ██║ ███████║
 ╚════╝   ╚═╝  ╚═╝  ╚═╝  ╚═╝   ╚═══╝   ╚═╝ ╚══════╝
"""


def _instance_label() -> str:
    """Чем эта копия отличается от «главной»: имя папки + порт. Вторая копия («jarvis-mama», 8766) — видно в заголовке окна,
    в первой строке лога и в диспетчере задач, иначе два одинаковых окна «J.A.R.V.I.S.» не различить."""
    from core.config import ROOT
    port = int(getattr(getattr(cfg, "server", None), "port", 8765) or 8765)
    name = ROOT.name
    if name.lower().endswith("-mama") or "mama" in name.lower():
        return f"для мамы · {name} · :{port}"
    return f"{name} · :{port}" if port != 8765 else ""


def _set_console_title(label: str) -> None:
    title = "J.A.R.V.I.S." + (f" — {label}" if label else "")
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(title)
        else:
            sys.stdout.write(f"\033]0;{title}\007"); sys.stdout.flush()
    except Exception:
        pass


async def main(with_tg: bool) -> None:
    print(BANNER)
    init_db()
    from core import VERSION
    label = _instance_label()
    _set_console_title(label)
    log.info("J.A.R.V.I.S. v%s%s · база готова: data/jarvis.db", VERSION, f" · копия {label}" if label else "")

    from core.brain import llm
    if await llm.ollama_available():
        log.info("Мозг: Ollama онлайн (%s), режим %s — прогреваю модель (keep_alive %s)", llm.OLLAMA_MODEL, llm.MODE, llm.OLLAMA_KEEP_ALIVE)
        asyncio.get_event_loop().create_task(llm.warm_ollama())
    elif llm.MODE == "cloud" and llm.cloud_enabled():
        log.info("Мозг: только облако (%s) — инструменты, заметки и память через него; Ollama не нужна.", llm.cloud_title())
    else:
        log.warning("Мозг: Ollama не отвечает — пока работают только команды-шаблоны.")
        log.warning("Диагностика: %s", await llm.ollama_diagnose())
        log.warning("Как только Ollama поднимется, Джарвис подхватит её сам, перезапуск не нужен.")
    try:
        from core.voice import stt, tts
        if os.getenv("JARVIS_NO_VOICE_WARMUP"):
            log.info("Голос: прогрев моделей отключён (JARVIS_NO_VOICE_WARMUP)")
        elif stt.available():
            log.info("Голос: распознавание whisper-%s, озвучка %s — прогреваю в фоне (первый раз качает модели)", stt.STT_MODEL, tts.ENGINE)
            stt.warmup(); tts.warmup()
        else:
            log.info("Голос: пакеты не установлены (update.bat) — голосовые в Telegram пока текстом")
    except Exception as e:  # pragma: no cover
        log.warning("Голос не инициализирован: %s", e)
    if llm.cloud_enabled():
        log.info("Облако: %s (анонимайзер %s)", llm.cloud_title(), "вкл" if cfg.brain.gemini.anonymize else "выкл")

    bot = None
    notify = None
    if with_tg:
        token = str(cfg.telegram.token or "")
        if ":" not in token or "ВСТАВЬ" in token:
            log.warning("Telegram-токен не заполнен в config.yaml — бот не запущен. API работает.")
            with_tg = False
    if with_tg:
        from core.telegram import bot as tgbot
        bot, dp = await tgbot.build()
        # самопроверка: текстовый обработчик должен быть привязан (v0.6.0 и старше — сломан, «печатает» и молчит)
        _hs = {h.callback.__name__ for h in tgbot.router.message.handlers}
        if "any_text" in _hs:
            log.info("Telegram: обработчики в порядке (%d шт., текст → any_text)", len(_hs))
        else:
            log.error("Telegram: ТЕКСТОВЫЙ ОБРАБОТЧИК НЕ ПРИВЯЗАН — это старый core/telegram/bot.py. Скопируйте папку core/ заново!")

        async def notify(text: str, buttons=None) -> None:  # noqa: F811
            await tgbot.notify(bot, text, buttons)

        async def _notify_photo(path: str, caption: str = "") -> None:
            await tgbot.notify_photo(bot, path, caption)
        notify.photo = _notify_photo  # type: ignore[attr-defined]

        async def _notify_voice(text: str, buttons=None) -> bool:
            return await tgbot.notify_voice(bot, text, buttons)
        notify.voice = _notify_voice  # type: ignore[attr-defined]

    async def _null_notify(text: str, buttons=None) -> None:
        log.info("[notify] %s", text)

    from core.brain import agent as _agent
    _agent.notify = notify   # результаты с ПК (план уборки, найденные файлы) для команд из Telegram
    sch = scheduler.build(notify or _null_notify)
    sch.start()
    # состояние присутствия: восстанавливаем последний снимок (перезапуск ≠ первый запуск), событие restart
    from core.services import state as _state
    _st = _state.restore()
    if not _st["first_run"] and _st["gap_min"] is not None:
        log.info("Перезапуск: пауза %d мин (до этого: %s)", _st["gap_min"], _st["was"])

    # порт занят = Джарвис уже запущен (второе окно / автозагрузка). Второй экземпляр отберёт у первого Telegram.
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("0.0.0.0", int(cfg.server.port)))
    except OSError:
        log.error("Порт %s уже занят — Джарвис УЖЕ ЗАПУЩЕН (другое окно или автозагрузка в трее/фоне).", cfg.server.port)
        log.error("Второе окно не нужно: закройте это. Если хотите перезапустить — закройте ВСЕ окна Джарвиса и запустите start.bat снова.")
        log.error("Найти скрытый экземпляр: Диспетчер задач → «python» → снять задачу.")
        sys.exit(3)
    finally:
        probe.close()

    from core.api.app import app
    config = uvicorn.Config(app, host=cfg.server.host, port=int(cfg.server.port), log_level="warning")
    server = uvicorn.Server(config)
    from core.config import ROOT
    if (ROOT / "web" / "site" / "index.html").exists() or (ROOT / "web" / "dist" / "index.html").exists():
        log.info("Сайт: http://localhost:%s  (открой в браузере)", cfg.server.port)
    else:
        log.warning("Папка web/site не найдена (%s) — показываю пробную страницу. "
                    "Скачай папку web/site из проекта и положи в web\\", ROOT / "web" / "site")
    if with_tg:
        log.info("Подключаюсь к Telegram (до 20 сек)...")

    app.state.tg_running = bool(with_tg)
    app.state.errors = []
    tasks = [asyncio.create_task(server.serve())]
    if with_tg:
        from core.brain.persona import say

        async def greet():
            await notify(say("greet"))
            log.info("Telegram-бот онлайн, отвечает только ID %s", cfg.telegram.owner_id)

        tasks.append(asyncio.create_task(tgbot.run_polling_forever(bot, dp, on_connected=greet)))
    try:
        await asyncio.gather(*tasks)
    finally:
        try:
            _state.shutdown()
        except Exception as e:  # pragma: no cover
            log.debug("state shutdown: %s", e)
        sch.shutdown(wait=False)
        if bot:
            await bot.session.close()


if __name__ == "__main__":
    loop_factory = None
    if sys.platform == "win32":
        import os
        os.system("chcp 65001 >nul")
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        loop_factory = asyncio.SelectorEventLoop  # стабильнее для сетевых библиотек на Windows
    try:
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            runner.run(main(with_tg="--no-tg" not in sys.argv))
    except KeyboardInterrupt:
        print("\nДжарвис выключен. До связи, сэр.")
