"""Уборка рабочего стола и «Загрузок» (выполняется на ПК внутри voice.bat).

Принцип: сначала план («что куда»), потом «да» — и только тогда переносим. Ничего не удаляем.
Файлы едут в `<папка>/Разобрано/<Категория>`, каждый перенос пишется в журнал, «отмени уборку» возвращает всё на место.

Не трогаем: папки, ярлыки (.lnk/.url), скрытые и системные файлы, недокачанное (.crdownload/.part/.tmp),
файлы, изменённые за последние 10 минут (вдруг ещё качается/сохраняется), и файлы, открытые сейчас в программе.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

log = logging.getLogger("assistant.tidy")
IS_WIN = sys.platform == "win32"

TIDY_DIR = "Разобрано"
FRESH_SEC = 10 * 60
SKIP_EXT = {".lnk", ".url", ".crdownload", ".part", ".tmp", ".download", ".ini", ".db"}
SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}

# порядок важен: первое совпадение побеждает
CATEGORIES: list[tuple[str, set[str]]] = [
    ("Проекты", {".aep", ".prproj", ".psd", ".psb", ".ai", ".indd", ".fig", ".blend", ".drp", ".c4d", ".prel", ".xd", ".sketch", ".afdesign", ".afphoto"}),
    ("Картинки", {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tif", ".tiff", ".svg", ".raw", ".cr2", ".nef", ".dng", ".arw"}),
    ("Видео", {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mts", ".wmv", ".mxf"}),
    ("Аудио", {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".aif", ".aiff"}),
    ("Документы", {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".epub", ".djvu", ".pages"}),
    ("Таблицы", {".xls", ".xlsx", ".csv", ".ods", ".numbers"}),
    ("Презентации", {".ppt", ".pptx", ".key", ".odp"}),
    ("Архивы", {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}),
    ("Установщики", {".exe", ".msi", ".msix", ".dmg", ".apk", ".appx"}),
    ("Шрифты", {".ttf", ".otf", ".woff", ".woff2"}),
    ("Код", {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".html", ".css", ".bat", ".ps1", ".sh", ".yaml", ".yml", ".sql", ".ipynb"}),
    ("Торренты", {".torrent"}),
]
SCREENSHOT_RX = re.compile(r"^(снимок экрана|screenshot|скриншот|screen shot|image_\d|photo_\d{4}|фото_\d|clip_?\d|запись экрана|screen recording)", re.I)
ROOT_TITLES = {"desktop": "Рабочий стол", "downloads": "Загрузки"}


# ---------------------------------------------------------------- где лежат папки
def known_folder(name: str) -> Path | None:
    """Настоящий путь «Рабочего стола»/«Загрузок» (Windows может держать их в OneDrive или на другом диске)."""
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes
            guids = {"desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]
            g = GUID()
            ctypes.windll.ole32.CLSIDFromString(guids[name], ctypes.byref(g))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
                p = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                if p.exists():
                    return p
        except Exception as e:  # pragma: no cover
            log.debug("known_folder %s: %s", name, e)
    p = Path.home() / ("Desktop" if name == "desktop" else "Downloads")
    return p if p.exists() else None


def roots_for(names: list[str]) -> dict[str, Path]:
    out = {}
    for n in names:
        p = known_folder(n)
        if p:
            out[n] = p
    return out


# ---------------------------------------------------------------- инвентаризация
def _hidden(p: Path) -> bool:
    if p.name.startswith(".") or p.name.startswith("~$"):
        return True
    if IS_WIN:
        try:
            return bool(os.stat(p).st_file_attributes & 0x6)   # HIDDEN | SYSTEM
        except OSError:
            return True
    return False


def _in_use(p: Path) -> bool:
    """Файл открыт в программе (Word, Premiere, архиватор…) — Windows не даст его записать/переместить."""
    try:
        with open(p, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def category(p: Path) -> str:
    if SCREENSHOT_RX.match(p.name) and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4", ".mov", ".gif", ".webp"}:
        return "Скриншоты"
    ext = p.suffix.lower()
    for name, exts in CATEGORIES:
        if ext in exts:
            return name
    return "Прочее"


def scan(root: Path, min_age_days: float = 0) -> dict:
    """Что лежит в папке верхнего уровня: план переноса + что пропускаем и почему."""
    now = time.time()
    moves, skipped = [], {"папки": 0, "ярлыки": 0, "скрытые": 0, "свежие": 0, "качаются": 0, "открыты": [], "старше нет": 0}
    try:
        entries = sorted(root.iterdir(), key=lambda x: x.name.lower())
    except OSError as e:
        log.warning("tidy scan %s: %s", root, e)
        return {"root": str(root), "moves": [], "skipped": skipped}
    for p in entries:
        if p.name == TIDY_DIR:
            continue
        if p.is_dir():
            skipped["папки"] += 1
            continue
        if p.suffix.lower() in (".crdownload", ".part", ".download"):
            skipped["качаются"] += 1
            continue
        if p.name.lower() in SKIP_NAMES:
            skipped["скрытые"] += 1
            continue
        if p.suffix.lower() in SKIP_EXT:
            skipped["ярлыки"] += 1
            continue
        if _hidden(p):
            skipped["скрытые"] += 1
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if now - st.st_mtime < FRESH_SEC:
            skipped["свежие"] += 1
            continue
        if min_age_days and now - st.st_mtime < min_age_days * 86400:
            skipped["старше нет"] += 1
            continue
        if _in_use(p):
            skipped["открыты"].append(p.name)
            continue
        cat = category(p)
        moves.append({"src": str(p), "dst": str(root / TIDY_DIR / cat / p.name), "cat": cat, "size": st.st_size})
    return {"root": str(root), "moves": moves, "skipped": skipped}


def make_plan(roots: dict[str, Path], data_dir: Path, min_age_days: float = 0) -> dict:
    plan = {"id": uuid.uuid4().hex[:8], "at": datetime.now().isoformat(timespec="seconds"), "parts": []}
    for name, root in roots.items():
        part = scan(root, min_age_days)
        part["name"] = name
        plan["parts"].append(part)
    plan["total"] = sum(len(p["moves"]) for p in plan["parts"])
    _plan_path(data_dir).parent.mkdir(parents=True, exist_ok=True)
    _plan_path(data_dir).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    return plan


def _plan_path(data_dir: Path) -> Path:
    return data_dir / "tidy_plan.json"


def _journal_path(data_dir: Path) -> Path:
    return data_dir / "tidy_journal.json"


def load_plan(data_dir: Path, plan_id: str | None = None) -> dict | None:
    try:
        plan = json.loads(_plan_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if plan_id and plan.get("id") != plan_id:
        return None
    return plan


# ---------------------------------------------------------------- текст плана
def _fmt_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit in ("Б", "КБ") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ГБ"


def plan_text(plan: dict, names_per_cat: int = 3) -> str:
    """План для чата/Telegram: по каждой папке — категории, сколько и примеры имён; что не трогаем."""
    if not plan["total"]:
        lines = []
        for part in plan["parts"]:
            sk = part["skipped"]
            why = ", ".join(x for x in [f"папок {sk['папки']}" if sk["папки"] else "", f"ярлыков {sk['ярлыки']}" if sk["ярлыки"] else "",
                                        f"открыто сейчас: {', '.join(sk['открыты'][:3])}" if sk["открыты"] else ""] if x)
            lines.append(f"{ROOT_TITLES.get(part['name'], part['name'])}: разбирать нечего" + (f" ({why})" if why else ""))
        return "🧹 " + " ".join(lines) + " Чисто."
    out = ["🧹 План уборки — ничего не удаляю, только переношу в папку «Разобрано»:"]
    for part in plan["parts"]:
        if not part["moves"] and not part["skipped"]["открыты"]:
            out.append(f"\n{ROOT_TITLES.get(part['name'], part['name'])}: чисто.")
            continue
        size = sum(m["size"] for m in part["moves"])
        out.append(f"\n{ROOT_TITLES.get(part['name'], part['name'])} — {len(part['moves'])} файл(ов), {_fmt_size(size)}:")
        by_cat: dict[str, list[str]] = {}
        for m in part["moves"]:
            by_cat.setdefault(m["cat"], []).append(Path(m["src"]).name)
        for cat, names in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
            sample = ", ".join(names[:names_per_cat]) + (f" … ещё {len(names) - names_per_cat}" if len(names) > names_per_cat else "")
            out.append(f"• {cat} ({len(names)}): {sample}")
        sk = part["skipped"]
        keep = [x for x in [f"папки ({sk['папки']})" if sk["папки"] else "", f"ярлыки ({sk['ярлыки']})" if sk["ярлыки"] else "",
                            f"свежие файлы ({sk['свежие']})" if sk["свежие"] else "", f"ещё качаются ({sk['качаются']})" if sk["качаются"] else "",
                            f"открыты сейчас: {', '.join(sk['открыты'][:3])}" if sk["открыты"] else ""] if x]
        if keep:
            out.append("  не трогаю: " + ", ".join(keep))
    out.append(f"\nВсего {plan['total']}. Убираем? «да» / «нет». Передумаете потом — «отмени уборку».")
    return "\n".join(out)


def plan_speech(plan: dict) -> str:
    """Короткая фраза для озвучки (полный список уходит в чат)."""
    if not plan["total"]:
        return "Разбирать нечего — чисто."
    parts = []
    for part in plan["parts"]:
        if part["moves"]:
            cats = len({m["cat"] for m in part["moves"]})
            parts.append(f"{ROOT_TITLES.get(part['name'], part['name']).lower()} — {len(part['moves'])} файлов в {cats} папок")
    return "Посмотрел: " + ", ".join(parts) + ". Список отправил в чат. Убираем?"


# ---------------------------------------------------------------- перенос и откат
def _free_name(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem, suf = dst.stem, dst.suffix
    for i in range(2, 1000):
        cand = dst.with_name(f"{stem} ({i}){suf}")
        if not cand.exists():
            return cand
    return dst.with_name(f"{stem} {uuid.uuid4().hex[:6]}{suf}")


def apply_plan(plan: dict, data_dir: Path) -> dict:
    """Перенести по плану. Возвращает {moved, busy, missing, journal_id}. Каждый перенос — в журнал."""
    moved, busy, missing = [], [], []
    for part in plan["parts"]:
        for m in part["moves"]:
            src, dst = Path(m["src"]), Path(m["dst"])
            if not src.exists():
                missing.append(src.name)
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst = _free_name(dst)
                os.replace(src, dst)
                moved.append({"from": str(src), "to": str(dst)})
            except PermissionError:
                busy.append(src.name)
            except OSError as e:
                log.warning("tidy move %s: %s", src, e)
                busy.append(src.name)
    entry = {"id": plan["id"], "at": datetime.now().isoformat(timespec="seconds"), "moves": moved}
    journal = _read_journal(data_dir)
    journal.append(entry)
    _journal_path(data_dir).write_text(json.dumps(journal[-20:], ensure_ascii=False), encoding="utf-8")
    try:
        _plan_path(data_dir).unlink()
    except OSError:
        pass
    return {"moved": len(moved), "busy": busy, "missing": missing, "journal_id": plan["id"], "cats": len({Path(x["to"]).parent.name for x in moved})}


def _read_journal(data_dir: Path) -> list[dict]:
    try:
        return json.loads(_journal_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def undo_last(data_dir: Path) -> dict:
    """Вернуть файлы последней уборки туда, где лежали. Пустые папки «Разобрано/…» убираем за собой."""
    journal = _read_journal(data_dir)
    if not journal:
        return {"restored": 0, "none": True}
    entry = journal.pop()
    restored, failed = 0, []
    for mv in reversed(entry["moves"]):
        src, dst = Path(mv["to"]), Path(mv["from"])
        if not src.exists():
            failed.append(src.name)
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, _free_name(dst))
            restored += 1
            for d in (src.parent, src.parent.parent):
                if d.name in (TIDY_DIR,) or d.parent.name == TIDY_DIR:
                    try:
                        d.rmdir()   # только если пустая
                    except OSError:
                        pass
        except OSError:
            failed.append(src.name)
    _journal_path(data_dir).write_text(json.dumps(journal, ensure_ascii=False), encoding="utf-8")
    return {"restored": restored, "failed": failed, "at": entry["at"]}


def done_text(res: dict) -> str:
    if not res["moved"] and not res["busy"]:
        return "Переносить уже нечего — файлы успели исчезнуть."
    t = f"✅ Убрал {res['moved']} файл(ов) в «Разобрано» ({res['cats']} папок)."
    if res["busy"]:
        t += f" Не дались (открыты): {', '.join(res['busy'][:5])}."
    if res["missing"]:
        t += f" Уже не было на месте: {len(res['missing'])}."
    return t + " Вернуть как было — «отмени уборку»."


def undo_text(res: dict) -> str:
    if res.get("none"):
        return "Нечего отменять — уборок ещё не было."
    try:
        when = datetime.fromisoformat(res["at"]).strftime("%d.%m в %H:%M")
    except (ValueError, KeyError):
        when = "недавно"
    t = f"↩️ Вернул {res['restored']} файл(ов) на место (уборка {when})."
    if res["failed"]:
        t += f" Не нашёл: {', '.join(res['failed'][:5])}."
    return t
