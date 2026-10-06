import { useEffect, useMemo, useRef, useState } from 'react'
import { Plus, Check, Play, Square, Trash2, MessageCircle, Wallet, Clock, ChevronDown, ChevronUp, Pencil, Clapperboard, RefreshCw, HelpCircle } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, money, moneyShort, dayLabel, shortDate, hhmm, toLocalISO } from '../lib/api'
import { Section, Empty, ErrorState, Sheet, Field, DateTimeField, Seg, Pills, Money, useToast, PageHead, useLeave, Swipe, ListSkeleton, Confirm } from '../components/ui'
import '../orders-glass.css'
import { useRefresh } from '../App'
import { usePageAccent } from '../lib/prefs'
import StageStepper from '../components/StageStepper'
import OrderDrawer from '../components/OrderDrawer'
import HowToOrders from '../components/HowToOrders'
import MenuButton from '../components/RowMenu'
import { ClientStageSelect, ClientStageNote } from '../components/ClientStage'
import { ORDER_STAGES, ORDER_STAGE_LABEL, ORDER_STAGE_TONE, stageOf, NEXT_STEP, STAGE_TO_STATUS } from '../lib/crm'
import { useI18n, t as T } from '../lib/i18n'
import { usePhone } from '../lib/motion'

/* Подписи полей на узком телефоне (≤380px) — на ступень мельче: длинная подпись
   вроде «дата следующего шага» на 375px съедала строку и отжимала само поле. */
const FIELD_LABEL_M = 'max-[380px]:[&_.label]:text-[length:11px]'

/* Лёгкая карточка телефона (≤820px): та же поверхность, но без тени и без хайрлайна —
   отступ 21px, радиус из токена (--r-lg; макет называет 24px — значение ведёт index.css), разделение тоном (макет).
   На десктопе (≥821px) класс не действует — там раздел получает стекло из .og-card (см. sectionCls). */
const CARD_M_LIGHT = 'max-[820px]:!bg-[var(--sf)] max-[820px]:!p-[21px] max-[820px]:!rounded-[var(--r-lg)] max-[820px]:!shadow-none max-[820px]:!transform-none'

/* Раздел страницы на телефоне — карточка, на десктопе — стеклянная карточка макета
   (.og-card в orders-glass.css: фон/кромка/блюр только ≥821px, телефон не трогаем). */
const sectionCls = (phone) => (phone ? `c ${CARD_M_LIGHT}` : 'c og-card')

/* Состояние человека в шапке героя (макет .av): щёлкает по кругу + тост, цвет —
   смысловой (зелёный свободен / янтарь занят / розовый пауза), ключи словаря свои. */
const AV_STATUS = [['or.free', 'var(--pos)'], ['status_in_progress', 'var(--warn)'], ['status_paused', 'var(--neg)']]

/* Срезы списка. Названия — ключи словаря (см. lib/i18n.js). */
const VIEWS = [['open', 'or.v_open'], ['unpaid', 'or.v_unpaid'], ['all', 'common.all']]
/* Цвет точки стадии: смысловой тон из DESIGN.md, иначе — акцент. */
const STAGE_VAR = { warn: 'var(--warn)', pos: 'var(--pos)', neg: 'var(--neg)' }
/* Подписи мелким кеглем на узком телефоне (≤380px) уменьшаются на ступень */
const SMALL_M = 'max-[380px]:text-[length:var(--fs-xs)]'
const ask = (text) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } }))
const hours = (h) => (h >= 1 ? `${Math.round(h * 10) / 10} ${T('unit.hour')}` : h > 0 ? `${Math.round(h * 60)} ${T('unit.min')}` : '—')

/* Ключевая сумма «доезжает» до значения за ~900 мс (макет: счётчик #ow/data-n).
   prefers-reduced-motion — сразу финальное значение. Значение тут числовое,
   форматирование — обычным money(), поэтому анимация не ломает валюту и пробелы. */
