"""Загрузка настроек из config.yaml (с запасным вариантом config.example.yaml)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import logging

import yaml

log = logging.getLogger("jarvis.config")

# Старые имена JARVIS_* поддерживаются для совместимости, но устарели:
# используйте ASSISTANT_* (удаление — через 2 релиза). Предупреждение — один раз за процесс.
_JARVIS_DEPRECATED = (
    "JARVIS_DATA_DIR",
    "JARVIS_CONFIG",
    "JARVIS_DB_PATH",
    "JARVIS_TG_TOKEN",
    "JARVIS_TG_OWNER",
    "JARVIS_API_TOKEN",
)
_WARNED_JARVIS: set[str] = set()


def _warn_jarvis_deprecated() -> None:
    """Один раз за процесс предупредить о заданных JARVIS_* (ASSISTANT_* — предпочтительно)."""
    hit = [n for n in _JARVIS_DEPRECATED if os.getenv(n) and n not in _WARNED_JARVIS]
    if not hit:
        return
    _WARNED_JARVIS.update(hit)
    log.warning(
        "JARVIS_* устарели, используйте ASSISTANT_*, поддержка будет удалена: %s",
        ", ".join(sorted(hit)),
    )

ROOT = Path(__file__).resolve().parent.parent
# Тесты и внешние стенды (например e2e Playwright) уводят БД и настройки в свою папку:
# JARVIS_DATA_DIR — вместо data/, JARVIS_CONFIG — вместо config.yaml, JARVIS_DB_PATH — вместо data/jarvis.db.
# Переменные не заданы → всё как было: настоящие data/ и config.yaml.
DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR") or os.getenv("ASSISTANT_DATA_DIR") or ROOT / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _config_file() -> Path:
    """Файл настроек, который нужно читать/писать: обычно config.yaml."""
    env = os.getenv("JARVIS_CONFIG") or os.getenv("ASSISTANT_CONFIG")
    return Path(env) if env else ROOT / "config.yaml"


def _config_src() -> Path:
    """Откуда читать настройки: свой config.yaml, а если его нет — config.example.yaml."""
    path = _config_file()
    return path if path.exists() else ROOT / "config.example.yaml"


class _Node:
    """Удобный доступ через точку: cfg.telegram.token."""

    def __init__(self, d: dict[str, Any]):
        for k, v in d.items():
            setattr(self, k, _Node(v) if isinstance(v, dict) else v)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __repr__(self) -> str:  # pragma: no cover
        return f"_Node({self.__dict__})"


def _load_env_file() -> None:
    """Подгрузить .env в переменные окружения.

    Файл никогда не читался автоматически, поэтому задокументированные в .env.example
    переменные молча не работали. Правила: только пустые (не заданные в системе) ключи,
    уже установленное окружение всегда важнее файла.
    """
    path = ROOT / ".env"
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip().strip('"').strip("'")


def _load() -> _Node:
    _warn_jarvis_deprecated()
    path = _config_src()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    # переменные окружения перекрывают файл (удобно для тестов и сервера)
    env_token = os.getenv("ASSISTANT_TG_TOKEN") or os.getenv("JARVIS_TG_TOKEN")
    if env_token:
        raw.setdefault("telegram", {})["token"] = env_token
    env_owner = os.getenv("ASSISTANT_TG_OWNER") or os.getenv("JARVIS_TG_OWNER")
    if env_owner:
        raw.setdefault("telegram", {})["owner_id"] = int(env_owner)
    env_ollama = os.getenv("OLLAMA_URL")  # docker-compose: http://ollama:11434
    if env_ollama:
        raw.setdefault("brain", {}).setdefault("ollama", {})["url"] = env_ollama
    env_gemini = os.getenv("GEMINI_API_KEY")
    if env_gemini:
        raw.setdefault("brain", {}).setdefault("gemini", {})["api_key"] = env_gemini
    # Секреты из окружения: переменная всегда важнее config.yaml (значения не логируем и не печатаем).
    # Подхватываются и из .env — его читает _load_env_file() до загрузки конфига; см. .env.example.
    env_cloud = os.getenv("CLOUD_API_KEY")
    if env_cloud:
        raw.setdefault("brain", {}).setdefault("cloud", {})["api_key"] = env_cloud
    env_gsecret = os.getenv("GOOGLE_CLIENT_SECRET")
    if env_gsecret:
        raw.setdefault("google", {})["client_secret"] = env_gsecret
    env_gid = os.getenv("GOOGLE_CLIENT_ID")
    if env_gid:
        raw.setdefault("google", {})["client_id"] = env_gid
    env_api = os.getenv("ASSISTANT_API_TOKEN") or os.getenv("JARVIS_API_TOKEN")
    if env_api:
        # ключ доступа к ядру с другой машины (config.yaml: voice.pc.api_token, см. voice_client.py)
        raw.setdefault("voice", {}).setdefault("pc", {})["api_token"] = env_api
    # Обезличивание текста перед отправкой в облако — ВКЛЮЧЕНО по умолчанию: личные данные не должны
    # уходить открытым текстом из-за того, что ключа нет в config.yaml (setdefault не перезаписывает —
    # явное `brain.gemini.anonymize: false` в файле остаётся в силе). Подробнее — core/brain/llm.py.
    raw.setdefault("brain", {}).setdefault("gemini", {}).setdefault("anonymize", True)
    return _Node(raw)


def refresh() -> None:
    """Перечитать config.yaml/.env в СУЩЕСТВУЮЩИЙ объект cfg (без подмены объекта).

    Подмена (`config.cfg = _load()` или `importlib.reload(config)`) оставляла модули,
    сделавшие `from config import cfg` (планировщик и др.), со старым конфигом:
    настройки, сменённые с сайта, до них не доходили, а тесты, патчащие cfg,
    начинали писать мимо временных путей."""
    _load_env_file()
    fresh = _load()
    cfg.__dict__.clear()
    cfg.__dict__.update(fresh.__dict__)


_load_env_file()
cfg = _load()
DB_PATH = Path(os.getenv("JARVIS_DB_PATH") or os.getenv("ASSISTANT_DB_PATH") or (DATA_DIR / "jarvis.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
TZ = cfg.owner.timezone if hasattr(cfg, "owner") else "Europe/Moscow"


# ---------------------------------------------------------------- редактирование config.yaml с сайта
# Какие ключи можно менять через страницу настроек: путь → (тип, подпись, секрет?)
EDITABLE: dict[str, tuple[str, str, bool]] = {
    "assistant.name": ("str", "Имя ассистента (так он представляется и откликается голосом)", False),
    "assistant.name_latin": ("str", "Имя латиницей (заголовки окон, логи)", False),
    "assistant.aliases": ("str", "Другие варианты имени через запятую", False),
    "owner.name": ("str", "Как к вам обращаться («сэр», «босс», имя; пусто — без обращения)", False),
    "telegram.token": ("str", "Токен Telegram-бота (от @BotFather)", True),
    "telegram.owner_id": ("int", "Ваш Telegram ID (от @userinfobot)", False),
    "telegram.morning_digest": ("str", "Утренний дайджест (ЧЧ:ММ, пусто — выключить)", False),
    "notifications.quiet_from": ("int", "Тихие часы: с (час 0–23) — ночью ассистент сам не пишет", False),
    "notifications.quiet_to": ("int", "Тихие часы: до (час 0–23)", False),
    "notifications.proactive_enabled": ("bool", "Сам напоминает о том, что заметил (просрочка оплаты, дело без срока, самочувствие)", False),
    "notifications.proactive_per_day": ("int", "Не больше стольких инициативных сообщений в день (5)", False),
    "notifications.proactive_vibe": ("bool", "Просто написать днём (как дела / шутка), если тихо 5+ часов", False),
    "telegram.proxy": ("str", "Прокси для Telegram (если api.telegram.org недоступен)", False),
    "telegram.quick": ("bool", "Быстрые шаблоны в Telegram: /exp 700 такси, /inc 15000 аванс, /task …, /event …", False),
    "telegram.webapp_url": ("str", "Адрес сайта для приложения в Telegram (https://…ts.net из funnel.bat)", False),
    "brain.mode": ("str", "Режим мозга: local / hybrid / cloud", False),
    "brain.ollama.url": ("str", "Адрес Ollama", False),
    "brain.ollama.model": ("str", "Модель Ollama", False),
    "brain.ollama.embed_model": ("str", "Модель эмбеддингов (смысловой поиск)", False),
    "brain.ollama.small_model": ("str", "Малая модель для мини-задач (судья «трата или заказ», уборка памяти): qwen2.5:1.5b — пусто = основная", False),
    "brain.ollama.small_keep_alive": ("str", "Сколько малая модель живёт в видеопамяти после задачи (5m; 0 — выгружать сразу)", False),
    "brain.ollama.vision_model": ("str", "Модель зрения (скриншоты, чеки): qwen2.5vl:3b / llava / moondream — пусто, если не ставили", False),
    "brain.vision.where": ("str", "Где смотреть картинки: auto (ПК, при сбое — облако; чеки только ПК) / cloud (всегда облако, быстро) / local (только ПК)", False),
    "brain.vision.allow_cloud": ("bool", "Скриншоты «что на экране» можно отправлять в облако, если нет локальной модели зрения (чеки — никогда)", False),
    "brain.cloud.provider": ("str", "Провайдер облака", False),
    "brain.cloud.api_key": ("str", "Ключ облака", True),
    "brain.cloud.model": ("str", "Модель облака (пусто — по умолчанию у провайдера)", False),
    "brain.cloud.base_url": ("str", "Адрес API (только для custom)", False),
    "brain.cloud.proxy": ("str", "Прокси для облака (обычно не нужен)", False),
    "brain.cloud.reasoning": ("str", "Рассуждения облака: auto (минимум, как раньше) / off — не думать вообще, экономия токенов и времени / minimal / low / medium / high", False),
    "brain.cloud.max_tokens": ("int", "Потолок ответа облака, токенов (1024; большие пачки — 2048–4096)", False),
    "brain.cloud.timeout": ("int", "Секунд ждать ответ облака (45; длинным ответам — 60–90)", False),
    "brain.cloud.personal_tools": ("bool", "Режим «облако вместо ПК» (brain.mode=cloud): отдавать облачной модели личные данные — заметки, память, карточки людей, сводки по деньгам и заказам. Выключено = облако только пишет, но не читает ваши данные", False),
    "brain.gemini.auto": ("bool", "Разговор и общие вопросы — в облако (иначе только по слову «облако, …»)", False),
    "brain.gemini.api_key": ("str", "Ключ Google Gemini (только если провайдер gemini)", True),
    "brain.gemini.model": ("str", "Модель Google Gemini (auto)", False),
    "brain.gemini.proxy": ("str", "Прокси для Google Gemini", False),
    "brain.gemini.anonymize": ("bool", "Обезличивать текст перед отправкой в облако", False),
    "brain.gemini.mark_source": ("bool", "Помечать источник ответа (⚡/🧠/☁️)", False),
    "brain.sorter.where": ("str", "Кто разбирает сообщения-списки на записи: cloud (облако, надёжнее; текст уходит целиком) / local (только ПК) / auto (ПК, при сбое облако)", False),
    "brain.sorter.confirm": ("bool", "Списки: сначала показать, как понял, и ждать «да» (иначе записывать сразу — «отмени» откатит всю пачку)", False),
    "brain.memory.enabled": ("bool", "Память о вас: запоминать факты из разговора, подтягивать нужное в ответы, портрет", False),
    "brain.memory.where": ("str", "Кто извлекает и обобщает факты: cloud (облако, при сбое ПК) / auto (ПК, при сбое облако) / local (только ПК). Поиск по памяти — всегда ПК", False),
    "brain.judge.enabled": ("bool", "Судья: спорную фразу («сайт 15000», «отдал Ване 2000») перед записью решает нейронка, а не шаблон", False),
    "brain.judge.where": ("str", "Кто судит: local (малая/основная модель на ПК; по умолчанию) / cloud (облако, при сбое ПК) / auto (ПК, при сбое облако)", False),
    "brain.memory.short_days": ("int", "Сколько дней факт живёт в «сейчас», прежде чем стать постоянным или уйти в архив", False),
    "brain.relations.enabled": ("bool", "Связи между записями в Мозге («связано:» в карточке, смысловые линии в графе)", False),
    "brain.relations.where": ("str", "Кто решает, связаны ли записи: cloud (облако, при сбое ПК) / auto (ПК, при сбое облако) / local (только ПК). Кандидатов всегда отбирает ПК", False),
    "voice.stt.model": ("str", "Модель распознавания Whisper: tiny / base / small / medium (точнее, но медленнее)", False),
    "voice.stt.cloud": ("bool", "Распознавать речь через Groq Whisper (~1 с, но голос уходит в облако; нужен провайдер groq)", False),
    "voice.tts.engine": ("str", "Голос: silero (офлайн) / edge (онлайн, Microsoft) / off", False),
    "voice.tts.speaker": ("str", "Голос Silero: eugene / aidar (муж.), baya / kseniya / xenia (жен.)", False),
    "voice.tts.edge_voice": ("str", "Голос Microsoft (если engine = edge)", False),
    "voice.tts.reply_in_telegram": ("str", "Голосовые ответы в Telegram: never (только текст) / voice (голосом на голосовые) / always", False),
    "voice.pc.hotkey": ("str", "Голос на ПК: горячая клавиша «слушать» (voice.bat)", False),
    "voice.pc.mic": ("str", "Голос на ПК: микрофон (пусто — по умолчанию; номер из «voice.bat --mics»)", False),
    "voice.pc.silence_sec": ("str", "Голос на ПК: пауза в речи (сек), после которой команда считается сказанной. 0.8 — быстро, 1.5–2 — если обрывает на раздумьях", False),
    "voice.pc.max_command_sec": ("int", "Голос на ПК: максимальная длина одной команды, секунд", False),
    "voice.pc.conversation_sec": ("int", "Голос на ПК: сколько секунд после ответа можно говорить без имени ассистента (0 — только после его вопросов)", False),
    "voice.pc.conversation_mode_sec": ("int", "Голос на ПК: окно в «режиме беседы» («<имя>, режим беседы» / «хватит болтать»), секунд", False),
    "voice.pc.morning_report": ("bool", "Голос на ПК: утренний доклад вслух, когда впервые сели за компьютер", False),
    "voice.pc.night_from": ("int", "Ночной режим с (час): тише и без лишних напоминаний вслух", False),
    "voice.pc.night_to": ("int", "Ночной режим до (час)", False),
    "voice.pc.filler_sec": ("str", "Через сколько секунд молчания мозга сказать «Секунду…» (0 — никогда)", False),
    "voice.pc.screen_time.enabled": ("bool", "Экранное время: сколько и где вы за ПК — карточка на «Сегодня», «сколько сидел за компом», строка в вечернем итоге. Только имя программы и сайт, всё локально. Включается на лету (~20 с)", False),
    "voice.pc.screen_time.idle_min": ("int", "Экранное время: минут без мыши/клавиатуры = «отошёл» (5)", False),
    "voice.pc.screen_time.nudges": ("bool", "Экранное время: редкие подколы по факту (YouTube час подряд при дедлайне, игра в рабочее время, 6 ч без перерыва)", False),
    "voice.pc.screen_time.keep_days": ("int", "Экранное время: сколько дней хранить подробности (90)", False),
    "voice.pc.tidy_downloads_days": ("int", "Ночная уборка «Загрузок» (voice.bat): файлы старше N дней — в Загрузки/Разобрано; 0 — выключено. Рабочий стол — только по команде", False),
    "voice.pc.games": ("str", "Свои игры для авто-игрового режима: имена exe через запятую (популярные знаю сам)", False),
    "finance.main_account": ("str", "Основной счёт", False),
    "persona.style": ("str", "Характер: swag (с юмором) / neutral (по делу)", False),
    "persona.humor_level": ("int", "Уровень юмора 0–10 (0–2 без шуток, 6–8 сарказм по делу, 9–10 жёстко)", False),
    "persona.nicknames": ("str", "Как ещё вас звать, через запятую («шеф, босс»)", False),
    "persona.where": ("str", "Кто формулирует инициативные фразы: cloud / auto / local", False),
    "persona.voice_accents": ("bool", "Итог дня и подколы иногда голосовым (не чаще раза в день)", False),
    "cards.mode": ("str", "Картинки-карточки в Telegram: always (всегда) / important (важные + короткие карточки на траты и задачи) / never", False),
    "server.port": ("int", "Порт сайта (нужен перезапуск)", False),
    "google.enabled": ("bool", "Отправлять события в Google Календарь (только ассистент → Google)", False),
    "google.client_id": ("str", "Google OAuth Client ID (…apps.googleusercontent.com) — см. README «Google Календарь»", False),
    "google.client_secret": ("str", "Google OAuth Client secret", True),
    "google.calendar_id": ("str", "ID календаря в Google (пусто — основной)", False),
    "google.proxy": ("str", "Прокси для Google (пусто — берётся прокси Telegram, если задан)", False),
    "backup.enabled": ("bool", "Ежедневный бэкап базы", False),
    "backup.dir": ("str", "Папка бэкапов", False),
    "backup.extra_dir": ("str", "Вторая копия (другой диск / папка Яндекс.Диска)", False),
    "backup.keep_days": ("int", "Хранить бэкапы, дней", False),
    "setup.done": ("bool", "Мастер первого запуска пройден", False),
    "brain.ollama.num_ctx": ("int", "Размер контекста локальной модели", False),
    "brain.ollama.keep_alive": ("str", "Держать модель в памяти после ответа (2h / 0)", False),
    "brain.lmstudio.enabled": ("bool", "LM Studio — второй движок рядом с Ollama (адрес и модель — строки ниже)", False),
    "brain.lmstudio.base_url": ("str", "Адрес LM Studio (/v1 допишется сам, можно голый хост)", False),
    "brain.lmstudio.model": ("str", "Модель, загруженная в LM Studio (должна совпадать с запущенной)", False),
    "brain.lmstudio.use": ("str", "Что отдать LM Studio: main — основные ответы / small — мини-задачи (судья, уборка памяти)", False),
    "voice.enabled": ("bool", "Голосовые сообщения в Telegram распознавать", False),
    "voice.stt.device": ("str", "Устройство Whisper: cpu / cuda", False),
    "owner.timezone": ("str", "Часовой пояс (Europe/Moscow)", False),
}


def _get_path(raw: dict, path: str, default=None):
    cur = raw
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# Значения по умолчанию для ключей, которых может не быть в config.yaml: read_settings показывает
# именно то, что реально действует (иначе UI показывал бы выключенным включённое по умолчанию).
SETTINGS_DEFAULTS = {"brain.gemini.anonymize": True, "brain.cloud.max_tokens": 1024, "brain.cloud.timeout": 45}


def read_settings() -> dict:
    """Текущие значения редактируемых ключей (секреты маскируются)."""
    src = _config_src()
    with open(src, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out = []
    for key, (typ, label, secret) in EDITABLE.items():
        fallback = SETTINGS_DEFAULTS.get(key, "" if typ == "str" else (0 if typ == "int" else False))
        val = _get_path(raw, key, fallback)
        if val is None:
            val = ""
        shown = val
        if secret:
            # Секрет (API-ключ/токен) наружу не показываем вообще — ни его кусок, ни длину: раньше
            # здесь отдавались первые 4 и последние 3 символа, а 7 символов ключа — это уже помощь
            # перебору. Состояние видно по полю `set`: «задан» / «не задан» (так же его показывает UI).
            shown = "задан" if val else "не задан"
        out.append({"key": key, "type": typ, "label": label, "secret": secret, "value": shown, "set": bool(val)})
    return {"file": str(src), "exists": _config_file().exists(), "items": out}


def _yaml_scalar(val, typ: str) -> str:
    if typ == "bool":
        return "true" if val else "false"
    if typ == "int":
        return str(int(val))
    s = "" if val is None else str(val)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_settings(changes: dict[str, object]) -> list[str]:
    """Меняет значения в config.yaml построчно, сохраняя комментарии. Возвращает список изменённых ключей.

    Формат файла — 2–3 уровня вложенности с отступами по 2 пробела (как в config.example.yaml)."""
    path = _config_file()
    if not path.exists():
        import shutil
        shutil.copy(ROOT / "config.example.yaml", path)
    lines = path.read_text(encoding="utf-8").splitlines()
    changed: list[str] = []
    for key, val in changes.items():
        if key not in EDITABLE:
            continue
        typ, _, secret = EDITABLE[key]
        # маска секрета («задан»/«не задан», старые маски с «…» и «•••») или пусто — не трогаем,
        # иначе фронт, отправляющий то, что получил, затёр бы настоящий ключ
        if secret and (val is None or (isinstance(val, str) and ("…" in val or val.strip().lower() in ("", "•••", "задан", "не задан")))):
            continue
        if typ == "int":
            try:
                val = int(str(val).strip() or 0)
            except ValueError:
                continue
        if typ == "bool":
            val = str(val).lower() in ("1", "true", "yes", "on", "да")
        parts = key.split(".")
        # ищем строку: спускаемся по уровням, следя за отступами
        idx, depth, i = -1, 0, 0
        while i < len(lines) and depth < len(parts):
            line = lines[i]
            stripped = line.lstrip(" ")
            indent = len(line) - len(stripped)
            if stripped and not stripped.startswith("#") and indent == depth * 2 and stripped.split(":")[0].strip() == parts[depth]:
                if depth == len(parts) - 1:
                    idx = i
                    break
                depth += 1
            elif stripped and not stripped.startswith("#") and indent < depth * 2:
                break  # вышли из секции — ключа нет
            i += 1
        rendered = f"{'  ' * (len(parts) - 1)}{parts[-1]}: {_yaml_scalar(val, typ)}"
        if idx >= 0:
            old = lines[idx]
            comment = ""
            # сохраняем хвостовой комментарий, если он есть и не внутри кавычек
            m = __import__("re").search(r'\s+#.*$', old.split('"')[-1] if old.count('"') % 2 == 0 else "")
            if m:
                comment = m.group(0)
            lines[idx] = rendered + comment
        else:
            # ключа нет (старый config.yaml без новой настройки) — спускаемся по секциям, недостающие создаём,
            # значение ставим в конец самой глубокой. Работает на любую глубину: voice.pc.screen_time.enabled — 4 уровня
            sec_start, sec_end, depth_i = -1, len(lines), 0
            for depth_i, part in enumerate(parts[:-1]):
                ind = "  " * depth_i
                rng = range(sec_start + 1, sec_end)
                found = next((n for n in rng if lines[n].startswith(ind) and not lines[n].startswith(ind + " ")
                              and not lines[n].lstrip().startswith("#") and lines[n].split(":")[0].strip() == part), -1)
                if found < 0:
                    # создаём секцию в конце родительской (перед пустыми строками-хвостом)
                    ins = sec_end
                    while ins > sec_start + 1 and not lines[ins - 1].strip():
                        ins -= 1
                    if depth_i == 0 and ins > 0 and lines[ins - 1].strip():
                        lines.insert(ins, ""); ins += 1
                    lines.insert(ins, f"{ind}{part}:")
                    found = ins
                    sec_end = found + 1
                # граница секции: до первой непустой строки с отступом ≤ текущего
                e = found + 1
                while e < len(lines) and (not lines[e].strip() or lines[e].lstrip().startswith("#") or lines[e].startswith(ind + "  ")):
                    e += 1
                sec_start, sec_end = found, e
            ins = sec_end
            while ins > sec_start + 1 and not lines[ins - 1].strip():
                ins -= 1
            lines.insert(ins, rendered)
        changed.append(key)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def setup_done() -> bool:
    """Мастер первого запуска пройден? Критерий: есть config.yaml и в нём заполнен режим мозга и (токен ИЛИ явный отказ от Telegram)."""
    path = _config_file()
    if not path.exists():
        return False
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return False
    return bool(_get_path(raw, "setup.done", False))
