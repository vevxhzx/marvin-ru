/* Новые карточки главной («сегодня»): быстрое дело, дневной лимит, цели, привычки,
   ближайшее дело. Каждая — самостоятельный виджет: скрывается, двигается и меняет
   ширину через общий механизм lib/layout, ничего вне главной не меняет.
   Данные — только из тех же ответов API, что уже грузит Today.jsx (dashboard/finance). */
import { useState } from 'react'
import { ArrowUpRight, Flame, Plus, Target, Timer, Zap } from 'lucide-react'
import { api, hhmm, isAllDay, money } from '../lib/api'
import { useI18n, t as T } from '../lib/i18n'
import { Streak, Heatmap } from './Widgets'
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
    <div className="flex h-full flex-col">
      <div className="hd">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-xl" style={{ background: 'var(--accent-soft)', color: 'var(--acc)' }}>
            <Zap size={15} />
          </span>
          <h2>{t('qa.title')}</h2>
        </div>
        <small>{t('qa.sub')}</small>
      </div>

      {/* переключатель: дело или трата */}
      <div className="mb-2.5 inline-flex self-start rounded-full p-[3px] text-[13px]" style={{ background: 'var(--sf2)', border: '1px solid var(--line)' }}>
        {[['task', 'qa.task'], ['expense', 'qa.expense']].map(([k, lk]) => (
          <button
            key={k}
            type="button"
            onClick={() => setMode(k)}
            className="rounded-full px-3 py-1 transition"
            style={mode === k ? { background: 'var(--sf)', color: 'var(--ink)', boxShadow: '0 1px 5px rgba(0,0,0,.16)' } : { color: 'var(--ink2)' }}
          >
            {t(lk)}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 rounded-full pl-4 pr-1.5" style={{ background: 'var(--sf2)', border: '1px solid var(--line)', height: 52 }}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder={t(mode === 'task' ? 'qa.ph_task' : 'qa.ph_expense')}
          className="min-w-0 flex-1 bg-transparent text-[14px] outline-none"
          style={{ color: 'var(--ink)' }}
        />
        <button
          type="button"
          onClick={send}
          disabled={busy || !text.trim()}
          className="btn !h-9 !w-9 !p-0 disabled:opacity-40"
          aria-label={t('common.add')}
        >
          <Plus size={17} />
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {(mode === 'task' ? ['qa.ex_task1', 'qa.ex_task2'] : ['qa.ex_exp1', 'qa.ex_exp2']).map((k) => (
          <button key={k} type="button" className="chip !mt-0 !py-1 !text-[12px]" onClick={() => setText(t(k))}>{t(k)}</button>
        ))}
      </div>
    </div>
  )
}

/* ---------- «можно потратить сегодня» + ближайший платёж ---------- */
export function SpendTodayWidget({ runway, payments }) {
  const { t } = useI18n()
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
    <div className="flex h-full flex-col">
      <div className="hd">
        <h2>{t('spend.title')}</h2>
        <small>{t('common.today')}</small>
      </div>
      <div className="big">{money(safe)}</div>
      <span className="tag">
        {t(days != null ? 'spend.until_income' : 'spend.by_pace', { count: days })}
      </span>

      <div className="hm">
        <div><small>{t('spend.free')}</small><b>{money(free)}</b></div>
        <div><small>{t('spend.per_day')}</small><b>{money(perDay)}</b></div>
      </div>

      <div className="mt-3 flex items-center gap-2 text-[12.5px]">
        <Timer size={13} className="shrink-0" />
        {next ? (
          <>
            <span className="min-w-0 flex-1 truncate">{t('spend.next', { title: next.title })}</span>
            <b className="shrink-0 whitespace-nowrap">{money(next.amount)}</b>
            <span className="mono shrink-0 opacity-80">{dm(next.date)}</span>
          </>
        ) : (
          <span className="opacity-80">{t('spend.no_payments')}</span>
        )}
      </div>
      {short > 0 && <div className="mt-1 text-[12px] font-semibold">{t('spend.short', { m: money(short) })}</div>}
    </div>
  )
}

