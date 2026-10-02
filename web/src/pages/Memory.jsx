import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, CalendarDays, CheckSquare, Wallet, FileText, Link2, MessageCircle, Cpu, ArrowUpRight, X, Pencil, Check, Star, RotateCcw, Plus, Monitor, Target, Bot } from 'lucide-react'
import { api, hhmm, dayLabel, shortDate } from '../lib/api'
import { Empty, Seg, PageHead, ListSkeleton, Pills, toast } from '../components/ui'
import { useRefresh } from '../App'
import { name as aName } from '../lib/name'
import { useI18n, localeOf, t as T } from '../lib/i18n'

/* Память — четыре вкладки: «сейчас» (свежее, живёт неделю), «о вас» (надолго + портрет), «события» (журнал
   всего, что ассистент понял и сделал) и «архив» (забытое и устаревшее — ничего не стирается, всё можно вернуть). */
const TABS = [['short', 'mem.t_short'], ['long', 'mem.t_long'], ['timeline', 'mem.t_timeline'], ['journal', 'mem.t_journal'], ['archive', 'mem.t_archive']]

export default function Memory() {
  const { t } = useI18n()
  const [tab, setTab] = useState('long')
  const [data, setData] = useState(null)
  const { tick } = useRefresh()
  const load = () => api.facts().then(setData).catch(() => setData({ items: [], stats: {}, enabled: false, categories: [] }))
  useEffect(() => { load() }, [tick])
  const st = data?.stats || {}
  const counts = { short: st.short, long: st.long, archive: st.archive }
  return (
    <div className="space-y-8">
      <PageHead kicker={t('mem.kicker', { name: aName().toLowerCase() })} title={t('nav.memory')} />
      <div className="no-scrollbar -mx-1 flex gap-1.5 overflow-x-auto px-1 animate-rise">
        {TABS.map(([id, l]) => (
          <button key={id} onClick={() => setTab(id)} className={`pill shrink-0 ${tab === id ? 'on' : ''}`}>
            {t(l)}{counts[id] ? <span className="idx !text-[10px] opacity-60">{counts[id]}</span> : null}
          </button>
        ))}
      </div>
      {tab === 'journal' ? <Journal /> : tab === 'timeline' ? <Timeline /> : <Facts layer={tab} data={data} reload={load} />}
    </div>
  )
}

const CATS = { 'о человеке': 'var(--accent)', 'предпочтение': '#7c3aed', 'здоровье': 'var(--neg)', 'работа': 'var(--warn)', 'быт': 'var(--ink-3)', 'отношения': '#db2777', 'привычка': 'var(--pos)' }
const ago = (iso) => {
  if (!iso) return ''
  const d = Math.floor((Date.now() - new Date(iso)) / 864e5)
  return d <= 0 ? T('common.today') : d === 1 ? T('common.yesterday') : T('mem.ago', { count: d })
}

