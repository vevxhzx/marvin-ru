import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { api, toLocalISO, isAllDay } from '../lib/api'
import { Sheet, Field, TimeField, Confirm, PRIORITY } from './ui'
import { useI18n } from '../lib/i18n'

/* Task form — the only task form in the app: new (task=null) and edit an existing one.
   Due date in three ways: no date · on a day (23:59, no "in an hour" reminders) · at a time.
   TaskPatch accepts title/due/priority/project/blocked_by — nothing else is in the form
   (the backend rejects note/repeat/tags).

   Sheet gives the three phone snaps (peek / half / full), the draggable grip and
   velocity close (components/ui.jsx + lib/gestures.js), so the form only fills it:
   big touch targets (priority and date pills ≥ --tap), calm rows, nothing clipped. */

const PRIOS = [1, 2, 3]
const WHENS = [['none', 'task.when_none'], ['day', 'task.when_day'], ['time', 'task.when_time']]
/* Pills are hand-rolled instead of <Pills>: the shared one is 32px tall, and here a
   thumb needs the full --tap. Shape and active state stay the .pill from index.css. */
const PILL = { minHeight: 'var(--tap)', padding: '0 18px', fontSize: 'var(--fs-base)' }
const BIG_FIELD = { minHeight: 'var(--tap-lg)' }

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
    setF({
      title: task.title || '',
      when: !due ? 'none' : isAllDay(task.due) ? 'day' : 'time',
      day: due.slice(0, 10),
      time: due && !isAllDay(task.due) ? due.slice(11, 16) : '',
      priority: task.priority || 2,
      project: task.project || '',
      blocked: task.blocked_by || '',
    })
  }, [open, task])

  const dueOf = () => {
    if (f.when === 'none' || !f.day) return null
    return f.when === 'time' && f.time ? `${f.day}T${f.time}` : `${f.day}T23:59`
  }

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    try {
      const due = dueOf()
      if (task) {
        await api.patchTask(task.id, { title: f.title, due, clear_due: !due, priority: Number(f.priority), project: f.project || '', blocked_by: f.blocked || '' })
        onDone(t('task.updated'))
      } else {
        await api.addTask({ title: f.title, due, priority: Number(f.priority), project: f.project || null })
        onDone(t('task.added'))
      }
    } catch (err) { onErr?.(err) } finally { setBusy(false) }
  }

  // deletion goes through a confirmation: one decision, never a stray click
  const del = async () => {
    setAskDel(false)
    try { await api.delTask(task.id); onDone(t('task.deleted')) } catch (err) { onErr?.(err) }
  }

  const todayISO = toLocalISO(new Date()).slice(0, 10)
  const tomorrowISO = toLocalISO(new Date(Date.now() + 864e5)).slice(0, 10)
  const dayKey = f.day === todayISO ? 'today' : f.day === tomorrowISO ? 'tomorrow' : 'other'
  const pickWhen = (w) => setF({ ...f, when: w, day: f.day || (w === 'none' ? '' : todayISO) })
  const pickDay = (v) => setF({ ...f, day: v === 'today' ? todayISO : v === 'tomorrow' ? tomorrowISO : f.day })

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={task ? t('task.title') : t('task.new')}
      sub={task ? (task.done ? t('task.done_sub') : undefined) : t('task.new_sub')}
    >
      <form onSubmit={submit} className="space-y-5">
        <Field label={t('task.what')}>
          <input
            autoFocus={!task}
            required
            className="input"
            style={{ ...BIG_FIELD, fontSize: 'var(--fs-lg)', fontWeight: 500 }}
            value={f.title}
            onChange={(e) => setF({ ...f, title: e.target.value })}
          />
        </Field>

        <Field label={t('task.prio_label')}>
          <div className="cluster" role="group" aria-label={t('task.prio_label')}>
            {PRIOS.map((p) => (
              <button
                key={p}
                type="button"
                className={`pill ${Number(f.priority) === p ? 'on' : ''}`}
                aria-pressed={Number(f.priority) === p}
                style={PILL}
                onClick={() => setF({ ...f, priority: p })}
              >
                <span className={`h-2 w-2 shrink-0 rounded-full ${PRIORITY[p].dot}`} aria-hidden="true" />
                {t(PRIORITY[p].label)}
              </button>
            ))}
          </div>
        </Field>

        <Field
          label={t('task.when')}
          hint={f.when === 'day' ? t('task.when_day_hint') : f.when === 'time' ? t('task.when_time_hint') : ''}
        >
          <div className="stack" style={{ gap: 'var(--s-3)' }}>
            <div className="cluster" role="group" aria-label={t('task.when')}>
              {WHENS.map(([w, key]) => (
                <button
                  key={w}
                  type="button"
                  className={`pill ${f.when === w ? 'on' : ''}`}
                  aria-pressed={f.when === w}
                  style={PILL}
                  onClick={() => pickWhen(w)}
                >
                  {t(key)}
                </button>
              ))}
            </div>

            {f.when !== 'none' && (
              <div className="cluster" style={{ gap: 'var(--s-2)' }}>
                <div className="seg" role="group" aria-label={t('common.date')}>
                  {[['today', 'common.today'], ['tomorrow', 'common.tomorrow'], ['other', 'task.pick_date']].map(([v, key]) => (
                    <button
                      key={v}
                      type="button"
                      className={dayKey === v ? 'on' : ''}
                      aria-pressed={dayKey === v}
                      style={{ minHeight: 'var(--tap)' }}
                      onClick={() => pickDay(v)}
                    >
                      {t(key)}
                    </button>
                  ))}
                </div>
                <input
                  type="date"
                  required
                  aria-label={t('task.pick_date')}
                  className="input"
                  style={{ ...BIG_FIELD, flex: '1 1 168px', minWidth: 0 }}
                  value={f.day}
                  onChange={(e) => setF({ ...f, day: e.target.value })}
                />
                {f.when === 'time' && (
                  <div style={{ minWidth: '116px', flex: '0 0 auto' }}>
                    <TimeField
                      required
                      className="!min-h-[var(--tap-lg)]"
                      value={f.time}
                      onChange={(v) => setF({ ...f, time: v })}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        </Field>

        <Field label={t('task.project')}>
          <input
            className="input"
            placeholder={t('task.project_ph')}
            value={f.project}
            onChange={(e) => setF({ ...f, project: e.target.value })}
          />
        </Field>

        {task && (
          <Field label={t('task.blocked_by')} hint={t('task.blocked_hint')}>
            <input
              className="input"
              placeholder={t('task.blocked_ph')}
              value={f.blocked}
              onChange={(e) => setF({ ...f, blocked: e.target.value })}
            />
          </Field>
        )}

        <div className="flex items-center gap-2">
          {task && (
            <button
              type="button"
              className="btn-icon outlined shrink-0"
              onClick={() => setAskDel(true)}
              aria-label={t('common.delete')}
              title={t('common.delete')}
              data-tip={t('common.delete')}
            >
              <Trash2 size={17} />
            </button>
          )}
          <button type="submit" className="btn-primary btn-lg flex-1" disabled={busy}>
            {task ? t('common.save') : t('common.add')}
          </button>
        </div>
      </form>

      <Confirm
        open={askDel}
        danger
        title={t('task.delete_title')}
        text={task ? t('task.delete_text', { title: task.title }) : ''}
        onOk={del}
        onClose={() => setAskDel(false)}
      />
    </Sheet>
  )
}