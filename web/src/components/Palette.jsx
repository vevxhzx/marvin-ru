import { useEffect, useMemo, useRef, useState } from 'react'
import { dat, gen } from '../lib/name'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Clapperboard, Sparkles, Wallet, CalendarDays, CheckSquare, Brain, Settings, Search, MessageCircle, Plus, Moon, Sun, Monitor, Undo2, Gamepad2, BarChart3, Coins, Flame, History, Link2, FileText, CornerDownLeft, Briefcase, Timer, Target, Users, Share2 } from 'lucide-react'
import { api, kb, kbAlt } from '../lib/api'
import { renderMd } from './Chat'
import { Empty } from './ui'
import { useI18n, t as T } from '../lib/i18n'

/* ⌘K — командная палитра: страницы, действия, поиск по Мозгу; всё остальное — фраза ассистенту.
   Fuzzy-поиск (подпоследовательность + вхождение), категории, недавние в localStorage, полная навигация с клавиатуры.
   label/hint — ключи словаря: подписи переключаются вместе с языком.
   Поверхность — обычная elevated-карточка (--surface-2 + --line): спокойно в обеих темах; подложка —
   затемнение из токена фона. Строки — --tap, анимируется только transform/opacity (rise/fade),
   уважается prefers-reduced-motion (общее правило в index.css).
   Строки в run()/ctx.send() — это фразы для ЯДРА, они остаются на русском (i18n-raw). */
