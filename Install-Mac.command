#!/bin/bash
# Один раз для друга на MacBook:
# 1) venv + пакеты (mac/install.sh)
# 2) приложение «J.A.R.V.I.S.» в ~/Applications (иконка в строке меню, без терминала)
# 3) опционально — автозапуск при входе
#
#   ./Install-Mac.command           обычный запуск
#   ./Install-Mac.command --check   ничего не ставить, только проверить окружение
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
ROOT="$(pwd)"
export JARVIS_ROOT="$ROOT"
# shellcheck source=mac/preflight.sh
. "$ROOT/mac/preflight.sh"
jarvis_utf8

# Временная папка для иконки — и trap, чтобы при любой ошибке ничего не осталось
# в data/ мусором (иначе .AppIcon.iconset живёт вечно после неудачного iconutil).
TMPD=""
cleanup() { [ -n "$TMPD" ] && [ -d "$TMPD" ] && rm -rf "$TMPD"; return 0; }
trap cleanup EXIT INT TERM

CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --check|--dry-run) CHECK_ONLY=1 ;;
    -h|--help) printf '  Использование: ./Install-Mac.command [--check]\n'; exit 0 ;;
    *) printf '  [!] Неизвестный аргумент: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

clear 2>/dev/null || true
printf '\n'
printf '  ╔══════════════════════════════════════════╗\n'
printf '  ║   Marvin — установка как приложения Mac  ║\n'
printf '  ╚══════════════════════════════════════════╝\n'
printf '\n'
printf '  Папка проекта: %s\n' "$ROOT"
printf '\n'

