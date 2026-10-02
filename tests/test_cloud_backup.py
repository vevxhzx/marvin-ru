# -*- coding: utf-8 -*-
"""Облачные бэкапы (core/services/cloud_backup.py): шифрование, WebDAV-запросы, API, выключено по умолчанию.

Сеть мокается в одной точке — `cloud_backup._open` (точно туда уходит urllib.request.urlopen):
так проверяются настоящие методы/URL/заголовки запросов без внешних серверов.
Любой тест, трогающий settings, идёт на временной БД (`fresh_db` из conftest) —
data/jarvis.db и config.yaml не открываются.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import urllib.error
import urllib.parse
from datetime import datetime, timedelta

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

# ---------------------------------------------------------------- мок-сеть
PROPFIND_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/u/jarvis-backups/backup-20250102-0300.db.enc</d:href>
    <d:propstat><d:prop><d:resourcetype/><d:getcontentlength>2048</d:getcontentlength>
      <d:getlastmodified>Thu, 02 Jan 2025 03:00:00 GMT</d:getlastmodified></d:prop>
      <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/u/jarvis-backups/backup-20250102-0300.db.manifest.json</d:href>
    <d:propstat><d:prop><d:resourcetype/><d:getcontentlength>300</d:getcontentlength>
      <d:getlastmodified>Thu, 02 Jan 2025 03:00:01 GMT</d:getlastmodified></d:prop>
      <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/u/jarvis-backups/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop>
      <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
  </d:response>
</d:multistatus>
"""


class FakeResp:
    def __init__(self, body=b"", status=200, headers=None):
        self.body, self.status, self.headers = body, status, headers or {}

    def read(self):
        return self.body

    def getcode(self):
        return self.status

    def close(self):
        pass


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(b""))


class FakeNet:
    """Подмена urllib.request.urlopen: пишет каждый запрос, отвечает по методу."""

    def __init__(self, propfind=PROPFIND_XML, files=None):
        self.calls: list[dict] = []
        self.propfind = propfind
        self.files = dict(files or {})

    def __call__(self, req, timeout=None):
        method = req.get_method()
        self.calls.append({"method": method, "url": req.full_url, "data": req.data or b"",
                           "headers": dict(req.headers), "timeout": timeout})
        if method == "PROPFIND":
            return FakeResp(self.propfind, 207)
        if method == "GET":
            name = urllib.parse.unquote(req.full_url.rsplit("/", 1)[-1])
            if name not in self.files:
                raise _http_error(req.full_url, 404)
            return FakeResp(self.files[name], 200)
        if method == "DELETE":
            return FakeResp(b"", 204)
        return FakeResp(b"", 201)   # PUT / MKCOL / HEAD


def _cfg(**over) -> dict:
    """Настройки для прямых вызовов сервиса (тестовые секреты, читаемых только в памяти)."""
    base = {"enabled": True, "url": "https://dav.example/remote.php/dav/files/u", "user": "u",
            "pass": "pw", "token": "", "dir": "/jarvis-backups", "encrypt_pass": "секрет-1",
            "every_hours": 24, "keep": 10}
    base.update(over)
    return base


@pytest.fixture()
def net(monkeypatch):
    """Мок-сеть на все тесты, которым нужна «жизнь» WebDAV."""
    from core.services import cloud_backup as cb
    n = FakeNet()
    monkeypatch.setattr(cb, "_open", n)
    return n


# ---------------------------------------------------------------- шифрование
def test_encrypt_roundtrip():
    from core.services import cloud_backup as cb
    src = b"sqlite-bytes-" * 500
    blob = cb.encrypt_bytes(src, "пароль-1")
    assert cb.decrypt_bytes(blob, "пароль-1") == src
    # неверный пароль — ошибка, а не тихо другие байты
    with pytest.raises(ValueError, match="пароль"):
        cb.decrypt_bytes(blob, "не тот пароль")
    # порча тела (GCM-тег) — тоже ошибка
    damaged = bytearray(blob)
    damaged[-1] ^= 0xFF
    with pytest.raises(ValueError):
        cb.decrypt_bytes(bytes(damaged), "пароль-1")