function Facts({ layer, data, reload }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  if (!data) return <ListSkeleton n={5} />
  const st = data.stats || {}
  const items = (data.items || []).filter((f) => f.layer === layer).sort((a, b) => (b.core - a.core) || (new Date(b.updated_at) - new Date(a.updated_at)))
  const run = async (fn, ok) => { setBusy(true); try { await fn(); ok && toast(ok); await reload() } catch (e) { toast(t('mem.failed'), { sub: e.message, kind: 'err' }) } finally { setBusy(false) } }
  const add = () => { const draftText = draft.trim(); if (!draftText) return; run(() => api.addFact({ text: draftText, layer: layer === 'archive' ? 'long' : layer }), t('mem.remembered')).then(() => { setDraft(''); setAdding(false) }) }
  const sub = t({ short: 'mem.sub_short', long: 'mem.sub_long', archive: 'mem.sub_archive' }[layer] || 'mem.sub_long')

  return (
    <div className="space-y-6 animate-rise">
      {!data.enabled && <div className="rule"><div className="row"><span className="muted text-[13.5px]">{t('mem.disabled')}</span></div></div>}

      {layer === 'long' && (
        <section>
          <div className="mb-1.5 flex items-baseline justify-between gap-2">
            <div className="label">{t('mem.portrait')}</div>
            <span className="faint text-[11px]">{st.portrait_at ? t('mem.built_at', { when: ago(st.portrait_at) }) : t('mem.not_built')}</span>
          </div>
          <div className="panel p-4 sm:p-5">
            {st.portrait ? (
              <div className="whitespace-pre-line text-[14.5px] leading-relaxed">{st.portrait}</div>
            ) : <div className="muted text-[13.5px]">{t('mem.portrait_hint')}</div>}
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
              <button className="text-accent hover:underline disabled:opacity-40" disabled={busy || (st.long || 0) < 3} onClick={() => run(() => api.rebuildPortrait(), t('mem.portrait_rebuilt'))}>{t('mem.rebuild_portrait')}</button>
              <span className="faint">· {t('mem.weekly_auto')}</span>
            </div>
          </div>
        </section>
      )}

      {layer === 'long' && <StyleBlock st={st} busy={busy} run={run} />}

      <section>
        <div className="mb-1.5 flex items-baseline justify-between gap-2">
          <div className="label">{t('mem.facts_n', { count: items.length })}</div>
          <div className="flex items-center gap-3 text-[12px]">
            {layer === 'short' && items.length > 0 && <button className="text-accent hover:underline disabled:opacity-40" disabled={busy} onClick={() => run(() => api.memoryTidy(), t('mem.tidied'))}>{t('mem.tidy_now')}</button>}
            {layer !== 'archive' && <button className="text-accent flex items-center gap-1 hover:underline" onClick={() => setAdding((v) => !v)}><Plus size={12} /> {t('common.add')}</button>}
          </div>
        </div>
        {sub && <div className="muted mb-3 text-[13px]">{sub}</div>}
        {adding && (
          <div className="composer mb-3 flex items-center gap-2 py-1.5 pl-4 pr-2">
            <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') add(); if (e.key === 'Escape') setAdding(false) }}
              className="h-9 w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]" placeholder={t('mem.fact_ph')} />
            <button className="btn-primary btn-sm" disabled={!draft.trim() || busy} onClick={add}>{t('mem.remember')}</button>
          </div>
        )}
        {items.length === 0 ? (
          <div className="rule"><Empty glyph="memory" text={t('mem.empty')} sub={t({ short: 'mem.e_short', long: 'mem.e_long', archive: 'mem.e_archive' }[layer] || 'mem.e_long')} /></div>
        ) : (
          <div className="rule">
            {items.map((f) => <FactRow key={f.id} f={f} busy={busy} run={run} cats={data.categories} />)}
          </div>
        )}
      </section>

      {layer === 'long' && <Lessons />}
    </div>
  )
}

/* «Как вы пишете» — 3–5 строк о стиле, собирается раз в неделю из ваших реплик; правится руками */
function StyleBlock({ st, busy, run }) {
  const [edit, setEdit] = useState(false)
  const [text, setText] = useState(st.style || '')
  useEffect(() => { if (!edit) setText(st.style || '') }, [st.style, edit])
  const { t } = useI18n()
  const save = () => run(() => api.setStyle(text), t('mem.style_fixed')).then(() => setEdit(false))
  return (
    <section>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <div className="label">{t('mem.how_you_write')}</div>
        <span className="faint text-[11px]">{st.style_at ? t('mem.noted_at', { when: ago(st.style_at) }) : t('mem.not_noted')}</span>
      </div>
      <div className="panel p-4 sm:p-5">
        {edit ? (
          <textarea autoFocus value={text} onChange={(e) => setText(e.target.value)} rows={5} className="input !h-auto w-full resize-none py-2 text-[14px] leading-relaxed" placeholder={t('mem.style_ph')} />
        ) : st.style ? (
          <div className="whitespace-pre-line text-[14.5px] leading-relaxed">{st.style}</div>
        ) : <div className="muted text-[13.5px]">{t('mem.style_hint')}</div>}
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
          {edit ? (
            <>
              <button className="text-accent hover:underline" disabled={busy} onClick={save}>{t('common.save')}</button>
              <button className="muted hover:underline" onClick={() => setEdit(false)}>{t('common.cancel')}</button>
            </>
          ) : (
            <>
              <button className="text-accent hover:underline disabled:opacity-40" disabled={busy} onClick={() => run(() => api.rebuildStyle(), t('mem.style_rebuilt'))}>{t('mem.rebuild_style')}</button>
              <button className="text-accent hover:underline" onClick={() => setEdit(true)}>{t('mem.fix')}</button>
              <span className="faint">· {t('mem.weekly_auto2')}</span>
            </>
          )}
        </div>
      </div>
    </section>
  )
}

