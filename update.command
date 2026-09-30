#!/bin/bash
# Обновить pip-пакеты после скачивания новой версии архива.
cd "$(dirname "$0")"
PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "  Нет .venv — сначала install.command"
  read -r -p "  Enter..."
  exit 1
fi
echo "  Обновляю пакеты..."
"$PY" -m pip install --upgrade pip -q --disable-pip-version-check
"$PY" -m pip install -r requirements.txt --disable-pip-version-check
if [ -f requirements-voice.txt ] && "$PY" -c "import voice_client" 2>/dev/null; then
  "$PY" voice_client.py --deps >/dev/null 2>&1 && \
    "$PY" -m pip install -r requirements-voice.txt -q --disable-pip-version-check || true
fi
echo ""
"$PY" -c "from core import VERSION; print('  core v' + VERSION)"
echo "  Готово. Запустите start.command"
echo ""
read -r -p "  Enter — закрыть..."
