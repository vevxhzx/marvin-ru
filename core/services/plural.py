"""Склонение русских существительных при числах.

Одна функция для всего проекта — и в текстах ассистента, и в карточках.
Раньше в каждом месте было своё «дней/день/дня», из-за чего появлялось
«1 дней из 30».

Правило: последние две цифры 11–14 → форма для многих; иначе последняя
цифра 1 → одна, 2–4 → несколько, иначе — многих.
"""
from __future__ import annotations


def plural(n: int | float, one: str, few: str, many: str) -> str:
    a = abs(int(n)) % 100
    b = a % 10
    if 10 < a < 20:
        return many
    if b == 1:
        return one
    if 1 < b < 5:
        return few
    return many


# Готовые формы для частых единиц — чтобы не повторять тройки слов.
def days(n: int | float) -> str:
    return plural(n, "день", "дня", "дней")


def hours(n: int | float) -> str:
    return plural(n, "час", "часа", "часов")


def minutes(n: int | float) -> str:
    return plural(n, "минута", "минуты", "минут")


def tasks_word(n: int | float) -> str:
    return plural(n, "задача", "задачи", "задач")


def events_word(n: int | float) -> str:
    return plural(n, "событие", "события", "событий")


def orders_word(n: int | float) -> str:
    return plural(n, "заказ", "заказа", "заказов")
