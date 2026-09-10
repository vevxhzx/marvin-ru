import { useEffect, useRef, useState } from 'react'
import { dat } from '../lib/name'
import { Link } from 'react-router-dom'
import { Check, ArrowUp, ArrowUpRight, ChevronDown, ChevronUp, SlidersHorizontal, GripVertical, RotateCcw, X, Eye, EyeOff } from 'lucide-react'
import { api, money, hhmm, dayLabel, MONTHS, isSameDay, relTime, plural, chatStream, kb } from '../lib/api'
import { Section, Empty, Num, useLeave, Swipe, ListSkeleton, Sheet, Switch } from '../components/ui'
import { renderMd, ACT } from '../components/Chat'
import { useRefresh } from '../App'
import { Forecast, Birthdays, useOrder, Draggable } from '../components/Widgets'
import { usePrefs, prefs as PREFS, DEFAULTS } from '../lib/prefs'

const GREETS = { morning: 'доброе утро', day: 'добрый день', evening: 'добрый вечер', night: 'доброй ночи' }
const part = (h) => (h < 5 ? 'night' : h < 12 ? 'morning' : h < 18 ? 'day' : 'evening')
const WD = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']

/* Блоки главной: порядок и видимость настраивает пользователь (localStorage), перетаскивание мышью. */
const BLOCKS = [
  { id: 'tasks', label: 'задачи' },
  { id: 'events', label: 'сегодня в календаре' },
  { id: 'upcoming', label: 'платежи на неделе' },
  { id: 'recent', label: 'недавно в памяти' },
  { id: 'money', label: 'деньги' },
]
const BLOCK_IDS = BLOCKS.map((b) => b.id)

/* Одна короткая фраза контекста — только самое важное, не перечисление всего. */
function contextLine(d, now) {
  const live = d.today.find((e) => new Date(e.start) <= now && e.end && new Date(e.end) >= now)
  if (live) return `сейчас — «${live.title}»`
  const next = d.today.find((e) => new Date(e.start) > now)
  if (next) { const m = Math.round((new Date(next.start) - now) / 60000); return m < 60 ? `через ${m} мин — «${next.title}»` : `ближайшее в ${hhmm(next.start)} — «${next.title}»` }
  const overdue = d.tasks.filter((t) => t.due && new Date(t.due) < now).length
  if (overdue) return `${overdue} ${plural(overdue, 'задача просрочена', 'задачи просрочены', 'задач просрочено')}`
  const todayT = d.tasks.filter((t) => t.due && isSameDay(t.due, now)).length
  if (todayT) return `${todayT} ${plural(todayT, 'задача', 'задачи', 'задач')} на сегодня, встреч нет`
  return d.tasks.length ? 'встреч нет — можно заняться задачами' : 'день свободен'
}

