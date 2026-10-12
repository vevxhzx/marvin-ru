/* mapp/shell.jsx — MApp-оболочка мобильной копии (порт референса shell.tsx/MarvinApp.tsx).
 *
 * Что внутри: тёмный фон m-bg + стеклянные орбы, скролл-экран с компакт-шапкой
 * (MScroll), нижняя капсула с 5 вкладками + FAB (BottomNav), тост с action
 * (MToast), QuickAdd-шторка (./QuickAdd.jsx) и сам MApp: экраны home/tasks/
 * calendar/finance/more/chat/settings, данные — только живые (lib/api.js).
 * Иконки сверены с нашей lucide-react 0.446 (SquareCheckBig/Ellipsis есть,
 * CircleQuestionMark отсутствует — здесь не используется).
 * Свои элементы — с data-testid m-*, существующие e2e-селекторы не трогаем.
 */
import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { CalendarDays, Check, ChevronLeft, LayoutGrid, Plus, Sparkles, SquareCheckBig, Wallet } from 'lucide-react'
import { useI18n } from '../lib/i18n'
import './mapp.css'

const MHome = lazy(() => import('./screens/Home.jsx'))
const MTasks = lazy(() => import('./screens/Tasks.jsx'))
const MCalendar = lazy(() => import('./screens/Calendar.jsx'))
const MFinance = lazy(() => import('./screens/Finance.jsx'))
const MBrain = lazy(() => import('./screens/Brain.jsx'))
const MOrders = lazy(() => import('./screens/Orders.jsx'))
const MPeople = lazy(() => import('./screens/People.jsx'))
const MMore = lazy(() => import('./screens/More.jsx'))
const MChat = lazy(() => import('./screens/Chat.jsx'))
const MSettings = lazy(() => import('./screens/Settings.jsx'))
const MQuickAdd = lazy(() => import('./QuickAdd.jsx'))

const cx = (...parts) => parts.filter(Boolean).join(' ')

/* ───────── стеклянные пузыри фона ───────── */
export function Orbs() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      <div className="m-orb anim-float" style={{ width: 178, height: 178, top: 74, right: -26 }} />
      <div className="m-orb anim-float-slow" style={{ width: 122, height: 122, top: 548, right: -56 }} />
      <div className="m-orb anim-float" style={{ width: 52, height: 52, top: 420, left: -20, opacity: 0.55 }} />
    </div>
  )
}

/* ───────── скролл экрана + компактная шапка ───────── */
export function MScroll({ title, onBack, children }) {
  const { t } = useI18n()
  const [blur, setBlur] = useState(false)
  const [compact, setCompact] = useState(false)
  return (
    <>
      <div
        data-testid="m-scroll"
        className="no-scrollbar anim-screen absolute inset-0 overflow-y-auto overscroll-contain pb-[132px] pt-[58px]"
        onScroll={(e) => {
          const y = e.currentTarget.scrollTop
          setBlur(y > 4)
          setCompact(y > 74)
        }}
      >
        {children}
      </div>
      <div
        aria-hidden="true"
        className={cx(
          'm-blur-top pointer-events-none absolute inset-x-0 top-0 z-30 h-[112px] transition-opacity duration-300',
          blur ? 'opacity-100' : 'opacity-0',
        )}
      />
      <div
        className={cx(
          'absolute inset-x-0 top-[52px] z-40 flex h-[40px] items-center justify-center px-16 transition-all duration-300',
          compact ? 'translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1.5 opacity-0',
        )}
      >
        {onBack && (
          <button
            onClick={onBack}
            aria-label={t('common.back')}
            data-testid="m-compact-back"
            className="m-glass absolute left-4 grid h-8 w-8 place-items-center rounded-full"
          >
            <ChevronLeft size={18} />
          </button>
        )}
        <span className="truncate text-[16px] font-semibold">{title}</span>
      </div>
    </>
  )
}

/* ───────── навбар: капсула с 5 вкладками + отдельная «+» ───────── */
const TABS = [
  { id: 'home', key: 'm.tab_home', icon: Sparkles },
  { id: 'tasks', key: 'm.tab_tasks', icon: SquareCheckBig },
  { id: 'calendar', key: 'm.tab_calendar', icon: CalendarDays },
  { id: 'finance', key: 'm.tab_finance', icon: Wallet },
  { id: 'more', key: 'm.tab_more', icon: LayoutGrid },
]

