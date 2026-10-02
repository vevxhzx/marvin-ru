#!/bin/bash
# ---------------------------------------------------------------------------
# Общие проверки для mac-скриптов проекта (Install-Mac / start / update /
# autostart / phone). Подключается, а не запускается:
#
#     . "$(dirname "$0")/mac/preflight.sh"
#
# Зачем отдельный файл: python нужной версии, занятость порта, ffmpeg,
# карантин, кодировка и подсказка про sudo нужны всем шести скриптам. Когда они
# живут в одном месте, они не разъезжаются: раньше проверка версии Python была
# только в install.command, а Install-Mac.command и start.command молча падали.
#
# Совместимость: только bash 3.2 (тот, что на свежем macOS) — без mapfile,
# без ассоциативных массивов, без ${var^^}. Никаких фич из bash 4+.
#
# Здесь нет `set -e`: библиотеку подключают скрипты, которые сами решают,
# прерываться им на ошибке или нет (в start.command цикл автоперезапуска).
# ---------------------------------------------------------------------------

# Минимальная версия Python — та же, что проверяет setup.py.
J_PY_MIN="3.10"

# --------------------------------------------------------------------------
# Вывод
# --------------------------------------------------------------------------
# Сообщения принимают printf-аргументы: jarvis_warn "Порт %s занят" "$PORT".
# Один аргумент печатается дословно (чтобы % в тексте не съедался).
_jarvis_fmt() {
  if [ "$#" -eq 0 ]; then return 0; fi
  if [ "$#" -eq 1 ]; then printf '%s' "$1"; return 0; fi
  printf "$@"
}
jarvis_say()  { printf '  %s\n' "$(_jarvis_fmt "$@")"; }
jarvis_ok()   { printf '  [ок] %s\n' "$(_jarvis_fmt "$@")"; }
jarvis_warn() { printf '  [!] %s\n' "$(_jarvis_fmt "$@")"; }
jarvis_err()  { printf '  [x] %s\n' "$(_jarvis_fmt "$@")" >&2; }

# Пауза «Enter — закрыть». В неинтерактивном запуске (CI, LaunchAgent, pipe)
# не блокируемся: скрипт обязан уметь завершиться без терминала.
jarvis_pause() {
  [ -t 0 ] || return 0
  [ -n "${1:-}" ] && printf '  %s' "$1"
  read -r _ || true
  printf '\n'
}

# Вопрос с ответом по умолчанию. Без терминала берём умолчание (в CI — «нет»).
jarvis_ask() {
  _q="$1"; _d="${2:-n}"
  if [ ! -t 0 ]; then
    printf '  %s [%s] — %s (нет терминала, беру «%s»)\n' "$_q" "$_d" "$_d" "$_d"
    printf '%s' "$_d"
    return 0
  fi
  printf '  %s [%s]: ' "$_q" "$_d"
  read -r _a || _a=""
  [ -z "$_a" ] && _a="$_d"
  printf '%s' "$_a"
}

jarvis_yes() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    y|yes|д|да) return 0 ;;
    *) return 1 ;;
  esac
}

# --------------------------------------------------------------------------
# Кодировка. Русские сообщения в Terminal ломаются, если LANG=C — pip и
# Python начинают спорить с stdout. Ничего не ломаем, только уточняем.
# --------------------------------------------------------------------------
jarvis_utf8() {
  case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *UTF-8|*utf8|*UTF8|*utf-8) : ;;
    "") export LANG="${LANG:-en_US.UTF-8}" ;;
    *)  : ;;   # пользователь выбрал не-UTF локаль — уважаем, но предупредим
  esac
  export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
  export PYTHONUTF8="${PYTHONUTF8:-1}"
}

# --------------------------------------------------------------------------
# Homebrew. На Apple Silicon `brew` лежит в /opt/homebrew/bin, которого нет в
# PATH у приложений, запущенных из Finder, — классическая причина
# «brew: command not found» из .command. Ищем руками.
# --------------------------------------------------------------------------
jarvis_find_brew() {
  if command -v brew >/dev/null 2>&1; then
    command -v brew
    return 0
  fi
  for _b in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
    [ -x "$_b" ] && { printf '%s' "$_b"; return 0; }
  done
  return 1
}

