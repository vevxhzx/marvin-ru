import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, CalendarDays, CheckSquare, Wallet, FileText, Link2, MessageCircle, Cpu, ArrowUpRight, X } from 'lucide-react'
import { api, hhmm, dayLabel, shortDate, plural } from '../lib/api'
import { Empty, Seg, PageHead, ListSkeleton } from '../components/ui'
import { useRefresh } from '../App'
import { name as aName } from '../lib/name'

/* Память — журнал всего, что ассистент понял и сделал. Категории, источник, время, переход к самой записи. */
const KINDS = [
  { id: '', label: 'всё' },
  { id: 'event', label: 'события', icon: CalendarDays, color: 'var(--accent)', to: '/calendar' },
  { id: 'task', label: 'задачи', icon: CheckSquare, color: 'var(--pos)', to: '/tasks' },
  { id: 'finance', label: 'деньги', icon: Wallet, color: 'var(--warn)', to: '/finance' },
  { id: 'note', label: 'мысли', icon: FileText, color: '#7c3aed', to: '/mind' },
  { id: 'link', label: 'ссылки', icon: Link2, color: '#0891b2', to: '/mind' },
  { id: 'chat', label: 'разговор', icon: MessageCircle, color: 'var(--ink-3)' },
  { id: 'system', label: 'система', icon: Cpu, color: 'var(--ink-3)' },
]
const K = Object.fromEntries(KINDS.map((k) => [k.id, k]))
const CH = { tg: 'telegram', 'tg-voice': 'telegram · голос', voice: 'голос', web: 'сайт', system: 'авто', test: 'тест' }
const clean = (s) => s.replace(/^(Мысль|Задача|Запланировано|Трата|Доход|Регулярный платёж|Ссылка):\s*/i, '')

export default function Memory() {
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
    <div className="space-y-8">
      <PageHead kicker={`что ${aName().toLowerCase()} понял и сделал`} title="память" idx={n}
        right={<Seg value={days} onChange={setDays} options={[[7, '7 дн'], [30, '30 дн'], [365, 'год']]} />} />

      {/* поиск + категории */}
      <div className="animate-rise space-y-3">
        <div className="composer flex items-center gap-2 py-1.5 pl-4 pr-2">
          <Search size={16} className="faint shrink-0" />
          <input value={q} onChange={(e) => setQ(e.target.value)} className="h-9 w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]" placeholder="Когда у меня была встреча с… / сколько на такси…" />
          {q && <button className="btn-icon !h-8 !w-8" onClick={() => setQ('')} aria-label="Очистить"><X size={14} /></button>}
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
        <div className="rule"><Empty glyph="memory" text={q ? 'Ничего не нашёл' : 'Пусто'} sub={q ? 'Попробуйте другими словами — я ищу по смыслу, а не по буквам' : 'Всё, что вы говорите ассистенту, появится здесь с датой и источником'} hint={q ? undefined : 'мысль: идея для проекта'} /></div>
      ) : (
        <div className="space-y-7">
          {groups.map(([day, list]) => (
            <section key={day} className="animate-rise">
              <div className="mb-1.5 flex items-baseline gap-2"><div className="label">{dayLabel(day)}</div><span className="faint text-[11px]">{shortDate(day)} · {list.length} {plural(list.length, 'запись', 'записи', 'записей')}</span></div>
              <div className="rule">
                {list.map((m) => <Entry key={m.id} m={m} open={openId === m.id} onToggle={() => setOpenId(openId === m.id ? null : m.id)} />)}
              </div>
            </section>
          ))}
          {n >= 300 && <div className="faint text-center text-[12px]">показаны последние 300 — уточните поиск или период</div>}
        </div>
      )}
    </div>
  )
}

function Entry({ m, open, onToggle }) {
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
            <span className="muted">{k.label || m.kind}</span>
            <span className="faint">· источник: {CH[m.channel] || m.channel}</span>
            <span className="faint">· {new Date(m.created_at).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })}</span>
            {k.to && <Link to={k.to} className="text-accent flex items-center gap-0.5 hover:underline" onClick={(e) => e.stopPropagation()}>открыть в «{k.label}» <ArrowUpRight size={12} /></Link>}
            {m.kind !== 'system' && <button className="text-accent hover:underline" onClick={(e) => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: `про «${text.slice(0, 60)}»: ` } })) }}>спросить ассистента</button>}
          </div>
        )}
      </div>
      {!open && m.channel && m.channel !== 'web' && <span className="faint hidden shrink-0 text-[11px] sm:block">{CH[m.channel] || m.channel}</span>}
    </div>
  )
}