export default function Today({ openChat, address = 'сэр' }) {
  const [d, setD] = useState(null)
  const { tick, bump } = useRefresh()
  const load = () => api.dashboard().then(setD).catch(() => {})
  useEffect(() => { load() }, [tick])

  const [prefs, setPrefs] = usePrefs()
  const [order, move, resetOrder] = useOrder('today.order.v2', BLOCK_IDS)
  const [custom, setCustom] = useState(false)
  const [editing, setEditing] = useState(false)   // режим перетаскивания
  const visible = order.filter((id) => !prefs.hiddenBlocks.includes(id))

  const now = new Date()
  const [leaveCls, leave] = useLeave()
  const done = (id) => leave(id, 'done', async () => { await api.doneTask(id); await load(); bump() })
  const delTask = (id) => leave(id, 'leaving', async () => { await api.delTask(id); await load(); bump() })

  const blocks = {
    tasks: <TasksBlock d={d} now={now} done={done} delTask={delTask} leaveCls={leaveCls} calm={prefs.density === 'calm'} />,
    events: <EventsBlock d={d} now={now} calm={prefs.density === 'calm'} />,
    upcoming: <UpcomingBlock d={d} />,
    recent: <RecentBlock d={d} />,
    money: <MoneyBlock d={d} />,
  }
  const wide = (id) => id === 'money'

  return (
    <div className="space-y-12 sm:space-y-14">
      <header className="animate-rise">
        <div className="label mb-2">{WD[now.getDay()]} · {now.getDate()} {MONTHS[now.getMonth()]}</div>
        {prefs.showGreeting && <h1 className="h1">{GREETS[part(now.getHours())]}, {prefs.address || address}</h1>}
        {prefs.showContext && <div className={`muted text-[15px] ${prefs.showGreeting ? 'mt-2' : ''}`}>{d ? contextLine(d, now) : <span className="fill animate-pulseSoft inline-block h-4 w-48 rounded-md align-middle" />}</div>}
        <Composer onOpenChat={openChat} quick={prefs.showQuick} />
      </header>
      {d && !editing && (
        <div className="-mt-6 flex justify-end sm:-mt-8">
          <button className="faint flex items-center gap-1.5 text-[12px] hover:text-accent" onClick={() => setCustom(true)}><SlidersHorizontal size={12} /> настроить главную</button>
        </div>
      )}

      {!d ? (
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-2"><ListSkeleton n={3} /><ListSkeleton n={3} /></div>
      ) : (
        <>
          {d.birthdays?.length > 0 && <Birthdays list={d.birthdays} />}
          <div className={`grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-x-14 ${editing ? 'select-none' : ''}`}>
            {visible.map((id) => (
              <Draggable key={id} id={id} onMove={move} className={`${wide(id) ? 'lg:col-span-2' : ''} ${editing ? 'cursor-grab rounded-2xl outline-dashed outline-1 outline-[var(--line-2)] p-3 -m-3 active:cursor-grabbing' : ''}`} disabled={!editing}>
                {editing && <div className="faint mb-2 flex items-center gap-1 text-[11px]"><GripVertical size={12} /> {BLOCKS.find((b) => b.id === id)?.label} — тяните</div>}
                {blocks[id]}
              </Draggable>
            ))}
          </div>
          {visible.length === 0 && <div className="rule"><Empty glyph="sleep" text="Все блоки скрыты" sub="Тихо и спокойно. Вернуть можно в настройке главной." /></div>}


          {editing && <div className="toast-in fixed inset-x-0 z-[70] flex justify-center md:bottom-8" style={{ bottom: 'calc(5.5rem + env(safe-area-inset-bottom, 0px))' }}><button className="btn-dark shadow-lg" onClick={() => setEditing(false)}><Check size={14} /> готово, порядок сохранён</button></div>}
        </>
      )}

      <Customize open={custom} onClose={() => setCustom(false)} prefs={prefs} setPrefs={setPrefs} order={order} move={move} address={address}
        onReset={() => { resetOrder(); setPrefs({ hiddenBlocks: DEFAULTS.hiddenBlocks, showGreeting: true, showContext: true, showQuick: true, density: 'calm' }) }} onDrag={() => { setCustom(false); setEditing(true) }} />
    </div>
  )
}

/* Настройка главной: какие блоки показывать, порядок, плотность, что в шапке */
function Customize({ open, onClose, prefs, setPrefs, order, move, onReset, onDrag, address }) {
  const toggle = (id) => setPrefs({ hidden: prefs.hiddenBlocks.includes(id) ? prefs.hiddenBlocks.filter((x) => x !== id) : [...prefs.hiddenBlocks, id] })
  const up = (id) => { const i = order.indexOf(id); if (i > 0) move(id, order[i - 1]) }
  const down = (id) => { const i = order.indexOf(id); if (i < order.length - 1) move(order[i + 1], id) }
  return (
    <Sheet open={open} onClose={onClose} title="главная" sub="Что показывать и в каком порядке. Всё хранится в этом браузере.">
      <div className="space-y-6">
        <div>
          <div className="label mb-2">блоки</div>
          <div className="rule">
            {order.map((id) => {
              const b = BLOCKS.find((x) => x.id === id); const on = !prefs.hiddenBlocks.includes(id)
              return (
                <div key={id} className={`row !py-2.5 ${on ? '' : 'opacity-50'}`}>
                  <button className="btn-icon !h-7 !w-7" onClick={() => toggle(id)} aria-label={on ? 'Скрыть' : 'Показать'}>{on ? <Eye size={14} /> : <EyeOff size={14} />}</button>
                  <span className="flex-1 text-[14px]">{b.label}</span>
                  <button className="btn-icon !h-7 !w-7" onClick={() => up(id)} aria-label="Выше"><ChevronUp size={14} /></button>
                  <button className="btn-icon !h-7 !w-7" onClick={() => down(id)} aria-label="Ниже"><ChevronDown size={14} /></button>
                </div>
              )
            })}
          </div>
          <button className="btn-ghost btn-sm mt-3" onClick={onDrag}><GripVertical size={13} /> перетащить мышью</button>
        </div>
        <div>
          <div className="label mb-2">шапка</div>
          <div className="rule">
            <div className="row !py-2.5"><span className="flex-1 text-[14px]">приветствие</span><Switch on={prefs.showGreeting} onChange={(v) => setPrefs({ showGreeting: v })} /></div>
            <div className="row !py-2.5"><span className="flex-1 text-[14px]">строка контекста</span><Switch on={prefs.showContext} onChange={(v) => setPrefs({ showContext: v })} /></div>
            <div className="row !py-2.5"><span className="flex-1 text-[14px]">быстрые слова под полем</span><Switch on={prefs.showQuick} onChange={(v) => setPrefs({ showQuick: v })} /></div>
            <div className="row !py-2.5"><span className="flex-1 text-[14px]">как обращаться</span><input className="input !h-9 !w-36 !rounded-xl !text-[13px]" placeholder={address} value={prefs.address} onChange={(e) => setPrefs({ address: e.target.value })} /></div>
          </div>
        </div>
        <div>
          <div className="label mb-2">плотность</div>
          <div className="seg">
            {[['calm', 'спокойно'], ['full', 'подробно']].map(([v, l]) => <button type="button" key={v} className={prefs.density === v ? 'on' : ''} onClick={() => setPrefs({ density: v })}>{l}</button>)}
          </div>
          <div className="faint mt-1.5 text-[12px]">«спокойно» — до 3 строк в блоке и без второстепенных подписей.</div>
        </div>
        <button className="btn-ghost btn-sm" onClick={onReset}><RotateCcw size={13} /> как было</button>
      </div>
    </Sheet>
  )
}

