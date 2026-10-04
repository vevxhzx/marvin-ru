import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, Search as SearchIcon, X, ChevronRight, ChevronLeft, EyeOff, Pencil, Check, Settings2 } from 'lucide-react'
import { api, hhmm, isSameDay, isAllDay } from '../lib/api'
import { Num, Empty, Swipe, PRIORITY, useToast, useLeave, useArrived, ListSkeleton } from '../components/ui'
import { useRefresh } from '../App'
import TaskSheet from '../components/TaskSheet'
import Aims from '../components/Aims'
import { usePrefs, prefs as PREFS } from '../lib/prefs'
import { usePageAccent } from '../lib/prefs'
import { useCardLayout, CardCtl } from '../lib/layout'
import { useI18n } from '../lib/i18n'
import { usePhone } from '../lib/motion'

/* Подписи полей на узком телефоне (≤380px) — на ступень мельче: длинная подпись
   вроде «дата следующего шага» на 375px съедала строку и отжимала само поле. */
const FIELD_LABEL_M = 'max-[380px]:[&_.label]:text-[length:11px]'

/* pages/Tasks.jsx — «Задачи» в двух раскладках, одна разметка:

   десктоп (≥821px) — панели-карточки: счётчики отдельной карточкой, быстрый ввод и поиск
                     отдельной, группы задач — поверхностями с шапкой и волосяными
                     разделителями внутри;
   телефон (≤820px) — плоские разделы и строки на фоне страницы, крупные зоны нажатия.

   Переключает только CSS (cardM ниже), логика, данные и разметка строк общие.

   Rows keep the markup e2e relies on: #p-tasks .rowi with the task title, the checkbox
   input[aria-label="закрыть задачу"], the view switcher inside .top .sg («выполнено»)
   and the primary action «+ задача». */

/* Поверхность-карточка в обеих раскладках: на десктопе (≥821px) с волосяной рамкой
   --line и отступом pad, на телефоне (≤820px) тот же блок, но легче — отступ 21px,
   радиус из токена (--r-lg), без тени и без хайрлайна: разделение тоном (макет).
   Параметр pad задаёт внутренние отступы блока: на десктопе своё значение, на телефоне
   отступ карточки всё равно 21px, поэтому разметка не дублируется. */
const cardM = (pad = '!p-[var(--card-pad)]') =>
  `c !rounded-[var(--r-lg)] ${pad} max-[820px]:!bg-[var(--sf)] max-[820px]:!p-[21px] max-[820px]:!rounded-[var(--r-lg)] max-[820px]:!shadow-none max-[820px]:!transform-none`

/* Blocks of the page in the «настроить» mode. Stored under a fresh key (tasks2):
   the old layout (done/list/empty/sort cards of the bento grid) has no blocks to
   reuse, and a stale order would hide the counters from an existing user. */
const BLOCKS = ['stats', 'tools', 'list']
const BLOCK_TITLES = { stats: 'tk.open', tools: 'common.search', list: 'nav.tasks' }

/* Заголовок списка для каждого вида */
const VIEW_TITLE = { open: 'tk.open', today: 'common.today_caps', done: 'tk.done', aims: 'goals.title' }
/* Порядок внутри групп задач */
const SORTS = [['priority', 'tk.by_priority'], ['due', 'tk.by_due'], ['new', 'tk.by_new']]

const dueTs = (t) => (t.due ? new Date(t.due).getTime() : 9e15)
const SORT_FN = {
  priority: (a, b) => a.priority - b.priority || dueTs(a) - dueTs(b),
  due: (a, b) => dueTs(a) - dueTs(b) || a.priority - b.priority,
  new: (a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0),
}

/* Общие размеры: зоны нажатия — из токенов, без «сырых» чисел */
const PILL = { minHeight: 'var(--tap)', padding: '0 16px' }
const SEG_BTN = { minHeight: 'var(--tap)', padding: '0 16px' }