# --------------------------------------------------------------------------
# Python 3 нужной версии
# --------------------------------------------------------------------------
# 0 — версия подходит; 1 — слишком старая/новая; 2 — интерпретатор не запустился.
jarvis_python_version_ok() {
  _p="${1:-python3}"
  command -v "$_p" >/dev/null 2>&1 || [ -x "$_p" ] || return 2
  "$_p" -c 'import sys; sys.exit(0 if sys.version_info >= tuple(int(x) for x in sys.argv[1].split(".")) else 1)' \
      "$J_PY_MIN" >/dev/null 2>&1
}

jarvis_python_version() {
  "${1:-python3}" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || printf '?'
}

# Печатает путь к интерпретатору, годному для .venv (3.10+), и ничего — если
# такого нет.
# Порядок кандидатов важен. На Apple Silicon `/usr/bin/python3` — это python из
# Xcode Command Line Tools, там обычно 3.9, и ставить им окружение бессмысленно
# (setup.py потом скажет «нужен 3.10+» и установщик молча закроется). Поэтому
# сначала пробуем то, что реально просит PATH (у человека с Homebrew там 3.12),
# потом известные места Homebrew (нужны, когда .command запущен из Finder и PATH
# не содержит /opt/homebrew/bin), и только в самом конце /usr/bin/python3.
jarvis_pick_python3() {
  _br=$(jarvis_find_brew || true)
  _bp=""
  [ -n "$_br" ] && _bp=$("$_br" --prefix 2>/dev/null)/bin/python3
  _path3=$(command -v python3 2>/dev/null || true)
  for _p in "$_path3" "$_bp" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
            python3.13 python3.12 python3.11 python3.10 /usr/bin/python3; do
    [ -n "$_p" ] || continue
    if jarvis_python_version_ok "$_p"; then
      printf '%s' "$_p"
      return 0
    fi
  done
  return 1
}

# Диагностика «python3 есть, но не тот». Ничего не ставит, ничего не меняет.
jarvis_explain_python() {
  _have="$1"
  jarvis_err "Подходящий Python $J_PY_MIN+ не найден (в PATH: ${_have:-ничего})."
  jarvis_say ""
  jarvis_say "  Что делать (sudo не нужен, ничего системного):"
  jarvis_say "    1) Homebrew — самый простой путь на Apple Silicon:"
  jarvis_say "         /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
  jarvis_say "         затем:  brew install python@3.12"
  jarvis_say "    2) Без Homebrew: https://www.python.org/downloads/macos/ → Python 3.12 (pkg-установщик)."
  jarvis_say ""
  if [ -n "$_have" ]; then
    jarvis_say "  Если python3 в PATH есть, но версия ниже — посмотрите, что именно нашлось:"
    jarvis_say "    \$ $_have -V"
    jarvis_say "  На Apple Silicon это почти всегда 3.9 из Xcode Command Line Tools."
    jarvis_say "  Поставьте Homebrew/Python 3.12 и запустите скрипт снова."
  fi
}

# --------------------------------------------------------------------------
# Путь к интерпретатору виртуального окружения (в venv он ВСЕГДА bin/python)
# --------------------------------------------------------------------------
jarvis_venv_python() { printf '%s/.venv/bin/python' "${JARVIS_ROOT:-$(pwd)}"; }

jarvis_require_venv() {
  _vp=$(jarvis_venv_python)
  if [ ! -x "$_vp" ]; then
    jarvis_err "Нет виртуального окружения: ${JARVIS_ROOT:-$(pwd)}/.venv"
    jarvis_say "  Поставьте один раз: двойной клик по Install-Mac.command"
    jarvis_say "  (или в Терминале: ./install.command), потом запустите снова."
    return 1
  fi
  if ! jarvis_python_version_ok "$_vp"; then
    jarvis_warn "В .venv интерпретатор $(jarvis_python_version "$_vp") — старее $J_PY_MIN."
    jarvis_say "  Проще пересоздать: rm -rf .venv && ./Install-Mac.command"
    return 1
  fi
  return 0
}

