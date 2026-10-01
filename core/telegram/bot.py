"""Telegram-бот. Отвечает только владельцу."""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, BotCommand, Message

from ..brain import agent
from ..brain.persona import localize, say
from ..config import cfg
from ..tools import registry

log = logging.getLogger("jarvis.tg")
router = Router()
OWNER_ID = int(cfg.telegram.owner_id)
from ..config import DATA_DIR
VOICE_DIR = DATA_DIR / "voice_tmp"

# Незавершённые голосовые: расшифровка, которую ждём подтвердить («Верно»). И защита от повторной доставки апдейта.
_VOICE_PENDING: dict[int, str] = {}
_VOICE_SEEN: dict[int, float] = {}


def _once(m: Message) -> bool:
    """True — обрабатываем впервые. Telegram иногда доставляет апдейт дважды (после рестарта/сети) —
    во второй раз молчим, чтобы не выполнить команду и не списать деньги дважды."""
    now = time.time()
    if m.message_id in _VOICE_SEEN and now - _VOICE_SEEN[m.message_id] < 180:
        return False
    _VOICE_SEEN[m.message_id] = now
    for k in [k for k, v in _VOICE_SEEN.items() if now - v > 600]:
        _VOICE_SEEN.pop(k, None)
    return True


def _voice_kb():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Верно", callback_data="vc:ok"),
        InlineKeyboardButton(text="🔁 Повторить", callback_data="vc:again"),
        InlineKeyboardButton(text="✏️ Исправить", callback_data="vc:fix"),
    ]])

# Нажатые кнопки напоминаний: повторный клик не должен откладывать/закрывать дважды.
_CB_DONE: dict[tuple, float] = {}


def _evening() -> datetime:
    """Куда отложить «вечером»: сегодня 19:00, а если уже позже — завтра 19:00."""
    from datetime import timedelta
    e = datetime.now().replace(hour=19, minute=0, second=0, microsecond=0)
    if e <= datetime.now():
        e += timedelta(days=1)
    return e


def _mine(m: Message) -> bool:
    return bool(m.from_user and m.from_user.id == OWNER_ID)


def _is_forwarded(m: Message) -> bool:
    """Пересланное сообщение (aiogram 3 forward_origin + старые поля). Такой текст — не команда владельца."""
    return bool(getattr(m, "forward_origin", None) or getattr(m, "forward_from", None)
                or getattr(m, "forward_from_chat", None) or getattr(m, "forward_sender_name", None)
                or getattr(m, "forward_date", None))


def _channel_for(m: Message, base: str = "tg") -> str:
    """Канал обработки: пересланные сообщения помечаем суффиксом -fwd, чтобы они не управляли ПК (ФАЗА 6)."""
    return f"{base}-fwd" if _is_forwarded(m) else base


@router.message(~F.from_user.id.in_({OWNER_ID}))
async def stranger(m: Message):
    log.info("Чужой пользователь %s (%s) — игнорирую", m.from_user.id if m.from_user else "?", m.from_user.username if m.from_user else "")
    # Молчим. ассистент не общается с незнакомцами.


@router.message(CommandStart())
async def start(m: Message):
    from core import VERSION
    await m.answer(say("greet") + f"\n<i>ядро v{VERSION}</i>\n\nПиши по-человечески:\n"
                   "• «потратил 700 на такси» / «зп 120 тыс»\n"
                   "• «встреча в среду в 15:00 с Ваней»\n"
                   "• «напомни завтра в 10 позвонить врачу»\n"
                   "• «задача: сдать отчёт через 3 дня» / «сделал отчёт»\n"
                   "• «долг Сберу 120к плачу 8к 25-го»\n"
                   "• «мысль: …» или просто кинь ссылку\n"
                   "• «что сегодня», «что завтра», «что на выходных», «долги», «календарь»\n"
                   "• «сколько потратил на еду за неделю», «куда ушли деньги»\n"
                   "• «заплатил Диме 2000», «перевёл 5000 на сбер», «снял 3000 наличных»\n"
                   "• «подписка яндекс плюс 399 25-го», «лимит на еду 20000»\n"
                   "• «отмени последнюю» — откатить трату\n"
                   "• /summary — итог дня · /find — поиск по Мозгу · /exp 700 такси — трата одним тапом")


_QUICK_HINT = {"расход": "700 такси", "доход": "15000 аванс", "задача": "сдать отчёт в пятницу", "встреча": "в среду в 15:00 с Димой"}
_QUICK_MAP = {"расход": "потратил {x}", "exp": "потратил {x}", "доход": "доход {x}", "inc": "доход {x}",
              "задача": "задача: {x}", "task": "задача: {x}", "встреча": "встреча {x}", "event": "встреча {x}"}
_QUICK_CANON = {"exp": "расход", "inc": "доход", "task": "задача", "event": "встреча"}


def _quick_enabled() -> bool:
    try:
        return bool(getattr(cfg.telegram, "quick", True))
    except Exception:  # pragma: no cover
        return True


@router.message(Command("расход", "exp", "доход", "inc", "задача", "task", "встреча", "event"))
async def cmd_quick(m: Message):
    """Быстрые шаблоны в один тап: /расход 700 такси, /доход 15000 аванс, /задача …, /встреча … — офлайн-правилами."""
    if not _quick_enabled():
        await m.answer("Быстрые шаблоны выключены: ⚙ Настройки → telegram → «быстрые шаблоны».")
        return
    parts = (m.text or "").split(maxsplit=1)
    cmd = parts[0].lstrip("/").split("@")[0]
    if cmd not in _QUICK_MAP:
        return
    canon = _QUICK_CANON.get(cmd, cmd)
    body = parts[1].strip() if len(parts) > 1 else ""
    if not body:
        await m.answer(f"Напишите так: /{cmd} {_QUICK_HINT[canon]}")
        return
    typing = asyncio.create_task(_keep_typing(m))
    try:
        r = await asyncio.wait_for(agent.handle(_QUICK_MAP[cmd].format(x=body), channel="tg"), timeout=HANDLE_TIMEOUT)
    finally:
        typing.cancel()
    await send_long(m, r.text or "…")
    await _maybe_send_card(m, r)


@router.message(Command("find", "найди", "поиск"))
async def cmd_find(m: Message):
    """Поиск по «второму мозгу» (заметки и ссылки) прямо из Telegram."""
    parts = (m.text or "").split(maxsplit=1)
    q = parts[1].strip() if len(parts) > 1 else ""
    if not q:
        await m.answer("Что искать? Например: /найди договор аренды")
        return
    typing = asyncio.create_task(_keep_typing(m))
    try:
        from core.services import semantic
        res = await semantic.search(q, limit=6)
    except Exception as e:
        log.warning("find failed: %s", e)
        await m.answer("Поиск не сработал, сэр. Попробуйте ещё раз.")
        return
    finally:
        typing.cancel()
    items = res.get("items") or []
    if not items:
        await m.answer("В Мозге ничего не нашёл, сэр. Либо не скидывали, либо названо иначе.")
        return
    lines = [f"🧠 В Мозге по «{q}»:"]
    for it in items[:6]:
        if it.get("kind") == "link":
            lines.append("— " + (it.get("title") or it.get("url") or "ссылка"))
            if it.get("url"):
                lines.append("  " + it["url"])
        else:
            lines.append("— " + (it.get("title") or (it.get("text") or "").strip()[:80]))
    await send_long(m, "\n".join(lines))


