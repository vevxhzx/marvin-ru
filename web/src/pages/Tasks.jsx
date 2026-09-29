import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, hhmm, isSameDay, plural } from '../lib/api'
import { Num, useToast } from '../components/ui'
import { useRefresh } from '../App'
import TaskSheet from '../components/TaskSheet'
import Aims from '../components/Aims'
import { usePrefs, prefs as PREFS } from '../lib/prefs'

const dueTs = (t) => (t.due ? new Date(t.due).getTime() : 9e15)
const SORT_FN = {
  priority: (a, b) => a.priority - b.priority || dueTs(a) - dueTs(b),
  due: (a, b) => dueTs(a) - dueTs(b) || a.priority - b.priority,
  new: (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0),
}

export default function Tasks() {
  const [tasks, setTasks] = useState(null)
  const [params, setParams] = useSearchParams()
  const view = params.get('view') || 'open'
  const setView = (v) => setParams(v === 'open' ? {} : { view: v }, { replace: true })
  const [quick, setQuick] = useState('')
  const [sheet, setSheet] = useState(null) // null | 'new' | задача
  const [, show] = useToast()
  const { tick, bump } = useRefresh()
  const [{ tasksSort = 'priority' }] = usePrefs()
  const sortFn = SORT_FN[tasksSort] || SORT_FN.priority

  const load = () => api.tasks(true, true).then(setTasks).catch(() => {})
  useEffect(() => { load() }, [tick])

  const now = new Date()
  const all = (tasks || []).filter((t) => t.kind !== 'event')
  const agenda = (tasks || []).filter((t) => t.kind === 'event')
  const open = all.filter((t) => !t.done).sort(sortFn)
  const done = all.filter((t) => t.done).sort((a, b) => new Date(b.done_at || 0) - new Date(a.done_at || 0))
  const todayTasks = open.filter((t) => t.due && isSameDay(t.due, now))

  const addQuick = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (!quick.trim()) return
    try {
      await api.chat(`задача: ${quick.trim()}`)
      setQuick('')
      load()
      bump()
    } catch (err) {
      show.err(err)
    }
  }

  const addQuickDirect = async (title) => {
    try {
      await api.chat(`задача: ${title}`)
      load()
      bump()
    } catch (err) {
      show.err(err)
    }
  }

  const toggle = async (t) => {
    try {
      if (t.done) {
        await api.undoneTask(t.id)
      } else {
        await api.doneTask(t.id)
        show('Задача закрыта', '', t.title)
      }
      load()
      bump()
    } catch (e) {
      show.err(e)
    }
  }

  const currentList = view === 'today' ? todayTasks : view === 'done' ? done : open
  const kicker = open.length ? `${open.length} в работе` : 'всё сделано'

  return (
    <div className="pg on" id="p-tasks">
      {/* Шапка */}
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>{view === 'aims' ? 'цели' : 'задачи'}</h1>
          <p className="sub r" style={{ '--i': 1 }}>{kicker}</p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          <div className="sg">
            <span className={view === 'open' ? 'on' : ''} onClick={() => setView('open')}>открытые</span>
            <span className={view === 'today' ? 'on' : ''} onClick={() => setView('today')}>сегодня</span>
            <span className={view === 'done' ? 'on' : ''} onClick={() => setView('done')}>выполнено</span>
            <span className={view === 'aims' ? 'on' : ''} onClick={() => setView('aims')}>цели</span>
          </div>
          {view !== 'aims' && (
            <span className="btn" onClick={() => setSheet('new')}>+ задача</span>
          )}
        </div>
      </div>

      {view === 'aims' ? (
        <div className="mt-8">
          <Aims tick={tick} bump={() => { load(); bump() }} />
        </div>
      ) : (
        <>
          {/* Композер задач */}
          <div className="comp r" style={{ '--i': 2 }}>
            <i></i>
            <input
              className="ph0"
              style={{ background: 'transparent', border: 0, outline: 'none', width: '100%', color: 'inherit' }}
              value={quick}
              onChange={(e) => setQuick(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addQuick(e)}
              placeholder="быстро, своими словами: «позвонить маме завтра в 18»…"
            />
            <span className="send" style={{ fontSize: '24px', cursor: 'pointer' }} onClick={addQuick}>+</span>
          </div>

          {/* Bento сетка задач */}
          <div className="bento">
            {/* Карточка 1: Выполнено (hero.s4) */}
            <section className="c hero s4 r" style={{ '--i': 3 }}>
              <div className="hd"><h2>выполнено</h2><small>всего</small></div>
              <div className="big"><Num value={done.length} /></div>
              <span className="tag">{open.length === 0 ? 'всё сделано' : `${open.length} в работе`}</span>
              <div className="hm">
                <div><small>сегодня по календарю</small><b>{agenda.length}</b></div>
                <div><small>цели</small><b>0</b></div>
              </div>
            </section>

            {/* Карточка 2: Список задач (s8) */}
            <section className="c s8 r" style={{ '--i': 4 }}>
              <div className="hd">
                <h2>{view === 'today' ? 'сегодня по календарю' : view === 'done' ? 'выполнено' : 'задачи в работе'}</h2>
                <small>{currentList.length}</small>
              </div>
              {currentList.length === 0 ? (
                <p style={{ color: 'var(--ink3)', paddingTop: '12px' }}>список пуст</p>
              ) : (
                currentList.map((t) => (
                  <label className="rowi ck" key={t.id}>
                    <input type="checkbox" checked={!!t.done} onChange={() => toggle(t)} />
                    <span className="t">
                      {t.title}
                      {t.sub || t.category ? <small>{t.sub || t.category}</small> : null}
                    </span>
                    {t.due && <time>{hhmm(t.due)}</time>}
                  </label>
                ))
              )}
            </section>

            {/* Карточка 3: Список пуст (p2.s6) */}
            <section className="c p2 s6 r" style={{ '--i': 5 }}>
              <div className="hd"><h2>список пуст</h2><small></small></div>
              <p className="emp">можно отдыхать, сэр. или сказать мне что-нибудь</p>
              <span className="chip" onClick={() => addQuickDirect('купить молоко')}>«задача: купить молоко» ↗</span>
            </section>

            {/* Карточка 4: Сортировка (p1.s6) */}
            <section className="c p1 s6 r" style={{ '--i': 6 }}>
              <div className="hd"><h2>сортировка</h2><small></small></div>
              <div className="sg">
                <span className={tasksSort === 'priority' ? 'on' : ''} onClick={() => PREFS.set({ tasksSort: 'priority' })}>по важности</span>
                <span className={tasksSort === 'due' ? 'on' : ''} onClick={() => PREFS.set({ tasksSort: 'due' })}>по сроку</span>
                <span className={tasksSort === 'new' ? 'on' : ''} onClick={() => PREFS.set({ tasksSort: 'new' })}>по новизне</span>
              </div>
              <p style={{ marginTop: '18px', opacity: 0.8 }}>важное сверху, просроченное подсвечивается</p>
            </section>
          </div>
        </>
      )}

      <TaskSheet open={!!sheet} task={sheet === 'new' ? null : sheet} onClose={() => setSheet(null)} onDone={() => { setSheet(null); load(); bump() }} />
    </div>
  )
}
