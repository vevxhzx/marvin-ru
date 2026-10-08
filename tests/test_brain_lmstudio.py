# -*- coding: utf-8 -*-
"""LM Studio — второй локальный движок (OpenAI-совместимый API).

Одновременно с Ollama: малая модель и эмбеддинги остаются там, а сюда отдаётся
выбранное в brain.lmstudio.use (main — основные ответы, small — мини-задачи).
Живого LM Studio в тестах нет — клиент подменён заглушкой.
"""
from __future__ import annotations

import asyncio

import pytest


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    """Заглушка httpx.AsyncClient: пишет, куда стучались, отвечает чем сказали."""

    def __init__(self, seen, openai_text="Готово.", ollama_text="ОТВЕТ ОЛЛАМЫ", fail_openai=False):
        self._seen = seen
        self._openai_text = openai_text
        self._ollama_text = ollama_text
        self._fail = fail_openai

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        self._seen.append(("GET", url))
        return _Resp({"data": [{"id": "google/gemma-4-e4b"}]})

    async def post(self, url, json=None, **kw):
        self._seen.append(("POST", url, json))
        if url.endswith("/chat/completions"):
            if self._fail:
                raise ConnectionError("LM Studio молчит")
            return _Resp({"choices": [{"message": {"content": self._openai_text}}]})
        return _Resp({"message": {"content": self._ollama_text}})


def _lm_on(monkeypatch, use="main", client=None, seen=None):
    """Включить LM Studio в тестах: роль + подменённые доступность и клиент."""
    from core.brain import llm

    seen = seen if seen is not None else []
    if client is None:
        client = _FakeClient(seen)
    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    monkeypatch.setattr(llm, "LMSTUDIO_BASE", "http://127.0.0.1:1234/v1")
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "google/gemma-4-e4b")
    monkeypatch.setattr(llm, "LMSTUDIO_USE", use)
    monkeypatch.setattr(llm, "lmstudio_available", lambda force=False: asyncio.sleep(0, result=True))
    monkeypatch.setattr(llm, "_local_client", lambda timeout: client)
    return llm, seen


def test_keys_visible_in_settings():
    """Ключи видны в настройках с правильными типами."""
    from core.config import EDITABLE

    assert EDITABLE["brain.lmstudio.enabled"][0] == "bool"
    assert EDITABLE["brain.lmstudio.base_url"][0] == "str"
    assert EDITABLE["brain.lmstudio.model"][0] == "str"
    assert EDITABLE["brain.lmstudio.use"][0] == "str"


def test_disabled_by_default_nothing_changes(monkeypatch):
    """Выключен по умолчанию: маршрутизация молчит, поведение прежнее."""
    from core.brain import llm

    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", False)
    assert llm.lmstudio_role() == ""


@pytest.mark.parametrize("junk", ["главное", "", None, "MAIN "])
def test_junk_use_means_main_or_off(monkeypatch, junk):
    """Мусор в use: main по модулю, роль считается только при включённом движке."""
    from core.brain import llm

    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    monkeypatch.setattr(llm, "LMSTUDIO_USE", junk)
    # нормализация живёт в reload_lmstudio_settings; сырое значение мимо main/small — не роль
    assert llm.lmstudio_role() == (junk if junk in ("main", "small") else "")


def test_main_answers_go_to_lmstudio(monkeypatch):
    """use=main: основной ответ — в LM Studio OpenAI-форматом, Ollama не трогаем."""
    llm, seen = _lm_on(monkeypatch, use="main")
    out = asyncio.run(llm.ollama_chat([{"role": "user", "content": "привет"}]))
    assert out["content"] == "Готово." and out["tool_calls"] == []
    posts = [s for s in seen if s[0] == "POST"]
    assert len(posts) == 1 and posts[0][1].endswith("/chat/completions")
    body = posts[0][2]
    assert body["model"] == "google/gemma-4-e4b" and body["messages"][0]["content"] == "привет"


def test_tools_stay_on_ollama(monkeypatch):
    """Вызовы функций — только через Ollama: LM Studio их не получает."""
    llm, seen = _lm_on(monkeypatch, use="main")
    out = asyncio.run(llm.ollama_chat(
        [{"role": "user", "content": "потрать"}],
        tools=[{"type": "function", "function": {"name": "add_expense"}}]))
    assert out["content"] == "ОТВЕТ ОЛЛАМЫ"
    urls = [s[1] for s in seen if s[0] == "POST"]
    assert urls and all(u.endswith("/api/chat") for u in urls)


def test_lmstudio_failure_falls_back_to_ollama(monkeypatch):
    """LM Studio молчит — основной ответ идёт в Ollama, а не в ошибку."""
    from core.brain import llm

    seen: list = []
    llm, seen = _lm_on(monkeypatch, use="main", client=_FakeClient(seen, fail_openai=True), seen=seen)
    out = asyncio.run(llm.ollama_chat([{"role": "user", "content": "привет"}]))
    assert out["content"] == "ОТВЕТ ОЛЛАМЫ"


def test_mini_tasks_go_to_lmstudio(monkeypatch):
    """use=small: мини-задача — в LM Studio, малая модель Ollama не трогается."""
    llm, seen = _lm_on(monkeypatch, use="small")
    out = asyncio.run(llm.small_chat("система", "пользователь"))
    assert out == "Готово."
    posts = [s for s in seen if s[0] == "POST"]
    assert len(posts) == 1 and posts[0][1].endswith("/chat/completions")
    assert posts[0][2]["messages"] == [{"role": "system", "content": "система"},
                                       {"role": "user", "content": "пользователь"}]


def test_main_role_keeps_mini_tasks_on_ollama(monkeypatch):
    """use=main: мини-задача без малой модели идёт через основной путь — а он и есть LM Studio."""
    from core.brain import llm

    seen: list = []
    _lm_on(monkeypatch, use="main", seen=seen)
    monkeypatch.setattr(llm, "small_model_active", lambda: False)
    out = asyncio.run(llm.small_chat("система", "пользователь"))
    assert out == "Готово."
    urls = [s[1] for s in seen if s[0] == "POST"]
    assert urls and all(u.endswith("/chat/completions") for u in urls)


@pytest.mark.parametrize("raw, want", [
    ("http://127.0.0.1:1234", "http://127.0.0.1:1234/v1"),       # голый хост — /v1 дописывается сам
    ("http://127.0.0.1:1234/", "http://127.0.0.1:1234/v1"),
    ("http://127.0.0.1:1234/v1", "http://127.0.0.1:1234/v1"),   # хвост уже есть — не дублируем
    ("http://127.0.0.1:1234/v1/", "http://127.0.0.1:1234/v1"),
    ("", "http://127.0.0.1:1234/v1"),                            # пусто — адрес по умолчанию
    ("http://10.0.0.5:8080/openai", "http://10.0.0.5:8080/openai"),  # чужой путь не трогаем
])
def test_base_url_normalized(raw, want):
    """Адрес без /v1 чинится сам — LM Studio понимает только /v1/models и /v1/chat/completions."""
    from core.brain import llm

    assert llm._norm_lms_base(raw) == want
