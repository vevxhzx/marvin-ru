import { useEffect, useMemo, useState } from 'react'
import { api, hhmm, MONTHS_NOM, MONTHS as MONTHS_GEN, isSameDay, toLocalISO, dayLabel, shortDate, fullDate, WD_SHORT_MON as WD_SHORT } from '../lib/api'
import { Sheet, Field, DateTimeField, Empty, useToast, ListSkeleton } from '../components/ui'
import { useRefresh } from '../App'
import { Plus, Check, ChevronLeft, Settings2 } from 'lucide-react'
import { useCardLayout, CardCtl, useWide } from '../lib/layout'
import '../cal-glass.css'
import { usePageAccent } from '../lib/prefs'
import { usePhone } from '../lib/motion'
import { useI18n, localeOf, t as T } from '../lib/i18n'

/* Подписи полей на узком телефоне (≤380px) — на ступень мельче: длинная подпись
   вроде «дата следующего шага» на 375px съедала строку и отжимала само поле. */
const FIELD_LABEL_M = 'max-[380px]:[&_.label]:text-[length:11px]'

/* pages/Calendar.jsx — «Календарь» as an editorial hierarchy:

     big headline + the one primary action (.top)
     a calm control bar under it: месяц/неделя · ‹ сегодня ›   (--tap targets)
     month: the grid on the page background — it scrolls horizontally INSIDE its card,
            never the page; the selected day stays in the card footer
     week: seven day columns, events as readable rows, today softly lime («ок»)
     day + upcoming: rows with date, time and what the event is tied to

   Grid columns keep their deliberately uneven widths (month card wide, day panel
   narrow) — the user can still cycle them in the «настроить» mode, and the layout
   lives under the same localStorage key as before. */

/* Лёгкая карточка телефона (≤820px): та же поверхность, но без тени и без хайрлайна —
   отступ 21px, радиус из токена (--r-lg; макет называет 24px — значение ведёт index.css), разделение тоном (макет).
   На десктопе (≥821px) эти классы не действуют — бенто-сетка остаётся прежней. */
const CARD_M_LIGHT = 'max-[820px]:!bg-[var(--sf)] max-[820px]:!p-[21px] max-[820px]:!rounded-[var(--r-lg)] max-[820px]:!shadow-none max-[820px]:!transform-none'

/* Подписи мелким кеглем на узком телефоне (≤380px) уменьшаются на ступень */
const SMALL_M = 'max-[380px]:text-[length:var(--fs-xs)]'

/* Переключатель .sg на телефоне: базовое правило разрешает перенос (flex-wrap: wrap),
   и на узком экране семь вкладок разъезжались на две строки. На телефоне — одна
   прокручиваемая строка, на десктопе вид прежний. */
const SEG_ROW_M = 'fade-x max-[820px]:!flex-nowrap max-[820px]:!overflow-x-auto'

/* Карточки сетки календаря: порядок и ширина меняются в режиме «настроить» */
const CAL_CARDS = ['month', 'day', 'week', 'upcoming']
const CAL_WIDTHS = { month: 8, day: 4, week: 12, upcoming: 12 }

/* Зоны нажатия и ширины — из токенов */
const SEG_BTN = { minHeight: 'var(--tap)', padding: '0 16px' }
const NAV_BTN = { minHeight: 'var(--tap)', minWidth: 'var(--tap)', padding: '0 14px' }
const MONTH_MIN_W = 420          // клетки месяца не сжимаются ниже ~56px — листается бок

