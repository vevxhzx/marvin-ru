# -*- coding: utf-8 -*-
"""Контракт для выпадашки «Основной счёт» в настройках: мейн — это флаг is_main в БД
(строка finance.main_account в конфиге читается только при первом сиде и дальше ни на что
не влияет). Переключение — через PUT /api/finance/accounts/{id} {is_main: true}."""
from tests.test_core import fresh_db  # noqa: F401  (временная БД на весь файл)


def test_main_account_switch_moves_flag(fresh_db):
    from core.services import finance
    a = finance.add_account("Сбер", "bank", 5000)
    b = finance.add_account("Кубышка", "bank", 10000)
    finance.update_account(a.id, is_main=True)
    assert finance.main_account_name() == "Сбер"
    finance.update_account(b.id, is_main=True)
    assert finance.main_account_name() == "Кубышка"
    with finance.session() as s:
        cur = s.get(finance.Account, a.id)
        assert cur.is_main is False, "старый мейн обязан сняться"


def test_main_account_switch_via_api_shape(fresh_db):
    """Форма, которую шлёт фронт: AccountPatch {is_main: true} через update_account."""
    from core.api.routers.finance import fin_account_update
    from core.api.schemas import AccountPatch
    from core.services import finance
    a = finance.add_account("Сбер", "bank", 5000)
    b = finance.add_account("Кубышка", "bank", 10000)
    fin_account_update(a.id, AccountPatch(is_main=True))
    assert finance.main_account_name() == "Сбер"
    fin_account_update(b.id, AccountPatch(is_main=True))
    assert finance.main_account_name() == "Кубышка"
