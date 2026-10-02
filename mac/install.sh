#!/bin/bash
# ---------------------------------------------------------------------------
# Установка окружения на macOS (и в CI без mac-железа).
#
#   ./mac/install.sh           полная установка: .venv + зависимости + config.yaml
#   ./mac/install.sh --check   НИЧЕГО не меняет: только проверки окружения (dry-run)
#
# Отдельный файл, а не блок в Install-Mac.command, потому что:
#   · на mac нужен НЕ requirements.txt, а requirements-mac.txt (см. файл — там
#     объяснение про torch и отсутствие колёс для Intel Mac);
#   · ту же установку должен уметь запустить CI (--check), где нет .venv;
#   · Install-Mac.command отвечает только за сборку .app и остаётся тонким.
#
# setup.py (общий для Windows) трогать нельзя: он жёстко ставит requirements.txt.
# Поэтому здесь та же логика, что в setup.py, но с правильным requirements-файлом.
# ---------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JARVIS_ROOT="$(cd "$HERE/.." && pwd)"
export JARVIS_ROOT
# shellcheck source=mac/preflight.sh
. "$HERE/preflight.sh"

CHECK_ONLY=0
for _arg in "$@"; do
  case "$_arg" in
    --check|--dry-run) CHECK_ONLY=1 ;;
    -h|--help)
      printf '  Использование: mac/install.sh [--check]\n'
      exit 0 ;;
    *) jarvis_err "Неизвестный аргумент: $_arg"; exit 2 ;;
  esac
done
jarvis_utf8

