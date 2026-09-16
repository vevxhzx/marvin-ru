import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { api, toLocalISO, isAllDay } from '../lib/api'
import { Sheet, Field, Seg, Pills } from './ui'

/* Одна форма задачи для всего сайта: новая (task=null) и правка существующей (task=…).
   Срок — тремя способами: без срока · на день (23:59, без напоминаний «через час») · ко времени. */
export default function TaskSheet({ open, task, onClose, onDone, onErr }) {
  const blank = { title: '', when: 'none', day: '', time: '', priority: 2, project: '' }
  const [f, setF] = useState(blank)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!open) return
    if (!task) { setF(blank); return }
    const due = task.due ? toLocalISO(task.due) : ''
    setF({ title: task.title || '', when: !due ? 'none' : isAllDay(task.due) ? 'day' : 'time', day: due.slice(0, 10), time: due && !isAllDay(task.due) ? due.slice(11, 16) : '', priority: task.priority || 2, project: task.project || '' })
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
      if (task) { await api.patchTask(task.id, { title: f.title, due, clear_due: !due, priority: Number(f.priority), project: f.project || '' }); onDone('Задача изменена') }
      else { await api.addTask({ title: f.title, due, priority: Number(f.priority), project: f.project || null }); onDone('Задача добавлена') }
    } catch (err) { onErr?.(err) } finally { setBusy(false) }
  }
  const del = async () => { try { await api.delTask(task.id); onDone('Задача удалена') } catch (err) { onErr?.(err) } }
  const todayISO = toLocalISO(new Date()).slice(0, 10)
  const tomorrowISO = toLocalISO(new Date(Date.now() + 864e5)).slice(0, 10)
  const pickWhen = (w) => setF({ ...f, when: w, day: f.day || (w === 'none' ? '' : todayISO) })
  return (
    <Sheet open={open} onClose={onClose} title={task ? 'задача' : 'новая задача'} sub={task ? (task.done ? 'выполнена' : undefined) : 'или просто скажите ассистенту — он поймёт срок из фразы'}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="что сделать"><input autoFocus={!task} className="input !text-[17px] !font-medium" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required /></Field>
        <Field label="приоритет"><Pills value={Number(f.priority)} onChange={(p) => setF({ ...f, priority: p })} options={[[1, 'важно'], [2, 'обычная'], [3, 'низкая']]} /></Field>
        <Field label="когда" hint={f.when === 'day' ? 'задача на весь день, без часа' : f.when === 'time' ? 'напомню утром и за час' : ''}>
          <div className="flex flex-wrap items-center gap-2">
            <Pills value={f.when} onChange={pickWhen} options={[['none', 'без срока'], ['day', 'на день'], ['time', 'ко времени']]} />
            {f.when !== 'none' && (
              <>
                <Seg value={f.day === todayISO ? 'today' : f.day === tomorrowISO ? 'tomorrow' : 'other'} onChange={(v) => setF({ ...f, day: v === 'today' ? todayISO : v === 'tomorrow' ? tomorrowISO : f.day })} options={[['today', 'сегодня'], ['tomorrow', 'завтра'], ['other', 'дата']]} />
                <input type="date" className="input !h-9 !w-auto" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value })} required />
                {f.when === 'time' && <input type="time" className="input !h-9 !w-auto" value={f.time} onChange={(e) => setF({ ...f, time: e.target.value })} required />}
              </>
            )}
          </div>
        </Field>
        <Field label="проект"><input className="input" placeholder="Работа / Дом" value={f.project} onChange={(e) => setF({ ...f, project: e.target.value })} /></Field>
        <div className="flex gap-2">
          {task && <button type="button" className="btn-ghost !px-3.5 neg" data-tip="удалить" onClick={del} aria-label="Удалить"><Trash2 size={15} /></button>}
          <button className="btn-primary btn-lg flex-1" disabled={busy}>{task ? 'сохранить' : 'добавить'}</button>
        </div>
      </form>
    </Sheet>
  )
}
