import { Component, useEffect, useState, createContext, useContext, useCallback, useRef } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Sun, Moon, Monitor, Sparkles, Wallet, CalendarDays, CheckSquare, Brain, Settings as SettingsIcon, Search, PanelLeftClose, PanelLeftOpen, Bell, History, MessageCircle, Briefcase, Square, Play, Users, Clapperboard } from 'lucide-react'
import Settings from './pages/Settings'
import { notifyFromEvent } from './lib/notify'
import { chimeFromEvent } from './lib/sound'
import Today from './pages/Today'
import Finance from './pages/Finance'
import Calendar from './pages/Calendar'
import Tasks from './pages/Tasks'
import Mind from './pages/Mind'
import Memory from './pages/Memory'
import People from './pages/People'
import BoardPage from './pages/Board'
import Orders, { useTimer, mmss } from './pages/Orders'
import Chat from './components/Chat'
import Palette from './components/Palette'
import { useLive, LiveDot, LivePopover, MicButton } from './components/Live'
import { setName, lower } from './lib/name'
import { usePrefs, prefs as PREFS, pullRemote, CLIENT_ID } from './lib/prefs'
import { api, relTime, kb, kbAlt } from './lib/api'
import { tg, tgBackButton } from './lib/tg'
import { Toaster, toast } from './components/ui'

/* Навигация по смыслу: рабочее пространство и система */
export const NAV_GROUPS = [
  { title: 'рабочее', items: [
    { to: '/', label: 'сегодня', icon: Sparkles, key: '1' },
    { to: '/tasks', label: 'задачи', icon: CheckSquare, key: '2' },
    { to: '/calendar', label: 'календарь', icon: CalendarDays, key: '3' },
    { to: '/finance', label: 'финансы', icon: Wallet, key: '4' },
    { to: '/orders', label: 'заказы', icon: Briefcase, key: '5' },
    { to: '/mind', label: 'мозг', icon: Brain, key: '6' },
    { to: '/board', label: 'доска', icon: Clapperboard, key: '0' },
    { to: '/people', label: 'люди', icon: Users, key: '9' },
  ] },
  { title: 'система', items: [
    { to: '/memory', label: 'память', icon: History, key: '7' },
    { to: '/settings', label: 'настройки', icon: SettingsIcon, key: '8' },
  ] },
]
const NAV = NAV_GROUPS.flatMap((g) => g.items)
const MOBILE_NAV = [NAV[0], NAV[1], NAV[2], NAV[3], NAV[4]]

// тема
const ThemeCtx = createContext(null)
export const useTheme = () => useContext(ThemeCtx)

function useThemeState() {
  const [mode, setModeState] = useState(() => localStorage.getItem('theme') || 'auto')
  const setMode = useCallback((m) => { setModeState(m); PREFS.set({ theme: m }) }, [])
  useEffect(() => { const h = (e) => setModeState(e.detail || 'auto'); window.addEventListener('prefs:theme', h); return () => window.removeEventListener('prefs:theme', h) }, [])
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const dark = mode === 'dark' || (mode === 'auto' && mq.matches)
      document.documentElement.classList.toggle('dark', dark)
      document.querySelector('meta[name=theme-color]')?.setAttribute('content', dark ? '#0e0e0d' : '#ecece9')
    }
    apply()
    mq.addEventListener('change', apply)
    localStorage.setItem('theme', mode)
    return () => mq.removeEventListener('change', apply)
  }, [mode])
  return [mode, setMode]
}

/* Ошибка отрисовки одной страницы не должна гасить весь экран в чёрный: ловим её здесь,
   показываем, что случилось, и даём уйти на главную. При смене маршрута сбрасывается. */
