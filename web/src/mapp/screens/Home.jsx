/* MHome — мобильная главная. Только живые данные через lib/api.js (dashboard + txs).
   Разметка — классы m-* и кит из ../ui.jsx (контракт параллельного агента). */
import { useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, Brain, Clapperboard, Users } from 'lucide-react'
import { api, hhmm, isSameDay, money } from '../../lib/api'
import { localeOf, useI18n } from '../../lib/i18n'
import { Avatar, BigMoney, Card, IconTile, MEmpty, MLoadError, MLoading, MarvinOrb, Overline, SectionHead, TaskCheck } from '../ui.jsx'

const goDefault = (id) => {
  const map = { brain: '/mind', orders: '/orders', people: '/people', finance: '/finance', tasks: '/tasks', calendar: '/calendar', settings: '/settings', chat: null }
  if (id === 'chat') {
    window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: '', send: false } }))
    return
  }
  window.location.assign(map[id] || '/')
}
const chatWith = (text) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text, send: false } }))

const day0 = (d = new Date()) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x }
const sameDay = (a, b) => isSameDay(a, b)
const evTime = (e) => new Date(e.start)

function greetKey(h) {
  if (h < 5) return 'm.greet_night'
  if (h < 12) return 'm.greet_morning'
  if (h < 18) return 'm.greet_day'
  if (h < 23) return 'm.greet_evening'
  return 'm.greet_night'
}

/* Прошлое для CashChart: идём от текущего баланса назад по дневным дельтам живых операций. */
function buildPast(txs, balance, days = 30) {
  const byDay = new Map()
  for (const tx of txs || []) {
    if (!tx?.date) continue
    const k = new Date(tx.date).toDateString()
    const dl = tx.kind === 'income' ? Number(tx.amount) || 0 : tx.kind === 'expense' ? -(Number(tx.amount) || 0) : 0
    byDay.set(k, (byDay.get(k) || 0) + dl)
  }
  const today = day0()
  const pts = []
  let after = 0
  for (let i = 0; i <= days; i++) {
    const d = new Date(today); d.setDate(d.getDate() - i)
    const delta = byDay.get(d.toDateString()) || 0
    pts.push({ date: d.toISOString(), balance: Math.round(balance - after) })
    after += delta
  }
  return pts.reverse()
}

