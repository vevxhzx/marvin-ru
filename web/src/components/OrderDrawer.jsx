// Панель заказа (drawer) — то, что открывается кликом по строке. Это шторка приложения
// (components/ui.jsx#Sheet): на телефоне — снизу, с ручкой и тремя точками прилипания,
// свайп за ручку вниз закрывает её по скорости, Esc и ✕ тоже.
//
// Внутри — редакционная иерархия: разделы идут в порядке «что делать дальше», каждый со своей
// подписью и своим действием справа, между ними — волосяная линия. Не сетка одинаковых коробок:
//   стадия → оплата → дедлайн → время (таймер и круги правок) → клиент → заметки/ТЗ →
//   чек-лист → комментарии → история.
// Стадия ЗАКАЗА двигается здесь, стадия КЛИЕНТА — отдельным списком в блоке «клиент» (не смешиваем).
import { useEffect, useRef, useState } from 'react'
import { Check, Square, Trash2, Wallet, Play, Square as StopIcon, User, Pencil, MessageCircle } from 'lucide-react'
import { api, money, dayLabel, shortDate, hhmm } from '../lib/api'
import { Sheet, ListSkeleton } from './ui'
import StageStepper from './StageStepper'
import { ClientStageSelect, ClientStageNote } from './ClientStage'
import { stageOf, ORDER_STAGE_LABEL } from '../lib/crm'
import { useI18n, t as T } from '../lib/i18n'

const hours = (h) => (h >= 1 ? `${Math.round(h * 10) / 10} ${T('unit.hour')}` : h > 0 ? `${Math.round(h * 60)} ${T('unit.min')}` : '—')

/* Раздел панели: подпись слева, действие справа, содержимое под ними.
   Между разделами — волосяная линия, а не одинаковые серые коробки: иерархия читается
   по ритму и подписи, а не по рамке. */