class PageGuard extends Component {
  state = { err: null, key: this.props.pathKey }
  static getDerivedStateFromError(err) { return { err } }
  static getDerivedStateFromProps(p, st) { return p.pathKey !== st.key ? { err: null, key: p.pathKey } : null }
  componentDidCatch(err) { try { console.error('page crashed:', err) } catch {} }
  render() {
    if (!this.state.err) return this.props.children
    const msg = String(this.state.err?.message || this.state.err).slice(0, 200)
    return (
      <div className="mx-auto max-w-[520px] py-16 text-center animate-rise">
        <div className="label mb-2">страница сломалась</div>
        <h1 className="text-[28px] font-semibold tracking-[-0.03em]">Что-то пошло не так</h1>
        <p className="muted mt-2 text-[14px]">Ошибка при отрисовке этой страницы. Остальное работает.</p>
        <pre className="fill mt-4 overflow-x-auto rounded-xl px-3 py-2 text-left text-[12px] leading-relaxed" style={{ whiteSpace: 'pre-wrap' }}>{msg}</pre>
        <div className="mt-5 flex justify-center gap-2">
          <button className="btn-ghost" onClick={() => this.setState({ err: null })}>попробовать ещё раз</button>
          <a className="btn-primary" href="/">на главную</a>
        </div>
      </div>
    )
  }
}

function NotFound() {
  const nav = useNavigate()
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-center">
      <div className="label">такой страницы нет</div>
      <div className="h1-sm">{window.location.pathname}</div>
      <button className="btn-soft btn-sm mt-2" onClick={() => nav('/')}>на главную</button>
    </div>
  )
}

// глобальный refresh: после действий в чате обновляем страницы
const RefreshCtx = createContext({ tick: 0, bump: () => {} })
export const useRefresh = () => useContext(RefreshCtx)

/* Центр уведомлений: напоминания, действия из Telegram/голоса, автоплатежи. Хранится в браузере (последние 40) */
const INBOX_KEY = 'inbox.v1'
const ACT_WORDS = { add_event: 'событие в календаре', add_task: 'задача', add_expense: 'трата', add_income: 'доход', add_note: 'мысль', add_link: 'ссылка', add_debt: 'долг', pay_debt: 'платёж по долгу', move_event: 'событие перенесено', complete_task: 'задача закрыта', add_recurring: 'регулярный платёж', undo: 'отмена', bulk_delete: 'удаление', add_order: 'заказ', update_order: 'заказ обновлён', order_payment: 'оплата по заказу', pomodoro: 'таймер', add_goal: 'цель', save_to_goal: 'в копилку' }
const CH_WORDS = { tg: 'Telegram', 'tg-voice': 'Telegram · голос', voice: 'голос', system: 'авто', web: 'сайт' }
function useInbox() {
  const [items, setItems] = useState(() => { try { return JSON.parse(localStorage.getItem(INBOX_KEY) || '[]') } catch { return [] } })
  const save = (next) => { setItems(next); localStorage.setItem(INBOX_KEY, JSON.stringify(next.slice(0, 40))) }
  const push = useCallback((it) => setItems((cur) => { const next = [{ id: Date.now() + Math.random(), at: new Date().toISOString(), read: false, ...it }, ...cur].slice(0, 40); localStorage.setItem(INBOX_KEY, JSON.stringify(next)); return next }), [])
  const markAll = () => save(items.map((x) => ({ ...x, read: true })))
  const clear = () => save([])
  return { items, push, markAll, clear, unread: items.filter((x) => !x.read).length }
}
export function inboxFromEvent(d) {
  if (!d) return null
  if (d.kind === 'reminder') return { title: d.text || 'Напоминание', sub: 'напоминание', tone: 'accent' }
  if (d.kind === 'recurring') return { title: d.text || 'Регулярный платёж проведён', sub: 'авто', tone: 'ok' }
  if (d.kind === 'payment_alert') return { title: d.text || 'На ближайшие платежи может не хватить', sub: 'финансы', tone: 'accent' }
  if (d.kind === 'chat' && d.channel && d.channel !== 'web' && d.actions?.length) {
    const what = [...new Set(d.actions.map((a) => ACT_WORDS[a]).filter(Boolean))]
    if (what.length) return { title: what.join(', ').replace(/^./, (c) => c.toUpperCase()), sub: `из ${CH_WORDS[d.channel] || d.channel}`, tone: 'ok' }
  }
  return null
}