function useCountUp(to, ms = 900) {
  const [v, setV] = useState(to)
  const from = useRef(to)
  useEffect(() => {
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const a = from.current
    if (reduce || a === to) { from.current = to; setV(to); return }
    let raf = 0
    const t0 = performance.now()
    const step = (now) => {
      const p = Math.min(1, (now - t0) / ms)
      const e = 1 - Math.pow(1 - p, 4)
      const nv = Math.round(a + (to - a) * e)
      from.current = nv
      setV(nv)
      if (p < 1) raf = requestAnimationFrame(step)
      else from.current = to
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [to, ms])
  return v
}

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
  const { t } = useI18n()
  const [orders, setOrders] = useState(null)
  const [loadErr, setLoadErr] = useState(false)
  const pageAcc = usePageAccent('orders')
  const [stats, setStats] = useState(null)
  const [pulse, setPulse] = useState(null)   // задержки оплат + налог за месяц (режим фрилансера)
  const [view, setView] = useState('open')
  const [stageTab, setStageTab] = useState('all')   // фильтр по стадии заказа (воронка)
  const [layout, setLayout] = useState(() => (typeof localStorage !== 'undefined' && localStorage.getItem('orders.layout')) || 'list')
  const [quick, setQuick] = useState('')
  const [sheet, setSheet] = useState(null)      // null | 'new' | order (форма заказа)
  const [drawerId, setDrawerId] = useState(null) // панель заказа — открывается кликом по строке
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
  const phone = usePhone()          // ≤820px: телефонная раскладка по макету
  /* Глубокая ссылка на заказ: /orders?order=12 открывает панель заказа. Так из карточки
     человека можно попасть прямо в заказ, а не «вернуться и искать его в списке». */
  const [params] = useSearchParams()
  const deepId = params.get('order')

  /* Состояние-пилюля героя (макет .av): цикл «свободен → в работе → на паузе» + тост. */
  const [avIdx, setAvIdx] = useState(0)
  const cycleAv = () => {
    const n = (avIdx + 1) % AV_STATUS.length
    setAvIdx(n)
    show(`${t('st.status')}: ${t(AV_STATUS[n][0])}`)
  }
  /* «Посадка» карточки после смены стадии (макет .land): строка/карточка подсвечивается
     один раз после перерисовки. Таймер чистим, чтобы предыдущая подсветка не «мигала». */
  const [landId, setLandId] = useState(null)
  const landT = useRef(0)
  const markLand = (id) => {
    setLandId(id)
    clearTimeout(landT.current)
    landT.current = setTimeout(() => setLandId(null), 1200)
  }
  useEffect(() => () => clearTimeout(landT.current), [])
  /* Вода в герое: высота подъезжает через transition (макет .water height-переход),
     стартует чуть позже монтирования, чтобы анимация было видно. */
  const [waterOn, setWaterOn] = useState(false)
  useEffect(() => { const id = setTimeout(() => setWaterOn(true), 350); return () => clearTimeout(id) }, [])
  /* 12 пузырьков — детерминированные смещения, без Math.random в рендере. */
  const bubbles = useMemo(() => Array.from({ length: 12 }, (_, i) => ({
    x: 4 + ((i * 47) % 92), s: 4 + ((i * 5) % 6), d: ((i * 1.7) % 6).toFixed(1),
  })), [])
  /* Иконка «проверить снова» крутится заново на каждый клик (перемонтирование по key). */
  const [fuSpin, setFuSpin] = useState(0)

  const load = () => {
    setLoadErr(false)
    return Promise.all([
      api.orders(true).then(setOrders).catch(() => setLoadErr(true)),
      api.orderStats(6).then(setStats),
      api.pulse().then(setPulse).catch(() => {}),
      api.crmFollowups().then(setFollowups).catch(() => {}), api.crmAnalytics(6).then(setAnalytics).catch(() => {}),
    ]).catch(() => {})
  }
  useEffect(() => { load() }, [tick])
  // «+» дока на заказах открывает форму нового заказа (AppShell шлёт orders:add)
  useEffect(() => {
    const on = () => setSheet('new')
    window.addEventListener('orders:add', on)
    return () => window.removeEventListener('orders:add', on)
  }, [])
  useEffect(() => { try { localStorage.setItem('orders.layout', layout) } catch { /* приватный режим — не запоминаем */ } }, [layout])
  useEffect(() => {
    if (!deepId) return
    const id = Number(deepId)
    if (Number.isFinite(id) && id > 0) { setView('all'); setStageTab('all'); setDrawerId(id) }
  }, [deepId])

  const all = orders || []
  /* Рельс стадий (макет .rail/.sn): счётчик и сумма по каждой стадии, включая пустые —
     пустые гаснут (.has), но остаются кликабельными: это навигация по воронке. */
  const stageCounts = useMemo(() => {
    const m = {}
    for (const o of all) { const k = stageOf(o); m[k] = (m[k] || 0) + 1 }
    return m
  }, [all])
  const stageSums = useMemo(() => {
    const m = {}
    for (const o of all) { const k = stageOf(o); m[k] = (m[k] || 0) + (o.price || 0) }
    return m
  }, [all])
  const list = useMemo(() => {
    let l = all
    if (view === 'open') l = l.filter((o) => ['new', 'work', 'review'].includes(o.status))
    else if (view === 'unpaid') l = l.filter((o) => o.status !== 'cancelled' && o.status !== 'paid' && o.left > 0 && o.status !== 'new')
    if (stageTab !== 'all') l = l.filter((o) => stageOf(o) === stageTab)
    return l
  }, [all, view, stageTab])
  const openN = all.filter((o) => ['new', 'work', 'review'].includes(o.status)).length
  const unpaid = all.filter((o) => ['work', 'review', 'done'].includes(o.status)).reduce((s, o) => s + o.left, 0)
  /* Сколько заказов ждут оплаты (штуки) — та же выборка, что и фильтр «ждут оплаты»,
     чтобы число в герое и список под ним не спорили друг с другом. */
  const unpaidN = all.filter((o) => o.status !== 'cancelled' && o.status !== 'paid' && o.left > 0 && o.status !== 'new').length
  const overdue = all.filter((o) => o.overdue).length
  const priceTotal = useMemo(() => all.reduce((s, o) => s + (o.price || 0), 0), [all])
  /* Уровень воды в герое (макет .water): доля неоплаченного от общей суммы заказов —
     реальные данные, 6% пустого героя, когда ждать нечего. Считаем здесь, а не выше:
     там unpaid/priceTotal ещё не объявлены (TDZ — страница падала целиком). */
  const fillPct = unpaid > 0 && priceTotal > 0 ? Math.min(70, 24 + 46 * Math.min(1, unpaid / priceTotal)) : 6
  const unpaidShown = useCountUp(unpaid)

  const addQuick = async (e) => {
    e.preventDefault(); if (!quick.trim()) return
    try { await api.chat(T('or.seed_order', { text: quick.trim() })); setQuick(''); load(); bump() } catch (err) { show.err(err) }
  }
  const [leaveCls, leave] = useLeave()
  const setStatus = async (o, status) => {
    if (status === 'paid' && o.left > 0) return setPay(o)   // деньги не записаны — сначала оплата, полная сумма сама закроет заказ
    try { await api.updateOrder(o.id, { status }); load(); bump(); if (status === 'paid') show(t('or.paid'), '', o.title) } catch (e) { show.err(e) }
  }
  // стадия заказа меняется через CRM (старый status синхронизируется на бэке).
  // «потерян» требует причину: клик по нему открывает вопрос, а не меняет стадию сразу.
  const setStage = async (o, stage) => {
    if (stage === stageOf(o)) return
    if (stage === 'lost') return setLost(o)
    if (stage === 'paid' && o.left > 0) return setPay(o)
    try { await api.crmSetStage(o.id, stage); show(t('stage.of', { label: t(ORDER_STAGE_LABEL[stage]) }), '', o.title); markLand(o.id); load(); bump() } catch (e) { show.err(e) }
  }
  const openDrawer = (o) => setDrawerId(o.id)
  const scanFollowups = async () => { try { const r = await api.crmScanFollowups(); await load(); show(t('or.fu_updated'), r.created?.length ? t('or.fu_new', { n: r.created.length }) : t('or.fu_none')) } catch (e) { show.err(e) } }
  const remove = (o) => leave(o.id, 'leaving', async () => { await api.delOrder(o.id); show(t('or.deleted'), '', o.title); load(); bump() })
  const start = async (o, minutes = null) => { try { await api.startTimer(o?.id || null, minutes); load() } catch (e) { show.err(e) } }
  const stop = async () => { try { await api.stopTimer(); load() } catch (e) { show.err(e) } }

  const kicker = overdue ? t('or.overdue_n', { count: overdue }) : openN ? t('or.open_n', { count: openN }) : t('or.free')
  const month = stats?.months?.at(-1)?.income || 0
  const prevMonth = stats?.months?.at(-2)
  /* Счётчики воронки — одной строкой под заголовком, без тяжёлых карточек. */
  const counters = [
    { key: 'open', label: t('or.v_open'), value: openN, hint: overdue ? t('or.overdue_n', { count: overdue }) : t('or.all_ok') },
    { key: 'unpaidn', label: t('or.v_unpaid'), value: unpaidN, hint: unpaidN ? t('or.find_debtors') : t('or.all_settled') },
    unpaid
      ? { key: 'unpaid', label: t('or.v_unpaid'), value: money(unpaid), tone: 'warn', onClick: () => setView('unpaid'), tip: t('or.find_debtors') }
      : { key: 'unpaid', label: t('or.v_unpaid'), value: money(0), hint: t('or.all_settled') },
    month ? { key: 'month', label: t('or.this_month'), value: money(month), tone: 'ok', hint: prevMonth ? t('or.prev_month', { m: money(prevMonth.income) }) : t('or.first_month') } : null,
    stats?.rate ? { key: 'rate', label: t('or.rate_hour'), value: money(stats.rate), hint: stats.total_hours ? `${hours(stats.total_hours)} ${t('or.by_timer')}` : t('or.by_timer') } : null,
    stats?.avg_check ? { key: 'check', label: t('or.avg_check'), value: money(stats.avg_check), hint: stats.avg_lead_days ? t('or.lead_days', { n: stats.avg_lead_days }) : t('or.by_closed') } : null,
  ].filter(Boolean)

  /* Плитки внутри героя: все метрики, кроме неоплаченного остатка (он — ключевое число).
     Порядок — как в макете: в работе → ждут оплаты → средний чек → за месяц → ставка. */
  const HERO_CELL_ORDER = { open: 0, unpaidn: 1, check: 2, month: 3, rate: 4 }
  const heroCells = counters
    .filter((c) => c.key !== 'unpaid')
    .sort((a, b) => (HERO_CELL_ORDER[a.key] ?? 9) - (HERO_CELL_ORDER[b.key] ?? 9))

  return (
    <div id="p-ord" className={`bento-page pg space-y-6 pt-4 ${FIELD_LABEL_M}`} style={pageAcc.style}>
      <PageHead kicker={kicker} title={t('nav.orders')} />

      {/* Панель страницы (макет .tb): вид и фильтр слева, «?» и «+ заказ» справа —
          всё в одну строку над героем, как в макете. */}
      <div className="og-tb animate-rise">
        <Seg value={layout} onChange={setLayout} options={[['list', t('or.layout_list')], ['board', t('or.layout_board')]]} />
        <Seg value={view} onChange={setView} options={VIEWS.map(([v, k]) => [v, t(k)])} />
        <span className="og-tb-r">
          <button type="button" className="btn-icon outlined" aria-label={t('howto.toggle_aria')} data-tip={t('howto.title')}
            onClick={() => window.dispatchEvent(new CustomEvent('orders:howto', { detail: 'toggle' }))}><HelpCircle size={16} /></button>
          <button className="btn-primary head-primary max-[820px]:!hidden" onClick={() => setSheet('new')}><Plus size={15} /> {t('od.order')}</button>
        </span>
      </div>

      {/* Ключевое число — герой макета (.oh): заголовок «ждут оплаты», пилюля состояния
          (клик щёлкает по кругу + тост), сумма с плавным «доездом», вода внизу с волной
          и пузырьками, снизу — плитки метрик (.mini). Всё остальное — в orders-glass.css. */}
      <div className="hero-card" data-reveal>
        <div className="hc-label og-hh">
          <b>{t('or.v_unpaid')}</b>
          <button type="button" className="og-av" aria-label={`${t('st.status')}: ${t(AV_STATUS[avIdx][0])}`}
            data-tip={t('st.status')} data-tip-side="bottom" onClick={cycleAv}>
            <i style={{ background: AV_STATUS[avIdx][1], color: AV_STATUS[avIdx][1] }} aria-hidden="true" />
            <span>{t(AV_STATUS[avIdx][0])}</span>
          </button>
        </div>
        <div className="hc-big num">{money(unpaidShown || 0)}</div>
        <div className="og-water" aria-hidden="true" style={{ height: waterOn ? `${fillPct}%` : '0%' }}>
          <svg className="og-wv" viewBox="0 0 1200 40" preserveAspectRatio="none"><path d="M0,20 Q150,0 300,20 T600,20 T900,20 T1200,20 V40 H0Z" /></svg>
          <svg className="og-wv og-wv2" viewBox="0 0 1200 40" preserveAspectRatio="none"><path d="M0,20 Q150,38 300,20 T600,20 T900,20 T1200,20 V40 H0Z" /></svg>
          {bubbles.map((b, i) => <i key={i} className="og-bub" style={{ '--x': `${b.x}%`, '--s': `${b.s}px`, '--d': `${b.d}s` }} />)}
        </div>
        <div className="hm">
          {heroCells.map((c) => (
            <div key={c.key} className="min-w-0" title={c.hint || undefined}>
              <small className="trunc">{c.label}</small>
              <b className="num block truncate">{c.value}</b>
            </div>
          ))}
        </div>
      </div>

      {/* Подсказка «как это работает» на телефоне свёрнута (см. HowToOrders) и открывается
          кнопкой «?» на панели выше — её единственная точка входа. */}
      <div className="-mt-4"><HowToOrders /></div>


      {/* Панель заказов идёт ПЕРВОЙ из модалок: всё, что открывают из неё (оплата, форма,
          карточка клиента), должно оказываться поверх — порядок DOM определяет стек. */}
      <OrderDrawer oid={drawerId} reloadKey={payTick} onClose={() => setDrawerId(null)} onChanged={() => { load(); bump() }} onErr={show.err} onMsg={(msg) => show(msg)}
        onClient={(cid) => { setDrawerId(null); setPersonCard(cid) }} onEdit={(o) => setSheet(o)} onPay={(o) => setPay(o)}
        onAsk={(o) => ask(T('or.ask_seed', { title: o.title }))} timer={timer} onStartTimer={start} onStopTimer={stop} mmss={mmss} />

      <OrderSheet open={!!sheet} order={sheet && sheet !== 'new' ? sheet : null} onClose={() => setSheet(null)} onDone={(msg) => { setSheet(null); show(msg); load(); bump() }} onErr={show.err} />
      <PaySheet order={pay} onClose={() => setPay(null)} onJustClose={async (o) => { setPay(null); try { await api.updateOrder(o.id, { status: 'paid' }); show(t('or.closed'), t('or.no_income'), o.title); setPayTick((x) => x + 1); load(); bump() } catch (e) { show.err(e) } }} onDone={(r) => { setPay(null); show(t(r.order.status === 'paid' ? 'or.closed_paid' : 'or.pay_to_income'), '', r.order.title); setPayTick((x) => x + 1); load(); bump() }} onErr={show.err} />
      <Confirm open={!!del} title={t('or.del_q')} text={del ? t('or.del_text', { title: del.title }) : ''} danger onOk={() => { remove(del); setDel(null) }} onClose={() => setDel(null)} />
      <LostSheet order={lost} onClose={() => setLost(null)} onDone={async (reason) => { try { await api.crmSetStage(lost.id, 'lost', reason); show(t('od.lost_marked'), '', lost.title); setLost(null); setPayTick((x) => x + 1); load(); bump() } catch (e) { show.err(e) } }} />
      <ClientCardSheet cid={personCard} onClose={() => setPersonCard(null)} onOrder={(oid) => { setPersonCard(null); setDrawerId(oid) }} />

      {/* Задержки оплат и налог — живая строка-пульс (без макетного аналога): точки
          мигают янтарём (ожидание), клик уводит в фильтр «ждут оплаты». */}
      {pulse?.enabled && (pulse.late?.length > 0 || pulse.tax?.tax_total > 0) && (
        <div className="og-pulse animate-rise flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[13px]">
          {pulse.late.map((x) => (
            <button key={x.order_id} type="button" className="max-[820px]:min-h-[var(--tap)] flex items-center gap-1.5 text-left" onClick={() => setView('unpaid')}>
              <span className="og-pdot" style={{ background: 'var(--warn)', color: 'var(--warn)' }} />
              <span><b className="font-medium">{x.client || x.title}</b><span className="muted"> {t('or.delays', { m: money(x.left), count: x.days }) + (x.typical_days != null ? t('or.typically', { n: x.typical_days }) : '')}</span></span>
            </button>
          ))}
          {pulse.tax?.tax_total > 0 && <span className="muted">{t('or.tax', { percent: pulse.tax.percent })} ~<b className="num font-medium" style={{ color: 'var(--ink)' }}>{money(pulse.tax.tax_total)}</b>{pulse.tax.tax_expected ? <span className="faint"> {t('or.tax_expected', { m: money(pulse.tax.tax_expected) })}</span> : ''}</span>}
        </div>
      )}

      {/* Напоминания (макет .rm/.rmc): чипы с пульсирующей точкой, справа — «проверить
          снова» с иконкой, которая крутится при клике. */}
      {followups.length > 0 && (
        <Section className={sectionCls(phone)} title={t('or.followups')} i={3}
          action={<button type="button" className="pill" onClick={() => { setFuSpin((x) => x + 1); scanFollowups() }}>
            <RefreshCw key={fuSpin} size={13} className={fuSpin ? 'og-spin' : undefined} /> {t('common.retry')}
          </button>}>
          <div className="og-rm">
            {followups.slice(0, 5).map((f) => (
              <button key={f.id} type="button" className="og-rmc" onClick={() => f.order_id && setDrawerId(f.order_id)}>
                <span className="trunc">{f.text}</span>
              </button>
            ))}
          </div>
        </Section>
      )}

      {/* Стадии (макет .rail/.sn): карточка со сворачиваемыми счётчиками — цветная
          планка сверху, количество, сумма; клик фильтрует список и канбан.
          Пустые стадии гаснут, но остаются: это навигация по воронке. */}
      {orders !== null && (
        <Section className={sectionCls(phone)} title={t('stage.block')} i={4}>
        <div className="og-rail no-scrollbar" role="group" aria-label={t('stage.block')}>
          {ORDER_STAGES.map(([k, label]) => {
            const n = stageCounts[k] || 0
            const on = stageTab === k
            return (
              <button key={k} type="button"
                className={`og-sn${on ? ' on' : ''}${n ? ' has' : ''}`}
                style={{ '--k': STAGE_VAR[ORDER_STAGE_TONE[k]] || 'var(--acc)' }}
                aria-pressed={on}
                onClick={() => setStageTab(on ? 'all' : k)}>
                <span>{t(label)}</span>
                <b className="num">{n}</b>
                <small className="num">{n ? moneyShort(stageSums[k] || 0) : '—'}</small>
              </button>
            )
          })}
        </div>
      </Section>
      )}

      {orders === null
        ? (loadErr ? <ErrorState onRetry={load} /> : <ListSkeleton n={5} rowH={78} avatar={false} />)
        : layout === 'board' ? (
          <Section className={sectionCls(phone)} title={t('or.layout_board')} idx={list.length} hint={t('or.board_hint')} i={5}>
            <Board orders={list} onOpen={openDrawer} onStage={setStage} stageTab={stageTab} landId={landId} />
          </Section>
        ) : (
          <Section className={sectionCls(phone)} title={t(VIEWS.find((v) => v[0] === view)[1])} idx={list.length} i={5}>
            {list.length === 0 ? (
              <div className="animate-rise">
                {view === 'open' ? <Empty glyph="tasks" text={t('or.empty_open')} sub={t('or.empty_open_sub')} hint={t('or.empty_open_hint')} />
                  : view === 'unpaid' ? <Empty glyph="money" text={t('or.empty_unpaid')} sub={t('or.empty_unpaid_sub')} />
                    : <Empty glyph="tasks" text={t('or.empty_all')} hint={t('or.empty_all_hint')} />}
              </div>
            ) : (
              <div className="og-olr">
                  {list.map((o, i) => <Row key={o.id} o={o} k={i} onOpen={() => openDrawer(o)} onEdit={() => setSheet(o)} onPay={() => setPay(o)}
                    onDel={() => setDel(o)} onStatus={setStatus} onStart={() => start(o)} onStage={(k) => setStage(o, k)} timer={timer}
                    extra={`${leaveCls(o.id)} ${landId === o.id ? 'og-land' : ''}`} />)}
              </div>
            )}
          </Section>
        )}

      {stats && (stats.clients.length > 0 || stats.months.some((m) => m.income)) && (
        <StatsBlock stats={stats} unpaid={unpaid} timer={timer} left={left}
          onUnpaid={() => { setView('unpaid'); window.scrollTo({ top: 0, behavior: 'smooth' }) }}
          onStart={() => start(null)} onStop={stop} i={6} />
      )}

      {analytics && analytics.clients?.length > 0 && <AnalyticsBlock a={analytics} i={7} />}
    </div>
  )
}

/* Счётчики одной строкой: подпись мелкая и приглушённая, число — табличное.
   Без карточек и градиентов — просто строка цифр под заголовком (DESIGN.md: плоско, тихо).
   Элементы — <span>, а не <div>: строка подставляется в <p class="sub"> внутри PageHead.
   Используется и на странице «люди» (счётчики там свои). */
export function StatRow({ items }) {
  if (!items?.length) return null
  const toneColor = { warn: 'var(--warn)', neg: 'var(--neg)', ok: 'var(--pos)' }
  return (
    /* на телефоне счётчики в две колонки, а не «метка число подсказка» в три строки:
       иначе строка разъезжается, а сиротская точка висит сама по себе */
    <span
      className="grid w-full grid-cols-2 items-baseline gap-x-4 gap-y-3 max-[820px]:grid-cols-2 min-[821px]:!flex min-[821px]:!w-auto min-[821px]:flex-wrap min-[821px]:items-baseline min-[821px]:gap-x-5"
      style={{ color: 'var(--ink-2)' }}
    >
      {items.map((it, i) => {
        const body = (
          <>
            <span className={`faint leading-tight ${SMALL_M}`} style={{ fontSize: 'var(--fs-xs)' }}>{it.label}</span>
            <span className="num font-medium" style={{ fontSize: 'var(--fs-lg)', color: toneColor[it.tone] || 'var(--ink)' }}>{it.value}</span>
            {it.hint && <span className="faint trunc" style={{ fontSize: 'var(--fs-xs)', maxWidth: '22ch' }} title={it.hint}>{it.hint}</span>}
          </>
        )
        return (
          <span key={it.key} className="flex min-w-0 flex-col gap-0.5 min-[821px]:flex-row min-[821px]:items-baseline min-[821px]:gap-2">
            {i > 0 && <span aria-hidden="true" className="faint -ml-3 hidden self-center min-[821px]:inline">·</span>}
            {it.onClick
              ? <button type="button" onClick={it.onClick} data-tip={it.tip} className="max-[820px]:!min-h-[var(--tap)] flex min-w-0 flex-col items-start gap-0.5 rounded-lg px-2 py-1 text-left transition-colors duration-200 hover:bg-[var(--fill)] min-[821px]:flex-row min-[821px]:items-baseline min-[821px]:gap-2 min-[821px]:rounded-full" style={{ font: 'inherit' }}>{body}</button>
              : <span className="flex min-w-0 flex-col items-start gap-0.5 min-[821px]:flex-row min-[821px]:items-baseline min-[821px]:gap-2">{body}</span>}
          </span>
        )
      })}
    </span>
  )
}

/* Строка заказа — карточка списка (макет .orw): точка стадии со свечением, заголовок
    и клиент, срок/долг подписями, сумма + «не оплачен», бейдж стадии и рельс прогресса
    (StageStepper — те же 9 отрезков, что .dts в макете), одна главная кнопка
    «следующий шаг», остальное — в меню «⋯». k — порядковый № для стартовой анимации. */
function Row({ o, k = 0, onOpen, onEdit, onPay, onDel, onStart, onStage, onStatus, timer, extra = '' }) {
  const { t } = useI18n()
  const nav = useNavigate()
  const [, show] = useToast()
  const stage = stageOf(o)
  const next = NEXT_STEP[stage]
  const closed = ['paid', 'cancelled'].includes(o.status)
  const running = timer?.active && timer.order_id === o.id && timer.kind === 'focus'
  const dl = o.deadline ? (o.overdue ? t('or.dl_overdue', { date: dayLabel(o.deadline).toLowerCase() }) : o.past_due ? t('or.dl_was', { date: shortDate(o.deadline).toLowerCase() }) : o.days_left === 0 ? t('common.today') : o.days_left === 1 ? t('common.tomorrow') : t('aims.by', { date: shortDate(o.deadline).toLowerCase() })) : null
  const pct = o.price > 0 ? Math.min(100, Math.round((o.paid / o.price) * 100)) : 0
  const stop = (fn) => (e) => { e.stopPropagation(); fn() }
  const openBoard = async () => {
    try { const b = await api.get(`/api/boards/for-order/${o.id}?create=true`); nav(`/board/${b.id}`) } catch (e) { show.err(e) }
  }
  const menu = [
    o.status !== 'cancelled' && o.left > 0 && { key: 'pay', text: t('or.m_pay'), icon: <Wallet size={13} />, onClick: onPay },
    running
      ? { key: 'stop', text: t('or.m_stop_timer'), icon: <Square size={13} />, onClick: onStart }
      : { key: 'timer', text: t('or.m_timer', { n: timer?.focus_min || 25 }), icon: <Play size={13} />, onClick: onStart },
    { key: 'edit', text: t('or.m_edit'), icon: <Pencil size={13} />, onClick: onEdit },
    { key: 'ask', text: t('or.m_ask'), icon: <MessageCircle size={13} />, onClick: () => ask(T('or.ask_seed', { title: o.title })) },
    { key: 'board', text: t(o.board_id ? 'or.m_board_open' : 'or.m_board_new'), icon: <Clapperboard size={13} />, onClick: openBoard },
    stage === 'lost' && { key: 'restore', text: t('or.m_restore'), icon: <RefreshCw size={13} />, onClick: () => onStage('in_work') },
    !closed && { key: 'cancel', text: t('or.m_cancel'), icon: <Square size={13} />, onClick: () => onStatus(o, 'cancelled') },
    !closed && { key: 'del', text: t('or.m_del'), icon: <Trash2 size={13} />, onClick: onDel, danger: true },
  ]
  const dlTone = o.overdue ? 'neg' : (!o.past_due && o.days_left != null && o.days_left <= 2) ? 'warn' : 'faint'
  return (
    <Swipe onLeft={!closed ? onDel : undefined} onRight={next ? () => onStage(next.stage) : undefined} rightLabel={next ? t(next.text) : t('common.done')}>
      <div className={`row-slide ${extra} ${closed ? 'opacity-60' : ''}`} style={{ '--k': k }}>
        <div role="button" tabIndex={0} aria-label={t('or.open_order', { title: o.title })} onClick={onOpen}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}
          className="row wide-row cursor-pointer"
          style={o.overdue ? { background: 'var(--neg-soft)' } : undefined}>
          <span aria-hidden="true" className="og-sd h-2 w-2 shrink-0 rounded-full" style={{ background: o.overdue ? 'var(--neg)' : (STAGE_VAR[ORDER_STAGE_TONE[stage]] || 'var(--acc)'), color: o.overdue ? 'var(--neg)' : (STAGE_VAR[ORDER_STAGE_TONE[stage]] || 'var(--acc)') }} />
          <div className="min-w-0 flex-[1_1_220px]">
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2.5">
              <span className="clamp-2 min-w-0 font-medium" style={{ fontSize: 'var(--fs-lg)' }} title={o.title}>{o.title}</span>
              {o.client && <span className="muted min-w-0 truncate" style={{ fontSize: 'var(--fs-sm)' }}>{o.client}</span>}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1" style={{ fontSize: 'var(--fs-xs)' }}>
              {dl && <span className={`flex items-center gap-1 ${dlTone}`}><Clock size={11} /> {dl}</span>}
              {o.price > 0 && o.left > 0 && <span className="muted">{t('or.left', { m: money(o.left) })}</span>}
              {o.price > 0 && o.paid > 0 && <span className="faint num">{t('or.paid_pct', { pct })}</span>}
              {o.hours > 0 && <span className={o.pulse?.warn ? 'warn' : 'faint'}>{o.hours}{o.rate ? ` · ${money(o.rate)}/${T('unit.hour')}` : ''}</span>}
              {running && <span className="accent">{t('or.timer_running')}</span>}
            </div>
          </div>
          {/* Колонка суммы фиксированной ширины: иначе «сдан»/«оплачен» прыгают по горизонтали. */}
          <div className="num shrink-0 text-right sm:w-[132px]" style={{ fontSize: 'var(--fs-lg)' }}>
            <div className="font-medium">{o.price ? money(o.price) : <span className="faint" style={{ fontSize: 'var(--fs-sm)' }}>{t('or.no_amount')}</span>}</div>
            {o.price > 0 && o.paid === 0 && !closed && o.status !== 'new' && <div className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{t('status_unpaid')}</div>}
          </div>
          <StageStepper compact stage={stage} onStage={onStage} revisions={o.revisions} className="max-w-full shrink-0 overflow-x-auto no-scrollbar sm:w-[136px]" />
          <div className="flex shrink-0 items-center gap-1.5">
            {next ? (
              <button type="button" className="btn-primary btn-sm" data-tip={next.tip} onClick={stop(() => onStage(next.stage))}>
                <Check size={13} /> {t(next.text)}
              </button>
            ) : <span className="badge pos shrink-0">{t('common.done')}</span>}
            {/* Меню «⋯» в RowMenu по умолчанию 28px; на тач-экране поднимаем до зоны нажатия. */}
            <MenuButton items={menu} ariaLabel={t('or.more_aria', { title: o.title })} className="max-[820px]:!h-11 max-[820px]:!w-11" />
          </div>
        </div>
      </div>
    </Swipe>
  )
}

