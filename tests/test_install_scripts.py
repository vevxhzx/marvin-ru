# -*- coding: utf-8 -*-
"""Статические проверки установки и запуска на macOS (Install-Mac.command и соседи).

Зачем этот файл: владельца Mac нет, поэтому скрипты установки нельзя проверить
руками. Всё, что можно поймать без живого Mac, ловится здесь — статикой, а
реальная установка дополнительно гоняется в CI на `macos-latest`
(.github/workflows/tests.yml, задание `macos`).

Проверки НЕ формальные: каждая ловит класс реальных поломок, из-за которых
установка на Mac ломалась или молча не работала:
  · .command в CRLF → bash: `$'\\r': command not found` (видим на Windows-редакторах);
  · забытый shebang / битый синтаксис → ловится `bash -n` (если bash есть в системе);
  · `/usr/bin/python3` с Xcode CLT (3.9) вместо нормального Python;
  · занятый порт 8765 без внятного сообщения;
  · `torch` в mac-зависимостях → падение на Intel Mac (нет macOS-колёс x86_64);
  · LaunchAgent без `data/` → launchd молча не стартует агент;
  · карантин Gatekeeper (`xattr -dr com.apple.quarantine`) не снимается;
  · `sudo` в скрипте установки.

Тесты ничего не выполняют на macOS и не трогают data/ — только читают файлы.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Что именно проверяем
# ---------------------------------------------------------------------------

# Скрипты macOS, которые эта задача auditing'ом приводит в порядок.
# install.command / voice.command / install_voice.command / build_web.command —
# наследие вне этого набора (см. LEGACY_STRICT); для них проверка строгого режима
# ослаблена намеренно, с явным списком, а не «на всё подряд».
MAC_SCRIPTS = (
    "Install-Mac.command",
    "start.command",
    "update.command",
    "autostart.command",
    "phone.command",
)
MAC_SHELL = ("mac/install.sh", "mac/preflight.sh", "mac/launcher.sh")

# mac/preflight.sh — библиотека, её `.` (source), а не исполняют. Строгий режим в ней
# запрещён намеренно: он влиял бы на подключающий скрипт (в start.command цикл
# автоперезапуска). Поэтому её проверяем отдельно.
MAC_SHELL_STRICT = ("mac/install.sh", "mac/launcher.sh")
PREFLIGHT = "mac/preflight.sh"

# Старые скрипты, которые ещё без `set -euo pipefail`. Список закрытый:
# тест ниже не даст ему молча разрастись.
LEGACY_STRICT = {
    "install.command",
    "voice.command",
    "install_voice.command",
    "build_web.command",
}

# Документы, где перечислены скриппы запуска. Если скрипт удалили или переименовали,
# а документация — нет, читатель получает инструкцию «двойной клик», которая не работает.
DOCS_WITH_SCRIPTS = ("README.md", "AGENTS.md", "ARCHITECTURE.md", "FEATURES.md")

_SCRIPT_REF = re.compile(r"[\\/]([\w.\-]+\.(?:command|bat))|([\w\-]+\.(?:command|bat))")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _command_files() -> list[Path]:
    return sorted(ROOT.glob("*.command"))


def _strip_noise(text: str) -> str:
    """Убирает комментарии и содержимое кавычек.

    Нужно, чтобы отличить «команду sudo» от «слова sudo в русском тексте»:
    sudo не должен вызываться, но упоминать его в подсказке можно и нужно.
    """
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        line = re.sub(r'"[^"]*"', '""', line)
        line = re.sub(r"'[^']*'", "''", line)
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 1. Документация не зовёт несуществующие скрипты
# ---------------------------------------------------------------------------

def test_documented_scripts_exist():
    missing: dict[str, list[str]] = {}
    docs: list[Path] = [ROOT / d for d in DOCS_WITH_SCRIPTS]
    docs += sorted((ROOT / "docs").glob("*.md"))
    docs += sorted((ROOT / "mac").glob("*.md"))
    for doc in docs:
        if not doc.exists():
            missing[str(doc.relative_to(ROOT))] = ["файл документации отсутствует"]
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        for m in _SCRIPT_REF.finditer(text):
            name = m.group(1) or m.group(2)
            # ссылки вида tools\fix_release_notes.bat живут в tools/
            if (ROOT / name).exists() or (ROOT / "tools" / name).exists():
                continue
            missing.setdefault(name, []).append(str(doc.relative_to(ROOT)))
    assert not missing, (
        "документация ссылается на несуществующие скрипты: "
        + "; ".join(f"{k} (в {', '.join(sorted(set(v)))})" for k, v in sorted(missing.items()))
    )


def test_documented_macos_entrypoint_exists():
    """README/docs должны где-то говорить про macOS, иначе инструкция только про Windows."""
    texts = []
    for rel in ("README.md", "docs/install.md", "mac/README.md"):
        p = ROOT / rel
        if p.exists():
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
    assert any("mac" in t.lower() and (".command" in t or "macos" in t.lower()) for t in texts)


# ---------------------------------------------------------------------------
# 2. Синтаксис и кодировка .command
# ---------------------------------------------------------------------------

def test_all_command_files_have_bash_shebang():
    """Без shebang двойной клик в Finder не знает, чем запускать файл."""
    files = _command_files() + [ROOT / p for p in MAC_SHELL]
    missing = [p.name for p in files
               if not p.read_text(encoding="utf-8", errors="replace").startswith("#!")]
    assert not missing, f"нет shebang: {missing}"


def test_command_files_are_unix_lf():
    """CRLF в .command — классика: bash спотыкается о `$'\\r': command not found`."""
    bad = []
    for p in _command_files() + [ROOT / q for q in MAC_SHELL]:
        raw = p.read_bytes()
        if b"\r\n" in raw:
            bad.append(p.name)
        if raw.startswith(b"\xef\xbb\xbf"):
            bad.append(p.name + " (BOM)")
    assert not bad, f"CRLF/BOM в shell-скриптах: {bad}"


def test_gitattributes_pin_shell_scripts_to_lf():
    """Если в репозитории есть .gitattributes — .command/.sh обязаны быть закреплены за LF.

    Ловушка: на Windows часто стоит core.autocrlf=true, и тогда `git add`
    переписывает скрипты в CRLF прямо в репозитории. На macOS такие файлы
    не запускаются (`$'\\r': command not found`).
    Рекомендуемое содержимое (см. docs/macos.md):
        *.command text eol=lf
        *.sh      text eol=lf
    Файла нет — проверять нечего; когда появится, тест начнёт требовать правила.
    """
    ga = ROOT / ".gitattributes"
    if not ga.exists():
        pytest.skip(".gitattributes нет — нечего проверять (риск описан в docs/macos.md)")
    text = ga.read_text(encoding="utf-8", errors="replace")
    for pattern in ("*.command", "*.sh"):
        lines = [ln for ln in text.splitlines() if pattern in ln]
        assert lines, f".gitattributes: нет правила для {pattern}"
        assert any("eol=lf" in ln or "-text" in ln for ln in lines), \
            f".gitattributes: {pattern} должен быть закреплён за LF (eol=lf), иначе CRLF на Windows"


def test_command_files_have_strict_mode():
    """`set -euo pipefail` — чтобы скрипт не падал молча и не работал с пустыми переменными."""
    for rel in MAC_SCRIPTS + MAC_SHELL_STRICT:
        text = _read(rel)
        assert re.search(r"^set -euo pipefail\s*$", text, re.M), f"{rel}: нет `set -euo pipefail`"


def test_preflight_is_a_library_not_a_script():
    """preflight подключают через `.` — он не должен включать `set -e` сам (это ломает цикл start)."""
    text = _read(PREFLIGHT)
    assert not re.search(r"^set\s+-[a-z]*e", text, re.M), \
        f"{PREFLIGHT} — библиотека: `set -e` из неё применится к вызывающему скрипту"
    # Библиотека подключается в общий шелл — она не должна заводить функции
    # и переменные без префикса, иначе пересечётся с вызывающим скриптом.
    defined = re.findall(r"^([A-Za-z_][\w]*)\s*\(\)", text, re.M)
    assert defined, f"{PREFLIGHT}: не нашлось ни одной функции"
    bad = [n for n in defined if not n.startswith(("jarvis_", "_jarvis_"))]
    assert not bad, f"{PREFLIGHT}: функции без префикса jarvis_ (пересекутся с вызывающим скриптом): {bad}"
    assigned = re.findall(r"^([A-Za-z_][\w]*)=(?!=)", text, re.M)
    bad_vars = [n for n in assigned if not n.startswith(("J_", "JARVIS_"))]
    assert not bad_vars, f"{PREFLIGHT}: переменные без префикса J_/JARVIS_: {bad_vars}"
    # и он действительно только подключается, а не запускается
    for rel in MAC_SCRIPTS + ("mac/install.sh",):
        assert re.search(r'^\.\s+"?\$\{?(HERE|ROOT)\}?/(mac/)?preflight\.sh"?', _read(rel), re.M), \
            f"{rel}: preflight должен подключаться через `.`, а не исполняться"


def test_legacy_strict_allowlist_does_not_grow():
    """Список старых скриптов без строгого режима — закрытый и не должен пополняться."""
    grown = set()
    for p in _command_files():
        if p.name in LEGACY_STRICT:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^set -euo pipefail\s*$", text, re.M):
            grown.add(p.name)
    assert not grown, (
        f"новые .command без `set -euo pipefail`: {sorted(grown)}. "
        f"Добавьте строгий режим (см. mac/preflight.sh) или осознанно внесите в LEGACY_STRICT."
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash не установлен в этой системе")
def test_command_files_pass_bash_syntax_check():
    """`bash -n` ловит синтаксис, который не поймает Python-тест (нет zsh/bash — пропуск)."""
    bash = shutil.which("bash")
    broken = []
    for rel in MAC_SCRIPTS + MAC_SHELL:
        proc = subprocess.run([bash, "-n", str(ROOT / rel)], capture_output=True, text=True)
        if proc.returncode != 0:
            broken.append(f"{rel}: {proc.stderr.strip()}")
    assert not broken, "bash -n не прошёл:\n" + "\n".join(broken)


# ---------------------------------------------------------------------------
# 3. В mac-скриптах нет виндовых путей и команд
# ---------------------------------------------------------------------------

def test_mac_scripts_have_no_windows_stuff():
    bad = []
    patterns = {
        "путь C:\\": r"[A-Za-z]:\\\\?",
        "переменная окружения %VAR%": r"%[A-Za-z_][A-Za-z_0-9]*%",
        "chcp/netsh/taskkill": r"(?<![\w/.-])(chcp|netsh|taskkill|ipconfig|where)\s+[A-Za-z0-9]",
        "путь пользователя Windows": r"(?i)AppData|System32|C:\\\\Users",
        "python.exe": r"\.venv[/\\]Scripts[/\\]python",
        "chdir-эквивалент": r"(?<![\w])(cd\s+/d\b)",
    }
    for rel in MAC_SCRIPTS + MAC_SHELL:
        text = _strip_noise(_read(rel))
        for label, rx in patterns.items():
            m = re.search(rx, text)
            if m:
                bad.append(f"{rel}: {label} → {m.group(0)!r}")
    assert not bad, "в mac-скриптах осталось виндовое:\n" + "\n".join(bad)


def test_mac_scripts_quote_cd_target():
    """`cd $ROOT` без кавычек ломается на папке с пробелом — на Mac такие есть («Мои документы»)."""
    bad = []
    for rel in MAC_SCRIPTS + MAC_SHELL:
        for line in _read(rel).splitlines():
            s = line.strip()
            if not s.startswith("cd "):
                continue
            target = s[3:].strip()
            if target.startswith(('"', "'", "(")) or target in (".", "-"):
                continue
            bad.append(f"{rel}: {s}")
    assert not bad, "cd без кавычек (ломается на путях с пробелами):\n" + "\n".join(bad)


def test_mac_scripts_never_call_sudo():
    """Установка в ~/Assistant и ~/.venv правами администратора не требует."""
    bad = []
    for rel in MAC_SCRIPTS + MAC_SHELL:
        text = _strip_noise(_read(rel))
        for m in re.finditer(r"(?:^|[;&|(]\s*|\bthen\s+|\bdo\s+)sudo\s+\w", text, re.M):
            bad.append(f"{rel}: {m.group(0).strip()}")
    assert not bad, "sudo в mac-скриптах (всё ставится в свою папку):\n" + "\n".join(bad)


# ---------------------------------------------------------------------------
# 4. Проверки окружения: Python, порт, ffmpeg, карантин
# ---------------------------------------------------------------------------

def test_mac_scripts_source_preflight():
    """Общие проверки живут в mac/preflight.sh — скрипты обязаны его подключать."""
    for rel in MAC_SCRIPTS + ("mac/install.sh",):
        assert "mac/preflight.sh" in _read(rel), f"{rel}: не подключает mac/preflight.sh"


def test_preflight_defines_needed_checks():
    text = _read("mac/preflight.sh")
    for fn in ("jarvis_python_version_ok", "jarvis_pick_python3", "jarvis_port",
               "jarvis_port_busy", "jarvis_port_report", "jarvis_check_ffmpeg",
               "jarvis_quarantine_clear", "jarvis_require_venv"):
        assert re.search(rf"^{fn}\(\)", text, re.M), f"в mac/preflight.sh нет {fn}()"


def test_preflight_python_min_version():
    """Ниже 3.10 setup.py всё равно откажется работать — проверяем то же самое."""
    text = _read("mac/preflight.sh")
    m = re.search(r'J_PY_MIN="(\d+)\.(\d+)"', text)
    assert m, "в mac/preflight.sh нет J_PY_MIN"
    assert (int(m.group(1)), int(m.group(2))) >= (3, 10), "J_PY_MIN ниже 3.10 — setup.py не согласится"
    assert 'sys.version_info' in text, "проверка версии Python должна опираться на sys.version_info"


def test_preflight_prefers_homebrew_over_xcode_clt_python():
    """`/usr/bin/python3` на Apple Silicon — это 3.9 из Command Line Tools."""
    text = _read("mac/preflight.sh")
    fn = re.search(r"^jarvis_pick_python3\(\).*?^}", text, re.M | re.S)
    assert fn, "нет jarvis_pick_python3()"
    body = fn.group(0)
    assert "/usr/bin/python3" in body, "список кандидатов должен доходить до /usr/bin/python3 как до последнего"
    assert body.rindex("/usr/bin/python3") > body.index("homebrew"), \
        "Homebrew-python должен проверяться раньше /usr/bin/python3 (Xcode CLT = 3.9)"
    assert re.search(r"Xcode Command Line Tools", text), "в preflight должно быть объяснение про CLT"


@pytest.mark.parametrize("rel", MAC_SCRIPTS)
def test_mac_script_checks_python_version(rel):
    """Каждый mac-скрипт либо сам спрашивает версию, либо зовёт обвязку preflight."""
    text = _read(rel)
    has_check = any(
        re.search(rx, text)
        for rx in (r"jarvis_python_version_ok", r"jarvis_require_venv", r"jarvis_pick_python3",
                   r"version_info")
    )
    assert has_check, f"{rel}: нет проверки версии Python"


@pytest.mark.parametrize("rel", MAC_SCRIPTS + ("mac/install.sh",))
def test_mac_script_checks_port(rel):
    """Занятый 8765 должен приводить к понятному сообщению, а не к падению ядра."""
    text = _read(rel)
    assert re.search(r"jarvis_port_(busy|report)\b", text), \
        f"{rel}: нет проверки занятости порта (jarvis_port_busy / jarvis_port_report)"
    assert re.search(r'\$\(\s*jarvis_port\s*\)', text), \
        f"{rel}: порт надо брать через jarvis_port (server.port из config.yaml), а не константой"


def test_preflight_port_comes_from_config():
    """run.py и jarvis_app.py берут порт из config.yaml — скрипты должны делать так же."""
    text = _read("mac/preflight.sh")
    fn = re.search(r"^jarvis_port\(\).*?^}", text, re.M | re.S)
    assert fn, "нет jarvis_port()"
    assert "config.yaml" in fn.group(0) and "server" in fn.group(0)


def test_install_mac_checks_ffmpeg():
    """ffmpeg на mac ставится через brew; скрипт должен сказать об этом, а не молчать."""
    text = _read("Install-Mac.command") + _read("mac/preflight.sh")
    assert "ffmpeg" in text
    assert "brew install ffmpeg" in text, "нет подсказки `brew install ffmpeg`"
    assert "jarvis_check_ffmpeg" in _read("Install-Mac.command")


def test_install_mac_clears_quarantine():
    """Скачанный ZIP помечен карантином: без xattr двойной клик не откроется."""
    text = _read("Install-Mac.command") + _read("mac/preflight.sh")
    assert "com.apple.quarantine" in text, "нет xattr -dr com.apple.quarantine"
    assert "Открыть" in text, "нет объяснения, что делать, если Gatekeeper всё равно ругается"


def test_install_mac_makes_scripts_executable():
    """ZIP из GitHub не сохраняет бит запуска — chmod обязан быть в скрипте."""
    assert re.search(r"chmod \+x", _read("Install-Mac.command"))


def test_install_mac_has_temp_cleanup_trap():
    """iconutil/sips пишут во временную папку — без trap она остаётся в data/ навсегда."""
    text = _read("Install-Mac.command")
    assert "trap" in text and "EXIT" in text, "нет trap на очистку временных файлов"
    assert re.search(r"mktemp -d", text), "временная папка должна создаваться через mktemp -d"


def test_install_mac_builds_app_and_verifies():
    """После сборки .app проверяем, что все обязательные файлы на месте."""
    text = _read("Install-Mac.command")
    for needle in ("Contents/MacOS/J.A.R.V.I.S.", "Contents/Info.plist",
                   "Contents/Resources/project_root"):
        assert needle in text, f"Install-Mac.command не собирает/не проверяет {needle}"
    assert re.search(r"project_root", text)
    assert "project_root" in _read("mac/launcher.sh"), "launcher.sh обязан читать project_root"


# ---------------------------------------------------------------------------
# 5. .venv и запуск
# ---------------------------------------------------------------------------

def test_venv_python_path_is_unix():
    """В venv на mac интерпретатор всегда .venv/bin/python (Scripts — только Windows)."""
    for rel in MAC_SCRIPTS + MAC_SHELL + ("mac/host.py",):
        text = _read(rel)
        assert not re.search(r"\.venv[/\\]+Scripts", text), f"{rel}: путь к python из Windows-venv"
    assert ".venv/bin/python" in _read("mac/install.sh")


def test_install_creates_venv_in_project_root():
    text = _read("mac/install.sh")
    assert re.search(r"-m\s+venv\s+\"?\$JARVIS_ROOT/\.venv|\-m venv \"?\$\{JARVIS_ROOT\}/\.venv", text) \
        or '"$JARVIS_ROOT/.venv"' in text, "venv должен создаваться внутри папки проекта"


def test_install_uses_mac_requirements():
    """Ядро на mac ставится из requirements-mac.txt, а не из requirements.txt (там torch)."""
    for rel in ("mac/install.sh", "start.command", "update.command"):
        text = _read(rel)
        assert "requirements-mac.txt" in text, f"{rel}: не использует requirements-mac.txt"
    assert not re.search(r'python3?\s+"?\$?\{?(ROOT|HERE|\$ROOT)?\}?[/ ]*setup\.py', _read("Install-Mac.command")), \
        "Install-Mac.command не должен звать setup.py: тот жёстко ставит requirements.txt с torch"


def test_start_command_restart_loop_survives_strict_mode():
    """`set -e` + голый `"$PY" run.py` убил бы автоперезапуск: нужен захват кода."""
    text = _read("start.command")
    assert re.search(r'"\$\{?PY\}?"?\s+run\.py.*\|\|', text), \
        "в start.command вызов run.py не guarded — set -e оборвёт цикл перезапуска"
    assert "while true" in text
    assert re.search(r'if\s+\[\s*"?\$\{?code\}?["\']?\s+-eq\s+3', text), \
        "нужна обработка кода 3 (порт занят)"


def test_start_command_handles_port_busy():
    text = _read("start.command")
    assert "jarvis_port_busy" in text, "start.command должен проверять занятость порта заранее"
    assert "start.command --stop" in text, "нужен понятный путь остановить уже запущенное ядро"


def test_autostart_creates_data_dir_before_plist():
    """Баг: launchd не стартует агент, если StandardOutPath ведёт в несуществующую data/."""
    text = _read("autostart.command")
    mkdir = text.index('mkdir -p "$ROOT/data"')
    plist = text.index("cat > \"$PLIST\"")
    assert mkdir < plist, "data/ должен создаваться ДО записи plist, иначе launchd молчит"


def test_autostart_escapes_xml_and_validates():
    """Папка проекта с «&» в имени ломает plist — launchd проглотит битый XML молча."""
    text = _read("autostart.command")
    assert "xml_escape" in text, "значения plist не экранируются"
    assert "plutil -lint" in text, "валидность plist не проверяется"
    assert "launchctl" in text
    assert "--remove" in text, "автозапуск нельзя снять одной командой"


def test_launcher_reports_errors_to_user():
    """mac/launcher.sh запускается без Терминала — молчаливый exit 1 это «ничего не работает»."""
    text = _read("mac/launcher.sh")
    assert "display alert" in text, "launcher.sh должен показывать osascript-алерт"
    assert re.search(r'/bin/bash\s+"\$ROOT/mac/install\.sh"', text), \
        "launcher должен ставить через mac/install.sh (requirements-mac), а не setup.py"


def test_host_py_uses_mac_installer():
    text = _read("mac/host.py")
    assert 'ROOT / "mac" / "install.sh"' in text, \
        "mac/host.py должен ставить через mac/install.sh, а не setup.py (requirements.txt с torch)"
    assert "PYTHONUNBUFFERED" in text or "PYTHONUNBUFFERED" in _read("mac/launcher.sh")


# ---------------------------------------------------------------------------
# 6. Режим --check (dry-run) для установки и запуска
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", MAC_SCRIPTS)
def test_mac_scripts_support_check_mode(rel):
    """--check нужен и для CI (ничего не ставить, только проверить), и для диагностики.

    Проверяем не только само слово, но и что оно разбирается как режим:
    в `case` должен быть переход в переменную режима, иначе --check
    молча ничего не сделает.
    """
    text = _read(rel)
    assert re.search(r"--check[^\n)]*\)\s*[A-Z_]+=", text), \
        f"{rel}: --check не разбирается как режим (нет перехода в case)"
    assert re.search(r'if \[ "\$\{?[A-Z_]+\}?" (?:-eq\s+1|=\s*"(?:check|status)")', text), \
        f"{rel}: нет ветки, обрабатывающей режим проверки"
    assert re.search(r"--dry-run", text), f"{rel}: нет синонима --dry-run (его зовут в CI и в инструкции)"


def test_ci_calls_check_modes():
    text = _read(".github/workflows/tests.yml")
    for rel in ("Install-Mac.command", "start.command", "update.command"):
        assert f"./{rel} --check" in text, f"CI не вызывает ./{rel} --check"


# ---------------------------------------------------------------------------
# 7. requirements-mac.txt
# ---------------------------------------------------------------------------

def _requirement_lines(rel: str) -> list[str]:
    out = []
    for raw in _read(rel).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        out.append(line)
    return out


def _pkg_name(line: str) -> str:
    name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].strip()
    return name.lower()


def test_requirements_mac_exists_and_marked():
    text = _read("requirements-mac.txt")
    assert "mac" in text.splitlines()[0].lower(), "первая строка должна объяснять, что файл для macOS"


def test_requirements_mac_has_no_windows_or_gpu_only_packages():
    """torch на macOS не ставится на Intel (нет колёс x86_64) — в базовый набор он не должен попадать."""
    forbidden = ("torch", "nvidia-", "pywin32", "pyinstaller", "pywebview",
                 "vosk", "sounddevice", "keyboard")
    offenders = []
    for line in _requirement_lines("requirements-mac.txt"):
        pkg = _pkg_name(line)
        if any(pkg == f or pkg.startswith(f + "-") or pkg.startswith(f + "_") for f in forbidden):
            offenders.append(line)
    assert not offenders, (
        f"в requirements-mac.txt есть пакеты без macOS-колёс или виндовые: {offenders}. "
        "Они должны быть в requirements-voice/silero/windows и ставиться отдельно."
    )
    text = _read("requirements-mac.txt")
    assert "-r requirements-windows" not in text
    assert "-r requirements-gpu" not in text


def test_requirements_mac_covers_everything_else():
    """Новый пакет в requirements.txt не должен молча пропасть на mac.

    Пакет должен быть либо настоящим требованием в requirements-mac.txt, либо
    помечен строкой-комментарием вида «# torch>=2.2 …» — то есть исключение
    должно быть явным, а не «упомянуто в абзаце где-то вверху».
    """
    mac_lines = [ln.strip() for ln in _read("requirements-mac.txt").splitlines()]
    mac_real = {_pkg_name(ln) for ln in mac_lines if ln and not ln.startswith("#") and not ln.startswith("-")}
    missing = []
    for line in _requirement_lines("requirements.txt"):
        pkg = _pkg_name(line)
        if pkg in mac_real:
            continue
        excluded = any(re.match(rf"^#\s*{re.escape(pkg)}(\b|[<>=!~\[])", ln) for ln in mac_lines)
        if not excluded:
            missing.append(pkg)
    assert not missing, (
        f"пакеты из requirements.txt не упомянуты в requirements-mac.txt: {missing}. "
        "Добавьте их в mac-набор или пометьте явной строкой-комментарием "
        "«# <пакет> …» с причиной, почему на mac он не ставится."
    )


def test_requirements_mac_has_tray_dependencies():
    """Значок в строке меню — pystray + Pillow; без них mac/host.py уходит в режим без иконки."""
    real = {_pkg_name(ln) for ln in _requirement_lines("requirements-mac.txt")}
    missing = [p for p in ("pystray", "pillow") if p not in real]
    assert not missing, (
        f"в requirements-mac.txt нет {missing} — без них не будет значка в строке меню "
        "(mac/host.py → run_headless, откроется просто браузер)"
    )


def test_requirements_dev_and_windows_untouched_by_mac_file():
    """mac-набор не должен подтягивать тестовые и виндовые аддоны."""
    text = _read("requirements-mac.txt")
    assert "pytest" not in text
    assert "requirements-dev" not in text


# ---------------------------------------------------------------------------
# 8. CI: задание для macOS должно существовать и не быть «зелёным всегда»
# ---------------------------------------------------------------------------

def _workflow() -> dict:
    import yaml
    return yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8"))


def _mac_job() -> dict | None:
    for name, job in (_workflow().get("jobs") or {}).items():
        if str((job or {}).get("runs-on", "")).startswith("macos"):
            return job
    return None


def test_ci_has_macos_job():
    job = _mac_job()
    assert job is not None, (
        "в .github/workflows/tests.yml нет задания на macos-*. "
        "Без него поломки Install-Mac.command не видны до прихода к владельцу на Mac."
    )
    steps = job.get("steps") or []
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert "mac/install.sh" in runs or "requirements-mac.txt" in runs, \
        "macOS-задание должно реально ставить mac-зависимости (requirements-mac.txt)"
    assert "pytest" in runs, "macOS-задание должно гонять тесты"
    assert "-n" in runs or "bash -n" in runs, "нужна проверка синтаксиса .command"


def test_ci_macos_job_can_fail():
    """Задание, которое не может упасть, не проверяет ничего."""
    job = _mac_job()
    assert job.get("continue-on-error") in (None, False), \
        "continue-on-error: true у macOS-задания — проверка не имеет смысла"
    for s in job.get("steps") or []:
        assert s.get("continue-on-error") in (None, False), \
            f"шаг {s.get('name')!r} помечен continue-on-error"
        cond = str(s.get("if", ""))
        assert not cond.startswith("${{ always()"), \
            f"шаг {s.get('name')!r} под `always()` — падение выше не будет видно"
    assert job.get("timeout-minutes"), "нужен timeout-minutes (раннер может зависнуть)"


def test_ci_installs_light_requirements_only():
    """Тяжёлое (голос/GPU) в mac-задании не ставим — иначе она станет дорогой и хрупкой."""
    job = _mac_job()
    runs = "\n".join(str(s.get("run", "")) for s in job.get("steps") or [])
    assert "requirements.txt" not in runs.replace("requirements-mac.txt", ""), \
        "macOS-задание ставит requirements.txt целиком — там torch, он не ставится на Intel Mac"
    assert "requirements-silero" not in runs
    assert "requirements-voice" not in runs
    assert "requirements-gpu" not in runs


def test_ci_mac_job_uses_temporary_db():
    """Тесты не должны трогать data/jarvis.db — проверяем, что это объявлено."""
    job = _mac_job()
    runs = "\n".join(str(s.get("run", "")) for s in job.get("steps") or [])
    assert "ASSISTANT_TEST=1" in runs, "нужен ASSISTANT_TEST=1 (tests/conftest.py) — тесты офлайн"


def test_workflows_use_minimal_permissions_and_no_secrets():
    wf = _workflow()
    assert (wf.get("permissions") or {}).get("contents") == "read", \
        "workflow должен оставаться с contents: read"
    raw = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "secrets." not in raw, "в workflow не должно быть обращений к секретам"


def test_windows_jobs_not_broken():
    """Существующее windows/ubuntu-задание должно остаться на месте."""
    jobs = _workflow().get("jobs") or {}
    assert "python" in jobs, "пропал основной pytest-job"
    assert "web" in jobs and "server" in jobs, "пропали web/server-задания"
    assert jobs["python"].get("runs-on") == "ubuntu-latest"
    runs = "\n".join(str(s.get("run", "")) for s in jobs["python"]["steps"])
    assert "python -m pytest tests -q" in runs, "основной job должен гонять полный набор"


# ---------------------------------------------------------------------------
# 9. Кросс-платформенность funnel_setup.py (Tailscale Funnel)
# ---------------------------------------------------------------------------

def test_funnel_setup_finds_tailscale_on_mac():
    text = _read("funnel_setup.py")
    assert "/Applications/Tailscale.app" in text, \
        "на macOS бинарник tailscale лежит внутри .app и не в PATH — его надо искать явно"
    assert r"C:\Program Files\Tailscale" in text, "windows-путь тоже должен остаться"
    assert "--check" in text, "нужен режим проверки без изменений (в т.ч. для CI)"
    assert "sys.platform == \"darwin\"" in text or "sys.platform == 'darwin'" in text


def test_funnel_setup_mentions_platform_script():
    """Сообщения не должны звать funnel.bat на Mac и наоборот."""
    text = _read("funnel_setup.py")
    assert "SCRIPT_HINT" in text and "START_HINT" in text, \
        "подсказки про скрипт должны зависеть от платформы"


# ---------------------------------------------------------------------------
# 10. Документация про macOS
# ---------------------------------------------------------------------------

def test_docs_macos_install_section():
    p = ROOT / "docs" / "macos.md"
    assert p.exists(), "нет docs/macos.md — человеку без Mac негде прочитать порядок шагов"
    text = p.read_text(encoding="utf-8")
    for needle, why in (
        ("Install-Mac.command", "главный шаг установки"),
        ("start.command", "запуск"),
        ("3.10", "минимальная версия Python"),
        ("brew install ffmpeg", "как поставить ffmpeg"),
        ("8765", "порт, который занят чаще всего"),
        ("com.apple.quarantine", "типичная блокировка Gatekeeper"),
        ("sudo", "что делать, если что-то просит права администратора"),
    ):
        assert needle in text, f"docs/macos.md не упоминает {needle} ({why})"


def test_docs_install_links_macos():
    """docs/install.md — основная инструкция; в ней должна быть ссылка на macOS-раздел."""
    text = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
    assert "macos.md" in text, "docs/install.md должен ссылаться на docs/macos.md"