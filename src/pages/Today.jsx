import { useEffect, useRef, useState, useMemo } from 'react'
import { api, money, hhmm, plural } from '../lib/api'
import { Num, useToast, PageAccent } from '../components/ui'
import { useRefresh } from '../App'
import TaskSheet from '../components/TaskSheet'
import { EventSheet } from './Calendar'
import { usePrefs, usePageAccent } from '../lib/prefs'
import { Sheet } from '../components/ui'
import { ArrowLeft, EyeOff, Plus, RotateCcw, Check, Sparkles, Square, Play } from 'lucide-react'
import { useCardLayout, CardCtl, useWide } from '../lib/layout'
import { useTimer, mmss } from './Orders'

import { TodaySummaryWidget, ScreenTimeBentoWidget } from '../components/ReportCards'
import { useNavigate } from 'react-router-dom'

const GREETS = { morning: 'доброе утро', day: 'добрый день', evening: 'добрый вечер', night: 'доброй ночи' }
const part = (h) => (h < 5 ? 'night' : h < 12 ? 'morning' : h < 18 ? 'day' : 'evening')
const WD = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']
const MONTHS_RU = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']

const SUGGESTIONS = ['700 такси', 'встреча в среду в 15 с Димой', 'мозг: идея для ролика', 'куда ушли деньги', 'напомни через 20 минут']

const ALL_WIDGET_DEFS = {
  summary: { id: 'summary', name: 'сводка дня', desc: 'Единый агрегатор задач, встреч и бюджета', defaultCol: 's8' },
  screen: { id: 'screen', name: 'время за пк', desc: 'Почасовая активность и фокус в программах', defaultCol: 's4' },
  balance: { id: 'balance', name: 'баланс', desc: 'Остаток средств, дней запаса и темп трат', defaultCol: 's4' },
  chart: { id: 'chart', name: 'касса на 30 дней', desc: 'Интерактивный график прогноза кассы', defaultCol: 's8' },
  expenses: { id: 'expenses', name: 'траты', desc: 'Расход за 30 дней и столбики по дням недели', defaultCol: 's4' },
  free: { id: 'free', name: 'свободно', desc: 'Свободный остаток в месяц и разбивка', defaultCol: 's4' },
  debts: { id: 'debts', name: 'долги', desc: 'Остаток долгов и шкала закрытия', defaultCol: 's4' },
  today: { id: 'today', name: 'сегодня', desc: 'Список событий на текущий день', defaultCol: 's4' },
  calendar: { id: 'calendar', name: 'календарь', desc: 'Мини-сетка текущего месяца с метками', defaultCol: 's4' },
  brain: { id: 'brain', name: 'мозг', desc: 'Последние сохранённые мысли и заметки', defaultCol: 's4' },
  pomo: { id: 'pomo', name: 'помодоро', desc: 'Виджет фокус-сессии и таймера', defaultCol: 's4' },
  orders: { id: 'orders', name: 'заказы в работе', desc: 'Активные заказы и дедлайны', defaultCol: 's8' },
}

const DEFAULT_ORDER = ['summary', 'screen', 'balance', 'chart', 'expenses', 'free', 'debts', 'today', 'calendar', 'brain']
const DEFAULT_WIDTHS = { summary: 8, screen: 4, balance: 4, chart: 8, expenses: 4, free: 4, debts: 4, today: 4, calendar: 4, brain: 4, pomo: 4, orders: 8 }

