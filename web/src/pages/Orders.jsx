import { useEffect, useMemo, useState } from 'react'
import { Plus, Check, Play, Square, Coffee, Trash2, MessageCircle, Wallet, Clock, ChevronDown, ChevronUp, Pencil } from 'lucide-react'
import { api, money, moneyShort, dayLabel, shortDate, hhmm, plural, toLocalISO } from '../lib/api'
import { Section, Empty, Sheet, Field, Seg, Pills, Money, useToast, PageHead, useLeave, Swipe, ListSkeleton, Confirm, Stat, Num } from '../components/ui'
import { useRefresh } from '../App'

const VIEWS = [['open', 'в работе'], ['unpaid', 'ждут оплаты'], ['all', 'все']]
const STATUS = { new: 'новый', work: 'в работе', review: 'на правках', done: 'сдан', paid: 'оплачен', cancelled: 'отменён' }
const STATUS_TONE = { new: '', work: 'accent', review: 'warn', done: 'pos', paid: 'pos', cancelled: '' }
const NEXT = { new: 'work', work: 'done', review: 'done', done: 'paid' }
const NEXT_LABEL = { new: 'в работу', work: 'сдан', review: 'сдан', done: 'оплачен' }
const ask = (text) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } }))
const hours = (h) => (h >= 1 ? `${Math.round(h * 10) / 10} ч` : h > 0 ? `${Math.round(h * 60)} мин` : '—')

/* Таймер помодоро: одна активная сессия на всю систему (сайт + Telegram + голос). Тикает локально, сверяется по SSE. */
export function useTimer() {
  const [t, setT] = useState(null)
  const [, setNow] = useState(0)
  const load = () => api.timer().then(setT).catch(() => {})
  useEffect(() => {
    load()
    const h = (e) => { if (['timer', 'chat', 'reminder'].includes(e.detail?.kind)) load() }
    window.addEventListener('assistant:event', h)
    const iv = setInterval(() => setNow(Date.now()), 1000)
    return () => { window.removeEventListener('assistant:event', h); clearInterval(iv) }
  }, [])
  const left = t?.active ? Math.max(0, Math.round((new Date(t.ends_at) - Date.now()) / 1000)) : 0
  return { t, left, reload: load }
}
export const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

