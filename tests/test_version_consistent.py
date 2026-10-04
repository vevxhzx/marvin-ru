"""CI-guard: core VERSION == package.json version == CHANGELOG head version.

web/package.json is intentionally excluded: it is 0.2.0, a different
generation counter for the frontend bundle, not the product release.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _changelog_head_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r"\s*##\s+(.+)", line)
        if not m:
            continue
        head = m.group(1).strip()
        if head.lower().startswith("unreleased"):
            continue  # skip "Unreleased" section, look at first real release
        m2 = re.match(r"(\d+\.\d+\.\d+)", head)
        assert m2, f"CHANGELOG head section has no X.Y.Z version: {line!r}"
        return m2.group(1)
    raise AssertionError("CHANGELOG.md has no '## X.Y.Z' section")


def test_version_consistent():
    from core import VERSION

    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    pkg_ver = pkg["version"]
    log_ver = _changelog_head_version()

    assert str(VERSION) == str(pkg_ver), (
        f"core.VERSION={VERSION!r} != package.json={pkg_ver!r}"
    )
    assert str(VERSION) == log_ver, (
        f"core.VERSION={VERSION!r} != CHANGELOG head={log_ver!r}"
    )
