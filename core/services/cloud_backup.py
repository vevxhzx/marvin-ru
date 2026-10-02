# -*- coding: utf-8 -*-
"""Облачные бэкапы базы: WebDAV (Яндекс.Диск, Nextcloud) + шифрование AES-256-GCM.

Зачем: при смерти ПК или сломанной базе восстановиться из чужой папки. Снимок уходит
в облако зашифрованным, рядом — открытый манифест (только метаданные: имя, размер,
sha256 ДО шифрования, дата, версия приложения; самих данных в нём нет).

Формат файла:  magic(4) | salt(16) | nonce(12) | ciphertext(+16 байт тег GCM)
    ключ  = scrypt(пароль шифрования, salt, n=2**14, r=8, p=1) → 32 байта (AES-256);
    AAD   = метка magic, поэтому подмена заголовка ломает расшифровку, а не «тихо портит» данные.

Всё живёт в settings KV — config.yaml не трогаем, секреты туда не пишутся:
    cloud.enabled       — выключен по умолчанию: поведение без облака не меняется
    cloud.url           — адрес WebDAV: https://webdav.yandex.ru | .../remote.php/dav/files/user
    cloud.user          — логин; пусто + «пароль/токен» = Bearer (Яндекс.Диск: OAuth-токен)
    cloud.pass          — пароль WebDAV или OAuth-токен (если логин пуст)
    cloud.token         — то же отдельным полем; приоритет token → pass (новый пароль его затирает)
    cloud.dir           — каталог в облаке, по умолчанию /jarvis-backups
    cloud.encrypt_pass  — пароль шифрования; без него восстановление невозможно
    cloud.every_hours   — период автоматической отправки, по умолчанию 24
    cloud.keep          — сколько backup-*.enc держать в облаке, по умолчанию 10
    cloud.last_attempt / cloud.last_ok / cloud.last_error / cloud.last_uploaded — статус
Наружу (в API) секреты уходят только флагами «задан / не задан» — значения никогда.

Сеть: только stdlib urllib.request, таймаут 30 с, повтор 1 раз (PUT/MKCOL/DELETE
идемпотентны — повтор безопасен). Ошибки — по-русски, без секретов в логах.
"""
from __future__ import annotations

import base64
import hashlib
import json as _json
import logging
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..db import get_setting, set_setting

log = logging.getLogger("jarvis.cloud")

TIMEOUT = 30      # таймаут одного запроса, сек
RETRIES = 1       # повтор после сетевой ошибки / 5xx
MAGIC = b"JBK1"   # метка формата файла
SALT_LEN, NONCE_LEN = 16, 12
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}   # вывод ключа из пароля (~16 МБ, ~50 мс)
DEFAULTS = {"dir": "/jarvis-backups", "every_hours": 24, "keep": 10}
SECRET_KEYS = ("pass", "token", "encrypt_pass")   # в API — только «задан/не задан»
# своё в облаке только это: чужие файлы не листаем на удаление и не качаем
_REMOTE_RX = re.compile(r"^backup-(?:pre-restore-)?\d{8}-\d{4}\.db(?:\.enc|\.manifest\.json)?$")

_MKCOL_BODY = (b'<?xml version="1.0" encoding="utf-8"?>'
               b'<d:mkcol xmlns:d="DAV:"><d:set><d:prop><d:resourcetype>'
               b'<d:collection/></d:resourcetype></d:set></d:mkcol>')
_PROPFIND_BODY = (b'<?xml version="1.0" encoding="utf-8"?>'
                  b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/>'
                  b'<d:getcontentlength/><d:getlastmodified/></d:prop></d:propfind>')
_XML_HEADERS = {"Content-Type": "application/xml; charset=utf-8"}

_HTTP_ERRORS = {
    401: "доступ отклонён (401): неверный логин/пароль или токен",
    403: "нет прав (403): проверьте доступ к каталогу на сервере",
    404: "не найдено (404): проверьте адрес WebDAV и каталог",
    405: "сервер не поддерживает эту операцию (405)",
    409: "конфликт (409): нет родительского каталога или файл уже существует",
    412: "сервер отклонил запрос (412)",
    423: "ресурс занят другим процессом (423)",
    507: "недостаточно места в облаке (507)",
}


