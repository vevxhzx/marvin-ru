import { Component, useEffect, useState, createContext, useContext, useCallback, useRef } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Sun, Moon, Monitor, Sparkles, Wallet, CalendarDays, CheckSquare, Brain, Settings as SettingsIcon, Search, PanelLeftClose, PanelLeftOpen, Bell, History, MessageCircle, Briefcase, Square, Play, Users, Clapperboard, Languages, Grid3x3, HelpCircle } from 'lucide-react'
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
import { usePrefs, prefs as PREFS, pullRemote, CLIENT_ID, apply } from './lib/prefs'
import { api, relTime, kb, kbAlt } from './lib/api'
import { tg, tgBackButton } from './lib/tg'
import { Toaster, toast, Sheet } from './components/ui'
import { useI18n, t as T } from './lib/i18n'

/* Навигация по смыслу: рабочее пространство и система.
   label/title — ключи словаря (lib/i18n.js), подписи живут в t(). */
export const NAV_GROUPS = [
  { title: 'nav.g_work', items: [
    { to: '/', label: 'nav.today', icon: Sparkles, key: '1' },
    { to: '/tasks', label: 'nav.tasks', icon: CheckSquare, key: '2' },
    { to: '/calendar', label: 'nav.calendar', icon: CalendarDays, key: '3' },
    { to: '/finance', label: 'nav.finance', icon: Wallet, key: '4' },
    { to: '/orders', label: 'nav.orders', icon: Briefcase, key: '5' },
    { to: '/mind', label: 'nav.mind', icon: Brain, key: '6' },
    { to: '/board', label: 'nav.board', icon: Clapperboard, key: '0' },
    { to: '/people', label: 'nav.people', icon: Users, key: '9' },
  ] },
  { title: 'nav.g_sys', items: [
    { to: '/memory', label: 'nav.memory', icon: History, key: '7' },
    { to: '/settings', label: 'nav.settings', icon: SettingsIcon, key: '8' },
  ] },
]
const NAV = NAV_GROUPS.flatMap((g) => g.items)
/* Нижняя панель телефона: до 4 разделов из настроек + «Ещё» (все остальные разделы и действия).
   Ровно пять вкладок — как в обычном приложении, а не «сколько поместилось». */
const MOBILE_NAV = [NAV[0], NAV[1], NAV[3], NAV[5]]
const MOBILE_TABS_MAX = 5   // 4 раздела + «Ещё»

/* Реестр горячих клавиш — одна точка правды: сюда смотрит обработчик в Shell и
   справка по клавише «?». Новая комбинация = новая строка в этом массиве:
   test(e, mod) решает, сработала ли клавиша, id — что сделать, combo/label — что показать. */
export const HOTKEYS = [
  { id: 'palette', combo: [kb('K'), kb('/')], label: 'hot.palette',
    test: (e, mod) => mod && (e.key.toLowerCase() === 'k' || e.key === '/') },
  { id: 'chat', combo: [kb('J')], label: 'hot.chat',
    test: (e, mod) => mod && e.key.toLowerCase() === 'j' },
  { id: 'nav', combo: [kbAlt('0…9')], label: 'hot.nav',
    test: (e, mod) => e.altKey && !mod && /^[0-9]$/.test(e.key) },
  { id: 'help', combo: ['?'], label: 'hot.help',
    test: (e, mod) => !mod && !e.altKey && (e.key === '?' || (e.key === '/' && e.shiftKey)) },
]
export const hotkeyId = (e) => {
  const mod = e.metaKey || e.ctrlKey
  return HOTKEYS.find((h) => h.test(e, mod))?.id || null
}


// тема
const ThemeCtx = createContext(null)
export const useTheme = () => useContext(ThemeCtx)

