#!/bin/bash
# Установка на macOS / Linux. Двойной клик в Finder (macOS) или: ./install.command
cd "$(dirname "$0")"
clear
echo ""
echo "  ================================================"
echo "    Ассистент  —  установка (macOS / Linux)"
echo "  ================================================"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "  [!] Python 3 не найден."
  echo "      macOS:  brew install python@3.12"
  echo "              (Homebrew: https://brew.sh)"
  echo "      или скачайте: https://www.python.org/downloads/"
  echo ""
  read -r -p "  Enter — закрыть..."
  exit 1
fi

PYVER=$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "?")
echo "  Python $PYVER · $(command -v python3)"
echo ""
python3 setup.py
code=$?
echo ""
if [ $code -eq 0 ]; then
  echo "  Дальше: дважды кликните start.command"
  echo "  (или в Терминале: ./start.command)"
fi
echo ""
read -r -p "  Enter — закрыть..."
exit $code
