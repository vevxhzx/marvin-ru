/* Финансы: один герой на экран, остальное — спокойно.

   Иерархия вкладки «обзор»:
     1. лаймовый герой — баланс крупно (--hero-fs) и три строки мелким под ним:
        свободно, до зарплаты, сколько дней до нуля. Никаких карточек на каждое число;
     2. один график «касса на N дней» (CashChart + ChartTip) — широкая спокойная панель;
     3. дальше — разделы-строки на волосяных разделителях: поток денег, лимиты по
        категориям, ближайшие платежи. Порядок и состав — кнопкой «настроить».

   Остальные вкладки — то же правило: один блок с данными сверху и списки-строки ниже.
   Все формы остались в шторках Sheet — меняется только вид. */

import { useEffect, useMemo, useState } from 'react'
import { api, money, shortDate, toLocalISO } from '../lib/api'
import { Sheet, Field, Empty, Money, Rowi, Skeleton, useToast, Confirm } from '../components/ui'
import { BigMoney, HeroLine, useNumFormats, useReveal } from '../components/Widgets'
import CashChart from '../components/CashChart'
import LifeRegime from '../components/LifeRegime'
import { ImportButton } from '../components/Widgets'
import { useRefresh } from '../App'
import { Plus, Search, Trash2, Edit2, CreditCard, Wallet, Landmark, PiggyBank, Target, ChevronLeft, EyeOff, Play, Pause } from 'lucide-react'
import { Techniques } from '../components/FinanceSmart'
import { useCardLayout, CardCtl } from '../lib/layout'
import { usePageAccent } from '../lib/prefs'
import { useI18n, localeOf, t as T } from '../lib/i18n'

/* Разделы-строки вкладки «обзор»: порядок и ширина хранятся общим модулем lib/layout.
   Числа потока (доходы, регулярные, платежи по долгам, свободно) больше не отдельные
   карточки — это строки внутри раздела «поток денег», поэтому в списке он один. */
const FIN_CARDS = ['flow', 'budgets', 'upcoming']
const FIN_CARD_WIDTHS = { flow: 12, budgets: 12, upcoming: 12 }
const FIN_CARD_LABELS = { flow: 'fin.flow_month', budgets: 'fin.c_budgets', upcoming: 'fin.c_upcoming' }

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

/* Знак суммы: минус — типографский, разряды неразрывные (форматы даёт useNumFormats) */
const MINUS = '−'

/* Раздел-строка: прозрачная секция с шапкой .hd и волосяными разделителями Rowi.
   Объявлена на уровне модуля, чтобы React не пересоздавал поддерево на каждом рендере.

   Разметка <section class="c"> — по ней ходят проверки e2e (история операций = секция с этим
   заголовком), поэтому класс .c остаётся, а карточная обёртка снимается теми же переопределениями,
   что и у строки человека в People.jsx: секция плоская, без фона, тени и подъёма по наведению. */
function Block({ title, note, action, children, className = '' }) {
  return (
    <section className={`c !rounded-none !p-0 !bg-transparent !shadow-none !transform-none !overflow-visible ${className}`} data-reveal>
      <div className="hd flex-wrap">
        <div className="min-w-0"><h2 className="trunc" title={title}>{title}</h2></div>
        <div className="flex items-center gap-2">
          {note && <small className="trunc">{note}</small>}
          {action}
        </div>
      </div>
      {children}
    </section>
  )
}

/* Кнопки-иконки строки: видны всегда (на тап-экранах раньше прятались до наведения) */
function RowActions({ children }) {
  return <div className="flex shrink-0 items-center gap-1">{children}</div>
}

function IconBtn({ onClick, title, children, danger }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="btn-icon"
      style={danger ? { color: 'var(--neg)' } : { color: 'var(--ink-3)' }}
      title={title}
      aria-label={title}
    >
      {children}
    </button>
  )
}

