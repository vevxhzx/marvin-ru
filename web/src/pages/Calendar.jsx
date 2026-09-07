import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Plus, Trash2, MapPin, Repeat, SkipForward } from 'lucide-react'
import { api, hhmm, MONTHS_NOM, MONTHS, isSameDay, toLocalISO, dayLabel, REPEAT_LABELS, WD_SHORT_MON } from '../lib/api'
import { Card, Section, Empty, Sheet, Field, Seg, useToast, Toast, PageHead, Swipe, useLeave } from '../components/ui'
import { useRefresh } from '../App'

const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

export default function Calendar() {
  const [cursor, setCursor] = useState(() => { const d = new Date(); d.setDate(1); d.setHours(0, 0, 0, 0); return d })
  const [selected, setSelected] = useState(new Date())
  const [events, setEvents] = useState([])
  const [sheet, setSheet] = useState(null) // null | 'new' | event
  const [view, setView] = useState('month')
  const [toast, show] = useToast()
  const { tick, bump } = useRefresh()
  const [leaveCls, leave] = useLeave()
  // свайп влево — удалить (у повтора — все повторы), свайп вправо у повтора — пропустить только этот раз
  const key = (e) => `${e.id}:${e.start}`
  const del = (e) => leave(key(e), 'leaving', async () => { try { await api.delEvent(e.id); show(e.repeat ? 'Повтор удалён' : 'Событие удалено'); await load(); bump() } catch (er) { show(er.message || 'Ошибка', 'err') } })
  const skip = (e) => leave(key(e), 'done', async () => { try { await api.skipEvent(e.id, toLocalISO(e.start)); show('Этот раз пропущен'); await load(); bump() } catch (er) { show(er.message || 'Ошибка', 'err') } })
  const rowOf = (e, compact) => (
    <Swipe key={key(e)} onLeft={() => del(e)} onRight={e.repeat ? () => skip(e) : undefined} leftLabel={e.repeat ? 'все повторы' : 'удалить'} rightLabel="пропустить" rightIcon={<SkipForward size={18} strokeWidth={2.4} />}>
      <EventRow e={e} onClick={() => setSheet(e)} compact={compact} extra={leaveCls(key(e))} />
    </Swipe>
  )

  const range = useMemo(() => {
    const start = new Date(cursor); start.setDate(1 - ((cursor.getDay() + 6) % 7) - 7)
    const end = new Date(start); end.setDate(start.getDate() + 7 * 8)
    return [start, end]
  }, [cursor])

  const load = () => api.events(toLocalISO(range[0]), toLocalISO(range[1])).then(setEvents).catch(() => {})
  useEffect(() => { load() }, [range, tick])

  const cells = useMemo(() => {
    const first = new Date(cursor)
    const offset = (first.getDay() + 6) % 7
    const start = new Date(first); start.setDate(1 - offset)
    return Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d })
  }, [cursor])

  const byDay = (d) => events.filter((e) => isSameDay(e.start, d)).sort((a, b) => new Date(a.start) - new Date(b.start))
  const dayEvents = byDay(selected)
  const today = new Date()
  const shift = (n) => { const d = new Date(cursor); d.setMonth(d.getMonth() + n); setCursor(d) }
  const weekDays = useMemo(() => { const s = new Date(selected); s.setDate(selected.getDate() - ((selected.getDay() + 6) % 7)); return Array.from({ length: 7 }, (_, i) => { const d = new Date(s); d.setDate(s.getDate() + i); return d }) }, [selected])

  return (
    <div className="space-y-6">
      <PageHead kicker={String(cursor.getFullYear())} title={MONTHS_NOM[cursor.getMonth()].toLowerCase()} idx={cursor.getMonth() + 1}
        right={<>
          <Seg value={view} onChange={setView} options={[['month', 'месяц'], ['week', 'неделя']]} />
          <div className="flex gap-1">
            <button className="btn-icon" onClick={() => shift(-1)}><ChevronLeft size={16} /></button>
            <button className="btn-ghost !px-3" onClick={() => { const d = new Date(); setSelected(new Date(d)); const c = new Date(d); c.setDate(1); c.setHours(0, 0, 0, 0); setCursor(c) }}>сегодня</button>
            <button className="btn-icon" onClick={() => shift(1)}><ChevronRight size={16} /></button>
          </div>
          <button className="btn-primary" onClick={() => setSheet('new')}><Plus size={15} /> <span className="hidden sm:inline">событие</span></button>
        </>} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
        {view === 'month' ? (
          <Card className="animate-rise !p-3 sm:!p-4 self-start">
            <div className="mb-1 grid grid-cols-7 text-center">{WD.map((w, i) => <div key={w} className={`label !text-[11px] py-1 ${i > 4 ? 'text-red/70' : ''}`}>{w}</div>)}</div>
            <div className="grid grid-cols-7 gap-1">
              {cells.map((d) => {
                const evs = byDay(d), inMonth = d.getMonth() === cursor.getMonth(), isT = isSameDay(d, today), isS = isSameDay(d, selected)
                return (
                  <button key={d.toISOString()} onClick={() => { setSelected(d); if (!inMonth) { const c = new Date(d); c.setDate(1); setCursor(c) } }}
                    className={`relative flex aspect-square flex-col items-center justify-start rounded-2xl pt-1.5 transition sm:aspect-[1/0.9] ${isS ? 'fill' : 'hover:bg-[var(--fill)]'} ${inMonth ? '' : 'opacity-30'}`}>
                    <span className={`num grid h-7 w-7 place-items-center rounded-full text-[14px] font-medium ${isT ? 'bg-accent text-white' : ''}`}>{d.getDate()}</span>
                    <div className="mt-auto mb-1.5 flex gap-0.5">
                      {evs.slice(0, 3).map((e) => <i key={e.id + e.start} className="h-1.5 w-1.5 rounded-full bg-accent" />)}
                      {evs.length > 3 && <span className="faint text-[9px] leading-none">+{evs.length - 3}</span>}
                    </div>
                  </button>
                )
              })}
            </div>
          </Card>
        ) : (
          <Card className="animate-rise !p-0 overflow-hidden">
            <div className="grid grid-cols-7 border-b hair">
              {weekDays.map((d) => (
                <button key={d.toISOString()} onClick={() => setSelected(d)} className={`flex flex-col items-center py-3 transition ${isSameDay(d, selected) ? 'fill' : ''}`}>
                  <span className="label !text-[11px]">{WD[(d.getDay() + 6) % 7]}</span>
                  <span className={`num mt-1 grid h-8 w-8 place-items-center rounded-full text-[15px] font-semibold ${isSameDay(d, today) ? 'bg-accent text-white' : ''}`}>{d.getDate()}</span>
                </button>
              ))}
            </div>
            <div className="scroll-thin max-h-[60vh] overflow-y-auto">
              {weekDays.map((d) => {
                const evs = byDay(d); if (!evs.length) return null
                return (
                  <div key={d.toISOString()} className="px-4 py-3 border-b hair last:border-0">
                    <div className="label mb-1">{dayLabel(d)}, {d.getDate()} {MONTHS[d.getMonth()]}</div>
                    {evs.map((e) => rowOf(e, true))}
                  </div>
                )
              })}
              {weekDays.every((d) => !byDay(d).length) && <Empty glyph="calendar" text="На этой неделе пусто" hint="встреча в среду в 15" />}
            </div>
          </Card>
        )}

        <Section title={dayLabel(selected).toLowerCase()} idx={selected.getDate()}
          hint={`${selected.getDate()} ${MONTHS[selected.getMonth()]}`}
          action={<button className="btn-ghost !py-1.5 !text-[13px]" onClick={() => setSheet('new')}><Plus size={14} /> в этот день</button>}>
          <div className="rule">
            {dayEvents.length === 0 ? <Empty glyph="calendar" text="Ничего не запланировано" sub="День свободен" hint="ужин в 7 вечера" /> : dayEvents.map((e) => rowOf(e))}
          </div>
        </Section>
      </div>

      <EventSheet open={!!sheet} ev={sheet === 'new' ? null : sheet} day={selected} onClose={() => setSheet(null)}
        onDone={(msg) => { setSheet(null); show(msg); load(); bump() }} />
      <Toast msg={toast.msg} kind={toast.kind} />
    </div>
  )
}

