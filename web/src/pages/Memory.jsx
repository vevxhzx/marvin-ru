import { useEffect, useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { api, hhmm, dayLabel, shortDate } from '../lib/api'
import { Card, Empty, Seg, Pills, Skeleton, PageHead } from '../components/ui'
import { useRefresh } from '../App'

const KINDS = [['', 'всё'], ['event', 'события'], ['task', 'задачи'], ['finance', 'деньги'], ['note', 'мысли'], ['link', 'ссылки']]
const ICON = { event: '📅', task: '✅', finance: '💸', note: '📝', link: '🔗', chat: '💬', system: '⚙️' }
const CH = { tg: 'Telegram', voice: 'голос', web: 'сайт', system: 'авто', test: 'тест' }

export default function Memory() {
  const [kind, setKind] = useState('')
  const [days, setDays] = useState(30)
  const [q, setQ] = useState('')
  const [items, setItems] = useState(null)
  const { tick } = useRefresh()

  useEffect(() => {
    const t = setTimeout(() => api.memory(days, kind || undefined, q || undefined).then(setItems).catch(() => {}), q ? 250 : 0)
    return () => clearTimeout(t)
  }, [kind, days, q, tick])

  const groups = useMemo(() => {
    const m = new Map()
    for (const x of items || []) { const k = new Date(x.created_at).toDateString(); if (!m.has(k)) m.set(k, []); m.get(k).push(x) }
    return [...m.entries()]
  }, [items])

  return (
    <div className="space-y-8">
      <PageHead kicker="всё, что вы мне говорили" title="память" idx={(items || []).length}
        right={<><Pills value={kind} onChange={setKind} options={KINDS} /><Seg value={days} onChange={setDays} options={[[7, '7 дн'], [30, '30 дн'], [365, 'год']]} /></>} />

      <div className="animate-rise relative">
        <Search size={17} className="faint absolute left-4 top-1/2 -translate-y-1/2" />
        <input value={q} onChange={(e) => setQ(e.target.value)} className="input !rounded-full !pl-11" placeholder="Когда у меня была встреча с…" />
      </div>

      {!items ? <Skeleton h={300} /> : groups.length === 0 ? <div className="rule"><Empty glyph="memory" text="Пусто" sub="Всё, что вы говорите ассистенту, появится здесь" /></div> : (
        <div className="space-y-5">
          {groups.map(([day, list]) => (
            <div key={day} className="animate-rise">
              <div className="label mb-1.5">{dayLabel(day)} · {shortDate(day)}</div>
              <div className="rule">
                <div className="relative">
                  <div className="absolute left-[57px] top-4 bottom-4 w-px" style={{ background: 'var(--line)' }} />
                  {list.map((m) => (
                    <div key={m.id} className="row !border-0 relative">
                      <span className="faint num w-11 shrink-0 text-[12px]">{hhmm(m.created_at)}</span>
                      <span className="relative z-10 grid h-7 w-7 shrink-0 place-items-center rounded-full text-sm" style={{ border: '1px solid var(--line)', background: 'var(--bg)' }}>{ICON[m.kind] || '•'}</span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[15px]">{m.text}</div>
                        <div className="faint text-[11px]">{CH[m.channel] || m.channel}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