/* Композер: фраза → ответ здесь же. Кнопки-подсказки — по желанию. */
function Composer({ onOpenChat, quick }) {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [reply, setReply] = useState(null)
  const inp = useRef(null)
  const { bump } = useRefresh()
  const send = async (text) => {
    text = (text ?? q).trim(); if (!text || busy) return
    setQ(''); setBusy(true); setReply({ text: '', streaming: true })
    window.dispatchEvent(new CustomEvent('assistant:busy', { detail: true }))
    try {
      const r = await chatStream(text, (piece) => setReply((x) => ({ ...(x || {}), text: (x?.text || '') + piece, streaming: true })))
      setReply({ text: r.text, actions: r.actions, via: r.via })
      if (r.actions?.length) bump()
    } catch (e) {
      setReply({ text: e?.status === 401 ? e.message : 'Ядро не ответило. Проверьте, что start.bat запущен, и повторите.', via: 'none' })
    } finally { setBusy(false); window.dispatchEvent(new CustomEvent('assistant:busy', { detail: false })) }
  }
  const acts = [...new Set((reply?.actions || []).filter((a) => ACT[a]))]
  const clarify = reply?.actions?.includes('clarify')
  const QUICK = [['задача', 'задача: '], ['трата', 'потратил '], ['встреча', 'встреча '], ['мысль', 'мысль: ']]
  return (
    <div className="mt-7 max-w-[680px]">
      <form onSubmit={(e) => { e.preventDefault(); send() }} className="composer flex items-center gap-2 py-2 pl-4 pr-2">
        <textarea ref={inp} rows={1} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
          placeholder={`сказать ${dat()}…`} className="py-1.5" />
        <button type="submit" disabled={!q.trim() || busy} className="btn-primary grid !h-9 !w-9 shrink-0 !rounded-full !p-0" aria-label="Отправить"><ArrowUp size={16} strokeWidth={2.4} /></button>
      </form>
      <div className="mt-2.5 flex items-center gap-3 px-2">
        {quick && QUICK.map(([l, t]) => <button key={l} className="muted text-[12.5px] hover:text-accent" onClick={() => { setQ(t); inp.current?.focus() }}>{l}</button>)}
        <button className="faint ml-auto text-[12px] hover:text-accent" onClick={onOpenChat}>вся переписка <span className="kbd ml-1">{kb('J')}</span></button>
      </div>
      {reply && (
        <div className="animate-rise mt-4 flex items-start gap-3 px-1">
          <span className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${reply.streaming ? 'dot-live' : ''}`} style={{ background: reply.via === 'none' ? 'var(--neg)' : 'var(--accent)', color: 'var(--accent)' }} />
          <div className="min-w-0 flex-1">
            <div className={`md whitespace-pre-wrap text-[14.5px] leading-relaxed ${reply.streaming ? 'cursor' : ''} ${reply.via === 'none' ? 'neg' : ''}`}>
              {reply.text ? renderMd(reply.text.replace(/\s*(⚡|🧠|☁️)\s*$/u, '')) : <span className="thinking inline-flex items-center gap-1 text-accent"><span /><span /><span /></span>}
            </div>
            {(acts.length > 0 || clarify) && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {acts.map((a) => { const [label, I] = ACT[a]; return <span key={a} className="act-card !py-1.5 bubble-in"><span className="act-ic !h-5 !w-5"><Check size={11} strokeWidth={3} /></span><span className="font-medium">{label}</span><I size={13} className="faint" /></span> })}
                {clarify && ['да', 'нет', 'календарь', 'задача'].map((w) => <button key={w} className="chip !py-1 hover:text-accent" onClick={() => send(w)}>{w}</button>)}
              </div>
            )}
          </div>
          <button className="btn-icon !h-7 !w-7 shrink-0" onClick={() => setReply(null)} aria-label="Скрыть"><X size={13} /></button>
        </div>
      )}
    </div>
  )
}

function TasksBlock({ d, now, done, delTask, leaveCls, calm }) {
  const list = [...d.tasks].sort((a, b) => (a.due ? new Date(a.due) : 9e15) - (b.due ? new Date(b.due) : 9e15) || a.priority - b.priority)
  const overdue = list.filter((t) => t.due && new Date(t.due) < now).length
  const shown = list.slice(0, calm ? 3 : 6)
  return (
    <Section title="задачи" idx={list.length} action={<Link to="/tasks" className="btn-ghost btn-sm">все <ArrowUpRight size={13} /></Link>}>
      <div className="rule">
        {list.length === 0 ? <Empty glyph="tasks" text="Всё сделано" hint="задача: позвонить маме" compact /> : (
          <div className="stagger">
            {shown.map((t) => {
              const od = t.due && new Date(t.due) < now
              return (
                <Swipe key={t.id} onRight={() => done(t.id)} onLeft={() => delTask(t.id)}>
                  <div className={`row row-slide group ${leaveCls(t.id)}`}>
                    <button onClick={() => done(t.id)} aria-label="Выполнено" className={`grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full border transition-all duration-300 hover:scale-110 active:scale-90 ${leaveCls(t.id) ? 'border-accent bg-accent text-white' : 'hover:border-accent'}`} style={leaveCls(t.id) ? {} : { borderColor: t.priority === 1 ? 'var(--neg)' : 'var(--line-2)' }}>
                      {leaveCls(t.id) ? <Check size={12} strokeWidth={3} className="check-pop" /> : <Check size={12} className="opacity-0 transition group-hover:opacity-40" />}
                    </button>
                    <div className="min-w-0 flex-1 truncate text-[14.5px] font-medium">{t.title}</div>
                    {t.due && <span className={`shrink-0 text-[12px] ${od ? 'neg' : 'faint'}`}>{od ? 'просрочено' : isSameDay(t.due, now) ? hhmm(t.due) : dayLabel(t.due).toLowerCase()}</span>}
                  </div>
                </Swipe>
              )
            })}
          </div>
        )}
      </div>
      {list.length > shown.length && <Link to="/tasks" className="faint mt-2 inline-block text-[12px] hover:text-accent">ещё {list.length - shown.length}{overdue ? ` · просрочено ${overdue}` : ''}</Link>}
    </Section>
  )
}

function EventsBlock({ d, now, calm }) {
  const upcomingWeek = d.week.filter((e) => !isSameDay(e.start, now)).slice(0, calm ? 2 : 4)
  return (
    <Section title="сегодня" idx={d.today.length} action={<Link to="/calendar" className="btn-ghost btn-sm">календарь <ArrowUpRight size={13} /></Link>}>
      <div className="rule">
        {d.today.length === 0 ? <Empty glyph="calendar" text="Встреч нет" hint="созвон завтра в 15" compact /> : <div className="stagger">{d.today.slice(0, calm ? 4 : 8).map((e) => <EventRow key={e.id + e.start} e={e} now={now} />)}</div>}
      </div>
      {upcomingWeek.length > 0 && (
        <div className="mt-4 border-t border-dashed border-[var(--line)] pt-3">
          <div className="label mb-2 !text-[10px] !text-[var(--ink-2)]">дальше на неделе</div>
          <div className="space-y-1">
            {upcomingWeek.map((e) => (
              <div key={e.id + e.start} className="flex items-baseline gap-3 text-[13px]">
                <span className="num w-[120px] shrink-0 truncate"><span className="font-medium">{dayLabel(e.start).toLowerCase()}</span><span className="faint">, {hhmm(e.start)}</span></span>
                <span className="muted truncate">{e.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Section>
  )
}

function UpcomingBlock({ d }) {
  return (
    <Section title="платежи на неделе" idx={d.upcoming.length} action={<Link to="/finance" className="btn-ghost btn-sm">финансы <ArrowUpRight size={13} /></Link>}>
      <div className="rule">
        {d.upcoming.length === 0 ? <Empty glyph="sleep" text="Ничего не списывается" compact /> : d.upcoming.slice(0, 5).map((r) => (
          <div key={r.id} className="row !py-2.5">
            <div className="min-w-0 flex-1 truncate text-[14.5px] font-medium">{r.title}</div>
            <div className="faint text-[12px]">{dayLabel(r.next_date).toLowerCase()}</div>
            <div className="num w-[88px] text-right text-[14.5px] font-medium">{money(r.amount)}</div>
          </div>
        ))}
      </div>
    </Section>
  )
}

function RecentBlock({ d }) {
  return (
    <Section title="недавно" action={<Link to="/memory" className="btn-ghost btn-sm">память <ArrowUpRight size={13} /></Link>}>
      <div className="rule">
        {d.memory.length === 0 ? <Empty glyph="memory" text="Пока пусто" hint="мысль: идея для проекта" compact /> : d.memory.slice(0, 4).map((m) => (
          <div key={m.id} className="row !py-2.5">
            <KindDot kind={m.kind} />
            <div className="min-w-0 flex-1 truncate text-[14px]">{m.text.replace(/^(Мысль|Задача|Запланировано|Трата|Регулярный платёж):\s*/i, '')}</div>
            <div className="faint shrink-0 text-[11.5px]">{relTime(m.created_at)}</div>
          </div>
        ))}
      </div>
    </Section>
  )
}

function MoneyBlock({ d }) {
  const [more, setMore] = useState(() => localStorage.getItem('today.fin') === 'on')
  const toggle = () => setMore((v) => { localStorage.setItem('today.fin', v ? 'off' : 'on'); return !v })
  const f = d.finance, cf = f.cashflow
  return (
    <section className="animate-rise">
      <button className="flex w-full items-center justify-between gap-3 text-left" onClick={toggle}>
        <div className="flex items-baseline gap-3"><h2 className="h2">деньги</h2><span className="muted num text-[13px]">{money(f.total_balance)}</span>{cf.free < 0 && <span className="badge neg">минус в месяце</span>}</div>
        <span className="btn-icon !h-8 !w-8">{more ? <ChevronUp size={15} /> : <ChevronDown size={15} />}</span>
      </button>
      {more && (
        <div className="animate-rise mt-4 grid grid-cols-1 gap-8 lg:grid-cols-[1fr_1.2fr]">
          <div className="grid grid-cols-2 gap-x-6 gap-y-6">
            <Tile label="баланс" value={<Num value={f.total_balance} fmt={money} />} />
            <Tile label="свободно в месяц" value={<Num value={cf.free} fmt={money} />} tone={cf.free < 0 ? 'neg' : 'accent'} />
            <Tile label={`траты · ${f.days} дн`} value={<Num value={f.spent} fmt={money} />} />
            <Tile label="долги" value={d.debts.filter((x) => !x.closed).length ? <Num value={f.debts_total} fmt={money} /> : '—'} />
          </div>
          <div>
            <div className="mb-2 flex items-baseline justify-between"><div className="label">касса на 30 дней</div><span className={`text-[12px] ${d.forecast?.ok ? 'muted' : 'neg'}`}>{d.forecast?.ok ? 'в минус не уходите' : 'при текущем темпе уйдёте в минус'}</span></div>
            <Forecast f={d.forecast} />
          </div>
        </div>
      )}
    </section>
  )
}

function Tile({ label, value, tone }) {
  return (
    <Link to="/finance" className="group block">
      <div className="label">{label}</div>
      <div className={`num mt-1.5 text-[24px] font-medium leading-none tracking-[-0.03em] transition-colors group-hover:text-accent sm:text-[28px] ${tone || ''}`}>{value}</div>
    </Link>
  )
}

const KIND_COLOR = { event: 'var(--accent)', task: 'var(--pos)', finance: 'var(--warn)', note: '#7c3aed', link: '#0891b2', chat: 'var(--ink-3)', system: 'var(--ink-3)' }
export function KindDot({ kind }) { return <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: KIND_COLOR[kind] || 'var(--ink-3)' }} /> }

function EventRow({ e, now }) {
  const start = new Date(e.start), end = e.end ? new Date(e.end) : null
  const live = start <= now && end && end >= now
  const past = end && end < now
  return (
    <div className={`row ${past ? 'opacity-50' : ''}`}>
      <div className="num w-12 shrink-0 text-[14.5px] font-semibold">{hhmm(e.start)}</div>
      <div className={`h-7 w-[3px] shrink-0 rounded-full ${live ? 'bg-green' : 'bg-accent'}`} />
      <div className="min-w-0 flex-1 truncate text-[14.5px] font-medium">{e.title}</div>
      {live && <span className="badge pos">сейчас</span>}
    </div>
  )
}
