# -*- coding: utf-8 -*-
"""Правила мозга, вынесенные из core/brain/agent.py.

Каждый модуль exposes RULES: список функций (text, low, channel) -> Reply | None.
agent.rules() — диспетчер по этим спискам, порядок вызовов сохранён 1:1.
presence_rule — async (вызывается из _handle, который не трогаем по логике).
"""
from __future__ import annotations
