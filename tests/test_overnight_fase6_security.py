"""ФАЗА 6 — Безопасность (аудит + минимальные правки). Офлайн, временная БД (fixture из test_core).

Проверяем:
1. скриншот/фото уходит в облако только при ЯВНОМ brain.vision.allow_cloud: true (по умолчанию — нет);
2. команды управления ПК не принимаются из пересланных сообщений (канал -fwd), но обычные каналы работают;
3. эндпоинт «что уйдёт в облако» — только чтение, обезличивает и не отправляет ничего;
4. отзыв/ротация ключа доступа для чужих устройств (уже есть — фиксируем регрессом).
"""
import asyncio
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-фикстура)


class _Resp:
    status_code = 200

    def __init__(self, text: str):
        self._text = text

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


# ---------------- 1. скриншот в облако только по явному разрешению ----------------
def test_screen_never_goes_to_cloud_without_explicit_optin(monkeypatch):
    from core.brain import llm
    monkeypatch.setattr(llm, "VISION_CLOUD_OK", False)     # allow_cloud не задан / false
    monkeypatch.setattr(llm, "VISION_WHERE", "cloud")      # даже при «всегда облако»
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)

    async def no_local():
        return False

    called = []

    async def fake_post(*a, **k):
        called.append(1)
        return _Resp("увидел пароль")

    monkeypatch.setattr(llm, "_local_vision_available", no_local)
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    ans = asyncio.run(llm.describe_image("SCREEN", "что на экране?", private=False))
    assert ans is None, "без allow_cloud скриншот не должен уходить в облако"
    assert not called, "в облако не должно быть ни одного запроса"


def test_screen_goes_to_cloud_only_when_explicitly_allowed(monkeypatch):
    from core.brain import llm
    monkeypatch.setattr(llm, "VISION_CLOUD_OK", True)      # пользователь явно разрешил
    monkeypatch.setattr(llm, "VISION_WHERE", "cloud")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)

    async def fake_post(*a, **k):
        return _Resp("на экране редактор")

    monkeypatch.setattr(llm, "_local_vision_available", lambda: asyncio.sleep(0, result=False))
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    ans = asyncio.run(llm.describe_image("SCREEN", "что на экране?", private=False))
    assert ans == "на экране редактор"


def test_vision_allow_cloud_setting_default_is_documented_false():
    """Дефолт в коде совпадает с описанием настройки (core/config.py): allow_cloud без значения = False."""
    from core import config
    assert "brain.vision.allow_cloud" in config.EDITABLE
    # в исходнике llm.py дефолт getattr(..., "allow_cloud", False), а не True
    import inspect
    from core.brain import llm
    src = inspect.getsource(llm)
    assert 'getattr(_vc, "allow_cloud", False)' in src
    assert 'getattr(_vision_cfg, "allow_cloud", False)' in src


def test_screen_endpoint_never_uses_cloud_fallback_in_auto(monkeypatch):
    """Скриншот с ПК (/api/vision/ask) в режиме auto НЕ уходит в облако «запасным путём» — только local."""
    from core.brain import llm
    monkeypatch.setattr(llm, "VISION_CLOUD_OK", True)
    monkeypatch.setattr(llm, "VISION_WHERE", "auto")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)

    async def no_local():
        return False

    called = []

    async def fake_post(*a, **k):
        called.append(1)
        return _Resp("x")

    monkeypatch.setattr(llm, "_local_vision_available", no_local)
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    r = _client().post("/api/vision/ask", json={"image_b64": "AAAA", "question": "что на экране?"})
    assert r.status_code == 200 and not called, "в auto экран не должен уходить в облако без явного where=cloud"


def test_screen_endpoint_uses_cloud_when_explicitly_selected(monkeypatch):
    from core.brain import llm
    monkeypatch.setattr(llm, "VISION_CLOUD_OK", True)
    monkeypatch.setattr(llm, "VISION_WHERE", "cloud")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)

    async def fake_post(*a, **k):
        return _Resp("на экране браузер")

    monkeypatch.setattr(llm, "_local_vision_available", lambda: asyncio.sleep(0, result=False))
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    d = _client().post("/api/vision/ask", json={"image_b64": "AAAA", "question": "что на экране?"}).json()
    assert d["text"] == "на экране браузер"