function Sec({ title, right, children }) {
  return (
    <section className="border-t py-4 first:border-t-0 first:pt-0" style={{ borderColor: 'var(--line)' }}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
        <span className="label">{title}</span>
        {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
      </div>
      {children}
    </section>
  )
}

/* Ряд чисел раздела: подпись сверху, значение снизу, всё табличное — столбик не «прыгает». */
function Figures({ items, className = '' }) {
  return (
    <div className={`grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4 ${className}`}>
      {items.map((it) => (
        <div key={it.label} className="min-w-0">
          <div className="label truncate" title={it.label}>{it.label}</div>
          <div className={`num mt-0.5 truncate ${it.tone === 'pos' ? 'pos' : it.tone === 'warn' ? 'warn' : ''}`} style={{ fontSize: 'var(--fs-lg)' }}
            title={typeof it.value === 'string' ? it.value : undefined}>{it.value}</div>
        </div>
      ))}
    </div>
  )
}

/* Круги правок: сколько кругов согласований прошло. Рисуем кружками — видно сразу,
   не читая подписи, и они не занимают места рядом с числами. */
function Revisions({ n = 0 }) {
  if (!n) return null
  const shown = Math.min(n, 8)
  return (
    <span className="flex items-center gap-2">
      <span className="flex items-center gap-1" aria-hidden="true">
        {Array.from({ length: shown }, (_, i) => <i key={i} className="block h-2 w-2 rounded-full" style={{ background: 'var(--warn)' }} />)}
      </span>
      <span className="num text-[12px]">{n}</span>
    </span>
  )
}

/* «Живой» срок: сегодня/завтра/просрочен вместо даты — так срочное видно сразу. */
function deadlineLabel(d, t) {
  if (!d.deadline) return null
  if (d.overdue) return t('or.dl_overdue', { date: dayLabel(d.deadline).toLowerCase() })
  if (d.past_due) return t('or.dl_was', { date: shortDate(d.deadline).toLowerCase() })
  if (d.days_left === 0) return t('common.today')
  if (d.days_left === 1) return t('common.tomorrow')
  return t('aims.by', { date: shortDate(d.deadline).toLowerCase() })
}

export default function OrderDrawer({ oid, reloadKey = 0, onClose, onChanged, onErr, onMsg, onClient, onEdit, onPay, onAsk, timer, onStartTimer, onStopTimer, mmss }) {
  const { t } = useI18n()
  const [d, setD] = useState(null)
  const [lost, setLost] = useState(null)             // причина потери
  const [comment, setComment] = useState('')
  const [check, setCheck] = useState('')
  const [stageView, setStageView] = useState(null)   // стадия КЛИЕНТА (отдельная сущность)
  const [min, setMin] = useState('')
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const prevOid = useRef(null)

  const load = () => {
    if (!oid) { setD(null); return }
    api.crmOrderCard(oid).then(setD).catch((e) => onErr?.(e))
  }
  // reloadKey растёт, когда оплату записали в соседней форме — тогда панель перечитывает заказ,
  // иначе в блоке «оплата» остались бы старые суммы
  useEffect(() => {
    if (prevOid.current !== oid) {
      prevOid.current = oid
      setLost(null); setStageView(null); setMin(''); setNote(''); setMsg('')
    }
    load()
  }, [oid, reloadKey])

  // стадия клиента — только когда у заказа есть клиент; перечитываем после оплаты/смены стадии
  useEffect(() => {
    const cid = d?.client_id
    if (!cid) { setStageView(null); return }
    api.get(`/api/crm/clients/${cid}/stage`).then(setStageView).catch(() => setStageView(null))
  }, [d?.client_id, d?.paid, d?.status])

  const act = async (fn, okMsg) => {
    setBusy(true)
    try {
      await fn()
      if (okMsg) onMsg?.(okMsg)
      load(); onChanged?.()
      return true
    } catch (e) { onErr?.(e); return false } finally { setBusy(false) }
  }
  const setStage = (k) => {
    if (k === 'lost') { setLost(''); return }
    act(() => api.crmSetStage(oid, k), t('stage.of', { label: t(ORDER_STAGE_LABEL[k]) || k }))
  }
  const confirmLost = async () => {
    const ok = await act(() => api.crmSetStage(oid, 'lost', lost.trim() || null), t('od.lost_marked'))
    if (ok) setLost(null)
  }
  const addManual = async () => {
    const n = Number(min)
    if (!Number.isFinite(n) || n < 1) { setMsg(t('od.enter_minutes')); return }
    const ok = await act(() => api.addOrderTime(oid, Math.round(n), { note: note.trim() || t('od.manual_time') }))
    if (ok) { setMin(''); setNote(''); setMsg(t('od.time_added')) }
  }

  const stage = stageOf(d)
  const running = timer?.active && timer.order_id === oid
  const left = d?.left ?? 0
  const price = d?.price || 0
  const pct = price > 0 ? Math.min(100, Math.round((d.paid / price) * 100)) : 0
  const dl = d ? deadlineLabel(d, t) : null

  return (
    <Sheet open={!!oid} wide onClose={onClose} title={d?.title || t('od.order')}
      sub={d ? `${d.client || t('od.no_client')}${d.deadline ? ` · ${t('od.due', { date: shortDate(d.deadline) })}` : ''}` : t('common.loading')}>
      {!d ? <ListSkeleton n={5} rowH={54} avatar={false} /> : (
        <div className="text-[13px]">
          {/* 1. стадия заказа — клик меняет, «потерян» спрашивает причину */}
          <Sec title={t('stage.block')} right={<span className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{t('od.stage_hint')}</span>}>
            <StageStepper stage={stage} onStage={setStage} revisions={d.revisions} disabled={busy} />
            {lost !== null && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <input className="input min-w-[200px] flex-1" placeholder={t('od.lost_ph')} value={lost} onChange={(e) => setLost(e.target.value)} aria-label={t('od.lost_label')} />
                <button className="btn-danger" onClick={confirmLost} disabled={busy || !lost.trim()}>{t('od.mark_lost')}</button>
                <button className="btn-ghost" onClick={() => setLost(null)}>{t('common.cancel')}</button>
              </div>
            )}
            {stage === 'lost' && d.lost_reason && <div className="neg mt-2 text-[12.5px]">{t('od.reason', { what: t.sv(d.lost_reason) || d.lost_reason })}</div>}
          </Sec>

          {/* 2. оплата */}
          <Sec title={t('od.payment')} right={left > 0
            ? <button type="button" className="btn-primary btn-sm" onClick={() => onPay?.(d)}><Wallet size={13} /> {t('od.record_pay')}</button>
            : <span className="pos" style={{ fontSize: 'var(--fs-xs)' }}>{t('od.no_debt')}</span>}>
            <Figures items={[
              { label: t('common.amount'), value: price ? money(price) : '—' },
              { label: t('od.prepaid'), value: money(d.prepaid || 0) },
              { label: t('od.paid'), value: money(d.paid), tone: 'pos' },
              { label: t('od.rest'), value: money(left), tone: left > 0 ? 'warn' : 'pos' },
            ]} />
            {price > 0 && (
              <div className="mt-2.5 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, background: pct >= 100 ? 'var(--pos)' : 'var(--acc)' }} />
                </div>
                <span className="num faint" style={{ fontSize: 'var(--fs-xs)' }}>{t('or.paid_pct', { pct })}</span>
              </div>
            )}
            {d.payments?.length > 0 && (
              <div className="mt-2.5 rule">
                {d.payments.map((p) => (
                  <div key={p.id} className="muted flex items-baseline justify-between gap-3 py-1 text-[12.5px]">
                    <span className="min-w-0 truncate">{dayLabel(p.date).toLowerCase()} · {p.note || t('od.payment')}</span><span className="num pos shrink-0">+{money(p.amount)}</span>
                  </div>
                ))}
              </div>
            )}
          </Sec>

          {/* 3. срок — обещание клиенту, поэтому отдельным разделом, а не строкой в сетке */}
          <Sec title={t('od.deadline')}>
            {d.deadline ? (
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className={d.overdue ? 'neg' : d.past_due ? 'faint' : ''} style={{ fontSize: 'var(--fs-lg)' }}>{dayLabel(d.deadline)}</span>
                <span className="muted num">{hhmm(d.deadline)}</span>
                {dl && <span className={`num ${d.overdue ? 'neg' : ''}`} style={{ fontSize: 'var(--fs-xs)' }}>{dl}</span>}
              </div>
            ) : <div className="faint text-[12.5px]">{t('od.no_client_hint')}</div>}
          </Sec>

          {/* 4. время: таймер, ручной ввод и круги правок */}
          <Sec title={t('common.time')} right={running
            ? <button type="button" className="btn-soft btn-sm" onClick={() => onStopTimer?.()}><StopIcon size={13} /> {t('pomo.stop_short')}</button>
            : <button type="button" className="btn-soft btn-sm" onClick={() => onStartTimer?.(d)}><Play size={13} /> {t('od.timer', { n: timer?.focus_min || 25 })}</button>}>
            <Figures items={[
              { label: t('od.logged'), value: hours(d.hours) + (d.estimate_h ? ` / ${hours(d.estimate_h)}` : '') },
              { label: t('od.rate'), value: d.rate ? `${money(d.rate)}/${T('unit.hour')}` : '—', tone: d.pulse?.warn ? 'warn' : '' },
              { label: t('od.revisions'), value: <Revisions n={d.revisions || 0} /> },
            ]} />
            {running && (
              <div className="accent mt-2 text-[12.5px]">
                {t('od.timer_running', { left: mmss ? mmss(Math.max(0, Math.round((new Date(timer.ends_at) - Date.now()) / 1000))) : '' })}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <input className="input !w-28 num" type="number" min="1" max="10080" placeholder={t('od.min_ph')} value={min} onChange={(e) => setMin(e.target.value)} aria-label={t('od.min_label')} />
              <input className="input min-w-[160px] flex-1" placeholder={t('od.what_ph')} value={note} onChange={(e) => setNote(e.target.value)} aria-label={t('od.what_label')} />
              <button className="btn-soft" onClick={addManual} disabled={busy}>{t('od.add_time')}</button>
            </div>
            {msg && <div className="muted mt-1 text-[12px]">{msg}</div>}
          </Sec>

          {/* 5. клиент: его собственная стадия (не стадия заказа) */}
          <Sec title={t('graph.one_client')} right={d.client_id
            ? <button type="button" className="btn-ghost btn-sm" onClick={() => onClient?.(d.client_id)}><User size={13} /> {t('od.client_card')}</button>
            : null}>
            {d.client_id ? (
              <>
                <div className="font-medium" style={{ fontSize: 'var(--fs-lg)' }}>{d.client}</div>
                <ClientStageSelect view={stageView} onView={setStageView} onErr={onErr} className="mt-2" />
                <ClientStageNote view={stageView} />
              </>
            ) : <div className="faint text-[12.5px]">{t('od.no_client_hint')}</div>}
          </Sec>

          {/* 6. заметки / ТЗ */}
          <Sec title={t('od.notes_spec')} right={
            <button type="button" className="btn-ghost btn-sm" onClick={() => onEdit?.(d)}><Pencil size={13} /> {t('od.edit_order')}</button>}>
            {d.notes
              ? <div className="muted whitespace-pre-wrap text-[13px]">{d.notes}</div>
              : <div className="faint text-[12.5px]">{t('od.notes_hint')}</div>}
          </Sec>

          {/* 7. чек-лист этапов */}
          <Sec title={t('od.checklist')}>
            {d.checklist?.length > 0 && (
              <div className="rule">
                {d.checklist.map((c) => (
                  <div key={c.id} className="flex items-center gap-2 py-0.5">
                    <button type="button" className="btn-icon !h-8 !w-8" onClick={() => act(() => api.crmToggleCheck(c.id))} aria-label={t('od.check_done', { title: c.title })} data-tip={t(c.done ? 'od.back_to_work' : 'common.done')}>
                      {c.done ? <Check size={14} /> : <Square size={14} />}
                    </button>
                    <span className={`min-w-0 flex-1 ${c.done ? 'muted line-through' : ''}`}>{c.title}</span>
                    <button type="button" className="btn-icon !h-8 !w-8 ml-auto faint" onClick={() => act(() => api.crmDelCheck(c.id))} aria-label={t('od.check_del', { title: c.title })} data-tip={t('od.del_step')}><Trash2 size={12} /></button>
                  </div>
                ))}
              </div>
            )}
            <form className="mt-2 flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); const ct = check.trim(); if (!ct) return; setCheck(''); act(() => api.crmAddCheck(oid, ct)) }}>
              <input className="input min-w-0 flex-1" placeholder={t('od.new_step')} value={check} onChange={(e) => setCheck(e.target.value)} aria-label={t('od.new_step_label')} />
              <button className="btn-soft shrink-0" disabled={!check.trim() || busy}>{t('common.add')}</button>
            </form>
          </Sec>

          {/* 8. комментарии */}
          <Sec title={t('od.comments')}>
            {d.comments?.length > 0 && (
              <div className="rule">
                {d.comments.map((c) => (
                  <div key={c.id} className="muted py-1 text-[12.5px]"><span className="faint num">{dayLabel(c.created_at).toLowerCase()} · {c.author}:</span> {c.text}</div>
                ))}
              </div>
            )}
            <div className="mt-2 flex items-center gap-2">
              <input className="input min-w-0 flex-1" placeholder={t('common.comment')} value={comment} onChange={(e) => setComment(e.target.value)} aria-label={t('od.new_comment')} />
              <button className="btn-soft shrink-0" disabled={!comment.trim() || busy}
                onClick={() => { const txt = comment.trim(); if (!txt) return; setComment(''); act(() => api.crmComment(oid, txt, d.client_id)) }}>{t('common.add')}</button>
            </div>
            {onAsk && (
              <button type="button" className="btn-ghost btn-sm mt-2" onClick={() => onAsk(d)}><MessageCircle size={13} /> {t('od.ask')}</button>
            )}
          </Sec>

          {/* 9. история: кто и когда что менял */}
          <Sec title={t('od.history')} right={<span className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{t('od.history_hint')}</span>}>
            <div className="max-h-[240px] space-y-1 overflow-y-auto">
              {d.activity?.map((a) => (
                <div key={a.id} className="flex gap-2 text-[12.5px]"><span className="faint shrink-0 num">{dayLabel(a.created_at).toLowerCase()}</span><span className="muted">{a.text}</span></div>
              ))}
              {!d.activity?.length && <div className="faint text-[12px]">{t('od.history_empty')}</div>}
            </div>
          </Sec>
        </div>
      )}
    </Sheet>
  )
}