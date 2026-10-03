// «Следующий шаг» клиента с датой — для страницы «люди» (карточка человека).
// Данные берём из существующей карточки CRM (/api/crm/clients/{id}/card) и сохраняем
// через существующий PATCH (/api/crm/clients/{id}) — новых эндпоинтов не заводим.
// Это про КЛИЕНТА, не про заказ: у заказа свой next_step в панели заказа.
//
// Если вызывающая сторона уже загрузила карточку (карточка человека), её можно передать
// пропом `card` — тогда повторный запрос не уходит: иначе на одного человека было бы
// два одинаковых GET-а подряд.
import { useEffect, useState } from 'react'
import { api, dayLabel, toLocalISO } from '../lib/api'
import { useToast } from './ui'
import { useI18n } from '../lib/i18n'

const fromCard = (r) => ({
  step: r?.next_step || '',
  at: r?.next_step_at ? toLocalISO(new Date(r.next_step_at)).slice(0, 10) : '',
})

export default function ClientNextStep({ cid, card, onErr, onSaved, className = '' }) {
  const { t } = useI18n()
  const [loaded, setLoaded] = useState(false)
  const [step, setStep] = useState('')
  const [at, setAt] = useState('')
  const [base, setBase] = useState({ step: '', at: '' })
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [, show] = useToast()

  // карточка снаружи: синхронизируемся с ней, отдельного запроса не делаем
  useEffect(() => {
    if (!cid) { setLoaded(false); setStep(''); setAt(''); return }
    if (card) {
      const v = fromCard(card)
      setStep(v.step); setAt(v.at); setBase(v); setLoaded(true)
      return
    }
    let on = true
    setLoaded(false)
    api.crmClientCard(cid).then((r) => {
      if (!on) return
      const v = fromCard(r)
      setStep(v.step); setAt(v.at); setBase(v); setLoaded(true)
    }).catch((e) => { if (on) { setLoaded(true); if (onErr) onErr(e); else show.err(e) } })
    return () => { on = false }
  }, [cid, card])   // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = loaded && (step !== base.step || at !== base.at)
  const save = async () => {
    setBusy(true)
    try {
      await api.crmUpdateClient(cid, { next_step: step.trim(), next_step_at: at ? `${at}T12:00:00` : null })
      setBase({ step: step.trim(), at })
      setNote(t('common.saved'))
      setTimeout(() => setNote(''), 2500)
      onSaved?.()
    } catch (e) { if (onErr) onErr(e); else show.err(e) } finally { setBusy(false) }
  }

  if (!loaded) return <div className={`faint text-[12px] ${className}`}>{t('next_step.loading')}</div>

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-2">
        <input className="input min-w-[160px] flex-1" value={step} onChange={(e) => setStep(e.target.value)}
          placeholder={t('next_step.ph')} aria-label={t('next_step.aria')} />
        <input type="date" className="input !w-[160px]" value={at} onChange={(e) => setAt(e.target.value)} aria-label={t('next_step.date')} />
        <button type="button" className="btn-soft shrink-0" onClick={save} disabled={!dirty || busy} aria-label={t('next_step.save')} title={t('next_step.save')}>
          {busy ? t('common.loading') : t('common.save')}
        </button>
      </div>
      <div className="faint mt-1 text-[12px] leading-snug">
        {note ? <span className="pos">{note}</span> : at ? t('next_step.hint_dated', { when: dayLabel(at) }) : t('next_step.hint_nodate')}
      </div>
    </div>
  )
}