export default function Orders() {
  const [orders, setOrders] = useState(null)
  const [stats, setStats] = useState(null)
  const [pulse, setPulse] = useState(null)   // задержки оплат + налог за месяц (режим фрилансера)
  const [view, setView] = useState('open')
  const [quick, setQuick] = useState('')
  const [sheet, setSheet] = useState(null)      // null | 'new' | order
  const [pay, setPay] = useState(null)          // order
  const [del, setDel] = useState(null)
  const [openId, setOpenId] = useState(null)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()
  const { t: timer, left } = useTimer()

  const load = () => Promise.all([api.orders(true).then(setOrders), api.orderStats(6).then(setStats), api.pulse().then(setPulse).catch(() => {})]).catch(() => {})
  useEffect(() => { load() }, [tick])

  const all = orders || []
  const list = useMemo(() => {
    if (view === 'open') return all.filter((o) => ['new', 'work', 'review'].includes(o.status))
    if (view === 'unpaid') return all.filter((o) => o.status !== 'cancelled' && o.status !== 'paid' && o.left > 0 && o.status !== 'new')
    return all
  }, [orders, view])
  const openN = all.filter((o) => ['new', 'work', 'review'].includes(o.status)).length
  const unpaid = all.filter((o) => o.status !== 'cancelled' && o.status !== 'new').reduce((s, o) => s + o.left, 0)
  const overdue = all.filter((o) => o.overdue).length

  const addQuick = async (e) => {
    e.preventDefault(); if (!quick.trim()) return
    try { await api.chat(`заказ: ${quick.trim()}`); setQuick(''); load(); bump() } catch (err) { show.err(err) }
  }
  const [leaveCls, leave] = useLeave()
  const setStatus = async (o, status) => { try { await api.updateOrder(o.id, { status }); load(); bump(); if (status === 'paid') show('Заказ оплачен', '', o.title) } catch (e) { show.err(e) } }
  const remove = (o) => leave(o.id, 'leaving', async () => { await api.delOrder(o.id); show('Заказ удалён', '', o.title); load(); bump() })
  const start = async (o, minutes = null) => { try { await api.startTimer(o?.id || null, minutes); load() } catch (e) { show.err(e) } }
  const stop = async () => { try { await api.stopTimer(); load() } catch (e) { show.err(e) } }

  const kicker = overdue ? `${overdue} ${plural(overdue, 'дедлайн горит', 'дедлайна горят', 'дедлайнов горят')}` : openN ? `${openN} ${plural(openN, 'заказ в работе', 'заказа в работе', 'заказов в работе')}` : 'свободен'
  return (
    <div className="space-y-10">
      <PageHead kicker={kicker} title="заказы" idx={openN}
        right={<><Seg value={view} onChange={setView} options={VIEWS} /><button className="btn-primary head-primary" onClick={() => setSheet('new')}><Plus size={15} /> заказ</button></>} />

      <form onSubmit={addQuick} className="composer animate-rise flex items-center gap-2 py-1.5 pl-4 pr-1.5">
        <Plus size={16} className="faint shrink-0" />
        <input value={quick} onChange={(e) => setQuick(e.target.value)} className="h-9 w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]" placeholder="Своими словами: «ролик для Пятёрочки, 25к, до пятницы»…" />
        <button className="btn-primary grid !h-9 !w-9 shrink-0 !rounded-full !p-0" disabled={!quick.trim()} aria-label="Добавить"><Plus size={16} /></button>
      </form>

      {/* таймер + деньги — одна спокойная полоса */}
      <div className="grid grid-cols-1 gap-8 sm:grid-cols-[auto_1fr] sm:items-start sm:gap-12">
        <TimerCard timer={timer} left={left} onStart={() => start(null)} onStop={stop} onBreak={() => api.startTimer(timer?.order_id || null, null, 'break').then(load).catch(show.err)} />
        <div className="grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
          <Stat label="ждут оплаты" value={<Num value={unpaid} fmt={money} />} tone={unpaid ? 'accent' : ''} />
          <Stat label="за этот месяц" value={stats ? <Num value={stats.months.at(-1)?.income || 0} fmt={money} /> : '—'} sub={stats?.months.at(-2) ? `прошлый · ${money(stats.months.at(-2).income)}` : undefined} />
          <Stat label="ставка в час" value={stats?.rate ? money(stats.rate) : '—'} sub={stats?.total_hours ? `${hours(stats.total_hours)} по таймеру` : 'запускайте таймер по заказу'} />
          <Stat label="средний чек" value={stats?.avg_check ? money(stats.avg_check) : '—'} sub={stats?.avg_lead_days ? `~${stats.avg_lead_days} дн. на заказ` : undefined} />
        </div>
      </div>

      {pulse?.enabled && (pulse.late?.length > 0 || pulse.tax?.tax_total > 0) && (
        <div className="animate-rise -mt-4 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[13px]">
          {pulse.late.map((x) => (
            <button key={x.order_id} type="button" className="flex items-center gap-1.5 text-left" onClick={() => setView('unpaid')}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'var(--warn)' }} />
              <span><b className="font-medium">{x.client || x.title}</b><span className="muted"> задерживает {money(x.left)} · {x.days} {plural(x.days, 'день', 'дня', 'дней')}{x.typical_days != null ? ` · обычно за ${x.typical_days}` : ''}</span></span>
            </button>
          ))}
          {pulse.tax?.tax_total > 0 && <span className="muted">налог {pulse.tax.percent} % за месяц ~<b className="num font-medium" style={{ color: 'var(--ink)' }}>{money(pulse.tax.tax_total)}</b>{pulse.tax.tax_expected ? <span className="faint"> (из них {money(pulse.tax.tax_expected)} с ожидаемого)</span> : ''}</span>}
        </div>
      )}

      {!orders ? <ListSkeleton n={4} /> : (
        <Section title={VIEWS.find((v) => v[0] === view)[1]} idx={list.length}>
          <div className="rule stagger">
            {list.length === 0 && (
              view === 'open' ? <Empty glyph="tasks" text="Заказов в работе нет" sub="Как возьмёте — скажите мне, я запомню дедлайн и буду ждать оплату" hint="заказ: монтаж свадьбы для Иванова, 60к, до 30 сентября" />
                : view === 'unpaid' ? <Empty glyph="money" text="Все оплатили" sub="Приятная пустота" />
                  : <Empty glyph="tasks" text="Пока пусто" hint="заказ: ролик для Пятёрочки, 25к, до пятницы" />
            )}
            {list.map((o) => <Row key={o.id} o={o} open={openId === o.id} onOpen={() => setOpenId(openId === o.id ? null : o.id)} onEdit={() => setSheet(o)} onPay={() => setPay(o)}
              onDel={() => setDel(o)} onStatus={setStatus} onStart={() => start(o)} timer={timer} extra={leaveCls(o.id)} />)}
          </div>
        </Section>
      )}

      {stats && (stats.clients.length > 0 || stats.months.some((m) => m.income)) && <StatsBlock stats={stats} />}

      <OrderSheet open={!!sheet} order={sheet && sheet !== 'new' ? sheet : null} onClose={() => setSheet(null)} onDone={(msg) => { setSheet(null); show(msg); load(); bump() }} onErr={show.err} />
      <PaySheet order={pay} onClose={() => setPay(null)} onDone={(r) => { setPay(null); show(r.order.status === 'paid' ? 'Заказ закрыт как оплаченный' : 'Оплата записана в доходы', '', r.order.title); load(); bump() }} onErr={show.err} />
      <Confirm open={!!del} title="Удалить заказ?" text={del ? `«${del.title}». Полученные оплаты останутся в доходах, время по таймеру — тоже.` : ''} danger onOk={() => { remove(del); setDel(null) }} onClose={() => setDel(null)} />
    </div>
  )
}