/* Переход между страницами: короткий, без блюра */
function PageTransition({ children, pathKey }) {
  const [shown, setShown] = useState({ key: pathKey, node: children })
  const [phase, setPhase] = useState('enter')
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    if (pathKey === shown.key) { setShown({ key: pathKey, node: children }); return }
    setPhase('exit')
    const t = setTimeout(() => { setShown({ key: pathKey, node: children }); setPhase('enter') }, 130)
    return () => clearTimeout(t)
  }, [pathKey, children]) // eslint-disable-line
  return <div key={shown.key} className={phase === 'exit' ? 'page-exit' : 'page-enter'}>{shown.node}</div>
}

// координаты клика → CSS-переменные для «волны» на кнопках
if (typeof window !== 'undefined') {
  window.addEventListener('pointerdown', (e) => {
    const b = e.target.closest?.('.btn-primary, .btn-dark')
    if (!b) return
    const r = b.getBoundingClientRect()
    b.style.setProperty('--rx', `${((e.clientX - r.left) / r.width) * 100}%`)
    b.style.setProperty('--ry', `${((e.clientY - r.top) / r.height) * 100}%`)
  }, { passive: true })
}

/* Идущее помодоро — в шапке на всех страницах: осталось, по какому заказу, стоп одной кнопкой */
function TopTimer() {
  const { t, left, reload } = useTimer()
  const nav = useNavigate()
  if (!t?.active) return null
  const brk = t.kind === 'break'
  return (
    <div className={`flex items-center gap-1.5 rounded-full py-1 pl-2.5 pr-1 text-[12.5px] md:hidden ${brk ? 'soft-pos' : 'soft-accent'} ${left === 0 ? 'animate-pulse' : ''}`}>
      <button className="flex items-center gap-1.5" onClick={() => nav('/orders')} data-tip={t.order || (brk ? 'перерыв' : 'фокус')}>
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'currentColor' }} />
        <span className="num font-medium tabular-nums">{mmss(left)}</span>
        {t.order && <span className="hidden max-w-[140px] truncate lg:inline">{t.order}</span>}
      </button>
      <button className="grid h-6 w-6 place-items-center rounded-full transition hover:bg-[var(--fill)]" aria-label="Стоп" data-tip="стоп" onClick={() => api.stopTimer().then(reload).catch(() => {})}><Square size={10} /></button>
    </div>
  )
}

/* Мини-помодоро в сайдбаре: кольцо + время + заказ. Нет таймера — кнопка «▶ 25:00» (длина из настроек).
   Клик по времени — на страницу заказов, стоп — квадрат. В свёрнутой панели — только кольцо. */
