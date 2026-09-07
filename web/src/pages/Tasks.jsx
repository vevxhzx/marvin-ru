import { useEffect, useMemo, useState } from 'react'
import { Check, Plus, Trash2, RotateCcw, Flag } from 'lucide-react'
import { api, dayLabel, hhmm, toLocalISO, isSameDay } from '../lib/api'
import { Card, Section, Empty, Sheet, Field, Seg, Pills, useToast, Toast, PRIORITY, PageHead, useLeave, useArrived, useDoneFlash, Swipe } from '../components/ui'
import { useRefresh } from '../App'

export default function Tasks() {
  const [tasks, setTasks] = useState([])
  const [showDone, setShowDone] = useState(false)
  const [quick, setQuick] = useState('')
  const [sheet, setSheet] = useState(false)
  const [toast, show] = useToast()
  const { tick, bump } = useRefresh()

  const load = () => api.tasks(true).then(setTasks).catch(() => {})
  useEffect(() => { load() }, [tick])

  const now = new Date()
  const open = tasks.filter((t) => !t.done)
  const done = tasks.filter((t) => t.done).sort((a, b) => new Date(b.done_at) - new Date(a.done_at))
  const groups = useMemo(() => {
    const g = { overdue: [], today: [], week: [], later: [], nodate: [] }
    const weekEnd = new Date(now); weekEnd.setDate(now.getDate() + 7)
    for (const t of open) {
      if (!t.due) g.nodate.push(t)
      else { const d = new Date(t.due); if (d < now) g.overdue.push(t); else if (isSameDay(d, now)) g.today.push(t); else if (d < weekEnd) g.week.push(t); else g.later.push(t) }
    }
    for (const k in g) g[k].sort((a, b) => a.priority - b.priority || (a.due ? new Date(a.due) : 9e15) - (b.due ? new Date(b.due) : 9e15))
    return g
  }, [tasks])

  const addQuick = async (e) => {
    e.preventDefault(); if (!quick.trim()) return
    // через мозг: понимает «сдать отчёт через 3 дня»
    await api.chat(`задача: ${quick.trim()}`); setQuick(''); flashQuick(); load(); bump()
  }
  const [leaveCls, leave] = useLeave()
  const arrivedCls = useArrived(tasks.filter((t) => !t.done).map((t) => t.id))
  const [quickDone, flashQuick] = useDoneFlash()
  // выполнение/удаление: сначала строка красиво уходит, потом запрос и перерисовка
  const toggle = (t) => t.done
    ? leave(t.id, 'leaving', async () => { await api.undoneTask(t.id); await load(); bump() })
    : leave(t.id, 'done', async () => { await api.doneTask(t.id); await load(); bump() })
  const del = (t) => leave(t.id, 'leaving', async () => { await api.delTask(t.id); show('Задача удалена'); await load(); bump() })

  const Group = ({ title, list, tone }) => list.length ? (
    <div>
      <div className={`label mb-1 ${tone || ''}`}>{title} · {list.length}</div>
      <div className="rule stagger">{list.map((t) => <Row key={t.id} t={t} onToggle={toggle} onDel={del} now={now} extra={`${leaveCls(t.id)} ${arrivedCls(t.id)}`} />)}</div>
    </div>
  ) : null

  return (
    <div className="space-y-10">
      <PageHead kicker={open.length ? `${open.length} открытых` : 'всё сделано'} title="задачи" idx={open.length}
        right={<button className="btn-primary" onClick={() => setSheet(true)}><Plus size={15} /> задача</button>} />

      <form onSubmit={addQuick} className="animate-rise flex gap-2">
        <input value={quick} onChange={(e) => setQuick(e.target.value)} className="input !rounded-full" placeholder="Быстро: «позвонить маме завтра в 18»…" />
        <button className={`btn-primary grid !h-12 !w-12 shrink-0 !rounded-full !p-0 ${quickDone}`} disabled={!quick.trim() && !quickDone}>{quickDone ? <Check size={18} strokeWidth={3} /> : <Plus size={18} />}</button>
      </form>

      {open.length === 0 && <div className="rule"><Empty glyph="tasks" text="Список пуст" sub="Можно отдыхать, сэр. Или сказать мне что-нибудь." hint="задача: купить молоко" /></div>}
      <div className="space-y-5">
        <Group title="Просрочено" list={groups.overdue} tone="!text-red" />
        <Group title="Сегодня" list={groups.today} tone="!text-accent" />
        <Group title="На неделе" list={groups.week} />
        <Group title="Позже" list={groups.later} />
        <Group title="Без срока" list={groups.nodate} />
      </div>

      {done.length > 0 && (
        <Section title="выполнено" idx={done.length} action={<button className="btn-ghost !py-1.5 !text-[13px]" onClick={() => setShowDone(!showDone)}>{showDone ? 'скрыть' : `показать ${done.length}`}</button>}>
          {showDone && <div className="rule">{done.slice(0, 30).map((t) => <Row key={t.id} t={t} onToggle={toggle} onDel={del} now={now} extra={leaveCls(t.id)} />)}</div>}
        </Section>
      )}

      <TaskSheet open={sheet} onClose={() => setSheet(false)} onDone={() => { setSheet(false); show('Задача добавлена'); load(); bump() }} />
      <Toast msg={toast.msg} kind={toast.kind} />
    </div>
  )
}

