import { useEffect, useState } from 'react'
import { Plus, Check, ChevronDown, ChevronUp, Pause, Play, X, MessageCircle } from 'lucide-react'
import { api, plural } from '../lib/api'
import { Section, Empty, Sheet, useToast } from './ui'

/* Цели: цель → вехи → задачи. Не список дел, а «ради чего список». Прогресс считается по закрытым задачам и заказам. */
const ask = (text) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } }))
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: new Date(iso).getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined }) : '')

export default function Aims({ tick, bump }) {
  const [list, setList] = useState(null)
  const [all, setAll] = useState(false)
  const [sheet, setSheet] = useState(false)
  const [, show] = useToast()
  const load = () => api.get(`/api/aims?all=${all}`).then(setList).catch(() => setList([]))
  useEffect(() => { load() }, [tick, all])
  const patch = async (id, body, msg) => { try { await api.put(`/api/aims/${id}`, body); await load(); bump?.(); if (msg) show(msg) } catch (e) { show.err(e) } }
  if (!list) return null
  const active = list.filter((a) => a.status === 'active')
  const rest = list.filter((a) => a.status !== 'active')
  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div className="muted text-[13px]">{active.length ? `${active.length} ${plural(active.length, 'активная цель', 'активные цели', 'активных целей')}` : 'Долгосрочное: то, ради чего задачи.'}</div>
        <div className="flex items-center gap-2">
          <button className={`btn-ghost btn-sm ${all ? 'text-accent' : ''}`} onClick={() => setAll(!all)}>{all ? 'только активные' : 'все'}</button>
          <button className="btn-primary head-primary" onClick={() => setSheet(true)}><Plus size={15} /> цель</button>
        </div>
      </div>
      {!list.length && <div className="rule"><Empty glyph="tasks" text="Целей пока нет" sub="Цель — это на месяцы: портфолио, доход, здоровье. Вехи и задачи подтянутся к ней." hint="цель: собрать портфолио до конца года, потому что хочу брать заказы дороже" onHint={() => ask('цель: ')} /></div>}
      <div className="space-y-4">
        {active.map((a) => <AimCard key={a.id} a={a} onPatch={patch} onChange={() => { load(); bump?.() }} />)}
      </div>
      {all && rest.length > 0 && (
        <Section title="закрытые и на паузе" idx={rest.length}>
          <div className="rule">
            {rest.map((a) => (
              <div key={a.id} className="row opacity-70">
                <span className="grid h-[22px] w-[22px] shrink-0 place-items-center text-[12px]">{a.status === 'done' ? <Check size={14} className="text-accent" /> : a.status === 'paused' ? <Pause size={12} /> : <X size={12} />}</span>
                <div className="min-w-0 flex-1">
                  <div className={`truncate text-[15px] ${a.status === 'done' ? '' : 'line-through'}`}>{a.title}</div>
                  <div className="muted text-[12px]">{a.status === 'done' ? `достигнута ${fmtDate(a.done_at)}` : a.status === 'paused' ? 'на паузе' : 'снята'}{a.why ? ` · ${a.why}` : ''}</div>
                </div>
                {a.status !== 'done' && <button className="btn-ghost btn-sm" onClick={() => patch(a.id, { status: 'active' }, 'Снова в работе')}><Play size={12} /> вернуть</button>}
              </div>
            ))}
          </div>
        </Section>
      )}
      <AimSheet open={sheet} onClose={() => setSheet(false)} onDone={() => { setSheet(false); load(); bump?.(); show('Цель поставлена') }} />
    </div>
  )
}

