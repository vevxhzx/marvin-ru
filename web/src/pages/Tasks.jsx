import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, EyeOff } from 'lucide-react'
import { api, hhmm, isSameDay, isAllDay } from '../lib/api'
import { Num, useToast, useLeave, useArrived, PageAccent, ListSkeleton } from '../components/ui'
import { useRefresh } from '../App'
import TaskSheet from '../components/TaskSheet'
import Aims from '../components/Aims'
import { usePrefs, prefs as PREFS } from '../lib/prefs'
import { usePageAccent } from '../lib/prefs'
import { useCardLayout, CardCtl, useWide } from '../lib/layout'
import { useI18n } from '../lib/i18n'

/* Подписи скрытых карточек в списке настроек — ключи словаря */
const CARD_TITLES = { done: 'tk.done', list: 'nav.tasks', empty: 'tk.list_empty', sort: 'tk.sort' }

const dueTs = (t) => (t.due ? new Date(t.due).getTime() : 9e15)
/* пилюля фильтра (как в People): выбрана — тёмная, нет — светлая */
const pill = (on) => ({ background: on ? 'var(--ink)' : 'var(--sf)', color: on ? 'var(--bg)' : 'var(--ink2)' })
const SORT_FN = {
  priority: (a, b) => a.priority - b.priority || dueTs(a) - dueTs(b),
  due: (a, b) => dueTs(a) - dueTs(b) || a.priority - b.priority,
  new: (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0),
}

/* Карточки этой страницы: порядок и ширина хранятся общим модулем lib/layout */
const CARDS = ['done', 'list', 'empty', 'sort']
const CARD_WIDTHS = { done: 4, list: 8, empty: 6, sort: 6 }

