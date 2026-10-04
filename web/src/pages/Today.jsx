/* Главная: две раскладки по ширине окна.

   Телефон (≤820px) — редакционная лента:
     1. строка-статус — приветствие крупно, контекст дня мельче (h1 нужен и TitleHeader:
        он по нему считает, когда сворачивать шапку телефона);
     2. композер фразы под ним и быстрые слова чипами;
     3. ОДНА доминирующая карточка «сейчас» — деньги (лаймовый герой) с одним ключевым
        числом и полосой на 30 дней; ниже — график кассы (широкая спокойная панель);
     4. дальше — спокойные блоки: списки-строки на волосяных разделителях, а панели
        остаются только там, где содержимое требует поверхности (календарь, помодоро,
        время за ПК, быстрое дело).

   Десктоп (≥821px) — бенто-сетка: у каждого блока своя поверхность, ширина по настройке.
   Различие только в ширине окна, разметка блоков общая: класс .wsec и переменная --wspan
   (index.css, блок «БЛОК ГЛАВНОЙ»). Логика, запросы и API не тронуты: те же пять ответов,
   что и раньше.

   Раскладка настраиваемая в обоих режимах (lib/layout): «настроить главную» включает и
   выключает блоки, двигает их (стрелки и перетаскивание) и меняет ширину. */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Check, EyeOff, Play, Plus, RotateCcw, Sparkles, Square } from 'lucide-react'
import { api, hhmm, money, relTime, shortDate, WD_SHORT_MON as WD_SHORT } from '../lib/api'
import { Empty, Rowi, Sheet, Skeleton, useToast } from '../components/ui'
import { BigMoney, HeroLine, useNumFormats, useReveal } from '../components/Widgets'
import { useRefresh } from '../App'
import TaskSheet from '../components/TaskSheet'
import { EventSheet } from './Calendar'
import { usePrefs, usePageAccent } from '../lib/prefs'
import { useCardLayout, CardCtl, useWide } from '../lib/layout'
import { useTimer, mmss } from './Orders'

import { ScreenTimeBentoWidget } from '../components/ReportCards'
// новые блоки главной: быстрое дело, лимит трат, цели, привычки, ближайшее дело
import { QuickAddWidget, SpendTodayWidget, GoalsWidget, HabitsWidget, NextUpWidget } from '../components/TodayCards'
import CashChart from '../components/CashChart'
import { TipBars } from '../components/ChartTip'
import { useI18n, localeOf, t as T } from '../lib/i18n'
import { usePhone } from '../lib/motion'

/* Подписи полей на узком телефоне (≤380px) — на ступень мельче: длинная подпись
   вроде «дата следующего шага» на 375px съедала строку и отжимала само поле. */
const FIELD_LABEL_M = 'max-[380px]:[&_.label]:text-[length:11px]'

/* Лёгкая карточка телефона (≤820px): поверхность остаётся, но блок становится легче —
   отступ 21px и радиус из токена (--r-lg; макет называет 24px — значение ведёт index.css), без тени и без рамки-хайрлайна:
   карточки на телефоне разделяет тон, а не обводка. На десктопе (≥821px) эти классы
   не действуют — там бенто-сетка с тенью и волосяной линией, её не трогаем. */
const CARD_LIGHT_M = 'max-[820px]:!bg-[var(--sf)] max-[820px]:!p-[21px] max-[820px]:!rounded-[var(--r-lg)] max-[820px]:!shadow-none max-[820px]:!transform-none'

/* Герой телефона: минимум 310px высотой (макет) и содержимое по центру — иначе
   простор уходит в пустоту под полосой дней. Лаймовый градиент и его мягкая тень
   остаются: это идентичность карточки, а не «лишняя» тень поверхности. */
/* На телефоне герой компактнее: баланс доминирует, но карточка не занимает весь экран —
   больше контента видно без прокрутки. */
const HERO_M = 'max-[820px]:!min-h-0 max-[820px]:!justify-start'

