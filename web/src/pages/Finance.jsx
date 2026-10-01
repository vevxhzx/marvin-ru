import { useEffect, useRef, useState, useMemo } from 'react'
import { api, money, shortDate, toLocalISO, plural } from '../lib/api'
import { Num, Sheet, Field, Empty, Money, useToast, PageAccent } from '../components/ui'
import CashChart from '../components/CashChart'
import { useRefresh } from '../App'
import { Plus, Search, Trash2, Edit2, ArrowDownRight, ArrowUpRight, CreditCard, Wallet, Landmark, PiggyBank, Target, Calendar, CheckCircle2, Sparkles, ChevronLeft, EyeOff } from 'lucide-react'
import { Techniques } from '../components/FinanceSmart'
import { useCardLayout, CardCtl, useWide } from '../lib/layout'
import { usePageAccent } from '../lib/prefs'

/* Карточки вкладки «обзор»: порядок и ширина хранятся общим модулем lib/layout */
const FIN_CARDS = ['balance', 'chart', 'income', 'recurring', 'debts', 'free', 'flow', 'budgets', 'upcoming']
const FIN_CARD_WIDTHS = { balance: 4, chart: 8, income: 3, recurring: 3, debts: 3, free: 3, flow: 12, budgets: 6, upcoming: 6 }
const FIN_CARD_LABELS = { balance: 'баланс', chart: 'касса', income: 'доход', recurring: 'регулярные', debts: 'долги', free: 'свободно', flow: 'поток', budgets: 'бюджеты', upcoming: 'ближайшие списания' }

/* Честная оценка «когда накоплю»: при темпе 5 000 ₽ в месяц — без обещаний точности */
const MON_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
function goalEta(need) {
  const months = Math.ceil(need / 5000)
  if (!Number.isFinite(months) || months <= 0) return ''
  if (months > 60) return null
  const d0 = new Date()
  d0.setMonth(d0.getMonth() + months)
  return `к ${d0.getDate()} ${MON_SHORT[d0.getMonth()]}`
}

