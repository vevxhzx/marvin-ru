"""Загрузка настроек из config.yaml (с запасным вариантом config.example.yaml)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


class _Node:
    """Удобный доступ через точку: cfg.telegram.token."""

    def __init__(self, d: dict[str, Any]):
        for k, v in d.items():
            setattr(self, k, _Node(v) if isinstance(v, dict) else v)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __repr__(self) -> str:  # pragma: no cover
        return f"_Node({self.__dict__})"


def _load() -> _Node:
    path = ROOT / "config.yaml"
    if not path.exists():
        path = ROOT / "config.example.yaml"
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
    return _Node(raw)


cfg = _load()
DB_PATH = DATA_DIR / "assistant.db"
TZ = cfg.owner.timezone if hasattr(cfg, "owner") else "Europe/Moscow"


# ---------------------------------------------------------------- редактирование config.yaml с сайта
# Какие ключи можно менять через страницу настроек: путь → (тип, подпись, секрет?)
EDITABLE: dict[str, tuple[str, str, bool]] = {
    "assistant.name": ("str", "Имя ассистента (так он представляется и откликается голосом)", False),
    "assistant.name_latin": ("str", "Имя латиницей (заголовки окон, логи)", False),
    "assistant.aliases": ("str", "Другие варианты имени через запятую", False),
    "owner.name": ("str", "Как к вам обращаться", False),
    "telegram.token": ("str", "Токен Telegram-бота (от @BotFather)", True),
    "telegram.owner_id": ("int", "Ваш Telegram ID (от @userinfobot)", False),
    "telegram.morning_digest": ("str", "Утренний дайджест (ЧЧ:ММ, пусто — выключить)", False),
    "telegram.proxy": ("str", "Прокси для Telegram (если api.telegram.org недоступен)", False),
    "brain.mode": ("str", "Режим мозга: local / hybrid / cloud", False),
    "brain.ollama.url": ("str", "Адрес Ollama", False),
    "brain.ollama.model": ("str", "Модель Ollama", False),
    "brain.ollama.embed_model": ("str", "Модель эмбеддингов (смысловой поиск)", False),
    "brain.ollama.vision_model": ("str", "Модель зрения (скриншоты, чеки): qwen2.5vl:3b / llava / moondream — пусто, если не ставили", False),
    "brain.vision.where": ("str", "Где смотреть картинки: auto (ПК, при сбое — облако; чеки только ПК) / cloud (всегда облако, быстро) / local (только ПК)", False),
    "brain.vision.allow_cloud": ("bool", "Скриншоты «что на экране» можно отправлять в облако, если нет локальной модели зрения (чеки — никогда)", False),
    "brain.cloud.provider": ("str", "Провайдер облака", False),
    "brain.cloud.api_key": ("str", "Ключ облака", True),
    "brain.cloud.model": ("str", "Модель облака (пусто — по умолчанию у провайдера)", False),
    "brain.cloud.base_url": ("str", "Адрес API (только для custom)", False),
    "brain.cloud.proxy": ("str", "Прокси для облака (обычно не нужен)", False),
    "brain.gemini.auto": ("bool", "Разговор и общие вопросы — в облако (иначе только по слову «облако, …»)", False),
    "brain.gemini.api_key": ("str", "Ключ Google Gemini (только если провайдер gemini)", True),
    "brain.gemini.model": ("str", "Модель Google Gemini (auto)", False),
    "brain.gemini.proxy": ("str", "Прокси для Google Gemini", False),
    "brain.gemini.anonymize": ("bool", "Обезличивать текст перед отправкой в облако", False),
    "brain.gemini.mark_source": ("bool", "Помечать источник ответа (⚡/🧠/☁️)", False),
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
    "voice.pc.games": ("str", "Свои игры для авто-игрового режима: имена exe через запятую (популярные знаю сам)", False),
    "finance.main_account": ("str", "Основной счёт", False),
    "persona.style": ("str", "Характер: swag (с юмором) / neutral (по делу)", False),
    "persona.humor_level": ("int", "Уровень юмора 0–10", False),
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


def read_settings() -> dict:
    """Текущие значения редактируемых ключей (секреты маскируются)."""
    path = ROOT / "config.yaml"
    src = path if path.exists() else ROOT / "config.example.yaml"
    with open(src, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out = []
    for key, (typ, label, secret) in EDITABLE.items():
        val = _get_path(raw, key, "" if typ == "str" else (0 if typ == "int" else False))
        if val is None:
            val = ""
        shown = val
        if secret and val:
            shown = str(val)[:4] + "…" + str(val)[-3:] if len(str(val)) > 8 else "•••"
        out.append({"key": key, "type": typ, "label": label, "secret": secret, "value": shown, "set": bool(val)})
    return {"file": str(src), "exists": path.exists(), "items": out}


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
    path = ROOT / "config.yaml"
    if not path.exists():
        import shutil
        shutil.copy(ROOT / "config.example.yaml", path)
    lines = path.read_text(encoding="utf-8").splitlines()
    changed: list[str] = []
    for key, val in changes.items():
        if key not in EDITABLE:
            continue
        typ, _, secret = EDITABLE[key]
        if secret and (val is None or (isinstance(val, str) and ("…" in val or val.strip() in ("", "•••")))):
            continue  # маска/пусто для секрета — не трогаем
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
            # ключа нет — добавляем в конец нужной секции (или создаём секцию)
            sec_i = next((n for n, l in enumerate(lines) if l.split(":")[0].strip() == parts[0] and not l.startswith(" ")), -1)
            if sec_i < 0:
                lines += ["", f"{parts[0]}:"]
                sec_i = len(lines) - 1
            end = sec_i + 1
            while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip() or lines[end].startswith("#")):
                end += 1
            while end > sec_i + 1 and not lines[end - 1].strip():
                end -= 1
            if len(parts) == 3:
                sub_i = next((n for n in range(sec_i + 1, end) if lines[n].startswith("  ") and not lines[n].startswith("    ") and lines[n].split(":")[0].strip() == parts[1]), -1)
                if sub_i < 0:
                    lines.insert(end, f"  {parts[1]}:"); end += 1
                    lines.insert(end, rendered)
                else:
                    e2 = sub_i + 1
                    while e2 < end and lines[e2].startswith("    "):
                        e2 += 1
                    lines.insert(e2, rendered)
            else:
                lines.insert(end, rendered)
        changed.append(key)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def setup_done() -> bool:
    """Мастер первого запуска пройден? Критерий: есть config.yaml и в нём заполнен режим мозга и (токен ИЛИ явный отказ от Telegram)."""
    path = ROOT / "config.yaml"
    if not path.exists():
        return False
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        return False
    return bool(_get_path(raw, "setup.done", False))
