#!/bin/bash
# Обновить pip-пакеты после скачивания новой версии архива.
#
#   ./update.command           обновить зависимости
#   ./update.command --check   проверить окружение, ничего не меняя (dry-run)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
ROOT="$(pwd)"
export JARVIS_ROOT="$ROOT"
# shellcheck source=mac/preflight.sh
. "$ROOT/mac/preflight.sh"
jarvis_utf8

PY="$ROOT/.venv/bin/python"
MODE="run"
for arg in "$@"; do
  case "$arg" in
    --check|--dry-run) MODE="check" ;;
    -h|--help) printf '  Использование: ./update.command [--check]\n'; exit 0 ;;
    *) jarvis_err "Неизвестный аргумент: $arg"; exit 2 ;;
  esac
done

# на mac ставим requirements-mac.txt: в requirements.txt есть torch, у которого
# нет колёс под Intel Mac — обновление там падало бы на сборке из исходников.
REQ="requirements.txt"
[ -f "$ROOT/requirements-mac.txt" ] && REQ="requirements-mac.txt"

if [ ! -x "$PY" ]; then
  jarvis_err "Нет .venv — сначала Install-Mac.command (или ./install.command)."
  jarvis_pause "  Enter — закрыть…"
  exit 1
fi
if ! jarvis_python_version_ok "$PY"; then
  jarvis_err "В .venv интерпретатор $(jarvis_python_version "$PY") — нужно $J_PY_MIN+."
  jarvis_say "  Пересоздать окружение: rm -rf .venv && ./Install-Mac.command"
  jarvis_pause "  Enter — закрыть…"
  exit 1
fi

if [ "$MODE" = "check" ]; then
  printf '\n'
  printf '  Проверка обновления на macOS (ничего не меняется)\n'
  printf '  ================================================\n'
  jarvis_ok "venv: $PY ($(jarvis_python_version "$PY"))"
  jarvis_ok "файл зависимостей: $REQ"
  if "$PY" -c "import fastapi, uvicorn, sqlmodel" >/dev/null 2>&1; then
    jarvis_ok "ядро импортируется"
  else
    jarvis_err "ядро не импортируется — запустите ./update.command без --check"
    printf '\n'
    exit 1
  fi
  jarvis_port_report "$(jarvis_port)" || true
  printf '\n'
  exit 0
fi

printf '\n'
jarvis_ok "venv: $PY ($(jarvis_python_version "$PY"))"
printf '\n'

# Порт занят — обновлять пакеты на живом процессе бессмысленно: файлы .venv
# переписываются, а импорты уже в памяти. Не фатально, но предупреждаем заранее.
if jarvis_port_busy "$(jarvis_port)"; then
  jarvis_warn "Ядро сейчас запущено на порту $(jarvis_port)."
  jarvis_say "  Лучше остановить его: ./start.command --stop  (или закройте окно Терминала)"
  jarvis_say "  и только потом обновлять. Продолжаю — пакеты просто перезапишутся на диске."
fi

printf '  Обновляю пакеты из %s…\n' "$REQ"
"$PY" -m pip install --upgrade pip -q --disable-pip-version-check \
  || jarvis_warn "не смог обновить pip — продолжаю (обычно не критично)"

if ! "$PY" -m pip install -r "$ROOT/$REQ" --disable-pip-version-check; then
  printf '\n'
  jarvis_err "pip не смог обновить зависимости. Текст ошибки выше — причина."
  jarvis_say "  Если жалуется на torch и вы на Intel Mac: так и должно быть — скажите,"
  jarvis_say "  что $REQ надо перезалить; если нужен Silero — ставьте его отдельно:"
  jarvis_say "    $PY -m pip install -r requirements-silero.txt --index-url https://download.pytorch.org/whl/cpu"
  jarvis_pause "  Enter — закрыть…"
  exit 1
fi

# Голосовой аддон обновляем только если он реально стоит: иначе тянем ~700 МБ
# тому, кто голосом и не пользуется.
if [ -f "$ROOT/requirements-voice.txt" ] && "$PY" -c "import vosk" >/dev/null 2>&1; then
  printf '  Голосовой аддон установлен — обновляю его тоже…\n'
  "$PY" -m pip install -r "$ROOT/requirements-voice.txt" -q --disable-pip-version-check \
    || jarvis_warn "голосовые пакеты не обновились (микрофон). Голос не сломается, продолжите."
else
  jarvis_say "  Голос не установлен — requirements-voice.txt пропускаю (нужен install_voice.command)."
fi

printf '\n'
"$PY" -c "from core import VERSION; print('  core v' + VERSION)" 2>/dev/null \
  || jarvis_warn "не смог прочитать версию ядра (core не импортируется?)"
printf '  Готово. Запустите ./start.command\n'
printf '\n'
jarvis_pause "  Enter — закрыть…"