/* Быстрые слова — одна прокручиваемая строка (макет), а не три ряда кнопок */
const CHIPS_M = 'no-scrollbar max-[820px]:!mx-0 max-[820px]:!mt-3 max-[820px]:!flex-nowrap max-[820px]:!overflow-x-auto max-[820px]:!pb-1'

const GREETS = { morning: 'td.greet_morning', day: 'td.greet_day', evening: 'td.greet_evening', night: 'td.greet_night' }
const part = (h) => (h < 5 ? 'night' : h < 12 ? 'morning' : h < 18 ? 'day' : 'evening')

/* Подсказки уходят в ядро — остаются на русском в обоих режимах (i18n-raw) */
const SUGGESTIONS = ['700 такси', 'встреча в среду в 15 с Димой', 'мозг: идея для ролика', 'куда ушли деньги', 'напомни через 20 минут'] // i18n-raw

const ALL_WIDGET_DEFS = {
  summary: { id: 'summary', name: 'td.w_summary', desc: 'td.d_summary', defaultCol: 's12' },
  screen: { id: 'screen', name: 'td.w_screen', desc: 'td.d_screen', defaultCol: 's4' },
  balance: { id: 'balance', name: 'td.w_balance', desc: 'td.d_balance', defaultCol: 's12' },
  chart: { id: 'chart', name: 'td.w_chart', desc: 'td.d_chart', defaultCol: 's12' },
  expenses: { id: 'expenses', name: 'td.w_expenses', desc: 'td.d_expenses', defaultCol: 's6' },
  free: { id: 'free', name: 'td.w_free', desc: 'td.d_free', defaultCol: 's6' },
  debts: { id: 'debts', name: 'td.w_debts', desc: 'td.d_debts', defaultCol: 's6' },
  today: { id: 'today', name: 'td.w_today', desc: 'td.d_today', defaultCol: 's6' },
  calendar: { id: 'calendar', name: 'td.w_calendar', desc: 'td.d_calendar', defaultCol: 's6' },
  brain: { id: 'brain', name: 'td.w_brain', desc: 'td.d_brain', defaultCol: 's6' },
  pomo: { id: 'pomo', name: 'td.w_pomo', desc: 'td.d_pomo', defaultCol: 's6' },
  orders: { id: 'orders', name: 'td.w_orders', desc: 'td.d_orders', defaultCol: 's12' },
  missed: { id: 'missed', name: 'td.w_missed', desc: 'td.d_missed', defaultCol: 's12' },
  // новые карточки — по умолчанию спрятаны (как pomo/orders/missed), включаются кнопкой «добавить карточку»
  quick: { id: 'quick', name: 'td.w_quick', desc: 'td.d_quick', defaultCol: 's6' },
  spend: { id: 'spend', name: 'td.w_spend', desc: 'td.d_spend', defaultCol: 's6' },
  goals: { id: 'goals', name: 'td.w_goals', desc: 'td.d_goals', defaultCol: 's12' },
  habits: { id: 'habits', name: 'td.w_habits', desc: 'td.d_habits', defaultCol: 's12' },
  next: { id: 'next', name: 'td.w_next', desc: 'td.d_next', defaultCol: 's6' },
}

/* По умолчанию деньги идут первыми: герой-карточка с ключевым числом, потом график кассы,
   потом день и дела, потом остальное. Дальше пользователь переставляет сам. */
const DEFAULT_ORDER = ['balance', 'chart', 'summary', 'today', 'expenses', 'free', 'debts',
  'screen', 'calendar', 'brain', 'pomo', 'orders', 'missed', 'quick', 'spend', 'goals',
  'habits', 'next']
/* Ширина по умолчанию — та же бенто-сетка, что была до редакционной ленты: герой и график
   во всю ширину (им нужен простор), остальное блоками по половине, парами. Всё это только
   стартовые значения: дальше ширину ведёт lib/layout (localStorage) и переключатель «ширина»
   в режиме правки — сетка не должна быть декорацией, она настраиваемая. */
