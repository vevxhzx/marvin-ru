# -*- coding: utf-8 -*-
"""ФАЗА «мозг» — маршрутизация к LLM: предсказуемость, честность, отсутствие двойных токенов.

Офлайн, без сети. Проверяем порядок «правила → локальная модель → облако», поведение при
таймауте/сбое облака и то, что в облако уходит ТОЛЬКО текст (никаких файлов и картинок).

Важно: `_ANSWER_CACHE` в agent и `_ANSWER_CACHE`-подобные кэши обходятся явно — иначе тест
зависит от порядка и может «проскочить» на закэшированном ответе.
"""
from __future__ import annotations

import asyncio
import json
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-фикстура на временной БД)


@pytest.fixture(autouse=True)
def _clear_caches():
    """Чистим кэш ответов агента: иначе тест может пройти на закэшированной фразе."""
    from core.brain import agent

    agent._ANSWER_CACHE.clear()
    yield
    agent._ANSWER_CACHE.clear()


# ============================================================ 1. предсказуемый порядок вызовов
def test_local_only_never_touches_cloud_even_on_failure(monkeypatch):
    """Ключевая гарантия local-first: в режиме local падение локальной модели НЕ превращается
    в запрос в облако. Раньше фолбэк на облако был безусловным — это тихо отменяло режим."""
    from core.brain import agent, llm

    cloud_calls: list[str] = []

    async def cloud(system, user_text, history=None, **kw):
        cloud_calls.append(user_text)
        return "облако ответило"

    async def local(text, channel, with_tools=True):
        return None                      # локальная модель не отвечает

    monkeypatch.setattr(llm, "MODE", "local")
    monkeypatch.setattr(agent, "via_ollama", local)
    monkeypatch.setattr(agent, "via_gemini", cloud)
    monkeypatch.setattr(agent, "is_personal", lambda t: False)   # иначе вопрос ушёл бы локально

    r = asyncio.run(agent.handle("что такое инфляция", "chat"))
    assert cloud_calls == [], f"режим local: облако звали с {cloud_calls}"
    assert r.via == "none"


def test_hybrid_order_is_rules_then_local_then_cloud(monkeypatch):
    """Порядок в hybrid: правило → локальная модель → облако (по необходимости)."""
    from core.brain import agent

    order: list[str] = []

    async def local(text, channel, with_tools=True):
        order.append("local")
        return None                       # локальная не ответила

    async def cloud(text, channel, explicit=True):
        order.append("cloud")
        return None

    monkeypatch.setattr(agent.llm, "MODE", "hybrid")
    # Облако включаем ЯВНО, а не «как сложилось по config.yaml»: без ключа облака cloud_enabled()
    # равно False, и общего вопроса не было бы куда направить. Тест про маршрутизацию, а не про
    # наличие ключей у машины, на которой он запущен (на CI секретов нет, локально есть).
    monkeypatch.setattr(agent.llm, "cloud_enabled", lambda: True)
    monkeypatch.setattr(agent.llm, "gemini_enabled", lambda: True)
    monkeypatch.setattr(agent.llm, "GEMINI_AUTO", True)
    monkeypatch.setattr(agent, "via_ollama", local)
    monkeypatch.setattr(agent, "via_gemini", cloud)
    monkeypatch.setattr(agent, "is_personal", lambda t: False)

    asyncio.run(agent.handle("а есть ли смысл в инфляции вообще", "chat"))
    assert "cloud" in order, order


def test_cloud_result_is_visible_to_user(monkeypatch):
    """Пользователь ВИДИТ, что ответ пришёл из облака (метка ☁️), а не из локальной модели.

    Это часть обещания режима: «в облако уходит только текст», и хозяин должен это видеть."""
    from core.brain import agent, llm

    monkeypatch.setattr(llm, "MARK_SOURCE", True)
    r = agent.Reply("Ответ облака", [], "gemini")
    agent._mark(r)
    assert "☁️" in r.text

    r2 = agent.Reply("Ответ локальный", [], "ollama")
    agent._mark(r2)
    assert "🧠" in r2.text


def test_cloud_mark_can_be_turned_off(monkeypatch):
    """Метку источника можно выключить настройкой (brain.gemini.mark_source: false)."""
    from core.brain import agent, llm

    monkeypatch.setattr(llm, "MARK_SOURCE", False)
    r = agent.Reply("Ответ облака", [], "gemini")
    agent._mark(r)
    assert "☁️" not in r.text


