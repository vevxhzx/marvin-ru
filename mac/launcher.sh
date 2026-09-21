#!/bin/bash
# Точка входа Marvin.app → mac/host.py (без окна Терминала).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
RES="$HERE/../Resources"

# 1) Install-Mac.command пишет сюда абсолютный путь к репо
if [ -f "$RES/project_root" ]; then
  ROOT="$(cat "$RES/project_root")"
# 2) .app лежит прямо в корне репо (dev)
elif [ -f "$HERE/../../../run.py" ]; then
  ROOT="$(cd "$HERE/../../.." && pwd)"
else
  osascript -e 'display alert "Marvin" message "Не найден проект. Запустите Install-Mac.command из папки ассистента."' 2>/dev/null || true
  exit 1
fi

export PYTHONUNBUFFERED=1
export ASSISTANT_NO_BROWSER=1
export MARVIN_OPEN="${MARVIN_OPEN:-1}"

cd "$ROOT" || exit 1
mkdir -p data

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  if command -v python3 >/dev/null 2>&1; then
    python3 "$ROOT/setup.py" >>"$ROOT/data/host.log" 2>&1 || true
  fi
fi
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  osascript -e 'display alert "Marvin" message "Нужен Python 3.12. Поставьте с python.org или: brew install python@3.12 — и снова Install-Mac.command."' 2>/dev/null || true
  exit 1
fi

exec "$PY" "$ROOT/mac/host.py"