function AimCard({ a, onPatch, onChange }) {
  const [v, setV] = useState(null)
  const [open, setOpen] = useState(false)
  const [msDraft, setMsDraft] = useState('')
  const [, show] = useToast()
  const loadView = () => api.get(`/api/aims/${a.id}`).then(setV).catch(() => {})
  useEffect(() => { if (open) loadView() }, [open, a.progress])
  const pct = Math.round((a.progress || 0) * 100)
  const stale = a.stale_days >= 14
  const addMs = async (e) => {
    e.preventDefault(); const t = msDraft.trim(); if (!t) return
    try { await api.post(`/api/aims/${a.id}/milestones`, { title: t }); setMsDraft(''); await loadView(); onChange() } catch (err) { show.err(err) }
  }
  const msStatus = async (m, status) => { try { await api.post(`/api/milestones/${m.id}/${status}`); await loadView(); onChange() } catch (err) { show.err(err) } }
  const doneTask = async (t) => { try { await api.doneTask(t.id); await loadView(); onChange() } catch (err) { show.err(err) } }
  return (
    <div className="card !p-4 sm:!p-5">
      <div className="flex items-start gap-3">
        <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setOpen(!open)}>
          <div className="flex items-baseline gap-2">
            <div className="truncate text-[16px] font-semibold">{a.title}</div>
            {a.priority === 1 && <span className="label !text-accent">главная</span>}
          </div>
          <div className="muted mt-0.5 text-[13px]">
            {a.why ? <span>{a.why}</span> : <span className="faint">зачем — не записано</span>}
            {a.due && <span> · к {fmtDate(a.due)}{a.days_left != null && a.days_left >= 0 ? ` (${a.days_left} дн.)` : ''}</span>}
            {a.days_left != null && a.days_left < 0 && <span className="neg"> · срок прошёл</span>}
          </div>
        </button>
        <div className="num shrink-0 text-[15px] font-semibold tabular-nums">{pct}%</div>
        <button className="btn-icon !h-7 !w-7" onClick={() => setOpen(!open)} aria-label={open ? 'Свернуть' : 'Раскрыть'}>{open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button>
      </div>
      <div className="progress mt-3"><div style={{ width: `${pct}%` }} /></div>
      {stale && !open && <div className="warn mt-2 text-[12px]">ничего не двигалось {a.stale_days} дн.</div>}
      {open && (
        <div className="mt-4 space-y-4" style={{ animation: 'rise .2s var(--ease-out)' }}>
          {!v ? <div className="muted text-[13px]">…</div> : (
            <>
              {v.milestones.length === 0 && v.tasks.length === 0 && <div className="muted text-[13px]">Пока пусто. Первая веха — первый ощутимый рубеж; задачи привяжутся к ней («задача: … к вехе …»).</div>}
              {v.milestones.map((m) => (
                <div key={m.id}>
                  <div className="flex items-center gap-2">
                    <button onClick={() => msStatus(m, m.status === 'done' ? 'open' : 'done')} aria-label="Веха закрыта" className={`grid h-[20px] w-[20px] shrink-0 place-items-center rounded-full border transition ${m.status === 'done' ? 'border-accent bg-accent text-accent-ink' : 'hover:border-accent'}`} style={{ borderColor: 'var(--line-2)' }}>{m.status === 'done' && <Check size={11} strokeWidth={3} />}</button>
                    <div className={`min-w-0 flex-1 truncate text-[14px] font-medium ${m.status === 'done' ? 'muted line-through' : ''}`}>{m.title}</div>
                    <div className="muted num text-[12px]">{Math.round(m.progress * 100)}%{m.order_title ? ` · заказ «${m.order_title}»` : ''}{m.due ? ` · к ${fmtDate(m.due)}` : ''}</div>
                  </div>
                  {m.tasks.length > 0 && (
                    <div className="ml-7 mt-1">
                      {m.tasks.map((t) => <TaskLine key={t.id} t={t} onDone={doneTask} />)}
                    </div>
                  )}
                </div>
              ))}
              {v.tasks.length > 0 && (
                <div>
                  <div className="label mb-1">без вехи</div>
                  {v.tasks.map((t) => <TaskLine key={t.id} t={t} onDone={doneTask} />)}
                </div>
              )}
              <form onSubmit={addMs} className="flex items-center gap-2">
                <Plus size={14} className="faint shrink-0" />
                <input value={msDraft} onChange={(e) => setMsDraft(e.target.value)} className="h-8 w-full bg-transparent text-[14px] outline-none placeholder:text-[var(--ink-3)]" placeholder="новая веха…" />
              </form>
              <div className="flex flex-wrap items-center gap-1 pt-1 text-[12px]">
                <button className="btn-ghost btn-sm" onClick={() => onPatch(a.id, { priority: a.priority === 1 ? 2 : 1 })}>{a.priority === 1 ? 'не главная' : 'сделать главной'}</button>
                <button className="btn-ghost btn-sm" onClick={() => onPatch(a.id, { status: 'paused' }, 'На паузе')}><Pause size={12} /> пауза</button>
                <button className="btn-ghost btn-sm" onClick={() => onPatch(a.id, { status: 'done' }, 'Цель закрыта')}><Check size={12} /> достигнута</button>
                <button className="btn-ghost btn-sm !text-red" onClick={() => onPatch(a.id, { status: 'dropped' }, 'Цель снята')}><X size={12} /> снять</button>
                <button className="btn-ghost btn-sm ml-auto" onClick={() => ask(`по цели «${a.title}»: `)}><MessageCircle size={12} /> обсудить</button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function TaskLine({ t, onDone }) {
  return (
    <div className="flex items-center gap-2 py-1">
      <button onClick={() => !t.done && onDone(t)} aria-label="Сделано" className={`grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border transition ${t.done ? 'border-accent bg-accent text-accent-ink' : 'hover:border-accent'}`} style={{ borderColor: 'var(--line-2)' }}>{t.done && <Check size={10} strokeWidth={3} />}</button>
      <div className={`min-w-0 flex-1 truncate text-[13px] ${t.done ? 'muted line-through' : ''}`}>{t.title}</div>
      {t.blocked_by && !t.done && <span className="warn truncate text-[11px]">⏸ {t.blocked_by}</span>}
      {t.due && !t.done && <span className="faint text-[11px]">{fmtDate(t.due)}</span>}
    </div>
  )
}

function AimSheet({ open, onClose, onDone }) {
  const [title, setTitle] = useState('')
  const [why, setWhy] = useState('')
  const [due, setDue] = useState('')
  const [busy, setBusy] = useState(false)
  const [, show] = useToast()
  useEffect(() => { if (open) { setTitle(''); setWhy(''); setDue('') } }, [open])
  const save = async (e) => {
    e.preventDefault(); if (title.trim().length < 2) return
    setBusy(true)
    try { await api.post('/api/aims', { title: title.trim(), why: why.trim(), due: due ? new Date(due + 'T00:00').toISOString() : null }); onDone() } catch (err) { show.err(err) } finally { setBusy(false) }
  }
  return (
    <Sheet open={open} onClose={onClose} title="новая цель" sub="Это на месяцы, не на день. Задачи и заказы будут двигать её сами.">
      <form onSubmit={save} className="space-y-4">
        <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} className="input" placeholder="Собрать портфолио по интерьерам" />
        <input value={why} onChange={(e) => setWhy(e.target.value)} className="input" placeholder="Зачем: брать заказы дороже (через месяц это единственное, что удержит)" />
        <label className="block">
          <div className="label mb-1">срок (необязательно)</div>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="input" />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>отмена</button>
          <button className="btn-primary" disabled={busy || title.trim().length < 2}>поставить</button>
        </div>
      </form>
    </Sheet>
  )
}
