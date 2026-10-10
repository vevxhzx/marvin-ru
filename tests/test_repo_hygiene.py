# -*- coding: utf-8 -*-
"""CI-guard от мусора в репозитории: в git не должны попадать кэши, логи,
пробы и локальные артефакты (история: bench_tts.py и voice_cache с чужим звуком).
Без git в PATH — скип, не провал."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# пути, которым не место вoura репозитории (подстроки/суффиксы имён из git ls-files)
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