export default function Tasks() {
  const { t } = useI18n()
  const [tasks, setTasks] = useState(null)
  const [params, setParams] = useSearchParams()
  const view = params.get('view') || 'open'
  const setView = (v) => setParams(v === 'open' ? {} : { view: v }, { replace: true })
  const [quick, setQuick] = useState('')
  const [q, setQ] = useState('')        // поиск по заголовку/проекту — локально, по уже загруженным задачам
  const [proj, setProj] = useState('')  // фильтр по проекту ('' — все)
  const nav = useNavigate()
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
  /* «сегодня»: дела на сегодня + встречи из календаря (одна картина, как в утреннем дайджесте) */
  const todayList = useMemo(() => {
    const at = (x) => new Date(x.due || x.start || 0).getTime()
    return [...todayTasks, ...agenda].sort((a, b) => (Number(!!a.done) - Number(!!b.done)) || at(a) - at(b))
  }, [tasks, tasksSort])

  /* Поиск и фильтр по проекту — всё локально, без запросов к серверу.
     Списки ниже считаются из тех же данных, поэтому фильтр применяется и к «сегодня»,
     и к встречам из календаря (у встреч проекта нет — под фильтр проекта они не попадают). */
  const filtering = !!q.trim() || !!proj
  const projects = useMemo(() => [...new Set((tasks || [])
    .filter((t) => t.kind !== 'event' && t.project).map((t) => t.project))]
    .sort((a, b) => String(a).localeCompare(String(b), 'ru')), [tasks])
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    const pass = (t) => (!proj || (t.project || '') === proj)
      && (!s || [t.title, t.project, t.sub, t.category].filter(Boolean).join(' ').toLowerCase().includes(s))
    return { open: open.filter(pass), done: done.filter(pass), today: todayList.filter(pass) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, q, proj, tasksSort])

  const addQuick = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (!quick.trim()) return
    try {
      await api.chat(`задача: ${quick.trim()}`)   // фраза уходит в ядро — всегда по-русски   // i18n-raw   // фраза уходит в ядро — всегда по-русски   // i18n-raw
      setQuick('')
      load()
      bump()
    } catch (err) {
      show.err(err)
    }
  }

  const addQuickDirect = async (title) => {
    try {
      await api.chat(`задача: ${title}`)   // фраза уходит в ядро — всегда по-русски   // i18n-raw   // фраза уходит в ядро — всегда по-русски   // i18n-raw
      load()
      bump()
    } catch (err) {
      show.err(err)
    }
  }

  const toggle = async (task) => {
    if (task.kind === 'event') {   // встреча из календаря: галочка закрывает её и в календаре
      try {
        await api.doneEvent(task.id, !task.done)
        show(t(task.done ? 'tk.back_to_cal' : 'tk.event_done'), '', task.title)
        load(); bump()
      } catch (e) { show.err(e) }
      return
    }
    if (task.done) {
      try { await api.undoneTask(task.id); load(); bump() } catch (e) { show.err(e) }
      return
    }
    // строка сначала красиво уезжает (зелёная вспышка), и только потом задача закрывается
    await leave(task.id, 'done', async () => {
      try {
        await api.doneTask(task.id)
        show(t('tk.task_done'), '', task.title)
        load()
        bump()
      } catch (e) { show.err(e) }
    })
  }

  const currentList = filtering
    ? (view === 'today' ? shown.today : view === 'done' ? shown.done : shown.open)
    : (view === 'today' ? todayList : view === 'done' ? done : open)
  const kicker = filtering
    ? t('tk.found_n', { n: currentList.length })
    : open.length ? t('tk.open_n', { n: open.length }) : t('tk.all_done')
  /* декоративная карточка «список пуст» — только когда реально пусто:
     ни открытых задач, ни невыполненных встреч (и данные уже загружены);
     при активном поиске/фильтре её не показываем — там будет «ничего не нашлось» */
  const nothingToDo = tasks !== null && !filtering && open.length === 0 && !agenda.some((e) => !e.done)
  /* текст пустого списка зависит от вкладки: если в «сегодня» пусто, а задачи в работе есть —
     не пишем «список пуст», иначе выглядит так, будто задач нет совсем */
  const emptyListText = nothingToDo
    ? t('tk.list_empty')
    : view === 'today'
      ? t('tk.today_empty') + (open.length ? ` · ${t('tk.open_n', { n: open.length })}` : '')
      : view === 'done'
        ? t('tk.done_empty')
        : t('tk.open_empty') + (agenda.some((e) => !e.done) ? t('tk.cal_hint') : '')

  return (
    <div className="pg on" id="p-tasks" style={pageAcc.style}>
      {/* Шапка */}
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>{t(view === 'aims' ? 'goals.title' : 'nav.tasks')}</h1>
          <p className="sub r" style={{ '--i': 1 }}>{kicker}</p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          <div className="sg">
            <button type="button" className={view === 'open' ? 'on' : ''} onClick={() => setView('open')}>{t('tk.open')}</button>
            <button type="button" className={view === 'today' ? 'on' : ''} onClick={() => setView('today')}>{t('common.today')}</button>
            <button type="button" className={view === 'done' ? 'on' : ''} onClick={() => setView('done')}>{t('tk.done')}</button>
            <button type="button" className={view === 'aims' ? 'on' : ''} onClick={() => setView('aims')}>{t('goals.title')}</button>
          </div>
          {view !== 'aims' && (
            <>
              <button type="button" className="btn-soft btn-sm" onClick={() => setCardsEdit((v) => !v)} title={t('tk.layout_tip')}>{t('tk.layout')}</button>
              <button type="button" className="btn" onClick={() => setSheet('new')}>+ {t('tk.task')}</button>
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
              placeholder={t('tk.quick_ph')}
            />
            <span className="send" style={{ fontSize: '24px', cursor: 'pointer' }} onClick={addQuick}>+</span>
          </div>

          {/* Поиск и фильтр по проекту — локально, по уже загруженным задачам */}
          <div className="r" style={{ '--i': 2, marginTop: '14px' }}>
            <div className="search" style={{ width: '100%', height: '48px' }}>
              <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                <circle cx="9" cy="9" r="6" />
                <path d="m14 14 3.5 3.5" />
              </svg>
              <input value={q} onChange={(e) => setQ(e.target.value)}
                style={{ background: 'transparent', border: 0, outline: 'none', width: '100%', color: 'inherit', font: 'inherit', marginLeft: '8px' }}
                placeholder={t('tk.search_ph')} />
              {q && <button type="button" className="faint shrink-0 px-1" onClick={() => setQ('')} aria-label={t('tk.clear_search')} title={t('tk.clear_search')}>✕</button>}
            </div>
            {projects.length > 0 && (
              <div className="flex flex-wrap items-center gap-2" style={{ marginTop: '10px' }}>
                <span className="label">{t('task.project')}</span>
                <button type="button" style={pill(!proj)} className="rounded-full px-3 py-1.5 text-[12.5px] font-medium transition" onClick={() => setProj('')}>{t('common.all')}</button>
                {projects.map((p) => (
                  <button type="button" key={p} style={pill(proj === p)} className="rounded-full px-3 py-1.5 text-[12.5px] font-medium transition"
                    onClick={() => setProj(proj === p ? '' : p)}>{p}</button>
                ))}
              </div>
            )}
            {filtering && (
              <div className="flex flex-wrap items-center gap-2" style={{ marginTop: '8px' }}>
                <span className="faint text-[12px]">{t('tk.filter_local', { n: currentList.length })}</span>
                <button type="button" className="btn-ghost btn-sm" onClick={() => { setQ(''); setProj('') }}>{t('common.reset')}</button>
              </div>
            )}
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
                  <div className="hd"><h2>{t('tk.done')}</h2><small>{t('common.total')}</small></div>
                  <div className="big"><Num value={done.length} /></div>
                  <span className="tag">{t(open.length === 0 ? 'tk.all_done' : 'tk.open_n', { n: open.length })}</span>
                  <div className="hm">
                    <div><small>{t('tk.today_cal')}</small><b>{agenda.length}</b></div>
                    <div><small>{t('goals.title')}</small><b>0</b></div>
                  </div>
                </section>
              )
              if (id === 'list') return (
                <section key="list" className="c s8 r" style={st}>{ctl}
                  <div className="hd">
                    <h2>{t(view === 'today' ? 'tk.today_cal' : view === 'done' ? 'tk.done' : 'tk.open_n', { n: open.length })}</h2>
                    <small>{currentList.length}</small>
                  </div>
                  {tasks === null ? (
                    <ListSkeleton n={5} />
                  ) : currentList.length === 0 && filtering ? (
                    <div className="space-y-2" style={{ paddingTop: '12px' }}>
                      <p style={{ color: 'var(--ink3)' }}>
                        {t('common.no_results')}{q.trim() ? t('tk.for_query', { q: q.trim() }) : ''}{proj ? t('tk.in_project', { p: proj }) : ''}.
                      </p>
                      <button type="button" className="btn-soft btn-sm" onClick={() => { setQ(''); setProj('') }}>{t('tk.reset_search')}</button>
                    </div>
                  ) : currentList.length === 0 ? (
                    <p style={{ color: 'var(--ink3)', paddingTop: '12px' }}>{emptyListText}</p>
                  ) : (
                    <>
                      <p className="label" style={{ marginTop: '-6px', marginBottom: '10px', textTransform: 'none', letterSpacing: 0 }}>
                        {t('tk.hint')}
                      </p>
                      {currentList.map((task) => (
                        <div className={`rowi ck ${leaveCls(task.id)} ${arriveCls(task.id)}`} key={task.id}>
                          <input type="checkbox" checked={!!task.done} onChange={() => toggle(task)} aria-label={task.done ? t('od.back_to_work') : t('tk.close_task')} />
                          <span className="t" style={{ cursor: 'pointer' }} onClick={() => (task.kind === 'event' ? nav('/calendar') : setSheet(task))} title={t(task.kind === 'event' ? 'tk.open_cal' : 'tk.open_task')}>
                            {task.title}
                            {task.kind === 'event' ? <small>{t('tk.event')}</small> : (task.sub || task.category ? <small>{task.sub || task.category}</small> : null)}
                          </span>
                          {task.due && !isAllDay(task.due) && <time>{hhmm(task.due)}</time>}
                          <button className="row-open" onClick={() => (task.kind === 'event' ? nav('/calendar') : setSheet(task))} aria-label={t(task.kind === 'event' ? 'tk.open_cal' : 'tk.open_task')} title={t(task.kind === 'event' ? 'tk.in_cal' : 'tk.edit_task')}><ChevronRight size={16} /></button>
                        </div>
                      ))}
                    </>
                  )}
                </section>
              )
              /* карточка скрыта, пока есть открытые задачи или встречи — не показываем её и в «спрятанных» */
              if (id === 'empty') {
                if (!nothingToDo) return null
                return (
                  <section key="empty" className="c p2 s6 r" style={st}>{ctl}
                    <div className="hd"><h2>{t('tk.list_empty')}</h2><small></small></div>
                    <p className="emp">{t('tk.rest_hint')}</p>
                    <button type="button" className="chip" onClick={() => addQuickDirect(t('tk.buy_milk'))}>{t('tk.buy_milk_hint')} ↗</button>
                  </section>
                )
              }
              return (
                <section key="sort" className="c p1 s4 r" style={st}>{ctl}
                  <div className="hd"><h2>{t('tk.sort')}</h2><small></small></div>
                  <div className="sg">
                    <button type="button" className={tasksSort === 'priority' ? 'on' : ''} onClick={() => PREFS.set({ tasksSort: 'priority' })}>{t('tk.by_priority')}</button>
                    <button type="button" className={tasksSort === 'due' ? 'on' : ''} onClick={() => PREFS.set({ tasksSort: 'due' })}>{t('tk.by_due')}</button>
                    <button type="button" className={tasksSort === 'new' ? 'on' : ''} onClick={() => PREFS.set({ tasksSort: 'new' })}>{t('tk.by_new')}</button>
                  </div>
                </section>
              )
            })}
            {cardsEdit && cardOrder.length < CARDS.length && (
              <section className="c s12 r" style={{ '--i': 8 }}>
                <div className="hd"><h2>{t('tk.hidden_cards')}</h2><small>{CARDS.length - cardOrder.length}</small></div>
                <div className="flex flex-wrap gap-2">
                  {CARDS.filter((x) => !cardOrder.includes(x)).map((x) => (
                    <button key={x} className="btn-soft btn-sm" onClick={() => setCardOrder((o) => [...o, x])}>+ {t(CARD_TITLES[x])}</button>
                  ))}
                  <button className="btn-ghost btn-sm" onClick={resetCards}>{t('tk.restore_all')}</button>
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