const PAGES = [
  { id: 'p-today', label: 'pal.today', icon: Sparkles, to: '/', get kbd() { return kbAlt('1') } },
  { id: 'p-tasks', label: 'pal.tasks', icon: CheckSquare, to: '/tasks', get kbd() { return kbAlt('2') } },
  { id: 'p-cal', label: 'pal.calendar', icon: CalendarDays, to: '/calendar', get kbd() { return kbAlt('3') } },
  { id: 'p-fin', label: 'pal.finance', icon: Wallet, to: '/finance', get kbd() { return kbAlt('4') } },
  { id: 'p-orders', label: 'pal.orders', icon: Briefcase, to: '/orders', get kbd() { return kbAlt('5') } },
  { id: 'p-mind', label: 'pal.mind', icon: Brain, to: '/mind', get kbd() { return kbAlt('6') } },
  { id: 'p-people', label: 'pal.people', icon: Users, to: '/people', get kbd() { return kbAlt('9') } },
  { id: 'p-graph', label: 'pal.graph', icon: Share2, to: '/mind?tab=graph' },
  { id: 'p-board', label: 'pal.board', icon: Clapperboard, to: '/board', get kbd() { return kbAlt('0') } },
  { id: 'p-mem', label: 'pal.memory', icon: History, to: '/memory', get kbd() { return kbAlt('7') } },
  { id: 'p-set', label: 'pal.settings', icon: Settings, to: '/settings', get kbd() { return kbAlt('8') } },
]
const ACTIONS = [
  { id: 'a-chat', get label() { return T('pal.write_to', { name: dat() }) }, hint: 'pal.hint_chat', icon: MessageCircle, get kbd() { return kb('J') }, run: (c) => c.openChat() },
  { id: 'a-tx', label: 'pal.add_expense', hint: 'pal.hint_finance', icon: Plus, run: (c) => c.chat('потратил ') },   // i18n-raw
  { id: 'a-task', label: 'pal.new_task', hint: 'pal.hint_tasks', icon: Plus, run: (c) => c.chat('задача: ') },   // i18n-raw
  { id: 'a-ev', label: 'pal.new_event', hint: 'pal.hint_calendar', icon: Plus, run: (c) => c.chat('встреча ') },   // i18n-raw
  { id: 'a-note', label: 'pal.add_note', hint: 'pal.hint_mind', icon: Plus, run: (c) => c.chat('мысль: ') },   // i18n-raw
  { id: 'a-board', label: 'pal.to_board', hint: 'pal.hint_board', icon: Plus, run: (c) => c.chat('на доску: ') },   // i18n-raw
  { id: 'a-story', label: 'pal.new_storyboard', hint: 'pal.hint_board', icon: Plus, run: (c) => c.chat('раскадровка: ') },   // i18n-raw
  { id: 'a-order', label: 'pal.new_order', hint: 'pal.hint_orders', icon: Plus, freelance: true, run: (c) => c.chat('заказ: ') },   // i18n-raw
  { id: 'a-pomo', label: 'pal.timer_25', hint: 'pal.hint_pomodoro', icon: Timer, freelance: true, run: (c) => c.send('таймер') },   // i18n-raw
  { id: 'a-pomo-stop', label: 'pal.timer_stop', hint: 'pal.hint_pomodoro', icon: Timer, freelance: true, run: (c) => c.send('стоп') },   // i18n-raw
  { id: 'a-goal', label: 'pal.new_goal', hint: 'pal.hint_finance', icon: Target, run: (c) => c.chat('цель: ') },   // i18n-raw
  { id: 'a-503020', label: 'pal.ask_503020', hint: 'pal.hint_ask', icon: BarChart3, run: (c) => c.send('50/30/20') },   // i18n-raw
  { id: 'a-cmp', label: 'pal.ask_cmp', hint: 'pal.hint_ask', icon: BarChart3, run: (c) => c.send('сравни с прошлым месяцем') },   // i18n-raw
  { id: 'a-fc', label: 'pal.ask_forecast', hint: 'pal.hint_ask', icon: BarChart3, run: (c) => c.send('прогноз') },   // i18n-raw
  { id: 'a-subs', label: 'pal.ask_subs', hint: 'pal.hint_ask', icon: Coins, run: (c) => c.send('подписки') },   // i18n-raw
  { id: 'a-streak', label: 'pal.ask_streak', hint: 'pal.hint_ask', icon: Flame, run: (c) => c.send('стрик') },   // i18n-raw
  { id: 'a-undo', label: 'pal.undo_last', hint: 'pal.hint_undo', icon: Undo2, run: (c) => c.send('отмена') },   // i18n-raw
  { id: 'a-game', label: 'pal.game_mode', hint: 'pal.hint_pc', icon: Gamepad2, run: (c) => c.game() },
  { id: 'a-light', label: 'pal.theme_light', hint: 'pal.hint_look', icon: Sun, run: (c) => c.theme('light') },
  { id: 'a-dark', label: 'pal.theme_dark', hint: 'pal.hint_look', icon: Moon, run: (c) => c.theme('dark') },
  { id: 'a-auto', label: 'pal.theme_auto', hint: 'pal.hint_look', icon: Monitor, run: (c) => c.theme('auto') },
]
const GROUP = { recent: 'pal.g_recent', page: 'pal.g_page', action: 'pal.g_action', found: 'pal.g_found', ask: 'pal.g_ask' }

const norm = (s) => String(s).toLowerCase().replace(/ё/g, 'е' /* i18n-raw */)
/* оценка: 0 — нет; больше — лучше (вхождение в начале > вхождение > подпоследовательность) */
function score(q, s) {
  q = norm(q); s = norm(s); if (!q) return 1
  if (s.startsWith(q)) return 100
  const i = s.indexOf(q); if (i >= 0) return 60 - Math.min(i, 30)
  let j = 0, gaps = 0, last = -1
  for (let k = 0; k < s.length && j < q.length; k++) if (s[k] === q[j]) { if (last >= 0 && k - last > 1) gaps++; last = k; j++ }
  return j === q.length ? Math.max(1, 20 - gaps * 3) : 0
}
const RKEY = 'palette.recent'
const recent = () => { try { return JSON.parse(localStorage.getItem(RKEY) || '[]') } catch { return [] } }
const remember = (id) => { const r = [id, ...recent().filter((x) => x !== id)].slice(0, 4); localStorage.setItem(RKEY, JSON.stringify(r)) }

