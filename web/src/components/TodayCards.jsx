/* Блоки главной («сегодня»): быстрое дело, дневной лимит, цели, привычки,
   ближайшее дело.

   Все они «безголовые»: заголовок блока рисует сама главная (Today.jsx) — он общий
   для всех блоков, иначе у каждого своя шапка и экран снова превращается в набор
   коробок. Здесь только содержание: числа, строки и полоски.

   Каждый блок — самостоятельный виджет: скрывается, двигается и меняет ширину через
   общий механизм lib/layout, ничего вне главной не меняет.
   Данные — только из тех же ответов API, что уже грузит Today.jsx (dashboard/finance). */
import { useState } from 'react'
import { ArrowUpRight, Flame, Plus, Target, Timer, Zap } from 'lucide-react'
import { api, hhmm, isAllDay, money } from '../lib/api'
import { useI18n, t as T } from '../lib/i18n'
import { Streak, Heatmap, useNumFormats, useBigSize } from './Widgets'
import { useTip } from './ChartTip'

const dm = (s) => `${s.slice(8, 10)}.${s.slice(5, 7)}`

/* ---------- «быстрое дело»: добавляем задачу или трату одной строкой ---------- */
export function QuickAddWidget({ onDone, onErr }) {
  const { t } = useI18n()
  const [mode, setMode] = useState('task')   // task | expense
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  const send = async () => {
    const txt = text.trim()
    if (!txt || busy) return
    setBusy(true)
    try {
      // те же шаблоны, что и на странице задач и в чипсах: «задача: …» / «трата: …».
      // Правила ядра понимают их без LLM, поэтому строка уходит мгновенно.
      await api.chat(`${mode === 'task' ? T('qa.seed_task') : T('qa.seed_expense')}: ${txt}`)
      setText('')
      onDone?.(t(mode === 'task' ? 'qa.added' : 'qa.expense_added'))
    } catch (e) {
      onErr?.(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {/* переключатель: дело или трата */}
      <div className="seg mb-3" role="group" aria-label={t('qa.title')}>
        <button type="button" className={mode === 'task' ? 'on' : ''} aria-pressed={mode === 'task'} onClick={() => setMode('task')}>{t('qa.task')}</button>
        <button type="button" className={mode === 'expense' ? 'on' : ''} aria-pressed={mode === 'expense'} onClick={() => setMode('expense')}>{t('qa.expense')}</button>
      </div>

      <div className="flex items-center gap-2 rounded-full pl-4 pr-1.5" style={{ background: 'var(--sf2)', border: '1px solid var(--line)', height: 52 }}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder={t(mode === 'task' ? 'qa.ph_task' : 'qa.ph_expense')}
          aria-label={t(mode === 'task' ? 'qa.ph_task' : 'qa.ph_expense')}
          className="min-w-0 flex-1 bg-transparent text-[length:var(--fs-base)] outline-none"
          style={{ color: 'var(--ink)' }}
        />
        <button
          type="button"
          onClick={send}
          disabled={busy || !text.trim()}
          className="btn !h-9 !w-9 !p-0 disabled:opacity-40"
          aria-label={t('common.add')}
          title={t('common.add')}
        >
          <Plus size={17} />
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {(mode === 'task' ? ['qa.ex_task1', 'qa.ex_task2'] : ['qa.ex_exp1', 'qa.ex_exp2']).map((k) => (
          <button key={k} type="button" className="chip !mt-0 !text-[length:var(--fs-xs)]" onClick={() => setText(t(k))}>{t(k)}</button>
        ))}
      </div>
    </div>
  )
}

/* ---------- «можно потратить сегодня» + ближайший платёж ---------- */
export function SpendTodayWidget({ runway, payments }) {
  const { t } = useI18n()
  const fmt = useNumFormats()
  const big = useBigSize('var(--hero-fs-2)')
  const rw = runway || {}
  const pay = payments || {}
  const list = (pay.payments || []).slice().sort((a, b) => new Date(a.date) - new Date(b.date))
  const next = list[0]
  const safe = Math.round(rw.safe_per_day || 0)
  const free = Math.round(rw.free || 0)
  const perDay = Math.round(rw.per_day_avg || 0)
  const days = rw.days_left_to_income
  const short = Math.round(pay.short || 0)

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="big" style={{ fontSize: big }}>
          <span className="num">{fmt.int(safe)}</span>
          <span style={{ fontSize: '0.55em', fontWeight: 400, opacity: 0.7, marginLeft: '0.12em' }}>₽</span>
        </span>
        <span className="muted text-[length:var(--fs-md)]">
          {t(days != null ? 'spend.until_income' : 'spend.by_pace', { count: days })}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[length:var(--fs-md)]">
        <span className="muted">{t('spend.free')} <b className="num text-[var(--ink)]">{money(free)}</b></span>
        <span className="muted">{t('spend.per_day')} <b className="num text-[var(--ink)]">{money(perDay)}</b></span>
      </div>

      <div className="mt-3 flex items-center gap-2 text-[length:var(--fs-md)]">
        <Timer size={14} className="shrink-0" />
        {next ? (
          <>
            <span className="min-w-0 flex-1 trunc">{t('spend.next', { title: next.title })}</span>
            <b className="num shrink-0 whitespace-nowrap">{money(next.amount)}</b>
            <span className="mono shrink-0 text-[var(--ink3)]">{dm(next.date)}</span>
          </>
        ) : (
          <span className="muted">{t('spend.no_payments')}</span>
        )}
      </div>
      {short > 0 && <div className="mt-1 text-[length:var(--fs-xs)] font-semibold text-[var(--neg)]">{t('spend.short', { m: money(short) })}</div>}
    </div>
  )
}

/* ---------- «цели»: прогресс + фокус дня ---------- */
export function GoalsWidget({ goals, tasks, onOpen }) {
  const { t } = useI18n()
  const fmt = useNumFormats()
  const tip = useTip()               // подсказка на полоске прогресса: сколько накоплено и когда ждать
  const list = (goals || []).slice().sort((a, b) => {
    const ax = a.days_left == null ? 9e9 : a.days_left
    const bx = b.days_left == null ? 9e9 : b.days_left
    return ax - bx
  }).slice(0, 3)
  const focus = (tasks || []).filter((x) => !x.done).sort((a, b) => (a.priority || 9) - (b.priority || 9))[0]
  const pctOf = (g) => Math.round((g.pct || 0) * 100)
  const tail = (g) => (g.days_left != null ? (g.days_left < 0 ? t('goals.overdue') : t('goals.in_days', { count: g.days_left })) : (g.per_month ? t('goals.per_month', { m: money(g.per_month) }) : ''))
  const savedLine = (g) => t('tip.saved_of', { m: money(g.saved), target: money(g.target) })
  const cur = tip.active?.i != null ? list[tip.active.i] : null

  return (
    <div>
      {focus && (
        <div className="rule pt-3">
          <div className="label">{t('focus.title')}</div>
          <div className="clamp-2 mt-1 text-[length:var(--fs-base)] font-medium leading-snug">{focus.title}</div>
          {focus.due && <div className="mt-0.5 text-[length:var(--fs-xs)] text-[var(--ink3)]">{t('goals.by', { time: hhmm(focus.due) })}</div>}
        </div>
      )}

      <div className="relative" ref={tip.hostRef} {...tip.host}>
        {list.map((g, gi) => {
          const pct = pctOf(g)
          // подсказка и подпись для скринридера — одна и та же строка
          const aria = `${g.title}: ${savedLine(g)}, ${t('tip.pct', { p: pct })}${tail(g) ? `, ${tail(g)}` : ''}`
          return (
            <div key={g.id} className="row chart-pt" {...tip.bind(gi, aria, 'group')}>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 text-[length:var(--fs-md)]">
                  <span aria-hidden="true">{g.icon || '🎯'}</span>
                  <span className="min-w-0 flex-1 trunc font-medium">{g.title}</span>
                  <span className="mono shrink-0 text-[length:var(--fs-xs)] text-[var(--ink3)]">{fmt.int(pct)} %</span>
                </div>
                <div className="progress mt-2">
                  <div style={{ width: `${Math.max(2, pct)}%` }} />
                </div>
                <div className="mt-1 flex items-baseline justify-between gap-3 text-[length:var(--fs-xs)] text-[var(--ink3)]">
                  <span className="num trunc">{fmt.nb(`${money(g.saved)} / ${money(g.target)}`)}</span>
                  <span className="shrink-0">{tail(g)}</span>
                </div>
              </div>
            </div>
          )
        })}
        {!list.length && <div className="muted pt-3 text-[length:var(--fs-md)]">{t('goals.none')}</div>}
      </div>

      {/* наведение, тап или стрелки на строке цели — сколько накоплено и когда ждать */}
      {tip.panel({
        title: cur ? `${cur.icon || '🎯'} ${cur.title}` : null,
        rows: cur ? [savedLine(cur), t('tip.pct', { p: pctOf(cur) }), tail(cur)].filter(Boolean) : [],
      })}

      {onOpen && (
        <button type="button" className="chip !mt-3 self-start !text-[length:var(--fs-xs)]" onClick={onOpen}>
          {t('goals.all')} <ArrowUpRight size={13} />
        </button>
      )}
    </div>
  )
}

/* ---------- «привычки»: стрик ведения дня + тепловая карта ---------- */
export function HabitsWidget({ streak }) {
  const { t } = useI18n()
  if (!streak) return <div className="muted text-[length:var(--fs-md)]">{t('habits.hint')}</div>
  return (
    <div>
      <Streak streak={streak} />
      {!streak.current && (
        <div className="mt-2 text-[length:var(--fs-md)] text-[var(--ink2)]">{t('habits.hint')}</div>
      )}
      {!!(streak.heatmap || []).length && (
        <div className="mt-3 pt-3">
          <Heatmap heatmap={streak.heatmap} weeks={13} />
        </div>
      )}
    </div>
  )
}

/* ---------- «ближайшее дело»: следующая встреча/задача и свободное окно до неё ---------- */
export function NextUpWidget({ events, tasks, onOpen }) {
  const { t } = useI18n()
  const fmt = useNumFormats()
  const now = new Date()
  const big = useBigSize('var(--hero-fs-2)')
  const items = []
  for (const e of events || []) {
    if (e.done || isAllDay(e.start)) continue
    items.push({ key: `e${e.id}`, kind: 'event', title: e.title, at: new Date(e.start) })
  }
  for (const x of tasks || []) {
    if (x.done || !x.due || isAllDay(x.due)) continue
    items.push({ key: `t${x.id}`, kind: 'task', title: x.title, at: new Date(x.due) })
  }
  // только сегодняшние дела: так «свободное окно» всегда в разумных часах,
  // а не «свободно 240 ч» из-за задачи на следующей неделе
  const upcoming = items
    .filter((x) => x.at.toDateString() === now.toDateString() && x.at - now >= -60000)
    .sort((a, b) => a.at - b.at)
  const next = upcoming[0]
  const freeMin = next ? Math.max(0, Math.round((next.at - now) / 60000)) : null
  const fh = freeMin != null ? Math.floor(freeMin / 60) : 0
  const fm = freeMin != null ? freeMin % 60 : 0

  return (
    <div>
      {next ? (
        <>
          <div className="num" style={{ fontSize: big, fontWeight: 500, letterSpacing: '-0.04em', lineHeight: 1.1 }}>{hhmm(next.at)}</div>
          <div className="clamp-2 mt-1 text-[length:var(--fs-base)] font-medium leading-snug">{next.title}</div>
          <div className="mt-2 inline-flex items-center gap-1.5 self-start rounded-full px-3 py-1 text-[length:var(--fs-xs)] font-medium"
            style={{ background: 'var(--accent-soft)', color: 'var(--acc)' }}>
            <Timer size={13} /> {t('nextup.free')} {fh ? `${fmt.int(fh)} ${t('unit.hour')} ` : ''}{fmt.int(fm)} {t('unit.min')}
          </div>
        </>
      ) : (
        <>
          <div className="muted text-[length:var(--fs-lg)]">{t('nextup.all_free')}</div>
        </>
      )}

      {upcoming.length > 1 && (
        <div className="rule mt-3 pt-1">
          {upcoming.slice(1, 3).map((x) => (
            <div key={x.key} className="row" style={{ color: 'var(--ink2)', fontSize: 'var(--fs-md)' }}>
              <span className="mono shrink-0">{hhmm(x.at)}</span>
              <span className="trunc">{x.title}</span>
            </div>
          ))}
        </div>
      )}

      {next && onOpen && (
        <button type="button" className="chip !mt-3 self-start !text-[length:var(--fs-xs)]" onClick={() => onOpen(next.kind)}>
          {t(next.kind === 'event' ? 'nextup.to_cal' : 'nextup.to_tasks')} <ArrowUpRight size={13} />
        </button>
      )}
    </div>
  )
}