# ---------------- 2. команды ПК — только из каналов владельца ----------------
def test_forwarded_text_cannot_control_pc(monkeypatch):
    from core.services import pc
    from core.brain import agent

    assert pc.from_trusted_channel("tg") and pc.from_trusted_channel("tg-voice")
    assert pc.from_trusted_channel("voice") and pc.from_trusted_channel("web")
    assert not pc.from_trusted_channel("tg-fwd") and not pc.from_trusted_channel("tg-voice-fwd")

    sent = []
    monkeypatch.setattr(pc, "dispatch", lambda cmd, ch: sent.append((cmd.action, ch)) or "ok")
    monkeypatch.setattr(pc, "alive", lambda: True)

    r = asyncio.run(agent.handle("открой ютуб", "tg-fwd"))
    assert "пересланных" in r.text and not sent, "пересланный текст не должен управлять ПК"

    r = asyncio.run(agent.handle("открой ютуб", "tg"))
    assert sent and sent[0][0] == "open_url", "обычный канал владельца продолжает работать"


def test_power_confirm_from_forwarded_channel_is_blocked(monkeypatch):
    from core.services import pc
    from core.brain import agent

    monkeypatch.setattr(pc, "alive", lambda: True)
    r = asyncio.run(agent.handle("выключи компьютер", "tg-fwd"))
    assert "пересланных" in r.text, "подтверждение выключения не должно даже предлагаться из -fwd"


# ---------------- 3. «что уйдёт в облако» — только чтение ----------------
def _client(remote: bool = False):
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, client=("192.168.1.50", 5555) if remote else ("127.0.0.1", 5555))


def test_cloud_preview_is_read_only_and_anonymizes(monkeypatch):
    from core.config import cfg
    monkeypatch.setattr(cfg.brain.gemini, "anonymize", True, raising=False)
    c = _client()
    r = c.post("/api/cloud/preview", json={"text": "пароль от вайфая qwerty123 запомни"})
    assert r.status_code == 200
    d = r.json()
    assert d["anonymized"] is True and d["text"] != "пароль от вайфая qwerty123 запомни"
    assert "qwerty123" not in d["text"] and "[скрыто]" in d["text"]
    assert "отправлено" in d["note"].lower() or "не отправля" in d["note"].lower()


def test_cloud_preview_local_mode_never_sends(monkeypatch):
    from core.brain import llm
    c = _client()
    monkeypatch.setattr(llm, "MODE", "local")
    d = c.post("/api/cloud/preview", json={"text": "объясни теорему"}).json()
    assert d["will_send"] is False
    assert d["mode"] == "local"


# ---------------- 4. ротация ключа (уже есть) — фиксируем контракт ----------------
def test_phone_rotate_endpoint_is_local_only():
    """Отзыв/ротация ключа есть (/api/phone/rotate), но с чужого устройства недоступен.
    Реальную ротацию в тесте не вызываем — она перезаписала бы data/api_token."""
    from core.api import auth
    remote = _client(remote=True)
    assert remote.post("/api/phone/rotate", headers={"X-Auth-Token": auth.token()}).status_code == 403


# ---------------- 5. «личные инструменты в облаке» (brain.cloud.personal_tools, дефолт False) ----------------
def _cloud_mode(monkeypatch, *, personal: bool):
    """Режим «облако вместо ПК»: llm.MODE=cloud + рабочий провайдер. personal — флаг согласия."""
    from core.brain import agent, llm

    async def _down(*a, **k):
        return False

    monkeypatch.setattr(llm, "MODE", "cloud")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    monkeypatch.setattr(llm, "ollama_available", _down)
    monkeypatch.setattr(llm, "CLOUD_PERSONAL", personal)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    return llm, agent


def test_personal_tools_flag_defaults_to_false(monkeypatch):
    """Дефолт — личные данные облаку не отдаём (совпадает с описанием настройки в core/config.py)."""
    from core import config
    from core.brain import llm
    assert "brain.cloud.personal_tools" in config.EDITABLE
    assert config.EDITABLE["brain.cloud.personal_tools"][0] == "bool"
    import inspect
    assert 'getattr(_cloud_cfg, "personal_tools", False)' in inspect.getsource(llm)


def test_cloud_mode_without_consent_gets_no_personal_tools(monkeypatch):
    """cloud + personal_tools=False: облако получает только пишущие инструменты, личные — нет."""
    llm, agent = _cloud_mode(monkeypatch, personal=False)
    seen = {}

    async def fake_cloud_tools(messages, tools, temperature=0.2):
        seen["tools"] = tools
        return {"content": "Готово.", "tool_calls": []}

    monkeypatch.setattr(llm, "cloud_tools_chat", fake_cloud_tools)
    r = asyncio.run(agent.via_ollama("сколько я потратил за неделю?", "web"))
    assert r is not None
    names = [t["function"]["name"] for t in seen["tools"]]
    assert "add_expense" in names, "пишущие инструменты остаются доступны — поведение по умолчанию не ломаем"
    for p in ("search_notes", "add_note", "finance_summary", "today_briefing", "person_card", "list_debts"):
        assert p not in names, f"личный инструмент {p} не должен уходить в облако без согласия"


