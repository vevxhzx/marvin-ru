"""Стенд маршрутизации: куда уйдёт фраза БЕЗ вызова моделей. Запуск: ASSISTANT_TEST=1 python tools/route_audit.py
Печатает таблицу: правило / судья / сортировщик / облако / локальная-с-инструментами, и размер промпта для локальной.

БД стенда — отдельная, во временной папке: стенд не имеет права трогать настоящую
data/jarvis.db (раньше init_db() звался на импорте и писал в неё). Перенаправление
выполняется ДО `import core.*`, потому что core/config.py читает пути на импорте.
"""
from __future__ import annotations
import json, sys, os, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ASSISTANT_TEST", "1")

# --- изоляция: своя папка и своя БД, плюс проверка «не настоящая» (как в tests/e2e/demo_db.py)
_ROOT = Path(__file__).resolve().parent.parent
_REAL_DB = (_ROOT / "data" / "jarvis.db").resolve()
_WORK = Path(tempfile.mkdtemp(prefix="route-audit-"))
os.environ["JARVIS_DATA_DIR"] = str(_WORK)
os.environ["JARVIS_DB_PATH"] = str(_WORK / "audit.db")
os.environ["JARVIS_CONFIG"] = str(_WORK / "config.yaml")
if Path(os.environ["JARVIS_DB_PATH"]).resolve() == _REAL_DB:
    raise RuntimeError("отказ: путь БД стенда совпал с настоящей data/jarvis.db")

from core import db
from core.brain import agent, sorter, persona, llm
from core.tools import registry

CASES = [
 # (фраза, ожидаемый маршрут)  маршруты: rule / judge / batch / cloud / local
 ("510 доставка еды", "rule"), ("доставка еды 510", "rule"), ("запиши 510 доставка еды", "rule"),
 ("ты еблан? запиши 510 доставка еды", "rule"), ("самокат 800", "judge"), ("кино 600", "rule"), ("обед 450", "rule"),
 ("врач 2500", "rule"), ("тренировка 3000", "judge"), ("аптека 340", "rule"), ("подарок маме 3000", "judge"),
 ("сайт 15000", "judge"), ("встреча в 15", "rule"), ("ужин в 19", "rule"), ("зубной завтра в 10", "rule"),
 ("как дела", "cloud"), ("что нового", "cloud"), ("как думаешь, брать ли айфон 17", "cloud"), ("посоветуй фильм", "cloud"),
 ("напиши поздравление другу", "cloud"), ("что такое инфляция", "cloud"), ("сколько будет 15% от 3400", "cloud"),
 ("сколько я потратил на еду", "rule"), ("что у меня завтра", "rule"), ("покажи задачи", "rule|local"), ("какой у меня баланс", "rule|local"),
 ("кто мне должен", "rule"), ("задача починить кран", "rule"), ("напомни завтра в 9 позвонить маме", "rule"), ("купить молоко", "rule"),
 ("мысль: сделать канал про монтаж", "rule"), ("хлеб, молоко, яйца", "local"), ("купить хлеб, позвонить маме, отправить инвойс", "batch"),
 ("задачи на день: хлеб, инвойс, звонок маме", "batch"), ("Вовчик устал сегодня, 3 монтажа подряд", "local"),
 ("кот опять сожрал провод", "local"), ("у меня день рождения 12 марта", "local"), ("меня зовут Вова, я монтажёр", "local"),
 ("разбери: доход 80к, аренда 30к, кредит 12к, хватит ли", "local"),
 ("вот думаю что взять на завтрак через 10 минут закажу самокат как думаешь что может быть", "cloud"),
 ("слушай а что если я возьму кредит на 300 тысяч на камеру", "cloud"),
 ("сегодня 3 монтажа сдал, устал как собака", "local"), ("переведи слово cat", "cloud"),
]

def route(t: str) -> tuple[str, str]:
    """Тот же порядок, что в agent._handle: список → судья → правила → облако/локальная."""
    if sorter.looks_like_batch(t):
        return "batch", ""
    d = agent._disputed(t)
    if d:
        return "judge", "/".join(d)
    try:
        r = agent.rules(t, "tg")
    except Exception as e:
        return "ERR", type(e).__name__
    if r is not None:
        return "rule", ",".join(r.actions) or "ответ"
    if not agent.is_personal(t):
        return "cloud", ""
    return "local", "tools"


def main() -> int:
    db.init_db()   # свежая схема (миграции) на БД стенда; иначе на старой базе упадёт guess_category
    bad = 0
    print(f"{'фраза':60} {'куда':6} {'ожид.':10} детали")
    for t, exp in CASES:
        got, det = route(t)
        ok = got in exp.split("|")
        bad += not ok
        print(f"{t[:60]:60} {got:6} {exp:10} {det[:40]} {'' if ok else '  <-- НЕ ТАК'}")
    print()
    sp = persona.system_prompt(compact=True)
    tools = json.dumps(registry.tools_schema(with_cloud=True), ensure_ascii=False)
    print(f"Промпт локальной модели с инструментами: характер {len(sp)//3} ток. + схемы {len(tools)//3} ток. (+правила ~700 + история ≤{6*600//3}) ≈ {(len(sp)+len(tools))//3+700+1200} ток. при num_ctx={llm.OLLAMA_NUM_CTX}")
    print(f"Ошибок маршрута: {bad} из {len(CASES)}")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