export function EventSheet({ open, ev, day, onClose, onDone }) {
  const { t } = useI18n()
  const isNew = ev === 'new' || !ev?.id
  // событие-проекция (задача/дедлайн заказа) в календаре правится в своей карточке — здесь только просмотр
  const synthetic = !isNew && Number(ev?.id) < 0
  const [title, setTitle] = useState('')
  const [start, setStart] = useState('')
  const [location, setLocation] = useState('')
  const [taskId, setTaskId] = useState('')
  const [orderId, setOrderId] = useState('')
  const [tasks, setTasks] = useState([])
  const [orders, setOrders] = useState([])
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setTitle(isNew ? '' : ev?.title || '')
    const d = isNew ? (day || new Date()) : new Date(ev?.start || Date.now())
    setStart(toLocalISO(d).slice(0, 16))
    setLocation(ev?.location || '')
    setTaskId(ev?.task_id ? String(ev.task_id) : '')
    setOrderId(ev?.order_id ? String(ev.order_id) : '')
    if (!synthetic) {
      api.tasks(true, false).then((l) => setTasks((l || []).filter((t) => t.kind !== 'event'))).catch(() => setTasks([]))
      api.orders(true).then((l) => setOrders(l || [])).catch(() => setOrders([]))
    }
  }, [open, ev, day, isNew])

  const save = async (e) => {
    if (e) e.preventDefault()
    if (!title.trim()) return
    setSaving(true)
    try {
      // Время уходит локальным «наивным» (то, что стоит в поле), а не через toISOString():
      // сервер, БД и подсказки живут в локальных часах, а UTC-строка теряла зону при записи —
      // 10:59 превращалось в 07:59 и вместе с встречей уезжал срок привязанной задачи.
      const at = new Date(start)
      const payload = {
        title: title.trim(),
        start: toLocalISO(at),
        location: location.trim() || null,
        task_id: taskId ? Number(taskId) : null,
        order_id: orderId ? Number(orderId) : null,
      }
      if (isNew) await api.addEvent({ ...payload, duration_min: 60, end: toLocalISO(new Date(at.getTime() + 3600000)) })
      else await api.updateEvent(ev.id, payload)
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!ev?.id) return
    try {
      await api.delEvent(ev.id)
      onDone()
    } catch (err) {
      show.err(err)
    }
  }

  const toggleDone = async () => {
    const next = ev.done ? 0 : 1
    setSaving(true)
    try {
      const r = await api.doneEvent(ev.id, !!next)
      const linked = (r?.linked || []).filter(Boolean)
      if (next) show(t('cal.done'), linked.join(' · '), ev.title)
      else show(t('cal.reopened'), linked.join(' · '), ev.title)
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  const kindChip = ev?.kind === 'task'
    ? { txt: t('cal.task_from_list'), cls: '!bg-[var(--acc)] !text-white' }
    : ev?.kind === 'order'
      ? { txt: t('cal.order_deadline'), cls: '!bg-[var(--warn)] !text-black' }
      : null

  if (synthetic) {
    return (
      <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={t(ev?.kind === 'order' ? 'cal.deliver' : 'cal.task_from_cal')}>
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            {kindChip && <span className={`chip ${kindChip.cls}`}>{kindChip.txt}</span>}
            {ev.done && <span className="badge pos">{t('tk.done')}</span>}
          </div>
          <div style={{ fontSize: 'var(--fs-2xl)', fontWeight: 600, letterSpacing: '-0.03em', overflowWrap: 'anywhere' }}>{ev?.title}</div>
          <div className="muted num" style={{ fontSize: 'var(--fs-md)' }}>
            {fullDate(ev?.start)} {ev?.start ? hhmm(ev.start) : ''}
          </div>
          <p className="faint" style={{ fontSize: 'var(--fs-md)', lineHeight: 'var(--lh-body)' }}>
            {ev?.kind === 'order' ? t('cal.order_help') : t('cal.task_help')}
          </p>
          <div className="flex flex-wrap justify-end gap-2 pt-1">
            <button type="button" className="btn-ghost" onClick={onClose}>{t('common.close')}</button>
            <button type="button" className="btn-primary" disabled={saving} onClick={toggleDone}>
              {t(ev.done ? 'od.back_to_work' : ev?.kind === 'order' ? 'cal.order_done' : 'cal.task_done')}
            </button>
          </div>
        </div>
      </Sheet>
    )
  }

  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={t(isNew ? 'cal.new_event' : ev.done ? 'cal.event_done' : 'cal.edit_event')}>
      <form onSubmit={save} className="space-y-4">
        <Field label={t('cal.title')}>
          <input
            className="input"
            autoFocus
            required
            style={{ minHeight: 'var(--tap-lg)', fontSize: 'var(--fs-lg)', fontWeight: 500 }}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('cal.title_ph')}
          />
        </Field>
        <Field label={t('cal.date_time')}>
          <DateTimeField value={start} onChange={setStart} className="!min-h-[var(--tap-lg)]" />
        </Field>
        <Field label={t('cal.place')}>
          <input className="input" value={location} onChange={(e) => setLocation(e.target.value)} placeholder={t('cal.place_ph')} />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={t('cal.link_task')} hint={t('cal.link_task_hint')}>
            <select className="input" value={taskId} onChange={(e) => setTaskId(e.target.value)}>
              <option value="">{t('cal.not_link')}</option>
              {tasks.map((tk) => <option key={tk.id} value={tk.id}>{tk.done ? '✓ ' : ''}{tk.title}</option>)}
            </select>
          </Field>
          <Field label={t('cal.link_order')} hint={t('cal.link_order_hint')}>
            <select className="input" value={orderId} onChange={(e) => setOrderId(e.target.value)}>
              <option value="">{t('cal.not_link')}</option>
              {orders.map((o) => <option key={o.id} value={o.id}>{o.title}</option>)}
            </select>
          </Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 pt-3">
          {!isNew ? (
            <button type="button" className="btn-ghost" style={{ color: 'var(--neg)' }} onClick={remove}>{t('common.delete')}</button>
          ) : <span />}
          <div className="flex gap-2">
            {!isNew && (
              <button type="button" className="btn-ghost" disabled={saving} onClick={toggleDone}>
                {t(ev.done ? 'cal.reopen' : 'cal.finish')}
              </button>
            )}
            <button type="button" className="btn-soft" onClick={onClose}>{t('common.cancel')}</button>
            <button type="submit" className="btn-primary" disabled={saving || !title.trim()}>{t(saving ? 'people.saving' : 'common.save')}</button>
          </div>
        </div>
      </form>
    </Sheet>
  )
}