@router.message(Command("итог", "итоги", "summary", "evening"))
async def cmd_summary(m: Message):
    """Итог дня одной карточкой (текст сразу, картинка — если включена в настройках)."""
    from core.services import cards
    typing = asyncio.create_task(_keep_typing(m))
    try:
        data = await asyncio.to_thread(cards.evening_data)
        text = cards.evening_text(data)
    finally:
        typing.cancel()
    await send_long(m, text)
    if cards.should_send("evening"):
        try:
            from aiogram.types import FSInputFile
            path = await asyncio.to_thread(cards.evening_card, None, data)
            if path:
                await m.answer_photo(FSInputFile(str(path)))
        except Exception as e:  # pragma: no cover
            log.debug("итог card: %s", e)


@router.message(Command("today"))
async def today(m: Message):
    await _answer_md(m, registry.today_briefing())
    await _send_card(m, "today")


@router.message(Command("money"))
async def money_cmd(m: Message):
    await _answer_md(m, registry.finance_summary(30))
    await _send_card(m, "money")


@router.message(Command("tasks"))
async def tasks_cmd(m: Message):
    await _answer_md(m, registry.list_tasks())
    await _send_card(m, "tasks")


@router.message(Command("orders"))
async def orders_cmd(m: Message):
    from ..services import orders
    await _answer_md(m, orders.summary_text())
    await _send_card(m, "orders")


@router.message(Command("missed", "упускаю"))
async def missed_cmd(m: Message):
    from ..services import missed as _missed
    await _answer_md(m, _missed.missed_text())
    await _send_card(m, "missed")


@router.message(Command("pomo"))
async def pomo_cmd(m: Message):
    """/pomo — 25 мин без заказа; /pomo ролик — по заказу; /pomo stop."""
    arg = (m.text or "").split(maxsplit=1)[1].strip() if len((m.text or "").split(maxsplit=1)) > 1 else ""
    if arg.lower() in ("stop", "стоп"):
        await _answer_md(m, registry.pomodoro("stop", _channel="tg"))
        return
    await _answer_md(m, registry.pomodoro("start", query=arg or None, minutes=None, _channel="tg"),
                     reply_markup=_kb([("⏹ Стоп", "pomo:0:stop")]))


@router.message(Command("goals"))
async def goals_cmd(m: Message):
    from ..services import goals
    await _answer_md(m, goals.goals_text())
    await _send_card(m, "goals")


@router.message(Command("events"))
async def events_cmd(m: Message):
    await _answer_md(m, registry.list_events(7))
    await _send_card(m, "events")


@router.message(Command("debts"))
async def debts_cmd(m: Message):
    await _answer_md(m, registry.list_debts())
    await _send_card(m, "debts")


@router.message(Command("voice"))
async def voice_cmd(m: Message):
    """Голосовые ответы: voice (на голосовые голосом) → always (всегда) → never (никогда) по кругу."""
    from core.voice import tts
    order = ["never", "voice", "always"]   # по умолчанию только текст; /voice → голосом на голосовые → голосом на всё → снова текст
    tts.REPLY_VOICE = order[(order.index(tts.REPLY_VOICE) + 1) % 3] if tts.REPLY_VOICE in order else "never"
    from core.config import write_settings as save_settings
    try:
        save_settings({"voice.tts.reply_in_telegram": tts.REPLY_VOICE})
    except Exception as e:
        log.debug("save voice setting: %s", e)
    label = {"voice": "отвечаю голосом на голосовые", "always": "отвечаю голосом на всё", "never": "отвечаю только текстом (расшифровка + ответ одним сообщением)"}[tts.REPLY_VOICE]
    await m.answer(f"🔊 Теперь {label}, сэр. Ещё раз /voice — переключить.")


@router.message(Command("game"))
async def game_cmd(m: Message):
    from core.brain import llm
    await m.answer(await llm.set_game_mode(not llm.GAME_MODE))