def test_encrypted_file_format():
    from core.services import cloud_backup as cb
    blob = cb.encrypt_bytes(b"x" * 10, "pw")
    assert blob[:4] == cb.MAGIC == b"JBK1"          # magic(4)
    assert len(blob) == 4 + 16 + 12 + 10 + 16       # salt(16) | nonce(12) | ct+tag
    assert cb.encrypt_bytes(b"x" * 10, "pw") != blob  # salt и nonce каждый раз свои
    with pytest.raises(ValueError):
        cb.encrypt_bytes(b"x", "")                    # без пароля не шифруем
    with pytest.raises(ValueError):
        cb.decrypt_bytes("короткий".encode(), "pw")   # не формат — честная ошибка


def test_decrypt_file_writes_dest(tmp_path):
    from core.services import cloud_backup as cb
    src = tmp_path / "backup-20250102-0300.db"
    enc = tmp_path / "backup-20250102-0300.db.enc"
    src.write_bytes("оригинал".encode())
    enc.write_bytes(cb.encrypt_bytes(src.read_bytes(), "pw"))
    dest = cb.decrypt_file(enc, "pw", tmp_path / "out.db")
    assert dest.read_bytes() == "оригинал".encode()
    assert cb.decrypt_file(enc, "pw") == "оригинал".encode()   # без dest — байты
    with pytest.raises(ValueError):
        cb.decrypt_file(enc, "другой", tmp_path / "bad.db")


# ---------------------------------------------------------------- запросы WebDAV
def test_upload_put_and_manifest(tmp_path, net, fresh_db):
    """PUT уходит на правильный URL с Basic-заголовком; манифест — открытым текстом."""
    from core.services import cloud_backup as cb
    src = tmp_path / "backup-20250102-0300.db"
    src.write_bytes(b"sqlite bytes")
    res = cb.upload_backup(src, _cfg())

    puts = [c for c in net.calls if c["method"] == "PUT"]
    assert len(puts) == 2
    base = "https://dav.example/remote.php/dav/files/u/jarvis-backups/"
    assert puts[0]["url"] == base + "backup-20250102-0300.db.enc"
    assert puts[1]["url"] == base + "backup-20250102-0300.db.manifest.json"
    assert puts[0]["headers"]["Authorization"] == "Basic " + base64.b64encode(b"u:pw").decode()
    assert puts[0]["timeout"] == cb.TIMEOUT
    # тело — шифрованное (исходных байт и пароля в запросе нет)
    assert puts[0]["data"][:4] == cb.MAGIC
    assert b"sqlite bytes" not in puts[0]["data"]
    assert "секрет-1" not in puts[0]["data"].decode("utf-8", "replace")
    # манифест открыт: имя, размер, sha256 ДО шифрования, версия
    man = json.loads(puts[1]["data"].decode("utf-8"))
    assert man["source"] == src.name and man["file"] == src.name + ".enc"
    assert man["size"] == len(b"sqlite bytes")
    assert man["sha256"] == hashlib.sha256(b"sqlite bytes").hexdigest()
    assert man["version"] and man["format"] == "aes-256-gcm/scrypt"
    # каталог создан, список снят (ротация) — Depth у PROPFIND
    assert any(c["method"] == "MKCOL" for c in net.calls)
    pf = [c for c in net.calls if c["method"] == "PROPFIND"]
    assert pf and all(c["headers"].get("Depth") for c in pf)
    assert res["ok"] and res["name"] == src.name + ".enc" and res["size"] == len(b"sqlite bytes")
    # и статус попытки записан в settings (его отдаёт GET /api/backups/cloud)
    from core.db import get_setting
    assert get_setting("cloud.last_attempt") and get_setting("cloud.last_uploaded")


