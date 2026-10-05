import { useEffect, useState } from 'react'
import { Plus, Check, ChevronDown, ChevronUp, Pause, Play, X, MessageCircle } from 'lucide-react'
import { api } from '../lib/api'
import { Section, Empty, Sheet, useToast } from './ui'
import { useI18n, localeOf, t as T } from '../lib/i18n'

/* Цели: цель → вехи → задачи. Не список дел, а «ради чего список». Прогресс считается по закрытым задачам и заказам. */
const ask = (text) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } }))
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString(localeOf(), { day: 'numeric', month: 'short', year: new Date(iso).getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined }).replace(/\.?\s*г\.$/u, '') : '')

export default function Aims({ tick, bump }) {
  const { t } = useI18n()
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
        <div className="muted text-[13px]">{t(active.length ? 'aims.active_n' : 'aims.long_term', { count: active.length })}</div>
        <div className="flex items-center gap-2">
          <button className={`btn-ghost btn-sm ${all ? 'text-accent' : ''}`} onClick={() => setAll(!all)}>{t(all ? 'aims.only_active' : 'common.all')}</button>
          <button className="btn-primary head-primary" onClick={() => setSheet(true)}><Plus size={15} /> {t('aims.goal')}</button>
        </div>
      </div>
      {!list.length && <div className="rule"><Empty glyph="tasks" text={t('aims.none')} sub={t('aims.none_hint')} hint={t('aims.hint_example')} onHint={() => ask(T('aims.seed_goal'))} /></div>}
      <div className="space-y-4">
        {active.map((a) => <AimCard key={a.id} a={a} onPatch={patch} onChange={() => { load(); bump?.() }} />)}
      </div>
      {all && rest.length > 0 && (
        <Section title={t('aims.closed_paused')} idx={rest.length}>
          <div className="rule">
            {rest.map((a) => (
              <div key={a.id} className="row opacity-70">
                <span className="grid h-[22px] w-[22px] shrink-0 place-items-center text-[12px]">{a.status === 'done' ? <Check size={14} className="text-accent" /> : a.status === 'paused' ? <Pause size={12} /> : <X size={12} />}</span>
                <div className="min-w-0 flex-1">
                  <div className={`truncate text-[15px] ${a.status === 'done' ? '' : 'line-through'}`}>{a.title}</div>
                  <div className="muted text-[12px]">{t(a.status === 'done' ? 'aims.reached' : a.status === 'paused' ? 'aims.on_pause' : 'aims.dropped', { date: fmtDate(a.done_at) })}{a.why ? ` · ${a.why}` : ''}</div>
                </div>
                {a.status !== 'done' && <button className="btn-ghost btn-sm" onClick={() => patch(a.id, { status: 'active' }, t('aims.back_to_work'))}><Play size={12} /> {t('aims.restore')}</button>}
              </div>
            ))}
          </div>
        </Section>
      )}
      <AimSheet open={sheet} onClose={() => setSheet(false)} onDone={() => { setSheet(false); load(); bump?.(); show(t('aims.set')) }} />
    </div>
  )
}

/* Кнопки-иконки строки цели — тот же вид, что у целей на «финансах»
   (Finance.jsx: локальные RowActions/IconBtn, кросс-импорт невозможен — дублируем ~12 строк):
   видны всегда, на тап-экранах не прячутся до наведения. */
function RowActions({ children }) {
  return <div className="flex shrink-0 items-center gap-1">{children}</div>
}

function IconBtn({ onClick, title, children, danger, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="btn-icon max-[820px]:!h-11 max-[820px]:!w-11"
      style={danger ? { color: 'var(--neg)' } : { color: 'var(--ink-3)' }}
      title={title}
      aria-label={label || title}
    >
      {children}
    </button>
  )
}

