import { useEffect, useState, createContext, useContext, useCallback, useRef } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { Sun, Moon, Monitor, Sparkles, Wallet, CalendarDays, CheckSquare, Brain, Settings as SettingsIcon } from 'lucide-react'
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
import { setName, name as aName, onName } from './lib/name'
import { api } from './lib/api'

const NAV = [
  { to: '/', label: 'сегодня', icon: Sparkles },
  { to: '/finance', label: 'финансы', icon: Wallet },
  { to: '/calendar', label: 'календарь', icon: CalendarDays },
  { to: '/tasks', label: 'задачи', icon: CheckSquare },
  { to: '/mind', label: 'мозг', icon: Brain },
]

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
      document.querySelector('meta[name=theme-color]')?.setAttribute('content', dark ? '#0f0f0e' : '#ecece9')
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

/* Переход между страницами: старая уезжает вверх и размывается, новая проявляется каскадом */
function PageTransition({ children, pathKey }) {
  const [shown, setShown] = useState({ key: pathKey, node: children })
  const [phase, setPhase] = useState('enter')
  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    if (pathKey === shown.key) { setShown({ key: pathKey, node: children }); return }
    setPhase('exit')
    const t = setTimeout(() => { setShown({ key: pathKey, node: children }); setPhase('enter') }, 170)
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


function Shell() {
  const [mode, setMode] = useTheme()
  const [health, setHealth] = useState(null)
  const [chatOpen, setChatOpen] = useState(false)
  const loc = useLocation()

  useEffect(() => {
    const load = () => api.health().then((h) => { setHealth(h); if (h?.name) setName(h.name) }).catch(() => setHealth({ ok: false }))
    load(); const t = setInterval(load, 30000); return () => clearInterval(t)
  }, [])
  useEffect(() => { window.scrollTo({ top: 0 }) }, [loc.pathname])
  // ⌘K / Ctrl+K — командная палитра с любой страницы (⌘J — чат)
  const [palOpen, setPalOpen] = useState(false)
  const [livePop, setLivePop] = useState(false)
  const live = useLive(health)
  useEffect(() => {
    const h = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalOpen((v) => !v) }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'j') { e.preventDefault(); setChatOpen((v) => !v) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [])
  // кнопка-подсказка в пустых состояниях: открыть чат с готовой фразой
  const [chatSeed, setChatSeed] = useState(null)
  useEffect(() => {
    const h = (e) => { setChatSeed({ text: e.detail?.text || '', n: Date.now() }); setChatOpen(true) }
    window.addEventListener('assistant:chat', h); return () => window.removeEventListener('assistant:chat', h)
  }, [])

  const cycle = () => {
    document.documentElement.classList.add('theme-anim')
    setTimeout(() => document.documentElement.classList.remove('theme-anim'), 600)
    setMode(mode === 'auto' ? 'light' : mode === 'light' ? 'dark' : 'auto')
  }
  const ThemeIcon = mode === 'light' ? Sun : mode === 'dark' ? Moon : Monitor

  return (
    <div className="min-h-screen">
      {/* top bar */}
      <div className="safe-t sticky top-0 z-[50] border-b hair" style={{ background: 'color-mix(in srgb, var(--bg) 88%, transparent)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)' }}>
        <div className="mx-auto flex h-[60px] max-w-[1320px] items-center justify-between gap-4 px-4 sm:px-8">
          <div className="relative flex items-center gap-2">
            <LiveDot live={live} onClick={() => setLivePop((v) => !v)} />
            <NavLink to="/" className="text-[16px] font-semibold tracking-[-0.03em]">{aName().toLowerCase()}</NavLink>
            {livePop && <LivePopover live={live} onClose={() => setLivePop(false)} />}
          </div>

          <nav className="hidden items-center gap-1.5 md:flex">
            {NAV.map(({ to, label }) => (
              <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `pill ${isActive ? 'on' : ''}`}>{label}</NavLink>
            ))}
            <NavLink to="/memory" className={({ isActive }) => `pill ${isActive ? 'on' : ''}`}>память</NavLink>
          </nav>

          <div className="flex items-center gap-2">
            <MicButton onText={(t) => { setChatSeed({ text: t, n: Date.now(), send: true }); setChatOpen(true) }} className="hidden sm:inline-flex" />
            <button className="btn-icon !h-9 !w-9" onClick={cycle} title="Тема"><ThemeIcon key={mode} size={15} className="theme-icon" /></button>
            <NavLink to="/settings" className={({ isActive }) => `btn-icon !h-9 !w-9 ${isActive ? 'text-accent' : ''}`} title="Настройки и статус"><SettingsIcon size={15} /></NavLink>
            <button className="btn-primary !px-4 !py-2" onClick={() => setChatOpen(true)} title="⌘J / Ctrl+J · палитра команд — ⌘K">написать <span className="ml-0.5 font-normal">↗</span></button>
          </div>
        </div>
      </div>

      {/* content */}
      <main className="relative z-0 mx-auto min-w-0 max-w-[1320px] px-4 pb-32 pt-8 sm:px-8 sm:pt-14 md:pb-24">
        <PageTransition pathKey={loc.pathname}>
        <Routes location={loc}>
          <Route path="/" element={<Today openChat={() => setChatOpen(true)} />} />
          <Route path="/finance" element={<Finance />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/mind" element={<Mind />} />
          <Route path="/memory" element={<Memory />} />
          <Route path="/settings" element={<Settings health={health} />} />
        </Routes>
        </PageTransition>
      </main>

      {/* footer-подпись */}
      <footer className="mx-auto max-w-[1320px] px-4 pb-28 sm:px-8 md:pb-10">
        <div className="rule flex flex-wrap items-baseline justify-between gap-2 pt-6">
          <div className="display text-[44px] sm:text-[72px]">{aName().toLowerCase()}<span className="accent">*</span></div>
          <div className="label">локально · {health?.ollama ? 'мозг онлайн' : 'только правила'} · v{health?.version || '?'}</div>
        </div>
      </footer>

      {/* bottom tabs (mobile) */}
      <nav className="tabbar fixed inset-x-0 bottom-0 z-[60] md:hidden">
        <div className="mx-3 flex items-stretch justify-around rounded-full border hair px-1 py-1" style={{ background: 'var(--bg)', boxShadow: '0 8px 30px rgba(0,0,0,.08)' }}>
          {NAV.map(({ to, label, icon: I }) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-0.5 rounded-full py-2 text-[10px] font-medium transition ${isActive ? 'text-accent' : 'faint'}`}>
              <I size={19} strokeWidth={2} /> {label}
            </NavLink>
          ))}
        </div>
      </nav>

      <Chat open={chatOpen} onClose={() => setChatOpen(false)} seed={chatSeed} />
      <Palette open={palOpen} onClose={() => setPalOpen(false)} openChat={() => setChatOpen(true)} setTheme={setMode} />
    </div>
  )
}

export default function App() {
  const theme = useThemeState()
  const [tick, setTick] = useState(0)
  const bump = useCallback(() => setTick((t) => t + 1), [])
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
        if (d) { try { notifyFromEvent(d) } catch {} }
      }
      es.onerror = () => { es.close(); setTimeout(connect, 4000) }
    }
    connect()
    const onVis = () => { if (document.visibilityState === 'visible') bump() }
    document.addEventListener('visibilitychange', onVis)
    return () => { es?.close(); document.removeEventListener('visibilitychange', onVis) }
  }, [bump])
  return (
    <ThemeCtx.Provider value={theme}>
      <RefreshCtx.Provider value={{ tick, bump }}>
        <BrowserRouter><Shell /></BrowserRouter>
      </RefreshCtx.Provider>
    </ThemeCtx.Provider>
  )
}