def test_list_remote_parses_propfind(net, fresh_db):
    from core.services import cloud_backup as cb
    items = cb.list_remote(_cfg())
    # каталог (collection) в список не попадает, манифест — остаётся (его фильтрует status())
    assert [i["name"] for i in items] == [
        "backup-20250102-0300.db.manifest.json", "backup-20250102-0300.db.enc"]
    enc = next(i for i in items if i["name"].endswith(".enc"))
    assert enc["size"] == 2048 and enc["mtime"] == "2025-01-02T03:00:00+00:00"
    assert net.calls[0]["method"] == "PROPFIND"
    assert net.calls[0]["headers"]["Depth"] == "1"


def test_auth_bearer_when_password_is_token(net, fresh_db):
    """Пароль без логина (OAuth-токен Яндекс.Диска) → Authorization: Bearer, а не Basic;
    отдельное поле token имеет приоритет, логин+пароль → Basic."""
    from core.services import cloud_backup as cb
    cfg = _cfg()
    cfg.update({"user": "", "pass": "y0_Agxxx-token"})
    cb.list_remote(cfg)
    assert net.calls[0]["headers"]["Authorization"] == "Bearer y0_Agxxx-token"
    net.calls.clear()
    cfg.update({"user": "", "pass": "пароль", "token": "отдельный-токен"})
    cb.list_remote(cfg)
    assert net.calls[0]["headers"]["Authorization"] == "Bearer отдельный-токен"
    net.calls.clear()
    cb.list_remote(_cfg())
    assert net.calls[0]["headers"]["Authorization"] == "Basic " + base64.b64encode(b"u:pw").decode()


def test_retry_once_then_network_error(monkeypatch, fresh_db):
    """Сетевая ошибка → ровно один повтор, потом понятный CloudError."""
    from core.services import cloud_backup as cb
    attempts = []

    def flaky(req, timeout=None):
        attempts.append(req.get_method())
        if len(attempts) == 1:
            raise urllib.error.URLError("нет сети")
        return FakeResp(b"", 201)

    monkeypatch.setattr(cb, "_open", flaky)
    cb._request(_cfg(), "PUT", "https://dav.example/x", data=b"1")
    assert len(attempts) == 2


def test_http_401_is_russian_error(monkeypatch, fresh_db):
    from core.services import cloud_backup as cb

    def unauthorized(req, timeout=None):
        raise _http_error(req.full_url, 401)

    monkeypatch.setattr(cb, "_open", unauthorized)
    with pytest.raises(cb.CloudError) as ei:
        cb._request(_cfg(), "PROPFIND", "https://dav.example/")
    assert "401" in str(ei.value) and "логин" in str(ei.value)


def test_ensure_dir_creates_intermediate(net, fresh_db):
    from core.services import cloud_backup as cb
    cb.ensure_dir(_cfg(dir="/a/b/c"), "/a/b/c")
    mk = [c["url"] for c in net.calls if c["method"] == "MKCOL"]
    assert mk == ["https://dav.example/remote.php/dav/files/u/a",
                  "https://dav.example/remote.php/dav/files/u/a/b",
                  "https://dav.example/remote.php/dav/files/u/a/b/c"]


def test_rotation_keeps_only_keep(tmp_path, monkeypatch, fresh_db):
    """В облаке держим не больше cloud.keep своих backup-*.enc: старые удаляются
    вместе с манифестами, чужие файлы не трогаются."""
    from core.services import cloud_backup as cb
    names = ("backup-20250102-0300.db.enc", "backup-20241111-2222.db.enc",
             "backup-20241111-2222.db.manifest.json", "чужой-файл.txt")
    xml = (b'<?xml version="1.0" encoding="utf-8"?>'
           b'<d:multistatus xmlns:d="DAV:">' + b"".join(
               (f'<d:response><d:href>/jarvis-backups/{n}</d:href>'
                f'<d:propstat><d:prop><d:resourcetype/><d:getcontentlength>10</d:getcontentlength></d:prop>'
                f'<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>').encode()
               for n in names) + b'</d:multistatus>')
    net = FakeNet(propfind=xml)
    monkeypatch.setattr(cb, "_open", net)
    src = tmp_path / "backup-20250303-0300.db"
    src.write_bytes(b"db")
    cb.upload_backup(src, _cfg(keep=1))   # в списке два .enc → остаётся только новый
    deletes = [c["url"].rsplit("/", 1)[-1] for c in net.calls if c["method"] == "DELETE"]
    assert deletes == ["backup-20241111-2222.db.enc", "backup-20241111-2222.db.manifest.json"]