@router.message(Command("app"))
async def app_cmd(m: Message):
    """Открыть сайт внутри Telegram (Mini App). Работает, когда задан telegram.webapp_url (см. funnel.bat)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    url = (getattr(cfg.telegram, "webapp_url", "") or "").strip()
    if not url.startswith("https://"):
        await m.answer("Приложение внутри Telegram ещё не подключено. На компьютере: <b>funnel.bat</b>, "
                       "затем перезапуск start.bat. Проверить: ⚙ Настройки → Интеграции → Telegram. Подробно: docs/telegram-miniapp.md")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=url))]])
    await m.answer("Сайт внутри Telegram — без VPN и переключений. Открывайте именно этой кнопкой (или ≡ слева от поля ввода): "
                   "по обычной ссылке Telegram не передаёт данные для входа.", reply_markup=kb)


@router.message(Command("diag"))
async def diag_cmd(m: Message):
    """Диагностика: кто отвечает и за сколько. Полезно, когда «печатает» и тишина."""
    import time
    from core.brain import llm
    lines = ["🔧 <b>Диагностика</b>"]
    t = time.monotonic()
    ok = await llm.ollama_available()
    lines.append(f"🧠 Ollama ({llm.OLLAMA_MODEL}): {'онлайн' if ok else 'НЕ отвечает'} · {time.monotonic() - t:.1f} с")
    llm.reload_cloud_settings()
    if llm.cloud_enabled():
        t = time.monotonic()
        try:
            res = await asyncio.wait_for(llm.cloud_check(), timeout=60)
        except asyncio.TimeoutError:
            res = {"ok": False, "detail": "не ответил за 60 с (виснет сеть до провайдера)"}
        lines.append(f"☁️ {llm.cloud_title()}: {'отвечает' if res.get('ok') else 'ОШИБКА'} · {time.monotonic() - t:.1f} с"
                     + (f"\nмодель {res.get('model')}" if res.get("ok") and res.get("model") else f"\n{res.get('detail')}"))
        # ФАЗА 6 (аудит F12): хвост ключа в диагностике убран — диагностика уходит в чат/логи, ключ там не нужен
        lines.append(f"маршрут: {llm._CLOUD_ROUTE_OK[0] if llm._CLOUD_ROUTE_OK else '—'} · "
                     f"ключ {'задан' if llm.CLOUD_KEY else 'НЕТ'} · модель {llm._cloud_model() or 'по умолчанию'}"
                     + (f" · личные данные в облаке: {'да' if llm.cloud_personal_tools() else 'нет'}" if llm.MODE == 'cloud' else ""))
    else:
        lines.append("☁️ облако выключено")
    lines.append(f"режим: {llm.MODE} · авто-облако: {'да' if llm.GEMINI_AUTO else 'нет'}")
    await m.answer("\n".join(lines))


@router.message(Command("id"))
async def id_cmd(m: Message):
    await m.answer(f"Ваш Telegram ID: <code>{m.from_user.id}</code>")


async def _keep_typing(m: Message):
    """«ассистент печатает…» пока думает локальная модель (статус живёт 5 сек, обновляем каждые 4)."""
    try:
        while True:
            await m.bot.send_chat_action(m.chat.id, ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass
    except Exception:  # pragma: no cover
        pass


import html as _html
import re as _re

_MD_RX = _re.compile(r"(\*\*|__|`{1,3}|^#{1,6}\s+)", _re.M)


def _to_html(text: str) -> str:
    """Ответы облачных моделей приходят в markdown с < > & — HTML-режим Telegram на этом падает.
    Экранируем всё, а простые **жирный** и `код` переводим в теги."""
    t = _html.escape(localize(text), quote=False)
    t = _re.sub(r"```[a-zA-Z]*\n?(.*?)```", lambda mm: f"<pre>{mm.group(1)}</pre>", t, flags=_re.S)
    t = _re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    t = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=_re.S)
    t = _re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    t = _re.sub(r"(?<!\w)_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)", r"<i>\1</i>", t)
    t = _re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", t, flags=_re.M)
    t = _re.sub(r"^[ \t]*[\*\-][ \t]+", "— ", t, flags=_re.M)
    t = _re.sub(r"^[ \t]*(\d+)[.)][ \t]+", r"\1. ", t, flags=_re.M)
    t = _re.sub(r"^[ \t]*[-*_]{3,}[ \t]*$", "", t, flags=_re.M)   # горизонтальные линии
    t = _re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def _to_html_cap(text: str, limit: int = 1000) -> str:
    """HTML для подписи к фото/голосу: Telegram режет подпись на 1000 символов, поэтому обрезаем сами —
    по строкам и с закрытием тегов, чтобы не отдать «<b>ИТОГИ ДНЯ…» без конца и не упасть."""
    t = _to_html(text)
    if len(t) <= limit:
        return t
    cut = _re.sub(r"<[^>]*$", "", t[:limit - 4])
    for tag in ("b", "i", "code", "pre"):
        if cut.count(f"<{tag}>") > cut.count(f"</{tag}>"):
            cut += f"</{tag}>"
    return cut.rstrip() + "…"


async def _send(m: Message, html_text: str, plain_text: str) -> bool:
    """Отправить одно сообщение: HTML → при ошибке разметки чистый текст; при сетевой ошибке — 3 попытки.
    Каждый сбой пишется в консоль, чтобы было видно, ПОЧЕМУ ответ не дошёл."""
    from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
    payloads = [(html_text, None), (plain_text, "plain")]
    for text, mode in payloads:
        for attempt in range(1, 4):
            try:
                if mode == "plain":
                    await m.answer(text, parse_mode=None)
                else:
                    await m.answer(text)
                log.info("→ tg: отправлено (%d симв.%s)", len(text), "" if mode is None else ", чистый текст")
                return True
            except TelegramRetryAfter as e:
                log.warning("→ tg: Telegram просит подождать %s с", e.retry_after)
                await asyncio.sleep(min(e.retry_after, 30))
            except TelegramBadRequest as e:
                log.warning("→ tg: Telegram отверг сообщение (%s) — %s", e.message, "пробую чистым текстом" if mode is None else "сдаюсь")
                break   # разметка — переходим к plain
            except TelegramNetworkError as e:
                log.warning("→ tg: сеть до Telegram (попытка %d/3): %s", attempt, e)
                await asyncio.sleep(2 * attempt)
            except Exception as e:
                log.warning("→ tg: не отправил (попытка %d/3): %s: %s", attempt, type(e).__name__, e)
                await asyncio.sleep(2 * attempt)
    _record_error(f"tg: не смог отправить ответ ({plain_text[:60]!r})")
    log.error("→ tg: ответ НЕ доставлен после всех попыток. Проверьте VPN/прокси Telegram.")
    return False


async def send_long(m: Message, text: str, raw_prefix: bool = False) -> None:
    """Отправить ответ любой длины и с любыми символами (режем по 3800 — лимит Telegram 4096)."""
    for i in range(0, len(text), 3800):
        chunk = text[i:i + 3800]
        if raw_prefix and i == 0 and "\n\n" in chunk:
            head, body = chunk.split("\n\n", 1)
            html_text = head + "\n\n" + _to_html(body)
        else:
            html_text = _to_html(chunk)
        await _send(m, html_text, _re.sub(r"<[^>]+>", "", chunk))


async def _answer_md(m: Message, text: str, **kw) -> None:
    """Команды отдают markdown (**жирный**). Шлём HTML-разметкой, при сбое — чистым текстом."""
    if kw.get("reply_markup"):
        try:
            await m.answer(_to_html(text), parse_mode=ParseMode.HTML, **kw)
            return
        except Exception as e:  # pragma: no cover
            log.debug("md answer с клавиатурой: %s", e)
    await _send(m, _to_html(text), text)


# Команда → функция красивой карточки (core.services.cards)
_CMD_CARDS = {"today": "today_card", "money": "finances_card", "tasks": "tasks_card", "orders": "orders_card",
              "missed": "missed_card", "goals": "goals_card", "events": "events_card", "debts": "debts_card",
              "forecast": "forecast_card"}


async def _send_card(m: Message, kind: str) -> None:
    """Красивая карточка-картинка к ответу команды (уважает cards.mode). Молчит при любом сбое."""
    from core.services import cards
    try:
        if not cards.should_send("finances" if kind == "money" else kind):
            return
        fn = getattr(cards, _CMD_CARDS.get(kind, ""), None)
        if not fn:
            return
        from aiogram.types import FSInputFile
        path = await asyncio.to_thread(fn)
        if path:
            await m.answer_photo(FSInputFile(str(path)))
    except Exception as e:  # pragma: no cover
        log.debug("карточка команды %s: %s", kind, e)


HANDLE_TIMEOUT = 120  # сек: дольше этого «печатает…» крутиться не будет — ответим, что зависли


@router.message(F.text)
async def any_text(m: Message):
    log.info("← tg: %r", (m.text or "")[:80])
    typing = asyncio.create_task(_keep_typing(m))
    try:
        r = await asyncio.wait_for(agent.handle(m.text, channel=_channel_for(m)), timeout=HANDLE_TIMEOUT)
        typing.cancel()
        await send_long(m, r.text or "…")
        await _maybe_send_card(m, r)
        from core.voice import tts
        if tts.enabled() and tts.REPLY_VOICE == "always":
            await _reply_voice(m, r.text)
    except asyncio.TimeoutError:
        typing.cancel()
        log.warning("handle timeout: %r", m.text[:80])
        _record_error("tg: таймаут обработки (>%ds): %s" % (HANDLE_TIMEOUT, m.text[:80]))
        msg = ("Завис на этом вопросе дольше двух минут, сэр. Скорее всего, облако или Ollama не отвечают — "
               "загляните в ⚙ Настройки → состояние.")
        await _send(m, msg, msg)
    except Exception as e:
        typing.cancel()
        log.exception("handle failed: %s", e)
        _record_error(f"tg: {e}")
        await m.answer(say("error"))
    finally:
        typing.cancel()


def _record_error(text: str) -> None:
    try:
        from ..api.app import app
        errs = list(getattr(app.state, "errors", []))
        errs.append({"at": datetime.now().isoformat(), "text": text[:300]})
        app.state.errors = errs[-30:]
    except Exception:  # pragma: no cover
        pass


async def _maybe_send_card(m: Message, r) -> None:
    """Короткая карточка-картинка следом за текстом (текст уже ушёл — ответ не задерживается).
    Молча ничего не делает, если картинки выключены или не получилось. Рендер — на ПК (Pillow), кэшируется."""
    try:
        from core.services import cards
        from aiogram.types import FSInputFile
        path = await asyncio.to_thread(cards.for_result, getattr(r, "actions", []) or [], r.text or "")
        if path:
            await m.answer_photo(FSInputFile(str(path)))
    except Exception as e:  # pragma: no cover
        log.debug("card follow-up: %s", e)


@router.message(F.voice | F.audio | F.video_note)
async def voice_msg(m: Message):
    """Голосовое → Whisper (локально) → agent.handle → ответ текстом и голосом.
    Если уверенность низкая — показываем расшифровку и спрашиваем: Верно / Повторить / Исправить."""
    from core.voice import stt, tts
    if not stt.available():
        await m.answer("Распознавание голосовых не установлено — запустите install_voice.bat, сэр.")
        return
    if not _once(m):
        return
    typing = asyncio.create_task(_keep_typing(m))
    tmp = None
    try:
        media = m.voice or m.audio or m.video_note
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = VOICE_DIR / f"in_{m.message_id}.ogg"
        await m.bot.download(media, destination=tmp)
        res = await asyncio.wait_for(stt.transcribe_detailed(tmp), timeout=120)
        text = (res.get("text") or "").strip()
        typing.cancel()
        if not text:
            await m.answer("Не разобрал ни слова, сэр. Ближе к микрофону или текстом.",
                           reply_markup=_kb([("🎙 повторить", "vc:again")]))
            return
        log.info("← tg voice: %r (conf %.2f, no_speech %.2f, via %s)", text[:80],
                 res.get("confidence", 0), res.get("no_speech", 0), res.get("via"))
        if stt.looks_unsure(res.get("confidence"), res.get("no_speech")):
            # Мусорную расшифровку в LLM НЕ отправляем: сначала подтверждение от человека.
            _VOICE_PENDING[m.chat.id] = text
            shown = text if len(text) <= 2800 else text[:2797].rstrip() + "…"
            await m.answer(f"🎙 Расслышал так — <b>так себе</b>:\n<blockquote>{_html.escape(shown)}</blockquote>\n\nВерно понял?",
                           reply_markup=_voice_kb())
            return
        await _run_voice_command(m, text)
    except asyncio.TimeoutError:
        typing.cancel()
        await m.answer("Слишком долго думал над голосовым, сэр. Попробуйте ещё раз или текстом.")
    except Exception as e:
        typing.cancel()
        log.exception("voice failed: %s", e)
        _record_error(f"tg voice: {e}")
        await m.answer(say("error"))
    finally:
        typing.cancel()
        if tmp:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


async def _run_voice_command(m: Message, text: str) -> None:
    """Выполнить распознанную команду и ответить: сверху расшифровка цитатой, снизу ответ; голосом — по настройке."""
    from core.voice import tts
    typing = asyncio.create_task(_keep_typing(m))
    try:
        r = await asyncio.wait_for(agent.handle(text, channel=_channel_for(m, "tg-voice")), timeout=HANDLE_TIMEOUT)
    finally:
        typing.cancel()
    # сверху — расшифровка ЦЕЛИКОМ (сворачиваемой цитатой), снизу — ответ; одно сообщение.
    shown = text if len(text) <= 3000 else text[:2997].rstrip() + "…"   # лимит одного сообщения Telegram — 4096
    quote = f"<blockquote expandable>🎙 {_html.escape(shown)}</blockquote>" if len(shown) > 140 else f"<blockquote>🎙 {_html.escape(shown)}</blockquote>"
    await send_long(m, f"{quote}\n\n{r.text or '…'}", raw_prefix=True)
    await _maybe_send_card(m, r)
    if tts.enabled() and tts.REPLY_VOICE in ("voice", "always"):
        await _reply_voice(m, r.text)


@router.callback_query(F.from_user.id == OWNER_ID, F.data.regexp(r"^vc:(ok|again|fix)$"))
async def cb_voice_confirm(cq: CallbackQuery):
    """Подтверждение расшифровки: Верно — выполняем; Повторить — ждём новое голосовое; Исправить — текстом."""
    act = cq.data.split(":")[1]
    chat = cq.message.chat.id
    text = _VOICE_PENDING.pop(chat, None)
    if act == "again":
        await cq.answer("Жду голосовое")
        await _drop_kb(cq, "🎙 Хорошо — запишите ещё раз, я слушаю.")
        return
    if act == "fix":
        await cq.answer("Напишите текстом")
        await _drop_kb(cq, "✏️ Напишите, что имели в виду, обычным сообщением — выполню.")
        return
    await cq.answer("Ок, выполняю")
    await _drop_kb(cq, f"🎙 {text}" if text else "Уже не помню эту фразу — повторите, пожалуйста.")
    if text:
        await _run_voice_command(cq.message, text)


async def _drop_kb(cq: CallbackQuery, note: str) -> None:
    """Убрать кнопки у сообщения и оставить итог (если редактировать нельзя — просто новое сообщение)."""
    try:
        await cq.message.edit_text(note, reply_markup=None)
    except Exception:
        try:
            await cq.message.answer(note)
        except Exception:  # pragma: no cover
            pass


async def _reply_voice(m: Message, text: str) -> None:
    """Озвучить ответ и отправить голосовым. Тихо пропускаем, если не вышло."""
    from core.voice import tts
    from aiogram.types import FSInputFile
    out = VOICE_DIR / f"out_{m.message_id}.ogg"
    try:
        await m.bot.send_chat_action(m.chat.id, ChatAction.RECORD_VOICE)
        p = await asyncio.wait_for(tts.speak_to_file(text, out), timeout=60)
        if p:
            await m.answer_voice(FSInputFile(p))
    except Exception as e:
        log.warning("tts reply failed: %s", e)
    finally:
        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass


@router.callback_query(F.from_user.id != OWNER_ID)
async def cb_stranger(cq: CallbackQuery):
    await cq.answer("Это личный ассистент.", show_alert=False)


@router.callback_query(F.data.regexp(r"^(ev|task):\d+:(ok|done|hour|min15|evening|tomorrow|habit)$"))
async def cb_reminder(cq: CallbackQuery):
    """Кнопки под напоминанием: сделано / отложить (15 мин / вечером / +1 час / завтра). Сообщение редактируется,
    кнопки убираются, показывается итог. Повторное нажатие не выполняется дважды."""
    from datetime import datetime, timedelta
    from core.services import calendar as cal, tasks as tsk
    ckey = (cq.message.chat.id, cq.message.message_id, cq.data)
    if ckey in _CB_DONE and time.time() - _CB_DONE[ckey] < 3600:
        await cq.answer("Уже нажато — принято.")
        return
    _CB_DONE[ckey] = time.time()
    kind, sid, act = cq.data.split(":")
    oid = int(sid)

    def when_due():
        if act == "min15":
            return datetime.now() + timedelta(minutes=15)
        if act == "evening":
            return _evening()
        if act == "hour":
            return datetime.now() + timedelta(hours=1)
        if act == "habit":
            from core.services import habits
            return habits.next_habit()
        return (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)

    msg = "Готово."
    try:
        if kind == "task":
            if act == "done":
                t = tsk.complete_task(oid)
                msg = f"✅ «{t.title}» — сделано. Красавчик, сэр." if t else "Задача уже закрыта."
            elif act == "tomorrow":
                from core.brain.dates import is_all_day
                t = tsk.postpone_to_tomorrow(oid)
                msg = (f"📅 «{t.title}» — перенёс на завтра" + ("." if is_all_day(t.due) else f", {t.due:%H:%M}.")) if t else "Задача не найдена."
            else:
                due = when_due()
                t = tsk.update_task(oid, due=due)
                msg = f"⏰ «{t.title}» — напомню в {due:%H:%M}." if t else "Задача не найдена."
        else:
            if act == "ok":
                msg = "Принято, сэр. Не опаздывайте."
            else:
                e = cal.move_event(oid, when_due())
                if not e:
                    msg = "Событие не найдено."
                elif act == "tomorrow":
                    msg = f"📅 «{e.title}» — перенёс на завтра, {e.start:%H:%M}."
                elif act == "evening":
                    msg = f"🌆 «{e.title}» — вечером, {e.start:%H:%M}."
                elif act == "min15":
                    msg = f"⏱ «{e.title}» — в {e.start:%H:%M}."
                else:
                    msg = f"⏰ «{e.title}» — теперь в {e.start:%H:%M}."
        if agent.on_change:
            agent.on_change("chat", {"channel": "tg", "actions": ["reminder_action"]})
    except Exception as ex:
        log.warning("callback failed: %s", ex)
        msg = f"Не получилось: {ex}"
    await cq.answer(msg[:180])
    try:
        await cq.message.edit_text((cq.message.html_text or cq.message.text or "") + f"\n\n<i>{msg}</i>", reply_markup=None)
    except Exception:
        await cq.message.answer(msg)


@router.callback_query(F.data.regexp(r"^pro:(task|mute|ok):\d+:[a-z]+$"))
async def cb_proactive(cq: CallbackQuery):
    """Кнопки под инициативным сообщением: поставить задачу / не надо про это / норм."""
    from core.services import proactive
    _, action, sid, why = cq.data.split(":")
    try:
        msg = proactive.act(action, int(sid), why)
        if agent.on_change and action == "task":
            agent.on_change("chat", {"channel": "tg", "actions": ["add_task"]})
    except Exception as ex:
        log.warning("proactive callback failed: %s", ex)
        msg = f"Не получилось: {ex}"
    await cq.answer(msg[:180])
    try:
        await cq.message.edit_text((cq.message.html_text or cq.message.text or "") + f"\n\n<i>{msg}</i>", reply_markup=None)
    except Exception:
        await cq.message.answer(msg)


@router.callback_query(F.data.regexp(r"^aim:\d+:(pause|drop|done)$"))
async def cb_aim(cq: CallbackQuery):
    """Кнопки под «цель стоит»: пауза / снять / достигнута."""
    from core.services import aims
    _, sid, act = cq.data.split(":")
    try:
        a = aims.close_aim(int(sid), {"pause": "paused", "drop": "dropped", "done": "done"}[act])
        msg = ("Цель не найдена." if not a else
               {"pause": f"«{a.title}» — на паузе. Вернёшься — скажи «цель … активна».", "drop": f"«{a.title}» снята. Без драмы.", "done": f"«{a.title}» — закрыта. Красиво."}[act])
        if agent.on_change:
            agent.on_change("chat", {"channel": "tg", "actions": ["close_aim"]})
    except Exception as ex:
        log.warning("aim callback failed: %s", ex)
        msg = f"Не получилось: {ex}"
    await cq.answer(msg[:180])
    try:
        await cq.message.edit_text((cq.message.html_text or cq.message.text or "") + f"\n\n<i>{msg}</i>", reply_markup=None)
    except Exception:
        await cq.message.answer(msg)


@router.callback_query(F.data.regexp(r"^pomo:\d+:(\d{1,3}|break|stop)$"))
async def cb_pomo(cq: CallbackQuery):
    """Кнопки под «помодоро готово»: ещё 25 / перерыв 5 / хватит."""
    from core.services import orders
    _, sid, act = cq.data.split(":")
    oid = int(sid) or None
    try:
        if act == "stop":
            orders.stop_session(); msg = "⏹ Таймер остановлен. Хорошая работа."
        elif act == "break":
            w = orders.start_session(oid, None, kind="break", source="tg"); msg = f"☕ Перерыв {w.planned_min} минут. Отойдите от монитора."
        else:
            w = orders.start_session(oid, int(act), source="tg"); msg = f"🍅 Ещё {w.planned_min} минут. Поехали."
        if agent.on_change:
            agent.on_change("timer", {})
    except Exception as ex:
        msg = f"Не получилось: {ex}"
    await cq.answer(msg[:180])
    try:
        await cq.message.edit_text((cq.message.html_text or cq.message.text or "") + f"\n\n<i>{msg}</i>", reply_markup=None)
    except Exception:
        await cq.message.answer(msg)


@router.message(Command("week"))
async def week_cmd(m: Message):
    from core.services import insights
    stop = asyncio.create_task(_keep_typing(m))
    try:
        txt = await asyncio.wait_for(insights.weekly_digest(), timeout=120) or "За неделю заметок не было — обозревать нечего, сэр."
    finally:
        stop.cancel()
    await send_long(m, txt)


@router.message(Command("report"))
async def report_cmd(m: Message):
    """Открытка-отчёт: /report — неделя, /report 30 — месяц."""
    from aiogram.types import BufferedInputFile
    from core.services import cards
    days = 30 if "30" in (m.text or "") or "мес" in (m.text or "") else 7
    path = await asyncio.to_thread(cards.report_card, days)
    if not path:
        await m.answer("Не смог нарисовать отчёт, сэр — смотрите лог."); return
    await m.answer_photo(BufferedInputFile(path.read_bytes(), filename=path.name), caption="📊 Итоги недели" if days == 7 else "📊 Итоги месяца")


@router.message(Command("month", "месяц"))
async def month_cmd(m: Message):
    """Снимок «как я жил в этом месяце» — одной карточкой (деньги, работа, привычки)."""
    from aiogram.types import BufferedInputFile
    from core.services import cards
    path = await asyncio.to_thread(cards.month_snapshot_card)
    if not path:
        await m.answer("Не смог собрать снимок месяца, сэр — смотрите лог."); return
    await m.answer_photo(BufferedInputFile(path.read_bytes(), filename=path.name), caption="🗓 Как я жил в этом месяце")


@router.message(Command("forecast"))
async def forecast_cmd(m: Message):
    from core.services import insights
    await m.answer(_to_html(insights.cash_forecast_text()))


@router.message(F.document)
async def document_msg(m: Message):
    """Файл: CSV/PDF/XLSX — пробуем как банковскую выписку. Прочее — объясняем."""
    import io
    name = (m.document.file_name or "").lower()
    if name.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic")) or (m.document.mime_type or "").startswith("image/"):
        await photo_msg(m, as_document=True); return   # фото «файлом», без сжатия
    if not name.endswith((".csv", ".pdf", ".xlsx", ".xls", ".txt")):
        await m.answer(f"Файл «{m.document.file_name}» получил, сэр, но понимаю только выписки (CSV/PDF/XLSX). Ссылки и заметки — просто текстом.")
        return
    if m.document.file_size and m.document.file_size > 15 * 1024 * 1024:
        await m.answer("Файл больше 15 МБ — многовато для выписки, сэр."); return
    from core.services import bank_import
    stop = asyncio.create_task(_keep_typing(m))
    try:
        buf = io.BytesIO()
        await m.bot.download(m.document, destination=buf)
        res = await asyncio.to_thread(bank_import.import_file, m.document.file_name or name, buf.getvalue(), None)
    finally:
        stop.cancel()
    if res.added and agent.on_change:
        agent.on_change("chat", {"channel": "tg", "actions": ["import"]})
    agent._log_chat("assistant", res.text(), "tg")
    await send_long(m, res.text())


BRAIN_CAP_RX = _re.compile(r"^\s*(в\s+мозг|мозг|мысль|заметка|запомни|сохрани|запиши|идея)(?![а-яё])\s*[:\-—,]?\s*", _re.I)
RECEIPT_CAP_RX = _re.compile(r"чек|квитанц|трат[аы]?\b|расход|купил|оплат|потратил", _re.I)
# последние фото из чата (для кнопки «💾 в мозг» и фразы «сохрани это в мозг»): id → (bytes, описание)
_RECENT_PHOTOS: dict[str, tuple[bytes, str]] = {}


def _remember_photo(raw: bytes, about: str) -> str:
    import hashlib
    key = hashlib.sha1(raw).hexdigest()[:10]
    _RECENT_PHOTOS[key] = (raw, about)
    while len(_RECENT_PHOTOS) > 12:
        _RECENT_PHOTOS.pop(next(iter(_RECENT_PHOTOS)))
    return key


def _save_photo_note(raw: bytes, text: str, about: str, channel: str = "tg"):
    """Фото + подпись → мысль с картинкой. Подпись пользователя — главный текст; описание от зрения — в конец,
    чтобы поиск по смыслу находил фото по содержимому."""
    from core.services import brain_notes
    rel = brain_notes.save_image(raw)
    body = (text or "").strip()
    if about:
        body = (body + "\n\n" if body else "") + "📷 " + about.strip()
    return brain_notes.add_note(body or "Фото", source=channel, image=rel, polish=bool(text))


async def _photo_bytes(m: Message, as_document: bool) -> bytes:
    import io
    buf = io.BytesIO()
    await m.bot.download(m.document if as_document else m.photo[-1], destination=buf)
    raw = buf.getvalue()
    if len(raw) > 2_500_000:
        # большой оригинал → ужимаем, иначе модель зрения захлебнётся, а Groq откажет по размеру
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(raw)).convert("RGB"); im.thumbnail((1600, 1600))
            out = io.BytesIO(); im.save(out, "JPEG", quality=85); raw = out.getvalue()
        except Exception:
            pass
    return raw


@router.message(F.photo)
async def photo_msg(m: Message, as_document: bool = False):
    """Фото в Telegram.
    • подпись начинается с «мозг»/«мысль»/«запомни» → сохраняем в мозг (картинка + подпись + краткое описание);
    • подпись про чек/трату или фото без подписи, похожее на чек → трата;
    • подпись-вопрос → отвечаем по фото;
    • просто фото/мем → реагируем по-человечески (кекаем), под ответом кнопка «💾 в мозг»."""
    import base64, json
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from core.brain import llm
    from core.services import finance
    caption = (m.caption or "").strip()
    mb = BRAIN_CAP_RX.match(caption)
    to_brain = bool(mb)
    if to_brain:
        caption = caption[mb.end():].strip()
    receipt_hint = not to_brain and bool(RECEIPT_CAP_RX.search(caption))
    stop = asyncio.create_task(_keep_typing(m))
    ans = None
    try:
        raw = await _photo_bytes(m, as_document)
        b64 = base64.b64encode(raw).decode()
        if to_brain:
            # в мозг: короткое описание — чтобы потом искать «та фотка с графиком»
            about = await asyncio.wait_for(llm.describe_image(b64, "Опиши, что на фото, одной-двумя фразами: главное содержимое, текст на картинке если есть. Без вступлений.", private=False, short=True), timeout=120) or ""
            _save_photo_note(raw, caption, about)
            if agent.on_change:
                agent.on_change("chat", {"channel": "tg", "actions": ["add_note"]})
            txt = "🧠 В мозг: фото" + (f" + «{caption[:80]}»" if caption else "") + (f"\n<i>{_html.escape(about[:200])}</i>" if about else "")
            agent._log_chat("assistant", txt, "tg")
            await m.answer(txt, parse_mode=ParseMode.HTML); return
        if caption and not receipt_hint:
            # подпись — это вопрос или контекст: «что это?», «переведи», «коллега прислал для мотивации»
            q = (f"Пользователь прислал фото с подписью: «{caption}». Ответь по фото и подписи как живой собеседник в мессенджере: "
                 "если это мем или смешная картинка — отреагируй с юмором в одну-три фразы; если вопрос — ответь по делу. "
                 "Никаких рассуждений, вариантов ответа и разбора — только сама реплика.")
            ans = await asyncio.wait_for(llm.describe_image(b64, q, private=False, short=False), timeout=180)
            if not ans:
                await m.answer("Фото получил, но посмотреть не могу: " + llm.vision_hint()); return
            key = _remember_photo(raw, ans)
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💾 в мозг", callback_data=f"brain:{key}")]])
            agent._log_chat("assistant", ans, "tg")
            await _send(m, _to_html(ans), ans) if len(ans) < 3500 else await send_long(m, ans)
            try:
                await m.answer("Сохранить фото в мозг?", reply_markup=kb)
            except Exception:
                pass
            return
        # без подписи (или подпись про чек): сначала пробуем как чек, иначе — реакция на картинку
        q = ("Посмотри на фото. ЕСЛИ это чек, квитанция или экран оплаты — верни СТРОГО JSON: "
             "{\"total\": число итого в рублях, \"store\": \"название магазина\", "
             "\"category\": одна из [Продукты, Кафе, Транспорт, Здоровье, Дом, Развлечения, Одежда, Связь, Прочее], \"items\": [\"2-4 главные позиции\"]}. "
             "ЕСЛИ это НЕ чек — верни {\"total\": 0, \"about\": \"что на фото, 1 фраза по-русски\", "
             "\"react\": \"твоя живая реакция на картинку как друга в мессенджере, 1-2 фразы: если мем — пошути в тему, если красиво — оцени, если скрин с текстом — скажи суть\"}. "
             "Только JSON, без рассуждений.")
        ans = await asyncio.wait_for(llm.describe_image(b64, q, private=True, short=False), timeout=180)
    finally:
        stop.cancel()
    if not ans:
        hint = llm.vision_hint()
        if llm.VISION_WHERE == "auto" and llm.cloud_enabled() and llm.CLOUD_PROVIDER in llm.CLOUD_VISION_MODELS:
            hint += " Чтобы чеки и фото шли в облако, поставьте в Настройки → мозг → «где смотреть картинки» = cloud."
        await m.answer("Фото получил, но посмотреть не могу: " + hint); return
    mt = _re.search(r"\{.*\}", ans, _re.S)
    try:
        data = json.loads(mt.group(0)) if mt else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    try:
        total = float(str(data.get("total") or 0).replace(",", ".").replace(" ", "") or 0)
    except ValueError:
        total = 0.0
    if total <= 0:
        about = (data.get("about") or "").strip()
        react = (data.get("react") or "").strip()
        if not about and not react and not mt:
            react = llm.strip_think(ans)[:600]
        if receipt_hint and not react:
            react = "На чек не похоже, сэр. Если это всё-таки трата — напишите сумму текстом: «потратил 700 на такси»."
        text = react or (("👁 " + about) if about else "Что это — не разобрал, сэр. Подпишите фото вопросом — отвечу по нему.")
        key = _remember_photo(raw, about or react)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💾 в мозг", callback_data=f"brain:{key}")]])
        agent._log_chat("assistant", text, "tg")
        try:
            await m.answer(_to_html(text), parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            await m.answer(text, reply_markup=kb)
        return
    note = ", ".join(filter(None, [data.get("store"), *(data.get("items") or [])[:3]]))[:120]
    cat = data.get("category") or None
    try:
        t = finance.add_transaction(total, "expense", cat, note or "чек", None, source="tg")
        msg = f"🧾 Записал трату <b>{finance.money(t.amount)}</b> · {t.category}" + (f" · {note}" if note else "") + "\nЕсли не так — «отмени» или «исправь сумму на …»."
    except Exception as e:
        msg = f"Чек прочитал ({finance.money(total)}), но записать не смог: {e}"
    if agent.on_change:
        agent.on_change("chat", {"channel": "tg", "actions": ["add_expense"]})
    await m.answer(msg)


@router.callback_query(F.data.regexp(r"^brain:[0-9a-f]+$"))
async def cb_brain(cq: CallbackQuery):
    """Кнопка «💾 в мозг» под реакцией на фото."""
    key = cq.data.split(":", 1)[1]
    item = _RECENT_PHOTOS.get(key)
    if not item:
        await cq.answer("Это фото уже не помню — пришлите его ещё раз с подписью «мозг».", show_alert=True); return
    raw, about = item
    try:
        _save_photo_note(raw, "", about)
        if agent.on_change:
            agent.on_change("chat", {"channel": "tg", "actions": ["add_note"]})
        await cq.answer("Сохранил в мозг 🧠")
        try:
            await cq.message.edit_text("🧠 Фото сохранено в мозг.", reply_markup=None)
        except Exception:
            pass
    except Exception as e:
        await cq.answer(f"Не вышло: {e}"[:180], show_alert=True)


@router.edited_message(~F.from_user.id.in_({OWNER_ID}))
async def edited_stranger(m: Message):
    pass


@router.edited_message()
async def edited(m: Message):
    """Отредактированное сообщение — не выполняем повторно, просто говорим об этом."""
    log.info("← tg: сообщение отредактировано (%r) — повторно не выполняю", (m.text or "")[:60])
    await _send(m, "Вижу, что вы отредактировали сообщение, сэр. Повторно я его не выполняю — если нужно, пришлите заново.",
                "Вижу, что вы отредактировали сообщение, сэр. Повторно я его не выполняю — если нужно, пришлите заново.")


@router.message()
async def anything_else(m: Message):
    """Всё, что не текст и не голос: фото, стикер, документ, локация… Раньше бот молчал — теперь объясняет."""
    kind = m.content_type
    log.info("← tg: не текст и не голос (%s) — пока не умею", kind)
    names = {"photo": "фото", "sticker": "стикер", "document": "файл", "video": "видео", "animation": "гифка",
             "location": "геопозиция", "contact": "контакт", "poll": "опрос"}
    what = names.get(str(kind), str(kind))
    txt = (f"Получил {what}, сэр, но пока понимаю только текст и голосовые. "
           + ("Фото и файлы подключу на этапе с файлами." if kind in ("photo", "document") else ""))
    if m.caption:
        # подпись к фото/файлу — выполняем как текст
        log.info("← tg: но есть подпись — выполняю её: %r", m.caption[:60])
        r = await asyncio.wait_for(agent.handle(m.caption, channel=_channel_for(m)), timeout=HANDLE_TIMEOUT)
        await send_long(m, r.text or "…")
        return
    await _send(m, txt, txt)


async def build() -> tuple[Bot, Dispatcher]:
    from aiogram.client.default import DefaultBotProperties
    from aiogram.client.session.aiohttp import AiohttpSession

    proxy = (getattr(cfg.telegram, "proxy", "") or "").strip() or None
    session = AiohttpSession(proxy=proxy, timeout=20)
    bot = Bot(cfg.telegram.token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    if proxy:
        log.info("Telegram через прокси: %s", proxy.split("@")[-1])
    return bot, dp


async def _set_menu_button(bot: Bot) -> None:
    """Кнопка-приложение слева от поля ввода (Mini App): открывает сайт прямо в Telegram.
    Адрес берётся из telegram.webapp_url (публичный https://…ts.net из funnel.bat). Пусто — кнопка обычная."""
    from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo
    url = (getattr(cfg.telegram, "webapp_url", "") or "").strip()
    try:
        if url.startswith("https://"):
            await bot.set_chat_menu_button(chat_id=OWNER_ID, menu_button=MenuButtonWebApp(text="Открыть", web_app=WebAppInfo(url=url)))
            log.info("Mini App в Telegram: %s", url)
        else:
            await bot.set_chat_menu_button(chat_id=OWNER_ID, menu_button=MenuButtonDefault())
            if url:
                log.warning("telegram.webapp_url должен начинаться с https:// — кнопка приложения не установлена")
    except Exception as e:
        log.warning("Не удалось установить кнопку приложения в Telegram: %s", e)


async def check_connection(bot: Bot) -> bool:
    """Пытаемся достучаться до Telegram. False = недоступен (блокировка/нет сети)."""
    try:
        me = await bot.get_me()
        log.info("Telegram OK: @%s", me.username)
        await bot.set_my_commands([
            BotCommand(command="today", description="Что сегодня"),
            BotCommand(command="money", description="Финансы"),
            BotCommand(command="tasks", description="Задачи"),
            BotCommand(command="events", description="Календарь на неделю"),
            BotCommand(command="debts", description="Долги"),
            BotCommand(command="forecast", description="Прогноз кассы на месяц"),
            BotCommand(command="orders", description="Заказы: дедлайны и кто должен"),
            BotCommand(command="missed", description="Что я упускаю: оплаты, долги, цели"),
            BotCommand(command="pomo", description="Помодоро 25 мин (/pomo ролик · /pomo stop)"),
            BotCommand(command="goals", description="Цели и конверты"),
            BotCommand(command="week", description="Обзор недели: мысли и задачи"),
            BotCommand(command="report", description="Открытка-отчёт за неделю (/report 30 — месяц)"),
            BotCommand(command="month", description="Как я жил в этом месяце — снимок"),
            BotCommand(command="summary", description="Итог дня одной карточкой"),
            BotCommand(command="find", description="Поиск по «второму мозгу»"),
            BotCommand(command="exp", description="Трата одним тапом: /exp 700 такси"),
            BotCommand(command="task", description="Задача одним тапом: /task сдать отчёт"),
            BotCommand(command="voice", description="Голосовые ответы: на голосовые / всегда / никогда"),
            BotCommand(command="game", description="Игровой режим вкл/выкл (освободить видеокарту)"),
            BotCommand(command="diag", description="Диагностика мозга и облака"),
            BotCommand(command="app", description="Открыть сайт внутри Telegram"),
        ])
        await _set_menu_button(bot)
        return True
    except Exception as e:
        name = type(e).__name__
        if "Unauthorized" in name:
            log.error("Telegram отклонил токен (Unauthorized). Проверь telegram.token в config.yaml.")
        else:
            log.warning("Telegram недоступен: %s", name)
        return False


async def run_polling_forever(bot: Bot, dp: Dispatcher, on_connected=None) -> None:
    """Опрос Telegram с бесконечными повторами: пропал интернет/VPN — переживём, вернётся — подхватим."""
    import asyncio
    announced = False
    delay = 15
    while True:
        if await check_connection(bot):
            delay = 15
            if not announced and on_connected:
                try:
                    await on_connected()
                except Exception:
                    pass
                announced = True
            try:
                await dp.start_polling(bot, handle_signals=False)
                return
            except Exception as e:
                if "Conflict" in str(e) or "terminated by other getUpdates" in str(e):
                    log.error("ДВА ДЖАРВИСА НА ОДНОМ БОТЕ: где-то запущено ещё одно окно (автозагрузка? старая копия?). "
                              "Сообщения уходят туда, а не сюда. Закройте все окна ассистента и запустите start.bat один раз.")
                    _record_error("tg: конфликт — запущен второй экземпляр бота")
                log.warning("Polling прервался: %s — переподключаюсь", type(e).__name__)
        else:
            log.warning("Не могу подключиться к api.telegram.org. Включи VPN или укажи telegram.proxy в config.yaml. "
                        "Повтор через %s сек. API и сайт работают.", delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 120)


def _kb(buttons, per_row: int = 2):
    """Инлайн-кнопки; по 2 в ряд — ряды одинаковой ширины, подписи не обрезаются."""
    if not buttons:
        return None
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


async def notify(bot: Bot, text: str, buttons=None) -> None:
    """Сообщение владельцу. buttons — [(подпись, callback_data), ...] в один ряд (инлайн-кнопки под напоминанием)."""
    try:
        await bot.send_message(OWNER_ID, _to_html(text), reply_markup=_kb(buttons))
    except Exception:
        try:
            await bot.send_message(OWNER_ID, text, parse_mode=None, reply_markup=_kb(buttons))
        except Exception as e:
            log.warning("notify failed: %s", e)


async def notify_voice(bot: Bot, text: str, buttons=None) -> bool:
    """Голосовое владельцу (текст озвучивается TTS) + тот же текст под ним, чтобы можно было прочитать и нажать кнопки.
    False — озвучить не вышло (вызывающий шлёт текстом)."""
    from core.voice import tts
    from aiogram.types import FSInputFile
    out = VOICE_DIR / f"notify_{int(datetime.now().timestamp())}.ogg"
    try:
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        await bot.send_chat_action(OWNER_ID, ChatAction.RECORD_VOICE)
        p = await asyncio.wait_for(tts.speak_to_file(text, out), timeout=60)
        if not p:
            return False
        await bot.send_voice(OWNER_ID, FSInputFile(p), caption=_to_html_cap(text), reply_markup=_kb(buttons))
        return True
    except Exception as e:
        log.warning("notify_voice failed: %s", e)
        return False
    finally:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass


async def notify_photo(bot: Bot, path: str, caption: str = "") -> None:
    from aiogram.types import FSInputFile
    try:
        await bot.send_photo(OWNER_ID, FSInputFile(path), caption=_to_html_cap(caption) if caption else None)
    except Exception as e:
        log.warning("notify_photo failed: %s", e)
