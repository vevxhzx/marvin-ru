# -*- coding: utf-8 -*-
"""Эмбеддинги и малая модель — через LM Studio, с откатом на Ollama.

Зачем. Раньше эмбеддинги жёстко ходили в Ollama (`/api/embed`), даже когда вся остальная
локальная работа ушла в LM Studio. В итоге нужен был второй запущенный процесс только ради
поиска по заметкам, и когда Ollama не поднята, семантика молчала, а поиск по словам работал
хуже. LM Studio умеет OpenAI-совместимый `/v1/embeddings` — добавляем его и пробуем сначала
его, а Ollama оставляем запасным путём.

Тем же приёмом решается вторая половина вопроса: у LM Studio можно указать ОТДЕЛЬНУЮ
маленькую модель (`brain.lmstudio.small_model`) для судьи и прочих мини-задач, чтобы они не
гоняли ту же 4B, что и основной чат.

Живого LM Studio в тестах нет — клиент подменён заглушкой, как в test_brain_lmstudio.py.
"""
from __future__ import annotations

import asyncio


class _Resp:
    def __init__(self, payload, status_code=200):
        self._p = payload
        self.status_code = status_code
        self.text = str(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._p


class _EmbedClient:
    """LM Studio с эмбеддингами: /v1/models отдаёт и чат-модель, и embed-модель."""

    def __init__(self, seen, models=None, embed_status=200, ollama_models=None):
        self._seen = seen
        self._models = [{"id": m} for m in (models or ["qwen3.5-4b", "nomic-embed-text"])]
        self._embed_status = embed_status
        self._ollama_models = ollama_models if ollama_models is not None else ["qwen3.5:4b", "nomic-embed-text"]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        self._seen.append(("GET", url))
        if "/models" in url:
            return _Resp({"data": self._models})
        return _Resp({"models": [{"name": n} for n in self._ollama_models]})

    async def post(self, url, json=None, **kw):
        self._seen.append(("POST", url, json))
        if url.endswith("/embeddings"):
            if self._embed_status != 200:
                return _Resp({"error": "нет"}, self._embed_status)
            inp = (json or {}).get("input")
            items = inp if isinstance(inp, list) else [inp]
            return _Resp({"data": [{"embedding": [0.1, 0.2, 0.3], "index": i} for i, _ in enumerate(items)]})
        if url.endswith("/api/embed"):
            inp = (json or {}).get("input")
            items = inp if isinstance(inp, list) else [inp]
            return _Resp({"embeddings": [[9.9, 9.9] for _ in items]})
        return _Resp({"message": {"content": "OLLAMA-ANSWER"}})


def _lm_on(monkeypatch, client, embed_model="nomic-embed-text", role="main"):
    from core.brain import llm

    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    monkeypatch.setattr(llm, "LMSTUDIO_BASE", "http://127.0.0.1:1234/v1")
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "qwen3.5-4b")
    monkeypatch.setattr(llm, "LMSTUDIO_USE", role)
    monkeypatch.setattr(llm, "LMSTUDIO_EMBED_MODEL", embed_model)
    monkeypatch.setattr(llm, "GAME_MODE", False)
    monkeypatch.setattr(llm, "_local_client", lambda timeout: client)
    monkeypatch.setattr(llm, "_LMS_MODELS_CACHE", (0.0, []))
    return llm


# --------------------------------------------------------------- сам клиент
def test_embed_goes_to_lmstudio_and_reads_openai_shape(monkeypatch):
    from core.brain.llm import lmstudio

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen))
    got = asyncio.run(lmstudio.lmstudio_embed(["raz", "dva"]))
    assert got == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    posts = [s for s in seen if s[0] == "POST" and s[1].endswith("/embeddings")]
    assert posts and posts[0][2]["model"] == "nomic-embed-text"
    assert posts[0][2]["input"] == ["raz", "dva"]


def test_embed_none_when_lmstudio_answers_error(monkeypatch):
    from core.brain.llm import lmstudio

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen, embed_status=400))
    assert asyncio.run(lmstudio.lmstudio_embed(["raz"])) is None


def test_embed_none_when_no_embed_model_configured(monkeypatch):
    from core.brain.llm import lmstudio

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen), embed_model="")
    assert asyncio.run(lmstudio.lmstudio_embed(["raz"])) is None


def test_embed_model_must_be_loaded_not_just_configured(monkeypatch):
    """Настроенная модель, которой нет в LM Studio, — не повод считать: молча уходим в Ollama."""
    from core.brain.llm import lmstudio

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen, models=["qwen3.5-4b"]), embed_model="nomic-embed-text")
    assert asyncio.run(lmstudio.lmstudio_embed(["raz"])) is None