# --------------------------------------------------------------------------
# Порт. Берём из config.yaml (server.port), как это делает run.py и jarvis_app.py,
# иначе скрипт «занято/свободно» будет врать про нестандартный порт.
# --------------------------------------------------------------------------
jarvis_port() {
  _root="${JARVIS_ROOT:-$(pwd)}"
  _py=$(jarvis_venv_python)
  [ -x "$_py" ] || _py=$(command -v python3 2>/dev/null || true)
  if [ -n "$_py" ] && [ -f "$_root/config.yaml" ]; then
    _p=$("$_py" - "$_root/config.yaml" <<'PY' 2>/dev/null
import sys
try:
    import yaml
    d = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
    print(int((d.get("server") or {}).get("port") or 8765))
except Exception:
    print(8765)
PY
    )
    case "$_p" in
      ''|*[!0-9]*) _p=8765 ;;
    esac
    printf '%s' "$_p"
    return 0
  fi
  # yaml нет (или venv не создан) — грубый разбор блока server: в config.yaml
  if [ -f "$_root/config.yaml" ]; then
    _p=$(awk '
      /^server:[[:space:]]*$/ {insrv=1; next}
      /^[A-Za-z_]/ {insrv=0}
      insrv && $1=="port:" {print $2; exit}' "$_root/config.yaml" 2>/dev/null | tr -d '"'"'"' ')
    case "$_p" in
      ''|*[!0-9]*) _p=8765 ;;
    esac
    printf '%s' "$_p"
    return 0
  fi
  printf '8765'
}

# 0 — порт свободен; 1 — кто-то слушает.
jarvis_port_busy() {
  _port="${1:-8765}"
  _py=$(jarvis_venv_python)
  [ -x "$_py" ] || _py=$(command -v python3 2>/dev/null || true)
  if [ -n "$_py" ]; then
    "$_py" - "$_port" <<'PY' >/dev/null 2>&1
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
    return $?
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$_port" -sTCP:LISTEN >/dev/null 2>&1 && return 1
    return 0
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$_port" >/dev/null 2>&1 && return 1
    return 0
  fi
  return 0   # нечем проверить — не мешаем запуску
}

# Понятное сообщение вместо молчаливого падения ядра.
jarvis_port_report() {
  _port="${1:-8765}"
  if jarvis_port_busy "$_port"; then
    jarvis_ok "Порт $_port свободен."
    return 0
  fi
  jarvis_warn "Порт $_port уже занят — скорее всего, ассистент уже запущен."
  jarvis_say "  Второй экземпляр поднимать не нужно: у него тот же Telegram-токен."
  jarvis_say "  Закройте другое окно/иконку в строке меню, либо:"
  jarvis_say "    $ lsof -nP -iTCP:$_port -sTCP:LISTEN     # кто слушает"
  jarvis_say "    $ kill <pid>                             # остановить"
  jarvis_say "  Порт меняется в config.yaml → server.port (и в ⚙ Настройки на сайте)."
  return 1
}

# --------------------------------------------------------------------------
# ffmpeg. На mac его ставят через brew; без него голосовые из Telegram
# декодирует PyAV (пакет av), но mp4/нестандартные форматы — нет.
# Молча умирать нельзя: предупреждаем и объясняем, как поставить.
# --------------------------------------------------------------------------
jarvis_check_ffmpeg() {
  if command -v ffmpeg >/dev/null 2>&1; then
    jarvis_ok "ffmpeg найден: $(command -v ffmpeg)"
    return 0
  fi
  jarvis_warn "ffmpeg не найден в PATH."
  jarvis_say "  Критично только для нестандартных аудио/видео форматов;"
  jarvis_say "  голосовые OGG/Opus из Telegram декодирует PyAV (пакет av) — это уже стоит."
  _br=$(jarvis_find_brew || true)
  if [ -n "$_br" ]; then
    jarvis_say "  Поставить (1–2 минуты, без sudo):   $_br install ffmpeg"
  else
    jarvis_say "  Поставить: brew install ffmpeg   (сначала Homebrew: https://brew.sh)"
  fi
  jarvis_say "  Продолжаю без него — если какой-то формат не прочитается, вернитесь сюда."
  return 0
}