function AimCard({ a, onPatch, onChange }) {
  const { t } = useI18n()
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
  /* Карточка цели — тем же строем, что цели на «финансах» (Finance.jsx, вкладка goals):
     заголовок + крупный % → градиентная полоса → строка срока → ряд действий
     (обсудить/главная/пауза/достигнута/снять). Контракт .glass-card/.gc-goals отсутствует —
     стоим на .card (= .panel: стекло + углубление в тёмной теме) и .num. */
  return (
    <div className="card glass-card gc-goals !p-4 sm:!p-5">
      <div className="flex items-start gap-3">
        <button type="button" className="min-w-0 flex-1 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
          <div className="flex items-baseline gap-2">
            <div className="truncate text-[16px] font-semibold">{a.title}</div>
            {a.priority === 1 && <span className="label shrink-0 !text-accent">{t('aims.main')}</span>}
          </div>
          <div className="muted mt-0.5 truncate text-[13px]">
            {a.why || <span className="faint">{t('aims.no_why')}</span>}
          </div>
        </button>
        <div className="num shrink-0 text-[20px] font-semibold leading-none tracking-[-0.03em]">{pct}<span className="text-[0.65em] font-medium opacity-60"> %</span></div>
        <button className="btn-icon shrink-0" onClick={() => setOpen(!open)} aria-label={t(open ? 'aims.collapse' : 'aims.expand')} aria-expanded={open}>{open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button>
      </div>
      <div className="progress mt-3 !h-[6px]"><div style={{ width: `${pct}%`, background: 'linear-gradient(90deg, var(--acc), color-mix(in srgb, var(--acc) 55%, #ffffff))' }} /></div>
      {(a.due || a.days_left < 0 || stale) && (
        <div className="muted mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[12px]">
          {a.due && <span className="num">{t('aims.by', { date: fmtDate(a.due) })}{a.days_left != null && a.days_left >= 0 ? t('aims.days_left', { n: a.days_left }) : ''}</span>}
          {a.days_left != null && a.days_left < 0 && <span className="neg">{t('aims.overdue')}</span>}
          {stale && <span className="warn">{t('aims.stale', { n: a.stale_days })}</span>}
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-1">
        <button className="btn-ghost btn-sm" onClick={() => ask(T('aims.seed_about', { title: a.title }))}><MessageCircle size={12} /> {t('aims.discuss')}</button>
        <button className="btn-ghost btn-sm" onClick={() => onPatch(a.id, { priority: a.priority === 1 ? 2 : 1 })}>{t(a.priority === 1 ? 'aims.unmain' : 'aims.make_main')}</button>
        <span className="ms-auto">
          <RowActions>
            <IconBtn onClick={() => onPatch(a.id, { status: 'paused' }, t('aims.paused'))} title={t('aims.pause')} label={t('aims.pause')}><Pause size={13} /></IconBtn>
            <IconBtn onClick={() => onPatch(a.id, { status: 'done' }, t('aims.closed'))} title={t('aims.reached_btn')} label={t('aims.reached_btn')}><Check size={13} /></IconBtn>
            <IconBtn danger onClick={() => onPatch(a.id, { status: 'dropped' }, t('aims.dropped_toast'))} title={t('aims.drop')} label={t('aims.drop')}><X size={13} /></IconBtn>
          </RowActions>
        </span>
      </div>
      {open && (
        <div className="mt-4 space-y-4" style={{ animation: 'rise .2s var(--ease-out)' }}>
          {!v ? <div className="muted text-[13px]">…</div> : (
            <>
              {v.milestones.length === 0 && v.tasks.length === 0 && <div className="muted text-[13px]">{t('aims.no_ms')}</div>}
              {v.milestones.map((m) => (
                <div key={m.id}>
                  <div className="flex items-center gap-2">
                    <button onClick={() => msStatus(m, m.status === 'done' ? 'open' : 'done')} aria-label={t('aims.ms_done')} className={`grid h-[20px] w-[20px] shrink-0 place-items-center rounded-full border transition ${m.status === 'done' ? 'border-accent bg-accent text-accent-ink' : 'hover:border-accent'}`} style={{ borderColor: 'var(--line-2)' }}>{m.status === 'done' && <Check size={11} strokeWidth={3} />}</button>
                    <div className={`min-w-0 flex-1 truncate text-[14px] font-medium ${m.status === 'done' ? 'muted line-through' : ''}`}>{m.title}</div>
                    <div className="muted num text-[12px]">{Math.round(m.progress * 100)}%{m.order_title ? ` · ${t('aims.order', { title: m.order_title })}` : ''}{m.due ? ` · ${t('aims.by', { date: fmtDate(m.due) })}` : ''}</div>
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
                  <div className="label mb-1">{t('aims.no_milestone')}</div>
                  {v.tasks.map((t) => <TaskLine key={t.id} t={t} onDone={doneTask} />)}
                </div>
              )}
              <form onSubmit={addMs} className="flex items-center gap-2">
                <Plus size={14} className="faint shrink-0" />
                <input value={msDraft} onChange={(e) => setMsDraft(e.target.value)} className="h-8 w-full bg-transparent text-[14px] outline-none placeholder:text-[var(--ink-3)]" placeholder={t('aims.new_ms')} />
              </form>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function TaskLine({ t, onDone }) {
  const { t: T2 } = useI18n()
  return (
    <div className="flex items-center gap-2 py-1">
      <button onClick={() => !t.done && onDone(t)} aria-label={T2('focus.done')} className={`grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border transition ${t.done ? 'border-accent bg-accent text-accent-ink' : 'hover:border-accent'}`} style={{ borderColor: 'var(--line-2)' }}>{t.done && <Check size={10} strokeWidth={3} />}</button>
      <div className={`min-w-0 flex-1 truncate text-[13px] ${t.done ? 'muted line-through' : ''}`}>{t.title}</div>
      {t.blocked_by && !t.done && <span className="warn truncate text-[11px]">⏸ {t.blocked_by}</span>}
      {t.due && !t.done && <span className="faint text-[11px]">{fmtDate(t.due)}</span>}
    </div>
  )
}

function AimSheet({ open, onClose, onDone }) {
  const { t } = useI18n()
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
    <Sheet open={open} onClose={onClose} title={t('aims.new_title')} sub={t('aims.new_sub')}>
      <form onSubmit={save} className="space-y-4">
        <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} className="input" placeholder={t('aims.ph_title')} />
        <input value={why} onChange={(e) => setWhy(e.target.value)} className="input" placeholder={t('aims.ph_why')} />
        <label className="block">
          <div className="label mb-1">{t('aims.due_label')}</div>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="input" />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn-ghost" onClick={onClose}>{t('common.cancel')}</button>
          <button className="btn-primary" disabled={busy || title.trim().length < 2}>{t('aims.set')}</button>
        </div>
      </form>
    </Sheet>
  )
}
