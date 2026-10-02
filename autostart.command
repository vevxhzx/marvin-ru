#!/bin/bash
# Автозапуск ядра при входе в macOS (LaunchAgent).
#
#   ./autostart.command            установить автозапуск
#   ./autostart.command --remove   убрать
#   ./autostart.command --status   показать состояние (ничего не меняя)
#   ./autostart.command --check    проверить окружение и не запускать ничего
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
ROOT="$(pwd)"
export JARVIS_ROOT="$ROOT"
# shellcheck source=mac/preflight.sh
. "$ROOT/mac/preflight.sh"
jarvis_utf8

LABEL="ru.jarvis.assistant"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
START="$ROOT/start.command"
MODE="install"
PAUSE=1

for arg in "$@"; do
  case "$arg" in
    --remove|--uninstall) MODE="remove" ;;
    --status) MODE="status" ;;
    --check|--dry-run) MODE="check" ;;
    --no-pause) PAUSE=0 ;;
    -h|--help) printf '  Использование: ./autostart.command [--remove|--status|--check|--no-pause]\n'; exit 0 ;;
    *) printf '  [!] Неизвестный аргумент: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

# launchd ругается на неэкранированные & и < в путях (а папка проекта может
# называться как угодно) — экранируем значения, которые идут в plist.
xml_escape() { printf '%s' "${1:-}" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

plist_path="$(xml_escape "$PLIST")"
start_path="$(xml_escape "$START")"
root_path="$(xml_escape "$ROOT")"
log_out="$(xml_escape "$ROOT/data/autostart.log")"
log_err="$(xml_escape "$ROOT/data/autostart.err")"

loaded() {
  # macOS ≥ 13: bootout/bootstrap, раньше: unload/load
  if launchctl print "gui/$(id -u)/${LABEL}" >/dev/null 2>&1; then
    return 0
  fi
  launchctl list 2>/dev/null | grep -q "[[:space:]]${LABEL}\$" && return 0
  return 1
}

unload_agent() {
  launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 \
    || launchctl unload "$PLIST" >/dev/null 2>&1 \
    || true
}

# --- режимы без изменений --------------------------------------------------
if [ "$MODE" = "status" ]; then
  printf '\n'
  if [ -f "$PLIST" ]; then
    jarvis_ok "plist есть: $PLIST"
  else
    jarvis_say "  plist нет — автозапуск не настроен: $PLIST"
  fi
  if loaded; then
    jarvis_ok "агент загружен (запустится при следующем входе)"
  else
    jarvis_say "  агент сейчас не загружен"
  fi
  printf '  Что запускается: %s\n' "$START"
  printf '  Логи:            %s/data/autostart.log, %s/data/autostart.err\n' "$ROOT" "$ROOT"
  [ "$PAUSE" -eq 1 ] && jarvis_pause "  Enter — закрыть…"
  exit 0
fi

if [ "$MODE" = "check" ]; then
  jarvis_require_venv || exit 1
  jarvis_ok "venv на месте"
  [ -x "$START" ] && jarvis_ok "start.command запускаемый" || { jarvis_err "start.command не запускаемый: chmod +x"; exit 1; }
  DIR="$(dirname "$PLIST")"
  if [ -d "$DIR" ]; then
    jarvis_ok "каталог LaunchAgents есть: $DIR"
  else
    jarvis_say "  каталога LaunchAgents ещё нет (создастся при установке): $DIR"
  fi
  if [ ! -d "$ROOT/data" ]; then
    jarvis_warn "нет $ROOT/data — launchd не сможет писать логи; сейчас создам"
    mkdir -p "$ROOT/data"
  fi
  command -v launchctl >/dev/null 2>&1 || { jarvis_err "нет launchctl — это не macOS"; exit 1; }
  jarvis_ok "launchctl доступен"
  # Порт: если он занят, автозапуск на следующем входе стартует второе окно,
  # и start.command сразу выйдет с кодом 3 — об этом лучше узнать заранее.
  jarvis_port_report "$(jarvis_port)" || true
  [ "$PAUSE" -eq 1 ] && jarvis_pause "  Enter — закрыть…"
  exit 0
fi

if [ "$MODE" = "remove" ]; then
  unload_agent
  if [ -f "$PLIST" ]; then
    rm -f "$PLIST"
    jarvis_ok "убрано: $PLIST"
  else
    jarvis_say "  и нечего было убирать: $PLIST"
  fi
  jarvis_say "  Если автозапуск ставил Install-Mac.command — там же отдельный ярлык:"
  jarvis_say "  $ rm -f ~/Library/LaunchAgents/ru.jarvis.assistant.app.plist"
  [ "$PAUSE" -eq 1 ] && jarvis_pause "  Enter — закрыть…"
  exit 0
fi

# --- установка -------------------------------------------------------------
printf '\n'
jarvis_require_venv || exit 1
jarvis_make_executable "$ROOT"/*.command "$ROOT/mac"/*.sh || true

# Каталог для логов ОБЯЗАТЕЛЕН до загрузки plist: если StandardOutPath ведёт в
# несуществующую папку, launchd молча не запускает агент — и автозапуск «включён»,
# а ядро не поднимается. Раньше data/ создавался только при ручном запуске.
mkdir -p "$ROOT/data"
jarvis_ok "каталог для логов: $ROOT/data"

mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${start_path}</string>
  </array>
  <key>WorkingDirectory</key><string>${root_path}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>StandardOutPath</key><string>${log_out}</string>
  <key>StandardErrorPath</key><string>${log_err}</string>
</dict>
</plist>
EOF

# Проверяем, что plist валиден: битый XML launchd проглотит молча, и автозапуск
# просто не сработает при следующем входе.
if command -v plutil >/dev/null 2>&1; then
  if ! plutil -lint "$PLIST" >/dev/null 2>&1; then
    jarvis_err "plist невалиден: $PLIST"
    jarvis_say "  Скорее всего, в пути к проекту есть символы & или <>."
    plutil -lint "$PLIST" 2>&1 | sed 's/^/  /'
    exit 1
  fi
  jarvis_ok "plist валиден"
fi

unload_agent
if launchctl bootstrap "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 \
   || launchctl load "$PLIST" >/dev/null 2>&1; then
  jarvis_ok "автозапуск включён: $PLIST"
else
  jarvis_warn "launchctl не подтвердил загрузку — файл создан, но активен он или нет, не видно."
  jarvis_say "  Проверить: launchctl print gui/$(id -u)/${LABEL}"
  jarvis_say "  Или включите вручную: Системные настройки → Основные → Объекты входа."
  jarvis_say "  Ошибки при следующем входе: $ROOT/data/autostart.err"
fi

printf '\n'
printf '  При входе в macOS поднимется start.command (ядро).\n'
printf '  Если окно Терминала мешает — закройте его после старта, ядро останется жив:\n'
printf '    закрыть окно: Ctrl+C только у новых; у уже запущенного — просто окно.\n'
printf '  Голос отдельно: добавьте voice.command в «Системные настройки → Основные → Объекты входа»\n'
printf '    или запускайте вручную после логина.\n'
printf '  Убрать автозапуск: ./autostart.command --remove\n'
printf '\n'
[ "$PAUSE" -eq 1 ] && jarvis_pause "  Enter — закрыть…"
exit 0