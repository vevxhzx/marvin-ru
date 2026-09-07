"""Мастер первого запуска: железо → рекомендация модели → проверки Telegram / Ollama / облака → запись config.yaml.

Логика вынесена из API, чтобы её можно было тестировать без сервера. Ничего не устанавливает молча:
скачивание модели Ollama запускается только по явному запросу со страницы /setup.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict

import httpx

log = logging.getLogger("assistant.setup")


# --------------------------------------------------------------------------- железо
@dataclass
class Hardware:
    os: str = ""
    cpu: str = ""
    ram_gb: float = 0
    gpu: str = ""            # название видеокарты (или пусто)
    vram_gb: float = 0       # видеопамять в ГБ (0 — нет/не определили)
    gpu_vendor: str = ""     # nvidia / amd / apple / intel / ""
    ollama: bool = False     # ollama установлена (есть в PATH или отвечает по сети)
    ollama_running: bool = False
    ollama_models: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _run(cmd: list[str], timeout: float = 8) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="ignore").stdout
    except Exception:
        return ""


def _ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        pass
    if sys.platform == "linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        return round(int(line.split()[1]) / 2**20, 1)
        except Exception:
            pass
    if sys.platform == "win32":
        out = _run(["wmic", "computersystem", "get", "TotalPhysicalMemory"])
        m = re.search(r"(\d{9,})", out)
        if m:
            return round(int(m.group(1)) / 2**30, 1)
    return 0


def _gpu() -> tuple[str, float, str]:
    """(название, VRAM ГБ, вендор). nvidia-smi надёжнее всего; на Windows добираем через wmic/PowerShell; на Mac — Apple Silicon."""
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if out.strip():
        name, mem = [x.strip() for x in out.strip().splitlines()[0].split(",")[:2]]
        try:
            return name, round(float(mem) / 1024, 1), "nvidia"
        except ValueError:
            return name, 0, "nvidia"
    if sys.platform == "darwin":
        chip = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        if "Apple" in chip:
            # у Apple Silicon память общая: Ollama может использовать ~2/3
            return chip, round(_ram_gb() * 0.66, 1), "apple"
        return chip, 0, ""
    if sys.platform == "win32":
        ps = _run(["powershell", "-NoProfile", "-Command",
                   "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json"], timeout=15)
        try:
            import json
            data = json.loads(ps) if ps.strip() else []
            if isinstance(data, dict):
                data = [data]
            best = None
            for g in data:
                nm = str(g.get("Name") or "")
                ram = float(g.get("AdapterRAM") or 0) / 2**30
                vendor = "nvidia" if "nvidia" in nm.lower() or "geforce" in nm.lower() else "amd" if "radeon" in nm.lower() or "amd" in nm.lower() else "intel" if "intel" in nm.lower() else ""
                if best is None or ram > best[1]:
                    best = (nm, round(ram, 1), vendor)
            if best:
                # AdapterRAM — 32-битное поле, карты >4 ГБ показываются как 4; помечаем как «не меньше»
                return best
        except Exception:
            pass
    if sys.platform == "linux":
        out = _run(["lspci"])
        for line in out.splitlines():
            if "VGA" in line or "3D" in line:
                nm = line.split(":")[-1].strip()
                vendor = "nvidia" if "nvidia" in nm.lower() else "amd" if "amd" in nm.lower() or "radeon" in nm.lower() else "intel" if "intel" in nm.lower() else ""
                return nm, 0, vendor
    return "", 0, ""


async def detect_hardware(ollama_url: str = "http://127.0.0.1:11434") -> Hardware:
    hw = Hardware(os=f"{platform.system()} {platform.release()}", cpu=platform.processor() or platform.machine(), ram_gb=_ram_gb())
    hw.gpu, hw.vram_gb, hw.gpu_vendor = await asyncio.to_thread(_gpu)
    hw.ollama = bool(shutil.which("ollama"))
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as c:
            r = await c.get(f"{ollama_url}/api/tags")
            if r.status_code == 200:
                hw.ollama = hw.ollama_running = True
                hw.ollama_models = [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        pass
    if hw.gpu_vendor == "nvidia" and hw.vram_gb and hw.vram_gb <= 4.1 and "GeForce" in hw.gpu and not shutil.which("nvidia-smi"):
        hw.notes.append("Объём видеопамяти определён приблизительно (Windows показывает не больше 4 ГБ) — уточните в рекомендации.")
    if hw.gpu_vendor == "amd":
        hw.notes.append("Видеокарта AMD: Ollama поддерживает не все модели Radeon; если будет медленно — выбирайте модель поменьше или облако.")
    return hw


# --------------------------------------------------------------------------- рекомендации моделей
# Список актуален на сентябрь 2026. Порядок — от лучшей к запасной для данного объёма памяти.
# vision=True — модель сама видит картинки (чеки, скриншоты); tools=True — умеет вызывать инструменты (обязательно для личного).
MODELS = [
    {"id": "qwen3.5:27b",  "min_vram": 18, "size_gb": 17, "vision": True,  "tools": True, "title": "Qwen 3.5 27B — максимум качества для домашней карты (RTX 3090/4090)"},
    {"id": "gemma4:12b",   "min_vram": 10, "size_gb": 8.1, "vision": True, "tools": True, "title": "Gemma 4 12B — очень хорошо по-русски, видит картинки"},
    {"id": "qwen3.5:9b",   "min_vram": 7.5, "size_gb": 6.0, "vision": True, "tools": True, "title": "Qwen 3.5 9B — золотая середина для 8 ГБ (RTX 3060/4060)"},
    {"id": "qwen3.5:4b",   "min_vram": 4.5, "size_gb": 2.8, "vision": True, "tools": True, "title": "Qwen 3.5 4B — быстрая, видит картинки, тянет 6 ГБ (GTX 1660, RTX 2060)"},
    {"id": "gemma4:e4b",   "min_vram": 4.5, "size_gb": 3.2, "vision": True, "tools": True, "title": "Gemma 4 E4B — альтернатива для 6 ГБ, чуть лучше в разговоре"},
    {"id": "qwen3.5:2b",   "min_vram": 2.5, "size_gb": 1.6, "vision": True, "tools": True, "title": "Qwen 3.5 2B — для 4 ГБ видеопамяти или процессора с 16 ГБ ОЗУ"},
    {"id": "qwen3.5:0.8b", "min_vram": 1.0, "size_gb": 0.7, "vision": False, "tools": True, "title": "Qwen 3.5 0.8B — совсем слабое железо; понимает команды, разговор так себе"},
]
EMBED_MODEL = "nomic-embed-text"


def recommend(hw: Hardware) -> dict:
    """Рекомендация режима и модели под железо."""
    vram = hw.vram_gb
    # Apple Silicon и ПК без дискретной карты: Ollama работает на CPU/общей памяти — считаем «условную VRAM» как треть ОЗУ
    effective = vram if vram >= 2 else round(min(hw.ram_gb * 0.35, 12), 1)
    on_cpu = vram < 2 and hw.gpu_vendor != "apple"
    fits = [m for m in MODELS if m["min_vram"] <= effective]
    primary = fits[0] if fits else None
    alts = fits[1:4]
    if on_cpu and primary and primary["min_vram"] > 5:
        # на процессоре большие модели невыносимо медленные
        primary = next((m for m in MODELS if m["min_vram"] <= 4.5), MODELS[-1])
        alts = [m for m in MODELS if m["min_vram"] <= 2.5 and m is not primary]
    if not primary or (on_cpu and hw.ram_gb and hw.ram_gb < 8):
        mode, why = "cloud", "Видеокарты нет и оперативной памяти мало — локальная модель будет отвечать минутами. Рекомендую облако."
    elif on_cpu:
        mode, why = "hybrid", f"Дискретной видеокарты не вижу — модель {primary['id']} пойдёт на процессоре (медленно, 10–30 с на ответ). Общие вопросы лучше отдать облаку."
    elif effective < 6:
        mode, why = "hybrid", f"Видеопамяти {vram} ГБ: {primary['id']} влезет целиком и будет отвечать за секунды. Сложные вопросы — в облако."
    else:
        mode, why = "hybrid", f"Видеопамяти {vram} ГБ: {primary['id']} — хорошо и быстро. Облако можно подключить для сложных вопросов или вовсе отключить (режим local)."
    return {"mode": mode, "why": why, "model": primary["id"] if primary else "", "primary": primary, "alternatives": alts,
            "effective_vram": effective, "on_cpu": on_cpu, "all": MODELS}


# --------------------------------------------------------------------------- проверки
async def check_telegram(token: str, proxy: str = "") -> dict:
    token = (token or "").strip()
    if not re.match(r"^\d{6,}:[A-Za-z0-9_-]{30,}$", token):
        return {"ok": False, "detail": "Это не похоже на токен. Он выглядит так: 123456789:AAF…, выдаёт @BotFather."}
    kw: dict = {"timeout": 12}
    if proxy:
        kw["proxy"] = proxy
    try:
        async with httpx.AsyncClient(**kw) as c:
            r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
            j = r.json()
            if not j.get("ok"):
                return {"ok": False, "detail": f"Telegram отверг токен: {j.get('description', r.status_code)}"}
            u = j["result"]
            return {"ok": True, "username": u.get("username"), "name": u.get("first_name"), "detail": f"Бот @{u.get('username')} на связи."}
    except httpx.ProxyError as e:
        return {"ok": False, "detail": f"Прокси не отвечает: {e}"}
    except Exception as e:
        return {"ok": False, "detail": f"Не достучался до api.telegram.org ({type(e).__name__}). В России нужен VPN или прокси — впишите его ниже.", "need_proxy": True}


async def wait_owner_id(token: str, proxy: str = "", timeout: float = 90) -> dict:
    """Ждём, пока владелец напишет боту что угодно, и забираем его ID из первого сообщения (long polling getUpdates)."""
    kw: dict = {"timeout": 35}
    if proxy:
        kw["proxy"] = proxy
    offset = None
    deadline = asyncio.get_event_loop().time() + timeout
    try:
        async with httpx.AsyncClient(**kw) as c:
            # сбрасываем накопившиеся старые апдейты, чтобы не поймать чужой ID из прошлого
            r = await c.get(f"https://api.telegram.org/bot{token}/getUpdates", params={"timeout": 0})
            for u in (r.json().get("result") or []):
                offset = u["update_id"] + 1
            while asyncio.get_event_loop().time() < deadline:
                params = {"timeout": 25}
                if offset:
                    params["offset"] = offset
                r = await c.get(f"https://api.telegram.org/bot{token}/getUpdates", params=params)
                for u in (r.json().get("result") or []):
                    offset = u["update_id"] + 1
                    msg = u.get("message") or u.get("edited_message") or {}
                    frm = msg.get("from") or {}
                    if frm.get("id") and not frm.get("is_bot"):
                        uid = int(frm["id"])
                        name = " ".join(filter(None, [frm.get("first_name"), frm.get("last_name")])) or frm.get("username") or str(uid)
                        try:
                            await c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                         json={"chat_id": uid, "text": f"Есть контакт. Ваш ID {uid} — теперь я отвечаю только вам. Возвращайтесь в мастер настройки."})
                        except Exception:
                            pass
                        return {"ok": True, "owner_id": uid, "name": name}
            return {"ok": False, "detail": "За полторы минуты сообщений боту не было. Откройте бота в Telegram, нажмите «Start» и попробуйте снова."}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


async def check_cloud(provider: str, api_key: str, model: str = "", base_url: str = "", proxy: str = "") -> dict:
    """Живой запрос к облаку выбранного провайдера, не трогая текущие настройки."""
    from .brain import llm
    prov = llm.PROVIDERS.get(provider)
    if provider == "gemini":
        return await _check_gemini(api_key, proxy)
    if not prov and provider != "custom":
        return {"ok": False, "detail": f"Неизвестный провайдер {provider}"}
    url = (base_url or (prov or {}).get("base_url", "")).rstrip("/")
    mdl = model or (prov or {}).get("model", "")
    if provider == "openrouter" and mdl in ("", "auto"):
        mdl = "openrouter/auto"
    if not url:
        return {"ok": False, "detail": "Укажите адрес API (base_url)."}
    if not api_key and provider != "custom":
        return {"ok": False, "detail": "Вставьте ключ."}
    kw: dict = {"timeout": 25}
    if proxy:
        kw["proxy"] = proxy
    body = {"model": mdl, "messages": [{"role": "user", "content": "Ответь одним словом: ок"}], "max_tokens": 20, "temperature": 0}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(**kw) as c:
            r = await c.post(f"{url}/chat/completions", json=body, headers=headers)
            if r.status_code in (401, 403):
                return {"ok": False, "detail": "Ключ не принят. Скопируйте его целиком, без пробелов."}
            if r.status_code == 404 and provider == "custom":
                return {"ok": False, "detail": f"По адресу {url} нет /chat/completions. Для LM Studio адрес обычно http://127.0.0.1:1234/v1"}
            if r.status_code == 429:
                return {"ok": True, "detail": "Ключ рабочий, но сейчас лимит запросов (429) — это нормально для бесплатных тарифов.", "model": mdl}
            r.raise_for_status()
            txt = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content", "")
            return {"ok": True, "detail": f"Отвечает ({mdl}).", "model": mdl, "sample": (txt or "")[:60]}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "detail": f"Ответ {e.response.status_code}: {e.response.text[:160]}"}
    except Exception as e:
        return {"ok": False, "detail": f"Не достучался до {url.split('/')[2]} ({type(e).__name__}). Возможно, нужен VPN или прокси.", "need_proxy": True}


async def _check_gemini(api_key: str, proxy: str = "") -> dict:
    kw: dict = {"timeout": 20}
    if proxy:
        kw["proxy"] = proxy
    try:
        async with httpx.AsyncClient(**kw) as c:
            r = await c.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": api_key})
            if r.status_code == 200:
                return {"ok": True, "detail": "Gemini отвечает."}
            return {"ok": False, "detail": f"Gemini: {r.status_code} {r.text[:120]}"}
    except Exception as e:
        return {"ok": False, "detail": f"Google недоступен ({type(e).__name__}) — из России нужен прокси.", "need_proxy": True}


# --------------------------------------------------------------------------- Ollama: статус и скачивание модели
_PULL: dict[str, dict] = {}   # model → {"status","done","total","error"}


async def ollama_status(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as c:
            r = await c.get(f"{url}/api/tags")
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return {"running": True, "installed": True, "models": models}
    except Exception:
        return {"running": False, "installed": bool(shutil.which("ollama")), "models": []}


async def ollama_pull(url: str, model: str) -> None:
    """Скачать модель через API Ollama, прогресс в _PULL[model]."""
    st = _PULL.setdefault(model, {"status": "starting", "done": 0, "total": 0, "error": None})
    try:
        async with httpx.AsyncClient(timeout=None, trust_env=False) as c:
            async with c.stream("POST", f"{url}/api/pull", json={"name": model, "stream": True}) as r:
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        import json
                        j = json.loads(line)
                    except Exception:
                        continue
                    if j.get("error"):
                        st.update(status="error", error=j["error"]); return
                    st["status"] = j.get("status", st["status"])
                    if j.get("total"):
                        st["total"] = j["total"]; st["done"] = j.get("completed", 0)
        st["status"] = "success"
    except Exception as e:
        st.update(status="error", error=f"{type(e).__name__}: {e}")
        return
    # вслед за основной моделью — маленькая модель эмбеддингов для смыслового поиска по заметкам (270 МБ, в фоне)
    if model != EMBED_MODEL and EMBED_MODEL not in _PULL:
        try:
            await ollama_pull(url, EMBED_MODEL)
        except Exception:
            pass


def pull_progress(model: str) -> dict:
    return _PULL.get(model, {"status": "idle", "done": 0, "total": 0, "error": None})


def start_ollama_if_installed() -> bool:
    """Ollama установлена, но не запущена (на Windows она обычно в трее и стартует сама) — пробуем поднять `ollama serve`."""
    exe = shutil.which("ollama")
    if not exe:
        return False
    try:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        return True
    except Exception as e:
        log.warning("ollama serve: %s", e)
        return False


def hardware_dict(hw: Hardware) -> dict:
    return asdict(hw)
