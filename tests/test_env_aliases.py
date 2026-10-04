# -*- coding: utf-8 -*-
"""Алиасы env-имён: ASSISTANT_* предпочтительно, JARVIS_* устарели, но работают.

ASSISTANT_* всегда побеждает JARVIS_*; использование только JARVIS_* работает
и пишет предупреждение (core/config.py: _warn_jarvis_deprecated, один раз за процесс).
"""
from __future__ import annotations

import logging
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

DUAL = (
    "ASSISTANT_TG_TOKEN",
    "JARVIS_TG_TOKEN",
    "ASSISTANT_TG_OWNER",
    "JARVIS_TG_OWNER",
    "ASSISTANT_API_TOKEN",
    "JARVIS_API_TOKEN",
)


def _reload_config(monkeypatch, env: dict[str, str]):
    from core import config as cfgmod

    cfgmod._WARNED_JARVIS.clear()
    for k in DUAL:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cfgmod.refresh()  # in-place: объект cfg тот же, держатели `from config import cfg` не сиротеют
    return cfgmod


def test_assistant_wins_over_jarvis(monkeypatch):
    mod = _reload_config(
        monkeypatch,
        {"ASSISTANT_TG_TOKEN": "A-123", "JARVIS_TG_TOKEN": "J-456"},
    )
    assert mod.cfg.telegram.token == "A-123"


def test_jarvis_only_works_and_warns(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="jarvis.config"):
        mod = _reload_config(monkeypatch, {"JARVIS_TG_TOKEN": "J-only"})
    assert mod.cfg.telegram.token == "J-only"
    assert any(
        "JARVIS_*" in r.message and "ASSISTANT_*" in r.message for r in caplog.records
    ), f"нет deprecation-предупреждения: {[r.message for r in caplog.records]}"
