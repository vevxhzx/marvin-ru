import { useEffect, useRef, useState, useMemo } from 'react'
import { api, money, hhmm, shortDate, relTime, WD_SHORT_MON as WD_SHORT } from '../lib/api'
import { Num, useToast, PageAccent, Skeleton, Empty } from '../components/ui'
import { useRefresh } from '../App'
import TaskSheet from '../components/TaskSheet'
import { EventSheet } from './Calendar'
import { usePrefs, usePageAccent } from '../lib/prefs'
import { Sheet } from '../components/ui'
import { ArrowLeft, EyeOff, Plus, RotateCcw, Check, Sparkles, Square, Play } from 'lucide-react'
import { useCardLayout, CardCtl, useWide } from '../lib/layout'
import { useTimer, mmss } from './Orders'

import { TodaySummaryWidget, ScreenTimeBentoWidget } from '../components/ReportCards'
// новые карточки главной: быстрое дело, лимит трат, цели, привычки, ближайшее дело
import { QuickAddWidget, SpendTodayWidget, GoalsWidget, HabitsWidget, NextUpWidget } from '../components/TodayCards'
import CashChart from '../components/CashChart'
import { TipBars } from '../components/ChartTip'
import { useNavigate } from 'react-router-dom'
import { useI18n, localeOf, t as T } from '../lib/i18n'

const GREETS = { morning: 'td.greet_morning', day: 'td.greet_day', evening: 'td.greet_evening', night: 'td.greet_night' }
const part = (h) => (h < 5 ? 'night' : h < 12 ? 'morning' : h < 18 ? 'day' : 'evening')

/* Подсказки уходят в ядро — остаются на русском в обоих режимах (i18n-raw) */
const SUGGESTIONS = ['700 такси', 'встреча в среду в 15 с Димой', 'мозг: идея для ролика', 'куда ушли деньги', 'напомни через 20 минут'] // i18n-raw

const ALL_WIDGET_DEFS = {
  summary: { id: 'summary', name: 'td.w_summary', desc: 'td.d_summary', defaultCol: 's8' },
  screen: { id: 'screen', name: 'td.w_screen', desc: 'td.d_screen', defaultCol: 's4' },
  balance: { id: 'balance', name: 'td.w_balance', desc: 'td.d_balance', defaultCol: 's4' },
  chart: { id: 'chart', name: 'td.w_chart', desc: 'td.d_chart', defaultCol: 's8' },
  expenses: { id: 'expenses', name: 'td.w_expenses', desc: 'td.d_expenses', defaultCol: 's4' },
  free: { id: 'free', name: 'td.w_free', desc: 'td.d_free', defaultCol: 's4' },
  debts: { id: 'debts', name: 'td.w_debts', desc: 'td.d_debts', defaultCol: 's4' },
  today: { id: 'today', name: 'td.w_today', desc: 'td.d_today', defaultCol: 's4' },
  calendar: { id: 'calendar', name: 'td.w_calendar', desc: 'td.d_calendar', defaultCol: 's4' },
  brain: { id: 'brain', name: 'td.w_brain', desc: 'td.d_brain', defaultCol: 's4' },
  pomo: { id: 'pomo', name: 'td.w_pomo', desc: 'td.d_pomo', defaultCol: 's4' },
  orders: { id: 'orders', name: 'td.w_orders', desc: 'td.d_orders', defaultCol: 's8' },
  missed: { id: 'missed', name: 'td.w_missed', desc: 'td.d_missed', defaultCol: 's8' },
  // новые карточки — по умолчанию спрятаны (как pomo/orders/missed), включаются кнопкой «добавить карточку»
  quick: { id: 'quick', name: 'td.w_quick', desc: 'td.d_quick', defaultCol: 's4' },
  spend: { id: 'spend', name: 'td.w_spend', desc: 'td.d_spend', defaultCol: 's4' },
  goals: { id: 'goals', name: 'td.w_goals', desc: 'td.d_goals', defaultCol: 's4' },
  habits: { id: 'habits', name: 'td.w_habits', desc: 'td.d_habits', defaultCol: 's4' },
  next: { id: 'next', name: 'td.w_next', desc: 'td.d_next', defaultCol: 's4' },
}

const DEFAULT_ORDER = ['summary', 'screen', 'balance', 'chart', 'expenses', 'free', 'debts', 'today', 'calendar', 'brain']
const DEFAULT_WIDTHS = { summary: 8, screen: 4, balance: 4, chart: 8, expenses: 4, free: 4, debts: 4, today: 4, calendar: 4, brain: 4, pomo: 4, orders: 8, missed: 8, quick: 4, spend: 4, goals: 4, habits: 4, next: 4 }