# --------------------------------------------------------------------------
# Gatekeeper. Скачанный ZIP помечается карантином: двойной клик по .command
# даёт «не удалось открыть, потому что это приложение от unidentified developer».
# xattr -dr com.apple.quarantine снимает метку рекурсивно.
# --------------------------------------------------------------------------
jarvis_quarantine_clear() {
  _target="${1:-${JARVIS_ROOT:-$(pwd)}}"
  if [ "$(uname -s)" != "Darwin" ]; then
    return 0
  fi
  if ! command -v xattr >/dev/null 2>&1; then
    return 0
  fi
  # macOS ≥ 12 без этой команды всё равно скажет «quarantine» в xattr -p
  if xattr -p com.apple.quarantine "$_target" >/dev/null 2>&1; then
    if xattr -dr com.apple.quarantine "$_target" 2>/dev/null || xattr -cr "$_target" 2>/dev/null; then
      jarvis_ok "Карантин Gatekeeper снят: $_target"
      return 0
    fi
    jarvis_warn "Не смог снять карантин с $_target (нет прав на файлы)."
    jarvis_say "  Без sudo это иногда не лечится — тогда откройте папку в Finder,"
    jarvis_say "  ПКМ по .command → «Открыть», и в диалоге нажмите «Открыть» ещё раз."
    return 1
  fi
  return 0
}

# chmod +x — второй по частоте повод «Terminal: permission denied».
jarvis_make_executable() {
  _ok=0
  for _f in "$@"; do
    [ -e "$_f" ] || continue
    chmod +x "$_f" 2>/dev/null && _ok=1 || jarvis_warn "не смог chmod +x: $_f"
  done
  return $_ok
}

# --------------------------------------------------------------------------
# Права на запись. Установка в ~/Downloads или в /Applications без прав должна
# сказать об этом ДО первой попытки создать .venv.
# --------------------------------------------------------------------------
jarvis_check_writable() {
  _dir="${1:-${JARVIS_ROOT:-$(pwd)}}"
  if [ ! -d "$_dir" ]; then
    jarvis_err "Папки нет: $_dir"
    return 1
  fi
  if [ -w "$_dir" ]; then
    jarvis_ok "Папка доступна для записи: $_dir"
    return 0
  fi
  jarvis_err "Нет прав на запись в $_dir"
  jarvis_say "  Перенесите проект в свою папку (например ~/Assistant) и запустите снова."
  jarvis_say "  sudo для установки НЕ нужен и не используется."
  return 1
}

# --------------------------------------------------------------------------
# Сборка ядра: сколько свободного места нужно. ~1 ГБ с учётом кэшей pip.
# --------------------------------------------------------------------------
jarvis_check_disk() {
  _root="${JARVIS_ROOT:-$(pwd)}"
  _df=$(df -Pk "$_root" 2>/dev/null | awk 'NR==2 {print $4}')
  case "$_df" in
    ''|*[!0-9]*) return 0 ;;   # df не сработал — не мешаем
  esac
  # базовая установка (requirements-mac.txt + кэш pip) — около 1 ГБ.
  # Просим 2 ГБ свободных, чтобы не упереться в середине установки.
  # Голосовой аддон сверху ещё ~3 ГБ — про него отдельно в install_voice.
  if [ "$_df" -lt 2000000 ]; then
    jarvis_warn "Свободно на диске всего $(( _df / 1000000 )) ГБ — базовой установке нужно ~1 ГБ."
    jarvis_say "  Освободите место («Системные настройки → Общие → Хранилище») и повторите."
    jarvis_say "  Голосовой аддон сверху возьмёт ещё ~3 ГБ."
    return 1
  fi
  jarvis_ok "Места на диске хватает (~$(( _df / 1000000 )) ГБ свободно)."
  return 0
}

# Сообщение «ничего от sudo не нужно» — один раз, в конце установки.
jarvis_no_sudo_note() {
  jarvis_say "  sudo не требовался: всё ставится в вашу папку и в ~/.venv."
}