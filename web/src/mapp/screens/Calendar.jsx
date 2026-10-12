/* MCalendar — мобильный календарь. Только живые данные через lib/api.js:
 * GET /api/events?start&end&tasks_too (события + задачи + дедлайны заказов),
 * POST/PUT/DELETE /api/events, POST /api/events/:id/done.
 * Кит из ../ui.jsx, стили m-*. */
import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, MapPin, Plus, Sparkles, Video } from 'lucide-react'
import { api, hhmm, isAllDay, isSameDay, shortDate, toLocalISO } from '../../lib/api'
import { localeOf, useI18n } from '../../lib/i18n'
import { Card, IconBtn, Overline, ScreenTitle, Segmented, TaskCheck } from '../ui.jsx'

const KIND_OF = { event: 'work', task: 'personal', order: 'money' }
const KIND_COLOR = { work: '#7d95ff', personal: '#c9a7ff', money: '#ffc24d', deadline: '#ff5c7a' }

const day0 = (d = new Date()) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x }
const wdIndex = (d) => (d.getDay() + 6) % 7
const toH = (s) => { const t = new Date(s); return t.getHours() + t.getMinutes() / 60 }
const isOverdue = (e, t0) => !e.done && new Date(e.start) < t0

export default function MCalendar() {
  const { t } = useI18n()
  const [today] = useState(() => new Date())
  const [mode, setMode] = useState('month')
  const [cursor, setCursor] = useState(() => { const d = new Date(); d.setDate(1); d.setHours(0, 0, 0, 0); return d })
  const [sel, setSel] = useState(() => new Date())
  const [hidden, setHidden] = useState([])
  const [events, setEvents] = useState(null)
  const [err, setErr] = useState(null)
  const [sheet, setSheet] = useState(null) // 'new' | event object
  const [toastMsg, setToastMsg] = useState(null)

  const t0 = useMemo(() => day0(today), [today])
  const y = cursor.getFullYear()
  const m = cursor.getMonth()
  const startOffset = wdIndex(new Date(y, m, 1))
  const daysIn = new Date(y, m + 1, 0).getDate()
  const rows = Math.ceil((startOffset + daysIn) / 7)
  const cells = useMemo(
    () => Array.from({ length: rows * 7 }, (_, i) => new Date(y, m, 1 - startOffset + i)),
    [y, m, startOffset, rows],
  )
  const weekStart = useMemo(() => addDays(sel, -wdIndex(sel)), [sel])
  const week = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart])

  const range = useMemo(() => {
    const a = mode === 'month' ? cells[0] : week[0]
    const b = mode === 'month' ? cells[cells.length - 1] : week[6]
    const s = day0(a)
    const e = new Date(day0(b)); e.setHours(23, 59, 0, 0)
    return [toLocalISO(s), toLocalISO(e)]
  }, [mode, cells, week])

  const load = () => api.events(range[0], range[1], true)
    .then((l) => { setEvents(l || []); setErr(null) })
    .catch(() => { setErr(true) })
  useEffect(() => { load() }, [range[0], range[1]]) // eslint-disable-line

  const toast = (text) => {
    setToastMsg(text)
    window.clearTimeout(toast._t)
    toast._t = window.setTimeout(() => setToastMsg(null), 3000)
  }

  const toggleDone = async (e) => {
    try {
      await api.doneEvent(e.id, !e.done)
      toast(t(e.done ? 'm.reopen' : 'm.done'))
      load()
    } catch (err2) { toast(String(err2?.message || err2)) }
  }

  const kindVisible = (e) => {
    const k = KIND_OF[e.kind] || 'work'
    if (hidden.includes(k)) return false
    if (isOverdue(e, t0) && hidden.includes('deadline')) return false
    return true
  }
  const visible = (d) => (events || [])
    .filter((e) => isSameDay(new Date(e.start), d) && kindVisible(e))
    .sort((a, b) => new Date(a.start) - new Date(b.start))
  const dotColor = (e) => (isOverdue(e, t0) ? KIND_COLOR.deadline : (KIND_COLOR[KIND_OF[e.kind]] || KIND_COLOR.work))

  const monthCount = (events || []).filter((e) => {
    const d = new Date(e.start)
    return d.getMonth() === m && d.getFullYear() === y && kindVisible(e)
  }).length

  const shift = (dir) => {
    if (mode === 'month') setCursor(new Date(y, m + dir, 1))
    else {
      const ns = addDays(sel, dir * 7)
      setSel(ns)
      setCursor(new Date(ns.getFullYear(), ns.getMonth(), 1))
    }
  }
  const goToday = () => { setSel(new Date()); setCursor(((d) => (d.setDate(1), d.setHours(0, 0, 0, 0), d))(new Date())) }
  const onTodayView = isSameDay(sel, today)

  const selEvents = visible(sel)
  const dayTasks = selEvents.filter((e) => e.kind === 'task')
  const busy = selEvents.reduce((s, e) => {
    const a = Math.max(8, Math.min(22, toH(e.start)))
    const b = e.end ? Math.max(8, Math.min(22, toH(e.end))) : a + 0.5
    return s + Math.max(0, b - a)
  }, 0)

  const monthName = new Date(y, m, 1).toLocaleDateString(localeOf(), { month: 'long' })
  const selWday = sel.toLocaleDateString(localeOf(), { weekday: 'long' })
  const selMon = sel.toLocaleDateString(localeOf(), { month: 'long' })

  if (err) {
    return (
      <div className="px-5 pt-10 text-center">
        <div className="text-[15px] text-white/70">{t('m.load_err')}</div>
        <button className="m-glass mt-3 rounded-full px-4 py-2 text-[13.5px]" onClick={load}>{t('m.retry')}</button>
      </div>
    )
  }
  if (!events) return <div className="px-5 pt-10 text-[15px] text-white/50">{t('m.loading')}</div>

  return (
    <div>
      <ScreenTitle
        title={monthName}
        subtitle={`${y} · ${t('m.cal_n', { count: monthCount })}`}
        right={(
          <>
            {!onTodayView && (
              <button onClick={goToday} className="m-glass anim-pop h-10 rounded-full px-4 text-[13.5px] font-medium">
                {t('m.today')}
              </button>
            )}
            <IconBtn icon={Plus} label={t('m.new_event')} onClick={() => setSheet('new')} />
          </>
        )}
      />

      <div className="mt-5 flex items-center gap-2 px-4">
        <Segmented
          className="w-[196px]"
          value={mode}
          onChange={setMode}
          options={[
            { id: 'month', label: t('m.month') },
            { id: 'week', label: t('m.week') },
          ]}
        />
        <div className="ml-auto flex gap-2">
          <IconBtn icon={ChevronLeft} label={t('m.nav_back')} onClick={() => shift(-1)} />
          <IconBtn icon={ChevronRight} label={t('m.nav_fwd')} onClick={() => shift(1)} />
        </div>
      </div>

      {mode === 'month' ? (
        <div className="anim-rise mt-4 px-4">
          <Card className="p-3.5">
            <div className="mb-1.5 grid grid-cols-7 gap-[5px]">
              {Array.from({ length: 7 }, (_, i) => new Date(2024, 0, 1 + i).toLocaleDateString(localeOf(), { weekday: 'short' })).map((d, i) => (
                <div key={`${d}-${i}`} className={`py-1 text-center text-[11px] font-semibold uppercase tracking-wider ${i >= 5 ? 'text-white/35' : 'text-white/55'}`}>
                  {d}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-[5px]">
              {cells.map((d) => {
                const out = d.getMonth() !== m
                const isT = isSameDay(d, today)
                const isS = isSameDay(d, sel)
                const evs = visible(d)
                return (
                  <button
                    key={d.toISOString()}
                    onClick={() => setSel(d)}
                    className={`flex h-[50px] flex-col items-center justify-center rounded-[14px] transition active:scale-95${out ? ' text-white/25' : ' bg-white/[0.045]'}${isS && !isT ? ' bg-white/[0.14] ring-1 ring-white/30' : ''}`}
                  >
                    <span className={`tnum grid h-[30px] w-[30px] place-items-center rounded-full text-[15px] font-semibold${isT ? ' m-active text-white' : ''}`}>
                      {d.getDate()}
                    </span>
                    <span className="mt-[3px] flex h-[5px] gap-[3px]">
                      {evs.slice(0, 3).map((e) => (
                        <span key={e.id} className="h-[5px] w-[5px] rounded-full" style={{ background: dotColor(e), opacity: out ? 0.4 : 1 }} />
                      ))}
                    </span>
                  </button>
                )
              })}
            </div>
            <Legend hidden={hidden} onToggle={(k) => setHidden((h) => (h.includes(k) ? h.filter((x) => x !== k) : [...h, k]))} />
          </Card>
        </div>
      ) : (
        <div className="anim-rise mt-4 px-4">
          <div className="grid grid-cols-7 gap-1.5">
            {week.map((d) => {
              const isS = isSameDay(d, sel)
              const isT = isSameDay(d, today)
              const evs = visible(d)
              const wd = d.toLocaleDateString(localeOf(), { weekday: 'short' })
              return (
                <button
                  key={d.toISOString()}
                  onClick={() => setSel(d)}
                  className={`flex flex-col items-center gap-1 rounded-[18px] py-2.5 transition active:scale-95${isS ? ' m-active' : ' m-card'}`}
                >
                  <span className={`text-[11px] font-semibold uppercase${isS ? ' text-white/85' : ' text-white/50'}`}>
                    {wd}
                  </span>
                  <span className={`tnum text-[18px] font-semibold${isT && !isS ? ' text-[#8ea3ff]' : ''}`}>{d.getDate()}</span>
                  <span className="flex h-[5px] gap-[2px]">
                    {evs.slice(0, 3).map((e) => (
                      <span key={e.id} className="h-[5px] w-[5px] rounded-full" style={{ background: isS ? '#fff' : dotColor(e) }} />
                    ))}
                  </span>
                </button>
              )
            })}
          </div>
          <Card className="mt-3 p-4">
            <div className="flex justify-between text-[12.5px] text-white/55">
              <span>{t('m.day_load')}</span>
              <span className="tnum">{busy ? t('m.busy_h', { n: busy % 1 ? busy.toFixed(1) : busy }) : t('m.free')}</span>
            </div>
            <div className="relative mt-3 h-8 overflow-hidden rounded-full bg-white/[0.05]">
              {selEvents.map((e) => {
                const s = Math.max(8, Math.min(22, toH(e.start)))
                const en = e.end ? Math.max(8, Math.min(22, toH(e.end))) : s + 0.5
                const c = dotColor(e)
                return (
                  <div
                    key={e.id}
                    className="absolute bottom-1 top-1 rounded-full"
                    style={{
                      left: `${((s - 8) / 14) * 100}%`,
                      width: `${Math.max(3, ((Math.max(en, s + 0.25) - s) / 14) * 100)}%`,
                      background: c,
                      boxShadow: `0 0 12px ${c}88`,
                    }}
                  />
                )
              })}
            </div>
            <div className="tnum mt-1.5 flex justify-between text-[10.5px] text-white/35">
              <span>8:00</span>
              <span>15:00</span>
              <span>22:00</span>
            </div>
          </Card>
        </div>
      )}

      <div className="mt-6 px-4">
        <div className="mb-3 px-1">
          {isSameDay(sel, today) && <Overline className="mb-1 text-[#8ea3ff]">{t('m.today')}</Overline>}
          <h2 className="text-[19px] font-semibold tracking-[-0.015em]">
            {selWday}, {sel.getDate()} {selMon}
          </h2>
          <div className="mt-0.5 text-[13px] text-white/55">
            {selEvents.length ? t('m.cal_n', { count: selEvents.length }) : t('m.no_events')}
            {dayTasks.length > 0 && ` · ${dayTasks.length} ${t('m.day_tasks')}`}
          </div>
        </div>

        {selEvents.length > 0 ? (
          <Card className="p-2">
            {selEvents.map((e, i) => (
              <div key={e.id} className={`flex gap-3 rounded-[20px] p-3${i < selEvents.length - 1 ? ' border-b border-white/[0.05]' : ''}`}>
                <div className="w-11 shrink-0">
                  <div className="tnum text-[14px] font-semibold">{isAllDay(e.start) ? '·' : hhmm(e.start)}</div>
                  {e.end && !isAllDay(e.start) && <div className="tnum text-[12px] text-white/45">{hhmm(e.end)}</div>}
                </div>
                <div className="w-[4px] shrink-0 rounded-full" style={{ background: dotColor(e) }} />
                <div className="min-w-0 flex-1">
                  <div className={`text-[15px] font-medium leading-snug${e.done ? ' text-white/40 line-through' : ''}`}>{e.title}</div>
                  <div className="mt-1 flex items-center gap-1.5 text-[12.5px] text-white/50">
                    {e.location ? (
                      <>
                        {String(e.location).toLowerCase().includes('meet') ? <Video size={13} /> : <MapPin size={13} />}
                        <span className="truncate">{e.location}</span>
                      </>
                    ) : (
                      t(e.kind === 'task' ? 'm.ev_tasks' : e.kind === 'order' ? 'm.ev_orders' : 'm.ev_meetings')
                    )}
                  </div>
                </div>
                <div className="self-center">
                  <TaskCheck done={!!e.done} priority="low" onToggle={() => toggleDone(e)} size={22} />
                </div>
              </div>
            ))}
          </Card>
        ) : (
          <Card className="flex items-center gap-3 p-4">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#7d95ff]/15 text-[#a9bbff]">
              <Sparkles size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[15px] font-medium">{t('m.free_day')}</div>
              <div className="text-[12.5px] leading-snug text-white/55">{t('m.free_day_sub')}</div>
            </div>
            <button onClick={() => setSheet('new')} className="shrink-0 rounded-full bg-white/10 px-3 py-1.5 text-[13px] font-medium">
              {t('m.plan')}
            </button>
          </Card>
        )}

        {dayTasks.length > 0 && (
          <Card className="mt-3 p-2">
            <div className="px-3 pb-1 pt-2">
              <Overline>{t('m.day_tasks')}</Overline>
            </div>
            {dayTasks.map((ev) => (
              <div key={ev.id} className="flex items-center gap-3 px-3 py-2.5">
                <TaskCheck size={22} done={!!ev.done} priority={ev.priority === 1 ? 'high' : 'low'} onToggle={() => toggleDone(ev)} />
                <span className={`flex-1 text-[14.5px] leading-snug${ev.done ? ' text-white/40 line-through' : ''}`}>
                  {ev.title}
                </span>
                {!isAllDay(ev.start) && <span className="tnum text-[12.5px] text-white/50">{hhmm(ev.start)}</span>}
              </div>
            ))}
          </Card>
        )}
      </div>

      {sheet && (
        <EventSheet
          ev={sheet}
          day={sel}
          onClose={() => setSheet(null)}
          onDone={() => { setSheet(null); load() }}
          notify={toast}
        />
      )}
      {toastMsg && (
        <div className="anim-toast fixed bottom-24 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full border border-white/10 bg-[#121a46]/95 py-2.5 pl-4 pr-2.5 shadow-xl backdrop-blur-xl">
          <span className="max-w-[70vw] truncate text-[13.5px]">{toastMsg}</span>
        </div>
      )}
    </div>
  )
}

function Legend({ hidden, onToggle }) {
  const { t } = useI18n()
  const items = [
    ['work', 'm.l_work'],
    ['personal', 'm.l_personal'],
    ['money', 'm.l_money'],
    ['deadline', 'm.l_deadline'],
  ]
  return (
    <div className="mt-3 flex flex-wrap gap-1.5 border-t border-white/[0.06] pt-3">
      {items.map(([k, key]) => {
        const off = hidden.includes(k)
        return (
          <button
            key={k}
            onClick={() => onToggle(k)}
            className={`inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium transition active:scale-95${off ? ' text-white/35 line-through' : ' bg-white/[0.06] text-white/75'}`}
          >
            <span className="h-2 w-2 rounded-full" style={{ background: KIND_COLOR[k], opacity: off ? 0.35 : 1 }} />
            {t(key)}
          </button>
        )
      })}
    </div>
  )
}

function EventSheet({ ev, day, onClose, onDone, notify }) {
  const { t } = useI18n()
  const isNew = ev === 'new' || !ev?.id
  const synthetic = !isNew && Number(ev?.id) < 0
  const [title, setTitle] = useState(isNew ? '' : ev?.title || '')
  const [start, setStart] = useState(() => {
    const d = isNew ? day : new Date(ev?.start || Date.now())
    return toLocalISO(d).slice(0, 16)
  })
  const [location, setLocation] = useState(isNew ? '' : ev?.location || '')
  const [saving, setSaving] = useState(false)

  const save = async (e) => {
    e?.preventDefault()
    if (!title.trim() || saving) return
    setSaving(true)
    try {
      const at = new Date(start)
      const payload = { title: title.trim(), start: toLocalISO(at), duration_min: 60, location: location.trim() || null }
      if (isNew) await api.addEvent(payload)
      else await api.updateEvent(ev.id, payload)
      onDone()
    } catch (err) { notify(String(err?.message || err)) } finally { setSaving(false) }
  }

  const remove = async () => {
    if (!ev?.id || saving) return
    setSaving(true)
    try { await api.delEvent(ev.id); onDone() } catch (err) { notify(String(err?.message || err)); setSaving(false) }
  }

  const toggleDone = async () => {
    setSaving(true)
    try { await api.doneEvent(ev.id, !ev.done); onDone() } catch (err) { notify(String(err?.message || err)); setSaving(false) }
  }

  return (
    <div className="anim-fade fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="anim-sheet m-card w-full max-w-[420px] rounded-[26px] p-5" onClick={(e) => e.stopPropagation()}>
        {synthetic ? (
          <>
            <Overline>{t(ev.kind === 'order' ? 'm.ev_orders' : 'm.ev_tasks')}</Overline>
            <div className="mt-2 text-[19px] font-semibold leading-snug">{ev?.title}</div>
            <div className="tnum mt-1 text-[13.5px] text-white/55">
              {shortDate(ev?.start)}{ev?.start && !isAllDay(ev.start) ? ` · ${hhmm(ev.start)}` : ''}
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={onClose} className="rounded-full bg-white/10 px-4 py-2.5 text-[14px] font-medium">{t('m.cancel')}</button>
              <button onClick={toggleDone} disabled={saving} className="m-active rounded-full px-4 py-2.5 text-[14px] font-semibold">
                {t(ev.done ? 'm.reopen' : 'm.done')}
              </button>
            </div>
          </>
        ) : (
          <form onSubmit={save}>
            <Overline>{t('m.new_event')}</Overline>
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('m.ev_title_ph')}
              className="mt-3 w-full rounded-[16px] border border-white/10 bg-white/[0.05] px-4 py-3 text-[16px] outline-none placeholder:text-white/35 focus:border-[#7d95ff]/50"
            />
            <div className="mt-2.5 flex gap-2">
              <input
                type="datetime-local"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="min-w-0 flex-1 rounded-[16px] border border-white/10 bg-white/[0.05] px-4 py-3 text-[14px] outline-none focus:border-[#7d95ff]/50"
              />
            </div>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder={t('m.place_ph')}
              className="mt-2.5 w-full rounded-[16px] border border-white/10 bg-white/[0.05] px-4 py-3 text-[15px] outline-none placeholder:text-white/35 focus:border-[#7d95ff]/50"
            />
            <div className="mt-4 flex items-center justify-between gap-2">
              {!isNew ? (
                <button type="button" onClick={remove} disabled={saving} className="px-2 py-2.5 text-[14px] font-medium text-[#ff9aac]">
                  {t('m.del')}
                </button>
              ) : <span />}
              <div className="flex gap-2">
                {!isNew && (
                  <button type="button" onClick={toggleDone} disabled={saving} className="rounded-full bg-white/10 px-4 py-2.5 text-[14px] font-medium">
                    {t(ev.done ? 'm.reopen' : 'm.done')}
                  </button>
                )}
                <button type="button" onClick={onClose} className="rounded-full bg-white/10 px-4 py-2.5 text-[14px] font-medium">{t('m.cancel')}</button>
                <button type="submit" disabled={saving || !title.trim()} className="m-active rounded-full px-5 py-2.5 text-[14px] font-semibold disabled:opacity-40">
                  {t('m.save')}
                </button>
              </div>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