/* Кружок завершения в строке календаря: галочка ставится на месте, без открытия карточки */
export function EvCheck({ ev, onToggle, small }) {
  const { t } = useI18n()
  return (
    <button
      type="button"
      className={`ev-check ${small ? 'sm' : ''} ${ev.done ? 'on' : ''}`}
      onClick={(e) => { e.stopPropagation(); onToggle(ev, e) }}
      aria-label={t(ev.done ? 'od.back_to_work' : 'cal.finish')}
      title={t(ev.done ? 'od.back_to_work' : 'cal.finish')}
    >
      <Check size={small ? 9 : 12} strokeWidth={3} aria-hidden="true" />
    </button>
  )
}

/* Подпись строки: откуда она — задача, дедлайн заказа или обычная встреча */
function evSub(e, tasks = [], orders = []) {
  const bits = []
  if (e.kind === 'task') bits.push(T('graph.one_task'))
  else if (e.kind === 'order') bits.push(`${T('graph.one_order')} · ${e.location || T('cal.deliver_short')}`)
  if (e.task_id && e.kind !== 'task') {
    const task = tasks.find((x) => x.id === Number(e.task_id))
    if (task) bits.push(T('cal.link_task', { title: task.title }))
  }
  if (e.order_id && e.kind !== 'order') {
    const order = orders.find((x) => x.id === Number(e.order_id))
    if (order) bits.push(T('cal.link_order', { title: order.title }))
  }
  if (e.location && e.kind !== 'order') bits.push(e.location)
  if (e.sub) bits.push(e.sub)
  return bits.join(' · ')
}

