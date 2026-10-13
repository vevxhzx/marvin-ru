/* MOrders — мобильные заказы. Только живые данные через lib/api.js:
   GET /api/orders, /api/orders/stats, /api/orders/pulse; оплаты/стадии —
   POST /api/orders/{id}/payments, PUT /api/crm/orders/{id}/stage. Кит из ../ui.jsx. */
import { useEffect, useMemo, useState } from 'react'
import { CircleHelp, Clock } from 'lucide-react'
import { api, money, shortDate } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { NEXT_STEP, ORDER_STAGES, ORDER_STAGE_LABEL, stageOf } from '../../lib/crm'
import { Avatar, BigMoney, Card, Chip, MEmpty, MLoadError, MLoading, Pill, ScreenTitle, Segmented } from '../ui.jsx'

const initialsOf = (s) => (s || '?').split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || '').join('') || '?'
const hueOf = (s) => [...String(s || '')].reduce((a, c) => a + c.charCodeAt(0), 0) % 6
const isOpen = (o) => ['new', 'work', 'review'].includes(o.status)
const needsPay = (o) => o.status !== 'cancelled' && o.status !== 'paid' && (o.left || 0) > 0 && o.status !== 'new'

function payMeta(o) {
  if (o.status === 'paid' || (o.price > 0 && (o.left || 0) <= 0)) return { tone: 'green', key: 'm.pay_full' }
  if ((o.paid || 0) > 0) return { tone: 'amber', key: 'm.pay_part' }
  return { tone: 'gray', key: 'm.pay_none' }
}

