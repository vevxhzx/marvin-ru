"""Обучение английскому: абзац дня по направлению, прогресс, свои тексты.

Новый домен рядом с остальными (`core/api/routers/*`), регистрируется в
`core/api/routers/__init__.py` ПЕРЕД `system` — тот должен остаться последним
(инвариант регистрации, см. докстринг `__init__.py`).

Авторизация — общая (AuthMiddleware в `core/api/app.py`): снаружи без ключа все
`/api/*` дают 401, отдельных проверок здесь не нужно. Ошибки — как у соседних
роутов: `HTTPException` с человеческим текстом (400 — плохой ввод, 404 — не найдено).

Хранение — только settings KV (`core/services/learn_en.py`): ни новых таблиц, ни миграций.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services import learn_en

router = APIRouter()


def register(app) -> None:
    app.include_router(router)


class EnglishSettingsIn(BaseModel):
    """Направление и флаг «генерировать абзацы нейросетью» (по умолчанию выключено)."""

    track: str | None = None
    llm: bool | None = None


class EnglishCustomIn(BaseModel):
    """Свой английский текст + перевод."""

    text_en: str = Field(..., min_length=1, max_length=8000)
    text_ru: str = Field("", max_length=8000)
    note: str = Field("", max_length=300)


@router.get("/api/english/settings")
def english_settings():
    """Настройки блока: выбранное направление, список направлений, флаг LLM, лимит своих текстов."""
    return learn_en.settings()


@router.put("/api/english/settings")
def english_settings_put(p: EnglishSettingsIn):
    """Переключить направление / включить-выключить генерацию нейросетью. Плохое значение — 400."""
    try:
        return learn_en.save_settings({"track": p.track, "llm": p.llm})
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/english/today")
async def english_today(track: str | None = None, day: str | None = None):
    """Абзац дня. Направление — из настроек; `?track=video` — превью другого направления
    (ничего не сохраняет). `?day=ГГГГ-ММ-ДД` — абзац за конкретный день."""
    return await learn_en.today_paragraph(track=track, day=day)


@router.post("/api/english/done")
def english_done(track: str | None = None, day: str | None = None):
    """Отметить день прочитанным: растёт стрик. Повтор в тот же день ничего не портит."""
    return learn_en.mark_done(track=track, day=day)


@router.get("/api/english/progress")
def english_progress():
    """Стрик, всего дней, последний день и разбивка по направлениям."""
    return learn_en.progress()


@router.get("/api/english/custom")
def english_custom_list():
    """Свои тексты, новые сверху (индексы — для удаления)."""
    return {"items": learn_en.custom_list(), "limit": learn_en.CUSTOM_LIMIT}


@router.post("/api/english/custom")
def english_custom_add(p: EnglishCustomIn):
    """Добавить свой текст + перевод. Лимит — 200 текстов."""
    try:
        row = learn_en.add_custom(p.text_en, p.text_ru, p.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "item": row, "count": len(learn_en.custom_list())}


@router.delete("/api/english/custom/{idx}")
def english_custom_del(idx: int):
    """Удалить свой текст по индексу из GET /api/english/custom."""
    if not learn_en.delete_custom(idx):
        raise HTTPException(404, "текст не найден")
    return {"ok": True, "count": len(learn_en.custom_list())}
