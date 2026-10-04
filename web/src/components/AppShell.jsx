/* components/AppShell.jsx — оболочка приложения.

   Сайдбар (десктоп) · липкая шапка с компактным заголовком · содержимое раздела ·
   плавающий док (телефон) · окна приложения (чат, палитра, «Ещё», справка).

   Логика (роуты, SSE, горячие клавиши, тема, тосты) живёт в App.jsx — здесь только
   раскладка и движение. Всё, что анимируется, идёт через lib/motion.js: переход между
   разделами, сворачивающийся заголовок, шторки, потянуть-обновить.
*/

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { NavLink, useNavigate } from 'react-router-dom'
import { Sun, Moon, Monitor, Square, Play, Search, MoreHorizontal, MessageCircle, HelpCircle, Download } from 'lucide-react'
import Chat from './Chat'
import Palette from './Palette'
import { LivePopover } from './Live'
import { useTimer, mmss } from '../pages/Orders'
import { lower } from '../lib/name'
import { api, relTime, kb } from '../lib/api'
import { useI18n, t as T } from '../lib/i18n'
import { crossfadeIn, crossfadeOut, viewTransition, motionOff, usePhone } from '../lib/motion'
import { usePullToRefresh } from '../lib/gestures'
import { headOf, textOf } from '../lib/nav'
import { Toaster, toast } from './ui'
import { canInstall, installPwa } from '../lib/sw'
import Dock from './Dock'
import SheetHost from './SheetHost'
import TitleHeader from './TitleHeader'
import CaptureSheet from './CaptureSheet'

/* Контекстное действие кнопки «+» дока: на разделе — своё добавление, иначе — шторка
   быстрого ввода. Разделы слушают событие и открывают свою форму. */
const ADD_EVENT = {
  '/tasks': 'tasks:add',
  '/calendar': 'calendar:add',
  '/finance': 'finance:add',
  '/orders': 'orders:add',
  '/mind': 'mind:add',
  '/people': 'people:add',
  '/memory': 'memory:add',
  '/board': 'board:add',
}

/* ---------- состояние ассистента для шапки и сайдбара ---------- */
export function assistantState(live, busy) {
  if (busy) return { dot: 'var(--accent)', text: T('state.thinking'), pulse: true }
  if (live.core === 'wait') return { dot: 'var(--ink-3)', text: T('state.connecting') }
  if (live.core === 'down') return { dot: 'var(--neg)', text: T('state.core_offline') }
  const pc = live.pc
  if (pc?.alive && ['listening', 'thinking', 'speaking'].includes(pc.mode)) return { dot: 'var(--pos)', text: { listening: T('state.listening'), thinking: T('state.thinking'), speaking: T('state.speaking') }[pc.mode], pulse: true }
  if (live.brain) return { dot: 'var(--accent)', text: T('state.ready') }
  return { dot: 'var(--warn)', text: T('state.ready_no_model') }
}

export function Logo({ size = 22 }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-lg" style={{ width: size + 6, height: size + 6, background: 'var(--ink)', color: 'var(--bg)' }}>
      <svg width={size - 6} height={size - 6} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="butt"><path d="M12 3v18M3 12h18M6 6l12 12M18 6L6 18" /></svg>
    </span>
  )
}

/* ---------- переключатель языка RU/EN ---------- */
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