def test_cloud_mode_with_consent_keeps_personal_tools(monkeypatch):
    """cloud + personal_tools=True: старый режим как был — все инструменты на месте (обратная совместимость)."""
    llm, agent = _cloud_mode(monkeypatch, personal=True)
    seen = {}

    async def fake_cloud_tools(messages, tools, temperature=0.2):
        seen["tools"] = tools
        return {"content": "Готово.", "tool_calls": []}

    monkeypatch.setattr(llm, "cloud_tools_chat", fake_cloud_tools)
    asyncio.run(agent.via_ollama("что в моих заметках?", "web"))
    names = [t["function"]["name"] for t in seen["tools"]]
    assert "search_notes" in names and "finance_summary" in names


def test_cloud_mode_blocked_personal_call_is_not_executed(monkeypatch):
    """Облако без согласия вызвало личный инструмент — не выполняем, результат не уходит провайдеру."""
    from core.tools import registry
    llm, agent = _cloud_mode(monkeypatch, personal=False)
    calls = []

    seen_msgs = []

    async def fake_cloud_tools(messages, tools, temperature=0.2):
        seen_msgs.append(messages)
        if len(seen_msgs) == 1:
            return {"content": "", "tool_calls": [{"name": "today_briefing", "arguments": {}}]}
        return {"content": "Не смог посмотреть деньги, сэр.", "tool_calls": []}

    orig_call = registry.call

    def spy(name, args, channel="tg"):
        calls.append(name)
        return orig_call(name, args, channel)

    monkeypatch.setattr(registry, "call", spy)
    monkeypatch.setattr(llm, "cloud_tools_chat", fake_cloud_tools)
    # не вопрос про данные — иначе сработал бы локальный _forced_tool (он считает данные сам, это безопасно)
    r = asyncio.run(agent.via_ollama("ну привет", "web"))
    assert "today_briefing" not in calls, "личный инструмент не должен выполняться по запросу облака"
    # облако получает отказ, а не содержимое базы
    told = [m["content"] for m in seen_msgs[-1] if m.get("role") == "tool"]
    assert told and "недоступны" in told[-1].lower()
    assert r is not None and "Не получилось" not in r.text


def test_hybrid_and_local_modes_unaffected_by_flag(monkeypatch):
    """local/hybrid идут в Ollama — флаг на них не влияет (ничего не ломаем)."""
    from core.brain import agent, llm
    from core.tools import registry

    async def _down(*a, **k):
        return False

    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "CLOUD_PERSONAL", False)

    async def _up(*a, **k):
        return True

    monkeypatch.setattr(llm, "ollama_available", _up)
    got = {}

    async def fake_ollama(messages, tools=None, **kw):
        got["tools"] = tools
        return {"content": "ок", "tool_calls": []}

    monkeypatch.setattr(llm, "ollama_chat", fake_ollama)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    asyncio.run(agent.via_ollama("что в моих заметках?", "web"))
    names = [t["function"]["name"] for t in (got["tools"] or [])]
    assert "search_notes" in names, "на ПК личные инструменты остаются"


def test_cloud_preview_reports_personal_tools_flag(monkeypatch):
    """Превью «что уйдёт в облако» показывает состояние флага — владелец видит режим."""
    from core.brain import llm
    monkeypatch.setattr(llm, "MODE", "cloud")
    monkeypatch.setattr(llm, "CLOUD_PERSONAL", False)
    d = _client().post("/api/cloud/preview", json={"text": "сколько я потратил?"}).json()
    assert d["personal_tools"] is False and d["mode"] == "cloud"
    monkeypatch.setattr(llm, "CLOUD_PERSONAL", True)
    d = _client().post("/api/cloud/preview", json={"text": "сколько я потратил?"}).json()
    assert d["personal_tools"] is True


def test_without_personal_keeps_write_tools_only():
    """Чистая функция фильтра: убирает ровно PERSONAL_TOOLS, остальное не трогает."""
    from core.tools import registry
    tools = registry.tools_schema(with_cloud=False, text=None)
    assert tools, "схема инструментов не должна быть пустой"
    left = [t["function"]["name"] for t in registry.without_personal(tools)]
    assert not set(left) & set(registry.PERSONAL_TOOLS)
    assert "add_expense" in left and "add_task" in left
    assert len(left) == len(tools) - len([t for t in tools if t["function"]["name"] in registry.PERSONAL_TOOLS])
