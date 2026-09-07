import { useEffect, useState } from 'react'
import { dat } from '../lib/name'
import { Link } from 'react-router-dom'
import { ChevronRight, Check, MessageCircle } from 'lucide-react'
import { api, money, hhmm, dayLabel, MONTHS, isSameDay, relTime, plural, catIcon } from '../lib/api'
import { Card, Section, Empty, Skeleton, PRIORITY, PageHead, Num, useLeave, Swipe } from '../components/ui'
import { useRefresh } from '../App'
import { Heatmap, Streak, Forecast, Birthdays, useOrder, Draggable } from '../components/Widgets'
import { GripVertical } from 'lucide-react'

const GREETS = { morning: 'Доброе утро', day: 'Добрый день', evening: 'Добрый вечер', night: 'Доброй ночи' }
const part = (h) => (h < 5 ? 'night' : h < 12 ? 'morning' : h < 18 ? 'day' : 'evening')
const KIND_ICON = { event: '📅', task: '✅', finance: '💸', note: '📝', link: '🔗', chat: '💬', system: '⚙️' }

export default function Today({ openChat }) {
  const [d, setD] = useState(null)
  const { tick } = useRefresh()
  const load = () => api.dashboard().then(setD).catch(() => {})
  useEffect(() => { load() }, [tick])

  const now = new Date()
  const [leaveCls, leave] = useLeave()
  const done = (id) => leave(id, 'done', async () => { await api.doneTask(id); await load() })
  const delTask = (id) => leave(id, 'leaving', async () => { await api.delTask(id); await load() })
  const [order, move, resetOrder] = useOrder('today.order', ['events', 'tasks', 'payments', 'memory', 'forecast', 'streak'])

  if (!d) return <div className="space-y-4"><Skeleton h={90} /><Skeleton h={160} /><Skeleton h={160} /></div>

  const f = d.finance, cf = f.cashflow
  const upcomingWeek = d.week.filter((e) => !isSameDay(e.start, now))
  const debtsOpen = d.debts.filter((x) => !x.closed)

  return (
    <div className="space-y-14 sm:space-y-20">
      <PageHead kicker={`${['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'][now.getDay()]} · ${now.getDate()} ${MONTHS[now.getMonth()]}`}
        title={<>{GREETS[part(now.getHours())].toLowerCase()},<br />сэр</>}
        right={<button onClick={openChat} className="btn-ghost">сказать {dat()} <span className="font-normal">↗</span></button>} />

      {/* Верхний ряд — деньги */}
      <div className="rule grid grid-cols-2 gap-y-8 pt-6 md:grid-cols-4">
        <Tile label="баланс" value={<Num value={f.total_balance} fmt={money} />} to="/finance" />
        <Tile label="свободно в месяц" value={<Num value={cf.free} fmt={money} />} tone={cf.free < 0 ? 'neg' : 'accent'} sub="после обязательств" to="/finance" />
        <Tile label={`траты · ${f.days} дн`} value={<Num value={f.spent} fmt={money} />} to="/finance" />
        <Tile label="долги" value={debtsOpen.length ? <Num value={f.debts_total} fmt={money} /> : '—'} sub={debtsOpen.length ? `${money(f.monthly_debt_payments)} в месяц` : 'нет'} to="/finance" />
      </div>

      {d.birthdays?.length > 0 && <Birthdays list={d.birthdays} />}

      {/* Секции можно перетаскивать за ручку — порядок запоминается в браузере */}
      <div className="grid grid-cols-1 gap-14 lg:grid-cols-2 lg:gap-12">
        {order.map((id, i) => (
          <Draggable key={id} id={id} onMove={move}>
            {WIDGETS[id]({ d, now, done, leaveCls, upcomingWeek, idx: i + 1 })}
          </Draggable>
        ))}
      </div>
      <div className="faint -mt-8 flex items-center gap-2 text-[11px]"><GripVertical size={12} /> блоки можно перетаскивать · <button className="hover:text-accent" onClick={resetOrder}>сбросить порядок</button></div>
    </div>
  )
}