class CloudError(Exception):
    """Ошибка облака с понятным человеку текстом (в сообщении нет паролей и токенов)."""


# ------------------------------------------------------------------ настройки (settings KV)
def _s(key: str, default: str = "") -> str:
    v = get_setting(f"cloud.{key}")
    return default if v is None else v


def load_cfg() -> dict:
    """Текущие настройки облака (со всеми секретами — только для внутреннего use)."""
    def _int(key: str, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(_s(key) or DEFAULTS[key])))
        except ValueError:
            return DEFAULTS[key]
    return {
        "enabled": _s("enabled") == "1",
        "url": _s("url").strip(),
        "user": _s("user").strip(),
        "pass": _s("pass"),
        "token": _s("token"),
        "dir": _s("dir").strip() or DEFAULTS["dir"],
        "encrypt_pass": _s("encrypt_pass"),
        "every_hours": _int("every_hours", 1, 720),
        "keep": _int("keep", 1, 1000),
    }


def enabled() -> bool:
    return load_cfg()["enabled"]


def save_settings(changes: dict) -> dict:
    """Сохранить настройки. Пустая строка в секретах = «не менять»; ValueError → 400 в API."""
    known = ("enabled", "url", "user", "pass", "token", "encrypt_pass", "dir", "every_hours", "keep")
    ch = {k: v for k, v in (changes or {}).items() if k in known}
    if not ch:
        raise ValueError("нет ни одного известного поля настроек")
    cur = load_cfg()
    on = bool(ch["enabled"]) if "enabled" in ch else cur["enabled"]
    url = str(ch.get("url", cur["url"])).strip()
    if url and not url.lower().startswith(("http://", "https://")):
        raise ValueError("адрес должен начинаться с http:// или https://")
    if on and not url:
        raise ValueError("укажите адрес WebDAV — без него отправлять некуда")
    # секреты: пусто/None — не меняем (фронт отдаёт пустую строку, если поле не трогали)
    for k in SECRET_KEYS:
        if k in ch and (str(ch.get(k) or "").strip()):
            set_setting(f"cloud.{k}", str(ch[k]).strip())
    # одно поле «пароль/токен» в UI: новый пароль затирает прежний токен, иначе token имеет приоритет
    if "pass" in ch and str(ch.get("pass") or "").strip():
        set_setting("cloud.token", None)
    if "url" in ch:
        set_setting("cloud.url", url)
    if "user" in ch:
        set_setting("cloud.user", str(ch.get("user") or "").strip())
    if "dir" in ch:
        d = str(ch.get("dir") or "").strip() or DEFAULTS["dir"]
        if not d.startswith("/"):
            d = "/" + d
        if re.search(r"[\\?#]", d):
            raise ValueError("в каталоге не должно быть \\, ? и #")
        set_setting("cloud.dir", d)
    if "enabled" in ch:
        set_setting("cloud.enabled", "1" if on else "0")
    for k, lo, hi in (("every_hours", 1, 720), ("keep", 1, 1000)):
        if k in ch:
            try:
                v = int(str(ch[k]).strip() or DEFAULTS[k])
            except ValueError:
                raise ValueError(f"{k}: ожидается целое число")
            set_setting(f"cloud.{k}", str(max(lo, min(hi, v))))
    return status(remote=False)


def status(remote: bool = True) -> dict:
    """Ответ GET /api/backups/cloud: без секретов, только «задан/не задан»."""
    cfg = load_cfg()
    out = {
        "enabled": cfg["enabled"],
        "configured": bool(cfg["url"]),
        "url": cfg["url"],
        "user": cfg["user"],
        "dir": cfg["dir"],
        "every_hours": cfg["every_hours"],
        "keep": cfg["keep"],
        "pass_set": bool(cfg["pass"] or cfg["token"]),
        "token_set": bool(cfg["token"]),
        "encrypt_pass_set": bool(cfg["encrypt_pass"]),
        "last_attempt": get_setting("cloud.last_attempt"),
        "last_ok": get_setting("cloud.last_ok"),
        "last_error": get_setting("cloud.last_error") or None,
        "last_uploaded": _json_obj(get_setting("cloud.last_uploaded")),
        "remote": [],
        "list_error": None,
    }
    # список файлов в облаке — только когда включено; выключено = ни одного сетевого запроса
    if remote and cfg["enabled"] and cfg["url"]:
        try:
            out["remote"] = [f for f in list_remote(cfg) if not f["name"].endswith(".manifest.json")]
        except Exception as e:
            out["list_error"] = str(e)
            log.warning("список файлов в облаке недоступен: %s", e)
    return out