# --- 0. права на исполнение и Gatekeeper -----------------------------------
# Двойной клик по .command из скачанного ZIP: сначала снимаем карантин
# (иначе Terminal скажет «не удалось открыть»), потом возвращаем бит запуска.
chmod +x "$ROOT"/*.command "$ROOT/mac"/*.sh 2>/dev/null || true
if ! jarvis_quarantine_clear "$ROOT"; then
  jarvis_say ""
  jarvis_say "  Часто помогает: Finder → правый клик по Install-Mac.command → «Открыть»"
  jarvis_say "  и в системном диалоге нажать «Открыть» ещё раз (это подтверждение для Gatekeeper)."
  jarvis_say ""
fi

# --- проверка без установки ------------------------------------------------
# Полный отчёт (включая Python, порт и место) собирает mac/install.sh --check,
# поэтому режим проверки запускается первым — иначе не увидим остальные проблемы.
if [ "$CHECK_ONLY" -eq 1 ]; then
  # через `bash`, а не напрямую: ZIP из GitHub не сохраняет бит запуска,
  # и на свежем Mac «Permission denied» на .sh — самая частая первая ошибка
  exec /bin/bash "$ROOT/mac/install.sh" --check
fi

# Python проверяем ДО установки, чтобы не печатать «1/3 …» и падать через две минуты.
# На Apple Silicon python3 из Xcode Command Line Tools — это 3.9, проекту нужно 3.10+.
if ! PY3=$(jarvis_pick_python3); then
  jarvis_say ""
  jarvis_explain_python "$(command -v python3 2>/dev/null || true)"
  jarvis_say ""
  jarvis_pause "  Enter — закрыть…"
  exit 1
fi
jarvis_ok "python3 $(jarvis_python_version "$PY3") — $PY3"
case "$PY3" in
  /usr/bin/python3*)
    jarvis_warn "взят /usr/bin/python3 (Xcode Command Line Tools)."
    jarvis_say "  Он подойдёт, но обновляется вместе с Xcode. Надёжнее: brew install python@3.12"
    ;;
esac
jarvis_check_writable "$ROOT" || { jarvis_pause "  Enter — закрыть…"; exit 1; }

# --- 1/3. окружение и пакеты ----------------------------------------------
printf '  [1/3] Библиотеки (2–5 мин при первом разе)…\n'
if ! /bin/bash "$ROOT/mac/install.sh"; then
  jarvis_say ""
  jarvis_err "Установка не прошла. Текст выше — что делать."
  jarvis_say "  Повторить позже: ./Install-Mac.command   (или только проверить: ./Install-Mac.command --check)"
  jarvis_pause "  Enter — закрыть…"
  exit 1
fi

# --- окружение: ffmpeg и порт ----------------------------------------------
jarvis_check_ffmpeg
PORT="$(jarvis_port)"
jarvis_port_report "$PORT" || true

# --- 2/3. собираем J.A.R.V.I.S..app → ~/Applications ----------------------
printf '\n  [2/3] Собираю J.A.R.V.I.S..app → ~/Applications …\n'
APP="$HOME/Applications/J.A.R.V.I.S..app"
mkdir -p "$HOME/Applications"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$ROOT/mac/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/mac/launcher.sh" "$APP/Contents/MacOS/J.A.R.V.I.S."
chmod +x "$APP/Contents/MacOS/J.A.R.V.I.S."
# абсолютный путь к репо (проект может лежать где угодно)
printf '%s\n' "$ROOT" > "$APP/Contents/Resources/project_root"

# иконка .icns, если есть sips/iconutil
ICON_SRC=""
for c in "$ROOT/web/site/icon-512.png" "$ROOT/web/public/icon-512.png"; do
  [ -f "$c" ] && ICON_SRC="$c" && break
done
if [ -n "$ICON_SRC" ] && command -v sips >/dev/null && command -v iconutil >/dev/null; then
  ICONSET="$TMPD/AppIcon.iconset"
  [ -n "$TMPD" ] || TMPD="$(mktemp -d 2>/dev/null || echo "$ROOT/data/.iconbuild.$$")"
  mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1 || true
    sips -z $((s*2)) $((s*2)) "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1 || true
  done
  if iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null; then
    jarvis_ok "иконка собрана"
  else
    jarvis_warn "iconutil не смог — приложение будет без иконки (работать не мешает)"
  fi
elif [ -n "$ICON_SRC" ]; then
  cp "$ICON_SRC" "$APP/Contents/Resources/AppIcon.png" 2>/dev/null || true
else
  jarvis_warn "не нашёл web/site/icon-512.png — приложение будет без иконки"
fi

# снять карантин у .app (Gatekeeper проверяет и собранное приложение)
jarvis_quarantine_clear "$APP" || true

# что должно быть в .app — иначе Finder «не открывает»
missing=""
for f in "$APP/Contents/Info.plist" "$APP/Contents/MacOS/J.A.R.V.I.S." "$APP/Contents/Resources/project_root"; do
  [ -e "$f" ] || missing="$missing $(basename "$f")"
done
if [ -n "$missing" ]; then
  jarvis_err "Приложение собралось не полностью, нет:$missing"
  jarvis_say "  Удалите $APP и запустите Install-Mac.command ещё раз."
  jarvis_pause "  Enter — закрыть…"
  exit 1
fi

# --- 3/3. готово -----------------------------------------------------------
printf '\n  [3/3] Готово: %s\n' "$APP"
printf '\n'
GO="$(jarvis_ask '  Запустить сейчас? [Y/n]' 'y')"
if jarvis_yes "$GO"; then
  open "$APP" || jarvis_say "  Не открылось автоматически — запустите вручную: open \"$APP\""
  printf '  Смотри иконку в строке меню (справа вверху, возле часов).\n'
  printf '  Кликни → «Открыть сайт». Первый раз — мастер настройки.\n'
fi

printf '\n'
AU="$(jarvis_ask '  Добавить в автозагрузку при входе в Mac? [y/N]' 'n')"
if jarvis_yes "$AU"; then
  if "$ROOT/autostart.command" --no-pause; then
    printf '  Автозапуск включён.\n'
  else
    jarvis_warn "Автозапуск не включился — подробности выше. Можно повторить: ./autostart.command"
  fi
fi

printf '\n'
printf '  Дальше другу:\n'
printf '  · иконка «J.A.R.V.I.S.» в Программах / Launchpad (папка Applications)\n'
printf '  · можно перетащить в Dock\n'
printf '  · Выйти — из меню иконки в строке меню\n'
printf '  · Без .app: ./start.command (окно Терминала, Ctrl+C — остановить)\n'
printf '  · Порт сайта: %s\n' "$PORT"
printf '  · Логи: %s/data/core.log и %s/data/host.log\n' "$ROOT" "$ROOT"
printf '\n'
printf '  Голос по-прежнему отдельный (микрофон): install_voice.command\n'
printf '  Ollama: https://ollama.com/download  (или cloud в мастере)\n'
jarvis_no_sudo_note
printf '\n'
jarvis_pause "  Enter — закрыть…"