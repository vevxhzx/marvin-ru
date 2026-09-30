#!/bin/bash
# Показать адреса для телефона (QR — в ⚙ Настройки → с телефона на уже запущенном ядре).
cd "$(dirname "$0")"
echo ""
echo "  === Доступ с телефона (macOS) ==="
echo "  1. Запустите start.command"
echo "  2. На сайте: ⚙ Настройки → «с телефона» — QR с ключом"
echo "  3. С другой сети — Tailscale (https://tailscale.com), оба устройства в одной сети"
echo ""
echo "  Брандмауэр macOS обычно пускает локальный порт 8765."
echo "  Если с телефона в той же Wi‑Fi не открывается:"
echo "    Системные настройки → Сеть → Брандмауэр → Параметры → разрешить python/терминал"
echo ""
if [ -x .venv/bin/python ]; then
  .venv/bin/python phone_info.py 2>/dev/null || python3 phone_info.py 2>/dev/null || true
elif command -v python3 >/dev/null; then
  python3 phone_info.py 2>/dev/null || true
fi
echo ""
read -r -p "  Enter — закрыть..."