/* ---------- идущий помодоро в шапке ---------- */
export function TopTimer() {
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

/* ---------- мини-помодоро в сайдбаре ---------- */
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

/* ---------- сайдбар (десктоп; на телефоне его прячет CSS) ----------
   Колонка тёмная в обеих темах (палитра макета-основы в index.css, --sb-*), поэтому
   бренд, подписи разделов, статус и помодоро берут светлые чернила из --sb-ink/--sb-dim.
   Ниже две кликабельные строки (помодоро и статус) — это по сути кнопки, поэтому у них
   есть роль и работа с клавиатуры: обводка фокуса идёт от общих правил index.css. */
function Sidebar({ live, busy, hiddenNav = [] }) {
  /* Помодоро в сайдбаре: по клику открывается окошко управления прямо над пунктом. */
  const [pomoOpen, setPomoOpen] = useState(false)
  const [pomoT, setPomoT] = useState(null)
  const [, setPomoTick] = useState(0)
  const pomoLeft = pomoT?.active ? Math.max(0, Math.round((new Date(pomoT.ends_at) - Date.now()) / 1000)) : 0
  const pomoTotal = (pomoT?.minutes || 25) * 60
  const navOrders = useNavigate()
  const pomoReload = useCallback(() => { api.timer().then(setPomoT).catch(() => {}) }, [])
  useEffect(() => {
    pomoReload()
    const iv = setInterval(() => { setPomoTick((n) => n + 1); pomoReload() }, 20000)
    return () => clearInterval(iv)
  }, [pomoReload])
  const { t } = useI18n()
  const st = assistantState(live, busy)
  const { t: tmr, left } = useTimer()
  const nav = useNavigate()
  const [pop, setPop] = useState(false)
  const pomoTime = tmr?.active ? mmss(left) : '90:00'
  const pomoLabel = tmr?.active ? (tmr.order || (tmr.kind === 'break' ? t('unit.break') : t('unit.focus'))) : t('unit.pomodoro')
  /* Enter/пробел — как обычный клик по строке */
  const onEnter = (fn) => (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn() } }

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
        <span className="pomo-slot block">
            <button
              type="button"
              className={`pomo nav-row${pomoOpen ? ' is-open' : ''}`}
              aria-expanded={pomoOpen}
              aria-haspopup="dialog"
              aria-label={t('side.pomodoro')}
              onClick={() => setPomoOpen((v) => !v)}
              onKeyDown={(e) => { if (e.key === 'Escape') setPomoOpen(false) }}
            >
              <span className="pomo-gauge" aria-hidden><span style={{ transform: `rotate(${(pomoT?.active ? pomoLeft / (pomoTotal || 1) : 0) * 360}deg)` }} /></span>
              <span className="pomo-t num">{pomoT?.active ? mmss(pomoLeft) : t('side.pomodoro')}</span>
            </button>
            {pomoOpen && (
              <PomodoroPanel
                timer={pomoT}
                left={pomoLeft}
                onClose={() => setPomoOpen(false)}
                onChanged={pomoReload}
              />
            )}
            </span>
        <div className="relative">
          <div className="st" role="button" tabIndex={0} aria-expanded={pop}
            onClick={() => setPop((v) => !v)} onKeyDown={onEnter(() => setPop((v) => !v))}
            style={{ cursor: 'pointer' }} title={st.text}>
            <i className="dot" style={{ background: st.dot }}></i>
            {st.text}
          </div>
          {pop && <LivePopover live={live} onClose={() => setPop(false)} place="absolute bottom-[calc(100%+8px)] left-0" />}
        </div>
      </div>
    </aside>
  )
}

/* ---------- центр уведомлений: выпадающий список под шапкой ---------- */
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

/* ---------- переход между разделами ----------
   View Transitions API, если браузер умеет: тогда React-обновление идёт через flushSync
   внутри вызова, а морфит заголовок (viewName ниже). Не умеет — наш crossfade:
   уход 130 мс → смена раздела → появление 280 мс. Оба варианта трогают только
   transform и opacity. */
export function PageTransition({ children, pathKey }) {
  const latest = useRef({ key: pathKey, node: children })
  latest.current = { key: pathKey, node: children }
  const [shown, setShown] = useState(() => ({ key: pathKey, node: children }))
  const hostRef = useRef(null)
  const first = useRef(true)
  const vtUsed = useRef(false)

  /* ref-колбэк ставит имя для View Transitions сразу на коммите — тогда и старый,
     и новый заголовок попадают в снимок и «морфятся» между разделами */
  const attach = useCallback((el) => {
    hostRef.current = el
    const h = el?.querySelector?.('h1')
    if (h) { try { h.style.viewTransitionName = 'page-title' } catch {} }
  }, [])

  /* уход старого раздела и смена (эффект зависит только от маршрута: ререндеры
     содержимого не должны перезапускать анимацию) */
  useEffect(() => {
    if (pathKey === shown.key) return
    let alive = true
    const swap = () => { if (alive) setShown(latest.current) }
    /* View Transitions срабатывают синхронно внутри вызова, поэтому флаг ставим заранее */
    vtUsed.current = !motionOff() && typeof document.startViewTransition === 'function'
    const vt = viewTransition(() => flushSync(swap))
    if (!vt.used) {
      vtUsed.current = false
      const h = crossfadeOut(hostRef.current, { shift: -6, duration: 130 }, swap)
      return () => { alive = false; h.cancel?.() }
    }
    return () => { alive = false }
  }, [pathKey]) // eslint-disable-line

  /* появление нового раздела */
  useEffect(() => {
    if (first.current) { first.current = false; return }
    if (shown.key !== pathKey) return
    if (vtUsed.current) { vtUsed.current = false; return }   // анимацией занимается браузер
    crossfadeIn(hostRef.current, { shift: 10, duration: 280 })
  }, [shown.key, pathKey])

  const node = latest.current.key === shown.key ? latest.current.node : shown.node
  return (
    <div ref={attach} key={shown.key} className="page-enter" data-page-root="">
      {node}
    </div>
  )
}