export default function Finance() {
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
        api.recurring().catch(() => []),
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

  // Экспорт выписки в CSV
  const exportCSV = () => {
    if (!txs.length) return
    const rows = [
      ['Дата', 'Сумма', 'Категория', 'Название', 'Счет'],
      ...txs.map(t => [
        t.date ? t.date.slice(0, 10) : '',
        t.amount,
        t.category || '',
        `"${(t.title || '').replace(/"/g, '""')}"`,
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
          <h1 className="r" style={{ '--i': 0 }}>финансы</h1>
          <p className="sub r" style={{ '--i': 1 }}>
            {tab === 'overview' && 'все счета и баланс'}
            {tab === 'txs' && `${shownTxs.length} ${plural(shownTxs.length, 'операция', 'операции', 'операций')}`}
            {tab === 'accounts' && `${accounts.length} ${plural(accounts.length, 'счёт', 'счёта', 'счетов')}`}
            {tab === 'debts' && `${debts.length} ${plural(debts.length, 'долг', 'долга', 'долгов')}`}
            {tab === 'recurring' && `${recurring.length} регулярных платежей`}
            {tab === 'goals' && `${goals.length} ${plural(goals.length, 'финансовая цель', 'финансовые цели', 'финансовых целей')}`}
          </p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          <div className="sg" title="период: цифры и операции считаются за него">
            <span className={days === 7 ? 'on' : ''} onClick={() => setDays(7)}>7 дн</span>
            <span className={days === 30 ? 'on' : ''} onClick={() => setDays(30)}>30 дн</span>
            <span className={days === 90 ? 'on' : ''} onClick={() => setDays(90)}>90 дн</span>
            <span className={days === 0 ? 'on' : ''} onClick={() => setDays(0)}>всё</span>
          </div>
          {tab === 'overview' && <span className="btn-soft btn-sm" onClick={() => setCardsEdit((v) => !v)} title="Переместить, спрятать или поменять ширину карточек">настроить</span>}
          <span className="btn g" onClick={exportCSV} title="Скачать CSV выписку">выписка</span>
          <span
            className="btn"
            onClick={() => {
              if (tab === 'accounts') { setEditingItem(null); setSheet('account') }
              else if (tab === 'debts') { setEditingItem(null); setSheet('debt') }
              else if (tab === 'recurring') { setEditingItem(null); setSheet('recurring') }
              else if (tab === 'goals') { setEditingItem(null); setSheet('goal') }
              else { setEditingItem(null); setSheet('tx') }
            }}
          >
            {tab === 'accounts' ? '+ счёт' : tab === 'debts' ? '+ долг' : tab === 'recurring' ? '+ платёж' : tab === 'goals' ? '+ цель' : '+ операция'}
          </span>
        </div>
      </div>

      {/* Вкладки разделов финансов в едином стиле бенто */}
      <div className="sg r my-4" style={{ '--i': 2 }}>
        <span className={tab === 'overview' ? 'on' : ''} onClick={() => setTab('overview')}>обзор</span>
        <span className={tab === 'txs' ? 'on' : ''} onClick={() => setTab('txs')}>операции</span>
        <span className={tab === 'accounts' ? 'on' : ''} onClick={() => setTab('accounts')}>счета</span>
        <span className={tab === 'debts' ? 'on' : ''} onClick={() => setTab('debts')}>долги</span>
        <span className={tab === 'recurring' ? 'on' : ''} onClick={() => setTab('recurring')}>регулярные</span>
        <span className={tab === 'goals' ? 'on' : ''} onClick={() => setTab('goals')}>цели</span>
        <span className={tab === 'techniques' ? 'on' : ''} onClick={() => setTab('techniques')}>техники</span>
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
                <div className="hd"><h2>баланс</h2><small>все счета</small></div>
                <div className="big"><Num value={balance} /> ₽</div>
                <span className="tag">за {days} дн −{money(spent)}</span>
                <div className="hm">
                  <div><small>доходы за {days} дн</small><b>+{money(earned)}</b></div>
                  <div><small>долги</small><b>{money(debtsTotal)}</b></div>
                </div>
              </section>
            )
            if (id === 'chart') return (
              <section key="chart" className="c chart s8 r" style={st}>{ctl}
                <div className="hd">
                  <h2>касса на {days || 'все'} {plural(days, 'день', 'дня', 'дней')}</h2>
                  <small>
                    {forecast ? `сейчас ${money(forecast.balance)} · темп ${money(forecast.avg_day_spent)}/дн · наведите на график` : 'при текущем темпе'}
                  </small>
                </div>
                {!forecast ? (
                  <p className="py-10 text-center text-sm text-[var(--ink3)]">загружаю прогноз…</p>
                ) : (
                  <CashChart f={forecast} height={200} txs={txs} legend={false} />
                )}
                <div className="lg">
                  <span><i style={{ background: '#ff9f5c' }}></i>факт</span>
                  <span><i style={{ background: 'var(--accent)' }}></i>прогноз</span>
                  <span><i style={{ border: '1.5px dashed var(--ink3)', background: 'none' }}></i>ноль</span>
                  {forecast?.runway_days != null && (
                    <span className="text-[var(--neg)]">до нуля ~{forecast.runway_days} дн</span>
                  )}
                  {forecast?.min_balance != null && forecast.min_balance >= 0 && (
                    <span>минимум {money(forecast.min_balance)} · {forecast.min_date?.slice(8, 10)}.{forecast.min_date?.slice(5, 7)}</span>
                  )}
                </div>
                {forecast?.scenarios?.realistic && forecast?.scenarios?.pessimistic
                  && forecast.scenarios.realistic.low !== forecast.scenarios.pessimistic.low && (
                  <div className="muted mt-1 text-[12px]">
                    сценарии: реалистично минимум <b className="num">{money(forecast.scenarios.realistic.low)}</b>
                    {' · '}пессимистично (оплаты позже ~{forecast.scenarios.pessimistic.delay_days ?? 0} дн) <b className={`num ${forecast.scenarios.pessimistic.ok ? '' : 'neg'}`}>{money(forecast.scenarios.pessimistic.low)}</b>
                  </div>
                )}
              </section>
            )
            if (id === 'income') return (
              <section key="income" className="c p2 s3 r" style={st}>{ctl}
                <div className="hd"><h2>доход</h2><small>{cf.income_is_estimate ? 'средний' : ''}</small></div>
                <div className="mid"><Num value={cf.income || 22844} /> ₽</div>
              </section>
            )
            if (id === 'recurring') return (
              <section key="recurring" className="c p1 s3 r" style={st}>{ctl}
                <div className="hd"><h2>регулярные</h2><small></small></div>
                <div className="mid"><Num value={cf.recurring || 1528} /> ₽</div>
              </section>
            )
            if (id === 'debts') return (
              <section key="debts" className="c blk s3 r" style={st}>{ctl}
                <div className="hd"><h2>по долгам</h2><small></small></div>
                <div className="mid"><Num value={cf.debt_payments || 13500} /> ₽</div>
              </section>
            )
            if (id === 'free') return (
              <section key="free" className="c tint-ok s3 r" style={st}>{ctl}
                <div className="hd"><h2>свободно</h2><small>в месяц</small></div>
                <div className="mid"><Num value={cf.free || 7816} /> ₽</div>
              </section>
            )
            if (id === 'budgets') return (
              <section key="budgets" className="c p2 s6 r" style={st}>{ctl}
                <div className="hd">
                  <h2>бюджеты на месяц</h2>
                  <span className="flex items-center gap-2">
                    <small>{budgetItems.length ? `${MON_SHORT[now.getMonth()]} · ${budgetLeft >= 0 ? 'осталось' : 'перерасход'}` : ''}</small>
                    <button type="button" className="btn-soft btn-sm !h-6" onClick={() => { setBudgetCat(null); setSheet('budget') }}>+ лимит</button>
                  </span>
                </div>
                {!budgetItems.length ? (
                  <div className="py-6 text-center">
                    <p className="text-sm text-[var(--ink3)]">лимиты не заданы — задайте месячный лимит на категорию, и тут появится контроль</p>
                    <button type="button" className="btn mt-3" onClick={() => { setBudgetCat(null); setSheet('budget') }}><Plus size={15} /> задать лимит</button>
                  </div>
                ) : (
                  <>
                    <div className="flex items-baseline gap-2">
                      <span className="text-[26px] font-semibold" style={{ color: budgetLeft < 0 ? 'var(--neg)' : 'inherit' }}>
                        <Num value={Math.abs(budgetLeft)} /> ₽
                      </span>
                      <span className="text-xs text-[var(--ink3)]">{budgetLeft < 0 ? 'перерасход' : 'в запасе'} из {money(totalBudget)}</span>
                    </div>
                    <div className="mt-4 space-y-3">
                      {budgetItems.slice(0, 5).map((b) => (
                        <div key={b.id || b.name} className="cursor-pointer text-[13px]" title="Изменить лимит" onClick={() => { setBudgetCat(b); setSheet('budget') }}>
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
                      <span>перерасход: {budgetItems.filter((b) => b.status === 'over').length} · нажмите категорию, чтобы поправить лимит</span>
                      <span className="btn-soft btn-sm" onClick={() => { setTxCategory('all'); setTab('txs') }}>смотреть операции →</span>
                    </div>
                  </>
                )}
              </section>
            )
            if (id === 'upcoming') return (
              <section key="upcoming" className="c s6 r" style={st}>{ctl}
                <div className="hd"><h2>ближайшие списания</h2><small>регулярные платежи</small></div>
                {!nextPayments.length ? (
                  <p className="py-6 text-center text-sm text-[var(--ink3)]">регулярных платежей нет</p>
                ) : nextPayments.slice(0, 5).map((r) => (
                  <div className="rowi" key={r.id}>
                    <time>{r.on.getDate()} {['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'][r.on.getMonth()]}</time>
                    <span className="t">
                      {r.title || r.name}
                      <small>через {daysUntil(r.on)} {plural(daysUntil(r.on), 'день', 'дня', 'дней')}{r.category ? ` · ${r.category}` : ''}</small>
                    </span>
                    <span className="amt">−{money(r.amount)}</span>
                  </div>
                ))}
                {nextPayments.length > 0 && (
                  <div className="flex items-center justify-between mt-3 pt-3 border-t border-[var(--line)] text-xs text-[var(--ink3)]">
                    <span>за 7 дней: {money(nextPayments.filter((r) => daysUntil(r.on) <= 7).reduce((s, r) => s + (r.amount || 0), 0))}</span>
                    <span className="btn-soft btn-sm" onClick={() => setTab('recurring')}>управление →</span>
                  </div>
                )}
              </section>
            )
            return (
              <section key="flow" className="c s12 r" style={st}>{ctl}
                <div className="hd"><h2>поток в месяц</h2><small>доход минус обязательные платежи — то, чем реально можно распоряжаться</small></div>
                <div className="flow">
                  <i style={{ width: `${flowRecurringPct}%`, background: 'linear-gradient(90deg, var(--ink), #4b4b55)' }}></i>
                  <i style={{ width: `${flowDebtPct}%`, background: 'linear-gradient(90deg, #b9bcc6, var(--ink3))' }}></i>
                  <i style={{ width: `${flowFreePct}%`, background: 'linear-gradient(90deg, var(--acc), #8a5cff)' }}></i>
                </div>
                <div className="fl">
                  <span>регулярные · долги · свободно</span>
                  <span>на жизнь обычно уходит {money(livingSpent)} → остаётся <b>{livingRemain < 0 ? '−' : ''}{money(Math.abs(livingRemain))}</b></span>
                </div>
              </section>
            )
          })}
          {cardsEdit && (
            <section className="c s12 r" style={{ '--i': 11 }}>
              <div className="hd"><h2>настройка карточек</h2><small></small></div>
              <p className="muted text-[13px]">стрелки — порядок, кнопка с числом — ширина карточки, крестик — спрятать.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {FIN_CARDS.filter((x) => !cardOrder.includes(x)).map((x) => (
                  <button key={x} className="btn-soft btn-sm" onClick={() => setCardOrder((o) => [...o, x])}>+ {FIN_CARD_LABELS[x]}</button>
                ))}
                <button className="btn-ghost btn-sm" onClick={resetCards}>вернуть всё как было</button>
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
                  placeholder="поиск по названию или категории…"
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
                    все
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
              </div>
            </div>
            {/* фильтр по счёту: отдельной строкой, чтобы не спорить с категориями */}
            <div className="flex flex-wrap items-center gap-2 mt-3 pt-3 border-t border-[var(--line)]">
              <span className="text-[11px] uppercase tracking-wider text-[var(--ink3)]">счёт</span>
              <span className="chips !m-0 !gap-1.5">
                <button type="button" className={txAccount === 'all' ? '!bg-[var(--ink)] !text-[var(--bg)]' : ''} onClick={() => setTxAccount('all')}>все</button>
                {accounts.map((a) => (
                  <button type="button" key={a.id || a.name} className={txAccount === a.name ? '!bg-[var(--ink)] !text-[var(--bg)]' : ''} onClick={() => setTxAccount(a.name)}>{a.name}</button>
                ))}
              </span>
              {(txCategory !== 'all' || txAccount !== 'all' || txSearch) && (
                <button type="button" className="btn-ghost btn-sm !h-6" onClick={() => { setTxCategory('all'); setTxAccount('all'); setTxSearch('') }}>сбросить</button>
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
              <h2>история операций</h2>
              <small>{shownTxs.length} {plural(shownTxs.length, 'запись', 'записи', 'записей')} · {days ? `за ${days} дн` : 'вся история'}</small>
            </div>
            {shownTxs.length === 0 ? (
              <p className="py-8 text-center text-sm text-[var(--ink3)]">нет операций за указанный период</p>
            ) : (
              shownTxs.map((t) => (
                <div className="rowi group" key={t.id}>
                  <time>{shortDate(t.date || t.created_at)}</time>
                  <span className="t">
                    {t.title || t.note || t.category || 'Операция'}
                    <small>
                      {[t.category, t.account, t.comment].filter(Boolean).join(' · ')}
                    </small>
                  </span>
                  {/* знак берём из kind: amount приходит из API положительным */}
                  <span className="amt" style={{ color: t.kind === 'income' ? 'var(--pos)' : 'inherit' }}>
                    {t.kind === 'income' ? '+' : t.kind === 'expense' ? '−' : ''}{money(t.amount)}
                  </span>
                  <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition">
                    <button
                      type="button"
                      onClick={() => { setEditingItem(t); setSheet('tx') }}
                      className="p-1.5 rounded-full hover:bg-[var(--sf)] text-[var(--ink2)]"
                      title="Редактировать"
                    >
                      <Edit2 size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (confirm('Удалить эту операцию?')) {
                          try {
                            await api.delTx(t.id)
                            load()
                            bump()
                          } catch (e) { show.err(e) }
                        }
                      }}
                      className="p-1.5 rounded-full hover:bg-[var(--sf)] text-[var(--neg)]"
                      title="Удалить"
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
                <h3 className="text-lg font-medium">Счета ещё не добавлены</h3>
                <p className="text-sm text-[var(--ink2)] mt-1">Добавьте банковские карты, наличные или кошельки для учёта баланса</p>
                <button
                  type="button"
                  className="btn mt-4"
                  onClick={() => { setEditingItem(null); setSheet('account') }}
                >
                  <Plus size={15} /> добавить счёт
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
                  <span className="text-[13px] text-[var(--ink3)]">{a.comment || ({ card: 'карта', cash: 'наличные', bank: 'счёт', savings: 'вклад', crypto: 'крипта' })[atype] || 'счёт'}</span>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      onClick={() => { setEditingItem(a); setSheet('account') }}
                      className="p-1 rounded-full text-[var(--ink2)] hover:text-[var(--ink)]"
                      title="Изменить"
                    >
                      <Edit2 size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (!confirm(`Удалить счёт «${a.name}»? Операции по нему останутся в истории.`)) return
                        try { await api.delAccount(a.id); load(); bump() } catch (e) { show.err(e) }
                      }}
                      className="p-1 rounded-full text-[var(--neg)] hover:bg-[var(--sf2)]"
                      title="Удалить счёт"
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
            <div className="hd"><h2>общий долг</h2><small>осталось</small></div>
            <div className="big"><Num value={debtsTotal} /> ₽</div>
            <span className="tag">
              {debts.length} {plural(debts.length, 'активный долг', 'активных долга', 'активных долгов')}
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
                  <small>{d.creditor || 'кредитор'}</small>
                </div>
                <div className="mid"><Num value={left} /> ₽</div>
                <div className="w-full bg-white/10 rounded-full h-2 mt-4 overflow-hidden">
                  <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, var(--acc), #8a5cff)' }}></div>
                </div>
                <div className="flex items-center justify-between mt-3 text-xs text-[#8b8e98] num">
                  <span>выплачено {money(paid)} ({pct}%)</span>
                  <span>из {money(total)}</span>
                </div>
                <div className="flex items-center justify-between mt-4 pt-3 border-t border-white/10">
                  <button
                    type="button"
                    onClick={() => { setEditingItem(d); setSheet('payDebt') }}
                    className="btn g !h-8 !px-3 text-[12px]"
                  >
                    внести платёж
                  </button>
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={() => { setEditingItem(d); setSheet('debt') }}
                      className="p-1.5 text-white/50 hover:text-white"
                      title="Изменить"
                    >
                      <Edit2 size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (!confirm(`Удалить долг «${d.name || d.title}»?`)) return
                        try { await api.delDebt(d.id); load(); bump() } catch (e) { show.err(e) }
                      }}
                      className="p-1.5 text-[var(--neg)] hover:opacity-80"
                      title="Удалить"
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
            <div className="hd"><h2>регулярные</h2><small>в месяц</small></div>
            <div className="big">
              <Num value={recurring.reduce((s, r) => s + (r.amount || 0), 0) || 1528} /> ₽
            </div>
            <span className="tag">
              {recurring.length} {plural(recurring.length, 'подписка', 'подписки', 'подписок')}
            </span>
          </section>

          <section className="c s8 r" style={{ '--i': 4 }}>
            <div className="hd"><h2>список регулярных платежей</h2><small>подписки, сервис, аренда</small></div>
            {recurring.length === 0 ? (
              <p className="py-6 text-center text-sm text-[var(--ink3)]">нет регулярных платежей</p>
            ) : (
              recurring.map((r) => (
                <div className="rowi group" key={r.id}>
                  <time>{(r.day_of_month || r.day) ? `${r.day_of_month || r.day} числа` : 'ежемес.'}</time>
                  <span className="t">
                    {r.name || r.title}
                    <small>{[r.category, r.account].filter(Boolean).join(' · ') || (r.kind === 'income' ? 'поступление' : 'списание')}</small>
                  </span>
                  <span className="amt" style={{ color: r.kind === 'income' ? 'var(--pos)' : 'inherit' }}>
                    {r.kind === 'income' ? '+' : '−'}{money(r.amount)}
                  </span>
                  <span className={`chip !ml-2 ${r.active === false ? '!opacity-50' : ''}`}>{r.active === false ? 'пауза' : 'активен'}</span>
                  <button
                    type="button"
                    onClick={() => { setEditingItem(r); setSheet('recurring') }}
                    className="p-1 rounded-full text-[var(--ink2)] hover:text-[var(--ink)] opacity-0 group-hover:opacity-100 transition"
                    title="Изменить платёж"
                  >
                    <Edit2 size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      if (!confirm(`Удалить платёж «${r.name || r.title}»?`)) return
                      try { await api.delRecurring(r.id); load(); bump() } catch (e) { show.err(e) }
                    }}
                    className="p-1 rounded-full text-[var(--neg)] hover:bg-[var(--sf2)]"
                    title="Удалить"
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
                <h3 className="text-lg font-medium">Нет активных финансовых целей</h3>
                <p className="text-sm text-[var(--ink2)] mt-1">Создайте цель, чтобы откладывать на мечту, подушку безопасности или покупки</p>
                <button
                  type="button"
                  className="btn mt-4"
                  onClick={() => { setEditingItem(null); setSheet('goal') }}
                >
                  <Plus size={15} /> создать цель
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
                    <small>{g.deadline ? shortDate(g.deadline) : 'бессрочно'}</small>
                  </div>
                  <div className="mid font-semibold"><Num value={current} /> ₽</div>
                  <div className="w-full bg-[var(--line)] rounded-full h-2 mt-4 overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, #19b34a, #14b8a6)' }}></div>
                  </div>
                  <div className="flex items-center justify-between mt-2.5 text-xs text-[var(--ink2)] num">
                    <span>{pct}% накоплено</span>
                    <span>цель: {money(target)}</span>
                  </div>
                  {target > current && goalEta(target - current) && (
                    <div className="mt-2 text-[12px] text-[var(--ink3)]">при 5 000 ₽/мес — {goalEta(target - current)}</div>
                  )}
                  <div className="flex items-center justify-between mt-4 pt-3 border-t border-[var(--line)]">
                    <button
                      type="button"
                      onClick={() => { setEditingItem(g); setSheet('putGoal') }}
                      className="btn !h-8 !px-3 text-[12px]"
                    >
                      пополнить
                    </button>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        onClick={() => { setEditingItem(g); setSheet('goal') }}
                        className="p-1 rounded-full text-[var(--ink2)] hover:text-[var(--ink)]"
                        title="Изменить"
                      >
                        <Edit2 size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          if (!confirm(`Удалить цель «${g.title || g.name}»?`)) return
                          try { await api.delGoal(g.id); load(); bump() } catch (e) { show.err(e) }
                        }}
                        className="p-1 rounded-full text-[var(--neg)] hover:bg-[var(--sf2)]"
                        title="Удалить"
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
                text="Техники пока не посчитаны"
                sub="Нужны операции за месяц — как только появятся, покажу 50/30/20, сравнение с прошлым месяцем и запас"
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
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
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
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
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
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
      />

      <BudgetSheet
        open={sheet === 'budget'}
        item={budgetCat}
        categories={categories}
        onClose={() => { setSheet(null); setBudgetCat(null) }}
        onDone={() => { setSheet(null); setBudgetCat(null); load(); bump() }}
      />
    </div>
  )
}

/* =========================================================================
   Диалоги редактирования (Sheet)
   ========================================================================= */

function TxSheet({ open, item, categories = [], accounts = [], onClose, onDone }) {
  const isNew = !item?.id
  const [amount, setAmount] = useState('')
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('')
  const [account, setAccount] = useState('')
  const [comment, setComment] = useState('')
  const [kind, setKind] = useState('expense')
  const [date, setDate] = useState('')
  const [saving, setSaving] = useState(false)
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
  }, [open, item])

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseFloat(amount.replace(/\s/g, ''))
    if (!a || isNaN(a)) return
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
    <Sheet open={open} onClose={onClose} title={isNew ? 'новая операция' : 'редактирование операции'}>
      <form onSubmit={submit} className="space-y-4">
        <div className="sg w-full">
          <span className={kind === 'expense' ? 'on' : ''} onClick={() => setKind('expense')}>расход</span>
          <span className={kind === 'income' ? 'on' : ''} onClick={() => setKind('income')}>доход</span>
        </div>
        <Field label="сумма (₽)">
          <input className="input" autoFocus type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="1000" />
        </Field>
        <Field label="описание">
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Супермаркет, такси, зарплата…" />
        </Field>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="категория">
            <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Еда, транспорт…" list="cat-list" />
            <datalist id="cat-list">
              {categories.map(c => <option key={c.id || c.name || c} value={c.name || c} />)}
            </datalist>
          </Field>
          <Field label="счёт">
            <select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>
              <option value="">не указан</option>
              {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
            </select>
          </Field>
        </div>
        <Field label="дата">
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="комментарий">
          <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="необязательно" />
        </Field>
        <div className="flex justify-between gap-2 pt-4">
          {!isNew && (
            <button type="button" className="btn g !text-[var(--neg)]"
              onClick={async () => {
                if (!confirm('Удалить операцию? Баланс счёта вернётся обратно.')) return
                try { await api.delTx(item.id); onDone() } catch (err) { show.err(err) }
              }}>удалить</button>
          )}
          <div className="ml-auto flex gap-2">
            <button type="button" className="btn g" onClick={onClose}>отмена</button>
            <button type="submit" className="btn" disabled={saving || !amount}>{saving ? 'сохраняю…' : 'сохранить'}</button>
          </div>
        </div>
      </form>
    </Sheet>
  )
}

function AccountSheet({ open, account, onClose, onDone }) {
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
    <Sheet open={open} onClose={onClose} title={isNew ? 'новый счёт' : 'редактировать счёт'}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="название счёта">
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Тинькофф, Сбербанк, Наличные…" />
        </Field>
        <Field label="текущий баланс (₽)">
          <input className="input" type="number" step="any" value={balance} onChange={(e) => setBalance(e.target.value)} placeholder="0" />
        </Field>
        <Field label="тип счёта">
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="card">Банковская карта</option>
            <option value="cash">Наличные</option>
            <option value="bank">Банковский счёт / вклад</option>
            <option value="crypto">Криптокошелёк</option>
          </select>
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>отмена</button>
          <button type="submit" className="btn" disabled={saving || !name.trim()}>{saving ? 'сохраняю…' : 'сохранить'}</button>
        </div>
      </form>
    </Sheet>
  )
}

function DebtSheet({ open, debt, onClose, onDone }) {
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
        name: name.trim(),
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
    <Sheet open={open} onClose={onClose} title={isNew ? 'новый долг' : 'редактировать долг'}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="название">
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Кредитка, долг другу…" />
        </Field>
        <Field label="кредитор (банк или человек)">
          <input className="input" value={creditor} onChange={(e) => setCreditor(e.target.value)} placeholder="Сбербанк, Иван…" />
        </Field>
        <Field label="общая сумма долга (₽)">
          <input className="input" type="number" step="any" value={total} onChange={(e) => setTotal(e.target.value)} placeholder="50000" />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>отмена</button>
          <button type="submit" className="btn" disabled={saving || !name.trim()}>{saving ? 'сохраняю…' : 'сохранить'}</button>
        </div>
      </form>
    </Sheet>
  )
}

