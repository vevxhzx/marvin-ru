"""Доска — бесконечный лист для раскадровок, сценариев и раскладки мыслей.

Что это и чего не делает: не Miro. Пять типов объектов (стикер, текст, кадр, картинка, стрелка) плюс карандаш.
Всё хранится в базе ассистента, поэтому он видит содержимое: «что у меня по сториборду ролика?»,
«кинь на доску: …». Картинки — в data/media, как у заметок.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime

from sqlmodel import select

from ..db import Aim, Board, BoardItem, Link, Note, Order, icontains, log_action, now, remember, session

TYPES = ("sticky", "text", "frame", "image", "arrow", "ink")
KINDS = ("free", "storyboard", "script")
RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5, "4:3": 4 / 3, "2.39:1": 2.39}
STICKY_COLORS = ("yellow", "pink", "blue", "green", "purple", "gray")
MAX_ITEMS = 5000
MAX_TEXT = 20000
MAX_INK_POINTS = 4000
FRAME_W = 320          # ширина кадра по умолчанию (px холста)
FRAME_GAP = 28

SCRIPT_TEMPLATE = (
    "# Название\n\n"
    "СЦЕНА 1 · ИНТ. СТУДИЯ — ДЕНЬ\n\n"
    "Краткое описание места и действия.\n\n"
    "ГЕРОЙ\n"
    "Реплика.\n\n"
    "СЦЕНА 2 · НАТ. УЛИЦА — ВЕЧЕР\n\n"
)


# ---------------------------------------------------------------- доски
def _bust() -> None:
    from .orders import _boards_by_order
    _boards_by_order.__dict__.pop("at", None)


def _out(b: Board, items: int | None = None) -> dict:
    d = {"id": b.id, "title": b.title, "kind": b.kind, "order_id": b.order_id, "aim_id": b.aim_id,
         "archived": b.archived, "revision": b.revision, "created_at": b.created_at, "updated_at": b.updated_at}
    try:
        d["view"] = json.loads(b.view or "{}")
    except ValueError:
        d["view"] = {}
    if items is not None:
        d["items"] = items
    return d


def list_boards(archived: bool = False) -> list[dict]:
    with session() as s:
        rows = s.exec(select(Board).where(Board.archived == archived).order_by(Board.updated_at.desc())).all()  # noqa: E712
        out = []
        for b in rows:
            n = len(s.exec(select(BoardItem.id).where(BoardItem.board_id == b.id)).all())
            d = _out(b, n)
            # обложка: первая картинка/кадр с картинкой
            pic = s.exec(select(BoardItem).where(BoardItem.board_id == b.id, BoardItem.type.in_(("image", "frame")))  # type: ignore[attr-defined]
                         .order_by(BoardItem.updated_at.desc()).limit(12)).all()
            cover = None
            for it in pic:
                src = _data(it).get("src") or _data(it).get("image")
                if src:
                    cover = src
                    break
            d["cover"] = cover
            if b.order_id:
                o = s.get(Order, b.order_id)
                d["order_title"] = o.title if o else None
            if b.aim_id:
                a = s.get(Aim, b.aim_id)
                d["aim_title"] = a.title if a else None
            out.append(d)
        return out


def get_board(bid: int) -> dict | None:
    with session() as s:
        b = s.get(Board, bid)
        if not b:
            return None
        items = s.exec(select(BoardItem).where(BoardItem.board_id == bid).order_by(BoardItem.z, BoardItem.id)).all()
        d = _out(b)
        d["items"] = [item_out(i) for i in items]
        if b.order_id:
            o = s.get(Order, b.order_id)
            d["order_title"] = o.title if o else None
        if b.aim_id:
            a = s.get(Aim, b.aim_id)
            d["aim_title"] = a.title if a else None
        return d


def add_board(title: str, kind: str = "free", order_id: int | None = None, aim_id: int | None = None,
              frames: int = 0, ratio: str = "16:9", source: str = "web") -> Board:
    title = (title or "").strip()[:120]
    if not title:
        raise ValueError("Нужно название доски")
    kind = kind if kind in KINDS else "free"
    with session() as s:
        if order_id and not s.get(Order, order_id):
            raise ValueError("Заказ не найден")
        if aim_id and not s.get(Aim, aim_id):
            raise ValueError("Цель не найдена")
        b = Board(title=title, kind=kind, order_id=order_id, aim_id=aim_id)
        s.add(b); s.commit(); s.refresh(b)
        if kind == "storyboard" and frames:
            _seed_frames(s, b.id, min(int(frames), 60), ratio)
        elif kind == "script":
            s.add(BoardItem(board_id=b.id, type="text", x=0, y=0, w=720, h=900, data=json.dumps({"text": SCRIPT_TEMPLATE, "size": "md"})))
        remember(s, "board", f"Новая доска «{b.title}»", "board", b.id)
        log_action(s, "add_board", "board", b.id, b.title, source)
        s.commit(); s.refresh(b)
        _bust()
        return b


def _seed_frames(s, bid: int, n: int, ratio: str) -> None:
    r = RATIOS.get(ratio, 16 / 9)
    w = FRAME_W; h = round(w / r) + 44
    per_row = 4 if r >= 1 else 6
    for i in range(n):
        s.add(BoardItem(board_id=bid, type="frame", x=(i % per_row) * (w + FRAME_GAP), y=(i // per_row) * (h + FRAME_GAP + 40),
                        w=w, h=h, z=i, data=json.dumps({"label": "", "ratio": ratio, "image": None, "seconds": 0, "n": i + 1})))


def update_board(bid: int, **fields) -> Board | None:
    with session() as s:
        b = s.get(Board, bid)
        if not b:
            return None
        for k, v in fields.items():
            if v is None:
                continue
            if k == "title":
                b.title = str(v).strip()[:120] or b.title
            elif k == "kind" and v in KINDS:
                b.kind = v
            elif k == "view":
                b.view = json.dumps({kk: number(v[kk], .05 if kk == "k" else -1000000, 8 if kk == "k" else 1000000) for kk in ("x", "y", "k") if kk in v})
            elif k == "archived":
                b.archived = bool(v)
            elif k == "order_id":
                if v and not s.get(Order, int(v)):
                    raise ValueError("Заказ не найден")
                b.order_id = int(v) or None
            elif k == "aim_id":
                if v and not s.get(Aim, int(v)):
                    raise ValueError("Цель не найдена")
                b.aim_id = int(v) or None
        if any(k != "view" for k in fields):
            b.updated_at = now(); b.revision += 1
        s.add(b); s.commit(); s.refresh(b)
        _bust()
        return b


def delete_board(bid: int) -> bool:
    """Доска не удаляется физически — уходит в архив (данные не теряем)."""
    with session() as s:
        b = s.get(Board, bid)
        if not b:
            return False
        b.archived = True; b.updated_at = now(); b.revision += 1
        s.add(b); remember(s, "board", f"Доска «{b.title}» в архиве", "board", b.id); s.commit()
        _bust()
        return True


def find_board(q: str) -> Board | None:
    q = (q or "").strip(" .«»\"")
    if not q:
        return None
    with session() as s:
        if q.isdigit():
            return s.get(Board, int(q))
        rows = s.exec(select(Board).where(Board.archived == False).order_by(Board.updated_at.desc())).all()  # noqa: E712
        ql = q.lower()
        for b in rows:
            if b.title.lower() == ql:
                return b
        for b in rows:
            if ql in b.title.lower() or b.title.lower() in ql:
                return b
        # доска заказа по названию заказа
        for b in rows:
            if b.order_id:
                o = s.get(Order, b.order_id)
                if o and (ql in o.title.lower() or o.title.lower() in ql):
                    return b
        return None


def board_for_order(order_id: int, create: bool = False) -> Board | None:
    with session() as s:
        b = s.exec(select(Board).where(Board.order_id == order_id, Board.archived == False)).first()  # noqa: E712
        if b or not create:
            return b
        o = s.get(Order, order_id)
        if not o:
            return None
    return add_board(o.title, "storyboard", order_id=order_id, frames=0)


# ---------------------------------------------------------------- объекты
def _data(it: BoardItem) -> dict:
    try:
        return json.loads(it.data or "{}")
    except ValueError:
        return {}


def item_out(it: BoardItem) -> dict:
    d = _data(it)
    return {"id": it.id, "type": it.type, "x": it.x, "y": it.y, "w": it.w,
            "h": frame_height(it.w, d) if it.type == "frame" else it.h, "z": it.z, "rot": it.rot,
            "data": d, "note_id": it.note_id, "link_id": it.link_id, "updated_at": it.updated_at}


def number(v, low=-1000000, high=1000000) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Ожидалось число") from None
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError(f"Число должно быть от {low:g} до {high:g}")
    return n


def frame_height(w: float, data: dict) -> float:
    # Та же геометрия в web/src/lib/board.js: изображение + масштабируемая подпись.
    scale = w / 320
    size = float(data.get("font_size", 18))
    chars = max(1, int(292 / (size * .56)))
    lines = sum(max(1, math.ceil(len(line) / chars)) for line in str(data.get("label", "")).split("\n"))
    caption = max(54, min(8, lines) * size * 1.35 + 22) * scale
    return w / RATIOS.get(data.get("ratio"), 16 / 9) + caption


def color(v, fallback="ink") -> str:
    if isinstance(v, str) and (v in (*STICKY_COLORS, "ink", "accent", "red", "warn", "white", "black", "transparent") or re.fullmatch(r"#[0-9a-fA-F]{6}", v)):
        return v
    return fallback


def text_style(d: dict) -> dict:
    out = {}
    if "font" in d:
        out["font"] = d["font"] if d["font"] in ("inter", "arial", "serif", "mono") else "inter"
    if "font_size" in d:
        out["font_size"] = number(d["font_size"], 8, 240)
    if "text_color" in d:
        out["text_color"] = color(d["text_color"])
    if "align" in d:
        out["align"] = d["align"] if d["align"] in ("left", "center", "right") else "left"
    for k in ("bold", "italic"):
        if k in d:
            out[k] = bool(d[k])
    return out


def _clean_data(t: str, d: dict) -> dict:
    if not isinstance(d, dict):
        raise ValueError("Данные объекта должны быть объектом JSON")
    style = text_style(d) if t in ("sticky", "text", "frame", "arrow") else {}
    if t == "sticky":
        out = {"text": str(d.get("text", ""))[:MAX_TEXT], "color": color(d.get("color"), "yellow")}
    elif t == "text":
        out = {"text": str(d.get("text", ""))[:MAX_TEXT], "size": d.get("size") if d.get("size") in ("sm", "md", "lg", "xl") else "md"}
    elif t == "frame":
        out = {"label": str(d.get("label", ""))[:2000], "ratio": d.get("ratio") if d.get("ratio") in RATIOS else "16:9",
               "image": _safe_src(d.get("image")), "seconds": number(d.get("seconds") or 0, 0, 3600),
               "n": int(number(d.get("n") or 0, 0, MAX_ITEMS))}
    elif t == "image":
        out = {"src": _safe_src(d.get("src")), "label": str(d.get("label", ""))[:300]}
    elif t == "arrow":
        out = {"from": _endpoint(d.get("from")), "to": _endpoint(d.get("to")), "label": str(d.get("label", ""))[:120],
               "style": d.get("style") if d.get("style") in ("arrow", "line") else "arrow"}
        if "color" in d:
            out["color"] = color(d["color"])
        if "width" in d:
            out["width"] = number(d["width"], 1, 24)
    elif t == "ink":
        pts = d.get("points") or []
        if not isinstance(pts, list) or len(pts) > MAX_INK_POINTS:
            raise ValueError(f"Штрих: не более {MAX_INK_POINTS} точек")
        if any(not isinstance(p, (list, tuple)) or len(p) < 2 for p in pts):
            raise ValueError("Неверные точки штриха")
        out = {"points": [[round(number(p[0]), 3), round(number(p[1]), 3)] for p in pts],
               "color": color(d.get("color")), "width": number(d.get("width") or 3, 1, 24)}
    else:
        raise ValueError("Неизвестный тип объекта")
    return {**out, **style}


def _safe_src(v) -> str | None:
    """Только относительный путь в data/media (как у заметок) — никаких внешних URL и data:."""
    if not v:
        return None
    v = str(v)
    if v.startswith("/media/"):
        v = v[len("/media/"):]
    if re.fullmatch(r"[\w\-./]+", v) and ".." not in v:
        return v
    return None


def _endpoint(v) -> dict | None:
    if v is None:
        return None
    if not isinstance(v, dict):
        raise ValueError("Неверный конец стрелки")
    if "item" in v:
        out = {"item": int(number(v["item"], -2**53 + 1, 2**53 - 1))}
        if "u" in v and "v" in v:
            out.update(u=number(v["u"], 0, 1), v=number(v["v"], 0, 1))
        return out
    if "x" in v and "y" in v:
        return {"x": number(v["x"]), "y": number(v["y"])}
    raise ValueError("Неверный конец стрелки")


def add_item(bid: int, type: str, x: float = 0, y: float = 0, w: float | None = None, h: float | None = None,
             data: dict | None = None, z: int | None = None, rot: float = 0, note_id: int | None = None, link_id: int | None = None) -> BoardItem:
    if type not in TYPES:
        raise ValueError(f"Тип объекта: {', '.join(TYPES)}")
    with session() as s:
        b = s.get(Board, bid)
        if not b:
            raise ValueError("Доска не найдена")
        cnt = len(s.exec(select(BoardItem.id).where(BoardItem.board_id == bid)).all())
        if cnt >= MAX_ITEMS:
            raise ValueError(f"На доске уже {MAX_ITEMS} объектов — заведите вторую")
        if z is None:
            top = s.exec(select(BoardItem.z).where(BoardItem.board_id == bid).order_by(BoardItem.z.desc()).limit(1)).first()
            z = (top or 0) + 1
        dw, dh = DEFAULT_SIZE.get(type, (200, 120))
        if type == "frame":
            r = RATIOS.get((data or {}).get("ratio", "16:9"), 16 / 9)
            dw = FRAME_W; dh = round(dw / r) + 44
        if note_id and not s.get(Note, note_id):
            note_id = None
        it = BoardItem(board_id=bid, type=type, x=number(x), y=number(y), w=number(w if w is not None else dw, 0), h=number(h if h is not None else dh, 0), z=int(number(z)), rot=number(rot),
                       data=json.dumps(_clean_data(type, data or {}), ensure_ascii=False), note_id=note_id, link_id=link_id)
        if it.type == "frame":
            it.h = frame_height(it.w, _data(it))
        s.add(it)
        b.updated_at = now(); b.revision += 1; s.add(b)
        s.commit(); s.refresh(it)
        return it


DEFAULT_SIZE = {"sticky": (180, 180), "text": (360, 160), "image": (320, 240), "arrow": (0, 0), "ink": (0, 0)}


def update_item(iid: int, board_id: int | None = None, **fields) -> BoardItem | None:
    with session() as s:
        it = s.get(BoardItem, iid)
        if not it or (board_id is not None and it.board_id != board_id):
            return None
        for k in ("x", "y", "w", "h", "rot"):
            if fields.get(k) is not None:
                setattr(it, k, number(fields[k], 0 if k in ("w", "h") else -1000000, 1000000))
        if fields.get("z") is not None:
            it.z = int(number(fields["z"]))
        if fields.get("data") is not None:
            it.data = json.dumps(_clean_data(it.type, {**_data(it), **fields["data"]}), ensure_ascii=False)
        if it.type == "frame":
            it.h = frame_height(it.w, _data(it))
        it.updated_at = now(); s.add(it)
        b = s.get(Board, it.board_id)
        b.updated_at = now(); b.revision += 1; s.add(b)
        s.commit(); s.refresh(it)
        return it


def bulk_update(bid: int, items: list[dict]) -> int:
    """Перенос/ресайз пачки объектов одним запросом (после перетаскивания выделения)."""
    n = 0
    with session() as s:
        for f in items[:500]:
            try:
                iid = int(f.get("id"))
            except (TypeError, ValueError):
                continue
            it = s.get(BoardItem, iid)
            if not it or it.board_id != bid:
                continue
            for k in ("x", "y", "w", "h", "rot"):
                if f.get(k) is not None:
                    setattr(it, k, number(f[k], 0 if k in ("w", "h") else -1000000, 1000000))
            if f.get("z") is not None:
                it.z = int(f["z"])
            if isinstance(f.get("data"), dict):
                it.data = json.dumps(_clean_data(it.type, {**_data(it), **f["data"]}), ensure_ascii=False)
            if it.type == "frame":
                it.h = frame_height(it.w, _data(it))
            it.updated_at = now(); s.add(it); n += 1
        b = s.get(Board, bid)
        if b and n:
            b.updated_at = now(); b.revision += 1; s.add(b)
        s.commit()
    return n


def delete_items(bid: int, ids: list[int]) -> int:
    n = 0
    with session() as s:
        for iid in ids[:500]:
            it = s.get(BoardItem, int(iid))
            if it and it.board_id == bid:
                s.delete(it); n += 1
        # стрелки, у которых пропал конец — тоже убираем
        if n:
            gone = {int(i) for i in ids}
            for it in s.exec(select(BoardItem).where(BoardItem.board_id == bid, BoardItem.type == "arrow")).all():
                d = _data(it)
                if any(isinstance(d.get(k), dict) and d[k].get("item") in gone for k in ("from", "to")):
                    s.delete(it); n += 1
            b = s.get(Board, bid)
            if b:
                b.updated_at = now(); b.revision += 1; s.add(b)
        s.commit()
    return n


def renumber_frames(bid: int) -> list[dict]:
    """Номера кадров по положению: слева направо, сверху вниз (ряды — по вертикальному перекрытию)."""
    with session() as s:
        frames = s.exec(select(BoardItem).where(BoardItem.board_id == bid, BoardItem.type == "frame")).all()
        if not frames:
            return []
        frames.sort(key=lambda f: (f.y, f.x))
        rows: list[list[BoardItem]] = []
        for f in frames:
            for row in rows:
                if abs(row[0].y - f.y) < row[0].h * 0.5:
                    row.append(f); break
            else:
                rows.append([f])
        n = 0
        changed = False
        for row in rows:
            row.sort(key=lambda f: f.x)
            for f in row:
                n += 1
                d = _data(f)
                if d.get("n") != n:
                    changed = True
                    d["n"] = n; f.data = json.dumps(d, ensure_ascii=False); s.add(f)
        if changed:
            b = s.get(Board, bid); b.revision += 1; s.add(b)
        s.commit()
        return [item_out(f) for row in rows for f in row]


def add_frame_next(bid: int, ratio: str | None = None) -> BoardItem:
    """«Добавить кадр»: ставит следующий кадр в конец последнего ряда (или новый ряд)."""
    with session() as s:
        frames = s.exec(select(BoardItem).where(BoardItem.board_id == bid, BoardItem.type == "frame")).all()
    ratio = ratio or (_data(frames[-1]).get("ratio") if frames else "16:9") or "16:9"
    r = RATIOS.get(ratio, 16 / 9)
    w = FRAME_W; h = round(w / r) + 44
    if not frames:
        x, y = 0.0, 0.0
    else:
        last = max(frames, key=lambda f: (round(f.y), f.x))
        per_row = 4 if r >= 1 else 6
        in_row = [f for f in frames if abs(f.y - last.y) < last.h * 0.5]
        if len(in_row) >= per_row:
            x, y = min(f.x for f in in_row), last.y + last.h + FRAME_GAP + 40
        else:
            x, y = last.x + last.w + FRAME_GAP, last.y
    it = add_item(bid, "frame", x, y, w, h, {"ratio": ratio, "n": len(frames) + 1})
    renumber_frames(bid)
    return it


# ---------------------------------------------------------------- тексты для ассистента
def board_text(b: Board | dict, limit: int = 1800) -> str:
    """Что на доске — словами (для чата/контекста заказа). Картинки не описываем."""
    d = b if isinstance(b, dict) else get_board(b.id)
    if not d:
        return ""
    items = d.get("items") or []
    frames = sorted([i for i in items if i["type"] == "frame"], key=lambda i: i["data"].get("n") or 0)
    stickies = [i for i in items if i["type"] == "sticky" and i["data"].get("text")]
    texts = [i for i in items if i["type"] == "text" and i["data"].get("text")]
    images = [i for i in items if i["type"] == "image"]
    lines = [f"🗂 «{d['title']}»" + (f" · заказ «{d['order_title']}»" if d.get("order_title") else "") + (f" · цель «{d['aim_title']}»" if d.get("aim_title") else "")]
    if frames:
        total = sum(float(f["data"].get("seconds") or 0) for f in frames)
        with_pic = sum(1 for f in frames if f["data"].get("image"))
        lines.append(f"Раскадровка: {len(frames)} кадр(ов), с картинкой {with_pic}" + (f", хронометраж {_sec(total)}" if total else ""))
        for f in frames[:24]:
            lab = (f["data"].get("label") or "").strip()
            sec = f["data"].get("seconds") or 0
            lines.append(f"  {f['data'].get('n') or '·'}. {lab or '—'}" + (f" ({_sec(sec)})" if sec else ""))
        if len(frames) > 24:
            lines.append(f"  … ещё {len(frames) - 24}")
    if stickies:
        lines.append(f"Стикеры ({len(stickies)}):")
        for st in stickies[:20]:
            lines.append("  • " + st["data"]["text"].strip().replace("\n", " ")[:120])
    if texts:
        lines.append(f"Тексты ({len(texts)}):")
        for tx in texts[:6]:
            t = tx["data"]["text"].strip()
            first = t.splitlines()[0][:80] if t else ""
            lines.append(f"  ¶ {first}" + (f" … ({len(t)} симв.)" if len(t) > 80 else ""))
    if images:
        lines.append(f"Картинок: {len(images)}")
    if len(items) == 0:
        lines.append("Пусто. Скажи «на доску: …» — поставлю стикер.")
    out = "\n".join(lines)
    return out if len(out) <= limit else out[:limit - 1] + "…"


def _sec(x: float) -> str:
    x = float(x)
    if x < 60:
        return f"{x:g} с"
    m, s = divmod(int(round(x)), 60)
    return f"{m}:{s:02d}"


def boards_text() -> str:
    bs = list_boards()
    if not bs:
        return "Досок нет. «доска: название» — заведу; «раскадровка: название на 8 кадров» — сразу с кадрами."
    lines = ["🗂 Доски:"]
    for b in bs[:12]:
        extra = f" · заказ «{b['order_title']}»" if b.get("order_title") else (f" · цель «{b['aim_title']}»" if b.get("aim_title") else "")
        lines.append(f"• {b['title']} — {b['items']} объект(ов), {KIND_RU.get(b['kind'], b['kind'])}{extra}")
    return "\n".join(lines)


KIND_RU = {"free": "свободная", "storyboard": "раскадровка", "script": "сценарий"}


def search_text(q: str) -> list[dict]:
    """Поиск по текстам объектов — для общего поиска на сайте."""
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    out = []
    with session() as s:
        for it in s.exec(select(BoardItem).where(BoardItem.type.in_(("sticky", "text", "frame")))).all():  # type: ignore[attr-defined]
            d = _data(it)
            t = (d.get("text") or d.get("label") or "")
            if q in t.lower():
                b = s.get(Board, it.board_id)
                if b and not b.archived:
                    out.append({"board_id": b.id, "board": b.title, "item_id": it.id, "type": it.type, "text": t[:160]})
            if len(out) >= 30:
                break
    return out


# ---------------------------------------------------------------- правила чата
BOARD_NEW_RX = re.compile(r"^\s*(?:новая\s+)?доска\s*[:\-—]\s*(.+?)\s*$", re.I)
STORY_NEW_RX = re.compile(r"^\s*(?:раскадровка|сториборд|storyboard)\s*[:\-—]\s*(.+?)(?:\s+(?:на|из)\s+(\d{1,2})\s+кадр\w*)?(?:\s+(\d+:\d+|\d+(?:[.,]\d+)?:1))?\s*$", re.I)
SCRIPT_NEW_RX = re.compile(r"^\s*сценарий\s*[:\-—]\s*(.+?)\s*$", re.I)
TO_BOARD_RX = re.compile(r"^\s*(?:кинь|закинь|брось|добавь|положи|запиши|поставь)?\s*(?:на|в)\s+доску(?:\s+[«\"]?(.+?)[»\"]?)?\s*[:\-—]\s*(.+?)\s*$", re.I)
TO_BOARD2_RX = re.compile(r"^\s*(?:кинь|закинь|брось|добавь|положи|поставь)\s+(.+?)\s+на\s+доску(?:\s+[«\"]?(.+?)[»\"]?)?\s*$", re.I)
BOARDS_Q_RX = re.compile(r"^\s*(?:мои\s+)?доски|(?:какие|что\s+за|покажи)\s+(?:у\s+меня\s+)?доски\W*$", re.I)
BOARD_Q_RX = re.compile(r"^\s*(?:что\s+(?:у\s+меня\s+)?(?:по|на)\s+(?:доске|раскадровке|сториборду|сценарию)|покажи\s+(?:доску|раскадровку|сториборд))\s*[«\"]?(.*?)[»\"]?\s*\??\s*$", re.I)


def chat_rule(t: str, channel: str = "tg") -> tuple[str, list[str]] | None:
    t = (t or "").strip()
    if not t or len(t) > 400:
        return None
    if BOARDS_Q_RX.match(t):
        return boards_text(), ["boards"]
    m = BOARD_Q_RX.match(t)
    if m:
        q = m.group(1).strip()
        b = find_board(q) if q else None
        if not b and not q:
            bs = list_boards()
            b = find_board(str(bs[0]["id"])) if bs else None
        if not b:
            return (f"Доски «{q}» не нашёл. " if q else "Досок нет. ") + "«доска: название» — заведу.", []
        return board_text(b), ["board"]
    m = STORY_NEW_RX.match(t)
    if m:
        title, n, ratio = m.group(1).strip(" .«»\""), int(m.group(2) or 0), (m.group(3) or "16:9").replace(",", ".")
        ratio = ratio if ratio in RATIOS else "16:9"
        from .orders import find_order
        o = find_order(title)
        b = add_board(title, "storyboard", order_id=o.id if o else None, frames=n or 6, ratio=ratio, source=channel)
        tail = f" (доска заказа «{o.title}»)" if o else ""
        return f"Раскадровка «{b.title}»{tail}: {n or 6} кадров {ratio}. Открой «доска» на сайте — подписи, картинки, длительности там.", ["add_board"]
    m = SCRIPT_NEW_RX.match(t)
    if m and len(m.group(1)) < 80 and not re.search(r"\b(?:такой|следующий|вот)\b", m.group(1), re.I):
        b = add_board(m.group(1).strip(" .«»\""), "script", source=channel)
        return f"Сценарий «{b.title}» — на доске, с шаблоном сцен. Пиши там или диктуй сюда «на доску {b.title}: …».", ["add_board"]
    m = BOARD_NEW_RX.match(t)
    if m:
        title = m.group(1).strip(" .«»\"")
        if find_board(title) and find_board(title).title.lower() == title.lower():
            return f"Доска «{title}» уже есть.", []
        from .orders import find_order
        o = find_order(title)
        b = add_board(title, "free", order_id=o.id if o else None, source=channel)
        return f"Доска «{b.title}» заведена" + (f" и привязана к заказу «{o.title}»" if o else "") + ". «на доску: мысль» — стикер туда.", ["add_board"]
    m = TO_BOARD_RX.match(t) or TO_BOARD2_RX.match(t)
    if m:
        if m.re is TO_BOARD2_RX:
            text, q = m.group(1).strip(), (m.group(2) or "").strip()
        else:
            q, text = (m.group(1) or "").strip(), m.group(2).strip()
        if len(text) < 2:
            return None
        b = find_board(q) if q else None
        if not b:
            bs = list_boards()
            if q or not bs:
                return (f"Доски «{q}» нет. " if q else "Досок пока нет. ") + f"Сказать «доска: {q or 'название'}» — заведу и положу туда.", []
            b = find_board(str(bs[0]["id"]))
        it = place_sticky(b.id, text)
        with session() as s:
            log_action(s, "board_sticky", "board_item", it.id, text[:60], channel); s.commit()
        return f"На доске «{b.title}»: «{text[:80]}».", ["board_sticky"]
    return None


def place_sticky(bid: int, text: str, color: str = "yellow") -> BoardItem:
    """Стикер в свободное место: правее самого правого объекта в верхнем ряду (не поверх)."""
    with session() as s:
        items = s.exec(select(BoardItem).where(BoardItem.board_id == bid, BoardItem.type != "ink")).all()
    if not items:
        x, y = 0.0, 0.0
    else:
        top = min(items, key=lambda i: i.y)
        row = [i for i in items if abs(i.y - top.y) < 200]
        right = max(row, key=lambda i: i.x + i.w)
        x, y = right.x + right.w + 24, top.y
    return add_item(bid, "sticky", x, y, data={"text": text[:2000], "color": color})


class BoardConflict(ValueError):
    """Содержимое изменили в другой вкладке или через ассистента; не затирать его."""


def sync_board(bid: int, revision: int, token: str, items: list[dict]) -> dict:
    """Один жест/пачка правок → один атомарный снимок. При сетевом повторе возвращаем те же id.
    Отрицательные id — временные в браузере; при undo удалённый объект восстанавливается с картой id.
    Обновления камеры не меняют revision. При конфликте содержимого возвращаем 409, не частичную запись.
    """
    from sqlalchemy import update
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", token or ""):
        raise ValueError("Неверный ключ сохранения")
    if len(items) > MAX_ITEMS or len(json.dumps(items, ensure_ascii=False, default=str)) > 8 * 1024 * 1024:
        raise ValueError("Слишком большая доска (лимит 5000 объектов / 8 МБ текста и штрихов)")
    normalized, ids = [], set()
    for obj in items:
        if not isinstance(obj, dict):
            raise ValueError("Неверный объект доски")
        iid = int(number(obj.get("id"), -2**53 + 1, 2**53 - 1))
        if not iid or iid in ids:
            raise ValueError("Повторяющийся или пустой id объекта")
        ids.add(iid)
        typ = obj.get("type")
        data = _clean_data(typ, obj.get("data") or {})
        f = {k: number(obj.get(k, 0)) for k in ("x", "y", "rot")}
        f.update(w=number(obj.get("w", 200), 0, 20000), h=number(obj.get("h", 120), 0, 20000), z=int(number(obj.get("z", 0))))
        if typ == "frame":
            f["w"] = max(f["w"], 60)
            f["h"] = frame_height(f["w"], data)
        if typ not in ("arrow", "ink") and min(f["w"], f["h"]) < 12:
            raise ValueError("Объект слишком мал")
        normalized.append((iid, typ, data, f, obj))
    for _, typ, data, _, _ in normalized:
        if typ == "arrow":
            for end in ("from", "to"):
                ep = data[end]
                if ep is None or ("item" in ep and ep["item"] not in ids):
                    raise ValueError("У стрелки отсутствует конец или связанный объект")
    with session() as s:
        b = s.get(Board, bid)
        if not b:
            raise LookupError("Доска не найдена")
        if b.archived:
            raise ValueError("Сначала верните доску из архива")
        ack = json.loads(b.last_sync or "{}")
        if ack.get("token") == token:
            return {"revision": ack["revision"], "id_map": ack["id_map"]}
        # CAS захватывает запись в той же транзакции, что и все объекты.
        res = s.execute(update(Board).where(Board.id == bid, Board.revision == revision).values(revision=revision + 1))
        if res.rowcount != 1:
            raise BoardConflict("Доска изменилась в другой вкладке")
        current = {i.id: i for i in s.exec(select(BoardItem).where(BoardItem.board_id == bid)).all()}
        id_map, rows = {}, []
        for iid, typ, data, f, obj in normalized:
            it = current.get(iid)
            if not it:
                if iid > 0 and s.get(BoardItem, iid):
                    raise ValueError("Объект принадлежит другой доске")
                it = BoardItem(board_id=bid, type=typ)
            it.type = typ
            for k, v in f.items():
                setattr(it, k, v)
            for k, model in (("note_id", Note), ("link_id", Link)):
                ref = obj.get(k)
                setattr(it, k, int(ref) if ref and s.get(model, int(ref)) else None)
            it.data = json.dumps(data, ensure_ascii=False)
            it.updated_at = now(); s.add(it); s.flush()
            id_map[str(iid)] = it.id
            rows.append((it, data))
        for it, data in rows:
            if it.type == "arrow":
                for name in ("from", "to"):
                    ep = data[name]
                    if "item" in ep:
                        ep["item"] = id_map[str(ep["item"])]
                it.data = json.dumps(data, ensure_ascii=False); s.add(it)
        for iid, it in current.items():
            if iid not in ids:
                s.delete(it)
        b.revision = revision + 1; b.updated_at = now()
        b.last_sync = json.dumps({"token": token, "revision": b.revision, "id_map": id_map})
        s.add(b); s.commit()
        return {"revision": b.revision, "id_map": id_map}


def save_asset(raw: bytes) -> dict:
    """Изображение для редактора: проверяем, переворачиваем по EXIF, сохраняем без потери альфа-канала.
    Только локальный файл; нет запросов в облако, внешних URL и выполнения SVG/HTML.
    """
    import hashlib
    import io
    from PIL import Image, ImageOps
    from .brain_notes import MEDIA_DIR
    if not raw or len(raw) > 20 * 1024 * 1024:
        raise ValueError("Нужна картинка не больше 20 МБ")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.format not in ("JPEG", "PNG", "WEBP", "GIF") or img.width * img.height > 40_000_000:
                raise ValueError("Недопустимый формат или размер картинки")
            img.load()
            img = ImageOps.exif_transpose(img)
            alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
            img = img.convert("RGBA" if alpha else "RGB")
            img.thumbnail((4096, 4096))
            w, h = img.size
            buff = io.BytesIO()
            ext = "png" if alpha else "jpg"
            if alpha:
                img.save(buff, "PNG", optimize=True)
            else:
                img.save(buff, "JPEG", quality=92, optimize=True)
    except Exception as e:
        raise ValueError("Не удалось прочитать картинку. Поддерживаются PNG, JPG, WebP и GIF") from e
    blob = buff.getvalue()
    path = f"boards/{hashlib.sha256(blob).hexdigest()[:32]}.{ext}"
    dest = MEDIA_DIR / path; dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(blob)
    return {"src": path, "w": w, "h": h}
