"""Батч 5: голос/фото/проактив + живой чаттинг. TDD-красные тесты."""
import asyncio
import inspect
import os

os.environ.setdefault("JARVIS_TEST", "1")


def _fresh_db_fixture(tmp_path, monkeypatch):
    from core import db
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    _fresh_db_fixture(tmp_path, monkeypatch)
    yield


def test_voice_pending_has_ttl():
    """_VOICE_PENDING ждёт подтверждения ограниченно (TTL), а не вечно."""
    from core.telegram import bot
    assert hasattr(bot, "VOICE_TTL"), "нет TTL для голосовых (VOICE_TTL)"
    assert int(bot.VOICE_TTL) >= 60, "TTL слишком маленький"
    assert hasattr(bot, "_pending_set") and hasattr(bot, "_pending_pop"), "нет helpers _pending_set/_pending_pop"
    # helpers учитывают TTL
    bot._VOICE_PENDING.clear()
    bot._pending_set(1, "первая фраза")
    assert bot._pending_pop(1) == "первая фраза"
    bot._pending_set(1, "первая фраза")
    # протухшее — отдаёт None (подтверждать нечего)
    import time
    old = time.time() - int(bot.VOICE_TTL) - 10
    # backdate внутренней метки
    v = bot._VOICE_PENDING.get(1)
    if isinstance(v, tuple):
        bot._VOICE_PENDING[1] = (v[0], old)
    else:
        pytest.fail("pending без метки времени — TTL не работает")
    assert bot._pending_pop(1) is None, "протухшая расшифровка всё ещё подтверждается"


def test_second_voice_does_not_silently_overwrite():
    """Второе голосовое не затирает молча первое: либо предупреждение, либо TTL-аргумент в коде."""
    from core.telegram import bot
    src = inspect.getsource(bot.voice_msg)
    has_warn = ("предыдущ" in src.lower() or "замен" in src.lower())
    has_ttl = ("VOICE_TTL" in src or "_pending_set" in src or "_pending_get" in src or "TTL" in src)
    assert has_warn, "второе неуверенное голосовое молча затирает первое (нет предупреждения)"
    assert has_ttl, "нет TTL/учёта протухания pending в voice_msg"


def test_receipt_photo_writes_expense_immediately(monkeypatch):
    """Чек — сразу трата + 'если не так — отмени', без лишних подтверждений."""
    from core.telegram import bot
    from core.services import finance
    from core.brain import llm

    async def fake_photo_bytes(m, as_document=False):
        return b"fakeimagebytes"

    async def fake_describe(b64, q, private=False, short=False):
        return '{"total": 500, "store": "Пятерочка", "category": "Продукты", "items": ["хлеб"]}'

    monkeypatch.setattr(bot, "_photo_bytes", fake_photo_bytes)
    monkeypatch.setattr(llm, "describe_image", fake_describe)

    seen = {}

    def fake_add(total, kind, cat, note, *a, **k):
        seen["total"] = total
        seen["kind"] = kind
        from types import SimpleNamespace
        return SimpleNamespace(amount=total, category=cat or "Продукты")

    monkeypatch.setattr(finance, "add_transaction", fake_add)

    sent = {}

    class FakeBot:
        async def send_chat_action(self, *a, **k):
            return None

    class FakeMsg:
        caption = "чек из магазина"
        photo = [object()]
        document = None
        bot = FakeBot()

        async def answer(self, text, parse_mode=None, reply_markup=None):
            sent["text"] = text

    # подпись про чек -> ветка чека (receipt_hint) либо без подписи; без подписи тоже чек
    m = FakeMsg()
    m.caption = ""
    asyncio.run(bot.photo_msg(m))
    assert seen.get("total") == 500, f"чек не записан сразу тратой: {seen}"
    assert seen.get("kind") == "expense"
    t = sent.get("text", "")
    assert "отмени" in t.lower(), f"нет 'если не так — отмени': {t[:200]}"


