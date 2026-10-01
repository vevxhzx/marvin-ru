"""ДЕМО-БД для e2e-стенда (Playwright): временная SQLite с правдоподобными данными.

Зачем: e2e-тесты должны видеть не пустые экраны. Вариант «копия настоящей базы» запрещён
правилами OVERNIGHT.md (реальные данные нельзя ни читать, ни тем более показывать в отчёте),
поэтому здесь отдельная фикстура: свои клиенты, свои заказы, свои суммы — ничего персонального
и ничего из data/jarvis.db.

Безопасность (главное):
  * путь БД задаётся ТОЛЬКО через JARVIS_DB_PATH / JARVIS_DATA_DIR / JARVIS_CONFIG
    (см. core/config.py: переменные окружения перекрывают data/ и config.yaml);
  * `prepare_env()` ставит эти переменные ДО первого `import core.*` — иначе импортировался бы
    настоящий data/jarvis.db;
  * `assert_safe()` проверяет, что БД и папка настроек лежат внутри workdir и не совпадают
    с настоящими data/ — стенд физически не может открыть реальную базу.

Использование из своего кода:
    from demo_db import seed_demo
    info = seed_demo()                      # {"db": путь, "workdir": ..., "counts": {...}}

Из командной строки:
    .venv\\Scripts\\python.exe tests\\e2e\\demo_db.py
    .venv\\Scripts\\python.exe tests\\e2e\\demo_db.py --workdir %TEMP%\\demo --quiet
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent          # корень репозитория
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REAL_DB = ROOT / "data" / "jarvis.db"                        # настоящая база — только для сравнения
REAL_DATA_DIR = ROOT / "data"
DEMO_CONFIG_NAME = "config.yaml"


def default_workdir() -> Path:
    """Папка стенда по умолчанию: %TEMP%/jarvis-e2e-<pid> — не переживает перезагрузку машины."""
    return Path(tempfile.gettempdir()) / f"jarvis-e2e-{os.getpid()}"


# ------------------------------------------------------------------ конфиг стенда
def make_demo_config(path: Path) -> Path:
    """Свой config.yaml для стенда: настройки владельца не читаются и тем более не пишутся.

    Берём config.example.yaml (без секретов) и ужимаем шумное/внешнее: мозг только локальный,
    облако выключено, бэкапы и проактивные сообщения — нет, мастер пройден (иначе сайт отдаёт /setup).
    """
    raw = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8")) or {}
    raw.setdefault("brain", {})["mode"] = "local"
    raw["brain"].setdefault("vision", {})["allow_cloud"] = False
    for section in ("memory", "relations", "judge"):
        raw["brain"].setdefault(section, {})["enabled"] = False
    raw.setdefault("brain", {}).setdefault("cloud", {})["api_key"] = ""
    raw.setdefault("brain", {}).setdefault("gemini", {})["api_key"] = ""
    raw.setdefault("brain", {}).setdefault("gemini", {})["auto"] = False
    raw.setdefault("notifications", {})["proactive_enabled"] = False
    raw.setdefault("notifications", {})["proactive_vibe"] = False
    raw.setdefault("backup", {})["enabled"] = False
    raw.setdefault("google", {})["enabled"] = False
    raw.setdefault("voice", {})["enabled"] = False
    raw.setdefault("server", {})["port"] = 0                  # порт задаёт serve.py (--port)
    raw["setup"] = {"done": True}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def prepare_env(workdir: Path, db_path: Path) -> dict[str, str]:
    """Перенаправить ядро на временную БД. Вызывать ДО `import core.*`."""
    env = {
        "JARVIS_DATA_DIR": str(workdir),
        "JARVIS_DB_PATH": str(db_path),
        "JARVIS_CONFIG": str(workdir / DEMO_CONFIG_NAME),
        "JARVIS_E2E": "1",
        # локальный стенд: никаких внешних сервисов (Ollama на «мёртвом» порту → мгновенный отказ,
        # а не ожидание таймаута), без прогрева голоса, без браузера, без мастера настройки
        "OLLAMA_URL": "http://127.0.0.1:1",
        "ASSISTANT_NO_VOICE_WARMUP": "1",
        "ASSISTANT_NO_BROWSER": "1",
        "ASSISTANT_TEST": "1",
        "JARVIS_TEST": "1",
    }
    os.environ.update(env)
    return env


def assert_safe(workdir: Path, db_path: Path) -> None:
    """Стенд не имеет права дотянуться до настоящей базы. Бросает RuntimeError, если что-то не так."""
    workdir = workdir.resolve()
    db_real = db_path.resolve()
    if db_real == REAL_DB.resolve():
        raise RuntimeError("отказ: путь БД совпадает с настоящей data/jarvis.db")
    if workdir == REAL_DATA_DIR.resolve() or REAL_DATA_DIR.resolve() in workdir.parents:
        raise RuntimeError(f"отказ: папка стенда внутри настоящего data/ ({workdir})")
    if not str(db_real).startswith(str(workdir)):
        raise RuntimeError(f"отказ: БД {db_real} вне папки стенда {workdir}")
    for key in ("JARVIS_DB_PATH", "JARVIS_DATA_DIR", "JARVIS_CONFIG"):
        val = os.environ.get(key)
        if val and Path(val).resolve() in (REAL_DB.resolve(), REAL_DATA_DIR.resolve()):
            raise RuntimeError(f"отказ: {key} указывает на настоящие данные ({val})")


# ------------------------------------------------------------------ мелкие помощники
def _dt(days: float = 0, hour: int = 12, minute: int = 0) -> datetime:
    """Дата относительно сегодня: _dt(-3) — три дня назад, _dt(2, 14, 30) — через два дня в 14:30."""
    base = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return base + timedelta(days=days)


def _spread(key: str) -> int:
    """Детерминированный «разброс» в днях по строке-ключу: без random.seed, чтобы демо было стабильным."""
    return (sum(ord(ch) for ch in key) % 6) + 1


def _status_for(stage: str) -> str:
    from core.crm.stages import status_for
    return status_for(stage)


# ------------------------------------------------------------------ демо-данные
def _seed() -> dict:
    """Насыпать демо-данные в уже созданную (пустую) БД. Печатает счётчики, возвращает их же."""
    from sqlmodel import select
    from core import db as core_db
    from core.crm import service as crm

    acc_main, acc_cash = "Основной", "Наличные"

    # --- счета (баланс ставится в конце: операции по заказам его двигают)
    with core_db.session() as s:
        for name, kind, main in ((acc_main, "bank", True), (acc_cash, "cash", False), ("Резерв", "bank", False)):
            if s.exec(select(core_db.Account).where(core_db.Account.name == name)).first() is None:
                s.add(core_db.Account(name=name, kind=kind, is_main=main))

    # --- клиенты (все вымышленные)
    clients = [
        dict(name="Кофейня «Зерно»", contact="@zerno_demo", kind="client", tags="еда,малый бизнес,постоянный",
             notes="Любят тёплые кадры, не любят музыку с вокалом", source="рекомендация", pay_mode="each",
             last_contact_at=_dt(-3, 11), next_step="прислать смету на второй ролик", next_step_at=_dt(2, 10)),
        dict(name="Студия «Кадр»", contact="hello@kadr-demo.ru", kind="client", tags="видео,постоянный,оплата по факту",
             notes="Продакшен-менеджер — Ирина", source="сайт", pay_mode="each",
             last_contact_at=_dt(-1, 16), next_step="отдать исходники шоурила", next_step_at=_dt(1, 12)),
        dict(name="Маркетинг «Вектор»", contact="marketing@vektor-demo.ru", kind="client", tags="реклама,договор",
             notes="Платит пачкой раз в две недели", source="Telegram", pay_mode="batch", pay_every=14,
             last_contact_at=_dt(-6, 15), next_step="напомнить про оплату по посадочной", next_step_at=_dt(3, 11)),
        dict(name="Анна Демо", contact="@anna_demo", kind="client", tags="монтаж,разовые",
             notes="Ищет монтажёра для интервью и подкастов", source="авито", pay_mode="each",
             last_contact_at=_dt(-9, 13), next_step="спросить про курс", next_step_at=_dt(4, 17)),
        dict(name="Богдан Тестов", contact="@bogdan_demo", kind="person", tags="подрядчик,звук",
             notes="Звукорежиссёр, берёт за час", source="сарафан", last_contact_at=_dt(-12, 18)),
    ]
    cid: dict[str, int] = {}
    with core_db.session() as s:
        for c in clients:
            row = core_db.Client(**c)
            s.add(row)
            s.commit()
            s.refresh(row)
            cid[row.name] = row.id
    zerno, kadr, vektor, anna = cid["Кофейня «Зерно»"], cid["Студия «Кадр»"], cid["Маркетинг «Вектор»"], cid["Анна Демо"]

    # --- заказы: все девять стадий воронки закрыты демо-данными
    order_rows = [
        dict(title="Рекламный ролик 30 сек для «Зерна»", client_id=zerno, price=45_000, stage="in_work",
             deadline=_dt(4, 18), estimate_h=12, created_at=_dt(-9, 10), revisions=1,
             notes="ТЗ: три сцены, тёплые краски, съёмка в зале. Исходники у клиента в облаке.",
             last_contact_at=_dt(-1, 10), next_step="отдать первую версию", next_step_at=_dt(2, 18)),
        dict(title="Ролики для сторис: 3 штуки", client_id=kadr, price=18_000, stage="revisions",
             deadline=_dt(2, 12), estimate_h=5, created_at=_dt(-6, 9), revisions=2,
             notes="Формат 9:16, по 15 секунд. Третий круг правок: поправить концовку.",
             last_contact_at=_dt(0, 9), next_step="ждать правки", next_step_at=_dt(1, 15)),
        dict(title="Посадочная страница: монтаж промо", client_id=vektor, price=90_000, stage="awaiting_payment",
             deadline=_dt(-3, 19), estimate_h=20, created_at=_dt(-28, 11),
             notes="Сдан 12-го, оплата пришла частично. Остаток по договорённости.",
             last_contact_at=_dt(-2, 13), next_step="напомнить про остаток оплаты", next_step_at=_dt(1, 10)),
        dict(title="Корпоративный ролик 2 минуты", client_id=kadr, price=150_000, stage="paid",
             deadline=_dt(-14, 18), estimate_h=38, created_at=_dt(-40, 9),
             notes="Полный цикл: съёмка, монтаж, цвет, звук. Оплачен полностью.",
             last_contact_at=_dt(-12, 12)),
        dict(title="Интервью с основателем: 40 минут", client_id=anna, price=22_000, stage="paid",
             deadline=_dt(-26, 20), estimate_h=6, created_at=_dt(-34, 14),
             notes="Простой монтаж: чистка звука, субтитры, обложка для подкаста.",
             last_contact_at=_dt(-25, 16)),
        dict(title="Анимация логотипа и заставки", client_id=vektor, price=35_000, stage="delivered",
             deadline=_dt(6, 12), estimate_h=10, created_at=_dt(-12, 16),
             notes="Отдал три варианта заставки. Ждут выбора, потом оплата.",
             last_contact_at=_dt(-1, 17), next_step="напомнить про выбор варианта", next_step_at=_dt(3, 12)),
        dict(title="Тизер 15 секунд для рассылки", client_id=zerno, price=12_000, stage="negotiation",
             deadline=_dt(9, 18), estimate_h=3, created_at=_dt(-4, 14),
             notes="Обсуждаем объём: один ролик или пакет из трёх.",
             last_contact_at=_dt(-2, 15), next_step="собрать два варианта сметы", next_step_at=_dt(2, 11)),
        dict(title="Обрезка вебинара: 2 часа → 40 минут", client_id=kadr, price=28_000, stage="spec",
             deadline=_dt(7, 18), estimate_h=7, created_at=_dt(-5, 10),
             notes="ТЗ согласовано: три главы, вырезать паузы и вопросы из чата.",
             last_contact_at=_dt(-3, 13), next_step="получить исходник вебинара", next_step_at=_dt(1, 11)),
        dict(title="Ролик к запуску курса", client_id=anna, price=0, stage="lead",
             deadline=None, estimate_h=0, created_at=_dt(-2, 19),
             notes="Лид из Авито. Сумма пока не обсуждалась.", last_contact_at=_dt(-2, 19)),
        dict(title="Монтаж подкаста: 4 выпуска", client_id=vektor, price=40_000, stage="lost",
             deadline=_dt(-20, 18), estimate_h=12, created_at=_dt(-35, 11),
             lost_reason="выбрали монтажёра дешевле", notes="Слишком долго согласовывали ТЗ.",
             last_contact_at=_dt(-18, 12)),
    ]
    oid: dict[str, int] = {}
    for row in order_rows:
        row = dict(row, status=_status_for(row["stage"]))
        title = row["title"]
        with core_db.session() as s:
            o = core_db.Order(**row)
            s.add(o)
            core_db.log_action(s, "add_order", "order", 0, title, "web")
            core_db.remember(s, "order", f"Заказ: «{title}» · {row['client_id'] and ''}{row['price']:.0f} ₽",
                             "order", None, "web")
            s.commit()
            s.refresh(o)
            oid[title] = o.id
        if row["stage"] in ("paid", "delivered", "awaiting_payment"):
            with core_db.session() as s:
                o = s.get(core_db.Order, oid[title])
                if o and not o.done_at:
                    o.done_at = _dt(-6, 18)
                    s.add(o)
                    s.commit()

    # --- оплаты по заказам: income-событие в финансах + запись в ленте CRM (идемпотентно)
    for title, amount, note, when in (
        ("Корпоративный ролик 2 минуты", 150_000, "полная оплата по договору", _dt(-12, 12)),
        ("Интервью с основателем: 40 минут", 22_000, "оплата картой", _dt(-25, 16)),
        ("Посадочная страница: монтаж промо", 45_000, "аванс 50%", _dt(-2, 13)),
        ("Рекламный ролик 30 сек для «Зерна»", 15_000, "предоплата 1/3", _dt(-6, 10)),
    ):
        crm.payment(oid[title], amount, note=note, account=acc_main, date=when,
                    idem_key=f"demo-pay-{oid[title]}-{int(amount)}", channel="web")

    # --- обычные операции за 45 дней, чтобы графики и прогноз кассы были не пустыми
    txs = [
        dict(amount=62_000, kind="income", category="Зарплата", account=acc_main, note="аванс за месяц", date=_dt(-33, 9)),
        dict(amount=7_500, kind="income", category="Фриланс", account=acc_main, note="разовый монтаж", date=_dt(-21, 17)),
        dict(amount=12_000, kind="income", category="Фриланс", account=acc_main, note="ролик для канала", date=_dt(-8, 15)),
        dict(amount=42_000, kind="expense", category="Жильё", account=acc_main, note="аренда", date=_dt(-35, 10)),
        dict(amount=1_990, kind="expense", category="Подписки", account=acc_main, note="облачный диск", date=_dt(-30, 10)),
        dict(amount=1_299, kind="expense", category="Подписки", account=acc_main, note="подписка редактора", date=_dt(-12, 10)),
        dict(amount=2_400, kind="expense", category="Здоровье", account=acc_main, note="аптека", date=_dt(-18, 19)),
        dict(amount=11_900, kind="expense", category="Техника", account=acc_main, note="внешний SSD 1 ТБ", date=_dt(-16, 13)),
        dict(amount=5_200, kind="expense", category="Одежда", account=acc_main, note="куртка", date=_dt(-25, 16)),
        dict(amount=1_800, kind="expense", category="Развлечения", account=acc_main, note="кино", date=_dt(-7, 21)),
        dict(amount=15_000, kind="expense", category="Долги", account=acc_main, note="платёж по рассрочке", date=_dt(-10, 11)),
        dict(amount=1_990, kind="expense", category="Подписки", account=acc_main, note="облачный диск", date=_dt(0, 10)),
    ]
    food = [("кофе и завтрак", 320), ("обед в кафе", 780), ("продукты на неделю", 2_350), ("доставка еды", 690), ("кофе с собой", 210)]
    for back in range(45):
        if back % 3 == 0:
            note, amt = food[back % len(food)]
            txs.append(dict(amount=amt, kind="expense", category="Еда", account=acc_main, note=note, date=_dt(-back, 12)))
        if back % 4 == 1:
            txs.append(dict(amount=180 + (back % 5) * 90, kind="expense", category="Транспорт", account=acc_cash,
                            note="такси" if back % 2 else "метро", date=_dt(-back, 9)))
    with core_db.session() as s:
        for t in txs:
            row = core_db.Transaction(amount=float(t["amount"]), kind=t["kind"], category=t["category"],
                                      account=t["account"], note=t["note"], date=t["date"], source="web")
            s.add(row)
            core_db.remember(s, "finance", f"{'Доход' if row.kind == 'income' else 'Трата'}: "
                                           f"{row.category} · {row.amount:.0f} ₽", "transaction", None, "web")
        s.commit()

    # --- регулярные платежи, долг, цели, долгосрочная цель
    debt_id = 0
    with core_db.session() as s:
        s.add(core_db.Recurring(title="Аренда", amount=42_000, kind="expense", category="Жильё", account=acc_main,
                                period="monthly", day=1, next_date=_dt(15, 10)))
        s.add(core_db.Recurring(title="Облачный диск", amount=1_990, kind="expense", category="Подписки",
                                account=acc_main, period="monthly", day=5, next_date=_dt(4, 10)))
        debt = core_db.Debt(title="Рассрочка за ноутбук", creditor="Демо-Банк", total=96_000, remaining=48_000,
                            rate=14.5, payment=8_000, pay_day=15)
        s.add(debt)
        s.commit()
        s.refresh(debt)
        debt_id = debt.id
        s.add(core_db.Recurring(title="Рассрочка за ноутбук", amount=8_000, kind="expense", category="Долги",
                                account=acc_main, period="monthly", day=15, next_date=_dt(8, 11), debt_id=debt.id))
        s.add(core_db.Goal(title="Подушка на три месяца", target=300_000, saved=120_000, due=_dt(150, 12), icon="🛟"))
        s.add(core_db.Goal(title="Новый монитор", target=60_000, saved=18_500, due=_dt(45, 12), icon="🖥"))
        aim = core_db.Aim(title="Устойчивый поток заказов", why="хочу меньше прыгать между клиентами",
                          priority=1, due=_dt(90, 12), last_touch=_dt(-3, 18))
        s.add(aim)
        s.commit()
        s.refresh(aim)
        s.add(core_db.Milestone(aim_id=aim.id, title="Шоурил 90 секунд", due=_dt(21, 12), notes="взять лучшее из трёх заказов"))
        s.add(core_db.Milestone(aim_id=aim.id, title="Поднять цену до 2 500 ₽/час", due=_dt(60, 12)))
        s.commit()

    # --- задачи: сегодняшние, просроченные, в работе, закрытые, заблокированная
    tasks = [
        dict(title="Отдать первую версию ролика для «Зерна»", priority=1, due=_dt(0, 18)),
        dict(title="Согласовать правки по сторис «Кадра»", priority=1, due=_dt(1, 15)),
        dict(title="Напомнить «Вектору» про остаток оплаты", priority=1, due=_dt(0, 12)),
        dict(title="Собрать смету на тизер: два варианта", priority=2, due=_dt(2, 11)),
        dict(title="Обновить портфолио: три новые работы", priority=2, due=_dt(-2, 21)),
        dict(title="Снять шоурил 90 секунд", priority=2, due=_dt(7, 12)),
        dict(title="Купить второй монитор", priority=3, due=None),
        dict(title="Разобрать исходники в «Загрузках»", priority=3, due=_dt(-1, 20), blocked_by="жду исходники от «Зерна»"),
        dict(title="Оплатить подписку редактора", priority=2, due=_dt(-1, 10), done=True, done_at=_dt(-1, 10)),
        dict(title="Снять показания счётчиков", priority=3, due=_dt(-6, 9), done=True, done_at=_dt(-6, 9)),
    ]
    with core_db.session() as s:
        for t in tasks:
            row = core_db.Task(created_at=_dt(-_spread(t["title"])), **t)
            s.add(row)
            core_db.remember(s, "task", f"Задача: {row.title}", "task", None, "web")
        s.commit()

    # --- события календаря: сегодня, повтор, с привязкой к заказу, прошедшие
    events = [
        dict(title="Планёрка со студией «Кадр»", start=_dt(0, 11), end=_dt(0, 11, 45),
             location="Zoom", repeat="weekly", repeat_days="1"),
        dict(title="Съёмка в кафе (ролик «Зерно»)", start=_dt(0, 15), end=_dt(0, 17, 30),
             location="Кофейня «Зерно»", notes="Звук: Богдан Тестов", order_id=oid["Рекламный ролик 30 сек для «Зерна»"]),
        dict(title="Звонок Анне Демо", start=_dt(1, 16), end=_dt(1, 16, 30), source="web"),
        dict(title="Сдать ролик студии «Кадр»", start=_dt(2, 12), end=_dt(2, 13)),
        dict(title="Съёмка интервью с Анной", start=_dt(5, 14), end=_dt(5, 17), location="Студия"),
        dict(title="Напомнить про оплату по посадочной", start=_dt(1, 10), end=_dt(1, 10, 15)),
        dict(title="Показать шоурил на отзыве", start=_dt(-2, 19), end=_dt(-2, 20), done=True, done_at=_dt(-2, 20)),
        dict(title="Монтаж: финальная сборка", start=_dt(-1, 13), end=_dt(-1, 18)),
        dict(title="Встреча с подрядчиком по звуку", start=_dt(-4, 17), end=_dt(-4, 18)),
        dict(title="Дедлайн: сдача промо «Вектора»", start=_dt(-3, 19), end=_dt(-3, 19)),
    ]
    with core_db.session() as s:
        for e in events:
            row = core_db.Event(**e)
            s.add(row)
            core_db.remember(s, "event", f"Событие: {row.title}", "event", None, "web")
        s.commit()

    # --- заметки и ссылки (мозг)
    notes = [
        ("Идея: рубрика «разбор кадра» — по одному интересному моменту из каждого ролика", "разбор кадра", "идея,контент"),
        ("Клиентам заходит короткий ролик с музыкой без слов. Длинное вступление — мимо", "что заходит клиентам", "работа"),
        ("Поднять цену до 2 500 ₽/час: с первого месяца отказы", "цены", "деньги,работа"),
        ("Дедлайн важнее тайминга: один пропущенный срок — минус клиент", "дедлайны", "работа"),
        ("Съёмка в кафе утром — свет мягкий и зал пустой", "съёмка", "свет,советы"),
        ("Тёмная тема сайта экономит глаза и выглядит дороже", "тема", "дизайн"),
        ("Хочу попробовать караоке-бар в центре — посмотреть, что за публика", "караоке-бар", "быт"),
    ]
    links = [
        ("https://example.com/montage-pricing", "Сколько брать за монтаж", "example.com"),
        ("https://example.com/short-form-video", "Короткие ролики: что работает", "example.com"),
        ("https://example.com/portfolio-structure", "Как собрать портфолио", "example.com"),
        ("https://example.com/interview-light", "Свет для съёмки интервью", "example.com"),
    ]
    with core_db.session() as s:
        for text, title, tags in notes:
            row = core_db.Note(text=text, title=title, tags=tags, polished=True, source="web",
                               created_at=_dt(-_spread(title) - 1))
            s.add(row)
            core_db.remember(s, "note", f"Мысль: {title}", "note", None, "web")
        for url, title, domain in links:
            s.add(core_db.Link(url=url, title=title, domain=domain, polished=True, tags="монтаж",
                               summary="Демонстрационная заметка для e2e: страница-заглушка про тему.",
                               source="web", created_at=_dt(-_spread(title))))
        s.commit()

    # --- факты о владельце: один в архиве (чтобы появилась метка «возможно устарело»)
    facts = [
        dict(text="Работаю монтажёром, в основном рекламные ролики до минуты", layer="long",
             category="работа", core=True, created_at=_dt(-60, 12)),
        dict(text="Не люблю созвоны раньше 10 утра", layer="long", category="предпочтение",
             core=True, created_at=_dt(-41, 12)),
        dict(text="Планирую поднять цену до 2 500 ₽ за час", layer="short", category="работа", created_at=_dt(-3, 12)),
        dict(text="Купил второй монитор, теперь рендер идёт быстрее", layer="short", category="быт", created_at=_dt(-2, 12)),
        dict(text="Хочу попробовать караоке-бар в центре", layer="archive", category="быт",
             archive_reason="устарело", created_at=_dt(-55, 12)),
    ]
    chat = [("user", "привет, что на сегодня?", 10, 0), ("assistant", "На сегодня: 3 задачи, 2 события, ожидается доход.", 10, 1),
            ("user", "сколько ждут оплаты", 10, 2), ("assistant", "Остаток по посадочной — 45 000 ₽.", 10, 3),
            ("user", "спасибо", 10, 4), ("assistant", "Пожалуйста.", 10, 5)]
    runs = [("rules", "записал задачу «Отдать первую версию ролика»", "add_task", 140),
            ("rules", "записал трату 780 ₽ «обед в кафе»", "add_expense", 90),
            ("rules", "ответил на «сколько ждут оплаты» без вызова инструментов", "", 120),
            ("ollama", "ответил на «привет»", "", 2100)]
    with core_db.session() as s:
        for f in facts:
            s.add(core_db.Fact(**f))
        for role, text, hour, minute in chat:
            s.add(core_db.ChatMessage(role=role, text=text, channel="web", created_at=_dt(0, hour, minute)))
        for route, text, tools, ms in runs:
            s.add(core_db.Run(text=text, channel="web", route=route, model="" if route == "rules" else "demo-model",
                              tools=tools, ms=ms, ok=True, created_at=_dt(-1, 15)))
        s.commit()

    # --- доски
    with core_db.session() as s:
        board = core_db.Board(title="Раскадровка: ролик «Зерно»", kind="storyboard",
                              order_id=oid["Рекламный ролик 30 сек для «Зерна»"], updated_at=_dt(-1, 16))
        s.add(board)
        s.commit()
        s.refresh(board)
        for it in (dict(type="sticky", x=40, y=40, data='{"text":"Кадр 1. Утро, свет в окне","color":"#ffd166"}'),
                   dict(type="sticky", x=320, y=40, data='{"text":"Кадр 2. Бариста у стойки","color":"#8ecae6"}'),
                   dict(type="frame", x=620, y=40, w=240, h=135, data='{"label":"3. Кофейня, 12 сек","ratio":"16:9","seconds":12}'),
                   dict(type="text", x=40, y=220, w=320, h=90,
                        data='{"text":"Музыка: лёгкая гитара, без вокала. Финал: «Ваш кофе — ваш ритуал»","size":14}'),
                   dict(type="arrow", x=880, y=90, w=120, h=40, data='{"label":"переход"}')):
            s.add(core_db.BoardItem(board_id=board.id, created_at=_dt(-2, 12), updated_at=_dt(-1, 16), **it))
        free = core_db.Board(title="Мысли на неделю", kind="free", updated_at=_dt(0, 9))
        s.add(free)
        s.commit()
        s.refresh(free)
        for i, text in enumerate(("Начать разбирать съёмки по сценам", "Посчитать реальные часы за неделю",
                                  "Придумать, как брать предоплату 50%", "Не забыть про подписку редактора")):
            s.add(core_db.BoardItem(board_id=free.id, type="sticky", x=40 + (i % 2) * 300, y=40 + (i // 2) * 160,
                                    data='{"text":"' + text + '","color":"#a0c4ff"}', created_at=_dt(-1, 10)))
        s.commit()

    # --- рабочие сессии (часы и ставка) и экранное время за последние 5 дней
    plan = [(-5, "Рекламный ролик 30 сек для «Зерна»", 3), (-5, "Рекламный ролик 30 сек для «Зерна»", 2),
            (-4, "Рекламный ролик 30 сек для «Зерна»", 4), (-4, "Обрезка вебинара: 2 часа → 40 минут", 2),
            (-3, "Рекламный ролик 30 сек для «Зерна»", 3), (-2, "Ролики для сторис: 3 штуки", 4),
            (-2, "Ролики для сторис: 3 штуки", 2), (-1, "Ролики для сторис: 3 штуки", 3),
            (-1, "Анимация логотипа и заставки", 2), (0, "Рекламный ролик 30 сек для «Зерна»", 2)]
    with core_db.session() as s:
        for back, title, hours in plan:
            start = _dt(back, 9 if back else 9)
            s.add(core_db.WorkSession(order_id=oid[title], kind="focus", started_at=start,
                                      ended_at=start + timedelta(hours=hours), planned_min=hours * 60,
                                      note="монтаж", source="web"))
        for back, app_, cat in ((-1, "premiere pro.exe", "работа"), (-1, "chrome.exe", "браузер"),
                                (0, "premiere pro.exe", "работа"), (0, "chrome.exe", "браузер")):
            start = _dt(back, 10)
            s.add(core_db.ScreenSlot(start=start, end=start + timedelta(hours=3), app=app_,
                                     title="монтаж", category=cat, idle=False))
        s.commit()

    # --- CRM: лента активности, комментарии, чек-листы, follow-up
    timeline = [
        ("Рекламный ролик 30 сек для «Зерна»", "stage", "Стадия: лид → переговоры → ТЗ согласовано → в работе", -9),
        ("Рекламный ролик 30 сек для «Зерна»", "note", "Получил исходники: 47 файлов, 38 минут видео", -8),
        ("Рекламный ролик 30 сек для «Зерна»", "payment", "Предоплата 15 000 ₽", -6),
        ("Рекламный ролик 30 сек для «Зерна»", "comment", "Клиент просит теплее цвет в третьей сцене", -2),
        ("Ролики для сторис: 3 штуки", "stage", "Стадия: в работе → на правках", -2),
        ("Ролики для сторис: 3 штуки", "comment", "Второй круг правок: поправить концовку", -1),
        ("Посадочная страница: монтаж промо", "stage", "Стадия: сдан → ждёт оплаты", -6),
        ("Посадочная страница: монтаж промо", "payment", "Аванс 50% — 45 000 ₽", -2),
        ("Анимация логотипа и заставки", "stage", "Стадия: в работе → сдан", -1),
        ("Монтаж подкаста: 4 выпуска", "stage", "Стадия: потерян — выбрали монтажёра дешевле", -18),
    ]
    with core_db.session() as s:
        for title, kind, text, back in timeline:
            s.add(core_db.CrmActivity(order_id=oid[title], kind=kind, text=text, channel="web",
                                      created_at=_dt(back, 12)))
        s.commit()
    for title, text in (("Рекламный ролик 30 сек для «Зерна»", "Просил сдвинуть музыку на две секунды позже"),
                        ("Ролики для сторис: 3 штуки", "Ирина: третий круг правок за счёт студии"),
                        ("Посадочная страница: монтаж промо", "Оплата придёт в начале месяца, бухгалтер предупредил")):
        crm.add_comment(oid[title], text)
    for title, checks in (("Рекламный ролик 30 сек для «Зерна»", [("Бриф и ТЗ", True), ("Исходники получены", True),
                                                                 ("Первая версия", True), ("Правки клиента", False),
                                                                 ("Сдача финала", False)]),
                          ("Ролики для сторис: 3 штуки", [("ТЗ", True), ("Черновики", True), ("Правки", False)]),
                          ("Посадочная страница: монтаж промо", [("Бриф", True), ("Монтаж", True), ("Сдача", True),
                                                                ("Оплата", False)])):
        for t, done in checks:
            crm.add_check(oid[title], t)
    with core_db.session() as s:
        done_titles = {"Рекламный ролик 30 сек для «Зерна»", "Ролики для сторис: 3 штуки"}
        for c in s.exec(select(core_db.CrmChecklist).where(core_db.CrmChecklist.done == False)).all():
            order = s.get(core_db.Order, c.order_id) if c.order_id else None
            if order and order.title in done_titles:
                c.done = True
                s.add(c)
        s.commit()
    for text, title, client_id, kind, due in (
        ("Клиент молчит 9 дней — написать «Вектору»", None, vektor, "silent", _dt(1, 11)),
        ("Дедлайн по посадочной прошёл, оплаты нет", "Посадочная страница: монтаж промо", vektor, "overdue", _dt(0, 12)),
        ("Неоплата больше 20 дней", "Посадочная страница: монтаж промо", vektor, "unpaid", _dt(2, 10)),
        ("Собрать смету на тизер", "Тизер 15 секунд для рассылки", zerno, "manual", _dt(2, 11)),
    ):
        crm.create_followup(text, order_id=oid[title] if title else None, client_id=client_id, kind=kind, due_at=due)

    # --- балансы счетов (ставим в конце: платежи по заказам их двигают)
    balances = {acc_main: 128_400, acc_cash: 4_500, "Резерв": 62_000}
    with core_db.session() as s:
        for a in s.exec(select(core_db.Account)).all():
            a.balance = balances.get(a.name, a.balance)
            s.add(a)
        s.commit()

    # --- счётчики для отчёта
    with core_db.session() as s:
        counts = {name: len(s.exec(select(model)).all()) for name, model in (
            ("clients", core_db.Client), ("orders", core_db.Order), ("transactions", core_db.Transaction),
            ("tasks", core_db.Task), ("events", core_db.Event), ("notes", core_db.Note), ("links", core_db.Link),
            ("memory", core_db.Memory), ("boards", core_db.Board), ("work_sessions", core_db.WorkSession),
            ("crm_activity", core_db.CrmActivity), ("followups", core_db.CrmFollowup), ("facts", core_db.Fact))}
    return counts


# ------------------------------------------------------------------ публичный API
def seed_demo(workdir: Path | str | None = None, db_path: Path | str | None = None,
              fresh: bool = True, quiet: bool = False) -> dict:
    """Создать временную БД и насыпать демо-данные. Возвращает пути и счётчики.

    workdir — папка стенда (по умолчанию %TEMP%/jarvis-e2e-<pid>); там же config.yaml стенда.
    db_path  — файл БД (по умолчанию workdir/jarvis.db).
    fresh    — True: пересоздать папку стенда с нуля (каждый прогон — чистая демо-БД).
    """
    workdir = Path(workdir) if workdir else default_workdir()
    db_path = Path(db_path) if db_path else workdir / "jarvis.db"
    if fresh and workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)
    assert_safe(workdir, db_path)
    make_demo_config(workdir / DEMO_CONFIG_NAME)
    prepare_env(workdir, db_path)
    assert_safe(workdir, db_path)                    # ещё раз: уже после подстановки переменных

    from core import db as core_db                   # импорт core — только после prepare_env()!
    core_db.init_db()
    counts = _seed()
    info = {"db": str(core_db.DB_PATH), "workdir": str(workdir),
            "config": str(workdir / DEMO_CONFIG_NAME), "counts": counts,
            "today": str(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))}
    if not quiet:
        print(f"[e2e] демо-БД: {info['db']}", file=sys.stderr)
        print(f"[e2e] папка стенда: {info['workdir']}", file=sys.stderr)
        print(f"[e2e] насыпано: {counts}", file=sys.stderr)
    return info


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Создать демо-БД для e2e-стенда")
    ap.add_argument("--workdir", default=os.getenv("E2E_WORKDIR") or "", help="папка стенда (по умолчанию: временная папка jarvis-e2e-<pid>)")
    ap.add_argument("--db", default=os.getenv("E2E_DB_PATH") or "", help="файл БД (по умолчанию workdir/jarvis.db)")
    ap.add_argument("--quiet", action="store_true", help="не печатать счётчики")
    args = ap.parse_args(argv)
    info = seed_demo(workdir=args.workdir or None, db_path=args.db or None, quiet=args.quiet)
    print(info["db"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())