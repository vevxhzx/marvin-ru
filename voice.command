#!/bin/bash
# Голосовой клиент. Ядро (start.command) должно уже работать.
cd "$(dirname "$0")"
export PYTHONUNBUFFERED=1
PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "  Нет .venv — install.command"
  read -r -p "  Enter..."
  exit 1
fi

echo ""
echo "  Голосовой клиент"
echo "  папка: $(pwd)"
echo "  лог:   data/voice.log"
echo ""

echo "  [1/2] проверка пакетов..."
if ! "$PY" voice_client.py --deps >/dev/null 2>&1; then
  echo "  [!] Голосовые пакеты не стоят — запустите install_voice.command"
  read -r -p "  Enter..."
  exit 1
fi

echo "  [2/2] слушаю. Имя ассистента или горячая клавиша. Ctrl+C — стоп."
echo ""
"$PY" voice_client.py "$@"
code=$?
echo ""
if [ $code -ne 0 ]; then
  echo "  [!] код $code · подробности в data/voice.log"
  read -r -p "  Enter..."
fi
exit $code
