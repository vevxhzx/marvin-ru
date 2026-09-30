import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, EyeOff } from 'lucide-react'
import { api, hhmm, isSameDay, plural } from '../lib/api'
import { Num, useToast, useLeave, useArrived, PageAccent, ListSkeleton } from '../components/ui'
import { useRefresh } from '../App'
import TaskSheet from '../components/TaskSheet'
import Aims from '../components/Aims'
import { usePrefs, prefs as PREFS } from '../lib/prefs'
import { usePageAccent } from '../lib/prefs'
import { useCardLayout, CardCtl, useWide } from '../lib/layout'

const dueTs = (t) => (t.due ? new Date(t.due).getTime() : 9e15)
const SORT_FN = {
  priority: (a, b) => a.priority - b.priority || dueTs(a) - dueTs(b),
  due: (a, b) => dueTs(a) - dueTs(b) || a.priority - b.priority,
  new: (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0),
}

/* Карточки этой страницы: порядок и ширина хранятся общим модулем lib/layout */
const CARDS = ['done', 'list', 'empty', 'sort']
const CARD_WIDTHS = { done: 4, list: 8, empty: 6, sort: 6 }

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
  const [cardsEdit, setCardsEdit] = useState(false)
  const { order: cardOrder, setOrder: setCardOrder, widths: cardWidths, move, cycleWidth, reset: resetCards } = useCardLayout('tasks', CARDS, CARD_WIDTHS)
  const wide = useWide()
  const pageAcc = usePageAccent('tasks')
  /* плашка задачи: уезжает с анимацией при закрытии и вспыхивает при появлении новой */
  const [leaveCls, leave] = useLeave()
  const arriveCls = useArrived((tasks || []).map((t) => t.id))

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
    if (t.done) {
      try { await api.undoneTask(t.id); load(); bump() } catch (e) { show.err(e) }
      return
    }
    // строка сначала красиво уезжает (зелёная вспышка), и только потом задача закрывается
    await leave(t.id, 'done', async () => {
      try {
        await api.doneTask(t.id)
        show('Задача закрыта', '', t.title)
        load()
        bump()
      } catch (e) { show.err(e) }
    })
  }

  const currentList = view === 'today' ? todayTasks : view === 'done' ? done : open
  const kicker = open.length ? `${open.length} в работе` : 'всё сделано'

  return (
    <div className="pg on" id="p-tasks" style={pageAcc.style}>
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
            <>
              <span className="btn-soft btn-sm" onClick={() => setCardsEdit((v) => !v)} title="Переместить, спрятать или поменять ширину карточек">настроить</span>
              <span className="btn" onClick={() => setSheet('new')}>+ задача</span>
              <PageAccent page="tasks" />
            </>
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

          {/* Bento сетка задач: порядок и ширина настраиваются кнопкой «настроить» */}
          <div className="bento">
            {cardOrder.map((id, i) => {
              const st = { '--i': 3 + i, ...(wide ? { gridColumn: `span ${cardWidths[id] || CARD_WIDTHS[id]}` } : {}) }
              const ctl = (
                <CardCtl id={id} order={cardOrder} edit={cardsEdit} wide={wide}
                  onMove={move} onHide={(x) => setCardOrder((o) => o.filter((w) => w !== x))}
                  onWidth={cycleWidth} width={cardWidths[id] || CARD_WIDTHS[id]}
                  Icon={ChevronLeft} HideIcon={EyeOff} />
              )
              if (id === 'done') return (
                <section key="done" className="c hero s4 r" style={st}>{ctl}
                  <div className="hd"><h2>выполнено</h2><small>всего</small></div>
                  <div className="big"><Num value={done.length} /></div>
                  <span className="tag">{open.length === 0 ? 'всё сделано' : `${open.length} в работе`}</span>
                  <div className="hm">
                    <div><small>сегодня по календарю</small><b>{agenda.length}</b></div>
                    <div><small>цели</small><b>0</b></div>
                  </div>
                </section>
              )
              if (id === 'list') return (
                <section key="list" className="c s8 r" style={st}>{ctl}
                  <div className="hd">
                    <h2>{view === 'today' ? 'сегодня по календарю' : view === 'done' ? 'выполнено' : 'задачи в работе'}</h2>
                    <small>{currentList.length}</small>
                  </div>
                  {tasks === null ? (
                    <ListSkeleton n={5} />
                  ) : currentList.length === 0 ? (
                    <p style={{ color: 'var(--ink3)', paddingTop: '12px' }}>список пуст</p>
                  ) : (
                    <>
                      <p className="label" style={{ marginTop: '-6px', marginBottom: '10px', textTransform: 'none', letterSpacing: 0 }}>
                        кружок слева — закрыть задачу · название — открыть и изменить
                      </p>
                      {currentList.map((t) => (
                        <div className={`rowi ck ${leaveCls(t.id)} ${arriveCls(t.id)}`} key={t.id}>
                          <input type="checkbox" checked={!!t.done} onChange={() => toggle(t)} aria-label={t.done ? 'вернуть в работу' : 'закрыть задачу'} />
                          <span className="t" style={{ cursor: 'pointer' }} onClick={() => setSheet(t)} title="открыть задачу">
                            {t.title}
                            {t.sub || t.category ? <small>{t.sub || t.category}</small> : null}
                          </span>
                          {t.due && <time>{hhmm(t.due)}</time>}
                          <button className="row-open" onClick={() => setSheet(t)} aria-label="открыть задачу" title="изменить задачу"><ChevronRight size={16} /></button>
                        </div>
                      ))}
                    </>
                  )}
                </section>
              )
              if (id === 'empty') return (
                <section key="empty" className="c p2 s6 r" style={st}>{ctl}
                  <div className="hd"><h2>список пуст</h2><small></small></div>
                  <p className="emp">можно отдыхать, сэр. или сказать мне что-нибудь</p>
                  <span className="chip" onClick={() => addQuickDirect('купить молоко')}>«задача: купить молоко» ↗</span>
                </section>
              )
              return (
                <section key="sort" className="c p1 s6 r" style={st}>{ctl}
                  <div className="hd"><h2>сортировка</h2><small></small></div>
                  <div className="sg">
                    <span className={tasksSort === 'priority' ? 'on' : ''} onClick={() => PREFS.set({ tasksSort: 'priority' })}>по важности</span>
                    <span className={tasksSort === 'due' ? 'on' : ''} onClick={() => PREFS.set({ tasksSort: 'due' })}>по сроку</span>
                    <span className={tasksSort === 'new' ? 'on' : ''} onClick={() => PREFS.set({ tasksSort: 'new' })}>по новизне</span>
                  </div>
                  <p style={{ marginTop: '18px', opacity: 0.8 }}>важное сверху, просроченное подсвечивается</p>
                </section>
              )
            })}
            {cardsEdit && cardOrder.length < CARDS.length && (
              <section className="c s12 r" style={{ '--i': 8 }}>
                <div className="hd"><h2>спрятанные карточки</h2><small>{CARDS.length - cardOrder.length}</small></div>
                <div className="flex flex-wrap gap-2">
                  {CARDS.filter((x) => !cardOrder.includes(x)).map((x) => (
                    <button key={x} className="btn-soft btn-sm" onClick={() => setCardOrder((o) => [...o, x])}>+ {({ done: 'выполнено', list: 'задачи', empty: 'список пуст', sort: 'сортировка' })[x]}</button>
                  ))}
                  <button className="btn-ghost btn-sm" onClick={resetCards}>вернуть всё как было</button>
                </div>
              </section>
            )}
          </div>
        </>
      )}

      <TaskSheet open={!!sheet} task={sheet === 'new' ? null : sheet} onClose={() => setSheet(null)}
        onDone={(msg) => { setSheet(null); load(); bump(); if (msg) show(msg) }} onErr={show.err} />
    </div>
  )
}