// Вселенная карточек — все известные виджеты: иначе добавленная карточка (pomo/orders/missed
// и новые) после перезагрузки отфильтровывалась бы из сохранённой раскладки.
const ALL_WIDGET_IDS = Object.keys(ALL_WIDGET_DEFS)

// Первый заход: фиксируем прежний набор карточек как стартовую раскладку, чтобы новые/редкие
// виджеты не появлялись сами. Дальше раскладку ведёт lib/layout в localStorage.
try {
  const LAYOUT_KEY = 'marvin.layout.today'
  if (typeof localStorage !== 'undefined' && !localStorage.getItem(LAYOUT_KEY)) {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({ order: [...DEFAULT_ORDER], widths: { ...DEFAULT_WIDTHS } }))
  }
} catch {}

export default function Today({ openChat, address = '' }) {
  const { t } = useI18n()
  const nav = useNavigate()
  const [d, setD] = useState(null)
  const [fin, setFin] = useState(null)
  const [fc, setFc] = useState(null)
  const [screenData, setScreenData] = useState(null)
  const [missed, setMissed] = useState(null)
  // данные главной загружены (хоть бы попытка была): карточки рисуют Skeleton, а не выдуманные суммы
  const [loaded, setLoaded] = useState(false)
  const { tick, bump } = useRefresh()
  const [prefs, setPrefs] = usePrefs()
  const [, show] = useToast()
  const { t: timer, left: pomoLeft, reload: reloadTimer } = useTimer()

  // Режим настройки главной: порядок и ширина карточек
  const [editMode, setEditMode] = useState(false)
  const { order: widgetOrder, setOrder: setWidgetOrder, widths: widgetWidths, move, drop: dropWidget, cycleWidth } = useCardLayout('today', ALL_WIDGET_IDS, DEFAULT_WIDTHS)
  const wide = useWide()
  const pageAcc = usePageAccent('today')
  const [addSheetOpen, setAddSheetOpen] = useState(false)
  const [draggedWidget, setDraggedWidget] = useState(null)

  const removeWidget = (id) => setWidgetOrder((o) => o.filter((w) => w !== id))

  const addWidget = (id) => {
    if (!widgetOrder.includes(id)) setWidgetOrder((o) => [...o, id])
    setAddSheetOpen(false)
  }

  const moveWidget = (id, direction) => move(id, direction)

  const resetWidgets = () => setWidgetOrder([...DEFAULT_ORDER])

  const load = () => {
    Promise.all([
      api.dashboard().catch(() => null),
      api.finSummary(30).catch(() => null),
      api.finForecast(30).catch(() => null),
      api.get('/api/screen?days=1').catch(() => null),
      api.missed().catch(() => null),
    ]).then(([dash, f, fe, sc, ms]) => {
      if (dash) setD(dash)
      if (f) setFin(f)
      if (fe) setFc(fe)
      if (sc) setScreenData(sc)
      if (ms) setMissed(ms)
    }).finally(() => setLoaded(true))
  }

  useEffect(() => { load() }, [tick])

  const now = new Date()
  const greeting = t(GREETS[part(now.getHours())])
  const ownerName = prefs.address || address || t('common.sir')
  const daySubtitle = now.toLocaleDateString(localeOf(), { weekday: 'long', day: 'numeric', month: 'long' })

  // Печатающийся плейсхолдер
  const [typed, setTyped] = useState('')
  const [inputVal, setInputVal] = useState('')
  const [isTypingManual, setIsTypingManual] = useState(false)

  useEffect(() => {
    if (isTypingManual) return
    let a = 0, c = 0, del = false
    let timeoutId
    function tickPh() {
      const w = SUGGESTIONS[a]
      if (!del) {
        c++
        setTyped(w.slice(0, c))
        if (c === w.length) {
          del = true
          timeoutId = setTimeout(tickPh, 1800)
          return
        }
        timeoutId = setTimeout(tickPh, 55)
        return
      }
      c -= 2
      if (c <= 0) {
        c = 0
        del = false
        a = (a + 1) % SUGGESTIONS.length
        setTyped('')
        timeoutId = setTimeout(tickPh, 350)
        return
      }
      setTyped(w.slice(0, c))
      timeoutId = setTimeout(tickPh, 22)
    }
    timeoutId = setTimeout(tickPh, 400)
    return () => clearTimeout(timeoutId)
  }, [isTypingManual])

  const handleSend = () => {
    const text = inputVal.trim() || typed
    if (!text) return
    window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text, send: true } }))
    setInputVal('')
    setIsTypingManual(false)
  }

  // Данные для карточки баланса
  const balance = d?.finance?.total_balance ?? d?.finance?.balance ?? 0
  const daysLeft = Math.min(30, Math.max(1, Math.round(d?.finance?.runway_days ?? 0)))
  const avgDaily = d?.finance?.avg_daily ?? 0
  // Прогноз на конец периода берём у сервера (реальные операции + регулярные платежи)
  const fcLast = fc?.points?.filter((p) => p.kind === 'future').slice(-1)[0]
  const forecastBalance = fcLast ? fcLast.balance : balance - avgDaily * 30

  // График кассы рисует CashChart (тот же, что в «финансах»): точка = баланс на конец дня,
  // подсказка в две подписанные строки, «сегодня» — последняя точка факта

  const startD = new Date(now)
  const endD = new Date(now)
  endD.setDate(endD.getDate() + 30)
  const z = (n) => ('0' + n).slice(-2)
  const startStr = `${z(startD.getDate())}.${z(startD.getMonth() + 1)}`
  const endStr = `${z(endD.getDate())}.${z(endD.getMonth() + 1)}`

  // Траты 30 дней и столбики по дням недели — сервер считает из реальных операций
  const expenses30 = fin?.spent || d?.finance?.expense_month || 0
  // высоты столбиков считает сам TipBars (components/ChartTip.jsx) — вместе с подсказкой

  // Свободно в месяц
  // cashflow приходит объектом { income, recurring, debt_payments, free } — берём свободные,
  // а не сам объект (иначе показывалось 0 ₽)
  const cf = d?.finance?.cashflow
  const freeMonth = Math.max(0, typeof cf === 'number' ? cf : cf?.free || 0)

  // Долги
  const debtTotal = (d?.debts || []).reduce((acc, x) => acc + (x.total - (x.paid || 0)), 0)
  const totalOrigDebts = (d?.debts || []).reduce((acc, x) => acc + (x.total || 0), 0) || debtTotal
  const debtClosedPct = totalOrigDebts > 0 ? Math.round(((totalOrigDebts - debtTotal) / totalOrigDebts) * 100) : 0
  const closedSegments = Math.round((debtClosedPct / 100) * 16)

  // Сегодня события
  const todayEvents = (d?.today || []).slice(0, 3)

  // Календарь: точки на днях, где реально есть что-то (события недели с главной + сроки задач).
  // Данные приходят с дашбордом — отдельных запросов не делаем; за пределами окна недели точек нет.
  const dayMarks = useMemo(() => {
    const key = (s) => {
      if (!s) return null
      const x = new Date(s)
      if (Number.isNaN(+x)) return null
      return `${x.getFullYear()}-${x.getMonth() + 1}-${x.getDate()}`
    }
    const ev = new Set(); const tk = new Set()
    for (const e of [...(d?.week || []), ...(d?.today || [])]) { const k = key(e?.start); if (k) ev.add(k) }
    for (const t of d?.tasks || []) { const k = key(t?.due); if (k) tk.add(k) }
    return { ev, tk }
  }, [d])

  const calCells = useMemo(() => {
    const curYear = now.getFullYear()
    const curMonth = now.getMonth()
    const firstDay = new Date(curYear, curMonth, 1)
    const offset = (firstDay.getDay() + 6) % 7
    const daysInMonth = new Date(curYear, curMonth + 1, 0).getDate()
    const daysInPrev = new Date(curYear, curMonth, 0).getDate()
    const cells = []
    for (let i = 0; i < 35; i++) {
      const dayIdx = i - offset + 1
      const isOut = dayIdx < 1 || dayIdx > daysInMonth
      const num = dayIdx < 1 ? daysInPrev + dayIdx : dayIdx > daysInMonth ? dayIdx - daysInMonth : dayIdx
      const isToday = !isOut && num === now.getDate()
      const mk = `${curYear}-${curMonth + 1}-${num}`
      const hasEvents = !isOut && (dayMarks.ev.has(mk) || dayMarks.tk.has(mk))
      // жёлтая точка — срок задачи, тёмная — событие
      const dotType = !isOut && dayMarks.tk.has(mk) && !dayMarks.ev.has(mk) ? 'y' : 'd'
      cells.push({ num, isOut, isToday, hasEvents, dotType, key: i })
    }
    return cells
  }, [now.getMonth(), now.getFullYear(), now.getDate(), dayMarks])

  // Мозг записи: подпись — реальный вид записи и её возраст, а не заложенное «сегодня»
  const KIND_RU = { note: 'graph.one_note', link: 'graph.one_link', task: 'graph.one_task', event: 'graph.one_event', finance: 'rc.money', chat: 'mem.k_chat', system: 'mem.k_system' }
  const recentNotes = (d?.memory || []).slice(0, 3).map((n) => ({
    id: n.id,
    title: n.text ? n.text.slice(0, 40) : t('common.notes'),
    type: KIND_RU[n.kind] ? t(KIND_RU[n.kind]) : (n.kind || t('mem.entries_n', { count: 1 })),
    date: n.created_at ? relTime(n.created_at) : '',
  }))

  // Диалоги правки
  const [editTask, setEditTask] = useState(null)
  const [editEvent, setEditEvent] = useState(null)

  // Drag and Drop handlers
  const handleDragStart = (e, id) => {
    if (!editMode) return
    setDraggedWidget(id)
    e.dataTransfer.setData('text/plain', id)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e) => {
    if (!editMode) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDrop = (e, targetId) => {
    if (!editMode || !draggedWidget || draggedWidget === targetId) return
    e.preventDefault()
    dropWidget(draggedWidget, targetId)
    setDraggedWidget(null)
  }

  // Рендер элементов управления карточки в режиме правки
  const renderCardControls = (widgetId) => (
    <CardCtl id={widgetId} order={widgetOrder} edit={editMode} wide={wide}
      onMove={moveWidget} onHide={removeWidget} onWidth={cycleWidth}
      width={widgetWidths[widgetId] || DEFAULT_WIDTHS[widgetId] || 4}
      Icon={ArrowLeft} HideIcon={EyeOff} />
  )

  // Генератор виджетов
  const renderWidget = (id, idx) => {
    const isWig = editMode ? 'wig' : ''
    // ширина задаётся инлайном (перебивает класс s4/s8), но только на широком экране —
    // на планшете и телефоне карточки по-прежнему подстраиваются под экран
    const animStyle = { '--i': 4 + idx, ...(wide ? { gridColumn: `span ${widgetWidths[id] || DEFAULT_WIDTHS[id] || 4}` } : {}) }
    const dragProps = editMode ? {
      draggable: true,
      onDragStart: (e) => handleDragStart(e, id),
      onDragOver: handleDragOver,
      onDrop: (e) => handleDrop(e, id),
    } : {}

    switch (id) {
      case 'summary':
        return (
          <section key="summary" className={`c s8 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('summary', idx)}
            {!d ? (
              // сводка не выдумывает траты: пока данных нет — скелет, если запрос упал — честное «нет данных»
              loaded
                ? <Empty compact glyph="money" text={t('td.no_summary')} sub={t('td.no_summary_hint')} />
                : <Skeleton h={172} />
            ) : (
              <TodaySummaryWidget
                data={{
                  tasks: d.tasks || [],
                  events: todayEvents || [],
                  balance: balance,
                  // поле есть в finance.summary() — ноль означает «сегодня не тратили», а не «нет данных»
                  spentToday: d.finance?.spent_today ?? 0,
                  dailyBudget: Math.round(balance / Math.max(1, daysLeft)),
                }}
                onOpenTasks={() => nav('/tasks')}
                onOpenCalendar={() => nav('/calendar')}
                onOpenFinance={() => nav('/finance')}
              />
            )}
          </section>
        )

      case 'screen':
        return (
          <section key="screen" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('screen', idx)}
            <ScreenTimeBentoWidget data={screenData} />
          </section>
        )

      case 'missed': {
        const m = missed || {}
        const rows = [
          ...(m.unpaid || []).map((o) => ({ k: 'unpaid', t: o.title, s: o.client || '', v: money(o.left) })),
          ...(m.overdue_debts || []).map((d) => ({ k: 'debt', t: d.title, s: t('td.pay_on', { d: d.pay_day }), v: money(d.payment) })),
          ...(m.tasks_no_due || []).map((x) => ({ k: 'task', t: x.title, s: t('task.when_none'), v: '' })),
          ...(m.goals_stale || []).map((g) => ({ k: 'goal', t: g.title, s: `${g.pct}%`, v: g.left ? money(g.left) : '' })),
        ]
        return (
          <section key="missed" className={`c s8 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('missed', idx)}
            <div className="hd"><h2>{t('td.w_missed')}</h2><small>{rows.length ? t('td.items_n', { n: rows.length }) : t('td.clean')}</small></div>
            {!missed ? (
              <div className="muted py-3 text-[13px]">{t('common.loading')}</div>
            ) : rows.length === 0 ? (
              <div className="muted py-3 text-[13.5px]">{t('td.nothing_missed')}</div>
            ) : (
              <div className="mt-1 space-y-1.5">
                {rows.slice(0, 8).map((r, i) => (
                  <div key={i} className="flex items-center gap-3 rounded-xl px-3 py-2" style={{ background: 'var(--sf2)' }}>
                    <span className="flex-1 truncate text-[13.5px] font-medium">{r.t}</span>
                    {r.s && <span className="faint shrink-0 text-[12px]">{r.s}</span>}
                    {r.v && <span className="shrink-0 text-[13.5px] font-semibold" style={{ color: (r.k === 'debt' || r.k === 'unpaid') ? 'var(--neg)' : 'var(--ink2)' }}>{r.v}</span>}
                  </div>
                ))}
              </div>
            )}
          </section>
        )
      }

      case 'balance':
        return (
          <section key="balance" className={`c hero s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('balance', idx)}
            <div className="hd"><h2>{t('td.w_balance')}</h2><small>{t('td.lasts_for')}</small></div>
            <div className="big"><Num value={balance} /> ₽</div>
            <span className="tag">{t('td.days_of_30', { count: daysLeft })}</span>
            <div className="days" id="days">
              {Array.from({ length: 30 }, (_, i) => (
                <i key={i} className={i < daysLeft ? 'on' : ''} style={{ '--k': i }} />
              ))}
            </div>
            <div className="dl mono"><span>{startStr}</span><span>{endStr}</span></div>
            <div className="hm">
              <div><small>{t('td.avg_day')}</small><b>{money(avgDaily)}</b></div>
              <div><small>{t('aims.by', { date: endStr })}</small><b>{forecastBalance < 0 ? '−' : ''}{money(Math.abs(forecastBalance))}</b></div>
            </div>
          </section>
        )

      case 'chart':
        return (
          <section key="chart" className={`c chart s8 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('chart', idx)}
            <div className="hd"><h2>{t('td.w_chart')}</h2><small>{fc ? t('td.chart_now', { bal: money(fc.balance), pace: money(fc.avg_day_spent) }) : t('fc.by_pace')}</small></div>
            {fc
              ? <CashChart f={fc} height={200} legend={false} />
              : <div className="cw" id="cw"><div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', opacity: 0.6 }}>{t('common.loading')}</div></div>}
            <div className="lg">
              <span><i style={{ background: '#ff9f5c' }}></i>{t('chart.fact')}</span>
              <span><i style={{ background: 'var(--accent)' }}></i>{t('chart.forecast')}</span>
              <span><i style={{ border: '1.5px dashed var(--ink3)', background: 'none' }}></i>{t('chart.zero')}</span>
              {fc?.runway_days != null && <span className="text-[var(--neg)]">{t('td.to_zero', { n: fc.runway_days })}</span>}
              {fc?.min_balance != null && fc.min_balance >= 0 && fc.min_date && (
                <span>{t('fc.min', { m: money(fc.min_balance) })} · {z(Number(fc.min_date.slice(8, 10)))}.{fc.min_date.slice(5, 7)}</span>
              )}
            </div>
          </section>
        )

      case 'expenses':
        return (
          <section key="expenses" className={`c p1 s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('expenses', idx)}
            <div className="hd"><h2>{t('td.w_expenses')}</h2><small>{t('td.d30')}</small></div>
            <div className="mid"><Num value={expenses30} /> ₽</div>
            {/* столбики по дням недели: подсказка — сколько потрачено в этот день недели */}
            {/* сервер отдаёт weekday[0] = понедельник, а WD_SHORT_MON начинается с воскресенья, поэтому подписи сдвигаем на день */}
            <TipBars kind="weekday" values={d?.finance?.weekday} labels={WD_SHORT.slice(1).concat(WD_SHORT[0])} />
          </section>
        )

      case 'free':
        return (
          <section key="free" className={`c p2 s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('free', idx)}
            <div className="hd"><h2>{t('td.w_free')}</h2><small>{t('td.per_month')}</small></div>
            <div className="mid"><Num value={freeMonth} /> ₽</div>
            {/* столбики по пятидневкам месяца: подсказка — сумма и доля трат месяца */}
            <TipBars kind="month" values={d?.finance?.month_days} labels={['1', '5', '10', '15', '20', '25', '30']} />
          </section>
        )

      case 'debts':
        return (
          <section key="debts" className={`c blk s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('debts', idx)}
            <div className="hd"><h2>{t('td.w_debts')}</h2><small>{t('common.total')}</small></div>
            <div className="mid"><Num value={debtTotal} /> ₽</div>
            <div className="seg" id="seg">
              {Array.from({ length: 16 }, (_, i) => (
                <i key={i} className={i < closedSegments ? 'on' : ''} style={{ '--k': i }} />
              ))}
            </div>
            <div className="cap mono">{t('td.closed_pct', { pct: debtClosedPct })}</div>
          </section>
        )

      case 'today':
        return (
          <section key="today" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('today', idx)}
            <div className="hd">
              <h2>{t('common.today')}</h2>
              <small>{t('cal.events_n', { count: todayEvents.length })}</small>
            </div>
            {todayEvents.length === 0 ? (
              <div className="py-4 text-center text-sm" style={{ color: 'var(--ink3)' }}>{t('td.no_events_today')}</div>
            ) : (
              todayEvents.map((e, eidx) => (
                <div className="rowi" key={e.id || eidx} onClick={() => setEditEvent(e)} style={{ cursor: 'pointer' }}>
                  <time>{hhmm(e.start || now)}</time>
                  <span className="t">{e.title}</span>
                </div>
              ))
            )}
          </section>
        )

      case 'calendar':
        return (
          <section key="calendar" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('calendar', idx)}
            <div className="hd"><h2>{now.toLocaleDateString(localeOf(), { month: 'long' })}</h2><small className="mono">{now.getFullYear()}</small></div>
            <div className="cal" id="cal">
              {WD_SHORT.slice(1).concat(WD_SHORT[0]).join(' ').split(' ').map((w) => (
                <span key={w} className="w mono">{w}</span>
              ))}
              {calCells.map((c) => (
                <b key={c.key} className={`${c.isOut ? 'o' : ''} ${c.isToday ? 't' : ''}`} style={{ '--k': c.key }}>
                  {c.isToday ? <span>{c.num}</span> : c.num}
                  {c.hasEvents && (
                    <em>
                      <i className={c.dotType === 'y' ? 'y' : ''}></i>
                    </em>
                  )}
                </b>
              ))}
            </div>
            <div className="nx">
              <small className="mono">{t('common.today')}, {hhmm(todayEvents[0]?.start || now)}</small>
              <span>{todayEvents[0]?.title || t('nextup.day_free')}</span>
            </div>
          </section>
        )

      case 'brain':
        return (
          <section key="brain" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('brain', idx)}
            <div className="hd">
              <h2>{t('nav.mind')}</h2>
              <small>{t('mem.entries_n', { count: (d?.memory || []).length })}</small>
            </div>
            {recentNotes.length ? recentNotes.map((n) => (
              <div className="note" key={n.id}>
                <b>{n.title}</b>
                <small>{[n.type, n.date].filter(Boolean).join(' · ')}</small>
              </div>
            )) : (
              <div className="muted text-[13px]">{t('td.no_notes')}</div>
            )}
          </section>
        )

      case 'pomo':
        return (
          <section key="pomo" className={`c p1 s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('pomo', idx)}
            <div className="hd"><h2>{t('unit.pomodoro')}</h2><small>{timer?.today_sessions ? t('td.sessions_day', { n: timer.today_sessions }) : ''}</small></div>
            <div className="pomo2">
              <div className="pomo-ring-wrap relative flex-none">
                <svg className="pomo-circle-lg" viewBox="0 0 80 80">
                  <defs>
                    <linearGradient id="pomoTodayGrad" x1="0" y1="0" x2="1" y2="1">
                      <stop offset="0%" stopColor="var(--acc)" />
                      <stop offset="100%" stopColor="#c04cff" />
                    </linearGradient>
                  </defs>
                  <circle className="bg" cx="40" cy="40" r="34" />
                  <circle
                    className="fg"
                    cx="40"
                    cy="40"
                    r="34"
                    stroke="url(#pomoTodayGrad)"
                    strokeDasharray={213.6}
                    strokeDashoffset={timer?.active ? 213.6 * (1 - Math.max(0, pomoLeft / ((timer.planned_min || 25) * 60))) : 0}
                  />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="mono font-semibold text-[15px]">{timer?.active ? mmss(pomoLeft) : '25:00'}</span>
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <b style={{ fontSize: '16px', fontWeight: 600 }} className="truncate block">
                  {timer?.active ? (timer.order || t('unit.focus')) : t('td.not_started')}
                </b>
                <div className="mt-2.5 flex items-center gap-2">
                  <button
                    type="button"
                    className={`btn !h-8 !px-3.5 !text-xs ${timer?.active ? '!bg-[var(--neg)] !text-white' : ''}`}
                    onClick={async () => {
                      try {
                        if (timer?.active) {
                          await api.stopTimer()
                        } else {
                          await api.startTimer(null, 25)
                        }
                        reloadTimer()
                      } catch (e) {
                        show.err(e)
                      }
                    }}
                  >
                    {timer?.active ? (
                      <><Square size={11} fill="currentColor" /> {t('pomo.stop_short')}</>
                    ) : (
                      <><Play size={11} fill="currentColor" /> {t('pomo.start_25')}</>
                    )}
                  </button>
                  {timer?.active && <span className="text-xs text-[var(--ink2)] mono">{timer.planned_min} мин</span>}
                </div>
              </div>
            </div>
          </section>
        )

      case 'orders': {
        // реальные активные заказы из дашборда (d.orders.open): статус, клиент, срок, остаток к оплате
        const open = d?.orders?.open || []
        const unpaid = d?.orders?.unpaid || 0
        return (
          <section key="orders" className={`c s8 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('orders', idx)}
            <div className="hd">
              <h2>{t('td.w_orders')}</h2>
              <small>{open.length ? t('tk.open_n', { n: open.length }) + (unpaid ? ` · ${t('or.st_awaiting', { m: money(unpaid) })}` : '') : ''}</small>
            </div>
            {!loaded ? (
              <Skeleton h={96} />
            ) : !open.length ? (
              <Empty glyph="tasks" text={t('or.empty_open')}
                sub={t('td.no_orders_sub')}
                hint={t('or.empty_open_hint')} />
            ) : (
              <div className="space-y-1">
                {open.map((o) => {
                  const left = Number(o.left ?? 0)
                  const sub = [o.client || '', o.deadline ? t('td.due', { date: shortDate(o.deadline) }) : t('td.no_due')].filter(Boolean).join(' · ')
                  return (
                    <div className="rowi cursor-pointer" key={o.id} onClick={() => nav('/orders')} title={t('td.open_orders')}>
                      <span className={`pl ${o.overdue ? 'y' : ''}`}>{o.status_label || o.status}</span>
                      <span className="t">{o.title}<small>{sub}</small></span>
                      <span className="amt">{money(left || o.price || 0)}<small>{t(left > 0 ? 'status_unpaid' : 'status_paid')}</small></span>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        )
      }

      case 'quick':
        return (
          <section key="quick" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('quick', idx)}
            <QuickAddWidget onDone={(m) => { show(m); load(); bump() }} onErr={show.err} />
          </section>
        )

      case 'spend':
        return (
          <section key="spend" className={`c p2 s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('spend', idx)}
            <SpendTodayWidget runway={d?.runway} payments={d?.payments} />
          </section>
        )

      case 'goals':
        return (
          <section key="goals" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('goals', idx)}
            <GoalsWidget goals={d?.goals} tasks={d?.tasks} onOpen={() => nav('/tasks?view=aims')} />
          </section>
        )

      case 'habits':
        return (
          <section key="habits" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('habits', idx)}
            <HabitsWidget streak={d?.streak} />
          </section>
        )

      case 'next':
        return (
          <section key="next" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('next', idx)}
            <NextUpWidget events={d?.today} tasks={d?.tasks} onOpen={(kind) => nav(kind === 'event' ? '/calendar' : '/tasks')} />
          </section>
        )

      default:
        return null
    }
  }

  const hiddenWidgets = Object.keys(ALL_WIDGET_DEFS).filter((id) => !widgetOrder.includes(id))

  return (
    <div className="pg on" id="p-today" style={pageAcc.style}>
      {/* Шапка страницы */}
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>{greeting}, {ownerName}</h1>
          <p className="sub r" style={{ '--i': 1 }}>{daySubtitle}</p>
        </div>
      </div>

      {/* Композер с печатной машинкой */}
      <div className="comp r" style={{ '--i': 2 }}>
        <i></i>
        {isTypingManual ? (
          <input
            autoFocus
            className="ph"
            style={{ background: 'transparent', border: 0, outline: 'none', width: '100%', color: 'inherit' }}
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            onBlur={() => { if (!inputVal.trim()) setIsTypingManual(false) }}
          />
        ) : (
          <button type="button" className="ph" id="ph" onClick={() => setIsTypingManual(true)}
            style={{ cursor: 'text', background: 'transparent', border: 0, textAlign: 'left' }}>
            {typed || t('td.tap_to_write')}
          </button>
        )}
        <button type="button" className="send" onClick={handleSend} aria-label={t('chat.send')} title={t('chat.send')}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 16V4M5 9l5-5 5 5" /></svg>
        </button>
      </div>

      {/* Чипсы быстрых команд */}
      <div className="chips r" style={{ '--i': 3 }}>
        <button type="button" onClick={() => { setIsTypingManual(true); setInputVal(T('qa.seed_task') + ': ') }}>{t('graph.one_task')}</button>
        <button type="button" onClick={() => { setIsTypingManual(true); setInputVal(T('qa.seed_expense') + ': ') }}>{t('qa.expense')}</button>
        <button type="button" onClick={() => { setIsTypingManual(true); setInputVal(T('ev_seed') + ': ') }}>{t('graph.one_event')}</button>
        <button type="button" onClick={() => { setIsTypingManual(true); setInputVal(T('nt_seed') + ': ') }}>{t('graph.one_note')}</button>
        <button type="button" onClick={() => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: T('td.seed_digest'), send: true } }))}>☀️ {t('rc.morning_digest')}</button>
        <button type="button" onClick={() => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: T('td.seed_week'), send: true } }))}>📊 {t('rc.week_summary')}</button>
        <button type="button" onClick={() => window.open('/api/snapshot/month.png', '_blank')}>🗓 {t('td.month_snapshot')}</button>
      </div>

      {/* Панель режима правки главной страницы */}
      {editMode && (
        <div className="c s12 r my-4 flex flex-wrap items-center justify-between gap-4 !p-4" style={{ border: '2px dashed var(--acc)', background: 'var(--sf2)', borderRadius: '24px' }}>
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--acc)] text-white">
              <Sparkles size={18} />
            </span>
            <div>
              <b className="block text-[15px] font-semibold">{t('td.edit_mode')}</b>
              <span className="text-[13px] text-[var(--ink2)]">
                {t('td.edit_mode_hint')}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn g !h-9 !px-4 text-[13px]"
              onClick={() => setAddSheetOpen(true)}
            >
              <Plus size={15} /> {t('td.add_card')}
            </button>
            <button
              type="button"
              className="btn g !h-9 !px-3 text-[13px]"
              onClick={resetWidgets}
              title={t('tk.layout_tip')}
            >
              <RotateCcw size={14} />
            </button>
            <button
              type="button"
              className="btn !h-9 !px-5 text-[13px]"
              onClick={() => setEditMode(false)}
            >
              <Check size={15} /> {t('common.done')}
            </button>
          </div>
        </div>
      )}

      {/* Сетка Bento из эталона */}
      <div className="bento">
        {widgetOrder.map((id, idx) => renderWidget(id, idx))}
      </div>

      {/* Кнопка «настроить главную» */}
      <button type="button" className="cfg" onClick={() => setEditMode((v) => !v)}>
        {t(editMode ? 'td.finish_setup' : 'td.setup_home')}
      </button>

      {/* Sheets для правки событий и задач */}
      <TaskSheet open={!!editTask} task={editTask} onClose={() => setEditTask(null)} onDone={(msg) => { setEditTask(null); load(); bump(); if (msg) show(msg) }} />
      <EventSheet open={!!editEvent} ev={editEvent} day={now} onClose={() => setEditEvent(null)} onDone={() => { setEditEvent(null); load(); bump() }} />

      {/* Sheet для добавления скрытых карточек */}
      <AddWidgetSheet
        open={addSheetOpen}
        onClose={() => setAddSheetOpen(false)}
        hiddenWidgets={hiddenWidgets}
        onAdd={addWidget}
      />
    </div>
  )
}

