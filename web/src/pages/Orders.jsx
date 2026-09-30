import { useEffect, useMemo, useState } from 'react'
import { Plus, Check, Play, Square, Coffee, Trash2, MessageCircle, Wallet, Clock, ChevronDown, ChevronUp, Pencil, Clapperboard, TrendingUp, Coins, Columns3, List, RefreshCw, Bell, User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, money, moneyShort, dayLabel, shortDate, hhmm, plural, toLocalISO } from '../lib/api'
import { Section, Empty, Sheet, Field, DateTimeField, Seg, Pills, Money, useToast, PageHead, useLeave, Swipe, ListSkeleton, Confirm, Num, PageAccent } from '../components/ui'
import { useRefresh } from '../App'
import { usePageAccent } from '../lib/prefs'

const VIEWS = [['open', 'в работе'], ['unpaid', 'ждут оплаты'], ['all', 'все']]
const STATUS = { new: 'новый', work: 'в работе', review: 'на правках', done: 'сдан', paid: 'оплачен', cancelled: 'отменён' }
const STATUS_TONE = { new: '', work: 'accent', review: 'warn', done: 'pos', paid: 'pos', cancelled: '' }
const STATUS_DOT = { new: 'var(--accent)', work: 'var(--accent)', review: 'var(--warn)', done: 'var(--pos)', paid: 'var(--pos)', cancelled: 'var(--ink-3)' }
const NEXT = { new: 'work', work: 'done', review: 'done', done: 'paid' }
const NEXT_LABEL = { new: 'в работу', work: 'сдан', review: 'сдан', done: 'оплачен' }

// CRM-воронка (фаза 4): стадии канбана. Старый status остаётся источником для фильтров/финансов.
const STAGES = [['lead', 'лид'], ['negotiation', 'переговоры'], ['spec', 'ТЗ согласовано'], ['in_work', 'в работе'],
  ['revisions', 'на правках'], ['delivered', 'сдан'], ['awaiting_payment', 'ждёт оплаты'], ['paid', 'оплачен'], ['lost', 'потерян']]
const STAGE_LABEL = Object.fromEntries(STAGES)
const STAGE_TONE = { lead: '', negotiation: 'accent', spec: 'accent', in_work: 'accent', revisions: 'warn', delivered: 'pos', awaiting_payment: 'warn', paid: 'pos', lost: '' }
const STATUS_STAGE = { new: 'lead', work: 'in_work', review: 'revisions', done: 'delivered', paid: 'paid', cancelled: 'lost' }
const stageOf = (o) => (o && o.stage && STAGE_LABEL[o.stage] ? o.stage : STATUS_STAGE[o?.status] || 'lead')
const LOST_STAGES = ['lost']
const ask = (text) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } }))
const hours = (h) => (h >= 1 ? `${Math.round(h * 10) / 10} ч` : h > 0 ? `${Math.round(h * 60)} мин` : '—')