function EventRow({ e, onClick, compact, extra = '' }) {
  const past = e.end && new Date(e.end) < new Date()
  return (
    <button onClick={onClick} className={`row row-slide w-full text-left ${past ? 'opacity-50' : ''} ${compact ? '!py-2 !border-0' : ''} ${extra}`}>
      <div className="w-14 shrink-0"><div className="num text-[15px] font-medium">{hhmm(e.start)}</div>{e.end && !compact && <div className="faint num text-[11px]">{hhmm(e.end)}</div>}</div>
      <div className="h-9 w-[2px] shrink-0 rounded-full bg-accent" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 truncate text-[15px] font-medium">{e.title}{e.repeat && <Repeat size={12} className="faint shrink-0" />}</div>
        {(e.location || e.repeat) && <div className="muted flex items-center gap-1 truncate text-[12px]">{e.location && <><MapPin size={11} />{e.location}</>}{e.repeat && <span className="faint">{e.location ? ' · ' : ''}{e.repeat_label}</span>}</div>}
      </div>
      <ChevronRight size={16} className="faint" />
    </button>
  )
}

function EventSheet({ open, ev, day, onClose, onDone }) {
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
    if (ev) await api.updateEvent(ev.id, body); else await api.addEvent(body)
    onDone(ev ? 'Событие обновлено' : 'Событие добавлено')
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
            <div className="mt-2 flex gap-1">{WD_SHORT_MON.map((w, i) => <button type="button" key={w} onClick={() => toggleDay(i)} className={`num grid h-9 w-9 place-items-center rounded-full text-[13px] font-medium transition ${f.repeat_days?.includes(i) ? 'bg-accent text-white' : 'fill'}`}>{w}</button>)}</div>
          )}
          {f.repeat && <div className="mt-2 flex items-center gap-2"><span className="faint text-[12px]">до</span><input type="date" className="input !w-auto !py-1.5" value={f.repeat_until || ''} onChange={(e) => setF({ ...f, repeat_until: e.target.value })} /><span className="faint text-[12px]">(пусто — бессрочно)</span></div>}
        </Field>
        <Field label="Заметки"><textarea className="input min-h-[70px]" value={f.notes || ''} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <div className="flex gap-2">
          {ev && <button type="button" className="btn-icon !h-auto !w-auto !px-3.5 !text-red" title={ev.repeat ? 'Удалить все повторы' : 'Удалить'} onClick={async () => { await api.delEvent(ev.id); onDone(ev.repeat ? 'Повтор удалён' : 'Событие удалено') }}><Trash2 size={15} /></button>}
          {ev && ev.repeat && <button type="button" className="btn-ghost" title="Пропустить только этот раз" onClick={async () => { await api.skipEvent(ev.id, toLocalISO(ev.start)); onDone('Этот раз пропущен') }}>пропустить раз</button>}
          <button className="btn-primary flex-1 !py-3">{ev ? 'сохранить' : 'добавить'}</button>
        </div>
      </form>
    </Sheet>
  )
}