export default function Today({ openChat, address = 'вовчик' }) {
  const nav = useNavigate()
  const [d, setD] = useState(null)
  const [fin, setFin] = useState(null)
  const [fc, setFc] = useState(null)
  const [screenData, setScreenData] = useState(null)
  const { tick, bump } = useRefresh()
  const [prefs, setPrefs] = usePrefs()
  const [, show] = useToast()
  const { t: timer, left: pomoLeft, reload: reloadTimer } = useTimer()

  // Режим настройки главной: порядок и ширина карточек
  const [editMode, setEditMode] = useState(false)
  const { order: widgetOrder, setOrder: setWidgetOrder, widths: widgetWidths, move, drop: dropWidget, cycleWidth, reset: resetLayout } = useCardLayout('today', DEFAULT_ORDER, DEFAULT_WIDTHS)
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

  const resetWidgets = () => resetLayout()

  const load = () => {
    Promise.all([
      api.dashboard().catch(() => null),
      api.finSummary(30).catch(() => null),
      api.finForecast(30).catch(() => null),
      api.get('/api/screen?days=1').catch(() => null),
    ]).then(([dash, f, fe, sc]) => {
      if (dash) setD(dash)
      if (f) setFin(f)
      if (fe) setFc(fe)
      if (sc) setScreenData(sc)
    })
  }

  useEffect(() => { load() }, [tick])

  const now = new Date()
  const greeting = GREETS[part(now.getHours())]
  const ownerName = prefs.address || address || 'вовчик'
  const daySubtitle = `${WD[now.getDay()]}, ${now.getDate()} ${MONTHS_GEN[now.getMonth()]}`

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
  const balance = d?.finance?.balance ?? 0
  const daysLeft = Math.min(30, Math.max(1, Math.round(d?.finance?.runway_days ?? 0)))
  const avgDaily = d?.finance?.avg_daily ?? 0
  // Прогноз на конец периода берём у сервера (реальные операции + регулярные платежи)
  const fcLast = fc?.points?.filter((p) => p.kind === 'future').slice(-1)[0]
  const forecastBalance = fcLast ? fcLast.balance : balance - avgDaily * 30

  // 30 дней отсечек
  const startD = new Date(now)
  const endD = new Date(now)
  endD.setDate(endD.getDate() + 30)
  const z = (n) => ('0' + n).slice(-2)
  const startStr = `${z(startD.getDate())}.${z(startD.getMonth() + 1)}`
  const endStr = `${z(endD.getDate())}.${z(endD.getMonth() + 1)}`

  // Траты 30 дней и столбики по дням недели — сервер считает из реальных операций
  const expenses30 = fin?.spent || d?.finance?.expense_month || 0
  const toBars = (sums) => {
    const max = Math.max(1, ...(sums || []))
    return (sums || []).map((h) => Math.round((h / max) * 100))
  }
  const weekdayHeights = toBars(d?.finance?.weekday)
  const monthDayHeights = toBars(d?.finance?.month_days)

  // Свободно в месяц
  const freeMonth = d?.finance?.cashflow ? Math.max(0, d.finance.cashflow) : 0

  // Долги
  const debtTotal = (d?.debts || []).reduce((acc, x) => acc + (x.total - (x.paid || 0)), 0)
  const totalOrigDebts = (d?.debts || []).reduce((acc, x) => acc + (x.total || 0), 0) || debtTotal
  const debtClosedPct = totalOrigDebts > 0 ? Math.round(((totalOrigDebts - debtTotal) / totalOrigDebts) * 100) : 0
  const closedSegments = Math.round((debtClosedPct / 100) * 16)

  // Сегодня события
  const todayEvents = (d?.today || []).slice(0, 3)

  // Календарь
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
      const hasEvents = !isOut && [7, 10, 12, 15, 16, 18, 19, 25, 27, 29].includes(num)
      const dotType = [25, 27].includes(num) ? 'y' : 'd'
      cells.push({ num, isOut, isToday, hasEvents, dotType, key: i })
    }
    return cells
  }, [now.getMonth(), now.getFullYear(), now.getDate()])

  // Мозг записи
  const recentNotes = (d?.memory || []).slice(0, 3).map((n) => ({
    id: n.id,
    title: n.text ? n.text.slice(0, 40) : 'Заметка',
    type: n.tags?.[0] || 'мысль',
    date: 'сегодня',
  }))

  // Скраббер графика: точки приходят из того же расчёта, что и в разделе «финансы» —
  // здесь раньше была рисованная вручную кривая, которая врала про будущий баланс
  const pts = fc?.points || []
  const geo = useMemo(() => {
    if (pts.length < 2) return null
    const vals = pts.map((p) => p.balance)
    let max = Math.max(...vals)
    let min = Math.min(...vals)
    if (min > 0) min = 0
    if (max < 0) max = 0
    const span = (max - min) || 1
    const X = (i) => (i / (pts.length - 1)) * 600
    const Y = (v) => 186 - ((v - min) / span) * 166
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(p.balance).toFixed(1)}`).join('')
    return { X, Y, line, area: `${line}L600 200L0 200Z`, zero: Y(0), iNow: Math.max(0, pts.findIndex((p) => p.kind === 'future')) }
  }, [fc])

  const [scrubI, setScrubI] = useState(null)
  const [scrubActive, setScrubActive] = useState(false)
  const svRef = useRef(null)

  const handlePointerMove = (e) => {
    if (!svRef.current || !pts.length || !geo) return
    const r = svRef.current.getBoundingClientRect()
    const fx = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
    setScrubI(Math.round(fx * (pts.length - 1)))
    setScrubActive(true)
  }

  const handlePointerLeave = () => { setScrubActive(false); setScrubI(null) }

  // подсказка: при наведении — день под курсором, в покое — итог на конец периода
  const tipI = scrubActive && scrubI != null ? scrubI : pts.length - 1
  const tipP = pts[tipI]
  const tipLeft = geo ? Math.min(Math.max(geo.X(tipI) / 6, 9), 91) : 50
  const tipTop = geo && tipP ? (geo.Y(tipP.balance) / 200) * 100 : 50
  const tipText = tipP
    ? `${z(Number(tipP.date.slice(8, 10)))}.${tipP.date.slice(5, 7)} · ${tipP.balance < 0 ? '−' : ''}${money(Math.abs(tipP.balance))}`
    : `${endStr} · ${forecastBalance < 0 ? '−' : ''}${money(Math.abs(forecastBalance))}`

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
            <TodaySummaryWidget
              data={{
                tasks: d?.tasks || [],
                events: todayEvents || [],
                balance: balance,
                spentToday: d?.finance?.spent_today ?? 450,
                dailyBudget: Math.round(balance / Math.max(1, daysLeft)),
              }}
              onOpenTasks={() => nav('/tasks')}
              onOpenCalendar={() => nav('/calendar')}
              onOpenFinance={() => nav('/finance')}
            />
          </section>
        )

      case 'screen':
        return (
          <section key="screen" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('screen', idx)}
            <ScreenTimeBentoWidget data={screenData} />
          </section>
        )

      case 'balance':
        return (
          <section key="balance" className={`c hero s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('balance', idx)}
            <div className="hd"><h2>баланс</h2><small>хватит на</small></div>
            <div className="big"><Num value={balance} /> ₽</div>
            <span className="tag">{daysLeft} дней из 30</span>
            <div className="days" id="days">
              {Array.from({ length: 30 }, (_, i) => (
                <i key={i} className={i < daysLeft ? 'on' : ''} style={{ '--k': i }} />
              ))}
            </div>
            <div className="dl mono"><span>{startStr}</span><span>{endStr}</span></div>
            <div className="hm">
              <div><small>в среднем в день</small><b>{money(avgDaily)}</b></div>
              <div><small>к {endStr}</small><b>{forecastBalance < 0 ? '−' : ''}{money(Math.abs(forecastBalance))}</b></div>
            </div>
          </section>
        )

      case 'chart':
        return (
          <section key="chart" className={`c chart s8 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('chart', idx)}
            <div className="hd"><h2>касса на 30 дней</h2><small>при текущем темпе</small></div>
            <div className="cw" id="cw" onPointerMove={handlePointerMove} onPointerLeave={handlePointerLeave}>
              {!geo ? (
                <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', opacity: 0.6 }}>
                  собираю данные…
                </div>
              ) : (
                <>
                  <div className="tip mono" id="tip" style={{ left: `${tipLeft}%`, top: `${tipTop}%` }}>
                    {tipText}
                  </div>
                  <svg id="sv" ref={svRef} viewBox="0 0 600 200" role="img" aria-label="касса на 30 дней">
                    <defs>
                      <linearGradient id="gaToday" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0" style={{ stopColor: 'var(--acc)', stopOpacity: 0.35 }} />
                        <stop offset="1" style={{ stopColor: 'var(--acc)', stopOpacity: 0 }} />
                      </linearGradient>
                      <linearGradient id="glToday" x1="0" x2="1">
                        <stop offset="0" style={{ stopColor: '#ff9f5c' }} />
                        <stop offset="1" style={{ stopColor: 'var(--acc)' }} />
                      </linearGradient>
                    </defs>
                    <line className="zero" x1="0" x2="600" y1={geo.zero} y2={geo.zero} />
                    <path className="ar" fill="url(#gaToday)" d={geo.area} />
                    <path className="ln" stroke="url(#glToday)" pathLength="1" d={geo.line} />
                    {geo.iNow > 0 && (
                      <line className="sl" x1={geo.X(geo.iNow)} x2={geo.X(geo.iNow)} y1="0" y2="200" style={{ opacity: 0.3, strokeDasharray: '4 6' }} />
                    )}
                    <circle className="pulse" cx={geo.X(0)} cy={geo.Y(pts[0].balance)} r="5" />
                    <circle className="d" style={{ '--t': '.9s' }} cx={geo.X(0)} cy={geo.Y(pts[0].balance)} r="5" fill="var(--pos)" />
                    <circle className="d" style={{ '--t': '1.4s' }} cx={geo.X(geo.iNow)} cy={geo.Y(pts[geo.iNow].balance)} r="5" fill="var(--ink)" />
                    <circle className="d" style={{ '--t': '2.1s' }} cx={geo.X(pts.length - 1)} cy={geo.Y(pts[pts.length - 1].balance)} r="6"
                      fill={pts[pts.length - 1].balance < 0 ? 'var(--neg)' : 'var(--pos)'} />
                    <line className="sl" x1={scrubActive ? geo.X(scrubI || 0) : 0} x2={scrubActive ? geo.X(scrubI || 0) : 0} y1="0" y2="200" style={{ opacity: scrubActive ? 0.6 : 0 }} />
                    <circle className="sd" r="5" fill="var(--ink)" opacity={scrubActive ? 1 : 0}
                      cx={scrubActive ? geo.X(scrubI || 0) : 0} cy={scrubActive ? geo.Y(pts[scrubI || 0]?.balance || 0) : 0} />
                  </svg>
                </>
              )}
            </div>
            <div className="ax mono"><span>{startStr}</span><span>сегодня</span><span>{endStr}</span></div>
            <div className="lg">
              <span><i style={{ background: '#ff9f5c' }}></i>факт</span>
              <span><i style={{ background: 'var(--acc)' }}></i>прогноз</span>
              {fc?.min_balance != null && fc.min_balance >= 0 && fc.min_date && (
                <span>минимум {money(fc.min_balance)} · {z(Number(fc.min_date.slice(8, 10)))}.{fc.min_date.slice(5, 7)}</span>
              )}
            </div>
          </section>
        )

      case 'expenses':
        return (
          <section key="expenses" className={`c p1 s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('expenses', idx)}
            <div className="hd"><h2>траты</h2><small>30 дней</small></div>
            <div className="mid"><Num value={expenses30} /> ₽</div>
            <div className="bars">
              {weekdayHeights.map((h, bidx) => (
                <i key={bidx} className={h ? '' : 'z'} style={{ '--h': `${h}%`, '--k': bidx }} />
              ))}
            </div>
            <div className="bl mono"><span>пн</span><span>вт</span><span>ср</span><span>чт</span><span>пт</span><span>сб</span><span>вс</span></div>
          </section>
        )

      case 'free':
        return (
          <section key="free" className={`c p2 s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('free', idx)}
            <div className="hd"><h2>свободно</h2><small>в месяц</small></div>
            <div className="mid"><Num value={freeMonth} /> ₽</div>
            <div className="bars">
              {monthDayHeights.map((h, bidx) => (
                <i key={bidx} className={h ? '' : 'z'} style={{ '--h': `${h}%`, '--k': bidx }} />
              ))}
            </div>
            <div className="bl mono"><span>1</span><span>5</span><span>10</span><span>15</span><span>20</span><span>25</span><span>30</span></div>
          </section>
        )

      case 'debts':
        return (
          <section key="debts" className={`c blk s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('debts', idx)}
            <div className="hd"><h2>долги</h2><small>всего</small></div>
            <div className="mid"><Num value={debtTotal} /> ₽</div>
            <div className="seg" id="seg">
              {Array.from({ length: 16 }, (_, i) => (
                <i key={i} className={i < closedSegments ? 'on' : ''} style={{ '--k': i }} />
              ))}
            </div>
            <div className="cap mono">закрыто {debtClosedPct}%</div>
          </section>
        )

      case 'today':
        return (
          <section key="today" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('today', idx)}
            <div className="hd">
              <h2>сегодня</h2>
              <small>{todayEvents.length} {plural(todayEvents.length, 'событие', 'события', 'событий')}</small>
            </div>
            {todayEvents.length === 0 ? (
              <div className="py-4 text-center text-sm" style={{ color: 'var(--ink3)' }}>нет событий на сегодня</div>
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
            <div className="hd"><h2>{MONTHS_RU[now.getMonth()]}</h2><small className="mono">{now.getFullYear()}</small></div>
            <div className="cal" id="cal">
              {'пн вт ср чт пт сб вс'.split(' ').map((w) => (
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
              <small className="mono">сегодня, {hhmm(todayEvents[0]?.start || now)}</small>
              <span>{todayEvents[0]?.title || 'день свободен'}</span>
            </div>
          </section>
        )

      case 'brain':
        return (
          <section key="brain" className={`c s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('brain', idx)}
            <div className="hd">
              <h2>мозг</h2>
              <small>{(d?.memory || []).length} {plural((d?.memory || []).length, 'запись', 'записи', 'записей')}</small>
            </div>
            {recentNotes.length ? recentNotes.map((n) => (
              <div className="note" key={n.id}>
                <b>{n.title}</b>
                <small>{n.type} · {n.date}</small>
              </div>
            )) : (
              <div className="muted text-[13px]">записей пока нет — скажите в чате «запиши: …»</div>
            )}
          </section>
        )

      case 'pomo':
        return (
          <section key="pomo" className={`c p1 s4 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('pomo', idx)}
            <div className="hd"><h2>помодоро</h2><small>{timer?.today_sessions ? `${timer.today_sessions} за день` : ''}</small></div>
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
                  {timer?.active ? (timer.order || 'фокус-сессия') : 'сегодня ещё не садились'}
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
                      <><Square size={11} fill="currentColor" /> остановить</>
                    ) : (
                      <><Play size={11} fill="currentColor" /> 25 минут</>
                    )}
                  </button>
                  {timer?.active && <span className="text-xs text-[var(--ink2)] mono">{timer.planned_min} мин</span>}
                </div>
              </div>
            </div>
          </section>
        )

      case 'orders':
        return (
          <section key="orders" className={`c s8 r ${isWig}`} style={animStyle} {...dragProps}>
            {renderCardControls('orders', idx)}
            <div className="hd"><h2>заказы в работе</h2><small></small></div>
            <div className="space-y-1">
              <div className="rowi">
                <span className="pl y">на правках</span>
                <span className="t">Монтаж узбекам2<small>кот прод · срок был вс 27 сен</small></span>
                <span className="amt">2 000 ₽<small>не оплачен</small></span>
              </div>
              <div className="rowi">
                <span className="pl">в работе</span>
                <span className="t">Вставка скаммерсу<small>илья (монтажер скаммерса)</small></span>
                <span className="amt">500 ₽<small>не оплачен</small></span>
              </div>
            </div>
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
        <div className="hr r" style={{ '--i': 1 }}>
          <PageAccent page="today" />
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
          <span className="ph" id="ph" onClick={() => setIsTypingManual(true)} style={{ cursor: 'text' }}>
            {typed}
          </span>
        )}
        <span className="send" onClick={handleSend} style={{ cursor: 'pointer' }}>
          <svg viewBox="0 0 20 20"><path d="M10 16V4M5 9l5-5 5 5" /></svg>
        </span>
      </div>

      {/* Чипсы быстрых команд */}
      <div className="chips r" style={{ '--i': 3 }}>
        <span onClick={() => { setIsTypingManual(true); setInputVal('задача: ') }}>задача</span>
        <span onClick={() => { setIsTypingManual(true); setInputVal('трата: ') }}>трата</span>
        <span onClick={() => { setIsTypingManual(true); setInputVal('встреча: ') }}>встреча</span>
        <span onClick={() => { setIsTypingManual(true); setInputVal('мысль: ') }}>мысль</span>
        <span onClick={() => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: 'доброе утро', send: true } }))}>☀️ дайджест</span>
        <span onClick={() => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: 'итоги недели', send: true } }))}>📊 итоги недели</span>
      </div>

      {/* Панель режима правки главной страницы */}
      {editMode && (
        <div className="c s12 r my-4 flex flex-wrap items-center justify-between gap-4 !p-4" style={{ border: '2px dashed var(--acc)', background: 'var(--sf2)', borderRadius: '24px' }}>
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--acc)] text-white">
              <Sparkles size={18} />
            </span>
            <div>
              <b className="block text-[15px] font-semibold">режим настройки главного экрана</b>
              <span className="text-[13px] text-[var(--ink2)]">
                перетаскивайте карточки мышью или стрелками, меняйте ширину (кнопка с числом столбцов), скрывайте и добавляйте новые
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn g !h-9 !px-4 text-[13px]"
              onClick={() => setAddSheetOpen(true)}
            >
              <Plus size={15} /> добавить карточку
            </button>
            <button
              type="button"
              className="btn g !h-9 !px-3 text-[13px]"
              onClick={resetWidgets}
              title="Сбросить порядок и ширину карточек"
            >
              <RotateCcw size={14} />
            </button>
            <button
              type="button"
              className="btn !h-9 !px-5 text-[13px]"
              onClick={() => setEditMode(false)}
            >
              <Check size={15} /> готово
            </button>
          </div>
        </div>
      )}

      {/* Сетка Bento из эталона */}
      <div className="bento">
        {widgetOrder.map((id, idx) => renderWidget(id, idx))}
      </div>

      {/* Кнопка «настроить главную» */}
      <div className="cfg" onClick={() => setEditMode((v) => !v)}>
        {editMode ? 'завершить настройку' : 'настроить главную'}
      </div>

      {/* Sheets для правки событий и задач */}
      <TaskSheet open={!!editTask} task={editTask} onClose={() => setEditTask(null)} onDone={() => { setEditTask(null); load(); bump() }} />
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
  return (
    <Sheet open={open} onClose={onClose} title="добавить виджет на главную">
      <div className="space-y-3">
        {hiddenWidgets.length === 0 ? (
          <p className="text-center py-6 text-sm text-[var(--ink3)]">Все доступные карточки уже добавлены на главный экран.</p>
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
                  <b className="block text-[15px] font-medium">{def.name}</b>
                  <span className="text-[13px] text-[var(--ink2)]">{def.desc}</span>
                </div>
                <span className="btn !h-8 !px-3 text-[12px] shrink-0">
                  <Plus size={14} /> добавить
                </span>
              </div>
            )
          })
        )}
        <div className="pt-4 flex justify-end">
          <button type="button" className="btn g !h-9 text-[13px]" onClick={onClose}>закрыть</button>
        </div>
      </div>
    </Sheet>
  )
}
