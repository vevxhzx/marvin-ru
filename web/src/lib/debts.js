/* Чистая математика долгов: тип, прогресс, сортировка и план погашения.
   Без React, i18n и зависимостей — модуль можно звать из UI и из Node-теста.
   Деньги здесь считаются в рублях с копейками, наружу отдаём округлённые
   целые для «переплаты» и итогов: в интерфейсе копейки только шумят. */

export const DEBT_KINDS = ['credit', 'credit_card', 'installment', 'personal', 'receivable']
export const DEBT_SORTS = ['manual', 'amount', 'rate', 'day', 'progress']

const num = (v, fallback = 0) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

const round2 = (v) => Math.round((num(v) + Number.EPSILON) * 100) / 100
const clamp = (v, min, max) => Math.min(max, Math.max(min, v))

/* Одна карточка: что показывать и какую полосу рисовать.
   Кредитка живёт по лимиту (использовано / лимит), остальные — по выплаченному
   (выплачено / сумма). `pct` — проценты 0..100, `progress` — доля 0..1. */
export function debtView(d = {}) {
  const total = Math.max(0, num(d.total))
  const remaining = Math.max(0, num(d.remaining ?? total))
  const paid = Math.max(0, num(d.paid ?? (total - remaining)))
  const kind = DEBT_KINDS.includes(d.kind) ? d.kind : 'credit'
  const isCard = kind === 'credit_card'
  const limit = Math.max(0, num(d.credit_limit) || total)
  const progress = isCard
    ? (limit > 0 ? remaining / limit : 0)
    : (total > 0 ? paid / total : 0)
  return {
    total,
    remaining,
    paid,
    kind,
    isCard,
    limit,
    progress: clamp(progress, 0, 1),
    pct: clamp(progress, 0, 1) * 100,
    rate: Math.max(0, num(d.rate)),
    payment: Math.max(0, num(d.payment)),
    payDay: clamp(Math.round(num(d.pay_day, 1)), 1, 31),
  }
}

/* Порядок карточек. «Вручную» — как отдал бэкенд (sort_order), остальные —
   по убыванию/возрастанию выбранного признака. Исходный массив не мутируем. */
export function sortDebts(list = [], mode = 'manual') {
  const arr = [...list]
  const byId = (a, b) => num(a.id) - num(b.id)
  if (mode === 'amount') {
    arr.sort((a, b) => debtView(b).remaining - debtView(a).remaining || byId(a, b))
  } else if (mode === 'rate') {
    arr.sort((a, b) => debtView(b).rate - debtView(a).rate || byId(a, b))
  } else if (mode === 'day') {
    arr.sort((a, b) => debtView(a).payDay - debtView(b).payDay || byId(a, b))
  } else if (mode === 'progress') {
    arr.sort((a, b) => debtView(b).pct - debtView(a).pct || byId(a, b))
  } else {
    arr.sort((a, b) => num(a.sort_order) - num(b.sort_order) || byId(a, b))
  }
  return arr
}

/* Помесячная симуляция погашения.
   debts      — активные долги (remaining > 0), поля remaining/rate/payment;
   monthly    — сколько пользователь готов платить в месяц всего;
   strategy   — 'avalanche' (сначала максимальная ставка) | 'snowball' (меньший остаток).
   Минимальные платежи идут по всем долгам, излишек — в целевой долг. Если введённая
   сумма меньше суммы минимальных, считаем по минимальным и помечаем insufficient:
   иначе симуляция «не платит» и результат вводит в заблуждение.
   Потолок 600 месяцев защищает от вечного цикла (нулевой платёж / платёж меньше процентов). */
export function payoffPlan(debts = [], monthly = 0, strategy = 'avalanche', maxMonths = 600) {
  const now = new Date()
  const rows = (debts || [])
    .filter((d) => num(d.remaining) > 0)
    .map((d) => {
      const start = Math.max(0, num(d.remaining))
      return {
        id: d.id,
        title: d.title || d.name || '',
        rate: Math.max(0, num(d.rate)),
        payment: Math.max(0, num(d.payment)),
        start,
        balance: start,
        interest: 0,
        closedMonth: null,
        closeDate: null,
      }
    })

  const minTotal = rows.reduce((sum, r) => sum + Math.min(r.payment, r.balance), 0)
  const wanted = Math.max(0, num(monthly))
  const budget = Math.max(wanted, minTotal)
  const insufficient = wanted + 0.005 < minTotal
  let totalInterest = 0
  let month = 0

  const pickTarget = () => {
    let best = null
    for (const r of rows) {
      if (r.balance <= 0.005) continue
      if (!best) { best = r; continue }
      if (strategy === 'snowball') {
        if (r.balance < best.balance || (r.balance === best.balance && r.rate > best.rate)) best = r
      } else if (r.rate > best.rate || (r.rate === best.rate && r.balance < best.balance)) {
        best = r
      }
    }
    return best
  }

  while (month < maxMonths && rows.some((r) => r.balance > 0.005)) {
    month += 1

    // проценты за месяц: ставка годовых / 12
    for (const r of rows) {
      if (r.balance <= 0) continue
      const interest = r.balance * r.rate / 1200
      if (interest > 0) {
        r.balance += interest
        r.interest += interest
        totalInterest += interest
      }
    }

    // сначала минимальные платежи по всем
    let available = budget
    for (const r of rows) {
      if (r.balance <= 0 || available <= 0) continue
      const pay = Math.min(r.payment, r.balance, available)
      if (pay > 0) {
        r.balance -= pay
        available -= pay
      }
    }

    // излишек — в целевой долг; закрылся — берём следующий в том же месяце
    let guard = 0
    while (available > 0.005 && guard++ <= rows.length) {
      const target = pickTarget()
      if (!target) break
      const pay = Math.min(target.balance, available)
      target.balance -= pay
      available -= pay
    }

    for (const r of rows) {
      if (r.balance <= 0.005 && r.closedMonth == null) {
        r.balance = 0
        r.closedMonth = month
        r.closeDate = new Date(now.getFullYear(), now.getMonth() + month, 1)
      }
    }
  }

  const done = rows.length === 0 || rows.every((r) => r.closedMonth != null)
  const months = done ? month : null
  const freeDate = done && months != null
    ? new Date(now.getFullYear(), now.getMonth() + months, 1)
    : null

  const out = rows
    .map((r) => ({
      id: r.id,
      title: r.title,
      rate: r.rate,
      payment: round2(r.payment),
      start: round2(r.start),
      interest: Math.round(r.interest),
      closedMonth: r.closedMonth,
      closeDate: r.closeDate,
    }))
    .sort((a, b) => {
      if (a.closedMonth == null && b.closedMonth == null) return b.start - a.start
      if (a.closedMonth == null) return 1
      if (b.closedMonth == null) return -1
      return a.closedMonth - b.closedMonth || b.start - a.start
    })

  return {
    rows: out,
    count: out.length,
    months,
    freeDate,
    totalInterest: Math.round(totalInterest),
    minTotal: Math.round(minTotal),
    monthly: Math.round(budget),
    insufficient,
    capped: !done,
    done,
  }
}