function useThemeState() {
  const [mode, setModeState] = useState(() => localStorage.getItem('theme') || 'auto')
  const setMode = useCallback((m) => { setModeState(m); PREFS.set({ theme: m }) }, [])
  useEffect(() => { const h = (e) => setModeState(e.detail || 'auto'); window.addEventListener('prefs:theme', h); return () => window.removeEventListener('prefs:theme', h) }, [])
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const applyTheme = () => {
      const dark = mode === 'dark' || (mode === 'auto' && mq.matches)
      const de = document.documentElement
      de.classList.toggle('dark', dark)
      /* data-theme — второй, «явный» признак темы: на него смотрят :root[data-theme=…] правила в index.css */
      de.setAttribute('data-theme', dark ? 'dark' : 'light')
      apply() // пересчитать акцент/оттенок под новую тему
      const metas = document.querySelectorAll('meta[name="theme-color"]')
      metas.forEach((m, i) => {
        if (i > 0) { m.remove(); return }
        m.removeAttribute('media')
        m.setAttribute('content', dark ? '#050507' : '#ecece9')
      })
    }
    applyTheme()
    mq.addEventListener('change', applyTheme)
    localStorage.setItem('theme', mode)
    return () => mq.removeEventListener('change', applyTheme)
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
        <div className="label mb-2">{T('err.broken')}</div>
        <h1 className="text-[28px] font-semibold tracking-[-0.03em]">{T('err.something')}</h1>
        <p className="muted mt-2 text-[14px]">{T('err.hint')}</p>
        <pre className="fill mt-4 overflow-x-auto rounded-xl px-3 py-2 text-left text-[12px] leading-relaxed" style={{ whiteSpace: 'pre-wrap' }}>{msg}</pre>
        <div className="mt-5 flex justify-center gap-2">
          <button className="btn-ghost" onClick={() => this.setState({ err: null })}>{T('err.retry')}</button>
          <a className="btn-primary" href="/">{T('err.home')}</a>
        </div>
      </div>
    )
  }
}

function NotFound() {
  const nav = useNavigate()
  const { t } = useI18n()
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-center">
      <div className="label">{t('err.no_page')}</div>
      <div className="h1-sm">{window.location.pathname}</div>
      <button className="btn-soft btn-sm mt-2" onClick={() => nav('/')}>{t('err.home')}</button>
    </div>
  )
}

// глобальный refresh: после действий в чате обновляем страницы
const RefreshCtx = createContext({ tick: 0, bump: () => {} })
export const useRefresh = () => useContext(RefreshCtx)

/* Центр уведомлений: напоминания, действия из Telegram/голоса, автоплатежи. Хранится в браузере (последние 40) */
const INBOX_KEY = 'inbox.v1'
/* Подписи действий/каналов приходят ключами (см. SERVER в lib/i18n.js) */
const CH_WORDS = { tg: 'ch_tg', 'tg-voice': 'ch_tg_voice', voice: 'ch_voice', system: 'ch_system', web: 'ch_web' }
/* Действия ассистента → ключ подписи (см. SERVER в lib/i18n.js) */
const ACT_WORDS = {
  add_event: 'act_add_event', add_task: 'act_add_task', add_expense: 'act_add_expense', add_income: 'act_add_income',
  add_note: 'act_add_note', add_link: 'act_add_link', add_debt: 'act_add_debt', pay_debt: 'act_pay_debt',
  move_event: 'act_move_event', complete_task: 'act_complete_task', add_recurring: 'act_add_recurring',
  undo: 'common.undo', bulk_delete: 'act_bulk_delete', add_order: 'act_add_order', update_order: 'act_update_order',
  order_payment: 'act_order_payment', pomodoro: 'act_pomodoro', add_goal: 'act_add_goal', save_to_goal: 'act_save_to_goal',
}
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
  if (d.kind === 'reminder') return { title: d.text || T('inbox.reminder'), sub: T('inbox.reminder_sub'), tone: 'accent' }
  if (d.kind === 'recurring') return { title: d.text || T('inbox.recurring_done'), sub: T('ch_system'), tone: 'ok' }
  if (d.kind === 'payment_alert') return { title: d.text || T('inbox.payment_alert'), sub: T('inbox.finance_sub'), tone: 'accent' }
  if (d.kind === 'chat' && d.channel && d.channel !== 'web' && d.actions?.length) {
    const what = [...new Set(d.actions.map((a) => (ACT_WORDS[a] ? T(ACT_WORDS[a]) : '')).filter(Boolean))]
    if (what.length) return { title: what.join(', ').replace(/^./, (c) => c.toUpperCase()), sub: T('inbox.from', { ch: T(CH_WORDS[d.channel] || d.channel) }), tone: 'ok' }
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
  const { t } = useI18n()
  const { t: tmr, left, reload } = useTimer()
  const nav = useNavigate()
  if (!tmr?.active) return null
  const brk = tmr.kind === 'break'
  const label = tmr.order || (brk ? t('unit.break') : t('unit.focus'))
  return (
    <div className={`flex items-center gap-1.5 rounded-full py-1 pl-2.5 pr-1 text-[12.5px] md:hidden ${brk ? 'soft-pos' : 'soft-accent'} ${left === 0 ? 'animate-pulse' : ''}`}>
      <button className="flex items-center gap-1.5" onClick={() => nav('/orders')} data-tip={label}>
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'currentColor' }} />
        <span className="num font-medium tabular-nums">{mmss(left)}</span>
        {tmr.order && <span className="hidden max-w-[140px] truncate lg:inline">{tmr.order}</span>}
      </button>
      <button className="grid h-6 w-6 place-items-center rounded-full transition hover:bg-[var(--fill)]" aria-label={t('pomo.stop')} data-tip={t('pomo.stop_short')} onClick={() => api.stopTimer().then(reload).catch(() => {})}><Square size={10} /></button>
    </div>
  )
}

