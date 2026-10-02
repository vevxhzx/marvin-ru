import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { api, toLocalISO, isAllDay } from '../lib/api'
import { Sheet, Field, Seg, Pills, TimeField, Confirm } from './ui'
import { useI18n } from '../lib/i18n'

/* Одна форма задачи для всего сайта: новая (task=null) и правка существующей (task=…).
   Срок — тремя способами: без срока · на день (23:59, без напоминаний «через час») · ко времени.
   Из TaskPatch API поддерживаются title/due/priority/project/blocked_by — больше в форме нет
   (note/repeat/tags у задач бэкенд не принимает). */
export default function TaskSheet({ open, task, onClose, onDone, onErr }) {
  const { t } = useI18n()
  const blank = { title: '', when: 'none', day: '', time: '', priority: 2, project: '', blocked: '' }
  const [f, setF] = useState(blank)
  const [busy, setBusy] = useState(false)
  const [askDel, setAskDel] = useState(false)
  useEffect(() => {
    if (!open) return
    if (!task) { setF(blank); return }
    const due = task.due ? toLocalISO(task.due) : ''
    setF({ title: task.title || '', when: !due ? 'none' : isAllDay(task.due) ? 'day' : 'time', day: due.slice(0, 10), time: due && !isAllDay(task.due) ? due.slice(11, 16) : '', priority: task.priority || 2, project: task.project || '', blocked: task.blocked_by || '' })
  }, [open, task])
  const dueOf = () => {
    if (f.when === 'none' || !f.day) return null
    return f.when === 'time' && f.time ? `${f.day}T${f.time}` : `${f.day}T23:59`
  }
  const submit = async (e) => {
    e.preventDefault(); if (busy) return
    setBusy(true)
    try {
      const due = dueOf()
      if (task) { await api.patchTask(task.id, { title: f.title, due, clear_due: !due, priority: Number(f.priority), project: f.project || '', blocked_by: f.blocked || '' }); onDone(t('task.updated')) }
      else { await api.addTask({ title: f.title, due, priority: Number(f.priority), project: f.project || null }); onDone(t('task.added')) }
    } catch (err) { onErr?.(err) } finally { setBusy(false) }
  }
  // удаление — только через подтверждение, одним решением, а не случайным кликом
  const del = async () => {
    setAskDel(false)
    try { await api.delTask(task.id); onDone(t('task.deleted')) } catch (err) { onErr?.(err) }
  }
  const todayISO = toLocalISO(new Date()).slice(0, 10)
  const tomorrowISO = toLocalISO(new Date(Date.now() + 864e5)).slice(0, 10)
  const pickWhen = (w) => setF({ ...f, when: w, day: f.day || (w === 'none' ? '' : todayISO) })
  return (
    <Sheet open={open} onClose={onClose} title={task ? t('task.title') : t('task.new')} sub={task ? (task.done ? t('task.done_sub') : undefined) : t('task.new_sub')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('task.what')}><input autoFocus={!task} className="input !text-[17px] !font-medium" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required /></Field>
        <Field label={t('task.prio_label')}><Pills value={Number(f.priority)} onChange={(p) => setF({ ...f, priority: p })} options={[[1, t('task.prio_high')], [2, t('task.prio_normal')], [3, t('task.prio_low')]]} /></Field>
        <Field label={t('task.when')} hint={f.when === 'day' ? t('task.when_day_hint') : f.when === 'time' ? t('task.when_time_hint') : ''}>
          <div className="flex flex-wrap items-center gap-2">
            <Pills value={f.when} onChange={pickWhen} options={[['none', t('task.when_none')], ['day', t('task.when_day')], ['time', t('task.when_time')]]} />
            {f.when !== 'none' && (
              <>
                <Seg value={f.day === todayISO ? 'today' : f.day === tomorrowISO ? 'tomorrow' : 'other'} onChange={(v) => setF({ ...f, day: v === 'today' ? todayISO : v === 'tomorrow' ? tomorrowISO : f.day })} options={[['today', t('common.today')], ['tomorrow', t('common.tomorrow')], ['other', t('task.pick_date')]]} />
                <input type="date" className="input !h-9 !w-auto" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value })} required />
                {f.when === 'time' && <TimeField value={f.time} onChange={(v) => setF({ ...f, time: v })} required />}
              </>
            )}
          </div>
        </Field>
        <Field label={t('task.project')}><input className="input" placeholder={t('task.project_ph')} value={f.project} onChange={(e) => setF({ ...f, project: e.target.value })} /></Field>
        {task && (
          <Field label={t('task.blocked_by')} hint={t('task.blocked_hint')}>
            <input className="input" placeholder={t('task.blocked_ph')} value={f.blocked}
              onChange={(e) => setF({ ...f, blocked: e.target.value })} />
          </Field>
        )}
        <div className="flex gap-2">
          {task && <button type="button" className="btn-ghost !px-3.5 neg" data-tip={t('common.delete')} onClick={() => setAskDel(true)} aria-label={t('common.delete')}><Trash2 size={15} /></button>}
          <button className="btn-primary btn-lg flex-1" disabled={busy}>{task ? t('common.save') : t('common.add')}</button>
        </div>
      </form>
      <Confirm open={askDel} danger title={t('task.delete_title')}
        text={task ? t('task.delete_text', { title: task.title }) : ''}
        onOk={del} onClose={() => setAskDel(false)} />
    </Sheet>
  )
}
