"""F2: money() показывает копейки тогда и только тогда, когда дробная часть ненулевая.

Одно симметричное правило с JS (fmtMoney): округление HALF_UP до 2 знаков,
копейки — только при ненулевой дробной части. До фикса Python делал
f"{x:,.0f}" (целые рубли), а Python round() — half-even, когда JS Math.round —
half-up: одно и то же значение рендерилось по-разному.
"""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

from core.services.finance import money  # noqa: E402


def test_money_kopecks_only_when_fractional():
    cases = {
        0.5: "0.50 ₽",
        1.5: "1.50 ₽",
        2.5: "2.50 ₽",
        -0.5: "-0.50 ₽",
        -1.5: "-1.50 ₽",
        2.675: "2.68 ₽",  # HALF_UP; banker's round(2.675, 2) дал бы 2.67
        999.99: "999.99 ₽",
        377.13: "377.13 ₽",
        1000.0: "1 000 ₽",
    }
    for v, expected in cases.items():
        assert money(v) == expected, f"money({v!r})"


def test_money_integers_unchanged():
    assert money(0) == "0 ₽"
    assert money(1500) == "1 500 ₽"
    assert money(-1500) == "-1 500 ₽"
    assert money(1000000) == "1 000 000 ₽"
    assert money(1000.004) == "1 000 ₽"  # округлилось до целого — копеек нет
    assert money(1000.50) == "1 000.50 ₽"
