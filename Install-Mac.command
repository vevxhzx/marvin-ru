#!/bin/bash
# Один раз для друга на MacBook:
# 1) venv + пакеты
# 2) приложение «Marvin» в ~/Applications (иконка в строке меню, без терминала)
# 3) опционально — автозапуск при входе
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
clear
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   Marvin — установка как приложения Mac  ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  Папка проекта: $ROOT"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "  Нужен Python 3.12:"
  echo "    brew install python@3.12"
  echo "    или https://www.python.org/downloads/"
  echo ""
  read -r -p "  Enter…"
  exit 1
fi

chmod +x *.command mac/launcher.sh 2>/dev/null || true
# снять quarantine с ZIP
xattr -cr . 2>/dev/null || true

echo "  [1/3] Библиотеки (2–5 мин при первом разе)…"
python3 setup.py
PY="$ROOT/.venv/bin/python"
"$PY" -m pip install pystray pillow -q --disable-pip-version-check

echo ""
echo "  [2/3] Собираю Marvin.app → ~/Applications …"
APP="$HOME/Applications/Marvin.app"
mkdir -p "$HOME/Applications"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$ROOT/mac/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/mac/launcher.sh" "$APP/Contents/MacOS/Marvin"
chmod +x "$APP/Contents/MacOS/Marvin"
# абсолютный путь к репо (проект может лежать где угодно)
echo "$ROOT" > "$APP/Contents/Resources/project_root"

# иконка .icns если есть sips/iconutil
ICON_SRC=""
for c in "$ROOT/web/site/icon-512.png" "$ROOT/web/public/icon-512.png"; do
  [ -f "$c" ] && ICON_SRC="$c" && break
done
if [ -n "$ICON_SRC" ] && command -v sips >/dev/null && command -v iconutil >/dev/null; then
  ICONSET="$ROOT/data/_AppIcon.iconset"
  rm -rf "$ICONSET" && mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1 || true
    sips -z $((s*2)) $((s*2)) "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1 || true
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || true
  rm -rf "$ICONSET"
elif [ -n "$ICON_SRC" ]; then
  cp "$ICON_SRC" "$APP/Contents/Resources/AppIcon.png" 2>/dev/null || true
fi

# убрать quarantine у .app
xattr -cr "$APP" 2>/dev/null || true

echo "  [3/3] Готово: $APP"
echo ""
read -r -p "  Запустить сейчас? [Y/n]: " GO
if [ -z "$GO" ] || [ "$GO" = "y" ] || [ "$GO" = "Y" ]; then
  open "$APP"
  echo "  Смотри иконку в строке меню (справа вверху, возле часов)."
  echo "  Кликни → «Открыть сайт». Первый раз — мастер настройки."
fi
echo ""
read -r -p "  Добавить в автозагрузку при входе в Mac? [y/N]: " AU
if [ "$AU" = "y" ] || [ "$AU" = "Y" ]; then
  LABEL="ru.marvin.assistant.app"
  PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>${APP}</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST" 2>/dev/null || launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  echo "  Автозапуск: $PLIST"
fi

echo ""
echo "  Дальше другу:"
echo "  · иконка «Marvin» в Программах / Launchpad (папка Applications)"
echo "  · можно перетащить в Dock"
echo "  · Выйти — из меню иконки в строке меню"
echo "  · Логи: $ROOT/data/core.log и host.log"
echo ""
echo "  Голос по-прежнему отдельный (микрофон): install_voice.command"
echo "  Ollama: https://ollama.com/download  (или cloud в мастере)"
echo ""
read -r -p "  Enter — закрыть…"