/* ------------------------------------------------------- канбан и закрытые стадии
   Закрытые стадии («сдан», «оплачен», «потерян») растут без ограничений: год работы — это
   сотни карточек, и доска от этого только тяжелее. Поэтому в них по умолчанию видны
   BOARD_LIMIT самых свежих заказов, дальше — кнопка «показать ещё» по BOARD_PAGE за нажатие
   (порциями, а не всё сразу: 200+ карточек за одно нажатие подвешивают страницу).
   Активные стадии показываются целиком — их всегда мало, и они должны быть видны. */
const BOARD_CLOSED = ['delivered', 'paid', 'lost']
const BOARD_LIMIT = 10   // карточек в свёрнутой закрытой колонке
const BOARD_PAGE = 30    // сколько добавляет «показать ещё»
const BOARD_MORE_KEY = 'orders.board.more.v1'

/* Порядок закрытых карточек — по свежести закрытия заказа, а не по дате создания:
   у «оплачен» это дата оплаты, у «сдан» — дата сдачи, у «потерян» — последний контакт
   (если контакта не было — дата создания). Свежие сверху: недавно закрытое и нужно вспомнить первым. */
const closedAt = (o) => {
  let max = 0
  for (const k of ['paid_at', 'done_at', 'last_contact_at', 'created_at']) {
    const ms = o?.[k] ? new Date(o[k]).getTime() : 0
    if (ms > max) max = ms
  }
  return max
}

