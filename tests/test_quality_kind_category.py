# -*- coding: utf-8 -*-
"""Качество: правка операции пересчитывает категорию при смене типа (бывший xfail P2).

Правило: пользовательская категория не теряется без причины — она меняется ТОЛЬКО если
конфликтует с новым kind (доход в «Еде»); совместимая категория остаётся на месте.
Временная БД — фикстура `fresh_db` из tests/conftest.py.
"""
from __future__ import annotations

import pytest

from core import db  # noqa: E402

pytestmark = pytest.mark.usefixtures("fresh_db")


def _fin():
    from core.services import finance
    return finance


def _tx(tx_id: int):
    with db.session() as s:
        return s.get(db.Transaction, tx_id)


def test_expense_turned_income_leaves_expense_category():
    f = _fin()
    t = f.add_transaction(500, "expense", "Еда", "обед", f.main_account_name())
    assert _tx(t.id).category == "Еда"
    f.update_transaction(t.id, kind="income")
    assert _tx(t.id).kind == "income"
    # «Еда» — категория расхода: доходу подставлена доходная, а не чужая
    assert _tx(t.id).category == "Прочий доход"
    assert all(c.kind == "income" for c in f.list_categories("income")
               if c.name == _tx(t.id).category)


def test_income_turned_expense_leaves_income_category():
    f = _fin()
    t = f.add_transaction(5_000, "income", "Прочий доход", "аванс", f.main_account_name())
    f.update_transaction(t.id, kind="expense")
    assert _tx(t.id).kind == "expense"
    assert _tx(t.id).category != "Прочий доход"
    assert any(c.name == _tx(t.id).category for c in f.list_categories("expense")), \
        f"категория расхода «{_tx(t.id).category}» не найдена среди расходных"


def test_compatible_category_survives_kind_change():
    """Совместимая категория не теряется: правка НЕ типа операции её не трогает."""
    f = _fin()
    t = f.add_transaction(500, "expense", "Еда", "обед", f.main_account_name())
    f.update_transaction(t.id, note="обед во вторник")          # kind не менялся
    assert _tx(t.id).category == "Еда"
    f.update_transaction(t.id, amount=600)                      # то же при правке суммы
    assert _tx(t.id).category == "Еда"


def test_explicit_category_wins_over_recalculation():
    """Явно переданная в той же правке категория важнее автоматического подбора."""
    f = _fin()
    t = f.add_transaction(500, "expense", "Еда", "обед", f.main_account_name())
    f.update_transaction(t.id, kind="income", category="Моя категория")
    assert _tx(t.id).kind == "income"
    assert _tx(t.id).category == "Моя категория"


def test_kind_change_to_transfer_drops_category():
    f = _fin()
    f.set_balance("Наличные", 1_000)
    t = f.add_transaction(500, "expense", "Еда", "обед", f.main_account_name())
    f.update_transaction(t.id, kind="transfer", to_account="Наличные")
    assert _tx(t.id).kind == "transfer"
    assert _tx(t.id).category is None


def test_category_kept_when_kind_roundtrips_through_compatible_value():
    """expense → income → expense: категория пересчитывается по правилам в обе стороны."""
    f = _fin()
    t = f.add_transaction(500, "expense", "Еда", "обед", f.main_account_name())
    f.update_transaction(t.id, kind="income")
    assert _tx(t.id).category == "Прочий доход"
    f.update_transaction(t.id, kind="expense")
    assert _tx(t.id).category != "Прочий доход"
    assert any(c.name == _tx(t.id).category for c in f.list_categories("expense"))
