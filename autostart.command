#!/bin/bash
# Автозапуск ядра при входе в macOS (LaunchAgent).
cd "$(dirname "$0")"
ROOT="$(pwd)"
LABEL="ru.marvin.assistant"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
START="$ROOT/start.command"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "  Сначала install.command"
  read -r -p "  Enter..."
  exit 1
fi
chmod +x "$ROOT"/*.command 2>/dev/null || true

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${START}</string>
  </array>
  <key>WorkingDirectory</key><string>${ROOT}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>StandardOutPath</key><string>${ROOT}/data/autostart.log</string>
  <key>StandardErrorPath</key><string>${ROOT}/data/autostart.err</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST" 2>/dev/null || launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || true

echo ""
echo "  Автозапуск включён: $PLIST"
echo "  При входе в macOS поднимется start.command (ядро)."
echo "  Голос отдельно: добавьте voice.command в «Системные настройки → Основные → Объекты входа»"
echo "    или запускайте вручную после логина."
echo ""
echo "  Убрать автозапуск:"
echo "    launchctl unload ~/Library/LaunchAgents/${LABEL}.plist"
echo "    rm ~/Library/LaunchAgents/${LABEL}.plist"
echo ""
read -r -p "  Enter — закрыть..."
