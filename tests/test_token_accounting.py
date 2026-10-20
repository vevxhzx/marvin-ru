# -*- coding: utf-8 -*-
"""Учёт токенов и денег: сбор usage со всех провайдеров, цены из настроек, журнал, API, экран.

Что здесь проверяется (по порядку «снизу вверх»):
  1) миграция v17 добавляет в `run` три колонки, идемпотентна и не теряет строки;
  2) usage разбирается из трёх разных форматов ответа (OpenRouter/OpenAI, Ollama, Gemini)
     и из мусора (нет полей, строки вместо чисел) — молча, без исключений;
  3) `trace.finish()` кладёт в строку накопленные за ход токены и суммирует несколько вызовов модели;
  4) деньги считаются ТОЛЬКО по цене из brain.pricing: известная цена — ожидаемая сумма,
     неизвестная — 0 и честный флаг «цена неизвестна» (никаких выдуманных чисел);
  5) `GET /api/runs` и `GET /api/runs/report` отдают токены и блок `spend`;
  6) `report_text()` (это уходит в Telegram словами) молчит про деньги, пока цена не задана.

Всё живёт на временной БД (`fresh_db` из tests/conftest.py), боевой `data/jarvis.db` не трогается.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("ASSISTANT_TEST", "1")

from core import db, migrations  # noqa: E402
from core.brain import llm  # noqa: E402
from core.brain.llm import base as llm_base  # noqa: E402
from core.services import trace  # noqa: E402

# Модель, которой платит хозяин (OpenRouter). Цены выдуманные — важно только их подставление.
DS = "deepseek/deepseek-v4.1-flash"


class _Node:
    """Простой узел конфига (как core.config._Node, но без импорта приватного класса)."""

    def __init__(self, d: dict):
        self.__dict__.update(d)


def _pricing(prompt: str = "", completion: str = "", models: dict | None = None) -> _Node:
    node = _Node({"default_prompt": prompt, "default_completion": completion})
    if models is not None:
        node.models = models
    return _Node({"pricing": node})


@pytest.fixture(autouse=True)
def _clean_usage():
    """Аккумулятор usage живёт в contextvars — сбрасываем между тестами, чтобы не наследовать ход."""
    llm_base.usage_reset()
    trace._cur.set(None)
    yield
    llm_base.usage_reset()
    trace._cur.set(None)


@pytest.fixture
def no_price(monkeypatch):
    """Цены не заданы (дефолт репозитория) — деньги не выдумываются."""
    monkeypatch.setattr(llm_base, "cfg", _Node({"brain": _pricing()}), raising=False)
    return monkeypatch


# ============================================================ 1. миграция
def test_v18_is_the_next_free_version():
    """Новая миграция обязана быть следующим свободным номером (иначе её не применить)."""
    versions = [v for v, _, _ in migrations.MIGRATIONS]
    assert versions == sorted(versions), "версии миграций должны идти по возрастанию"
    assert versions[-1] == 18, "следующая свободная версия — 18"
    assert len(set(versions)) == len(versions), "номер миграции не переиспользуется"
    # v17 — учёт токенов; проверяем, что она на месте, хотя последняя уже v18
    descriptions = {v: d for v, d, _ in migrations.MIGRATIONS}
    assert "run" in descriptions[17]


def _cols(eng, table: str = "run") -> set[str]:
    with eng.connect() as c:
        return {r[1] for r in c.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()}


def test_run_columns_appear_after_migration(tmp_path):
    """Колонки появляются именно миграцией — и в старой базе, и на свежей."""
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:
        c.execute(text('CREATE TABLE "run" (id INTEGER PRIMARY KEY, text VARCHAR, created_at DATETIME)'))
        c.execute(text("INSERT INTO \"run\" (id, text) VALUES (1, 'старый ход')"))
    migrations.apply(eng, had_db=False)
    assert {"prompt_tokens", "completion_tokens", "cost_usd"} <= _cols(eng)
    with eng.connect() as c:
        # миграция не разрушительна: старая строка на месте, новые колонки с дефолтами
        row = c.execute(text('SELECT text, prompt_tokens, completion_tokens, cost_usd FROM "run" WHERE id=1')).one()
        assert row[0] == "старый ход"
        assert (row[1], row[2], row[3]) == (0, 0, 0.0)


def test_migration_is_idempotent(tmp_path):
    """Повторный apply() ничего не применяет и не падает; сами колонки добавляются один раз."""
    db.SQLModel.metadata.create_all(eng := create_engine(f"sqlite:///{tmp_path / 'a.db'}"))
    first = migrations.apply(eng, had_db=False)
    assert first["applied"] == [v for v, _, _ in migrations.MIGRATIONS]
    before = _cols(eng)
    assert {"prompt_tokens", "completion_tokens", "cost_usd"} <= before
    second = migrations.apply(eng, had_db=False)
    assert second["applied"] == []
    assert _cols(eng) == before


def test_fresh_db_has_usage_columns(fresh_db):
    """На боевой схеме (SQLModel) колонки тоже есть — иначе модель и база разойдутся."""
    assert {"prompt_tokens", "completion_tokens", "cost_usd"} <= set(db.Run.model_fields.keys())
    assert {"prompt_tokens", "completion_tokens", "cost_usd"} <= _cols(db.engine)


# ============================================================ 2. usage со всех провайдеров
def test_tokens_from_openrouter_answer():
    """OpenRouter (OpenAI-формат): usage.prompt_tokens / completion_tokens / total_tokens."""
    data = {"id": "gen-1", "model": DS,
            "usage": {"prompt_tokens": 1234, "completion_tokens": 56, "total_tokens": 1290},
            "choices": [{"message": {"content": "ок"}}]}
    assert llm_base.tokens_openai(data) == (1234, 56)


def test_tokens_from_lmstudio_answer():
    """LM Studio — тот же OpenAI-формат, но без total_tokens."""
    data = {"usage": {"prompt_tokens": 42, "completion_tokens": 7},
            "choices": [{"message": {"content": "ок"}}]}
    assert llm_base.tokens_openai(data) == (42, 7)


def test_tokens_from_ollama_answer():
    """Ollama /api/chat: prompt_eval_count и eval_count, а не usage."""
    data = {"model": "qwen3:4b", "done": True, "prompt_eval_count": 812, "eval_count": 39,
            "message": {"content": "ок"}}
    assert llm_base.tokens_ollama(data) == (812, 39)


def test_tokens_from_gemini_answer():
    """Gemini отдаёт usageMetadata с другими именами."""
    data = {"usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 20, "totalTokenCount": 320}}
    assert llm_base.tokens_gemini(data) == (300, 20)


@pytest.mark.parametrize("bad", [None, {}, {"usage": None}, {"usage": {}},
                                 {"usage": {"prompt_tokens": "x", "completion_tokens": None}},
                                 {"prompt_eval_count": "нет"}, {"usage": {"prompt_tokens": -5}}])
def test_tokens_tolerate_junk(bad):
    """Мусор в ответе не должен ронять ход: молча возвращаем нули."""
    for fn in (llm_base.tokens_openai, llm_base.tokens_ollama, llm_base.tokens_gemini):
        p, c = fn(bad)
        assert p == 0 and c == 0, fn


def test_usage_note_accumulates_in_context():
    llm_base.usage_reset()
    assert llm_base.usage_now().prompt_tokens == 0
    llm_base.usage_note(DS, 100, 10)
    llm_base.usage_note(DS, 200, 20)
    u = llm_base.usage_now()
    assert (u.prompt_tokens, u.completion_tokens) == (300, 30)
    assert u.n_calls == 2 and DS in u.models
    llm_base.usage_reset()
    assert llm_base.usage_now().n_calls == 0


def test_usage_note_ignores_empty_calls():
    """Ответ без счётчиков (LM Studio без usage) не должен создавать «нулевой» вызов."""
    llm_base.usage_reset()
    llm_base.usage_note("qwen3:4b", 0, 0)
    assert llm_base.usage_now().n_calls == 0


# ============================================================ 2б. провайдеры действительно отмечают usage
# Парсеры выше проверяют формат, а эти тесты — что вызовы вставлены в те провайдеры,
# где должны быть: иначе счётчик останется пустым при живом облаке.


class _Resp:
    """Фейковый ответ провайдера: ровно те методы, которые трогает код cloud/ollama/lmstudio."""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(str(self.status_code), request=None, response=None)


def _cloud_ready(monkeypatch, model: str = DS):
    """Облако включено, модель задана, анонимайзер и маршруты не трогают сеть."""
    from core.brain import llm

    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "CLOUD_KEY", "k")
    monkeypatch.setattr(llm, "CLOUD_MODEL", model)
    monkeypatch.setattr(llm, "anonymize", lambda t: t)
    monkeypatch.setattr(llm, "resolve_cloud_model", lambda force=False: _sleep(model))
    monkeypatch.setattr(llm, "_cloud_stream", lambda b, h, s: _sleep(None))
    monkeypatch.setattr(llm, "_cloud_routes", lambda: [("прямо", None)])
    return llm


async def _sleep(value):
    return value


# ВАЖНО: счётчик живёт в ContextVar, а asyncio.run() выполняет корутину в СВОЕЙ копии
# контекста. Поэтому usage_now() читаем ВНУТРИ той же корутины, что и вызов модели,
# иначе увидим пустой счётчик из внешнего контекста (и это не баг, а смысл ContextVar).


def test_cloud_chat_counts_openrouter_usage(monkeypatch):
    import asyncio

    llm = _cloud_ready(monkeypatch)
    payload = {"model": DS, "choices": [{"message": {"content": "ок"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 321, "completion_tokens": 12}}

    async def post(path, body, headers, timeout=None):
        return _Resp(payload)

    monkeypatch.setattr(llm, "_cloud_post", post)

    async def scenario():
        llm_base.usage_reset()
        out = await llm.cloud_chat("S", "привет")
        return out, llm_base.usage_now()

    out, u = asyncio.run(scenario())
    assert out == "ок"
    assert (u.prompt_tokens, u.completion_tokens) == (321, 12)
    assert u.models == [DS]


def test_cloud_chat_counts_retried_request_separately(monkeypatch):
    """Ответ обрезан по max_tokens, запрос ушёл второй раз — платят дважды, значит считаем дважды.

    Иначе статистика врёт в сторону «меньше»: хозяин видит половину реального счёта."""
    import asyncio

    llm = _cloud_ready(monkeypatch)
    seq = [
        # первый ответ: всё ушло в размышления, content пуст, finish_reason=length → будет повтор
        _Resp({"model": DS, "choices": [{"message": {"content": "", "reasoning": "…"},
                                          "finish_reason": "length"}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 50}}),
        # повтор с max_tokens=4096: ответ нормальный
        _Resp({"model": DS, "choices": [{"message": {"content": "ок"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 20}}),
    ]
    calls: list = []

    async def post(path, body, headers, timeout=None):
        calls.append(body.get("max_tokens"))
        return seq[min(len(calls) - 1, len(seq) - 1)]

    monkeypatch.setattr(llm, "_cloud_post", post)

    async def scenario():
        llm_base.usage_reset()
        out = await llm.cloud_chat("S", "привет")
        return out, llm_base.usage_now()

    out, u = asyncio.run(scenario())
    assert out == "ок" and len(calls) == 2, "ожидался повтор запроса с увеличенным лимитом"
    assert (u.prompt_tokens, u.completion_tokens) == (200, 70)


def test_cloud_tools_chat_counts_usage(monkeypatch):
    """Путь с инструментами (режим cloud) тоже считает токены — там их больше всего."""
    import asyncio

    llm = _cloud_ready(monkeypatch)
    payload = {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "add_task", "arguments": '{"title": "купить хлеб"}'}}]}}],
        "usage": {"prompt_tokens": 700, "completion_tokens": 33}}

    async def post(path, body, headers, timeout=None):
        return _Resp(payload)

    monkeypatch.setattr(llm, "_cloud_post", post)

    async def scenario():
        llm_base.usage_reset()
        out = await llm.cloud_tools_chat([{"role": "user", "content": "задача: купить хлеб"}],
                                          [{"type": "function", "function": {"name": "add_task"}}])
        return out, llm_base.usage_now()

    out, u = asyncio.run(scenario())
    assert out and out["tool_calls"][0]["name"] == "add_task"
    assert (u.prompt_tokens, u.completion_tokens) == (700, 33)


def test_ollama_chat_counts_usage(monkeypatch):
    """Локальная модель денег не стоит, но токены показываем: по ним видно объём и скорость."""
    import asyncio

    from core.brain import llm

    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", False)
    payload = {"done": True, "prompt_eval_count": 640, "eval_count": 48,
               "message": {"content": "ок", "tool_calls": []}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return _Resp(payload)

    monkeypatch.setattr(llm, "_local_client", lambda t: _Client())

    async def scenario():
        llm_base.usage_reset()
        out = await llm.ollama_chat([{"role": "user", "content": "привет"}])
        return out, llm_base.usage_now()

    out, u = asyncio.run(scenario())
    assert out["content"] == "ок"
    assert (u.prompt_tokens, u.completion_tokens) == (640, 48)


def test_usage_does_not_leak_from_one_task_to_another(monkeypatch):
    """Фоновая задача не приписывает свои токены ходу хозяина.

    Именно ради этого счётчик на ContextVar: у фоновой задачи (уборка памяти, напоминания)
    своя копия контекста, её set() не виден в ходе, который её запустил."""
    import asyncio

    from core.brain import llm

    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", False)

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return _Resp({"done": True, "prompt_eval_count": 300, "eval_count": 30,
                          "message": {"content": "фон", "tool_calls": []}})

    monkeypatch.setattr(llm, "_local_client", lambda t: _Client())

    async def scenario():
        llm_base.usage_reset()

        async def background():
            return await llm.ollama_chat([{"role": "user", "content": "фоновая уборка"}])

        task = asyncio.create_task(background())
        await asyncio.sleep(0.05)             # фоновый вызов успел отметить токены у себя
        own = await llm.ollama_chat([{"role": "user", "content": "мой ход"}])
        await task
        return own, llm_base.usage_now()

    out, u = asyncio.run(scenario())
    assert out["content"] == "фон"
    assert (u.prompt_tokens, u.completion_tokens) == (300, 30), "в ход хозяина попал чужой вызов"


# ============================================================ 3. журнал
def test_finish_writes_tokens_of_the_turn(fresh_db, no_price):
    trace.start("расскажи анекдот", "web")
    trace.step(DS)
    llm_base.usage_note(DS, 1500, 120)
    trace.finish("gemini", [])
    row = trace.recent()[0]
    assert row["prompt_tokens"] == 1500
    assert row["completion_tokens"] == 120
    assert row["tokens"] == 1620
    assert row["cost_usd"] == 0.0 and row["priced"] is False


def test_finish_sums_several_model_calls(fresh_db, no_price):
    """Цикл «модель → инструмент → модель»: токены обоих вызовов в одной строке."""
    trace.start("запиши три траты", "web")
    llm_base.usage_note(DS, 1000, 100)
    trace.step(DS)
    llm_base.usage_note(DS, 900, 250)
    trace.finish("gemini", ["add_expense"])
    row = trace.recent()[0]
    assert row["steps"] == 1
    assert (row["prompt_tokens"], row["completion_tokens"]) == (1900, 350)


def test_start_resets_usage_of_previous_turn(fresh_db, no_price):
    """Ходы не делят счётчик: следующий ход не inherits токены предыдущего."""
    trace.start("первый", "web")
    llm_base.usage_note(DS, 500, 50)
    trace.finish("gemini", [])
    trace.start("второй", "web")
    llm_base.usage_note(DS, 10, 1)
    trace.finish("gemini", [])
    rows = trace.recent()
    assert rows[0]["prompt_tokens"] == 10
    assert rows[1]["prompt_tokens"] == 500


def test_rules_turn_has_no_tokens(fresh_db, no_price):
    """Ход, отвеченный шаблонами, токенов не тратит — честный ноль, а не выдумка."""
    trace.start("потратил 700 на такси", "web")
    trace.finish("rules", ["add_expense"])
    row = trace.recent()[0]
    assert (row["prompt_tokens"], row["completion_tokens"], row["cost_usd"]) == (0, 0, 0.0)


def test_run_model_filled_from_usage_when_step_missing(fresh_db, no_price):
    """Если trace.step не звали, модель берётся из usage — иначе в разбивке «пусто»."""
    trace.start("привет", "web")
    llm_base.usage_note(DS, 10, 2)
    trace.finish("gemini", [])
    assert trace.recent()[0]["model"] == DS


# ============================================================ 4. деньги
def test_cost_with_known_price(monkeypatch):
    """Известная цена → ожидаемая сумма: 1M токенов по $0.14/$0.28."""
    monkeypatch.setattr(llm_base, "cfg", _Node({"brain": _pricing("0.14", "0.28")}), raising=False)
    usd, priced = llm_base.cost_usd(DS, 1_000_000, 1_000_000)
    assert priced is True
    assert usd == pytest.approx(0.42, rel=1e-6)
    usd2, priced2 = llm_base.cost_usd(DS, 1000, 200)
    assert priced2 is True
    assert usd2 == pytest.approx(0.000196, rel=1e-3)


def test_cost_unknown_price_is_zero_and_flagged(no_price):
    """Цены нет — ноль и флаг «не посчитано». Никаких «примерно»."""
    usd, priced = llm_base.cost_usd(DS, 1_000_000, 1_000_000)
    assert usd == 0.0 and priced is False


def test_pricing_prefers_per_model_entry(monkeypatch):
    """Своя цена модели важнее общей; общая — запасной вариант для остальных."""
    monkeypatch.setattr(llm_base, "cfg",
                        _Node({"brain": _pricing("0.14", "0.28", models={DS: {"prompt": 1.0, "completion": 2.0}})}),
                        raising=False)
    assert llm_base.pricing_for(DS) == (1.0, 2.0)
    assert llm_base.pricing_for("some/other-model") == (0.14, 0.28)
    assert llm_base.pricing_for("") is None


def test_pricing_matches_free_suffix(monkeypatch):
    """OpenRouter отдаёт «model:free» — цена должна находиться по имени без суффикса."""
    monkeypatch.setattr(llm_base, "cfg",
                        _Node({"brain": _pricing(models={DS: {"prompt": 0.5, "completion": 1.5}})}),
                        raising=False)
    assert llm_base.pricing_for(DS + ":free") == (0.5, 1.5)
    assert llm_base.pricing_for("DEEPSEEK/DeepSeek-V4.1-Flash") == (0.5, 1.5)


def test_pricing_list_shorthand(monkeypatch):
    """Короткая запись «модель: [prompt, completion]» тоже понимается."""
    monkeypatch.setattr(llm_base, "cfg", _Node({"brain": _pricing(models={DS: [0.3, 0.9]})}), raising=False)
    assert llm_base.pricing_for(DS) == (0.3, 0.9)


def test_explicit_zero_price_means_free(monkeypatch):
    """Явный ноль — это «бесплатно»: расход 0, но ход считается посчитанным."""
    monkeypatch.setattr(llm_base, "cfg",
                        _Node({"brain": _pricing("9", "9", models={DS: {"prompt": 0, "completion": 0}})}),
                        raising=False)
    usd, priced = llm_base.cost_usd(DS, 1000, 1000)
    assert usd == 0.0 and priced is True


def test_trace_writes_cost_per_call_model(fresh_db, monkeypatch):
    """Цена берётся по модели КАЖДОГО вызова, а не по модели хода: локальный ноль, облако — по цене."""
    monkeypatch.setattr(llm_base, "cfg",
                        _Node({"brain": _pricing(models={DS: {"prompt": 1.0, "completion": 2.0}})}),
                        raising=False)
    trace.start("смешанный ход", "web")
    llm_base.usage_note("qwen3:4b", 5000, 900)   # локальная — денег нет
    llm_base.usage_note(DS, 1_000_000, 500_000)
    trace.finish("gemini", [])
    row = trace.recent()[0]
    assert row["cost_usd"] == pytest.approx(2.0, rel=1e-6)
    assert row["priced"] is True


def test_spend_stats_split_by_route_and_model(fresh_db, monkeypatch):
    """Сводка расхода: суммы, токены, разбивка по путям и по моделям, честный «без цены»."""
    monkeypatch.setattr(llm_base, "cfg",
                        _Node({"brain": _pricing(models={DS: {"prompt": 1.0, "completion": 2.0}})}),
                        raising=False)
    # два облачных хода с ценой
    for _ in range(2):
        trace.start("спроси у облака", "web")
        llm_base.usage_note(DS, 1_000_000, 500_000)
        trace.finish("gemini", [])
    # локальный ход — цены нет
    trace.start("ответь локально", "tg")
    llm_base.usage_note("qwen3:4b", 400, 80)
    trace.finish("ollama", [])
    # правила — токенов нет вовсе
    trace.start("потратил 100 на кофе", "tg")
    trace.finish("rules", ["add_expense"])

    sp = trace.spend_stats(30)
    assert sp["total_usd"] == pytest.approx(4.0, rel=1e-6)
    assert sp["tokens_in"] == 2_000_000 + 400
    assert sp["tokens_out"] == 1_000_000 + 80
    assert sp["by_route"]["gemini"]["usd"] == pytest.approx(4.0, rel=1e-6)
    assert sp["by_route"]["gemini"]["n"] == 2
    assert sp["by_route"]["ollama"]["usd"] == 0.0
    assert sp["by_route"]["rules"]["tokens_in"] == 0
    assert sp["by_model"][DS]["usd"] == pytest.approx(4.0, rel=1e-6)
    assert sp["by_model"]["qwen3:4b"]["tokens_in"] == 400
    assert sp["uncpriced"] == 1          # локальный ход: токены есть, цена неизвестна
    assert sp["priced"] is True
    assert sp["days"] == 30


def test_spend_stats_without_prices_is_honest(fresh_db, no_price):
    """Цен нет: total_usd = 0, uncpriced растёт, priced = False — сайт покажет «задай цену»."""
    trace.start("спроси", "web")
    llm_base.usage_note(DS, 10_000, 1_000)
    trace.finish("gemini", [])
    sp = trace.spend_stats(7)
    assert sp["total_usd"] == 0.0
    assert sp["priced"] is False and sp["counted"] is False
    assert sp["uncpriced"] == 1
    assert sp["tokens_in"] == 10_000


def test_money_recorded_earlier_survives_price_removal(fresh_db, monkeypatch):
    """Цену посчитали, потом убрали из настроек — потраченные деньги остаются потраченными.

    Обратный случай «цены нет, но деньги посчитаны» тоже возможен: нечего отменять задним
    числом. Поэтому у spend два флага: priced (цена настроена сейчас) и counted (стоимость
    известна хоть для части ходов). Считать их одним было бы враньё в обе стороны."""
    monkeypatch.setattr(llm_base, "cfg",
                        _Node({"brain": _pricing(models={DS: {"prompt": 1.0, "completion": 2.0}})}),
                        raising=False)
    trace.start("спроси", "web")
    llm_base.usage_note(DS, 1_000_000, 1_000_000)
    trace.finish("gemini", [])
    # хозяин убрал цену (например переехал на другого провайдера)
    monkeypatch.setattr(llm_base, "cfg", _Node({"brain": _pricing()}), raising=False)

    sp = trace.spend_stats(7)
    assert sp["total_usd"] == pytest.approx(3.0, rel=1e-6), "потраченное не должно обнуляться"
    assert sp["priced"] is False          # настройки сейчас пусты
    assert sp["counted"] is True          # но стоимость известна
    assert sp["uncpriced"] == 0
    assert trace.recent()[0]["priced"] is True

    txt = trace.report_text(7)
    assert "$" in txt, "посчитанные деньги должны упоминаться, даже если цена убрана"


def test_free_model_is_not_uncpriced(fresh_db, monkeypatch):
    """Явно нулевая цена = «бесплатно»: ход посчитан, «без цены» про него не говорим."""
    monkeypatch.setattr(llm_base, "cfg", _Node({"brain": _pricing(models={DS: {"prompt": 0, "completion": 0}})}),
                        raising=False)
    trace.start("спроси", "web")
    llm_base.usage_note(DS, 5_000, 400)
    trace.finish("gemini", [])
    sp = trace.spend_stats(7)
    assert sp["total_usd"] == 0.0
    assert sp["uncpriced"] == 0
    assert sp["counted"] is True
    assert trace.recent()[0]["priced"] is True


# ============================================================ 5. API
def test_api_runs_items_have_tokens_and_cost(fresh_db, _client, monkeypatch):
    monkeypatch.setattr(llm_base, "cfg",
                        _Node({"brain": _pricing(models={DS: {"prompt": 1.0, "completion": 2.0}})}),
                        raising=False)
    trace.start("вопрос в облако", "web")
    llm_base.usage_note(DS, 1_000_000, 500_000)
    trace.finish("gemini", [])
    item = _client.get("/api/runs").json()["items"][0]
    assert item["prompt_tokens"] == 1_000_000
    assert item["completion_tokens"] == 500_000
    assert item["tokens"] == 1_500_000
    assert item["cost_usd"] == pytest.approx(2.0, rel=1e-6)
    assert item["priced"] is True


def test_api_runs_report_has_spend_block(fresh_db, _client, monkeypatch):
    monkeypatch.setattr(llm_base, "cfg",
                        _Node({"brain": _pricing(models={DS: {"prompt": 1.0, "completion": 2.0}})}),
                        raising=False)
    trace.start("вопрос", "web")
    llm_base.usage_note(DS, 1_000_000, 500_000)
    trace.finish("gemini", [])
    rep = _client.get("/api/runs/report?days=7").json()
    sp = rep["spend"]
    assert sp["days"] == 7
    assert sp["total_usd"] == pytest.approx(2.0, rel=1e-6)
    assert sp["tokens_in"] == 1_000_000 and sp["tokens_out"] == 500_000
    assert sp["by_route"]["gemini"]["usd"] == pytest.approx(2.0, rel=1e-6)
    assert sp["by_route"]["gemini"]["ru"]          # подпись пути по-русски приезжает с сервера
    assert sp["by_model"][DS]["usd"] == pytest.approx(2.0, rel=1e-6)
    assert sp["uncpriced"] == 0
    assert "text" in rep


def test_api_runs_report_without_price_says_so(fresh_db, _client, no_price):
    trace.start("вопрос", "web")
    llm_base.usage_note(DS, 2_000, 300)
    trace.finish("gemini", [])
    sp = _client.get("/api/runs/report?days=7").json()["spend"]
    assert sp["total_usd"] == 0.0 and sp["priced"] is False and sp["uncpriced"] == 1


# ============================================================ 6. отчёт словами (Telegram)
def _one_priced_turn(monkeypatch, usd_per_mtok: str = "0.14"):
    monkeypatch.setattr(llm_base, "cfg", _Node({"brain": _pricing(usd_per_mtok, usd_per_mtok)}), raising=False)
    trace.start("расскажи про кванты", "tg")
    llm_base.usage_note(DS, 1_000_000, 1_000_000)
    trace.finish("gemini", [])
    return trace.report_text(7)


def test_report_text_is_silent_about_money_without_price(fresh_db, no_price):
    """Цена не задана — про деньги ни слова: «$0.00» в Telegram выводить нечего."""
    trace.start("расскажи про кванты", "tg")
    llm_base.usage_note(DS, 1_000_000, 1_000_000)
    trace.finish("gemini", [])
    txt = trace.report_text(7)
    assert "обращений" in txt
    assert "$" not in txt and "0.00" not in txt and "расход" not in txt.lower()


def test_report_text_mentions_spend_when_priced(fresh_db, monkeypatch):
    txt = _one_priced_turn(monkeypatch)
    assert "обращений" in txt
    assert "$" in txt and "0,28" in txt or "0.28" in txt


def test_report_text_ignores_turns_without_tokens(fresh_db, monkeypatch):
    """Цена есть, но ход отвечен правилами — денег не было, молчим."""
    monkeypatch.setattr(llm_base, "cfg", _Node({"brain": _pricing("0.14", "0.14")}), raising=False)
    trace.start("потратил 700 на такси", "tg")
    trace.finish("rules", ["add_expense"])
    txt = trace.report_text(7)
    assert "обращений" in txt
    assert "$" not in txt
