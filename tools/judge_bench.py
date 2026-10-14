"""Стенд точности судьи: какая маленькая модель решает тип записи лучше.

Зачем. Судья отвечает на один вопрос: «это трата, доход, долг, заказ, задача, событие или
заметка?» Ошибиться он может двумя способами, и цена у ошибок разная:

  * уверенная неправильная классификация — худший случай: запись падает в базу не туда,
    ты узнаёшь об этом через месяц и не понимаешь почему;
  * отказ (confidence ниже порога) — не опасно, бот просто переспросит, но если отказывает
    постоянно, ты перестаёшь его слушать.

Поэтому точность меряется не «сколько ответов», а двумя числами: сколько из УВЕРЕННЫХ
ответов верных и как часто судья вообще отказывается. Быстрота (токенов в секунду) —
третье, самое дешёвое: медленный, но верный судья лучше быстрого и путающего.

Как пользоваться (из корня репозитория, при поднятом LM Studio):

    python tools/judge_bench.py                      # текущая модель из настроек
    python tools/judge_bench.py --model Qwen2.5-1.5B-Instruct-GGUF
    python tools/judge_bench.py --model qwen3.5-4b
    python tools/judge_bench.py --repeat 3          # замер скорости на нескольких прогонах

Ничего не пишет: стенд только зовёт `judge.decide()` и печатает отчёт. База не трогается.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# (фраза, правильный тип, какие типы вообще допустимы для этой фразы)
# Второе поле — эталон: его задаёшь ты, а не модель. Третье — реальные кандидаты из
# agent._disputed(): судье нельзя ответить «expense», если фраза про заказ.
CASES: list[tuple[str, str, tuple[str, ...]]] = [
    # --- деньги: дал/взял у человека → долг, но похоже на трату
    ("отдал Ване 2000", "debt", ("expense", "debt", "income")),
    ("перевёл 5000 маме", "debt", ("expense", "debt", "income")),
    ("одолжил 1500 у Кости", "debt", ("expense", "debt", "income")),
    ("Ваня должен мне 3000", "debt", ("expense", "debt", "income")),
    ("вернул 700 Сергею", "debt", ("expense", "debt", "income")),
    # --- трата: понятно, но короткая фраза без глагола
    ("300 такси", "expense", ("expense", "income", "order")),
    ("700 продукты", "expense", ("expense", "income", "order")),
    ("2500 шиномонтаж", "expense", ("expense", "income", "order")),
    ("1500 аптека", "expense", ("expense", "income", "order")),
    ("4000 ремонт", "expense", ("expense", "income", "order")),
    # --- доход: поступление денег
    ("20000 за монтаж ролика", "income", ("expense", "income", "order")),
    ("пришли 3000 за курс", "income", ("expense", "income", "order")),
    ("заработал 45000", "income", ("expense", "income", "order")),
    ("аванс 8000 за проект", "income", ("expense", "income", "order")),
    # --- заказ: работа, но похожа на доход или трату
    ("монтаж ролика 5000", "order", ("expense", "income", "order")),
    ("взял заказ на рекламу 15000", "order", ("expense", "income", "order")),
    ("съёмка для Кирилла 8000", "order", ("expense", "income", "order")),
    ("заказ на лендинг 40000", "order", ("expense", "income", "order")),
]


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.0f}%"


async def run(model: str | None, repeat: int) -> dict:
    from core.brain import llm
    from core.services import judge

    if model:
        # Фасад core.brain.llm пересылает запись в модуль-владелец, так что так
        # меняется именно то, что читает small_chat().
        llm.LMSTUDIO_SMALL_MODEL = model

    def where() -> str:
        if model:
            return model
        return llm.LMSTUDIO_SMALL_MODEL or f"{llm.LMSTUDIO_MODEL} (основная)"

    print(f"Модель судьи: {where()}")
    print(f"Случаев: {len(CASES)}, повторов для скорости: {repeat}\n")

    answered = 0          # уверенных ответов
    correct = 0           # из них верных
    refused = 0           # отказался (confidence ниже порога)
    broken = 0            # не ответил вовсе (none / мусор)
    wrong: list[tuple[str, str, str]] = []
    refused_list: list[str] = []
    per_kind: dict[str, list[bool]] = {}
    times: list[float] = []

    for phrase, want, allowed in CASES:
        t0 = time.monotonic()
        got, src = await judge.decide(phrase, allowed)
        times.append(time.monotonic() - t0)
        bucket = per_kind.setdefault(want, [])
        if got is None:
            if src == "none":
                broken += 1
            else:
                refused += 1
                refused_list.append(phrase)
            bucket.append(False)
        else:
            answered += 1
            ok = got == want
            bucket.append(ok)
            if ok:
                correct += 1
            else:
                wrong.append((phrase, want, got))

    acc = correct / answered if answered else 0.0
    total = len(CASES)
    print("=== ИТОГ ===")
    print(f"  уверенных ответов: {answered} из {total}")
    print(f"  из них верных:      {correct}  ({_fmt_pct(acc) if answered else '—'})")
    print(f"  отказался спросить: {refused}  ({_fmt_pct(refused / total)})")
    print(f"  не ответил вовсе:   {broken}")
    if times:
        avg = sum(times) / len(times)
        print(f"  среднее время:     {avg:.2f} с на фразу")

    if wrong:
        print("\n=== УВЕРЕННЫЕ ОШИБКИ (самое дорогое) ===")
        for phrase, want, got in wrong:
            print(f"  {phrase!r}: ждали {want}, получили {got}")
    if refused_list:
        print("\n=== ОТКАЗАЛСЯ (безопасно, но раздражает) ===")
        for phrase in refused_list:
            print(f"  {phrase!r}")

    print("\n=== ПО ТИПАМ ===")
    for kind in sorted(per_kind):
        hits = per_kind[kind]
        print(f"  {kind:8} {_fmt_pct(sum(hits) / len(hits))}  ({sum(hits)}/{len(hits)})")

    print("\n=== ВЕРДИКТ ===")
    if answered and acc >= 0.9 and refused / total <= 0.2:
        print("  Модель годится на судью.")
    elif acc >= 0.8:
        print("  Годится, но с оговоркой: точность ниже 90% — ошибочные записи будут.")
        print("  Либо оставь судью на основной модели, либо добавь в ФЕАТURES примеры ошибок.")
    else:
        print("  Как судья не годится: слишком много уверенных ошибок.")
        print("  Оставь small_model пустым — судья пойдёт на основную модель.")

    return {"acc": acc, "refused": refused / total, "answered": answered}


async def main() -> None:
    ap = argparse.ArgumentParser(description="Стенд точности судьи")
    ap.add_argument("--model", help="модель LM Studio для судьи (пишется только на время прогона)")
    ap.add_argument("--repeat", type=int, default=1, help="сколько раз прогнать каждый случай")
    args = ap.parse_args()
    await run(args.model, max(1, args.repeat))


if __name__ == "__main__":
    # ASSISTANT_TEST здесь НЕ включаем намеренно: этот режим гасит обращения к моделям,
    # а стенд как раз их меряет. Ставить его можно было бы только для проверки, что
    # скрипт вообще запускается — но тогда он вернёт «не ответил вовсе» по всем случаям.
    asyncio.run(main())