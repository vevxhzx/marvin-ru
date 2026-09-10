import { useEffect, useMemo, useState } from 'react'
import { Check, Plus, Trash2, MessageCircle, CalendarClock, ArrowDownUp } from 'lucide-react'
import { api, dayLabel, hhmm, isSameDay, plural } from '../lib/api'
import { Section, Empty, Sheet, Field, Seg, Pills, useToast, PriorityDot, PageHead, useLeave, useArrived, useDoneFlash, Swipe, ListSkeleton } from '../components/ui'
import { useRefresh } from '../App'
import { usePrefs, prefs as PREFS } from '../lib/prefs'

const VIEWS = [['open', 'открытые'], ['today', 'сегодня'], ['done', 'выполнено']]
const SORTS = [['priority', 'по важности'], ['due', 'по сроку'], ['new', 'по новизне']]
const dueTs = (t) => (t.due ? new Date(t.due).getTime() : 9e15)
const SORT_FN = {
  priority: (a, b) => a.priority - b.priority || dueTs(a) - dueTs(b),
  due: (a, b) => dueTs(a) - dueTs(b) || a.priority - b.priority,
  new: (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0),
}
const ask = (text) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } }))

export default function Tasks() {
  const [tasks, setTasks] = useState(null)
  const [view, setView] = useState('open')
  const [quick, setQuick] = useState('')
  const [sheet, setSheet] = useState(false)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()
  const { tasksSort = 'priority' } = usePrefs()
  const sortFn = SORT_FN[tasksSort] || SORT_FN.priority

  const load = () => api.tasks(true).then(setTasks).catch(() => {})
  useEffect(() => { load() }, [tick])

  const now = new Date()
  const all = tasks || []
  const open = all.filter((t) => !t.done)
  const done = all.filter((t) => t.done).sort((a, b) => new Date(b.done_at) - new Date(a.done_at))
  const groups = useMemo(() => {
    const g = { overdue: [], today: [], week: [], later: [], nodate: [] }
    const weekEnd = new Date(now); weekEnd.setDate(now.getDate() + 7)
    for (const t of open) {
      if (!t.due) g.nodate.push(t)
      else { const d = new Date(t.due); if (d < now) g.overdue.push(t); else if (isSameDay(d, now)) g.today.push(t); else if (d < weekEnd) g.week.push(t); else g.later.push(t) }
    }
    for (const k in g) g[k].sort(sortFn)
    return g
  }, [tasks, tasksSort])

  const addQuick = async (e) => {
    e.preventDefault(); if (!quick.trim()) return
    try { await api.chat(`задача: ${quick.trim()}`); setQuick(''); flashQuick(); load(); bump() } catch (err) { show.err(err) }
  }
  const [leaveCls, leave] = useLeave()
  const arrivedCls = useArrived(open.map((t) => t.id))
  const [quickDone, flashQuick] = useDoneFlash()
  const toggle = (t) => t.done
    ? leave(t.id, 'leaving', async () => { await api.undoneTask(t.id); await load(); bump() })
    : leave(t.id, 'done', async () => { await api.doneTask(t.id); await load(); bump(); show('Задача закрыта', '', t.title) })
  const del = (t) => leave(t.id, 'leaving', async () => { await api.delTask(t.id); show('Задача удалена', '', t.title); await load(); bump() })
  const setPriority = async (t, p) => { try { await api.patchTask(t.id, { priority: p }); load(); bump() } catch (e) { show.err(e) } }

  const Group = ({ title, list, tone }) => list.length ? (
    <div>
      <div className={`label mb-1 ${tone || ''}`}>{title} <span className="idx">{list.length}</span></div>
      <div className="rule stagger">{list.map((t) => <Row key={t.id} t={t} onToggle={toggle} onDel={del} onPriority={setPriority} now={now} extra={`${leaveCls(t.id)} ${arrivedCls(t.id)}`} />)}</div>
    </div>
  ) : null

  const kicker = groups.overdue.length ? `${groups.overdue.length} ${plural(groups.overdue.length, 'просрочена', 'просрочены', 'просрочено')}` : open.length ? `${open.length} ${plural(open.length, 'открытая', 'открытые', 'открытых')}` : 'всё сделано'
  return (
    <div className="space-y-10">
      <PageHead kicker={kicker} title="задачи" idx={open.length}
        right={<><Seg value={view} onChange={setView} options={VIEWS} /><button className="btn-primary" onClick={() => setSheet(true)}><Plus size={15} /> задача</button></>} />

      <form onSubmit={addQuick} className="composer animate-rise flex items-center gap-2 py-1.5 pl-4 pr-1.5">
        <Plus size={16} className="faint shrink-0" />
        <input value={quick} onChange={(e) => setQuick(e.target.value)} className="h-9 w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]" placeholder="Быстро, своими словами: «позвонить маме завтра в 18»…" />
        <button className={`btn-primary grid !h-9 !w-9 shrink-0 !rounded-full !p-0 ${quickDone}`} disabled={!quick.trim() && !quickDone} aria-label="Добавить">{quickDone ? <Check size={16} strokeWidth={3} /> : <Plus size={16} />}</button>
      </form>

      {view !== 'done' && (
        <div className="-mt-6 flex items-center justify-end gap-1 text-[12px]">
          <ArrowDownUp size={12} className="faint" />
          {SORTS.map(([v, l]) => <button key={v} type="button" onClick={() => PREFS.set({ tasksSort: v })} className={`rounded-md px-2 py-1 transition-colors ${v === tasksSort ? 'bg-[var(--fill)] text-[var(--ink)]' : 'faint hover:text-[var(--ink)]'}`}>{l}</button>)}
        </div>
      )}

      {!tasks ? <ListSkeleton n={5} /> : view === 'done' ? (
        <Section title="выполнено" idx={done.length}>
          <div className="rule">
            {done.length === 0 ? <Empty glyph="tasks" text="Пока ничего не закрыто" sub="Первая галочка — самая приятная" /> : done.slice(0, 50).map((t) => <Row key={t.id} t={t} onToggle={toggle} onDel={del} onPriority={setPriority} now={now} extra={leaveCls(t.id)} />)}
          </div>
        </Section>
      ) : view === 'today' ? (
        <div className="space-y-6">
          {!groups.overdue.length && !groups.today.length && <div className="rule"><Empty glyph="tasks" text="На сегодня пусто" sub="Можно взять что-то из «позже» или отдохнуть, сэр" hint="задача: разобрать почту сегодня" /></div>}
          <Group title="просрочено" list={groups.overdue} tone="!text-red" />
          <Group title="сегодня" list={groups.today} tone="!text-accent" />
        </div>
      ) : (
        <div className="space-y-6">
          {open.length === 0 && <div className="rule"><Empty glyph="tasks" text="Список пуст" sub="Можно отдыхать, сэр. Или сказать мне что-нибудь." hint="задача: купить молоко" /></div>}
          <Group title="просрочено" list={groups.overdue} tone="!text-red" />
          <Group title="сегодня" list={groups.today} tone="!text-accent" />
          <Group title="на неделе" list={groups.week} />
          <Group title="позже" list={groups.later} />
          <Group title="без срока" list={groups.nodate} />
          {done.length > 0 && <button className="btn-ghost btn-sm" onClick={() => setView('done')}>выполнено · {done.length}</button>}
        </div>
      )}

      <TaskSheet open={sheet} onClose={() => setSheet(false)} onDone={() => { setSheet(false); show('Задача добавлена'); load(); bump() }} onErr={show.err} />
    </div>
  )
}