def _json_obj(raw: str | None) -> dict | None:
    try:
        v = _json.loads(raw) if raw else None
        return v if isinstance(v, dict) else None
    except (ValueError, TypeError):
        return None


def _record(ok: bool, error: object = "", uploaded: dict | None = None) -> None:
    """Статус попытки в settings (его отдают GET /api/backups/cloud). Секретов в тексте нет."""
    now = datetime.now().isoformat(timespec="seconds")
    set_setting("cloud.last_attempt", now)
    if ok:
        set_setting("cloud.last_ok", now)
        set_setting("cloud.last_error", None)
        if uploaded:
            set_setting("cloud.last_uploaded", _json.dumps(uploaded, ensure_ascii=False))
    else:
        set_setting("cloud.last_error", str(error)[:500])


def due() -> bool:
    """Пора ли отправлять: прошло cloud.every_hours с последней ПОПЫТКИ (в т.ч. неудачной)."""
    raw = get_setting("cloud.last_attempt")
    if not raw:
        return True
    try:
        last = datetime.fromisoformat(raw)
    except ValueError:
        return True
    return datetime.now() - last >= timedelta(hours=load_cfg()["every_hours"])


# ------------------------------------------------------------------ шифрование
def _key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT)


def encrypt_bytes(data: bytes, password: str) -> bytes:
    """Байты → magic(4) | salt(16) | nonce(12) | ciphertext+tag."""
    if not password:
        raise ValueError("пароль шифрования не задан — без него восстановление невозможно")
    salt, nonce = secrets.token_bytes(SALT_LEN), secrets.token_bytes(NONCE_LEN)
    ct = AESGCM(_key(password, salt)).encrypt(nonce, data, MAGIC)
    return MAGIC + salt + nonce + ct


def decrypt_bytes(blob: bytes, password: str) -> bytes:
    """Расшифровка. Неверный пароль/порча — ValueError, а не тихая порча данных (GCM ловит тег)."""
    if len(blob) < 4 + SALT_LEN + NONCE_LEN + 16:
        raise ValueError("файл слишком короткий — не похож на зашифрованный бэкап")
    if blob[:4] != MAGIC:
        raise ValueError("не тот формат файла (нет метки JBK1)")
    salt, nonce, ct = blob[4:4 + SALT_LEN], blob[4 + SALT_LEN:4 + SALT_LEN + NONCE_LEN], blob[4 + SALT_LEN + NONCE_LEN:]
    try:
        return AESGCM(_key(password, salt)).decrypt(nonce, ct, MAGIC)
    except InvalidTag:
        raise ValueError("неверный пароль шифрования или файл повреждён") from None
    except ValueError as e:   # например, битая длина nonce от «рук» сломанного файла
        raise ValueError(f"не удалось расшифровать: {e}") from None


