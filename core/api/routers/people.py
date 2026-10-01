"""Люди, связи и цели (ФАЗА 7, шаг 7.3).

Роуты перенесены из `core/api/app.py` МЕХАНИЧЕСКИ: пути, методы, тела функций,
порядок ответов и логика не менялись. Декораторы сохраняют полный путь
(`/api/...`), поэтому `router` создаётся БЕЗ prefix — пути совпадают 1:1.

Инвариант регистрации (см. `core/api/routers/__init__.py`): `register(app)`
вызывается из `app.py` ПОСЛЕ `include_router(_crm_router)` и ДО статики и
catch-all SPA. Порядок роутов внутри модуля = порядок в `app.py` на шаге 7.0.

Своих хелперов у людей нет: `_order_or_404` ушёл в `orders.py` (шаг 7.2),
`insights.related` нужен `mind.py` (шаг 7.5). `/api/relations/*` — только
`set_status`; `/api/aims*` — только сервис `aims`.

`core/crm/router.py` (prefix `/api/crm`) НЕ тронут: у CRM есть свои
`/api/crm/clients/{cid}/card` и `PUT /api/crm/clients/{cid}` — пути другие,
дублирования нет.

Локальные импорты внутри тел роутов сохранены как есть (в проекте это осознанный
приём: быстрый старт, обход циклов) — у них ровно на одна точка больше,
т.к. модуль лежит на уровне `core/api/routers/`.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...db import session
from ...services import people, relations
from .._shared import broadcast
from ..schemas import AimIn, AimPatch, MilestoneIn, PersonIn, RelationIn

router = APIRouter()


def register(app) -> None:
    app.include_router(router)


@router.put("/api/relations/{rid}")
def relation_set(rid: int, p: RelationIn):
    """Крестик на связи: status=no — пара больше никогда не предлагается. Переход по связи — status=yes."""
    r = relations.set_status(rid, p.status)
    if not r:
        raise HTTPException(404)
    return r


# ---------------- цели (aims): цель → вехи → задачи; фокус дня ----------------
@router.get("/api/aims")
def get_aims(all: bool = False):
    from ...services import aims
    return aims.list_aims(include_closed=all)


@router.get("/api/aims/{aim_id}")
def get_aim(aim_id: int):
    from ...services import aims
    v = aims.aim_view(aim_id)
    if not v:
        raise HTTPException(404)
    return v


@router.post("/api/aims")
def create_aim(a: AimIn):
    from ...services import aims
    aim = aims.add_aim(a.title, a.why, a.due, a.priority, source="web")
    return aims.aim_view(aim.id)


@router.put("/api/aims/{aim_id}")
def patch_aim(aim_id: int, p: AimPatch):
    from ...services import aims
    fields = p.model_dump(exclude_none=True)
    fields.pop("clear_due", None)
    if p.clear_due:
        fields["due"] = None; fields["clear_due"] = True
    a = aims.update_aim(aim_id, **fields)
    if not a:
        raise HTTPException(404)
    return aims.aim_view(aim_id)


@router.post("/api/aims/{aim_id}/milestones")
def create_milestone(aim_id: int, m: MilestoneIn):
    from ...services import aims
    if not aims.find_aim(aim_id):
        raise HTTPException(404)
    ms = aims.add_milestone(aim_id, m.title, m.due, m.order_id, m.notes)
    return aims.aim_view(ms.aim_id)


@router.post("/api/milestones/{mid}/{status}")
def set_milestone(mid: int, status: str):
    from ...services import aims
    if status not in ("done", "open", "dropped"):
        raise HTTPException(400, "status: done | open | dropped")
    ms = aims.close_milestone(mid, status)
    if not ms:
        raise HTTPException(404)
    return aims.aim_view(ms.aim_id)


# ---------------- люди и граф ----------------
@router.get("/api/people/batch-hints")
def people_batch_hints():
    """Клиенты, у которых 2+ заказа оплачены одним днём, а режим ещё «за каждый» — предложить «пачкой»."""
    from ...services import pulse
    return pulse.guess_batch_clients()


@router.get("/api/people/kinds")
def people_kinds():
    """Типы «кто это»: встроенные + свои (people.kinds)."""
    return people.all_kinds()


@router.delete("/api/people/kinds/{kind}")
def people_kind_delete(kind: str):
    n = people.remove_custom_kind(kind)
    broadcast("people")
    return {"ok": True, "reassigned": n}


@router.get("/api/people")
def people_list():
    from ...services import people
    return people.list_people()


@router.post("/api/people")
def people_add(p: PersonIn):
    from ...services import people
    if not (p.name or "").strip():
        raise HTTPException(400, "Нужно имя")
    c = people.add_person(p.name, p.kind or None, p.contact, p.notes, p.aliases, p.birthday, p.tags)
    broadcast("chat", {"channel": "web", "actions": ["add_person"]})
    return people.card(c)


@router.get("/api/people/today")
def people_today():
    from ...services import people
    return people.people_today()


@router.get("/api/people/{cid}")
def people_card(cid: int):
    from ...services import people
    from ...db import Client
    with session() as s:
        c = s.get(Client, cid)
    if not c:
        raise HTTPException(404)
    return people.card(c, limit=20)


@router.put("/api/people/{cid}")
def people_update(cid: int, p: PersonIn):
    from ...services import people
    c = people.update_person(cid, **p.model_dump(exclude_none=True))
    if not c:
        raise HTTPException(404)
    broadcast("chat", {"channel": "web", "actions": ["update_person"]})
    return people.card(c, limit=20)
