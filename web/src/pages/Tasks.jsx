import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, Search as SearchIcon, X, ChevronRight, ChevronLeft, EyeOff, Pencil, Check, Settings2, SlidersHorizontal } from 'lucide-react'
import { api, hhmm, isSameDay, isAllDay, shortDate } from '../lib/api'
import { Num, Empty, ErrorState, Swipe, PRIORITY, useToast, useLeave, useArrived, ListSkeleton } from '../components/ui'
import { useRefresh } from '../App'
import TaskSheet from '../components/TaskSheet'
import Aims from '../components/Aims'
import { usePrefs, prefs as PREFS } from '../lib/prefs'
import { usePageAccent } from '../lib/prefs'
import { useCardLayout, CardCtl } from '../lib/layout'
import { useI18n, fmtWeekday } from '../lib/i18n'
import { usePhone } from '../lib/motion'
import '../tasks-glass.css'

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
const BLOCKS = ['stats', 'list']
const BLOCK_TITLES = { stats: 'tk.open', list: 'nav.tasks' }

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

/* Группы списка «по сроку» (макет ver6, .gh2: просрочено / сегодня / завтра / …).
   Локальная пара ru+en: i18n.js принадлежит другому агенту, новых ключей не заводим —
   берём язык из useI18n(). */
const GROUP_KEYS = { // i18n-raw — локальная пара ru+en внутри файла, новых ключей в i18n.js не заводим
  ru: { nodue: 'без срока', over: 'просрочено', today: 'сегодня', tom: 'завтра', week: 'на этой неделе', later: 'позже' },
  en: { nodue: 'no due date', over: 'overdue', today: 'today', tom: 'tomorrow', week: 'this week', later: 'later' },
}
const dayStart = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
const groupOf = (task, now) => {
  if (!task.due) return 'nodue'
  const diff = Math.round((dayStart(new Date(task.due)) - dayStart(now)) / 864e5)
  return diff < 0 ? 'over' : diff === 0 ? 'today' : diff === 1 ? 'tom' : diff <= 7 ? 'week' : 'later'
}

/* Превью разбора быстрой строки (макет #qp): подсказка, а не парсер — сама фраза
   всё равно уходит ядру бэкенда (api.chat), которое разбирает её по-своему.
   Ключи русские, как и в самой команде «задача: …» — i18n-raw. */