/* Раскрытость закрытых колонок живёт в localStorage (по стадии): перерисовка доски,
   смена вкладки и перезагрузка страницы не должны сбрасывать то, что уже открыли.
   По умолчанию свёрнуто. Ключи читаем только из своего списка стадий. */
function readBoardMore() {
  try {
    const raw = JSON.parse(localStorage.getItem(BOARD_MORE_KEY) || '{}')
    if (!raw || typeof raw !== 'object') return {}
    const out = {}
    for (const k of BOARD_CLOSED) {
      const n = Math.round(Number(raw[k]))
      if (Number.isFinite(n) && n > BOARD_LIMIT) out[k] = n
    }
    return out
  } catch { return {} }
}

/* Канбан CRM: нативный HTML5 drag&drop (десктоп) + список «стадия» на каждой карточке
   (альтернатива без перетаскивания — на телефоне жест не нужен).
   Колонка показывает стадию, количество и сумму заказов; цвет — по смыслу из DESIGN.md.
   Счётчик и сумма в шапке считаются по ВСЕМ заказам стадии, а не по видимым карточкам,
   иначе цифры в колонке врали бы относительно сводки и аналитики. */
function Board({ orders, onOpen, onStage, stageTab = 'all', landId = null }) {
  const { t } = useI18n()
  const [drag, setDrag] = useState(null)
  const [over, setOver] = useState(null)
  const [more, setMore] = useState(readBoardMore)
  useEffect(() => { try { localStorage.setItem(BOARD_MORE_KEY, JSON.stringify(more)) } catch { /* приватный режим — не запоминаем */ } }, [more])
  // сколько карточек показывать в стадии: активные — все, закрытые — до раскрытой порции
  const shownOf = (k, total) => (BOARD_CLOSED.includes(k) ? Math.min(Math.max(more[k] || BOARD_LIMIT, BOARD_LIMIT), total) : total)
  const setShown = (k, n) => setMore((m) => ({ ...m, [k]: n }))
  const cols = useMemo(() => {
    const m = {}
    ORDER_STAGES.forEach(([k]) => { m[k] = [] })
    orders.forEach((o) => { (m[stageOf(o)] || (m[stageOf(o)] = [])).push(o) })
    for (const k of BOARD_CLOSED) if (m[k]) m[k].sort((a, b) => closedAt(b) - closedAt(a) || b.id - a.id)
    return m
  }, [orders])
  // сводка над доской: сколько закрытых заказов прямо сейчас не видно
  const hidden = useMemo(
    () => BOARD_CLOSED.reduce((s, k) => s + Math.max(0, (cols[k]?.length || 0) - shownOf(k, cols[k]?.length || 0)), 0),
    [cols, more],   // eslint-disable-line react-hooks/exhaustive-deps
  )
  // «показать» из сводки: ещё одна порция в каждой закрытой колонке, а не всё сразу
  const showNextPage = () => setMore((m) => {
    const next = { ...m }
    for (const k of BOARD_CLOSED) {
      const total = cols[k]?.length || 0
      if (total > shownOf(k, total)) next[k] = Math.min(shownOf(k, total) + BOARD_PAGE, total)
    }
    return next
  })
  return (
    <div className="kanban-scroll pb-3">
      {/* сводка над колонками: сколько закрытых заказов спрятано прямо сейчас. Клик открывает
          ещё одну порцию в каждой закрытой стадии, дальше — кнопки в самих колонках. */}
      {hidden > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px]">
          <button type="button" className="btn-soft" onClick={showNextPage}
            aria-label={t('or.board_hidden_aria', { count: hidden })} data-tip={t('or.board_hint_limited')}>
            <ChevronDown size={13} /> {t('or.board_hidden', { count: hidden })}
          </button>
          <span className="faint text-[12px]">{t('or.board_hint_limited')}</span>
        </div>
      )}
      <div className="og-kb flex gap-3" style={{ minWidth: 'max-content' }}>
        {ORDER_STAGES.map(([k, label]) => {
          const tone = ORDER_STAGE_TONE[k]
          const col = cols[k] || []
          const sum = col.reduce((s, o) => s + (o.price || 0), 0)
          // в закрытой стадии видно не всё: 10 по умолчанию, дальше порциями по 30
          const shown = shownOf(k, col.length)
          const rest = col.length - shown
          const kcolor = STAGE_VAR[tone] || 'var(--acc)'
          return (
            <div key={k} className={`og-kcol w-[262px] shrink-0 ${stageTab === k ? 'hl' : ''} ${over === k ? 'ovr' : ''}`}
              style={{ '--k': kcolor }}
              onDragOver={(e) => { e.preventDefault(); setOver(k) }}
              onDragLeave={() => setOver((x) => (x === k ? null : x))}
              onDrop={(e) => { e.preventDefault(); const d = drag; setOver(null); setDrag(null); if (d) onStage(d, k) }}>
              <div className="og-kh" aria-label={t('or.column_aria', {
                label: t(label), n: col.length, sum: sum > 0 ? t('or.column_sum', { m: money(sum) }) : '',
              })}>
                <span className="truncate text-[13px] font-medium">{t(label)}</span>
                <span className="num shrink-0 text-[12px]">
                  <span className={col.length ? 'text-[var(--ink-2)]' : 'faint'}>{col.length}</span>
                  {sum > 0 && <span className="faint"> · {moneyShort(sum)}</span>}
                </span>
              </div>
              <div className="og-kz space-y-2" style={{ minHeight: 56 }}>
                {col.slice(0, shown).map((o) => (
                  <div key={o.id} role="button" tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(o) } }}
                    draggable
                    onDragStart={(e) => { try { e.dataTransfer.setData('text/plain', String(o.id)) } catch { /* ignore */ } e.dataTransfer.effectAllowed = 'move'; setDrag(o) }}
                    onDragEnd={() => { setDrag(null); setOver(null) }}
                    onClick={() => onOpen(o)}
                    aria-label={t('or.open_order', { title: o.title })}
                    title={o.title}
                    className={`og-kcard cursor-grab px-3 py-2.5 active:cursor-grabbing ${drag?.id === o.id ? 'dg' : ''} ${o.overdue ? 'og-over' : ''} ${landId === o.id ? 'land' : ''}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-[13.5px] font-medium">{o.title}</div>
                        {o.client && <div className="muted truncate text-[12px]">{o.client}</div>}
                      </div>
                      {o.deadline && <span className={`num shrink-0 text-[12px] ${o.overdue ? 'neg' : 'faint'}`}>{shortDate(o.deadline)}</span>}
                    </div>
                    <div className="mt-1.5 flex items-center justify-between gap-2 text-[12px]">
                      <span className="muted num">{o.price ? money(o.price) : '—'}</span>
                      {o.left > 0 && o.status !== 'new' && <span className="faint num">{t('or.debt', { m: money(o.left) })}</span>}
                      {o.revisions > 0 && <span className="warn">{t('or.rev', { n: o.revisions })}</span>}
                    </div>
                    {o.price > 0 && (
                      <div className="og-pbar mt-1.5 h-1 overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
                        <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.round((o.paid / o.price) * 100))}%`, background: 'var(--acc)' }} />
                      </div>
                    )}
                    <div className="mt-2 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                      <select className="input !h-8 min-w-0 flex-1 !text-[12.5px]" value={stageOf(o)} onChange={(e) => onStage(o, e.target.value)}
                        aria-label={t('or.stage_aria', { title: o.title })} data-tip={t('stage.aria')}>
                        {ORDER_STAGES.map(([sk, sl]) => <option key={sk} value={sk}>{t(sl)}</option>)}
                      </select>
                    </div>
                  </div>
                ))}
                {col.length === 0 && (
                  <div className="og-kp rounded-xl px-3 py-4 text-center text-[12px] faint" style={{ border: '1px dashed var(--line)' }}>
                    {t('or.drop_here')}
                  </div>
                )}
                {/* крупная кнопка во всю ширину колонки: на телефоне зона нажатия ≥44px (см. index.css, .btn) */}
                {rest > 0 && (
                  <button type="button" className="btn-soft w-full" data-tip={t('or.board_more_tip')}
                    aria-label={t('or.board_more_aria', { count: rest, label: t(label) })}
                    onClick={() => setShown(k, Math.min(shown + BOARD_PAGE, col.length))}>
                    <ChevronDown size={13} /> {t('or.board_more', { n: rest })}
                  </button>
                )}
                {rest === 0 && shown > BOARD_LIMIT && (
                  <button type="button" className="btn-ghost w-full"
                    aria-label={t('or.board_collapse_aria', { label: t(label) })} onClick={() => setShown(k, BOARD_LIMIT)}>
                    <ChevronUp size={13} /> {t('or.board_collapse')}
                  </button>
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
  const { t } = useI18n()
  const [reason, setReason] = useState('')
  useEffect(() => { setReason('') }, [order?.id])
  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={!!order} onClose={onClose} title={t('or.mark_lost')} sub={order ? `«${order.title}»` : ''}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (reason.trim()) onDone(reason.trim()) }}>
        <Field label={t('or.why_lost')} hint={t('or.why_lost_hint')}>
          <input autoFocus className="input" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder={t('or.why_lost_ph')} aria-label={t('or.why_lost')} />
        </Field>
        <div className="muted text-[12.5px]">{t('or.lost_note')}</div>
        <div className="flex gap-2">
          <button className="btn-primary" disabled={!reason.trim()} type="submit">{t('or.mark_lost')}</button>
          <button type="button" className="btn-ghost" onClick={onClose}>{t('common.cancel')}</button>
        </div>
      </form>
    </Sheet>
  )
}

