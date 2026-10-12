"""Память о хозяине: что запоминать, что подтягивать в ответ, что забывать.

Слои (см. db.Fact):
  short   — контекст последних дней («болит спина», «делаю ролик для Пятёрочки»);
  long    — устойчивое («кот Барсик», «мама живёт в Туле», «не любит созвоны утром»);
  archive — устарело / забыто по просьбе / не пригодилось. Не удаляется — просто не попадает в контекст.
Разговор — ChatMessage (рабочая память), эпизоды — Memory, знания — Note/Link/Relation.

Три процесса:
  extract()  — после ответа, в фоне: нейронка смотрит на реплику хозяина и известные по теме факты → add / update / nothing.
  context()  — перед LLM-ответом: ядро портрета + факты, близкие по смыслу к реплике (эмбеддинги, только ПК).
  nightly()  — уборка: short старше N дней → long или archive; дубли схлопываются; портрет пересобирается раз в неделю.
Секреты (пароли, PIN, коды) не запоминаются никогда: фильтр до нейронки и проверка после.
"""
from __future__ import annotations

import sys as _sys
import types as _types


from . import extract as _mod_extract
from . import nightly as _mod_nightly
from . import portrait as _mod_portrait
from . import recall as _mod_recall
from . import store as _mod_store
from .extract import _ask, _cloud_sees_stored, _parse, _suggest_task, extract, worth_extracting
from .nightly import nightly, review_importance
from .portrait import rebuild_portrait, rebuild_style, style_line
from .recall import (
    _SUGGEST, _USED_IDS, clear_suggest, clear_used_ids, context,
    context_with_ids, peek_used_ids, pop_suggest, pop_used_ids,
    recall, set_suggest, set_used_ids,
)
from .store import (
    CATEGORIES, COMMAND_RX, CORE_MAX, CTX_MAX, CTX_MIN_SCORE, DEDUP_SCORE,
    DECAY_PENALTY, DISMISSED_KEY, EXTRACT_PROMPT, FADE_SUMMARY,
    IMPORTANCE_PROMPT, PORTRAIT_AT_KEY, PORTRAIT_KEY, PORTRAIT_PROMPT,
    PROMOTE_PROMPT, SECRET_RX, STYLE_AT_KEY, STYLE_KEY, STYLE_LINE_MAX,
    STYLE_PROMPT, UNUSED_DAYS, _cos, _dedupe, _dismissed, _dt,
    _embed, _extract_due, _faded, _meta_columns, _norm, _num, _remember_dismiss,
    _vec, about_me_text, add_fact, add_fact_sync, confirm, confirm_fact,
    decay, decay_days, decay_half_life, decay_max_mentions, dismiss,
    enabled, fact_meta, fact_source, find_fact, forget, get_fact_by_source_ref, index_pending,
    list_facts, log, restore, set_fact_meta, short_days, stats,
    suggest_enabled, suggest_timeout, update_fact, where,
)

__all__ = [
    "CATEGORIES", "COMMAND_RX", "CORE_MAX", "CTX_MAX", "CTX_MIN_SCORE",
    "DEDUP_SCORE", "DECAY_PENALTY", "DISMISSED_KEY", "EXTRACT_PROMPT",
    "FADE_SUMMARY", "IMPORTANCE_PROMPT", "PORTRAIT_AT_KEY", "PORTRAIT_KEY",
    "PORTRAIT_PROMPT", "PROMOTE_PROMPT", "SECRET_RX", "STYLE_AT_KEY",
    "STYLE_KEY", "STYLE_LINE_MAX", "STYLE_PROMPT", "UNUSED_DAYS",
    "_META_COLS", "_SUGGEST", "_USED_IDS",
    "_ask", "_cloud_sees_stored", "_cos", "_dedupe", "_dismissed", "_dt",
    "_embed", "_extract_due", "_faded", "_meta_columns", "_norm", "_num",
    "_parse", "_remember_dismiss", "_suggest_task", "_vec",
    "about_me_text", "add_fact", "add_fact_sync", "clear_suggest",
    "clear_used_ids", "confirm", "confirm_fact", "context", "context_with_ids",
    "decay", "decay_days", "decay_half_life", "decay_max_mentions", "dismiss",
    "enabled", "extract", "fact_meta", "fact_source", "find_fact", "forget",
    "get_fact_by_source_ref", "index_pending", "list_facts", "log", "nightly", "peek_used_ids",
    "pop_suggest", "pop_used_ids", "rebuild_portrait", "rebuild_style",
    "recall", "restore", "review_importance", "set_fact_meta",
    "set_suggest", "set_used_ids", "short_days", "stats", "style_line",
    "suggest_enabled", "suggest_timeout", "update_fact", "where",
    "worth_extracting",
]


class _MemoryPackage(_types.ModuleType):
    """Фасад пакета: setattr/delattr пробрасываются в подмодули.

    Тесты и агент патчат атрибуты пакета (monkeypatch.setattr(memory, "enabled", ...)),
    а внутренние вызовы идут через globals подмодулей — без проброса патч бы не увидели.
    """

    def __setattr__(self, name: str, value) -> None:
        _types.ModuleType.__setattr__(self, name, value)
        if name.startswith("__") and name.endswith("__"):
            return
        for _mod in (_mod_store, _mod_recall, _mod_extract, _mod_portrait, _mod_nightly):
            if name in _mod.__dict__:
                try:
                    setattr(_mod, name, value)
                except Exception:
                    pass

    def __delattr__(self, name: str) -> None:
        _types.ModuleType.__delattr__(self, name)
        for _mod in (_mod_store, _mod_recall, _mod_extract, _mod_portrait, _mod_nightly):
            if name in _mod.__dict__:
                try:
                    delattr(_mod, name)
                except Exception:
                    pass

    def __getattr__(self, name: str):
        if name == "_META_COLS":
            return _mod_store._META_COLS
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __dir__(self):
        return sorted(set(_types.ModuleType.__dir__(self)) | {"_META_COLS"})


_sys.modules[__name__].__class__ = _MemoryPackage