def test_download_decrypts_and_verifies_manifest(tmp_path, net, fresh_db):
    from core.services import cloud_backup as cb
    plain = "восстановленная база".encode()
    enc = cb.encrypt_bytes(plain, "секрет-1")
    man = json.dumps({"sha256": hashlib.sha256(plain).hexdigest()}).encode()
    net.files["backup-20250102-0300.db.enc"] = enc
    net.files["backup-20250102-0300.db.manifest.json"] = man
    dest = tmp_path / "backups" / "backup-20250102-0300.db"
    res = cb.download_remote("backup-20250102-0300.db.enc", dest, _cfg())
    assert res["ok"] and dest.read_bytes() == plain
    # битая контрольная сумма — отказ, а не «восстановленная» порча
    net.files["backup-20250102-0300.db.manifest.json"] = json.dumps({"sha256": "0" * 64}).encode()
    with pytest.raises(ValueError, match="контрольная сумма"):
        cb.download_remote("backup-20250102-0300.db.enc", tmp_path / "bad.db", _cfg())


@pytest.mark.parametrize("name", ["../../config.yaml", "..\\..\\x.db", "backup-hack.db",
                                  "config-20250101-0000/api_token", "jarvis.db"])
def test_remote_name_traversal_rejected(net, fresh_db, name):
    from core.services import cloud_backup as cb
    with pytest.raises(ValueError):
        cb.download_remote(name, "/tmp/x", _cfg())
    with pytest.raises(ValueError):
        cb.delete_remote(name, _cfg())
    # ни одного сетевого запроса — имя не доходит до облака
    assert net.calls == []


# ---------------------------------------------------------------- выключено по умолчанию
def test_disabled_by_default(fresh_db, monkeypatch):
    from core.db import get_setting
    from core.services import cloud_backup as cb

    def no_net(*a, **k):
        raise AssertionError("сеть не должна вызываться, пока облако выключено")

    monkeypatch.setattr(cb, "_open", no_net)
    assert cb.enabled() is False
    st = cb.status()
    assert st["enabled"] is False and st["configured"] is False
    assert st["remote"] == [] and st["url"] == ""
    with pytest.raises(ValueError):
        cb.upload_latest()
    # попыток не было — поведение без облака не изменилось
    assert get_setting("cloud.last_attempt") is None


