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
