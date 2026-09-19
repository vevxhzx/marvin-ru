"""Экранное время: склейка пульсов, простой, сессии, отчёт, шаблоны чата, поводы для подколов."""
import os
from datetime import datetime, timedelta

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from core import db  # noqa: E402
from core.services import screen  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    monkeypatch.setattr(screen, "enabled", lambda: True)
    monkeypatch.setattr(screen, "idle_min", lambda: 5)
    monkeypatch.setattr(screen, "nudges_enabled", lambda: True)
    yield


def _day(t0: datetime, plan: list[tuple[int, str, str, int]]):
    """plan: (минут, app, title, idle_sec) — прогоняем пульсы по 20 с."""
    now = t0
    for minutes, app, title, idle in plan:
        for i in range(minutes * 3):
            now += timedelta(seconds=20)
            # простой в реальности растёт с нуля: idle=1 в плане означает «не трогал мышь весь этот кусок»
            screen.record(app, title, (i + 1) * 20 if idle else 0, now=now)
    return now


def test_classify():
    assert screen.classify("adobe premiere pro.exe", "проект.prproj") == ("Premiere Pro", "", "работа")
    assert screen.classify("chrome.exe", "Как монтировать - YouTube - Google Chrome") == ("YouTube", "Chrome", "медиа")
    assert screen.classify("chrome.exe", "Telegram Web - Google Chrome")[0] == "Telegram Web"
    assert screen.classify("chrome.exe", "Какой-то сайт - Google Chrome") == ("Какой-то сайт", "Chrome", "браузер")
    assert screen.classify("telegram.exe", "Telegram")[2] == "общение"
    assert screen.classify("cs2.exe", "Counter-Strike 2", {"cs2.exe"})[2] == "игра"


def test_slots_merge_and_summary():
    t0 = datetime(2026, 9, 17, 9, 40)
    _day(t0, [(60, "adobe premiere pro.exe", "ролик", 0), (30, "chrome.exe", "Обзор - YouTube - Google Chrome", 0),
              (15, "chrome.exe", "Обзор - YouTube - Google Chrome", 1),   # не трогал мышь 15 минут: первые 5 — ещё «смотрит», дальше «отошёл»
              (20, "telegram.exe", "Telegram", 0)])
    rows = screen.slots(t0)
    assert [(r.app, r.idle) for r in rows] == [("Premiere Pro", False), ("YouTube", False), ("Отошёл", True), ("Telegram", False)]
    d = screen.summary(t0)
    assert 107 <= d["active_min"] <= 112 and 14 <= d["idle_min"] <= 16   # простой отсчитывается с последнего движения мыши, а не с 5-й минуты
    assert d["apps"][0][0] == "Premiere Pro" and 58 <= d["apps"][0][1] <= 61
    assert d["cats"]["работа"] >= 58
    assert len(d["sessions"]) == 2      # ушёл на 10 минут → два подхода
    assert d["first"].hour == 9
    assert sum(d["hours"]) == d["active_min"]


def test_text_and_chat_rule():
    t0 = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    _day(t0, [(45, "adobe premiere pro.exe", "ролик", 0), (20, "chrome.exe", "Обзор - YouTube - Google Chrome", 0)])
    txt = screen.text()
    assert "За ПК сегодня" in txt and "Premiere Pro" in txt and "YouTube" in txt
    assert screen.chat_rule("сколько я сегодня сидел за компом") and "Premiere" in screen.chat_rule("сколько я сегодня сидел за компом")
    yt = screen.chat_rule("сколько ютуба сегодня")
    assert yt and "20 мин" in yt
    assert screen.chat_rule("сколько потратил на еду") is None
    assert screen.evening_line().startswith("🖥") and "Premiere" in screen.evening_line()


def test_disabled_says_how_to_enable(monkeypatch):
    monkeypatch.setattr(screen, "enabled", lambda: False)
    assert screen.record("chrome.exe", "x", 0) is None
    assert "выключено" in screen.text()
    assert screen.nudge_facts() == []


def test_nudges_media_streak_and_marathon():
    from core.services import tasks
    tasks.add_task("Сдать ролик Пятёрочке", datetime.now().replace(hour=23, minute=0))
    t0 = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    now = _day(t0, [(30, "adobe premiere pro.exe", "ролик", 0), (70, "chrome.exe", "Обзор - YouTube - Google Chrome", 0)])
    facts = screen.nudge_facts(now)
    kinds = {f["fact"]["kind"] for f in facts}
    assert "screen_media" in kinds
    media = next(f for f in facts if f["fact"]["kind"] == "screen_media")
    assert media["fact"]["minutes"] >= 60 and "Пятёрочке" in (media["fact"]["deadline_tasks"] or [""])[0]
    # 6 часов без перерыва
    now = _day(now, [(270, "adobe premiere pro.exe", "ролик", 0)])
    facts = screen.nudge_facts(now)
    assert any(f["fact"]["kind"] == "screen_marathon" for f in facts)


def test_cleanup_keeps_recent(monkeypatch):
    monkeypatch.setattr(screen, "keep_days", lambda: 7)
    old = datetime.now() - timedelta(days=10)
    with db.session() as s:
        s.add(db.ScreenSlot(start=old, end=old + timedelta(minutes=5), app="X", category="прочее")); s.commit()
    _day(datetime.now() - timedelta(minutes=10), [(3, "telegram.exe", "Telegram", 0)])
    assert screen.cleanup() == 1
    assert len(screen.slots()) == 1


def test_write_settings_creates_nested_section(tmp_path, monkeypatch):
    """Старый config.yaml без блока screen_time: включение с сайта должно создать voice.pc.screen_time.enabled, а не сломать yaml
    (0.9.17: write_settings умел только 3 уровня — ключ вставлялся с неверным отступом и конфиг переставал читаться)."""
    import shutil
    import yaml
    from core import config
    src = (config.ROOT / "config.example.yaml").read_text(encoding="utf-8")
    import re
    src = re.sub(r"\n    screen_time:.*?keep_days: 90[^\n]*\n", "\n", src, flags=re.S)
    assert "screen_time" not in src
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "config.example.yaml").write_text(src, encoding="utf-8")
    (tmp_path / "config.yaml").write_text(src, encoding="utf-8")
    assert config.write_settings({"voice.pc.screen_time.enabled": True, "voice.pc.screen_time.idle_min": 7}) == ["voice.pc.screen_time.enabled", "voice.pc.screen_time.idle_min"]
    d = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert d["voice"]["pc"]["screen_time"] == {"enabled": True, "idle_min": 7}
    assert d["server"]["port"] == 8765                       # соседние секции целы
    config.write_settings({"voice.pc.screen_time.enabled": False})
    d = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert d["voice"]["pc"]["screen_time"]["enabled"] is False
    assert (tmp_path / "config.yaml").read_text(encoding="utf-8").count("screen_time:") == 1
