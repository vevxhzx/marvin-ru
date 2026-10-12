/* MFinance — мобильные финансы. Только живые данные через lib/api.js:
 * finSummary / finForecast / txs / accounts / debts / recurring / goals
 * (+ addTx / addAccount / addDebt+payDebt / addGoal+putGoal).
 * Долги — нейтрально («осталось X»), без заявлений о направлении.
 * Кит из ../ui.jsx, стили m-*. */
import { useEffect, useMemo, useState } from 'react'
import { ArrowDownLeft, ArrowUpRight, Plus } from 'lucide-react'
import { api, catColor, catLabel, money, parseNum, shortDate } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { Avatar, BigMoney, Card, HUES, Overline, Pill, ScreenTitle, ScrollTabs, SectionHead, Segmented } from '../ui.jsx'

const MINUS = '−'
const initialsOf = (s) => String(s || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?'
const hueOf = (s) => [...String(s || '')].reduce((a, c) => a + c.charCodeAt(0), 0) % HUES.length
const dm = (iso) => {
  const d = new Date(iso)
  if (Number.isNaN(d)) return ''
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'numeric' })
}

export default function MFinance() {
  const { t } = useI18n()
  const [tab, setTab] = useState('overview')
  const [days, setDays] = useState(30)
  const [sum, setSum] = useState(null)
  const [fc, setFc] = useState(null)
  const [txs, setTxs] = useState([])
  const [accounts, setAccounts] = useState([])
  const [debts, setDebts] = useState([])
  const [recurring, setRecurring] = useState([])
  const [goals, setGoals] = useState([])
  const [err, setErr] = useState(null)
  const [toastMsg, setToastMsg] = useState(null)

  const load = () => Promise.all([
    api.finSummary(days).catch(() => null),
    api.finForecast(days).catch(() => null),
    api.txs(days).catch(() => []),
    api.accounts().catch(() => []),
    api.debts().catch(() => []),
    api.recurring(true).catch(() => []),
    api.goals().catch(() => []),
  ]).then(([s, f, x, a, d, r, g]) => {
    if (!s && !f) { setErr(true); return }
    setSum(s); setFc(f); setTxs(x || []); setAccounts(a || [])
    setDebts(d || []); setRecurring(r || []); setGoals(g || []); setErr(null)
  })
  useEffect(() => { load() }, [days]) // eslint-disable-line

  const toast = (text) => {
    setToastMsg(text)
    window.clearTimeout(toast._t)
    toast._t = window.setTimeout(() => setToastMsg(null), 3000)
  }
  const mutate = async (fn, ok) => {
    try { await fn(); if (ok) toast(ok); load() } catch (e) { toast(String(e?.message || e)) }
  }

  const tabs = useMemo(() => [
    { id: 'overview', label: t('m.f_overview') },
    { id: 'ops', label: t('m.f_ops') },
    { id: 'accounts', label: t('m.f_accounts') },
    { id: 'debts', label: t('m.f_debts') },
    { id: 'subs', label: t('m.f_subs') },
    { id: 'goals', label: t('m.f_goals') },
  ], [t])

  if (err) {
    return (
      <div className="px-5 pt-10 text-center">
        <div className="text-[15px] text-white/70">{t('m.load_err')}</div>
        <button className="m-glass mt-3 rounded-full px-4 py-2 text-[13.5px]" onClick={load}>{t('m.retry')}</button>
      </div>
    )
  }
  if (!sum && !fc) return <div className="px-5 pt-10 text-[15px] text-white/50">{t('m.loading')}</div>

  return (
    <div>
      <ScreenTitle title={t('m.finance_title')} subtitle={t('m.finance_sub')} />
      <div className="mt-5 px-4">
        <ScrollTabs value={tab} onChange={setTab} options={tabs} />
      </div>
      <div key={tab} className="anim-rise">
        {tab === 'overview' && <Overview sum={sum} fc={fc} days={days} onDays={setDays} recurring={recurring} />}
        {tab === 'ops' && <Ops txs={txs} onMutate={mutate} />}
        {tab === 'accounts' && <Accounts accounts={accounts} onMutate={mutate} />}
        {tab === 'debts' && <Debts debts={debts} sum={sum} onMutate={mutate} />}
        {tab === 'subs' && <Subs recurring={recurring} />}
        {tab === 'goals' && <Goals goals={goals} onMutate={mutate} />}
      </div>
      {toastMsg && (
        <div className="anim-toast fixed bottom-24 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full border border-white/10 bg-[#121a46]/95 py-2.5 pl-4 pr-2.5 shadow-xl backdrop-blur-xl">
          <span className="max-w-[70vw] truncate text-[13.5px]">{toastMsg}</span>
        </div>
      )}
    </div>
  )
}