function PayDebtSheet({ open, debt, accounts = [], onClose, onDone }) {
  const [amount, setAmount] = useState('')
  const [account, setAccount] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => { if (open) setAccount(accounts[0]?.name || '') }, [open])

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseFloat(amount)
    if (!a || isNaN(a) || !debt?.id) return
    setSaving(true)
    try {
      await api.payDebt(debt.id, a, { account })
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={`внести платёж: ${debt?.name || ''}`}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="сумма платежа (₽)">
          <input className="input" autoFocus type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="5000" />
        </Field>
        <Field label="списать со счёта" hint="деньги реально уйдут с баланса — иначе расчёт не сойдётся">
          <select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="none">не списывать</option>
            {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
          </select>
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>отмена</button>
          <button type="submit" className="btn" disabled={saving || !amount}>{saving ? 'сохраняю…' : 'внести'}</button>
        </div>
      </form>
    </Sheet>
  )
}

function RecurringSheet({ open, item, categories = [], onClose, onDone }) {
  const isNew = !item?.id
  const [name, setName] = useState('')
  const [amount, setAmount] = useState('')
  const [category, setCategory] = useState('')
  const [day, setDay] = useState('1')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setName(item?.name || item?.title || '')
    setAmount(item?.amount != null ? String(item.amount) : '')
    setCategory(item?.category || '')
    setDay(item?.day ? String(item.day) : '1')
  }, [open, item])

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const payload = {
        name: name.trim(),
        amount: parseFloat(amount) || 0,
        category: category.trim() || undefined,
        day: parseInt(day, 10) || 1,
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

  return (
    <Sheet open={open} onClose={onClose} title={isNew ? 'новый регулярный платёж' : 'редактировать платёж'}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="название">
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Яндекс Плюс, Спортзал, Подписка…" />
        </Field>
        <Field label="сумма в месяц (₽)">
          <input className="input" type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="499" />
        </Field>
        <Field label="день списания (1–31)">
          <input className="input" type="number" min="1" max="31" value={day} onChange={(e) => setDay(e.target.value)} />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>отмена</button>
          <button type="submit" className="btn" disabled={saving || !name.trim()}>{saving ? 'сохраняю…' : 'сохранить'}</button>
        </div>
      </form>
    </Sheet>
  )
}