def test_due_respects_every_hours(fresh_db):
    from core.db import set_setting
    from core.services import cloud_backup as cb
    set_setting("cloud.enabled", "1")
    assert cb.due() is True                                   # попыток не было
    set_setting("cloud.last_attempt", datetime.now().isoformat(timespec="seconds"))
    assert cb.due() is False                                  # только что пробовали
    old = (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")
    set_setting("cloud.last_attempt", old)
    assert cb.due() is True                                   # прошло больше 24 ч


# ---------------------------------------------------------------- API
def test_api_status_masks_secrets(_client, fresh_db):
    from core.db import set_setting
    set_setting("cloud.url", "https://webdav.yandex.ru")
    set_setting("cloud.user", "user@ya.ru")
    set_setting("cloud.pass", "TOP-SECRET-PASS")
    set_setting("cloud.token", "TOP-SECRET-TOKEN")
    set_setting("cloud.encrypt_pass", "TOP-SECRET-ENC")
    r = _client.get("/api/backups/cloud")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False and body["configured"] is True
    assert body["pass_set"] and body["token_set"] and body["encrypt_pass_set"]
    for secret in ("TOP-SECRET-PASS", "TOP-SECRET-TOKEN", "TOP-SECRET-ENC"):
        assert secret not in r.text
    assert body["remote"] == [] and body["last_uploaded"] is None


def test_api_put_enabled_requires_url(_client, fresh_db):
    r = _client.put("/api/backups/cloud", json={"enabled": True})
    assert r.status_code == 400 and "адрес" in r.json()["detail"].lower()
    ok = _client.put("/api/backups/cloud", json={"enabled": False, "dir": "backups"})
    assert ok.status_code == 200
    assert ok.json()["dir"] == "/backups"          # каталог нормализуется
    # пустой пароль = «не менять», новый — сохраняется и заменяет токен
    _client.put("/api/backups/cloud", json={"url": "https://dav.example", "pass": "новый"})
    from core.db import get_setting
    assert get_setting("cloud.pass") == "новый"
    r2 = _client.put("/api/backups/cloud", json={"pass": ""})
    assert r2.status_code == 200 and get_setting("cloud.pass") == "новый"


def test_api_download_rejects_traversal(_client, monkeypatch):
    from core.services import cloud_backup as cb

    def no_net(*a, **k):
        raise AssertionError("сеть не должна вызываться при неверном имени")

    monkeypatch.setattr(cb, "_open", no_net)
    for bad in ("../../config.yaml", "backup-hack.db", "config-20250101-0000/api_token"):
        r = _client.get("/api/backups/cloud/download", params={"name": bad})
        assert r.status_code == 400, (bad, r.status_code, r.text)
    # без имени — 422 (роут вообще не отрабатывает)
    assert _client.get("/api/backups/cloud/download").status_code == 422


def test_api_upload_and_download_flow(_client, fresh_db, monkeypatch, tmp_path):
    """POST /upload шлёт PUT; GET /download кладёт расшифрованный .db в backups/."""
    from core.db import set_setting
    from core.services import cloud_backup as cb
    from core.services import scheduler

    bdir = tmp_path / "backups"
    bdir.mkdir()
    (bdir / "backup-20250102-0300.db").write_bytes("свежая база".encode())
    monkeypatch.setattr(scheduler, "_backup_dir", lambda: bdir)
    set_setting("cloud.enabled", "1")
    set_setting("cloud.url", "https://dav.example")
    set_setting("cloud.encrypt_pass", "секрет-1")

    net = FakeNet()
    monkeypatch.setattr(cb, "_open", net)
    up = _client.post("/api/backups/cloud/upload")
    assert up.status_code == 200, up.text
    assert up.json()["name"] == "backup-20250102-0300.db.enc"
    assert any(c["method"] == "PUT" for c in net.calls)

    # положили в «облако» то, что теперь скачаем обратно
    plain = "восстановленная база".encode()
    net.files["backup-20241111-2222.db.enc"] = cb.encrypt_bytes(plain, "секрет-1")
    net.files["backup-20241111-2222.db.manifest.json"] = json.dumps(
        {"sha256": hashlib.sha256(plain).hexdigest()}).encode()
    dl = _client.get("/api/backups/cloud/download", params={"name": "backup-20241111-2222.db.enc"})
    assert dl.status_code == 200, dl.text
    assert (bdir / "backup-20241111-2222.db").read_bytes() == plain
    # файл виден существующему GET /api/backups → кнопка «восстановить» работает как раньше
    names = [b["name"] for b in _client.get("/api/backups").json()]
    assert "backup-20241111-2222.db" in names
    # без включённого тумблера отправка не работает
    set_setting("cloud.enabled", "0")
    assert _client.post("/api/backups/cloud/upload").status_code == 400


def test_api_test_connection(_client, fresh_db, monkeypatch):
    """POST /test: пустой адрес — честная ошибка, с адресом — PROPFIND/MKCOL без падений."""
    from core.services import cloud_backup as cb
    assert _client.post("/api/backups/cloud/test").json() == {"ok": False, "error": "адрес облака не задан"}
    monkeypatch.setattr(cb, "_open", FakeNet())
    r = _client.put("/api/backups/cloud", json={"url": "https://dav.example"})
    assert r.status_code == 200
    res = _client.post("/api/backups/cloud/test").json()
    assert res["ok"] is True and "jarvis-backups" in res["detail"]
    assert res["auth"] == "без авторизации"   # секреты в ответ не попадают ни в каком виде
