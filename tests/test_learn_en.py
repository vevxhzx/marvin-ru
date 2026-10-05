# -*- coding: utf-8 -*-
"""Блок обучения английскому: `core/services/learn_en.py` + `/api/english/*`.

Что проверяем:
* детерминированность абзаца дня (в один день — тот же текст, на другой день и на другом
  направлении — другой), полнота ответа (перевод, ключевые слова, тема);
* прогресс: `done` → стрик/всего дней, повтор в тот же день не накручивает, разрыв серии;
* свои тексты: добавление, список, удаление, лимит, честная ошибка на пустом;
* переключение направления в настройках запоминается;
* недоступная LLM → тихо встроенный корпус, без ошибки (и по умолчанию LLM вообще не трогается);
* авторизация: снаружи без ключа — 401 (как у соседних роутов).

Сеть не используется: при `english.llm=1` подменяется единственная точка обращения к модели —
`learn_en._llm_paragraph`. Всё состояние — во временной БД (`fresh_db`), config.yaml не пишется.
"""
from __future__ import annotations

import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from core.services import learn_en  # noqa: E402

TODAY = learn_en.today()


@pytest.fixture
def client(fresh_db):
    """TestClient к API поверх временной БД (хост testserver → авторизация отключена)."""
    from fastapi.testclient import TestClient

    from core.api.app import app
    return TestClient(app, client=("127.0.0.1", 5555), base_url="http://testserver")


# ---------------------------------------------------------------- корпус и детерминированность
def test_builtin_corpus_size_per_track():
    """Минимум по 8 абзацев на каждое встроенное направление, у каждого — перевод и слова."""
    for track in ("video", "general"):
        body = learn_en.CORPUS[track]
        assert len(body) >= 8, f"{track}: всего {len(body)} абзацев"
        for topic, en, ru, words in body:
            assert topic and en and ru, f"{track}: пустая тема/текст/перевод — {topic}"
            assert len(en.split()) >= 25, f"{track}/{topic}: слишком короткий абзац"
            assert 3 <= len(words) <= 5, f"{track}/{topic}: {len(words)} ключевых слов"
            for w, ph, note in words:
                assert w and ph and note, f"{track}/{topic}: неполное ключевое слово — {w}"


def test_video_corpus_has_editing_terms():
    """Техдокументация монтажа: термины поста реально есть в корпусе направления video."""
    blob = " ".join(en for _t, en, _ru, _w in learn_en.CORPUS["video"]).lower() + " " + \
        " ".join(f"{w} {n}" for _t, _en, _ru, ws in learn_en.CORPUS["video"] for w, _p, n in ws).lower()
    for term in ("timeline", "cut", "keyframe", "proxy", "codec", "lut", "waveform", "render",
                 "ingest", "a-roll", "b-roll", "deliverable"):
        assert term in blob, f"в корпусе video нет термина {term}"


def test_today_same_within_a_day(client):
    """Два запроса в один день — тот же самый абзац (детерминированно по дате)."""
    a = client.get("/api/english/today").json()
    b = client.get("/api/english/today").json()
    assert a["text_en"] == b["text_en"]
    assert a["title"] == b["title"]
    assert a["date"] == b["date"] == TODAY


def test_today_response_shape(client):
    """Структура ответа: date/track/title/text_en/text_ru/words/source/is_new."""
    d = client.get("/api/english/today").json()
    for k in ("date", "track", "title", "text_en", "text_ru", "words", "source", "is_new"):
        assert k in d, f"в ответе нет {k}"
    assert d["source"] == "builtin"
    assert d["track"] == "video"
    assert 3 <= len(d["words"]) <= 5
    for w in d["words"]:
        assert set(w) == {"word", "phonetic", "note"} and w["word"] and w["phonetic"] and w["note"]


def test_today_changes_with_day(client):
    """На следующий день абзац другой."""
    a = client.get("/api/english/today").json()
    from datetime import date, timedelta
    nd = (date.fromisoformat(TODAY) + timedelta(days=1)).isoformat()
    b = client.get(f"/api/english/today?day={nd}").json()
    assert b["date"] == nd
    assert b["text_en"] != a["text_en"], "абзац не сменился при смене даты"


def test_today_changes_with_track(client):
    """Превью другого направления отдаёт другой абзац и настройки НЕ меняет."""
    a = client.get("/api/english/today").json()
    b = client.get("/api/english/today?track=general").json()
    assert b["track"] == "general" and b["source"] == "builtin"
    assert b["text_en"] != a["text_en"]
    assert client.get("/api/english/settings").json()["track"] == "video", "превью не должно сохранять направление"


