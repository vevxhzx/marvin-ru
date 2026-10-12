# -*- coding: utf-8 -*-
"""CI-guard от мусора в репозитории: в git не должны попадать кэши, логи,
пробы и локальные артефакты (история: bench_tts.py и voice_cache с чужим звуком).
Без git в PATH — скип, не провал."""
import shutil
import subprocess
from pathlib import Path

import pytest

import re

ROOT = Path(__file__).resolve().parent.parent

# пути, которым не место в репозитории (подстроки/суффиксы имён из git ls-files)
JUNK_PARTS = (
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "node_modules", ".venv/", "/venv/",
)
JUNK_SUFFIX = (
    ".pyc", ".pyo", ".log", ".part", ".tmp", ".swp",
)


def _tracked() -> list[str] | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        out = subprocess.run([git, "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.splitlines()


def test_no_junk_tracked():
    files = _tracked()
    if files is None:
        pytest.skip("нет git — проверять нечего")
    bad = [f for f in files
           if any(p in f for p in JUNK_PARTS) or f.endswith(JUNK_SUFFIX)]
    assert not bad, f"мусор в git (удалить + проверить .gitignore): {bad[:10]}"


def test_voice_probe_files_not_committed():
    """Одноразовые замеры (`bench_*.py`, `*_raw.txt` в корне) — не коммитим."""
    files = _tracked()
    if files is None:
        pytest.skip("нет git — проверять нечего")
    bad = [f for f in files if "/" not in f and (f.startswith("bench_") or f.endswith("_raw.txt"))]
    assert not bad, f"пробы в корне репозитория: {bad}"


def test_gitignore_covers_junk():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pat in ("__pycache__", "*.pyc", "*.log", "node_modules", ".venv/", "data/"):
        assert pat in gi, f".gitignore без {pat} — мусор вернётся"


# вызовы, пишущие в БД: тест без fresh_db/_client (и без своей autouse-фикстуры)
# ходит в боевую data/jarvis.db. История: _mk без изоляции + main_account="Кубышка"
# в конфиге роняли чужие прогоны дубликатом и правили боевой баланс.
_WRITES = (
    "agent.handle(", "add_transaction(", "add_order(", "add_task(", "add_event(",
    "add_debt(", "pay_debt(", "add_account(", "set_balance(", "update_task(",
    "update_event(", "update_transaction(", "update_debt(", "update_account(",
    "delete_task(", "delete_event(", "delete_transaction(", "delete_debt(",
    "complete_task(", "undo.undo_", "undo_last(", "add_note(",
    "add_fact", "add_payment(", "postpone_to_tomorrow(", "link_debt_account(",
    "unlink_debt_account(", "calendar.add_", "tasks.add_", "brain_notes.add_",
    "move_event(", "add_recurring(", "add_goal(", "save_to_goal(",
)


def _has_own_autouse_db(src: str) -> bool:
    """Своя autouse-фикстура с временной БД (как _db в test_boards.py)."""
    for m in re.finditer(r"@pytest\.fixture\(autouse=True\)\s*\ndef \w+\([^)]*\)\s*:", src):
        body = src[m.end():]
        body = body[: len(body) if "\ndef " not in body else body.index("\ndef ")]
        if "tmp_path" in body and ("engine" in body or "monkeypatch" in body):
            return True
    return False


def _imports_isolation(src: str) -> bool:
    """Трюк команды: `from tests.test_core import fresh_db` — pytest подхватывает
    импортированную autouse-фикстуру, и весь файл идёт на временной БД."""
    return bool(re.search(r"from tests\.\w+ import .*fresh_db", src))


def _has_file_isolation(src: str) -> bool:
    """Файл целиком на временной БД: свой autouse, импорт fresh_db
    или pytestmark usefixtures."""
    if _has_own_autouse_db(src) or _imports_isolation(src):
        return True
    return bool(re.search(r"pytestmark\s*=\s*pytest\.mark\.usefixtures\((\"|')[^\"']*(fresh_db|_client)", src))


def test_db_writes_are_isolated():
    """Каждый тест, пишущий в БД, обязан брать fresh_db/_client (или свой autouse)."""
    bad: list[str] = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        if path.name.startswith("test_zz_"):
            continue
        src = path.read_text(encoding="utf-8")
        if _has_file_isolation(src):
            continue
        for m in re.finditer(r"def (test_\w+)\(([^)]*)\)\s*:", src):
            name, args = m.group(1), m.group(2)
            if "fresh_db" in args or "_client" in args or "tmp_path" in args:
                continue
            body = src[m.end():]
            body = body[: len(body) if "\ndef test_" not in body else body.index("\ndef test_")]
            if any(w in body for w in _WRITES):
                bad.append(f"{path.name}::{name}")
    assert not bad, f"тесты пишут в боевую БД без изоляции: {bad[:15]}"
