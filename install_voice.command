#!/bin/bash
# Голосовой аддон (микрофон, wake word, озвучка, трей). macOS / Linux.
# Управление окнами/«что на экране» как на Windows — частично; ядро + Telegram + сайт — полностью.
cd "$(dirname "$0")"
PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "  Сначала install.command, потом start.command, потом это."
  read -r -p "  Enter..."
  exit 1
fi

echo ""
echo "  Голосовой аддон (~700 МБ: whisper, vosk, mic, tray)"
echo ""
echo "  [1/2] Базовые пакеты..."
if ! "$PY" -m pip install -r requirements-voice.txt --disable-pip-version-check; then
  echo "  [!] pip не смог. Проверьте интернет и повторите."
  read -r -p "  Enter..."
  exit 1
fi

echo ""
echo "  [2/2] Silero — офлайн-озвучка (~2 ГБ, опционально)."
echo "        Без неё говорит голос Microsoft Edge (нужен интернет)."
read -r -p "        Ставить Silero? [y/N]: " SIL
if [ "$SIL" = "y" ] || [ "$SIL" = "Y" ]; then
  "$PY" -m pip install -r requirements-silero.txt --disable-pip-version-check \
    --index-url https://download.pytorch.org/whl/cpu || \
    echo "  [!] Silero не встал — будет Edge TTS."
fi

echo ""
# PortAudio для sounddevice
if [[ "$(uname -s)" == "Darwin" ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "  [i] Если микрофон не откроется: установите Homebrew (https://brew.sh) и выполните:"
    echo "      brew install portaudio"
  elif ! brew list portaudio >/dev/null 2>&1; then
    echo "  [i] Ставлю portaudio (нужен sounddevice)..."
    brew install portaudio || echo "  [!] brew install portaudio не вышло — поставьте вручную."
  fi
  echo "  [i] macOS спросит доступ к Микрофону для Терминала — разрешите."
fi

echo ""
"$PY" voice_client.py --check || true
echo ""
echo "  Готово. Запущено ядро (start.command) → затем voice.command"
echo ""
read -r -p "  Enter — закрыть..."