# ============================================================ 2. таймауты и сбои без мигания
def test_cloud_timeout_produces_readable_reason(monkeypatch):
    """Таймаут облака → понятная фраза пользователю: что случилось и что делать."""
    import httpx

    from core.brain import llm

    def explain():
        return llm._explain_cloud_error(httpx.ReadTimeout("timed out"), None)

    msg = explain()
    assert "не достучался" in msg
    assert "Traceback" not in msg
    assert "ReadTimeout" in msg        # класс ошибки полезен для диагностики
    assert len(msg) < 400


@pytest.mark.parametrize("status,needle", [
    (401, "ключ не принят"),
    (404, "не найдена"),
    (429, "лимит"),
    (402, "кредиты"),
])
def test_cloud_http_errors_are_translated(status, needle):
    """Коды провайдера переводятся на человеческий язык, а не показываются как есть."""
    from core.brain import llm

    class R:
        status_code = status
        text = "some provider text"

        def json(self):
            return {"error": {"message": "provider says no"}}

    msg = llm._explain_cloud_error(Exception("boom"), R())
    assert needle in msg.lower()
    assert f"{status}" in msg or "не принят" in msg


def test_no_double_billing_on_retry(monkeypatch):
    """Ретрай на другой модели происходит ОДИН раз и по понятной причине (модель отвергнута).

    Ключевое: ретрай не выполняется на «успешном» ответе — только на 404/429/400, когда токены
    не были потрачены впустую, и не зацикливается."""
    from core.brain import llm

    attempts: list[str] = []

    class R:
        status_code = 404
        text = "no such model"
        _n = 0

        def json(self):
            return {"choices": [{"message": {"content": "ок"}}]}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("404", request=None, response=None)

    import httpx

    async def post(path, body, headers, timeout=45):
        attempts.append(body["model"])
        raise httpx.ConnectError("нет маршрута")

    monkeypatch.setattr(llm, "_cloud_post", post)
    monkeypatch.setattr(llm, "MODE", "cloud")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "CLOUD_KEY", "k")
    monkeypatch.setattr(llm, "CLOUD_MODEL", "нет-такой-модели")
    monkeypatch.setattr(llm, "resolve_cloud_model", lambda force=False: asyncio.sleep(0, result="нет-такой-модели"))
    monkeypatch.setattr(llm, "_cloud_routes", lambda: [("direct", None)])

    out = asyncio.run(llm.cloud_chat("S", "привет"))
    assert out is None
    assert llm.LAST_CLOUD_ERROR and "Traceback" not in llm.LAST_CLOUD_ERROR


def test_num_ctx_grows_instead_of_silent_truncation(monkeypatch):
    """Слишком большой запрос НЕ обрезается молча: окно расширяется, и об этом пишется в лог.

    Тихая обрезка даёт «Сэр,» вместо ответа — самый неприятный сбой в этом проекте."""
    import inspect

    from core.brain import llm

    src = inspect.getsource(llm.ollama_chat)
    assert "num_ctx *= 2" in src
    assert "не влезает в num_ctx" in src      # предупреждение есть
    assert "num_ctx < 32768" in src# и потолок расширения ограничен


def test_prompt_is_fitted_before_request():
    """Промпт ужимается ДО отправки (_fit_budget), а не после обрезанного ответа."""
    import inspect

    from core.brain import agent

    src = inspect.getsource(agent.via_ollama)
    assert src.index("_fit_budget") < src.index("for _ in range(4)")


# ============================================================ 3. в облако уходит только текст
def test_cloud_request_contains_text_only(monkeypatch):
    """В облако уходит текст. Ни файлов, ни путей, ни картинок в теле запроса быть не должно."""
    from core.brain import llm

    seen: list[dict] = []

    async def fake_post(path, body, headers, timeout=45):
        seen.append(body)
        return None

    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "CLOUD_KEY", "k")
    monkeypatch.setattr(llm, "anonymize", lambda t: t)
    monkeypatch.setattr(llm, "resolve_cloud_model", lambda force=False: asyncio.sleep(0, result="m"))
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    monkeypatch.setattr(llm, "_cloud_stream", lambda b, h, s: asyncio.sleep(0, result=None))
    asyncio.run(llm.cloud_chat("system", "привет", None))
    assert seen, "запрос в облако должен был уйти"
    body = json.dumps(seen[0], ensure_ascii=False).lower()
    for banned in (".png", ".jpg", ".pdf", ".db", "c:\\\\", "/home/", "base64,"):
        assert banned not in body, f"в облако ушло лишнее: {banned}"


