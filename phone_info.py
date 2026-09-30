"""Печатает адреса, по которым сайт ассистента открывается с телефона (Tailscale и домашняя сеть)."""
import os
import socket
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


def tailscale_ip() -> str | None:
    for exe in ("tailscale", r"C:\Program Files\Tailscale\tailscale.exe"):
        try:
            out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.strip()
            if out:
                return out.splitlines()[0].strip()
        except Exception:
            continue
    return None


def lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


ts, lan = tailscale_ip(), lan_ip()
host = socket.gethostname()
print()
if ts:
    print(f"  Tailscale (из любой сети, телефон тоже в Tailscale):  http://{ts}:{PORT}")
    print(f"                                       или по имени:  http://{host.lower()}:{PORT}")
else:
    print("  Tailscale не найден. Поставьте с https://tailscale.com/download на ПК и телефон,")
    print("  войдите одним аккаунтом (Google/Apple) на обоих — и запустите phone.bat ещё раз.")
if lan:
    print(f"  Домашний Wi-Fi (телефон в той же сети):               http://{lan}:{PORT}")
print()
print("  Откройте адрес в браузере телефона -> меню -> «Добавить на экран Домой».")
print("  QR-код с этим адресом есть на сайте: Настройки -> «Телефон».")
