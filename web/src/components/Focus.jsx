import { useEffect, useState } from 'react'
import { Check, Target, ArrowUpRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Section, useLeave } from './ui'

const ask = (text) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } }))

/* Фокус дня: 1–3 шага, которые двигают цели (не список всех задач). Рисуется только если цели есть.
   Галочка — та же complete_task, что и везде; после неё ассистент сам скажет, что продвинулось. */
export default function Focus({ tick, onDone }) {
  const [f, setF] = useState(null)
  const [leaveCls, leave] = useLeave()
  useEffect(() => { api.get('/api/focus').then(setF).catch(() => setF(null)) }, [tick])
  if (!f || !f.aims) return null
  const done = (it) => leave(it.task_id, 'done', async () => { await api.doneTask(it.task_id); setF(await api.get('/api/focus').catch(() => f)); onDone?.() })
  return (
    <Section title="фокус дня" idx={f.items.length || undefined}
      action={<Link to="/tasks?view=aims" className="btn-ghost btn-sm flex items-center gap-1">цели <ArrowUpRight size={12} /></Link>}>
      {!f.items.length && !f.blocked.length ? (
        <div className="muted text-[13px]">По целям всё, что можно, сделано. Следующая веха — за вами.</div>
      ) : (
        <div className="rule stagger">
          {f.items.map((it, i) => it.task_id == null ? (
            <button key={`h${i}`} type="button" className="row w-full text-left" onClick={() => ask(it.title.startsWith('Поставить') ? `веха: ` : `задача: … к вехе ${it.why}`)}>
              <span className="grid h-[22px] w-[22px] shrink-0 place-items-center"><Target size={13} className="faint" /></span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[15px] text-[var(--ink-2)]">{it.title}</div>
                <div className="muted truncate text-[12px]">{it.aim} · нажмите, чтобы сказать ассистенту</div>
              </div>
            </button>
          ) : (
            <div key={it.task_id} className={`row row-slide group done-fade ${leaveCls(it.task_id)}`}>
              <button onClick={() => done(it)} aria-label="Сделано" className={`grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full border transition-all duration-300 hover:scale-110 active:scale-90 ${leaveCls(it.task_id).includes('done') ? 'border-accent bg-accent text-accent-ink' : 'hover:border-accent'}`} style={{ borderColor: 'var(--line-2)' }}>
                <Check size={12} className={leaveCls(it.task_id).includes('done') ? 'check-pop' : 'opacity-0 transition group-hover:opacity-40'} strokeWidth={3} />
              </button>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[15px] font-medium">{it.title}</div>
                <div className="muted flex items-center gap-1 truncate text-[12px]"><Target size={11} /> {it.aim}{it.why && it.why !== 'цель' && it.why !== 'главная цель' ? ` · ${it.why}` : ''}</div>
              </div>
            </div>
          ))}
          {f.blocked.map((b) => (
            <div key={`b${b.task_id}`} className="row opacity-60">
              <span className="grid h-[22px] w-[22px] shrink-0 place-items-center text-[12px]">⏸</span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px]">{b.title}</div>
                <div className="warn truncate text-[12px]">мешает: {b.blocked_by}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  )
}