/* ---------- оболочка ---------- */
/* ---------- помодоро: окошко управления над пунктом сайдбара ---------- */

function PomodoroPanel({ timer, left, onClose, onChanged }) {
  const { t } = useI18n()
  const [mins, setMins] = useState(25)
  const [busy, setBusy] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    api.pomodoro().then((p) => { if (p?.focus_min) setMins(p.focus_min) }).catch(() => {})
  }, [])

  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
    window.addEventListener('pointerdown', away, true)
    return () => { window.removeEventListener('keydown', h); window.removeEventListener('pointerdown', away, true) }
  }, [onClose])

  const call = (fn) => {
    setBusy(true)
    Promise.resolve(fn())
      .then(onChanged)
      .catch(() => {})
      .finally(() => setBusy(false))
  }

  const start = () => call(() => api.req('POST', '/api/orders/timer', { minutes: mins, kind: 'focus' }))
  const stop = () => call(() => api.req('DELETE', '/api/orders/timer'))
  const saveMins = (n) => {
    const v = Math.max(5, Math.min(120, n))
    setMins(v)
    call(() => api.savePomodoro({ focus_min: v }))
  }

  return (
    <div ref={ref} className="pomo-pop" role="dialog" aria-label={t('side.pomodoro')}>
      <div className="pomo-pop-row">
        <span className="num pomo-pop-time">{timer?.active ? mmss(left) : '—:—'}</span>
        <span className="faint pomo-pop-hint">
          {timer?.active ? (timer.kind === 'break' ? t('pomo.break') : t('pomo.focus')) : t('pomo.stopped')}
        </span>
      </div>
      <div className="pomo-pop-row">
        <button type="button" className="btn-icon" aria-label={t('common.decrease')} disabled={busy} onClick={() => saveMins(mins - 5)}>−</button>
        <span className="num pomo-pop-mins">{mins} {t('pomo.min')}</span>
        <button type="button" className="btn-icon" aria-label={t('common.increase')} disabled={busy} onClick={() => saveMins(mins + 5)}>+</button>
      </div>
      <div className="pomo-pop-actions">
        {timer?.active
          ? <button type="button" className="btn flex-1" disabled={busy} onClick={stop}>{t('pomo.pause')}</button>
          : <button type="button" className="btn-primary flex-1" disabled={busy} onClick={start}>{t('pomo.start')}</button>}
        <button type="button" className="btn-ghost" disabled={busy || !timer?.active} onClick={() => call(() => api.req('DELETE', '/api/orders/timer'))}>{t('pomo.reset')}</button>
      </div>
      <button type="button" className="pomo-pop-link" onClick={() => { onClose(); navOrders && navOrders() }}>
        {t('pomo.to_orders')}
      </button>
    </div>
  )
}

/* ---------- «все разделы»: шторка меню телефона (кнопка «…» в шапке) ----------
   Заказы, мозг, доска, люди, память, настройки — всё, чего нет в доке; ниже
   разделитель и действия: чат, язык, тема, справка, установка приложения. */
function useInstallable() {
  const [yes, setYes] = useState(() => (typeof canInstall === 'function' ? canInstall() : false))
  useEffect(() => {
    const on = () => setYes(!!canInstall())
    window.addEventListener('pwa:installable', on)
    on()
    return () => window.removeEventListener('pwa:installable', on)
  }, [])
  return yes
}