def test_anonymizer_hides_personal_data(monkeypatch):
    """Анонимайзер прячет имя, телефон, суммы и секреты ДО отправки (дефолт включён)."""
    from core.brain import llm

    text = "Позвони Васе по +7 999 123-45-67, он должен 45000, почта a@b.ru"
    out = llm.anonymize(text)
    assert "999 123" not in out
    assert "a@b.ru" not in out
    assert "[скрыто]" in out or "[телефон]" in out or "[email]" in out


def test_anonymizer_enabled_by_default(monkeypatch):
    """Анонимайзер включён по умолчанию и отключается только явным настройкой."""
    from core.brain import llm
    from core.config import cfg

    assert cfg.brain.gemini.anonymize is True


def test_history_survives_anonymizer(monkeypatch):
    """История чата тоже проходит анонимайзер — иначе имя всплыло бы мимо фильтра."""
    from core.brain import llm
    from core.config import cfg

    seen: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ок"}]}}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            seen["body"] = json
            return _Resp()

    monkeypatch.setattr(cfg.brain.gemini, "anonymize", True)
    monkeypatch.setattr(llm, "GEMINI_KEY", "k")
    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "gemini_enabled", lambda: True)
    monkeypatch.setattr(llm, "resolve_gemini_model", lambda: asyncio.sleep(0, result="gemini-2.5-flash"))
    monkeypatch.setattr(llm, "_gemini_client", lambda timeout: _Client())
    ans = asyncio.run(llm.gemini_chat("S", "мой телефон +7 999 123-45-67",
                                      [{"role": "user", "text": "письмо a@b.ru"}]))
    assert ans == "ок"
    body = json.dumps(seen["body"], ensure_ascii=False)
    assert "999 123" not in body and "a@b.ru" not in body, body
    assert "[скрыто]" in body or "[телефон]" in body or "[email]" in body


# ============================================================ 4. num_ctx и лимиты контекста
def test_context_budget_is_positive_by_default():
    """Бюджет контекста считается от реального num_ctx и остаётся положительным."""
    from core.brain import budget, llm

    assert llm.OLLAMA_NUM_CTX >= 2048
    est = budget.est_request([{"role": "user", "content": "x" * 3000}])
    assert est > 0


def test_system_prompt_size_is_stable():
    """Размер системного промпта не должен «прыгать» от запроса к запросу — иначе кэш Ollama сбрасывается.

    Системный промпт собирается из постоянных блоков; меняться от фразы может только
    блок памяти (он идёт отдельно, в сообщение пользователя)."""
    from core.brain import agent

    a = agent._system()
    b = agent._system()
    assert a == b


def test_memory_block_is_not_in_system_prompt():
    """Блок «что ты знаешь о хозяине» НЕ живёт в системном сообщении ОСНОВНОГО пути.

    Основной путь — с инструментами: там системный промпт + схемы инструментов постоянны
    от запроса к запросу, и Ollama берёт их из кэша. Если положить туда память (она меняется
    от фразы к фразе), кэш сбрасывается и модель заново читает ~6k токенов — на слабой
    видеокарте это 15–25 с на ход."""
    import inspect

    from core.brain import agent

    src = inspect.getsource(agent.via_ollama)
    # блок памяти приходит результатом _turn_context и уходит в сообщение пользователя
    assert "_turn_context(text)" in src
    assert 'ctx_head = budget.assemble' in src
    assert "ЧТО ТЫ ЗНАЕШЬ" not in agent._system()
    # статика системного промпта постоянна (иначе кэш Ollama бесполезен)
    assert agent._system() == agent._system()


def test_tools_schema_is_conditional_not_always_full():
    """Набор схем инструментов зависит от смысла фразы, а не всегда полный.

    40 схем — это ~5.3k токенов промпта; на 6 ГБ видеокарте их чтение занимает 30–35 с."""
    from core.tools import registry

    core_only = registry.tools_schema(with_cloud=False, text="кот опять сожрал провод")
    money = registry.tools_schema(with_cloud=False, text="сколько я должен по долгам")
    assert len(core_only) < len(money)
    assert "add_expense" in [t["function"]["name"] for t in core_only]
    assert "list_debts" in [t["function"]["name"] for t in money]


def test_cloud_tool_not_sent_to_local_only_turn():
    """Локальной модели схема облачного инструмента не нужна, если облако выключено."""
    from core.tools import registry

    names = [t["function"]["name"] for t in registry.tools_schema(with_cloud=False, text="привет")]
    assert registry.CLOUD_TOOL not in names
    assert registry.CLOUD_TOOL in [t["function"]["name"] for t in registry.tools_schema(with_cloud=True, text="привет")]