def decrypt_file(path, password, dest=None):
    """Расшифровать файл. dest не задан → bytes; задан → записать по пути и вернуть Path."""
    blob = Path(path).read_bytes()
    data = decrypt_bytes(blob, password)
    if dest is None:
        return data
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def sha256(path) -> str:
    """sha256 файла (hex) — тем же числом лежит в манифесте, сверяется при скачивании."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ WebDAV на stdlib
def _auth(cfg: dict) -> str | None:
    """Bearer, если задан токен (или пароль без логина — «токен в поле пароля»), иначе Basic."""
    token = (cfg.get("token") or "").strip()
    user = (cfg.get("user") or "").strip()
    pw = cfg.get("pass") or ""
    if token:
        return "Bearer " + token
    if pw and not user:
        return "Bearer " + pw
    if user or pw:
        raw = f"{user}:{pw}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")
    return None


def _open(req, timeout=TIMEOUT):
    """Отдельная точка выхода в сеть — тесты мокают именно её."""
    return urllib.request.urlopen(req, timeout=timeout)


def _err_text(code: int, method: str) -> str:
    return f"{_HTTP_ERRORS.get(code, f'сервер облака ответил ошибкой {code}')} · {method}"


def _request(cfg, method, url, data=None, headers=None, allow=()):
    """Один запрос: авторизация, таймаут 30 с, повтор 1 раз при сетевой ошибке или 5xx.

    allow — коды, которые не считаются ошибкой (404 при проверке, 405 у MKCOL и т.п.).
    Возвращает (код, тело, заголовки); прочие ошибки → CloudError с русским текстом."""
    h = {"User-Agent": "jarvis-backup", "Accept": "*/*"}
    auth = _auth(cfg)
    if auth:
        h["Authorization"] = auth
    if headers:
        h.update(headers)
    last: Exception | None = None
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            resp = _open(req, TIMEOUT)
            try:
                body = resp.read()
                code = int(getattr(resp, "status", None) or resp.getcode() or 200)
                rh = dict(resp.headers or {})
            finally:
                close = getattr(resp, "close", None)
                if close:
                    close()
            return code, body, rh
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:
                pass
            if e.code in allow:
                return int(e.code), body, dict(e.headers or {})
            if e.code < 500 or attempt >= RETRIES:
                raise CloudError(_err_text(e.code, method)) from None
            last = CloudError(_err_text(e.code, method))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            log.warning("webdav %s (попытка %d/%d): %s", method, attempt + 1, RETRIES + 1, e)
    raise CloudError(f"нет связи с облаком: {last}")


def _base_url(cfg) -> str:
    url = (cfg.get("url") or "").rstrip("/")
    if not url:
        raise ValueError("адрес облака не задан")
    return url


def _dir_url(cfg) -> str:
    parts = [p for p in (cfg.get("dir") or DEFAULTS["dir"]).strip("/").split("/") if p]
    return _base_url(cfg) + "".join("/" + urllib.parse.quote(urllib.parse.unquote(p)) for p in parts)


def _file_url(cfg, name: str) -> str:
    return _dir_url(cfg) + "/" + urllib.parse.quote(name)


def _propfind(cfg, url: str, depth: str) -> tuple[int, bytes]:
    return _request(cfg, "PROPFIND", url, data=_PROPFIND_BODY,
                    headers={**_XML_HEADERS, "Depth": depth}, allow=(404,))[:2]


def _exists(cfg, url: str) -> bool:
    code, _ = _propfind(cfg, url, "0")
    return code != 404


def ensure_dir(cfg, dirpath: str) -> None:
    """MKCOL по частям — промежуточные каталоги создаём сами; существующий не ошибка."""
    parts = [p for p in (dirpath or "").strip("/").split("/") if p]
    cur = ""
    for p in parts:
        cur += "/" + urllib.parse.quote(urllib.parse.unquote(p))
        url = _base_url(cfg) + cur
        _request(cfg, "MKCOL", url, data=_MKCOL_BODY, headers=_XML_HEADERS,
                 allow=(400, 405, 409, 415))
        if not _exists(cfg, url):
            # часть серверов не принимает тело MKCOL — пробуем пустым
            _request(cfg, "MKCOL", url, allow=(405, 409))
            if not _exists(cfg, url):
                raise CloudError(f"не удалось создать каталог {cur}: нет прав на запись")


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _child_text(el, name: str) -> str | None:
    for c in el:
        if _local(c.tag) == name:
            return (c.text or "").strip() or None
    return None


def _httpdate(raw: str) -> str:
    """HTTP-дата (RFC 1123) → ISO; не разобралась — возвращаем как есть."""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        return raw


def _parse_propfind(body: bytes) -> list[dict]:
    """207 Multi-Status → [{name, size, mtime, dir}]. Пространства имён любые (local-name)."""
    out: list[dict] = []
    root = ET.fromstring(body)
    for resp in root:
        if _local(resp.tag) != "response":
            continue
        href = _child_text(resp, "href") or ""
        if not href:
            continue
        name = urllib.parse.unquote(href.rstrip("/").split("/")[-1])
        size, mtime, is_dir = 0, None, False
        for ps in resp:
            if _local(ps.tag) != "propstat":
                continue
            st = _child_text(ps, "status") or ""
            if st and " 200 " not in st:   # непропавшие свойства не читаем
                continue
            for ps_child in ps:
                if _local(ps_child.tag) != "prop":
                    continue
                for pe in ps_child:
                    ln = _local(pe.tag)
                    if ln == "resourcetype":
                        is_dir = any(_local(c.tag) == "collection" for c in pe)
                    elif ln == "getcontentlength" and pe.text:
                        try:
                            size = int(pe.text)
                        except ValueError:
                            pass
                    elif ln == "getlastmodified" and pe.text:
                        mtime = _httpdate(pe.text.strip())
        out.append({"name": name, "size": size, "mtime": mtime, "dir": is_dir})
    return out


def list_remote(cfg=None) -> list[dict]:
    """Файлы в каталоге облака: имя, размер, дата (новые сверху). Каталога нет → []."""
    cfg = cfg if cfg is not None else load_cfg()
    code, body = _propfind(cfg, _dir_url(cfg), "1")
    if code == 404:
        return []
    items = [i for i in _parse_propfind(body) if not i["dir"] and i["name"]]
    items.sort(key=lambda i: i["name"], reverse=True)   # имя содержит дату — сортировка как по времени
    return items


def verify_connection(cfg=None) -> dict:
    """«Проверить соединение»: доступ к корню, создание каталога, список файлов. Секретов в ответе нет."""
    cfg = cfg if cfg is not None else load_cfg()
    if not cfg.get("url"):
        return {"ok": False, "error": "адрес облака не задан"}
    auth = _auth(cfg)
    try:
        code, _ = _propfind(cfg, _base_url(cfg) + "/", "0")
        if code == 404:
            return {"ok": False, "error": "адрес не найден (404): проверьте URL"}
        ensure_dir(cfg, cfg["dir"])
        files = [f for f in list_remote(cfg) if not f["name"].endswith(".manifest.json")]
        return {"ok": True, "detail": f"каталог {cfg['dir']} доступен, файлов: {len(files)}",
                "files": len(files),
                "auth": "bearer-токен" if auth and auth.startswith("Bearer") else ("логин+пароль" if auth else "без авторизации")}
    except (CloudError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:   # неожиданное — тоже честно, но без падения роута
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------------ файлы
def _check_name(name: str) -> str:
    """Только свои backup-*.db(.enc/.manifest.json), без path traversal."""
    name = (name or "").strip()
    if not _REMOTE_RX.match(name) or "/" in name or "\\" in name or ".." in name:
        raise ValueError("Неверное имя файла")
    return name


def upload_backup(path, cfg=None) -> dict:
    """Снимок → .enc (AES-256-GCM) + manifest.json → PUT → ротация по cloud.keep."""
    cfg = cfg if cfg is not None else load_cfg()
    if not (cfg.get("url") or ""):
        raise ValueError("адрес облака не задан")
    password = cfg.get("encrypt_pass") or ""
    if not password:
        raise ValueError("пароль шифрования не задан — без него восстановление невозможно")
    src = Path(path)
    if not src.is_file():
        raise LookupError(f"файла бэкапа нет: {src.name}")
    data = src.read_bytes()
    enc = encrypt_bytes(data, password)
    manifest = {
        "file": src.name + ".enc",
        "source": src.name,
        "size": len(data),
        "enc_size": len(enc),
        "sha256": _sha256(data),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "app": "jarvis",
        "version": _app_version(),
        "format": "aes-256-gcm/scrypt",
    }
    try:
        ensure_dir(cfg, cfg["dir"])
        _request(cfg, "PUT", _file_url(cfg, src.name + ".enc"), data=enc,
                 headers={"Content-Type": "application/octet-stream"})
        _request(cfg, "PUT", _file_url(cfg, src.name + ".manifest.json"),
                 data=_json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8"),
                 headers={"Content-Type": "application/json; charset=utf-8"})
        removed = _rotate(cfg)
    except Exception as e:
        _record(False, e)
        raise
    at = datetime.now().isoformat(timespec="seconds")
    _record(True, uploaded={"name": src.name + ".enc", "at": at, "size": len(data)})
    log.info("облачный бэкап: %s → %s (%d → %d Б, удалено старых: %d)",
             src.name, cfg["dir"], len(data), len(enc), removed)
    return {"ok": True, "name": src.name + ".enc", "source": src.name, "size": len(data),
            "enc_size": len(enc), "sha256": manifest["sha256"], "rotated": removed, "at": at}


def _app_version() -> str:
    try:
        from .. import VERSION
        return str(VERSION)
    except Exception:   # pragma: no cover — версия не должна ломать отправку
        return "unknown"


def _rotate(cfg) -> int:
    """Держать в облаке не больше cloud.keep своих backup-*.enc (удаляются вместе с манифестом)."""
    keep = int(cfg.get("keep") or DEFAULTS["keep"])
    files = [f for f in list_remote(cfg) if f["name"].endswith(".enc") and _REMOTE_RX.match(f["name"])]
    files.sort(key=lambda f: f["name"], reverse=True)   # имя содержит дату
    removed = 0
    for f in files[keep:]:
        try:
            delete_remote(f["name"], cfg)
            removed += 1
        except (CloudError, ValueError) as e:
            log.warning("ротация в облаке: %s не удалился: %s", f["name"], e)
    return removed


def delete_remote(name, cfg=None) -> dict:
    """Удалить файл из облака (404 = уже нет — ок). Только свои backup-*."""
    cfg = cfg if cfg is not None else load_cfg()
    name = _check_name(name)
    targets = [name] + ([name[:-4] + ".manifest.json"] if name.endswith(".enc") else [])
    for t in targets:
        _request(cfg, "DELETE", _file_url(cfg, t), allow=(404,))
    return {"ok": True, "deleted": targets}


def download_remote(name, dest, cfg=None) -> dict:
    """Скачать файл из облака в dest; .enc расшифровывается сразу (sha256 сверяется с манифестом)."""
    cfg = cfg if cfg is not None else load_cfg()
    name = _check_name(name)
    dest = Path(dest)
    code, body, _ = _request(cfg, "GET", _file_url(cfg, name), allow=(404,))
    if code == 404:
        raise LookupError("в облаке такого файла нет")
    if name.endswith(".enc"):
        manifest = None
        mcode, mbody, _ = _request(cfg, "GET", _file_url(cfg, name[:-4] + ".manifest.json"), allow=(404,))
        if mcode != 404:
            manifest = _json_obj(mbody.decode("utf-8", "replace"))
        password = cfg.get("encrypt_pass") or ""
        if not password:
            raise ValueError("пароль шифрования не задан — файл не расшифровать")
        data = decrypt_bytes(body, password)
        want = (manifest or {}).get("sha256")
        if want and _sha256(data) != want:
            raise ValueError("контрольная сумма не совпала — файл повреждён или манифест чужой")
    else:
        data = body
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")   # атомарно: полфайла не должно остаться
    tmp.write_bytes(data)
    tmp.replace(dest)
    return {"ok": True, "name": name, "path": str(dest), "local": dest.name, "size": len(data)}


def download_to_backups(name) -> dict:
    """Скачать в локальные backups/ (шифрованный — расшифровать в .db):
    дальше файл подхватывает существующая кнопка «восстановить из бэкапа»."""
    from . import scheduler
    name = _check_name(name)
    local = name[:-4] if name.endswith(".enc") else name   # .enc → .db, чтобы годился для restore
    dest = scheduler._backup_dir() / local
    res = download_remote(name, dest)
    log.info("облачный бэкап скачан: %s → %s", name, dest.name)
    return res


def upload_latest(create: bool = True) -> dict:
    """Самый свежий локальный снимок в облако. Выключено → ValueError и ни одного запроса."""
    cfg = load_cfg()
    if not cfg["enabled"]:
        raise ValueError("облачные бэкапы выключены")
    from . import scheduler
    path = None
    items = [b for b in scheduler.list_backups(limit=50) if b["kind"] == "db"]
    if items:
        try:
            path = scheduler.resolve_backup_file(items[0]["name"])
        except (LookupError, ValueError):
            path = None
    if path is None and create:
        path = scheduler.backup_db(force=True)   # локального снимка нет — сначала делаем
    if path is None:
        raise LookupError("нет локального бэкапа — нечего отправлять")
    return upload_backup(path, cfg)