const WIDGETS = {
  events: ({ d, now, upcomingWeek, idx }) => (
    <Section title="сегодня" idx={idx} action={<Link to="/calendar" className="btn-ghost !py-1.5 !text-[13px]">календарь ↗</Link>}>
      <div className="rule">
        {d.today.length === 0 ? (
          <Empty glyph="calendar" text="Встреч нет" sub="Подозрительно спокойно, сэр" hint="созвон завтра в 15" />
        ) : (
          <div className="stagger">{d.today.map((e) => <EventRow key={e.id} e={e} now={now} />)}</div>
        )}
      </div>
      {upcomingWeek.length > 0 && (
        <div className="mt-3 px-1">
          <div className="label mb-1.5">Ближайшие</div>
          <div className="space-y-1.5">
            {upcomingWeek.slice(0, 4).map((e) => (
              <div key={e.id} className="flex items-baseline gap-3 text-[14px]">
                <span className="muted w-32 shrink-0 truncate tabular-nums">{dayLabel(e.start)}, {hhmm(e.start)}</span>
                <span className="truncate font-medium">{e.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Section>
  ),
  tasks: ({ d, now, done, leaveCls, idx }) => (
    <Section title="задачи" idx={idx} action={<Link to="/tasks" className="btn-ghost !py-1.5 !text-[13px]">все ↗</Link>}>
      <div className="rule">
        {d.tasks.length === 0 ? (
          <Empty glyph="tasks" text="Всё сделано" sub="Или вы мне ничего не сказали" hint="задача: позвонить маме" />
        ) : (
          <div className="stagger">
            {d.tasks.slice(0, 6).map((t) => (
              <Swipe key={t.id} onRight={() => done(t.id)} onLeft={() => delTask(t.id)}>
              <div className={`row row-slide group ${leaveCls(t.id)}`}>
                <button onClick={() => done(t.id)} className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border transition-all duration-300 hover:scale-110 active:scale-90 ${leaveCls(t.id) ? 'border-accent bg-accent text-white' : 'hover:border-accent'}`} style={leaveCls(t.id) ? {} : { borderColor: 'var(--line-2)' }}>{leaveCls(t.id) ? <Check size={13} strokeWidth={3} className="check-pop" /> : <Check size={13} className="opacity-0 transition group-hover:opacity-40" />}</button>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[15px] font-medium">{t.title}</div>
                  {t.due && <div className={`text-[12px] ${new Date(t.due) < now ? 'text-red' : 'muted'}`}>до {dayLabel(t.due)}, {hhmm(t.due)}</div>}
                </div>
                <span className={`h-2 w-2 shrink-0 rounded-full ${PRIORITY[t.priority]?.dot}`} />
              </div>
              </Swipe>
            ))}
          </div>
        )}
      </div>
    </Section>
  ),
  payments: ({ d, idx }) => (
    <Section title="платежи на неделе" idx={idx}>
      <div className="rule">
        {d.upcoming.length === 0 ? <Empty glyph="sleep" text="Ничего не списывается" sub="Ближайшую неделю платежей нет" /> : (
          <div>
            {d.upcoming.map((r) => (
              <div key={r.id} className="row">
                <span className="mono grid h-9 w-9 shrink-0 place-items-center rounded-full border hair text-[12px] uppercase">{(r.category || '•')[0]}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[15px] font-medium">{r.title}</div>
                  <div className="muted text-[12px]">{dayLabel(r.next_date)}</div>
                </div>
                <div className="num font-medium">{money(r.amount)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Section>
  ),
  memory: ({ d, idx }) => (
    <Section title="недавно" idx={idx} action={<Link to="/memory" className="btn-ghost !py-1.5 !text-[13px]">память ↗</Link>}>
      <div className="rule">
        {d.memory.length === 0 ? <Empty glyph="memory" text="Память пуста" sub="Всё, что вы говорите мне, оседает здесь" hint="мысль: идея для проекта" /> : (
          <div>
            {d.memory.slice(0, 6).map((m) => (
              <div key={m.id} className="row !py-2.5">
                <span className="text-base">{KIND_ICON[m.kind] || '•'}</span>
                <div className="min-w-0 flex-1 truncate text-[14px]">{m.text}</div>
                <div className="faint shrink-0 text-[12px]">{relTime(m.created_at)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Section>
  ),
  forecast: ({ d, idx }) => (
    <Section title="касса на 30 дней" idx={idx} hint={d.forecast?.ok ? 'При текущем темпе в минус не уходите.' : 'При текущем темпе уйдёте в минус — стоит притормозить.'} action={<Link to="/finance" className="btn-ghost !py-1.5 !text-[13px]">финансы ↗</Link>}>
      <div className="rule pt-4"><Forecast f={d.forecast} /></div>
    </Section>
  ),
  streak: ({ d, idx }) => (
    <Section title="дисциплина" idx={idx} hint="Дни, когда вы что-то записали. Чем темнее — тем больше.">
      <div className="rule space-y-5 pt-4">
        <Streak streak={d.streak} />
        <div className="overflow-x-auto pb-1"><Heatmap heatmap={d.streak?.heatmap || d.heatmap} /></div>
      </div>
    </Section>
  ),
}

function Tile({ label, value, sub, tone, to }) {
  const color = tone === 'accent' ? 'accent' : tone === 'neg' ? 'neg' : ''
  const inner = (
    <div className="group">
      <div className="label">{label}</div>
      <div className={`num mt-2 text-[26px] font-medium leading-none tracking-[-0.04em] transition-all duration-300 group-hover:translate-x-1 group-hover:text-accent sm:text-[34px] ${color}`}>{value}</div>
      {sub && <div className="muted mt-1.5 text-[12px]">{sub}</div>}
    </div>
  )
  return to ? <Link to={to} className="animate-rise block">{inner}</Link> : inner
}

function EventRow({ e, now }) {
  const start = new Date(e.start), end = e.end ? new Date(e.end) : null
  const live = start <= now && end && end >= now
  const past = end && end < now
  return (
    <div className={`row ${past ? 'opacity-50' : ''}`}>
      <div className="w-14 shrink-0">
        <div className="num text-[15px] font-semibold">{hhmm(e.start)}</div>
        {end && <div className="faint num text-[11px]">{hhmm(end)}</div>}
      </div>
      <div className={`h-9 w-[3px] shrink-0 rounded-full ${live ? 'bg-green' : 'bg-accent'}`} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[15px] font-medium">{e.title}</div>
        {e.location && <div className="muted truncate text-[12px]">{e.location}</div>}
      </div>
      {live ? <span className="chip on">сейчас</span> : (!past && start - now < 3 * 3600e3 && start > now) ? <span className="chip">{untilText(start, now)}</span> : null}
    </div>
  )
}


function untilText(start, now) {
  const m = Math.round((start - now) / 60000)
  if (m < 1) return 'вот-вот'
  if (m < 60) return `через ${m} мин`
  const h = Math.floor(m / 60), r = m % 60
  return `через ${h} ч${r ? ` ${r} мин` : ''}`
}
