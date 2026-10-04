# -*- coding: utf-8 -*-
"""Второй ассистент на этом же ПК — для мамы (или любого близкого человека). Запускается из mama.bat.

Что делает, по шагам и с вопросами:
  1. копирует проект в соседнюю папку (без вашей базы, конфига и голосовых моделей);
  2. спрашивает, как обращаться к хозяйке, токен нового бота и ключ Groq (проверяет живьём);
  3. ловит её Telegram-ID автоматически — ей достаточно нажать Start у бота;
  4. пишет config.yaml копии: только облако, порт 8766, без голоса на ПК, без анонимайзера, мягкий характер;
  5. по желанию — второй Tailscale Funnel (порт 8443) для кнопки «Открыть» и ярлык в автозагрузку.

Никаких pip/консольных команд от пользователя. Всё повторно запускаемо: уже сделанные шаги пропускаются.
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    os.system("chcp 65001 >nul")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))

PORT = 8766          # сайт второй копии (у вашего — 8765)
FUNNEL_PORT = 8443   # публичный порт второго Funnel (у вашего — 443)
SKIP_DIRS = {"data", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "web", "vendor", ".git"}
SKIP_FILES = {"config.yaml", "mama.bat", "mama_setup.py"}


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    tail = f" [{default}]" if default else ""
    while True:
        try:
            v = input(f"  {prompt}{tail}: ").strip()
        except EOFError:
            v = ""
        if not v and default:
            return default
        if v:
            return v


def yes(prompt: str, default: bool = True) -> bool:
    v = ask(prompt + (" (Д/н)" if default else " (д/Н)"), "д" if default else "н").lower()
    return v in ("д", "да", "y", "yes", "")


def hr(title: str) -> None:
    print(f"\n  ── {title} " + "─" * max(4, 56 - len(title)))


def copy_project(dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in SRC.iterdir():
        if item.name in SKIP_DIRS or item.name in SKIP_FILES:
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
        else:
            shutil.copy2(item, target)
    # её start.bat — с другим заголовком окна: два одинаковых «Marvin» на панели задач не различить
    try:
        bat = (dst / "start.bat").read_text(encoding="utf-8", errors="replace")
        bat = bat.replace("title Marvin\r\n", "title Marvin - MAMA (port 8766)\r\n", 1).replace("title Marvin\n", "title Marvin - MAMA (port 8766)\n", 1)
        bat = bat.replace("echo Jarvis is ALREADY RUNNING", "echo Jarvis (mama) is ALREADY RUNNING").replace("echo Jarvis stopped.", "echo Jarvis (mama) stopped.")
        (dst / "start.bat").write_text(bat, encoding="utf-8")
    except OSError as e:
        print(f"  (start.bat копии без своего заголовка: {e})")
    # собранный сайт (web/site) нужен, исходники и node_modules — нет
    for built in ("web/site", "web/dist"):
        p = SRC / built
        if p.exists():
            shutil.copytree(p, dst / built, dirs_exist_ok=True)
            break
    # общий .venv: у копии свой не нужен, start.bat ищет .venv рядом — делаем junction (Windows) или симлинк
    venv_dst = dst / ".venv"
    if (SRC / ".venv").exists() and not venv_dst.exists():
        if sys.platform == "win32":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(venv_dst), str(SRC / ".venv")], capture_output=True)
        if not venv_dst.exists():
            try:
                os.symlink(SRC / ".venv", venv_dst, target_is_directory=True)
            except OSError:
                shutil.copytree(SRC / ".venv", venv_dst, symlinks=True)


async def tg_check(token: str, proxy: str) -> dict:
    import httpx
    if not re.match(r"^\d{6,}:[A-Za-z0-9_-]{30,}$", token):
        return {"ok": False, "detail": "это не похоже на токен — он выглядит как 123456789:AAF…, выдаёт @BotFather"}
    kw: dict = {"timeout": 12}
    if proxy:
        kw["proxy"] = proxy
    try:
        async with httpx.AsyncClient(**kw) as c:
            j = (await c.get(f"https://api.telegram.org/bot{token}/getMe")).json()
            if not j.get("ok"):
                return {"ok": False, "detail": f"Telegram отверг токен: {j.get('description')}"}
            return {"ok": True, "username": j["result"].get("username")}
    except Exception as e:
        return {"ok": False, "detail": f"не достучался до api.telegram.org ({type(e).__name__}) — нужен VPN на ПК или прокси"}


async def tg_wait_owner(token: str, proxy: str, name: str, timeout: float = 180) -> dict:
    """Ждём первое сообщение боту и забираем ID отправителя (как мастер Marvin: старые апдейты сбрасываем)."""
    import httpx
    kw: dict = {"timeout": 35}
    if proxy:
        kw["proxy"] = proxy
    offset = None
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    async with httpx.AsyncClient(**kw) as c:
        r = await c.get(f"https://api.telegram.org/bot{token}/getUpdates", params={"timeout": 0})
        for u in (r.json().get("result") or []):
            offset = u["update_id"] + 1
        while loop.time() < deadline:
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
                    who = " ".join(filter(None, [frm.get("first_name"), frm.get("last_name")])) or frm.get("username") or str(uid)
                    try:
                        await c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                     json={"chat_id": uid, "text": f"Здравствуйте! Я {name}. Теперь я отвечаю только вам. "
                                                                    "Через минуту меня включат — и можно писать."})
                    except Exception:
                        pass
                    return {"ok": True, "owner_id": uid, "name": who}
    return {"ok": False}


async def groq_check(key: str, proxy: str) -> dict:
    import httpx
    kw: dict = {"timeout": 25}
    if proxy:
        kw["proxy"] = proxy
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(**kw) as c:
            # 1) ключ и живой список моделей (Groq регулярно выводит модели из оборота — ничего не хардкодим)
            r = await c.get("https://api.groq.com/openai/v1/models", headers=headers)
            if r.status_code in (401, 403):
                return {"ok": False, "detail": "ключ не принят — скопируйте целиком, без пробелов"}
            if r.status_code >= 400:
                return {"ok": False, "detail": f"Groq ответил {r.status_code}: {r.text[:120]}"}
            ids = [m.get("id", "") for m in r.json().get("data", [])]
            prefer = ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "meta-llama/llama-4-scout-17b-16e-instruct", "qwen/qwen3-32b")
            model = next((m for m in prefer if m in ids), None) or next((i for i in ids if not any(x in i for x in ("compound", "guard", "whisper", "orpheus", "tts"))), None)
            if not model:
                return {"ok": False, "detail": "у этого ключа нет ни одной чат-модели — проверьте аккаунт Groq"}
            # 2) живой запрос
            body = {"model": model, "messages": [{"role": "user", "content": "Ответь одним словом: ок"}], "max_tokens": 10, "temperature": 0}
            r = await c.post("https://api.groq.com/openai/v1/chat/completions", json=body, headers=headers)
            if r.status_code >= 400:
                return {"ok": False, "detail": f"Groq ответил {r.status_code}: {r.text[:120]}"}
            return {"ok": True, "model": model}
    except Exception as e:
        return {"ok": False, "detail": f"не достучался до api.groq.com ({type(e).__name__})"}


def write_config(dst: Path, values: dict) -> None:
    """Пишем config.yaml копии через тот же построчный write_settings, что и сайт, — комментарии сохраняются.
    Импортируем core копии, чтобы ROOT указывал на неё."""
    shutil.copy(SRC / "config.example.yaml", dst / "config.yaml")   # настройка «заново» = чистый шаблон + значения ниже
    _apply_settings(dst, values)


def _apply_settings(dst: Path, values: dict) -> None:
    """write_settings из core копии (чтобы ROOT был её). Данные — через временный файл в UTF-8:
    stdin/argv дочернего процесса на Windows идут в cp1252 и падают на кириллице."""
    import json
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False)
        tmp = f.name
    code = ("import sys, json, io; sys.path.insert(0, sys.argv[1]); from core.config import write_settings; "
            "write_settings(json.load(io.open(sys.argv[2], encoding='utf-8')))")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        r = subprocess.run([sys.executable, "-c", code, str(dst), tmp], capture_output=True, cwd=str(dst), env=env)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")[-400:])


def tailscale(*args, timeout=60):
    for exe in ("tailscale", r"C:\Program Files\Tailscale\tailscale.exe"):
        try:
            r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            return 1, "таймаут"
    return None, ""


def setup_funnel() -> str | None:
    code, _ = tailscale("version", timeout=10)
    if code is None:
        print("  Tailscale не найден — кнопки «Открыть» пока не будет. Поставьте Tailscale, пройдите funnel.bat")
        print("  у себя, потом запустите mama.bat ещё раз — он добавит только этот шаг.")
        return None
    _, st = tailscale("funnel", "status")
    m = re.search(r"(https://[\w.-]+\.ts\.net)", st)
    if not m:
        print("  У вашего ассистента Funnel ещё не включён (funnel.bat). Сначала он, потом снова mama.bat.")
        return None
    base = m.group(1)
    if f":{FUNNEL_PORT}" in st and str(PORT) in st:
        print(f"  Второй Funnel уже включён: {base}:{FUNNEL_PORT}")
        return f"{base}:{FUNNEL_PORT}"
    code, out = tailscale("funnel", "--bg", f"--https={FUNNEL_PORT}", str(PORT), timeout=90)
    if code != 0:
        print("  Не удалось включить второй Funnel. Ответ Tailscale:")
        print("  " + "\n  ".join(out.strip().splitlines()[-5:]))
        return None
    print(f"  Готово: {base}:{FUNNEL_PORT} → сайт второй копии")
    return f"{base}:{FUNNEL_PORT}"


def add_autostart(dst: Path, title: str) -> None:
    if sys.platform != "win32":
        return
    lnk = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup" / f"{title}.lnk"
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); $s.TargetPath='{dst / 'start.bat'}'; "
          f"$s.WorkingDirectory='{dst}'; $s.WindowStyle=7; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    print(f"  Ярлык автозагрузки: {lnk}")


def main() -> int:
    print("\n  ================================================")
    print("    Marvin для мамы — вторая копия на этом ПК")
    print("  ================================================")
    print("  Понадобятся: токен нового бота (@BotFather → /newbot) и ключ Groq")
    print("  (console.groq.com/keys, бесплатно, лучше отдельный аккаунт). Телефон мамы — под рукой.")

    hr("1. Папка")
    default_dst = str(SRC.parent / (SRC.name + "-mama"))
    dst = Path(ask("Куда положить копию", default_dst))
    if dst.resolve() == SRC.resolve():
        print("  Это та же папка. Нужна другая."); return 1
    exists = (dst / "run.py").exists()
    print("  Копирую проект…" if not exists else "  Копия уже есть — обновляю файлы (база и настройки не трогаются).")
    copy_project(dst)
    print("        ок")

    cfg_path = dst / "config.yaml"
    if cfg_path.exists() and not yes("config.yaml копии уже заполнен. Пройти настройку заново?", default=False):
        values = None
    else:
        hr("2. Обращение")
        assistant = "Марвин"
        owner = ask("Как ему обращаться к ней («мам», «Наталья», «Наталья Петровна»)", "мам")
        tz = ask("Часовой пояс", "Europe/Moscow")

        hr("3. Telegram-бот")
        print("  В Telegram: @BotFather → /newbot → имя (например «Помощник мамы») → юзернейм (…_bot) → скопируйте токен.")
        proxy = ""
        while True:
            token = ask("Токен бота")
            res = asyncio.run(tg_check(token, proxy))
            if res["ok"]:
                print(f"        ок: @{res['username']}"); break
            print(f"  ✗ {res['detail']}")
            if "VPN" in res["detail"] and not proxy:
                proxy = ask("Прокси для Telegram (как у вашего ассистента; пусто — попробовать снова)", "")
                proxy = "" if proxy in ("-", "нет") else proxy
        print(f"\n  Теперь с ТЕЛЕФОНА МАМЫ откройте https://t.me/{res['username']} и нажмите «Start».")
        print("  (Можно с вашего телефона, если бот будет у вас — тогда ID будет ваш.)")
        print("  Жду до 3 минут…")
        w = asyncio.run(tg_wait_owner(token, proxy, assistant))
        if not w.get("ok"):
            print("  Сообщений не было. Запустите mama.bat ещё раз, когда телефон будет рядом."); return 1
        owner_id = w["owner_id"]
        print(f"        ок: {w['name']} (ID {owner_id}) — бот будет отвечать только ей")

        hr("4. Мозг — облако Groq")
        print("  console.groq.com/keys → Create API Key → скопируйте (начинается на gsk_).")
        while True:
            key = ask("Ключ Groq")
            res = asyncio.run(groq_check(key, ""))
            if res["ok"]:
                print(f"        ок: Groq отвечает ({res['model']})"); break
            print(f"  ✗ {res['detail']}")

        values = {
            "owner.name": owner, "owner.timezone": tz,
            "telegram.token": token, "telegram.owner_id": owner_id, "telegram.proxy": proxy,
            "brain.mode": "cloud", "brain.cloud.provider": "groq", "brain.cloud.api_key": key,
            "brain.cloud.model": "",   # пусто: модель выбирается из живого списка Groq автоматически
            "brain.vision.where": "cloud", "brain.gemini.anonymize": False, "brain.gemini.mark_source": False,
            "persona.style": "neutral",
            # голосовые в Telegram — да (мамы любят наговаривать), распознаёт Groq Whisper за секунду; озвучка не нужна
            "voice.enabled": True, "voice.stt.cloud": True, "voice.tts.engine": "off",
            "voice.tts.reply_in_telegram": "never", "finance.main_account": "Карта",
            "server.port": PORT,
        }
        write_config(dst, values)
        print("        config.yaml копии записан")

    hr("5. Кнопка «Открыть» в её Telegram (сайт внутри чата)")
    url = None
    if yes("Настроить сейчас? (нужен Tailscale, как у вашего funnel.bat)"):
        url = setup_funnel()
        if url:
            try:
                _apply_settings(dst, {"telegram.webapp_url": url})
                print("        адрес записан в config.yaml копии")
            except RuntimeError as e:
                print(f"  ✗ не смог записать адрес: {e}. Впишите вручную: telegram.webapp_url: \"{url}\"")

    hr("6. Автозагрузка")
    if yes("Запускать её копию вместе с Windows (вместе с вашей)?"):
        add_autostart(dst, "Marvin - mama")

    print("\n  ================================================")
    print("    Готово. Что дальше:")
    print(f"     1. Бот работает, пока открыто окно {dst / 'start.bat'} (можно свернуть, закрывать нельзя).")
    print("     2. Маме: написать боту что угодно — он ответит. Инструкция для неё: docs\\for-mom.md")
    print("        (перешлите ей файл или распечатайте).")
    if url:
        print(f"     3. Кнопка «Открыть» появится в её боте после запуска. Адрес: {url}")
    print("     Обе копии независимы: разные боты, базы и ключи; ваш ассистент её сообщений не видит.")
    print("  ================================================\n")
    if sys.platform == "win32" and ask("Запустить её копию прямо сейчас? (д/н)", "д").lower().startswith(("д", "y")):
        subprocess.Popen(["cmd", "/c", "start", "", str(dst / "start.bat")], cwd=str(dst))
        print("        открылось второе окно — через ~10 секунд бот отвечает маме. Окно можно свернуть.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Прервано. Запустите mama.bat снова — сделанное сохранится.")
        sys.exit(1)
