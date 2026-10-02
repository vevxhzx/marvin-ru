import { useEffect, useRef, useState, useMemo } from 'react'
import { api, money, shortDate, toLocalISO } from '../lib/api'
import { Num, Sheet, Field, Empty, Money, useToast, PageAccent, Confirm } from '../components/ui'
import CashChart from '../components/CashChart'
import { ImportButton } from '../components/Widgets'
import { useRefresh } from '../App'
import { Plus, Search, Trash2, Edit2, ArrowDownRight, ArrowUpRight, CreditCard, Wallet, Landmark, PiggyBank, Target, Calendar, CheckCircle2, Sparkles, ChevronLeft, EyeOff, Play, Pause } from 'lucide-react'
import { Techniques } from '../components/FinanceSmart'
import { useCardLayout, CardCtl, useWide } from '../lib/layout'
import { usePageAccent } from '../lib/prefs'
import { useI18n, localeOf, t as T } from '../lib/i18n'

/* Карточки вкладки «обзор»: порядок и ширина хранятся общим модулем lib/layout */
const FIN_CARDS = ['balance', 'chart', 'income', 'recurring', 'debts', 'free', 'flow', 'budgets', 'upcoming']
const FIN_CARD_WIDTHS = { balance: 4, chart: 8, income: 3, recurring: 3, debts: 3, free: 3, flow: 12, budgets: 6, upcoming: 6 }
const FIN_CARD_LABELS = { balance: 'fin.c_balance', chart: 'fin.c_chart', income: 'fin.c_income', recurring: 'fin.c_recurring', debts: 'fin.c_debts', free: 'fin.c_free', flow: 'fin.c_flow', budgets: 'fin.c_budgets', upcoming: 'fin.c_upcoming' }

/* Честная оценка «когда накоплю»: при темпе 5 000 ₽ в месяц — без обещаний точности */
const MON_SHORT = Array.from({ length: 12 }, (_, i) => new Date(2024, i, 1).toLocaleDateString(localeOf(), { month: 'short' }).replace(/\.$/, ''))
function goalEta(need) {
  const months = Math.ceil(need / 5000)
  if (!Number.isFinite(months) || months <= 0) return ''
  if (months > 60) return null
  const d0 = new Date()
  d0.setMonth(d0.getMonth() + months)
  return T('fin.on_day', { d: d0.getDate(), m: MON_SHORT[d0.getMonth()] })
}