/* Мини-помодоро в сайдбаре: кольцо + время + заказ. Нет таймера — кнопка «▶ 25:00» (длина из настроек).
   Клик по времени — на страницу заказов, стоп — квадрат. В свёрнутой панели — только кольцо. */
function SideTimer({ min }) {
  const { t } = useI18n()
  const { t: tmr, left, reload } = useTimer()
  const nav = useNavigate()
  const [busy, setBusy] = useState(false)
  const active = !!tmr?.active
  const brk = tmr?.kind === 'break'
  const total = active ? tmr.planned_min * 60 : 1
  const pct = active ? Math.min(1, left / total) : 0
  const R = min ? 11 : 13, C = 2 * Math.PI * R, S = R * 2 + 6
  const color = brk ? 'var(--pos)' : 'var(--accent)'
  const label = active ? (tmr.order || (brk ? t('unit.break') : t('unit.focus'))) : t('unit.pomodoro')
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
      <button className="grid h-9 w-9 place-items-center rounded-xl transition hover:bg-[var(--fill)]"
        data-tip={active ? `${mmss(left)} · ${label} · ${t('pomo.tap_to_stop')}` : t('pomo.planned', { n: tmr?.focus_min || 25 })}
        data-tip-side="right"
        onClick={() => run(() => (active ? api.stopTimer() : api.startTimer(null, null)))}>{ring}</button>
    )
  }
  if (!active) {
    return (
      <button className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-[12.5px] transition hover:bg-[var(--fill)]" onClick={() => run(() => api.startTimer(null, null))} data-tip={t('pomo.start')}>
        {ring}
        <span className="num font-medium tabular-nums">{String(tmr?.focus_min || 25).padStart(2, '0')}:00</span>
        <span className="muted truncate">{tmr?.today_sessions ? t('pomo.today_n', { count: tmr.today_sessions }) : t('unit.pomodoro')}</span>
      </button>
    )
  }
  return (
    <div className={`flex items-center gap-2.5 rounded-xl py-2 pl-3 pr-1.5 text-[12.5px] ${brk ? 'soft-pos' : 'soft-accent'}`} style={{ animation: 'rise .25s var(--ease-out)' }}>
      <button className="flex min-w-0 flex-1 items-center gap-2.5" onClick={() => nav('/orders')} data-tip={label}>
        {ring}
        <span className="min-w-0 text-left leading-tight">
          <span className={`num block font-medium tabular-nums ${left === 0 ? 'animate-pulse' : ''}`}>{mmss(left)}</span>
          <span className="block truncate text-[11px] opacity-70">{label}</span>
        </span>
      </button>
      <button className="grid h-7 w-7 shrink-0 place-items-center rounded-lg transition hover:bg-[var(--fill)]" aria-label={t('pomo.stop')} data-tip={t('pomo.stop_short')} onClick={() => run(() => api.stopTimer())}><Square size={10} /></button>
    </div>
  )
}

