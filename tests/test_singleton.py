"""Один экземпляр (I24): acquire → второй acquire отказывает → release → снова ок; stale-перезапись."""
import json


def _mod(monkeypatch, tmp_path):
    from core import singleton as s
    monkeypatch.setattr(s, "lock_path", lambda: tmp_path / ".db.lock")
    assert s._held is None
    return s


def test_acquire_twice_refuses_then_release(monkeypatch, tmp_path):
    s = _mod(monkeypatch, tmp_path)
    try:
        assert s.acquire() is None
        assert s.acquire() is not None  # второй — отказ, не зависаем
    finally:
        s.release()
    assert s._held is None
    # после release занимаем снова
    assert s.acquire() is None
    s.release()


def test_stale_lock_overwritten(monkeypatch, tmp_path):
    s = _mod(monkeypatch, tmp_path)
    dead = 99999999
    assert not s.pid_alive(dead)
    (tmp_path / ".db.lock").write_text(json.dumps({"pid": dead, "started_at": "2000-01-01T00:00:00"}),
                                       encoding="utf-8")
    try:
        assert s.acquire() is None  # мёртвый PID — перезаписали
        s._held.seek(0)  # файл под OS-блокировкой: читаем через тот же handle
        assert json.loads(s._held.read().decode("utf-8").lstrip("\x00 "))["pid"] != dead
    finally:
        s.release()


def test_live_pid_refuses(monkeypatch, tmp_path):
    s = _mod(monkeypatch, tmp_path)
    (tmp_path / ".db.lock").write_text(json.dumps({"pid": 123456, "started_at": "now"}),
                                       encoding="utf-8")
    monkeypatch.setattr(s, "pid_alive", lambda pid: True)  # чужой процесс жив
    assert s.acquire() is not None  # отказ, чужой файл не перезаписываем
    assert s._held is None