def test_today_unknown_track_falls_back(client):
    """Неизвестное направление не ломает ответ — отдаётся дефолтное."""
    d = client.get("/api/english/today?track=does-not-exist").json()
    assert d["track"] == "video" and d["text_en"]


def test_pick_index_is_stable_and_adjacent_days_differ():
    """Индекс не «прыгает» между вызовами, соседние дни дают разные абзацы."""
    from datetime import date, timedelta
    assert learn_en.pick_index("2026-03-01", "video") == learn_en.pick_index("2026-03-01", "video")
    d = date(2026, 3, 1)
    for track in ("video", "general"):
        idx = [learn_en.pick_index((d + timedelta(days=i)).isoformat(), track) for i in range(40)]
        assert all(0 <= i < len(learn_en.CORPUS[track]) for i in idx)
        assert all(a != b for a, b in zip(idx, idx[1:])), f"{track}: соседние дни дали один абзац"


# ---------------------------------------------------------------- прогресс и стрик
def test_done_then_progress(client):
    client.put("/api/english/settings", json={"track": "video"})
    d = client.get("/api/english/today").json()
    r = client.post("/api/english/done")
    assert r.status_code == 200
    assert r.json()["streak"] == 1 and r.json()["total_days"] == 1
    p = client.get("/api/english/progress").json()
    assert p["streak"] == 1
    assert p["total_days"] == 1
    assert p["last_date"] == TODAY
    assert p["by_track"]["video"]["days"] == 1
    assert p["today_done"] is True
    assert d["text_en"]


def test_done_twice_same_day_is_idempotent(client):
    client.post("/api/english/done")
    r = client.post("/api/english/done")
    p = client.get("/api/english/progress").json()
    assert p["total_days"] == 1 and p["streak"] == 1
    assert r.json()["already"] is True


def test_streak_grows_over_consecutive_days(client):
    """Три дня подряд (сегодня, вчера, позавчера) — стрик 3; всего дней 3."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(TODAY)
    for i in (2, 1, 0):
        client.post(f"/api/english/done?day={(d0 - timedelta(days=i)).isoformat()}")
    p = client.get("/api/english/progress").json()
    assert p["total_days"] == 3
    assert p["streak"] == 3


def test_streak_zero_after_a_long_gap(client):
    """Если последний отмеченный день старше вчера — серия считается прерванной (streak 0)."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(TODAY)
    for i in (10, 9, 8):
        client.post(f"/api/english/done?day={(d0 - timedelta(days=i)).isoformat()}")
    p = client.get("/api/english/progress").json()
    assert p["streak"] == 0
    assert p["total_days"] == 3, "всего дней не теряется"
    assert p["last_date"] == (d0 - timedelta(days=8)).isoformat()


def test_streak_breaks_after_a_gap(client):
    """Пропущенные дни обнуляют серию: 6,5,4 и 1,0 назад → стрик 2, а не 5."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(TODAY)
    for i in (6, 5, 4):
        client.post(f"/api/english/done?day={(d0 - timedelta(days=i)).isoformat()}")
    assert client.get("/api/english/progress").json()["streak"] == 0
    client.post(f"/api/english/done?day={(d0 - timedelta(days=1)).isoformat()}")   # вчера
    client.post("/api/english/done")                                               # сегодня
    p = client.get("/api/english/progress").json()
    assert p["streak"] == 2, "после разрыва серия должна начаться заново"
    assert p["total_days"] == 5
    assert p["last_date"] == TODAY


def test_progress_by_track_splits(client):
    """Разбивка по направлениям: день учитывается в том направлении, которое было выбрано."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(TODAY)
    client.post(f"/api/english/done?track=video&day={(d0 - timedelta(days=1)).isoformat()}")
    client.post("/api/english/done?track=general")   # сегодня
    by = client.get("/api/english/progress").json()["by_track"]
    assert by["video"]["days"] == 1 and by["general"]["days"] == 1
    assert by["video"]["last_date"] == (d0 - timedelta(days=1)).isoformat()
    assert by["general"]["last_date"] == TODAY


def test_progress_one_day_one_track(client):
    """Отметить один день дважды с разными направлениями не создаёт двух записей."""
    client.post("/api/english/done?track=video")
    client.post("/api/english/done?track=general")
    p = client.get("/api/english/progress").json()
    assert p["total_days"] == 1
    assert list(p["by_track"]) == ["general"]


