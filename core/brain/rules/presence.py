# -*- coding: utf-8 -*-
"""Присутствие/режимы: цели (aims), рутины, доски, решения, лента,
самопроверка, стоп фоновой работы, «что происходит».

Вынесено из core/brain/agent.py 1:1 (_presence_rules + _money_like +
STOP_JOB_RX/WHATS_UP_RX). _is_analysis остаётся в agent.
Async: вызывается из _handle без смены логики.
"""
from __future__ import annotations

import re

from ..agent import STOP_JOB_RX, WHATS_UP_RX, Reply, _is_analysis, _money_like


async def presence_rule(text: str, low: str, channel: str) -> Reply | None:
    """Правила 0.10: цели (aims), решения, лента, самопроверка, стоп фоновой работы, «что происходит».
    Всё без модели — это команды к своим данным, а не разговор."""
    from core.services import aims, decisions, health, state, timeline
    from core.services import tasks

    t = text.strip()
    # --- цели --- («цель: подушка 300к к марту» с суммой — это денежный конверт, его берёт GOAL_RX ниже по цепочке)
    ma = aims.AIM_RX.match(t)
    if ma and _money_like(ma.group(2)):
        return None
    m = aims.AIM_CLOSE_RX.match(t)
    if m:
        name = (m.group(1) or m.group(3) or "").strip()
        aim = aims.find_aim(name)
        if not aim:
            return Reply(f"Цели «{name}» не нашёл. «Мои цели» — покажу, какие есть.", [], "rules")
        drop = bool(m.group(1)) and m.group(2).lower() in ("отбой", "отменяется", "больше не актуальна") or bool(m.group(3)) and re.match(r"^\s*(убери|отмени)", t, re.I)
        aims.close_aim(aim, "dropped" if drop else "done")
        return Reply((f"Цель «{aim.title}» снята. Без драмы — не всё, что начал, надо дожимать." if drop else f"Цель «{aim.title}» закрыта. Это не задача из списка — это то, ради чего список был."), ["close_aim"], "rules")
    m = re.match(r"^\s*цель\s+[«\"]?(.+?)[»\"]?\s+(?:активна|снова в работе|возобновляется|продолжаем)\s*[.!]?\s*$", t, re.I)
    if m:
        aim = aims.find_aim(m.group(1), any_status=True)
        if aim:
            aims.update_aim(aim.id, status="active")
            return Reply(f"«{aim.title}» снова в работе.", ["reopen_aim"], "rules")
    a = aims.detect_aim_phrase(t)
    if a:
        existing = aims.find_aim(a["title"])
        if existing and existing.title.lower() == a["title"].lower():
            return Reply(f"Такая цель уже есть: «{existing.title}» ({int(aims.progress(existing) * 100)}%).", [], "rules")
        aim = aims.add_aim(a["title"], why=a["why"], due=a["due"], source=channel)
        tail = f", к {aim.due:%d.%m.%Y}" if aim.due else ""
        why = "" if aim.why else " Зачем она тебе — скажи, запишу: через месяц это единственное, что удержит."
        return Reply(f"Цель поставлена: «{aim.title}»{tail}. Теперь «веха: …» — первый ощутимый рубеж, а задачи к ней я подтяну сам.{why}", ["add_aim"], "rules")
    m = aims.MS_RX.match(t)
    if m and not _is_analysis(t):
        title, aim_q = m.group(1).strip(" .«»\""), (m.group(2) or "").strip()
        aim = aims.find_aim(aim_q) if aim_q else None
        if aim is None:
            active = aims.list_aims()
            if len(active) == 1:
                aim = aims.find_aim(active[0]["id"])
            elif not active:
                return Reply("Вех без цели не бывает. Сначала «цель: …».", [], "rules")
            else:
                return Reply("К какой цели? " + "; ".join(f"«{x['title']}»" for x in active[:4]) + ". Скажи «веха: … к цели <название>».", [], "rules")
        ms = aims.add_milestone(aim, title)
        return Reply(f"Веха «{ms.title}» — в цели «{aim.title}». Задачи к ней: «задача: … к вехе {ms.title[:20]}» или просто закрывай дела — я сам спрошу, если похоже.", ["add_milestone"], "rules")
    if aims.FOCUS_RX.match(t):
        return Reply(aims.text_focus(), ["focus"], "rules")
    if aims.AIMS_RX.match(t):
        # «цели» — и долгосрочные (aims), и денежные конверты (goals) одним ответом: человек не обязан помнить разницу
        from core.services import goals as _goals
        parts, acts = [], ["aims"]
        if aims.list_aims():
            parts.append(aims.text_aims())
        if _goals.list_goals():
            parts.append(_goals.goals_text()); acts.append("list_goals")
        if not parts:
            parts.append(aims.text_aims())
        return Reply("\n\n".join(parts), acts, "rules")
    m = aims.BLOCK_RX.match(t)
    if m and len(m.group(2).strip()) >= 3 and not _is_analysis(t):
        tk = tasks.find_task(m.group(1).strip())
        if tk:
            aims.set_blocked(tk.id, m.group(2).strip())
            return Reply(f"«{tk.title}» — стоит: {m.group(2).strip()}. Из фокуса убрал, в «мешает» добавил. Скажи «разблокирована», когда сдвинется.", ["block_task"], "rules")
    m = re.match(r"^\s*(?:задача\s+)?[«\"]?(.+?)[»\"]?\s+(?:разблокирован\w*|сдвинулась|пошла|больше не стоит)\s*[.!]?\s*$", t, re.I)
    if m:
        tk = tasks.find_task(m.group(1).strip())
        if tk and tk.blocked_by:
            aims.set_blocked(tk.id, "")
            return Reply(f"«{tk.title}» снова в работе.", ["unblock_task"], "rules")
    # --- рутины ---
    from core.services import routines
    rt = routines.chat_rule(t)
    if rt:
        return Reply(rt, ["routines"], "rules")
    # --- доски: «доска: …», «раскадровка: … на 8 кадров», «на доску: мысль», «что по доске …» ---
    if not _is_analysis(t):
        from core.services import boards
        try:
            br = boards.chat_rule(t, channel)
        except ValueError as e:
            return Reply(str(e), [], "rules")
        if br:
            return Reply(br[0], br[1], "rules")
    # --- решения ---
    d = decisions.chat_rule(t, channel)
    if d:
        return Reply(d, ["decision"], "rules")
    # --- лента ---
    tl = timeline.chat_rule(t)
    if tl:
        return Reply(tl, ["timeline"], "rules")
    # --- самопроверка ---
    if health.SELF_RX.match(t):
        res = await health.diagnose()
        health.record(res)
        return Reply(res["text"], ["diagnose"], "rules")
    # --- фоновые работы ---
    if STOP_JOB_RX.match(t):
        job = state.running_job()
        if job:
            state.job_fail(job["name"], "остановлено по команде")
            return Reply(f"Остановил «{job['name']}».", ["stop_job"], "rules")
        return None   # обычный «стоп» (например, голосу) — дальше по цепочке
    if WHATS_UP_RX.match(t):
        sn = state.snapshot()
        parts = []
        line = state.line()
        if line:
            parts.append(line)
        if sn["jobs"]:
            parts.append("Фон: " + ", ".join(f"{j['name']} {int((j['progress'] or 0) * 100)}%" for j in sn["jobs"]))
        if sn["pending"]:
            parts.append("Жду ответа: " + sn["pending"])
        from core.brain import attention
        left = attention.budget_left()
        parts.append(f"Инициатив на сегодня осталось {left}" + (f", отложено {attention.queue_size()}" if attention.queue_size() else "") + ".")
        return Reply(" ".join(parts) if parts else "Тихо. ПК не на связи, фоновых работ нет, жду.", ["state"], "rules")
    return None


RULES = [presence_rule]
