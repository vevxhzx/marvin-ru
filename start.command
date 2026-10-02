#!/bin/bash
# Запуск ядра. Окно/вкладку Терминала держите открытой.
# Двойной клик в Finder или: ./start.command
#
#   ./start.command            запуск ядра (с автоперезапуском)
#   ./start.command --stop     остановить ядро, запущенное где угодно на этом порту
#   ./start.command --check    проверить окружение, ничего не запуская (dry-run)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
ROOT="$(pwd)"
export JARVIS_ROOT="$ROOT"
# shellcheck source=mac/preflight.sh
. "$ROOT/mac/preflight.sh"
jarvis_utf8
export PYTHONUNBUFFERED=1

PY="$ROOT/.venv/bin/python"
MODE="run"
for arg in "$@"; do
  case "$arg" in
    --stop) MODE="stop" ;;
    --check|--dry-run) MODE="check" ;;
    -h|--help) printf '  Использование: ./start.command [--stop|--check]\n'; exit 0 ;;
    *) jarvis_err "Неизвестный аргумент: $arg"; exit 2 ;;
  esac
done

# --- остановка --------------------------------------------------------------
if [ "$MODE" = "stop" ]; then
  PORT="$(jarvis_port)"
  printf '\n'
  if jarvis_port_busy "$PORT"; then
    jarvis_say "На порту $PORT никто не слушает — ядро уже остановлено."
    jarvis_pause "  Enter — закрыть…"
    exit 0
  fi
  PIDS=""
  if command -v lsof >/dev/null 2>&1; then
    PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  fi
  if [ -z "$PIDS" ] && command -v pgrep >/dev/null 2>&1; then
    PIDS="$(pgrep -f "$ROOT/run.py" 2>/dev/null || true)"
  fi
  if [ -z "$PIDS" ]; then
    jarvis_err "Порт $PORT занят, но ядро среди слушающих не нашлось — остановите вручную:"
    jarvis_say "  $ lsof -nP -iTCP:$PORT -sTCP:LISTEN"
    exit 1
  fi
  # shellcheck disable=SC2086
  kill -TERM $PIDS 2>/dev/null || true
  for _i in 1 2 3 4 5 6 7 8 9 10; do
    jarvis_port_busy "$PORT" || break
    sleep 1
  done
  if jarvis_port_busy "$PORT"; then
    jarvis_warn "Не остановился за 10 секунд — убиваю принудительно."
    # shellcheck disable=SC2086
    kill -KILL $(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || echo $PIDS) 2>/dev/null || true
  fi
  jarvis_ok "Ядро на порту $PORT остановлено (pid: $PIDS)."
  jarvis_pause "  Enter — закрыть…"
  exit 0
fi

# --- проверка без запуска ---------------------------------------------------
if [ "$MODE" = "check" ]; then
  printf '\n'
  printf '  Проверка запуска на macOS (ничего не меняется)\n'
  printf '  ================================================\n'
  rc=0
  jarvis_require_venv || rc=1
  if [ "$rc" -eq 0 ]; then
    jarvis_ok "venv: $PY ($(jarvis_python_version "$PY"))"
    for mod in fastapi uvicorn sqlmodel yaml; do
      if "$PY" -c "import $mod" >/dev/null 2>&1; then
        jarvis_ok "импорт $mod"
      else
        jarvis_err "в .venv нет $mod — поставьте: ./Install-Mac.command"
        rc=1
      fi
    done
  fi
  for f in run.py config.yaml; do
    if [ -f "$ROOT/$f" ]; then
      jarvis_ok "есть $f"
    else
      jarvis_err "НЕТ $f — установка не завершена"
      rc=1
    fi
  done
  if [ -f "$ROOT/web/site/index.html" ]; then
    jarvis_ok "есть web/site/index.html"
  else
    jarvis_warn "нет web/site/index.html — сайт не отдастся: ./build_web.command (нужен Node)"
    rc=1
  fi
  PORT="$(jarvis_port)"
  jarvis_port_report "$PORT" || true
  jarvis_check_ffmpeg
  printf '\n'
  if [ "$rc" -eq 0 ]; then
    jarvis_ok "Итог: стартовать можно (./start.command)."
  else
    jarvis_err "Итог: сначала установка (./Install-Mac.command)."
  fi
  printf '\n'
  exit "$rc"
fi

# --- обычный запуск ---------------------------------------------------------
if [ ! -x "$PY" ]; then
  jarvis_err "Сначала Install-Mac.command (нет .venv/bin/python)."
  jarvis_say "  Или в Терминале: ./install.command"
  jarvis_pause "  Enter — закрыть…"
  exit 1
fi
if ! jarvis_python_version_ok "$PY"; then
  jarvis_err "В .venv интерпретатор $(jarvis_python_version "$PY") — нужно $J_PY_MIN+."
  jarvis_say "  Пересоздать окружение: rm -rf .venv && ./Install-Mac.command"
  jarvis_pause "  Enter — закрыть…"
  exit 1
fi

# после update — дотянуть пакеты (быстро, если всё уже есть)
REQ="requirements.txt"
[ -f "$ROOT/requirements-mac.txt" ] && REQ="requirements-mac.txt"
"$PY" -m pip install -r "$REQ" -q --disable-pip-version-check >/dev/null 2>&1 \
  || jarvis_warn "не смог дотянуть пакеты из $REQ (сеть?) — запускаю как есть"

PORT="$(jarvis_port)"
jarvis_check_ffmpeg

if jarvis_port_busy "$PORT"; then
  jarvis_err "Порт $PORT занят — второй экземпляр запускать не нужно."
  jarvis_say "  Остановить то, что слушает: ./start.command --stop"
  jarvis_say "  Сайт при этом доступен: http://localhost:$PORT/"
  jarvis_pause "  Enter — закрыть…"
  exit 3
fi

printf '\n'
printf '  Ядро ассистента. Остановить: Ctrl+C\n'
printf '  Сайт: http://localhost:%s/\n' "$PORT"
printf '  Лог и база: %s/data/\n' "$ROOT"
printf '\n'

restarts=0
while true; do
  code=0
  "$PY" run.py || code=$?
  # 3 = порт занят: ассистент уже запущен в другом окне (см. run.py)
  if [ "$code" -eq 3 ]; then
    printf '\n'
    printf '  Ассистент уже запущен в другом окне. Закройте это.\n'
    jarvis_pause "  Enter — закрыть…"
    exit 0
  fi
  restarts=$((restarts + 1))
  if [ "$restarts" -ge 3 ]; then
    printf '\n'
    printf '  Ядро завершилось с кодом %s три раза подряд — больше не перезапускаю.\n' "$code"
    printf '  Подробности: %s/data/core.log\n' "$ROOT"
    jarvis_pause "  Enter — закрыть…"
    exit "$code"
  fi
  printf '\n'
  printf '  Перезапуск через 3 сек (попытка %s из 3, Ctrl+C — выход)...\n' "$((restarts + 1))"
  sleep 3 || exit 0
done