function SideTimer({ min }) {
  const { t, left, reload } = useTimer()
  const nav = useNavigate()
  const [busy, setBusy] = useState(false)
  const active = !!t?.active
  const brk = t?.kind === 'break'
  const total = active ? t.planned_min * 60 : 1
  const pct = active ? Math.min(1, left / total) : 0
  const R = min ? 11 : 13, C = 2 * Math.PI * R, S = R * 2 + 6
  const color = brk ? 'var(--pos)' : 'var(--accent)'
  const run = (fn) => { if (busy) return; setBusy(true); fn().then(reload).catch(() => {}).finally(() => setBusy(false)) }
  const ring = (
    <span className="relative grid shrink-0 place-items-center" style={{ width: S, height: S }}>
      <svg width={S} height={S} viewBox={`0 0 ${S} ${S}`} className="-rotate-90">
        <circle cx={S / 2} cy={S / 2} r={R} fill="none" stroke="var(--line-2)" strokeWidth="2" />
        {active && <circle cx={S / 2} cy={S / 2} r={R} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeDasharray={C} strokeDashoffset={C * (1 - pct)} style={{ transition: 'stroke-dashoffset 1s linear' }} />}
      </svg>
      {active ? <span className={`absolute h-1.5 w-1.5 rounded-full ${left === 0 ? 'dot-live' : ''}`} style={{ background: color, color }} /> : <Play size={9} className="absolute muted" />}
    </span>
  )
  if (min) {
    return (
      <button className="grid h-9 w-9 place-items-center rounded-xl transition hover:bg-[var(--fill)]" data-tip={active ? `${mmss(left)} · ${t.order || (brk ? 'перерыв' : 'фокус')} · клик — стоп` : `помодоро ${t?.focus_min || 25} мин`} data-tip-side="right"
        onClick={() => run(() => (active ? api.stopTimer() : api.startTimer(null, null)))}>{ring}</button>
    )
  }
  if (!active) {
    return (
      <button className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-[12.5px] transition hover:bg-[var(--fill)]" onClick={() => run(() => api.startTimer(null, null))} data-tip="запустить помодоро">
        {ring}
        <span className="num font-medium tabular-nums">{String(t?.focus_min || 25).padStart(2, '0')}:00</span>
        <span className="muted truncate">{t?.today_sessions ? `сегодня ${t.today_sessions} ${t.today_sessions === 1 ? "помидор" : t.today_sessions < 5 ? "помидора" : "помидоров"}` : 'помодоро'}</span>
      </button>
    )
  }
  return (
    <div className={`flex items-center gap-2.5 rounded-xl py-2 pl-3 pr-1.5 text-[12.5px] ${brk ? 'soft-pos' : 'soft-accent'}`} style={{ animation: 'rise .25s var(--ease-out)' }}>
      <button className="flex min-w-0 flex-1 items-center gap-2.5" onClick={() => nav('/orders')} data-tip={t.order || (brk ? 'перерыв' : 'фокус')}>
        {ring}
        <span className="min-w-0 text-left leading-tight">
          <span className={`num block font-medium tabular-nums ${left === 0 ? 'animate-pulse' : ''}`}>{mmss(left)}</span>
          <span className="block truncate text-[11px] opacity-70">{t.order || (brk ? 'перерыв' : 'фокус')}</span>
        </span>
      </button>
      <button className="grid h-7 w-7 shrink-0 place-items-center rounded-lg transition hover:bg-[var(--fill)]" aria-label="Стоп" data-tip="стоп" onClick={() => run(() => api.stopTimer())}><Square size={10} /></button>
    </div>
  )
}

/* Состояние ассистента для шапки/сайдбара: готов · думает · офлайн · только правила */
export function assistantState(live, busy) {
  if (busy) return { dot: 'var(--accent)', text: 'думаю…', pulse: true }
  if (live.core === 'wait') return { dot: 'var(--ink-3)', text: 'подключаюсь…' }
  if (live.core === 'down') return { dot: 'var(--neg)', text: 'ядро офлайн' }
  const pc = live.pc
  if (pc?.alive && ['listening', 'thinking', 'speaking'].includes(pc.mode)) return { dot: 'var(--pos)', text: { listening: 'слушаю', thinking: 'думаю', speaking: 'говорю' }[pc.mode], pulse: true }
  if (live.brain) return { dot: 'var(--accent)', text: 'готов' }
  return { dot: 'var(--warn)', text: 'готов · без модели' }
}

