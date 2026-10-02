// Стадия КЛИЕНТА в интерфейсе: бейдж + выпадающий список для ручной смены.
// Это НЕ стадия заказа (см. lib/crm.js): стадия клиента обновляется автоматически по оплатам,
// а ручное значение авто-логика не перетирает — поэтому показываем метку «вручную» и кнопку «вернуть авто».
import { useCallback, useEffect, useState } from 'react'
import { PencilLine, Undo2 } from 'lucide-react'
import { CLIENT_STAGES, CLIENT_STAGE_LABEL, CLIENT_STAGE_HINT, CLIENT_STAGE_TONE, clientStageApi, clientStageLabel, clientStageHint } from '../lib/crm'
import { useI18n } from '../lib/i18n'

/** Бейдж стадии клиента. `view` — ответ /api/crm/clients/{id}/stage. */
export function ClientStageBadge({ view, className = '' }) {
  const { t } = useI18n()
  if (!view?.stage) return null
  return (
    <span className={`badge ${CLIENT_STAGE_TONE[view.stage] || ''} ${className}`}>
      {view.label || clientStageLabel(view.stage) || view.stage}
      {view.manual && <span className="faint text-[10px]" title={t('cstage.manual_title')}>{t('cstage.manual')}</span>}
    </span>
  )
}

/** Одна строка-пояснение: как стадия посчитана (для подписи под списком). */
export function ClientStageNote({ view }) {
  const { t } = useI18n()
  if (!view) return null
  return (
    <div className="faint mt-1 text-[11.5px]">
      {view.manual
        ? t('cstage.manual_note')
        : view.auto ? t('cstage.auto_by_orders', { label: view.auto_label || clientStageLabel(view.auto) }) : t('cstage.no_signal')}
      {view.paid_orders ? ` · ${t('cstage.paid_orders', { n: view.paid_orders })}` : ''}
    </div>
  )
}

/** Выпадающий список стадии клиента + «вернуть авто», если значение ручное. */
export function ClientStageSelect({ view, onView, onErr, className = '', label }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const cur = view?.stage || 'lead'
  const pick = async (e) => {
    const v = e.target.value
    if (!view?.client_id || v === cur) return
    setBusy(true)
    try { onView(await clientStageApi.set(view.client_id, v)) } catch (err) { onErr?.(err) } finally { setBusy(false) }
  }
  const toAuto = async () => {
    setBusy(true)
    try { onView(await clientStageApi.clearManual(view.client_id)) } catch (err) { onErr?.(err) } finally { setBusy(false) }
  }
  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <PencilLine size={13} className="faint shrink-0" aria-hidden />
      <select className="input !h-8 !w-auto min-w-[150px] text-[13px]" value={cur} onChange={pick} disabled={busy} aria-label={label || t('cstage.title')}
        title={clientStageHint(cur)}>
        {CLIENT_STAGES.map(([k, l]) => <option key={k} value={k}>{t(l)} — {clientStageHint(k)}</option>)}
      </select>
      {view?.manual && (
        <button type="button" className="btn-ghost btn-sm" disabled={busy} onClick={toAuto} data-tip={t('cstage.back_to_auto_tip')}>
          <Undo2 size={13} /> {t('cstage.back_to_auto')}
        </button>
      )}
    </div>
  )
}

/** Стадия одного клиента: загрузка + смена. Возвращает [view, setView]. */
export function useClientStage(cid, onErr) {
  const [view, setView] = useState(null)
  const load = useCallback(() => {
    if (!cid) { setView(null); return }
    clientStageApi.get(cid).then(setView).catch((e) => { setView(null); onErr?.(e) })
  }, [cid, onErr])
  useEffect(() => { load() }, [load])
  return [view, setView, load]
}