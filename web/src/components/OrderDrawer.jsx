// Панель заказа (drawer) — то, что открывается кликом по строке. Блоки по порядку «что делать дальше»:
//   стадия → оплата → время → клиент → заметки/ТЗ → история (лента активности, комментарии, чек-лист).
// Стадия ЗАКАЗА двигается здесь, стадия КЛИЕНТА — отдельным списком в блоке «клиент» (не смешиваем).
import { useEffect, useRef, useState } from 'react'
import { Check, Square, Trash2, Wallet, Play, Square as StopIcon, User, Pencil, MessageCircle } from 'lucide-react'
import { api, money, dayLabel, shortDate, hhmm } from '../lib/api'
import { Sheet } from './ui'
import StageStepper from './StageStepper'
import { ClientStageSelect, ClientStageNote } from './ClientStage'
import { stageOf, ORDER_STAGE_LABEL } from '../lib/crm'
import { useI18n, t as T } from '../lib/i18n'

const hours = (h) => (h >= 1 ? `${Math.round(h * 10) / 10} ${T('unit.hour')}` : h > 0 ? `${Math.round(h * 60)} ${T('unit.min')}` : '—')

/* Блок панели: подпись + содержимое. Один стиль для всех блоков — иначе их не отличить. */
function Block({ title, right, children }) {
  return (
    <section className="rounded-2xl p-3.5" style={{ background: 'var(--sf2)', boxShadow: 'inset 0 0 0 1px var(--line)' }}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="label">{title}</span>
        {right}
      </div>
      {children}
    </section>
  )
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

  return (
    <Sheet open={!!oid} wide onClose={onClose} title={d?.title || t('od.order')}
      sub={d ? `${d.client || t('od.no_client')}${d.deadline ? ` · ${t('od.due', { date: shortDate(d.deadline) })}` : ''}` : t('common.loading')}>
      {!d ? <div className="muted text-[13px]">{t('common.loading')}</div> : (
        <div className="space-y-3 text-[13px]">
          {/* 1. стадия заказа — клик меняет, «потерян» спрашивает причину */}
          <Block title={t('stage.aria')} right={<span className="faint text-[11.5px]">{t('od.stage_hint')}</span>}>
            <StageStepper stage={stage} onStage={setStage} revisions={d.revisions} disabled={busy} />
            {lost !== null && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input className="input !h-8 min-w-[200px] flex-1" placeholder={t('od.lost_ph')} value={lost} onChange={(e) => setLost(e.target.value)} aria-label={t('od.lost_label')} />
                <button className="btn-danger btn-sm" onClick={confirmLost} disabled={busy || !lost.trim()}>{t('od.mark_lost')}</button>
                <button className="btn-ghost btn-sm" onClick={() => setLost(null)}>{t('common.cancel')}</button>
              </div>
            )}
            {stage === 'lost' && d.lost_reason && <div className="neg mt-2 text-[12.5px]">{t('od.reason', { what: t.sv(d.lost_reason) || d.lost_reason })}</div>}
          </Block>

          {/* 2. оплата */}
          <Block title={t('od.payment')} right={left > 0
            ? <button type="button" className="btn-primary btn-sm" onClick={() => onPay?.(d)}><Wallet size={13} /> {t('od.record_pay')}</button>
            : <span className="pos text-[12px]">{t('od.no_debt')}</span>}>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
              <div><div className="label">{t('common.amount')}</div><div className="num mt-0.5">{price ? money(price) : '—'}</div></div>
              <div><div className="label">{t('od.prepaid')}</div><div className="num mt-0.5">{money(d.prepaid || 0)}</div></div>
              <div><div className="label">{t('od.rest')}</div><div className={`num mt-0.5 ${left > 0 ? 'warn' : 'pos'}`}>{money(left)}</div></div>
              <div><div className="label">{t('od.paid')}</div><div className="num mt-0.5">{money(d.paid)}</div></div>
            </div>
            {price > 0 && (
              <div className="mt-2 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, var(--acc), var(--acc2))' }} />
                </div>
                <span className="num faint text-[11px]">{pct}%</span>
              </div>
            )}
            {d.payments?.length > 0 && (
              <div className="mt-2 space-y-0.5">
                {d.payments.map((p) => (
                  <div key={p.id} className="muted flex justify-between gap-3 text-[12.5px]">
                    <span>{dayLabel(p.date).toLowerCase()} · {p.note || t('od.payment')}</span><span className="num pos">+{money(p.amount)}</span>
                  </div>
                ))}
              </div>
            )}
          </Block>

          {/* 3. время: таймер + ручной ввод */}
          <Block title={t('common.time')} right={running
            ? <button type="button" className="btn-soft btn-sm" onClick={() => onStopTimer?.()}><StopIcon size={13} /> {t('pomo.stop_short')}</button>
            : <button type="button" className="btn-soft btn-sm" onClick={() => onStartTimer?.(d)}><Play size={13} /> {t('od.timer', { n: timer?.focus_min || 25 })}</button>}>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
              <div><div className="label">{t('od.logged')}</div><div className="num mt-0.5">{hours(d.hours)}{d.estimate_h ? <span className="muted"> {t('od.of', { h: hours(d.estimate_h) })}</span> : ''}</div></div>
              <div><div className="label">{t('od.rate')}</div><div className={`num mt-0.5 ${d.pulse?.warn ? 'warn' : ''}`}>{d.rate ? `${money(d.rate)}/${T('unit.hour')}` : '—'}</div></div>
              <div><div className="label">{t('od.revisions')}</div><div className="num mt-0.5">{d.revisions || 0}</div></div>
              <div><div className="label">{t('od.deadline')}</div><div className="mt-0.5">{d.deadline ? `${dayLabel(d.deadline).toLowerCase()}, ${hhmm(d.deadline)}` : '—'}</div></div>
            </div>
            {running && (
              <div className="accent mt-2 text-[12.5px]">
                {t('od.timer_running', { left: mmss ? mmss(Math.max(0, Math.round((new Date(timer.ends_at) - Date.now()) / 1000))) : '' })}
              </div>
            )}
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <input className="input !h-8 !w-24 num" type="number" min="1" max="10080" placeholder={t('od.min_ph')} value={min} onChange={(e) => setMin(e.target.value)} aria-label={t('od.min_label')} />
              <input className="input !h-8 min-w-[160px] flex-1" placeholder={t('od.what_ph')} value={note} onChange={(e) => setNote(e.target.value)} aria-label={t('od.what_label')} />
              <button className="btn-soft btn-sm" onClick={addManual} disabled={busy}>{t('od.add_time')}</button>
            </div>
            {msg && <div className="muted mt-1 text-[12px]">{msg}</div>}
          </Block>

          {/* 4. клиент: карточка + его собственная стадия (не стадия заказа) */}
          <Block title={t('graph.one_client')} right={d.client_id
            ? <button type="button" className="btn-ghost btn-sm" onClick={() => onClient?.(d.client_id)}><User size={13} /> {t('od.client_card')}</button>
            : null}>
            {d.client_id ? (
              <>
                <div className="text-[13.5px] font-medium">{d.client}</div>
                <ClientStageSelect view={stageView} onView={setStageView} onErr={onErr} className="mt-2" />
                <ClientStageNote view={stageView} />
              </>
            ) : <div className="faint text-[12.5px]">{t('od.no_client_hint')}</div>}
          </Block>

          {/* 5. заметки / ТЗ */}
          <Block title={t('od.notes_spec')} right={
            <button type="button" className="btn-ghost btn-sm" onClick={() => onEdit?.(d)}><Pencil size={13} /> {t('od.edit_order')}</button>}>
            {d.notes
              ? <div className="muted whitespace-pre-wrap text-[13px]">{d.notes}</div>
              : <div className="faint text-[12.5px]">{t('od.notes_hint')}</div>}
          </Block>

          {/* 6. чек-лист и комментарии */}
          <Block title={t('od.checklist')}>
            {d.checklist?.map((c) => (
              <div key={c.id} className="flex items-center gap-2 py-0.5">
                <button type="button" className="btn-icon !h-6 !w-6" onClick={() => act(() => api.crmToggleCheck(c.id))} aria-label={t('od.check_done', { title: c.title })} data-tip={t(c.done ? 'od.back_to_work' : 'common.done')}>
                  {c.done ? <Check size={13} /> : <Square size={13} />}
                </button>
                <span className={c.done ? 'muted line-through' : ''}>{c.title}</span>
                <button type="button" className="btn-icon !h-6 !w-6 ml-auto faint" onClick={() => act(() => api.crmDelCheck(c.id))} aria-label={t('od.check_del', { title: c.title })} data-tip={t('od.del_step')}><Trash2 size={12} /></button>
              </div>
            ))}
            <form className="mt-1.5 flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); const ct = check.trim(); if (!ct) return; setCheck(''); act(() => api.crmAddCheck(oid, ct)) }}>
              <input className="input !h-8 flex-1" placeholder={t('od.new_step')} value={check} onChange={(e) => setCheck(e.target.value)} aria-label={t('od.new_step_label')} />
              <button className="btn-soft btn-sm" disabled={!check.trim() || busy}>{t('common.add')}</button>
            </form>
          </Block>

          <Block title={t('od.comments')}>
            {d.comments?.map((c) => (
              <div key={c.id} className="muted py-0.5 text-[12.5px]"><span className="faint num">{dayLabel(c.created_at).toLowerCase()} · {c.author}:</span> {c.text}</div>
            ))}
            <div className="mt-1.5 flex items-center gap-2">
              <input className="input !h-8 flex-1" placeholder={t('common.comment')} value={comment} onChange={(e) => setComment(e.target.value)} aria-label={t('od.new_comment')} />
              <button className="btn-soft btn-sm" disabled={!comment.trim() || busy}
                onClick={() => { const t = comment.trim(); if (!t) return; setComment(''); act(() => api.crmComment(oid, ct, d.client_id)) }}>{t('common.add')}</button>
            </div>
            {onAsk && (
              <button type="button" className="btn-ghost btn-sm mt-2" onClick={() => onAsk(d)}><MessageCircle size={13} /> {t('od.ask')}</button>
            )}
          </Block>

          <Block title={t('od.history')} right={<span className="faint text-[11.5px]">{t('od.history_hint')}</span>}>
            <div className="max-h-[240px] space-y-1 overflow-y-auto">
              {d.activity?.map((a) => (
                <div key={a.id} className="flex gap-2 text-[12.5px]"><span className="faint shrink-0 num">{dayLabel(a.created_at).toLowerCase()}</span><span className="muted">{a.text}</span></div>
              ))}
              {!d.activity?.length && <div className="faint text-[12px]">{t('od.history_empty')}</div>}
            </div>
          </Block>
        </div>
      )}
    </Sheet>
  )
}