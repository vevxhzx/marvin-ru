#!/usr/bin/env sh
# Marvin — проверка окружения на Linux/macOS: что установлено и что чинить.
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "[!] Python не найден. Поставьте Python 3.11+ и запустите ./install.sh"
  exit 1
fi

"$PY" doctor.py "$@"