/* Уроки — на чём переучился: «сайт 15000» → доход. Крестик — забыть урок */
const LESSON_RU = { expense: 'les.expense', income: 'les.income', debt: 'les.debt', order: 'les.order', task: 'les.task', event: 'les.event', note: 'les.note', mute: 'les.mute' }
function Lessons() {
  const { t } = useI18n()
  const [items, setItems] = useState(null)
  const load = () => api.lessons().then(setItems).catch(() => setItems([]))
  useEffect(() => { load() }, [])
  if (!items || items.length === 0) return null
  const del = async (id) => { try { await api.delLesson(id); toast(t('les.forgotten')); load() } catch (e) { toast(t('mem.failed'), { sub: e.message, kind: 'err' }) } }
  return (
    <section>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <div className="label">{t('les.title')}</div>
        <span className="faint text-[11px]">{t('les.n', { count: items.length })}</span>
      </div>
      <div className="muted mb-3 text-[13px]">{t('les.hint')}</div>
      <div className="rule">
        {items.map((l) => (
          <div key={l.id} className="row group">
            <div className="min-w-0 flex-1 text-[14px]">
              <span className="truncate">«{l.text}»</span>
              <span className="faint"> → </span>
              <span className="muted">{t(LESSON_RU[l.kind]) || l.kind}</span>
              {l.wrong && <span className="faint text-[12px]"> {t('les.was', { what: t(LESSON_RU[l.wrong]) || l.wrong })}</span>}
            </div>
            {l.uses > 0 && <span className="faint hidden shrink-0 text-[11px] sm:block">{t('les.used', { n: l.uses })}</span>}
            <button className="btn-icon !h-7 !w-7 shrink-0" onClick={() => del(l.id)} aria-label={t('les.forget')}><X size={13} /></button>
          </div>
        ))}
      </div>
    </section>
  )
}