function TimerCard({ timer, left, onStart, onStop, onBreak }) {
  const active = timer?.active
  const total = active ? timer.planned_min * 60 : 25 * 60
  const pct = active ? 1 - left / total : 0
  const R = 30, C = 2 * Math.PI * R
  return (
    <div className="flex items-center gap-4">
      <div className="relative grid h-[76px] w-[76px] place-items-center">
        <svg width="76" height="76" viewBox="0 0 76 76" className="-rotate-90">
          <circle cx="38" cy="38" r={R} fill="none" stroke="var(--fill-2)" strokeWidth="3" />
          {active && <circle cx="38" cy="38" r={R} fill="none" stroke={timer.kind === 'break' ? 'var(--pos)' : 'var(--accent)'} strokeWidth="3" strokeLinecap="round" strokeDasharray={C} strokeDashoffset={C * (1 - pct)} style={{ transition: 'stroke-dashoffset 1s linear' }} />}
        </svg>
        <div className={`num absolute text-[17px] font-medium tracking-tight ${active && left === 0 ? 'neg' : ''}`}>{active ? mmss(left) : `${String(timer?.focus_min || 25).padStart(2, '0')}:00`}</div>
      </div>
      <div className="min-w-0">
        <div className="label">{active ? (timer.kind === 'break' ? 'перерыв' : 'фокус') : 'помодоро'}</div>
        <div className="mt-1 truncate text-[15px] font-medium">{active ? (timer.order || 'без заказа') : `сегодня ${timer?.today_min || 0} мин · ${timer?.today_sessions || 0} 🍅`}</div>
        <div className="mt-2 flex items-center gap-1.5">
          {active ? (
            <>
              <button className="btn-soft btn-sm" onClick={onStop}><Square size={12} /> стоп</button>
              {timer.kind !== 'break' && <button className="btn-ghost btn-sm" onClick={onBreak}><Coffee size={12} /> перерыв {timer.break_min || 5}</button>}
            </>
          ) : (
            <>
              <button className="btn-soft btn-sm" onClick={onStart}><Play size={12} /> {timer?.focus_min || 25} минут</button>
              {timer?.today_min > 0 && <span className="faint text-[12px]">сегодня {timer.today_min} мин</span>}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Row({ o, open, onOpen, onEdit, onPay, onDel, onStatus, onStart, timer, extra = '' }) {
  const closed = ['paid', 'cancelled'].includes(o.status)
  const running = timer?.active && timer.order_id === o.id && timer.kind === 'focus'
  const dl = o.deadline ? (o.overdue ? `просрочен · ${dayLabel(o.deadline).toLowerCase()}` : o.days_left === 0 ? 'сегодня' : o.days_left === 1 ? 'завтра' : `до ${shortDate(o.deadline).toLowerCase()}`) : null
  return (
    <Swipe onLeft={!closed ? onDel : undefined} onRight={!closed && NEXT[o.status] ? () => onStatus(o, NEXT[o.status]) : undefined} rightLabel={NEXT_LABEL[o.status] || 'готово'}>
      <div className={`row-slide done-fade ${extra} ${closed ? 'opacity-55' : ''}`}>
        <div className="row group cursor-pointer" onClick={onOpen}>
          <span className={`badge shrink-0 ${STATUS_TONE[o.status]}`}>{STATUS[o.status]}</span>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <div className="truncate text-[15px] font-medium">{o.title}</div>
              {o.client && <div className="muted shrink-0 truncate text-[13px]">{o.client}</div>}
            </div>
            <div className={`flex flex-wrap items-center gap-x-1.5 text-[12px] ${o.overdue ? 'neg' : (o.days_left != null && o.days_left <= 2) ? 'warn' : 'muted'}`}>
              {dl && <span className="flex items-center gap-1"><Clock size={11} /> {dl}</span>}
              {o.hours > 0 && <span className={o.pulse?.warn ? 'warn' : 'muted'}>{dl ? '· ' : ''}{hours(o.hours)}{o.pulse?.estimate_h ? ` из ${hours(o.pulse.estimate_h)}` : ''}{o.rate ? ` · ${money(o.rate)}/ч` : ''}</span>}
              {running && <span className="accent">{dl || o.hours ? '· ' : ''}идёт таймер</span>}
            </div>
          </div>
          <div className="num shrink-0 text-right">
            <div className="text-[15px] font-medium">{o.price ? money(o.price) : <span className="faint">без суммы</span>}</div>
            {o.price > 0 && o.paid > 0 && o.left > 0 && <div className="muted text-[11.5px]">осталось {money(o.left)}</div>}
            {o.price > 0 && o.paid === 0 && !closed && o.status !== 'new' && <div className="faint text-[11.5px]">не оплачен</div>}
          </div>
          {!closed && <button className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100 focus:opacity-100" data-tip={running ? 'таймер идёт' : `таймер ${timer?.focus_min || 25} мин`} onClick={(e) => { e.stopPropagation(); if (!running) onStart() }} aria-label="Таймер">{running ? <span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> : <Play size={13} />}</button>}
          <span className="btn-icon !h-7 !w-7 faint">{open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</span>
        </div>
        {open && <Details o={o} onEdit={onEdit} onPay={onPay} onDel={onDel} onStatus={onStatus} onStart={onStart} closed={closed} />}
      </div>
    </Swipe>
  )
}

function Details({ o, onEdit, onPay, onDel, onStatus, onStart, closed }) {
  const [d, setD] = useState(null)
  useEffect(() => { api.order(o.id).then(setD).catch(() => {}) }, [o.id, o.paid, o.hours, o.status])
  return (
    <div className="animate-rise -mt-1 mb-3 ml-[2px] space-y-3 border-l-2 pl-4" style={{ borderColor: 'var(--line)' }}>
      {o.notes && <div className="muted whitespace-pre-wrap text-[13.5px]">{o.notes}</div>}
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-4">
        <div><div className="label">оплачено</div><div className="num mt-0.5">{money(o.paid)}{o.price ? <span className="muted"> из {money(o.price)}</span> : ''}</div></div>
        <div><div className="label">время</div><div className="num mt-0.5">{hours(o.hours)}{o.estimate_h ? <span className="muted"> из {hours(o.estimate_h)} плана</span> : ''}</div></div>
        <div><div className="label">ставка</div><div className={`num mt-0.5 ${o.pulse?.warn ? 'warn' : ''}`}>{o.rate ? `${money(o.rate)}/ч` : '—'}{o.pulse?.planned_rate && o.pulse.planned_rate !== o.rate ? <span className="muted"> · план {money(o.pulse.planned_rate)}</span> : ''}</div></div>
        <div><div className="label">дедлайн</div><div className="mt-0.5">{o.deadline ? `${dayLabel(o.deadline).toLowerCase()}, ${hhmm(o.deadline)}` : '—'}</div></div>
      </div>
      {o.pulse?.warn && <div className="warn text-[12.5px]">заказ съедает на {o.pulse.over_pct} % больше времени, чем планировали — {hours(o.pulse.hours)} из {hours(o.pulse.estimate_h)}</div>}
      {d?.payments?.length > 0 && (
        <div className="text-[12.5px]"><div className="label mb-1">оплаты</div>{d.payments.map((p) => <div key={p.id} className="muted flex justify-between gap-3"><span>{dayLabel(p.date).toLowerCase()} · {p.note || 'оплата'}</span><span className="num pos">+{money(p.amount)}</span></div>)}</div>
      )}
      <div className="flex flex-wrap items-center gap-1.5 pt-1">
        {!closed && NEXT[o.status] && <button className="btn-primary btn-sm" onClick={() => onStatus(o, NEXT[o.status])}><Check size={13} /> {NEXT_LABEL[o.status]}</button>}
        {!closed && o.status === 'work' && <button className="btn-ghost btn-sm" onClick={() => onStatus(o, 'review')}>на правки</button>}
        {o.status !== 'cancelled' && o.left > 0 && <button className="btn-soft btn-sm" onClick={onPay}><Wallet size={13} /> оплата</button>}
        {!closed && <button className="btn-ghost btn-sm" onClick={onStart}><Play size={13} /> таймер</button>}
        <button className="btn-ghost btn-sm" onClick={onEdit}><Pencil size={13} /> изменить</button>
        <button className="btn-ghost btn-sm" onClick={() => ask(`по заказу «${o.title}»: `)}><MessageCircle size={13} /> обсудить</button>
        {!closed && <button className="btn-ghost btn-sm" onClick={() => onStatus(o, 'cancelled')}>отменить</button>}
        <button className="btn-icon !h-7 !w-7 ml-auto" data-tip="удалить" onClick={onDel}><Trash2 size={13} /></button>
      </div>
    </div>
  )
}

function StatsBlock({ stats }) {
  const [more, setMore] = useState(false)
  const max = Math.max(1, ...stats.months.map((m) => m.income))
  const maxF = Math.max(1, ...stats.focus_days.map((d) => d.min))
  return (
    <Section title="как идут дела" hint="доход по месяцам — только оплаты по заказам; часы — по таймеру">
      <div className="grid grid-cols-1 gap-10 lg:grid-cols-2">
        <div>
          <div className="label mb-3">доход по месяцам</div>
          <div className="flex h-[120px] items-end gap-2">
            {stats.months.map((m) => (
              <div key={m.month} className="group flex flex-1 flex-col items-center gap-1.5">
                <div className="num text-[11px] opacity-0 transition group-hover:opacity-100">{m.income ? moneyShort(m.income) : ''}</div>
                <div className="w-full rounded-t-md transition-all duration-700" style={{ height: `${Math.max(2, (m.income / max) * 90)}px`, background: m.month === stats.months.at(-1).month ? 'var(--accent)' : 'var(--fill-2)' }} />
                <div className="faint mono text-[10px]">{m.month.slice(5)}</div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <div className="mb-3 flex items-baseline justify-between"><div className="label">фокус за 2 недели</div><span className="muted text-[12px]">{stats.week_load_h ? `${hours(stats.week_load_h)} за неделю` : 'таймер ещё не запускали'}</span></div>
          <div className="flex h-[120px] items-end gap-1">
            {stats.focus_days.map((d) => (
              <div key={d.date} className="flex flex-1 flex-col items-center gap-1.5" title={`${d.date.slice(8)}.${d.date.slice(5, 7)} · ${d.min} мин`}>
                <div className="w-full rounded-t-md" style={{ height: `${Math.max(2, (d.min / maxF) * 90)}px`, background: d.min ? 'var(--pos)' : 'var(--fill-2)', opacity: d.min ? 0.85 : 1 }} />
                <div className="faint mono text-[9px]">{d.date.slice(8)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {stats.clients.length > 0 && (
        <div className="mt-8">
          <button className="flex items-center gap-2 text-left" onClick={() => setMore((v) => !v)}><span className="label">клиенты · {stats.clients.length}</span>{more ? <ChevronUp size={13} className="faint" /> : <ChevronDown size={13} className="faint" />}</button>
          {more && (
            <div className="rule mt-2 animate-rise">
              {stats.clients.map((c) => (
                <div key={c.client} className="row">
                  <div className="min-w-0 flex-1"><div className="truncate text-[14px] font-medium">{c.client}</div><div className="muted text-[12px]">{c.orders} {plural(c.orders, 'заказ', 'заказа', 'заказов')}{c.open ? ` · ${c.open} в работе` : ''}{c.hours ? ` · ${hours(c.hours)}` : ''}{c.rate ? ` · ${money(c.rate)}/ч` : ''}</div></div>
                  <div className="num text-right"><div className="text-[14px] font-medium">{money(c.paid)}</div>{c.unpaid > 0 && <div className="warn text-[11.5px]">ждём {money(c.unpaid)}</div>}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Section>
  )
}

const blank = { title: '', price: '', client: '', deadline: '', notes: '', estimate_h: '', status: 'work' }
function OrderSheet({ open, order, onClose, onDone, onErr }) {
  const [f, setF] = useState(blank)
  const [clients, setClients] = useState([])
  useEffect(() => {
    if (!open) return
    api.clients().then(setClients).catch(() => {})
    setF(order ? { title: order.title, price: order.price ? String(order.price) : '', client: order.client || '', deadline: order.deadline ? toLocalISO(new Date(order.deadline)).slice(0, 16) : '', notes: order.notes || '', estimate_h: order.estimate_h ? String(order.estimate_h) : '', status: order.status } : blank)
  }, [open, order])
  const submit = async (e) => {
    e.preventDefault()
    const body = { title: f.title.trim(), price: Number(String(f.price).replace(/\s/g, '').replace(',', '.')) || 0, client: f.client.trim() || null, deadline: f.deadline || null, notes: f.notes.trim() || null, estimate_h: Number(f.estimate_h) || 0, status: f.status }
    try {
      if (order) await api.updateOrder(order.id, body); else await api.addOrder(body)
      onDone(order ? 'Заказ обновлён' : 'Заказ добавлен')
    } catch (err) { onErr(err) }
  }
  return (
    <Sheet open={open} onClose={onClose} title={order ? 'заказ' : 'новый заказ'} sub={order ? undefined : 'или скажите ассистенту: «заказ: ролик для Пятёрочки, 25к, до пятницы»'}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="что делаем"><input autoFocus className="input !text-[17px] !font-medium" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required placeholder="Монтаж ролика" /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="сумма"><Money value={f.price} onChange={(v) => setF({ ...f, price: v })} /></Field>
          <Field label="клиент"><input className="input" list="clients-list" value={f.client} onChange={(e) => setF({ ...f, client: e.target.value })} placeholder="Пятёрочка" /><datalist id="clients-list">{clients.map((c) => <option key={c.id} value={c.name} />)}</datalist></Field>
          <Field label="дедлайн"><input type="datetime-local" className="input" value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} /></Field>
          <Field label="план по времени" hint="часов"><input type="number" min="0" step="0.5" className="input num" value={f.estimate_h} onChange={(e) => setF({ ...f, estimate_h: e.target.value })} placeholder="8" /></Field>
        </div>
        {order && <Field label="статус"><Pills value={f.status} onChange={(s) => setF({ ...f, status: s })} options={Object.entries(STATUS)} /></Field>}
        <Field label="заметки"><textarea className="input min-h-[72px]" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="ТЗ, ссылки на исходники, договорённости" /></Field>
        <button className="btn-primary btn-lg w-full">{order ? 'сохранить' : 'добавить'}</button>
      </form>
    </Sheet>
  )
}

function PaySheet({ order, onClose, onDone, onErr }) {
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [accounts, setAccounts] = useState([])
  const [account, setAccount] = useState('')
  useEffect(() => { if (order) { setAmount(order.left ? String(order.left) : ''); setNote(''); api.accounts().then((a) => { setAccounts(a); setAccount(a.find((x) => x.is_main)?.name || a[0]?.name || '') }).catch(() => {}) } }, [order])
  const submit = async (e) => {
    e.preventDefault()
    const n = Number(String(amount).replace(/\s/g, '').replace(',', '.'))
    if (!n || n <= 0) return onErr(new Error('Сумма должна быть больше нуля'))
    try { onDone(await api.payOrder(order.id, n, { note: note || null, account: account || null })) } catch (err) { onErr(err) }
  }
  return (
    <Sheet open={!!order} onClose={onClose} title="оплата по заказу" sub={order ? `«${order.title}»${order.left ? ` · осталось ${money(order.left)}` : ''}` : ''}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="сумма"><Money value={amount} onChange={setAmount} big autoFocus /></Field>
        {order?.left > 0 && <div className="flex flex-wrap gap-1.5">
          {[0.3, 0.5, 1].map((k) => <button type="button" key={k} className="chip" onClick={() => setAmount(String(Math.round(order.left * k)))}>{k === 1 ? 'всё' : `${k * 100}%`} · {money(Math.round(order.left * k))}</button>)}
        </div>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="на счёт"><select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>{accounts.filter((a) => a.kind !== 'debt_only').map((a) => <option key={a.id} value={a.name}>{a.name}</option>)}</select></Field>
          <Field label="комментарий"><input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="аванс / остаток" /></Field>
        </div>
        <div className="muted text-[12.5px]">Запишется как доход «Фриланс» с привязкой к заказу. Полная сумма закроет заказ как оплаченный.</div>
        <button className="btn-primary btn-lg w-full">записать</button>
      </form>
    </Sheet>
  )
}