const quickParse = (s) => {
  let x = ` ${s} `
  let time = null, day = null, imp = false
  const m = x.match(/(\d{1,2})[:.](\d{2})/)
  if (m) { time = `${m[1].padStart(2, '0')}:${m[2]}`; x = x.replace(m[0], ' ') }
  const d = x.match(/\s(послезавтра|завтра|сегодня)(?=\s)/i)
  if (d) { day = { сегодня: 0, завтра: 1, послезавтра: 2 }[d[1].toLowerCase()]; x = x.replace(d[1], ' ') }
  if (/\s(!+|важно)(?=\s)/i.test(x)) imp = true
  if (time && day == null) day = 0
  return { time, day, imp }
}
const dayObj = (off) => { const x = new Date(); x.setDate(x.getDate() + off); return x }
const dateAt = (off) => {
  const d = dayObj(off)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/* Общие размеры: зоны нажатия — из токенов, без «сырых» чисел */
const PILL = { minHeight: 'var(--tap)', padding: '0 16px' }
const SEG_BTN = { minHeight: 'var(--tap)', padding: '0 16px' }

/* Ряд чипов на телефоне: одна прокручиваемая строка вместо переноса в несколько рядов */
const CHIPS_ROW_M = 'no-scrollbar fade-x max-[820px]:!flex-nowrap max-[820px]:!overflow-x-auto max-[820px]:!pb-1'

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

/* Фильтр по важности — кнопка-слайдер в шапке и попап .pp с чипами (макет ver6).
   Попап позиционируется абсолютом внутри .top (там нет overflow), а не порталом —
   шапка не обрезается ни в одной раскладке. */
function PriorityFilter({ value, onChange, projects = [], proj = '', onProj }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)

  useEffect(() => {
    if (!open) return
    const away = (e) => { if (!wrap.current?.contains(e.target)) setOpen(false) }
    const key = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', key) }
  }, [open])

  const opts = [
    [-1, 'common.all', ''],
    [1, 'task.prio_high', PRIORITY[1].dot],
    [2, 'task.prio_normal', PRIORITY[2].dot],
    [3, 'task.prio_low', PRIORITY[3].dot],
  ]
  return (
    <span className="tg-fwrap" ref={wrap}>
      <button
        type="button"
        className={`ib tg-fbtn${value > 0 ? ' on' : ''}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t('common.priority')}
        title={t('common.priority')}
      >
        <SlidersHorizontal size={16} strokeWidth={1.8} aria-hidden="true" />
      </button>
      {open && (
        <div className="tg-pp" role="dialog" aria-label={t('common.priority')}>
          <span className="tg-pp-note">{t('common.priority')}</span>
          <div className="tg-chs">
            {opts.map(([v, key, dot]) => (
              <button
                key={key}
                type="button"
                className={`tg-cp${value === v ? ' on' : ''}`}
                aria-pressed={value === v}
                onClick={() => { onChange(v); setOpen(false) }}
              >
                {dot ? <i className={`tg-cpd ${dot}`} aria-hidden="true" /> : null}
                {t(key)}
              </button>
            ))}
          </div>
          {/* проекты — из уже загруженных задач, без лишних запросов */}
          {onProj && projects.length > 0 && (
            <>
              <span className="tg-pp-note">{t('task.project')}</span>
              <div className="tg-chs">
                <button type="button" className={`tg-cp${!proj ? ' on' : ''}`} aria-pressed={!proj} onClick={() => { onProj(''); setOpen(false) }}>
                  {t('common.all')}
                </button>
                {projects.map((p) => (
                  <button key={p} type="button" className={`tg-cp${proj === p ? ' on' : ''}`} aria-pressed={proj === p} onClick={() => { onProj(p === proj ? '' : p); setOpen(false) }}>
                    {p}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </span>
  )
}

/* Инлайн-редактор строки (макет .edt): раскрывается грид-строкой по шеврону, внутри —
   заголовок, срок (чипы), важность (чипы), удаление. Живёт в DOM всегда (чтобы анимация
   expand работала), скрытые строки гасит visibility — иначе Tab заходил бы в свёрнутые
   поля. Сохранение — те же api.patchTask/delTask, что и в шторке TaskSheet. */
function TaskEditor({ task, open, onClose, onPatch, onDelete }) {
  const { t } = useI18n()
  const [title, setTitle] = useState(task.title)
  const inp = useRef(null)
  useEffect(() => { setTitle(task.title) }, [task.id, task.title])
  // как в макете: фокус в поле через 350 мс после раскрытия
  useEffect(() => {
    if (!open) return
    const id = setTimeout(() => inp.current?.focus(), 350)
    return () => clearTimeout(id)
  }, [open])

  const due = task.due ? String(task.due).slice(0, 10) : null
  const sat = (6 - new Date().getDay() + 7) % 7 || 7   // ближайшая суббота (7 — если сегодня суббота)
  const dayChips = [
    { off: 0, label: t('common.today') },
    { off: 1, label: t('common.tomorrow') },
    { off: sat, label: fmtWeekday(new Date(Date.now() + sat * 864e5), 'long') },
    { off: null, label: t('task.when_none') },
  ]
  const prio = task.priority || 2
  const commit = () => {
    const v = title.trim()
    if (!v) { setTitle(task.title); return }
    if (v !== task.title) onPatch({ title: v })
  }

  return (
    <div className="edt">
      <div className="edi">
        <div className="ep">
          <input
            ref={inp}
            className="ei"
            value={title}
            aria-label={t('common.title')}
            autoComplete="off"
            onChange={(e) => setTitle(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => { if (e.key === 'Enter') { commit(); onClose() } }}
          />
          <div className="er">
            <span>{t('task.when')}</span>
            {dayChips.map((c) => (
              <button
                key={c.off == null ? 'none' : c.off}
                type="button"
                className={`tg-cp${(c.off == null ? !task.due : due === dateAt(c.off)) ? ' on' : ''}`}
                onClick={() => onPatch(c.off == null ? { due: null, clear_due: true } : { due: `${dateAt(c.off)}T23:59` })}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div className="er">
            <span>{t('common.importance')}</span>
            {[3, 2, 1].map((p) => (
              <button
                key={p}
                type="button"
                className={`tg-cp${prio === p ? ' on' : ''}`}
                aria-pressed={prio === p}
                onClick={() => onPatch({ priority: p })}
              >
                <i className={`tg-cpd ${PRIORITY[p].dot}`} aria-hidden="true" />
                {t(PRIORITY[p].label)}
              </button>
            ))}
          </div>
          <div className="er">
            <button type="button" className="tg-del" onClick={onDelete}>{t('common.delete')}</button>
          </div>
        </div>
      </div>
    </div>
  )
}

/* Тост с кнопкой «вернуть» (макет .toast.u): закрытие и удаление можно откатить.
   Свой портал — общий Toaster из ui.jsx кнопок не рисует, а он чужой. */
function UndoToast({ data, onUndo, onClose }) {
  const { t } = useI18n()
  useEffect(() => {
    if (!data) return
    const id = setTimeout(onClose, 4500)
    return () => clearTimeout(id)
  }, [data])
  if (!data) return null
  return createPortal(
    <div className="tg-toast" role="status">
      <span className="tg-toast-t">
        {data.title}
        {data.sub ? <i>{data.sub}</i> : null}
      </span>
      <button type="button" className="tg-toast-u" onClick={onUndo}>{t('mem.restore')}</button>
    </div>,
    document.body,
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
  const { t, lang } = useI18n()
  const [tasks, setTasks] = useState(null)
  const [params, setParams] = useSearchParams()
  const view = params.get('view') || 'open'
  const setView = (v) => setParams(v === 'open' ? {} : { view: v }, { replace: true })
  const [quick, setQuick] = useState('')
  const [q, setQ] = useState('')        // search by title/project — local, over the loaded tasks
  const [proj, setProj] = useState('')  // project filter ('' — all)
  const [prio, setPrio] = useState(-1)  // priority filter from the toolbar popover (-1 — all)
  const [openId, setOpenId] = useState(null) // row expanded by the inline editor
  const [undo, setUndo] = useState(null)     // toast with the «вернуть» button
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
  /* row flashes on arrival and leaves nicely when closed. 1050ms — как в макете:
     кружок заливается ~500мс, строка уезжает вправо и схлопывается, и только потом
     задача закрывается на сервере (см. .leaving-done в tasks-glass.css). */
  const [leaveCls, leave] = useLeave(1050)
  const arriveCls = useArrived((tasks || []).map((t) => t.id))

  const [loadErr, setLoadErr] = useState(false)
  const load = () => { setLoadErr(false); return api.tasks(true, true).then(setTasks).catch(() => setLoadErr(true)) }
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

  /* Side column (glass port): today ring + week bars. Client-side only, derived
     from the already-loaded api.tasks(true,true) payload — no new requests.
     Week bars count done.done_at per day over the last 7 days incl. today. */
  const todayDone = todayList.filter((t) => t.done).length
  const todayTotal = todayList.length
  const ringFrac = todayTotal ? todayDone / todayTotal : 0
  const weekBars = useMemo(() => {
    const days = []
    for (let i = 6; i >= 0; i--) days.push(new Date(now.getFullYear(), now.getMonth(), now.getDate() - i))
    const counts = days.map((d) => done.filter((x) => {
      if (!x.done_at) return false
      const at = new Date(x.done_at)
      return !Number.isNaN(at) && isSameDay(at, d)
    }).length)
    return { days, counts, total: counts.reduce((a, b) => a + b, 0), peak: Math.max(...counts, 0) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks])
  const RING_R = 52
  const RING_C = 2 * Math.PI * RING_R
  /* Кольцо при появлении страницы «прочерчивается» (макет .rg2: 100 → доля через 300мс),
     дальше просто перетекает transition-ом; класс снимаем, чтобы анимация не повторялась. */
  const [ringInit, setRingInit] = useState(true)
  useEffect(() => { const id = setTimeout(() => setRingInit(false), 1400); return () => clearTimeout(id) }, [])
  /* Бары недели растут с перелётом (старт с 2% — как grow() в макете, через 60мс). */
  const [barsUp, setBarsUp] = useState(false)
  useEffect(() => {
    setBarsUp(false)
    const id = setTimeout(() => setBarsUp(true), 60)
    return () => clearTimeout(id)
  }, [weekBars])
  /* Строка-редактор живёт внутри списка: при смене вида или сортировки закрываем. */
  useEffect(() => { setOpenId(null) }, [view, tasksSort])

  /* Текст справа от кольца: сколько осталось / всё сделано + подсказка про просроченное. */
  const remain = todayTotal - todayDone
  const overdueN = open.filter((x) => x.due && new Date(x.due).getTime() < now.getTime()).length
  const ringBig = !todayTotal ? t('tk.today_empty') : remain ? t('tk.open_n', { count: remain }) : t('tk.all_done')

  /* Search and project filter are local, no server requests. Lists are derived from the
     same data, so the filter applies to «сегодня» too; meetings have no project. */
  const filtering = !!q.trim() || !!proj || prio > 0
  const projects = useMemo(() => [...new Set((tasks || [])
    .filter((t) => t.kind !== 'event' && t.project).map((t) => t.project))]
    .sort((a, b) => String(a).localeCompare(String(b), 'ru')), [tasks])
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    const pass = (t) => (!proj || (t.project || '') === proj)
      && (!s || [t.title, t.project, t.sub, t.category].filter(Boolean).join(' ').toLowerCase().includes(s))
      && (prio < 1 || (t.priority || 2) === prio)
    return { open: open.filter(pass), done: done.filter(pass), today: todayList.filter(pass) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tasks, q, proj, prio, tasksSort])

  const resetFilters = () => { setQ(''); setProj(''); setPrio(-1) }

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
    if (leaveCls(task.id)) return   // строка уже уезжает — второй клик не роняем запрос
    if (task.done) {
      try { await api.undoneTask(task.id); load(); bump() } catch (e) { show.err(e) }
      return
    }
    // the row leaves first (checkbox fills, 550ms, then the row slides out), and only
    // then the task is closed — and the toast offers to bring it back
    await leave(task.id, 'done', async () => {
      try {
        await api.doneTask(task.id)
        setUndo({
          title: t('tk.task_done'),
          sub: task.title,
          act: async () => { try { await api.undoneTask(task.id); load(); bump() } catch (e) { show.err(e) } },
        })
        load()
        bump()
      } catch (e) { show.err(e) }
    })
  }

  const patchTask = async (task, p) => {
    try { await api.patchTask(task.id, p); load() } catch (e) { show.err(e) }
  }

  /* Удаление из инлайн-редактора — сразу, но с тостом «вернуть» (макет .dl + undo):
     восстановление собирает задачу заново из полей строки. */
  const removeTask = async (task) => {
    setOpenId(null)
    try {
      await api.delTask(task.id)
      setUndo({
        title: t('task.deleted'),
        sub: task.title,
        act: async () => {
          try {
            await api.addTask({ title: task.title, due: task.due || null, priority: task.priority, project: task.project || null })
            load(); bump()
          } catch (e) { show.err(e) }
        },
      })
      load(); bump()
    } catch (e) { show.err(e) }
  }

  const setPriority = (task, priority) => patchTask(task, { priority })

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
        sub: t('tk.filter_local', { n: currentList.length }) + (q.trim() ? t('tk.for_query', { q: q.trim() }) : '') + (proj ? t('tk.in_project', { p: proj }) : '') + (prio > 0 ? ` · ${t(PRIORITY[prio].label)}` : ''),
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

  /* Строки списка + заголовки групп (макет .gh2). Группы рисуем только при сортировке
     «по сроку» — как list() в макете; чебокс, чипы и инлайн-редактор живут в строке. */
  const grouped = tasksSort === 'due' && view !== 'done'
  const gh = GROUP_KEYS[lang] || GROUP_KEYS.ru

  const renderRow = (task) => {
    const canEdit = task.kind !== 'event' && !task.done   // встречи и закрытые — без редактора
    const editOpen = canEdit && openId === task.id
    const dueCls = !task.done && task.due
      ? (new Date(task.due).getTime() < Date.now() ? ' is-over' : isSameDay(task.due, now) ? ' is-today' : '')
      : ''
    const sub = task.kind === 'event' ? t('tk.event') : [task.sub, task.category].filter(Boolean).join(' · ')
    return (
      <Swipe
        onRight={task.done ? undefined : () => toggle(task)}
        onLeft={() => openTask(task)}
        leftLabel={t('common.edit')}
        rightLabel={t('common.done')}
        leftIcon={<Pencil size={18} strokeWidth={2.2} aria-hidden="true" />}
      >
        <div className={`rowi ck ${leaveCls(task.id)} ${arriveCls(task.id)} ${task.done ? 'is-done' : ''}${editOpen ? ' open' : ''}`}>
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
              (project chip, due chip) goes next to it — on a narrow screen a
              long name must not squeeze the row into a tall narrow column. */}
          <div className="min-w-0 flex-1">
            <button
              type="button"
              className="t"
              onClick={() => openTask(task)}
              title={task.title}
            >
              <span className="flex min-w-0 items-center gap-2">
                {canEdit && <PriorityCell value={task.priority} onChange={(p) => setPriority(task, p)} />}
                <span className="trunc font-medium" style={{ fontSize: 'var(--fs-base)' }}>{task.title}</span>
              </span>
              {sub && (
                <span className="muted mt-0.5 block trunc text-[length:var(--fs-xs)]" title={sub}>
                  {sub}
                </span>
              )}
            </button>
          </div>

          {/* тег проекта — амберный .tag из макета */}
          {task.project && <span className="tg-tag shrink-0" title={task.project}>{task.project}</span>}

          {task.due && (
            <span className={`due-tag shrink-0${dueCls}`}>
              {isAllDay(task.due) ? shortDate(task.due) : hhmm(task.due)}
            </span>
          )}

          {/* шеврон: у встречи — календарь, у готовой задачи его нет (макет), у живой — редактор */}
          {(task.kind === 'event' || !task.done) && (
            <button
              type="button"
              className="row-open"
              onClick={() => (canEdit ? setOpenId(editOpen ? null : task.id) : openTask(task))}
              aria-label={task.kind === 'event' ? t('tk.open_cal') : t('tk.edit_task')}
              title={task.kind === 'event' ? t('tk.in_cal') : t('tk.edit_task')}
              aria-expanded={canEdit ? editOpen : undefined}
            >
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          )}

          {task.kind !== 'event' && (
            <TaskEditor
              task={task}
              open={editOpen}
              onClose={() => setOpenId(null)}
              onPatch={(p) => patchTask(task, p)}
              onDelete={() => removeTask(task)}
            />
          )}
        </div>
      </Swipe>
    )
  }

  const listNodes = () => {
    const out = []
    let g = null
    currentList.forEach((task, idx) => {
      if (grouped) {
        const k = groupOf(task, now)
        if (k !== g) {
          g = k
          out.push(<div key={`gh-${k}`} className={`gh2${k === 'over' ? ' o' : ''}`}>{gh[k]}</div>)
        }
      }
      out.push(
        <div className="tg-sw" key={task.id} style={{ '--k': idx }}>
          {renderRow(task)}
        </div>,
      )
    })
    return out
  }

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
            {/* Фильтр по важности — как .ib + .pp в макете (чипы всех/важные/обычные/низкие) */}
            {view !== 'aims' && (
              <PriorityFilter value={prio} onChange={setPrio} projects={projects} proj={proj} onProj={setProj} />
            )}
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
          <div className="bento mt-5">
          {/* The list: на десктопе широкая glass-панель двухколоночной раскладки
              (вторая колонка — .tg-side ниже), на телефоне плоский раздел.
              Строки без изменений разметки: dot приоритета, заголовок,
              чип due-tag, chevron — одевает tasks-glass.css. */}
          {blockOrder.includes('list') && (
            <section className={`relative s12 tg-list ${cardM()}`} style={{ '--i': 1 }}>
              {ctl('list')}
              <div
                className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2"
                style={cardsEdit ? { paddingRight: 128 } : undefined}
              >
                <div className="min-w-0">
                  <h2 className="h3">{t(VIEW_TITLE[view] || 'tk.open')}</h2>
                  <p className="muted" style={{ fontSize: 'var(--fs-xs)', marginTop: 2 }}>{t('tk.hint')}</p>
                </div>
                {/* Сортировка — как #tso в макете: на вкладке «выполнено» её нет */}
                {view !== 'done' && (
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
                )}
              </div>

              <div className="rule" style={{ marginTop: 'var(--s-3)' }} />

              {/* Быстрый ввод + поиск (макет #qa / .srch). Чипы под строкой — только
                  клиентское превью разбора; сама фраза уходит ядру как раньше. */}
              <div className="tg-tools">
                {view === 'open' && (
                  <form className="tg-quick" onSubmit={addQuick}>
                    <span className="tg-qmark" aria-hidden="true">＋</span>
                    <input
                      value={quick}
                      onChange={(e) => setQuick(e.target.value)}
                      placeholder={t('tk.quick_ph')}
                      aria-label={t('task.what')}
                      autoComplete="off"
                    />
                    <span className="tg-qenter" aria-hidden="true">enter</span>
                    {/* без submit-кнопки неявная отправка по Enter ненадёжна */}
                    <button type="submit" hidden tabIndex={-1} aria-hidden="true">enter</button>
                  </form>
                )}
                <div className="tg-search">
                  <SearchIcon size={15} strokeWidth={2} aria-hidden="true" />
                  <input
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder={t('tk.search_ph')}
                    aria-label={t('common.search')}
                    autoComplete="off"
                  />
                  {q && (
                    <button type="button" onClick={() => setQ('')} aria-label={t('tk.clear_search')} title={t('tk.clear_search')}>
                      <X size={13} aria-hidden="true" />
                    </button>
                  )}
                </div>
              </div>
              {view === 'open' && (
                <div className="tg-chips">
                  {quick.trim() ? (() => {
                    const p = quickParse(quick)
                    const chips = []
                    if (p.day != null) chips.push(<span key="d" className="tg-chip on">{p.day === 0 ? t('common.today') : p.day === 1 ? t('common.tomorrow') : shortDate(dayObj(p.day))}</span>)
                    if (p.time) chips.push(<span key="t" className="tg-chip on">{p.time}</span>)
                    if (p.imp) chips.push(<span key="p" className="tg-chip hot">{t('task.prio_high')}</span>)
                    if (!chips.length) chips.push(<span key="n" className="tg-chip-note muted">{t('task.when_none')}</span>)
                    return chips
                  })() : null}
                </div>
              )}

              {tasks === null ? (
                loadErr ? <ErrorState onRetry={load} /> : <ListSkeleton n={6} rowH={66} className="mt-2" />
              ) : currentList.length === 0 ? (
                <Empty glyph={empty.glyph} text={empty.text} sub={empty.sub} hint={empty.hint} onHint={empty.onHint} action={empty.action} />
              ) : (
                <div className="stagger" key={`${view}-${tasksSort}-${prio}`}>
                  {listNodes()}
                </div>
              )}
            </section>
          )}
          {/* Side column (glass port, ref ver6): ring «сегодня» + бары недели.
              div, не aside — index.css прячет aside на телефоне, а колонка там
              остаётся, стеком под списком. Те же данные, что уже загружены. */}
          {blockOrder.includes('list') && (
            <div className="s12 tg-side">
              <section className={`tg-card ${cardM()}`} style={{ '--i': 2 }}>
                <div className="hd">
                  <h2 className="h3">{t('common.today')}</h2>
                  <small>{t('tk.open_n', { count: open.length })}</small>
                </div>
                {/* как .rg2 в макете: кольцо слева, крупная строка и заметка справа */}
                <div className="tg-ring-row">
                  <div className="tg-ringw">
                    <svg viewBox="0 0 120 120" aria-hidden="true">
                      <circle cx="60" cy="60" r={RING_R} className="tg-ring-track" />
                      <circle
                        cx="60"
                        cy="60"
                        r={RING_R}
                        className={`tg-ring-fg${ringInit ? ' is-init' : ''}`}
                        style={{ '--c': String(RING_C), '--off': String(RING_C * (1 - ringFrac)), strokeDashoffset: 'var(--off)' }}
                        strokeDasharray={RING_C}
                        strokeLinecap="round"
                        transform="rotate(-90 60 60)"
                      />
                    </svg>
                    <div className="tg-ring-ct">
                      <span className="tg-ring-num num">{todayDone}/{todayTotal}</span>
                    </div>
                  </div>
                  <div className="tg-ring-side">
                    <div className="tg-ring-big">{ringBig}</div>
                    {overdueN > 0 && <div className="tg-ring-note">{t('or.overdue_n', { count: overdueN })}</div>}
                  </div>
                </div>
              </section>
              <section className={`tg-card ${cardM()}`} style={{ '--i': 3 }}>
                <div className="hd">
                  <h2 className="h3">{t('common.week')}</h2>
                  <small>{t('tk.done')} · <span className="num">{weekBars.total}</span></small>
                </div>
                <div className="tg-bars" role="img" aria-label={`${t('tk.done')} · ${weekBars.total}`}>
                  {weekBars.days.map((d, i) => {
                    const v = weekBars.counts[i]
                    const peak = v > 0 && v === weekBars.peak
                    // старт с 2% и рост с перелётом — как grow() в макете; пустые дни ноль
                    const h = !v ? 0 : barsUp ? Math.max(Math.round((v / weekBars.peak) * 100), 18) : 2
                    return (
                      <div key={d.toDateString()} className="tg-bar-col">
                        <div className="tg-bar-track">
                          <div className={`tg-bar-fill${peak ? ' is-peak' : ''}`} style={{ height: `${h}%` }} />
                        </div>
                        <span className="tg-bar-day">{fmtWeekday(d, 'short')}</span>
                        <span className="tg-bar-num num">{v || ''}</span>
                      </div>
                    )
                  })}
                </div>
              </section>
            </div>
          )}
          </div>

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

      {/* тост «вернуть» — закрытую задачу и удаление можно откатить (макет .toast.u) */}
      <UndoToast
        data={undo}
        onUndo={() => { const a = undo?.act; setUndo(null); a?.() }}
        onClose={() => setUndo(null)}
      />

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