const DEFAULT_WIDTHS = {
  // первый ряд: герой с балансом и касса — поровну; второй ряд: четыре карточки по 4
  balance: 6, chart: 6,
  summary: 4, today: 4, expenses: 4, free: 4,
  debts: 6, screen: 6, calendar: 6, brain: 6,
  pomo: 4, orders: 4, missed: 4, quick: 4, spend: 4, goals: 4, habits: 4, next: 4,
}

/* Поверхность нужна блоку только на ТЕЛЕФОНЕ: герой с ключевым числом, график (нужна ширина),
   календарь, помодоро, время за ПК, быстрое дело (поле ввода). Остальные блоки там — списки
   на волосяных разделителях без своей коробки. На десктопе поверхность получают все (CSS). */
const PANELS = new Set(['balance', 'chart', 'screen', 'calendar', 'pomo', 'quick'])

/* Вселенная карточек — все известные виджеты: иначе добавленная карточка (pomo/orders/missed
   и новые) после перезагрузки отфильтровывалась бы из сохранённой раскладки. */
const ALL_WIDGET_IDS = Object.keys(ALL_WIDGET_DEFS)

// Первый заход: фиксируем прежний набор карточек как стартовую раскладку, чтобы новые/редкие
// виджеты не появлялись сами. Дальше раскладку ведёт lib/layout в localStorage.
try {
  const LAYOUT_KEY = 'marvin.layout.today2'
  if (typeof localStorage !== 'undefined' && !localStorage.getItem(LAYOUT_KEY)) {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({ order: [...DEFAULT_ORDER], widths: { ...DEFAULT_WIDTHS } }))
  }
} catch {}

/* Строка-значение в герое: подпись слева, сумма справа — без отдельной карточки на число
   (живёт в components/Widgets.jsx рядом с BigMoney — общий примитив обоих экранов) */

/* Заголовок блока: тот же спокойный .hd, что у карточек, но шапка может переноситься.
   На уровне модуля, чтобы React не пересоздавал поддерево на каждом рендере. */
function BlockHead({ title, note }) {
  return (
    <div className="hd flex-wrap">
      <div className="min-w-0">
        <h2 className="trunc" title={title}>{title}</h2>
      </div>
      {note && <small className="trunc max-[380px]:text-[length:var(--fs-xs)]">{note}</small>}
    </div>
  )
}

