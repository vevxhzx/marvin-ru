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

    def __init__(self, seen, openai_text="Готово.", ollama_text="ОТВЕТ ОЛЛАМЫ", fail_openai=False,
                 models=None):
        self._seen = seen
        self._openai_text = openai_text
        self._ollama_text = ollama_text
        self._fail = fail_openai
        self._models = [{"id": m} for m in (models if models is not None else ["google/gemma-4-e4b"])]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        self._seen.append(("GET", url))
        return _Resp({"data": self._models})

    async def post(self, url, json=None, **kw):
        self._seen.append(("POST", url, json))
        if url.endswith("/chat/completions"):
            if self._fail:
                raise ConnectionError("LM Studio молчит")
            if (json or {}).get("tools"):
                return _Resp({"choices": [{"message": {"content": "", "tool_calls": [
                    {"id": "call_0", "type": "function",
                     "function": {"name": "agenda", "arguments": '{"days": 1}'}}]}}]})
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
    monkeypatch.setattr(llm, "_LMS_MODELS_CACHE", (0.0, []))
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
    assert body.get("reasoning_effort") == "none"   # думы выключены: иначе ответ уходит в reasoning_content


def test_tools_go_to_lmstudio_with_mapping(monkeypatch):
    """use=main: вызовы функций — в LM Studio OpenAI-форматом, ответ маппится обратно."""
    llm, seen = _lm_on(monkeypatch, use="main")
    out = asyncio.run(llm.ollama_chat(
        [{"role": "user", "content": "потрать"}],
        tools=[{"type": "function", "function": {"name": "add_expense"}}]))
    assert out["tool_calls"] == [{"name": "agenda", "arguments": {"days": 1}}]
    posts = [s for s in seen if s[0] == "POST"]
    assert len(posts) == 1 and posts[0][1].endswith("/chat/completions")
    body = posts[0][2]
    assert body["tool_choice"] == "auto" and body["tools"][0]["function"]["name"] == "add_expense"


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


def test_uses_loaded_model_when_configured_missing(monkeypatch):
    """Название сверять не нужно: отвечает уже загруженная модель."""
    from core.brain import llm

    seen: list = []
    _lm_on(monkeypatch, use="main", client=_FakeClient(seen, models=["qwen/qwen3.5-9b"]), seen=seen)
    out = asyncio.run(llm.ollama_chat([{"role": "user", "content": "привет"}]))
    assert out["content"] == "Готово."
    body = [s for s in seen if s[0] == "POST"][0][2]
    assert body["model"] == "qwen/qwen3.5-9b"


def test_tools_fallback_to_ollama_on_failure(monkeypatch):
    """LM Studio упал посреди инструментов — зовём Ollama, а не ошибку."""
    from core.brain import llm

    seen: list = []
    llm, seen = _lm_on(monkeypatch, use="main", client=_FakeClient(seen, fail_openai=True), seen=seen)
    out = asyncio.run(llm.ollama_chat(
        [{"role": "user", "content": "потрать"}],
        tools=[{"type": "function", "function": {"name": "add_expense"}}]))
    assert out["content"] == "ОТВЕТ ОЛЛАМЫ"


def test_ollama_fallback_does_not_pin_memory(monkeypatch):
    """Запасной путь в Ollama при основном на LM Studio — разовый (keep_alive=0), иначе
    модель снова сядет в память на 2 часа и война за видеопамять вернётся."""
    from core.brain import llm

    seen: list = []
    llm, seen = _lm_on(monkeypatch, use="main", client=_FakeClient(seen, fail_openai=True), seen=seen)
    asyncio.run(llm.ollama_chat([{"role": "user", "content": "привет"}]))
    bodies = [s[2] for s in seen if s[0] == "POST" and s[1].endswith("/api/chat")]
    assert bodies and all(b.get("keep_alive") == "0" for b in bodies)


def test_warm_skipped_when_lmstudio_main(monkeypatch):
    """Прогрев не грузит модель Ollama заранее, если основное отвечает LM Studio."""
    from core.brain import llm

    seen: list = []
    _lm_on(monkeypatch, use="main", seen=seen)
    assert asyncio.run(llm.warm_ollama()) is False
    assert not [s for s in seen if s[0] == "POST"]


def test_evict_unloads_ollama_main():
    """Выгрузка бьёт точно в основную модель Ollama с keep_alive=0 (малую не трогаем)."""
    from core.brain import llm

    seen: list = []

    class _SyncResp:
        status_code = 200

    class _SyncClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, **kw):
            seen.append((url, json))
            return _SyncResp()

    import httpx
    real = httpx.Client
    httpx.Client = _SyncClient
    try:
        assert llm.evict_ollama_main() is True
    finally:
        httpx.Client = real
    assert len(seen) == 1
    url, body = seen[0]
    assert url == f"{llm.OLLAMA_URL}/api/generate"
    assert body["model"] == llm.OLLAMA_MODEL and body["keep_alive"] == 0
