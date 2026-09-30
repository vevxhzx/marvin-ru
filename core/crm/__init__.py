"""CRM-фаза 4: воронка заказов, карточки клиента/заказа, follow-up, деньги, аналитика.

Код изолирован от монолитов `app.py`/`app.py`-роутов: логика — в `core/crm/service.py`
и `core/crm/stages.py`, HTTP-слой — в `core/crm/router.py` (подключается в `app.py`).
"""
