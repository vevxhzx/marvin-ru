import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Plus, Trash2, MapPin, Repeat, SkipForward, Check, CheckSquare, Briefcase } from 'lucide-react'
import { api, hhmm, MONTHS_NOM, MONTHS, isSameDay, toLocalISO, dayLabel, shortDate, REPEAT_LABELS, WD_SHORT_MON, plural } from '../lib/api'
import { Card, Section, Empty, Sheet, Field, Seg, useToast, PageHead, Swipe, useLeave } from '../components/ui'
import { useRefresh } from '../App'
import DayStrip from '../components/DayStrip'
import TaskSheet from '../components/TaskSheet'
import { OrderSheet } from './Orders'

const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export default function Calendar() {
  const [cursor, setCursor] = useState(() => { const d = new Date(); d.setDate(1); d.setHours(0, 0, 0, 0); return d })
  const [selected, setSelected] = useState(new Date())
  const [events, setEvents] = useState(null)
  const [sheet, setSheet] = useState(null) // null | 'new' | event
  const [taskSheet, setTaskSheet] = useState(null)   // задача из календаря правится на месте, без перехода
  const [orderSheet, setOrderSheet] = useState(null) // дедлайн заказа — тоже
  const openTask = async (e) => { try { setTaskSheet(await api.task(e.task_id)) } catch (er) { show.err(er) } }
  const openOrder = async (e) => { try { setOrderSheet(await api.order(e.order_id)) } catch (er) { show.err(er) } }
  const [view, setView] = useState('month')
  const [, show] = useToast()
  const { tick, bump } = useRefresh()
  const [leaveCls, leave] = useLeave()
  const key = (e) => `${e.id}:${e.start}`
  const del = (e) => leave(key(e), 'leaving', async () => { try { await api.delEvent(e.id); show(e.repeat ? 'Повтор удалён' : 'Событие удалено', '', e.title); await load(); bump() } catch (er) { show.err(er) } })
  const skip = (e) => leave(key(e), 'done', async () => { try { await api.skipEvent(e.id, toLocalISO(e.start)); show('Этот раз пропущен', '', e.title); await load(); bump() } catch (er) { show.err(er) } })
  // задача с дедлайном живёт в календаре как строка с чекбоксом: отметил здесь — закрылась в задачах (одна запись в базе)
  const toggleTask = (e) => leave(key(e), 'done', async () => { try { await (e.done ? api.undoneTask(e.task_id) : api.doneTask(e.task_id)); show(e.done ? 'Вернул в дела' : 'Сделано', '', e.title); await load(); bump() } catch (er) { show.err(er) } })
  // событие — тоже дело: галочка ставится тут, видна в «Делах» и уходит в Google (✓ в названии). Для повтора — только этот раз
  const toggleEvent = (e) => leave(key(e), e.done ? 'leaving' : 'done', async () => { try { await api.doneEvent(e.id, !e.done, toLocalISO(e.start)); if (!e.done) show('Сделано', '', e.title); await load(); bump() } catch (er) { show.err(er) } })
  // дедлайн заказа — строка-ссылка в «Заказы» (сдать / отметить — там же)
  const markDone = (e) => leave(key(e), 'done', async () => { try { await api.updateOrder(e.order_id, { status: 'done' }); show('Заказ сдан', '', e.title); await load(); bump() } catch (er) { show.err(er) } })
  const rowOf = (e, compact) => e.kind === 'order' ? (
    <Swipe key={key(e)} onRight={() => markDone(e)} rightLabel="сдан" rightIcon={<Check size={18} strokeWidth={2.6} />}>
      <OrderRow e={e} onDone={() => markDone(e)} onOpen={() => openOrder(e)} compact={compact} extra={leaveCls(key(e))} />
    </Swipe>
  ) : e.kind === 'task' ? (
    <Swipe key={key(e)} onRight={() => toggleTask(e)} rightLabel={e.done ? 'вернуть' : 'сделано'} rightIcon={<Check size={18} strokeWidth={2.6} />}>
      <TaskRow e={e} onToggle={() => toggleTask(e)} onOpen={() => openTask(e)} compact={compact} extra={leaveCls(key(e))} />
    </Swipe>
  ) : (
    <Swipe key={key(e)} onLeft={() => del(e)} onRight={() => toggleEvent(e)} leftLabel={e.repeat ? 'все повторы' : 'удалить'} rightLabel={e.done ? 'вернуть' : 'сделано'} rightIcon={<Check size={18} strokeWidth={2.6} />}>
      <EventRow e={e} onClick={() => setSheet(e)} onToggle={() => toggleEvent(e)} compact={compact} extra={leaveCls(key(e))} />
    </Swipe>
  )

  const range = useMemo(() => {
    const start = new Date(cursor); start.setDate(1 - ((cursor.getDay() + 6) % 7) - 7)
    const end = new Date(start); end.setDate(start.getDate() + 7 * 8)
    return [start, end]
  }, [cursor])

  const load = () => api.events(toLocalISO(range[0]), toLocalISO(range[1]), true).then(setEvents).catch(() => setEvents([]))
  useEffect(() => { load() }, [range, tick])

  const cells = useMemo(() => {
    const first = new Date(cursor)
    const offset = (first.getDay() + 6) % 7
    const start = new Date(first); start.setDate(1 - offset)
    return Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d })
  }, [cursor])

  const evs = events || []
  const byDay = (d) => evs.filter((e) => isSameDay(e.start, d) && !(e.kind === 'task' && e.done && !isSameDay(e.start, today))).sort((a, b) => new Date(a.start) - new Date(b.start))
  const dayEvents = byDay(selected)
  const today = new Date()
  const isToday = isSameDay(selected, today)
  const shift = (n) => { const d = new Date(cursor); d.setMonth(d.getMonth() + n); setCursor(d) }
  const goToday = () => { const d = new Date(); setSelected(d); const c = new Date(d); c.setDate(1); c.setHours(0, 0, 0, 0); setCursor(c) }
  const weekDays = useMemo(() => { const s = new Date(selected); s.setDate(selected.getDate() - ((selected.getDay() + 6) % 7)); return Array.from({ length: 7 }, (_, i) => { const d = new Date(s); d.setDate(s.getDate() + i); return d }) }, [selected])
  // ближайшее: 7 дней от сегодня, кроме выбранного дня
  const upcoming = useMemo(() => { const lim = new Date(today); lim.setDate(lim.getDate() + 7); return evs.filter((e) => new Date(e.start) > today && new Date(e.start) < lim && !isSameDay(e.start, selected)).sort((a, b) => new Date(a.start) - new Date(b.start)).slice(0, 6) }, [evs, selected])

  // ←/→ — дни, T — сегодня (когда фокус не в поле ввода)
  useEffect(() => {
    const h = (e) => {
      if (sheet || ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName) || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { const d = new Date(selected); d.setDate(d.getDate() + (e.key === 'ArrowLeft' ? -1 : 1)); setSelected(d); if (d.getMonth() !== cursor.getMonth()) { const c = new Date(d); c.setDate(1); c.setHours(0, 0, 0, 0); setCursor(c) } }
      else if (e.key === 't' || e.key === 'е') goToday()
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [selected, cursor, sheet])

  return (
    <div className="space-y-6">
      <PageHead kicker={String(cursor.getFullYear())} title={MONTHS_NOM[cursor.getMonth()].toLowerCase()} idx={cursor.getMonth() + 1}
        right={<>
          <Seg value={view} onChange={setView} options={[['month', 'месяц'], ['week', 'неделя']]} />
          <div className="nav-group-btn">
            <button className="btn-icon outlined" onClick={() => shift(-1)} aria-label="Предыдущий месяц"><ChevronLeft size={16} /></button>
            <button className={`btn-ghost !px-3 ${isToday && cursor.getMonth() === today.getMonth() ? 'opacity-50' : ''}`} onClick={goToday} data-tip="клавиша T">сегодня</button>
            <button className="btn-icon outlined" onClick={() => shift(1)} aria-label="Следующий месяц"><ChevronRight size={16} /></button>
          </div>
          <button className="btn-primary head-primary" onClick={() => setSheet('new')}><Plus size={15} /> событие</button>
        </>} />

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[1.3fr_1fr] lg:gap-10">
        <div className="order-2 space-y-8 lg:order-1">
          {view === 'month' ? (
            <div className="animate-rise">
              <div className="mb-1 grid grid-cols-7 text-center">{WD.map((w, i) => <div key={w} className={`label !text-[10.5px] py-1 ${i > 4 ? 'neg opacity-70' : ''}`}>{w}</div>)}</div>
              <div className="grid grid-cols-7 gap-1">
                {cells.map((d) => {
                  const list = byDay(d), inMonth = d.getMonth() === cursor.getMonth(), isT = isSameDay(d, today), isS = isSameDay(d, selected)
                  return (
                    <button key={d.toISOString()} onClick={() => { setSelected(d); if (!inMonth) { const c = new Date(d); c.setDate(1); setCursor(c) } }}
                      className={`relative flex aspect-square flex-col items-center justify-start rounded-xl pt-1.5 transition sm:aspect-[1/0.85] ${isS ? 'fill' : 'hover:bg-[var(--fill)]'} ${inMonth ? '' : 'opacity-30'}`} style={isS ? { boxShadow: 'inset 0 0 0 1px var(--line-2)' } : {}}>
                      <span className={`num grid h-7 w-7 place-items-center rounded-full text-[13.5px] font-medium ${isT ? 'bg-accent text-accent-ink' : ''}`}>{d.getDate()}</span>
                      <div className="mt-auto mb-1.5 flex gap-0.5">
                        {list.slice(0, 3).map((e) => <i key={e.id + e.start} className={`h-1.5 w-1.5 rounded-full ${e.kind === 'task' ? 'border border-[var(--accent)]' : e.kind === 'order' ? 'bg-[var(--warn)]' : 'bg-accent'}`} style={e.kind === 'task' && e.done ? { opacity: .4 } : {}} />)}
                        {list.length > 3 && <span className="faint text-[9px] leading-none">+{list.length - 3}</span>}
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          ) : (
            <Card className="animate-rise !p-0 overflow-hidden">
              <div className="grid grid-cols-7 border-b hair">
                {weekDays.map((d) => (
                  <button key={d.toISOString()} onClick={() => setSelected(d)} className={`flex flex-col items-center py-3 transition ${isSameDay(d, selected) ? 'fill' : ''}`}>
                    <span className="label !text-[10.5px]">{WD[(d.getDay() + 6) % 7]}</span>
                    <span className={`num mt-1 grid h-8 w-8 place-items-center rounded-full text-[15px] font-semibold ${isSameDay(d, today) ? 'bg-accent text-accent-ink' : ''}`}>{d.getDate()}</span>
                  </button>
                ))}
              </div>
              <div className="scroll-thin max-h-[calc(60vh/var(--ui-zoom))] overflow-y-auto">
                {weekDays.map((d) => {
                  const list = byDay(d); if (!list.length) return null
                  return (
                    <div key={d.toISOString()} className="px-4 py-3 border-b hair last:border-0">
                      <div className="label mb-1">{dayLabel(d)}, {d.getDate()} {MONTHS[d.getMonth()]}</div>
                      {list.map((e) => rowOf(e, true))}
                    </div>
                  )
                })}
                {weekDays.every((d) => !byDay(d).length) && <Empty glyph="calendar" text="На этой неделе пусто" hint="встреча в среду в 15" />}
              </div>
            </Card>
          )}

          {upcoming.length > 0 && (
            <Section title="ближайшее" idx={upcoming.length} hint="7 дней">
              <div className="rule">
                {upcoming.map((e) => (
                  <button key={key(e)} className="row row-hover w-full text-left" onClick={() => setSelected(new Date(e.start))}>
                    <span className="muted num w-[116px] shrink-0 text-[13px]">{dayLabel(e.start).toLowerCase()}, {hhmm(e.start)}</span>
                    <span className={`truncate text-[14.5px] font-medium ${e.done ? 'line-through opacity-50' : ''}`}>{e.title}</span>
                    {e.kind === 'task' && <CheckSquare size={12} className="faint shrink-0" />}
                    {e.kind === 'order' && <Briefcase size={12} className="faint shrink-0" />}
                    {e.repeat && <Repeat size={12} className="faint shrink-0" />}
                  </button>
                ))}
              </div>
            </Section>
          )}
        </div>

        {/* день: таймлайн с линией «сейчас»; на телефоне — сразу под шапкой */}
        <Section className="order-1 lg:order-2" title={dayLabel(selected).toLowerCase()} idx={selected.getDate()}
          hint={dayHint(selected, dayEvents)}
          action={<button className="btn-ghost btn-sm" onClick={() => setSheet('new')}><Plus size={14} /> в этот день</button>}>
          {events === null ? <div className="fill h-40 animate-pulseSoft rounded-2xl" /> : dayEvents.length === 0 ? (
            <div className="rule"><Empty glyph="calendar" text={isToday ? 'Сегодня свободно' : 'Ничего не запланировано'} sub={isToday ? 'Подозрительно спокойно, сэр' : 'День свободен'} hint={isToday ? 'ужин в 7 вечера' : `встреча ${selected.getDate()} ${MONTHS[selected.getMonth()]} в 15`} /></div>
          ) : (
            <>
              <DayStrip list={dayEvents} isToday={isToday} onPick={(e) => (e.kind === 'task' ? openTask(e) : e.kind === 'order' ? openOrder(e) : setSheet(e))} />
              <DayTimeline list={dayEvents} isToday={isToday} rowOf={rowOf} />
            </>
          )}
        </Section>
      </div>

      <EventSheet open={!!sheet} ev={sheet === 'new' ? null : sheet} day={selected} onClose={() => setSheet(null)}
        onDone={(msg) => { setSheet(null); show(msg); load(); bump() }} onErr={show.err} />
      <TaskSheet open={!!taskSheet} task={taskSheet} onClose={() => setTaskSheet(null)} onDone={(msg) => { setTaskSheet(null); show(msg); load(); bump() }} onErr={show.err} />
      <OrderSheet open={!!orderSheet} order={orderSheet} onClose={() => setOrderSheet(null)} onDone={(msg) => { setOrderSheet(null); show(msg); load(); bump() }} onErr={show.err} />
    </div>
  )
}

/* Список дня + линия текущего времени (только для сегодня): всё выше неё — прошло, ниже — впереди.
   Чтобы линия не выглядела «пустой полоской», она подписана и показывает, сколько до ближайшего события. */
function DayTimeline({ list, isToday, rowOf }) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { if (!isToday) return; const t = setInterval(() => setNow(new Date()), 60000); return () => clearInterval(t) }, [isToday])
  let placed = !isToday
  const out = []
  list.forEach((e, i) => {
    if (!placed && new Date(e.start) > now) { out.push(<NowLine key="now" now={now} next={e} first={i === 0} />); placed = true }
    out.push(rowOf(e))
  })
  if (!placed) out.push(<NowLine key="now" now={now} next={null} />)
  return <div className="rule stagger">{out}</div>
}
const untilText = (ms) => {
  const m = Math.max(1, Math.round(ms / 60000))
  if (m < 60) return `через ${m} мин`
  const h = Math.floor(m / 60), r = m % 60
  return r ? `через ${h} ч ${r} мин` : `через ${h} ч`
}
function NowLine({ now, next, first }) {
  const hint = next ? `${first ? 'первое' : 'дальше'} — ${untilText(new Date(next.start) - now)}` : 'на сегодня всё'
  return (
    <div className="relative flex items-center gap-2 py-1.5" aria-label="сейчас">
      <span className="num neg shrink-0 text-[11px] font-medium">{hhmm(now)}</span>
      <span className="relative h-[2px] flex-1 rounded-full" style={{ background: 'var(--neg)', opacity: .85 }}><span className="absolute -left-1 -top-[3px] h-2 w-2 rounded-full" style={{ background: 'var(--neg)' }} /></span>
      <span className="faint shrink-0 text-[11px]">сейчас · {hint}</span>
    </div>
  )
}

function EventRow({ e, onClick, onToggle, compact, extra = '' }) {
  const now = new Date()
  const past = e.end && new Date(e.end) < now
  const live = !e.done && new Date(e.start) <= now && e.end && new Date(e.end) >= now
  const checked = e.done || extra.includes('leaving-done')
  return (
    <div className={`row row-slide row-hover group ${past || e.done ? 'opacity-50' : ''} ${compact ? '!py-2 !border-0' : ''} ${extra}`}>
      <div className="w-12 shrink-0"><div className="num text-[14.5px] font-semibold">{hhmm(e.start)}</div>{e.end && !compact && <div className="faint num text-[11px]">{hhmm(e.end)}</div>}</div>
      {/* галочка появляется у события, когда до него меньше суток или оно уже идёт/прошло — раньше отмечать нечего */}
      {(checked || new Date(e.start) - now < 864e5) && onToggle
        ? <button onClick={onToggle} aria-label={e.done ? 'Вернуть' : 'Сделано'} className={`grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full border transition-all duration-300 hover:scale-110 active:scale-90 ${checked ? 'border-accent bg-accent text-accent-ink' : 'hover:border-accent'}`} style={checked ? {} : { borderColor: 'var(--line-2)' }}>
            {checked ? <Check size={13} strokeWidth={3} className="check-pop" /> : <Check size={12} className="opacity-0 transition group-hover:opacity-40" />}
          </button>
        : <div className={`h-8 w-[3px] shrink-0 rounded-full ${live ? 'bg-green' : 'bg-accent'}`} />}
      <button onClick={onClick} className="min-w-0 flex-1 text-left">
        <div className={`flex items-center gap-1.5 truncate text-[14.5px] font-medium ${e.done ? 'line-through' : ''}`}>{e.title}{e.repeat && <Repeat size={12} className="faint shrink-0" />}</div>
        {(e.location || e.repeat) && <div className="muted flex items-center gap-1 truncate text-[12px]">{e.location && <><MapPin size={11} />{e.location}</>}{e.repeat && <span className="faint">{e.location ? ' · ' : ''}{e.repeat_label}</span>}</div>}
      </button>
      {live ? <span className="badge pos">сейчас</span> : <ChevronRight size={15} className="faint" />}
    </div>
  )
}

function dayHint(selected, list) {
  const n = (k) => list.filter((e) => e.kind === k).length
  const ev = list.filter((e) => e.kind !== 'task' && e.kind !== 'order').length
  const parts = []
  if (ev) parts.push(`${ev} ${plural(ev, 'событие', 'события', 'событий')}`)
  if (n('task')) parts.push(`${n('task')} ${plural(n('task'), 'задача', 'задачи', 'задач')}`)
  if (n('order')) parts.push(`${n('order')} ${plural(n('order'), 'дедлайн', 'дедлайна', 'дедлайнов')}`)
  return `${selected.getDate()} ${MONTHS[selected.getMonth()]}${parts.length ? ' · ' + parts.join(' · ') : ''}`
}

function OrderRow({ e, onDone, onOpen, compact, extra = '' }) {
  const past = new Date(e.start) < new Date()
  const overdue = past && e.status !== 'review'   // на правках после срока — сдано, идут правки: не краснеем
  return (
    <div className={`row row-slide row-hover ${compact ? '!py-2 !border-0' : ''} ${extra}`}>
      <div className="w-12 shrink-0"><div className={`num text-[14.5px] font-semibold ${e.all_day ? 'faint !text-[11px] !font-medium' : ''}`}>{e.all_day ? 'день' : hhmm(e.start)}</div>{!compact && <div className="faint text-[11px]">заказ</div>}</div>
      <button onClick={onDone} aria-label="Сдан" data-tip="сдан" className="grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full border transition-all duration-300 hover:scale-110 hover:border-accent active:scale-90" style={{ borderColor: overdue ? 'var(--neg)' : 'var(--line-2)' }}>
        <Briefcase size={11} className="faint" />
      </button>
      <button onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className="truncate text-[14.5px] font-medium">{e.title}</div>
        {overdue && <div className="neg text-[12px]">дедлайн прошёл</div>}
        {past && !overdue && <div className="muted text-[12px]">на правках · срок был {shortDate(e.start).toLowerCase()}</div>}
      </button>
      <ChevronRight size={15} className="faint" />
    </div>
  )
}

function TaskRow({ e, onToggle, onOpen, compact, extra = '' }) {
  const overdue = !e.done && new Date(e.start) < new Date()
  return (
    <div className={`row row-slide row-hover ${compact ? '!py-2 !border-0' : ''} ${extra}`}>
      <div className="w-12 shrink-0"><div className={`num text-[14.5px] font-semibold ${e.all_day ? 'faint !text-[11px] !font-medium' : ''}`}>{e.all_day ? 'день' : hhmm(e.start)}</div>{!compact && <div className="faint text-[11px]">{e.all_day || !e.end ? 'задача' : <span className="num">{hhmm(e.end)}</span>}</div>}</div>
      <button onClick={onToggle} aria-label={e.done ? 'Вернуть' : 'Выполнено'} className={`grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full border transition-all duration-300 hover:scale-110 active:scale-90 ${e.done ? 'border-accent bg-accent text-accent-ink' : 'hover:border-accent'}`} style={e.done ? {} : { borderColor: e.priority === 1 ? 'var(--neg)' : 'var(--line-2)' }}>
        {e.done && <Check size={13} strokeWidth={3} />}
      </button>
      <button onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className={`truncate text-[14.5px] font-medium ${e.done ? 'line-through opacity-50' : ''}`}>{e.title}</div>
        {overdue && <div className="neg text-[12px]">просрочено</div>}
      </button>
      <ChevronRight size={15} className="faint" />
    </div>
  )
}

export function EventSheet({ open, ev, day, onClose, onDone, onErr }) {
  const [f, setF] = useState({})
  useEffect(() => {
    if (!open) return
    if (ev) setF({ title: ev.title, start: toLocalISO(ev.start), duration_min: ev.end ? Math.round((new Date(ev.end) - new Date(ev.start)) / 60000) : 60, location: ev.location || '', notes: ev.notes || '', remind_minutes: ev.remind_minutes ?? 30,
      repeat: ev.repeat || '', repeat_days: (ev.repeat_days || '').split(',').filter(Boolean).map(Number), repeat_until: ev.repeat_until ? toLocalISO(ev.repeat_until).slice(0, 10) : '', occurrence: ev.start })
    else { const d = new Date(day); const n = new Date(); d.setHours(isSameDay(d, n) ? n.getHours() + 1 : 10, 0, 0, 0); setF({ title: '', start: toLocalISO(d), duration_min: 60, location: '', notes: '', remind_minutes: 30, repeat: '', repeat_days: [], repeat_until: '' }) }
  }, [open, ev, day])
  const submit = async (e) => {
    e.preventDefault()
    const body = { title: f.title, start: f.start, duration_min: Number(f.duration_min), remind_minutes: Number(f.remind_minutes), location: f.location || null, notes: f.notes || null,
      repeat: f.repeat || '', repeat_days: f.repeat === 'weekly' ? f.repeat_days : [], repeat_until: f.repeat_until ? f.repeat_until + 'T23:59' : null }
    // у повторяющегося события start — дата ПЕРВОГО повтора; если правили конкретное вхождение, сдвигаем только время
    if (ev && ev.repeat && f.occurrence && f.start !== toLocalISO(f.occurrence)) {
      const orig = new Date(ev.start), nw = new Date(f.start)
      const sameDay = toLocalISO(nw).slice(0, 10) === toLocalISO(orig).slice(0, 10)
      if (sameDay) { const base = new Date(ev.repeat_anchor || ev.start); base.setHours(nw.getHours(), nw.getMinutes(), 0, 0); body.start = toLocalISO(base) }
    }
    try { if (ev) await api.updateEvent(ev.id, body); else await api.addEvent(body); onDone(ev ? 'Событие обновлено' : 'Событие добавлено') } catch (err) { onErr?.(err) }
  }
  const toggleDay = (i) => setF((x) => ({ ...x, repeat_days: x.repeat_days.includes(i) ? x.repeat_days.filter((d) => d !== i) : [...x.repeat_days, i].sort() }))
  return (
    <Sheet open={open} onClose={onClose} title={ev ? 'событие' : 'новое событие'}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Название"><input autoFocus className="input !text-[18px] !font-medium" placeholder="Встреча с…" value={f.title || ''} onChange={(e) => setF({ ...f, title: e.target.value })} required /></Field>
        <div className="grid grid-cols-[1fr_auto] gap-3 sm:grid-cols-[1fr_130px]">
          <Field label="Начало" className="min-w-0"><input type="datetime-local" className="input" value={f.start || ''} onChange={(e) => setF({ ...f, start: e.target.value })} required /></Field>
          <Field label="Длительность" className="w-[104px] sm:w-auto">
            <select className="input" value={f.duration_min} onChange={(e) => setF({ ...f, duration_min: e.target.value })}>{[15, 30, 45, 60, 90, 120, 180, 240, 480].map((m) => <option key={m} value={m}>{m < 60 ? `${m} мин` : `${m / 60} ч`}</option>)}</select>
          </Field>
        </div>
        <Field label="Место"><input className="input" placeholder="Адрес, Zoom, кафе…" value={f.location || ''} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        <Field label="Напомнить за">
          <div className="flex flex-wrap gap-1.5">{[0, 10, 30, 60, 180, 1440].map((m) => <button type="button" key={m} onClick={() => setF({ ...f, remind_minutes: m })} className={`chip !py-1.5 ${Number(f.remind_minutes) === m ? 'on' : ''}`}>{m === 0 ? 'в момент' : m < 60 ? `${m} мин` : m < 1440 ? `${m / 60} ч` : 'день'}</button>)}</div>
        </Field>
        <Field label="Повтор">
          <div className="flex flex-wrap gap-1.5">{Object.entries(REPEAT_LABELS).map(([v, l]) => <button type="button" key={v} onClick={() => setF({ ...f, repeat: v, repeat_days: v === 'weekly' && !f.repeat_days?.length ? [(new Date(f.start).getDay() + 6) % 7] : f.repeat_days })} className={`chip !py-1.5 ${(f.repeat || '') === v ? 'on' : ''}`}>{l}</button>)}</div>
          {f.repeat === 'weekly' && (
            <div className="mt-2 flex gap-1">{WD_SHORT_MON.map((w, i) => <button type="button" key={w} onClick={() => toggleDay(i)} className={`num grid h-9 w-9 place-items-center rounded-full text-[13px] font-medium transition ${f.repeat_days?.includes(i) ? 'bg-accent text-accent-ink' : 'fill'}`}>{w}</button>)}</div>
          )}
          {f.repeat && <div className="mt-2 flex items-center gap-2"><span className="faint text-[12px]">до</span><input type="date" className="input !w-auto !py-1.5" value={f.repeat_until || ''} onChange={(e) => setF({ ...f, repeat_until: e.target.value })} /><span className="faint text-[12px]">(пусто — бессрочно)</span></div>}
        </Field>
        <Field label="Заметки"><textarea className="input min-h-[70px]" value={f.notes || ''} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <div className="flex gap-2">
          {ev && <button type="button" className="btn-ghost !px-3.5 neg" title={ev.repeat ? 'Удалить все повторы' : 'Удалить'} onClick={async () => { await api.delEvent(ev.id); onDone(ev.repeat ? 'Повтор удалён' : 'Событие удалено') }}><Trash2 size={15} /></button>}
          {ev && ev.repeat && <button type="button" className="btn-ghost" title="Пропустить только этот раз" onClick={async () => { await api.skipEvent(ev.id, toLocalISO(ev.start)); onDone('Этот раз пропущен') }}>пропустить раз</button>}
          {ev && <button type="button" className="btn-ghost" onClick={async () => { await api.doneEvent(ev.id, !ev.done, toLocalISO(ev.start)); onDone(ev.done ? 'Снова в планах' : 'Сделано') }}><Check size={14} /> {ev.done ? 'вернуть' : 'сделано'}</button>}
          <button className="btn-primary btn-lg flex-1">{ev ? 'сохранить' : 'добавить'}</button>
        </div>
      </form>
    </Sheet>
  )
}
