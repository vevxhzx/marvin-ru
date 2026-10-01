# .venv\Scripts\python.exe reviews\_check_7_6.py  (запускать из корня репозитория)
# Эмпирическая проверка шага 7.6: SSE не сломаны (НЕ 422/404), статика отдаётся.
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
os.environ["ASSISTANT_TEST"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.routing import Match  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from core.api.app import app  # noqa: E402

ok = True


def flat_routes(routes, out=None):
    """Развернуть дерево роутов (FastAPI 0.141 держит include_router вложенно)."""
    out = [] if out is None else out
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":
            flat_routes(r.original_router.routes, out)
            continue
        if getattr(r, "path", None) is not None:
            out.append(r)
    return out


FLAT = flat_routes(app.router.routes)


def probe(method, path):
    """Запустить ASGI-приложение и поймать только http.response.start (без чтения тела).

    Нужен для SSE: StreamingResponse бесконечен, TestClient буферизует тело и «вечность».
    Заголовки ответа приходят сразу — получаем статус и content-type, потом отменяем.
    """
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "headers": [(b"host", b"localhost")],
        "client": ("127.0.0.1", 12345), "server": ("localhost", 8765),
    }
    start = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            start.update(message)
            raise asyncio.CancelledError  # заголовки есть — тело (бесконечное) не читаем

    async def run():
        try:
            await app(scope, receive, send)
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    return start


def hdrs(start):
    return {k.decode(): v.decode(errors="replace") for k, v in start.get("headers", [])}


# 1) GET /api/events/stream (SSE) — статус и content-type БЕЗ 422/404
st = probe("GET", "/api/events/stream")
h = hdrs(st)
code = st.get("status")
ctype = h.get("content-type", "")
good = code not in (422, 404, 405) and "text/event-stream" in ctype
ok = ok and good
print(f"{'OK  ' if good else 'FAIL'} GET /api/events/stream -> {code} content-type={ctype!r}")

# 1b) тот же маршрут — уровень роутинга: выигрывает САМ, а не /api/events/{event_id}
scope = {"type": "http", "method": "GET", "path": "/api/events/stream", "root_path": "", "headers": []}
matched = [r.path for r in FLAT if r.matches(scope)[0] is Match.FULL]
good = bool(matched) and matched[0] == "/api/events/stream"
ok = ok and good
print(f"{'OK  ' if good else 'FAIL'} routing GET /api/events/stream -> {matched[:3]}")

# 2) POST /api/chat/stream — путь и метод доступны (НЕ 404/405), матчится наш путь;
#    живой POST с валидным телом (агент в тестовом режиме отвечает быстро)
scope2 = {"type": "http", "method": "POST", "path": "/api/chat/stream", "root_path": "", "headers": []}
matched2 = [r.path for r in FLAT if r.matches(scope2)[0] is Match.FULL]
c = TestClient(app)
r2 = c.post("/api/chat/stream", json={"text": "hi", "channel": "web"})
good = matched2[:1] == ["/api/chat/stream"] and r2.status_code not in (404, 405, 422)
ok = ok and good
print(f"{'OK  ' if good else 'FAIL'} POST /api/chat/stream -> status={r2.status_code} matched={matched2[:2]}")

# 3) Смоук статики: GET / отдаёт HTML, GET /manifest.json — JSON
r3 = c.get("/")
good = r3.status_code == 200 and "text/html" in r3.headers.get("content-type", "")
ok = ok and good
print(f"{'OK  ' if good else 'FAIL'} GET / -> {r3.status_code} content-type={r3.headers.get('content-type')!r} len={len(r3.content)}")

r4 = c.get("/manifest.json")
good = r4.status_code == 200 and "json" in r4.headers.get("content-type", "")
ok = ok and good
print(f"{'OK  ' if good else 'FAIL'} GET /manifest.json -> {r4.status_code} content-type={r4.headers.get('content-type')!r}")

# 4) быстрый смоук перенесённых системных роутов
for path in ("/api/health", "/api/ui-prefs", "/api/edition"):
    rr = c.get(path)
    good = rr.status_code == 200
    ok = ok and good
    print(f"{'OK  ' if good else 'FAIL'} GET {path} -> {rr.status_code}")

print("ALL OK" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