def test_proactive_quiet_hours_silent(monkeypatch):
    """Проактив ночью молчит (тихие часы), даже если повод есть."""
    from datetime import datetime, timedelta
    from core.services import proactive, tasks

    monkeypatch.setattr(proactive, "vibe_enabled", lambda: False)

    class N:
        quiet_from = 23
        quiet_to = 8
        proactive_enabled = True
        proactive_per_day = 5

    from core import config
    monkeypatch.setattr(config.cfg, "notifications", N(), raising=False)

    t = tasks.add_task("Разобрать балкон батч5", None, source="test")
    from core import db as _db
    with _db.session() as s:
        row = s.get(_db.Task, t.id)
        row.created_at = datetime.now() - timedelta(days=8)
        s.add(row)
        s.commit()
    assert [x for x in proactive.candidates() if x["key"].startswith("stale:")]
    night = datetime.now().replace(hour=3, minute=0, second=0, microsecond=0)
    res = asyncio.run(proactive.tick(now=night, quiet=False))
    assert res is None, f"ночью проактив должен молчать, а отдал: {res}"
    # днём — отдаёт
    day = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    res2 = asyncio.run(proactive.tick(now=day, quiet=False))
    assert res2 is not None, "днём проактив должен отдать повод"


def test_proactive_limit_and_mute(monkeypatch):
    """Лимит/день и mute глушат проактив."""
    import asyncio
    from datetime import datetime, timedelta
    from core.services import proactive, tasks

    monkeypatch.setattr(proactive, "vibe_enabled", lambda: False)

    class N:
        quiet_from = 23
        quiet_to = 8
        proactive_enabled = True
        proactive_per_day = 5

    from core import config
    monkeypatch.setattr(config.cfg, "notifications", N(), raising=False)
    day = datetime.now().replace(hour=12, minute=0)
    t = tasks.add_task("Дело для лимита батч5", None, source="test")
    from core import db as _db
    with _db.session() as s:
        row = s.get(_db.Task, t.id)
        row.created_at = datetime.now() - timedelta(days=8)
        s.add(row)
        s.commit()
    monkeypatch.setattr(proactive, "per_day", lambda: 0)
    assert asyncio.run(proactive.tick(now=day)) is None, "лимит 0 — должен молчать"
    monkeypatch.setattr(proactive, "per_day", lambda: 5)
    assert proactive.act("mute", t.id, "stale").startswith("Понял")
    assert all(not x["key"].startswith("stale") for x in proactive.candidates())


def test_system_prompt_chat_style(monkeypatch):
    """Чаттинг: коротко без воды, списки только где надо, заголовок жирным, цифры в коде, без заглушек."""
    from core.brain import persona

    monkeypatch.setattr(persona, "STYLE", "swag")
    monkeypatch.setattr(persona, "HUMOR", 8)
    p = persona.system_prompt()
    low = p.lower()
    assert "без воды" in low, "нет запрета воды"
    assert "секунду" in low and "запускаю мозги" in low, "нет запрета заглушек"
    assert "**" in p and "заголовок" in low, "нет жирного заголовка"
    assert "`" in p, "цифры должны быть в коде (бэктики)"
    assert "только где надо" in low, "списки — только где надо (нет явной фразы)"

    monkeypatch.setattr(persona, "STYLE", "neutral")
    monkeypatch.setattr(persona, "HUMOR", 2)
    pn = persona.system_prompt().lower()
    assert "без воды" in pn, "neutral: нет запрета воды"
    assert "секунду" in pn, "neutral: нет запрета заглушек"
    assert "только где надо" in pn, "neutral: списки — только где надо"

    # буквальные маркеры старых тестов — не ломать
    monkeypatch.setattr(persona, "STYLE", "swag")
    monkeypatch.setattr(persona, "HUMOR", 8)
    full = persona.system_prompt()
    for m in ["ХАРАКТЕР.", "БЕЗОПАСНОСТЬ.", "ОТКАЗЫ.", "ГРАДАЦИЯ", "ЗАПРЕЩЕНО", "ШУТКИ ПО ЗАПРОСУ", "это мой принцип"]:
        assert m in full, f"сломан старый маркер: {m}"