function FactRow({ f, busy, run, cats }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState(false)
  const [text, setText] = useState(f.text)
  const save = () => { const next = text.trim(); if (!next || next === f.text) return setEdit(false); run(() => api.updateFact(f.id, { text: next }), t('mem.fixed')).then(() => setEdit(false)) }
  const color = CATS[f.category] || 'var(--ink-3)'
  /* метка «возможно устарело» — факт не трогали > 30 дней (только показ, данные не меняем) */
  const stale = (() => {
    const ts = f.updated_at || f.created_at
    return !!ts && f.layer !== 'archive' && (Date.now() - new Date(ts)) / 864e5 > 30
  })()
  return (
    <div className={`row cursor-pointer !items-start ${open ? '' : 'row-hover'}`} onClick={() => !edit && setOpen((v) => !v)} style={open ? { background: 'var(--fill)' } : {}}>
      <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} />
      <div className="min-w-0 flex-1">
        {edit ? (
          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <input autoFocus value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { setText(f.text); setEdit(false) } }} className="input !h-9" />
            <button className="btn-icon !h-8 !w-8" onClick={save} aria-label={t('common.save_changes')}><Check size={14} /></button>
          </div>
        ) : (
          <div className={`text-[14.5px] leading-snug ${open ? '' : 'truncate'}`}>{f.core && <Star size={12} className="mr-1 inline -mt-0.5" style={{ color: 'var(--warn)', fill: 'var(--warn)' }} />}{f.text}</div>
        )}
        {stale && <span className="soft-warn mt-1 inline-block rounded-full px-2 py-0.5 text-[11px]">{t('mem.maybe_stale')}</span>}
        {open && !edit && (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px]" style={{ animation: 'fade .16s ease-out' }} onClick={(e) => e.stopPropagation()}>
            <span className="muted">{f.category}</span>
            <span className="faint">· {ago(f.updated_at || f.created_at)}</span>
            {f.uses > 0 && <span className="faint">· {t('mem.used_n', { count: f.uses })}</span>}
            {f.layer === 'archive' && f.archive_reason && <span className="faint">· {f.archive_reason}{f.replaced_by ? ` → #${f.replaced_by}` : ''}</span>}
            {f.layer !== 'archive' ? (
              <>
                <button className="text-accent flex items-center gap-1 hover:underline" disabled={busy} onClick={() => setEdit(true)}><Pencil size={12} /> {t('mem.fix')}</button>
                <button className="text-accent flex items-center gap-1 hover:underline" disabled={busy} onClick={() => run(() => api.updateFact(f.id, { core: !f.core }), f.core ? t('mem.not_core') : t('mem.always_core'))}><Star size={12} /> {t(f.core ? 'mem.less_important' : 'mem.important')}</button>
                {f.layer === 'short' && <button className="text-accent hover:underline" disabled={busy} onClick={() => run(() => api.updateFact(f.id, { layer: 'long' }), t('mem.kept_long'))}>{t('mem.keep_long')}</button>}
                <button className="hover:underline" style={{ color: 'var(--neg)' }} disabled={busy} onClick={() => run(() => api.forgetFact(f.id), t('mem.forgotten'))}>{t('mem.forget')}</button>
              </>
            ) : (
              <button className="text-accent flex items-center gap-1 hover:underline" disabled={busy} onClick={() => run(() => api.restoreFact(f.id), t('mem.restored'))}><RotateCcw size={12} /> {t('mem.restore')}</button>
            )}
            {f.layer !== 'archive' && <Pills className="w-full" value={f.category} onChange={(c) => c !== f.category && run(() => api.updateFact(f.id, { category: c }))} options={(cats || []).map((c) => [c, c])} />}
          </div>
        )}
      </div>
      {!open && <span className="faint hidden shrink-0 text-[11px] sm:block">{ago(f.updated_at || f.created_at)}</span>}
    </div>
  )
}

/* ---------------- события: журнал всего, что ассистент понял и сделал ---------------- */
const KINDS = [
  { id: '', label: 'mem.k_all' },
  { id: 'event', label: 'mem.k_events', icon: CalendarDays, color: 'var(--accent)', to: '/calendar' },
  { id: 'task', label: 'mem.k_tasks', icon: CheckSquare, color: 'var(--pos)', to: '/tasks' },
  { id: 'finance', label: 'mem.k_money', icon: Wallet, color: 'var(--warn)', to: '/finance' },
  { id: 'note', label: 'mem.k_notes', icon: FileText, color: '#7c3aed', to: '/mind' },
  { id: 'link', label: 'mem.k_links', icon: Link2, color: '#0891b2', to: '/mind' },
  { id: 'chat', label: 'mem.k_chat', icon: MessageCircle, color: 'var(--ink-3)' },
  { id: 'system', label: 'mem.k_system', icon: Cpu, color: 'var(--ink-3)' },
  { id: 'presence', label: 'mem.k_presence', icon: Monitor, color: 'var(--ink-3)' },
  { id: 'aim', label: 'mem.k_aims', icon: Target, color: 'var(--accent)', to: '/tasks?view=aims' },
]
const K = Object.fromEntries(KINDS.map((k) => [k.id, k]))
const CH = { tg: 'ch_tg', 'tg-voice': 'ch_tg_voice', voice: 'ch_voice', web: 'ch_web', system: 'ch_system', test: 'mem.ch_test' }
// отсекаем служебный префикс ядра — это данные, не интерфейс   // i18n-raw
const clean = (s) => s.replace(/^(Мысль|Задача|Запланировано|Трата|Доход|Регулярный платёж|Ссылка):\s*/i, '')