export default function Finance() {
  const { t } = useI18n()
  const fmt = useNumFormats()
  const [tab, setTab] = useState('overview') // 'overview' | 'txs' | 'accounts' | 'debts' | 'recurring' | 'goals' | 'techniques'
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
  // Режим жизни (services/regime.py): по умолчанию выключен, цифры считаются как раньше
  const [regime, setRegime] = useState(null)

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
  const { order: cardOrder, setOrder: setCardOrder, move, reset: resetCards } = useCardLayout('finance', FIN_CARDS, FIN_CARD_WIDTHS)
  const pageAcc = usePageAccent('finance')
  const reveal = useReveal(tab)

  const [, show] = useToast()
  const { tick, bump } = useRefresh()

  const load = async () => {
    try {
      const [s, t, accs, d, rec, g, cats, tech, fc, bg, rg] = await Promise.all([
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
        api.get('/api/finance/regimes').catch(() => null),   // режим жизни (по умолчанию выключен)
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
      // сводка/прогноз уже принесли regime — берём из них, отдельный ответ только как запасной вариант
      setRegime(s?.regime || fc?.regime || bg?.safe?.regime || rg || null)
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
  // Считаются ли цифры по режиму жизни: берём из ответа сервера (сводка/прогноз), иначе плашка
  const regCounted = !!(sum?.regime?.counted || forecast?.regime?.counted)
  const debtsTotal = sum?.debts_total ?? (debts.reduce((acc, x) => acc + ((x.total || 0) - (x.paid || 0)), 0) || 205700)

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

  // «До зарплаты» и «безопасно в день» — из того же ответа сводки (services/finance.safe_to_spend)
  const safe = sum?.safe || null
  const daysLeft = safe?.days_left ?? forecast?.days_to_income ?? null
  const safePerDay = safe?.per_day ?? null

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
      ...shownTxs.map(x => [
        x.date ? x.date.slice(0, 10) : '',
        x.amount,
        x.category || '',
        `"${(x.title || x.note || '').replace(/"/g, '""')}"`,
        x.account || ''
      ])
    ]
    // Файл отдаём объектом Blob, а не ссылкой вида data:text/csv;…:
    // percent-encoding всей выписки (encodeURIComponent) Chromium обрывает — скачивание
    // приходит отменённым, а «голый» data:-URL портится на «#» и «?» в описании операции.
    // BOM — чтобы Excel открыл кириллицу без плясок с кодировкой.
    const csvContent = '\uFEFF' + rows.map(e => e.join(';')).join('\n')
    const url = URL.createObjectURL(new Blob([csvContent], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.setAttribute('href', url)
    link.setAttribute('download', `statement_${toLocalISO(now).slice(0, 10)}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    // адрес живёт, пока Chromium читает файл: отпускаем его не в том же кадре
    setTimeout(() => URL.revokeObjectURL(url), 30_000)
  }

  const addForTab = () => {
    if (tab === 'accounts') { setEditingItem(null); setSheet('account') }
    else if (tab === 'debts') { setEditingItem(null); setSheet('debt') }
    else if (tab === 'recurring') { setEditingItem(null); setSheet('recurring') }
    else if (tab === 'goals') { setEditingItem(null); setSheet('goal') }
    else { setEditingItem(null); setSheet('tx') }
  }

  const tabLine = tab === 'overview' ? t('fin.sub_overview')
    : tab === 'txs' ? t('fin.n_txs', { count: shownTxs.length })
      : tab === 'accounts' ? t('fin.n_accounts', { count: accounts.length })
        : tab === 'debts' ? t('fin.n_debts', { count: debts.length })
          : tab === 'recurring' ? t('fin.n_rec', { n: recActive.length, paused: recPaused.length ? t('fin.n_rec_paused', { n: recPaused.length }) : '' })
            : tab === 'goals' ? t('fin.n_goals', { count: goals.length })
              : t('tech.title')

  return (
    <div className="pg on" id="p-fin" style={pageAcc.style} ref={reveal}>
      {/* Шапка экрана: заголовок, что показываем, и действия справа */}
      <header className="top" data-reveal>
        <div className="min-w-0">
          <h1>{t('nav.finance')}</h1>
          <p className="sub">{tabLine}</p>
        </div>
        <div className="hr">
          {/* Переключатель периода — в шапке: период режет данные ВСЕХ вкладок (обзор, операции,
              счета, долги), а не только списка операций. Тот же сегмент .sg в .top, что на
              задачах и календаре — и по нему ходят проверки e2e (#p-fin .top .sg[title^="период"]). */}
          <div className="sg" role="group" aria-label={t('fin.period_tip')} title={t('fin.period_tip')}>
            {[[7, 'mem.d7'], [30, 'mem.d30'], [90, 'fin.d90'], [0, 'fin.d_all']].map(([v, key]) => (
              <button key={v} type="button" className={days === v ? 'on' : ''} aria-pressed={days === v} onClick={() => setDays(v)}>
                {t(key)}
              </button>
            ))}
          </div>
          {tab === 'overview' && (
            <button type="button" className="btn-soft btn-sm" onClick={() => setCardsEdit((v) => !v)}
              title={t('tk.layout_tip')} aria-label={t('fin.configure_cards')}>
              {t('tk.layout')}
            </button>
          )}
          <button type="button" className="btn-soft btn-sm" onClick={exportCSV}
            title={t('fin.csv_dl')} aria-label={t('fin.csv_dl')}>
            {t('fin.statement')}
          </button>
          <button
            type="button"
            className="btn btn-sm"
            title={t('fin.add_entry')}
            aria-label={t('fin.add_entry')}
            onClick={addForTab}
          >
            {t(tab === 'accounts' ? 'fin.add_account' : tab === 'debts' ? 'fin.add_debt' : tab === 'recurring' ? 'fin.add_pay' : tab === 'goals' ? 'fin.add_goal' : 'fin.add_tx')}
          </button>
        </div>
      </header>

      {/* Режим жизни: чип в шапке + переключатель «считать по режиму». По умолчанию выключен,
          тогда все цифры ниже считаются по всем данным, как раньше. */}
      <LifeRegime info={regime} onChanged={(r) => { setRegime(r); load() }} />

      {/* Вкладки разделов — прямой ребёнок .pg (без обёртки): на них завязаны проверки e2e
          (#p-fin > .sg). Спокойный сегмент, активная вкладка читается заливкой. */}
      <div className="sg mt-3" role="group" aria-label={t('nav.finance')}>
        {[['overview', 'fin.tab_overview'], ['txs', 'fin.tab_txs'], ['accounts', 'fin.tab_accounts'], ['debts', 'fin.tab_debts'],
          ['recurring', 'fin.tab_recurring'], ['goals', 'goals.title'], ['techniques', 'tech.title']].map(([k, key]) => (
            <button key={k} type="button" className={tab === k ? 'on' : ''} aria-pressed={tab === k} onClick={() => setTab(k)}>
              {t(key)}
            </button>
          ))}
      </div>

      {/* ---------------- ОБЗОР ---------------- */}
      {tab === 'overview' && (
        <>
          {/* Герой: баланс крупно и три строки мелким под ним — без карточек на каждое число */}
          <section className="c hero mt-4" data-reveal>
            <div className="hd flex-wrap">
              <div className="min-w-0"><h2 className="trunc">{t('fin.c_balance')}</h2></div>
              <small className="trunc">{t('fin.all_accounts')}</small>
            </div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
              <BigMoney value={balance} format={fmt.int} label={money(balance)} fs="clamp(38px, 7vw, 68px)" />
              <span className="tag" style={{ marginTop: 0 }}>{t('fin.for_days', { n: days || t('common.all'), m: money(spent) })}</span>
            </div>
            {regCounted && (
              <div className="mt-1 text-[length:var(--fs-md)] opacity-75">{t('reg.spent_by_regime')}</div>
            )}
            <div className="mt-3" style={{ borderTop: '1px solid var(--hero-ink-16)', paddingTop: 'var(--s-2)' }}>
              <HeroLine label={`${t('fin.c_free')} / ${t('td.per_month').toLowerCase()}`} value={fmt.money(cf.free || 0)} />
              {daysLeft != null && (
                <HeroLine
                  label={t('spend.until_income', { count: daysLeft })}
                  value={safePerDay != null ? `${t('fc.safe')} ${fmt.money(Math.round(safePerDay))}` : '—'}
                />
              )}
              {forecast?.runway_days != null && (
                <HeroLine label={t('td.to_zero', { n: forecast.runway_days })} value={forecast?.min_balance != null ? fmt.money(forecast.min_balance) : '—'} />
              )}
            </div>
          </section>

          {/* Один график на экран: касса на N дней, интерактивный, с подсказками ChartTip */}
          <section className="c chart mt-4" data-reveal>
            <div className="hd flex-wrap">
              <div className="min-w-0">
                <h2 className="trunc">{t('fin.cash_on', { n: days || t('common.all'), days: t('run.days_n', { count: days }) })}</h2>
              </div>
              <small className="trunc">
                {forecast
                  ? `${t('fin.fc_now', { bal: money(forecast.balance), pace: money(forecast.avg_day_spent) })}${regCounted ? ` · ${t('reg.by_regime')}` : ''}`
                  : t('fc.by_pace')}
              </small>
            </div>
            {forecast
              ? <CashChart f={forecast} height={220} txs={txs} legend={false} />
              : <Skeleton h={220} radius="var(--r-md)" />}
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
              <div className="muted mt-2 text-[length:var(--fs-xs)]">
                {t('fin.scen_min')} <b className="num">{money(forecast.scenarios.realistic.low)}</b>
                {' · '}{t('fin.pessimistic', { n: forecast.scenarios.pessimistic.delay_days ?? 0 })} <b className={`num ${forecast.scenarios.pessimistic.ok ? '' : 'neg'}`}>{money(forecast.scenarios.pessimistic.low)}</b>
              </div>
            )}
          </section>

          {/* Дальше — разделы-строки. Порядок и состав — кнопкой «настроить» */}
          <div className="stack mt-5 !gap-6">
            {cardOrder.map((id) => {
              const ctl = (
                <CardCtl id={id} order={cardOrder} edit={cardsEdit}
                  onMove={move} onHide={(x) => setCardOrder((o) => o.filter((w) => w !== x))}
                  Icon={ChevronLeft} HideIcon={EyeOff} />
              )

              /* Поток денег: четыре строки-числа и полоса долей */
              if (id === 'flow') {
                return (
                  <section key="flow" data-reveal className="relative">
                    {ctl}
                    <div className="hd flex-wrap">
                      <div className="min-w-0"><h2 className="trunc">{t('fin.flow_month')}</h2></div>
                    </div>
                    <Rowi
                      title={t('fin.c_income')}
                      sub={cf.income_is_estimate ? t('fin.average') : t('fin.income_days', { n: days })}
                      right={<span className="amt pos">+{fmt.money(cf.income || 0)}</span>}
                    />
                    <Rowi title={t('fin.c_recurring')} right={<span className="amt">{MINUS}{fmt.money(cf.recurring || 0)}</span>} />
                    <Rowi title={t('fin.by_debts')} right={<span className="amt">{MINUS}{fmt.money(cf.debt_payments || 0)}</span>} />
                    <Rowi
                      title={t('fin.c_free')}
                      sub={t('td.per_month')}
                      right={<span className="num text-[length:var(--fs-lg)] font-medium text-[var(--pos)]">{fmt.money(cf.free || 0)}</span>}
                    />
                    <div className="rule mt-3 pt-1">
                      <div className="flow" style={{ marginTop: 0 }}>
                        <i style={{ width: `${flowRecurringPct}%`, background: 'var(--ink)' }} />
                        <i style={{ width: `${flowDebtPct}%`, background: 'var(--ink-3)' }} />
                        <i style={{ width: `${flowFreePct}%`, background: 'var(--accent)' }} />
                      </div>
                      <div className="fl">
                        <span>{t('fin.reg_debt_free')}</span>
                        <span>{t('fin.living_costs')} {fmt.money(livingSpent)} → {t('fin.remains')} <b className={livingRemain < 0 ? 'neg' : ''}>{livingRemain < 0 ? MINUS : ''}{fmt.money(Math.abs(livingRemain))}</b></span>
                      </div>
                    </div>
                  </section>
                )
              }

              /* Лимиты по категориям: строки с полосками */
              if (id === 'budgets') {
                return (
                  <section key="budgets" data-reveal className="relative">
                    {ctl}
                    <div className="hd flex-wrap">
                      <div className="min-w-0"><h2 className="trunc">{t('fin.budgets_month')}</h2></div>
                      <div className="flex items-center gap-2">
                        <small className="trunc">{budgetItems.length ? `${MON_SHORT[now.getMonth()]} · ${t(budgetLeft >= 0 ? 'fin.left' : 'fin.over')}` : ''}</small>
                        <button type="button" className="btn-soft btn-sm" onClick={() => { setBudgetCat(null); setSheet('budget') }}
                          title={t('fin.limit')}>
                          + {t('fin.limit')}
                        </button>
                      </div>
                    </div>
                    {!budgetItems.length ? (
                      <div className="py-4">
                        <p className="text-[length:var(--fs-md)] text-[var(--ink3)]">{t('fin.no_limits')}</p>
                        <button type="button" className="btn mt-3" onClick={() => { setBudgetCat(null); setSheet('budget') }}>
                          <Plus size={15} /> {t('fin.set_limit')}
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                          <span className="num text-[length:var(--fs-2xl)] font-medium tracking-[-0.03em]" style={{ color: budgetLeft < 0 ? 'var(--neg)' : 'inherit' }}>
                            {budgetLeft < 0 ? MINUS : ''}{fmt.money(Math.abs(budgetLeft))}
                          </span>
                          <span className="muted text-[length:var(--fs-md)]">{t(budgetLeft < 0 ? 'fin.over' : 'fin.left')} {t('fin.of', { m: money(totalBudget) })}</span>
                        </div>
                        {budgetItems.slice(0, 5).map((b) => (
                          <button
                            key={b.id || b.name}
                            type="button"
                            className="rule block w-full pb-3 pt-2 text-left"
                            title={t('fin.edit_limit')}
                            onClick={() => { setBudgetCat(b); setSheet('budget') }}
                          >
                            <div className="flex items-baseline justify-between gap-3">
                              <span className="trunc text-[length:var(--fs-base)]">{b.icon} {b.name}</span>
                              <span className="num shrink-0 text-[length:var(--fs-md)] text-[var(--ink-2)]">{fmt.nb(`${money(b.spent)} / ${money(b.budget)}`)}</span>
                            </div>
                            <div className="progress mt-2">
                              <div style={{ width: `${Math.min(100, Math.round((b.pct || 0) * 100))}%`, background: b.status === 'over' ? 'var(--neg)' : b.status === 'warn' ? 'var(--warn)' : 'var(--accent)' }} />
                            </div>
                          </button>
                        ))}
                        <div className="rule flex flex-wrap items-center justify-between gap-2 pt-3 text-[length:var(--fs-md)] text-[var(--ink-3)]">
                          <span>{t('fin.over_note', { n: budgetItems.filter((b) => b.status === 'over').length })}</span>
                          <button type="button" className="btn-soft btn-sm" onClick={() => { setTxCategory('all'); setTab('txs') }}>{t('fin.see_txs')}</button>
                        </div>
                      </>
                    )}
                  </section>
                )
              }

              /* Ближайшие платежи: строки с датой и суммой */
              return (
                <section key="upcoming" data-reveal className="relative">
                  {ctl}
                  <div className="hd flex-wrap">
                    <div className="min-w-0"><h2 className="trunc">{t('fin.c_upcoming')}</h2></div>
                    <small className="trunc">{t('fin.recurring_pays')}</small>
                  </div>
                  {!nextPayments.length ? (
                    <div className="muted py-3 text-[length:var(--fs-md)]">{t('fin.no_recurring')}</div>
                  ) : nextPayments.slice(0, 5).map((r) => (
                    <Rowi
                      key={r.id}
                      time={`${z(r.on.getDate())}.${z(r.on.getMonth() + 1)}`}
                      title={r.title || r.name}
                      sub={`${t('fin.in_n', { n: daysUntil(r.on) })}${r.category ? ` · ${r.category}` : ''}`}
                      right={<span className="amt">{MINUS}{fmt.money(r.amount)}</span>}
                    />
                  ))}
                  {nextPayments.length > 0 && (
                    <div className="rule flex flex-wrap items-center justify-between gap-2 pt-3 text-[length:var(--fs-md)] text-[var(--ink-3)]">
                      <span>{t('fin.last7')} {fmt.money(nextPayments.filter((r) => daysUntil(r.on) <= 7).reduce((s, r) => s + (r.amount || 0), 0))}</span>
                      <button type="button" className="btn-soft btn-sm" onClick={() => setTab('recurring')}>{t('fin.manage')}</button>
                    </div>
                  )}
                </section>
              )
            })}

            {cardsEdit && (
              <section className="c" data-reveal>
                <div className="hd flex-wrap">
                  <div className="min-w-0"><h2 className="trunc">{t('fin.cards_setup')}</h2></div>
                </div>
                <p className="muted text-[length:var(--fs-md)]">{t('fin.cards_setup_hint')}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {FIN_CARDS.filter((x) => !cardOrder.includes(x)).map((x) => (
                    <button key={x} className="btn-soft btn-sm" onClick={() => setCardOrder((o) => [...o, x])}>+ {t(FIN_CARD_LABELS[x])}</button>
                  ))}
                  <button className="btn-ghost btn-sm" onClick={resetCards}>{t('tk.restore_all')}</button>
                </div>
              </section>
            )}
          </div>
        </>
      )}

      {/* ---------------- ОПЕРАЦИИ ---------------- */}
      {tab === 'txs' && (
        <>
          <section className="c mt-4" data-reveal>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <label className="input flex min-w-[220px] flex-1 items-center gap-2.5">
                <Search size={16} className="faint shrink-0" aria-hidden="true" />
                <input
                  type="search"
                  aria-label={t('fin.search_ph')}
                  placeholder={t('fin.search_ph')}
                  value={txSearch}
                  onChange={(e) => setTxSearch(e.target.value)}
                  className="min-w-0 flex-1 bg-transparent outline-none"
                />
              </label>
              {/* импорт выписки Т-Банка: рядом с фильтрами и «выпиской» (CSV/PDF/XLSX, можно перетащить) */}
              <ImportButton
                onDone={(r) => {
                  if (r?.ok) { show(r.text || t('fin.import_added')); load(); bump() }
                  else show(r?.text || t('fin.import_bad'), 'err')
                }}
                onErr={show.err}
              />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <button type="button" className={`chip ${txCategory === 'all' ? 'on' : ''}`} aria-pressed={txCategory === 'all'} onClick={() => setTxCategory('all')}>
                {t('common.all')}
              </button>
              {categories.map((c) => (
                <button
                  type="button"
                  key={c.id || c.name}
                  className={`chip ${txCategory === (c.name || c) ? 'on' : ''}`}
                  aria-pressed={txCategory === (c.name || c)}
                  onClick={() => setTxCategory(c.name || c)}
                >
                  <span className="trunc">{c.name || c}</span>
                </button>
              ))}
            </div>
            <div className="rule mt-3 flex flex-wrap items-center gap-2 pt-3">
              <span className="label">{t('graph.one_account')}</span>
              <button type="button" className={`chip ${txAccount === 'all' ? 'on' : ''}`} aria-pressed={txAccount === 'all'} onClick={() => setTxAccount('all')}>{t('common.all')}</button>
              {accounts.map((a) => (
                <button key={a.id || a.name} type="button" className={`chip ${txAccount === a.name ? 'on' : ''}`} aria-pressed={txAccount === a.name} onClick={() => setTxAccount(a.name)}>
                  <span className="trunc">{a.name}</span>
                </button>
              ))}
              {(txCategory !== 'all' || txAccount !== 'all' || txSearch) && (
                <button type="button" className="btn-ghost btn-sm" onClick={() => { setTxCategory('all'); setTxAccount('all'); setTxSearch('') }}>{t('common.reset')}</button>
              )}
              <span className="num ml-auto text-[length:var(--fs-base)]">
                <b className="pos">+{fmt.money(filteredTxs.income)}</b>
                <span className="text-[var(--ink3)]"> / </span>
                <b>{MINUS}{fmt.money(filteredTxs.expense)}</b>
              </span>
            </div>
          </section>

          <Block
            className="mt-5"
            title={t('fin.tx_history')}
            note={`${t('mem.entries_n', { count: shownTxs.length })} · ${days ? t('fin.for_days_short', { n: days }) : t('fin.all_history')}`}
          >
            {!shownTxs.length ? (
              <div className="muted py-3 text-[length:var(--fs-md)]">{t('fin.no_txs_period')}</div>
            ) : shownTxs.map((tx) => (
              <div className="rowi" key={tx.id}>
                <time>{shortDate(tx.date || tx.created_at)}</time>
                <span className="t">
                  <span className="clamp-2 block">{tx.title || tx.note || tx.category || t('fin.tx')}</span>
                  <small>{[tx.category, tx.account, tx.comment].filter(Boolean).join(' · ')}</small>
                </span>
                {/* знак берём из kind: amount приходит из API положительным */}
                <span className="amt" style={{ color: tx.kind === 'income' ? 'var(--pos)' : 'inherit' }}>
                  {tx.kind === 'income' ? '+' : tx.kind === 'expense' ? MINUS : ''}{money(tx.amount)}
                </span>
                <RowActions>
                  <IconBtn onClick={() => { setEditingItem(tx); setSheet('tx') }} title={t('common.edit')}>
                    <Edit2 size={14} />
                  </IconBtn>
                  <IconBtn
                    danger
                    title={t('common.delete_title')}
                    onClick={() => setAsk({
                      title: t('fin.del_tx_q'),
                      text: t('fin.del_tx_text'),
                      msg: t('fin.tx_deleted'),
                      run: () => api.delTx(tx.id),
                    })}
                  >
                    <Trash2 size={14} />
                  </IconBtn>
                </RowActions>
              </div>
            ))}
          </Block>
        </>
      )}

      {/* ---------------- СЧЕТА ---------------- */}
      {tab === 'accounts' && (
        <Block className="mt-5" title={t('fin.tab_accounts')} note={t('fin.n_accounts', { count: accounts.length })}>
          {!accounts.length ? (
            <Empty glyph="money" text={t('fin.no_accounts')} sub={t('fin.no_accounts_hint')}
              action={<button type="button" className="btn" onClick={() => { setEditingItem(null); setSheet('account') }}><Plus size={15} /> {t('fin.add_account')}</button>} />
          ) : accounts.map((a) => {
            const atype = a.type || a.kind || 'bank'
            const Icon = atype === 'card' ? CreditCard : atype === 'cash' ? Wallet : atype === 'crypto' ? PiggyBank : Landmark
            const kindLabel = ({ card: t('acc.card'), cash: t('acc.cash2'), bank: t('graph.one_account'), savings: t('acc.deposit'), crypto: t('acc.crypto') })[atype] || t('graph.one_account')
            return (
              <div className="rowi" key={a.id || a.name}>
                <span className="w-9 shrink-0 text-[var(--ink-3)]" aria-hidden="true"><Icon size={17} /></span>
                <span className="t">
                  <span className="clamp-2 block">{a.name}</span>
                  <small>{a.comment || kindLabel} · {a.currency || 'RUB'}</small>
                </span>
                <span className="amt num" style={{ fontSize: 'var(--fs-lg)' }}>{fmt.money(a.balance || 0)}</span>
                <RowActions>
                  <IconBtn onClick={() => { setEditingItem(a); setSheet('account') }} title={t('common.edit')}><Edit2 size={14} /></IconBtn>
                  <IconBtn
                    danger
                    title={t('fin.del_acc_q')}
                    onClick={() => setAsk({
                      title: t('fin.del_acc_q_name', { name: a.name }),
                      text: t('fin.del_acc_text'),
                      msg: t('fin.acc_deleted'),
                      run: () => api.delAccount(a.id),
                    })}
                  >
                    <Trash2 size={14} />
                  </IconBtn>
                </RowActions>
              </div>
            )
          })}
        </Block>
      )}

      {/* ---------------- ДОЛГИ ---------------- */}
      {tab === 'debts' && (
        <>
          <section className="c hero mt-4" data-reveal>
            <div className="hd flex-wrap">
              <div className="min-w-0"><h2 className="trunc">{t('fin.total_debt')}</h2></div>
            </div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
              <BigMoney value={debtsTotal} format={fmt.int} label={money(debtsTotal)} />
              <span className="tag" style={{ marginTop: 0 }}>{t('fin.n_active_debt', { count: debts.length })}</span>
            </div>
          </section>

          <Block className="mt-5" title={t('fin.tab_debts')} note={t('fin.n_debts', { count: debts.length })}>
            {!debts.length ? (
              <Empty glyph="debt" text={t('td.clean')} sub={t('td.nothing_missed')}
                action={<button type="button" className="btn" onClick={() => { setEditingItem(null); setSheet('debt') }}><Plus size={15} /> {t('fin.add_debt')}</button>} />
            ) : debts.map((d) => {
              const total = d.total || 1
              const paid = d.paid || 0
              const left = Math.max(0, total - paid)
              const pct = Math.min(100, Math.round((paid / total) * 100))
              return (
                <div key={d.id} className="rule py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                    <div className="min-w-0 flex-1">
                      <div className="clamp-2 text-[length:var(--fs-base)] font-medium">{d.name || d.title}</div>
                      <div className="muted mt-0.5 text-[length:var(--fs-md)]">
                        {t('fin.paid_out')} {fmt.money(paid)} ({fmt.int(pct)} %) · {t('fin.of')} {fmt.money(total)}
                      </div>
                    </div>
                    <span className="num shrink-0 text-[length:var(--fs-lg)] font-medium">{fmt.money(left)}</span>
                  </div>
                  <div className="progress mt-2"><div style={{ width: `${pct}%` }} /></div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="muted trunc text-[length:var(--fs-xs)]">{d.creditor || t('fin.creditor')}</span>
                    <RowActions>
                      <button type="button" className="btn-soft btn-sm" onClick={() => { setEditingItem(d); setSheet('payDebt') }}>{t('fin.make_payment')}</button>
                      <IconBtn onClick={() => { setEditingItem(d); setSheet('debt') }} title={t('common.edit')}><Edit2 size={14} /></IconBtn>
                      <IconBtn
                        danger
                        title={t('common.delete_title')}
                        onClick={() => setAsk({
                          title: t('fin.del_debt_q_name', { name: d.name || d.title }),
                          text: t('fin.del_debt_text'),
                          msg: t('fin.debt_deleted'),
                          run: () => api.delDebt(d.id),
                        })}
                      >
                        <Trash2 size={14} />
                      </IconBtn>
                    </RowActions>
                  </div>
                </div>
              )
            })}
          </Block>
        </>
      )}

      {/* ---------------- РЕГУЛЯРНЫЕ ---------------- */}
      {tab === 'recurring' && (
        <Block
          className="mt-5"
          title={t('fin.c_recurring')}
          note={`${fmt.money(recExpense)}${recIncome > 0 ? ` · +${fmt.money(recIncome)}` : ''}`}
          action={recPaused.length > 0 ? (
            <button type="button" className="btn-soft btn-sm" onClick={() => setShowPaused((v) => !v)} title={t('fin.paused_hint')}>
              {showPaused ? t('fin.hide_paused') : t('fin.show_paused_n', { n: recPaused.length })}
            </button>
          ) : null}
        >
          {recShown.length === 0 ? (
            <div className="muted py-3 text-[length:var(--fs-md)]">{recurring.length > 0 ? t('fin.all_paused') : t('fin.no_recurring')}</div>
          ) : recShown.map((r) => (
            <div className="rowi" key={r.id}>
              <time>{(r.day_of_month || r.day) ? t('fin.day_of_month', { d: r.day_of_month || r.day }) : t('fin.per_month_short')}</time>
              <span className="t">
                <span className="clamp-2 block">{r.name || r.title}</span>
                <small>{[r.category, r.account].filter(Boolean).join(' · ') || (r.kind === 'income' ? t('fin.inflow') : t('fin.outflow'))}</small>
              </span>
              <span className="amt" style={{ color: r.kind === 'income' ? 'var(--pos)' : 'inherit' }}>
                {r.kind === 'income' ? '+' : MINUS}{fmt.money(r.amount)}
              </span>
              <RowActions>
                <IconBtn
                  title={r.active === false ? 'Включить: платёж снова пойдёт в прогноз' : t('fin.pause_tip')}
                  onClick={() => toggleActive(r)}
                >
                  {r.active === false ? <Play size={14} /> : <Pause size={14} />}
                </IconBtn>
                <IconBtn onClick={() => { setEditingItem(r); setSheet('recurring') }} title={t('fin.edit_pay')}><Edit2 size={14} /></IconBtn>
                <IconBtn
                  danger
                  title={t('fin.remove_pay')}
                  onClick={() => setAsk({
                    title: t('fin.del_rec_q_name', { name: r.name || r.title }),
                    text: t('fin.pause_note'),
                    msg: t('fin.paused'),
                    run: () => api.delRecurring(r.id),
                  })}
                >
                  <Trash2 size={14} />
                </IconBtn>
              </RowActions>
            </div>
          ))}
          {recPaused.length > 0 && (
            <div className="rule pt-3 text-[length:var(--fs-md)] text-[var(--ink-3)]">
              {t('fin.paused_n', { count: recPaused.length })}
            </div>
          )}
        </Block>
      )}

      {/* ---------------- ЦЕЛИ ---------------- */}
      {tab === 'goals' && (
        <Block className="mt-5" title={t('goals.title')} note={t('fin.n_goals', { count: goals.length })}>
          {!goals.length ? (
            <Empty glyph="mind" text={t('fin.no_goals')} sub={t('fin.no_goals_hint')}
              action={<button type="button" className="btn" onClick={() => { setEditingItem(null); setSheet('goal') }}><Target size={15} /> {t('gl.goal')}</button>} />
          ) : goals.map((g) => {
            const current = g.current || 0
            const target = g.target || 1
            const pct = Math.min(100, Math.round((current / target) * 100))
            const eta = target > current ? goalEta(target - current) : null
            return (
              <div key={g.id} className="rule py-3">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <div className="min-w-0 flex-1">
                    <div className="clamp-2 text-[length:var(--fs-base)] font-medium">{g.title || g.name}</div>
                    <div className="muted mt-0.5 text-[length:var(--fs-md)]">
                      {t('fin.saved_pct', { pct })}{g.deadline ? ` · ${shortDate(g.deadline)}` : ''}
                    </div>
                  </div>
                  <span className="num shrink-0 text-[length:var(--fs-lg)] font-medium">
                    {fmt.money(current)} <span className="text-[length:var(--fs-md)] text-[var(--ink3)]">/ {fmt.money(target)}</span>
                  </span>
                </div>
                <div className="progress mt-2"><div style={{ width: `${Math.max(2, pct)}%` }} /></div>
                {eta && (
                  <div className="mt-1.5 text-[length:var(--fs-xs)] text-[var(--ink-3)]">{t('gl.at_rate', { m: money(5000) })} {eta}</div>
                )}
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <span className="muted trunc text-[length:var(--fs-xs)]">{g.deadline ? shortDate(g.deadline) : t('fin.forever')}</span>
                  <RowActions>
                    <button type="button" className="btn btn-sm" onClick={() => { setEditingItem(g); setSheet('putGoal') }}>{t('fin.top_up')}</button>
                    <IconBtn onClick={() => { setEditingItem(g); setSheet('goal') }} title={t('common.edit')}><Edit2 size={14} /></IconBtn>
                    <IconBtn
                      danger
                      title={t('common.delete_title')}
                      onClick={() => setAsk({
                        title: t('fin.del_goal_q_name', { name: g.title || g.name }),
                        text: t('gl.del_text2'),
                        msg: t('gl.deleted'),
                        run: () => api.delGoal(g.id),
                      })}
                    >
                      <Trash2 size={14} />
                    </IconBtn>
                  </RowActions>
                </div>
              </div>
            )
          })}
        </Block>
      )}

      {/* ---------------- ТЕХНИКИ ---------------- */}
      {tab === 'techniques' && (
        <section className="c mt-4" data-reveal>
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
    <Sheet open={open} onClose={onClose} title={isNew ? t('fin.add_tx') : t('fin.edit_tx')}>
      <form onSubmit={submit} className="space-y-4">
        <div className="seg">
          <button type="button" className={kind === 'expense' ? 'on' : ''} aria-pressed={kind === 'expense'} onClick={() => setKind('expense')}>{t('fin.expense')}</button>
          <button type="button" className={kind === 'income' ? 'on' : ''} aria-pressed={kind === 'income'} onClick={() => setKind('income')}>{t('fin.income')}</button>
        </div>
        <Field label={t('fin.amount_rub')} error={amountErr}>
          <Money value={amount} onChange={setAmount} min={0} placeholder="1000" autoFocus required />
        </Field>
        <Field label={t('fin.description')}>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('fin.desc_ph')} />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
    <Sheet open={open} onClose={onClose} title={isNew ? t('fin.add_account') : t('fin.edit_account')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('acc.name')}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('acc.name_ph')} />
        </Field>
        <Field label={t('acc.current_balance')}>
          <Money value={balance} onChange={setBalance} placeholder="0" />
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
    <Sheet open={open} onClose={onClose} title={isNew ? t('fin.add_debt') : t('fin.edit_debt')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('common.title')}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('fin.debt_ph')} />
        </Field>
        <Field label={t('fin.creditor2')}>
          <input className="input" value={creditor} onChange={(e) => setCreditor(e.target.value)} placeholder={t('fin.creditor_ph')} />
        </Field>
        <Field label={t('fin.total_amount')}>
          <Money value={total} onChange={setTotal} min={0} placeholder="50000" required />
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
          <Money value={amount} onChange={setAmount} min={0} placeholder="5000" autoFocus required />
        </Field>
        <Field label={t('fin.charge')} error={accErr} hint={t('fin.charge_hint')}>
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
    <Sheet open={open} onClose={onClose} title={isNew ? t('fin.add_pay') : t('fin.edit_pay2')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('fin.kind')} hint={t('fin.outflow_hint')}>
          <div className="seg">
            <button type="button" className={!isIncome ? 'on' : ''} aria-pressed={!isIncome} onClick={() => setKind('expense')}>{t('fin.outflow')}</button>
            <button type="button" className={isIncome ? 'on' : ''} aria-pressed={isIncome} onClick={() => setKind('income')}>{t('fin.income')}</button>
          </div>
        </Field>
        <Field label={t('common.title')}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('fin.pay_ph2')} />
        </Field>
        <Field label={t('fin.amount_month')}>
          <Money value={amount} onChange={setAmount} min={0} placeholder="499" required />
        </Field>
        <Field label={t('fin.pay_day')}>
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
    <Sheet open={open} onClose={onClose} title={isNew ? t('fin.add_goal') : t('fin.edit_goal')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('gl.goal_name')}>
          <input className="input" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('gl.goal_ph2')} />
        </Field>
        <Field label={t('gl.target')}>
          <Money value={target} onChange={setTarget} min={1} placeholder="100000" required />
        </Field>
        <Field label={t('gl.saved')}>
          <Money value={current} onChange={setCurrent} min={0} placeholder="0" />
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
          <Money value={amount} onChange={setAmount} min={0} placeholder="2000" autoFocus required />
        </Field>
        <Field label={t('fin.charge')} hint={t('fin.top_hint')}>
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

/* Месячный лимит категории: хранится в Category.budget, раздел «лимиты» читает его
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