function Sidebar({ live, busy, hiddenNav = [] }) {
  const st = assistantState(live, busy)
  const { t, left } = useTimer()
  const nav = useNavigate()
  const [pop, setPop] = useState(false)
  const pomoTime = t?.active ? mmss(left) : '90:00'
  const pomoLabel = t?.active ? (t.order || (t.kind === 'break' ? 'перерыв' : 'фокус')) : 'помодоро'

  return (
    <aside>
      <div className="logo"><i></i>{lower()}</div>
      <nav>
        <NavLink to="/" end className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><circle cx="10" cy="10" r="2"/></svg>сегодня
        </NavLink>
        <NavLink to="/tasks" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><rect x="3" y="3" width="14" height="14" rx="4"/><path d="m7 10 2 2 4-4"/></svg>задачи
        </NavLink>
        <NavLink to="/calendar" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><rect x="3" y="4" width="14" height="13" rx="3"/><path d="M3 8h14M7 2v3M13 2v3"/></svg>календарь
        </NavLink>
        <NavLink to="/finance" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><rect x="3" y="5" width="14" height="11" rx="3"/><path d="M13 10.5h1"/></svg>финансы
        </NavLink>
        {!hiddenNav.includes('/orders') && (
          <NavLink to="/orders" className={({ isActive }) => isActive ? 'on' : ''}>
            <svg viewBox="0 0 20 20"><rect x="3" y="6" width="14" height="10" rx="3"/><path d="M7.5 6V4.5h5V6"/></svg>заказы
          </NavLink>
        )}
        <NavLink to="/mind" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><path d="M10 3.5a4 4 0 0 0-4 4 3 3 0 0 0-1 5 3.5 3.5 0 0 0 5 3.5zm0 0a4 4 0 0 1 4 4 3 3 0 0 1 1 5 3.5 3.5 0 0 1-5 3.5z"/></svg>мозг
        </NavLink>
        <NavLink to="/board" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><rect x="3" y="4" width="14" height="12" rx="3"/><path d="M7 4v12M13 4v12"/></svg>доска
        </NavLink>
        <NavLink to="/people" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><circle cx="7.5" cy="7" r="2.5"/><circle cx="14" cy="8" r="2"/><path d="M3 16c0-3 2-4.5 4.5-4.5S12 13 12 16M13 12c2 0 4 1 4 4"/></svg>люди
        </NavLink>
        <NavLink to="/memory" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="M10 6v4l2.5 2.5"/></svg>память
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="3"/><path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4"/></svg>настройки
        </NavLink>
      </nav>
      <div className="sb">
        <div className="pomo select-none" onClick={() => nav('/orders')} style={{ cursor: 'pointer', outline: 'none' }}>
          <svg className="pomo-gauge" viewBox="0 0 24 24" style={{ outline: 'none', border: 'none', boxShadow: 'none' }}>
            <defs>
              <linearGradient id="pomoSideGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#5b7cff" />
                <stop offset="100%" stopColor="#c04cff" />
              </linearGradient>
            </defs>
            <circle className="bg" cx="12" cy="12" r="10" />
            <circle className="fg" cx="12" cy="12" r="10" stroke="url(#pomoSideGrad)" />
          </svg>
          <span><b className="mono">{pomoTime}</b> {pomoLabel}</span>
        </div>
        <div className="relative">
          <div className="st" onClick={() => setPop((v) => !v)} style={{ cursor: 'pointer' }} title={st.text}>
            <i className="dot" style={{ background: st.dot }}></i>
            {st.text}
          </div>
          {pop && <LivePopover live={live} onClose={() => setPop(false)} place="absolute bottom-[calc(100%+8px)] left-0" />}
        </div>
      </div>
    </aside>
  )
}

export function Logo({ size = 22 }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-lg" style={{ width: size + 6, height: size + 6, background: 'var(--ink)', color: 'var(--bg)' }}>
      <svg width={size - 6} height={size - 6} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="butt"><path d="M12 3v18M3 12h18M6 6l12 12M18 6L6 18" /></svg>
    </span>
  )
}

