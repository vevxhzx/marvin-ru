#!/usr/bin/env sh
# Marvin — запуск на Linux/macOS.
set -e
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  echo "[!] Marvin ещё не установлен. Сначала запустите ./install.sh"
  exit 1
fi

# после обновления проекта дотягиваем новые библиотеки (быстро, если всё на месте)
"$PY" -m pip install -r requirements.txt -q --disable-pip-version-check >/dev/null 2>&1 || true

exec "$PY" run.py
