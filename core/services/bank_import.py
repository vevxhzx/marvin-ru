"""Импорт банковских выписок (Т-Банк CSV/PDF, а также любой CSV с колонками дата/сумма/описание).

Все операции получают import_hash = sha1(дата+сумма+описание) → повторный импорт того же файла ничего не задвоит.
Ничего не отправляется в облако: разбор — регулярками, категории — по ключевым словам (+ локальная LLM не нужна).
Переводы между своими счетами и пополнения с других своих карт помечаются как переводы и в доходы не идут.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from . import finance

log = logging.getLogger("assistant.import")

# известные заголовки Т-Банка (экспорт из приложения/личного кабинета, cp1251/utf-8, разделитель ;)
TB_DATE = ("Дата операции", "Дата платежа")
TB_AMOUNT = ("Сумма операции", "Сумма платежа")
TB_DESC = ("Описание",)
TB_CAT = ("Категория",)
TB_STATUS = ("Статус",)
TB_CARD = ("Номер карты",)

TRANSFER_RX = re.compile(r"перевод (между|на карту|с карты|себе|внутренний)|внутрибанковский|пополнение\.\s*система быстрых платежей|"
                         r"перевод по номеру телефона|со счёта|с вклада|на вклад|накопительн|инвест", re.I)
SKIP_RX = re.compile(r"кэшбэк|cashback|проценты на остаток", re.I)          # это доход, но особый — пусть будет «Кэшбэк»
CAT_MAP = {   # категория Т-Банка → наша
    "Супермаркеты": "Продукты", "Рестораны": "Кафе", "Фастфуд": "Кафе", "Транспорт": "Транспорт", "Такси": "Транспорт",
    "Топливо": "Транспорт", "Аптеки": "Здоровье", "Медицина": "Здоровье", "Дом и ремонт": "Дом", "Дом, ремонт": "Дом",
    "ЖКХ": "Дом", "Связь": "Связь", "Мобильная связь": "Связь", "Интернет": "Связь", "Кино": "Развлечения", "Развлечения": "Развлечения",
    "Одежда и обувь": "Одежда", "Красота": "Здоровье", "Цифровые товары": "Подписки", "Сервисы": "Подписки", "Маркетплейсы": "Покупки",
    "Онлайн-магазины": "Покупки", "Зарплата": "Зарплата", "Переводы": "Переводы", "Финансовые услуги": "Прочее",
}


@dataclass
class Row:
    date: datetime
    amount: float            # >0 доход, <0 расход
    desc: str
    category: str | None = None
    bank_cat: str | None = None
    transfer: bool = False
    hash: str = ""


@dataclass
class Result:
    added: int = 0
    skipped_dup: int = 0
    skipped_transfer: int = 0
    skipped_fail: int = 0
    total_expense: float = 0.0
    total_income: float = 0.0
    rows: int = 0
    from_date: datetime | None = None
    to_date: datetime | None = None
    errors: list[str] = field(default_factory=list)

    def text(self) -> str:
        if not self.rows:
            return "Не смог разобрать файл: не нашёл ни одной операции. " + (self.errors[0] if self.errors else "Нужен CSV из Т-Банка или PDF-выписка.")
        p = f"📥 Выписка разобрана: {self.rows} операций"
        if self.from_date and self.to_date:
            p += f" ({self.from_date:%d.%m}–{self.to_date:%d.%m.%Y})"
        p += f".\n✅ Добавлено {self.added}: расходы {finance.money(self.total_expense)}, доходы {finance.money(self.total_income)}."
        extra = []
        if self.skipped_dup:
            extra.append(f"{self.skipped_dup} уже были")
        if self.skipped_transfer:
            extra.append(f"{self.skipped_transfer} переводов между своими счетами пропущено")
        if self.skipped_fail:
            extra.append(f"{self.skipped_fail} не записались")
        if extra:
            p += "\n" + " · ".join(extra) + "."
        p += "\nЕсли что-то попало не туда — правьте на сайте, категории запомню."
        return p


def _num(s: str) -> float | None:
    s = (s or "").strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d.\-+]", "", s)
    try:
        return float(s) if s not in ("", "-", "+", ".") else None
    except ValueError:
        return None


def _date(s: str) -> datetime | None:
    s = (s or "").strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def _hash(d: datetime, amount: float, desc: str) -> str:
    return hashlib.sha1(f"{d:%Y-%m-%d %H:%M}|{amount:.2f}|{desc.strip().lower()[:60]}".encode()).hexdigest()[:32]


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


# ---------------------------------------------------------------- CSV
def parse_csv(data: bytes) -> list[Row]:
    text = _decode(data)
    sample = text[:4000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames:
        return []
    heads = [h.strip() for h in reader.fieldnames]

    def pick(cands, fuzzy=()):
        for c in cands:
            if c in heads:
                return c
        for h in heads:
            if any(f in h.lower() for f in fuzzy):
                return h
        return None

    hd = pick(TB_DATE, ("дата", "date"))
    ha = pick(TB_AMOUNT, ("сумма", "amount", "sum"))
    hs = pick(TB_DESC, ("описан", "назнач", "description", "контрагент", "merchant"))
    hc = pick(TB_CAT, ("категор", "category"))
    hst = pick(TB_STATUS, ("статус", "status"))
    if not (hd and ha):
        return []
    rows: list[Row] = []
    for rec in reader:
        rec = {(k or "").strip(): (v or "") for k, v in rec.items()}
        if hst and rec.get(hst, "").strip().upper() in ("FAILED", "ОТКЛОНЕНО", "ОТМЕНЕНО", "CANCELED"):
            continue
        d = _date(rec.get(hd, ""))
        a = _num(rec.get(ha, ""))
        if d is None or a is None or a == 0:
            continue
        desc = (rec.get(hs, "") if hs else "").strip() or (rec.get(hc, "") if hc else "").strip() or "операция"
        bank_cat = (rec.get(hc, "") if hc else "").strip() or None
        rows.append(Row(date=d, amount=a, desc=desc, bank_cat=bank_cat, transfer=bool(TRANSFER_RX.search(desc) or (bank_cat or "").lower() == "переводы"),
                        hash=_hash(d, a, desc)))
    return rows


# ---------------------------------------------------------------- PDF (выписка Т-Банка)
PDF_LINE_RX = re.compile(r"(\d{2}\.\d{2}\.\d{4})(?:\s+\d{2}:\d{2})?\s+(?:\d{2}\.\d{2}\.\d{4}\s+)?([+\-−–]?\s?\d[\d\s\xa0]*[.,]?\d{0,2})\s*(?:₽|RUB|i)?\s+(.+?)$")


def parse_pdf(data: bytes) -> tuple[list[Row], str | None]:
    try:
        import pdfplumber
    except ImportError:
        return [], "Для PDF нужен пакет pdfplumber — запустите update.bat."
    rows: list[Row] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                # 1) таблицы
                for tbl in page.extract_tables() or []:
                    for r in tbl:
                        cells = [(c or "").replace("\n", " ").strip() for c in r]
                        if len(cells) < 3:
                            continue
                        d = next((_date(c) for c in cells if _date(c)), None)
                        if not d:
                            continue
                        amt = None
                        for c in cells[1:]:
                            if re.fullmatch(r"[+\-−–]?\s?\d[\d\s\xa0]*[.,]?\d{0,2}\s*(₽|RUB|i)?", c):
                                amt = _num(c.replace("−", "-").replace("–", "-")); break
                        if amt is None:
                            continue
                        desc = max((c for c in cells if not _date(c) and _num(c) is None), key=len, default="операция")
                        rows.append(Row(date=d, amount=amt, desc=desc, transfer=bool(TRANSFER_RX.search(desc)), hash=_hash(d, amt, desc)))
                if rows:
                    continue
                # 2) построчно
                for line in (page.extract_text() or "").splitlines():
                    m = PDF_LINE_RX.match(line.strip())
                    if not m:
                        continue
                    d = _date(m.group(1)); amt = _num(m.group(2).replace("−", "-").replace("–", "-"))
                    if d and amt:
                        desc = m.group(3).strip()
                        rows.append(Row(date=d, amount=amt, desc=desc, transfer=bool(TRANSFER_RX.search(desc)), hash=_hash(d, amt, desc)))
    except Exception as e:
        return [], f"PDF не читается: {e}"
    # в PDF Т-Банка расходы часто без минуса: если все суммы положительные — считаем расходом всё, кроме явных доходов
    if rows and all(r.amount > 0 for r in rows):
        for r in rows:
            if not re.search(r"зарплат|пополнен|зачислен|возврат|кэшбэк|процент|перевод от|входящ", r.desc, re.I):
                r.amount = -r.amount
    return rows, None


# ---------------------------------------------------------------- применить
def _category(r: Row) -> str | None:
    if r.bank_cat and r.bank_cat in CAT_MAP:
        return CAT_MAP[r.bank_cat]
    kind = "income" if r.amount > 0 else "expense"
    if SKIP_RX.search(r.desc):
        return "Кэшбэк" if kind == "income" else None
    g = finance.guess_category(r.desc, kind)
    if g in ("Другое", "Прочий доход") and r.bank_cat:
        return CAT_MAP.get(r.bank_cat) or r.bank_cat[:30]
    return g


def apply(rows: list[Row], account: str | None = None, skip_transfers: bool = True) -> Result:
    res = Result(rows=len(rows))
    if rows:
        res.from_date = min(r.date for r in rows); res.to_date = max(r.date for r in rows)
    from sqlmodel import select
    from ..db import Transaction, session
    with session() as s:
        existing = {t.import_hash for t in s.exec(select(Transaction).where(Transaction.import_hash != None)).all()} if rows else set()  # noqa: E711
    seen: set[str] = set()
    for r in sorted(rows, key=lambda x: x.date):
        if r.hash in existing or r.hash in seen:
            res.skipped_dup += 1; continue
        seen.add(r.hash)
        if skip_transfers and r.transfer:
            res.skipped_transfer += 1; continue
        kind = "income" if r.amount > 0 else "expense"
        try:
            finance.add_transaction(abs(r.amount), kind, _category(r), r.desc[:120], account, date=r.date, source="import", import_hash=r.hash)
            res.added += 1
            if kind == "expense":
                res.total_expense += abs(r.amount)
            else:
                res.total_income += r.amount
        except Exception as e:
            res.skipped_fail += 1
            if len(res.errors) < 3:
                res.errors.append(str(e))
    return res


def import_file(name: str, data: bytes, account: str | None = None) -> Result:
    low = (name or "").lower()
    if low.endswith(".pdf") or data[:4] == b"%PDF":
        rows, err = parse_pdf(data)
        res = apply(rows, account)
        if err:
            res.errors.insert(0, err)
        return res
    if low.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            buf = io.StringIO(); w = csv.writer(buf, delimiter=";")
            for row in ws.iter_rows(values_only=True):
                w.writerow(["" if v is None else (v.strftime("%d.%m.%Y %H:%M:%S") if hasattr(v, "strftime") else v) for v in row])
            data = buf.getvalue().encode("utf-8")
        except ImportError:
            r = Result(); r.errors.append("Для Excel нужен пакет openpyxl — запустите update.bat."); return r
        except Exception as e:
            r = Result(); r.errors.append(f"Excel не читается: {e}"); return r
    return apply(parse_csv(data), account)