# ---------------------------------------------------------------- свои тексты
def test_custom_add_list_delete(client):
    r = client.post("/api/english/custom", json={"text_en": "The edit is ready for review.", "text_ru": "Монтаж готов к проверке.", "note": "для клиента"})
    assert r.status_code == 200 and r.json()["count"] == 1
    items = client.get("/api/english/custom").json()
    assert items["limit"] == 200
    assert items["items"][0]["text_en"] == "The edit is ready for review."
    assert items["items"][0]["text_ru"] == "Монтаж готов к проверке."
    assert client.delete("/api/english/custom/0").json()["count"] == 0
    assert client.get("/api/english/custom").json()["items"] == []


def test_custom_requires_text(client):
    """Пустой английский текст — 422 от схемы, пробелы — 400 с понятным текстом."""
    assert client.post("/api/english/custom", json={"text_en": ""}).status_code in (400, 422)
    r = client.post("/api/english/custom", json={"text_en": "   "})
    assert r.status_code == 400 and "английском" in r.json()["detail"]


def test_custom_delete_missing_404(client):
    assert client.delete("/api/english/custom/7").status_code == 404


def test_custom_today_uses_own_text(client):
    """Направление custom: абзац дня приходит из своих текстов, ключевых слов нет."""
    client.put("/api/english/settings", json={"track": "custom"})
    d = client.get("/api/english/today").json()
    assert d["source"] == "custom" and d["text_en"] == "" and d["words"] == []
    client.post("/api/english/custom", json={"text_en": "Cut the B-roll before the interview.", "text_ru": "Режьте перебивку до интервью."})
    d = client.get("/api/english/today").json()
    assert d["source"] == "custom"
    assert d["text_en"] == "Cut the B-roll before the interview."
    assert d["text_ru"] == "Режьте перебивку до интервью."


def test_custom_limit(client, monkeypatch):
    """Лимит своих текстов: лишнее не добавляется, лишнее не падает."""
    monkeypatch.setattr(learn_en, "CUSTOM_LIMIT", 2)
    for i in range(4):
        client.post("/api/english/custom", json={"text_en": f"text {i}", "text_ru": ""})
    items = client.get("/api/english/custom").json()
    assert items["limit"] == 2
    assert len(items["items"]) == 2
    assert items["items"][0]["text_en"] == "text 3"   # новые сверху


# ---------------------------------------------------------------- настройки направления
def test_settings_defaults(client):
    s = client.get("/api/english/settings").json()
    assert s["track"] == "video"
    assert s["llm"] is False, "генерация нейросетью по умолчанию ВЫКЛ — поведение не меняется"
    assert s["default_track"] == "video"
    assert [t["id"] for t in s["tracks"]] == ["video", "general", "custom"]
    assert s["tracks"][0]["title"] == "Техдокументация для монтажёров"
    assert s["custom_count"] == 0


def test_settings_switch_track_is_saved(client):
    r = client.put("/api/english/settings", json={"track": "general"})
    assert r.status_code == 200 and r.json()["track"] == "general"
    assert client.get("/api/english/settings").json()["track"] == "general"
    assert client.get("/api/english/today").json()["track"] == "general"
    # переключение назад
    client.put("/api/english/settings", json={"track": "video"})
    assert client.get("/api/english/today").json()["track"] == "video"


def test_settings_rejects_unknown_track(client):
    r = client.put("/api/english/settings", json={"track": "klingon"})
    assert r.status_code == 400 and "направление" in r.json()["detail"]
    assert client.get("/api/english/settings").json()["track"] == "video"


def test_settings_ignores_unknown_field(client):
    """Неизвестное поле молча игнорируется (как у соседних роутов — 422 не ловим), настройки не меняются."""
    r = client.put("/api/english/settings", json={"nope": 1})
    assert r.status_code == 200
    assert r.json()["track"] == "video"
    # на уровне сервиса (прямой вызов, не через схему API) неизвестное поле — ошибка
    with pytest.raises(ValueError):
        learn_en.save_settings({"nope": 1})


def test_settings_llm_flag_persists(client):
    r = client.put("/api/english/settings", json={"llm": True})
    assert r.json()["llm"] is True
    assert client.get("/api/english/settings").json()["llm"] is True
    client.put("/api/english/settings", json={"llm": False})
    assert client.get("/api/english/settings").json()["llm"] is False


# ---------------------------------------------------------------- LLM: выключена / недоступна / ответила
def test_llm_disabled_by_default_never_calls_model(client, monkeypatch):
    """Флаг english.llm выключен — к модели не ходим вообще (поведение по умолчанию не меняется)."""
    async def boom(*a, **k):   # pragma: no cover — вызываться не должна
        raise AssertionError("LLM не должна вызываться при english.llm=0")

    monkeypatch.setattr(learn_en, "_llm_paragraph", boom)
    d = client.get("/api/english/today").json()
    assert d["source"] == "builtin"