export function BottomNav({ active, onTab, onPlus }) {
  const { t } = useI18n()
  const idx = Math.max(0, TABS.findIndex((x) => x.id === active))
  return (
    <div data-testid="m-nav" className="pointer-events-none absolute inset-x-0 bottom-[26px] z-40 flex items-center gap-2.5 px-4">
      <nav className="m-glass-strong pointer-events-auto relative flex h-[64px] flex-1 items-center rounded-full p-1">
        <div
          aria-hidden="true"
          className="absolute bottom-1 left-1 top-1 rounded-full border border-white/20 bg-white/[0.14] shadow-[inset_0_1px_0_rgba(255,255,255,0.3),0_6px_16px_-6px_rgba(0,0,0,0.35)] transition-transform duration-500 ease-[cubic-bezier(.3,1.3,.5,1)]"
          style={{ width: 'calc((100% - 8px) / 5)', transform: `translateX(${idx * 100}%)` }}
        />
        {TABS.map((x) => {
          const on = x.id === active
          const Icon = x.icon
          return (
            <button
              key={x.id}
              onClick={() => onTab(x.id)}
              data-testid={`m-tab-${x.id}`}
              aria-current={on ? 'true' : undefined}
              aria-label={t(x.key)}
              title={t(x.key)}
              className={cx(
                'relative z-10 flex h-full flex-1 items-center justify-center transition-colors active:scale-95',
                on ? 'text-white' : 'text-white/55',
              )}
            >
              <Icon size={23} strokeWidth={on ? 2.2 : 1.8} />
            </button>
          )
        })}
      </nav>
      <button
        onClick={onPlus}
        aria-label={t('common.add')}
        data-testid="m-fab"
        className="m-fab pointer-events-auto grid h-[64px] w-[64px] shrink-0 place-items-center rounded-full transition active:scale-90"
      >
        <Plus size={28} strokeWidth={2.4} />
      </button>
    </div>
  )
}

/* ───────── тост с action ───────── */
export function MToast({ data, onClose, raised }) {
  if (!data) return null
  return (
    <div
      data-testid="m-toast"
      className={cx(
        'anim-toast absolute inset-x-4 z-50 flex items-center gap-3 rounded-[20px] border border-white/10 bg-[#0d1336]/95 px-4 py-3 shadow-[0_20px_40px_-12px_rgba(0,0,0,0.6)] backdrop-blur-xl',
        raised ? 'bottom-[150px]' : 'bottom-[104px]',
      )}
    >
      <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#3ddc97]/15 text-[#7cf0c0]">
        <Check size={15} strokeWidth={2.6} />
      </div>
      <span className="flex-1 text-[14px] leading-snug">{data.text}</span>
      {data.action && (
        <button
          data-testid="m-toast-action"
          onClick={() => {
            try { data.action.fn() } catch {}
            onClose()
          }}
          className="shrink-0 text-[14px] font-semibold text-[#a9bbff]"
        >
          {data.action.label}
        </button>
      )}
    </div>
  )
}

/* ───────── заглушка разделов второй очереди (календарь/финансы) ───────── */
export function MSoon() {
  const { t } = useI18n()
  return (
    <div data-testid="m-soon" className="px-4 pt-16 text-center">
      <div className="text-[34px]" aria-hidden="true">✦</div>
      <div className="mt-2 text-[16px] font-semibold">{t('m.soon_title')}</div>
      <div className="mt-1 text-[13px] text-white/55">{t('m.soon_sub')}</div>
    </div>
  )
}

const TAB_OF = {
  home: 'home', chat: 'home', tasks: 'tasks', calendar: 'calendar',
  finance: 'finance', more: 'more', brain: 'more', orders: 'more',
  people: 'more', settings: 'more',
}

/* Все экраны — внутренние (живые данные через lib/api.js). */
const KNOWN = new Set([
  'home', 'tasks', 'calendar', 'finance', 'more', 'brain',
  'orders', 'people', 'chat', 'settings',
])

