"""F6: retention support БЕЗ удаления — только date-индексы (v9). tmp DB only, live config.yaml не трогаем."""
from sqlalchemy import event, text
from sqlmodel import create_engine


def _tmp_engine(tmp_path, monkeypatch):
    from core import db
    eng = create_engine(f"sqlite:///{tmp_path / 'r.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    return eng


def test_v9_indexes_idempotent(tmp_path, monkeypatch):
    from core import db, migrations
    eng = _tmp_engine(tmp_path, monkeypatch)
    db.init_db()  # раз
    db.init_db()  # два — без ошибок
    with eng.connect() as c:
        have = {r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).all()}
    for name in ("ix_chatmessage_created_at", "ix_memory_created_at", "ix_actionlog_created_at"):
        assert name in have, f"нет {name}"
    # embedding: date-колонки нет — индекса и не должно быть
    with eng.connect() as c:
        cols = {r[1] for r in c.execute(text('PRAGMA table_info("embedding")')).all()}
    assert "created_at" not in cols
    # повторный apply — no-op по v9
    cur = migrations.current_version(eng)
    res = migrations.apply(eng, had_db=True)
    assert res["applied"] == [] and migrations.current_version(eng) == cur