/* ---------- «цели»: прогресс + фокус дня ---------- */
export function GoalsWidget({ goals, tasks, onOpen }) {
  const { t } = useI18n()
  const tip = useTip()               // подсказка на полоске прогресса: сколько накоплено и когда ждать
  const list = (goals || []).slice().sort((a, b) => {
    const ax = a.days_left == null ? 9e9 : a.days_left
    const bx = b.days_left == null ? 9e9 : b.days_left
    return ax - bx
  }).slice(0, 3)
  const focus = (tasks || []).filter((t) => !t.done).sort((a, b) => (a.priority || 9) - (b.priority || 9))[0]
  const pctOf = (g) => Math.round((g.pct || 0) * 100)
  const tail = (g) => (g.days_left != null ? (g.days_left < 0 ? t('goals.overdue') : t('goals.in_days', { count: g.days_left })) : (g.per_month ? t('goals.per_month', { m: money(g.per_month) }) : ''))
  const savedLine = (g) => t('tip.saved_of', { m: money(g.saved), target: money(g.target) })
  const cur = tip.active?.i != null ? list[tip.active.i] : null

  return (
    <div className="flex h-full flex-col">
      <div className="hd">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-xl" style={{ background: 'var(--accent-soft)', color: 'var(--acc)' }}>
            <Target size={15} />
          </span>
          <h2>{t('goals.title')}</h2>
        </div>
        <small>{list.length ? t('goals.active_n', { count: list.length }) : t('goals.empty')}</small>
      </div>

      {focus && (
        <div className="mb-3 rounded-2xl p-3" style={{ background: 'var(--sf2)' }}>
          <div className="faint text-[11px] uppercase tracking-wide">{t('focus.title')}</div>
          <div className="mt-1 line-clamp-2 text-[14px] font-medium leading-snug">{focus.title}</div>
          {focus.due && <div className="faint mt-0.5 text-[12px]">{t('goals.by', { time: hhmm(focus.due) })}</div>}
        </div>
      )}

      <div className="relative space-y-3" ref={tip.hostRef}>
        {list.map((g, gi) => {
          const pct = pctOf(g)
          // подсказка и подпись для скринридера — одна и та же строка
          const aria = `${g.title}: ${savedLine(g)}, ${t('tip.pct', { p: pct })}${tail(g) ? `, ${tail(g)}` : ''}`
          return (
            <div key={g.id} className="chart-pt rounded-xl" {...tip.bind(gi, aria, 'group')}>
              <div className="flex items-baseline gap-2 text-[13.5px]">
                <span>{g.icon || '🎯'}</span>
                <span className="min-w-0 flex-1 truncate font-medium">{g.title}</span>
                <span className="mono faint text-[12px]">{pct}%</span>
              </div>
              <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full" style={{ background: 'var(--sf2)' }}>
                <div style={{ width: `${Math.max(2, pct)}%`, height: '100%', borderRadius: 999, background: 'linear-gradient(90deg, var(--acc), #8a5cff)', transition: 'width .8s var(--e)' }} />
              </div>
              <div className="faint mt-1 flex justify-between text-[11.5px]">
                <span>{money(g.saved)} из {money(g.target)}</span>
                <span>{tail(g)}</span>
              </div>
            </div>
          )
        })}
        {!list.length && <div className="muted text-[13px]">{t('goals.none')}</div>}
      </div>

      {/* наведение, тап или стрелки на строке цели — сколько накоплено и когда ждать */}
      {tip.panel({
        title: cur ? `${cur.icon || '🎯'} ${cur.title}` : null,
        rows: cur ? [savedLine(cur), t('tip.pct', { p: pctOf(cur) }), tail(cur)].filter(Boolean) : [],
      })}

      {onOpen && (
        <button type="button" className="chip !mt-3 self-start !py-1.5 !text-[12.5px]" onClick={onOpen}>
          {t('goals.all')} <ArrowUpRight size={13} />
        </button>
      )}
    </div>
  )
}

/* ---------- «привычки»: стрик ведения дня + тепловая карта ---------- */
export function HabitsWidget({ streak }) {
  const { t } = useI18n()
  return (
    <div className="flex h-full flex-col">
      <div className="hd">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-xl" style={{ background: 'var(--warn-soft)', color: 'var(--warn)' }}>
            <Flame size={15} />
          </span>
          <h2>{t('habits.title')}</h2>
        </div>
        <small>{t('habits.sub')}</small>
      </div>

      <Streak streak={streak} />
      {!streak?.current && (
        <div className="muted mt-2 text-[13px]">{t('habits.hint')}</div>
      )}
      {!!(streak?.heatmap || []).length && (
        <div className="mt-auto pt-4">
          <Heatmap heatmap={streak.heatmap} weeks={13} />
        </div>
      )}
    </div>
  )
}

/* ---------- «ближайшее дело»: следующая встреча/задача и свободное окно до неё ---------- */
export function NextUpWidget({ events, tasks, onOpen }) {
  const { t } = useI18n()
  const now = new Date()
  const items = []
  for (const e of events || []) {
    if (e.done || isAllDay(e.start)) continue
    items.push({ key: `e${e.id}`, kind: 'event', title: e.title, at: new Date(e.start) })
  }
  for (const t of tasks || []) {
    if (t.done || !t.due || isAllDay(t.due)) continue
    items.push({ key: `t${t.id}`, kind: 'task', title: t.title, at: new Date(t.due) })
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
    <div className="flex h-full flex-col">
      <div className="hd">
        <h2>{t('nextup.title')}</h2>
        <small>{next ? hhmm(next.at) : t('nextup.day_free')}</small>
      </div>

      {next ? (
        <>
          <div className="mid">{hhmm(next.at)}</div>
          <div className="mt-1 line-clamp-2 text-[15px] font-medium leading-snug">{next.title}</div>
          <div className="mt-3 inline-flex items-center gap-1.5 self-start rounded-full px-3 py-1 text-[12.5px] font-medium"
            style={{ background: 'var(--accent-soft)', color: 'var(--acc)' }}>
            <Timer size={13} /> {t('nextup.free')} {fh ? `${fh} ${t('unit.hour')} ` : ''}{fm} {t('unit.min')}
          </div>
        </>
      ) : (
        <>
          <div className="mid">{t('nextup.free')}</div>
          <div className="muted mt-1 text-[13.5px]">{t('nextup.all_free')}</div>
        </>
      )}

      {upcoming.length > 1 && (
        <div className="mt-auto space-y-1.5 pt-3">
          {upcoming.slice(1, 3).map((x) => (
            <div key={x.key} className="flex items-center gap-2 text-[12.5px]" style={{ color: 'var(--ink2)' }}>
              <span className="mono shrink-0">{hhmm(x.at)}</span>
              <span className="truncate">{x.title}</span>
            </div>
          ))}
        </div>
      )}

      {next && onOpen && (
        <button type="button" className="chip !mt-3 self-start !py-1.5 !text-[12.5px]" onClick={() => onOpen(next.kind)}>
          {t(next.kind === 'event' ? 'nextup.to_cal' : 'nextup.to_tasks')} <ArrowUpRight size={13} />
        </button>
      )}
    </div>
  )
}
