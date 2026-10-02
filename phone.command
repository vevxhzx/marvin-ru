#!/bin/bash
# Показать адреса для телефона (QR — в ⚙ Настройки → с телефона на уже запущенном ядре).
#
#   ./phone.command           адреса + подсказки
#   ./phone.command --check   только проверки (порт, python), ничего не меняя
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
ROOT="$(pwd)"
export JARVIS_ROOT="$ROOT"
# shellcheck source=mac/preflight.sh
. "$ROOT/mac/preflight.sh"
jarvis_utf8

MODE="run"
for arg in "$@"; do
  case "$arg" in
    --check|--dry-run) MODE="check" ;;
    -h|--help) printf '  Использование: ./phone.command [--check]\n'; exit 0 ;;
    *) jarvis_err "Неизвестный аргумент: $arg"; exit 2 ;;
  esac
done

PORT="$(jarvis_port)"

printf '\n'
printf '  === Доступ с телефона (macOS) ===\n'

if jarvis_port_busy "$PORT"; then
  jarvis_warn "На порту $PORT сейчас никто не слушает — сначала ./start.command."
else
  jarvis_ok "Ядро отвечает на порту %s — телефон увидит сайт." "$PORT"
fi

printf '  1. Запустите ./start.command\n'
printf '  2. На сайте: ⚙ Настройки → «с телефона» — QR с ключом\n'
printf '  3. С другой сети — Tailscale (https://tailscale.com), оба устройства в одной сети\n'
printf '\n'
printf '  Брандмауэр macOS обычно пускает локальный порт %s.\n' "$PORT"
printf '  Если с телефона в той же Wi‑Fi не открывается:\n'
printf '    Системные настройки → Сеть → Брандмауэр → Параметры → разрешить python/терминал\n'
printf '\n'

if [ -x "$ROOT/.venv/bin/python" ]; then
  if ! jarvis_python_version_ok "$ROOT/.venv/bin/python"; then
    jarvis_warn "В .venv интерпретатор $(jarvis_python_version "$ROOT/.venv/bin/python") — нужно $J_PY_MIN+."
    jarvis_say "  Пересоздать: rm -rf .venv && ./Install-Mac.command"
  fi
  "$ROOT/.venv/bin/python" "$ROOT/phone_info.py" || jarvis_warn "phone_info.py не отработал (подробности выше)."
elif command -v python3 >/dev/null 2>&1; then
  python3 "$ROOT/phone_info.py" || jarvis_warn "phone_info.py не отработал."
else
  jarvis_warn "Нет ни .venv, ни python3 — адреса показать нечем."
fi

if [ "$MODE" = "check" ]; then
  if [ -f "$ROOT/phone_info.py" ]; then
    jarvis_ok "phone_info.py на месте"
  else
    jarvis_err "НЕТ phone_info.py — адреса показать нечем"
    exit 1
  fi
  jarvis_ok "порт из config.yaml: $PORT"
  exit 0
fi

printf '  Публичный адрес без VPN (Tailscale Funnel) — спросите у того, кто ставил,\n'
printf '  или выполните вручную:  .venv/bin/python funnel_setup.py\n'
printf '\n'
jarvis_pause "  Enter — закрыть..."