export default function MOrders() {
  const { t } = useI18n()
  const [orders, setOrders] = useState(null)
  const [stats, setStats] = useState(null)
  const [pulse, setPulse] = useState(null)
  const [err, setErr] = useState(null)
  const [mode, setMode] = useState('list')
  const [filter, setFilter] = useState('work')
  const [free, setFree] = useState(true)
  const [toastMsg, setToastMsg] = useState(null)

  const load = () => {
    setErr(null)
    return Promise.all([
      api.orders(true).then((l) => setOrders(l || [])).catch(() => setErr(true)),
      api.orderStats(6).then(setStats).catch(() => {}),
      api.pulse().then(setPulse).catch(() => {}),
    ])
  }
  useEffect(() => { load() }, [])

  const toast = (text) => {
    setToastMsg(text)
    window.clearTimeout(toast._t)
    toast._t = window.setTimeout(() => setToastMsg(null), 3200)
  }

  const all = orders || []
  const inWork = useMemo(() => all.filter(isOpen), [all])
  const awaiting = useMemo(() => all.filter(needsPay), [all])
  const list = filter === 'work' ? inWork : filter === 'await' ? awaiting : all
  const owedTotal = useMemo(() => awaiting.reduce((s, o) => s + (o.left || 0), 0), [awaiting])
  const month = stats?.months?.at(-1)?.income || 0
  const nearest = useMemo(() => {
    const ds = awaiting.filter((o) => o.deadline).sort((a, b) => new Date(a.deadline) - new Date(b.deadline))
    return ds[0] || null
  }, [awaiting])

  const act = async (fn, okMsg) => {
    try { await fn(); toast(okMsg); load() } catch (e) { toast(String(e?.message || e)) }
  }
  const payFull = (o) => act(() => api.payOrder(o.id, o.left), t('m.pay_done'))
  const toStage = (o, stage) => act(() => api.crmSetStage(o.id, stage), t('m.stage_done', { what: t(ORDER_STAGE_LABEL[stage] || stage) }))

  if (err) {
    return <MLoadError onRetry={load} />
  }
  if (!orders) return <MLoading rows={4} rowH={92} avatar={false} />

  return (
    <div>
      <ScreenTitle
        overline={t('m.in_work', { count: inWork.length })}
        title={t('m.orders')}
        right={(
          <button type="button" aria-label={t('howto.title')} onClick={() => toast(t('howto.subtitle'))} className="grid h-10 w-10 place-items-center rounded-full bg-white/[0.07] text-white/70 transition active:scale-90">
            <CircleHelp size={18} />
          </button>
        )}
      />

      <div className="mt-5 px-4">
        <div className="m-hero relative overflow-hidden rounded-[30px] p-5">
          <div className="pointer-events-none absolute -right-12 -top-16 h-48 w-48 rounded-full bg-white/20 blur-2xl" />
          <div className="relative flex items-center justify-between gap-2">
            <span className="text-[15px] font-semibold">{t('m.await_pay')}</span>
            <button
              type="button"
              onClick={() => { setFree((f) => !f); toast(free ? t('m.busy_toast') : t('m.free_toast')) }}
              className="m-tile flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-medium transition active:scale-95"
            >
              <span className="h-2 w-2 rounded-full" style={free ? { background: '#3ddc97', boxShadow: '0 0 8px #3ddc97' } : { background: '#ffc24d', boxShadow: '0 0 8px #ffc24d' }} />
              {free ? t('m.free_status') : t('m.busy')}
            </button>
          </div>
          <BigMoney value={owedTotal} size={48} className="relative mt-2" />
          <div className="relative mt-1.5 text-[13px] text-white/75">
            {t('m.bills_n', { count: awaiting.length })}
            {nearest ? ` · ${t('m.nearest', { what: `«${nearest.title}»` })}` : ''}
          </div>
          <div className="relative mt-4 grid grid-cols-2 gap-2">
            <Stat label={t('m.st_work')} value={String(inWork.length)} />
            <Stat label={t('m.st_avg')} value={stats?.avg_check ? money(stats.avg_check) : '—'} />
            <Stat label={t('m.st_month')} value={month ? money(month) : '—'} />
            <Stat label={t('m.st_rate')} value={stats?.rate ? t('m.per_hour', { v: money(stats.rate) }) : '—'} />
          </div>
        </div>
      </div>

      {pulse?.enabled && (pulse.late || []).length > 0 && (
        <div className="mt-3 space-y-1.5 px-4">
          {pulse.late.slice(0, 3).map((x) => (
            <button type="button" key={x.order_id} onClick={() => setFilter('await')} className="flex w-full items-center gap-2 rounded-[16px] bg-white/[0.06] px-3.5 py-2.5 text-left text-[13px] text-white/75 transition active:scale-[0.98]">
              <span className="h-2 w-2 shrink-0 rounded-full bg-[#ffc24d] shadow-[0_0_8px_#ffc24d]" />
              <span className="min-w-0 flex-1 truncate"><b className="font-medium text-white/90">{x.client || x.title}</b> · {money(x.left)} · {t('m.days_n', { count: x.days })}</span>
            </button>
          ))}
        </div>
      )}

      <div className="mt-5 flex items-center gap-2 px-4">
        <Segmented
          className="w-[196px]"
          value={mode}
          onChange={setMode}
          options={[{ id: 'list', label: t('m.seg_list') }, { id: 'kanban', label: t('m.seg_kanban') }]}
        />
      </div>

      {mode === 'list' ? (
        <div key="list" className="anim-rise">
          <div className="no-scrollbar mt-3 flex gap-2 overflow-x-auto px-4">
            <Chip active={filter === 'work'} onClick={() => setFilter('work')} count={inWork.length}>{t('m.f_work')}</Chip>
            <Chip active={filter === 'await'} onClick={() => setFilter('await')} count={awaiting.length}>{t('m.f_await')}</Chip>
            <Chip active={filter === 'all'} onClick={() => setFilter('all')} count={all.length}>{t('m.f_all')}</Chip>
          </div>
          <div className="mt-3 space-y-3 px-4">
            {list.map((o) => <OrderCard key={o.id} o={o} onPay={() => payFull(o)} onStage={(s) => toStage(o, s)} />)}
            {list.length === 0 && (
              <Card className="px-4 py-5">
                <MEmpty compact glyph="memory" text={t('m.orders_empty')} sub={t('m.orders_empty_sub')} hint={t('m.orders_hint')} />
              </Card>
            )}
          </div>
        </div>
      ) : (
        <div key="kanban" className="anim-rise no-scrollbar mt-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-2">
          {ORDER_STAGES.map(([k, label]) => {
            const items = all.filter((o) => stageOf(o) === k)
            return (
              <div key={k} className="w-[252px] shrink-0 snap-start scroll-ml-4">
                <div className="mb-2 flex items-center justify-between px-1.5">
                  <span className="text-[14px] font-semibold">{t(label)}</span>
                  <span className="tnum rounded-full bg-white/10 px-2 py-0.5 text-[12px] text-white/60">{items.length}</span>
                </div>
                <div className="min-h-[180px] space-y-2 rounded-[24px] bg-white/[0.06] p-2">
                  {items.map((o) => (
                    <Card key={o.id} className="rounded-[18px] p-3">
                      <div className="text-[11.5px] text-white/50">{o.client || '—'}</div>
                      <div className="mt-0.5 text-[14px] font-semibold leading-snug">{o.title}</div>
                      <div className="mt-2.5 flex items-center justify-between gap-2">
                        <span className="tnum text-[13.5px] font-semibold">{o.price ? money(o.price) : '—'}</span>
                        <DeadlinePill o={o} />
                      </div>
                      <select
                        value={stageOf(o)}
                        onChange={(e) => toStage(o, e.target.value)}
                        aria-label={t('stage.aria')}
                        className="mt-2.5 h-9 w-full rounded-full border border-white/10 bg-white/[0.06] px-2 text-[12.5px] text-white/80 outline-none"
                      >
                        {ORDER_STAGES.map(([sk, sl]) => <option key={sk} value={sk}>{t(sl)}</option>)}
                      </select>
                    </Card>
                  ))}
                  {items.length === 0 && <div className="py-8 text-center text-[12.5px] text-white/35">{t('m.empty')}</div>}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {toastMsg && (
        <div className="anim-toast fixed bottom-24 left-1/2 z-50 -translate-x-1/2 rounded-full border border-white/10 bg-[#121a46]/95 px-4 py-2.5 text-[13.5px] shadow-xl backdrop-blur-xl">{toastMsg}</div>
      )}
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="m-tile rounded-[18px] px-3.5 py-3">
      <div className="text-[12px] text-white/75">{label}</div>
      <div className="tnum mt-0.5 truncate text-[18px] font-semibold">{value}</div>
    </div>
  )
}

function DeadlinePill({ o }) {
  const { t } = useI18n()
  if (!o.deadline) return <Pill tone="gray">{t('m.no_deadline')}</Pill>
  if (o.overdue) return <Pill tone="red" icon={Clock}>{shortDate(o.deadline)}</Pill>
  if (o.days_left === 0) return <Pill tone="amber" icon={Clock}>{t('m.today')}</Pill>
  if (o.days_left === 1) return <Pill tone="amber" icon={Clock}>{t('m.tomorrow')}</Pill>
  return <Pill tone="gray" icon={Clock}>{shortDate(o.deadline)}</Pill>
}

/* Полоса этапов: 9 стадий CRM ужаты в 5 делений (мобильный формат референса).
   lost — красная, paid — полная, остальные — позиция по шкале. */
function OrderCard({ o, onPay, onStage }) {
  const { t } = useI18n()
  const idx = ORDER_STAGES.findIndex(([k]) => k === stageOf(o))
  const pos = o.stage === 'lost' || o.status === 'cancelled' ? -1 : stageOf(o) === 'paid' || o.status === 'paid' ? 5 : Math.min(4, Math.floor(Math.max(0, idx) / 9 * 5))
  const pay = payMeta(o)
  const next = NEXT_STEP[stageOf(o)]
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2.5">
        <Avatar initials={initialsOf(o.client || o.title)} hue={hueOf(o.client || o.title)} size={30} />
        <span className="min-w-0 flex-1 truncate text-[13px] text-white/60">{o.client || '—'}</span>
        <DeadlinePill o={o} />
      </div>
      <div className="mt-2.5 text-[17px] font-semibold leading-snug">{o.title}</div>
      <div className="mt-3 flex gap-1">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-1.5 flex-1 rounded-full"
            style={pos === -1
              ? { background: 'rgba(255,92,122,0.55)' }
              : i < pos || pos === 5
                ? { background: '#7d95ff' }
                : i === pos
                  ? { background: '#fff', boxShadow: '0 0 8px rgba(255,255,255,0.7)' }
                  : { background: 'rgba(255,255,255,0.12)' }}
          />
        ))}
      </div>
      <div className="mt-2 text-[12.5px] text-white/55">
        {t('m.stage', { what: t(ORDER_STAGE_LABEL[stageOf(o)] || stageOf(o)) })} · {t('m.of_n', { a: Math.max(0, idx) + 1, b: ORDER_STAGES.length })}
      </div>
      <div className="mt-3 flex items-center justify-between gap-2 border-t border-white/[0.07] pt-3">
        <div className="min-w-0">
          <span className="tnum text-[17px] font-semibold">{o.price ? money(o.price) : '—'}</span>
          {(o.left || 0) > 0 && o.status !== 'new' && <span className="tnum ml-2 text-[12.5px] font-medium text-[#ffd581]">{t('m.waiting', { v: money(o.left) })}</span>}
        </div>
        <Pill tone={needsPay(o) ? 'red' : pay.tone} dot>{needsPay(o) ? t('crm.stage_awaiting_payment') : t(pay.key)}</Pill>
      </div>
      <div className="mt-3 flex gap-2">
        {(o.left || 0) > 0 && o.status !== 'new' && o.status !== 'cancelled' && (
          <button type="button" onClick={onPay} className="h-10 flex-1 rounded-full bg-white text-[13.5px] font-semibold text-[#2b3a9a] transition active:scale-[0.97]">{t('m.pay')}</button>
        )}
        {next && (
          <button type="button" onClick={() => onStage(next.stage)} className="h-10 flex-1 rounded-full border border-white/15 bg-white/[0.07] text-[13.5px] font-medium text-white/85 transition active:scale-[0.97]">
            {t('m.next', { what: t(next.text) })}
          </button>
        )}
      </div>
    </Card>
  )
}
