/* MTasks — мобильные задачи. Живые данные: GET /api/tasks, POST /api/tasks, done/undone.
   Кит из ../ui.jsx, стили m-*. */
import { useEffect, useMemo, useState } from 'react'
import { ArrowUp, ArrowUpDown, Check, ChevronDown, Clock, ListChecks, Plus, Repeat, Search, X } from 'lucide-react'
import { api, hhmm, isAllDay, isSameDay, money, shortDate } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { Card, Count, Overline, Pill, ScreenTitle, Segmented, TaskCheck } from '../ui.jsx'

const day0 = (d = new Date()) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
const prStr = (p) => (p === 1 ? 'high' : p === 3 ? 'low' : 'mid')

function bucketOf(t, now) {
  if (!t.due) return 'someday'
  const dt = new Date(t.due)
  if (Number.isNaN(dt)) return 'someday'
  const d0 = day0(now).getTime(), dd = day0(dt).getTime()
  if (dd < d0) return 'overdue'
  if (dd === d0) return 'today'
  if (dd === d0 + 864e5) return 'tomorrow'
  return 'later'
}

/* Эвристика превью (клиентская, без сервера): время, день, срочность. */
function parseQuick(s) {
  const txt = String(s || '')
  const low = txt.toLowerCase().replace(/ё/g, 'е')   // i18n-raw
  const mTime = txt.match(/(\d{1,2})[:.](\d{2})/)
  const time = mTime ? `${String(Math.min(23, +mTime[1])).padStart(2, '0')}:${mTime[2]}` : null
  let date = null
  if (/послезавтра|day after/.test(low)) date = 2
  else if (/завтра|tomorrow/.test(low)) date = 1
  else if (/сегодня|today/.test(low)) date = 0
  const priority = /срочно|важно|asap|urgent|!!!/.test(low) ? 'high' : null
  return { time, date, priority }
}
function dueISO(dateOff, time) {
  const d = new Date(); d.setDate(d.getDate() + (dateOff ?? 0))
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${time || '23:59'}`
}

export default function MTasks() {
  const { t } = useI18n()
  const [all, setAll] = useState(null)
  const [err, setErr] = useState(null)
  const [view, setView] = useState('today')
  const [sort, setSort] = useState('importance')
  const [sortOpen, setSortOpen] = useState(false)
  const [search, setSearch] = useState(null)
  const [draft, setDraft] = useState('')
  const [toastMsg, setToastMsg] = useState(null)
  const now = useMemo(() => new Date(), [])

  const load = () => api.tasks(true, false).then((l) => { setAll(l || []); setErr(null) }).catch(() => setErr(true))
  useEffect(() => { load() }, [])

  const toast = (text, action) => {
    setToastMsg({ text, action })
    window.clearTimeout(toast._t)
    toast._t = window.setTimeout(() => setToastMsg(null), 4000)
  }

  const open = useMemo(() => (all || []).filter((x) => !x.done && x.kind !== 'event'), [all])
  const doneList = useMemo(() => (all || []).filter((x) => !!x.done), [all])
  const withBucket = useMemo(() => open.map((x) => ({ ...x, _b: bucketOf(x, now) })), [open, now])
  const todayCount = withBucket.filter((x) => x._b === 'today' || x._b === 'overdue').length

  let list = view === 'done' ? doneList : view === 'today'
    ? withBucket.filter((x) => x._b === 'today' || x._b === 'overdue')
    : withBucket
  if (search) list = list.filter((x) => (x.title || '').toLowerCase().includes(search.toLowerCase()))
  const sorter = (a, b) => sort === 'importance'
    ? (a.priority - b.priority) || ((a.due || '99') > (b.due || '99') ? 1 : -1)
    : sort === 'due'
      ? ((a.due || '99') > (b.due || '99') ? 1 : (a.due || '99') < (b.due || '99') ? -1 : 0)
      : new Date(b.created_at || 0) - new Date(a.created_at || 0)
  const sorted = [...list].sort(sorter)
  const sortLabel = sort === 'importance' ? t('m.sort_imp') : sort === 'due' ? t('m.sort_due') : t('m.sort_new')

  const groups = view === 'done'
    ? [{ key: 'done', label: t('m.b_done'), items: [...list].sort((a, b) => new Date(b.done_at || 0) - new Date(a.done_at || 0)) }]
    : ['overdue', 'today', 'tomorrow', 'later', 'someday'].map((b) => ({
        key: b,
        label: t(`m.b_${b === 'someday' ? 'someday' : b === 'overdue' ? 'overdue' : b === 'today' ? 'today' : b === 'tomorrow' ? 'tomorrow' : 'later'}`),
        items: sorted.filter((x) => x._b === b),
      })).filter((g) => g.items.length > 0)

  const toggle = async (x) => {
    try {
      if (x.done) { await api.undoneTask(x.id); toast(t('m.back_work')); }
      else { await api.doneTask(x.id); toast(t('m.task_done'), { label: t('m.undo'), fn: async () => { try { await api.undoneTask(x.id); load() } catch {} } }) }
      load()
    } catch (e) { toast(String(e?.message || e)) }
  }

  const parsed = draft.trim() ? parseQuick(draft) : null
  const submit = async (e) => {
    e?.preventDefault()
    const title = draft.trim()
    if (!title) return
    const p = parseQuick(title)
    const body = { title }
    if (p.date != null || p.time) body.due = dueISO(p.date ?? 0, p.time)
    if (p.priority === 'high') body.priority = 1
    try {
      await api.addTask(body)
      const when = p.date === 1 ? t('m.tomorrow') : p.date === 2 ? '' : t('m.today')
      toast(t('m.added', { when: `${when}${p.time ? ` ${p.time}` : ''}`.trim() }))
      setDraft('')
      load()
    } catch (err2) { toast(String(err2?.message || err2)) }
  }

  if (err) {
    return (
      <div className="px-5 pt-10 text-center">
        <div className="text-[15px] text-white/70">{t('m.load_err')}</div>
        <button className="m-glass mt-3 rounded-full px-4 py-2 text-[13.5px]" onClick={load}>{t('m.retry')}</button>
      </div>
    )
  }
  if (!all) return <div className="px-5 pt-10 text-[15px] text-white/50">{t('m.loading')}</div>

  return (
    <div>
      <ScreenTitle
        title={t('m.tasks_title')}
        subtitle={t('m.tasks_sub', { open: open.length, today: todayCount })}
        right={(
          <button aria-label={t('common.search')} onClick={() => setSearch((s) => (s === null ? '' : null))} className="grid h-10 w-10 place-items-center rounded-full bg-white/[0.07] text-white/70">
            {search !== null ? <X size={18} /> : <Search size={18} />}
          </button>
        )}
      />
      <div className="mt-5 px-4">
        <Segmented
          value={view}
          onChange={setView}
          options={[
            { id: 'today', label: <>{t('m.seg_today')} <Count n={todayCount} /></> },
            { id: 'all', label: <>{t('m.seg_all')} <Count n={open.length} /></> },
            { id: 'done', label: <>{t('m.seg_done')} <Count n={doneList.length} /></> },
          ]}
        />
      </div>
      {search !== null && (
        <div className="anim-rise mt-3 px-4">
          <div className="m-glass flex h-12 items-center gap-2.5 rounded-full px-4">
            <Search size={18} className="text-white/50" />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('m.search_ph')}
              className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-white/40"
            />
          </div>
        </div>
      )}
      <div className="mt-3 px-4">
        <form
          onSubmit={submit}
          className="flex h-[54px] items-center gap-2 rounded-full border border-white/10 bg-[#0f1640]/75 pl-4 pr-1.5 transition focus-within:border-[#7d95ff]/50"
        >
          <Plus size={20} className="shrink-0 text-[#8ea3ff]" />
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t('m.quick_ph')}
            className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-white/40"
          />
          {draft ? (
            <button type="submit" aria-label={t('common.add')} className="m-fab anim-pop grid h-10 w-10 shrink-0 place-items-center rounded-full">
              <ArrowUp size={18} strokeWidth={2.5} />
            </button>
          ) : null}
        </form>
        {parsed && (
          <div className="anim-fade mt-2 flex flex-wrap items-center gap-1.5 px-2">
            <span className="text-[12px] text-white/45">{t('m.parsed')}</span>
            <Pill tone="blue">{parsed.date === 1 ? t('m.tomorrow') : t('m.today')}</Pill>
            {parsed.time && <Pill tone="blue" icon={Clock}>{parsed.time}</Pill>}
            {parsed.priority === 'high' && <Pill tone="red">{t('m.urgent')}</Pill>}
          </div>
        )}
      </div>
      <div className="relative z-20 mt-4 flex items-center justify-between px-5">
        <button onClick={() => setSortOpen((o) => !o)} className="flex h-8 items-center gap-1.5 text-[13px] font-medium text-white/70">
          <ArrowUpDown size={14} />
          {sortLabel}
          <ChevronDown size={14} className={`transition${sortOpen ? ' rotate-180' : ''}`} />
        </button>
        <span className="tnum text-[12px] text-white/40">{t('m.in_list', { n: list.length })}</span>
        {sortOpen && (
          <div className="anim-rise absolute left-4 top-9 w-56 rounded-[20px] border border-white/10 bg-[#121a46]/95 p-1.5 shadow-[0_24px_48px_-12px_rgba(0,0,0,0.65)] backdrop-blur-xl">
            {[['importance', 'm.sort_imp'], ['due', 'm.sort_due'], ['new', 'm.sort_new']].map(([k, key]) => (
              <button
                key={k}
                onClick={() => { setSort(k); setSortOpen(false) }}
                className="flex w-full items-center justify-between rounded-[14px] px-3 py-2.5 text-[14px] transition hover:bg-white/5"
              >
                {t(key)}
                {sort === k && <Check size={16} className="text-[#8ea3ff]" />}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="mt-2 space-y-3 px-4 pt-3">
        {groups.map((g) => (
          <Card key={g.key} className="px-1.5 py-1.5">
            <div className="px-3.5 pb-1 pt-3">
              <Overline className={g.key === 'overdue' ? 'text-[#ff9aac]' : undefined}>{g.label} · {g.items.length}</Overline>
            </div>
            {g.items.map((x, i) => (
              <MTaskRow key={x.id} task={x} last={i === g.items.length - 1} onToggle={() => toggle(x)} />
            ))}
          </Card>
        ))}
        {groups.length === 0 && (
          <Card className="px-6 py-10 text-center">
            <div className="text-[34px]">✦</div>
            <div className="mt-2 text-[16px] font-semibold">{t('m.empty')}</div>
            <div className="mt-1 text-[13px] text-white/55">{t('m.empty_sub')}</div>
          </Card>
        )}
      </div>
      {toastMsg && (
        <div className="fixed bottom-24 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full border border-white/10 bg-[#121a46]/95 py-2.5 pl-4 pr-2.5 shadow-xl backdrop-blur-xl">
          <span className="max-w-[60vw] truncate text-[13.5px]">{toastMsg.text}</span>
          {toastMsg.action && (
            <button
              onClick={() => { toastMsg.action.fn(); setToastMsg(null) }}
              className="shrink-0 rounded-full bg-white/10 px-3 py-1.5 text-[13px] font-medium"
            >
              {toastMsg.action.label}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function MTaskRow({ task: x, last, onToggle }) {
  const { t } = useI18n()
  const done = !!x.done
  const b = x._b || bucketOf(x, new Date())
  const tone = b === 'overdue' ? 'red' : b === 'today' ? 'amber' : b === 'tomorrow' ? 'blue' : 'gray'
  const when = x.due
    ? (isAllDay(x.due) ? shortDate(x.due) : (b === 'tomorrow' ? `${t('m.tomorrow')} ${hhmm(x.due)}` : hhmm(x.due)))
    : t('m.no_due')
  void money
  return (
    <div className={`flex items-start gap-3 px-3.5 py-3${!last ? ' border-b border-white/[0.06]' : ''}`}>
      <div className="-mt-[2px]">
        <TaskCheck done={done} priority={prStr(x.priority)} onToggle={onToggle} />
      </div>
      <div className="min-w-0 flex-1">
        <div className={`line-clamp-2 text-[15px] font-medium leading-[1.35]${done ? ' text-white/45 line-through decoration-white/40' : ''}`}>
          {x.title}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1.5">
          {x.due && <Pill tone={done ? 'gray' : tone} icon={Clock}>{when}</Pill>}
          {x.project && <span className="text-[12.5px] text-white/55">{x.project}</span>}
          {x.repeat && <Repeat size={13} className="text-white/45" />}
          {x.sub && <span className="tnum inline-flex items-center gap-1 text-[12.5px] text-white/45"><ListChecks size={13} />{x.sub}</span>}
        </div>
      </div>
    </div>
  )
}
