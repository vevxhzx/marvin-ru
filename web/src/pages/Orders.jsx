import { useEffect, useMemo, useState } from 'react'
import { Plus, Check, Play, Square, Trash2, MessageCircle, Wallet, Clock, ChevronDown, ChevronUp, Pencil, Clapperboard, TrendingUp, Coins, List, RefreshCw, Bell, User, HelpCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, money, moneyShort, dayLabel, shortDate, hhmm, plural, toLocalISO } from '../lib/api'
import { Section, Empty, Sheet, Field, DateTimeField, Seg, Pills, Money, useToast, PageHead, useLeave, Swipe, ListSkeleton, Confirm, Num, PageAccent } from '../components/ui'
import { useRefresh } from '../App'
import { usePageAccent } from '../lib/prefs'
import StageStepper from '../components/StageStepper'
import OrderDrawer from '../components/OrderDrawer'
import HowToOrders from '../components/HowToOrders'
import MenuButton from '../components/RowMenu'
import { ClientStageBadge, ClientStageSelect, ClientStageNote } from '../components/ClientStage'
import {
  ORDER_STAGES, ORDER_STAGE_LABEL, ORDER_STAGE_TONE, stageOf, NEXT_STEP, STAGE_TO_STATUS,
} from '../lib/crm'

const VIEWS = [['open', 'в работе'], ['unpaid', 'ждут оплаты'], ['all', 'все']]
const STATUS_DOT = { new: 'var(--accent)', work: 'var(--accent)', review: 'var(--warn)', done: 'var(--pos)', paid: 'var(--pos)', cancelled: 'var(--ink-3)' }
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
  const [sheet, setSheet] = useState(null)      // null | 'new' | order (форма заказа)
  const [drawerId, setDrawerId] = useState(null) // боковая панель заказа — открывается кликом по строке
  const [personCard, setPersonCard] = useState(null)  // CRM-карточка клиента
  const [pay, setPay] = useState(null)          // order
  const [del, setDel] = useState(null)
  const [lost, setLost] = useState(null)        // заказ, у которого спрашиваем причину потери
  const [payTick, setPayTick] = useState(0)      // оплата снаружи панели — панель должна перечитать заказ
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
  // стадия заказа меняется через CRM (старый status синхронизируется на бэке).
  // «потерян» требует причину: клик по нему открывает вопрос, а не меняет стадию сразу.
  const setStage = async (o, stage) => {
    if (stage === stageOf(o)) return
    if (stage === 'lost') return setLost(o)
    if (stage === 'paid' && o.left > 0) return setPay(o)
    try { await api.crmSetStage(o.id, stage); show(`Стадия: ${ORDER_STAGE_LABEL[stage]}`, '', o.title); load(); bump() } catch (e) { show.err(e) }
  }
  const openDrawer = (o) => setDrawerId(o.id)
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
          <button type="button" className="btn-icon outlined" aria-label="Как это работает: 3 шага" data-tip="Как это работает"
            onClick={() => window.dispatchEvent(new CustomEvent('orders:howto', { detail: 'toggle' }))}><HelpCircle size={16} /></button>
          <button className="btn-primary head-primary" onClick={() => setSheet('new')}><Plus size={15} /> заказ</button>
        </>} />

      <div className="-mt-4"><HowToOrders /></div>

      <form onSubmit={addQuick} className="composer animate-rise flex items-center gap-2 py-1.5 pl-4 pr-1.5">
        <Plus size={16} className="faint shrink-0" />
        <input value={quick} onChange={(e) => setQuick(e.target.value)} className="h-9 w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]" placeholder="Своими словами: «ролик для Пятёрочки, 25к, до пятницы»…" />
        <button className="btn-primary grid !h-9 !w-9 shrink-0 !rounded-full !p-0" disabled={!quick.trim()} aria-label="Добавить"><Plus size={16} /></button>
      </form>

      {/* сводка: смысловые плитки (лайм — деньги, янтарь — ожидание); пустые не показываем.
          Помодоро живёт в сайдбаре и в шапке-таймере — на странице заказов не дублируем. */}
      <div className="bento" style={{ marginTop: 26 }}>
        <Tile span="s4" icon={<Play size={16} />}
          label="в работе" value={<Num value={openN} />}
          sub={overdue ? `${overdue} ${plural(overdue, 'дедлайн горит', 'дедлайна горят', 'дедлайнов горят')}` : 'всё под контролем'} />
        <Tile span="s4" tone="warn" icon={<Wallet size={16} />}
          label="ждут оплаты" value={<Num value={unpaid} fmt={money} />} onClick={() => setView('unpaid')} tip={unpaid ? 'показать, кто не заплатил' : undefined}
          sub={unpaid ? 'нажмите, чтобы найти должников' : 'все рассчитались'} />
        {stats && <Tile span="s4" tone="ok" icon={<TrendingUp size={16} />}
          label="за этот месяц" value={<Num value={month} fmt={money} />}
          sub={prevMonth ? `прошлый · ${money(prevMonth.income)}` : 'первый месяц в работе'} />}
        {stats?.rate ? <Tile span="s4" icon={<Clock size={16} />}
          label="ставка в час" value={money(stats.rate)}
          sub={stats.total_hours ? `${hours(stats.total_hours)} по таймеру` : 'по таймеру'} /> : null}
        {stats?.avg_check ? <Tile span="s4" icon={<Coins size={16} />}
          label="средний чек" value={money(stats.avg_check)}
          sub={stats.avg_lead_days ? `~${stats.avg_lead_days} дн. на заказ` : 'по закрытым заказам'} /> : null}
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
            <button key={f.id} type="button" className="flex items-center gap-1.5 text-left" onClick={() => f.order_id && setDrawerId(f.order_id)}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: f.kind === 'overdue' ? 'var(--neg)' : 'var(--warn)' }} />
              <span className="truncate max-w-[280px]">{f.text}</span>
            </button>
          ))}
          <button type="button" className="btn-ghost btn-sm" onClick={scanFollowups}><RefreshCw size={12} /> обновить</button>
        </div>
      )}

      {!orders ? <ListSkeleton n={4} /> : layout === 'board' ? (
        <Section title="канбан" idx={list.length}
          hint="Перетащите карточку в другую колонку — это меняет стадию заказа. Без перетаскивания: выберите стадию в списке на карточке.">
          <Board orders={list} onOpen={openDrawer} onStage={setStage} />
        </Section>
      ) : (
        <Section title={VIEWS.find((v) => v[0] === view)[1]} idx={list.length}
          hint="Клик по строке открывает панель заказа: стадия, оплата, время, клиент, история. В строке одна главная кнопка «следующий шаг», остальные действия — в меню «⋯». На телефоне: свайп вправо — следующий шаг, влево — удалить.">
          <div className="stagger space-y-2.5">
            {list.length === 0 && (
              view === 'open' ? <Empty glyph="tasks" text="Заказов в работе нет" sub="Как возьмёте — скажите мне, я запомню дедлайн и буду ждать оплату" hint="заказ: монтаж свадьбы для Иванова, 60к, до 30 сентября" />
                : view === 'unpaid' ? <Empty glyph="money" text="Все оплатили" sub="Приятная пустота" />
                  : <Empty glyph="tasks" text="Пока пусто" hint="заказ: ролик для Пятёрочки, 25к, до пятницы" />
            )}
            {list.map((o) => <Row key={o.id} o={o} onOpen={() => openDrawer(o)} onEdit={() => setSheet(o)} onPay={() => setPay(o)}
              onDel={() => setDel(o)} onStatus={setStatus} onStart={() => start(o)} onStage={(k) => setStage(o, k)} timer={timer} extra={leaveCls(o.id)} />)}
          </div>
        </Section>
      )}

      {stats && (stats.clients.length > 0 || stats.months.some((m) => m.income)) && <StatsBlock stats={stats} onUnpaid={() => { setView('unpaid'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />}

      {/* Панель заказа идёт ПЕРВОЙ из модалок: всё, что открывают из неё (оплата, форма,
          карточка клиента), должно оказываться поверх — порядок DOM определяет стек. */}
      <OrderDrawer oid={drawerId} reloadKey={payTick} onClose={() => setDrawerId(null)} onChanged={() => { load(); bump() }} onErr={show.err} onMsg={(t) => show(t)}
        onClient={(cid) => { setDrawerId(null); setPersonCard(cid) }} onEdit={(o) => setSheet(o)} onPay={(o) => setPay(o)}
        onAsk={(o) => ask(`по заказу «${o.title}»: `)} timer={timer} onStartTimer={start} onStopTimer={stop} mmss={mmss} />

      <OrderSheet open={!!sheet} order={sheet && sheet !== 'new' ? sheet : null} onClose={() => setSheet(null)} onDone={(msg) => { setSheet(null); show(msg); load(); bump() }} onErr={show.err} />
      <PaySheet order={pay} onClose={() => setPay(null)} onJustClose={async (o) => { setPay(null); try { await api.updateOrder(o.id, { status: 'paid' }); show('Заказ закрыт', 'без записи в доходы', o.title); setPayTick((x) => x + 1); load(); bump() } catch (e) { show.err(e) } }} onDone={(r) => { setPay(null); show(r.order.status === 'paid' ? 'Заказ закрыт как оплаченный' : 'Оплата записана в доходы', '', r.order.title); setPayTick((x) => x + 1); load(); bump() }} onErr={show.err} />
      <Confirm open={!!del} title="Удалить заказ?" text={del ? `«${del.title}». Полученные оплаты останутся в доходах, время по таймеру — тоже.` : ''} danger onOk={() => { remove(del); setDel(null) }} onClose={() => setDel(null)} />

      <LostSheet order={lost} onClose={() => setLost(null)} onDone={async (reason) => { try { await api.crmSetStage(lost.id, 'lost', reason); show('Заказ помечен потерянным', '', lost.title); setLost(null); setPayTick((x) => x + 1); load(); bump() } catch (e) { show.err(e) } }} />
      <ClientCardSheet cid={personCard} onClose={() => setPersonCard(null)} onOrder={(oid) => { setPersonCard(null); setDrawerId(oid) }} />
      {analytics && analytics.clients?.length > 0 && <AnalyticsBlock a={analytics} />}
    </div>
  )
}

/* Плитка сводки. tone — смысловой тинт (.tint-ok/.tint-warn/…); без него — нейтральная
   поверхность. Старый градиентный вид оставлен на случай явного gradient. */
function Tile({ span = 's4', gradient, ink = '#ffffff', glow = 'rgba(16,17,20,0.5)', tone, icon, label, value, sub, onClick, tip }) {
  const inner = (
    <>
      {icon && <span className="pointer-events-none absolute right-5 top-5 opacity-70" aria-hidden>{icon}</span>}
      <div className="label" style={{ color: 'inherit', opacity: 0.72 }}>{label}</div>
      <div className="num mt-3 text-[32px] font-medium leading-none tracking-[-0.045em] sm:text-[38px]">{value}</div>
      {sub && <div className="mt-2 max-w-[94%] text-[12.5px] leading-snug" style={{ opacity: 0.82 }}>{sub}</div>}
    </>
  )
  const style = gradient
    ? { background: gradient, color: ink, borderRadius: 26, padding: '22px 24px', minHeight: 132, overflow: 'visible', boxShadow: `inset 0 1px 0 rgba(255,255,255,0.35), 0 18px 40px -22px ${glow}` }
    : { borderRadius: 26, padding: '22px 24px', minHeight: 132, overflow: 'visible' }
  const cls = `c ${span} relative block ${tone ? `tint-${tone}` : ''}`
  return onClick
    ? <button type="button" onClick={onClick} data-tip={tip} className={`${cls} w-full text-left transition duration-300 hover:-translate-y-0.5`} style={style}>{inner}</button>
    : <section className={cls} style={style}>{inner}</section>
}

/* Строка заказа: кликабельна целиком (открывает панель), одна главная кнопка «следующий шаг»
   с понятным текстом по текущей стадии. Остальные действия — в меню «⋯» с текстовыми подписями.
   Кнопка «карточка» убрана: панель заказа и есть карточка. */
function Row({ o, onOpen, onEdit, onPay, onDel, onStart, onStage, onStatus, timer, extra = '' }) {
  const nav = useNavigate()
  const [, show] = useToast()
  const stage = stageOf(o)
  const next = NEXT_STEP[stage]
  const closed = ['paid', 'cancelled'].includes(o.status)
  const running = timer?.active && timer.order_id === o.id && timer.kind === 'focus'
  const dl = o.deadline ? (o.overdue ? `просрочен · ${dayLabel(o.deadline).toLowerCase()}` : o.past_due ? `срок был ${shortDate(o.deadline).toLowerCase()}` : o.days_left === 0 ? 'сегодня' : o.days_left === 1 ? 'завтра' : `до ${shortDate(o.deadline).toLowerCase()}`) : null
  const pct = o.price > 0 ? Math.min(100, Math.round((o.paid / o.price) * 100)) : 0
  const stop = (fn) => (e) => { e.stopPropagation(); fn() }
  const openBoard = async () => {
    try { const b = await api.get(`/api/boards/for-order/${o.id}?create=true`); nav(`/board/${b.id}`) } catch (e) { show.err(e) }
  }
  const menu = [
    o.status !== 'cancelled' && o.left > 0 && { key: 'pay', text: 'Записать оплату', icon: <Wallet size={13} />, onClick: onPay },
    running
      ? { key: 'stop', text: 'Остановить таймер', icon: <Square size={13} />, onClick: onStart }
      : { key: 'timer', text: `Таймер ${timer?.focus_min || 25} минут`, icon: <Play size={13} />, onClick: onStart },
    { key: 'edit', text: 'Изменить заказ', icon: <Pencil size={13} />, onClick: onEdit },
    { key: 'ask', text: 'Обсудить с ассистентом', icon: <MessageCircle size={13} />, onClick: () => ask(`по заказу «${o.title}»: `) },
    { key: 'board', text: o.board_id ? 'Открыть доску заказа' : 'Создать доску заказа', icon: <Clapperboard size={13} />, onClick: openBoard },
    stage === 'lost' && { key: 'restore', text: 'Вернуть в работу', icon: <RefreshCw size={13} />, onClick: () => onStage('in_work') },
    !closed && { key: 'cancel', text: 'Отменить заказ', icon: <Square size={13} />, onClick: () => onStatus(o, 'cancelled') },
    !closed && { key: 'del', text: 'Удалить заказ', icon: <Trash2 size={13} />, onClick: onDel, danger: true },
  ]
  return (
    <Swipe onLeft={!closed ? onDel : undefined} onRight={next ? () => onStage(next.stage) : undefined} rightLabel={next?.text || 'готово'}>
      <div className={`row-slide ${extra} ${closed ? 'opacity-55' : ''}`}>
        <div role="button" tabIndex={0} aria-label={`Открыть заказ «${o.title}»`} onClick={onOpen}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}
          className={`group relative cursor-pointer px-4 py-3.5 transition duration-300 hover:-translate-y-px ${CARD_SHADOW}`}
          style={{ background: o.overdue ? 'var(--neg-soft)' : 'var(--sf)', borderRadius: 22, ...(o.overdue ? { boxShadow: 'inset 0 0 0 1.5px var(--neg)' } : null) }}>
          <div className="relative flex flex-wrap items-center gap-x-3 gap-y-2 pl-1">
            <span className="absolute -left-4 bottom-1 top-1 w-1 rounded-full" style={{ background: o.overdue ? 'var(--neg)' : STATUS_DOT[o.status] }} aria-hidden />
            <div className="min-w-[200px] flex-1">
              <div className="flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2">
                <div className="min-w-0 truncate text-[15px] font-medium">{o.title}</div>
                {o.client && <div className="muted min-w-0 truncate text-[12.5px] sm:shrink-0 sm:text-[13px]">{o.client}</div>}
              </div>
              <div className={`mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] ${o.overdue ? 'neg' : (!o.past_due && o.days_left != null && o.days_left <= 2) ? 'warn' : 'muted'}`}>
                {dl && <span className="flex items-center gap-1"><Clock size={11} /> {dl}</span>}
                {o.hours > 0 && <span className={o.pulse?.warn ? 'warn' : 'muted'}>{o.hours}{o.pulse?.estimate_h ? ` из ${hours(o.pulse.estimate_h)}` : ''}{o.rate ? ` · ${money(o.rate)}/ч` : ''}</span>}
                {running && <span className="accent flex items-center gap-1">идёт таймер</span>}
              </div>
              <StageStepper compact stage={stage} onStage={onStage} revisions={o.revisions} className="mt-1.5" />
              {o.price > 0 && (
                <div className="mt-1.5 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
                    <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, var(--acc), var(--acc2))' }} />
                  </div>
                  <span className="num faint shrink-0 text-[10.5px]">оплачено {pct}%</span>
                </div>
              )}
            </div>
            <div className="num shrink-0 text-right">
              <div className="text-[15px] font-medium">{o.price ? money(o.price) : <span className="faint">без суммы</span>}</div>
              {o.price > 0 && o.paid > 0 && o.left > 0 && <div className="muted text-[11.5px]">осталось {money(o.left)}</div>}
              {o.price > 0 && o.paid === 0 && !closed && o.status !== 'new' && <div className="faint text-[11.5px]">не оплачен</div>}
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {next ? (
                <button type="button" className="btn-primary btn-sm !h-8" data-tip={next.tip} onClick={stop(() => onStage(next.stage))}>
                  <Check size={13} /> {next.text}
                </button>
              ) : <span className="badge pos shrink-0">готово</span>}
              <MenuButton items={menu} ariaLabel={`Ещё действия: ${o.title}`} />
            </div>
          </div>
        </div>
      </div>
    </Swipe>
  )
}

