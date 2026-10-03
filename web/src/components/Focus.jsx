import { useEffect, useState } from 'react'
import { Check, Target, ArrowUpRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Section, Pressable, useLeave } from './ui'
import { useI18n, SERVER } from '../lib/i18n'

const ask = (text) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } }))

/* Фокус дня: 1–3 шага, которые двигают цели (не список всех задач). Рисуется только если цели есть.
   Галочка — та же complete_task, что и везде; после неё ассистент сам скажет, что продвинулось.
   Строка — спокойная: слева название и подпись, справа зона нажатия --tap. Длинные названия
   и цели не обрезаются молча: оба текста усекаются многоточием и уходят в title. */
export default function Focus({ tick, onDone }) {
  const { t } = useI18n()
  const [f, setF] = useState(null)
  const [leaveCls, leave] = useLeave()
  useEffect(() => { api.get('/api/focus').then(setF).catch(() => setF(null)) }, [tick])
  if (!f || !f.aims) return null
  const done = (it) => leave(it.task_id, 'done', async () => { await api.doneTask(it.task_id); setF(await api.get('/api/focus').catch(() => f)); onDone?.() })
  // «цель»/«главная цель» — служебные подписи от сервера, в EN это просто Goal / Main goal
  const whys = new Set([t('focus.why_goal'), t('focus.why_main')])
  const whyOf = (it) => (it.why ? t.sv(it.why) : '')
  const doneCls = (id) => leaveCls(id).includes('done')

  return (
    <Section title={t('focus.title')} idx={f.items.length || undefined}
      action={<Link to="/tasks?view=aims" className="btn-ghost btn-sm flex items-center gap-1">{t('focus.goals')} <ArrowUpRight size={12} /></Link>}>
      {!f.items.length && !f.blocked.length ? (
        <div className="muted" style={{ fontSize: 'var(--fs-md)', lineHeight: 'var(--lh-body)' }}>{t('focus.all_done')}</div>
      ) : (
        <div className="rule stagger">
          {f.items.map((it, i) => {
            const why = whyOf(it)
            return it.task_id == null ? (
              <Pressable key={`h${i}`} className="row min-h-[var(--tap)] w-full text-left" title={it.title}
                onClick={() => ask(it.title.startsWith(SERVER.focus_title_set.ru) ? t('focus.seed_milestone') : t('focus.seed_task', { why: t.sv(it.why) }))}>
                <span className="grid h-[var(--tap)] w-[26px] shrink-0 place-items-center" aria-hidden="true"><Target size={14} className="faint" /></span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium tracking-[-0.01em]" style={{ fontSize: 'var(--fs-base)' }}>{it.title}</span>
                  <span className="muted block truncate" style={{ fontSize: 'var(--fs-xs)', lineHeight: 'var(--lh-snug)' }}>{it.aim} · {t('focus.tap_hint')}</span>
                </span>
              </Pressable>
            ) : (
              <div key={it.task_id} className={`row row-slide done-fade min-h-[var(--tap)] ${leaveCls(it.task_id)}`}>
                <Pressable onClick={() => done(it)} aria-label={t('focus.done')} title={it.title}
                  className={`grid h-[var(--tap)] w-[var(--tap)] shrink-0 place-items-center rounded-full transition-transform active:scale-95 ${doneCls(it.task_id) ? 'bg-accent text-accent-ink' : ''}`}
                  style={{ marginLeft: -11, color: doneCls(it.task_id) ? undefined : 'var(--ink-3)' }}>
                  <span className={`grid h-[22px] w-[22px] place-items-center rounded-full transition-colors ${doneCls(it.task_id) ? '' : 'border'}`}
                    style={{ borderColor: doneCls(it.task_id) ? undefined : 'var(--line-2)' }}>
                    <Check size={12} className={doneCls(it.task_id) ? 'check-pop' : ''} strokeWidth={3} />
                  </span>
                </Pressable>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium tracking-[-0.01em]" style={{ fontSize: 'var(--fs-base)' }} title={it.title}>{it.title}</div>
                  <div className="muted flex items-center gap-1 truncate" style={{ fontSize: 'var(--fs-xs)', lineHeight: 'var(--lh-snug)' }} title={it.aim}>
                    <Target size={11} aria-hidden="true" className="shrink-0" /> {it.aim}{why && !whys.has(why) ? ` · ${why}` : ''}
                  </div>
                </div>
              </div>
            )
          })}
          {f.blocked.map((b) => (
            <div key={`b${b.task_id}`} className="row min-h-[var(--tap)] opacity-60">
              <span className="grid h-[var(--tap)] w-[26px] shrink-0 place-items-center" style={{ fontSize: 'var(--fs-xs)' }} aria-hidden="true">⏸</span>
              <div className="min-w-0 flex-1">
                <div className="truncate" style={{ fontSize: 'var(--fs-base)' }} title={b.title}>{b.title}</div>
                <div className="warn truncate" style={{ fontSize: 'var(--fs-xs)', lineHeight: 'var(--lh-snug)' }}>{t('focus.blocked_by', { what: b.blocked_by })}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  )
}