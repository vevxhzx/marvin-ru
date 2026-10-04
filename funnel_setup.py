"""Включает Tailscale Funnel для сайта ассистента и записывает публичный адрес в config.yaml (telegram.webapp_url).

Запускается из funnel.bat (Windows) или вручную на macOS/Linux. Ничего не ставит
и не требует прав администратора.
  python funnel_setup.py          — включить/проверить и записать адрес
  python funnel_setup.py off      — выключить Funnel (сайт снова доступен только внутри Tailscale)
  python funnel_setup.py --check  — только проверка (ничего не меняется; годится для CI)
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if os.name == "nt":
    os.system("chcp 65001 >nul")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PORT = 8765
try:
    from core.config import cfg
    PORT = int(getattr(getattr(cfg, "server", None), "port", PORT) or PORT)
except Exception:
    pass

# --- где лежит tailscale CLI -------------------------------------------------
# На macOS `tailscale` лежит внутри .app (/Applications/Tailscale.app/Contents/MacOS/Tailscale)
# и его НЕТ в PATH, пока не установлен Homebrew-пакет или не прописан руками —
# раньше скрипт искал только Windows-путь и на Mac отвечал «Tailscale не найден».
IS_MAC = sys.platform == "darwin"
IS_WIN = os.name == "nt"

if IS_MAC:
    EXES = (
        "tailscale",
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
        "/opt/homebrew/bin/tailscale",
        "/usr/local/bin/tailscale",
    )
    SCRIPT_HINT = "funnel.command  (или в Терминале: .venv/bin/python funnel_setup.py)"
    START_HINT = "start.command"
    DOWNLOAD = "https://tailscale.com/download/mac"
    GUI = "Tailscale в строке меню"
else:
    EXES = ("tailscale", r"C:\Program Files\Tailscale\tailscale.exe")
    SCRIPT_HINT = "funnel.bat"
    START_HINT = "start.bat"
    DOWNLOAD = "https://tailscale.com/download/windows"
    GUI = "Tailscale в трее"


def ts(*args, timeout=30):
    for exe in EXES:
        try:
            r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            return 1, "таймаут"
    return None, ""


def public_url(status_text: str) -> str | None:
    m = re.search(r"(https://[\w.-]+\.ts\.net)\S*", status_text)
    return m.group(1) if m else None


def preflight() -> bool:
    """Проверка перед открытием туннеля: сервер отвечает, а снаружи без ключа — 401.

    Туннель публикует весь порт API, поэтому смотрим глазами «снаружи»:
    Funnel добавляет заголовки X-Forwarded-*, и сервер считает такой запрос
    внешним (plain-запрос с loopback сервер доверяет по дизайну — см. core/api/auth.py).
    """
    import urllib.error
    import urllib.request
    base = f"http://127.0.0.1:{PORT}"
    warn = ""
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=5) as r:
            if r.status != 200:
                warn = f"/api/health отвечает HTTP {r.status}, а не 200"
    except Exception as e:
        warn = f"сервер не отвечает (/api/health: {e}) — туннель откроет мёртвый порт"
    if not warn:
        req = urllib.request.Request(base + "/api/status", headers={"X-Forwarded-For": "203.0.113.1"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:
            code = None
            warn = f"не смог проверить защиту API (/api/status: {e})"
        if not warn and code != 401:
            warn = f"/api/status без ключа отвечает {code}, а не 401 — данные могут быть видны всем"
    if warn:
        print(f"  [!] {warn}.")
        print("      Туннель публикует ВЕСЬ порт API; единственная защита — bearer cookie/ключ.")
        try:
            return input("  Продолжить всё равно? [y/N]: ").strip().lower() == "y"
        except (EOFError, KeyboardInterrupt):
            return False
    print("  [ок] Сервер отвечает, снаружи без ключа — 401.")
    return True


def check() -> int:
    """Проверка без изменений: есть ли tailscale, подключён ли, включён ли Funnel.

    Нужен, чтобы проверить macOS-окружение в CI и не гадать: раньше единственный
    способ понять, работает ли Funnel на Mac, — включить его по-настоящему.
    """
    print()
    print(f"  Платформа:  {'macOS' if IS_MAC else 'Windows' if IS_WIN else 'Linux'}")
    print(f"  Порт:       {PORT}")
    code, out = ts("version", timeout=10)
    if code is None:
        print(f"  [!] Tailscale не найден ни по одному из путей: {', '.join(EXES)}")
        print(f"      Поставить: {DOWNLOAD}  →  войти  →  запустить снова")
        return 1
    print(f"  [ок] Tailscale: {out.strip().splitlines()[0] if out.strip() else 'версия неизвестна'}")
    code, out = ts("status", timeout=15)
    if code != 0 or "Logged out" in out or "stopped" in out.lower():
        print(f"  [!] Tailscale не подключён — откройте {GUI} → Log in / Connect")
        print("      Войти нужно один раз с тем же аккаунтом (Google/Apple), что и на телефоне.")
        return 1
    print("  [ок] Tailscale подключён")
    _, st = ts("funnel", "status", timeout=15)
    url = public_url(st)
    if "funnel on" in st.lower() and str(PORT) in st:
        print(f"  [ок] Funnel уже включён: {url or '(адрес не разобрал)'}")
    else:
        print("  Funnel выключен (сайт виден только внутри вашей сети Tailscale).")
        print(f"      Включить: {SCRIPT_HINT}")
    print()
    print("  Ничего не менялось — это была только проверка.")
    return 0


def main() -> int:
    print()
    if len(sys.argv) > 1 and sys.argv[1] in ("--check", "-c"):
        return check()
    if len(sys.argv) > 1 and sys.argv[1] == "off":
        code, out = ts("funnel", "reset")
        if code is None:
            print("  Tailscale не найден."); return 1
        ts("serve", "reset")
        print("  Funnel выключен. Сайт снова доступен только внутри вашей сети Tailscale.")
        print("  Адрес в config.yaml (telegram.webapp_url) не трогал — кнопка в боте перестанет открываться,")
        print("  очистите поле в ⚙ Настройки → Интеграции → Telegram, если выключаете насовсем.")
        return 0

    code, out = ts("version")
    if code is None:
        print(f"  Tailscale не установлен. Поставьте с {DOWNLOAD}, войдите — и запустите снова.")
        print(f"  На macOS бинарник лежит в /Applications/Tailscale.app/Contents/MacOS/Tailscale —")
        print("  скрипт ищет его сам, в PATH добавлять ничего не нужно.")
        return 1
    code, out = ts("status", timeout=15)
    if code != 0 or "Logged out" in out or "stopped" in out.lower():
        print(f"  Tailscale установлен, но не подключён. Откройте {GUI} → Log in / Connect, затем снова {SCRIPT_HINT}.")
        print("  " + out.strip().splitlines()[0] if out.strip() else "")
        return 1

    if not preflight():
        print("  Отменено.")
        return 1

    # уже включён?
    _, st = ts("funnel", "status")
    if "funnel on" in st.lower() and str(PORT) in st:
        url = public_url(st)
        print(f"  Funnel уже включён: {url}")
    else:
        print(f"  Включаю Funnel на порт {PORT} …")
        code, out = ts("funnel", "--bg", str(PORT), timeout=90)
        if code != 0:
            low = out.lower()
            if "already exists" in low or "conflict" in low:
                print("  Занята предыдущая настройка — сбрасываю и включаю заново.")
                ts("serve", "reset"); ts("funnel", "reset")
                code, out = ts("funnel", "--bg", str(PORT), timeout=90)
        if code != 0:
            print("  Не получилось включить Funnel. Что ответил Tailscale:")
            print("  " + "\n  ".join(out.strip().splitlines()[-8:]))
            print()
            print("  Чаще всего это значит, что в админке Tailscale ещё не включены HTTPS и Funnel:")
            print("    1) https://login.tailscale.com/admin/dns → Enable HTTPS")
            print("    2) https://login.tailscale.com/admin/acls → в policy должен быть nodeAttrs с \"funnel\"")
            print("       (Tailscale сам предложит ссылку с готовым правкой — просто примите её)")
            print(f"  Затем запустите {SCRIPT_HINT} ещё раз.")
            return 1
        _, st = ts("funnel", "status")
        url = public_url(st) or public_url(out)
        if not url:
            print("  Funnel включён, но адрес не разобрал. Вывод `tailscale funnel status`:")
            print("  " + "\n  ".join(st.strip().splitlines()[:6]))
            return 1
        print(f"  Готово: {url}")

    # записать адрес в config.yaml
    try:
        from core.config import write_settings, cfg as _cfg
        cur = (getattr(_cfg.telegram, "webapp_url", "") or "").strip()
        if cur != url:
            write_settings({"telegram.webapp_url": url})
            print(f"  Записал в config.yaml: telegram.webapp_url = {url}")
            print(f"  ! Перезапустите ассистента ({START_HINT}), чтобы в боте появилась кнопка приложения.")
        else:
            print("  В config.yaml адрес уже такой же.")
    except Exception as e:
        print(f"  Не смог записать адрес в config.yaml ({e}). Впишите вручную: telegram.webapp_url: \"{url}\"")

    print()
    print("  Что дальше:")
    print(f"   1. С телефона БЕЗ VPN откройте {url} — должен показаться экран входа (без данных: это нормально).")
    print("   2. В Telegram напишите боту /app — кнопка «Открыть приложение». Или кнопка ≡ слева от поля ввода.")
    print("   3. Хотите кнопку и в списке чатов/по ссылке — @BotFather → /mybots → бот → Bot Settings → Menu Button")
    print(f"      → Configure menu button → вставьте {url}")
    print()
    print("  Важно: туннель публикует ВЕСЬ порт API, а не только экран входа.")
    print("  Единственная защита — bearer cookie/ключ: не делитесь адресом с посторонними.")
    print(f"  Выключить публичный доступ: {'funnel.bat off' if IS_WIN else '.venv/bin/python funnel_setup.py off'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