STEP=0
TOTAL=4
step() { STEP=$((STEP + 1)); printf '\n  [%d/%d] %s\n' "$STEP" "$TOTAL" "$1"; }
fail() { jarvis_err "$1"; shift; [ $# -gt 0 ] && jarvis_say "$@"; exit 1; }

REQ=""
if [ -f "$JARVIS_ROOT/requirements-mac.txt" ]; then
  REQ="requirements-mac.txt"
elif [ -f "$JARVIS_ROOT/requirements.txt" ]; then
  REQ="requirements.txt"
  jarvis_warn "requirements-mac.txt не найден — ставлю общий requirements.txt (на Intel Mac может упасть torch)."
fi

VENV_PY="$JARVIS_ROOT/.venv/bin/python"

# ===========================================================================
# Режим проверки: ничего не пишем, только отвечаем на вопрос «а встанет ли?»
# ===========================================================================
if [ "$CHECK_ONLY" -eq 1 ]; then
  printf '\n  ================================================\n'
  printf '    Проверка окружения macOS (ничего не меняется)\n'
  printf '  ================================================\n'
  printf '  система:  %s %s\n' "$(uname -s)" "$(uname -m)"
  printf '  папка:   %s\n' "$JARVIS_ROOT"
  printf '\n'

  rc=0

  if PY3=$(jarvis_pick_python3); then
    jarvis_ok "python3 $(jarvis_python_version "$PY3") — $PY3"
  else
    jarvis_explain_python "$(command -v python3 2>/dev/null || true)"
    rc=1
  fi

  jarvis_check_writable "$JARVIS_ROOT" || rc=1
  jarvis_check_disk || rc=1

  if [ -n "$REQ" ]; then
    jarvis_ok "файл зависимостей: $REQ"
  else
    jarvis_err "нет ни requirements-mac.txt, ни requirements.txt"
    rc=1
  fi

  jarvis_check_ffmpeg

  if jarvis_port_busy "$(jarvis_port)"; then
    jarvis_ok "порт $(jarvis_port) свободен"
  else
    jarvis_warn "порт $(jarvis_port) занят — ядро, видимо, уже запущено (это не ошибка установки)"
  fi

  for f in run.py config.example.yaml mac/host.py; do
    if [ -f "$JARVIS_ROOT/$f" ]; then
      jarvis_ok "есть $f"
    else
      jarvis_err "НЕТ $f — архив распакован не полностью"
      rc=1
    fi
  done
  if [ -f "$JARVIS_ROOT/web/site/index.html" ]; then
    jarvis_ok "есть web/site/index.html (собранный сайт, Node не нужен)"
  else
    jarvis_warn "нет web/site/index.html — сайт придётся пересобрать: ./build_web.command (нужен Node)"
    rc=1
  fi

  if [ -x "$VENV_PY" ]; then
    jarvis_ok "venv: python $(jarvis_python_version "$VENV_PY") ($VENV_PY)"
    for mod in fastapi uvicorn sqlmodel yaml; do
      if "$VENV_PY" -c "import $mod" >/dev/null 2>&1; then
        jarvis_ok "импорт $mod"
      else
        jarvis_err "в .venv нет $mod — установка недоделана: ./mac/install.sh"
        rc=1
      fi
    done
  else
    jarvis_warn "venv ещё нет (.venv/bin/python) — это нормально до Install-Mac.command"
  fi

  if [ "$(uname -s)" = "Darwin" ]; then
    if jarvis_quarantine_clear "$JARVIS_ROOT"; then
      :
    else
      rc=1
    fi
  fi

  printf '\n'
  if [ "$rc" -eq 0 ]; then
    jarvis_ok "Итог: можно ставить (./Install-Mac.command)."
  else
    jarvis_err "Итог: есть проблемы (см. выше)."
  fi
  printf '\n'
  exit "$rc"
fi

# ===========================================================================
# Установка
# ===========================================================================
printf '\n  ================================================\n'
printf '    Ассистент  —  установка на macOS\n'
printf '  ================================================\n'
printf '  папка: %s\n' "$JARVIS_ROOT"
printf '\n'

# --- 1. Python -------------------------------------------------------------
step "Проверяю Python"
PY3=$(jarvis_pick_python3) || { jarvis_explain_python "$(command -v python3 2>/dev/null || true)"; exit 1; }
jarvis_ok "python3 $(jarvis_python_version "$PY3") — $PY3"
case "$PY3" in
  /usr/bin/python3*)
    jarvis_warn "взят /usr/bin/python3 (Xcode Command Line Tools)."
    jarvis_say "  Он работает, но обновляется вместе с Xcode. Надёжнее Homebrew: brew install python@3.12"
    ;;
esac

jarvis_check_writable "$JARVIS_ROOT" || exit 1
jarvis_check_disk || exit 1

# --- 2. .venv --------------------------------------------------------------
step "Создаю виртуальное окружение (.venv)"
if [ -x "$VENV_PY" ]; then
  jarvis_ok "уже есть: $VENV_PY ($(jarvis_python_version "$VENV_PY"))"
else
  # старый/битый .venv — venv не пересоздастся, а pip внутри будет падать
  if [ -d "$JARVIS_ROOT/.venv" ]; then
    jarvis_warn ".venv есть, но битый — пересоздаю"
    rm -rf "$JARVIS_ROOT/.venv"
  fi
  "$PY3" -m venv "$JARVIS_ROOT/.venv" \
    || fail "python -m venv не отработал." \
           "Обычно это значит, что не хватает ensurepip. Поставьте Python через" \
           "python.org (pkg-установщик) или brew install python@3.12 — и повторите."
  jarvis_ok "создан: $VENV_PY ($(jarvis_python_version "$VENV_PY"))"
fi
[ -x "$VENV_PY" ] || fail "После venv нет $VENV_PY — установка не удалась."

"$VENV_PY" -m pip install --upgrade pip -q --disable-pip-version-check \
  || jarvis_warn "не смог обновить сам pip — продолжаю (обычно не критично)"
jarvis_ok "pip $("$VENV_PY" -m pip --version 2>/dev/null | awk '{print $2}')"

# --- 3. зависимости -------------------------------------------------------
step "Ставлю библиотеки из $REQ (2–5 минут, ~300 МБ)"
if ! "$VENV_PY" -m pip install -r "$JARVIS_ROOT/$REQ" --disable-pip-version-check; then
  jarvis_err "pip не смог поставить зависимости."
  jarvis_say ""
  jarvis_say "  Что обычно бывает причиной:"
  jarvis_say "   · нет интернета или pypi.org недоступен (иногда нужен VPN) —"
  jarvis_say "     проверьте: $ curl -I https://pypi.org/simple/ ;"
  jarvis_say "   · Python слишком новый (3.15+) — поставьте рядом 3.12 и повторите:"
  jarvis_say "     rm -rf .venv && ./Install-Mac.command"
  jarvis_say "   · на Intel Mac и macOS 13 упал torch — этого быть не должно, в $REQ его нет;"
  jarvis_say "     если в сообщении упоминается torch, скажите: файл $REQ надо обновить."
  jarvis_say ""
  exit 1
fi
jarvis_ok "библиотеки стоят"

# Иконка в строке меню — отдельная необязательная вещь: если не встала,
# ядро работает, просто приложение откроет браузер (mac/host.py → run_headless).
if ! "$VENV_PY" -c "import pystray" >/dev/null 2>&1; then
  jarvis_warn "pystray/pillow не встали — иконки в строке меню не будет, сайт откроется в браузере"
  jarvis_warn "  починить позже: $VENV_PY -m pip install pystray pillow"
fi

# --- 4. настройки и проверка ---------------------------------------------
step "Создаю config.yaml и проверяю импорт"
if [ ! -f "$JARVIS_ROOT/config.yaml" ]; then
  if [ -f "$JARVIS_ROOT/config.example.yaml" ]; then
    cp "$JARVIS_ROOT/config.example.yaml" "$JARVIS_ROOT/config.yaml"
    jarvis_ok "создан config.yaml (заполнять руками не нужно — мастер на сайте)"
  else
    jarvis_warn "нет config.example.yaml — скопируйте его в config.yaml вручную"
  fi
else
  jarvis_ok "config.yaml уже есть — не трогаю (там ваши ключи)"
fi

for mod in fastapi uvicorn sqlmodel yaml; do
  "$VENV_PY" -c "import $mod" >/dev/null 2>&1 \
    || fail "Пакет $mod не импортируется после установки — окружение собрано не полностью."
done
jarvis_ok "ядро импортируется (fastapi, uvicorn, sqlmodel, yaml)"

printf '\n  ================================================\n'
printf '    Готово.\n'
printf '  ================================================\n'
printf '  Запуск:  ./start.command   (или соберите .app — Install-Mac.command)\n'
printf '  Сайт:    http://localhost:%s\n' "$(jarvis_port)"
printf '  Настройка имени, мозга и Telegram — в мастере, который откроется в браузере.\n'
printf '  Локальная модель (по желанию): https://ollama.com/download\n'
printf '  Логи:    data/core.log\n'
jarvis_no_sudo_note
printf '\n'