function Journal() {
  const { t } = useI18n()
  const [kind, setKind] = useState('')
  const [days, setDays] = useState(30)
  const [q, setQ] = useState('')
  const [items, setItems] = useState(null)
  const [openId, setOpenId] = useState(null)
  const { tick } = useRefresh()

  useEffect(() => {
    const t = setTimeout(() => api.memory(days, kind || undefined, q || undefined).then(setItems).catch(() => setItems([])), q ? 250 : 0)
    return () => clearTimeout(t)
  }, [kind, days, q, tick])

  const counts = useMemo(() => { const c = {}; for (const x of items || []) c[x.kind] = (c[x.kind] || 0) + 1; return c }, [items])
  const groups = useMemo(() => {
    const m = new Map()
    for (const x of items || []) { const k = new Date(x.created_at).toDateString(); if (!m.has(k)) m.set(k, []); m.get(k).push(x) }
    return [...m.entries()]
  }, [items])

  const n = (items || []).length
  return (
    <div className="space-y-6">
      {/* поиск + категории */}
      <div className="animate-rise space-y-3">
        <div className="flex items-center justify-between gap-2">
          <div className="label">{t('mem.entries_n', { count: n })}</div>
          <Seg value={days} onChange={setDays} options={[[7, t('mem.d7')], [30, t('mem.d30')], [365, t('mem.d365')]]} />
        </div>
        <div className="composer flex items-center gap-2 py-1.5 pl-4 pr-2">
          <Search size={16} className="faint shrink-0" />
          <input value={q} onChange={(e) => setQ(e.target.value)} className="h-9 w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]" placeholder={t('mem.search_ph')} />
          {q && <button className="btn-icon !h-8 !w-8" onClick={() => setQ('')} aria-label={t('tk.clear_search')}><X size={14} /></button>}
        </div>
        <div className="no-scrollbar -mx-1 flex gap-1.5 overflow-x-auto px-1">
          {KINDS.map((k) => (
            <button key={k.id} onClick={() => setKind(k.id)} className={`pill shrink-0 ${kind === k.id ? 'on' : ''}`}>
              {k.icon && <span className="h-1.5 w-1.5 rounded-full" style={{ background: kind === k.id ? 'currentColor' : k.color }} />}
              {k.label}{k.id && counts[k.id] && !kind ? <span className="idx !text-[10px] opacity-60">{counts[k.id]}</span> : null}
            </button>
          ))}
        </div>
      </div>

      {!items ? <ListSkeleton n={6} /> : groups.length === 0 ? (
        <div className="rule"><Empty glyph="memory" text={t(q ? 'common.no_results' : 'mem.empty')} sub={t(q ? 'mem.try_words' : 'mem.everything_here')} hint={q ? undefined : t('mem.hint_example')} /></div>
      ) : (
        <div className="space-y-7">
          {groups.map(([day, list]) => (
            <section key={day} className="animate-rise">
              <div className="mb-1.5 flex items-baseline gap-2"><div className="label">{dayLabel(day)}</div><span className="faint text-[11px]">{shortDate(day)} · {t('mem.entries_n', { count: list.length })}</span></div>
              <div className="rule">
                {list.map((m) => <Entry key={m.id} m={m} open={openId === m.id} onToggle={() => setOpenId(openId === m.id ? null : m.id)} />)}
              </div>
            </section>
          ))}
          {n >= 300 && <div className="faint text-center text-[12px]">{t('mem.capped')}</div>}
        </div>
      )}
    </div>
  )
}

