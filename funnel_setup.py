"""Включает Tailscale Funnel для сайта ассистента и записывает публичный адрес в config.yaml (telegram.webapp_url).

Запускается из funnel.bat. Ничего не ставит и не требует прав администратора.
  python funnel_setup.py          — включить/проверить и записать адрес
  python funnel_setup.py off      — выключить Funnel (сайт снова доступен только внутри Tailscale)
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

EXES = ("tailscale", r"C:\Program Files\Tailscale\tailscale.exe")


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


def main() -> int:
    print()
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
        print("  Tailscale не установлен. Поставьте с https://tailscale.com/download/windows, войдите — и запустите снова.")
        return 1
    code, out = ts("status", timeout=15)
    if code != 0 or "Logged out" in out or "stopped" in out.lower():
        print("  Tailscale установлен, но не подключён. Откройте Tailscale в трее → Log in / Connect, затем снова funnel.bat.")
        print("  " + out.strip().splitlines()[0] if out.strip() else "")
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
            print("  Затем запустите funnel.bat ещё раз.")
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
            print("  ! Перезапустите ассистента (start.bat), чтобы в боте появилась кнопка приложения.")
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
    print("  Кто может открыть этот адрес: любой, кто его знает — но увидит только пустой экран входа.")
    print("  Данные отдаются только после подтверждения Telegram, что это вы (ваш ID из config.yaml).")
    print("  Выключить публичный доступ: funnel.bat off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
