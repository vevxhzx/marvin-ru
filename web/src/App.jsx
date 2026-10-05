import { Component, Suspense, lazy, useEffect, useState, createContext, useContext, useCallback, useRef } from 'react'
import { BrowserRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { notifyFromEvent } from './lib/notify'
import { chimeFromEvent } from './lib/sound'
import Today from './pages/Today'
import Calendar from './pages/Calendar'
import Tasks from './pages/Tasks'
import Mind from './pages/Mind'
import People from './pages/People'
import Orders from './pages/Orders'
import { useI18n, t as T } from './lib/i18n'
import { api, kb, kbAlt } from './lib/api'
import { tg, tgBackButton } from './lib/tg'
import { setName } from './lib/name'
import { usePrefs, prefs as PREFS, pullRemote, CLIENT_ID, apply } from './lib/prefs'
import { useLive } from './components/Live'
import { NAV, NAV_GROUPS, pickTabs, pickMore } from './lib/nav'
import { Skeleton, toast } from './components/ui'
import AppShell from './components/AppShell'

/* Тяжёлые страницы — отдельными чанками: главная грузится сразу, а финансы/доска/
// память/настройки подтягиваются по первому переходу. Фолбэк — тот же Skeleton,
// что и при загрузке данных (components/ui.jsx), прыжка раскладки нет. */
const Finance = lazy(() => import('./pages/Finance'))
const BoardPage = lazy(() => import('./pages/Board'))
const Memory = lazy(() => import('./pages/Memory'))
const Settings = lazy(() => import('./pages/Settings'))

function PageFallback() {
  return (
    <div className="pg" aria-hidden="true">
      <Skeleton h={220} radius="var(--r-xl)" />
    </div>
  )
}

/* Навигация и её оболочка живут в lib/nav.js (один список на сайдбар, палитру и док).
   Здесь переэкспортируем, потому что настройки и другие страницы берут NAV_GROUPS отсюда.
   Оболочка (components/AppShell) монтирует ровно один док (components/Dock.jsx) и окна
   через один хост — components/SheetHost.jsx, тонкую обёртку над шторкой ui.jsx#Sheet. */
export { NAV_GROUPS }
export { Logo, LangToggle, assistantState, PageTransition } from './components/AppShell'

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
  const save = useCallback((next) => { setItems(next); localStorage.setItem(INBOX_KEY, JSON.stringify(next.slice(0, 40))) }, [])
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

/* Оболочка: логика приложения (роуты, SSE, горячие клавиши, тема, чат).
   Раскладка и движение — в components/AppShell. */
function Shell({ inbox }) {
  const { t } = useI18n()
  const [mode, setMode] = useTheme()
  const [health, setHealth] = useState(null)
  const [chatOpen, setChatOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const loc = useLocation()
  const nav = useNavigate()
  const { bump } = useRefresh()

  useEffect(() => {
    const load = () => api.health().then((h) => { setHealth(h); if (h?.name) setName(h.name) }).catch(() => setHealth({ ok: false }))
    load(); const t = setInterval(load, 30000); return () => clearInterval(t)
  }, [])
  // Скролл наверх — при смене страницы И при смене вкладки внутри неё (?tab=).
  // Раньше реакция была только на pathname: на «Мозге» клик по вкладке менял лишь
  // query, остаток прокрутки оставался — новый список открывался под липкой шапкой,
  // а сами вкладки уезжали вверх и было непонятно, что открыто. ?q= (поиск) не
  // участвует намеренно: он пишется на каждый символ, прыжок наверх помешал бы набору.
  const scrollKey = `${loc.pathname}#${new URLSearchParams(loc.search).get('tab') || ''}`
  useEffect(() => { window.scrollTo({ top: 0 }) }, [scrollKey])
  // внутри Telegram: системная кнопка «назад» в шапке ведёт на главную (с главной Telegram сам показывает «закрыть»)
  useEffect(() => {
    if (!tg.active) return
    return tgBackButton(loc.pathname !== '/', () => nav('/'))
  }, [loc.pathname, nav])
  const [palOpen, setPalOpen] = useState(false)
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
  const [prefs] = usePrefs()
  const [address, setAddress] = useState('')
  useEffect(() => {
    const load = () => api.settings().then((d) => { const it = d.items?.find((x) => x.key === 'owner.name'); setAddress(it?.value ? String(it.value).toLowerCase() : t('common.sir')) }).catch(() => {})
    load(); pullRemote()
    const h = (e) => { if (e.detail?.kind === 'settings') load() }
    window.addEventListener('assistant:event', h)
    return () => window.removeEventListener('assistant:event', h)
  }, [])
  // режим фрилансера: выключен — «заказы» уходят из меню/палитры/дока (страница остаётся доступна по адресу)
  const [freelance, setFreelance] = useState(() => localStorage.getItem('freelance.on') !== '0')
  useEffect(() => {
    const apply = (r) => { setFreelance(!!r.enabled); localStorage.setItem('freelance.on', r.enabled ? '1' : '0') }
    api.freelance().then(apply).catch(() => {})
    const h = (e) => apply(e.detail || {})
    window.addEventListener('freelance:changed', h); return () => window.removeEventListener('freelance:changed', h)
  }, [])
  const hiddenNav = freelance ? prefs.hiddenNav : [...prefs.hiddenNav, '/orders']
  // нижние вкладки: до 4 разделов из настроек + «Ещё» с остальными
  const tabs = pickTabs(prefs.tabbar, freelance)
  const more = pickMore(tabs, freelance)

  /* Потянуть-обновить: перечитываем состояние ядра и будим страницы */
  const onRefresh = useCallback(async () => {
    bump()
    try { const h = await api.health(); setHealth(h); if (h?.name) setName(h.name) } catch { /* офлайн — тихо */ }
  }, [bump])

  if (denied) return <Gate denied={denied} />

  return (
    <AppShell
      live={live}
      busy={busy}
      health={health}
      inbox={inbox}
      inboxOpen={inboxOpen}
      onInbox={() => setInboxOpen((v) => !v)}
      pathKey={loc.pathname}
      address={address}
      onSearch={() => setPalOpen(true)}
      chatOpen={chatOpen}
      chatSeed={chatSeed}
      onChat={() => setChatOpen(true)}
      onChatClose={() => setChatOpen(false)}
      palOpen={palOpen}
      onPalClose={() => setPalOpen(false)}
      onPalChat={() => { setPalOpen(false); setChatOpen(true) }}
      setTheme={setMode}
      mode={mode}
      onTheme={cycle}
      helpOpen={helpOpen}
      onHelp={() => setHelpOpen(true)}
      onHelpClose={() => setHelpOpen(false)}
      hotkeys={HOTKEYS}
      tabs={tabs}
      more={more}
      compact={prefs.compactNav}
      hiddenNav={hiddenNav}
      onRefresh={onRefresh}
    >
      <PageGuard pathKey={loc.pathname}>
        <Suspense fallback={<PageFallback />}>
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
        </Suspense>
      </PageGuard>
    </AppShell>
  )
}

/* Живое соединение с ядром: useLive держит SSE-подобный опрос и пульс ПК-клиента */

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