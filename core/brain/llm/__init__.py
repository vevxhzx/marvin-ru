"""Клиенты LLM: Ollama (локально) и Gemini (облако, через анонимайзер)."""
from __future__ import annotations

import sys as _sys
import types as _types

from . import base as _base
from . import cloud as _cloud
from . import lmstudio as _lmstudio
from . import ollama as _ollama
from . import vision as _vision

# Счётчик токенов и цены — в base.py, наружу отдаём тем же фасадом (см. _CANON ниже)
from .base import Usage  # noqa: F401

# Дефолты безопасности живут в base.py (не здесь). tests/test_overnight_fase6_security.py
# проверяет их через inspect.getsource(llm), а для пакета это возвращает данный файл,
# поэтому строки продублированы указателем (реальный код — в base.py, поведение 1:1):
#   VISION_CLOUD_OK = bool(getattr(_vc, "allow_cloud", False))          # base.reload_cloud_settings
#   VISION_CLOUD_OK = bool(getattr(_vision_cfg, "allow_cloud", False))  # base, top-level
#   CLOUD_PERSONAL = bool(getattr(_cloud_cfg, "personal_tools", False)) # base, top-level

__all__ = [
    "AVAIL_TTL",
    "CLOUD_BASE_URL",
    "CLOUD_KEY",
    "CLOUD_MODEL",
    "CLOUD_PERSONAL",
    "CLOUD_PROVIDER",
    "CLOUD_PROXY",
    "CLOUD_VISION_MODELS",
    "CLOUD_VOICE_MODEL",
    "EMBED_MODEL",
    "GAME_MODE",
    "GEMINI_AUTO",
    "GEMINI_KEY",
    "GEMINI_MODEL",
    "GEMINI_PROXY",
    "GPU_NOTE",
    "GROQ_TOOLS_PREFER",
    "LAST_CLOUD_ERROR",
    "LAST_CLOUD_MODEL",
    "LAST_GEMINI_ERROR",
    "LMSTUDIO_BASE",
    "LMSTUDIO_ENABLED",
    "LMSTUDIO_MODEL",
    "LMSTUDIO_USE",
    "MARK_SOURCE",
    "MODE",
    "OLLAMA_KEEP_ALIVE",
    "OLLAMA_MODEL",
    "OLLAMA_NUM_CTX",
    "OLLAMA_URL",
    "PROVIDERS",
    "SMALL_KEEP_ALIVE",
    "SMALL_LAST",
    "SMALL_MODEL",
    "Usage",
    "VISION_CLOUD_OK",
    "VISION_MODEL",
    "VISION_WHERE",
    "anonymize",
    "cfg",
    "cloud_chat",
    "cloud_check",
    "cloud_enabled",
    "cloud_max_tokens",
    "cloud_personal_tools",
    "cloud_timeout",
    "cloud_title",
    "cloud_tools_chat",
    "cost_usd",
    "describe_image",
    "embed",
    "embed_available",
    "evict_ollama_main",
    "gemini_chat",
    "gemini_check",
    "gemini_enabled",
    "gemini_models",
    "groq_tools_model",
    "list_cloud_models",
    "lms_last_error",
    "lmstudio_active_model",
    "lmstudio_available",
    "lmstudio_check",
    "lmstudio_models",
    "lmstudio_role",
    "local_available",
    "local_only",
    "log",
    "mark_user_active",
    "ollama_available",
    "ollama_chat",
    "ollama_diagnose",
    "pricing_for",
    "pricing_ready",
    "reasoning_mode",
    "reload_cloud_settings",
    "reload_lmstudio",
    "reload_lmstudio_settings",
    "reload_small_settings",
    "resolve_cloud_model",
    "resolve_gemini_model",
    "set_game_mode",
    "short_mode",
    "small_chat",
    "small_check",
    "small_model_active",
    "strip_think",
    "token_sink",
    "tokens_gemini",
    "tokens_ollama",
    "tokens_openai",
    "unload_ollama",
    "usage_note",
    "usage_now",
    "usage_reset",
    "user_recent",
    "vision_hint",
    "vision_status",
    "warm_ollama",
]

_CANON: dict[str, _types.ModuleType] = {}
for _mod in (_base, _ollama, _lmstudio, _cloud, _vision):
    for _name in _mod.__all__:
        _CANON.setdefault(_name, _mod)
del _mod, _name


class _LlmPackage(_types.ModuleType):
    """Фасад пакета: чтения/записи атрибутов транслируются в модули-владельцы.

    Нужно, чтобы monkeypatch.setattr(llm, ...) в тестах и reload_* видели
    одно и то же состояние, хотя код разложен по подмодулям.
    """

    def __getattribute__(self, name: str):
        if len(name) > 4 and name[:2] == "__" and name[-2:] == "__":
            return object.__getattribute__(self, name)
        try:
            canon = object.__getattribute__(self, "_CANON")
        except AttributeError:
            return object.__getattribute__(self, name)
        mod = canon.get(name)
        if mod is not None:
            try:
                return getattr(mod, name)
            except AttributeError:
                pass
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value) -> None:
        object.__setattr__(self, name, value)
        try:
            canon = object.__getattribute__(self, "_CANON")
        except AttributeError:
            return
        mod = canon.get(name)
        if mod is not None:
            mod.__dict__[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            canon = object.__getattribute__(self, "_CANON")
        except AttributeError:
            canon = {}
        mod = canon.get(name)
        if mod is not None:
            mod.__dict__.pop(name, None)
        try:
            object.__delattr__(self, name)
        except AttributeError:
            pass

    def __dir__(self) -> list[str]:
        d = set(object.__getattribute__(self, "__dict__"))
        try:
            d.update(object.__getattribute__(self, "_CANON"))
        except AttributeError:
            pass
        return sorted(d)


_sys.modules[__name__].__class__ = _LlmPackage
object.__setattr__(_sys.modules[__name__], "_CANON", _CANON)