/* Мягкая карточка строки: нейтральная тень, на hover — чуть сильнее (и подъём через hover:-translate-y-px) */
const CARD_SHADOW = 'shadow-[inset_0_0_0_1px_var(--line),0_16px_34px_-24px_rgba(16,17,20,0.35)] hover:shadow-[inset_0_0_0_1px_var(--line),0_22px_42px_-24px_rgba(16,17,20,0.5)]'

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
  const pageAcc = usePageAccent('orders')
  const [stats, setStats] = useState(null)
  const [pulse, setPulse] = useState(null)   // задержки оплат + налог за месяц (режим фрилансера)
  const [view, setView] = useState('open')
  const [layout, setLayout] = useState(() => (typeof localStorage !== 'undefined' && localStorage.getItem('orders.layout')) || 'list')
  const [quick, setQuick] = useState('')
  const [sheet, setSheet] = useState(null)      // null | 'new' | order
  const [card, setCard] = useState(null)        // CRM-карточка заказа (rich)
  const [personCard, setPersonCard] = useState(null)  // CRM-карточка клиента
  const [pay, setPay] = useState(null)          // order
  const [del, setDel] = useState(null)
  const [openId, setOpenId] = useState(null)
  const [followups, setFollowups] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()
  const { t: timer, left } = useTimer()

  const load = () => Promise.all([
    api.orders(true).then(setOrders), api.orderStats(6).then(setStats), api.pulse().then(setPulse).catch(() => {}),
    api.crmFollowups().then(setFollowups).catch(() => {}), api.crmAnalytics(6).then(setAnalytics).catch(() => {}),
  ]).catch(() => {})
  useEffect(() => { load() }, [tick])
  useEffect(() => { try { localStorage.setItem('orders.layout', layout) } catch { /* ignore */ } }, [layout])

  const all = orders || []
  const list = useMemo(() => {
    if (view === 'open') return all.filter((o) => ['new', 'work', 'review'].includes(o.status))
    if (view === 'unpaid') return all.filter((o) => o.status !== 'cancelled' && o.status !== 'paid' && o.left > 0 && o.status !== 'new')
    return all
  }, [orders, view])
  const openN = all.filter((o) => ['new', 'work', 'review'].includes(o.status)).length
  const unpaid = all.filter((o) => ['work', 'review', 'done'].includes(o.status)).reduce((s, o) => s + o.left, 0)
  const overdue = all.filter((o) => o.overdue).length

  const addQuick = async (e) => {
    e.preventDefault(); if (!quick.trim()) return
    try { await api.chat(`заказ: ${quick.trim()}`); setQuick(''); load(); bump() } catch (err) { show.err(err) }
  }
  const [leaveCls, leave] = useLeave()
  const setStatus = async (o, status) => {
    if (status === 'paid' && o.left > 0) return setPay(o)   // деньги не записаны — сначала оплата, полная сумма сама закроет заказ
    try { await api.updateOrder(o.id, { status }); load(); bump(); if (status === 'paid') show('Заказ оплачен', '', o.title) } catch (e) { show.err(e) }
  }
  // перетаскивание по канбану: стадия меняется через CRM (status синхронизируется на бэке)
  const setStage = async (o, stage) => {
    if (stage === stageOf(o)) return
    if (stage === 'paid' && o.left > 0) return setPay(o)
    try { await api.crmSetStage(o.id, stage); show(`Стадия: ${STAGE_LABEL[stage]}`, '', o.title); load(); bump() } catch (e) { show.err(e) }
  }
  const openCard = (o) => setCard(o.id)
  const scanFollowups = async () => { try { const r = await api.crmScanFollowups(); await load(); show('Напоминания обновлены', r.created?.length ? `новых: ${r.created.length}` : 'новых нет') } catch (e) { show.err(e) } }
  const remove = (o) => leave(o.id, 'leaving', async () => { await api.delOrder(o.id); show('Заказ удалён', '', o.title); load(); bump() })
  const start = async (o, minutes = null) => { try { await api.startTimer(o?.id || null, minutes); load() } catch (e) { show.err(e) } }
  const stop = async () => { try { await api.stopTimer(); load() } catch (e) { show.err(e) } }

  const kicker = overdue ? `${overdue} ${plural(overdue, 'дедлайн горит', 'дедлайна горят', 'дедлайнов горят')}` : openN ? `${openN} ${plural(openN, 'заказ в работе', 'заказа в работе', 'заказов в работе')}` : 'свободен'
  const month = stats?.months?.at(-1)?.income || 0
  const prevMonth = stats?.months?.at(-2)
  return (
    <div className="bento-page space-y-8 pt-4" style={{ ...pageAcc.style, '--acc2': 'color-mix(in srgb, var(--acc) 55%, #8a5cff)' }}>
      <PageHead kicker={kicker} title="заказы" idx={openN}
        right={<>
          <Seg value={layout} onChange={setLayout} options={[['list', 'список'], ['board', 'канбан']]} />
          <Seg value={view} onChange={setView} options={VIEWS} />
          <PageAccent page="orders" />
          <button className="btn-primary head-primary" onClick={() => setSheet('new')}><Plus size={15} /> заказ</button>
        </>} />

      <form onSubmit={addQuick} className="composer animate-rise flex items-center gap-2 py-1.5 pl-4 pr-1.5">
        <Plus size={16} className="faint shrink-0" />
        <input value={quick} onChange={(e) => setQuick(e.target.value)} className="h-9 w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]" placeholder="Своими словами: «ролик для Пятёрочки, 25к, до пятницы»…" />
        <button className="btn-primary grid !h-9 !w-9 shrink-0 !rounded-full !p-0" disabled={!quick.trim()} aria-label="Добавить"><Plus size={16} /></button>
      </form>

      {/* сводка: таймер + градиентные hero-плитки в одной bento-сетке */}
      <div className="bento" style={{ marginTop: 26 }}>
        <section className="c s4 flex items-center" style={{ borderRadius: 26 }}>
          <TimerCard timer={timer} left={left} onStart={() => start(null)} onStop={stop} onBreak={() => api.startTimer(timer?.order_id || null, null, 'break').then(load).catch(show.err)} />
        </section>
        <Tile span="s4" glow="color-mix(in srgb, var(--acc) 60%, transparent)" gradient="linear-gradient(135deg, var(--acc) 0%, var(--acc2) 100%)" ink="var(--accent-ink)" icon={<Play size={16} />}
          label="в работе" value={<Num value={openN} />}
          sub={overdue ? `${overdue} ${plural(overdue, 'дедлайн горит', 'дедлайна горят', 'дедлайнов горят')}` : 'всё под контролем'} />
        <Tile span="s4" glow="rgba(255,59,92,0.5)" gradient="linear-gradient(135deg,#ff3b5c 0%,#ff5f3b 55%,#ff9f0a 100%)" icon={<Wallet size={16} />}
          label="ждут оплаты" value={<Num value={unpaid} fmt={money} />} onClick={() => setView('unpaid')} tip={unpaid ? 'показать, кто не заплатил' : undefined}
          sub={unpaid ? 'нажмите, чтобы найти должников' : 'все рассчитались'} />
        <Tile span="s4" glow="rgba(25,179,74,0.5)" gradient="linear-gradient(135deg,#19b34a 0%,#12b08a 55%,#10b3a3 100%)" icon={<TrendingUp size={16} />}
          label="за этот месяц" value={stats ? <Num value={month} fmt={money} /> : '—'}
          sub={prevMonth ? `прошлый · ${money(prevMonth.income)}` : 'первый месяц в работе'} />
        <Tile span="s4" ink="#2a2470" glow="rgba(116,92,255,0.28)" gradient="linear-gradient(140deg,#eef0ff 0%,#ddd6ff 100%)" icon={<Clock size={16} />}
          label="ставка в час" value={stats?.rate ? money(stats.rate) : '—'}
          sub={stats?.total_hours ? `${hours(stats.total_hours)} по таймеру` : 'запускайте таймер по заказу'} />
        <Tile span="s4" ink="#0f5a2b" glow="rgba(25,179,74,0.26)" gradient="linear-gradient(140deg,#e9f8ef 0%,#d2f1e6 100%)" icon={<Coins size={16} />}
          label="средний чек" value={stats?.avg_check ? money(stats.avg_check) : '—'}
          sub={stats?.avg_lead_days ? `~${stats.avg_lead_days} дн. на заказ` : 'по закрытым заказам'} />
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

      {followups.length > 0 && (
        <div className="animate-rise -mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px]">
          <span className="muted flex items-center gap-1.5"><Bell size={13} /> follow-up:</span>
          {followups.slice(0, 5).map((f) => (
            <button key={f.id} type="button" className="flex items-center gap-1.5 text-left" onClick={() => f.order_id && openCard({ id: f.order_id })}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: f.kind === 'overdue' ? 'var(--neg)' : 'var(--warn)' }} />
              <span className="truncate max-w-[280px]">{f.text}</span>
            </button>
          ))}
          <button type="button" className="btn-ghost btn-sm" onClick={scanFollowups}><RefreshCw size={12} /> обновить</button>
        </div>
      )}

      {!orders ? <ListSkeleton n={4} /> : layout === 'board' ? (
        <Section title="канбан" idx={list.length}
          hint="перетаскивайте карточки между колонками или открывайте их с изменениями правок, оплат, чек-листа и ленты. На телефоне переключатель «список» удобнее.">
          <Board orders={list} timer={timer} onCard={openCard} onStage={setStage} onStart={start} />
        </Section>
      ) : (
        <Section title={VIEWS.find((v) => v[0] === view)[1]} idx={list.length}
          hint="как закрыть заказ: кнопка со статусом справа в строке, либо раскройте заказ (стрелка) — там «сдан», оплата и удаление. На телефоне — свайп вправо: следующий статус, влево: удалить.">
          <div className="stagger space-y-2.5">
            {list.length === 0 && (
              view === 'open' ? <Empty glyph="tasks" text="Заказов в работе нет" sub="Как возьмёте — скажите мне, я запомню дедлайн и буду ждать оплату" hint="заказ: монтаж свадьбы для Иванова, 60к, до 30 сентября" />
                : view === 'unpaid' ? <Empty glyph="money" text="Все оплатили" sub="Приятная пустота" />
                  : <Empty glyph="tasks" text="Пока пусто" hint="заказ: ролик для Пятёрочки, 25к, до пятницы" />
            )}
            {list.map((o) => <Row key={o.id} o={o} open={openId === o.id} onOpen={() => setOpenId(openId === o.id ? null : o.id)} onEdit={() => setSheet(o)} onPay={() => setPay(o)}
              onDel={() => setDel(o)} onStatus={setStatus} onStart={() => start(o)} onCard={() => openCard(o)} timer={timer} extra={leaveCls(o.id)} />)}
          </div>
        </Section>
      )}

      {stats && (stats.clients.length > 0 || stats.months.some((m) => m.income)) && <StatsBlock stats={stats} onUnpaid={() => { setView('unpaid'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />}

      <OrderSheet open={!!sheet} order={sheet && sheet !== 'new' ? sheet : null} onClose={() => setSheet(null)} onDone={(msg) => { setSheet(null); show(msg); load(); bump() }} onErr={show.err} />
      <PaySheet order={pay} onClose={() => setPay(null)} onJustClose={async (o) => { setPay(null); try { await api.updateOrder(o.id, { status: 'paid' }); show('Заказ закрыт', 'без записи в доходы', o.title); load(); bump() } catch (e) { show.err(e) } }} onDone={(r) => { setPay(null); show(r.order.status === 'paid' ? 'Заказ закрыт как оплаченный' : 'Оплата записана в доходы', '', r.order.title); load(); bump() }} onErr={show.err} />
      <Confirm open={!!del} title="Удалить заказ?" text={del ? `«${del.title}». Полученные оплаты останутся в доходах, время по таймеру — тоже.` : ''} danger onOk={() => { remove(del); setDel(null) }} onClose={() => setDel(null)} />

      <CrmOrderSheet oid={card} onClose={() => setCard(null)} onClient={(cid) => { setCard(null); setPersonCard(cid) }}
        onChanged={() => { load(); bump() }} onErr={show.err} />
      <ClientCardSheet cid={personCard} onClose={() => setPersonCard(null)} onCard={(oid) => { setPersonCard(null); setCard(oid) }} />
      {analytics && analytics.clients?.length > 0 && <AnalyticsBlock a={analytics} />}
    </div>
  )
}

/* Градиентная hero-плитка сводки: крупная цифра, мелкая подпись, мягкая цветная тень */
function Tile({ span = 's4', gradient, ink = '#ffffff', glow = 'rgba(16,17,20,0.5)', icon, label, value, sub, onClick, tip }) {
  const inner = (
    <>
      {icon && <span className="pointer-events-none absolute right-5 top-5 opacity-70" aria-hidden>{icon}</span>}
      <div className="label" style={{ color: 'inherit', opacity: 0.72 }}>{label}</div>
      <div className="num mt-3 text-[32px] font-medium leading-none tracking-[-0.045em] sm:text-[38px]">{value}</div>
      {sub && <div className="mt-2 max-w-[94%] text-[12.5px] leading-snug" style={{ opacity: 0.82 }}>{sub}</div>}
    </>
  )
  const style = { background: gradient, color: ink, borderRadius: 26, padding: '22px 24px', minHeight: 132, overflow: 'visible', boxShadow: `inset 0 1px 0 rgba(255,255,255,0.35), 0 18px 40px -22px ${glow}` }
  return onClick
    ? <button type="button" onClick={onClick} data-tip={tip} className={`c ${span} relative block w-full text-left transition duration-300 hover:-translate-y-0.5`} style={style}>{inner}</button>
    : <section className={`c ${span} relative block`} style={style}>{inner}</section>
}

function TimerCard({ timer, left, onStart, onStop, onBreak }) {
  const active = timer?.active
  const total = active ? timer.planned_min * 60 : 25 * 60
  const pct = active ? 1 - left / total : 0
  const R = 30, C = 2 * Math.PI * R
  return (
    <div className="flex w-full items-center gap-4">
      <div className="relative grid h-[76px] w-[76px] shrink-0 place-items-center">
        <svg width="76" height="76" viewBox="0 0 76 76" className="-rotate-90">
          <circle cx="38" cy="38" r={R} fill="none" stroke="var(--fill-2)" strokeWidth="3" />
          {active && <circle cx="38" cy="38" r={R} fill="none" stroke={timer.kind === 'break' ? 'var(--pos)' : 'var(--accent)'} strokeWidth="3" strokeLinecap="round" strokeDasharray={C} strokeDashoffset={C * (1 - pct)} style={{ transition: 'stroke-dashoffset 1s linear' }} />}
        </svg>
        <div className={`num absolute text-[17px] font-medium tracking-tight ${active && left === 0 ? 'neg' : ''}`}>{active ? mmss(left) : `${String(timer?.focus_min || 25).padStart(2, '0')}:00`}</div>
      </div>
      <div className="min-w-0">
        <div className="label">{active ? (timer.kind === 'break' ? 'перерыв' : 'фокус') : 'помодоро'}</div>
        <div className="mt-1 truncate text-[15px] font-medium">{active ? (timer.order || 'без заказа') : (timer?.today_sessions ? `сегодня ${timer.today_min || 0} мин · ${timer.today_sessions} ${plural(timer.today_sessions, 'помидор', 'помидора', 'помидоров')}` : 'сегодня ещё не садились')}</div>
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

function Row({ o, open, onOpen, onEdit, onPay, onDel, onStatus, onStart, onCard, timer, extra = '' }) {
  const closed = ['paid', 'cancelled'].includes(o.status)
  const running = timer?.active && timer.order_id === o.id && timer.kind === 'focus'
  const dl = o.deadline ? (o.overdue ? `просрочен · ${dayLabel(o.deadline).toLowerCase()}` : o.past_due ? `срок был ${shortDate(o.deadline).toLowerCase()}` : o.days_left === 0 ? 'сегодня' : o.days_left === 1 ? 'завтра' : `до ${shortDate(o.deadline).toLowerCase()}`) : null
  const pct = o.price > 0 ? Math.min(100, Math.round((o.paid / o.price) * 100)) : 0
  return (
    <Swipe onLeft={!closed ? onDel : undefined} onRight={!closed && NEXT[o.status] ? () => onStatus(o, NEXT[o.status]) : undefined} rightLabel={NEXT_LABEL[o.status] || 'готово'}>
      <div className={`row-slide ${extra} ${closed ? 'opacity-55' : ''}`}>
        <div className={`group relative cursor-pointer px-4 py-3.5 transition duration-300 hover:-translate-y-px ${CARD_SHADOW}`} style={{ background: o.overdue ? 'var(--neg-soft)' : 'var(--sf)', borderRadius: 22, ...(o.overdue ? { boxShadow: 'inset 0 0 0 1.5px var(--neg)' } : null) }} onClick={onOpen}>
          <div className="relative flex items-center gap-3.5 pl-1">
            <span className="absolute -left-4 bottom-1 top-1 w-1 rounded-full" style={{ background: o.overdue ? 'var(--neg)' : STATUS_DOT[o.status] }} aria-hidden />
            <span className={`badge !hidden shrink-0 sm:!inline-flex ${STATUS_TONE[o.status]}`}>{STATUS[o.status]}</span>
            <span className="h-2 w-2 shrink-0 rounded-full sm:hidden" style={{ background: STATUS_DOT[o.status] }} aria-label={STATUS[o.status]} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-col sm:flex-row sm:items-baseline sm:gap-2">
                <div className="min-w-0 truncate text-[15px] font-medium">{o.title}</div>
                {o.client && <div className="muted min-w-0 truncate text-[12.5px] sm:shrink-0 sm:text-[13px]">{o.client}</div>}
              </div>
              <div className={`flex flex-wrap items-center gap-x-1.5 text-[12px] ${o.overdue ? 'neg' : (!o.past_due && o.days_left != null && o.days_left <= 2) ? 'warn' : 'muted'}`}>
                {dl && <span className="flex items-center gap-1"><Clock size={11} /> {dl}</span>}
                {o.hours > 0 && <span className={o.pulse?.warn ? 'warn' : 'muted'}>{dl ? '· ' : ''}{hours(o.hours)}{o.pulse?.estimate_h ? ` из ${hours(o.pulse.estimate_h)}` : ''}{o.rate ? ` · ${money(o.rate)}/ч` : ''}</span>}
                {running && <span className="accent">{dl || o.hours ? '· ' : ''}идёт таймер</span>}
              </div>
              {o.price > 0 && (
                <div className="mt-2 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
                    <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, var(--acc), var(--acc2))' }} />
                  </div>
                  <span className="num faint shrink-0 text-[10.5px]">{pct}%</span>
                </div>
              )}
            </div>
            <div className="num shrink-0 text-right">
              <div className="text-[15px] font-medium">{o.price ? money(o.price) : <span className="faint">без суммы</span>}</div>
              {o.price > 0 && o.paid > 0 && o.left > 0 && <div className="muted text-[11.5px]">осталось {money(o.left)}</div>}
              {o.price > 0 && o.paid === 0 && !closed && o.status !== 'new' && <div className="faint text-[11.5px]">не оплачен</div>}
            </div>
            {!closed && NEXT[o.status] && (
              <button className="btn-soft btn-sm !h-7 shrink-0 hidden sm:inline-flex" title={`перевести в статус «${STATUS[NEXT[o.status]]}»`} onClick={(e) => { e.stopPropagation(); onStatus(o, NEXT[o.status]) }}>
                <Check size={12} /> {NEXT_LABEL[o.status]}
              </button>
            )}
            {!closed && <button className="btn-icon !hidden !h-7 !w-7 opacity-0 transition group-hover:opacity-100 focus:opacity-100 sm:!inline-flex" data-tip={running ? 'таймер идёт' : `таймер ${timer?.focus_min || 25} мин`} onClick={(e) => { e.stopPropagation(); if (!running) onStart() }} aria-label="Таймер">{running ? <span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> : <Play size={13} />}</button>}
            <span className="btn-icon !h-7 !w-7 faint">{open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</span>
          </div>
          {open && <Details o={o} onEdit={onEdit} onPay={onPay} onDel={onDel} onStatus={onStatus} onStart={onStart} onCard={onCard} closed={closed} />}
        </div>
      </div>
    </Swipe>
  )
}

function Details({ o, onEdit, onPay, onDel, onStatus, onStart, onCard, closed }) {
  const [d, setD] = useState(null)
  const [manualMin, setManualMin] = useState('')
  const [manualNote, setManualNote] = useState('')
  const [manualBusy, setManualBusy] = useState(false)
  const [manualMsg, setManualMsg] = useState('')
  const [screenProjects, setScreenProjects] = useState([])
  useEffect(() => { api.order(o.id).then(setD).catch(() => {}); api.screen(1).then((r) => setScreenProjects(r.projects || [])).catch(() => setScreenProjects([])) }, [o.id, o.paid, o.hours, o.status])
  const addManual = async () => {
    const minutes = Number(manualMin)
    if (!Number.isFinite(minutes) || minutes < 1) { setManualMsg('Укажи минуты'); return }
    setManualBusy(true); setManualMsg('')
    try {
      await api.addOrderTime(o.id, Math.round(minutes), { note: manualNote.trim() || 'ручной учёт' })
      setManualMin(''); setManualNote(''); setManualMsg('Время добавлено')
      const fresh = await api.order(o.id); setD(fresh)
    } catch (e) { setManualMsg(e.message || 'Не удалось сохранить') } finally { setManualBusy(false) }
  }
  return (
    <div className="animate-rise mt-3 space-y-3 rounded-2xl p-3.5 sm:p-4" style={{ background: 'var(--sf2)' }}>
      {o.notes && <div className="muted whitespace-pre-wrap text-[13.5px]">{o.notes}</div>}
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-4">
        <div><div className="label">оплачено</div><div className="num mt-0.5">{money(o.paid)}{o.price ? <span className="muted"> из {money(o.price)}</span> : ''}</div></div>
        <div><div className="label">время</div><div className="num mt-0.5">{hours(o.hours)}{o.estimate_h ? <span className="muted"> из {hours(o.estimate_h)} плана</span> : ''}</div></div>
        <div><div className="label">ставка</div><div className={`num mt-0.5 ${o.pulse?.warn ? 'warn' : ''}`}>{o.rate ? `${money(o.rate)}/ч` : '—'}{o.pulse?.planned_rate && o.pulse.planned_rate !== o.rate ? <span className="muted"> · план {money(o.pulse.planned_rate)}</span> : ''}</div></div>
        <div><div className="label">дедлайн</div><div className="mt-0.5">{o.deadline ? `${dayLabel(o.deadline).toLowerCase()}, ${hhmm(o.deadline)}` : '—'}</div></div>
      </div>
      {o.pulse?.warn && <div className="warn text-[12.5px]">заказ съедает на {o.pulse.over_pct} % больше времени, чем планировали — {hours(o.pulse.hours)} из {hours(o.pulse.estimate_h)}</div>}
      <div className="rounded-xl border hair p-3" style={{ background: 'var(--sf)' }}>
        <div className="label mb-2">добавить потраченное время</div>
        <div className="flex flex-wrap items-center gap-2">
          <input className="input !h-8 !w-24 num" type="number" min="1" max="10080" placeholder="минуты" value={manualMin} onChange={(e) => setManualMin(e.target.value)} aria-label="Потраченные минуты" />
          <input className="input !h-8 min-w-[160px] flex-1" placeholder="что делал (необязательно)" value={manualNote} onChange={(e) => setManualNote(e.target.value)} aria-label="Комментарий к времени" />
          <button className="btn-soft btn-sm" disabled={manualBusy} onClick={addManual}>{manualBusy ? 'сохраняю…' : 'добавить'}</button>
        </div>
        {manualMsg && <div className="muted mt-1 text-[12px]">{manualMsg}</div>}
      </div>
      {screenProjects.length > 0 && <div className="rounded-xl border hair p-3" style={{ background: 'var(--sf)' }}>
        <div className="label mb-2">найдено за ПК сегодня</div>
        <div className="space-y-1.5">
          {screenProjects.map((x) => <div key={`${x.app}-${x.project}`} className="flex items-center justify-between gap-3 text-[12.5px]">
            <span className="min-w-0 truncate"><b>{x.app}</b> · {x.project} · {hours(x.minutes / 60)}</span>
            <button className="btn-ghost btn-sm shrink-0" onClick={async () => { try { await api.addOrderScreenTime(o.id, x); setScreenProjects((p) => p.filter((q) => q !== x)); const fresh = await api.order(o.id); setD(fresh) } catch (e) { setManualMsg(e.message || 'Не удалось добавить') } }}>добавить</button>
          </div>)}
        </div>
      </div>}
      {d?.payments?.length > 0 && (
        <div className="text-[12.5px]"><div className="label mb-1">оплаты</div>{d.payments.map((p) => <div key={p.id} className="muted flex justify-between gap-3"><span>{dayLabel(p.date).toLowerCase()} · {p.note || 'оплата'}</span><span className="num pos">+{money(p.amount)}</span></div>)}</div>
      )}
      <div className="flex flex-wrap items-center gap-1.5 pt-1">
        {!closed && NEXT[o.status] && <button className="btn-primary btn-sm" onClick={() => onStatus(o, NEXT[o.status])}><Check size={13} /> {NEXT_LABEL[o.status]}</button>}
        {!closed && o.status === 'work' && <button className="btn-ghost btn-sm" onClick={() => onStatus(o, 'review')}>на правки</button>}
        {o.status !== 'cancelled' && o.left > 0 && <button className="btn-soft btn-sm" onClick={onPay}><Wallet size={13} /> оплата</button>}
        {!closed && <button className="btn-ghost btn-sm" onClick={onStart}><Play size={13} /> таймер</button>}
        {onCard && <button className="btn-soft btn-sm" onClick={onCard}><Columns3 size={13} /> карточка</button>}
        <button className="btn-ghost btn-sm" onClick={onEdit}><Pencil size={13} /> изменить</button>
        <button className="btn-ghost btn-sm" onClick={() => ask(`по заказу «${o.title}»: `)}><MessageCircle size={13} /> обсудить</button>
        <BoardButton o={o} />
        {!closed && <button className="btn-ghost btn-sm" onClick={() => onStatus(o, 'cancelled')}>отменить</button>}
        <button className="btn-icon !h-7 !w-7 ml-auto" data-tip="удалить" onClick={onDel}><Trash2 size={13} /></button>
      </div>
    </div>
  )
}

/* Канбан CRM: нативный HTML5 drag&drop, новых зависимостей нет */
function Board({ orders, onCard, onStage }) {
  const [drag, setDrag] = useState(null)
  const [over, setOver] = useState(null)
  const cols = useMemo(() => {
    const m = {}
    STAGES.forEach(([k]) => { m[k] = [] })
    orders.forEach((o) => { (m[stageOf(o)] || (m[stageOf(o)] = [])).push(o) })
    return m
  }, [orders])
  return (
    <div className="overflow-x-auto pb-3">
      <div className="flex gap-3" style={{ minWidth: 'max-content' }}>
        {STAGES.map(([k, label]) => (
          <div key={k} className="w-[258px] shrink-0"
            onDragOver={(e) => { e.preventDefault(); setOver(k) }}
            onDragLeave={() => setOver((x) => (x === k ? null : x))}
            onDrop={(e) => { e.preventDefault(); const d = drag; setOver(null); setDrag(null); if (d) onStage(d, k) }}>
            <div className="mb-2 flex items-center justify-between rounded-xl px-3 py-2" style={{ background: 'var(--sf2)', outline: over === k ? '2px solid var(--acc)' : 'none' }}>
              <span className="text-[12.5px] font-medium">{label}</span>
              <span className="num faint text-[11px]">{cols[k].length}</span>
            </div>
            <div className="space-y-2" style={{ minHeight: 56 }}>
              {cols[k].map((o) => (
                <div key={o.id} draggable
                  onDragStart={(e) => { try { e.dataTransfer.setData('text/plain', String(o.id)) } catch { /* ignore */ } e.dataTransfer.effectAllowed = 'move'; setDrag(o) }}
                  onDragEnd={() => { setDrag(null); setOver(null) }}
                  onClick={() => onCard(o)}
                  className={`cursor-grab rounded-2xl px-3 py-2.5 transition active:cursor-grabbing ${drag?.id === o.id ? 'opacity-50' : ''}`}
                  style={{ background: o.overdue ? 'var(--neg-soft)' : 'var(--sf)', boxShadow: 'inset 0 0 0 1px var(--line)', borderRadius: 18 }}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-[13.5px] font-medium">{o.title}</div>
                      {o.client && <div className="muted truncate text-[12px]">{o.client}</div>}
                    </div>
                    {o.deadline && <span className={`shrink-0 text-[10.5px] ${o.overdue ? 'neg' : 'faint'}`}>{shortDate(o.deadline)}</span>}
                  </div>
                  <div className="mt-1.5 flex items-center justify-between text-[11.5px]">
                    <span className="muted num">{o.price ? money(o.price) : '—'}</span>
                    {o.left > 0 && o.status !== 'new' && <span className="faint num">долг {money(o.left)}</span>}
                    {o.revisions > 0 && <span className="warn">правки ×{o.revisions}</span>}
                  </div>
                  {o.price > 0 && (
                    <div className="mt-1.5 h-1 overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
                      <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.round((o.paid / o.price) * 100))}%`, background: 'linear-gradient(90deg, var(--acc), var(--acc2))' }} />
                    </div>
                  )}
                </div>
              ))}
              {cols[k].length === 0 && <div className="rounded-xl px-3 py-4 text-center faint text-[11.5px]" style={{ border: '1px dashed var(--line)' }}>пусто</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* Карточка заказа CRM: стадии, деньги, правки, чек-лист, комментарии, лента, шаблоны */
function CrmOrderSheet({ oid, onClose, onClient, onChanged, onErr }) {
  const [d, setD] = useState(null)
  const [comment, setComment] = useState('')
  const [check, setCheck] = useState('')
  const [tpl, setTpl] = useState(null)
  const [lost, setLost] = useState(null)
  const load = () => { if (oid) api.crmOrderCard(oid).then(setD).catch(() => {}); else setD(null) }
  useEffect(() => { setD(null); setTpl(null); setLost(null); load() }, [oid])
  const act = async (fn) => { try { await fn(); load(); onChanged?.() } catch (e) { onErr?.(e) } }
  const addComment = async () => { const t = comment.trim(); if (!t) return; setComment(''); await act(() => api.crmComment(oid, t, d?.client_id)) }
  const addCheck = async (e) => { e.preventDefault(); const t = check.trim(); if (!t) return; setCheck(''); await act(() => api.crmAddCheck(oid, t)) }
  const useTpl = async (name) => { const t = tpl?.[name]; if (t) window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: t } })) }
  return (
    <Sheet open={!!oid} onClose={onClose} wide title={d?.title || 'заказ'} sub={d ? `${d.client || 'без клиента'}${d.deadline ? ` · до ${shortDate(d.deadline)}` : ''}` : ''}>
      {!d ? <div className="muted text-[13px]">загружаю…</div> : (
        <div className="space-y-4 text-[13px]">
          <div className="flex flex-wrap items-center gap-1.5">
            {STAGES.map(([k, label]) => (
              <button key={k} className={`chip ${stageOf(d) === k ? 'on' : ''}`} disabled={!!lost}
                onClick={() => (k === 'lost' ? setLost('') : act(() => api.crmSetStage(oid, k)))}>{label}{d.revisions > 0 && k === 'revisions' ? ` ×${d.revisions}` : ''}</button>
            ))}
          </div>
          {lost !== null && (
            <div className="flex flex-wrap items-center gap-2">
              <input className="input !h-8 min-w-[200px] flex-1" placeholder="причина потери" value={lost} onChange={(e) => setLost(e.target.value)} />
              <button className="btn-danger btn-sm" onClick={() => act(() => api.crmSetStage(oid, 'lost', lost.trim() || null))}>потерян</button>
              <button className="btn-ghost btn-sm" onClick={() => setLost(null)}>отмена</button>
            </div>
          )}

          <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
            <div><div className="label">предоплата</div><div className="num mt-0.5">{money(d.prepaid || 0)}</div></div>
            <div><div className="label">остаток</div><div className={`num mt-0.5 ${d.left > 0 ? 'warn' : 'pos'}`}>{money(d.remaining || 0)}</div></div>
            <div><div className="label">оплачено</div><div className="num mt-0.5">{money(d.paid)}{d.price ? <span className="muted"> / {money(d.price)}</span> : ''}</div></div>
            <div><div className="label">правки · часы</div><div className="num mt-0.5">{d.revisions} · {d.hours ? `${Math.round(d.hours * 10) / 10} ч` : '—'}{d.rate ? <span className="muted"> · {money(d.rate)}/ч</span> : ''}</div></div>
          </div>
          {d.client_id && <button className="btn-soft btn-sm" onClick={() => onClient(d.client_id)}><User size={13} /> карточка клиента</button>}

          {d.payments?.length > 0 && (
            <div><div className="label mb-1">оплаты (частичные)</div>
              {d.payments.map((p) => <div key={p.id} className="muted flex justify-between gap-3"><span>{dayLabel(p.date).toLowerCase()} · {p.note || 'оплата'}</span><span className="num pos">+{money(p.amount)}</span></div>)}
            </div>
          )}

          <div>
            <div className="label mb-1.5">чек-лист этапов</div>
            {d.checklist?.map((c) => (
              <div key={c.id} className="flex items-center gap-2 py-0.5">
                <button className="btn-icon !h-6 !w-6" onClick={() => act(() => api.crmToggleCheck(c.id))} aria-label="готово">{c.done ? <Check size={13} /> : <Square size={13} />}</button>
                <span className={c.done ? 'muted line-through' : ''}>{c.title}</span>
                <button className="btn-icon !h-6 !w-6 ml-auto faint" onClick={() => act(() => api.crmDelCheck(c.id))} aria-label="удалить"><Trash2 size={12} /></button>
              </div>
            ))}
            <form onSubmit={addCheck} className="mt-1.5 flex items-center gap-2">
              <input className="input !h-8 flex-1" placeholder="новый этап" value={check} onChange={(e) => setCheck(e.target.value)} />
              <button className="btn-soft btn-sm" disabled={!check.trim()}>добавить</button>
            </form>
          </div>

          <div>
            <div className="label mb-1.5">комментарии</div>
            {d.comments?.map((c) => <div key={c.id} className="muted py-0.5"><span className="faint">{dayLabel(c.created_at).toLowerCase()} · {c.author}:</span> {c.text}</div>)}
            <div className="mt-1.5 flex items-center gap-2">
              <input className="input !h-8 flex-1" placeholder="комментарий" value={comment} onChange={(e) => setComment(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addComment()} />
              <button className="btn-soft btn-sm" disabled={!comment.trim()} onClick={addComment}>добавить</button>
            </div>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="label">лента активности</span>
              <button className="btn-ghost btn-sm" onClick={async () => { try { setTpl(await api.crmTemplates(oid)) } catch (e) { onErr?.(e) } }}>шаблоны сообщений</button>
            </div>
            {tpl && <div className="mb-2 flex flex-wrap gap-1.5">{Object.entries(tpl).map(([k, t]) => <button key={k} className="chip" onClick={() => useTpl(k)}>{k}</button>)}</div>}
            <div className="max-h-[220px] space-y-1 overflow-y-auto">
              {d.activity?.map((a) => <div key={a.id} className="flex gap-2 text-[12.5px]"><span className="faint shrink-0 num">{dayLabel(a.created_at).toLowerCase()}</span><span className="muted">{a.text}</span></div>)}
              {!d.activity?.length && <div className="faint text-[12px]">пока ничего не происходило</div>}
            </div>
          </div>
        </div>
      )}
    </Sheet>
  )
}

/* Карточка клиента CRM: LTV, средний чек, долг, источник, теги, контакт, следующий шаг, история */
function ClientCardSheet({ cid, onClose, onCard }) {
  const [d, setD] = useState(null)
  const [step, setStep] = useState('')
  useEffect(() => { if (cid) api.crmClientCard(cid).then((r) => { setD(r); setStep(r.next_step || '') }).catch(() => {}); else setD(null) }, [cid])
  const save = async (p) => { try { await api.crmUpdateClient(cid, p); setD(await api.crmClientCard(cid)) } catch { /* ignore */ } }
  return (
    <Sheet open={!!cid} onClose={onClose} wide title={d?.client?.name || 'клиент'} sub={d?.source ? `источник: ${d.source}` : ''}>
      {!d ? <div className="muted text-[13px]">загружаю…</div> : (
        <div className="space-y-4 text-[13px]">
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
            <div><div className="label">LTV</div><div className="num mt-0.5 pos">{money(d.ltv)}</div></div>
            <div><div className="label">средний чек</div><div className="num mt-0.5">{d.avg_check ? money(d.avg_check) : '—'}</div></div>
            <div><div className="label">текущий долг</div><div className={`num mt-0.5 ${d.debt > 0 ? 'warn' : ''}`}>{money(d.debt)}</div></div>
            <div><div className="label">заказов</div><div className="num mt-0.5">{d.orders_count}</div></div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <div><div className="label mb-1">источник лида</div>
              <input className="input !h-8" defaultValue={d.source} placeholder="рекомендация, сайт…" onBlur={(e) => e.target.value !== d.source && save({ source: e.target.value })} /></div>
            <div><div className="label mb-1">последний контакт</div><div className="mt-1.5">{d.last_contact_at ? dayLabel(d.last_contact_at) : '—'}</div></div>
          </div>
          {d.tags?.length > 0 && <div className="flex flex-wrap gap-1.5">{d.tags.map((t) => <span key={t} className="chip on">{t}</span>)}</div>}
          <div>
            <div className="label mb-1">следующий шаг</div>
            <div className="flex items-center gap-2">
              <input className="input !h-8 flex-1" value={step} onChange={(e) => setStep(e.target.value)} placeholder="позвонить, прислать смету…" />
              <button className="btn-soft btn-sm" disabled={step === (d.next_step || '')} onClick={() => save({ next_step: step })}>сохранить</button>
            </div>
            {d.next_step_at && <div className="faint mt-1 text-[12px]">к {dayLabel(d.next_step_at)}</div>}
          </div>
          <div>
            <div className="label mb-1.5">история заказов</div>
            {d.orders.map((o) => (
              <button key={o.id} type="button" className="flex w-full items-center justify-between gap-3 py-0.5 text-left" onClick={() => onCard(o.id)}>
                <span className="min-w-0 truncate">{o.title} <span className="faint">· {STAGE_LABEL[stageOf(o)]}</span></span>
                <span className="num shrink-0">{o.price ? money(o.price) : '—'}{o.left > 0 ? <span className="faint"> · долг {money(o.left)}</span> : ''}</span>
              </button>
            ))}
            {!d.orders.length && <div className="faint text-[12px]">заказов ещё нет</div>}
          </div>
          {d.activity?.length > 0 && <div>
            <div className="label mb-1.5">лента</div>
            <div className="max-h-[180px] space-y-1 overflow-y-auto">{d.activity.map((a) => <div key={a.id} className="muted text-[12.5px]"><span className="faint num">{dayLabel(a.created_at).toLowerCase()}</span> {a.text}</div>)}</div>
          </div>}
        </div>
      )}
    </Sheet>
  )
}

/* Аналитика CRM: конверсия воронки и топ клиентов (read-only) */
function AnalyticsBlock({ a }) {
  const max = Math.max(1, ...a.funnel.map((f) => f.count))
  return (
    <Section title="воронка и топ клиентов" hint="конверсия по стадиям и доход по клиентам — только чтение">
      <div className="space-y-2">
        {a.funnel.map((f) => (
          <div key={f.stage} className="flex items-center gap-3 text-[12.5px]">
            <span className="w-[110px] shrink-0 muted">{f.label}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
              <div className="h-full rounded-full" style={{ width: `${Math.round((f.count / max) * 100)}%`, background: f.stage === 'paid' ? 'var(--pos)' : f.stage === 'lost' ? 'var(--neg)' : 'linear-gradient(90deg, var(--acc), var(--acc2))' }} />
            </div>
            <span className="num w-8 shrink-0 text-right">{f.count}</span>
          </div>
        ))}
      </div>
      <div className="mt-4 grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {a.top.map((c) => <div key={c.client_id ?? 'none'} className="flex items-center justify-between gap-3 text-[12.5px]"><span className="min-w-0 truncate">{c.client} <span className="faint">· {c.orders}</span></span><span className="num pos shrink-0">{money(c.revenue)}</span></div>)}
      </div>
      <div className="muted mt-3 text-[12px]">конверсия {a.conversion}% · выиграно {a.won} из {a.total}{a.avg_check ? ` · средний чек ${money(a.avg_check)}` : ''}</div>
    </Section>
  )
}

function StatsBlock({ stats, onUnpaid }) {
  const [more, setMore] = useState(false)
  const max = Math.max(1, ...stats.months.map((m) => m.income))
  const maxF = Math.max(1, ...stats.focus_days.map((d) => d.min))
  const lastMonth = stats.months.at(-1)?.month
  return (
    <Section title="как идут дела" hint="доход по месяцам — только оплаты по заказам; часы — по таймеру">
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div className="c" style={{ borderRadius: 26 }}>
          <div className="label mb-5">доход по месяцам</div>
          <div className="flex h-[132px] items-end gap-2">
            {stats.months.map((m) => {
              const cur = m.month === lastMonth
              return (
                <div key={m.month} className="group flex flex-1 flex-col items-center gap-1.5">
                  <div className="num text-[11px] opacity-0 transition group-hover:opacity-100">{m.income ? moneyShort(m.income) : ''}</div>
                  <div className="w-full rounded-t-lg transition-all duration-700" style={{
                    height: `${Math.max(3, (m.income / max) * 96)}px`,
                    background: cur ? 'linear-gradient(180deg, var(--acc2) 0%, var(--acc) 100%)' : m.income ? 'linear-gradient(180deg, color-mix(in srgb, var(--acc) 55%, transparent), color-mix(in srgb, var(--acc) 32%, transparent))' : 'var(--fill-2)',
                    boxShadow: cur ? '0 12px 26px -12px color-mix(in srgb, var(--acc) 60%, transparent)' : 'none',
                  }} />
                  <div className="faint mono text-[10px]">{m.month.slice(5)}</div>
                </div>
              )
            })}
          </div>
        </div>
        <div className="c" style={{ borderRadius: 26 }}>
          <div className="mb-5 flex items-baseline justify-between"><div className="label">фокус за 2 недели</div><span className="muted text-[12px]">{stats.week_load_h ? `${hours(stats.week_load_h)} за неделю` : 'таймер ещё не запускали'}</span></div>
          <div className="flex h-[132px] items-end gap-1">
            {stats.focus_days.map((d) => (
              <div key={d.date} className="flex flex-1 flex-col items-center gap-1.5" title={`${d.date.slice(8)}.${d.date.slice(5, 7)} · ${d.min} мин`}>
                <div className="w-full rounded-t-md" style={{
                  height: `${Math.max(3, (d.min / maxF) * 96)}px`,
                  background: d.min ? 'linear-gradient(180deg,#19b34a 0%,#10b3a3 100%)' : 'var(--fill-2)',
                  opacity: d.min ? 0.92 : 1,
                  boxShadow: d.min ? '0 10px 22px -12px rgba(16,179,163,0.6)' : 'none',
                }} />
                <div className="faint mono text-[9px]">{d.date.slice(8)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {stats.clients.length > 0 && (
        <div className="c mt-5" style={{ borderRadius: 26 }}>
          <button className="flex items-center gap-2 text-left" onClick={() => setMore((v) => !v)}><span className="label">клиенты · {stats.clients.length}</span>{more ? <ChevronUp size={13} className="faint" /> : <ChevronDown size={13} className="faint" />}</button>
          {more && (
            <div className="mt-3 animate-rise">
              {stats.clients.map((c) => (
                <div key={c.client} className="row">
                  <div className="min-w-0 flex-1"><div className="truncate text-[14px] font-medium">{c.client}</div><div className="muted text-[12px]">{c.orders} {plural(c.orders, 'заказ', 'заказа', 'заказов')}{c.total ? ` на ${money(c.total)}` : ''}{c.open ? ` · ${c.open} в работе` : ''}{c.hours ? ` · ${hours(c.hours)}` : ''}{c.rate ? ` · ${money(c.rate)}/ч` : ''}</div></div>
                  <div className="num text-right">
                    {c.paid > 0 ? <div className="text-[14px] font-medium">{money(c.paid)} <span className="faint text-[11px] font-normal">получено</span></div> : <div className="faint text-[12.5px]">оплат не записано</div>}
                    {c.unpaid > 0 && <button type="button" className="warn text-[11.5px]" onClick={onUnpaid}>ждём {money(c.unpaid)}</button>}
                  </div>
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
export function OrderSheet({ open, order, onClose, onDone, onErr }) {
  const [f, setF] = useState(blank)
  const [clients, setClients] = useState([])
  const [hint, setHint] = useState(null)
  useEffect(() => {
    if (!open) return
    api.clients().then(setClients).catch(() => {})
    setF(order ? { title: order.title, price: order.price ? String(order.price) : '', client: order.client || '', deadline: order.deadline ? toLocalISO(new Date(order.deadline)).slice(0, 16) : '', notes: order.notes || '', estimate_h: order.estimate_h ? String(order.estimate_h) : '', status: order.status } : blank)
  }, [open, order])
  // Подсказка цены/часов по похожим прошлым заказам (только для нового заказа, с задержкой ввода)
  useEffect(() => {
    if (!open || order) { setHint(null); return }
    const t = f.title.trim()
    if (t.length < 4) { setHint(null); return }
    let on = true
    const id = setTimeout(() => {
      api.ordersSuggest(t).then((s) => { if (on) setHint(s && s.count ? s : null) }).catch(() => {})
    }, 450)
    return () => { on = false; clearTimeout(id) }
  }, [f.title, open, order])
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
        {hint && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl px-3 py-2 text-[12.5px]" style={{ background: 'var(--sf2)' }}>
            <span className="muted">похожие: {hint.sample?.slice(0, 2).join(', ')}</span>
            {hint.price ? <span>обычно <b>{money(hint.price)}</b></span> : null}
            {hint.hours ? <span className="muted">≈{hint.hours} ч{hint.rate ? ` · ${money(hint.rate)}/ч` : ''}</span> : null}
            <button type="button" className="btn-ghost btn-sm !h-6 ml-auto" onClick={() => setF((x) => ({ ...x, ...(hint.price ? { price: String(hint.price) } : {}), ...(hint.hours ? { estimate_h: String(hint.hours) } : {}) }))}>подставить</button>
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="сумма"><Money value={f.price} onChange={(v) => setF({ ...f, price: v })} /></Field>
          <Field label="клиент"><input className="input" list="clients-list" value={f.client} onChange={(e) => setF({ ...f, client: e.target.value })} placeholder="Пятёрочка" /><datalist id="clients-list">{clients.map((c) => <option key={c.id} value={c.name} />)}</datalist></Field>
          <Field label="дедлайн"><DateTimeField value={f.deadline} onChange={(v) => setF({ ...f, deadline: v })} /></Field>
          <Field label="план по времени" hint="часов"><input type="number" min="0" step="0.5" className="input num" value={f.estimate_h} onChange={(e) => setF({ ...f, estimate_h: e.target.value })} placeholder="8" /></Field>
        </div>
        <Field label="статус" hint={order ? undefined : 'старый заказ — сразу «сдан», оплату запишете после'}><Pills value={f.status} onChange={(s) => setF({ ...f, status: s })} options={Object.entries(STATUS).filter(([k]) => order || !['paid', 'cancelled'].includes(k))} /></Field>
        <Field label="заметки"><textarea className="input min-h-[72px]" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="ТЗ, ссылки на исходники, договорённости" /></Field>
        <button className="btn-primary btn-lg w-full">{order ? 'сохранить' : 'добавить'}</button>
      </form>
    </Sheet>
  )
}

function PaySheet({ order, onClose, onDone, onErr, onJustClose }) {
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [accounts, setAccounts] = useState([])
  const [account, setAccount] = useState('')
  const [date, setDate] = useState('')
  useEffect(() => { if (order) { setAmount(order.left ? String(order.left) : ''); setNote(''); setDate(toLocalISO(new Date()).slice(0, 10)); api.accounts().then((a) => { setAccounts(a); setAccount(a.find((x) => x.is_main)?.name || a[0]?.name || '') }).catch(() => {}) } }, [order])
  const submit = async (e) => {
    e.preventDefault()
    const n = Number(String(amount).replace(/\s/g, '').replace(',', '.'))
    if (!n || n <= 0) return onErr(new Error('Сумма должна быть больше нуля'))
    const today = toLocalISO(new Date()).slice(0, 10)
    try { onDone(await api.payOrder(order.id, n, { note: note || null, account: account || null, date: date && date !== today ? `${date}T12:00:00` : null })) } catch (err) { onErr(err) }
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
          <Field label="дата" hint="когда пришли деньги"><input type="date" className="input" value={date} max={toLocalISO(new Date()).slice(0, 10)} onChange={(e) => setDate(e.target.value)} /></Field>
        </div>
        <div className="muted text-[12.5px]">Запишется как доход «Фриланс» с привязкой к заказу в выбранный день. Полная сумма закроет заказ как оплаченный.</div>
        <button className="btn-primary btn-lg w-full">записать</button>
        {onJustClose && <button type="button" className="btn-ghost btn-sm w-full" onClick={() => onJustClose(order)}>деньги уже учтены — просто закрыть заказ</button>}
      </form>
    </Sheet>
  )
}


/* Доска заказа: раскадровка/референсы/сценарий. Есть — открыть; нет — создать (пустая раскадровка, привязанная к заказу). */
function BoardButton({ o }) {
  const nav = useNavigate()
  const [, show] = useToast()
  const go = async () => {
    try { const b = await api.get(`/api/boards/for-order/${o.id}?create=true`); nav(`/board/${b.id}`) } catch (e) { show.err(e) }
  }
  return <button className="btn-ghost btn-sm" onClick={go} data-tip={o.board_id ? 'открыть доску заказа' : 'создать доску заказа'}><Clapperboard size={13} /> {o.board_id ? 'доска' : 'доска +'}</button>
}