/* Ряд чипов на телефоне: одна прокручиваемая строка вместо переноса в несколько рядов */
const CHIPS_ROW_M = 'no-scrollbar max-[820px]:!flex-nowrap max-[820px]:!overflow-x-auto max-[820px]:!pb-1'

/* Точка приоритета в строке: крупная зона нажатия (--tap) и меню через портал в body —
   строка лежит внутри .swipe с overflow:hidden, обычный absolute-попап там обрезался бы. */
function PriorityCell({ value, onChange }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)
  const btn = useRef(null)

  const toggle = () => {
    if (open) return setOpen(false)
    const el = btn.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const left = Math.max(8, Math.min(r.right - 168, window.innerWidth - 168))
    const below = r.bottom + 8 + 150 < window.innerHeight
    setPos({ left, top: below ? r.bottom + 8 : undefined, bottom: below ? undefined : Math.max(8, r.top - 158) })
    setOpen(true)
  }

  useEffect(() => {
    if (!open) return
    const away = (e) => { if (!btn.current?.contains(e.target) && !e.target.closest?.('[data-pr-menu]')) setOpen(false) }
    const key = (e) => { if (e.key === 'Escape') setOpen(false) }
    const scroll = () => setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('touchstart', away, { passive: true })
    document.addEventListener('keydown', key)
    window.addEventListener('scroll', scroll, true)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('touchstart', away)
      document.removeEventListener('keydown', key)
      window.removeEventListener('scroll', scroll, true)
    }
  }, [open])

  const label = t(PRIORITY[value]?.label || 'task.prio_normal')
  return (
    <>
      <button
        ref={btn}
        type="button"
        className="btn-icon shrink-0"
        style={{ width: 'var(--tap)', height: 'var(--tap)' }}
        onClick={toggle}
        aria-label={t('common.priority')}
        aria-haspopup="menu"
        aria-expanded={open}
        title={label}
        data-tip={open ? undefined : label}
      >
        <span className={`h-2.5 w-2.5 rounded-full ${PRIORITY[value]?.dot}`} aria-hidden="true" />
      </button>
      {open && pos && createPortal(
        <div
          data-pr-menu
          role="menu"
          className="elevated fixed z-[130] w-[168px] !p-1"
          style={{ left: pos.left, top: pos.top, bottom: pos.bottom, animation: 'rise .16s var(--ease-out)' }}
        >
          <div className="label px-2.5 pb-1 pt-1.5">{t('common.importance')}</div>
          {[1, 2, 3].map((p) => (
            <button
              key={p}
              type="button"
              role="menuitemradio"
              aria-checked={p === value}
              className="flex w-full items-center gap-2 rounded-lg px-2.5"
              style={{ minHeight: 'var(--tap)', fontSize: 'var(--fs-base)' }}
              onClick={() => { setOpen(false); if (p !== value) onChange(p) }}
            >
              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${PRIORITY[p].dot}`} aria-hidden="true" />
              <span className="min-w-0 flex-1 trunc">{t(PRIORITY[p].label)}</span>
              {p === value && <Check size={15} strokeWidth={2.4} className="shrink-0" style={{ color: 'var(--acc)' }} aria-hidden="true" />}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  )
}

/* Полоса счётчиков — это и есть переключатель вида, поэтому второго сегмента на странице
   нет. Разметка .sg остаётся (единый сегмент системы, на неё ходят проверки e2e).
   На десктопе её границы отдаёт карточка-обёртка, на телефоне сама полоса волосяная:
   телефонная карточка вокруг уже есть, вторая линия была бы лишней. */
/* Переключатель вида — компактные подчёркнутые вкладки с числом, как на «Финансах».
   Разметка .sg остаётся (e2e ищет «выполнено» внутри .top .sg). */
function Counters({ items, view, onChange, label }) {
  const { t } = useI18n()
  return (
    <div className="sg tabs w-full" role="group" aria-label={label}>
      {items.map((c) => {
        const on = c.id === view
        return (
          <button
            key={c.id}
            type="button"
            className={on ? 'on' : ''}
            aria-pressed={on}
            onClick={() => onChange(c.id)}
          >
            {t(c.label)} <b className="num" style={{ fontWeight: 600, opacity: on ? 1 : 0.55 }}>{c.n}</b>
          </button>
        )
      })}
    </div>
  )
}

export default function Tasks() {
  const { t } = useI18n()
  const [tasks, setTasks] = useState(null)
  const [params, setParams] = useSearchParams()
  const view = params.get('view') || 'open'
  const setView = (v) => setParams(v === 'open' ? {} : { view: v }, { replace: true })
  const [quick, setQuick] = useState('')
  const [q, setQ] = useState('')        // search by title/project — local, over the loaded tasks
  const [proj, setProj] = useState('')  // project filter ('' — all)
  const [aims, setAims] = useState(0)    // goals count for the counter strip
  const nav = useNavigate()
  const [sheet, setSheet] = useState(null) // null | 'new' | task
  const [, show] = useToast()
  const { tick, bump } = useRefresh()
  const [{ tasksSort = 'priority' }] = usePrefs()
  const sortFn = SORT_FN[tasksSort] || SORT_FN.priority
  const [cardsEdit, setCardsEdit] = useState(false)
  const { order: blockOrder, setOrder: setBlockOrder, move, reset: resetBlocks } = useCardLayout('tasks2', BLOCKS)
  const pageAcc = usePageAccent('tasks')
  const phone = usePhone()          // ≤820px: телефонная раскладка по макету
  /* row flashes on arrival and leaves nicely when closed */
  const [leaveCls, leave] = useLeave()
  const arriveCls = useArrived((tasks || []).map((t) => t.id))

  const load = () => api.tasks(true, true).then(setTasks).catch(() => {})
  useEffect(() => { load() }, [tick])
  // «+» дока на этом разделе открывает форму новой задачи (AppShell шлёт tasks:add)
  useEffect(() => {
    const on = () => setSheet('new')
    window.addEventListener('tasks:add', on)
    return () => window.removeEventListener('tasks:add', on)
  }, [])
  // goals for the counter strip: the same endpoint the «цели» tab renders
  useEffect(() => {
    let alive = true
    api.get('/api/aims').then((l) => { if (alive) setAims(Array.isArray(l) ? l.length : 0) }).catch(() => {})
    return () => { alive = false }
  }, [tick])

  const now = new Date()
  const all = (tasks || []).filter((t) => t.kind !== 'event')
  const agenda = (tasks || []).filter((t) => t.kind === 'event')
  const open = all.filter((t) => !t.done).sort(sortFn)
  const done = all.filter((t) => t.done).sort((a, b) => new Date(b.done_at || 0) - new Date(a.done_at || 0))
  const todayTasks = open.filter((t) => t.due && isSameDay(t.due, now))
  /* «сегодня»: due today + meetings from the calendar (one picture, as in the morning digest) */
  const todayList = useMemo(() => {
    const at = (x) => new Date(x.due || x.start || 0).getTime()
    return [...todayTasks, ...agenda].sort((a, b) => (Number(!!a.done) - Number(!!b.done)) || at(a) - at(b))
  }, [tasks, tasksSort])

  /* Search and project filter are local, no server requests. Lists are derived from the
     same data, so the filter applies to «сегодня» too; meetings have no project. */
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

  const resetFilters = () => { setQ(''); setProj('') }

  const addQuick = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (!quick.trim()) return
    try {
      await api.chat(`задача: ${quick.trim()}`)   // фраза уходит в ядро — всегда по-русски   // i18n-raw
      setQuick('')
      load()
      bump()
    } catch (err) {
      show.err(err)
    }
  }

  const addQuickDirect = async (title) => {
    try {
      await api.chat(`задача: ${title}`)   // фраза уходит в ядро — всегда по-русски   // i18n-raw
      load()
      bump()
    } catch (err) {
      show.err(err)
    }
  }

  const toggle = async (task) => {
    if (task.kind === 'event') {   // meeting from the calendar: the tick closes it there too
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
    // the row leaves first (a green flash), and only then the task is closed
    await leave(task.id, 'done', async () => {
      try {
        await api.doneTask(task.id)
        show(t('tk.task_done'), '', task.title)
        load()
        bump()
      } catch (e) { show.err(e) }
    })
  }

  const setPriority = async (task, priority) => {
    try { await api.patchTask(task.id, { priority }); load() } catch (e) { show.err(e) }
  }

  const openTask = (task) => (task.kind === 'event' ? nav('/calendar') : setSheet(task))

  const currentList = filtering
    ? (view === 'today' ? shown.today : view === 'done' ? shown.done : shown.open)
    : (view === 'today' ? todayList : view === 'done' ? done : open)
  const kicker = filtering
    ? t('tk.found_n', { n: currentList.length })
    : open.length ? t('tk.open_n', { count: open.length }) : t('tk.all_done')

  const counters = [
    { id: 'open', label: 'tk.open', n: open.length },
    { id: 'today', label: 'common.today', n: todayList.length },
    { id: 'done', label: 'tk.done', n: done.length },
    { id: 'aims', label: 'goals.title', n: aims },
  ]

  /* Пустое состояние: с характером и подсказкой, а не пустая полоса.
     Под фильтром — одно «ничего не нашлось», без «списка пуст» (иначе кажется, что задач нет). */
  const empty = (() => {
    if (filtering) {
      return {
        glyph: 'search',
        text: t('common.no_results'),
        sub: t('tk.filter_local', { n: currentList.length }) + (q.trim() ? t('tk.for_query', { q: q.trim() }) : '') + (proj ? t('tk.in_project', { p: proj }) : ''),
        action: <button type="button" className="btn-soft btn-sm" onClick={resetFilters}>{t('tk.reset_search')}</button>,
      }
    }
    if (view === 'today') return { glyph: 'calendar', text: t('tk.today_empty'), sub: t('tk.empty_today_sub') }
    if (view === 'done') return { glyph: 'tasks', text: t('tk.done_empty'), sub: t('tk.empty_done_sub') }
    return {
      glyph: 'tasks',
      text: t('tk.empty_none'),
      sub: t('tk.empty_none_sub'),
      hint: t('tk.buy_milk'),
      onHint: () => addQuickDirect(t('tk.buy_milk')),
      action: <button type="button" className="btn-primary" onClick={() => setSheet('new')}>{t('task.new')}</button>,
    }
  })()

  const ctl = (id) => (cardsEdit ? (
    <CardCtl
      key={`${id}-ctl`}
      id={id}
      order={blockOrder}
      edit
      onMove={move}
      onHide={(x) => setBlockOrder((o) => o.filter((w) => w !== x))}
      HideIcon={EyeOff}
      Icon={ChevronLeft}
    />
  ) : null)

  return (
    <div className={`pg on ${FIELD_LABEL_M}`} id="p-tasks" style={pageAcc.style}>
      {/* Header: только крупный заголовок. Действия: «+» — в доке (контекстно),
          настройка разделов — ниже, справа от переключателя вида. Переключатель
          (.sg) остаётся внутри .top — на него ходят проверки e2e. */}
      <header className="top">
        <div className="min-w-0 flex-1">
          <h1 className="r trunc" style={{ '--i': 0 }}>{t(view === 'aims' ? 'goals.title' : 'nav.tasks')}</h1>
          <p className="sub r" style={{ '--i': 1 }}>
            {view === 'aims' ? t('goals.active_n', { count: aims }) : kicker}
          </p>
        </div>
        {blockOrder.includes('stats') && (
          <div className="r mt-3 flex w-full items-center gap-2" style={{ '--i': 2 }}>
            <div className="min-w-0 flex-1">
              <Counters items={counters} view={view} onChange={setView} label={t('nav.tasks')} />
            </div>
            {view !== 'aims' && (
              <button
                type="button"
                className="btn-icon outlined shrink-0"
                onClick={() => setCardsEdit((v) => !v)}
                title={t('tk.layout_tip')}
                aria-label={t('tk.layout')}
                aria-pressed={cardsEdit}
              >
                <Settings2 size={16} aria-hidden="true" />
              </button>
            )}
            {/* На ПК добавление остаётся в шапке; на телефоне его заменяет «+» в доке */}
            {view !== 'aims' && (
              <button type="button" className="btn-primary btn-sm head-primary max-[820px]:!hidden shrink-0" onClick={() => setSheet('new')}>
                + {t('tk.task')}
              </button>
            )}
          </div>
        )}
      </header>

      {view === 'aims' ? (
        <div className="mt-6">
          <Aims tick={tick} bump={() => { load(); bump() }} />
        </div>
      ) : (
        <>
          {/* Quick add — one line, your own words. На десктопе панель-карточка, на телефоне
              тот же блок без обёртки. */}
          {blockOrder.includes('tools') && (
            <section className="relative mt-5">
              {ctl('tools')}
              <div className={cardsEdit ? 'pt-8' : ''}>
                {projects.length > 0 && (
                  <div className={`cluster mt-3 ${CHIPS_ROW_M} fade-x`} role="group" aria-label={t('task.project')}>
                    <span className="label">{t('task.project')}</span>
                    <button
                      type="button"
                      className={`pill ${!proj ? 'on' : ''}`}
                      aria-pressed={!proj}
                      style={PILL}
                      onClick={() => setProj('')}
                    >
                      {t('common.all')}
                    </button>
                    {projects.map((p) => (
                      <button
                        key={p}
                        type="button"
                        className={`pill max-[820px]:!shrink-0 ${proj === p ? 'on' : ''}`}
                        aria-pressed={proj === p}
                        style={{ ...PILL, maxWidth: '46vw' }}
                        title={p}
                        onClick={() => setProj(proj === p ? '' : p)}
                      >
                        <span className="trunc">{p}</span>
                      </button>
                    ))}
                  </div>
                )}

                {filtering && (
                  <div className="cluster mt-3">
                    <span className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{t('tk.filter_local', { n: currentList.length })}</span>
                    <button type="button" className="btn-ghost btn-sm" onClick={resetFilters}>{t('tk.reset_search')}</button>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* The list: на десктопе панель-карточка с шапкой и волосяными разделителями,
              на телефоне плоский раздел на фоне страницы. Каскад появления общий. */}
          {blockOrder.includes('list') && (
            <section className={`relative mt-5 ${cardM()}`}>
              {ctl('list')}
              <div
                className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2"
                style={cardsEdit ? { paddingRight: 128 } : undefined}
              >
                <div className="min-w-0">
                  <h2 className="h3">{t(VIEW_TITLE[view] || 'tk.open')}</h2>
                  <p className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 2 }}>{t('tk.hint')}</p>
                </div>
                <div className="sg fade-x max-w-full" role="group" aria-label={t('tk.sort')}>
                  {SORTS.map(([v, key]) => (
                    <button
                      key={v}
                      type="button"
                      className={tasksSort === v ? 'on' : ''}
                      aria-pressed={tasksSort === v}
                      onClick={() => PREFS.set({ tasksSort: v })}
                    >
                      {t(key)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="rule" style={{ marginTop: 'var(--s-3)' }} />

              {tasks === null ? (
                <ListSkeleton n={6} rowH={66} className="mt-2" />
              ) : currentList.length === 0 ? (
                <Empty glyph={empty.glyph} text={empty.text} sub={empty.sub} hint={empty.hint} onHint={empty.onHint} action={empty.action} />
              ) : (
                <div className="stagger">
                  {currentList.map((task) => (
                    <Swipe
                      key={task.id}
                      onRight={task.done ? undefined : () => toggle(task)}
                      onLeft={() => openTask(task)}
                      leftLabel={t('common.edit')}
                      rightLabel={t('common.done')}
                      leftIcon={<Pencil size={18} strokeWidth={2.2} aria-hidden="true" />}
                    >
                      <div
                        className={`rowi ck ${leaveCls(task.id)} ${arriveCls(task.id)} ${task.done ? 'is-done' : ''}`}
                      >
                        {/* big checkbox: the label is the touch target, the circle is 22–26px */}
                        <label className="ck shrink-0" style={{ display: 'grid', placeItems: 'center', width: 'var(--tap)', height: 'var(--tap)', marginLeft: -10 }}>
                          <input
                            type="checkbox"
                            checked={!!task.done}
                            onChange={() => toggle(task)}
                            aria-label={task.done ? t('od.back_to_work') : t('tk.close_task')}
                          />
                        </label>

                        {/* The title takes the whole middle column and wraps freely; the meta
                            (priority, time, project) goes under it — on a narrow screen a
                            long name must not squeeze the row into a tall narrow column. */}
                        <div className="min-w-0 flex-1">
                          <button
                            type="button"
                            className="t"
                            onClick={() => openTask(task)}
                            title={task.title}
                            style={{ display: 'block', width: '100%', textAlign: 'left', overflowWrap: 'anywhere', background: 'transparent', border: 0, font: 'inherit', color: 'inherit', cursor: 'pointer' }}
                          >
                            <span className="flex min-w-0 items-center gap-2">
                              {task.kind !== 'event' && <PriorityCell value={task.priority} onChange={(p) => setPriority(task, p)} />}
                              <span className="trunc font-medium" style={{ fontSize: 'var(--fs-base)' }}>{task.title}</span>
                            </span>
                            {(task.kind === 'event' || task.sub || task.category || task.project) && (
                              <span className="muted mt-0.5 block trunc text-[length:var(--fs-xs)]" title={[task.sub || task.category, task.project].filter(Boolean).join(' · ')}>
                                {task.kind === 'event' ? t('tk.event') : [task.sub || task.category, task.project].filter(Boolean).join(' · ')}
                              </span>
                            )}
                          </button>
                        </div>

                        {task.due && (
                          <span className="due-tag shrink-0">
                            {isAllDay(task.due) ? shortDate(task.due) : hhmm(task.due)}
                          </span>
                        )}

                        <button
                          type="button"
                          className="row-open"
                          onClick={() => openTask(task)}
                          aria-label={task.kind === 'event' ? t('tk.open_cal') : t('tk.edit_task')}
                          title={task.kind === 'event' ? t('tk.in_cal') : t('tk.edit_task')}
                        >
                          <ChevronRight size={16} aria-hidden="true" />
                        </button>
                      </div>
                    </Swipe>
                  ))}
                </div>
              )}
            </section>
          )}

          {cardsEdit && blockOrder.length < BLOCKS.length && (
            <section className="relative mt-7">
              <h2 className="h4">{t('tk.hidden_cards')}</h2>
              <div className="cluster mt-2">
                {BLOCKS.filter((x) => !blockOrder.includes(x)).map((x) => (
                  <button key={x} type="button" className="btn-soft btn-sm" onClick={() => setBlockOrder((o) => [...o, x])}>
                    + {t(BLOCK_TITLES[x])}
                  </button>
                ))}
                <button type="button" className="btn-ghost btn-sm" onClick={resetBlocks}>{t('tk.restore_all')}</button>
              </div>
            </section>
          )}
        </>
      )}

      <TaskSheet
        open={!!sheet}
        task={sheet === 'new' ? null : sheet}
        onClose={() => setSheet(null)}
        onDone={(msg) => { setSheet(null); load(); bump(); if (msg) show(msg) }}
        onErr={show.err}
      />
    </div>
  )
}