/* Карточка клиента CRM: стадия клиента (отдельная сущность!), LTV, средний чек, долг,
    источник, теги, контакт, следующий шаг с датой, история заказов. */
export function ClientCardSheet({ cid, onClose, onOrder }) {
  const { t } = useI18n()
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
    <Sheet bodyClass={FIELD_LABEL_M} open={!!cid} onClose={onClose} wide title={d?.client?.name || t('graph.one_client')} sub={d?.source ? t('mem.source', { what: d.source }) : ''}>
      {!d ? <ListSkeleton n={3} rowH={40} avatar={false} /> : (
        <div className="space-y-5 text-[13px]">
          <section>
            <div className="label mb-1.5">{t('or.cc_stage_note')}</div>
            <ClientStageSelect view={d.stage} onView={(v) => setD({ ...d, stage: v })} onErr={show.err} label={t('cstage.for', { name: d.client?.name || '' })} />
            <ClientStageNote view={d.stage} />
          </section>
          <section className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
            <div><div className="label">LTV</div><div className="num mt-0.5 pos">{money(d.ltv)}</div></div>
            <div><div className="label">{t('or.avg_check')}</div><div className="num mt-0.5">{d.avg_check ? money(d.avg_check) : '—'}</div></div>
            <div><div className="label">{t('or.cc_debt')}</div><div className={`num mt-0.5 ${d.debt > 0 ? 'warn' : ''}`}>{money(d.debt)}</div></div>
            <div><div className="label">{t('or.cc_orders')}</div><div className="num mt-0.5">{d.orders_count}</div></div>
          </section>
          <section className="grid gap-2 sm:grid-cols-2">
            <div><div className="label mb-1">{t('or.cc_source')}</div>
              <input className="input" defaultValue={d.source} placeholder={t('or.cc_source_ph')} aria-label={t('or.cc_source')} onBlur={(e) => e.target.value !== d.source && save({ source: e.target.value })} /></div>
            <div><div className="label mb-1">{t('or.cc_last')}</div>
              <div className="mt-2">{d.last_contact_at ? dayLabel(d.last_contact_at) : '—'}</div></div>
          </section>
          {d.tags?.length > 0 && <div className="flex flex-wrap gap-1.5">{d.tags.map((x) => <span key={x} className="chip on">{x}</span>)}</div>}
          <section>
            <div className="label mb-1">{t('next_step.title')}</div>
            <div className="flex flex-wrap items-center gap-2">
              <input className="input min-w-[180px] flex-1" value={step} onChange={(e) => setStep(e.target.value)} placeholder={t('next_step.ph')} aria-label={t('next_step.aria')} />
              <input type="date" className="input !w-[160px]" value={stepAt} onChange={(e) => setStepAt(e.target.value)} aria-label={t('next_step.date')} />
              <button className="btn-soft" disabled={step === (d.next_step || '') && stepAt === (d.next_step_at ? toLocalISO(new Date(d.next_step_at)).slice(0, 10) : '')} onClick={saveStep} aria-label={t('next_step.save')}>{t('common.save')}</button>
            </div>
            {err && <div className="neg mt-1 text-[12px]">{err}</div>}
            <div className="faint mt-1 text-[12px]">{d.next_step_at ? t('or.cc_was', { when: dayLabel(d.next_step_at) }) : t('or.cc_date_hint')}</div>
          </section>
          <section>
            <div className="label mb-1.5">{t('or.cc_history')}</div>
            <div className="rule">
              {d.orders.map((o) => (
                <button key={o.id} type="button" className="row w-full !py-1.5 text-left" onClick={() => onOrder?.(o.id)}>
                  <span className="min-w-0 truncate">{o.title} <span className="faint">· {t(ORDER_STAGE_LABEL[stageOf(o)])}</span></span>
                  <span className="num shrink-0">{o.price ? money(o.price) : '—'}{o.left > 0 ? <span className="faint"> · {t('or.debt', { m: money(o.left) })}</span> : ''}</span>
                </button>
              ))}
            </div>
            {!d.orders.length && <div className="faint text-[12px]">{t('or.cc_no_orders')}</div>}
          </section>
          {d.activity?.length > 0 && <section>
            <div className="label mb-1.5">{t('mem.t_timeline')}</div>
            <div className="max-h-[180px] space-y-1 overflow-y-auto">{d.activity.map((a) => <div key={a.id} className="muted text-[12.5px]"><span className="faint num">{dayLabel(a.created_at).toLowerCase()}</span> {a.text}</div>)}</div>
          </section>}
        </div>
      )}
    </Sheet>
  )
}