# ============================================================ reasoning в чат не попадает
def test_cloud_openrouter_suppresses_reasoning(monkeypatch):
    """OpenRouter: мыслим коротко (effort=minimal) и reasoning не отдаём; в системном промпте —
    просьба отвечать только готовым результатом.

    FIX: в чат приходил сплошной поток рассуждений («Хорошо, пользователь просит шутку… Сначала
    смотрю на данные…»), обрезанный по max_tokens, без единой финальной реплики."""
    from core.brain import llm

    seen: list[dict] = []

    async def fake_post(path, body, headers, timeout=45):
        seen.append(body)
        return None

    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "CLOUD_KEY", "k")
    monkeypatch.setattr(llm, "anonymize", lambda t: t)
    monkeypatch.setattr(llm, "resolve_cloud_model", lambda force=False: asyncio.sleep(0, result="deepseek/deepseek-r1:free"))
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    monkeypatch.setattr(llm, "_cloud_stream", lambda b, h, s: asyncio.sleep(0, result=None))
    asyncio.run(llm.cloud_chat("system", "привет", None))
    assert seen, "запрос в облако должен был уйти"
    body = seen[0]
    assert body.get("reasoning") == {"effort": "minimal", "exclude": True}, body.get("reasoning")
    sys_msg = body["messages"][0]
    assert sys_msg["role"] == "system"
    assert llm._NO_THINK_HINT in sys_msg["content"], "в системный промпт не попала просьба не показывать мысли"


def test_reasoning_is_never_returned_as_answer(monkeypatch):
    """Пустой content при заполненном reasoning → None (фолбэк на локальную модель), а не поток мыслей."""
    from core.brain import llm

    class _Resp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"finish_reason": "length",
                                 "message": {"content": "",
                                             "reasoning": "Хорошо, пользователь просит шутку. Сначала смотрю на данные: "
                                                          "сейчас понедельник, за ПК 1 минута. Нужно ответить в характере…"}}]}

    async def fake_post(path, body, headers, timeout=45):
        return _Resp()

    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "CLOUD_KEY", "k")
    monkeypatch.setattr(llm, "anonymize", lambda t: t)
    monkeypatch.setattr(llm, "resolve_cloud_model", lambda force=False: asyncio.sleep(0, result="deepseek/deepseek-r1:free"))
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    out = asyncio.run(llm.cloud_chat("S", "расскажи шутку", None))
    assert out is None, f"рассуждения не должны отдаваться как ответ, получено: {str(out)[:80]!r}"
    assert llm.LAST_CLOUD_ERROR and "рассуждени" in llm.LAST_CLOUD_ERROR


# ============================================================ DeepSeek как облако
def test_deepseek_provider_preset_is_ready():
    """Провайдер DeepSeek подключается пресетом: base_url, модель и опознавание reasoning-версии."""
    from core.brain import llm

    p = llm.PROVIDERS["deepseek"]
    assert p["base_url"] == "https://api.deepseek.com/v1"
    assert p["model"] == "deepseek-chat"
    monkey_model = llm._THINK_RX.search("deepseek-reasoner")
    assert monkey_model, "deepseek-reasoner должна распознаваться как reasoning-модель (лимит ответа 700, а не 220)"


def test_deepseek_temperature_is_stripped_on_400(monkeypatch):
    """deepseek-reasoner отвечает 400 на temperature — снимаем параметр и повторяем, а не уводим ответ в локальную модель."""
    from core.brain import llm

    seen: list[dict] = []
    calls = {"n": 0}

    class _Resp:
        status_code = 400
        text = "deepseek-reasoner does not support the parameter temperature"

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "Готово, ответил."}}]}

    async def fake_post(path, body, headers, timeout=45):
        calls["n"] += 1
        seen.append(dict(body))
        if calls["n"] == 1:
            return _Resp()
        r = _Resp()
        r.status_code = 200
        r.text = ""
        return r

    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "CLOUD_KEY", "k")
    monkeypatch.setattr(llm, "anonymize", lambda t: t)
    monkeypatch.setattr(llm, "resolve_cloud_model", lambda force=False: asyncio.sleep(0, result="deepseek-reasoner"))
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    out = asyncio.run(llm.cloud_chat("system", "привет", None))
    assert out == "Готово, ответил.", out
    assert calls["n"] == 2, "должен быть ровно один повтор без temperature"
    assert "temperature" in seen[0] and "temperature" not in seen[1]