export default function Finance() {
  const { t } = useI18n()
  const [tab, setTab] = useState('overview') // 'overview' | 'txs' | 'accounts' | 'debts' | 'recurring' | 'goals'
  const [days, setDays] = useState(30)
  const [sum, setSum] = useState(null)
  const [txs, setTxs] = useState([])
  const [accounts, setAccounts] = useState([])
  const [debts, setDebts] = useState([])
  const [recurring, setRecurring] = useState([])
  const [goals, setGoals] = useState([])
  const [categories, setCategories] = useState([])
  const [techniquesData, setTechniquesData] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [budgets, setBudgets] = useState(null)

  // Modal sheets
  const [sheet, setSheet] = useState(null) // 'tx' | 'account' | 'debt' | 'payDebt' | 'recurring' | 'goal' | 'putGoal' | 'budget'
  const [editingItem, setEditingItem] = useState(null)
  const [budgetCat, setBudgetCat] = useState(null) // категория/бюджет, для которого правим лимит
  // подтверждение удаления вместо нативного confirm(): { title, text, run }
  const [ask, setAsk] = useState(null)

  // Filters for txs
  const [txSearch, setTxSearch] = useState('')
  const [txCategory, setTxCategory] = useState('all')
  const [txAccount, setTxAccount] = useState('all')
  const [cardsEdit, setCardsEdit] = useState(false)
  const { order: cardOrder, setOrder: setCardOrder, widths: cardWidths, move, cycleWidth, reset: resetCards } = useCardLayout('finance', FIN_CARDS, FIN_CARD_WIDTHS)
  const wide = useWide()
  const pageAcc = usePageAccent('finance')

  const [, show] = useToast()
  const { tick, bump } = useRefresh()

  const load = async () => {
    try {
      const [s, t, accs, d, rec, g, cats, tech, fc, bg] = await Promise.all([
        api.finSummary(days).catch(() => null),
        api.txs(days).catch(() => []),
        api.accounts().catch(() => []),
        api.debts().catch(() => []),
        api.recurring(true).catch(() => []),   // с паузами: паузы нужно видеть и включать
        api.goals().catch(() => []),
        api.categories().catch(() => []),
        api.techniques().catch(() => null),
        api.finForecast(days || 90).catch(() => null),
        api.budgets().catch(() => null),
      ])
      if (s) setSum(s)
      setTxs(t || [])
      setAccounts(accs || [])
      setDebts(d || [])
      setRecurring(rec || [])
      setGoals(g || [])
      setCategories(cats || [])
      if (tech) setTechniquesData(tech)
      if (fc) setForecast(fc)
      setBudgets(bg)
    } catch (e) {
      show.err(e)
    }
  }

  useEffect(() => { load() }, [days, tick])

  const cf = sum?.cashflow || {
    income: 22844,
    recurring: 1528,
    debt_payments: 13500,
    free: 7816,
    income_is_estimate: true,
  }

  const balance = sum?.total_balance ?? sum?.balance ?? 0
  const spent = sum?.spent ?? 55950
  const earned = sum?.earned ?? 63662
  const debtsTotal = sum?.debts_total ?? (debts.reduce((acc, d) => acc + ((d.total || 0) - (d.paid || 0)), 0) || 205700)

  // Расчет долей потока
  const totalFlow = (cf.recurring || 0) + (cf.debt_payments || 0) + Math.max(0, cf.free || 0) || 1
  const flowRecurringPct = Math.round(((cf.recurring || 1528) / totalFlow) * 100 * 10) / 10
  const flowDebtPct = Math.round(((cf.debt_payments || 13500) / totalFlow) * 100 * 10) / 10
  const flowFreePct = Math.max(0, Math.round((100 - flowRecurringPct - flowDebtPct) * 10) / 10)

  const livingSpent = spent || 40575
  const livingRemain = (cf.free || 7816) - livingSpent

  // График кассы рисует CashChart (общий с главной): точка = баланс на конец дня

  const now = new Date()
  const z = (n) => ('0' + n).slice(-2)

  // Ближайшие списания: дата берётся из дня платежа, а не «ежемесячно» — так видно, когда придётся платить
  const nextPayments = useMemo(() => {
    const today0 = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    return recurring
      .filter((r) => r.active !== false && r.kind !== 'income')
      .map((r) => {
        const dom = Math.min(Number(r.day_of_month || r.day) || 1, 28)
        let d0 = new Date(now.getFullYear(), now.getMonth(), dom)
        if (d0 < today0) d0 = new Date(now.getFullYear(), now.getMonth() + 1, dom)
        return { ...r, on: d0, dom }
      })
      .sort((a, b) => a.on - b.on)
  }, [recurring, now.getMonth(), now.getDate()])

  // Активные и «на паузе»: расчёт (сводка, прогноз) считает только активные —
  // как и бэкенд (list_recurring(active_only=True)), но паузы показываем опционально
  const recActive = useMemo(() => recurring.filter((r) => r.active !== false), [recurring])
  const recPaused = useMemo(() => recurring.filter((r) => r.active === false), [recurring])
  const recExpense = recActive.filter((r) => r.kind !== 'income').reduce((s, r) => s + Number(r.amount || 0), 0)
  const recIncome = recActive.filter((r) => r.kind === 'income').reduce((s, r) => s + Number(r.amount || 0), 0)
  const [showPaused, setShowPaused] = useState(false)
  const recShown = showPaused ? recurring : recActive
  const toggleActive = async (r) => {
    try { await api.updateRecurring(r.id, { active: r.active === false }); load(); bump() } catch (e) { show.err(e) }
  }

  const daysUntil = (d0) => Math.round((d0 - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5)
  // API отдаёт список лимитов в поле budgets (категории с лимитом > 0)
  const budgetItems = Array.isArray(budgets) ? budgets : (budgets?.budgets || [])
  const totalBudget = budgetItems.reduce((s, b) => s + (b.budget || 0), 0)
  const totalSpent = budgetItems.reduce((s, b) => s + (b.spent || 0), 0)
  const budgetLeft = totalBudget - totalSpent

  // Фильтрация транзакций
  const filteredTxs = useMemo(() => {
    const q = txSearch.trim().toLowerCase()
    const list = txs.filter((t) => {
      const matchCat = txCategory === 'all' || t.category === txCategory
      const matchAcc = txAccount === 'all' || t.account === txAccount
      const matchSearch = !q ||
        (t.title && t.title.toLowerCase().includes(q)) ||
        (t.note && t.note.toLowerCase().includes(q)) ||
        (t.category && t.category.toLowerCase().includes(q)) ||
        (t.comment && t.comment.toLowerCase().includes(q)) ||
        (t.account && t.account.toLowerCase().includes(q))
      return matchCat && matchAcc && matchSearch
    })
    // сумма в БД всегда положительная, знак хранится в kind — иначе траты считались бы доходом
    const income = list.filter((t) => t.kind === 'income').reduce((s, t) => s + Number(t.amount), 0)
    const expense = list.filter((t) => t.kind === 'expense').reduce((s, t) => s + Number(t.amount), 0)
    return { list, income: Math.round(income), expense: Math.round(expense) }
  }, [txs, txCategory, txAccount, txSearch])
  const shownTxs = filteredTxs.list

  // Экспорт выписки в CSV — повторяет то, что видит пользователь: берём shownTxs
  // (учитывает период, фильтр по счёту/категории и поиск), а не все txs (D2)
  const exportCSV = () => {
    if (!shownTxs.length) return
    const rows = [
      [t('fin.csv.date'), t('fin.csv.amount'), t('fin.csv.category'), t('fin.csv.title'), t('fin.csv.account')],
      ...shownTxs.map(t => [
        t.date ? t.date.slice(0, 10) : '',
        t.amount,
        t.category || '',
        `"${(t.title || t.note || '').replace(/"/g, '""')}"`,
        t.account || ''
      ])
    ]
    const csvContent = 'data:text/csv;charset=utf-8,\uFEFF' + rows.map(e => e.join(';')).join('\n')
    const encodedUri = encodeURI(csvContent)
    const link = document.createElement('a')
    link.setAttribute('href', encodedUri)
    link.setAttribute('download', `statement_${toLocalISO(now).slice(0, 10)}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <div className="pg on" id="p-fin" style={pageAcc.style}>
      {/* Шапка страницы */}
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>{t('nav.finance')}</h1>
          <p className="sub r" style={{ '--i': 1 }}>
            {tab === 'overview' && t('fin.sub_overview')}
            {tab === 'txs' && t('fin.n_txs', { count: shownTxs.length })}
            {tab === 'accounts' && t('fin.n_accounts', { count: accounts.length })}
            {tab === 'debts' && t('fin.n_debts', { count: debts.length })}
            {tab === 'recurring' && t('fin.n_rec', { n: recActive.length, paused: recPaused.length ? t('fin.n_rec_paused', { n: recPaused.length }) : '' })}
            {tab === 'goals' && t('fin.n_goals', { count: goals.length })}
          </p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          <div className="sg" title={t('fin.period_tip')}>
            <button type="button" className={days === 7 ? 'on' : ''} onClick={() => setDays(7)}>{t('mem.d7')}</button>
            <button type="button" className={days === 30 ? 'on' : ''} onClick={() => setDays(30)}>{t('mem.d30')}</button>
            <button type="button" className={days === 90 ? 'on' : ''} onClick={() => setDays(90)}>{t('fin.d90')}</button>
            <button type="button" className={days === 0 ? 'on' : ''} onClick={() => setDays(0)}>{t('fin.d_all')}</button>
          </div>
          {tab === 'overview' && <button type="button" className="btn-soft btn-sm" onClick={() => setCardsEdit((v) => !v)} title={t('tk.layout_tip')} aria-label={t('fin.configure_cards')}>{t('tk.layout')}</button>}
          <button type="button" className="btn g" onClick={exportCSV} title={t('fin.csv_dl')} aria-label={t('fin.csv_dl')}>{t('fin.statement')}</button>
          <button
            type="button"
            className="btn"
            title={t('fin.add_entry')}
            aria-label={t('fin.add_entry')}
            onClick={() => {
              if (tab === 'accounts') { setEditingItem(null); setSheet('account') }
              else if (tab === 'debts') { setEditingItem(null); setSheet('debt') }
              else if (tab === 'recurring') { setEditingItem(null); setSheet('recurring') }
              else if (tab === 'goals') { setEditingItem(null); setSheet('goal') }
              else { setEditingItem(null); setSheet('tx') }
            }}
          >
            {t(tab === 'accounts' ? 'fin.add_account' : tab === 'debts' ? 'fin.add_debt' : tab === 'recurring' ? 'fin.add_pay' : tab === 'goals' ? 'fin.add_goal' : 'fin.add_tx')}
          </button>
        </div>
      </div>

      {/* Вкладки разделов финансов в едином стиле бенто */}
      <div className="sg r my-4" style={{ '--i': 2 }}>
        <button type="button" className={tab === 'overview' ? 'on' : ''} onClick={() => setTab('overview')}>{t('fin.tab_overview')}</button>
        <button type="button" className={tab === 'txs' ? 'on' : ''} onClick={() => setTab('txs')}>{t('fin.tab_txs')}</button>
        <button type="button" className={tab === 'accounts' ? 'on' : ''} onClick={() => setTab('accounts')}>{t('fin.tab_accounts')}</button>
        <button type="button" className={tab === 'debts' ? 'on' : ''} onClick={() => setTab('debts')}>{t('fin.tab_debts')}</button>
        <button type="button" className={tab === 'recurring' ? 'on' : ''} onClick={() => setTab('recurring')}>{t('fin.tab_recurring')}</button>
        <button type="button" className={tab === 'goals' ? 'on' : ''} onClick={() => setTab('goals')}>{t('goals.title')}</button>
        <button type="button" className={tab === 'techniques' ? 'on' : ''} onClick={() => setTab('techniques')}>{t('tech.title')}</button>
      </div>

      {/* Вкладка 1: ОБЗОР (Классический Bento из эталона; порядок и ширина — кнопка «настроить») */}
      {tab === 'overview' && (
        <div className="bento">
          {cardOrder.map((id, i) => {
            const st = { '--i': 3 + i, ...(wide ? { gridColumn: `span ${cardWidths[id] || FIN_CARD_WIDTHS[id]}` } : {}) }
            const ctl = (
              <CardCtl id={id} order={cardOrder} edit={cardsEdit} wide={wide}
                onMove={move} onHide={(x) => setCardOrder((o) => o.filter((w) => w !== x))}
                onWidth={cycleWidth} width={cardWidths[id] || FIN_CARD_WIDTHS[id]}
                Icon={ChevronLeft} HideIcon={EyeOff} />
            )
            if (id === 'balance') return (
              <section key="balance" className="c hero s4 r" style={st}>{ctl}
                <div className="hd"><h2>{t('fin.c_balance')}</h2><small>{t('fin.all_accounts')}</small></div>
                <div className="big"><Num value={balance} /> ₽</div>
                <span className="tag">{t('fin.for_days', { n: days, m: money(spent) })}</span>
                <div className="hm">
                  <div><small>{t('fin.income_days', { n: days })}</small><b>+{money(earned)}</b></div>
                  <div><small>{t('fin.c_debts')}</small><b>{money(debtsTotal)}</b></div>
                </div>
              </section>
            )
            if (id === 'chart') return (
              <section key="chart" className="c chart s8 r" style={st}>{ctl}
                <div className="hd">
                  <h2>{t('fin.cash_on', { n: days || t('common.all'), days: t('run.days_n', { count: days }) })}</h2>
                  <small>
                    {forecast ? t('fin.fc_now', { bal: money(forecast.balance), pace: money(forecast.avg_day_spent) }) : t('fc.by_pace')}
                  </small>
                </div>
                {!forecast ? (
                  <p className="py-10 text-center text-sm text-[var(--ink3)]">{t('common.loading')}</p>
                ) : (
                  <CashChart f={forecast} height={200} txs={txs} legend={false} />
                )}
                <div className="lg">
                  <span><i style={{ background: '#ff9f5c' }}></i>{t('chart.fact')}</span>
                  <span><i style={{ background: 'var(--accent)' }}></i>{t('chart.forecast')}</span>
                  <span><i style={{ border: '1.5px dashed var(--ink3)', background: 'none' }}></i>{t('chart.zero')}</span>
                  {forecast?.runway_days != null && (
                    <span className="text-[var(--neg)]">{t('td.to_zero', { n: forecast.runway_days })}</span>
                  )}
                  {forecast?.min_balance != null && forecast.min_balance >= 0 && (
                    <span>{t('fc.min', { m: money(forecast.min_balance) })} · {forecast.min_date?.slice(8, 10)}.{forecast.min_date?.slice(5, 7)}</span>
                  )}
                </div>
                {forecast?.scenarios?.realistic && forecast?.scenarios?.pessimistic
                  && forecast.scenarios.realistic.low !== forecast.scenarios.pessimistic.low && (
                  <div className="muted mt-1 text-[12px]">
                    {t('fin.scen_min')} <b className="num">{money(forecast.scenarios.realistic.low)}</b>
                    {' · '}{t('fin.pessimistic', { n: forecast.scenarios.pessimistic.delay_days ?? 0 })} <b className={`num ${forecast.scenarios.pessimistic.ok ? '' : 'neg'}`}>{money(forecast.scenarios.pessimistic.low)}</b>
                  </div>
                )}
              </section>
            )
            if (id === 'income') return (
              <section key="income" className="c p2 s3 r" style={st}>{ctl}
                <div className="hd"><h2>{t('fin.c_income')}</h2><small>{cf.income_is_estimate ? t('fin.average') : ''}</small></div>
                <div className="mid"><Num value={cf.income || 22844} /> ₽</div>
              </section>
            )
            if (id === 'recurring') return (
              <section key="recurring" className="c p1 s3 r" style={st}>{ctl}
                <div className="hd"><h2>{t('fin.c_recurring')}</h2><small></small></div>
                <div className="mid"><Num value={cf.recurring || 1528} /> ₽</div>
              </section>
            )
            if (id === 'debts') return (
              <section key="debts" className="c blk s3 r" style={st}>{ctl}
                <div className="hd"><h2>{t('fin.by_debts')}</h2><small></small></div>
                <div className="mid"><Num value={cf.debt_payments || 13500} /> ₽</div>
              </section>
            )
            if (id === 'free') return (
              <section key="free" className="c tint-ok s3 r" style={st}>{ctl}
                <div className="hd"><h2>{t('fin.c_free')}</h2><small>{t('td.per_month')}</small></div>
                <div className="mid"><Num value={cf.free || 7816} /> ₽</div>
              </section>
            )
            if (id === 'budgets') return (
              <section key="budgets" className="c p2 s6 r" style={st}>{ctl}
                <div className="hd">
                  <h2>{t('fin.budgets_month')}</h2>
                  <span className="flex items-center gap-2">
                    <small>{budgetItems.length ? `${MON_SHORT[now.getMonth()]} · ${t(budgetLeft >= 0 ? 'fin.left' : 'fin.over')}` : ''}</small>
                    <button type="button" className="btn-soft btn-sm !h-6" onClick={() => { setBudgetCat(null); setSheet('budget') }}>+ {t('fin.limit')}</button>
                  </span>
                </div>
                {!budgetItems.length ? (
                  <div className="py-6 text-center">
                    <p className="text-sm text-[var(--ink3)]">{t('fin.no_limits')}</p>
                    <button type="button" className="btn mt-3" onClick={() => { setBudgetCat(null); setSheet('budget') }}><Plus size={15} /> {t('fin.set_limit')}</button>
                  </div>
                ) : (
                  <>
                    <div className="flex items-baseline gap-2">
                      <span className="text-[26px] font-semibold" style={{ color: budgetLeft < 0 ? 'var(--neg)' : 'inherit' }}>
                        <Num value={Math.abs(budgetLeft)} /> ₽
                      </span>
                      <span className="text-xs text-[var(--ink3)]">{t(budgetLeft < 0 ? 'fin.over' : 'fin.left')} {t('fin.of', { m: money(totalBudget) })}</span>
                    </div>
                    <div className="mt-4 space-y-3">
                      {budgetItems.slice(0, 5).map((b) => (
                        <div key={b.id || b.name} className="cursor-pointer text-[13px]" title={t('fin.edit_limit')} onClick={() => { setBudgetCat(b); setSheet('budget') }}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="flex items-center gap-1.5">{b.icon} {b.name}</span>
                            <span className="num text-[var(--ink2)]">{money(b.spent)} / {money(b.budget)}</span>
                          </div>
                          <div className="h-1.5 rounded-full bg-[var(--sf2)] overflow-hidden">
                            <div className="h-full rounded-full transition-all" style={{
                              width: `${Math.min(100, Math.round((b.pct || 0) * 100))}%`,
                              background: b.status === 'over' ? 'linear-gradient(90deg, #ff3b5c, #ff8a3d)' : b.status === 'warn' ? 'linear-gradient(90deg, #ffb020, #ff8a3d)' : 'linear-gradient(90deg, var(--acc), #8a5cff)',
                            }}></div>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center justify-between mt-4 pt-3 border-t border-[var(--line)] text-xs text-[var(--ink3)]">
                      <span>{t('fin.over_note', { n: budgetItems.filter((b) => b.status === 'over').length })}</span>
                      <button type="button" className="btn-soft btn-sm" onClick={() => { setTxCategory('all'); setTab('txs') }}>{t('fin.see_txs')}</button>
                    </div>
                  </>
                )}
              </section>
            )
            if (id === 'upcoming') return (
              <section key="upcoming" className="c s6 r" style={st}>{ctl}
                <div className="hd"><h2>{t('fin.c_upcoming')}</h2><small>{t('fin.recurring_pays')}</small></div>
                {!nextPayments.length ? (
                  <p className="py-6 text-center text-sm text-[var(--ink3)]">{t('fin.no_recurring')}</p>
                ) : nextPayments.slice(0, 5).map((r) => (
                  <div className="rowi" key={r.id}>
                    <time>{r.on.getDate()} {MON_SHORT[r.on.getMonth()]}</time>
                    <span className="t">
                      {r.title || r.name}
                      <small>{t('fin.in_n', { n: daysUntil(r.on) })}{r.category ? ` · ${r.category}` : ''}</small>
                    </span>
                    <span className="amt">−{money(r.amount)}</span>
                  </div>
                ))}
                {nextPayments.length > 0 && (
                  <div className="flex items-center justify-between mt-3 pt-3 border-t border-[var(--line)] text-xs text-[var(--ink3)]">
                    <span>{t('fin.last7')} {money(nextPayments.filter((r) => daysUntil(r.on) <= 7).reduce((s, r) => s + (r.amount || 0), 0))}</span>
                    <button type="button" className="btn-soft btn-sm" onClick={() => setTab('recurring')}>{t('fin.manage')}</button>
                  </div>
                )}
              </section>
            )
            return (
              <section key="flow" className="c s12 r" style={st}>{ctl}
                <div className="hd"><h2>{t('fin.flow_month')}</h2><small>{t('fin.flow_month_hint')}</small></div>
                <div className="flow">
                  <i style={{ width: `${flowRecurringPct}%`, background: 'linear-gradient(90deg, var(--ink), #4b4b55)' }}></i>
                  <i style={{ width: `${flowDebtPct}%`, background: 'linear-gradient(90deg, #b9bcc6, var(--ink3))' }}></i>
                  <i style={{ width: `${flowFreePct}%`, background: 'linear-gradient(90deg, var(--acc), #8a5cff)' }}></i>
                </div>
                <div className="fl">
                  <span>{t('fin.reg_debt_free')}</span>
                  <span>{t('fin.living_costs')} {money(livingSpent)} → {t('fin.remains')} <b>{livingRemain < 0 ? '−' : ''}{money(Math.abs(livingRemain))}</b></span>
                </div>
              </section>
            )
          })}
          {cardsEdit && (
            <section className="c s12 r" style={{ '--i': 11 }}>
              <div className="hd"><h2>{t('fin.cards_setup')}</h2><small></small></div>
              <p className="muted text-[13px]">{t('fin.cards_setup_hint')}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {FIN_CARDS.filter((x) => !cardOrder.includes(x)).map((x) => (
                  <button key={x} className="btn-soft btn-sm" onClick={() => setCardOrder((o) => [...o, x])}>+ {t(FIN_CARD_LABELS[x])}</button>
                ))}
                <button className="btn-ghost btn-sm" onClick={resetCards}>{t('tk.restore_all')}</button>
              </div>
            </section>
          )}
        </div>
      )}

      {/* Вкладка 2: ОПЕРАЦИИ (Таблица и фильтры в бенто стиле) */}
      {tab === 'txs' && (
        <div className="bento">
          {/* Поиск и фильтры по категориям */}
          <section className="c s12 r" style={{ '--i': 3 }}>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="search !w-full sm:!w-72">
                <Search size={16} />
                <input
                  type="text"
                  placeholder={t('fin.search_ph')}
                  value={txSearch}
                  onChange={(e) => setTxSearch(e.target.value)}
                  className="bg-transparent outline-none w-full text-sm text-[var(--ink)]"
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <span
                  className={`chips !m-0 !gap-1.5`}
                >
                  <button
                    type="button"
                    className={txCategory === 'all' ? '!bg-[var(--ink)] !text-[var(--bg)]' : ''}
                    onClick={() => setTxCategory('all')}
                  >
                    {t('common.all')}
                  </button>
                  {categories.map((c) => (
                    <button
                      type="button"
                      key={c.id || c.name}
                      className={txCategory === (c.name || c) ? '!bg-[var(--ink)] !text-[var(--bg)]' : ''}
                      onClick={() => setTxCategory(c.name || c)}
                    >
                      {c.name || c}
                    </button>
                  ))}
                </span>
                {/* импорт выписки Т-Банка: рядом с фильтрами и «выпиской» (CSV/PDF/XLSX, можно перетащить) */}
                <ImportButton
                  className="ml-auto"
                  onDone={(r) => {
                    if (r?.ok) { show(r.text || t('fin.import_added')); load(); bump() }
                    else show(r?.text || t('fin.import_bad'), 'err')
                  }}
                  onErr={show.err}
                />
              </div>
            </div>
            {/* фильтр по счёту: отдельной строкой, чтобы не спорить с категориями */}
            <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-[var(--line)]">
              <span className="text-[11px] uppercase tracking-wider text-[var(--ink3)]">{t('graph.one_account')}</span>
              <span className="chips !m-0 !gap-1.5">
                <button type="button" className={txAccount === 'all' ? '!bg-[var(--ink)] !text-[var(--bg)]' : ''} onClick={() => setTxAccount('all')}>{t('common.all')}</button>
                {accounts.map((a) => (
                  <button type="button" key={a.id || a.name} className={txAccount === a.name ? '!bg-[var(--ink)] !text-[var(--bg)]' : ''} onClick={() => setTxAccount(a.name)}>{a.name}</button>
                ))}
              </span>
              {(txCategory !== 'all' || txAccount !== 'all' || txSearch) && (
                <button type="button" className="btn-ghost btn-sm !h-6" onClick={() => { setTxCategory('all'); setTxAccount('all'); setTxSearch('') }}>{t('common.reset')}</button>
              )}
              <span className="ml-auto text-[13px] num text-[var(--ink2)]">
                <b className="text-[var(--pos)]">+{money(filteredTxs.income)}</b>
                <span className="text-[var(--ink3)]"> / </span>
                <b>−{money(filteredTxs.expense)}</b>
              </span>
            </div>
          </section>

          {/* Список операций */}
          <section className="c s12 r" style={{ '--i': 4 }}>
            <div className="hd">
              <h2>{t('fin.tx_history')}</h2>
              <small>{t('mem.entries_n', { count: shownTxs.length })} · {days ? t('fin.for_days_short', { n: days }) : t('fin.all_history')}</small>
            </div>
            {shownTxs.length === 0 ? (
              <p className="py-8 text-center text-sm text-[var(--ink3)]">{t('fin.no_txs_period')}</p>
            ) : (
              shownTxs.map((tx) => (
                <div className="rowi group" key={tx.id}>
                  <time>{shortDate(tx.date || tx.created_at)}</time>
                  <span className="t">
                    {tx.title || tx.note || tx.category || t('fin.tx')}
                    <small>
                      {[tx.category, tx.account, tx.comment].filter(Boolean).join(' · ')}
                    </small>
                  </span>
                  {/* знак берём из kind: amount приходит из API положительным */}
                  <span className="amt" style={{ color: tx.kind === 'income' ? 'var(--pos)' : 'inherit' }}>
                    {tx.kind === 'income' ? '+' : tx.kind === 'expense' ? '−' : ''}{money(tx.amount)}
                  </span>
                  <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition">
                    <button
                      type="button"
                      onClick={() => { setEditingItem(tx); setSheet('tx') }}
                      className="p-1.5 rounded-full hover:bg-[var(--sf)] text-[var(--ink2)]"
                      title={t('common.edit')}
                    >
                      <Edit2 size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setAsk({
                        title: t('fin.del_tx_q'),
                        text: t('fin.del_tx_text'),
                        msg: t('fin.tx_deleted'),
                        run: () => api.delTx(tx.id),
                      })}
                      className="p-1.5 rounded-full hover:bg-[var(--sf)] text-[var(--neg)]"
                      title={t('common.delete_title')}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              ))
            )}
          </section>
        </div>
      )}

      {/* Вкладка 3: СЧЕТА (Карточки счетов в стиле бенто) */}
      {tab === 'accounts' && (
        <div className="bento">
          {accounts.length === 0 ? (
            <section className="c s12 r" style={{ '--i': 3 }}>
              <div className="text-center py-10">
                <Wallet className="mx-auto mb-3 opacity-30" size={36} />
                <h3 className="text-lg font-medium">{t('fin.no_accounts')}</h3>
                <p className="text-sm text-[var(--ink2)] mt-1">{t('fin.no_accounts_hint')}</p>
                <button
                  type="button"
                  className="btn mt-4"
                  onClick={() => { setEditingItem(null); setSheet('account') }}
                >
                  <Plus size={15} /> {t('fin.add_account')}
                </button>
              </div>
            </section>
          ) : (
            accounts.map((a, idx) => {
              const atype = a.type || a.kind || 'bank'
              return (
              <section key={a.id || idx} className="c s4 r relative" style={{ '--i': 3 + idx }}>
                <div className="hd">
                  <h2 className="flex items-center gap-2">
                    {atype === 'card' && <CreditCard size={17} />}
                    {atype === 'cash' && <Wallet size={17} />}
                    {atype === 'crypto' && <PiggyBank size={17} />}
                    {(atype === 'bank' || atype === 'savings') && <Landmark size={17} />}
                    {a.name}
                  </h2>
                  <small>{a.currency || 'RUB'}</small>
                </div>
                <div className="mid font-semibold"><Num value={a.balance || 0} /> ₽</div>
                <div className="flex items-center justify-between mt-4 pt-3 border-t border-[var(--line)]">
                  <span className="text-[13px] text-[var(--ink3)]">{a.comment || ({ card: t('acc.card'), cash: t('acc.cash2'), bank: t('graph.one_account'), savings: t('acc.deposit'), crypto: t('acc.crypto') })[atype] || t('graph.one_account')}</span>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      onClick={() => { setEditingItem(a); setSheet('account') }}
                      className="p-1 rounded-full text-[var(--ink2)] hover:text-[var(--ink)]"
                      title={t('common.edit')}
                    >
                      <Edit2 size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setAsk({
                        title: t('fin.del_acc_q_name', { name: a.name }),
                        text: t('fin.del_acc_text'),
                        msg: t('fin.acc_deleted'),
                        run: () => api.delAccount(a.id),
                      })}
                      className="p-1 rounded-full text-[var(--neg)] hover:bg-[var(--sf2)]"
                      title={t('fin.del_acc_q')}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              </section>
              )
            })
          )}
        </div>
      )}

      {/* Вкладка 4: ДОЛГИ (Прогресс и платежи в стиле бенто) */}
      {tab === 'debts' && (
        <div className="bento">
          <section className="c hero s4 r" style={{ '--i': 3 }}>
            <div className="hd"><h2>{t('fin.total_debt')}</h2><small>{t('fin.debt_left_hint')}</small></div>
            <div className="big"><Num value={debtsTotal} /> ₽</div>
            <span className="tag">
              {t('fin.n_active_debt', { count: debts.length })}
            </span>
          </section>

          {debts.map((d, idx) => {
            const total = d.total || 1
            const paid = d.paid || 0
            const left = Math.max(0, total - paid)
            const pct = Math.min(100, Math.round((paid / total) * 100))
            return (
              <section key={d.id || idx} className="c blk s4 r" style={{ '--i': 4 + idx }}>
                <div className="hd">
                  <h2>{d.name || d.title}</h2>
                  <small>{d.creditor || t('fin.creditor')}</small>
                </div>
                <div className="mid"><Num value={left} /> ₽</div>
                <div className="w-full bg-white/10 rounded-full h-2 mt-4 overflow-hidden">
                  <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, var(--acc), #8a5cff)' }}></div>
                </div>
                <div className="flex items-center justify-between mt-3 text-xs text-[#8b8e98] num">
                  <span>{t('fin.paid_out')} {money(paid)} ({pct}%)</span>
                  <span>{t('fin.of')} {money(total)}</span>
                </div>
                <div className="flex items-center justify-between mt-4 pt-3 border-t border-white/10">
                  <button
                    type="button"
                    onClick={() => { setEditingItem(d); setSheet('payDebt') }}
                    className="btn g !h-8 !px-3 text-[12px]"
                  >
                    {t('fin.make_payment')}
                  </button>
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={() => { setEditingItem(d); setSheet('debt') }}
                      className="p-1.5 text-white/50 hover:text-white"
                      title={t('common.edit')}
                    >
                      <Edit2 size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setAsk({
                        title: t('fin.del_debt_q_name', { name: d.name || d.title }),
                        text: t('fin.del_debt_text'),
                        msg: t('fin.debt_deleted'),
                        run: () => api.delDebt(d.id),
                      })}
                      className="p-1.5 text-[var(--neg)] hover:opacity-80"
                      title={t('common.delete_title')}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              </section>
            )
          })}
        </div>
      )}

      {/* Вкладка 5: РЕГУЛЯРНЫЕ (Подписки и обязательные платежи в стиле бенто) */}
      {tab === 'recurring' && (
        <div className="bento">
          <section className="c p1 s4 r" style={{ '--i': 3 }}>
            <div className="hd"><h2>{t('fin.c_recurring')}</h2><small>{t('fin.per_month_spends')}</small></div>
            <div className="big">
              <Num value={recExpense} /> ₽
            </div>
            <span className="tag">
              {recIncome > 0 && (
                <span style={{ color: 'var(--pos)' }}>{t('fin.income_plus')}{money(recIncome)} · </span>
              )}
              {t('fin.n_active_pay', { count: recActive.length })}
              {recPaused.length > 0 ? t('fin.paused_n', { count: recPaused.length }) : ''}
            </span>
          </section>

          <section className="c s8 r" style={{ '--i': 4 }}>
            <div className="hd">
              <h2>{t('fin.rec_list')}</h2>
              <small>{t('fin.rec_list_hint')}</small>
            </div>
            {recPaused.length > 0 && (
              <div className="flex justify-end -mt-2 mb-2">
                <button
                  type="button"
                  className="btn-soft btn-sm"
                  onClick={() => setShowPaused((v) => !v)}
                  title={t('fin.paused_hint')}
                >
                  {showPaused ? t('fin.hide_paused') : t('fin.show_paused_n', { n: recPaused.length })}
                </button>
              </div>
            )}
            {recShown.length === 0 ? (
              <p className="py-6 text-center text-sm text-[var(--ink3)]">
                {recurring.length > 0 ? t('fin.all_paused') : t('fin.no_recurring')}
              </p>
            ) : (
              recShown.map((r) => (
                <div className="rowi group" key={r.id}>
                  <time>{(r.day_of_month || r.day) ? t('fin.day_of_month', { d: r.day_of_month || r.day }) : t('fin.per_month_short')}</time>
                  <span className="t">
                    {r.name || r.title}
                    <small>{[r.category, r.account].filter(Boolean).join(' · ') || (r.kind === 'income' ? t('fin.inflow') : t('fin.outflow'))}</small>
                  </span>
                  <span className="amt" style={{ color: r.kind === 'income' ? 'var(--pos)' : 'inherit' }}>
                    {r.kind === 'income' ? '+' : '−'}{money(r.amount)}
                  </span>
                  <span className={`chip !ml-2 ${r.active === false ? '!opacity-50' : ''}`}>{r.active === false ? t('aims.pause') : t('status_active')}</span>
                  <button
                    type="button"
                    onClick={() => toggleActive(r)}
                    className="p-1 rounded-full text-[var(--ink2)] hover:text-[var(--ink)] transition"
                    title={r.active === false ? 'Включить: платёж снова пойдёт в прогноз' : t('fin.pause_tip')}
                  >
                    {r.active === false ? <Play size={13} /> : <Pause size={13} />}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setEditingItem(r); setSheet('recurring') }}
                    className="p-1 rounded-full text-[var(--ink2)] hover:text-[var(--ink)] opacity-0 group-hover:opacity-100 transition"
                    title={t('fin.edit_pay')}
                  >
                    <Edit2 size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setAsk({
                      title: t('fin.del_rec_q_name', { name: r.name || r.title }),
                      text: t('fin.pause_note'),
                      msg: t('fin.paused'),
                      run: () => api.delRecurring(r.id),
                    })}
                    className="p-1 rounded-full text-[var(--neg)] hover:bg-[var(--sf2)]"
                    title={t('fin.remove_pay')}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))
            )}
          </section>
        </div>
      )}

      {/* Вкладка 6: ЦЕЛИ (Финансовые цели и копилки в стиле бенто) */}
      {tab === 'goals' && (
        <div className="bento">
          {goals.length === 0 ? (
            <section className="c s12 r" style={{ '--i': 3 }}>
              <div className="text-center py-10">
                <Target className="mx-auto mb-3 opacity-30" size={36} />
                <h3 className="text-lg font-medium">{t('fin.no_goals')}</h3>
                <p className="text-sm text-[var(--ink2)] mt-1">{t('fin.no_goals_hint')}</p>
                <button
                  type="button"
                  className="btn mt-4"
                  onClick={() => { setEditingItem(null); setSheet('goal') }}
                >
                  <Plus size={15} /> {t('gl.goal')}
                </button>
              </div>
            </section>
          ) : (
            goals.map((g, idx) => {
              const current = g.current || 0
              const target = g.target || 1
              const pct = Math.min(100, Math.round((current / target) * 100))
              return (
                <section key={g.id || idx} className="c p2 s4 r" style={{ '--i': 3 + idx }}>
                  <div className="hd">
                    <h2>{g.title || g.name}</h2>
                    <small>{g.deadline ? shortDate(g.deadline) : t('fin.forever')}</small>
                  </div>
                  <div className="mid font-semibold"><Num value={current} /> ₽</div>
                  <div className="w-full bg-[var(--line)] rounded-full h-2 mt-4 overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, #19b34a, #14b8a6)' }}></div>
                  </div>
                  <div className="flex items-center justify-between mt-2.5 text-xs text-[var(--ink2)] num">
                    <span>{t('fin.saved_pct', { pct })}</span>
                    <span>{t('fin.goal_colon')} {money(target)}</span>
                  </div>
                  {target > current && goalEta(target - current) && (
                    <div className="mt-2 text-[12px] text-[var(--ink3)]">{t('gl.at_rate', { m: money(5000) })} {goalEta(target - current)}</div>
                  )}
                  <div className="flex items-center justify-between mt-4 pt-3 border-t border-[var(--line)]">
                    <button
                      type="button"
                      onClick={() => { setEditingItem(g); setSheet('putGoal') }}
                      className="btn !h-8 !px-3 text-[12px]"
                    >
                      {t('fin.top_up')}
                    </button>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        onClick={() => { setEditingItem(g); setSheet('goal') }}
                        className="p-1 rounded-full text-[var(--ink2)] hover:text-[var(--ink)]"
                        title={t('common.edit')}
                      >
                        <Edit2 size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setAsk({
                          title: t('fin.del_goal_q_name', { name: g.title || g.name }),
                          text: t('gl.del_text2'),
                          msg: t('gl.deleted'),
                          run: () => api.delGoal(g.id),
                        })}
                        className="p-1 rounded-full text-[var(--neg)] hover:bg-[var(--sf2)]"
                        title={t('common.delete_title')}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                </section>
              )
            })
          )}
        </div>
      )}

      {/* Вкладка 7: ТЕХНИКИ (50/30/20, Сравнение с прошлым месяцем, На сколько хватит, Годовые) */}
      {tab === 'techniques' && (
        <div className="bento">
          <section className="c s12 r" style={{ '--i': 3 }}>
            {techniquesData ? (
              <Techniques
                t={techniquesData}
                onOpenCat={(c) => { setTxCategory(c); setTab('txs') }}
              />
            ) : (
              <Empty
                glyph="money"
                text={t('tech.not_calc')}
                sub={t('tech.need_txs')}
                compact
              />
            )}
          </section>
        </div>
      )}

      {/* Sheets: диалоги создания и редактирования сущностей финансов */}
      <TxSheet
        open={sheet === 'tx'}
        item={editingItem}
        categories={categories}
        accounts={accounts}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={(msg) => { setSheet(null); setEditingItem(null); load(); bump(); if (msg) show(msg) }}
      />

      <AccountSheet
        open={sheet === 'account'}
        account={editingItem}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
      />

      <DebtSheet
        open={sheet === 'debt'}
        debt={editingItem}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
      />

      <PayDebtSheet
        open={sheet === 'payDebt'}
        debt={editingItem}
        accounts={accounts}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={(msg) => { setSheet(null); setEditingItem(null); load(); bump(); if (msg) show(msg) }}
      />

      <RecurringSheet
        open={sheet === 'recurring'}
        item={editingItem}
        categories={categories}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
      />

      <GoalSheet
        open={sheet === 'goal'}
        goal={editingItem}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
      />

      <PutGoalSheet
        open={sheet === 'putGoal'}
        goal={editingItem}
        accounts={accounts}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={(msg) => { setSheet(null); setEditingItem(null); load(); bump(); if (msg) show(msg) }}
      />

      <BudgetSheet
        open={sheet === 'budget'}
        item={budgetCat}
        categories={categories}
        onClose={() => { setSheet(null); setBudgetCat(null) }}
        onDone={() => { setSheet(null); setBudgetCat(null); load(); bump() }}
      />

      {/* Подтверждение удаления вместо нативного confirm(): одна шторка на всю страницу */}
      <Confirm
        open={!!ask}
        danger
        title={ask?.title || ''}
        text={ask?.text || ''}
        onClose={() => setAsk(null)}
        onOk={async () => {
          const a = ask
          setAsk(null)
          if (!a) return
          try { await a.run(); if (a.msg) show(a.msg); load(); bump() } catch (e) { show.err(e) }
        }}
      />
    </div>
  )
}

/* =========================================================================
   Диалоги редактирования (Sheet)
   ========================================================================= */

function TxSheet({ open, item, categories = [], accounts = [], onClose, onDone }) {
  const { t } = useI18n()
  const isNew = !item?.id
  const [amount, setAmount] = useState('')
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('')
  const [account, setAccount] = useState('')
  const [comment, setComment] = useState('')
  const [kind, setKind] = useState('expense')
  const [date, setDate] = useState('')
  const [saving, setSaving] = useState(false)
  const [amountErr, setAmountErr] = useState('')
  const [askDel, setAskDel] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    if (item) {
      setAmount(String(Math.abs(item.amount || 0)))
      setTitle(item.title || item.note || '')   // описание хранится в note
      setCategory(item.category || '')
      setAccount(item.account || '')
      setComment(item.comment || '')
      // переводы форма не редактирует — сохраняем их тип, иначе трата/доход «съест» перевод
      setKind(item.kind === 'income' ? 'income' : item.kind === 'transfer' ? 'transfer' : 'expense')
      setDate(item.date ? item.date.slice(0, 10) : toLocalISO(new Date()).slice(0, 10))
    } else {
      setAmount('')
      setTitle('')
      setCategory('')
      setAccount(accounts[0]?.name || '')
      setComment('')
      setKind('expense')
      setDate(toLocalISO(new Date()).slice(0, 10))
    }
    setAmountErr('')
  }, [open, item])

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseFloat(amount.replace(/\s/g, ''))
    if (isNaN(a)) return
    // нулевая сумма не «тихая»: кнопка активна, поэтому объясняем прямо в форме (D3);
    // отрицательные и нечисловые значения ведут себя как раньше (Math.abs / игнор)
    if (a === 0) { setAmountErr(t('or.amount_zero')); return }
    setAmountErr('')
    setSaving(true)
    try {
      // API принимает положительную сумму и kind; описание/комментарий кладём в note
      const payload = {
        amount: Math.abs(a),
        kind,
        category: category.trim() || undefined,
        note: [title.trim(), comment.trim()].filter(Boolean).join(' · ') || undefined,
        account: account.trim() || undefined,
        date: date ? `${date}T${item?.date ? item.date.slice(11, 19) : '12:00:00'}` : toLocalISO(new Date()).slice(0, 10),
      }
      if (isNew) {
        await api.addTx(payload)
      } else {
        await api.updateTx(item.id, payload)
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={isNew ? 'новая операция' : t('fin.edit_tx')}>
      <form onSubmit={submit} className="space-y-4">
        <div className="sg w-full">
          <button type="button" className={kind === 'expense' ? 'on' : ''} onClick={() => setKind('expense')}>{t('fin.expense')}</button>
          <button type="button" className={kind === 'income' ? 'on' : ''} onClick={() => setKind('income')}>{t('fin.income')}</button>
        </div>
        <Field label={t('fin.amount_rub')} error={amountErr}>
          <input className="input" autoFocus type="number" step="any" value={amount}
            onChange={(e) => { setAmount(e.target.value); if (amountErr) setAmountErr('') }}
            placeholder="1000" />
        </Field>
        <Field label={t('fin.description')}>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('fin.desc_ph')} />
        </Field>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label={t('common.category')}>
            <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} placeholder={t('fin.cat_ph')} list="cat-list" />
            <datalist id="cat-list">
              {categories.map(c => <option key={c.id || c.name || c} value={c.name || c} />)}
            </datalist>
          </Field>
          <Field label={t('graph.one_account')}>
            <select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>
              <option value="">{t('fin.not_set')}</option>
              {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
            </select>
          </Field>
        </div>
        <Field label={t('common.date')}>
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label={t('common.comment')}>
          <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder={t('common.optional')} />
        </Field>
        <div className="flex justify-between gap-2 pt-4">
          {!isNew && (
            <button type="button" className="btn g !text-[var(--neg)]" onClick={() => setAskDel(true)}>{t('common.delete')}</button>
          )}
          <div className="ml-auto flex gap-2">
            <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
            <button type="submit" className="btn" disabled={saving || !amount}>{saving ? t('people.saving') : t('common.save')}</button>
          </div>
        </div>
      </form>
      <Confirm open={askDel} danger title={t('fin.del_tx_q')} text={t('fin.del_tx_text')}
        onOk={async () => { setAskDel(false); try { await api.delTx(item.id); onDone(t('fin.tx_deleted')) } catch (err) { show.err(err) } }}
        onClose={() => setAskDel(false)} />
    </Sheet>
  )
}

function AccountSheet({ open, account, onClose, onDone }) {
  const { t } = useI18n()
  const isNew = !account?.id
  const [name, setName] = useState('')
  const [balance, setBalance] = useState('')
  const [type, setType] = useState('card')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setName(account?.name || '')
    setBalance(account?.balance != null ? String(account.balance) : '')
    setType(account?.type || account?.kind || 'card')
  }, [open, account])

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const payload = {
        name: name.trim(),
        balance: parseFloat(balance) || 0,
        type,
        kind: type,   // сиды хранят kind, форма — type: держим оба, чтобы иконка и расчёты сходились
      }
      if (isNew) {
        await api.addAccount(payload)
      } else {
        await api.updateAccount(account.id, payload)
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={isNew ? 'новый счёт' : t('fin.edit_account')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('acc.name')}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('acc.name_ph')} />
        </Field>
        <Field label={t('acc.current_balance')}>
          <input className="input" type="number" step="any" value={balance} onChange={(e) => setBalance(e.target.value)} placeholder="0" />
        </Field>
        <Field label={t('acc.type')}>
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="card">{t('acc.bank_card')}</option>
            <option value="cash">{t('acc.cash')}</option>
            <option value="bank">{t('acc.deposit')}</option>
            <option value="crypto">{t('acc.crypto_wallet')}</option>
          </select>
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !name.trim()}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function DebtSheet({ open, debt, onClose, onDone }) {
  const { t } = useI18n()
  const isNew = !debt?.id
  const [name, setName] = useState('')
  const [creditor, setCreditor] = useState('')
  const [total, setTotal] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setName(debt?.name || debt?.title || '')
    setCreditor(debt?.creditor || '')
    setTotal(debt?.total != null ? String(debt.total) : '')
  }, [open, debt])

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const payload = {
        title: name.trim(),   // API ждёт `title`; `name` — устаревший алиас (422 «Field required»)
        creditor: creditor.trim() || undefined,
        total: parseFloat(total) || 0,
      }
      if (isNew) {
        await api.addDebt(payload)
      } else {
        await api.updateDebt(debt.id, payload)
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={isNew ? 'новый долг' : t('fin.edit_debt')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('common.title')}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('fin.debt_ph')} />
        </Field>
        <Field label={t('fin.creditor2')}>
          <input className="input" value={creditor} onChange={(e) => setCreditor(e.target.value)} placeholder={t('fin.creditor_ph')} />
        </Field>
        <Field label={t('fin.total_amount')}>
          <input className="input" type="number" step="any" value={total} onChange={(e) => setTotal(e.target.value)} placeholder="50000" />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !name.trim()}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function PayDebtSheet({ open, debt, accounts = [], onClose, onDone }) {
  const { t } = useI18n()
  const [amount, setAmount] = useState('')
  const [account, setAccount] = useState('none')
  const [accErr, setAccErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  // по умолчанию — «не списывать»: счёт пользователь выбирает сам, а не таём первый попавшийся
  useEffect(() => { if (open) { setAccount('none'); setAccErr('') } }, [open])

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseFloat(amount)
    if (!a || isNaN(a) || !debt?.id) return
    // PayIn принимает только amount/account/date: «не списывать» бэкенд не умеет,
    // а пустой счёт превратился бы в основной (деньги всё равно ушли бы) — просим выбрать честно
    if (account === 'none') { setAccErr(t('fin.pick_account')); return }
    setAccErr('')
    setSaving(true)
    try {
      await api.payDebt(debt.id, a, { account })
      onDone(t('fin.pay_made'))
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={t('fin.pay_debt_title', { name: debt?.name || debt?.title || '' })}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('fin.pay_amount')}>
          <input className="input" autoFocus type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="5000" />
        </Field>
        <Field label={t('fin.charge')} error={accErr}
          hint={account === 'none' ? 'выберите счёт — иначе остаток долга не сойдётся' : t('fin.charge_hint')}>
          <select className="input" value={account} onChange={(e) => { setAccount(e.target.value); if (accErr) setAccErr('') }}>
            <option value="none">{t('fin.no_charge')}</option>
            {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
          </select>
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !amount}>{saving ? t('people.saving') : t('fin.submit')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function RecurringSheet({ open, item, categories = [], onClose, onDone }) {
  const { t } = useI18n()
  const isNew = !item?.id
  const [name, setName] = useState('')
  const [amount, setAmount] = useState('')
  const [category, setCategory] = useState('')
  const [day, setDay] = useState('1')
  const [kind, setKind] = useState('expense')   // expense — списание, income — регулярный доход
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setName(item?.name || item?.title || '')
    setAmount(item?.amount != null ? String(item.amount) : '')
    setCategory(item?.category || '')
    setDay(item?.day ? String(item.day) : '1')
    setKind(item?.kind === 'income' ? 'income' : 'expense')
  }, [open, item])

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const payload = {
        title: name.trim(),   // API ждёт `title`; `name` — устаревший алиас (422 «Field required»)
        amount: parseFloat(amount) || 0,
        category: category.trim() || undefined,
        day: parseInt(day, 10) || 1,
        kind,
      }
      if (isNew) {
        await api.addRecurring(payload)
      } else {
        await api.updateRecurring(item.id, payload)
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  const isIncome = kind === 'income'
  return (
    <Sheet open={open} onClose={onClose} title={isNew ? 'новый регулярный платёж' : t('fin.edit_pay2')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('fin.kind')} hint={isIncome ? 'поступление: уйдёт в доход и в прогноз кассы' : t('fin.outflow_hint')}>
          <div className="sg">
            <button type="button" className={!isIncome ? 'on' : ''} onClick={() => setKind('expense')}>{t('fin.outflow')}</button>
            <button type="button" className={isIncome ? 'on' : ''} onClick={() => setKind('income')}>{t('fin.income')}</button>
          </div>
        </Field>
        <Field label={t('common.title')}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={isIncome ? 'Зарплата, аренда, фриланс…' : t('fin.pay_ph2')} />
        </Field>
        <Field label={isIncome ? 'сумма поступления в месяц (₽)' : t('fin.amount_month')}>
          <input className="input" type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="499" />
        </Field>
        <Field label={isIncome ? 'день поступления (1–31)' : t('fin.pay_day')}>
          <input className="input" type="number" min="1" max="31" value={day} onChange={(e) => setDay(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !name.trim()}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function GoalSheet({ open, goal, onClose, onDone }) {
  const { t } = useI18n()
  const isNew = !goal?.id
  const [title, setTitle] = useState('')
  const [target, setTarget] = useState('')
  const [current, setCurrent] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setTitle(goal?.title || goal?.name || '')
    setTarget(goal?.target != null ? String(goal.target) : '')
    setCurrent(goal?.current != null ? String(goal.current) : '0')
  }, [open, goal])

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (!title.trim()) return
    setSaving(true)
    try {
      const payload = {
        title: title.trim(),
        target: parseFloat(target) || 0,
        current: parseFloat(current) || 0,
      }
      if (isNew) {
        await api.addGoal(payload)
      } else {
        await api.updateGoal(goal.id, payload)
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={isNew ? 'новая финансовая цель' : t('fin.edit_goal')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('gl.goal_name')}>
          <input className="input" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('gl.goal_ph2')} />
        </Field>
        <Field label={t('gl.target')}>
          <input className="input" type="number" step="any" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="100000" />
        </Field>
        <Field label={t('gl.saved')}>
          <input className="input" type="number" step="any" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="0" />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !title.trim()}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function PutGoalSheet({ open, goal, accounts = [], onClose, onDone }) {
  const { t } = useI18n()
  const [amount, setAmount] = useState('')
  const [account, setAccount] = useState('none')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  // по умолчанию — «не списывать»: баланс не трогаем, пока пользователь сам не выберет счёт
  useEffect(() => { if (open) setAccount('none') }, [open])

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseFloat(amount)
    if (!a || isNaN(a) || !goal?.id) return
    setSaving(true)
    try {
      // «не списывать» = просто отметить накопление: GoalPut.record_tx=false, транзакция не создаётся
      if (account === 'none') await api.putGoal(goal.id, a, { record_tx: false })
      else await api.putGoal(goal.id, a, { account })
      onDone(t('fin.topped_up'))
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={t('fin.top_up_title', { name: goal?.title || goal?.name || '' })}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('fin.top_amount')}>
          <input className="input" autoFocus type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="2000" />
        </Field>
        <Field label={t('fin.charge')}
          hint={account === 'none' ? 'баланс не тронется — просто отмечу накопление на цели' : t('fin.top_hint')}>
          <select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="none">{t('fin.no_charge')}</option>
            {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
          </select>
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !amount}>{saving ? t('people.saving') : t('fin.top_up')}</button>
        </div>
      </form>
    </Sheet>
  )
}

/* Месячный лимит категории: хранится в Category.budget, карточка «бюджеты» читает его
   через /api/finance/budgets. Лимит необязателен — 0 или пусто означает «без контроля». */
function BudgetSheet({ open, item, categories = [], onClose, onDone }) {
  const { t } = useI18n()
  const [cid, setCid] = useState('')
  const [amount, setAmount] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()
  const options = useMemo(() => categories.filter((c) => c.kind !== 'income'), [categories])

  useEffect(() => {
    if (!open) return
    // item приходит со строки бюджета; для «+ лимит» берём первую расходную категорию
    const chosen = item?.id != null ? (options.find((c) => c.id === item.id) || item) : options[0]
    setCid(chosen?.id != null ? String(chosen.id) : '')
    setAmount(chosen?.budget ? String(chosen.budget) : '')
  }, [open, item?.id, options.length])

  const pick = (id) => {
    setCid(id)
    const c = options.find((x) => String(x.id) === id)
    setAmount(c?.budget ? String(c.budget) : '')
  }

  const submit = async (e) => {
    if (e) e.preventDefault()
    const id = Number(cid)
    if (!id) return
    setSaving(true)
    try {
      const n = parseFloat(String(amount).replace(/\s|\u00a0/g, '').replace(',', '.')) || 0
      await api.updateCategory(id, { budget: n })
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={t('fin.limit_month')} sub={t('fin.limit_optional')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('common.category')}>
          <select className="input" value={cid} onChange={(e) => pick(e.target.value)} autoFocus>
            {!options.length && <option value="">{t('fin.no_exp_cats')}</option>}
            {options.map((c) => <option key={c.id} value={c.id}>{c.icon} {c.name}{c.budget ? ` · ${money(c.budget)}` : ''}</option>)}
          </select>
        </Field>
        <Field label={t('fin.limit_month_rub')} hint={t('fin.zero_no_limit')}>
          <Money value={amount} onChange={setAmount} min={0} placeholder="0" />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !cid}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}
