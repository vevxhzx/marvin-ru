"""Уборка рабочего стола: план → «да» → перенос → «отмени уборку». Ничего не удаляется."""
import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("JARVIS_DB", ":memory:")


def _mk(root: Path, name: str, age_sec: int = 3600, body: bytes = b"x") -> Path:
    p = root / name
    p.write_bytes(body)
    t = time.time() - age_sec
    os.utime(p, (t, t))
    return p


def test_tidy_plan_apply_undo(tmp_path: Path):
    from core.pc import tidy
    desk, dl, data = tmp_path / "Desktop", tmp_path / "Downloads", tmp_path / "data"
    desk.mkdir(); dl.mkdir(); data.mkdir()
    _mk(desk, "договор.pdf"); _mk(desk, "Снимок экрана 2026-09-01.png"); _mk(desk, "лого.png"); _mk(desk, "ролик_v3.aep")
    _mk(desk, "Premiere.lnk"); (desk / "Проект X").mkdir(); _mk(desk / "Проект X", "внутри.txt")
    _mk(desk, "только_что.txt", age_sec=5)                   # свежий — не трогаем
    _mk(dl, "setup.exe"); _mk(dl, "архив.zip"); _mk(dl, "фильм.mkv.crdownload"); _mk(dl, "desktop.ini")
    plan = tidy.make_plan({"desktop": desk, "downloads": dl}, data)
    cats = {Path(m["src"]).name: m["cat"] for part in plan["parts"] for m in part["moves"]}
    assert cats == {"договор.pdf": "Документы", "Снимок экрана 2026-09-01.png": "Скриншоты", "лого.png": "Картинки",
                    "ролик_v3.aep": "Проекты", "setup.exe": "Установщики", "архив.zip": "Архивы"}
    d = plan["parts"][0]["skipped"]
    assert d["папки"] == 1 and d["ярлыки"] == 1 and d["свежие"] == 1
    txt = tidy.plan_text(plan)
    assert "Разобрано" in txt and "Документы (1)" in txt and "«да»" in txt and "не трогаю: папки (1), ярлыки (1)" in txt
    assert "4 файлов" in tidy.plan_speech(plan) and "Убираем?" in tidy.plan_speech(plan)
    # план сохранён, применяем
    assert tidy.load_plan(data, plan["id"]) and tidy.load_plan(data, "nope") is None
    res = tidy.apply_plan(plan, data)
    assert res["moved"] == 6 and not res["busy"]
    assert (desk / "Разобрано" / "Документы" / "договор.pdf").exists() and (dl / "Разобрано" / "Архивы" / "архив.zip").exists()
    assert (desk / "Premiere.lnk").exists() and (desk / "Проект X" / "внутри.txt").exists() and (desk / "только_что.txt").exists()
    assert not (desk / "договор.pdf").exists() and tidy.load_plan(data) is None
    # повторная уборка — «Разобрано» не разбираем заново
    assert tidy.make_plan({"desktop": desk}, data)["total"] == 0
    assert "чисто" in tidy.plan_text(tidy.make_plan({"desktop": desk}, data)).lower()
    # откат
    u = tidy.undo_last(data)
    assert u["restored"] == 6 and not u["failed"]
    assert (desk / "договор.pdf").exists() and (dl / "setup.exe").exists() and not (desk / "Разобрано").exists()
    assert tidy.undo_last(data).get("none")
    # одноимённый файл в целевой папке не затирается
    (desk / "Разобрано" / "Документы").mkdir(parents=True)
    _mk(desk / "Разобрано" / "Документы", "договор.pdf", body=b"old")
    plan = tidy.make_plan({"desktop": desk}, data)
    tidy.apply_plan(plan, data)
    assert (desk / "Разобрано" / "Документы" / "договор.pdf").read_bytes() == b"old" and (desk / "Разобрано" / "Документы" / "договор (2).pdf").exists()


