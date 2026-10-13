"""HTTP-эндпоинты демо-данных: `POST /api/demo/seed`, `POST /api/demo/clear`, `GET /api/demo/status`.

Зачем отдельный модуль рядом с остальными (`core/api/routers/*`): фича первичного заполнения
живёт отдельно от доменов (деньги/дела/календарь) и не должна раздувать `system.py`.
Логика — в `core/services/demo_seed.py`, роутер только переводит HTTP в вызовы сервиса.

ПОДКЛЮЧЕНИЕ (одна строка при слиянии — `core/api/routers/__init__.py` в этой ветке занят
параллельной работой, поэтому здесь роутер НЕ подключён):

    в `core/api/routers/__init__.py`:
      1) в импорте добавить demo:
             from . import boards, chat, demo, finance, learn, mind, orders, pc, people, system, tasks
      2) в `register()` вызвать его ДО system (system обязан остаться последним —
         иначе сломается инвариант регистрации и тест test_p7_routers_registration):
             demo.register(app)     # демо-данные: /api/demo/* — перед system

Авторизация — общая (`core/api/auth.py`, AuthMiddleware в `core/api/app.py`): middleware
проверяет любой путь, начинающийся с `/api/`, поэтому отдельных проверок здесь не нужно —
внешний клиент без ключа получает 401 на всех трёх маршрутах (проверено тестами).

ПОЧЕМУ ИМЕННО ДО system (проверено на живом app, не на глаз): `system` подключается последним
из доменов, а сразу после него в `app.py` идёт catch-all SPA `/{path:path}`. Если включить
роутер позже, он встанет ПОСЛЕ catch-all — и `/api/demo/*` начнёт отдавать HTML/404 даже
с верным ключом (`GET` перехватывает catch-all). Проверено: demo=24, system=25, spa=27 —
с такой позиции 401 без ключа и 200 со с ключом; при включении в конец — 404.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...services import demo_seed

router = APIRouter(prefix="/api/demo")


def register(app) -> None:
    app.include_router(router)


@router.get("/status")
def demo_status():
    """Что сейчас в базе: `empty` / `demo` / `mixed` / `own` + счётчики. UI по нему решает,
    какую кнопку показать: «загрузить пример данных» или «очистить и начать с нуля»."""
    return demo_seed.demo_status()


@router.post("/seed")
def demo_seed_load():
    """Загрузить пример данных. Идемпотентно: если демо уже есть — ничего не добавляем.
    Ошибка загрузки — 400 (в базе при этом ничего не остаётся: сид откатывается сам)."""
    res = demo_seed.seed_demo()
    if not res.get("ok"):
        raise HTTPException(400, res.get("message") or res.get("error") or "не получилось загрузить пример данных")
    return res


@router.post("/clear")
def demo_seed_clear():
    """Удалить ТОЛЬКО демо-данные, реальные записи не трогаются. Идемпотентно и безопасно
    на пустой базе. Ответ содержит `removed` (что сняли) и `kept` (что оставили и почему)."""
    return demo_seed.clear_demo()