"""Управление ПК: разбор команд («открой ютуб», «найди файл договор», «пауза») и доставка их голосовому клиенту.

Ядро само ничего на ПК не делает (оно может жить и на VPS) — оно шлёт команду через SSE (/api/events/stream, kind="pc"),
а voice_client.py, который крутится на ПК, выполняет её (core/pc/actions.py) и присылает результат в /api/pc/result.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

log = logging.getLogger("assistant.pc")

# состояние ПК-клиента: когда последний раз был на связи и что сейчас делает (idle/listening/thinking/speaking/off)
LAST_SEEN: float = 0.0
STATE: dict = {"mode": "offline", "text": ""}
_pending_results: list[dict] = []   # результаты команд (поиск файлов), которые ещё не показали


def alive() -> bool:
    return time.time() - LAST_SEEN < 90


def seen(state: dict | None = None) -> None:
    global LAST_SEEN
    LAST_SEEN = time.time()
    if state:
        STATE.update(state)


# ---------------------------------------------------------------- разбор команд
SITES = {
    "ютуб": "https://youtube.com", "youtube": "https://youtube.com", "телеграм": "https://web.telegram.org", "telegram": "https://web.telegram.org",
    "гугл": "https://google.com", "google": "https://google.com", "почту": "https://mail.google.com", "почта": "https://mail.google.com", "gmail": "https://mail.google.com",
    "яндекс": "https://ya.ru", "кинопоиск": "https://kinopoisk.ru", "вк": "https://vk.com", "вконтакте": "https://vk.com", "твич": "https://twitch.tv", "twitch": "https://twitch.tv",
    "гитхаб": "https://github.com", "github": "https://github.com", "хабр": "https://habr.com", "чат гпт": "https://chatgpt.com", "chatgpt": "https://chatgpt.com", "джипити": "https://chatgpt.com",
    "озон": "https://ozon.ru", "вайлдберриз": "https://wildberries.ru", "авито": "https://avito.ru", "карты": "https://yandex.ru/maps", "погоду": "https://yandex.ru/pogoda", "погода": "https://yandex.ru/pogoda",
    "нетфликс": "https://netflix.com", "спотифай": "https://open.spotify.com", "spotify": "https://open.spotify.com", "яндекс музыку": "https://music.yandex.ru", "музыку": "https://music.yandex.ru",
    "ассистента": "__self__", "сайт ассистента": "__self__", "твой сайт": "__self__",
}
APPS = {
    "телегу": "telegram", "телеграм": "telegram", "telegram": "telegram", "дискорд": "discord", "discord": "discord", "стим": "steam", "steam": "steam",
    "блокнот": "notepad", "калькулятор": "calc", "проводник": "explorer", "браузер": "__browser__", "хром": "chrome", "chrome": "chrome", "эксель": "excel", "ворд": "winword",
    "фотошоп": "photoshop", "премьер": "premiere", "obs": "obs64", "обс": "obs64", "спотифай": "spotify", "vs code": "code", "вс код": "code", "код": "code", "терминал": "wt", "консоль": "cmd",
    "диспетчер задач": "taskmgr", "настройки": "ms-settings:", "параметры": "ms-settings:", "корзину": "shell:RecycleBinFolder", "загрузки": "shell:Downloads", "рабочий стол": "shell:Desktop", "документы": "shell:Personal",
}
MEDIA = {
    "pause": r"^(пауза|поставь\s+на\s+паузу|стоп\s+музык\w*|останови\s+музык\w*|продолж\w*|играй|плей|play|включи\s+музык\w*|воспроизвед\w*)$",
    "next": r"^(следующ\w*(\s+трек|\s+песн\w*)?|дальше|переключи(\s+трек|\s+песню)?|скип|skip)$",
    "prev": r"^(предыдущ\w*(\s+трек|\s+песн\w*)?|назад(\s+трек)?|верни\s+трек)$",
    "vol_down": r"^(тише|потише|сделай\s+тише|убавь(\s+звук|\s+громкость)?|громкость\s+вниз|звук\s+тише)$",
    "vol_up": r"^(громче|погромче|сделай\s+громче|прибавь(\s+звук|\s+громкость)?|громкость\s+вверх|звук\s+громче)$",
    "mute": r"^(без\s+звука|выключи\s+звук|заглуши|мьют|mute|включи\s+звук|верни\s+звук)$",
}
OPEN_RX = re.compile(r"^\s*(открой|открыть|запусти|запустить|включи|покажи|зайди\s+(?:в|на)|перейди\s+(?:в|на))\s+(?:мне\s+)?(?:сайт\s+|приложение\s+|программу\s+)?(.+?)\s*$", re.I)
FIND_RX = re.compile(r"^\s*(найди|найти|поищи|где)\s+(?:мне\s+)?(?:на\s+(?:компе|компьютере|пк|диске)\s+)?(?:файл\w*|папк\w*|документ\w*|фотк\w*|фото|видео|презентаци\w*)?\s*(?:с\s+названием\s+|по\s+названию\s+|про\s+|со\s+словом\s+)?(.+?)\s*$", re.I)
SCREEN_RX = re.compile(r"^\s*(что\s+(?:у\s+меня\s+)?на\s+экране|посмотри\s+на\s+экран|глянь\s+на\s+экран|что\s+я\s+(?:сейчас\s+)?(?:смотрю|читаю|вижу)|переведи\s+(?:это|экран|что\s+на\s+экране)|прочитай\s+(?:это|экран|что\s+на\s+экране)|объясни\s+(?:это|что\s+на\s+экране)|скриншот)\b(.*)$", re.I)
CLIP_RX = re.compile(r"^\s*(запомни\s+это|сохрани\s+это|запомни\s+(?:из\s+)?буфер\w*|сохрани\s+(?:из\s+)?буфер\w*|запиши\s+это|это\s+в\s+мозг)\s*[.!]?\s*$", re.I)
STATUS_RX = re.compile(r"^\s*(статус\s+(?:костюма|системы|компа|компьютера|пк|железа)|как\s+(?:там\s+)?(?:комп|компьютер|железо|система)|температур\w*(\s+процессора|\s+видеокарты)?|сколько\s+места\s+на\s+диске|загрузка\s+(?:процессора|видеокарты|системы))\s*[?.!]?\s*$", re.I)
LOCK_RX = re.compile(r"^\s*(заблокируй\s+(?:комп|компьютер|экран|пк)|блокировка|выключи\s+(?:комп|компьютер|пк)|перезагрузи\s+(?:комп|компьютер|пк)|спящий\s+режим|усыпи\s+(?:комп|компьютер))\s*[.!]?\s*$", re.I)


@dataclass
class PcCommand:
    action: str                 # open_url / open_app / open_path / find / media / screen / clipboard / status / power
    arg: str = ""
    extra: dict = field(default_factory=dict)
    say: str = ""               # что ответить пользователю сразу


def parse(text: str) -> PcCommand | None:
    """Команда для ПК или None. Работает и в ядре (для TG/сайта), и в голосовом клиенте (быстрый путь)."""
    t = text.strip().rstrip(".!").strip()
    low = t.lower()
    for act, rx in MEDIA.items():
        if re.match(rx, low, re.I):
            return PcCommand("media", act, say={"pause": "Есть.", "next": "Дальше.", "prev": "Назад.", "vol_down": "Тише.", "vol_up": "Громче.", "mute": "Тихо."}[act])
    if SCREEN_RX.match(t):
        m = SCREEN_RX.match(t)
        q = (m.group(2) or "").strip(" ,—-") or ""
        head = m.group(1).lower()
        if head.startswith("переведи"):
            q = "Переведи текст на экране на русский язык. Только перевод, кратко."
        elif head.startswith("прочитай"):
            q = "Прочитай и перескажи текст на экране кратко, по-русски."
        elif head.startswith("объясни"):
            q = "Объясни, что происходит на экране, по-русски, кратко."
        elif not q:
            q = "Что на экране? Опиши кратко по-русски: что за окно, о чём текст, что важно."
        return PcCommand("screen", q, say="Смотрю на экран…")
    if CLIP_RX.match(t):
        return PcCommand("clipboard", "", say="Беру из буфера обмена.")
    if STATUS_RX.match(t):
        return PcCommand("status", "", say="Проверяю системы.")
    if LOCK_RX.match(t):
        what = low
        kind = "lock" if "блок" in what else "shutdown" if "выключи" in what else "reboot" if "перезагруз" in what else "sleep"
        return PcCommand("power", kind, say={"lock": "Блокирую.", "shutdown": "Выключаю компьютер через 30 секунд. «Отмена выключения» — если передумали.", "reboot": "Перезагружаю через 30 секунд.", "sleep": "Спокойной ночи, сэр."}[kind])
    if re.match(r"^\s*отмен[аи]\s+выключени\w*\s*$", low):
        return PcCommand("power", "abort", say="Отменил выключение.")
    m = FIND_RX.match(t)
    if m and len(m.group(2).split()) <= 6 and not re.search(r"\b(встреч|задач|заметк|мысл|трат|долг|событ)\w*", low):
        return PcCommand("find", m.group(2).strip(" «»\"'"), say=f"Ищу «{m.group(2).strip()}» на компьютере…")
    m = OPEN_RX.match(t)
    if m and re.search(r"\b(задач|дел[аоы]?|встреч|событи|календар|финанс|баланс|долг|трат|расход|доход|заметк|мысл|ссылк|мозг|памят|бриф|план|подписк|прогноз|отч[её]т|сводк|напомина|регулярн)", low):
        m = None   # «покажи задачи», «открой календарь» — это про данные ассистента, не про ПК
    if m:
        target = m.group(2).strip(" «»\"'").lower()
        if re.search(r"^(https?://|www\.)|\.(ru|com|org|net|io|tv|me|dev|app)(/|$)", target):
            url = target if target.startswith("http") else "https://" + target
            return PcCommand("open_url", url, say=f"Открываю {target}.")
        for k in sorted(SITES, key=len, reverse=True):
            if target == k or target.startswith(k + " ") or target.endswith(" " + k):
                return PcCommand("open_url", SITES[k], say=f"Открываю {k}." if SITES[k] != "__self__" else "Открываю мой сайт.")
        for k in sorted(APPS, key=len, reverse=True):
            if target == k or target.startswith(k + " "):
                return PcCommand("open_app", APPS[k], say=f"Запускаю {k}.")
        if re.search(r"[\\/:]|\.[a-z0-9]{2,4}$", target):
            return PcCommand("open_path", m.group(2).strip(), say=f"Открываю {m.group(2).strip()}.")
        # неизвестное слово после «открой/запусти» — пробуем как программу или поиск в Google
        verb = m.group(1).lower()
        if verb.startswith(("запусти",)):
            return PcCommand("open_app", target, say=f"Пробую запустить {target}.")
        if verb.startswith(("открой", "зайди", "перейди")) and len(target.split()) <= 4:
            return PcCommand("open_url", "https://www.google.com/search?q=" + target.replace(" ", "+"), say=f"Ищу «{target}» в Google.")
        return None
    return None


# ---------------------------------------------------------------- доставка в клиент
def dispatch(cmd: PcCommand, channel: str) -> str:
    """Отправить команду ПК-клиенту (через SSE). Вернуть текст ответа пользователю."""
    from ..brain import agent
    if not alive():
        return "ПК-клиент не на связи, сэр: запустите voice.bat на компьютере — тогда смогу открывать программы и файлы."
    if agent.on_change:
        agent.on_change("pc", {"action": cmd.action, "arg": cmd.arg, "extra": cmd.extra, "channel": channel})
    return cmd.say or "Выполняю."


def push_result(text: str, channel: str = "voice") -> None:
    """Голосовой клиент прислал результат (например, список найденных файлов)."""
    _pending_results.append({"text": text, "channel": channel, "at": time.time()})
    del _pending_results[:-20]


def pop_results() -> list[dict]:
    out = list(_pending_results)
    _pending_results.clear()
    return out