def test_tidy_chat_flow_plan_then_yes():
    """«разбери рабочий стол» → команда ПК (не «анализ»); план с ПК ставит вопрос; «да» → tidy_apply с id плана."""
    from fastapi.testclient import TestClient
    from core.api.app import app
    from core.services import pc
    from core.brain import agent
    sent = []
    prev = agent.on_change
    agent.on_change = lambda kind, payload: sent.append((kind, payload)) if kind == "pc" else None
    try:
        c = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5555))
        pc.seen({"mode": "idle"})
        r = c.post("/api/chat", json={"text": "разбери рабочий стол", "channel": "web"}).json()
        assert r["actions"] == ["pc_tidy"] and "план" in r["text"].lower()
        assert sent[-1][0] == "pc" and sent[-1][1]["action"] == "tidy" and sent[-1][1]["arg"] == "desktop"
        # ПК прислал план
        c.post("/api/pc/result", json={"text": "🧹 План уборки…", "channel": "web", "kind": "tidy_plan", "extra": {"plan_id": "abc123", "total": 4}})
        r = c.post("/api/chat", json={"text": "да", "channel": "web"}).json()
        assert r["actions"] == ["pc_tidy"]
        assert sent[-1][1]["action"] == "tidy_apply" and sent[-1][1]["arg"] == "abc123"
        # пустой план вопрос не ставит — «да» ни к чему не приводит
        c.post("/api/pc/result", json={"text": "чисто", "channel": "web", "kind": "tidy_plan", "extra": {"plan_id": "zzz", "total": 0}})
        n = len(sent)
        c.post("/api/chat", json={"text": "да", "channel": "web"})
        assert not any(p.get("action") == "tidy_apply" for k, p in sent[n:])
        # «нет» снимает вопрос
        c.post("/api/pc/result", json={"text": "план", "channel": "web", "kind": "tidy_plan", "extra": {"plan_id": "q1", "total": 2}})
        assert "Отбой" in c.post("/api/chat", json={"text": "нет", "channel": "web"}).json()["text"]
        # отмена уборки и «разбери ситуацию» — не уборка
        assert c.post("/api/chat", json={"text": "отмени уборку", "channel": "web"}).json()["actions"] == ["pc_tidy_undo"]
        assert sent[-1][1]["action"] == "tidy_undo"
        # ПК не на связи — понятная подсказка
        pc.LAST_SEEN = 0
        assert "voice.bat" in c.post("/api/chat", json={"text": "прибери в загрузках", "channel": "web"}).json()["text"]
    finally:
        agent.on_change = prev


def test_nightly_tidy_only_old_downloads(tmp_path: Path, monkeypatch):
    """Ночная уборка: только «Загрузки», только старше N дней, только в окно 3–6 утра и раз в сутки; выключена по умолчанию."""
    from core.pc import loop, tidy
    from datetime import datetime as _dt
    dl = tmp_path / "Downloads"; dl.mkdir()
    _mk(dl, "старый.pdf", age_sec=10 * 86400); _mk(dl, "недавний.pdf", age_sec=2 * 86400)
    monkeypatch.setattr(tidy, "known_folder", lambda name: dl if name == "downloads" else None)
    monkeypatch.setattr(loop, "_post", lambda *a, **k: None)

    class FakeDT(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt(2026, 9, 14, 4, 0)
    monkeypatch.setattr(loop, "datetime", FakeDT)
    loop.setup("http://x", tmp_path / "data")          # по умолчанию 0 → выключено
    loop.nightly_tidy_check()
    assert (dl / "старый.pdf").exists()
    loop.setup("http://x", tmp_path / "data", tidy_downloads_days=7)
    loop._tidy_done = None
    loop.nightly_tidy_check()
    assert (dl / "Разобрано" / "Документы" / "старый.pdf").exists() and (dl / "недавний.pdf").exists()
    # второй раз за ночь не запускается
    _mk(dl, "ещё_старый.pdf", age_sec=10 * 86400)
    loop.nightly_tidy_check()
    assert (dl / "ещё_старый.pdf").exists()
    assert tidy.undo_last(tmp_path / "data")["restored"] == 1 and (dl / "старый.pdf").exists()