function InboxPanel({ inbox, onClose }) {
  const ref = useRef(null)
  useEffect(() => {
    const h = (e) => { if (!ref.current?.contains(e.target)) onClose() }
    const k = (e) => e.key === 'Escape' && onClose()
    setTimeout(() => { document.addEventListener('mousedown', h); document.addEventListener('keydown', k) }, 0)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [onClose])
  useEffect(() => { const t = setTimeout(inbox.markAll, 1200); return () => clearTimeout(t) }, []) // eslint-disable-line
  return (
    <div ref={ref} className="elevated absolute right-0 top-[44px] z-[75] w-[340px] max-w-[calc(100vw-24px)] overflow-hidden !p-0" style={{ animation: 'rise .22s var(--ease-out)' }}>
      <div className="flex items-center justify-between border-b hair px-4 py-2.5">
        <div className="text-[13px] font-medium">уведомления</div>
        {inbox.items.length > 0 && <button className="faint text-[12px] hover:text-accent" onClick={inbox.clear}>очистить</button>}
      </div>
      <div className="scroll-thin max-h-[calc(60vh/var(--ui-zoom))] overflow-y-auto">
        {inbox.items.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <div className="text-[14px] font-medium">Пока тихо</div>
            <div className="muted mt-1 text-[12.5px]">Сюда придут напоминания и то, что {lower()} сделал из Telegram или голосом.</div>
          </div>
        ) : inbox.items.map((it) => (
          <div key={it.id} className="flex items-start gap-3 border-b hair px-4 py-3 last:border-0">
            <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${it.read ? '' : 'dot-live'}`} style={{ background: it.read ? 'var(--line-2)' : 'var(--accent)', color: 'var(--accent)' }} />
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] leading-snug">{it.title}</div>
              <div className="faint mt-0.5 text-[11.5px]">{[it.sub, relTime(it.at)].filter(Boolean).join(' · ')}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Shell({ inbox }) {
  const [mode, setMode] = useTheme()
  const [health, setHealth] = useState(null)
  const [chatOpen, setChatOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const loc = useLocation()
  const nav = useNavigate()
  const [min, setMinState] = useState(() => localStorage.getItem('sidebar') === 'min')
  const setMin = (v) => { setMinState(v); localStorage.setItem('sidebar', v ? 'min' : 'full') }

  useEffect(() => {
    const load = () => api.health().then((h) => { setHealth(h); if (h?.name) setName(h.name) }).catch(() => setHealth({ ok: false }))
    load(); const t = setInterval(load, 30000); return () => clearInterval(t)
  }, [])
  useEffect(() => { window.scrollTo({ top: 0 }) }, [loc.pathname])
  // внутри Telegram: системная кнопка «назад» в шапке ведёт на главную (с главной Telegram сам показывает «закрыть»)
  useEffect(() => {
    if (!tg.active) return
    return tgBackButton(loc.pathname !== '/', () => nav('/'))
  }, [loc.pathname, nav])
  const [palOpen, setPalOpen] = useState(false)
  const [livePop, setLivePop] = useState(false)
  const [inboxOpen, setInboxOpen] = useState(false)
  const live = useLive(health)
  // ⌘K / ⌘/ — палитра; ⌘J — чат; Alt+1..9 — разделы
  useEffect(() => {
    const h = (e) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && (e.key.toLowerCase() === 'k' || e.key === '/')) { e.preventDefault(); setPalOpen((v) => !v) }
      else if (mod && e.key.toLowerCase() === 'j') { e.preventDefault(); setChatOpen((v) => !v) }
      else if (e.altKey && !mod && /^[0-9]$/.test(e.key)) { const it = NAV.find((n) => n.key === e.key); if (it) { e.preventDefault(); nav(it.to) } }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [nav])
  // кнопка-подсказка в пустых состояниях: открыть чат с готовой фразой
  const [chatSeed, setChatSeed] = useState(null)
  useEffect(() => {
    const h = (e) => { setChatSeed({ text: e.detail?.text || '', n: Date.now(), send: !!e.detail?.send }); setChatOpen(true) }
    const b = (e) => setBusy(!!e.detail)
    window.addEventListener('assistant:chat', h); window.addEventListener('assistant:busy', b)
    return () => { window.removeEventListener('assistant:chat', h); window.removeEventListener('assistant:busy', b) }
  }, [])

  // 401 от любого запроса: чужое устройство / истёкшая сессия Telegram — вместо вечных скелетонов честный экран
  const [denied, setDenied] = useState(null)
  useEffect(() => {
    const h = (e) => setDenied((d) => d || e.detail)
    window.addEventListener('assistant:denied', h); return () => window.removeEventListener('assistant:denied', h)
  }, [])

  const cycle = () => {
    document.documentElement.classList.add('theme-anim')
    setTimeout(() => document.documentElement.classList.remove('theme-anim'), 600)
    setMode(mode === 'auto' ? 'light' : mode === 'light' ? 'dark' : 'auto')
  }
  const ThemeIcon = mode === 'light' ? Sun : mode === 'dark' ? Moon : Monitor
  const st = assistantState(live, busy)
  const [prefs] = usePrefs()
  const [address, setAddress] = useState('сэр')
  useEffect(() => {
    const load = () => api.settings().then((d) => { const it = d.items?.find((x) => x.key === 'owner.name'); setAddress(it?.value ? String(it.value).toLowerCase() : '') }).catch(() => {})
    load(); pullRemote()
    const h = (e) => { if (e.detail?.kind === 'settings') load() }
    window.addEventListener('assistant:event', h)
    return () => window.removeEventListener('assistant:event', h)
  }, [])
  // режим фрилансера: выключен — «заказы» уходят из меню/палитры/нижней панели (страница остаётся доступна по адресу)
  const [freelance, setFreelance] = useState(() => localStorage.getItem('freelance.on') !== '0')
  useEffect(() => {
    const apply = (r) => { setFreelance(!!r.enabled); localStorage.setItem('freelance.on', r.enabled ? '1' : '0') }
    api.freelance().then(apply).catch(() => {})
    const h = (e) => apply(e.detail || {})
    window.addEventListener('freelance:changed', h); return () => window.removeEventListener('freelance:changed', h)
  }, [])
  const hiddenNav = freelance ? prefs.hiddenNav : [...prefs.hiddenNav, '/orders']
  const mobileNav = (prefs.tabbar || []).filter((to) => freelance || to !== '/orders').map((to) => NAV.find((n) => n.to === to)).filter(Boolean).slice(0, 5)

  if (denied) return <Gate denied={denied} />

  return (
    <>
      <div className="aur"><i></i><i></i><i></i></div>
      <div className="app">
        <Sidebar live={live} busy={busy} hiddenNav={hiddenNav} />

        <main>
          <div className="gt r">
            <TopTimer />
            <div className="search" onClick={() => setPalOpen(true)} style={{ cursor: 'pointer' }}>
              <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><circle cx="9" cy="9" r="6"/><path d="m14 14 3.5 3.5"/></svg>
              найти<span className="kbd mono">Ctrl K</span>
            </div>
            <div className="ib" onClick={() => setInboxOpen((v) => !v)} style={{ cursor: 'pointer' }}>
              <svg viewBox="0 0 20 20"><path d="M5 14V9a5 5 0 0 1 10 0v5l1.5 1.5h-13zM8.5 18h3"/></svg>
              {inbox.unread > 0 && <u></u>}
            </div>
            <div className="av" onClick={() => setChatOpen(true)} style={{ cursor: 'pointer' }}>
              {address ? address.slice(0, 1).toLowerCase() : 'в'}
            </div>
          </div>

          <div className="relative">
            {inboxOpen && <InboxPanel inbox={inbox} onClose={() => setInboxOpen(false)} />}
          </div>

          {health && !health.ok && (
            <div className="mb-6 animate-rise">
              <div className="soft-neg flex flex-wrap items-center justify-between gap-2 rounded-2xl px-4 py-2.5 text-[13px]">
                <span>Ядро не отвечает — данные могут быть устаревшими.</span>
                <button className="btn-ghost btn-sm" onClick={() => api.health().then(setHealth).catch(() => {})}>проверить снова</button>
              </div>
            </div>
          )}

          <PageGuard pathKey={loc.pathname}>
            <Routes location={loc}>
              <Route path="/" element={<Today openChat={() => setChatOpen(true)} address={address} />} />
              <Route path="/finance" element={<Finance />} />
              <Route path="/calendar" element={<Calendar />} />
              <Route path="/tasks" element={<Tasks />} />
              <Route path="/orders" element={<Orders />} />
              <Route path="/mind" element={<Mind />} />
              <Route path="/board" element={<BoardPage />} />
              <Route path="/board/:id" element={<BoardPage />} />
              <Route path="/people" element={<People />} />
              <Route path="/memory" element={<Memory />} />
              <Route path="/settings" element={<Settings health={health} />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </PageGuard>
        </main>

        {/* bottom tabs (mobile <= 820px) */}
        <nav className="tabbar fixed inset-x-0 bottom-0 z-[60] md:hidden">
          <div className="mx-3 flex items-stretch justify-around rounded-full border hair px-1 py-1" style={{ background: 'var(--surface-2)', boxShadow: 'var(--shadow-2)' }}>
            {(mobileNav.length ? mobileNav : MOBILE_NAV.filter((n) => freelance || n.to !== '/orders')).map(({ to, label, icon: I }) => (
              <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) =>
                `flex flex-1 flex-col items-center gap-0.5 rounded-full py-2 text-[10px] font-medium transition ${isActive ? 'text-accent' : 'faint'}`}>
                <I size={19} strokeWidth={2} /> <span>{label}</span>
              </NavLink>
            ))}
          </div>
        </nav>

        <Chat open={chatOpen} onClose={() => setChatOpen(false)} seed={chatSeed} />
        <Palette open={palOpen} onClose={() => setPalOpen(false)} openChat={() => setChatOpen(true)} setTheme={setMode} />
        <Toaster />
      </div>
    </>
  )
}

function Gate({ denied }) {
  const tgMode = denied.tg
  const title = tgMode ? (denied.tgError ? 'Telegram не подтвердил вход' : 'Сессия истекла') : 'Нет доступа с этого устройства'
  // webview Telegram, но без данных для входа: сайт открыт как обычная ссылка, а не кнопкой бота
  const tgLink = !tgMode && /Telegram|TelegramBot|tgWebApp/i.test(navigator.userAgent + location.hash) || (!tgMode && !!window.Telegram)
  const text = tgMode
    ? (denied.tgError ? `${denied.tgError}.` : 'Закройте приложение и откройте его снова — Telegram подтвердит вход заново.')
    : tgLink
      ? 'Сайт открыт как обычная ссылка — так Telegram не передаёт данные для входа. Вернитесь в чат с ботом и нажмите кнопку «Открыть» слева от поля ввода или отправьте /app и нажмите кнопку под ответом.'
      : 'Этот ассистент отвечает только своему владельцу. Откройте сайт по QR из ⚙ Настроек → «телефон» на компьютере или через кнопку «Открыть» в чате с ботом в Telegram.'
  return (
    <div className="safe-t flex min-h-screen items-center justify-center px-6">
      <div className="animate-rise w-full max-w-sm text-center">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl" style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: 'var(--ink-3)' }} />
        </div>
        <div className="h3">{title}</div>
        <p className="muted mt-2 text-[14px] leading-relaxed">{text}</p>
        {tgMode ? (
          <button className="btn-primary mt-6" onClick={() => { try { tg.app?.close() } catch {} location.reload() }}>закрыть и открыть заново</button>
        ) : (
          <button className="btn-ghost mt-6" onClick={() => location.reload()}>проверить снова</button>
        )}
        <div className="faint mt-8 text-[12px]">Данные не покидают компьютер владельца. Этот экран — всё, что видно без входа.</div>
      </div>
    </div>
  )
}

export default function App() {
  const theme = useThemeState()
  const [tick, setTick] = useState(0)
  const bump = useCallback(() => setTick((t) => t + 1), [])
  const inbox = useInbox()
  // живые обновления: что-то сделано в Telegram / голосом / планировщиком → страницы перечитывают данные
  useEffect(() => {
    let es, timer
    const connect = () => {
      es = new EventSource('/api/events/stream')
      es.onmessage = (ev) => {
        let d = null
        try { d = JSON.parse(ev.data) } catch {}
        if (d) window.dispatchEvent(new CustomEvent('assistant:event', { detail: d }))
        if (d?.kind === 'pc_state') return          // пульс ПК-клиента — данные не менялись
        if (d?.kind === 'ui_prefs') { if (d.origin !== CLIENT_ID) pullRemote(); return }   // оформление поменяли на другом устройстве
        if (d?.kind === 'settings') return          // owner.name и т.п. — Shell перечитает сам по assistant:event
        clearTimeout(timer); timer = setTimeout(bump, 150)
        if (d) {
          try { notifyFromEvent(d) } catch {}
          try { chimeFromEvent(d) } catch {}
          const it = inboxFromEvent(d)
          if (it) { inbox.push(it); if (document.visibilityState === 'visible') toast(it.title, { sub: it.sub, kind: it.tone === 'ok' ? 'ok' : '' }) }
        }
      }
      es.onerror = () => { es.close(); setTimeout(connect, 4000) }
    }
    connect()
    const onVis = () => { if (document.visibilityState === 'visible') bump() }
    document.addEventListener('visibilitychange', onVis)
    return () => { es?.close(); document.removeEventListener('visibilitychange', onVis) }
  }, [bump]) // eslint-disable-line
  return (
    <ThemeCtx.Provider value={theme}>
      <RefreshCtx.Provider value={{ tick, bump }}>
        <BrowserRouter><Shell inbox={inbox} /></BrowserRouter>
      </RefreshCtx.Provider>
    </ThemeCtx.Provider>
  )
}