function SectionsSheet({ open, onClose, more, onSearch, onChat, onTheme, onHelp, mode, langNode }) {
  const { t } = useI18n()
  const installable = useInstallable()
  const doInstall = async () => {
    const ok = await installPwa()
    if (ok) { onClose?.(); toast(t('common.done')) }
    else toast(t('st.install_failed'), { kind: 'err', sub: t('st.install_manual') })
  }
  return (
    <SheetHost open={open} onClose={onClose} title={t('nav.more_title')} sub={t('nav.more_sub')} initialSnap={2}>
      <div className="space-y-2">
        <button type="button" className="more-row" onClick={() => { onClose?.(); onSearch?.() }}>
          <span className="more-ic"><Search size={17} strokeWidth={1.8} aria-hidden="true" /></span>
          {t('common.search')}
        </button>
        {(more || []).map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className="more-row" onClick={onClose}>
            <span className="more-ic"><Icon size={17} strokeWidth={1.8} aria-hidden="true" /></span>
            {t(label)}
          </NavLink>
        ))}
        <div className="rule !my-3" />
        <button type="button" className="more-row" onClick={() => { onClose?.(); onChat?.() }}>
          <span className="more-ic"><MessageCircle size={17} strokeWidth={1.8} aria-hidden="true" /></span>
          {t('more.chat')}
        </button>
        {langNode && (
          <div className="more-row !cursor-default items-center justify-between" style={{ background: 'transparent' }}>
            <span className="flex items-center gap-3">
              <span className="more-ic"><MoreHorizontal size={17} strokeWidth={1.8} aria-hidden="true" style={{ visibility: 'hidden' }} /></span>
              <span>{T('lang.aria')}</span>
            </span>
            {langNode}
          </div>
        )}
        <button type="button" className="more-row" onClick={() => { onClose?.(); onTheme?.() }}>
          <span className="more-ic">
            {mode === 'light' ? <Sun size={17} /> : mode === 'dark' ? <Moon size={17} /> : <Monitor size={17} />}
          </span>
          {t('st.theme')}
        </button>
        <button type="button" className="more-row" onClick={() => { onClose?.(); onHelp?.() }}>
          <span className="more-ic"><HelpCircle size={17} strokeWidth={1.8} aria-hidden="true" /></span>
          {t('more.keys')}
        </button>
        {installable && (
          <button type="button" className="more-row" onClick={() => { doInstall() }}>
            <span className="more-ic"><Download size={17} strokeWidth={1.8} aria-hidden="true" /></span>
            {t('st.install')}
          </button>
        )}
      </div>
    </SheetHost>
  )
}

