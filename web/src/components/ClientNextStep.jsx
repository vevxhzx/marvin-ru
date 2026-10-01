// «Следующий шаг» клиента с датой — для страницы «люди» (карточка человека).
// Данные берём из существующей карточки CRM (/api/crm/clients/{id}/card) и сохраняем
// через существующий PATCH (/api/crm/clients/{id}) — новых эндпоинтов не заводим.
// Это про КЛИЕНТА, не про заказ: у заказа свой next_step в панели заказа.
import { useEffect, useState } from 'react'
import { api, dayLabel, toLocalISO } from '../lib/api'
import { useToast } from './ui'

export default function ClientNextStep({ cid, onErr, className = '' }) {
  const [loaded, setLoaded] = useState(false)
  const [step, setStep] = useState('')
  const [at, setAt] = useState('')
  const [base, setBase] = useState({ step: '', at: '' })
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [, show] = useToast()

  useEffect(() => {
    if (!cid) { setLoaded(false); setStep(''); setAt(''); return }
    let on = true
    api.crmClientCard(cid).then((r) => {
      if (!on) return
      const a = r.next_step_at ? toLocalISO(new Date(r.next_step_at)).slice(0, 10) : ''
      setStep(r.next_step || ''); setAt(a); setBase({ step: r.next_step || '', at: a }); setLoaded(true)
    }).catch((e) => { if (onErr) onErr(e); else show.err(e) })
    return () => { on = false }
  }, [cid])

  const dirty = loaded && (step !== base.step || at !== base.at)
  const save = async () => {
    setBusy(true)
    try {
      await api.crmUpdateClient(cid, { next_step: step.trim(), next_step_at: at ? `${at}T12:00:00` : null })
      setBase({ step: step.trim(), at })
      setNote('сохранено')
      setTimeout(() => setNote(''), 2500)
    } catch (e) { if (onErr) onErr(e); else show.err(e) } finally { setBusy(false) }
  }

  if (!loaded) return <div className={`faint text-[12px] ${className}`}>загружаю следующий шаг…</div>

  return (
    <div className={className}>
      <div className="label mb-1">следующий шаг</div>
      <div className="flex flex-wrap items-center gap-2">
        <input className="input !h-8 min-w-[160px] flex-1" value={step} onChange={(e) => setStep(e.target.value)}
          placeholder="позвонить, прислать смету…" aria-label="Следующий шаг" />
        <input type="date" className="input !h-8 !w-[150px]" value={at} onChange={(e) => setAt(e.target.value)} aria-label="Дата следующего шага" />
        <button type="button" className="btn-soft btn-sm" onClick={save} disabled={!dirty || busy} aria-label="Сохранить следующий шаг">{busy ? 'сохраняю…' : 'сохранить'}</button>
      </div>
      <div className="faint mt-1 text-[12px]">
        {note ? <span className="pos">{note}</span> : at ? `к ${dayLabel(at).toLowerCase()} — попадёт в follow-up` : 'дата не задана; без неё напоминание не создастся'}
      </div>
    </div>
  )
}