/* Аналитика CRM: конверсия воронки и топ клиентов (read-only).
   Воронка — горизонтальные полосы (.fr2/.fb макета), цвет стадии смысловой
   (зелёный = оплачено/сдано, янтарь = ждём, розовый = потеряно), клиенты —
   строки (.kv: имя + сколько заказов слева, выручка справа), снизу — конверсия. */
const TONE_COLOR = { warn: 'var(--warn)', pos: 'var(--pos)', neg: 'var(--neg)' }
function AnalyticsBlock({ a, i = 0 }) {
  const { t } = useI18n()
  const phone = usePhone()
  const max = Math.max(1, ...a.funnel.map((f) => f.count))
  // полосы «дорастают» до значения через transition — как в макете (.fb width)
  const [grown, setGrown] = useState(false)
  useEffect(() => { const id = setTimeout(() => setGrown(true), 60); return () => clearTimeout(id) }, [])
  return (
    <Section className={sectionCls(phone)} title={t('or.an_title')} hint={t('or.an_hint')} i={i}>
      <div className="og-fun">
        {a.funnel.map((f) => (
          <div key={f.stage} className="og-fr2">
            <span className="muted trunc">{t.sv(f.label) || f.label}</span>
            <div className="og-fb">
              <i className="og-fbi" style={{ '--k': TONE_COLOR[ORDER_STAGE_TONE[f.stage]] || 'var(--acc)', width: grown ? `${Math.round((f.count / max) * 100)}%` : '0%' }} />
            </div>
            <b className="num">{f.count}</b>
          </div>
        ))}
      </div>
      <div className="og-tc mt-4">
        {a.top.map((c) => (
          <div key={c.client_id ?? 'none'} className="og-kv">
            <span className="min-w-0 trunc">{c.client}<small>{t('or.cc_orders_n', { count: c.orders })}</small></span>
            <b className={`num ${c.revenue > 0 ? 'pos' : 'faint'}`}>{money(c.revenue)}</b>
          </div>
        ))}
      </div>
      <div className="muted mt-3 text-[12px]">{t('or.an_foot', { conv: a.conversion, won: a.won, total: a.total }) + (a.avg_check ? t('or.an_avg', { m: money(a.avg_check) }) : '')}</div>
    </Section>
  )
}