/* Канбан CRM: нативный HTML5 drag&drop (десктоп) + список «стадия» на каждой карточке
   (альтернатива без перетаскивания — на телефоне жест не нужен).
   Колонка показывает стадию, количество и сумму заказов; цвет — по смыслу из DESIGN.md. */
function Board({ orders, onOpen, onStage }) {
  const [drag, setDrag] = useState(null)
  const [over, setOver] = useState(null)
  const cols = useMemo(() => {
    const m = {}
    ORDER_STAGES.forEach(([k]) => { m[k] = [] })
    orders.forEach((o) => { (m[stageOf(o)] || (m[stageOf(o)] = [])).push(o) })
    return m
  }, [orders])
  return (
    <div className="overflow-x-auto pb-3">
      <div className="flex gap-3" style={{ minWidth: 'max-content' }}>
        {ORDER_STAGES.map(([k, label]) => {
          const tone = ORDER_STAGE_TONE[k]
          const col = cols[k] || []
          const sum = col.reduce((s, o) => s + (o.price || 0), 0)
          return (
            <div key={k} className="w-[258px] shrink-0"
              onDragOver={(e) => { e.preventDefault(); setOver(k) }}
              onDragLeave={() => setOver((x) => (x === k ? null : x))}
              onDrop={(e) => { e.preventDefault(); const d = drag; setOver(null); setDrag(null); if (d) onStage(d, k) }}>
              <div className="mb-2 overflow-hidden rounded-xl" aria-label={`Колонка «${label}»: заказов ${col.length}${sum > 0 ? `, на ${money(sum)}` : ''}`}
                style={{ background: 'var(--sf2)', boxShadow: 'inset 0 0 0 1px var(--line)', outline: over === k ? '2px solid var(--acc)' : 'none' }}>
                <div className="h-[3px]" style={{ background: tone === 'pos' ? 'var(--pos)' : tone === 'warn' ? 'var(--warn)' : tone === 'neg' ? 'var(--neg)' : 'var(--acc)' }} aria-hidden />
                <div className="flex items-center justify-between gap-2 px-3 py-2">
                  <span className="truncate text-[12.5px] font-medium">{label}</span>
                  <span className="num shrink-0 text-[11px]">
                    <span className={col.length ? 'text-[var(--ink-2)]' : 'faint'}>{col.length}</span>
                    {sum > 0 && <span className="faint"> · {moneyShort(sum)}</span>}
                  </span>
                </div>
              </div>
              <div className="space-y-2" style={{ minHeight: 56 }}>
                {col.map((o) => (
                  <div key={o.id} draggable
                    onDragStart={(e) => { try { e.dataTransfer.setData('text/plain', String(o.id)) } catch { /* ignore */ } e.dataTransfer.effectAllowed = 'move'; setDrag(o) }}
                    onDragEnd={() => { setDrag(null); setOver(null) }}
                    onClick={() => onOpen(o)}
                    className={`cursor-grab rounded-2xl px-3 py-2.5 transition active:cursor-grabbing ${drag?.id === o.id ? 'opacity-50' : ''}`}
                    style={{ background: o.overdue ? 'var(--neg-soft)' : 'var(--sf)', boxShadow: o.overdue ? 'inset 0 0 0 1.5px var(--neg)' : 'inset 0 0 0 1px var(--line)', borderRadius: 18 }}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-[13.5px] font-medium">{o.title}</div>
                        {o.client && <div className="muted truncate text-[12px]">{o.client}</div>}
                      </div>
                      {o.deadline && <span className={`shrink-0 text-[10.5px] ${o.overdue ? 'neg' : 'faint'}`}>{shortDate(o.deadline)}</span>}
                    </div>
                    <div className="mt-1.5 flex items-center justify-between gap-2 text-[11.5px]">
                      <span className="muted num">{o.price ? money(o.price) : '—'}</span>
                      {o.left > 0 && o.status !== 'new' && <span className="faint num">долг {money(o.left)}</span>}
                      {o.revisions > 0 && <span className="warn">правки ×{o.revisions}</span>}
                    </div>
                    {o.price > 0 && (
                      <div className="mt-1.5 h-1 overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
                        <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.round((o.paid / o.price) * 100))}%`, background: 'linear-gradient(90deg, var(--acc), var(--acc2))' }} />
                      </div>
                    )}
                    <div className="mt-2 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      <select className="input !h-7 flex-1 !text-[12px]" value={stageOf(o)} onChange={(e) => onStage(o, e.target.value)}
                        aria-label={`Стадия заказа «${o.title}»`} data-tip="стадия заказа">
                        {ORDER_STAGES.map(([sk, sl]) => <option key={sk} value={sk}>{sl}</option>)}
                      </select>
                    </div>
                  </div>
                ))}
                {col.length === 0 && (
                  <div className="rounded-xl px-3 py-4 text-center text-[11.5px] faint" style={{ border: '1px dashed var(--line)' }}>
                    Перетащите карточку сюда
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* «Потерян» требует причину: короткая форма, дальше стадия уходит в CRM. */
function LostSheet({ order, onClose, onDone }) {
  const [reason, setReason] = useState('')
  useEffect(() => { setReason('') }, [order?.id])
  return (
    <Sheet open={!!order} onClose={onClose} title="пометить потерянным" sub={order ? `«${order.title}»` : ''}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (reason.trim()) onDone(reason.trim()) }}>
        <Field label="почему заказ потерян" hint="обязательно — по этой причине видно в ленте">
          <input autoFocus className="input" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="дорого, клиент пропал, взял другого подрядчика…" />
        </Field>
        <div className="muted text-[12.5px]">Заказ уедет в колонку «потерян». Стадию можно вернуть в любой момент — в строке заказа или в панели.</div>
        <div className="flex gap-2">
          <button className="btn-primary" disabled={!reason.trim()} type="submit">пометить потерянным</button>
          <button type="button" className="btn-ghost" onClick={onClose}>отмена</button>
        </div>
      </form>
    </Sheet>
  )
}

/* Карточка клиента CRM: стадия клиента (отдельная сущность!), LTV, средний чек, долг,
   источник, теги, контакт, следующий шаг с датой, история заказов. */
export function ClientCardSheet({ cid, onClose, onOrder }) {
  const [d, setD] = useState(null)
  const [step, setStep] = useState('')
  const [stepAt, setStepAt] = useState('')
  const [err, setErr] = useState('')
  const [, show] = useToast()
  useEffect(() => {
    if (!cid) { setD(null); return }
    api.crmClientCard(cid).then((r) => {
      setD(r); setStep(r.next_step || ''); setStepAt(r.next_step_at ? toLocalISO(new Date(r.next_step_at)).slice(0, 10) : '')
    }).catch(() => setD(null))
  }, [cid])
  const save = async (p) => {
    try { await api.crmUpdateClient(cid, p); setD(await api.crmClientCard(cid)) } catch (e) { show.err(e) }
  }
  const saveStep = async () => {
    setErr('')
    await save({ next_step: step, next_step_at: stepAt ? `${stepAt}T12:00:00` : null })
  }
  return (
    <Sheet open={!!cid} onClose={onClose} wide title={d?.client?.name || 'клиент'} sub={d?.source ? `источник: ${d.source}` : ''}>
      {!d ? <div className="muted text-[13px]">загружаю…</div> : (
        <div className="space-y-4 text-[13px]">
          <div>
            <div className="label mb-1.5">стадия клиента — не стадия заказа</div>
            <ClientStageSelect view={d.stage} onView={(v) => setD({ ...d, stage: v })} onErr={show.err} label={`Стадия клиента ${d.client?.name || ''}`} />
            <ClientStageNote view={d.stage} />
          </div>
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
            <div className="flex flex-wrap items-center gap-2">
              <input className="input !h-8 min-w-[180px] flex-1" value={step} onChange={(e) => setStep(e.target.value)} placeholder="позвонить, прислать смету…" aria-label="Следующий шаг" />
              <input type="date" className="input !h-8 !w-[150px]" value={stepAt} onChange={(e) => setStepAt(e.target.value)} aria-label="Дата следующего шага" />
              <button className="btn-soft btn-sm" disabled={step === (d.next_step || '') && stepAt === (d.next_step_at ? toLocalISO(new Date(d.next_step_at)).slice(0, 10) : '')} onClick={saveStep}>сохранить</button>
            </div>
            {err && <div className="neg mt-1 text-[12px]">{err}</div>}
            <div className="faint mt-1 text-[12px]">{d.next_step_at ? `было: к ${dayLabel(d.next_step_at)}` : 'даты можно задать здесь — она попадёт в follow-up'}</div>
          </div>
          <div>
            <div className="label mb-1.5">история заказов</div>
            {d.orders.map((o) => (
              <button key={o.id} type="button" className="flex w-full items-center justify-between gap-3 py-0.5 text-left" onClick={() => onOrder?.(o.id)}>
                <span className="min-w-0 truncate">{o.title} <span className="faint">· {ORDER_STAGE_LABEL[stageOf(o)]}</span></span>
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

/* Стадии, которые имеет смысл выбрать при создании (воронка CRM, те же подписи, что и везде).
   «оплачен» появляется только через оплату, «потерян» — с причиной, позже. */
const NEW_STAGES = [['lead', 'лид'], ['negotiation', 'переговоры'], ['spec', 'ТЗ согласовано'], ['in_work', 'в работе'], ['revisions', 'на правках'], ['delivered', 'сдан']]

const blank = { title: '', price: '', client: '', deadline: '', notes: '', estimate_h: '', stage: 'in_work', done: false, paid: '' }
export function OrderSheet({ open, order, onClose, onDone, onErr }) {
  const [f, setF] = useState(blank)
  const [clients, setClients] = useState([])
  const [hint, setHint] = useState(null)
  useEffect(() => {
    if (!open) return
    api.clients().then(setClients).catch(() => {})
    const st = order ? stageOf(order) : 'in_work'
    setF(order
      ? { title: order.title, price: order.price ? String(order.price) : '', client: order.client || '', deadline: order.deadline ? toLocalISO(new Date(order.deadline)).slice(0, 16) : '', notes: order.notes || '', estimate_h: order.estimate_h ? String(order.estimate_h) : '', stage: st, done: st === 'delivered' || st === 'awaiting_payment', paid: '' }
      : blank)
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
    const stage = f.done ? 'delivered' : f.stage
    const body = {
      title: f.title.trim(), price: Number(String(f.price).replace(/\s/g, '').replace(',', '.')) || 0,
      client: f.client.trim() || null, deadline: f.deadline || null, notes: f.notes.trim() || null,
      estimate_h: Number(f.estimate_h) || 0, status: STAGE_TO_STATUS[stage] || 'work',
    }
    try {
      // эндпоинт /api/orders знает только старый статус; точную стадию воронки ставим через CRM
      const saved = order ? await api.updateOrder(order.id, body) : await api.addOrder(body)
      const oid = order ? order.id : saved?.id
      const now = stageOf(saved || order || {})
      if (oid && stage !== now) { try { await api.crmSetStage(oid, stage) } catch { /* стадия не критична для сохранения */ } }
      const paid = Number(String(f.paid).replace(/\s/g, '').replace(',', '.'))
      if (oid && f.done && paid > 0) { try { await api.payOrder(oid, paid, { note: 'оплата при создании' }) } catch { /* покажем тост */ } }
      onDone(order ? 'Заказ обновлён' : (f.done ? 'Заказ добавлен как сданный' : 'Заказ добавлен'))
    } catch (err) { onErr(err) }
  }
  const toggleDone = (v) => setF({ ...f, done: v, stage: v ? 'delivered' : f.stage === 'delivered' ? 'in_work' : f.stage })
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
          <Field label="Сколько часов планируете" hint="план по времени"><input type="number" min="0" step="0.5" className="input num" value={f.estimate_h} onChange={(e) => setF({ ...f, estimate_h: e.target.value })} placeholder="8" /></Field>
        </div>

        {/* чекбокс вместо непонятной подсказки про «старый заказ»: ставит «сдан» и открывает поле оплаты */}
        <label className="flex cursor-pointer items-center gap-2.5 text-[13.5px]">
          <input type="checkbox" className="h-4 w-4 accent-[var(--acc)]" checked={f.done} onChange={(e) => toggleDone(e.target.checked)} />
          <span>Заказ уже выполнен — поставлю стадию «сдан»</span>
        </label>
        {f.done && (
          <Field label="уже получено за заказ" hint="можно позже — в панели заказа">
            <Money value={f.paid} onChange={(v) => setF({ ...f, paid: v })} placeholder="0" />
          </Field>
        )}

        {!f.done && (
          <Field label="стадия заказа" hint="воронка CRM — та же, что на канбане">
            <Pills value={f.stage} onChange={(s) => setF({ ...f, stage: s })} options={NEW_STAGES} />
          </Field>
        )}
        <Field label="заметки и ТЗ"><textarea className="input min-h-[72px]" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="ТЗ, ссылки на исходники, договорённости" /></Field>
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
