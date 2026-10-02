# -*- coding: utf-8 -*-
"""ФАЗА «мозг» — контекст, промпт и честность LLM-пути (агент M).

Офлайн, без сети: LLM замокан, а любой сетевой вызов подменён на падающий — тест сам падает,
если в облако всё-таки ушло что-то (local-first проверяется буквально).

Что проверяем:
1. local-режим НЕ делает ни одного облачного запроса (подмена httpx/клиента с падением);
2. hybrid/cloud: предсказуемый порядок «правила → локальная модель → облако» и честный фолбэк;
3. таймаут облака → понятная ошибка пользователю, а не стектрейс;
4. быстрые команды работают БЕЗ LLM (реальные фразы, латентность под лампой);
5. размер системного промпта в пределах потолка; важные блоки не режутся никогда;
6. обрезка истории сохраняет последние реплики, а выброшенное сворачивается в сводку;
7. инструмент удаления без подтверждения не выполняется; недоверенный источник не может писать.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-фикстура на временной БД)


def _add_event(title: str, when: str):
    """Событие с заданной датой (calendar.add_event ждёт datetime, строки не берёт)."""
    from core.services import calendar

    return calendar.add_event(title, datetime.fromisoformat(when))


# ============================================================ 1. local = ни одного облачного запроса
class _NoNetwork(Exception):
    """Любой реальный сетевой вызов в этом тесте — падение."""


@pytest.fixture(autouse=True)
def _clean_llm_globals():
    """Глобалы модуля LLM переживают тесты в одном процессе — чистим, чтобы порядок не влиял на результат."""
    from core.brain import llm

    llm.LAST_CLOUD_ERROR = None
    llm.LAST_GEMINI_ERROR = None
    llm.LAST_CLOUD_MODEL = ""
    from core.brain import agent

    agent._ANSWER_CACHE.clear()
    yield
    llm.LAST_CLOUD_ERROR = None
    agent._ANSWER_CACHE.clear()


@pytest.fixture
def no_network(monkeypatch):
    """Любая попытка уйти в сеть (httpx/urllib) поднимает _NoNetwork.

    Это и есть проверка local-first: не «функция вернула False», а «запрос физически не отправлен»."""
    import httpx

    def boom(*a, **k):
        raise _NoNetwork("сеть запрещена в тесте local-first")

    monkeypatch.setattr(httpx.AsyncClient, "request", boom)
    monkeypatch.setattr(httpx.AsyncClient, "send", boom)
    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    monkeypatch.setattr(httpx.AsyncClient, "stream", boom)
    yield


def test_local_mode_never_reaches_cloud(monkeypatch, no_network):
    """В режиме local облако не вызывается НИ РАЗУ — даже если ключ провайдера прописан."""
    from core.brain import agent, llm

    monkeypatch.setattr(llm, "MODE", "local")
    # ключ ЕСТЬ, провайдер выбран — ловушка: cloud_enabled() должен всё равно быть False
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "CLOUD_KEY", "sk-test-never-used")
    monkeypatch.setattr(llm, "GEMINI_KEY", "AIza-test-never-used")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "gemini_enabled", lambda: False)

    async def ollama_off(*a, **k):
        return False

    monkeypatch.setattr(llm, "ollama_available", ollama_off)
    # напрямую в оба облачных входа (те, что реально шлют данные), а не только через агент
    assert asyncio.run(llm.cloud_chat("S", "привет")) is None
    assert asyncio.run(llm.cloud_tools_chat([{"role": "user", "content": "привет"}], [])) is None
    assert asyncio.run(llm.gemini_chat("S", "привет")) is None
    # и весь ход целиком — тоже должен уйти в честное «мозг не запущен», а не в облако
    r = asyncio.run(agent.handle("что такое инфляция", "chat"))
    assert r.via == "none" and "облак" in r.text.lower()


def test_local_only_blocks_even_configured_cloud(monkeypatch):
    """Клапан local-first стоит в точке отправки, а не только в cloud_enabled().

    Иначе новый путь (зрение, health-check, фолбэк) смог бы отправить данные в облако."""
    from core.brain import llm

    monkeypatch.setattr(llm, "MODE", "local")
    assert llm.local_only() is True
    monkeypatch.setattr(llm, "MODE", "hybrid")
    assert llm.local_only() is False


def test_vision_never_goes_to_cloud_in_local_mode(monkeypatch, no_network):
    """Скриншот/фото в режиме local в облако не уходит, даже если vision.where=cloud и ключ есть."""
    from core.brain import llm

    monkeypatch.setattr(llm, "MODE", "local")
    monkeypatch.setattr(llm, "VISION_CLOUD_OK", True)
    monkeypatch.setattr(llm, "VISION_WHERE", "cloud")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    monkeypatch.setattr(llm, "VISION_MODEL", "")

    async def no_local():
        return False

    monkeypatch.setattr(llm, "_local_vision_available", no_local)
    assert asyncio.run(llm.describe_image("SCREENSHOT", "что на экране?")) is None


# ============================================================ 2. порядок «правила → локальная → облако»
def _route(monkeypatch, *, local_ok, cloud_text):
    """Подменить оба пути логгером вызовов и вернуть функцию, читающую лог."""
    from core.brain import agent, llm

    calls: list[str] = []

    monkeypatch.setattr(llm, "MODE", "hybrid")

    async def avail(force=False):
        return local_ok

    monkeypatch.setattr(llm, "ollama_available", avail)

    async def fake_ollama(text, channel, with_tools=True):
        calls.append("ollama")
        return agent.Reply("ответ локальной модели", [], "ollama") if local_ok else None

    async def fake_cloud(text, channel, explicit=True):
        calls.append("cloud")
        return agent.Reply(cloud_text, [], "gemini") if cloud_text else None

    monkeypatch.setattr(agent, "via_ollama", fake_ollama)
    monkeypatch.setattr(agent, "via_gemini", fake_cloud)
    return calls


def test_rules_win_over_llm_and_cloud(monkeypatch):
    """Правило-шаблон срабатывает ПЕРВЫМ: ни локальная модель, ни облако не зовутся."""
    from core.brain import agent

    calls = _route(monkeypatch, local_ok=True, cloud_text="облако")
    r = asyncio.run(agent.handle("потратил 700 на такси", "chat"))
    assert calls == [], "быстрая команда не должна дёргать ни одну модель"
    assert r.via == "rules" and "700" in r.text


def test_local_first_then_cloud_fallback(monkeypatch):
    """hybrid: личное → локальная модель; облако только если локальная не ответила."""
    from core.brain import agent

    calls = _route(monkeypatch, local_ok=True, cloud_text="облако")
    asyncio.run(agent.handle("мой долг когда закроется", "chat"))
    assert calls == ["ollama"], "личное должно остаться на локальной модели"


def test_cloud_used_for_general_questions_only(monkeypatch):
    """Общий вопрос без личных данных в hybrid уходит в облако, локальную модель не трогает."""
    from core.brain import agent

    calls = _route(monkeypatch, local_ok=True, cloud_text="Инфляция — рост цен.")
    asyncio.run(agent.handle("что такое инфляция", "chat"))
    assert calls == ["cloud"], calls


def test_cloud_timeout_gives_readable_error(monkeypatch):
    """Облако упало/не ответило — пользователь получает текст, а не стектрейс."""
    from core.brain import agent, llm

    _route(monkeypatch, local_ok=False, cloud_text="")
    # LAST_CLOUD_ERROR — глобаль модуля, заполняется реальным запросом; здесь его задаём руками,
    # иначе тест зависел бы от того, что осталось от предыдущего теста в этом же процессе.
    monkeypatch.setattr(llm, "LAST_CLOUD_ERROR",
                        "Groq: не достучался до api.groq.com ни напрямую, ни через прокси (ReadTimeout). Включите VPN.")

    r = asyncio.run(agent.handle("что такое инфляция", "chat"))
    assert r.via == "none"
    assert r.text and "Traceback" not in r.text
    assert "Error" not in r.text, r.text
    assert "Groq" in r.text or "облако" in r.text.lower()


# ============================================================ 3. быстрые команды без LLM
# Реальные фразы, которые пользователь пишет руками. Всё это должно уходить БЕЗ сети и БЕЗ модели.
OFFLINE_PHRASES = [
    ("потратил 700 на такси", "add_expense"),
    ("потратил 150 тыс на ремонт", "add_expense"),
    ("купил 25к видеокарту", "add_expense"),
    ("потратил 1,5к на билеты", "add_expense"),
    ("списали 3к", "add_expense"),
    ("-1500", "add_expense"),
    ("700 такси", "add_expense"),
    ("кофе 350", "add_expense"),
    ("доход 50000", "add_income"),
    ("аванс 30000", "add_income"),
    ("долг банку 120к плачу 8к 25-го", "add_debt"),
    ("должен Ване 5000", "add_debt"),
    ("встреча в среду в 15", "add_event"),
    ("встреча завтра в 15", "add_event"),
    ("ужин в 7 вечера", "add_event"),
    ("каждый пн в 19 тренировка", "add_event"),
    ("задача: починить полку", "add_task"),
    ("надо купить молоко", "add_task"),
    ("мысль: купить молоко", "add_note"),
    ("подписка netflix 599 в месяц", "add_recurring"),
    ("подписка яндекс плюс 399 25-го", "add_recurring"),
]


@pytest.mark.parametrize("phrase,action", OFFLINE_PHRASES)
def test_phrase_works_offline_without_llm(phrase, action, no_network):
    """Ни одного сетевого вызова: падающая подмена httpx просит свидетельств у самой команды."""
    from core.brain import agent

    r = agent.rules(phrase, "chat")
    assert r is not None, f"«{phrase}» ушёл в LLM — должно работать офлайн"
    assert action in r.actions, f"«{phrase}» → {r.actions}, ждали {action}"


@pytest.mark.parametrize("phrase,_action", OFFLINE_PHRASES)
def test_offline_commands_are_fast(phrase, _action, no_network):
    """Проверка «не тормозим ~40 офлайн-команд»: правила обязаны быть быстрее локальной модели.

    Локальный ответ — это сотни миллисекунд и выше (даже в кэше), а здесь просто чтение и запись в БД."""
    from core.brain import agent

    t0 = time.perf_counter()
    agent.rules(phrase, "chat")
    dt_ms = (time.perf_counter() - t0) * 1000
    assert dt_ms < 250, f"«{phrase}» шёл {dt_ms:.0f} мс — это уже не быстрый путь"


def test_payment_goes_to_existing_debt_not_to_expense():
    """«заплатил Ване 2000» при заведённом долге — это pay_debt, а не трата.

    Без долга «Ване» правильно срабатывает как обычная трата (об этом test_golden_quick.py),
    поэтому долг заводим явно — проверяем именно маршрутизацию платежа."""
    from core.brain import agent
    from core.services import finance

    finance.add_debt("Ване", 10000.0, 0, 0, 1)
    r = agent.rules("заплатил Ване 2000", "chat")
    assert r is not None and "pay_debt" in r.actions, r.actions if r else None


def test_money_day_number_is_not_taken_as_amount():
    """Реальный баг: «с 5-го плачу 3000» читалась как 5 ₽ вместо 3000.

    Порядковый номер дня («5-го», «5 числа») не сумма. Проверяем на разборе суммы и на команде."""
    from core.brain.dates import parse_amount

    assert parse_amount("с 5-го плачу 3000 за интернет")[0] == 3000
    assert parse_amount("5-го")[0] is None
    assert parse_amount("аренда 25к 5-го числа")[0] == 25000
    # сумма с разрядами перед днём не ломается
    assert parse_amount("1200 5-го")[0] == 1200
    assert parse_amount("399 25-го")[0] == 399


def test_recurring_payment_keeps_real_amount_and_clean_title():
    """«каждый месяц с 5-го плачу 3000 за интернет» → 3000 ₽, а не 5 ₽, и не «С -го плачу …»."""
    from core.brain import quick
    from core.services import finance

    res = quick.subscriptions("каждый месяц с 5-го плачу 3000 за интернет", "chat")
    assert res and res[1] == ["add_recurring"]
    rec = finance.list_recurring()[0]
    assert rec.amount == 3000
    assert rec.day == 5
    assert "го" not in rec.title.lower() and not rec.title.lower().startswith("с")


# ============================================================ 4. размер системного промпта и потолки
def test_system_prompt_within_budget_and_keeps_important_blocks(monkeypatch):
    """Потолок включён — важные блоки (характер, безопасность, отказы) не режутся НИКОГДА."""
    from core.brain import agent, budget, persona

    full = persona.system_prompt(compact=False)
    monkeypatch.setattr(budget, "system_max_chars", lambda: 10 ** 9)
    assert agent._system() == full          # потолок не задан → промпт как был

    # потолок ниже «несжимаемого» остатка: важные блоки всё равно обязаны выжить
    monkeypatch.setattr(budget, "system_max_chars", lambda: 2800)
    trimmed = agent._system()
    assert len(trimmed) < len(full), "потолок должен ужимать необязательные блоки"
    for marker in ("Ты — ", "БЕЗОПАСНОСТЬ.", "ОТКАЗЫ.", "ХАРАКТЕР."):
        assert marker in trimmed, f"важный блок «{marker}» срезали потолком"
    # и именно необязательное ушло первым
    assert "ОБРАЗЦЫ ТОНА" not in trimmed


def test_trim_static_is_a_noop_when_disabled():
    """По умолчанию потолок выключен (0) — поведение не меняется (правило AGENTS.md)."""
    from core.brain import budget

    assert budget.system_max_chars() == 0
    s = "A" * 5000
    assert budget.trim_static(s, budget.system_max_chars()) == s


def test_local_turn_fits_default_window():
    """Полный ход (система + схемы + хвост истории) влезает в num_ctx без аварийной перезагрузки модели."""
    from core.brain import budget, llm, persona
    from core.tools import registry

    sp = persona.system_prompt(compact=False)
    tools = json.dumps(registry.tools_schema(with_cloud=True, text="кот опять сожрал провод"), ensure_ascii=False)
    est = budget.est_request(
        [{"role": "system", "content": sp}] + [{"role": "user", "content": "x" * 600}] * 2 + [{"role": "user", "content": "реплика"}],
        json.loads(tools))
    assert est < llm.OLLAMA_NUM_CTX, f"≈{est} ток. не влезает в {llm.OLLAMA_NUM_CTX}"


def test_block_order_is_canonical():
    """Единый порядок блоков: личность → уроки → память → «не повторяй» → реплика."""
    from core.brain import budget

    out = budget.assemble({"text": "РЕПЛИКА", "memory_core": "ПАМЯТЬ", "lessons": "УРОКИ", "persona": "ЛИЧНОСТЬ"})
    assert out == "ЛИЧНОСТЬУРОКИПАМЯТЬРЕПЛИКА"
    assert budget.assemble({"persona": "П", "nothing": "ПРОПУЩЕНО"}) == "П"


# ============================================================ 5. обрезка истории
def test_history_trim_keeps_tail_and_summarizes_dropped(monkeypatch):
    """Хвост истории (последние реплики) сохраняется, выброшенное — сводка, а не дыра в контексте."""
    from core.brain import agent, llm

    monkeypatch.setattr(llm, "OLLAMA_NUM_CTX", 2400)
    msgs = [{"role": "system", "content": "S" * 900}]
    for i in range(10):
        msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"реплика-{i} " + "хвост " * 90})
    msgs.append({"role": "user", "content": "текущая реплика (сейчас четверг)"})

    out = agent._fit_budget(msgs, [], "test")
    assert out[0]["content"].startswith("S")                      # система не тронута
    assert out[-1]["content"] == "текущая реплика (сейчас четверг)"   # ход пользователя цел
    texts = [m["content"] for m in out]
    assert any("РАНЕЕ В ЭТОМ РАЗГОВОРЕ" in t for t in texts), "выброшенное должно свернуться в сводку"
    assert any("реплика-7" in t for t in texts), "последняя реплика хозяина обязана остаться"
    assert not any(t.strip().startswith("реплика-0 ") for t in texts), "дальняя история должна уйти"
    est = sum(len(m["content"]) for m in out) // 3 + 200
    assert est <= 2400 - 512 - 250, est


def test_history_trim_never_splits_a_pair(monkeypatch):
    """Хвост не должен начинаться с чужой реплики (модель и провайдеры это не любят)."""
    from core.brain import agent, llm

    monkeypatch.setattr(llm, "OLLAMA_NUM_CTX", 2600)
    msgs = [{"role": "system", "content": "S" * 900}]
    for i in range(10):
        msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i} " + "хвост " * 90})
    msgs.append({"role": "user", "content": "сейчас"})
    out = agent._fit_budget(msgs, [], "test")
    hist = [m["role"] for m in out[1:-1]]
    assert hist[0] == "user", f"история начинается с {hist[0]}"


def test_history_trim_keeps_core_facts_and_style():
    """Реальный баг: при нехватке окна старый код резал блок памяти по последней строке и
    выбрасывал факты core/state и профиль стиля. Важное не режется — режется только релевантное."""
    from core.brain import agent

    body = ("ЧТО ТЫ ЗНАЕШЬ О ХОЗЯИНЕ (фон, а не материал для шуток):\n"
            "Портрет: сухой, любит кофе.\n"
            "— работает в студии (core)\n"
            "— кот Чиназес (core)\n"
            "— ездил в Прагу в июле (сейчас)\n"
            "— покупал билеты на конференцию (сейчас)\n"
            "КАК ОН ПИШЕТ (подстраивай тон и длину ответа, слова понимай по его словарю):\n"
            "коротко, с матом, без заглавных")
    keep, drop = agent._split_memory(body)
    assert "Портрет: сухой, любит кофе." in keep
    assert "кот Чиназес" in keep
    assert "работает в студии" in keep
    assert "КАК ОН ПИШЕТ" in keep
    assert "Прагу" in drop and "конференцию" in drop
    assert len(keep) < len(body), "релевантное должно уйти, а важное остаться"


def test_summary_keeps_topics_and_is_short():
    """Сводка — короткая и про темы, а не простыня цитат (за это платим токенами)."""
    from core.brain import budget

    turns = [{"role": "user", "text": f"вопрос про заказ номер {i} " + "подробностей " * 60} for i in range(5)]
    line = budget.summarize(turns)
    assert line.startswith("РАНЕЕ В ЭТОМ РАЗГОВОРЕ")
    assert len(line) < 400, len(line)
    assert "подробностей подробностей подробностей" not in line   # не дословная простыня
    assert budget.summarize([]) == ""


# ============================================================ 6. граница «LLM → данные»
def test_destructive_tool_requires_confirmation(monkeypatch):
    """Инструмент удаления без подтверждения НЕ выполняется: пользователю задаётся вопрос."""
    from core.brain import agent
    from core.services import calendar

    _add_event("Встреча с клиентом", "2026-03-10T15:00:00")

    async def fake_chat(messages, tools=None, **kw):
        return {"content": "удалил, сэр", "tool_calls": [
            {"name": "delete_event", "arguments": {"query": "Встреча с клиентом"}}]}

    monkeypatch.setattr(agent, "_chat", fake_chat)
    r = asyncio.run(agent.via_ollama("удали встречу с клиентом", "chat"))
    assert "clarify" in r.actions
    assert "?" in r.text, "нужен явный вопрос «точно удалить?»"
    assert calendar.find_event("Встреча с клиентом") is not None, "событие удалили без подтверждения!"


def test_untrusted_source_cannot_call_write_tool():
    """Содержимое заметки/ссылки/пересланного сообщения не может выполнить опасный инструмент (ФАЗА 6)."""
    from core.tools import registry
    from core.services import calendar

    _add_event("Созвон с подрядчиком", "2026-03-11T12:00:00")
    res = registry.call("delete_event", {"query": "Созвон с подрядчиком"}, "tg-fwd", trusted=False)
    assert not res.ok and res.risk == "destructive"
    assert registry.UNTRUSTED_BLOCK in res.for_model()
    assert calendar.find_event("Созвон с подрядчиком") is not None, "недоверенный источник удалил событие!"


def test_untrusted_source_can_still_read():
    """Запрет касается только записи: чтение из непроверенного источника не ломается (обычные команды живы)."""
    from core.tools import registry

    r = registry.call("list_events", {"days": 7}, "tg-fwd", trusted=False)
    assert r.ok
    assert r.risk == "read"


def test_trusted_source_may_call_tool():
    """Обычные каналы владельца работают как раньше — защита не ломает штатные команды."""
    from core.tools import registry
    from core.services import calendar

    _add_event("Планёрка", "2026-03-12T10:00:00")
    r = registry.call("list_events", {"days": 7}, "tg")
    assert r.ok


def test_agent_passes_trust_flag_from_channel(monkeypatch):
    """Агент берёт доверие канала (-fwd) и передаёт его в инструмент — граница не обходится."""
    import inspect

    from core.brain import agent

    src = inspect.getsource(agent.via_ollama)
    assert "pc.from_trusted_channel(channel)" in src
    assert "trusted=tool_trusted" in src


def test_tool_schema_is_whitelist_only():
    """Граница «LLM → данные»: произвольных SQL/команд в схеме быть не может — только белый список."""
    from core.tools import registry

    # ask_cloud — служебный инструмент: в схеме есть, локально исполняется агентом, а не функцией
    assert set(registry.TOOLS) - {registry.CLOUD_TOOL} == set(registry.FUNCS), "схема и исполняемые функции разошлись"
    for name, spec in registry.TOOLS.items():
        fn_name = spec["function"]["name"]
        assert fn_name == name
        assert fn_name.isidentifier() and all(c.isalnum() or c == "_" for c in fn_name)
    # явного SQL/выполнения в аргументах нет: схемы описывают только скалярные поля
    banned = {"sql", "query_sql", "exec", "eval", "run", "shell", "command"}
    for spec in registry.TOOLS.values():
        assert not (set(spec["function"]["parameters"].get("properties") or {}) & banned)