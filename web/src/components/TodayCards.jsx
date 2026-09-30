/* Новые карточки главной («сегодня»): быстрое дело, дневной лимит, цели, привычки,
   ближайшее дело. Каждая — самостоятельный виджет: скрывается, двигается и меняет
   ширину через общий механизм lib/layout, ничего вне главной не меняет.
   Данные — только из тех же ответов API, что уже грузит Today.jsx (dashboard/finance). */
import { useState } from 'react'
import { ArrowUpRight, Flame, Plus, Target, Timer, Zap } from 'lucide-react'
import { api, hhmm, isAllDay, money, plural } from '../lib/api'
import { Streak, Heatmap } from './Widgets'

const dm = (s) => `${s.slice(8, 10)}.${s.slice(5, 7)}`

/* ---------- «быстрое дело»: добавляем задачу или трату одной строкой ---------- */
export function QuickAddWidget({ onDone, onErr }) {
  const [mode, setMode] = useState('task')   // task | expense
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  const send = async () => {
    const t = text.trim()
    if (!t || busy) return
    setBusy(true)
    try {
      // те же шаблоны, что и на странице задач и в чипсах: «задача: …» / «трата: …».
      // Правила ядра понимают их без LLM, поэтому строка уходит мгновенно.
      await api.chat(`${mode === 'task' ? 'задача' : 'трата'}: ${t}`)
      setText('')
      onDone?.(mode === 'task' ? 'Дело добавлено' : 'Трата записана')
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
          <h2>быстрое дело</h2>
        </div>
        <small>не уходя со страницы</small>
      </div>

      {/* переключатель: дело или трата */}
      <div className="mb-2.5 inline-flex self-start rounded-full p-[3px] text-[13px]" style={{ background: 'var(--sf2)', border: '1px solid var(--line)' }}>
        {[['task', 'дело'], ['expense', 'трата']].map(([k, label]) => (
          <button
            key={k}
            type="button"
            onClick={() => setMode(k)}
            className="rounded-full px-3 py-1 transition"
            style={mode === k ? { background: 'var(--sf)', color: 'var(--ink)', boxShadow: '0 1px 5px rgba(0,0,0,.16)' } : { color: 'var(--ink2)' }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-2 rounded-full pl-4 pr-1.5" style={{ background: 'var(--sf2)', border: '1px solid var(--line)', height: 52 }}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder={mode === 'task' ? 'позвонить маме завтра в 18' : '450 такси'}
          className="min-w-0 flex-1 bg-transparent text-[14px] outline-none"
          style={{ color: 'var(--ink)' }}
        />
        <button
          type="button"
          onClick={send}
          disabled={busy || !text.trim()}
          className="btn !h-9 !w-9 !p-0 disabled:opacity-40"
          aria-label="добавить"
        >
          <Plus size={17} />
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {(mode === 'task' ? ['позвонить маме', 'оплатить коммуналку'] : ['700 такси', 'кофе 250']).map((s) => (
          <button key={s} type="button" className="chip !mt-0 !py-1 !text-[12px]" onClick={() => setText(s)}>{s}</button>
        ))}
      </div>
    </div>
  )
}

/* ---------- «можно потратить сегодня» + ближайший платёж ---------- */
export function SpendTodayWidget({ runway, payments }) {
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
        <h2>можно потратить</h2>
        <small>сегодня</small>
      </div>
      <div className="big">{money(safe)}</div>
      <span className="tag">
        {days != null ? `до дохода ${days} ${plural(days, 'день', 'дня', 'дней')}` : 'по текущему темпу'}
      </span>

      <div className="hm">
        <div><small>свободно</small><b>{money(free)}</b></div>
        <div><small>трачу в день</small><b>{money(perDay)}</b></div>
      </div>

      <div className="mt-3 flex items-center gap-2 text-[12.5px]">
        <Timer size={13} className="shrink-0" />
        {next ? (
          <>
            <span className="min-w-0 flex-1 truncate">ближайший: {next.title}</span>
            <b className="shrink-0 whitespace-nowrap">{money(next.amount)}</b>
            <span className="mono shrink-0 opacity-80">{dm(next.date)}</span>
          </>
        ) : (
          <span className="opacity-80">ближайших платежей нет</span>
        )}
      </div>
      {short > 0 && <div className="mt-1 text-[12px] font-semibold">не хватает {money(short)}</div>}
    </div>
  )
}

/* ---------- «цели»: прогресс + фокус дня ---------- */
export function GoalsWidget({ goals, tasks, onOpen }) {
  const list = (goals || []).slice().sort((a, b) => {
    const ax = a.days_left == null ? 9e9 : a.days_left
    const bx = b.days_left == null ? 9e9 : b.days_left
    return ax - bx
  }).slice(0, 3)
  const focus = (tasks || []).filter((t) => !t.done).sort((a, b) => (a.priority || 9) - (b.priority || 9))[0]

  return (
    <div className="flex h-full flex-col">
      <div className="hd">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-xl" style={{ background: 'var(--accent-soft)', color: 'var(--acc)' }}>
            <Target size={15} />
          </span>
          <h2>цели</h2>
        </div>
        <small>{list.length ? `${list.length} в работе` : 'пока пусто'}</small>
      </div>

      {focus && (
        <div className="mb-3 rounded-2xl p-3" style={{ background: 'var(--sf2)' }}>
          <div className="faint text-[11px] uppercase tracking-wide">фокус дня</div>
          <div className="mt-1 line-clamp-2 text-[14px] font-medium leading-snug">{focus.title}</div>
          {focus.due && <div className="faint mt-0.5 text-[12px]">до {hhmm(focus.due)}</div>}
        </div>
      )}

      <div className="space-y-3">
        {list.map((g) => {
          const pct = Math.round((g.pct || 0) * 100)
          return (
            <div key={g.id}>
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
                <span>{g.days_left != null ? (g.days_left < 0 ? 'просрочена' : `${g.days_left} дн`) : (g.per_month ? `${money(g.per_month)}/мес` : '')}</span>
              </div>
            </div>
          )
        })}
        {!list.length && <div className="muted text-[13px]">Целей пока нет — скажите в чате «цель: …»</div>}
      </div>

      {onOpen && (
        <button type="button" className="chip !mt-3 self-start !py-1.5 !text-[12.5px]" onClick={onOpen}>
          все цели <ArrowUpRight size={13} />
        </button>
      )}
    </div>
  )
}

/* ---------- «привычки»: стрик ведения дня + тепловая карта ---------- */
export function HabitsWidget({ streak }) {
  return (
    <div className="flex h-full flex-col">
      <div className="hd">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-xl" style={{ background: 'var(--warn-soft)', color: 'var(--warn)' }}>
            <Flame size={15} />
          </span>
          <h2>привычки</h2>
        </div>
        <small>ведение дня</small>
      </div>

      <Streak streak={streak} />
      {!streak?.current && (
        <div className="muted mt-2 text-[13px]">Начните вести день — запишите трату, дело или мысль.</div>
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
        <h2>ближайшее</h2>
        <small>{next ? hhmm(next.at) : 'день свободен'}</small>
      </div>

      {next ? (
        <>
          <div className="mid">{hhmm(next.at)}</div>
          <div className="mt-1 line-clamp-2 text-[15px] font-medium leading-snug">{next.title}</div>
          <div className="mt-3 inline-flex items-center gap-1.5 self-start rounded-full px-3 py-1 text-[12.5px] font-medium"
            style={{ background: 'var(--accent-soft)', color: 'var(--acc)' }}>
            <Timer size={13} /> свободно {fh ? `${fh} ч ` : ''}{fm} мин
          </div>
        </>
      ) : (
        <>
          <div className="mid">свободно</div>
          <div className="muted mt-1 text-[13.5px]">дел с конкретным временем больше нет — день ваш.</div>
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
          {next.kind === 'event' ? 'в календарь' : 'к задачам'} <ArrowUpRight size={13} />
        </button>
      )}
    </div>
  )
}
