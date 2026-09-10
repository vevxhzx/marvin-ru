import { useEffect, useState, createContext, useContext, useCallback, useRef } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Sun, Moon, Monitor, Sparkles, Wallet, CalendarDays, CheckSquare, Brain, Settings as SettingsIcon, Search, PanelLeftClose, PanelLeftOpen, Bell, History, MessageCircle } from 'lucide-react'
import Settings from './pages/Settings'
import { notifyFromEvent } from './lib/notify'
import Today from './pages/Today'
import Finance from './pages/Finance'
import Calendar from './pages/Calendar'
import Tasks from './pages/Tasks'
import Mind from './pages/Mind'
import Memory from './pages/Memory'
import Chat from './components/Chat'
import Palette from './components/Palette'
import { useLive, LiveDot, LivePopover, MicButton } from './components/Live'
import { setName, lower } from './lib/name'
import { usePrefs } from './lib/prefs'
import { api, relTime, kb, kbAlt } from './lib/api'
import { Toaster, toast } from './components/ui'

/* Навигация по смыслу: рабочее пространство и система */
export const NAV_GROUPS = [
  { title: 'рабочее', items: [
    { to: '/', label: 'сегодня', icon: Sparkles, key: '1' },
    { to: '/tasks', label: 'задачи', icon: CheckSquare, key: '2' },
    { to: '/calendar', label: 'календарь', icon: CalendarDays, key: '3' },
    { to: '/finance', label: 'финансы', icon: Wallet, key: '4' },
    { to: '/mind', label: 'мозг', icon: Brain, key: '5' },
  ] },
  { title: 'система', items: [
    { to: '/memory', label: 'память', icon: History, key: '6' },
    { to: '/settings', label: 'настройки', icon: SettingsIcon, key: '7' },
  ] },
]
const NAV = NAV_GROUPS.flatMap((g) => g.items)
const MOBILE_NAV = [NAV[0], NAV[1], NAV[2], NAV[3], NAV[4]]

// тема
const ThemeCtx = createContext(null)
export const useTheme = () => useContext(ThemeCtx)

