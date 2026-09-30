#!/bin/bash
# Запуск ядра. Окно/вкладку Терминала держите открытой.
# Двойной клик в Finder или: ./start.command
cd "$(dirname "$0")"
export PYTHONUNBUFFERED=1

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "  Сначала install.command (нет .venv)."
  read -r -p "  Enter — закрыть..."
  exit 1
fi

# после update — дотянуть пакеты (быстро, если всё уже есть)
"$PY" -m pip install -r requirements.txt -q --disable-pip-version-check >/dev/null 2>&1 || true

echo ""
echo "  Ядро ассистента. Остановить: Ctrl+C"
echo "  Лог и база: $(pwd)/data/"
echo ""

while true; do
  "$PY" run.py
  code=$?
  # 3 = уже запущен (если когда-нибудь появится lock); пока просто рестарт
  if [ $code -eq 3 ]; then
    echo ""
    echo "  Ассистент уже запущен в другом окне. Закройте это."
    read -r -p "  Enter — закрыть..."
    exit 0
  fi
  echo ""
  echo "  Перезапуск через 3 сек (Ctrl+C — выход)..."
  sleep 3 || exit 0
done
