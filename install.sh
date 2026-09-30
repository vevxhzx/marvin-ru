#!/usr/bin/env sh
# Marvin — установка на Linux/macOS.
# Делает то же, что install.bat: .venv, зависимости, config.yaml.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] Python 3 не найден. Поставьте Python 3.11+ и запустите ./install.sh снова."
  exit 1
fi

python3 setup.py

echo
echo "Дальше: ./start.sh  — откроется браузер с мастером настройки."
echo "Если что-то не работает: ./doctor.sh покажет, чего не хватает."