function useThemeState() {
  const [mode, setMode] = useState(() => localStorage.getItem('theme') || 'auto')
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

// глобальный refresh: после действий в чате обновляем страницы
const RefreshCtx = createContext({ tick: 0, bump: () => {} })
export const useRefresh = () => useContext(RefreshCtx)

/* Центр уведомлений: напоминания, действия из Telegram/голоса, автоплатежи. Хранится в браузере (последние 40) */
const INBOX_KEY = 'inbox.v1'
const ACT_WORDS = { add_event: 'событие в календаре', add_task: 'задача', add_expense: 'трата', add_income: 'доход', add_note: 'мысль', add_link: 'ссылка', add_debt: 'долг', pay_debt: 'платёж по долгу', move_event: 'событие перенесено', complete_task: 'задача закрыта', add_recurring: 'регулярный платёж', undo: 'отмена', bulk_delete: 'удаление' }
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

function Sidebar({ min, setMin, live, busy, mode, cycle, ThemeIcon, hiddenNav = [] }) {
  const st = assistantState(live, busy)
  return (
    <aside className={`sidebar sticky top-0 hidden h-screen shrink-0 flex-col border-r hair px-3 py-4 md:flex ${min ? 'min' : ''}`}>
      <NavLink to="/" className={`mb-5 flex items-center gap-2.5 px-2 ${min ? 'justify-center px-0' : ''}`}>
        <Logo />
        {!min && <span className="text-[15px] font-semibold tracking-[-0.03em]">{lower()}</span>}
      </NavLink>
      <nav className="flex-1 space-y-5">
        {NAV_GROUPS.map((g) => (
          <div key={g.title}>
            <div className="nav-group label mb-1.5 px-3 !text-[10px]">{g.title}</div>
            <div className="space-y-0.5">
              {g.items.filter(({ to }) => !hiddenNav.includes(to)).map(({ to, label, icon: I, key }) => (
                <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`} data-tip={min ? label : undefined} data-tip-side="right">
                  <I size={17} strokeWidth={1.9} className="shrink-0" />
                  <span className="nav-label">{label}</span>
                  <span className="nav-kbd kbd">{kbAlt(key)}</span>
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className={`mt-4 space-y-2 ${min ? 'flex flex-col items-center' : ''}`}>
        <div className={`flex items-center gap-2.5 rounded-xl px-3 py-2 text-[12.5px] ${min ? 'justify-center px-0' : ''}`} style={{ background: 'var(--fill)' }} title={st.text}>
          <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${st.pulse ? 'dot-live' : ''}`} style={{ background: st.dot, color: st.dot }} />
          {!min && <span className="muted truncate">{st.text}</span>}
        </div>
        <div className={`flex items-center ${min ? 'flex-col gap-1' : 'justify-between px-1'}`}>
          <button className="btn-icon !h-8 !w-8" onClick={cycle} data-tip={{ auto: 'тема: как в системе', light: 'тема: светлая', dark: 'тема: тёмная' }[mode]} data-tip-side={min ? 'right' : undefined}><ThemeIcon key={mode} size={14} className="theme-icon" /></button>
          <button className="btn-icon !h-8 !w-8" onClick={() => setMin(!min)} data-tip={min ? 'развернуть' : 'свернуть'} data-tip-side={min ? 'right' : undefined}>{min ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}</button>
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
      <div className="scroll-thin max-h-[60vh] overflow-y-auto">
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
  const [palOpen, setPalOpen] = useState(false)
  const [livePop, setLivePop] = useState(false)
  const [inboxOpen, setInboxOpen] = useState(false)
  const live = useLive(health)
  // ⌘K / ⌘/ — палитра; ⌘J — чат; Alt+1..7 — разделы
  useEffect(() => {
    const h = (e) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && (e.key.toLowerCase() === 'k' || e.key === '/')) { e.preventDefault(); setPalOpen((v) => !v) }
      else if (mod && e.key.toLowerCase() === 'j') { e.preventDefault(); setChatOpen((v) => !v) }
      else if (e.altKey && !mod && /^[1-7]$/.test(e.key)) { const it = NAV.find((n) => n.key === e.key); if (it) { e.preventDefault(); nav(it.to) } }
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

  const cycle = () => {
    document.documentElement.classList.add('theme-anim')
    setTimeout(() => document.documentElement.classList.remove('theme-anim'), 600)
    setMode(mode === 'auto' ? 'light' : mode === 'light' ? 'dark' : 'auto')
  }
  const ThemeIcon = mode === 'light' ? Sun : mode === 'dark' ? Moon : Monitor
  const st = assistantState(live, busy)
  const [prefs] = usePrefs()
  const [address, setAddress] = useState('сэр')
  useEffect(() => { api.settings().then((d) => { const it = d.items?.find((x) => x.key === 'owner.name'); if (it?.value) setAddress(String(it.value).toLowerCase()) }).catch(() => {}) }, [])
  const mobileNav = (prefs.tabbar || []).map((to) => NAV.find((n) => n.to === to)).filter(Boolean).slice(0, 5)

  return (
    <div className="flex min-h-screen">
      <Sidebar min={min} setMin={setMin} live={live} busy={busy} mode={mode} cycle={cycle} ThemeIcon={ThemeIcon} hiddenNav={prefs.hiddenNav} />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* top bar */}
        <div className="topbar safe-t sticky top-0 z-[50]">
          <div className="mx-auto flex h-[var(--topbar-h)] w-full max-w-[var(--content-max)] items-center justify-between gap-3 px-4 sm:px-8">
            <div className="relative flex items-center gap-2 md:hidden">
              <LiveDot live={live} onClick={() => setLivePop((v) => !v)} />
              <NavLink to="/" className="text-[15px] font-semibold tracking-[-0.03em]">{lower()}</NavLink>
              {livePop && <LivePopover live={live} onClose={() => setLivePop(false)} />}
            </div>
            <button className="search-trigger hidden md:flex" onClick={() => setPalOpen(true)}>
              <Search size={14} /><span className="flex-1 text-left">найти или спросить…</span><span className="kbd">{kb('K')}</span>
            </button>
            <div className="flex items-center gap-1.5">
              <button className="btn-icon !h-9 !w-9 md:hidden" onClick={() => setPalOpen(true)} aria-label="Поиск"><Search size={16} /></button>
              <MicButton onText={(t) => { setChatSeed({ text: t, n: Date.now(), send: true }); setChatOpen(true) }} className="hidden sm:inline-flex" />
              <div className="relative">
                <button className="btn-icon !h-9 !w-9" onClick={() => setInboxOpen((v) => !v)} aria-label="Уведомления" data-tip="уведомления">
                  <Bell size={16} />
                  {inbox.unread > 0 && <span className="absolute right-1.5 top-1.5 grid h-4 min-w-[16px] place-items-center rounded-full px-1 text-[10px] font-semibold text-white" style={{ background: 'var(--accent)' }}>{inbox.unread}</span>}
                </button>
                {inboxOpen && <InboxPanel inbox={inbox} onClose={() => setInboxOpen(false)} />}
              </div>
              <button className="btn-ghost !h-9" onClick={() => setChatOpen(true)} data-tip={`чат · ${kb('J')}`}>
                <MessageCircle size={15} /><span className="hidden sm:inline">чат</span>
              </button>
            </div>
          </div>
        </div>

        {health && !health.ok && (
          <div className="mx-auto w-full max-w-[var(--content-max)] px-4 pt-3 sm:px-8 animate-rise">
            <div className="soft-neg flex flex-wrap items-center justify-between gap-2 rounded-2xl px-4 py-2.5 text-[13px]">
              <span>Ядро не отвечает — данные могут быть устаревшими. Проверьте, что <code className="mono">start.bat</code> запущен.</span>
              <button className="btn-ghost btn-sm" style={{ color: 'inherit', borderColor: 'currentColor' }} onClick={() => api.health().then((h) => setHealth(h)).catch(() => {})}>проверить снова</button>
            </div>
          </div>
        )}

        {/* content */}
        <main className="relative z-0 mx-auto w-full min-w-0 max-w-[var(--content-max)] flex-1 px-4 pb-28 pt-6 sm:px-8 sm:pt-8 md:pb-16">
          <PageTransition pathKey={loc.pathname}>
          <Routes location={loc}>
            <Route path="/" element={<Today openChat={() => setChatOpen(true)} state={st} address={address} />} />
            <Route path="/finance" element={<Finance />} />
            <Route path="/calendar" element={<Calendar />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/mind" element={<Mind />} />
            <Route path="/memory" element={<Memory />} />
            <Route path="/settings" element={<Settings health={health} />} />
          </Routes>
          </PageTransition>
        </main>

        <footer className="mx-auto w-full max-w-[var(--content-max)] px-4 pb-28 sm:px-8 md:pb-6">
          <div className="rule flex flex-wrap items-center justify-between gap-2 pt-4">
            <div className="label">{lower()} · локально · {health?.ollama ? 'модель онлайн' : 'без локальной модели'}</div>
            <div className="label">v{health?.version || '?'}</div>
          </div>
        </footer>
      </div>

      {/* bottom tabs (mobile) */}
      <nav className={`tabbar fixed inset-x-0 bottom-0 z-[60] md:hidden ${prefs.compactNav ? 'compact' : ''}`}>
        <div className="mx-3 flex items-stretch justify-around rounded-full border hair px-1 py-1" style={{ background: 'var(--surface-2)', boxShadow: 'var(--shadow-2)' }}>
          {(mobileNav.length ? mobileNav : MOBILE_NAV).map(({ to, label, icon: I }) => (
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
        clearTimeout(timer); timer = setTimeout(bump, 150)
        if (d) {
          try { notifyFromEvent(d) } catch {}
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