# --------------------------------------------------------------- маршрутизация
def test_public_embed_prefers_lmstudio_over_ollama(monkeypatch):
    """Главное: Ollama больше не обязана быть запущена."""
    from core.brain import llm

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen))
    got = asyncio.run(llm.embed(["raz"]))
    assert got == [[0.1, 0.2, 0.3]]
    assert any(s[1].endswith("/embeddings") for s in seen)
    assert not any(s[1].endswith("/api/embed") for s in seen)


def test_embed_falls_back_to_ollama_when_lmstudio_off(monkeypatch):
    from core.brain import llm

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen))
    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", False)
    got = asyncio.run(llm.embed(["raz"]))
    assert got == [[9.9, 9.9]]
    assert any(s[1].endswith("/api/embed") for s in seen)


def test_embed_falls_back_to_ollama_when_lmstudio_errors(monkeypatch):
    """LM Studio ответил 500 — не роняем память, считаем через Ollama (как раньше)."""
    from core.brain import llm

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen, embed_status=500))
    got = asyncio.run(llm.embed(["raz"]))
    assert got == [[9.9, 9.9]]
    assert any(s[1].endswith("/api/embed") for s in seen)


def test_embed_none_in_game_mode(monkeypatch):
    """Игровой режим не грузим: карта должна остаться свободной."""
    from core.brain import llm

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen))
    monkeypatch.setattr(llm, "GAME_MODE", True)
    assert asyncio.run(llm.embed(["raz"])) is None
    assert not seen


def test_embed_empty_list_short_circuits(monkeypatch):
    from core.brain import llm

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen))
    assert asyncio.run(llm.embed([])) == []


def test_embed_available_true_when_only_lmstudio_has_model(monkeypatch):
    from core.brain import llm

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen, models=["qwen3.5-4b", "nomic-embed-text"],
                                     ollama_models=["qwen3.5:4b"]))
    assert asyncio.run(llm.embed_available()) is True


def test_embed_available_false_when_nothing_has_model(monkeypatch):
    from core.brain import llm

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen, models=["qwen3.5-4b"], ollama_models=["qwen3.5:4b"]),
           embed_model="")
    assert asyncio.run(llm.embed_available()) is False


# --------------------------------------------------------------- малая модель
def test_small_chat_uses_its_own_model_when_configured(monkeypatch):
    """Судья и мелочи — на отдельной маленькой модели, а не на основной 4B."""
    from core.brain import llm

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen))
    monkeypatch.setattr(llm, "LMSTUDIO_SMALL_MODEL", "qwen3-1.7b")
    asyncio.run(llm.small_chat("system", "vopros"))
    posts = [s for s in seen if s[0] == "POST" and s[1].endswith("/chat/completions")]
    assert posts and posts[0][2]["model"] == "qwen3-1.7b", "малая модель не подставилась"


def test_small_chat_falls_back_to_main_model(monkeypatch):
    from core.brain import llm

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen))
    monkeypatch.setattr(llm, "LMSTUDIO_SMALL_MODEL", "")
    asyncio.run(llm.small_chat("system", "vopros"))
    posts = [s for s in seen if s[0] == "POST" and s[1].endswith("/chat/completions")]
    assert posts and posts[0][2]["model"] == "qwen3.5-4b"


def test_main_chat_ignores_small_model(monkeypatch):
    """Маленькая модель — только для мини-задач; основной чат её не трогает."""
    from core.brain import llm
    from core.brain.llm import lmstudio

    seen = []
    _lm_on(monkeypatch, _EmbedClient(seen))
    monkeypatch.setattr(llm, "LMSTUDIO_SMALL_MODEL", "qwen3-1.7b")
    asyncio.run(lmstudio._lmstudio_chat([{"role": "user", "content": "privet"}]))
    posts = [s for s in seen if s[0] == "POST" and s[1].endswith("/chat/completions")]
    assert posts and posts[0][2]["model"] == "qwen3.5-4b"


# --------------------------------------------------------------- настройки
def test_new_keys_visible_in_settings():
    from core.config import EDITABLE

    assert EDITABLE["brain.lmstudio.embed_model"][0] == "str"
    assert EDITABLE["brain.lmstudio.small_model"][0] == "str"


def test_defaults_are_off_so_old_installs_unchanged():
    """Пустые значения по умолчанию: у кого LM Studio не настроен, поведение прежнее."""
    from core.brain import llm

    assert isinstance(llm.LMSTUDIO_EMBED_MODEL, str)
    assert isinstance(llm.LMSTUDIO_SMALL_MODEL, str)