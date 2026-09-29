import { useEffect, useMemo, useState } from 'react'
import { api, hhmm, MONTHS_NOM, MONTHS as MONTHS_GEN, isSameDay, toLocalISO, dayLabel, shortDate, plural } from '../lib/api'
import { Sheet, Field, useToast } from '../components/ui'
import { useRefresh } from '../App'
import { Plus, ChevronLeft, ChevronRight, Calendar as CalIcon } from 'lucide-react'
import { useCardLayout, CardCtl, useWide } from '../lib/layout'

const WD = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']
const WD_FULL = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']

/* Карточки сетки календаря: порядок и ширина меняются в режиме «настроить» */
const CAL_CARDS = ['month', 'day', 'week', 'upcoming']
const CAL_WIDTHS = { month: 8, day: 4, week: 12, upcoming: 12 }

export function EventSheet({ open, ev, day, onClose, onDone }) {
  const isNew = ev === 'new' || !ev?.id
  const [title, setTitle] = useState('')
  const [start, setStart] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setTitle(isNew ? '' : ev?.title || '')
    const d = isNew ? (day || new Date()) : new Date(ev?.start || Date.now())
    setStart(toLocalISO(d).slice(0, 16))
  }, [open, ev, day, isNew])

  const save = async (e) => {
    if (e) e.preventDefault()
    if (!title.trim()) return
    setSaving(true)
    try {
      if (isNew) {
        await api.addEvent({ title: title.trim(), start: new Date(start).toISOString() })
      } else {
        await api.updateEvent(ev.id, { title: title.trim(), start: new Date(start).toISOString() })
      }
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

  return (
    <Sheet open={open} onClose={onClose} title={isNew ? 'новое событие' : 'редактировать событие'}>
      <form onSubmit={save} className="space-y-4">
        <Field label="название события">
          <input className="input" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Встреча с клиентом, созвон…" />
        </Field>
        <Field label="дата и время">
          <input type="datetime-local" className="input" value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
        <div className="flex items-center justify-between pt-4">
          {!isNew && <button type="button" className="btn g !text-[var(--neg)]" onClick={remove}>удалить</button>}
          <div className="ml-auto flex gap-2">
            <button type="button" className="btn g" onClick={onClose}>отмена</button>
            <button type="submit" className="btn" disabled={saving || !title.trim()}>{saving ? 'сохраняю…' : 'сохранить'}</button>
          </div>
        </div>
      </form>
    </Sheet>
  )
}

export default function Calendar() {
  const [cursor, setCursor] = useState(() => { const d = new Date(); d.setDate(1); d.setHours(0, 0, 0, 0); return d })
  const [selected, setSelected] = useState(new Date())
  const [events, setEvents] = useState([])
  const [sheet, setSheet] = useState(null)
  const [view, setView] = useState('month') // 'month' | 'week'
  const { tick, bump } = useRefresh()

  const range = useMemo(() => {
    const start = new Date(cursor)
    start.setDate(1 - ((cursor.getDay() + 6) % 7) - 14)
    const end = new Date(start)
    end.setDate(start.getDate() + 7 * 10)
    return [start, end]
  }, [cursor])

  const load = () => api.events(toLocalISO(range[0]), toLocalISO(range[1]), true).then(setEvents).catch(() => setEvents([]))
  useEffect(() => { load() }, [range, tick])

  const today = new Date()

  // Раскладка карточек: порядок и ширина (режим «настроить» в шапке)
  const wide = useWide()
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
        name: WD[cur.getDay()],
        fullName: WD_FULL[cur.getDay()],
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
  const upcoming = (events || []).filter((e) => new Date(e.start) > today).sort((a, b) => new Date(a.start) - new Date(b.start)).slice(0, 6)

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

  const goToday = () => {
    const d = new Date()
    setSelected(d)
    const c = new Date(d)
    c.setDate(1)
    c.setHours(0, 0, 0, 0)
    setCursor(c)
  }

  return (
    <div className="pg on" id="p-cal">
      {/* Шапка календаря */}
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>
            {view === 'week' ? `неделя ${selected.getDate()} ${MONTHS_GEN[selected.getMonth()]}` : MONTHS_NOM[cursor.getMonth()].toLowerCase()}
          </h1>
          <p className="sub r" style={{ '--i': 1 }}>{cursor.getFullYear()}</p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          <div className="sg">
            <span className={view === 'month' ? 'on' : ''} onClick={() => setView('month')}>месяц</span>
            <span className={view === 'week' ? 'on' : ''} onClick={() => setView('week')}>неделя</span>
          </div>
          <div className="sg">
            <span onClick={() => shiftTime(-1)}>‹</span>
            <span onClick={goToday}>сегодня</span>
            <span onClick={() => shiftTime(1)}>›</span>
          </div>
          <span className="btn" onClick={() => setSheet('new')}>+ событие</span>
          {shown.length > 1 && (
            <span className="btn-soft btn-sm" onClick={() => setCardsEdit((v) => !v)}
              title="Переместить или поменять ширину карточек">настроить</span>
          )}
        </div>
      </div>

      {/* Bento сетка календаря */}
      <div className="bento">
        {/* Вид «Месяц» */}
        {view === 'month' && (
          <>
            <section className="c s8 r flex flex-col" style={{ '--i': 2, minHeight: '560px', ...cardSt('month') }}>
              {cardCtl('month')}
              <div className="cal2" id="cal2">
                <div className="cal2-head">
                  {'пн вт ср чт пт сб вс'.split(' ').map((w) => (
                    <span className="mono font-semibold" key={w}>{w}</span>
                  ))}
                </div>
                <div className="cal2-grid">
                  {cells.slice(0, cells[35]?.isOut ? 35 : 42).map((c) => (
                    <b
                      key={c.key}
                      className={`${c.isOut ? 'o' : ''} ${c.isToday ? 't' : ''} ${c.isSel && !c.isToday ? 'is-sel' : ''}`}
                      style={{ '--k': c.key }}
                      onClick={() => setSelected(c.date)}
                    >
                      <div className="flex items-center justify-between w-full">
                        <span className="day-num">{c.num}</span>
                        {c.dotsCount > 0 && !c.isToday && (
                          <span className="w-1.5 h-1.5 rounded-full bg-[var(--acc)]"></span>
                        )}
                      </div>
                      {c.events && c.events.length > 0 && (
                        <div className="day-evs">
                          {c.events.slice(0, 2).map((ev, evIdx) => (
                            <span key={ev.id || evIdx} className={`ev-pill ${ev.kind === 'order' ? 'y' : ''}`}>
                              {ev.title}
                            </span>
                          ))}
                          {c.events.length > 2 && (
                            <span className="text-[10px] text-[var(--ink3)] font-medium pl-1">
                              +{c.events.length - 2} ещё
                            </span>
                          )}
                        </div>
                      )}
                    </b>
                  ))}
                </div>
              </div>
              <div className="mt-auto pt-3.5 border-t border-[var(--line)] flex items-center justify-between text-xs text-[var(--ink2)]">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-[var(--acc)] shadow-[0_0_8px_var(--acc)]"></span>
                  <span>Выбранный день: <strong className="text-[var(--ink)] font-semibold">{dayLabel(selected)}, {selected.getDate()} {MONTHS_GEN[selected.getMonth()]}</strong></span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="mono text-[var(--ink3)]">{dayEvents.length} {plural(dayEvents.length, 'событие', 'события', 'событий')}</span>
                  <button type="button" className="btn g !h-7 !px-3 !text-xs" onClick={() => setSheet('new')}>
                    <Plus size={12} /> добавить
                  </button>
                </div>
              </div>
            </section>

            <section className="c s4 r flex flex-col" style={{ '--i': 3, minHeight: '560px', ...cardSt('day') }}>
              {cardCtl('day')}
              <div className="hd">
                <h2>{isSameDay(selected, today) ? 'сегодня' : dayLabel(selected)}</h2>
                <small>{shortDate(selected)} · {dayEvents.length} {plural(dayEvents.length, 'событие', 'события', 'событий')}</small>
              </div>
              <div className="flex-1 overflow-y-auto pr-1 space-y-1">
                {dayEvents.length === 0 ? (
                  <div className="py-12 text-center text-sm text-[var(--ink3)] flex flex-col items-center justify-center gap-2">
                    <span>нет событий на этот день</span>
                    <button type="button" className="btn g !h-8 !px-3.5 !text-xs mt-2" onClick={() => setSheet('new')}>
                      <Plus size={13} /> записать событие
                    </button>
                  </div>
                ) : (
                  dayEvents.map((e) => (
                    <div className="rowi hover:bg-[var(--sf2)] !rounded-xl !px-2.5 transition" key={e.id} onClick={() => setSheet(e)} style={{ cursor: 'pointer' }}>
                      <time className="text-[var(--acc)] font-medium">{hhmm(e.start)}</time>
                      <span className="t">
                        {e.title}
                        {e.sub && <small>{e.sub}</small>}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </section>
          </>
        )}

        {/* Вид «Неделя» */}
        {view === 'week' && (
          <section className="c s12 r" style={{ '--i': 2, ...cardSt('week') }}>
            {cardCtl('week')}
            <div className="hd">
              <h2>расписание на неделю</h2>
              <small>кликните на день или событие для просмотра</small>
            </div>
            {/* на телефоне неделя листается вбок (7 колонок в ряд), на ПК — как обычно */}
            <div className="flex gap-3 mt-4 overflow-x-auto -mx-1 px-1 pb-1 md:mx-0 md:px-0 md:pb-0 md:overflow-visible md:grid md:grid-cols-7">
              {weekDays.map((dayItem) => {
                const isCurrent = dayItem.isToday
                const isPicked = dayItem.isSel
                return (
                  <div
                    key={dayItem.key}
                    onClick={() => setSelected(dayItem.date)}
                    className={`w-[200px] shrink-0 md:w-auto md:shrink rounded-2xl p-3 border transition cursor-pointer flex flex-col min-h-[140px] ${
                      isPicked
                        ? 'border-[var(--acc)] bg-[var(--sf2)] shadow-sm'
                        : isCurrent
                        ? 'border-[var(--acc)]/40 bg-[var(--sf)]'
                        : 'border-[var(--line)] bg-[var(--sf)] hover:border-[var(--ink3)]'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs uppercase font-medium text-[var(--ink2)]">{dayItem.name}</span>
                      <span
                        className={`text-sm font-semibold rounded-full w-6 h-6 flex items-center justify-center ${
                          isCurrent ? 'bg-[var(--acc)] text-white' : ''
                        }`}
                      >
                        {dayItem.num}
                      </span>
                    </div>

                    <div className="flex-1 space-y-1.5 mt-1 overflow-hidden">
                      {dayItem.events.length === 0 ? (
                        <span className="text-[11px] text-[var(--ink3)] italic opacity-60">свободно</span>
                      ) : (
                        dayItem.events.map((ev) => (
                          <div
                            key={ev.id}
                            onClick={(e) => { e.stopPropagation(); setSheet(ev) }}
                            className="p-1.5 rounded-lg text-xs bg-[var(--sf2)] border border-[var(--line)] hover:scale-[1.02] transition"
                            title={ev.title}
                          >
                            <span className="mono text-[10px] text-[var(--ink3)] block">{hhmm(ev.start)}</span>
                            <span className="font-medium truncate block">{ev.title}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* Карточка: Ближайшие события (s12) */}
        <section className="c s12 r" style={{ '--i': 4, ...cardSt('upcoming') }}>
          {cardCtl('upcoming')}
          <div className="hd">
            <h2>ближайшее</h2>
            <small>на 7 дней вперёд · {upcoming.length}</small>
          </div>
          {upcoming.length === 0 ? (
            <p className="py-4 text-center text-sm text-[var(--ink3)]">нет предстоящих событий</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6">
              {upcoming.map((e) => {
                const d = new Date(e.start)
                return (
                  <div className="rowi" key={e.id} onClick={() => setSheet(e)} style={{ cursor: 'pointer' }}>
                    <time>{WD[d.getDay()]} {hhmm(e.start)}</time>
                    <span className="t">
                      {e.title}
                      <small>{shortDate(e.start)}</small>
                    </span>
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