/* Состояние ассистента для шапки/сайдбара: готов · думает · офлайн · только правила */
export function assistantState(live, busy) {
  if (busy) return { dot: 'var(--accent)', text: T('state.thinking'), pulse: true }
  if (live.core === 'wait') return { dot: 'var(--ink-3)', text: T('state.connecting') }
  if (live.core === 'down') return { dot: 'var(--neg)', text: T('state.core_offline') }
  const pc = live.pc
  if (pc?.alive && ['listening', 'thinking', 'speaking'].includes(pc.mode)) return { dot: 'var(--pos)', text: { listening: T('state.listening'), thinking: T('state.thinking'), speaking: T('state.speaking') }[pc.mode], pulse: true }
  if (live.brain) return { dot: 'var(--accent)', text: T('state.ready') }
  return { dot: 'var(--warn)', text: T('state.ready_no_model') }
}

function Sidebar({ live, busy, hiddenNav = [] }) {
  const { t } = useI18n()
  const st = assistantState(live, busy)
  const { t: tmr, left } = useTimer()
  const nav = useNavigate()
  const [pop, setPop] = useState(false)
  const pomoTime = tmr?.active ? mmss(left) : '90:00'
  const pomoLabel = tmr?.active ? (tmr.order || (tmr.kind === 'break' ? t('unit.break') : t('unit.focus'))) : t('unit.pomodoro')

  return (
    <aside>
      <div className="logo"><i></i>{lower()}</div>
      <nav>
        <div className="nav-group-title">{t('nav.g_plan')}</div>
        <NavLink to="/" end className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><circle cx="10" cy="10" r="2"/></svg>{t('nav.today')}
        </NavLink>
        <NavLink to="/tasks" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><rect x="3" y="3" width="14" height="14" rx="4"/><path d="m7 10 2 2 4-4"/></svg>{t('nav.tasks')}
        </NavLink>
        <NavLink to="/calendar" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><rect x="3" y="4" width="14" height="13" rx="3"/><path d="M3 8h14M7 2v3M13 2v3"/></svg>{t('nav.calendar')}
        </NavLink>
        <NavLink to="/board" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><rect x="3" y="4" width="14" height="12" rx="3"/><path d="M7 4v12M13 4v12"/></svg>{t('nav.board')}
        </NavLink>

        <div className="nav-group-title">{t('nav.g_money')}</div>
        <NavLink to="/finance" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><rect x="3" y="5" width="14" height="11" rx="3"/><path d="M13 10.5h1"/></svg>{t('nav.finance')}
        </NavLink>
        {!hiddenNav.includes('/orders') && (
          <NavLink to="/orders" className={({ isActive }) => isActive ? 'on' : ''}>
            <svg viewBox="0 0 20 20"><rect x="3" y="6" width="14" height="10" rx="3"/><path d="M7.5 6V4.5h5V6"/></svg>{t('nav.orders')}
          </NavLink>
        )}

        <div className="nav-group-title">{t('nav.g_people')}</div>
        <NavLink to="/people" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><circle cx="7.5" cy="7" r="2.5"/><circle cx="14" cy="8" r="2"/><path d="M3 16c0-3 2-4.5 4.5-4.5S12 13 12 16M13 12c2 0 4 1 4 4"/></svg>{t('nav.people')}
        </NavLink>

        <div className="nav-group-title">{t('nav.g_jarvis')}</div>
        <NavLink to="/mind" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><path d="M10 3.5a4 4 0 0 0-4 4 3 3 0 0 0-1 5 3.5 3.5 0 0 0 5 3.5zm0 0a4 4 0 0 1 4 4 3 3 0 0 1 1 5 3.5 3.5 0 0 1-5 3.5z"/></svg>{t('nav.mind')}
        </NavLink>
        <NavLink to="/memory" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="7"/><path d="M10 6v4l2.5 2.5"/></svg>{t('nav.memory')}
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => isActive ? 'on' : ''}>
          <svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="3"/><path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4"/></svg>{t('nav.settings')}
        </NavLink>
      </nav>
      <div className="sb">
        <div className="pomo select-none" onClick={() => nav('/orders')} style={{ cursor: 'pointer', outline: 'none' }}>
          <svg className="pomo-gauge" viewBox="0 0 24 24" style={{ outline: 'none', border: 'none', boxShadow: 'none' }}>
            <defs>
              <linearGradient id="pomoSideGrad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="var(--acc)" />
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
  const { t } = useI18n()
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
        <div className="text-[13px] font-medium">{t('inbox.title')}</div>
        {inbox.items.length > 0 && <button className="faint text-[12px] hover:text-accent" onClick={inbox.clear}>{t('inbox.clear')}</button>}
      </div>
      <div className="scroll-thin max-h-[calc(60vh/var(--ui-zoom))] overflow-y-auto">
        {inbox.items.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <div className="text-[14px] font-medium">{t('inbox.quiet')}</div>
            <div className="muted mt-1 text-[12.5px]">{t('inbox.quiet_hint', { name: lower() })}</div>
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

/* Переключатель языка RU/EN в шапке — компактный, как кнопка «цвет».
   Состояние общее с настройками (см. Settings.jsx): оба берут setLang() из lib/i18n. */
export function LangToggle({ className = '' }) {
  const { lang, setLang } = useI18n()
  const pick = (l) => { if (l !== lang) setLang(l) }
  return (
    <div className={`lang-toggle ${className}`} role="group" aria-label={T('lang.aria')}>
      {['ru', 'en'].map((l) => (
        <button
          key={l}
          type="button"
          className={l === lang ? 'on' : ''}
          aria-pressed={l === lang}
          lang={l}
          title={T(`lang.${l}_title`)}
          onClick={() => pick(l)}
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  )
}

function Shell({ inbox }) {
  const { t } = useI18n()
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
  // Горячие клавиши идут через реестр HOTKEYS (выше): обработчик только решает, что делать
  const [helpOpen, setHelpOpen] = useState(false)
  useEffect(() => {
    const h = (e) => {
      const id = hotkeyId(e)
      if (id === 'palette') { e.preventDefault(); setPalOpen((v) => !v) }
      else if (id === 'chat') { e.preventDefault(); setChatOpen((v) => !v) }
      else if (id === 'nav') { const it = NAV.find((n) => n.key === e.key); if (it) { e.preventDefault(); nav(it.to) } }
      else if (id === 'help') {
        // «?» внутри поля ввода — это текст, а не справка
        const t = e.target
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
        e.preventDefault(); setHelpOpen((v) => !v)
      }
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

  // Ярлык PWA (?quick=exp и т.п.): открываем чат с готовым началом фразы и чистим адрес.
  useEffect(() => {
    const usp = new URLSearchParams(window.location.search)
    const q = usp.get('quick')
    if (q == null) return
    // фразы уходят в ядро — они на русском в любом режиме интерфейса   // i18n-raw
    const MAP = { exp: 'потратил ', inc: 'получил ', task: 'задача: ', note: 'мысль: ', event: 'встреча: ', money: 'баланс' } // i18n-raw
    setChatSeed({ text: MAP[q] ?? '', n: Date.now(), send: false })
    setChatOpen(true)
    usp.delete('quick')
    const qs = usp.toString()
    window.history.replaceState({}, '', window.location.pathname + (qs ? `?${qs}` : ''))
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
  const [address, setAddress] = useState('')
  useEffect(() => {
    const load = () => api.settings().then((d) => { const it = d.items?.find((x) => x.key === 'owner.name'); setAddress(it?.value ? String(it.value).toLowerCase() : t('common.sir')) }).catch(() => {})
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
  const [moreOpen, setMoreOpen] = useState(false)
  // нижние вкладки: до 4 разделов из настроек + «Ещё» с остальными
  const mobileNav = (prefs.tabbar || []).filter((to) => freelance || to !== '/orders')
    .map((to) => NAV.find((n) => n.to === to)).filter(Boolean)
    .slice(0, MOBILE_TABS_MAX - 1)
  const tabs = mobileNav.length ? mobileNav : MOBILE_NAV.filter((n) => freelance || n.to !== '/orders')
  // «Ещё»: всё, чего нет в нижних вкладках, плюс действия, которые на телефоне спрятаны в меню
  const moreNav = NAV.filter((n) => !tabs.some((t) => t.to === n.to) && (freelance || n.to !== '/orders'))

  if (denied) return <Gate denied={denied} />

  return (
    <>
      <div className="aur"><i></i><i></i><i></i></div>
      <div className="app">
        <Sidebar live={live} busy={busy} hiddenNav={hiddenNav} />

        <main>
          <div className="gt r">
            <TopTimer />
            <div className="search" onClick={() => setPalOpen(true)} style={{ cursor: 'pointer' }} role="button" tabIndex={0}
              aria-label={t('common.search')} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPalOpen(true) } }}>
              <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><circle cx="9" cy="9" r="6"/><path d="m14 14 3.5 3.5"/></svg>
              {t('common.search')}<span className="kbd mono">{kb('K')}</span>
            </div>
            <LangToggle />
            <div className="ib" onClick={() => setInboxOpen((v) => !v)} style={{ cursor: 'pointer' }} role="button" tabIndex={0}
              aria-label={t('inbox.title')} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setInboxOpen((v) => !v) } }}>
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 14V9a5 5 0 0 1 10 0v5l1.5 1.5h-13zM8.5 18h3"/></svg>
              {inbox.unread > 0 && <u></u>}
            </div>
            <div className="av" onClick={() => setChatOpen(true)} style={{ cursor: 'pointer' }} role="button" tabIndex={0}
              aria-label={t('chat.title')} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setChatOpen(true) } }}>
              {address ? address.slice(0, 1).toLowerCase() : t('common.you_initial')}
            </div>
          </div>

          <div className="relative">
            {inboxOpen && <InboxPanel inbox={inbox} onClose={() => setInboxOpen(false)} />}
          </div>

          {health && !health.ok && (
            <div className="mb-6 animate-rise">
              <div className="soft-neg flex flex-wrap items-center justify-between gap-2 rounded-2xl px-4 py-2.5 text-[13px]">
                <span>{t('shell.core_down')}</span>
                <button className="btn-ghost btn-sm" onClick={() => api.health().then(setHealth).catch(() => {})}>{t('common.retry')}</button>
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

        {/* Нижняя навигация телефона: 4 раздела + «Ещё». На десктопе её нет — там боковая панель. */}
        <nav className={`tabbar ${prefs.compactNav ? 'compact' : ''}`} aria-label={t('nav.mobile_menu')}>
          <div>
            {tabs.map(({ to, label, icon: I }) => (
              <NavLink key={to} to={to} end={to === '/'}>
                <I size={21} strokeWidth={2} aria-hidden="true" />
                <span>{t(label)}</span>
              </NavLink>
            ))}
            <button type="button" className={`tab-more ${moreOpen ? 'on' : ''}`} onClick={() => setMoreOpen(true)}
              aria-label={t('nav.more')} aria-haspopup="dialog" aria-expanded={moreOpen}>
              <Grid3x3 size={21} strokeWidth={2} aria-hidden="true" />
              <span>{t('nav.more')}</span>
            </button>
          </div>
        </nav>

        {/* «Ещё»: остальные разделы + то, что на телефоне спрятано в меню (тема, справка, чат) */}
        <Sheet open={moreOpen} onClose={() => setMoreOpen(false)} title={t('nav.more_title')} sub={t('nav.more_sub')}>
          <div className="space-y-2">
            {moreNav.map(({ to, label, icon: I }) => (
              <NavLink key={to} to={to} className="more-row" onClick={() => setMoreOpen(false)}>
                <span className="more-ic"><I size={17} strokeWidth={1.8} aria-hidden="true" /></span>
                {t(label)}
              </NavLink>
            ))}
            <div className="rule !my-3" />
            <button type="button" className="more-row" onClick={() => { setMoreOpen(false); setChatOpen(true) }}>
              <span className="more-ic"><MessageCircle size={17} strokeWidth={1.8} aria-hidden="true" /></span>
              {t('more.chat')}
            </button>
            <button type="button" className="more-row" onClick={() => { setMoreOpen(false); cycle() }}>
              <span className="more-ic">{mode === 'light' ? <Sun size={17} /> : mode === 'dark' ? <Moon size={17} /> : <Monitor size={17} />}</span>
              {t('st.theme')}
            </button>
            <button type="button" className="more-row" onClick={() => { setMoreOpen(false); setHelpOpen(true) }}>
              <span className="more-ic"><HelpCircle size={17} strokeWidth={1.8} aria-hidden="true" /></span>
              {t('more.keys')}
            </button>
          </div>
        </Sheet>

        <Chat open={chatOpen} onClose={() => setChatOpen(false)} seed={chatSeed} />
        <Palette open={palOpen} onClose={() => setPalOpen(false)} openChat={() => setChatOpen(true)} setTheme={setMode} />
        {/* Справка по горячим клавишам — список собирается из того же реестра HOTKEYS */}
        <Sheet open={helpOpen} onClose={() => setHelpOpen(false)} title={t('hot.title')} sub={t('hot.sub')}>
          <div className="space-y-1.5">
            {HOTKEYS.map((hk) => (
              <div key={hk.id} className="flex items-center justify-between gap-4 rounded-xl px-3.5 py-3" style={{ background: 'var(--surface-2)' }}>
                <span className="text-[13.5px]">{t(hk.label)}</span>
                <span className="flex shrink-0 gap-1.5">
                  {hk.combo.map((c) => <span key={c} className="kbd mono">{c}</span>)}
                </span>
              </div>
            ))}
          </div>
          <div className="faint mt-4 text-[12.5px]">{t('hot.footer')}</div>
        </Sheet>
        <Toaster />
      </div>
    </>
  )
}

function Gate({ denied }) {
  const { t } = useI18n()
  const tgMode = denied.tg
  const title = tgMode ? (denied.tgError ? t('gate.tg_failed') : t('gate.session_expired')) : t('gate.no_access')
  // webview Telegram, но без данных для входа: сайт открыт как обычная ссылка, а не кнопкой бота
  const tgLink = !tgMode && /Telegram|TelegramBot|tgWebApp/i.test(navigator.userAgent + location.hash) || (!tgMode && !!window.Telegram)
  const text = tgMode
    ? (denied.tgError ? `${denied.tgError}.` : t('gate.tg_reopen'))
    : tgLink
      ? t('gate.tg_link')
      : t('gate.only_owner')
  return (
    <div className="safe-t flex min-h-[100dvh] items-center justify-center px-6">
      <div className="animate-rise w-full max-w-sm text-center">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl" style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: 'var(--ink-3)' }} />
        </div>
        <div className="h3">{title}</div>
        <p className="muted mt-2 text-[14px] leading-relaxed">{text}</p>
        {tgMode ? (
          <button className="btn-primary mt-6" onClick={() => { try { tg.app?.close() } catch {} location.reload() }}>{t('gate.close_reopen')}</button>
        ) : (
          <button className="btn-ghost mt-6" onClick={() => location.reload()}>{t('common.retry')}</button>
        )}
        <div className="faint mt-8 text-[12px]">{t('gate.privacy')}</div>
      </div>
    </div>
  )
}

export default function App() {
  const theme = useThemeState()
  const [tick, setTick] = useState(0)
  const bump = useCallback(() => setTick((t) => t + 1), [])
  const inbox = useInbox()
  /* Установленное приложение (PWA) и обычная вкладка — разные безопасные зоны:
     помечаем <html>, чтобы CSS (safe-area, отступы) знал, где рисуем. */
  useEffect(() => {
    const de = document.documentElement
    const mark = () => {
      const standalone = window.matchMedia?.('(display-mode: standalone)')?.matches
        || window.matchMedia?.('(display-mode: window-controls-overlay)')?.matches
        || window.navigator.standalone === true
      de.dataset.pwa = standalone ? 'standalone' : 'browser'
    }
    mark()
    const mq = window.matchMedia?.('(display-mode: standalone)')
    mq?.addEventListener?.('change', mark)
    return () => mq?.removeEventListener?.('change', mark)
  }, [])
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