/* «Как идут дела» (макет .mc/.bz): столбики дохода и фокуса растут от 3px до значения
   после монтирования; в текущем месяце рядом со столбиком дохода — пунктирный
   «ждём оплаты» (реальный неоплаченный остаток). Рядом с фокусом — пилюля таймера
   (та же /api/orders/timer, что в строке заказа): запуск и стоп одним нажатием. */
function StatsBlock({ stats, unpaid = 0, onUnpaid, timer = null, left = 0, onStart, onStop, i = 0 }) {
  const { t } = useI18n()
  const phone = usePhone()
  const [more, setMore] = useState(false)
  const [grown, setGrown] = useState(false)
  useEffect(() => { const id = setTimeout(() => setGrown(true), 60); return () => clearTimeout(id) }, [])
  const max = Math.max(1, ...stats.months.map((m) => m.income))
  const maxF = Math.max(1, ...stats.focus_days.map((d) => d.min))
  const lastMonth = stats.months.at(-1)?.month
  const h = (v, m) => `${grown ? Math.min(96, Math.max(3, (v / m) * 92)) : 3}px`
  return (
    <Section className={sectionCls(phone)} title={t('or.st_title')} hint={t('or.st_hint')} i={i}>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <div>
          <div className="label mb-4">{t('or.st_income')}</div>
          <div className="flex h-[120px] items-end gap-2">
            {stats.months.map((m) => {
              const cur = m.month === lastMonth
              return (
                <div key={m.month} className="group flex flex-1 flex-col items-center gap-1.5">
                  <div className="num text-[12px] opacity-0 transition group-hover:opacity-100">{m.income ? moneyShort(m.income) : ''}</div>
                  <div className="og-bz">
                    {cur && unpaid > 0 && <div className="og-gh" style={{ height: h(unpaid, max) }} title={t('or.st_awaiting', { m: money(unpaid) })} aria-hidden="true" />}
                    <div className={`og-b ${m.income ? 'og-p' : 'og-zero'}`} style={{ height: h(m.income, max) }} />
                  </div>
                  <div className="faint num text-[12px]">{m.month.slice(5)}</div>
                </div>
              )
            })}
          </div>
        </div>
        <div>
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1.5">
            <div className="label">{t('or.st_focus')}</div>
            <span className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5 text-[12px]">
              <span className="muted">{timer?.active ? t('od.timer_running', { left: mmss(left) }) : stats.week_load_h ? t('or.st_week', { h: hours(stats.week_load_h) }) : t('or.st_no_timer')}</span>
              <button type="button" className="pill og-tmr" onClick={timer?.active ? onStop : onStart}>
                {timer?.active ? <><Square size={12} /> {t('pomo.stop_short')}</> : <><Play size={12} /> {t('pomo.start_short')}</>}
              </button>
            </span>
          </div>
          <div className="flex h-[120px] items-end gap-1">
            {stats.focus_days.map((d) => (
              <div key={d.date} className="flex flex-1 flex-col items-center gap-1.5" title={t('or.st_day', { date: `${d.date.slice(8)}.${d.date.slice(5, 7)}`, min: d.min })}>
                <div className={`og-b ${d.min ? 'og-f' : 'og-zero'}`} style={{ height: h(d.min, maxF) }} />
                <div className="faint num text-[12px]">{d.date.slice(8)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
      {stats.clients.length > 0 && (
        <div className="mt-5">
          <button className="max-[820px]:min-h-[var(--tap)] cluster text-left" onClick={() => setMore((v) => !v)}>
            <span className="label">{t('or.st_clients', { n: stats.clients.length })}</span>
            {more ? <ChevronUp size={13} className="faint" /> : <ChevronDown size={13} className="faint" />}
          </button>
          {more && (
            <div className="rule mt-2 animate-rise">
              {stats.clients.map((c) => (
                <div key={c.client} className="row">
                  <div className="min-w-0 flex-1"><div className="truncate text-[14px] font-medium">{c.client}</div><div className="muted text-[12px]">{t('or.cc_orders_n', { count: c.orders }) + (c.total ? ` ${t('or.on', { m: money(c.total) })}` : '') + (c.open ? ` · ${t('tk.open_n', { n: c.open })}` : '') + (c.hours ? ` · ${hours(c.hours)}` : '') + (c.rate ? ` · ${money(c.rate)}/${T('unit.hour')}` : '')}</div></div>
                  <div className="num text-right">
                    {c.paid > 0 ? <div className="text-[14px] font-medium">{money(c.paid)} <span className="faint text-[12px] font-normal">{t('or.st_received')}</span></div> : <div className="faint text-[12.5px]">{t('or.st_no_pays')}</div>}
                    {c.unpaid > 0 && <button type="button" className="warn text-[12px]" onClick={onUnpaid}>{t('or.st_awaiting', { m: money(c.unpaid) })}</button>}
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
const NEW_STAGES = [['lead', 'crm.stage_lead'], ['negotiation', 'crm.stage_negotiation'], ['spec', 'crm.stage_spec'], ['in_work', 'crm.stage_in_work'], ['revisions', 'crm.stage_revisions'], ['delivered', 'crm.stage_delivered']]

const blank = { title: '', price: '', client: '', deadline: '', notes: '', estimate_h: '', stage: 'in_work', done: false, paid: '' }
export function OrderSheet({ open, order, onClose, onDone, onErr }) {
  const { t } = useI18n()
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
    const q = f.title.trim()
    if (q.length < 4) { setHint(null); return }
    let on = true
    const id = setTimeout(() => {
      api.ordersSuggest(q).then((s) => { if (on) setHint(s && s.count ? s : null) }).catch(() => {})
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
      if (oid && f.done && paid > 0) { try { await api.payOrder(oid, paid, { note: t('or.pay_on_create') }) } catch { /* покажем тост */ } }
      onDone(t(order ? 'or.updated' : f.done ? 'or.added_delivered' : 'or.added'))
    } catch (err) { onErr(err) }
  }
  const toggleDone = (v) => setF({ ...f, done: v, stage: v ? 'delivered' : f.stage === 'delivered' ? 'in_work' : f.stage })
  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={t(order ? 'od.order' : 'or.new_order')} sub={order ? undefined : t('or.new_order_sub')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('or.what_do')}><input autoFocus className="input !text-[19px] !font-medium" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required placeholder={t('or.what_do_ph')} /></Field>
        {hint && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl px-3 py-2 text-[12.5px]" style={{ background: 'var(--sf2)' }}>
            <span className="muted">{t('or.similar', { what: hint.sample?.slice(0, 2).join(', ') })}</span>
            {hint.price ? <span>{t('or.usually', { m: money(hint.price) })}</span> : null}
            {hint.hours ? <span className="muted">≈{hint.hours} {t('unit.hour')}{hint.rate ? ` · ${money(hint.rate)}/${T('unit.hour')}` : ''}</span> : null}
            <button type="button" className="btn-ghost btn-sm ml-auto" onClick={() => setF((x) => ({ ...x, ...(hint.price ? { price: String(hint.price) } : {}), ...(hint.hours ? { estimate_h: String(hint.hours) } : {}) }))}>{t('or.apply')}</button>
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label={t('common.amount')}><Money value={f.price} onChange={(v) => setF({ ...f, price: v })} /></Field>
          <Field label={t('graph.one_client')}><input className="input" list="clients-list" value={f.client} onChange={(e) => setF({ ...f, client: e.target.value })} placeholder={t('or.client_ph')} /><datalist id="clients-list">{clients.map((c) => <option key={c.id} value={c.name} />)}</datalist></Field>
          <Field label={t('od.deadline')}><DateTimeField value={f.deadline} onChange={(v) => setF({ ...f, deadline: v })} /></Field>
          <Field label={t('or.hours_plan')} hint={t('or.time_plan')}><input type="number" min="0" step="0.5" className="input num" value={f.estimate_h} onChange={(e) => setF({ ...f, estimate_h: e.target.value })} placeholder="8" /></Field>
        </div>

        {/* чекбокс вместо непонятной подсказки про «старый заказ»: ставит «сдан» и открывает поле оплаты */}
        <label className="flex min-h-[var(--tap)] cursor-pointer items-center gap-2.5 text-[13.5px]">
          <input type="checkbox" className="h-5 w-5 shrink-0 accent-[var(--acc)]" checked={f.done} onChange={(e) => toggleDone(e.target.checked)} />
          <span>{t('or.already_done')}</span>
        </label>
        {f.done && (
          <Field label={t('or.already_paid')} hint={t('or.later')}>
            <Money value={f.paid} onChange={(v) => setF({ ...f, paid: v })} placeholder="0" />
          </Field>
        )}

        {!f.done && (
          <Field label={t('stage.block')} hint={t('or.crm_hint')}>
            <Pills value={f.stage} onChange={(s) => setF({ ...f, stage: s })} options={NEW_STAGES.map(([k, l]) => [k, t(l)])} />
          </Field>
        )}
        <Field label={t('od.notes_spec')}><textarea className="input min-h-[84px]" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder={t('or.notes_ph')} /></Field>
        <button className="btn-primary btn-lg w-full">{t(order ? 'common.save' : 'common.add')}</button>
      </form>
    </Sheet>
  )
}

function newPaymentKey() {
  try { if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID() } catch { /* старый браузер — ниже запасной вариант */ }
  return `pay-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function PaySheet({ order, onClose, onDone, onErr, onJustClose }) {
  const { t } = useI18n()
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [accounts, setAccounts] = useState([])
  const [account, setAccount] = useState('')
  const [date, setDate] = useState('')
  // Ключ идемпотентности ОДИН на открытую форму: двойной клик по «записать» уходит с тем же
  // ключом, сервер вернёт уже записанную операцию и второго дохода не появится (P1 ревью A/B).
  const [payKey, setPayKey] = useState('')
  useEffect(() => { if (order) { setAmount(order.left ? String(order.left) : ''); setNote(''); setDate(toLocalISO(new Date()).slice(0, 10)); setPayKey(newPaymentKey()); api.accounts().then((a) => { setAccounts(a); setAccount(a.find((x) => x.is_main)?.name || a[0]?.name || '') }).catch(() => {}) } }, [order])
  const submit = async (e) => {
    e.preventDefault()
    const n = Number(String(amount).replace(/\s/g, '').replace(',', '.'))
    if (!n || n <= 0) return onErr(new Error(t('or.amount_zero')))
    const today = toLocalISO(new Date()).slice(0, 10)
    try { onDone(await api.payOrder(order.id, n, { note: note || null, account: account || null, date: date && date !== today ? `${date}T12:00:00` : null, idem_key: payKey || null })) } catch (err) { onErr(err) }
  }
  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={!!order} onClose={onClose} title={t('or.pay_title')} sub={order ? `«${order.title}»${order.left ? ` · ${t('or.left', { m: money(order.left) })}` : ''}` : ''}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('common.amount')}><Money value={amount} onChange={setAmount} big autoFocus /></Field>
        {order?.left > 0 && <div className="flex flex-wrap gap-1.5">
          {[0.3, 0.5, 1].map((k) => <button type="button" key={k} className="chip" onClick={() => setAmount(String(Math.round(order.left * k)))}>{k === 1 ? t('common.all') : `${k * 100}%`} · {money(Math.round(order.left * k))}</button>)}
        </div>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label={t('or.to_account')}><select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>{accounts.filter((a) => a.kind !== 'debt_only').map((a) => <option key={a.id} value={a.name}>{a.name}</option>)}</select></Field>
          <Field label={t('common.comment')}><input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('or.pay_ph')} /></Field>
          <Field label={t('common.date')} hint={t('or.pay_date_hint')}><input type="date" className="input" value={date} max={toLocalISO(new Date()).slice(0, 10)} onChange={(e) => setDate(e.target.value)} /></Field>
        </div>
        <div className="muted text-[12.5px]">{t('or.pay_note')}</div>
        <button className="btn-primary btn-lg w-full">{t('or.record')}</button>
        {onJustClose && <button type="button" className="btn-ghost w-full" onClick={() => onJustClose(order)}>{t('or.pay_already')}</button>}
      </form>
    </Sheet>
  )
}