function Row({ t, onToggle, onDel, now, extra = '' }) {
  const overdue = !t.done && t.due && new Date(t.due) < now
  const going = extra.includes('leaving')
  return (
    <Swipe onRight={!going ? () => onToggle(t) : undefined} onLeft={!going ? () => onDel(t) : undefined} rightLabel={t.done ? 'вернуть' : 'готово'}>
    <div className={`row row-slide group done-fade ${t.done ? 'opacity-50' : ''} ${extra}`}>
      <button onClick={() => !going && onToggle(t)} className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border transition-all duration-300 hover:scale-110 active:scale-90 ${t.done || extra.includes('leaving-done') ? 'border-accent bg-accent text-white check-pop' : 'hover:border-accent'}`} style={t.done || extra.includes('leaving-done') ? {} : { borderColor: 'var(--line-2)' }}>
        {t.done || extra.includes('leaving-done') ? <Check size={14} strokeWidth={3} className="check-pop" /> : <Check size={14} className="opacity-0 transition group-hover:opacity-40" />}
      </button>
      <div className="min-w-0 flex-1">
        <div className={`truncate text-[15px] font-medium ${t.done ? 'line-through' : ''}`}>{t.title}</div>
        <div className={`text-[12px] ${overdue ? 'text-red' : 'muted'}`}>
          {t.due ? `до ${dayLabel(t.due)}, ${hhmm(t.due)}` : t.project || ''}{t.done && t.done_at ? ` · сделано ${dayLabel(t.done_at)}` : ''}
        </div>
      </div>
      <span className={`h-2 w-2 shrink-0 rounded-full ${PRIORITY[t.priority]?.dot}`} title={PRIORITY[t.priority]?.label} />
      <button className="btn-icon !h-8 !w-8 opacity-0 transition group-hover:opacity-100" onClick={() => onDel(t)}><Trash2 size={14} /></button>
    </div>
    </Swipe>
  )
}

function TaskSheet({ open, onClose, onDone }) {
  const [f, setF] = useState({ title: '', due: '', priority: 2, project: '' })
  useEffect(() => { if (open) setF({ title: '', due: '', priority: 2, project: '' }) }, [open])
  const submit = async (e) => { e.preventDefault(); await api.addTask({ title: f.title, due: f.due || null, priority: Number(f.priority), project: f.project || null }); onDone() }
  return (
    <Sheet open={open} onClose={onClose} title="новая задача">
      <form onSubmit={submit} className="space-y-4">
        <Field label="что сделать"><input autoFocus className="input !text-[18px] !font-medium" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required /></Field>
        <Field label="приоритет"><Pills value={Number(f.priority)} onChange={(p) => setF({ ...f, priority: p })} options={[[1, 'важно'], [2, 'обычная'], [3, 'низкая']]} /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="дедлайн"><input type="datetime-local" className="input" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></Field>
          <Field label="проект"><input className="input" placeholder="Работа / Дом" value={f.project} onChange={(e) => setF({ ...f, project: e.target.value })} /></Field>
        </div>
        <button className="btn-primary w-full !py-3">добавить</button>
      </form>
    </Sheet>
  )
}