def test_llm_enabled_but_unavailable_falls_back(client, monkeypatch):
    """english.llm=1, но модель недоступна → тихо встроенный корпус, ответ 200, не ошибка."""
    async def offline(*a, **k):
        return None

    monkeypatch.setattr(learn_en, "_llm_paragraph", offline)
    client.put("/api/english/settings", json={"llm": True})
    d = client.get("/api/english/today").json()
    assert d["source"] == "builtin" and d["text_en"] and d["text_ru"]
    assert d["words"]


def test_llm_paragraph_is_cached_per_day(client, monkeypatch):
    """Сгенерированный абзац кэшируется на день: второй запрос LLM не дёргает."""
    calls = []

    async def gen(day, track):
        calls.append((day, track))
        return {"title": "Cutting to music", "text_en": "Cut on the beat.", "text_ru": "Режьте по биту.",
                "words": [{"word": "beat", "phonetic": "biːt", "note": "доля"}], "source": "llm", "is_new": True}

    monkeypatch.setattr(learn_en, "_llm_paragraph", gen)
    client.put("/api/english/settings", json={"llm": True})
    a = client.get("/api/english/today").json()
    b = client.get("/api/english/today").json()
    assert a["source"] == "llm" and a["text_en"] == "Cut on the beat."
    assert b == a
    assert len(calls) == 1, "кэш на день не сработал"
    # другой день — новая генерация
    client.get("/api/english/today?day=2026-01-01")
    assert len(calls) == 2


def test_llm_bad_answer_falls_back(client, monkeypatch):
    """Мусор от модели вместо JSON → встроенный корпус, без 500."""
    async def junk(day, track):
        return None

    monkeypatch.setattr(learn_en, "_llm_paragraph", junk)
    client.put("/api/english/settings", json={"llm": True})
    assert client.get("/api/english/today").json()["source"] == "builtin"


def test_llm_parse_json_helper():
    assert learn_en._parse_json('```json\n{"title": "Cut", "text_en": "Cut to music."}\n```')["text_en"] == "Cut to music."
    assert learn_en._parse_json("всё подряд") is None
    assert learn_en._parse_json("") is None
    assert learn_en._clean_words([{"word": " beat ", "phonetic": "biːt", "note": "доля"}, "мусор", {"word": ""}]) == [
        {"word": "beat", "phonetic": "biːt", "note": "доля"}]


# ---------------------------------------------------------------- авторизация (как у соседних роутов)
@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/english/today", None),
    ("GET", "/api/english/progress", None),
    ("GET", "/api/english/settings", None),
    ("GET", "/api/english/custom", None),
    ("POST", "/api/english/done", None),
    ("POST", "/api/english/custom", {"text_en": "Hi", "text_ru": "Привет"}),
    ("PUT", "/api/english/settings", {"track": "general"}),
    ("DELETE", "/api/english/custom/0", None),
])
def test_remote_without_key_401(fresh_db, method, path, body):  # noqa: ARG001 — изоляция БД: DELETE/PUT идут в живой API
    """С телефона без ключа — 401 на всех маршрутах блока (общий AuthMiddleware)."""
    from fastapi.testclient import TestClient

    from core.api.app import app
    c = TestClient(app, client=("192.168.1.50", 5555), base_url="http://testserver")
    assert c.request(method, path, json=body).status_code == 401


def test_router_is_registered_before_spa_catchall():
    """learn подключён ДО catch-all SPA, иначе /api/english/* отдал бы HTML."""
    from core.api.app import app

    paths = [getattr(r, "original_router", None) for r in app.router.routes]
    flat = []
    for r in app.router.routes:
        if type(r).__name__ == "_IncludedRouter":
            flat += [(getattr(x, "path", ""), tuple(sorted(getattr(x, "methods", []) or []))) for x in r.original_router.routes]
    idx_learn = next(i for i, r in enumerate(app.router.routes)
                      if type(r).__name__ == "_IncludedRouter"
                      and any(getattr(x, "path", "") == "/api/english/today" for x in r.original_router.routes))
    idx_spa = next(i for i, r in enumerate(app.router.routes) if getattr(r, "path", "") == "/{path:path}")
    assert idx_learn < idx_spa, "роутер learn должен регистрироваться до catch-all SPA"
    assert paths and any(p for p in paths)
    assert ("/api/english/progress", ("GET",)) in flat