export default function Calendar() {
  const { t } = useI18n()
  const [cursor, setCursor] = useState(() => { const d = new Date(); d.setDate(1); d.setHours(0, 0, 0, 0); return d })
  const [selected, setSelected] = useState(new Date())
  /* Один объект «сегодня» на весь срок жизни страницы: раньше здесь стояло
     `const today = new Date()` в deps у useMemo — сетка пересчитывалась на каждый рендер */
  const [today] = useState(() => new Date())
  const [events, setEvents] = useState([])
  const [linkTasks, setLinkTasks] = useState([])
  const [linkOrders, setLinkOrders] = useState([])
  const [sheet, setSheet] = useState(null)
  const [view, setView] = useState('month') // 'month' | 'week'
  const [loaded, setLoaded] = useState(false)
  const { tick, bump } = useRefresh()
  const [, show] = useToast()

  /* телефонная раскладка: колонки недели по высоте содержимого, на ПК — одной высоты */
  const phone = usePhone()

  const range = useMemo(() => {
    const start = new Date(cursor)
    start.setDate(1 - ((cursor.getDay() + 6) % 7) - 14)
    const end = new Date(start)
    end.setDate(start.getDate() + 7 * 10)
    return [start, end]
  }, [cursor])

  const load = () => api.events(toLocalISO(range[0]), toLocalISO(range[1]), true).then(setEvents).catch(() => setEvents([])).finally(() => setLoaded(true))
  useEffect(() => { load() }, [range, tick])
  // «+» дока на календаре открывает форму новой встречи (AppShell шлёт calendar:add)
  useEffect(() => {
    const on = () => setSheet('new')
    window.addEventListener('calendar:add', on)
    return () => window.removeEventListener('calendar:add', on)
  }, [])
  // справочники для привязок «встреча → задача/заказ»: тянем один раз
  useEffect(() => {
    api.tasks(true, false).then((l) => setLinkTasks((l || []).filter((tk) => tk.kind !== 'event'))).catch(() => {})
    api.orders(true).then((l) => setLinkOrders(l || [])).catch(() => {})
  }, [])

  /* Завершение встречи/задачи/дедлайна заказа — сервер закрывает связанные сущности,
     а тост показывает, что именно синхронизировалось. */
  const toggleDone = async (e) => {
    const next = e.done ? 0 : 1
    setEvents((list) => list.map((x) => (x.id === e.id ? { ...x, done: next } : x)))
    try {
      const r = await api.doneEvent(e.id, !!next)
      const linked = (r?.linked || []).filter(Boolean)
      if (next) {
        show(t('cal.done'), linked.join(' · '), e.title)
      } else {
        show(t('cal.reopened'), linked.join(' · '), e.title)
      }
      load()
      bump()
    } catch (err) {
      show.err(err)
      load()
    }
  }

  // Раскладка карточек: порядок и ширина (режим «настроить» в шапке)
  const wide = useWide()
  const pageAcc = usePageAccent('calendar')
  const [cardsEdit, setCardsEdit] = useState(false)
  const { order: cardOrder, widths: cardWidths, move, cycleWidth } = useCardLayout('calendar', CAL_CARDS, CAL_WIDTHS)
  /** карточки, которые есть в текущем виде, в сохранённом порядке */
  const shown = (view === 'month' ? ['month', 'day', 'upcoming'] : ['week', 'upcoming'])
    .filter((id) => cardOrder.includes(id))
    .sort((a, b) => cardOrder.indexOf(a) - cardOrder.indexOf(b))
  const cardSt = (id, extra = {}) => ({
    order: cardOrder.indexOf(id),
    ...extra,
    ...(wide ? { gridColumn: `span ${cardWidths[id] || CAL_WIDTHS[id]}` } : {}),
  })
  const cardCtl = (id) => (
    <CardCtl id={id} order={cardOrder} edit={cardsEdit} wide={wide}
      onMove={move} onWidth={cycleWidth} width={cardWidths[id] || CAL_WIDTHS[id]}
      Icon={ChevronLeft} />
  )

  // Ячейки сетки месяца
  const cells = useMemo(() => {
    const curYear = cursor.getFullYear()
    const curMonth = cursor.getMonth()
    const firstDay = new Date(curYear, curMonth, 1)
    const offset = (firstDay.getDay() + 6) % 7
    const daysInMonth = new Date(curYear, curMonth + 1, 0).getDate()
    const daysInPrev = new Date(curYear, curMonth, 0).getDate()
    const res = []

    for (let i = 0; i < 42; i++) {
      const dayIdx = i - offset + 1
      const isOut = dayIdx < 1 || dayIdx > daysInMonth
      const num = dayIdx < 1 ? daysInPrev + dayIdx : dayIdx > daysInMonth ? dayIdx - daysInMonth : dayIdx
      const cellDate = new Date(curYear, dayIdx < 1 ? curMonth - 1 : dayIdx > daysInMonth ? curMonth + 1 : curMonth, num)
      const isToday = isSameDay(cellDate, today)
      const isSel = isSameDay(cellDate, selected)
      const dayEvs = (events || []).filter((e) => isSameDay(new Date(e.start), cellDate))
      res.push({
        num,
        isOut,
        isToday,
        isSel,
        date: cellDate,
        dotsCount: dayEvs.length,
        events: dayEvs,
        hasSpecial: dayEvs.some((e) => e.kind === 'order' || e.repeat),
        key: i,
      })
    }
    return res
  }, [cursor, events, selected, today])

  // Дни текущей недели для недельного вида
  const weekDays = useMemo(() => {
    const d = new Date(selected)
    const dayOfWeek = (d.getDay() + 6) % 7 // 0 = пн, 6 = вс
    const startOfWeek = new Date(d)
    startOfWeek.setDate(d.getDate() - dayOfWeek)
    const daysArr = []
    for (let i = 0; i < 7; i++) {
      const cur = new Date(startOfWeek)
      cur.setDate(startOfWeek.getDate() + i)
      const dayEvs = (events || []).filter((e) => isSameDay(new Date(e.start), cur)).sort((a, b) => new Date(a.start) - new Date(b.start))
      daysArr.push({
        date: cur,
        name: WD_SHORT[cur.getDay()],
        fullName: cur.toLocaleDateString(localeOf(), { weekday: 'long' }),
        num: cur.getDate(),
        isToday: isSameDay(cur, today),
        isSel: isSameDay(cur, selected),
        events: dayEvs,
        key: i,
      })
    }
    return daysArr
  }, [selected, events, today])

  const dayEvents = (events || []).filter((e) => isSameDay(new Date(e.start), selected)).sort((a, b) => new Date(a.start) - new Date(b.start))
  const upcomingAll = (events || []).filter((e) => new Date(e.start) > today)
  const upcoming = [...upcomingAll].sort((a, b) => new Date(a.start) - new Date(b.start)).slice(0, 6)
  const monthCount = (events || []).filter((e) => {
    const d = new Date(e.start)
    return d.getMonth() === cursor.getMonth() && d.getFullYear() === cursor.getFullYear()
  }).length
  /* Glass nearest strip: node positions derived from the existing upcoming order —
     visual only, no new data or strings */
  const calgNodes = upcoming.map((e, i) => ({
    e,
    x: upcoming.length === 1 ? 58 : 24 + (i * (66 / Math.max(1, upcoming.length - 1))),
  }))
  const calgFill = calgNodes.length ? calgNodes[0].x : 44

  /** Ячейки, которые реально нарисованы в сетке месяца (35 или 42 дня) */
  const gridCells = cells.slice(0, cells[35]?.isOut ? 35 : 42)
  /* Клавиатура в сетке: день фокусируется (tabIndex), ←/→/↑/↓ и Home/End — переход
     к дню, Enter/Пробел — открыть день (он станет выбранным в карточке «день»). */
  const dayKeyDown = (e, idx) => {
    const last = gridCells.length - 1
    let to = null
    if (e.key === 'ArrowRight') to = idx + 1
    else if (e.key === 'ArrowLeft') to = idx - 1
    else if (e.key === 'ArrowDown') to = idx + 7
    else if (e.key === 'ArrowUp') to = idx - 7
    else if (e.key === 'Home') to = idx - (idx % 7)
    else if (e.key === 'End') to = idx - (idx % 7) + 6
    if (to !== null) {
      e.preventDefault()
      const next = Math.max(0, Math.min(last, to))
      const nodes = e.currentTarget.parentElement?.querySelectorAll('[data-day]')
      nodes?.[next]?.focus()
      return
    }
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setSelected(gridCells[idx].date)
    }
  }

  const shiftTime = (n) => {
    if (view === 'week') {
      const d = new Date(selected)
      d.setDate(d.getDate() + n * 7)
      setSelected(d)
      const c = new Date(d)
      c.setDate(1)
      c.setHours(0, 0, 0, 0)
      setCursor(c)
    } else {
      const d = new Date(cursor)
      d.setMonth(d.getMonth() + n)
      setCursor(d)
    }
  }

  /* Один день вперёд/назад: двигаем выбранный день и, если месяц сменился, курсор —
     тогда же перезагрузится диапазон событий. */
  const shiftDay = (n) => {
    const d = new Date(selected)
    d.setDate(d.getDate() + n)
    setSelected(d)
    const c = new Date(d)
    c.setDate(1)
    c.setHours(0, 0, 0, 0)
    setCursor(c)
  }

  const goToday = () => {
    const d = new Date()
    setSelected(d)
    const c = new Date(d)
    c.setDate(1)
    c.setHours(0, 0, 0, 0)
    setCursor(c)
  }

  /* Клавиатура страницы: T — сегодня, ←/→ — день. Внутри сетки стрелки шагают по дням
     (обработчик дня вызывает preventDefault), в полях и шторках — не мешаем. */
  useEffect(() => {
    const onKey = (e) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return
      const el = e.target
      const tag = el?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable) return
      if (document.querySelector('.sheet-backdrop')) return
      if (el?.closest?.('[data-day]')) return
      if (e.key === 'ArrowLeft') { e.preventDefault(); shiftDay(-1); return }
      if (e.key === 'ArrowRight') { e.preventDefault(); shiftDay(1); return }
      // 't' и та же клавиша в русской раскладке — это про раскладку, не текст   // i18n-raw
      const k = String(e.key).toLowerCase()
      if (k === 't' || k === 'е') { e.preventDefault(); goToday() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected]) // eslint-disable-line

  /* Подписи «‹» и «›»: месяц или неделя, к которым они ведут, — без новых ключей */
  const shiftLabel = (n) => {
    if (view === 'week') return t('cal.week')
    const d = new Date(cursor)
    d.setMonth(d.getMonth() + n)
    return `${MONTHS_GEN[d.getMonth()]} ${d.getFullYear()}`
  }

  const headTitle = view === 'week'
    ? t('cal.week_of', { d: selected.getDate(), m: MONTHS_GEN[selected.getMonth()] })
    : MONTHS_NOM[cursor.getMonth()].toLowerCase()
  const weekRange = useMemo(() => {
    const a = weekDays[0]?.date
    const b = weekDays[6]?.date
    if (!a || !b) return ''
    return `${a.getDate()}–${b.getDate()} ${MONTHS_GEN[b.getMonth()]} ${b.getFullYear()}`
  }, [weekDays])

  return (
    <div className={`pg on ${FIELD_LABEL_M}`} id="p-cal" style={pageAcc.style}>
      {/* Header: заголовок + спокойная панель управления под ним. «+» — в доке.
          Панель держит .sg внутри .top — на них ходят проверки e2e («‹»/«сегодня»/«›»). */}
      <header className="top">
        <div className="min-w-0 flex-1">
          <h1 className="r" style={{ '--i': 0 }}>{headTitle}</h1>
          <p className="sub r" style={{ '--i': 1 }}>{view === 'week' ? weekRange : cursor.getFullYear()}</p>
        </div>
        <div className="calg-tb flex w-full flex-wrap items-center justify-between gap-2 r" style={{ '--i': 2 }}>
          <div className={`sg ${SEG_ROW_M}`} role="group" aria-label={t('nav.calendar')}>
            <button
              type="button"
              className={view === 'month' ? 'on' : ''}
              aria-pressed={view === 'month'}
              style={SEG_BTN}
              onClick={() => setView('month')}
            >
              {t('cal.month')}
            </button>
            <button
              type="button"
              className={view === 'week' ? 'on' : ''}
              aria-pressed={view === 'week'}
              style={SEG_BTN}
              onClick={() => setView('week')}
            >
              {t('cal.week')}
            </button>
          </div>
          <div className={`sg ${SEG_ROW_M}`} role="group" aria-label={t('cal.week_plan')}>
            <button type="button" onClick={() => shiftTime(-1)} aria-label={shiftLabel(-1)} title={shiftLabel(-1)} style={NAV_BTN}>
              <span aria-hidden="true">‹</span>
            </button>
            <button type="button" onClick={goToday} aria-label={t('common.today')} title={t('common.today')} style={{ ...NAV_BTN, paddingInline: 16 }}>
              <span>{t('common.today')}</span>
            </button>
            <button type="button" onClick={() => shiftTime(1)} aria-label={shiftLabel(1)} title={shiftLabel(1)} style={NAV_BTN}>
              <span aria-hidden="true">›</span>
            </button>
          </div>
          {shown.length > 1 && (
            <button
              type="button"
              className="btn-icon outlined shrink-0"
              onClick={() => setCardsEdit((v) => !v)}
              title={t('tk.layout_tip')}
              aria-label={t('tk.layout')}
              aria-pressed={cardsEdit}
            >
              <Settings2 size={16} aria-hidden="true" />
            </button>
          )}
          {/* На ПК добавление в шапке; на телефоне — «+» в доке */}
          <button type="button" className="btn-primary btn-sm head-primary max-[820px]:!hidden shrink-0" onClick={() => setSheet('new')}>
            + {t('cal.event')}
          </button>
        </div>
      </header>

      {/* Bento сетка календаря */}
      <div className="bento">
        {/* Вид «Месяц» */}
        {view === 'month' && (
          <>
            <section className={`c s8 r flex flex-col ${CARD_M_LIGHT}`} style={{ '--i': 3, minHeight: phone ? undefined : '560px', ...cardSt('month') }}>
              {cardCtl('month')}
              <div className="hd" style={cardsEdit ? { paddingRight: 128 } : undefined}>
                <h2 className="h3">{MONTHS_GEN[cursor.getMonth()]} {cursor.getFullYear()}</h2>
                <small className={SMALL_M}>{t('cal.events_n', { count: monthCount })}</small>
              </div>
              {/* Сетка едет вбок внутри карточки: страница не прокручивается по горизонтали,
                  колонки остаются читаемыми (minWidth), а резина гасится контейнером. */}
              <div
                style={{
                  overflowX: 'auto',
                  overscrollBehaviorX: 'contain',
                  WebkitOverflowScrolling: 'touch',
                  marginInline: -6,
                  paddingInline: 6,
                  paddingBottom: 4,
                }}
              >
                <div className="cal2" id="cal2" style={{ minWidth: phone ? 0 : MONTH_MIN_W }}>
                  <div className="cal2-head">
                    {WD_SHORT.slice(1).concat(WD_SHORT[0]).map((w, i) => (
                      <span className="mono" key={`${w}-${i}`} style={{ minWidth: 0 }}>{w}</span>
                    ))}
                  </div>
                  <div className="cal2-grid" style={{ gridTemplateRows: `repeat(${Math.ceil(gridCells.length / 7)}, minmax(48px, 1fr))` }}>
                    {gridCells.map((c, i) => (
                      <b
                        key={c.key}
                        data-day={i}
                        tabIndex={0}
                        role="button"
                        aria-current={c.isToday ? 'date' : undefined}
                        aria-label={`${c.num}, ${c.events.length ? c.events.map((e) => e.title).join(', ') : t('cal.no_events')}`}
                        className={`calg-dy ${c.isOut ? 'o' : ''} ${c.isToday ? 't' : ''} ${c.isSel && !c.isToday ? 'is-sel' : ''}`}
                        style={{ '--k': c.key, minWidth: 0 }}
                        onClick={() => setSelected(c.date)}
                        onKeyDown={(e) => dayKeyDown(e, i)}
                      >
                        <div className="flex w-full items-center justify-between">
                          <span className="day-num">{c.num}</span>
                          {c.dotsCount > 0 && !c.isToday && (
                            <em aria-hidden="true">
                              {c.events.slice(0, 3).map((ev, k) => (
                                <i key={k} className={ev.kind === 'order' ? 'y' : ''} />
                              ))}
                            </em>
                          )}
                        </div>
                        {c.events.length > 0 && (
                          <div className="day-evs">
                            {c.events.slice(0, 2).map((ev, evIdx) => (
                              <span key={ev.id || evIdx} className={`ev-pill ${ev.kind === 'order' ? 'y' : ''} ${ev.done ? 'done' : ''}`}>
                                {ev.done ? '✓ ' : ''}{ev.title}
                              </span>
                            ))}
                          </div>
                        )}
                      </b>
                    ))}
                  </div>
                </div>
              </div>
              {/* Выбранный день и его счётчик — в подвале карточки */}
              <div className="rule mt-auto flex flex-wrap items-center justify-between gap-3" style={{ marginTop: 'var(--s-3)', paddingTop: 'var(--s-3)' }}>
                <div className="min-w-0">
                  <div className="trunc" style={{ fontSize: 'var(--fs-base)' }}>
                    {dayLabel(selected)}, {selected.getDate()} {MONTHS_GEN[selected.getMonth()]}
                  </div>
                  <div className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{t('cal.events_n', { count: dayEvents.length })}</div>
                </div>
                <button type="button" className="btn-soft btn-sm shrink-0" onClick={() => setSheet('new')}>
                  <Plus size={14} strokeWidth={2.4} aria-hidden="true" /> {t('cal.add_event')}
                </button>
              </div>
            </section>

            <section className={`c s4 r flex flex-col ${CARD_M_LIGHT}`} style={{ '--i': 4, minHeight: '560px', ...cardSt('day') }}>
              {cardCtl('day')}
              <div className="hd" style={cardsEdit ? { paddingRight: 128 } : undefined}>
                <h2>{isSameDay(selected, today) ? t('common.today') : dayLabel(selected)}</h2>
                <small className={SMALL_M}>{shortDate(selected)} · {t('cal.events_n', { count: dayEvents.length })}</small>
              </div>
              {/* Side header: big gradient date (ref .big2) + weekday note — visual only,
                  same info as .hd above, hidden from screen readers to avoid duplication */}
              <div className="calg-side-top" aria-hidden="true">
                <div className="calg-big">{selected.getDate()}</div>
                <div className="calg-side-note">
                  <span className="calg-side-wd">{selected.toLocaleDateString(localeOf(), { weekday: 'long' })}</span>
                  <span className="calg-side-mo">{MONTHS_GEN[selected.getMonth()]} {selected.getFullYear()}</span>
                </div>
              </div>
              {/* Прокрутка нужна только когда есть что листать: на пустом дне inline
                  overflow-y обрезал бы свечение солнышка (.calg-sun, box-shadow до 80px)
                  жёстким прямоугольником — там короткий блок, скролла нет, поэтому
                  свечению позволяем выйти за колонку (обрезает уже карточка — мягко). */}
              <div
                className="flex-1 overflow-y-auto"
                style={{
                  overscrollBehavior: 'contain',
                  paddingRight: 2,
                  overflow: loaded && dayEvents.length === 0 ? 'visible' : undefined,
                }}
              >
                {!loaded ? (
                  <ListSkeleton n={4} rowH={58} />
                ) : dayEvents.length === 0 ? (
                  /* Ref empty-day: sun orb + note (footer .calg-btn below is the accent CTA) —
                     same strings/handler, visual-only, no new i18n */
                  <div className="calg-empty">
                    <span className="calg-sun" aria-hidden="true" />
                    <div className="calg-empty-t">{t('cal.e_day')}</div>
                    <div className="calg-empty-s">{t('cal.e_day_sub')}</div>
                  </div>
                ) : (
                  dayEvents.map((e) => (
                    <div
                      className={`rowi ${e.done ? 'is-done' : ''}`}
                      key={e.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setSheet(e)}
                      onKeyDown={(k) => {
                        if (k.target !== k.currentTarget) return   // EvCheck handles itself
                        if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); setSheet(e) }
                      }}
                      style={{ cursor: 'pointer', overflowWrap: 'anywhere' }}
                    >
                      <EvCheck ev={e} onToggle={toggleDone} />
                      <time style={{ color: 'var(--acc)', fontWeight: 500 }}>{hhmm(e.start)}</time>
                      <span className="t">
                        {e.title}
                        {(evSub(e, linkTasks, linkOrders) || e.sub) && <small>{evSub(e, linkTasks, linkOrders) || e.sub}</small>}
                      </span>
                    </div>
                  ))
                )}
              </div>
              {/* Side footer: accent create button reusing the existing create handler */}
              <div className="calg-side-foot">
                <button type="button" className="calg-btn" onClick={() => setSheet('new')}>
                  <Plus size={14} strokeWidth={2.4} aria-hidden="true" /> {t('cal.add_event')}
                </button>
              </div>
            </section>
          </>
        )}

        {/* Вид «Неделя» */}
        {view === 'week' && (
          <section className={`c s12 r ${CARD_M_LIGHT}`} style={{ '--i': 3, ...cardSt('week') }}>
            {cardCtl('week')}
            <div className="hd" style={cardsEdit ? { paddingRight: 128 } : undefined}>
              <h2 className="h3">{t('cal.week_plan')}</h2>
              <small className={SMALL_M}>{t('cal.week_hint')}</small>
            </div>
            {/* На телефоне неделя листается вбок внутри карточки (снап, без резины),
                на ПК — семь равных колонок. */}
            <div
              className="mt-4 flex gap-3 md:grid md:grid-cols-7 md:gap-3"
              style={{
                overflowX: 'auto',
                overscrollBehaviorX: 'contain',
                WebkitOverflowScrolling: 'touch',
                scrollSnapType: 'x proximity',
                paddingBottom: 4,
                /* колонки по высоте contents: пустой день не растягивается под соседний */
                alignItems: phone ? 'flex-start' : 'stretch',
              }}
            >
              {weekDays.map((dayItem) => (
                <div
                  key={dayItem.key}
                  onClick={() => setSelected(dayItem.date)}
                  role="button"
                  tabIndex={0}
                  aria-pressed={dayItem.isSel}
                  onKeyDown={(k) => { if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); setSelected(dayItem.date) } }}
                  className={`flex shrink-0 flex-col rounded-2xl p-3 md:shrink ${dayItem.isToday ? 'tint-ok' : ''}`}
                  style={{
                    /* на телефоне колонка фиксированной ширины и листается; на ПК её задаёт сетка */
                    width: phone ? 176 : undefined,
                    minWidth: phone ? 176 : 0,
                    minHeight: '148px',
                    scrollSnapAlign: 'start',
                    background: dayItem.isToday ? undefined : 'var(--sf)',
                    border: dayItem.isToday ? undefined : '1px solid var(--line)',
                    boxShadow: dayItem.isSel ? 'inset 0 0 0 1.5px var(--acc)' : undefined,
                  }}
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <span className="mono" style={{ fontSize: 'var(--fs-xs)', color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{dayItem.name}</span>
                    <span
                      className="num grid h-7 w-7 shrink-0 place-items-center rounded-full"
                      style={{
                        fontSize: 'var(--fs-md)',
                        fontWeight: 600,
                        background: dayItem.isToday ? 'var(--pos)' : 'var(--fill)',
                        color: dayItem.isToday ? 'var(--bg)' : 'var(--ink)',
                      }}
                    >
                      {dayItem.num}
                    </span>
                  </div>

                  <div className="mt-1 flex flex-col gap-1.5">
                    {dayItem.events.length === 0 ? (
                      <span className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{t('run.free')}</span>
                    ) : (
                      dayItem.events.map((ev) => (
                        <div
                          key={ev.id}
                          role="button"
                          tabIndex={0}
                          onClick={(e) => { e.stopPropagation(); setSheet(ev) }}
                          onKeyDown={(k) => {
                            if (k.target !== k.currentTarget) return   // EvCheck handles itself
                            if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); setSheet(ev) }
                          }}
                          title={ev.title}
                          className={`flex items-start gap-2 rounded-xl px-2 py-1.5 ${ev.done ? 'is-done' : ''}`}
                          style={{
                            minHeight: 'var(--tap)',
                            background: 'var(--sf2)',
                            cursor: 'pointer',
                            opacity: ev.done ? 0.72 : 1,
                          }}
                        >
                          <EvCheck small ev={ev} onToggle={toggleDone} />
                          <span className="min-w-0 flex-1">
                            <span className="mono block" style={{ fontSize: 'var(--fs-xs)', color: 'var(--ink-3)' }}>{hhmm(ev.start)}</span>
                            <span className="clamp-2 block" style={{ fontSize: 'var(--fs-md)', fontWeight: 500, overflowWrap: 'anywhere', textDecoration: ev.done ? 'line-through' : undefined }}>{ev.title}</span>
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Карточка: Ближайшие события (s12) — класс cal-upcoming: на телефоне строки
            перекладываем в две линии (см. cal-glass.css), список «Сегодня» не трогаем */}
        <section className={`c s12 r ${CARD_M_LIGHT} cal-upcoming`} style={{ '--i': 5, ...cardSt('upcoming') }}>
          {cardCtl('upcoming')}
          <div className="hd" style={cardsEdit ? { paddingRight: 128 } : undefined}>
            <h2 className="h3">{t('nextup.title')}</h2>
            <small className={SMALL_M}>{t('cal.upcoming_note', { all: upcomingAll.length, shown: upcoming.length })}</small>
          </div>
          {/* Nearest strip: now-node + event nodes over existing upcoming data
              (ref .tr/.nd) — visual only, rows below stay the interactive source */}
          {loaded && calgNodes.length > 0 && (
            <div className="calg-tr" aria-hidden="true" style={{ '--calg-fill': `${calgFill}%` }}>
              <div className="calg-nd calg-now" style={{ '--x': '3%' }}><span>{t('mem.t_short')}</span></div>
              {calgNodes.map(({ e, x }) => (
                <div key={e.id} className="calg-nd" style={{ '--x': `${x}%` }}>
                  <span>{e.title}<small>{shortDate(e.start)} · {hhmm(e.start)}</small></span>
                </div>
              ))}
            </div>
          )}
          {!loaded ? (
            <ListSkeleton n={3} rowH={58} />
          ) : upcoming.length === 0 ? (
            <Empty
              compact
              glyph="calendar"
              text={t('cal.no_upcoming')}
              sub={t('cal.e_upcoming_sub')}
              action={<button type="button" className="btn-soft btn-sm" onClick={() => setSheet('new')}>{t('cal.add_event')}</button>}
            />
          ) : (
            <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
              {upcoming.map((e) => {
                const d = new Date(e.start)
                const sub = evSub(e, linkTasks, linkOrders)
                return (
                  <div className={`rowi ${e.done ? 'is-done' : ''}`} key={e.id} role="button" tabIndex={0}
                    onClick={() => setSheet(e)}
                    onKeyDown={(k) => {
                      if (k.target !== k.currentTarget) return   // EvCheck handles itself
                      if (k.key === 'Enter' || k.key === ' ') { k.preventDefault(); setSheet(e) }
                    }}
                    style={{ cursor: 'pointer', overflowWrap: 'anywhere' }}>
                    <EvCheck ev={e} onToggle={toggleDone} />
                    <time>{WD_SHORT[d.getDay()]} {hhmm(e.start)}</time>
                    <span className="t">
                      {e.title}
                      <small>{[shortDate(e.start), sub].filter(Boolean).join(' · ')}</small>
                    </span>
                    <span className="chip shrink-0">{t(e.kind === 'task' ? 'graph.one_task' : e.kind === 'order' ? 'graph.one_order' : 'graph.one_event')}</span>
                  </div>
                )
              })}
            </div>
          )}
        </section>
      </div>

      <EventSheet open={!!sheet} ev={sheet} day={selected} onClose={() => setSheet(null)} onDone={() => { setSheet(null); load(); bump() }} />
    </div>
  )
}