export default function AppShell({
  live, busy, health, inbox, inboxOpen, onInbox, pathKey, address, onSearch,
  chatOpen, chatSeed, onChat, onChatClose, palOpen, onPalClose, onPalChat, setTheme,
  mode, onTheme, helpOpen, onHelp, onHelpClose, hotkeys, tabs, more, compact,
  hiddenNav, onRefresh, children,
}) {
  const { t, fmtDate, fmtWeekday } = useI18n()
  const phone = usePhone()
  const head = headOf(pathKey)
  const contentRef = useRef(null)
  const headRef = useRef(null)
  const [headH, setHeadH] = useState(0)
  const [moreOpen, setMoreOpen] = useState(false)
  const [captureOpen, setCaptureOpen] = useState(false)
  const [gtSolid, setGtSolid] = useState(false)

  /* «+» дока: на разделе — своё добавление (событие), иначе — шторка быстрого ввода */
  const handleAdd = useCallback((path) => {
    const ev = ADD_EVENT[path]
    if (ev) window.dispatchEvent(new CustomEvent(ev))
    else setCaptureOpen(true)
  }, [])

  /* Размытая подложка шапки — только когда страница ушла под неё: у самой строки
     фона нет (макет), а при скролле текст под шапкой не должен просвечивать. */
  useEffect(() => {
    const on = () => setGtSolid(window.scrollY > 8)
    on()
    window.addEventListener('scroll', on, { passive: true })
    return () => window.removeEventListener('scroll', on)
  }, [])

  /* Строка-статус телефона: слева дата («суббота · 3 октября»), справа иконки —
     как в свежем макете владельца. Дата живёт здесь, а не в шапке страницы. */
  const dateLine = (() => {
    const now = new Date()
    return `${fmtWeekday(now, 'long')} · ${fmtDate(now, { day: 'numeric', month: 'long' })}`
  })()

  /* высота липкой шапки: индикатор «потянуть-обновить» встаёт ровно под ней */
  useLayoutEffect(() => {
    const el = headRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => setHeadH(el.getBoundingClientRect().height))
    ro.observe(el)
    setHeadH(el.getBoundingClientRect().height)
    return () => ro.disconnect()
  }, [])

  const ptr = usePullToRefresh({ onRefresh })

  return (
    <>
      <div className="aur"><i></i><i></i><i></i></div>
      <div className="app">
        <Sidebar live={live} busy={busy} hiddenNav={hiddenNav} />

        <main>
          <div className={`gt r ${gtSolid ? 'gt-solid' : ''}`} ref={headRef}>
            <TopTimer />
            {phone ? (
              /* на телефоне поиск — строка в шторке «все разделы»: в шапке по макету
                 только круглые кнопки, иначе они теснят дату и сжимаются в эллипсы */
              null
            ) : (
              <div className="search" onClick={onSearch} style={{ cursor: 'pointer' }} role="button" tabIndex={0}
                aria-label={t('common.search')} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSearch() } }}>
                <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><circle cx="9" cy="9" r="6"/><path d="m14 14 3.5 3.5"/></svg>
                {t('common.search')}<span className="kbd mono">{kb('K')}</span>
              </div>
            )}
            <div className="ib" onClick={onInbox} style={{ cursor: 'pointer' }} role="button" tabIndex={0}
              aria-label={t('inbox.title')} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onInbox() } }}>
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 14V9a5 5 0 0 1 10 0v5l1.5 1.5h-13zM8.5 18h3"/></svg>
              {inbox.unread > 0 && <u></u>}
            </div>
            {/* Чат — иконкой, а не кругом-профилем с инициалом: профилей у владельца нет */}
            <button type="button" className="ib" onClick={onChat}
              aria-label={t('chat.title')} title={t('chat.title')}>
              <MessageCircle size={18} aria-hidden="true" />
            </button>
          </div>

          <div className="relative">
            {inboxOpen && <InboxPanel inbox={inbox} onClose={onInbox} />}
          </div>

          {health && !health.ok && (
            <div className="mb-6 animate-rise">
              <div className="soft-neg flex flex-wrap items-center justify-between gap-2 rounded-2xl px-4 py-2.5 text-[13px]">
                <span>{t('shell.core_down')}</span>
                <button className="btn-ghost btn-sm" onClick={() => api.health().then(() => onRefresh?.()).catch(() => {})}>{t('common.retry')}</button>
              </div>
            </div>
          )}

          {/* потянуть-обновить: индикатор под липкой шапкой, только transform + opacity */}
          <div className="relative" {...ptr.bind} ref={contentRef}>
            <div
              className="flex items-center justify-center gap-2 text-[12px] text-accent"
              style={{ ...ptr.style, position: 'absolute', top: -(headH + 10), left: 0, right: 0 }}
              aria-hidden="true"
            >
              <span className="grid h-5 w-5 place-items-center" style={ptr.ring}>
                <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                  <path d="M16 10a6 6 0 1 1-2.2-4.6M16 4v3h-3" />
                </svg>
              </span>
              {textOf(t, ptr.busy ? 'ptr.loading' : 'ptr.hint')}
            </div>
            <PageTransition pathKey={pathKey}>{children}</PageTransition>
          </div>
        </main>

        <Dock tabs={tabs} pathname={pathKey} compact={compact} onMore={() => setMoreOpen(true)} onAdd={handleAdd} />

        <SheetHost open={captureOpen} onClose={() => setCaptureOpen(false)} title={t('cap.title')} sub={t('cap.sub')}>
          <CaptureSheet open={captureOpen} onClose={() => setCaptureOpen(false)} />
        </SheetHost>

        <SectionsSheet
          open={moreOpen}
          onClose={() => setMoreOpen(false)}
          more={more}
          onSearch={onSearch}
          onChat={onChat}
          onTheme={onTheme}
          onHelp={onHelp}
          mode={mode}
          langNode={phone ? <LangToggle /> : null}
        />

        <Chat open={chatOpen} onClose={onChatClose} seed={chatSeed} />
        <Palette open={palOpen} onClose={onPalClose} openChat={onPalChat} setTheme={setTheme} />

        {/* Справка по горячим клавишам — список собирается из того же реестра HOTKEYS */}
        <SheetHost open={helpOpen} onClose={onHelpClose} title={t('hot.title')} sub={t('hot.sub')}>
          <div className="space-y-1.5">
            {(hotkeys || []).map((hk) => (
              <div key={hk.id} className="flex items-center justify-between gap-4 rounded-xl px-3.5 py-3" style={{ background: 'var(--surface-2)' }}>
                <span className="text-[13.5px]">{t(hk.label)}</span>
                <span className="flex shrink-0 gap-1.5">
                  {hk.combo.map((c) => <span key={c} className="kbd mono">{c}</span>)}
                </span>
              </div>
            ))}
          </div>
          <div className="faint mt-4 text-[12.5px]">{t('hot.footer')}</div>
        </SheetHost>
        <Toaster />
      </div>
    </>
  )
}