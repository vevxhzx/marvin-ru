/* Плашка «режим жизни» в шапке финансов: чип с названием и датами, кнопки «изменить»/«закрыть»,
   переключатель «считать по режиму» и пустое состояние с подсказкой, если режимов нет.
   Данные — /api/finance/regimes* (core/services/regime.py). Состояние переключателя живёт
   в настройках на сервере, поэтому телефон и компьютер считают одинаково. */
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { Sheet, Field, Confirm, useToast } from './ui'
import { Trash2 } from 'lucide-react'

const todayISO = () => new Date().toISOString().slice(0, 10)

/* Короткая дата для плашки: сервер отдаёт ISO, показываем «28.10», а если год не текущий —
   полную дату (иначе «1 марта» будущего года читается как позавчера). */
function shortDate(iso, lang) {
  if (!iso) return ''
  const [y, m, d] = String(iso).slice(0, 10).split('-')
  if (!y || !m || !d) return String(iso)
  if (y === String(new Date().getFullYear())) return `${d}.${m}`
  const loc = lang === 'en' ? 'en-US' : 'ru-RU'
  const s = new Date(`${y}-${m}-${d}`).toLocaleDateString(loc, { day: '2-digit', month: '2-digit', year: 'numeric' })
  return lang === 'en' ? s : s.replaceAll('/', '.')
}

export default function LifeRegime({ info, onChanged }) {
  const { t, lang } = useI18n()
  const [, show] = useToast()
  const [edit, setEdit] = useState(false)
  const [askDel, setAskDel] = useState(false)
  const [form, setForm] = useState({ title: '', start: todayISO(), end: '', note: '' })

  const cur = info?.current || info?.active || null
  const apply = !!info?.apply
  const counted = !!info?.counted

  useEffect(() => {
    if (!edit) return
    setForm({ title: cur?.title || '', start: cur?.start || todayISO(), end: cur?.end || '', note: cur?.note || '' })
  }, [edit, cur])

  const reload = async () => {
    try { onChanged?.(await api.get('/api/finance/regimes')) } catch { /* тихо: плашка останется прежней */ }
  }

  const toggle = async () => {
    try { await api.post('/api/finance/regime/apply', { on: !apply }); await reload() } catch (e) { show.err(e) }
  }

  const closeRegime = async () => {
    if (!cur) return
    try {
      await api.post(`/api/finance/regimes/${cur.id}/close`, {})
      await reload()
      show(t('reg.closed_ok', { name: cur.title }))
    } catch (e) { show.err(e) }
  }

  const remove = async () => {
    setAskDel(false)
    if (!cur) return
    try { await api.del(`/api/finance/regimes/${cur.id}`); await reload(); show(t('reg.deleted')) } catch (e) { show.err(e) }
  }

  const save = async () => {
    const title = form.title.trim()
    if (!title) return
    const body = { title, start: form.start || null, end: form.end || null, note: form.note || '' }
    try {
      if (cur) await api.put(`/api/finance/regimes/${cur.id}`, body)
      else await api.post('/api/finance/regimes', body)
      setEdit(false)
      await reload()
    } catch (e) { show.err(e) }
  }

  const chipLabel = !cur ? '' : (cur.end
    ? t('reg.chip_range', { name: cur.title, from: shortDate(cur.start, lang), to: shortDate(cur.end, lang) })
    : t('reg.chip', { name: cur.title, from: shortDate(cur.start, lang) }))

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      {cur ? (
        <span className="chip" title={counted ? t('reg.apply_on') : t('reg.apply_off')}>
          {chipLabel}
          {!cur.open && <span className="faint">· {t('reg.chip_closed')}</span>}
        </span>
      ) : (
        <span className="muted text-[12px]">{t('reg.empty')}</span>
      )}

      {cur && (
        <>
          <button type="button" className="btn-soft btn-sm" onClick={() => setEdit(true)} title={t('reg.edit')}>{t('reg.edit')}</button>
          {cur.open && <button type="button" className="btn-soft btn-sm" onClick={closeRegime} title={t('reg.close_tip')}>{t('reg.close')}</button>}
          <button type="button" className="btn-soft btn-sm" onClick={() => setAskDel(true)} title={t('reg.delete_tip')} aria-label={t('reg.delete')}>
            <Trash2 size={13} />
          </button>
        </>
      )}
      {!cur && <button type="button" className="btn-soft btn-sm" onClick={() => setEdit(true)}>{t('reg.new')}</button>}

      {/* переключатель: по умолчанию выключен — без режима цифры считаются как раньше */}
      <button type="button" className={`pill ${apply ? 'on' : ''}`} onClick={toggle} title={t('reg.apply_tip')} aria-pressed={apply}>
        {apply ? t('reg.apply_on') : t('reg.apply_off')}
      </button>

      <Sheet open={edit} onClose={() => setEdit(false)} title={cur ? t('reg.edit') : t('reg.new')} sub={t('reg.apply_tip')}>
        <div className="grid gap-3">
          <Field label={t('reg.name')}>
            <input className="input" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder={t('reg.title')} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('reg.from')}>
              <input type="date" className="input" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
            </Field>
            <Field label={t('reg.to')} hint={form.end ? '' : t('reg.open_until')}>
              <input type="date" className="input" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} />
            </Field>
          </div>
          <Field label={t('reg.note')}>
            <input className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </Field>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-soft" onClick={() => setEdit(false)}>{t('common.cancel')}</button>
            <button type="button" className="btn g" onClick={save} disabled={!form.title.trim()}>{t('common.save')}</button>
          </div>
        </div>
      </Sheet>

      <Confirm open={askDel} danger title={t('reg.delete')} text={t('reg.delete_tip')}
        onOk={remove} onClose={() => setAskDel(false)} />
    </div>
  )
}