function AddWidgetSheet({ open, onClose, hiddenWidgets, onAdd }) {
  const { t } = useI18n()
  return (
    <Sheet open={open} onClose={onClose} title={t('td.add_widget_title')}>
      <div className="space-y-3">
        {hiddenWidgets.length === 0 ? (
          <p className="text-center py-6 text-sm text-[var(--ink3)]">{t('td.all_cards_added')}</p>
        ) : (
          hiddenWidgets.map((id) => {
            const def = ALL_WIDGET_DEFS[id]
            if (!def) return null
            return (
              <div
                key={id}
                onClick={() => onAdd(id)}
                className="flex items-center justify-between p-4 rounded-2xl border border-[var(--line)] hover:bg-[var(--sf2)] transition cursor-pointer"
              >
                <div>
                  <b className="block text-[15px] font-medium">{t(def.name)}</b>
                  <span className="text-[13px] text-[var(--ink2)]">{t(def.desc)}</span>
                </div>
                <span className="btn !h-8 !px-3 text-[12px] shrink-0">
                  <Plus size={14} /> {t('common.add')}
                </span>
              </div>
            )
          })
        )}
        <div className="pt-4 flex justify-end">
          <button type="button" className="btn g !h-9 text-[13px]" onClick={onClose}>{t('common.close')}</button>
        </div>
      </div>
    </Sheet>
  )
}