export default function MHome(props = {}) {
  const { t } = useI18n()
  const go = props.go || goDefault
  const [dash, setDash] = useState(null)
  const [txs, setTxs] = useState(null)
  const [err, setErr] = useState(null)
  const [toastMsg, setToastMsg] = useState(null)
  const [initials, setInitials] = useState('·')

  const load = () => Promise.all([api.dashboard().catch(() => null), api.txs(30).catch(() => [])]).then(([d, x]) => {
    if (!d) { setErr(true); return }
    setDash(d); setTxs(x || []); setErr(null)
  })
  useEffect(() => {
    let live = true
    load().then(() => { if (!live) return })
    api.settings().then((d) => {
      if (!live) return
      const it = d?.items?.find((x) => x.key === 'owner.name')
      const v = String(it?.value || '').trim()
      if (v) setInitials(v[0].toUpperCase())
    }).catch(() => {})
    return () => { live = false }
  }, [])

  const toast = (text, action) => {
    setToastMsg({ text, action })
    window.clearTimeout(toast._t)
    toast._t = window.setTimeout(() => setToastMsg(null), 4000)
  }

  const toggleTask = async (x) => {
    try {
      if (x.done) { await api.undoneTask(x.id); toast(t('m.back_work')) }
      else { await api.doneTask(x.id); toast(t('m.task_done'), { label: t('m.undo'), fn: async () => { try { await api.undoneTask(x.id); load() } catch {} } }) }
      load()
    } catch (e) { toast(String(e?.message || e)) }
  }

  const now = useMemo(() => new Date(), [])
  const fin = dash?.finance || {}
  const balance = Number(fin.total_balance ?? fin.balance ?? 0)
  const avgDay = Number(fin.avg_daily ?? dash?.forecast?.per_day ?? 0)
  const runway = fin.runway_days ?? null
  const fit = runway == null ? 30 : Math.max(0, Math.min(30, Math.round(runway)))
  const lowDate = dash?.forecast?.low_date || null
  const lowShort = lowDate ? new Date(lowDate).toLocaleDateString(localeOf(), { day: 'numeric', month: 'numeric' }) : null

  const openTasks = useMemo(() => (dash?.tasks || []).filter((x) => !x.done), [dash])
  const todayEvents = useMemo(() => {
    const list = [...(dash?.today || [])].sort((a, b) => new Date(a.start) - new Date(b.start))
    return list
  }, [dash])
  const openToday = useMemo(() => {
    const t0 = day0(now).getTime()
    return openTasks.filter((x) => {
      if (!x.due) return false
      const dt = new Date(x.due).getTime()
      return dt < t0 + 864e5 && !Number.isNaN(dt)
    }).length
  }, [openTasks, now])

  const agenda = useMemo(() => {
    const items = []
    for (const e of todayEvents) {
      if (e.done) continue
      items.push({ type: 'event', id: `e${e.id}`, at: evTime(e), title: e.title, sub: e.location || '', kind: e.kind || 'event' })
    }
    for (const x of openTasks) {
      if (!x.due || !sameDay(x.due, now)) continue
      const at = new Date(x.due)
      if (Number.isNaN(at)) continue
      items.push({ type: 'task', id: `t${x.id}`, at, title: x.title, task: x })
    }
    return items.sort((a, b) => a.at - b.at)
  }, [todayEvents, openTasks, now])

  const nextUp = agenda.find((a) => a.at > now)
  const nowLine = nextUp
    ? `${t('m.now', { time: now.toLocaleTimeString(localeOf(), { hour: '2-digit', minute: '2-digit' }) })} · ${nextUp.title.slice(0, 42)}`
    : t('m.now', { time: now.toLocaleTimeString(localeOf(), { hour: '2-digit', minute: '2-digit' }) })

  const mainTask = useMemo(() => {
    const c = openTasks.filter((x) => x.due).sort((a, b) => (a.priority - b.priority) || (new Date(a.due) - new Date(b.due)))[0]
    return c || openTasks.sort((a, b) => a.priority - b.priority)[0] || null
  }, [openTasks])

  const memCount = (dash?.memory || []).length
  const ordersOpen = (dash?.orders?.open || []).length
  const bdays = (dash?.birthdays || []).length
  const shortcuts = [
    { id: 'brain', label: t('m.brain'), value: t('m.notes_n', { count: memCount }), icon: Brain, color: '#ff8da1' },
    { id: 'orders', label: t('m.orders'), value: t('m.in_work', { count: ordersOpen }), icon: Clapperboard, color: '#ffc24d' },
    { id: 'people', label: t('m.people'), value: t('m.soon_n', { count: bdays }), icon: Users, color: '#3ddc97' },
  ]

  const fcPts = dash?.forecast?.points || []
  const past = useMemo(() => (txs ? buildPast(txs, balance) : []), [txs, balance])

  if (err) {
    return <MLoadError onRetry={load} />
  }
  if (!dash) return <MLoading rows={4} rowH={60} avatar={false} />

  return (
    <div>
      <div className="flex items-start justify-between gap-3 px-5 pt-1">
        <div>
          <Overline>{now.toLocaleDateString(localeOf(), { weekday: 'long', day: 'numeric', month: 'long' })}</Overline>
          <h1 className="mt-1.5 text-[32px] font-bold leading-[1.05] tracking-[-0.025em]">{t(greetKey(now.getHours()))}</h1>
        </div>
        <button type="button" onClick={() => go('settings')} aria-label={t('m.profile')} className="relative mt-0.5 transition active:scale-90">
          <Avatar initials={initials} hue={0} size={42} className="ring-2 ring-white/25" />
          <span className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full bg-[#ff5c7a] ring-2 ring-[#3446a3]" />
        </button>
      </div>

      <div className="mt-5 px-4">
        <div className="m-glass rounded-[26px] p-4">
          <div className="flex items-start gap-3">
            <MarvinOrb size={38} />
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-medium text-white/60">{t('m.marvin_brief')}</div>
              <p className="mt-1 text-[15px] leading-[1.42] text-white/90">
                {t('m.tasks_n', { count: openToday })} {t('m.meetings_n', { count: todayEvents.length })}
                {mainTask ? `. ${t('m.main_thing', { what: mainTask.title })}` : ''}
              </p>
            </div>
          </div>
          <div className="no-scrollbar -mx-4 mt-3 flex gap-2 overflow-x-auto px-4">
            {/* фразы уходят в ядро — оно русское в любом режиме интерфейса */}   {/* i18n-raw */}
            {[['m.chip_plan', 'план дня'], ['m.chip_debts', 'кто мне должен'], ['m.chip_delay', 'что можно отложить']].map(([k, raw]) => (
              <button
                type="button"
                key={k}
                onClick={() => chatWith(raw)}
                className="shrink-0 rounded-full border border-white/15 bg-white/[0.08] px-3.5 py-2 text-[13px] font-medium text-white/85 transition active:scale-95"
              >
                {t(k)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-3 px-4">
        <button type="button" onClick={() => go('finance')} aria-label={t('m.balance')} className="m-hero holo-border relative block w-full cursor-pointer overflow-hidden rounded-[30px] p-5 text-left transition active:scale-[0.985]">
          <div className="pointer-events-none absolute -right-12 -top-16 h-48 w-48 rounded-full bg-white/20 blur-2xl" />
          <div className="relative flex items-center justify-between">
            <span className="text-[15px] font-semibold">{t('m.balance')}</span>
            <span className="m-tile rounded-full px-3 py-1 text-[12px] font-medium">{t('m.days_fit', { n: fit })}</span>
          </div>
          <BigMoney value={balance} size={54} className="relative mt-3" />
          <div className="relative mt-4 flex h-[22px] items-end gap-[3px]">
            {Array.from({ length: 30 }).map((_, i) => (
              <div key={i} className={i < fit ? 'flex-1 rounded-full bg-white' : 'flex-1 rounded-full bg-white/45'} style={{ height: i < fit ? 22 : 15 }} />
            ))}
          </div>
          <div className="tnum relative mt-1.5 flex justify-between text-[11px] text-white/70">
            <span>{t('m.today')}</span>
            <span>{lowShort || ''}</span>
          </div>
          <div className="relative mt-4 grid grid-cols-3 gap-2">
            {[
              [t('m.per_day'), avgDay],
              [t('m.free'), Number(fin.cashflow?.free ?? fin.safe?.free ?? 0)],
              [lowShort ? t('m.by_date', { date: lowShort }) : t('m.forecast'), Number(dash?.forecast?.low ?? balance)],
            ].map(([l, v]) => (
              <div key={l} className="m-tile min-w-0 rounded-[18px] px-2.5 py-2.5">
                <div className="truncate text-[11.5px] text-white/75">{l}</div>
                <div className="tnum mt-0.5 truncate text-[14.5px] font-semibold" title={money(v)}>{money(v)}</div>
              </div>
            ))}
          </div>
        </button>
      </div>

      <div className="mt-7 px-4">
        <SectionHead title={t('m.today')} action={t('m.all_tasks')} onAction={() => go('tasks')} />
        <Card className="p-2">
          <div className="flex items-center gap-2 px-3 pb-1 pt-2 text-[12px] font-medium text-[#ff9aac]">
            <span className="relative flex h-2 w-2">
              <span className="pulse-ring absolute inset-0 rounded-full bg-[#ff5c7a]" />
              <span className="relative h-2 w-2 rounded-full bg-[#ff5c7a]" />
            </span>
            {nowLine}
            <span className="h-px flex-1 bg-[#ff5c7a]/30" />
          </div>
          {agenda.length === 0 && (
            <MEmpty
              className="px-3"
              compact
              glyph="calendar"
              text={t('m.home_empty')}
              sub={t('m.home_empty_sub')}
              hint={t('m.home_hint')}
            />
          )}
          {agenda.map((a, i) => (
            <div key={a.id} className={`flex items-center gap-3 rounded-[20px] px-3 py-3${i < agenda.length - 1 ? ' border-b border-white/[0.05]' : ''}`}>
              <div className="tnum w-11 shrink-0 text-[13px] font-semibold text-white/80">{hhmm(a.at)}</div>
              {a.type === 'task' ? (
                <TaskCheck
                  size={22}
                  done={!!a.task.done}
                  priority={a.task.priority === 1 ? 'high' : a.task.priority === 3 ? 'low' : 'mid'}
                  onToggle={() => toggleTask(a.task)}
                />
              ) : (
                <span className="h-9 w-[4px] shrink-0 rounded-full bg-[#7d95ff]" style={{ marginInline: 9 }} />
              )}
              <div className="min-w-0 flex-1">
                <div className={`text-[15px] font-medium leading-snug${a.type === 'task' && a.task.done ? ' text-white/40 line-through' : ''}`}>{a.title}</div>
                {a.sub ? <div className="mt-0.5 truncate text-[12.5px] text-white/50">{a.sub}</div> : null}
              </div>
            </div>
          ))}
        </Card>
      </div>

      <div className="mt-4 px-4">
        <Card className="p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[17px] font-semibold">{t('m.cash_title')}</div>
              <div className="tnum mt-1 text-[13px] text-white/55">
                {t('m.pace', { v: money(avgDay) })}
              </div>
            </div>
            <button type="button" onClick={() => go('finance')} aria-label={t('m.open')} className="grid h-9 w-9 place-items-center rounded-full bg-white/[0.07] text-white/70">
              <ArrowUpRight size={17} />
            </button>
          </div>
          <MCashChart past={past} future={fcPts} />
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-white/55">
            <span className="flex items-center gap-1.5"><span className="h-[3px] w-4 rounded-full bg-[#ffd23f]" />{t('m.fact')}</span>
            <span className="flex items-center gap-1.5"><span className="w-4 border-t-2 border-dashed border-[#7d95ff]" />{t('m.forecast')}</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#3ddc97]" />{t('m.income')}</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-[#e6e9ff]" />{t('m.expense')}</span>
          </div>
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2.5 px-4">
        {shortcuts.map((s) => (
          <button type="button" key={s.id} onClick={() => go(s.id)} className="m-glass rounded-[22px] p-3.5 text-left transition active:scale-[0.96]">
            <IconTile icon={s.icon} color={s.color} />
            <div className="mt-3 text-[14px] font-semibold">{s.label}</div>
            <div className="text-[12px] text-white/55">{s.value}</div>
          </button>
        ))}
      </div>
      {toastMsg && (
        <div className="anim-toast fixed bottom-24 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full border border-white/10 bg-[#121a46]/95 py-2.5 pl-4 pr-2.5 shadow-xl backdrop-blur-xl">
          <span className="max-w-[60vw] truncate text-[13.5px]">{toastMsg.text}</span>
          {toastMsg.action && (
            <button
              type="button"
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

/* ───────── график кассы: step-path, жёлтый факт + пунктир-прогноз + линия ноля ───────── */
export function MCashChart({ past = [], future = [] }) {
  const { t } = useI18n()
  const W = 318, H = 170, B = 22
  const vals = [...past.map((p) => p.balance), ...future.map((p) => p.balance)]
  if (!vals.length) return <div className="mt-4 text-[13px] leading-snug text-white/50">{t('m.cash_empty')}</div>
  let min = Math.min(0, ...vals), max = Math.max(0, ...vals)
  if (max - min < 1) { max += 1; min -= 1 }
  const pad = (max - min) * 0.08; min -= pad; max += pad
  const n = Math.max(1, vals.length - 1)
  const x = (i) => (i / n) * W
  const y = (v) => H - B - ((v - min) / (max - min)) * (H - B - 10)
  const step = (pts) => pts.map(([px, py], i) => (i === 0 ? `M${px},${py}` : `H${px} V${py}`)).join(' ')
  const pastPts = past.map((p, i) => [x(i), y(p.balance)])
  const futPts = future.map((p, i) => [x(past.length - 1 + i), y(p.balance)])
  const ups = [], downs = []
  future.forEach((p, i) => {
    const net = (p.events || []).reduce((s, e) => s + (Number(e.amount) || 0), 0)
    if (net > 0) ups.push(i)
    else if (net < 0) downs.push(i)
  })
  const d0 = past[0]?.date ? new Date(past[0].date) : new Date()
  const dT = past.length ? new Date(past[past.length - 1].date) : new Date()
  const dE = future.length ? new Date(future[future.length - 1].date) : dT
  const f = (d) => d.toLocaleDateString(localeOf(), { day: 'numeric', month: 'numeric' })
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-4 h-auto w-full overflow-visible" role="img" aria-label={t('m.cash_title')}>
      <line x1="0" x2={W} y1={y(0)} y2={y(0)} stroke="#ff7a9a" strokeOpacity="0.55" strokeDasharray="3 4" />
      <text x={W} y={y(0) - 6} textAnchor="end" fill="#ff9aac" fontSize="10.5" opacity="0.85">{t('m.zero')}</text>
      {past.length > 0 && <line x1={x(past.length - 1)} x2={x(past.length - 1)} y1="4" y2={H - B} stroke="white" strokeOpacity="0.3" strokeDasharray="2 4" />}
      {futPts.length > 1 && <path d={step(futPts)} fill="none" stroke="#7d95ff" strokeWidth="2" strokeDasharray="5 4" strokeLinejoin="round" />}
      {pastPts.length > 1 && <path d={step(pastPts)} fill="none" stroke="#ffd23f" strokeWidth="2.5" strokeLinejoin="round" />}
      {ups.slice(0, 6).map((i) => (
        <circle key={`u${i}`} cx={futPts[i][0]} cy={futPts[i][1]} r="3.6" fill="#3ddc97" stroke="#10163d" strokeWidth="1.6" />
      ))}
      {downs.slice(0, 6).map((i) => (
        <circle key={`d${i}`} cx={futPts[i][0]} cy={futPts[i][1]} r="3.6" fill="#e6e9ff" stroke="#10163d" strokeWidth="1.6" />
      ))}
      {pastPts.length > 0 && <circle cx={pastPts[pastPts.length - 1][0]} cy={pastPts[pastPts.length - 1][1]} r="5.5" fill="#ffd23f" stroke="#10163d" strokeWidth="2" />}
      {[[0, f(d0)], [past.length - 1, t('m.today')], [n, f(dE)]].map(([i, l], k) => (
        <text key={k} x={x(i)} y={H - 4} textAnchor={k === 0 ? 'start' : k === 2 ? 'end' : 'middle'} fill={k === 1 ? '#fff' : 'rgba(255,255,255,0.45)'} fontSize="10.5" fontWeight={k === 1 ? 600 : 400}>{l}</text>
      ))}
    </svg>
  )
}