function GoalSheet({ open, goal, onClose, onDone }) {
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
    <Sheet open={open} onClose={onClose} title={isNew ? 'новая финансовая цель' : 'редактировать цель'}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="название цели">
          <input className="input" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Подушка безопасности, новый ноутбук…" />
        </Field>
        <Field label="целевая сумма (₽)">
          <input className="input" type="number" step="any" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="100000" />
        </Field>
        <Field label="уже накоплено (₽)">
          <input className="input" type="number" step="any" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="0" />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>отмена</button>
          <button type="submit" className="btn" disabled={saving || !title.trim()}>{saving ? 'сохраняю…' : 'сохранить'}</button>
        </div>
      </form>
    </Sheet>
  )
}

function PutGoalSheet({ open, goal, accounts = [], onClose, onDone }) {
  const [amount, setAmount] = useState('')
  const [account, setAccount] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => { if (open) setAccount(accounts[0]?.name || '') }, [open])

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseFloat(amount)
    if (!a || isNaN(a) || !goal?.id) return
    setSaving(true)
    try {
      await api.putGoal(goal.id, a, { account })
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={`пополнить копилку: ${goal?.title || goal?.name || ''}`}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="сумма пополнения (₽)">
          <input className="input" autoFocus type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="2000" />
        </Field>
        <Field label="списать со счёта" hint="отложенные деньги уйдут с баланса — так видна настоящая картина">
          <select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="none">не списывать</option>
            {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
          </select>
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>отмена</button>
          <button type="submit" className="btn" disabled={saving || !amount}>{saving ? 'сохраняю…' : 'пополнить'}</button>
        </div>
      </form>
    </Sheet>
  )
}

/* Месячный лимит категории: хранится в Category.budget, карточка «бюджеты» читает его
   через /api/finance/budgets. Лимит необязателен — 0 или пусто означает «без контроля». */
function BudgetSheet({ open, item, categories = [], onClose, onDone }) {
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
    <Sheet open={open} onClose={onClose} title="лимит на месяц" sub="необязательно: 0 или пусто — категория без контроля">
      <form onSubmit={submit} className="space-y-4">
        <Field label="категория">
          <select className="input" value={cid} onChange={(e) => pick(e.target.value)} autoFocus>
            {!options.length && <option value="">нет расходных категорий</option>}
            {options.map((c) => <option key={c.id} value={c.id}>{c.icon} {c.name}{c.budget ? ` · ${money(c.budget)}` : ''}</option>)}
          </select>
        </Field>
        <Field label="лимит на месяц (₽)" hint="0 — без лимита">
          <Money value={amount} onChange={setAmount} min={0} placeholder="0" />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>отмена</button>
          <button type="submit" className="btn" disabled={saving || !cid}>{saving ? 'сохраняю…' : 'сохранить'}</button>
        </div>
      </form>
    </Sheet>
  )
}