function screenTitle(t, screen) {
  if (screen === 'tasks') return t('m.tasks_title')
  if (screen === 'calendar') return t('m.tab_calendar')
  if (screen === 'finance') return t('m.tab_finance')
  if (screen === 'more') return t('common.more')
  if (screen === 'brain') return t('m.brain')
  if (screen === 'orders') return t('m.orders')
  if (screen === 'people') return t('m.people')
  if (screen === 'settings') return t('nav.settings')
  return t('m.tab_home')
}

/* Экраны с кнопкой «назад» в компакт-шапке — все подразделы «ещё». */
const BACK_OF = { brain: 'more', orders: 'more', people: 'more', settings: 'more' }

export default function MApp() {
  const { t } = useI18n()
  const [screen, setScreen] = useState('home')
  const [sheet, setSheet] = useState(false)
  const [chatSeed, setChatSeed] = useState(null)
  const [toastData, setToastData] = useState(null)
  const timer = useRef(0)

  /* MApp живёт в тёмном скине всегда: форсим data-theme=dark + .dark,
     при размонтировании возвращаем как было (десктопную тему не трогаем). */
  useEffect(() => {
    const de = document.documentElement
    const prevTheme = de.getAttribute('data-theme')
    const prevDark = de.classList.contains('dark')
    de.setAttribute('data-theme', 'dark')
    de.classList.add('dark')
    return () => {
      if (prevTheme == null) de.removeAttribute('data-theme')
      else de.setAttribute('data-theme', prevTheme)
      de.classList.toggle('dark', prevDark)
    }
  }, [])
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const toast = useCallback((text, action) => {
    window.clearTimeout(timer.current)
    setToastData({ id: Date.now() + Math.random(), text, action })
    timer.current = window.setTimeout(() => setToastData(null), 3400)
  }, [])

  const go = useCallback((s) => {
    if (!KNOWN.has(s)) return
    setSheet(false)
    setScreen(s)
  }, [])

  /* Чипсы главной шлют assistant:chat — внутри MApp это вход в мобильный чат. */
  useEffect(() => {
    const h = (e) => {
      setChatSeed({ text: e.detail?.text || '', n: Date.now(), send: !!e.detail?.send })
      setSheet(false)
      setScreen('chat')
    }
    window.addEventListener('assistant:chat', h)
    return () => window.removeEventListener('assistant:chat', h)
  }, [])

  const chat = screen === 'chat'
  const content = screen === 'home'
    ? <MHome go={go} />
    : screen === 'tasks'
      ? <MTasks />
      : screen === 'calendar'
        ? <MCalendar />
        : screen === 'finance'
          ? <MFinance />
          : screen === 'more'
            ? <MMore go={go} />
            : screen === 'brain'
              ? <MBrain />
              : screen === 'orders'
                ? <MOrders />
                : screen === 'people'
                  ? <MPeople />
                  : screen === 'settings'
                    ? <MSettings go={go} />
                    : <MSoon />
  const backTo = BACK_OF[screen]

  return (
    <div data-testid="m-app" className="mapp-root m-bg fixed inset-0 select-none overflow-hidden text-white">
      <Orbs />
      <div key={screen} className="absolute inset-0">
        <Suspense fallback={null}>
          {chat
            ? <MChat seed={chatSeed} go={go} toast={toast} />
            : (
              <MScroll title={screenTitle(t, screen)} onBack={backTo ? () => go(backTo) : undefined}>
                {content}
              </MScroll>
            )}
        </Suspense>
      </div>
      {!chat && <div aria-hidden="true" className="m-blur-bottom pointer-events-none absolute inset-x-0 bottom-0 z-30 h-[130px]" />}
      {!chat && <BottomNav active={TAB_OF[screen] || 'home'} onTab={go} onPlus={() => setSheet(true)} />}
      {toastData && <MToast key={toastData.id} data={toastData} raised={chat} onClose={() => setToastData(null)} />}
      {sheet && (
        <Suspense fallback={null}>
          <MQuickAdd onClose={() => setSheet(false)} toast={toast} go={go} />
        </Suspense>
      )}
    </div>
  )
}