function Row({ t, onToggle, onDel, onPriority, now, extra = '' }) {
  const overdue = !t.done && t.due && new Date(t.due) < now
  const going = extra.includes('leaving')
  const checked = t.done || extra.includes('leaving-done')
  return (
    <Swipe onRight={!going ? () => onToggle(t) : undefined} onLeft={!going ? () => onDel(t) : undefined} rightLabel={t.done ? 'вернуть' : 'готово'}>
      <div className={`row row-slide group done-fade ${t.done ? 'opacity-50' : ''} ${extra}`}>
        <button onClick={() => !going && onToggle(t)} aria-label={t.done ? 'Вернуть' : 'Выполнено'} className={`grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full border transition-all duration-300 hover:scale-110 active:scale-90 ${checked ? 'border-accent bg-accent text-white' : 'hover:border-accent'}`} style={checked ? {} : { borderColor: t.priority === 1 ? 'var(--neg)' : 'var(--line-2)' }}>
          {checked ? <Check size={12} strokeWidth={3} className="check-pop" /> : <Check size={12} className="opacity-0 transition group-hover:opacity-40" />}
        </button>
        <div className="min-w-0 flex-1">
          <div className={`truncate text-[15px] font-medium ${t.done ? 'line-through' : ''}`}>{t.title}</div>
          <div className={`flex items-center gap-1.5 text-[12px] ${overdue ? 'neg' : 'muted'}`}>
            {t.due && <span className="flex items-center gap-1"><CalendarClock size={11} /> {overdue ? 'просрочено · ' : ''}{dayLabel(t.due).toLowerCase()}, {hhmm(t.due)}</span>}
            {t.project && <span>{t.due ? '· ' : ''}{t.project}</span>}
            {t.done && t.done_at && <span>· сделано {dayLabel(t.done_at).toLowerCase()}</span>}
            {!t.due && !t.project && !t.done && <span className="faint">без срока</span>}
          </div>
        </div>
        {!t.done && <PriorityDot value={t.priority} onChange={(p) => onPriority(t, p)} disabled={going} />}
        <button className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100 focus:opacity-100" data-tip="обсудить с ассистентом" onClick={() => ask(`по задаче «${t.title}»: `)} aria-label="Обсудить"><MessageCircle size={14} /></button>
        <button className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100 focus:opacity-100" data-tip="удалить" onClick={() => onDel(t)} aria-label="Удалить"><Trash2 size={14} /></button>
      </div>
    </Swipe>
  )
}

function TaskSheet({ open, onClose, onDone, onErr }) {
  const [f, setF] = useState({ title: '', due: '', priority: 2, project: '' })
  useEffect(() => { if (open) setF({ title: '', due: '', priority: 2, project: '' }) }, [open])
  const submit = async (e) => { e.preventDefault(); try { await api.addTask({ title: f.title, due: f.due || null, priority: Number(f.priority), project: f.project || null }); onDone() } catch (err) { onErr(err) } }
  return (
    <Sheet open={open} onClose={onClose} title="новая задача" sub="или просто скажите ассистенту — он поймёт срок из фразы">
      <form onSubmit={submit} className="space-y-4">
        <Field label="что сделать"><input autoFocus className="input !text-[17px] !font-medium" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required /></Field>
        <Field label="приоритет"><Pills value={Number(f.priority)} onChange={(p) => setF({ ...f, priority: p })} options={[[1, 'важно'], [2, 'обычная'], [3, 'низкая']]} /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="дедлайн"><input type="datetime-local" className="input" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></Field>
          <Field label="проект"><input className="input" placeholder="Работа / Дом" value={f.project} onChange={(e) => setF({ ...f, project: e.target.value })} /></Field>
        </div>
        <button className="btn-primary btn-lg w-full">добавить</button>
      </form>
    </Sheet>
  )
}
