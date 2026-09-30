"""Карточки-картинки: фирменный стиль, режим отправки (cards.mode), кэш по содержимому."""
import os

os.environ.setdefault("JARVIS_TEST", "1")


def test_should_send_modes(monkeypatch):
    from core.services import cards
    monkeypatch.setattr(cards, "IMAGES_MODE", "never")
    assert not cards.should_send("digest") and not cards.should_send("expense")
    monkeypatch.setattr(cards, "IMAGES_MODE", "important")
    assert cards.should_send("digest") and cards.should_send("report")    # важные
    assert cards.should_send("expense") and cards.should_send("task")     # короткие на траты/задачи
    monkeypatch.setattr(cards, "IMAGES_MODE", "always")
    assert cards.should_send("note")                                      # в «always» — вообще всё


def test_action_card_renders_brand_style(tmp_path, monkeypatch):
    from core.services import cards
    monkeypatch.setattr(cards, "DATA_DIR", tmp_path)
    p = cards.task_card("сдать отчёт", "10.09 15:00")
    assert p and p.exists() and p.stat().st_size > 1000
    # PNG с сигнатурой и в папке кэша
    assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert "card_cache" in str(p)


def test_action_card_cached(tmp_path, monkeypatch):
    """Одинаковую карточку не рисуем дважды: второй вызов отдаёт тот же файл без перезаписи."""
    from core.services import cards
    monkeypatch.setattr(cards, "DATA_DIR", tmp_path)
    p1 = cards.action_card("event", "встреча с Димой", "15:00")
    mtime = p1.stat().st_mtime_ns
    p2 = cards.action_card("event", "встреча с Димой", "15:00")
    assert p2 == p1 and p2.stat().st_mtime_ns == mtime


def test_expense_card_renders(tmp_path, monkeypatch):
    from core.services import cards
    from core import db
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    monkeypatch.setattr(cards, "DATA_DIR", tmp_path)

    class _Tx:
        kind, amount, category, account = "expense", 700.0, "Еда", "Основной"

    p = cards.expense_card(_Tx(), 12345.0)
    assert p and p.exists() and p.stat().st_size > 1000


def test_quick_templates_and_find_mapping():
    """Быстрые шаблоны Telegram: латиница/кириллица → правильные фразы (выключаются настройкой telegram.quick)."""
    from core.telegram import bot as tb
    assert tb._QUICK_MAP["exp"] == "потратил {x}" and tb._QUICK_MAP["расход"] == "потратил {x}"
    assert tb._QUICK_MAP["task"].startswith("задача:") and tb._QUICK_MAP["event"].startswith("встреча")
    assert tb._QUICK_CANON["exp"] == "расход"
    assert tb._quick_enabled() in (True, False)


def test_band_card_is_21_9(tmp_path, monkeypatch):
    """Короткие карточки — узкая полоса 21:9 (не «фулл-фотка»), в стиле утреннего дайджеста."""
    from core.services import cards
    from PIL import Image
    monkeypatch.setattr(cards, "DATA_DIR", tmp_path)
    p = cards.band_card("task", "сдать отчёт", "10.09 15:00",
                        [("дело", "отчёт", cards.INK), ("когда", "10.09", cards.INK_2)])
    assert p and p.exists()
    im = Image.open(p)
    assert im.size == (1260, 540)
    assert abs(im.size[0] / im.size[1] - 21 / 9) < 0.01


def test_for_result_picks_card(tmp_path, monkeypatch):
    """«Важный ответ» → одна карточка (та же логика для сайта и Telegram)."""
    from core.services import cards
    monkeypatch.setattr(cards, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cards, "IMAGES_MODE", "important")

    class Tx:
        kind, amount, category, account = "expense", 700.0, "Еда", "Основной"

    monkeypatch.setattr(cards.finance, "last_transaction", lambda: Tx())
    monkeypatch.setattr(cards.finance, "summary", lambda days=30: {"total_balance": 1000.0})
    monkeypatch.setattr(cards.finance, "budgets", lambda: [])
    p = cards.for_result(["add_expense"], "потратил 700 на еду")
    assert p and p.exists()
    # на простое действие карточку не рисуем
    assert cards.for_result(["add_note"], "просто мысль") is None
