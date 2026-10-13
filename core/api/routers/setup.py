"""Мастер первой установки: серверная часть страницы `core/api/setup.html`.

Страница самодостаточная (свой HTML+JS, без сборки) и зовёт 11 адресов этого
роутера: `/state`, `/hardware`, `/ollama`, `/ollama/pull` (+ прогресс
`/ollama/pull/{model}`), `/providers`, `/check/cloud`, `/check/telegram`,
`/telegram/owner`, `/save`, `/restart`. Пока адресов не было в коде, первый запуск
у любого нового человека упирался в мёртвый мастер: `core/api/app.py::spa`
редиректит на `/setup` любую страницу, пока `setup_done()` ложно.

Правила, из-за которых модуль написан именно так:

* **Только свой компьютер.** Отдельных проверок здесь нет — `/api/setup/` и `/setup`
  уже в `LOCAL_ONLY_EARLY_PREFIXES`/`LOCAL_ONLY_PREFIXES` (`core/api/auth.py`):
  снаружи 403 даже с ключом, 401 без ключа. Модуль не должен это ломать, поэтому
  новых «разрешений» тут не заводим.
* **Секреты.** Приходят токен Telegram и ключи облака. Пишем их только через
  `config.write_settings()` (он же не даёт затереть ключ маской), наружу отдаём
  только «задан/не задан» (как `config.read_settings()`), в лог не пишем. Отдельно
  режем токен из логов httpx — адрес Bot API содержит токен целиком.
* **Никаких блокировок в event loop.** Всё долгое — в поток через
  `asyncio.to_thread` (паттерн `core/api/routers/chat.py`): скачивание модели на
  5–10 минут, ожидание сообщения от хозяина до 90 секунд, запись config.yaml.
* **Честность.** Ни один ответ не говорит «готово» без настоящей проверки:
  железо читается через psutil, модели — живым запросом в Ollama, ключ облака и
  токен Telegram — настоящей проверкой с внятной ошибкой по-русски.
* **Лёгкий старт.** psutil (он идёт в SLIM-сборку как запрещённый пакет) импортируется
  лениво, как и мозг: `core/api/app.py` импортирует все роутеры при старте ядра.

Подключение: `core/api/routers/__init__.py` → `setup.register(app)` ДО `system`
(инварианты регистрации — в докстринге `__init__.py`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...config import ROOT, read_settings, setup_done, write_settings

router = APIRouter(prefix="/api/setup")
log = logging.getLogger("jarvis.api.setup")

# сколько ждём сообщения от хозяина в Telegram (страница пишет «до 90 секунд»)
OWNER_WAIT_SEC = 90.0
# сколько ждём живой ответ Ollama/облака/Telegram
OLLAMA_TIMEOUT = 3.0
HTTP_TIMEOUT = 15.0
CHAT_TIMEOUT = 30.0

# ---------------- секреты ----------------
# Единственные ключи-секреты, которые мастер знает (см. EDITABLE в core/config.py).
_SECRET_KEYS = ("telegram.token", "brain.cloud.api_key", "brain.gemini.api_key")
# Что мастер имеет право записать. Всё остальное (server.password, google.*, …) —
# не его дело: мастер открыт первому встречному, лишние кнопки ему не нужны.
_SAVE_ALLOWED = {
    "assistant.name", "assistant.name_latin", "assistant.aliases",
    "owner.name",
    "persona.style", "persona.humor_level",
    "brain.mode", "brain.ollama.model",
    "brain.cloud.provider", "brain.cloud.api_key", "brain.cloud.model", "brain.cloud.base_url", "brain.cloud.proxy",
    "brain.gemini.api_key", "brain.gemini.model", "brain.gemini.proxy",
    "brain.vision.where",
    "telegram.token", "telegram.owner_id", "telegram.proxy",
    "setup.done",
}
# Настройки, которые ядро читает один раз при старте (module-level константы),
# поэтому без перезапуска не применятся — честно говорим об этом в ответе /save.
_RESTART_PREFIXES = ("telegram.", "backup.", "server.", "assistant.")
# Что применяется на лету теми же вызовами, что и в PUT /api/settings (system.py).
_LIVE_PREFIXES = ("brain.cloud.", "brain.gemini.", "brain.mode", "brain.vision.", "brain.sorter.",
                  "owner.", "persona.", "brain.ollama.small_")
# Что показываем в /state без секретов (страница подставляет assistant.name и owner.name)
_STATE_KEYS = ("assistant.name", "assistant.name_latin", "owner.name", "persona.style", "brain.mode",
               "brain.ollama.model", "brain.cloud.provider", "telegram.owner_id")
_MODEL_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$")
_TG_TOKEN_RX = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
_TG_URL_RX = re.compile(r"/bot\d+:[A-Za-z0-9_-]{5,}")

# Модели для шага «локальная модель». size_gb — вес на диске (как в Ollama),
# min_vram — сколько видеопамяти нужно, чтобы модель работала быстро (вес + запас
# под контекст). Числа ориентировочные: мастер показывает оценку, а не паспорт,
# «не влезет в вашу память» — предупреждение, а не запрет.
LOCAL_MODELS = (
    {"id": "qwen2.5:3b", "title": "Лёгкая: быстрая даже на слабой видеокарте", "size_gb": 1.9, "min_vram": 4},
    {"id": "gemma3:4b", "title": "Универсальная: хороша с текстом и кодом", "size_gb": 3.3, "min_vram": 5},
    {"id": "qwen3:4b", "title": "Умная: думает перед ответом, отвечает быстрее", "size_gb": 2.6, "min_vram": 5},
    {"id": "qwen2.5:7b", "title": "Большая: заметно умнее, нужна видеокарта от 6 ГБ", "size_gb": 4.7, "min_vram": 7},
    {"id": "gemma3:12b", "title": "Самая большая: нужна видеокарта от 10 ГБ", "size_gb": 8.1, "min_vram": 11},
)
# Gemini в core/brain/llm/base.py::PROVIDERS нет (там только OpenAI-совместимые),
# поэтому карточку провайдера для мастера дописываем здесь.
_GEMINI = {"title": "Google Gemini", "free": True, "base_url": "https://generativelanguage.googleapis.com/v1beta",
           "model": "gemini-2.5-flash", "key_url": "https://aistudio.google.com/app/apikey"}
_PROVIDER_ORDER = ("groq", "openrouter", "nvidia", "deepseek", "gemini", "custom")


def register(app) -> None:
    app.include_router(router)
    _install_token_log_filter()


# ============================ секреты в логах ============================
class _RedactTelegramToken(logging.Filter):
    """httpx пишет каждый запрос на INFO, а адрес Bot API — это `…/bot<токен>/getMe`:
    без фильтра токен бота оседает в logs/*.log. Закрываем адрес, не теряя сам факт запроса."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - кривое форматирование — не наша забота
            return True
        if _TG_URL_RX.search(msg):
            record.msg = _TG_URL_RX.sub("/bot<токен>", msg)
            record.args = ()
        return True


def _install_token_log_filter() -> None:
    lg = logging.getLogger("httpx")
    if not any(isinstance(f, _RedactTelegramToken) for f in lg.filters):
        lg.addFilter(_RedactTelegramToken())


# ============================ HTTP-клиенты (те же, что у мозга) ============================
def _local_client(timeout: float) -> httpx.AsyncClient:
    """Клиент локальной Ollama — тот же, что у мозга (`core/brain/llm/base.py`):
    без системного прокси и VPN. Отдельная обёртка нужна только чтобы тесты
    подставляли транспорт (httpx.MockTransport)."""
    from ...brain.llm import base as _base
    return _base._local_client(timeout)


def _sync_client(timeout: float) -> httpx.Client:
    """Синхронный клиент Ollama — для стримового скачивания модели в потоке
    (прецедент — `core/brain/llm/ollama.py::evict_ollama_main`)."""
    return httpx.Client(timeout=timeout, trust_env=False)


def _cloud_client(timeout: float, proxy: str | None = None) -> httpx.AsyncClient:
    """Клиент облака — тот же, что у `core/brain/llm/cloud.py::_cloud_client`
    (trust_env=False, socks/http-прокси по настройке)."""
    from ...brain.llm import cloud as _cloud
    return _cloud._cloud_client(timeout, proxy)


def _proxy_client(timeout: float, proxy: str | None = None) -> httpx.AsyncClient:
    """Клиент Telegram (та же схема, что облачный: без системного прокси, со своим)."""
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10), trust_env=False, proxy=proxy)


def _sync_proxy_client(timeout: float, proxy: str | None = None) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout, connect=10), trust_env=False, proxy=proxy)


def _bad_proxy() -> str:
    return "прокси указан неверно (нужен socks5:// или http:// с адресом и портом)"


# ============================ /state ============================
@router.get("/state")
async def state():
    """Честная картина: мастер пройден ли, что уже настроено, какая модель скачана.

    Секретов в ответе нет вообще: у секретных ключей — только булевы флаги в `keys`
    (так же, как `config.read_settings()` отдаёт «задан/не задан»).
    """
    items = {i["key"]: i for i in read_settings()["items"]}
    settings = {k: {"value": items[k]["value"]} for k in _STATE_KEYS if k in items}
    keys = {k: bool(items[k]["set"]) for k in _SECRET_KEYS if k in items}
    running, models = await _probe_tags()
    from ...brain import llm
    want = (llm.OLLAMA_MODEL or "").strip()
    have = _have_model(models, want)
    return {
        "done": setup_done(),
        "settings": settings,
        "keys": keys,
        "ollama": {
            "running": running,
            "models": models,
            "model": want,
            # та же проверка, что llm.embed_available(), но по уже полученному
            # списку моделей — без второго запроса к Ollama
            "embed_ready": any(m.split(":")[0] == (llm.EMBED_MODEL or "").split(":")[0] for m in models),
            "have_model": bool(want) and have,
        },
        "restart_required": bool(setup_done() and not (await llm.ollama_available())),
    }


def _have_model(models: list[str], want: str) -> bool:
    """Есть ли модель в Ollama. `qwen2.5:3b` == `qwen2.5:3b`, но не `qwen2.5:7b`."""
    if not want:
        return False
    base, _, tag = want.partition(":")
    tag = tag or "latest"
    for m in models:
        mbase, _, mtag = m.partition(":")
        if mbase == base and (mtag or "latest") == tag:
            return True
    return False


# ============================ /hardware ============================
def _gpu_sync() -> tuple[str, Optional[float]]:
    """Видеокарта и её память — только если это действительно можно узнать (nvidia-smi).
    Ничего не выдумываем: без nvidia-smi вернём пусто, мастер покажет «не найдена»."""
    exe = shutil.which("nvidia-smi") or r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    try:
        r = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return "", None
    if r.returncode != 0:
        return "", None
    first = (r.stdout or "").strip().splitlines()
    if not first:
        return "", None
    name, _, mem = first[0].partition(",")
    try:
        return name.strip(), round(int(mem.strip()) / 1024, 1)
    except ValueError:
        return name.strip(), None


def _hardware_sync() -> dict:
    """Реальные цифры машины. psutil импортируется здесь: в SLIM-сборке его нет
    (tests/test_slim_imports.py) — тогда показываем то, что узнать смогли, и честно говорим об этом."""
    notes: list[str] = []
    ram_gb: Optional[float] = None
    cpu = (platform.processor() or platform.machine() or "").strip()
    cores = ""
    try:
        import psutil
        ram_gb = round(psutil.virtual_memory().total / 2 ** 30, 1)
        phys, logical = psutil.cpu_count(logical=False), psutil.cpu_count()
        cores = f"{phys or logical} ядер" if (phys or logical) else ""
    except Exception:
        notes.append("не смог прочитать данные о процессоре и памяти (psutil) — показываю минимум")
    gpu, vram_gb = _gpu_sync()
    if not gpu:
        notes.append("видеокарту определить не удалось — если она есть, проверьте по её названию в диспетчере устройств")
    free_gb = None
    try:
        free_gb = round(shutil.disk_usage(ROOT).free / 2 ** 30, 1)
    except Exception:  # pragma: no cover - диск всегда на месте
        pass
    if free_gb is not None and free_gb < 10:
        notes.append(f"на диске осталось {free_gb} ГБ — для локальной модели нужно 5–10 ГБ")
    installed = _ollama_installed_sync()
    return {"cpu": cpu, "cores": cores, "ram_gb": ram_gb, "gpu": gpu, "vram_gb": vram_gb,
            "disk_free_gb": free_gb, "ollama": installed, "ollama_running": False,
            "system": platform.system(), "notes": notes}


def _recommend(hw: dict, ollama_running: bool) -> dict:
    """Что предложить по этому железу. Правило простое и объясняемое: локально — когда
    видеопамяти хватает на модель целиком, иначе «компьютер + облако», а совсем без
    видеокарты — облако (но с честным предупреждением, что личные данные уйдут провайдеру)."""
    vram = float(hw.get("vram_gb") or 0)
    ram = float(hw.get("ram_gb") or 0)
    models = [dict(m) for m in LOCAL_MODELS]
    fit = [m for m in models if vram >= m["min_vram"]]
    model = (fit[-1] if fit else models[0])["id"]
    if vram >= 7:
        mode = "local"
        why = (f"Видеокарты хватает на {model} целиком — можно работать полностью на этом компьютере, "
               "в интернет ничего не уходит. Ответы будут на своём железе.")
    elif vram >= 4 or ram >= 16:
        mode = "hybrid"
        why = ("Личное (деньги, календарь, заметки, люди) — локально, общие вопросы — в облако. "
               "Так быстрее и умнее всего, а приватные записи всё равно никуда не уходят.")
    else:
        mode = "cloud"
        why = ("Видеокарты нет или она совсем слабая: локальная модель будет думать минутами. "
               "Беру облако — работает быстро, но всё, что вы пишете, уходит провайдеру; "
               "личное лучше оставить в заметках, а не в общих вопросах.")
    notes = list(hw.get("notes") or [])
    if hw.get("ollama") and not ollama_running:
        notes.append("Ollama установлена, но не запущена — запустите её из меню «Пуск»")
    elif not hw.get("ollama"):
        notes.append("Ollama не установлена — бесплатная программа с ollama.com/download, ставится за минуту")
    return {"mode": mode, "model": model, "why": why, "all": models,
            "effective_vram": round(vram, 1), "notes": notes}


@router.get("/hardware")
async def hardware():
    """Железо и рекомендация режима. Считаем в потоке: psutil и nvidia-smi блокирующие."""
    hw = await asyncio.to_thread(_hardware_sync)
    running, _models = await _probe_tags()
    hw["ollama_running"] = running
    rec = _recommend(hw, running)
    hw["notes"] = list(hw["notes"]) + [n for n in rec["notes"]]
    rec.pop("notes", None)
    return {"hardware": hw, "recommend": rec}


# ============================ /ollama и скачивание ============================
def _ollama_installed_sync() -> bool:
    """Стоит ли Ollama на компьютере (программа, не модель)."""
    if shutil.which("ollama"):
        return True
    return any(Path(p).exists() for p in (
        r"C:\Program Files\Ollama\ollama.exe",
        r"C:\Users\%s\AppData\Local\Programs\Ollama\ollama.exe" % os.environ.get("USERNAME", ""),
        "/Applications/Ollama.app/Contents/Resources/ollama",
        "/usr/local/bin/ollama",
        "/usr/bin/ollama",
    ))


async def _probe_tags() -> tuple[bool, list[str]]:
    """Живая Ollama: отвечает ли и какие модели скачаны (GET /api/tags)."""
    from ...brain import llm
    try:
        async with _local_client(OLLAMA_TIMEOUT) as c:
            r = await c.get(f"{llm.OLLAMA_URL}/api/tags")
            if r.status_code != 200:
                return False, []
            raw = (r.json() or {}).get("models") or []
            return True, sorted({str(m.get("name") or "") for m in raw if m.get("name")})
    except Exception as e:
        log.debug("Ollama не ответила: %s: %s", type(e).__name__, str(e)[:120])
        return False, []


@router.get("/ollama")
async def ollama():
    """Оllama установлена / запущена / какие модели уже скачаны. Никогда не 500:
    страница ждёт этот ответ даже когда Ollama нет."""
    running, models = await _probe_tags()
    installed = await asyncio.to_thread(_ollama_installed_sync) or running
    from ...brain import llm
    return {"running": running, "installed": bool(installed), "models": models,
            "url": llm.OLLAMA_URL, "model": llm.OLLAMA_MODEL}


# прогресс скачивания: {model: {status, done, total, error}}
_PULLS: dict[str, dict] = {}
_PULL_LOCK = threading.Lock()


def _pull_slot(model: str) -> dict:
    with _PULL_LOCK:
        return _PULLS.setdefault(model, {"status": "idle", "done": 0, "total": 0, "error": ""})


def _download_model(model: str) -> None:
    """Скачать модель через Ollama (POST /api/pull, поток NDJSON с прогрессом).

    Блокирующий httpx — поэтому вызывается только из потока (`asyncio.to_thread`).
    Ошибку не поднимаем наружу: статус «error» с текстом читает страница.
    """
    from ...brain import llm
    st = _pull_slot(model)
    st.update({"status": "downloading", "done": 0, "total": 0, "error": ""})
    try:
        with _sync_client(3600) as c, c.stream("POST", f"{llm.OLLAMA_URL}/api/pull",
                                                json={"model": model, "stream": True}) as r:
            if r.status_code != 200:
                raise RuntimeError(f"Ollama ответила {r.status_code}: {r.text[:120]}")
            for line in r.iter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise RuntimeError(str(chunk["error"])[:160])
                st["done"] = int(chunk.get("completed") or st["done"])
                st["total"] = int(chunk.get("total") or st["total"])
                if chunk.get("status"):
                    st["status"] = str(chunk["status"])
    except Exception as e:
        st["status"] = "error"
        st["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        log.warning("не скачалась модель %s: %s", model, st["error"])
        return
    st.update({"status": "success", "done": st["total"] or 1, "error": ""})
    log.info("модель %s скачана", model)


class PullIn(BaseModel):
    model: str = Field("", max_length=120)


@router.post("/ollama/pull")
async def ollama_pull(p: PullIn):
    """Запустить скачивание модели. Отвечает сразу, прогресс — по /ollama/pull/{model}."""
    model = (p.model or "").strip()
    if not _MODEL_RX.match(model):
        raise HTTPException(400, "Не похоже на имя модели Ollama (например qwen2.5:3b)")
    _running, models = await _probe_tags()
    if _have_model(models, model):
        st = _pull_slot(model)
        st.update({"status": "success", "done": 1, "total": 1, "error": ""})
        return {"ok": True, "already": True, "model": model, "detail": "модель уже скачана"}
    slot = _pull_slot(model)
    with _PULL_LOCK:
        if slot["status"] == "downloading":
            return {"ok": True, "already": True, "model": model, "detail": "модель уже качается"}
    # долгая операция — в поток, event loop свободен (как в core/api/routers/chat.py)
    asyncio.create_task(asyncio.to_thread(_download_model, model))
    log.info("скачиваю модель %s", model)
    return {"ok": True, "already": False, "model": model, "detail": "скачивание пошло в фоне"}


@router.get("/ollama/pull/{model}")
async def ollama_pull_status(model: str):
    """Прогресс скачивания: {status, done, total, error} (страница опрашивает раз в 1.2 с)."""
    return dict(_pull_slot(model))


# ============================ /providers ============================
@router.get("/providers")
async def providers():
    """Какие облачные провайдеры есть и что уже настроено. Ключи наружу не уходят —
    только флаг `configured` (задан/не задан), как в `config.read_settings()`."""
    from ...brain import llm
    items = {i["key"]: i for i in read_settings()["items"]}
    out = []
    for pid in _PROVIDER_ORDER:
        info = dict(llm.PROVIDERS.get(pid) or _GEMINI)
        out.append({
            "id": pid,
            "title": info.get("title") or pid,
            "free": info.get("free"),
            "base_url": info.get("base_url") or "",
            "model": info.get("model") or "",
            "key_url": info.get("key_url") or "",
            "configured": bool(items.get("brain.cloud.api_key", {}).get("set")) if pid != "gemini"
            else bool(items.get("brain.gemini.api_key", {}).get("set")),
            "active": str(getattr(llm, "CLOUD_PROVIDER", "") or "") == pid,
        })
    return out


# ============================ /check/cloud ============================
class CloudCheckIn(BaseModel):
    provider: str = Field("groq", max_length=40)
    api_key: str = Field("", max_length=400)
    model: str = Field("", max_length=200)
    base_url: str = Field("", max_length=400)
    proxy: str = Field("", max_length=400)


def _explain_cloud(e: Optional[Exception], r, name: str, model: str, base: str) -> str:
    """Человеческое объяснение ошибки облака. Тексты — те же, что у
    `core/brain/llm/cloud.py::_explain_cloud_error`, но мастер проверяет ключ, который
    ещё НЕ записан в настройки, а та функция читает глобальные настройки мозга
    (текущий провайдер/адрес/ключ) — поэтому тексты продублированы здесь, с именем
    и адресом из запроса."""
    if r is not None:
        try:
            msg = (r.json().get("error") or {}).get("message") or r.text[:200]
        except Exception:
            msg = r.text[:200]
        if r.status_code in (401, 403):
            return f"{name}: ключ не принят ({r.status_code}): {msg}"
        if r.status_code == 404:
            return f"{name}: модель «{model}» не найдена (404). Проверьте название модели или оставьте пустым."
        if r.status_code == 429:
            return f"{name}: лимит бесплатных запросов исчерпан (429). Подождите или смените модель/провайдера."
        if r.status_code == 402:
            return f"{name}: закончились кредиты (402)."
        return f"{name} ответил {r.status_code}: {msg}"
    if isinstance(e, (httpx.ConnectError, httpx.ProxyError, httpx.TimeoutException, httpx.RemoteProtocolError)):
        host = base.split("//")[-1].split("/")[0] if "//" in base else base
        return (f"{name}: не достучался до {host} ни напрямую, ни через прокси ({type(e).__name__}). "
                "Включите VPN или укажите прокси (тот же, что у Telegram).")
    return f"{name}: {type(e).__name__}: {e}" if e else f"{name}: неизвестная ошибка"


@router.post("/check/cloud")
async def check_cloud(p: CloudCheckIn):
    """Настоящая проверка ключа: спрашиваем у провайдера список моделей (дёшево),
    а если сервера без /models — шлём один короткий запрос к модели."""
    from ...brain import llm
    pid = (p.provider or "").strip().lower()
    info = dict(llm.PROVIDERS.get(pid) or _GEMINI)
    name = str(info.get("title") or pid)
    if pid not in _PROVIDER_ORDER:
        return {"ok": False, "detail": f"Провайдер «{p.provider}» неизвестен — выберите из списка."}
    key = (p.api_key or "").strip()
    if not key:
        return {"ok": False, "detail": "Вставьте ключ — без него проверить нечего."}
    proxy = (p.proxy or "").strip() or None
    base = (p.base_url or "").strip() or str(info.get("base_url") or "")
    base = base.rstrip("/")
    if not base:
        return {"ok": False, "detail": "Для своего провайдера нужен адрес API (например http://127.0.0.1:1234/v1)."}
    model = (p.model or "").strip() or str(info.get("model") or "")
    headers = ({"x-goog-api-key": key} if pid == "gemini"
               else {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    path = "/models" if pid == "gemini" else "/chat/completions"
    url = base if pid == "gemini" else f"{base}/models"
    try:
        async with _cloud_client(HTTP_TIMEOUT, proxy) as c:
            r = await c.get(url, headers=headers)
            if r.status_code == 200:
                data = (r.json() or {}).get("data") or (r.json() or {}).get("models") or []
                ids = [str(m.get("id") or m.get("name") or "") for m in data]
                ids = [i.replace("models/", "") for i in ids if i]
                return {"ok": True, "detail": f"{name}: ключ принят, моделей доступно {len(ids)}.",
                        "provider": pid, "models": ids[:20]}
            if r.status_code not in (404, 405):
                return {"ok": False, "detail": _explain_cloud(None, r, name, model, base), "provider": pid}
    except Exception as e:
        if isinstance(e, (httpx.ProxyError, ImportError)):
            return {"ok": False, "detail": _bad_proxy(), "provider": pid, "need_proxy": True}
        return {"ok": False, "detail": _explain_cloud(e, None, name, model, base), "provider": pid,
                "need_proxy": isinstance(e, (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError))}
    # сервера без /models — проверяем настоящим коротким запросом
    body = ({"contents": [{"parts": [{"text": "Ответь одним словом: работаешь?"}]}], "maxOutputTokens": 8}
            if pid == "gemini" else
            {"model": model, "messages": [{"role": "user", "content": "Ответь одним словом: работаешь?"}],
             "max_tokens": 8, "temperature": 0})
    try:
        async with _cloud_client(CHAT_TIMEOUT, proxy) as c:
            r = await c.post(f"{base}{path}", json=body, headers=headers)
        if r.status_code == 200:
            return {"ok": True, "detail": f"{name}: ключ принят, модель {model or 'по умолчанию'} ответила.",
                    "provider": pid}
        return {"ok": False, "detail": _explain_cloud(None, r, name, model, base), "provider": pid}
    except Exception as e:
        if isinstance(e, (httpx.ProxyError, ImportError)):
            return {"ok": False, "detail": _bad_proxy(), "provider": pid, "need_proxy": True}
        return {"ok": False, "detail": _explain_cloud(e, None, name, model, base), "provider": pid,
                "need_proxy": isinstance(e, (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError))}


# ============================ /check/telegram и /telegram/owner ============================
class TgCheckIn(BaseModel):
    token: str = Field("", max_length=200)
    proxy: str = Field("", max_length=400)


def _tg_bad_token(token: str) -> str:
    if not token.strip():
        return "Вставьте токен от @BotFather — он выглядит как 123456789:AAF…"
    return "Токен выглядит не так: у @BotFather он вида 123456789:AAF… (числа, двоеточие, буквы). Проверьте, что скопировали целиком."


def _explain_tg(e: Optional[Exception], r, proxy: Optional[str]) -> str:
    """Почему Telegram не ответил. Тексты — по образцу `_explain_gemini_error`
    (`core/brain/llm/cloud.py`): что делать человеку, а не код ошибки."""
    if r is not None:
        if r.status_code == 401:
            return "Telegram не принял токен (401): проверьте, что скопировали его целиком и он ещё не отозван."
        if r.status_code == 404:
            return "Telegram не знает такой токен (404). Создайте нового бота у @BotFather и попробуйте снова."
        return f"Telegram ответил {r.status_code}: {r.text[:160]}"
    if isinstance(e, (httpx.ProxyError, ImportError)):
        return _bad_proxy()
    if isinstance(e, (httpx.ConnectError, httpx.RemoteProtocolError)):
        return ("Не достучался до api.telegram.org. Включите VPN или укажите прокси для Telegram "
                "(тот же, что в v2rayN/Nekoray → «Local socks port»).")
    if isinstance(e, httpx.TimeoutException):
        return "Telegram не ответил за 15 секунд. Проверьте интернет или укажите прокси."
    return f"Telegram: {type(e).__name__}: {e}" if e else "Telegram: неизвестная ошибка"


def _tg_client_kwargs(proxy: Optional[str]) -> dict:
    return {"timeout": httpx.Timeout(HTTP_TIMEOUT, connect=10), "trust_env": False, "proxy": proxy}


@router.post("/check/telegram")
async def check_telegram(p: TgCheckIn):
    """Живая проверка бота: getMe. Токен в ответе и в логе не появляется."""
    token = (p.token or "").strip()
    if not _TG_TOKEN_RX.match(token):
        return {"ok": False, "detail": _tg_bad_token(token)}
    proxy = (p.proxy or "").strip() or None
    try:
        async with _proxy_client(HTTP_TIMEOUT, proxy) as c:
            r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
        if r.status_code == 200:
            me = ((r.json() or {}).get("result") or {})
            name = str(me.get("first_name") or me.get("username") or "")
            return {"ok": True, "detail": f"Бот @{me.get('username') or name} отвечает, всё готово.",
                    "username": str(me.get("username") or ""), "name": name}
        return {"ok": False, "detail": _explain_tg(None, r, proxy)}
    except Exception as e:
        need = isinstance(e, (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError))
        return {"ok": False, "detail": _explain_tg(e, None, proxy), "need_proxy": need}


def _wait_owner_sync(token: str, proxy: Optional[str], timeout: float) -> dict:
    """Дождаться первого сообщения от хозяина и ответить ему. Блокирующий httpx — только в потоке.

    offset поднимаем по ходу, чтобы не разбирать старые сообщения (бот может быть не новый).
    """
    api = f"https://api.telegram.org/bot{token}"
    deadline = time.monotonic() + max(1.0, timeout)
    offset: Optional[int] = None
    try:
        with _sync_proxy_client(25, proxy) as c:
            while time.monotonic() < deadline:
                left = max(1, min(15, int(deadline - time.monotonic())))
                r = c.get(f"{api}/getUpdates", params={"timeout": left, **({"offset": offset} if offset else {})})
                if r.status_code != 200:
                    return {"ok": False, "detail": _explain_tg(None, r, proxy)}
                for upd in (r.json().get("result") or []):
                    offset = max(offset or 0, int(upd.get("update_id") or 0)) + 1
                    msg = upd.get("message") or upd.get("edited_message") or {}
                    frm = msg.get("from") or {}
                    chat = msg.get("chat") or {}
                    uid = int(chat.get("id") or frm.get("id") or 0)
                    if not uid or frm.get("is_bot"):
                        continue
                    from ...config import cfg
                    name = str(getattr(cfg.assistant, "name", "") or "Марвин")
                    who = str(getattr(cfg.owner, "name", "") or "").strip()
                    c.post(f"{api}/sendMessage", json={
                        "chat_id": uid,
                        "text": f"{('Здравствуйте, ' + who + '. ') if who else ''}"
                                f"Я {name}, настройка закончена — теперь отвечаю только вам.",
                    })
                    return {"ok": True, "owner_id": uid,
                            "name": str(frm.get("first_name") or frm.get("username") or "вы"),
                            "detail": f"Это вы, {frm.get('first_name') or frm.get('username') or 'хозяин'}."}
            return {"ok": False, "detail": "Сообщения не пришли. Напишите боту в Telegram (что угодно) и нажмите кнопку ещё раз."}
    except Exception as e:
        return {"ok": False, "detail": _explain_tg(e, None, proxy)}


@router.post("/telegram/owner")
async def telegram_owner(p: TgCheckIn):
    """Определить ваш Telegram ID: ждём сообщение от вас и отвечаем (до 90 секунд).
    В event loop не идёт — ждание в потоке, как принято в проекте."""
    token = (p.token or "").strip()
    if not _TG_TOKEN_RX.match(token):
        return {"ok": False, "detail": _tg_bad_token(token)}
    proxy = (p.proxy or "").strip() or None
    out = await asyncio.to_thread(_wait_owner_sync, token, proxy, OWNER_WAIT_SEC)
    out.setdefault("detail", "")
    log.info("определил Telegram-владельца: %s", "да" if out.get("ok") else "нет")
    return out


# ============================ /save ============================
class SaveIn(BaseModel):
    changes: dict = Field(default_factory=dict)


def _needs_restart(key: str) -> bool:
    if key.startswith("brain.ollama."):
        return not key.startswith("brain.ollama.small_")   # малой модели хватает reload_small_settings()
    return key.startswith(_RESTART_PREFIXES)


def _apply_live(changed: list[str]) -> list[str]:
    """Применить на лету то, что умеется без перезапуска (те же вызовы, что в
    PUT /api/settings, core/api/routers/system.py). Ошибка здесь не отменяет
    сохранение: настройки уже в config.yaml, перезапуск их подхватит."""
    applied: list[str] = []
    try:
        if any(k.startswith(_LIVE_PREFIXES) for k in changed):
            from ...brain import llm
            llm.reload_cloud_settings()
            applied.append("cloud")
        if any(k.startswith("brain.ollama.small_") for k in changed):
            from ...brain import llm
            llm.reload_small_settings()
            applied.append("small")
        if any(k.startswith(("owner.", "persona.")) for k in changed):
            from ...brain import persona
            persona.reload_persona()
            applied.append("persona")
    except Exception as e:  # pragma: no cover - не должен ронять сохранение
        log.warning("не применил на лету %s: %s", applied, type(e).__name__)
    return applied


def _check_changes(changes: dict) -> dict:
    """Только ключи мастера и только простые значения. Ничего не пишем, пока не проверили."""
    if not isinstance(changes, dict):
        raise HTTPException(400, "changes должен быть словарём «ключ: значение»")
    if len(changes) > 40:
        raise HTTPException(400, "Слишком много настроек за раз — мастер так не работает")
    bad = sorted(k for k in changes if k not in _SAVE_ALLOWED)
    if bad:
        raise HTTPException(400, f"Мастер не меняет эти настройки: {', '.join(bad[:5])}")
    out: dict[str, object] = {}
    for k, v in changes.items():
        if isinstance(v, bool) or isinstance(v, int) or v is None:
            out[k] = v
        elif isinstance(v, str) and len(v) <= 4000:
            out[k] = v
        else:
            raise HTTPException(400, f"«{k}»: значение должно быть текстом или числом")
    return out


@router.post("/save")
async def save(p: SaveIn):
    """Сохранить настройки мастера. Секреты уходят только в config.yaml через
    `config.write_settings()` — наружу возвращаем список изменённых ключей и честно
    говорим, что заработает после перезапуска, а что уже сейчас."""
    changes = _check_changes(p.changes or {})
    if not changes:
        return {"ok": True, "changed": [], "restart": [], "applied": [], "done": setup_done()}
    changed = await asyncio.to_thread(write_settings, changes)   # запись файла — в поток
    applied = _apply_live(changed)
    items = {i["key"]: i for i in read_settings()["items"]}
    return {
        "ok": True,
        "changed": changed,
        "restart": [k for k in changed if _needs_restart(k)],
        "applied": applied,
        "done": setup_done(),
        "keys": {k: bool(items[k]["set"]) for k in _SECRET_KEYS if k in items},
    }


# ============================ /restart ============================
_RESTART_RESULT: Optional[dict] = None
_RESTART_LOCK = threading.Lock()


def _relaunch_argv() -> Optional[list[str]]:
    """Команда, которой можно поднять это же ядро снова: тот же интерпретатор и тот же run.py.
    None — процесс запущен не через run.py (uvicorn/wsgi/тест), и перезапуск себе не вернуть."""
    entry = ROOT / "run.py"
    if not entry.exists() or os.path.basename(sys.argv[0] or "") not in ("run.py", "run.pyc"):
        return None
    flags = [a for a in sys.argv[1:] if a == "--no-tg"]   # сохраняем только флаги запуска
    return [sys.executable, str(entry), *flags]


def _supervisor() -> Optional[str]:
    """Есть ли скрипт-надзиратель, который перезапустит нас сам (start.bat / start.command).
    Тогда достаточно выйти — новое окно не нужно (иначе получится два ядра)."""
    try:
        import psutil
        cmd = " ".join(psutil.Process(os.getppid()).cmdline() or [])
    except Exception:
        return None
    low = (cmd or "").lower()
    for marker in ("start.bat", "start.command", "start.sh", "launcher.sh", "launchd"):
        if marker in low:
            return marker
    return None


def _spawn_relauncher(argv: list[str]) -> bool:
    """Поднять новое ядро отдельным процессом: сначала пережидаем собственный PID,
    чтобы новый экземпляр не отобрал порт у ещё живого."""
    code = ("import os,subprocess,sys,time\n"
            "pid,root=int(sys.argv[1]),sys.argv[2]\n"
            "for _ in range(240):\n"
            "    try: os.kill(pid,0)\n"
            "    except OSError: break\n"
            "    time.sleep(0.25)\n"
            "subprocess.Popen(sys.argv[3:],cwd=root)\n")
    kw: dict = {"cwd": str(ROOT), "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kw["start_new_session"] = True
    subprocess.Popen([sys.executable, "-c", code, str(os.getpid()), str(ROOT), *argv], **kw)
    return True


def _schedule_exit(delay: float = 1.2) -> None:
    """Выйти из процесса, дав ответу уйти браузеру. os._exit, а не sys.exit:
    иначе uvicorn успевает закрыть сокеты и повиснуть на finally (см. run.py)."""
    def _bye() -> None:
        time.sleep(delay)
        os._exit(0)

    threading.Thread(target=_bye, daemon=True).start()


def _is_test_run() -> bool:
    """Тесты/стенды (ASSISTANT_TEST=1) ядро не перезапускают — иначе pytest просто умрёт."""
    return bool(os.getenv("ASSISTANT_TEST") or os.getenv("JARVIS_TEST"))


def _restart_plan() -> dict:
    """Что реально можно сделать. Честность важнее удобства: если надёжно нельзя —
    так и говорим «перезапустите вручную»."""
    if _is_test_run():
        return {"ok": False, "manual": True, "how": "test",
                "detail": "тестовый запуск — ядро не перезапускаю"}
    argv = _relaunch_argv()
    if argv is None:
        return {"ok": False, "manual": True, "how": "unknown",
                "detail": "Ядро запущено не через run.py — перезапустите его вручную (start.bat), настройки уже сохранены."}
    sup = _supervisor()
    if sup:
        return {"ok": True, "manual": False, "how": "supervisor", "detail": f"Перезапускаю через {sup}."}
    return {"ok": True, "manual": False, "how": "spawn", "detail": "Перезапускаю ядро в новом окне."}


@router.post("/restart")
async def restart():
    """Перезапуск ядра после мастера. Повторный вызов ничего не делает (идемпотентно):
    второй клик не должен плодить процессы."""
    global _RESTART_RESULT
    plan: dict
    exit_now = False
    with _RESTART_LOCK:
        if _RESTART_RESULT is not None:
            return {**_RESTART_RESULT, "already": True}
        plan = _restart_plan()
        if plan["ok"]:
            if plan["how"] == "spawn":
                try:
                    _spawn_relauncher(_relaunch_argv() or [])
                except Exception as e:
                    log.warning("не смог поднять новое ядро: %s", type(e).__name__)
                    plan = {"ok": False, "manual": True, "how": "spawn",
                            "detail": f"Не смог запустить новое ядро ({type(e).__name__}). Перезапустите вручную."}
            else:
                exit_now = True          # надзиратель поднимет нас сам
        _RESTART_RESULT = plan
    if exit_now:
        _schedule_exit()
    log.info("перезапуск после мастера: %s", plan.get("how"))
    return plan