/* ───────── обзор ───────── */
function Overview({ sum, fc, days, onDays, recurring }) {
  const { t } = useI18n()
  const balance = sum?.total_balance ?? sum?.balance ?? fc?.balance ?? 0
  const spent = sum?.spent ?? 0
  const free = sum?.cashflow?.free ?? 0
  const safePerDay = sum?.safe?.per_day ?? fc?.safe_per_day ?? null
  const daysToIncome = sum?.safe?.days_left ?? fc?.days_to_income ?? null
  const runwayDays = fc?.runway_days ?? sum?.runway_days ?? null
  const pace = fc?.avg_day_spent ?? sum?.avg_daily ?? 0

  const cats = useMemo(() => {
    const by = sum?.by_category || {}
    return Object.entries(by).map(([name, v]) => ({ name, sum: Number(v) || 0 })).sort((a, b) => b.sum - a.sum)
  }, [sum])
  const catTotal = cats.reduce((s, c) => s + c.sum, 0) || spent
  const top5 = cats.slice(0, 5)

  const subs = useMemo(() => (recurring || [])
    .filter((r) => r.active !== false && r.kind !== 'income')
    .sort((a, b) => new Date(a.next_date) - new Date(b.next_date)), [recurring])

  const calm = runwayDays == null || runwayDays >= 30
  const tight = !calm && runwayDays >= 7
  const lowDate = fc?.min_date ? dm(fc.min_date) : ''

  return (
    <>
      <div className="mt-4 px-4">
        <div className="m-hero relative overflow-hidden rounded-[30px] p-5">
          <div className="pointer-events-none absolute -right-10 -top-20 h-52 w-52 rounded-full bg-white/25 blur-2xl" />
          <div className="relative flex items-center justify-between">
            <span className="text-[15px] font-semibold">{t('m.balance')}</span>
            <span className="text-[13px] text-white/75">{t('m.total_acc')}</span>
          </div>
          <BigMoney value={balance} size={54} className="relative mt-3" />
          <div className="m-tile tnum relative mt-3 inline-flex rounded-full px-3 py-1.5 text-[12.5px] font-medium">
            {t('m.spent_for', { n: days, v: money(spent) })}
          </div>
          <div className="relative mt-4 grid grid-cols-2 gap-2">
            <div className="m-tile rounded-[18px] px-3.5 py-3">
              <div className="text-[12px] text-white/75">{t('m.free')}</div>
              <div className="tnum mt-0.5 text-[17px] font-semibold">{money(free)}</div>
            </div>
            <div className="m-tile rounded-[18px] px-3.5 py-3">
              <div className="text-[12px] text-white/75">{t('m.safe_day')}</div>
              <div className="tnum mt-0.5 text-[17px] font-semibold">{safePerDay != null ? money(safePerDay) : '—'}</div>
            </div>
          </div>
          {daysToIncome != null && (
            <div className="relative mt-2.5 px-1 text-[12px] text-white/70">{t('m.days_to_income', { count: daysToIncome })}</div>
          )}
        </div>
      </div>

      <div className="mt-4 px-4">
        <Card className="p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[17px] font-semibold">{t('m.runway_title')}</div>
              <div className="mt-1 text-[13px] text-white/55">{t('m.runway_sub')}</div>
            </div>
            <Pill tone={calm ? 'green' : tight ? 'amber' : 'red'} dot>
              {t(calm ? 'm.calm' : 'm.tight')}
            </Pill>
          </div>
          <Runway days={runwayDays} />
          {lowDate && (
            <div className="-mt-2 text-center text-[13.5px] text-white/65">
              {t('m.runway_until', { date: lowDate, pace: money(pace) })}
            </div>
          )}
        </Card>
      </div>

      <div className="mt-4 px-4">
        <Card className="p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="text-[17px] font-semibold">{t('m.expenses')}</div>
            <Segmented
              size="sm"
              className="w-[196px]"
              value={String(days)}
              onChange={(v) => onDays(Number(v))}
              options={[
                { id: '7', label: t('m.days_n', { count: 7 }) },
                { id: '30', label: t('m.days_n', { count: 30 }) },
                { id: '90', label: t('m.days_n', { count: 90 }) },
              ]}
            />
          </div>
          <div className="tnum mt-3 text-[30px] font-semibold tracking-[-0.02em]">{money(spent)}</div>
          {catTotal > 0 && (
            <>
              <div className="mt-4 flex h-3 gap-[3px]">
                {cats.map((c) => (
                  <div key={c.name} className="rounded-full" style={{ flex: c.sum, background: catColor(c.name) }} />
                ))}
              </div>
              <div className="mt-3">
                {top5.map((c) => (
                  <div key={c.name} className="flex items-center gap-3 py-2">
                    <LetterTile letter={c.name[0]} color={catColor(c.name)} />
                    <div className="min-w-0 flex-1">
                      <div className="text-[14.5px] font-medium">{catLabel(c.name)}</div>
                      <div className="tnum text-[12px] text-white/45">{t('m.of_spent', { p: Math.round((c.sum / catTotal) * 100) })}</div>
                    </div>
                    <div className="tnum text-[14.5px] font-semibold">{money(c.sum)}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </Card>
      </div>

      {subs.length > 0 && (
        <div className="mt-6 px-4">
          <SectionHead title={t('m.next_charges')} />
          <div className="no-scrollbar -mx-4 flex gap-2.5 overflow-x-auto px-4">
            {subs.slice(0, 6).map((s) => (
              <div key={s.id} className="m-card w-[132px] shrink-0 rounded-[22px] p-3.5">
                <LetterTile letter={(s.title || '?')[0]} color={HUES[hueOf(s.title)]} />
                <div className="mt-3 truncate text-[13.5px] font-medium">{s.title}</div>
                <div className="tnum text-[15px] font-semibold">{money(s.amount)}</div>
                <div className="text-[12px] text-white/45">{s.next_date ? dm(s.next_date) : ''}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

/* gauge-запас хода: тики по референсу, живые дни */
function Runway({ days }) {
  const { t } = useI18n()
  const N = 41
  const cx = 150, cy = 126, r1 = 98, r2 = 114
  const frac = days == null ? 1 : Math.max(0, Math.min(days / 120, 1))
  const A = [91, 120, 255], B = [130, 242, 255]
  const mix = (k) => `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * k)).join(',')})`
  return (
    <svg viewBox="0 0 300 206" className="mx-auto mt-2 block w-full max-w-[300px]">
      {Array.from({ length: N }, (_, i) => {
        const k = i / (N - 1)
        const a = ((150 + k * 240) * Math.PI) / 180
        const on = k <= frac
        const long = i % 5 === 0
        const ri = long ? r1 - 8 : r1
        return (
          <line
            key={i}
            x1={cx + Math.cos(a) * ri}
            y1={cy + Math.sin(a) * ri}
            x2={cx + Math.cos(a) * r2}
            y2={cy + Math.sin(a) * r2}
            stroke={on ? mix(frac ? k / frac : 1) : 'rgba(255,255,255,0.13)'}
            strokeWidth={long ? 3.4 : 2.6}
            strokeLinecap="round"
          />
        )
      })}
      <text x={cx} y={cy + 6} textAnchor="middle" fill="#fff" fontSize="60" fontWeight="700" letterSpacing="-2">
        {days ?? '—'}
      </text>
      {days != null && (
        <text x={cx} y={cy + 34} textAnchor="middle" fill="rgba(255,255,255,0.6)" fontSize="15">
          {t('m.days_n', { count: days })}
        </text>
      )}
      <text x={cx - 90} y={cy + 74} textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="10.5">0</text>
      <text x={cx + 90} y={cy + 74} textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="10.5">120</text>
    </svg>
  )
}

/* ───────── операции ───────── */
function Ops({ txs, onMutate }) {
  const { t } = useI18n()
  const [title, setTitle] = useState('')
  const [amount, setAmount] = useState('')
  const [kind, setKind] = useState('expense')

  const income = txs.filter((o) => o.kind === 'income').reduce((s, o) => s + Number(o.amount || 0), 0)
  const expense = txs.filter((o) => o.kind === 'expense').reduce((s, o) => s + Number(o.amount || 0), 0)
  const groups = useMemo(() => {
    const m = new Map()
    for (const o of txs) {
      const k = o.date ? new Date(o.date).toDateString() : ''
      if (!m.has(k)) m.set(k, [])
      m.get(k).push(o)
    }
    return [...m.entries()].sort((a, b) => new Date(b[0]) - new Date(a[0]))
  }, [txs])

  const submit = (e) => {
    e?.preventDefault()
    const v = parseNum(amount)
    if (!title.trim() || !Number.isFinite(v) || v <= 0) return
    onMutate(() => api.addTx({ amount: v, kind, note: title.trim() }), t('m.done'))
    setTitle(''); setAmount('')
  }

  return (
    <div className="mt-4 space-y-4 px-4">
      <div className="grid grid-cols-2 gap-2">
        <Card className="rounded-[22px] p-4">
          <div className="flex items-center gap-1.5 text-[12px] text-white/55">
            <ArrowDownLeft size={14} className="text-[#7cf0c0]" />
            {t('m.came')}
          </div>
          <div className="tnum mt-1 text-[19px] font-semibold text-[#7cf0c0]">+{money(income)}</div>
        </Card>
        <Card className="rounded-[22px] p-4">
          <div className="flex items-center gap-1.5 text-[12px] text-white/55">
            <ArrowUpRight size={14} className="text-[#ff9aac]" />
            {t('m.gone')}
          </div>
          <div className="tnum mt-1 text-[19px] font-semibold">{MINUS}{money(expense)}</div>
        </Card>
      </div>
      {groups.map(([k, list]) => (
        <div key={k}>
          <Overline className="mb-2 px-1">{k ? shortDate(list[0].date) : t('m.no_due')}</Overline>
          <Card className="p-1.5">
            {list.map((o, i) => (
              <div key={o.id} className={`flex items-center gap-3 px-3 py-3${i < list.length - 1 ? ' border-b border-white/[0.05]' : ''}`}>
                <LetterTile letter={(o.title || o.note || o.category || '?')[0]} color={catColor(o.category || '')} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[15px] font-medium">{o.title || o.note || catLabel(o.category || '')}</div>
                  <div className="text-[12.5px] text-white/45">{o.category ? catLabel(o.category) : ''}{o.account ? ` · ${o.account}` : ''}</div>
                </div>
                <div className={`tnum text-[15px] font-semibold${o.kind === 'income' ? ' text-[#7cf0c0]' : ''}`}>
                  {o.kind === 'income' ? `+${money(o.amount)}` : `${MINUS}${money(o.amount)}`}
                </div>
              </div>
            ))}
          </Card>
        </div>
      ))}
      {groups.length === 0 && <div className="py-6 text-center text-[14px] text-white/45">{t('m.list_empty')}</div>}
      <form onSubmit={submit} className="flex h-[54px] items-center gap-2 rounded-full border border-white/10 bg-[#0f1640]/75 pl-4 pr-1.5 transition focus-within:border-[#7d95ff]/50">
        <Plus size={20} className="shrink-0 text-[#8ea3ff]" />
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('m.op_title_ph')}
          className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-white/40"
        />
        <input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder={t('common.amount')}
          inputMode="decimal"
          className="tnum w-[76px] shrink-0 bg-transparent text-right text-[15px] outline-none placeholder:text-white/40"
        />
        <button
          type="button"
          onClick={() => setKind((k) => (k === 'expense' ? 'income' : 'expense'))}
          className={`shrink-0 rounded-full px-3 py-2 text-[13px] font-semibold${kind === 'income' ? ' bg-[#3ddc97]/20 text-[#7cf0c0]' : ' bg-white/10 text-white/70'}`}
        >
          {t(kind === 'income' ? 'm.income' : 'm.expense')}
        </button>
        {(title || amount) && (
          <button type="submit" aria-label={t('common.add')} className="m-fab anim-pop grid h-10 w-10 shrink-0 place-items-center rounded-full text-white">
            <ArrowUpRight size={18} strokeWidth={2.5} />
          </button>
        )}
      </form>
    </div>
  )
}

/* ───────── счета ───────── */
function Accounts({ accounts, onMutate }) {
  const { t } = useI18n()
  const [name, setName] = useState('')
  const [balance, setBalance] = useState('')
  const cash = accounts.filter((a) => a.kind !== 'debt_only')
  const total = cash.reduce((s, a) => s + (Number(a.balance) || 0), 0)

  const submit = (e) => {
    e?.preventDefault()
    if (!name.trim()) return
    const v = parseNum(balance)
    onMutate(() => api.addAccount({ name: name.trim(), kind: 'bank', balance: Number.isFinite(v) ? v : 0 }), t('m.done'))
    setName(''); setBalance('')
  }

  return (
    <div className="mt-4 space-y-3 px-4">
      <Card className="p-5">
        <Overline>{t('m.total_acc')}</Overline>
        <BigMoney value={total} size={40} className="mt-2" />
        {total > 0 && (
          <div className="mt-4 flex h-2.5 gap-[3px]">
            {cash.map((a) => (
              <div key={a.id ?? a.name} className="rounded-full" style={{ flex: Math.max(Number(a.balance) || 0, 1), background: HUES[hueOf(a.name)] }} />
            ))}
          </div>
        )}
      </Card>
      {accounts.map((a) => (
        <Card key={a.id ?? a.name} className="flex items-center gap-3 rounded-[24px] p-4">
          <LetterTile letter={(a.name || '?')[0]} color={HUES[hueOf(a.name)]} />
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-medium">{a.name}</div>
            {a.kind === 'debt_only' && <div className="text-[12.5px] text-white/45">{t('m.f_debts')}</div>}
          </div>
          <div className="tnum text-[15.5px] font-semibold">{money(a.balance)}</div>
        </Card>
      ))}
      {accounts.length === 0 && <div className="py-6 text-center text-[14px] text-white/45">{t('m.list_empty')}</div>}
      <form onSubmit={submit} className="flex h-[54px] items-center gap-2 rounded-full border border-white/10 bg-[#0f1640]/75 pl-4 pr-1.5 transition focus-within:border-[#7d95ff]/50">
        <Plus size={20} className="shrink-0 text-[#8ea3ff]" />
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('m.acc_new')} className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-white/40" />
        <input value={balance} onChange={(e) => setBalance(e.target.value)} placeholder={t('common.amount')} inputMode="decimal" className="tnum w-[76px] shrink-0 bg-transparent text-right text-[15px] outline-none placeholder:text-white/40" />
        {name && <button type="submit" aria-label={t('common.add')} className="m-fab anim-pop grid h-10 w-10 shrink-0 place-items-center rounded-full text-white"><ArrowUpRight size={18} strokeWidth={2.5} /></button>}
      </form>
    </div>
  )
}

/* ───────── долги (нейтрально: только «осталось X») ───────── */
function Debts({ debts, sum, onMutate }) {
  const { t } = useI18n()
  const [title, setTitle] = useState('')
  const [amount, setAmount] = useState('')
  const [payId, setPayId] = useState(null)
  const [payAmt, setPayAmt] = useState('')
  const open = debts.filter((d) => !d.closed)
  const total = sum?.debts_total ?? open.reduce((s, d) => s + (Number(d.remaining) || 0), 0)

  const submit = (e) => {
    e?.preventDefault()
    const v = parseNum(amount)
    if (!title.trim() || !Number.isFinite(v) || v <= 0) return
    onMutate(() => api.addDebt({ title: title.trim(), total: v, remaining: v }), t('m.done'))
    setTitle(''); setAmount('')
  }
  const pay = (id) => {
    const v = parseNum(payAmt)
    if (!Number.isFinite(v) || v <= 0) return
    onMutate(() => api.payDebt(id, v), t('m.done'))
    setPayId(null); setPayAmt('')
  }

  return (
    <div className="mt-4 space-y-3 px-4">
      <div className="m-hero relative overflow-hidden rounded-[28px] p-5">
        <div className="pointer-events-none absolute -right-10 -top-16 h-44 w-44 rounded-full bg-white/20 blur-2xl" />
        <div className="relative text-[15px] font-semibold">{t('m.f_debts')}</div>
        <BigMoney value={total} size={44} className="relative mt-2" />
        <div className="relative mt-2 text-[13px] text-white/75">{t('m.entries_n', { count: open.length })}</div>
      </div>
      {debts.map((d) => (
        <Card key={d.id} className="rounded-[24px] p-4">
          <div className="flex items-center gap-3">
            <Avatar initials={initialsOf(d.creditor || d.title)} hue={hueOf(d.title)} size={42} />
            <div className="min-w-0 flex-1">
              <div className="text-[15.5px] font-semibold">{d.title}</div>
              {d.creditor && <div className="text-[12.5px] text-white/50">{d.creditor}</div>}
            </div>
            <div className="tnum text-[16px] font-semibold text-[#ffd581]">{money(d.remaining)}</div>
          </div>
          <div className="mt-3 flex items-center justify-between gap-2">
            <Pill tone={d.closed ? 'green' : 'gray'}>{d.closed ? t('m.debt_closed') : t('m.left', { v: money(d.remaining) })}</Pill>
            {!d.closed && payId !== d.id && (
              <button onClick={() => { setPayId(d.id); setPayAmt('') }} className="shrink-0 rounded-full bg-white/10 px-3 py-1.5 text-[13px] font-medium transition active:scale-95">
                {t('m.debt_pay')}
              </button>
            )}
          </div>
          {!d.closed && payId === d.id && (
            <form onSubmit={(e) => { e.preventDefault(); pay(d.id) }} className="anim-rise mt-2.5 flex items-center gap-2">
              <input value={payAmt} onChange={(e) => setPayAmt(e.target.value)} placeholder={t('common.amount')} inputMode="decimal" autoFocus className="tnum min-w-0 flex-1 rounded-full border border-white/10 bg-white/[0.05] px-4 py-2.5 text-[15px] outline-none placeholder:text-white/35 focus:border-[#7d95ff]/50" />
              <button type="submit" className="m-active shrink-0 rounded-full px-4 py-2.5 text-[14px] font-semibold">{t('m.save')}</button>
            </form>
          )}
        </Card>
      ))}
      {debts.length === 0 && <div className="py-6 text-center text-[14px] text-white/45">{t('m.list_empty')}</div>}
      <form onSubmit={submit} className="flex h-[54px] items-center gap-2 rounded-full border border-white/10 bg-[#0f1640]/75 pl-4 pr-1.5 transition focus-within:border-[#7d95ff]/50">
        <Plus size={20} className="shrink-0 text-[#8ea3ff]" />
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('m.debt_new')} className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-white/40" />
        <input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={t('common.amount')} inputMode="decimal" className="tnum w-[76px] shrink-0 bg-transparent text-right text-[15px] outline-none placeholder:text-white/40" />
        {(title || amount) && <button type="submit" aria-label={t('common.add')} className="m-fab anim-pop grid h-10 w-10 shrink-0 place-items-center rounded-full text-white"><ArrowUpRight size={18} strokeWidth={2.5} /></button>}
      </form>
    </div>
  )
}

/* ───────── подписки ───────── */
function Subs({ recurring }) {
  const { t } = useI18n()
  const subs = (recurring || []).filter((r) => r.active !== false && r.kind !== 'income')
  const total = subs.reduce((s, x) => s + (Number(x.amount) || 0), 0)
  return (
    <div className="mt-4 space-y-3 px-4">
      <Card className="p-5">
        <Overline>{t('m.per_month')}</Overline>
        <BigMoney value={total} size={40} className="mt-2" />
        <div className="tnum mt-2 text-[13px] text-white/55">{t('m.per_year', { v: money(total * 12) })} · {t('m.entries_n', { count: subs.length })}</div>
      </Card>
      {subs.length > 0 && (
        <Card className="p-1.5">
          {subs.map((s, i) => (
            <div key={s.id} className={`flex items-center gap-3 px-3 py-3${i < subs.length - 1 ? ' border-b border-white/[0.05]' : ''}`}>
              <LetterTile letter={(s.title || '?')[0]} color={HUES[hueOf(s.title)]} />
              <div className="min-w-0 flex-1">
                <div className="text-[15px] font-medium">{s.title}</div>
                <div className="text-[12.5px] text-white/45">{s.next_date ? t('m.charge_on', { date: dm(s.next_date) }) : ''}</div>
              </div>
              <div className="tnum text-[15px] font-semibold">{money(s.amount)}</div>
            </div>
          ))}
        </Card>
      )}
      {subs.length === 0 && <div className="py-6 text-center text-[14px] text-white/45">{t('m.list_empty')}</div>}
    </div>
  )
}

/* ───────── цели ───────── */
function Goals({ goals, onMutate }) {
  const { t } = useI18n()
  const [title, setTitle] = useState('')
  const [target, setTarget] = useState('')
  const [putId, setPutId] = useState(null)
  const [putAmt, setPutAmt] = useState('')

  const submit = (e) => {
    e?.preventDefault()
    const v = parseNum(target)
    if (!title.trim() || !Number.isFinite(v) || v <= 0) return
    onMutate(() => api.addGoal({ title: title.trim(), target: v }), t('m.done'))
    setTitle(''); setTarget('')
  }
  const put = (id) => {
    const v = parseNum(putAmt)
    if (!Number.isFinite(v) || v <= 0) return
    onMutate(() => api.putGoal(id, v), t('m.done'))
    setPutId(null); setPutAmt('')
  }

  return (
    <div className="mt-4 space-y-3 px-4">
      {goals.map((g) => {
        const p = g.target ? (Number(g.saved) || 0) / Number(g.target) : 0
        const color = HUES[hueOf(g.title)]
        return (
          <Card key={g.id} className="rounded-[24px] p-5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[16px] font-semibold">{g.title}</span>
              <span className="tnum text-[13px] font-semibold">{Math.round(p * 100)}%</span>
            </div>
            <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-white/[0.08]">
              <div className="h-full rounded-full" style={{ width: `${Math.max(p * 100, 2)}%`, background: color }} />
            </div>
            <div className="tnum mt-2 flex justify-between text-[12.5px] text-white/55">
              <span>{money(g.saved)}</span>
              <span>{t('m.goal_of', { v: money(g.target) })}</span>
            </div>
            {putId !== g.id ? (
              <button onClick={() => { setPutId(g.id); setPutAmt('') }} className="mt-3 rounded-full bg-white/10 px-3 py-1.5 text-[13px] font-medium transition active:scale-95">
                {t('m.goal_put')}
              </button>
            ) : (
              <form onSubmit={(e) => { e.preventDefault(); put(g.id) }} className="anim-rise mt-3 flex items-center gap-2">
                <input value={putAmt} onChange={(e) => setPutAmt(e.target.value)} placeholder={t('common.amount')} inputMode="decimal" autoFocus className="tnum min-w-0 flex-1 rounded-full border border-white/10 bg-white/[0.05] px-4 py-2.5 text-[15px] outline-none placeholder:text-white/35 focus:border-[#7d95ff]/50" />
                <button type="submit" className="m-active shrink-0 rounded-full px-4 py-2.5 text-[14px] font-semibold">{t('m.save')}</button>
              </form>
            )}
          </Card>
        )
      })}
      {goals.length === 0 && <div className="py-6 text-center text-[14px] text-white/45">{t('m.list_empty')}</div>}
      <form onSubmit={submit} className="flex h-[54px] items-center gap-2 rounded-full border border-white/10 bg-[#0f1640]/75 pl-4 pr-1.5 transition focus-within:border-[#7d95ff]/50">
        <Plus size={20} className="shrink-0 text-[#8ea3ff]" />
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('m.goal_new')} className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-white/40" />
        <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder={t('common.amount')} inputMode="decimal" className="tnum w-[76px] shrink-0 bg-transparent text-right text-[15px] outline-none placeholder:text-white/40" />
        {(title || target) && <button type="submit" aria-label={t('common.add')} className="m-fab anim-pop grid h-10 w-10 shrink-0 place-items-center rounded-full text-white"><ArrowUpRight size={18} strokeWidth={2.5} /></button>}
      </form>
    </div>
  )
}

function LetterTile({ letter, color }) {
  return (
    <div className="grid h-10 w-10 shrink-0 place-items-center rounded-[12px] text-[16px] font-bold text-[#0e1438]" style={{ background: color }}>
      {String(letter || '?').toUpperCase()}
    </div>
  )
}