export default function Palette({ open, onClose, openChat, setTheme }) {
  const { t, lang } = useI18n()
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const [found, setFound] = useState([])
  const [busy, setBusy] = useState(false)
  const [answer, setAnswer] = useState(null)
  const inp = useRef(null)
  const list = useRef(null)
  const nav = useNavigate()

  useEffect(() => { if (open) { setQ(''); setSel(0); setAnswer(null); setFound([]); setTimeout(() => inp.current?.focus(), 30) } }, [open])
  useEffect(() => {
    if (!open || q.trim().length < 3) { setFound([]); return }
    const t = setTimeout(() => api.semantic(q, 5).then((r) => setFound(r.items || [])).catch(() => setFound([])), 220)
    return () => clearTimeout(t)
  }, [q, open])

  const ctx = useMemo(() => ({
    openChat: () => { onClose(); openChat() },
    chat: (text) => { onClose(); window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } })) },
    send: async (text) => { setBusy(true); setAnswer(null); try { const r = await api.chat(text); setAnswer(r.text) } catch (e) { setAnswer(T('pal.core_down', { msg: e.message })) } finally { setBusy(false) } },
    game: async () => { setBusy(true); try { const s = await api.status(); const r = await api.post('/api/game', { on: !s.game_mode }); setAnswer(r.text) } catch (e) { setAnswer(e.message) } finally { setBusy(false) } },
    theme: (m) => { setTheme(m); onClose() },
  }), [onClose, openChat, setTheme])

  const fl = localStorage.getItem('freelance.on') !== '0'   // режим фрилансера выключен — заказы и таймер не предлагаем
  // ключи → подписи текущего языка (lang в зависимостях, чтобы список перестроился при смене языка)
  const all = useMemo(() => [...PAGES.filter((p) => fl || p.to !== '/orders').map((p) => ({ ...p, kind: 'page', label: t(p.label), hint: t('pal.hint_page') })), ...ACTIONS.filter((a) => fl || !a.freelance).map((a) => ({ ...a, label: a.label, kind: 'action' }))], [fl, lang])
  const items = useMemo(() => {
    const qq = q.trim()
    let out = []
    if (!qq) {
      const rec = recent().map((id) => all.find((x) => x.id === id)).filter(Boolean).map((x) => ({ ...x, group: 'recent' }))
      out = [...rec, ...all.filter((x) => !rec.some((r) => r.id === x.id)).map((x) => ({ ...x, group: x.kind }))]
    } else {
      out = all.map((x) => ({ ...x, group: x.kind, hint: x.hint ? t(x.hint) : x.hint, s: Math.max(score(qq, x.label), score(qq, t(x.hint) || '') * 0.5) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s)
      for (const f of found) out.push({ id: `f-${f.kind}-${f.id}`, kind: 'found', group: 'found', label: f.title || f.text || f.url, hint: f.kind === 'note' ? t('pal.hint_note') : t('pal.hint_link'), icon: f.kind === 'link' ? Link2 : FileText, item: f })
      out.push({ id: 'ask', kind: 'ask', group: 'ask', label: t('pal.ask', { name: gen(), q: qq }), hint: 'enter', icon: MessageCircle })
    }
    return out.slice(0, 16)
  }, [q, found, all, open, lang])

  useEffect(() => { setSel(0) }, [q])
  useEffect(() => { list.current?.querySelector(`[data-i="${sel}"]`)?.scrollIntoView({ block: 'nearest' }) }, [sel])

  const run = (it) => {
    if (!it) return
    if (it.kind === 'page') { remember(it.id); nav(it.to); onClose() }
    else if (it.kind === 'action') { remember(it.id); it.run(ctx) }
    else if (it.kind === 'found') { if (it.item.kind === 'link' && it.item.url) window.open(it.item.url, '_blank'); else { nav('/mind'); onClose() } }
    else if (it.kind === 'ask') ctx.send(q.trim())
  }

  useEffect(() => {
    if (!open) return
    const h = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      else if (e.key === 'ArrowDown' || (e.key === 'j' && e.ctrlKey)) { e.preventDefault(); setSel((s) => Math.min(items.length - 1, s + 1)) }
      else if (e.key === 'ArrowUp' || (e.key === 'k' && e.ctrlKey)) { e.preventDefault(); setSel((s) => Math.max(0, s - 1)) }
      else if (e.key === 'Enter') { e.preventDefault(); run(items[sel]) }
      else if (e.key === 'Tab') { e.preventDefault(); setSel((s) => (s + (e.shiftKey ? -1 : 1) + items.length) % items.length) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [open, items, sel]) // eslint-disable-line

  if (!open) return null
  let lastGroup = null
  return createPortal(
    <div className="fixed inset-0 flex items-start justify-center px-3 pt-[calc(10vh/var(--ui-zoom))] sm:pt-[calc(14vh/var(--ui-zoom))]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      style={{ zIndex: 'var(--z-scrim)', background: 'color-mix(in srgb, var(--bg) 40%, rgba(8, 8, 12, .46))', animation: 'fade .16s ease-out' }}>
      <div className="elevated flex max-h-[86dvh] w-full max-w-[600px] flex-col overflow-hidden" style={{ animation: 'rise .22s var(--ease-out)' }}
        role="dialog" aria-modal="true" aria-label={t('pal.aria')}>
        <div className="hair flex items-center gap-3 border-b px-4">
          <Search size={16} className="faint shrink-0" aria-hidden="true" />
          <input ref={inp} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('pal.ph')} aria-label={t('pal.ph')}
            className="w-full bg-transparent outline-none placeholder:text-[var(--ink-3)]" style={{ height: 52, fontSize: 'var(--fs-base)' }} />
          <span className="kbd" aria-hidden="true">esc</span>
        </div>
        {(answer || busy) && (
          <div className="hair animate-rise border-b px-4 py-3" style={{ fontSize: 'var(--fs-base)', lineHeight: 'var(--lh-body)' }}>
            {busy ? <span className="muted flex items-center gap-2" style={{ fontSize: 'var(--fs-md)' }}><span className="thinking flex items-center gap-1 text-accent"><span /><span /><span /></span> {t('chat.thinking')}</span>
              : <div className="md whitespace-pre-wrap">{renderMd(String(answer).replace(/\s*(⚡|🧠|☁️)\s*$/u, ''))}</div>}
          </div>
        )}
        <div ref={list} className="scroll-thin min-h-0 flex-1 overflow-y-auto py-1.5">
          {items.map((it, i) => {
            const I = it.icon
            const head = it.group !== lastGroup ? (lastGroup = it.group, t(GROUP[it.group])) : null
            return (
              <div key={it.id}>
                {head && <div className="label px-4 pb-1 pt-2.5">{head}</div>}
                <button type="button" data-i={i} onMouseMove={() => sel !== i && setSel(i)} onClick={() => run(it)} title={it.label}
                  aria-selected={i === sel}
                  className={`mx-1.5 flex min-h-[var(--tap)] w-[calc(100%-12px)] items-center gap-3 rounded-xl px-2.5 text-left transition-colors ${i === sel ? 'fill' : ''}`}>
                  <span aria-hidden="true" className={`grid h-6 w-6 shrink-0 place-items-center rounded-md ${i === sel ? 'text-accent' : 'muted'}`}><I size={15} /></span>
                  <span className="min-w-0 flex-1 truncate" style={{ fontSize: 'var(--fs-base)' }}>{it.label}</span>
                  {it.kbd ? <span className="kbd shrink-0">{it.kbd}</span> : <span className="faint shrink-0 truncate" style={{ fontSize: 'var(--fs-xs)' }}>{it.hint}</span>}
                  {i === sel && <CornerDownLeft size={12} className="faint shrink-0" aria-hidden="true" />}
                </button>
              </div>
            )
          })}
          {!items.length && <Empty compact glyph="search" text={t('pal.nothing')} />}
        </div>
        <div className="faint hair flex items-center justify-between gap-3 border-t px-4 py-2" style={{ fontSize: 'var(--fs-xs)' }}>
          <span className="truncate"><span className="kbd">↑↓</span> {t('pal.pick')} · <span className="kbd">↵</span> {t('pal.run')} · <span className="kbd">tab</span> {t('pal.next')}</span>
          <span className="kbd shrink-0">{kb('K')}</span>
        </div>
      </div>
    </div>, document.body)
}