function Entry({ m, open, onToggle }) {
  const { t } = useI18n()
  const k = K[m.kind] || {}
  const I = k.icon || MessageCircle
  const text = clean(m.text)
  return (
    <div className={`row cursor-pointer !items-start ${open ? '' : 'row-hover'}`} onClick={onToggle} style={open ? { background: 'var(--fill)' } : {}}>
      <span className="faint num mt-[3px] w-11 shrink-0 text-[12px]">{hhmm(m.created_at)}</span>
      <span className="mt-[3px] grid h-[18px] w-[18px] shrink-0 place-items-center" style={{ color: k.color || 'var(--ink-3)' }}><I size={14} /></span>
      <div className="min-w-0 flex-1">
        <div className={`text-[14.5px] leading-snug ${open ? '' : 'truncate'}`}>{text}</div>
        {open && (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]" style={{ animation: 'fade .16s ease-out' }}>
            <span className="muted">{k.label ? t(k.label) : m.kind}</span>
            <span className="faint">· {t('mem.source', { what: CH[m.channel] ? t(CH[m.channel]) : m.channel })}</span>
            <span className="faint">· {new Date(m.created_at).toLocaleString(localeOf(), { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }).replace(/\.?\s*г\.$/u, '')}</span>
            {k.to && <Link to={k.to} className="text-accent flex items-center gap-0.5 hover:underline" onClick={(e) => e.stopPropagation()}>{t('mem.open_in', { what: t(k.label) })} <ArrowUpRight size={12} /></Link>}
            {m.kind !== 'system' && <button className="text-accent hover:underline" onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: T('mem.ask_seed', { what: text.slice(0, 60) }) } })) }}>{t('mem.ask')}</button>}
          </div>
        )}
      </div>
      {!open && m.channel && m.channel !== 'web' && <span className="faint hidden shrink-0 text-[11px] sm:block">{CH[m.channel] || m.channel}</span>}
    </div>
  )
}


/* Лента дня: человек и ассистент одной хронологией — сессии за ПК (≥15 мин), действия, события присутствия, разговор (счётчик), провалы. */
const WHO_ME = 'я'   // i18n-raw — ключ из лога ядра
const WHO = { 'я': { label: 'mem.w_you', color: 'var(--ink)' }, 'джарвис': { label: 'mem.w_assistant', color: 'var(--accent)', icon: Bot }, 'пк': { label: 'mem.w_pc', color: 'var(--ink-3)', icon: Monitor } }
function Timeline() {
  const { t } = useI18n()
  const [day, setDay] = useState(0)   // 0 сегодня, 1 вчера…
  const [q, setQ] = useState('')
  const [items, setItems] = useState(null)
  const { tick } = useRefresh()
  const date = useMemo(() => { const d = new Date(); d.setDate(d.getDate() - day); return d }, [day])
  useEffect(() => {
    const iso = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    api.get(`/api/timeline?day=${iso}${q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ''}`).then(setItems).catch(() => setItems([]))
  }, [day, q, tick])
  return (
    <div className="space-y-5 animate-rise">
      <div className="flex flex-wrap items-center gap-2">
        <Seg value={day} onChange={setDay} options={[[0, t('common.today')], [1, t('common.yesterday')], [2, t('mem.day_before')]]} />
        <label className="relative ml-auto block w-full sm:w-64">
          <Search size={14} className="faint absolute left-3 top-1/2 -translate-y-1/2" />
          <input value={q} onChange={(e) => setQ(e.target.value)} className="input !h-9 !pl-9 !text-[14px]" placeholder={t('mem.timeline_search_ph')} />
        </label>
      </div>
      {!items ? <ListSkeleton n={6} /> : items.length === 0 ? (
        <div className="rule"><Empty glyph="memory" text={t(q ? 'mem.timeline_none' : 'mem.timeline_empty')} sub={t(q ? 'mem.timeline_other' : 'mem.timeline_hint')} /></div>
      ) : (
        <div className="rule">
          {items.map((it, i) => {
            const w = WHO[it.who] || WHO[WHO_ME]
            const I = w.icon
            return (
              <div key={i} className={`row !items-start ${it.kind === 'fail' ? 'opacity-70' : ''}`}>
                <span className="faint num mt-[3px] w-11 shrink-0 text-[12px]">{hhmm(it.at)}</span>
                <span className="mt-[3px] grid h-[18px] w-[18px] shrink-0 place-items-center" style={{ color: w.color }}>{I ? <I size={14} /> : <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'var(--ink-2)' }} />}</span>
                <div className="min-w-0 flex-1">
                  <div className={`text-[14.5px] leading-snug ${it.kind === 'screen' ? 'muted' : ''}`}>{clean(it.text)}</div>
                </div>
                {it.who !== WHO_ME && <span className="faint hidden shrink-0 text-[11px] sm:block">{t(w.label)}</span>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
