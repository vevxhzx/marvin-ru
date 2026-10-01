"""Доски заказов (макеты) (ФАЗА 7, шаг 7.2).

Роуты перенесены из `core/api/app.py` МЕХАНИЧЕСКИ: пути, методы, тела функций,
порядок ответов и логика не менялись. Декораторы сохраняют полный путь
(`/api/...`), поэтому `router` создаётся БЕЗ prefix — пути совпадают 1:1.

Инвариант регистрации (см. `core/api/routers/__init__.py`): `register(app)`
вызывается из `app.py` ПОСЛЕ `include_router(_crm_router)` и ДО статики и
catch-all SPA. Порядок роутов внутри модуля = порядок в `app.py` на шаге 7.0.

`/api/boards/{bid}/asset` и `/api/boards/{bid}/image` (§6.2 отчёта 7.0) пишут
файлы на диск, а `image` локально тянет `io` + `PIL.Image` — оставлены ровно
как были, тяжёлые импорты локальные.

Локальные импорты внутри тел роутов сохранены как есть (в проекте это осознанный
приём: быстрый старт, обход циклов) — у них ровно на одну точку больше,
т.к. модуль лежит на уровне `core/api/routers/`.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ...services import brain_notes
from ..schemas import (BoardBulk, BoardIds, BoardIn, BoardItemIn, BoardItemPatch, BoardPatch, BoardSync)

router = APIRouter()


def register(app) -> None:
    app.include_router(router)


# ---------------------------------------------------------------- доска
@router.get("/api/boards")
def boards_list(archived: bool = False):
    from ...services import boards
    return boards.list_boards(archived)


@router.post("/api/boards")
def boards_create(b: BoardIn):
    from ...services import boards
    try:
        nb = boards.add_board(b.title, b.kind, b.order_id, b.aim_id, b.frames, b.ratio, "web")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return boards.get_board(nb.id)


@router.get("/api/boards/search")
def boards_search(q: str = ""):
    from ...services import boards
    return boards.search_text(q)


@router.get("/api/boards/for-order/{oid}")
def boards_for_order(oid: int, create: bool = False):
    from ...services import boards
    b = boards.board_for_order(oid, create)
    if not b:
        raise HTTPException(404)
    return boards.get_board(b.id)


@router.get("/api/boards/{bid}")
def boards_get(bid: int):
    from ...services import boards
    d = boards.get_board(bid)
    if not d:
        raise HTTPException(404)
    return d


@router.get("/api/boards/{bid}/text")
def boards_text(bid: int):
    from ...services import boards
    d = boards.get_board(bid)
    if not d:
        raise HTTPException(404)
    return {"text": boards.board_text(d)}


@router.put("/api/boards/{bid}")
def boards_patch(bid: int, p: BoardPatch):
    from ...services import boards
    try:
        b = boards.update_board(bid, **p.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not b:
        raise HTTPException(404)
    return boards.get_board(bid)


@router.delete("/api/boards/{bid}")
def boards_delete(bid: int):
    from ...services import boards
    if not boards.delete_board(bid):
        raise HTTPException(404)
    return {"ok": True}


@router.post("/api/boards/{bid}/items")
def boards_item_add(bid: int, it: BoardItemIn):
    from ...services import boards
    try:
        row = boards.add_item(bid, it.type, it.x, it.y, it.w, it.h, it.data, it.z, it.rot, it.note_id, it.link_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return boards.item_out(row)


@router.post("/api/boards/{bid}/frame")
def boards_frame_next(bid: int, ratio: Optional[str] = None):
    from ...services import boards
    if not boards.get_board(bid):
        raise HTTPException(404)
    try:
        row = boards.add_frame_next(bid, ratio)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return boards.item_out(row)


@router.post("/api/boards/{bid}/renumber")
def boards_renumber(bid: int):
    from ...services import boards
    if not boards.get_board(bid):
        raise HTTPException(404)
    return boards.renumber_frames(bid)


@router.put("/api/boards/{bid}/items")
def boards_bulk(bid: int, b: BoardBulk):
    from ...services import boards
    if not boards.get_board(bid):
        raise HTTPException(404)
    try:
        return {"updated": boards.bulk_update(bid, b.items)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/boards/{bid}/items/{iid}")
def boards_item_patch(bid: int, iid: int, p: BoardItemPatch):
    from ...services import boards
    try:
        row = boards.update_item(iid, board_id=bid, **p.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not row:
        raise HTTPException(404)
    return boards.item_out(row)


@router.post("/api/boards/{bid}/items/delete")
def boards_items_delete(bid: int, b: BoardIds):
    from ...services import boards
    if not boards.get_board(bid):
        raise HTTPException(404)
    return {"deleted": boards.delete_items(bid, b.ids)}


@router.put("/api/boards/{bid}/sync")
def boards_sync(bid: int, b: BoardSync):
    """Атомарное сохранение всей доски: одна ревизия — один снимок. 409 — доска изменилась в другой вкладке."""
    from ...services import boards
    try:
        return boards.sync_board(bid, b.revision, b.token, b.items)
    except boards.BoardConflict as e:
        raise HTTPException(409, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/boards/{bid}/asset")
async def boards_asset(bid: int, file: UploadFile = File(...)):
    """Картинка для редактора: только файл в data/media, объект на доске создаёт сам редактор (и сохраняет через sync)."""
    from ...services import boards
    if not boards.get_board(bid):
        raise HTTPException(404)
    raw = await file.read()
    try:
        return boards.save_asset(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/boards/{bid}/image")
async def boards_image(bid: int, file: UploadFile = File(...), x: float = Form(0), y: float = Form(0),
                       frame_id: Optional[int] = Form(None)):
    """Картинка на доску: новым объектом или внутрь кадра (frame_id). Хранится в data/media, как фото заметок."""
    from ...services import boards
    if not boards.get_board(bid):
        raise HTTPException(404)
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Картинка больше 20 МБ")
    # на доску — только настоящая картинка (заметки терпимее: туда падают любые файлы из TG)
    w, h = 320.0, 240.0
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw)); im.verify()
        im = Image.open(io.BytesIO(raw)); iw, ih = im.size
        w = min(480.0, float(iw)); h = w * ih / iw
    except Exception:
        raise HTTPException(400, "Это не картинка (нужны jpg/png/webp/gif)")
    src = brain_notes.save_image(raw)
    if frame_id:
        row = boards.update_item(frame_id, board_id=bid, data={"image": src})
        if not row:
            raise HTTPException(404, "Кадр не найден")
        return boards.item_out(row)
    row = boards.add_item(bid, "image", x, y, w, h, {"src": src})
    return boards.item_out(row)