export default function Today({ openChat, address = '' }) {
  const { t } = useI18n()
  const nav = useNavigate()
  const fmt = useNumFormats()
  const [d, setD] = useState(null)
  const [fin, setFin] = useState(null)
  const [fc, setFc] = useState(null)
  const [screenData, setScreenData] = useState(null)
  const [missed, setMissed] = useState(null)
  // данные главной загружены (хоть бы попытка была): блоки рисуют Skeleton, а не выдуманные суммы
  const [loaded, setLoaded] = useState(false)
  const { tick, bump } = useRefresh()
  const [prefs, setPrefs] = usePrefs()
  const [, show] = useToast()
  const { t: timer, left: pomoLeft, reload: reloadTimer } = useTimer()

  // Режим настройки главной: порядок и ширина блоков
  const [editMode, setEditMode] = useState(false)
  const { order: widgetOrder, setOrder: setWidgetOrder, widths: widgetWidths, move, drop: dropWidget, cycleWidth } = /* Порядок берём из DEFAULT_ORDER (герой с балансом → касса → списки), а не из порядка
   объявления виджетов: иначе первыми оказывались сводка дня и время за ПК.
   Ключ хранения новый — старые сохранённые порядки игнорируются. */
  useCardLayout('today2', DEFAULT_ORDER, DEFAULT_WIDTHS)
  const wide = useWide()
  const phone = usePhone()          // ≤820px: телефонная раскладка по макету
  const pageAcc = usePageAccent('today')
  const [addSheetOpen, setAddSheetOpen] = useState(false)
  const [draggedWidget, setDraggedWidget] = useState(null)
  const reveal = useReveal(editMode)

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

  // Рендер элементов управления блоком в режиме правки
  const renderCardControls = (widgetId) => (
    <CardCtl id={widgetId} order={widgetOrder} edit={editMode} wide={wide}
      onMove={moveWidget} onHide={removeWidget} onWidth={cycleWidth}
      width={widgetWidths[widgetId] || DEFAULT_WIDTHS[widgetId] || 6}
      Icon={ArrowLeft} HideIcon={EyeOff} />
  )

  /* Общая оболочка блока: одна разметка на две раскладки, различие только в ширине окна
     (index.css, блок «БЛОК ГЛАВНОЙ»):
       — телефон (≤820px): PANELS остаются карточками, остальные — прозрачные секции со
         строками на волосяных разделителях (новая компактная лента);
       — десктоп (≥821px): .wsec даёт поверхность КАЖДОМУ блоку, и это снова бенто-сетка.
     Ширина из настроек едет в grid-column через CSS-переменную --wspan (а не инлайном):
     инлайн перебил бы медиазапрос и на телефоне растянул бы блок, хотя там всё в одну колонку.

     На телефоне блок — тоже карточка (макет): одна колонка, отступ 21px, радиус из токена, без
     тени и без хайрлайна; разделение тоном. На десктопе вид остаётся прежним. */
  const blockProps = (id) => {
    const span = widgetWidths[id] || DEFAULT_WIDTHS[id] || 6
    const surface = PANELS.has(id)
    const cls = surface ? (id === 'balance' ? `c hero home-hero ${HERO_M}` : id === 'chart' ? 'c chart' : 'c') : ''
    // в режиме правки у секций справа освобождаем место под стрелки/ширину/глаз (CSS .wsec-edit)
    const pad = editMode && !surface ? 'wsec-edit' : ''
    return {
      'data-reveal': '',
      className: `${editMode ? 'wig ' : ''}wsec ${cls} ${pad} ${CARD_LIGHT_M}`,
      style: { '--wspan': span },
      draggable: editMode || undefined,
      onDragStart: editMode ? (e) => handleDragStart(e, id) : undefined,
      onDragOver: editMode ? handleDragOver : undefined,
      onDrop: editMode ? (e) => handleDrop(e, id) : undefined,
    }
  }

  // Генератор блоков
  const renderBlock = (id) => {
    const bp = blockProps(id)
    const ctl = renderCardControls(id)

    switch (id) {
      /* ---- доминирующая карточка: одно ключевое число, деньги ---- */
      case 'balance':
        return (
          <section key={id} {...bp}>
            {ctl}
            {/* Как в макете: в шапке 「баланс」 слева и стеклянная пилюля срока справа,
                крупная сумма доминирует, полоса дней — под ней, а спокойные вторичные
                числа уходят в стеклянные плитки внизу (не спорят с балансом). */}
            <div className="hd flex-wrap">
              <h2 className="trunc">{t('td.w_balance')}</h2>
              <span className="tag" style={{ marginTop: 0 }}>{t('td.days_of_30', { count: daysLeft })}</span>
            </div>
            {!d ? (
              loaded
                ? <Empty compact glyph="money" text={t('td.no_summary')} sub={t('td.no_summary_hint')} />
                : <Skeleton h={150} radius="var(--r-lg)" />
            ) : (
              <>
                <BigMoney value={balance} format={fmt.int} label={money(balance)} />
                <div className="days !max-w-[440px]" id="days">
                  {Array.from({ length: 30 }, (_, i) => (
                    <i key={i} className={i < daysLeft ? 'on' : ''} style={{ '--k': i }} />
                  ))}
                </div>
                <div className="dl mono !max-w-[440px]"><span>{startStr}</span><span>{endStr}</span></div>
                <div className="glass-tiles mt-4">
                  <div><small>{t('td.avg_day')}</small><b className="num">{money(avgDaily)}</b></div>
                  <div><small>{t('fin.c_free')}</small><b className="num">{money(freeMonth)}</b></div>
                  <div><small>{t('aims.by', { date: endStr })}</small><b className="num">{`${forecastBalance < 0 ? '−' : ''}${money(Math.abs(forecastBalance))}`}</b></div>
                </div>
              </>
            )}
          </section>
        )

      /* ---- касса на 30 дней: широкая спокойная панель с подсказками ---- */
      case 'chart':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead
              title={t('td.w_chart')}
              note={fc ? t('td.chart_now', { bal: money(fc.balance), pace: money(fc.avg_day_spent) }) : t('fc.by_pace')}
            />
            {fc
              ? <CashChart f={fc} height={200} legend={false} />
              : <Skeleton h={200} radius="var(--r-md)" />}
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

      /* ---- сводка дня: три строки, а не три коробки ---- */
      case 'summary':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('rc.day_summary')} note={daySubtitle} />
            {!d ? (
              loaded
                ? <Empty compact glyph="money" text={t('td.no_summary')} sub={t('td.no_summary_hint')} />
                : <Skeleton h={132} />
            ) : (
              <Rowi
                title={t('rc.money')}
                sub={t('rc.spent_short', { m: money(d.finance?.spent_today ?? 0) })}
                right={<span className="amt"><span className="num">{fmt.int(balance)}</span> <span className="faint text-[length:var(--fs-xs)]">₽</span></span>}
                onClick={() => nav('/finance')}
              />
            )}
            {d && (
              <>
                <Rowi
                  title={t('rc.meetings')}
                  sub={todayEvents[0]?.title || t('nextup.day_free')}
                  right={<span className="num text-[length:var(--fs-base)]">{todayEvents.length}</span>}
                  onClick={() => nav('/calendar')}
                />
                <Rowi
                  title={t('rc.things').toLowerCase()}
                  sub={(d.tasks || []).filter((x) => x.done).length
                    ? t('rc.closed_n', { count: (d.tasks || []).filter((x) => x.done).length })
                    : t('rc.all_ahead')}
                  right={<span className="num text-[length:var(--fs-base)]">{(d.tasks || []).filter((x) => !x.done).length}</span>}
                  onClick={() => nav('/tasks')}
                />
              </>
            )}
          </section>
        )

      /* ---- события сегодня: строки времени ---- */
      case 'today':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('common.today')} note={t('cal.events_n', { count: todayEvents.length })} />
            {!d ? <Skeleton h={92} /> : todayEvents.length === 0 ? (
              <div className="muted py-3 text-[length:var(--fs-md)]">{t('td.no_events_today')}</div>
            ) : (
              todayEvents.map((e, eidx) => (
                <Rowi key={e.id || eidx} time={hhmm(e.start || now)} title={e.title} onClick={() => setEditEvent(e)} />
              ))
            )}
          </section>
        )

      /* ---- траты за 30 дней: число + столбики по дням недели ---- */
      case 'expenses':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('td.w_expenses')} note={t('td.d30')} />
            <div className="text-[length:var(--fs-2xl)] font-medium tracking-[-0.03em] num">
              {fmt.int(expenses30)} <span className="text-[length:var(--fs-lg)] opacity-70">₽</span>
            </div>
            {/* столбики по дням недели: подсказка — сколько потрачено в этот день недели */}
            {/* сервер отдаёт weekday[0] = понедельник, а WD_SHORT_MON начинается с воскресенья, поэтому подписи сдвигаем на день */}
            <TipBars
              kind="weekday"
              values={d?.finance?.weekday}
              labels={phone ? [] : WD_SHORT.slice(1).concat(WD_SHORT[0])}
              barClass="bars !text-[var(--ink-2)]"
              labelClass="bl mono !opacity-100 text-[var(--ink-2)]"
            />
          </section>
        )

      /* ---- свободно в месяц: число + столбики по пятидневкам ---- */
      case 'free':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('td.w_free')} note={t('td.per_month')} />
            <div className="text-[length:var(--fs-2xl)] font-medium tracking-[-0.03em] num">
              {fmt.int(freeMonth)} <span className="text-[length:var(--fs-lg)] opacity-70">₽</span>
            </div>
            <TipBars
              kind="month"
              values={d?.finance?.month_days}
              labels={phone ? [] : ['1', '5', '10', '15', '20', '25', '30']}
              barClass="bars !text-[var(--pos)]"
              labelClass="bl mono !opacity-100 text-[var(--ink-2)]"
            />
          </section>
        )

      /* ---- долги: остаток и полоса закрытия ---- */
      case 'debts':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('td.w_debts')} note={t('common.total')} />
            <div className="text-[length:var(--fs-2xl)] font-medium tracking-[-0.03em] num">
              {fmt.int(debtTotal)} <span className="text-[length:var(--fs-lg)] opacity-70">₽</span>
            </div>
            <div className="progress mt-3"><div style={{ width: `${Math.max(2, debtClosedPct)}%` }} /></div>
            <div className="mt-1.5 text-[length:var(--fs-xs)] text-[var(--ink-3)]">{t('td.closed_pct', { pct: debtClosedPct })}</div>
          </section>
        )

      /* ---- время за ПК: панель (графику нужна поверхность) ---- */
      case 'screen':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('td.w_screen')} note={screenData?.active_min ? t('screen.today') : ''} />
            <ScreenTimeBentoWidget data={screenData} />
          </section>
        )

      /* ---- календарь: панель ---- */
      case 'calendar':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={now.toLocaleDateString(localeOf(), { month: 'long' })} note={String(now.getFullYear())} />
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
              <span className="trunc">{todayEvents[0]?.title || t('nextup.day_free')}</span>
            </div>
          </section>
        )

      /* ---- мозг: строки записей ---- */
      case 'brain':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('nav.mind')} note={t('mem.entries_n', { count: (d?.memory || []).length })} />
            {!d ? <Skeleton h={92} /> : recentNotes.length ? recentNotes.map((n) => (
              <Rowi key={n.id} title={n.title} sub={[n.type, n.date].filter(Boolean).join(' · ')} onClick={() => nav('/memory')} />
            )) : (
              <div className="muted py-3 text-[length:var(--fs-md)]">{t('td.no_notes')}</div>
            )}
          </section>
        )

      /* ---- помодоро: панель ---- */
      case 'pomo':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('unit.pomodoro')} note={timer?.today_sessions ? t('td.sessions_day', { n: timer.today_sessions }) : ''} />
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
                  <span className="mono font-semibold text-[length:var(--fs-base)]">{timer?.active ? mmss(pomoLeft) : '25:00'}</span>
                </div>
              </div>
              <div className="flex-1 min-w-0">
                <b className="block truncate text-[length:var(--fs-lg)] font-semibold">
                  {timer?.active ? (timer.order || t('unit.focus')) : t('td.not_started')}
                </b>
                <div className="mt-2.5 flex items-center gap-2">
                  <button
                    type="button"
                    className={`btn !h-9 !px-3.5 !text-xs ${timer?.active ? '!bg-[var(--neg)] !text-white' : ''}`}
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
                  {timer?.active && <span className="mono text-[length:var(--fs-xs)] text-[var(--ink2)]">{fmt.int(timer.planned_min)} {t('unit.min')}</span>}
                </div>
              </div>
            </div>
          </section>
        )

      /* ---- заказы: строки с суммами ---- */
      case 'orders': {
        // реальные активные заказы из дашборда (d.orders.open): статус, клиент, срок, остаток к оплате
        const open = d?.orders?.open || []
        const unpaid = d?.orders?.unpaid || 0
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead
              title={t('td.w_orders')}
              note={open.length ? `${t('tk.open_n', { n: open.length })}${unpaid ? ` · ${t('or.st_awaiting', { m: money(unpaid) })}` : ''}` : ''}
            />
            {!loaded ? <Skeleton h={96} /> : !open.length ? (
              <Empty glyph="tasks" compact text={t('or.empty_open')} sub={t('td.no_orders_sub')} hint={t('or.empty_open_hint')} />
            ) : (
              open.map((o) => {
                const left = Number(o.left ?? 0)
                const sub = [o.client || '', o.deadline ? t('td.due', { date: shortDate(o.deadline) }) : t('td.no_due')].filter(Boolean).join(' · ')
                return (
                  <Rowi
                    key={o.id}
                    title={<span className="flex min-w-0 items-center gap-2"><span className={`pl shrink-0 ${o.overdue ? 'y' : ''}`}>{o.status_label || o.status}</span><span className="trunc">{o.title}</span></span>}
                    sub={sub}
                    right={<span className="amt">{money(left || o.price || 0)}<small>{t(left > 0 ? 'status_unpaid' : 'status_paid')}</small></span>}
                    onClick={() => nav('/orders')}
                  />
                )
              })
            )}
          </section>
        )
      }

      /* ---- что я упускаю: строки с суммами ---- */
      case 'missed': {
        const m = missed || {}
        const rows = [
          ...(m.unpaid || []).map((o) => ({ k: 'unpaid', t: o.title, s: o.client || '', v: money(o.left) })),
          ...(m.overdue_debts || []).map((x) => ({ k: 'debt', t: x.title, s: t('td.pay_on', { d: x.pay_day }), v: money(x.payment) })),
          ...(m.tasks_no_due || []).map((x) => ({ k: 'task', t: x.title, s: t('task.when_none'), v: '' })),
          ...(m.goals_stale || []).map((g) => ({ k: 'goal', t: g.title, s: `${g.pct}%`, v: g.left ? money(g.left) : '' })),
        ]
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('td.w_missed')} note={rows.length ? t('td.items_n', { n: rows.length }) : t('td.clean')} />
            {!missed ? <Skeleton h={72} /> : rows.length === 0 ? (
              <div className="muted py-3 text-[length:var(--fs-md)]">{t('td.nothing_missed')}</div>
            ) : (
              rows.slice(0, 8).map((r, i) => (
                <Rowi
                  key={i}
                  title={<span className="trunc">{r.t}</span>}
                  sub={r.s || undefined}
                  right={r.v ? <span className="amt" style={{ color: (r.k === 'debt' || r.k === 'unpaid') ? 'var(--neg)' : 'var(--ink2)' }}>{r.v}</span> : undefined}
                />
              ))
            )}
          </section>
        )
      }

      /* ---- быстрое дело: панель (поле ввода требует поверхности) ---- */
      case 'quick':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('qa.title')} note={t('qa.sub')} />
            <QuickAddWidget onDone={(m) => { show(m); load(); bump() }} onErr={show.err} />
          </section>
        )

      /* ---- можно потратить сегодня ---- */
      case 'spend':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('spend.title')} note={t('common.today')} />
            <SpendTodayWidget runway={d?.runway} payments={d?.payments} />
          </section>
        )

      /* ---- цели ---- */
      case 'goals':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('goals.title')} note={t('goals.active_n', { count: (d?.goals || []).length })} />
            <GoalsWidget goals={d?.goals} tasks={d?.tasks} onOpen={() => nav('/tasks?view=aims')} />
          </section>
        )

      /* ---- привычки ---- */
      case 'habits':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('habits.title')} note={t('habits.sub')} />
            <HabitsWidget streak={d?.streak} />
          </section>
        )

      /* ---- ближайшее дело ---- */
      case 'next':
        return (
          <section key={id} {...bp}>
            {ctl}
            <BlockHead title={t('nextup.title')} note={t('common.today')} />
            <NextUpWidget events={d?.today} tasks={d?.tasks} onOpen={(kind) => nav(kind === 'event' ? '/calendar' : '/tasks')} />
          </section>
        )

      default:
        return null
    }
  }

  const hiddenWidgets = Object.keys(ALL_WIDGET_DEFS).filter((id) => !widgetOrder.includes(id))

  return (
    <div className={`pg on ${FIELD_LABEL_M}`} id="p-today" style={pageAcc.style} ref={reveal}>
      {/* 1. Строка-статус: день мельче, имя крупно. h1 нужен и TitleHeader телефона.
          На телефоне верхней шапки нет — дата стоит здесь, над именем, как в макете. */}
      <header className="top" data-reveal>
        <div className="min-w-0">
          <div className="text-[length:var(--fs-md)] text-[var(--ink3)] max-[380px]:text-[length:var(--fs-xs)]">{daySubtitle}</div>
          <h1 className="fade-r" title={`${greeting}, ${ownerName}`}>{greeting}, {ownerName}</h1>
        </div>
      </header>

      {/* Панель режима правки главной страницы */}
      {editMode && (
        <div className="c s12 my-4 flex flex-wrap items-center justify-between gap-4 !p-4" style={{ border: '2px dashed var(--acc)', background: 'var(--sf2)', borderRadius: '24px' }}>
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--acc)] text-white">
              <Sparkles size={18} />
            </span>
            <div>
              <b className="block text-[length:var(--fs-base)] font-semibold">{t('td.edit_mode')}</b>
              <span className="text-[length:var(--fs-md)] text-[var(--ink2)]">
                {t('td.edit_mode_hint')}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn g !h-9 !px-4 text-[length:var(--fs-md)]"
              onClick={() => setAddSheetOpen(true)}
            >
              <Plus size={15} /> {t('td.add_card')}
            </button>
            <button
              type="button"
              className="btn g !h-9 !px-3 text-[length:var(--fs-md)]"
              onClick={resetWidgets}
              title={t('tk.layout_tip')}
              aria-label={t('tk.restore_all')}
            >
              <RotateCcw size={14} />
            </button>
            <button
              type="button"
              className="btn !h-9 !px-5 text-[length:var(--fs-md)]"
              onClick={() => setEditMode(false)}
            >
              <Check size={15} /> {t('common.done')}
            </button>
          </div>
        </div>
      )}

      {/* 3–4. Блоки: ширина по настройке, появление каскадом (data-reveal).
          На телефоне это одна колонка (CSS даёт span 12), а вертикальный ритм между
          блоками шире десктопных 16px — карточкам нужно воздуха, иначе лента слипается. */}
      <div className="bento" style={phone ? { rowGap: 20 } : undefined}>
        {widgetOrder.map((id) => renderBlock(id))}
      </div>

      {/* Настройка главной — одна точка входа (и на телефоне тоже): полоса-подпись
          в конце ленты, без рамки и без соседних кнопок. */}
      <button type="button" className="cfg max-[820px]:!mt-4 max-[820px]:!text-center" onClick={() => setEditMode((v) => !v)}>
        {t(editMode ? 'td.finish_setup' : 'td.setup_home')}
      </button>

      {/* Sheets для правки событий и задач */}
      <TaskSheet open={!!editTask} task={editTask} onClose={() => setEditTask(null)} onDone={(msg) => { setEditTask(null); load(); bump(); if (msg) show(msg) }} />
      <EventSheet open={!!editEvent} ev={editEvent} day={now} onClose={() => setEditEvent(null)} onDone={() => { setEditEvent(null); load(); bump() }} />

      {/* Sheet для добавления скрытых блоков */}
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
      <div className="stack">
        {hiddenWidgets.length === 0 ? (
          <p className="py-6 text-center text-[length:var(--fs-md)] text-[var(--ink3)]">{t('td.all_cards_added')}</p>
        ) : (
          hiddenWidgets.map((id) => {
            const def = ALL_WIDGET_DEFS[id]
            if (!def) return null
            return (
              <button
                key={id}
                type="button"
                onClick={() => onAdd(id)}
                className="more-row items-start gap-3 text-left"
              >
                <span className="min-w-0 flex-1">
                  <b className="block text-[length:var(--fs-base)] font-medium">{t(def.name)}</b>
                  <span className="block text-[length:var(--fs-md)] text-[var(--ink2)]">{t(def.desc)}</span>
                </span>
                <span className="btn-icon shrink-0" style={{ background: 'var(--fill)' }} aria-hidden="true">
                  <Plus size={16} />
                </span>
              </button>
            )
          })
        )}
        <div className="pt-3 flex justify-end">
          <button type="button" className="btn g !h-9 text-[length:var(--fs-md)]" onClick={onClose}>{t('common.close')}</button>
        </div>
      </div>
    </Sheet>
  )
}