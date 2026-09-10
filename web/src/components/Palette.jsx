import { useEffect, useMemo, useRef, useState } from 'react'
import { dat, gen } from '../lib/name'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Sparkles, Wallet, CalendarDays, CheckSquare, Brain, Settings, Search, MessageCircle, Plus, Moon, Sun, Monitor, Undo2, Gamepad2, BarChart3, Coins, Flame, History, Link2, FileText, CornerDownLeft } from 'lucide-react'
import { api, kb, kbAlt } from '../lib/api'
import { renderMd } from './Chat'

/* ⌘K — командная палитра: страницы, действия, поиск по Мозгу; всё остальное — фраза ассистенту.
   Fuzzy-поиск (подпоследовательность + вхождение), категории, недавние в localStorage, полная навигация с клавиатуры. */
const PAGES = [
  { id: 'p-today', label: 'сегодня', icon: Sparkles, to: '/', get kbd() { return kbAlt('1') } },
  { id: 'p-tasks', label: 'задачи', icon: CheckSquare, to: '/tasks', get kbd() { return kbAlt('2') } },
  { id: 'p-cal', label: 'календарь', icon: CalendarDays, to: '/calendar', get kbd() { return kbAlt('3') } },
  { id: 'p-fin', label: 'финансы', icon: Wallet, to: '/finance', get kbd() { return kbAlt('4') } },
  { id: 'p-mind', label: 'мозг', icon: Brain, to: '/mind', get kbd() { return kbAlt('5') } },
  { id: 'p-mem', label: 'память', icon: History, to: '/memory', get kbd() { return kbAlt('6') } },
  { id: 'p-set', label: 'настройки', icon: Settings, to: '/settings', get kbd() { return kbAlt('7') } },
]
const ACTIONS = [
  { id: 'a-chat', get label() { return `написать ${dat()}…` }, hint: 'чат', icon: MessageCircle, get kbd() { return kb('J') }, run: (c) => c.openChat() },
  { id: 'a-tx', label: 'добавить трату', hint: 'финансы', icon: Plus, run: (c) => c.chat('потратил ') },
  { id: 'a-task', label: 'новая задача', hint: 'задачи', icon: Plus, run: (c) => c.chat('задача: ') },
  { id: 'a-ev', label: 'новая встреча', hint: 'календарь', icon: Plus, run: (c) => c.chat('встреча ') },
  { id: 'a-note', label: 'записать мысль', hint: 'мозг', icon: Plus, run: (c) => c.chat('мысль: ') },
  { id: 'a-fc', label: 'прогноз денег на месяц', hint: 'спросить', icon: BarChart3, run: (c) => c.send('прогноз') },
  { id: 'a-subs', label: 'найти подписки', hint: 'спросить', icon: Coins, run: (c) => c.send('подписки') },
  { id: 'a-streak', label: 'мой стрик', hint: 'спросить', icon: Flame, run: (c) => c.send('стрик') },
  { id: 'a-undo', label: 'отменить последнее действие', hint: 'отмена', icon: Undo2, run: (c) => c.send('отмена') },
  { id: 'a-game', label: 'игровой режим вкл/выкл', hint: 'пк', icon: Gamepad2, run: (c) => c.game() },
  { id: 'a-light', label: 'тема: светлая', hint: 'вид', icon: Sun, run: (c) => c.theme('light') },
  { id: 'a-dark', label: 'тема: тёмная', hint: 'вид', icon: Moon, run: (c) => c.theme('dark') },
  { id: 'a-auto', label: 'тема: как в системе', hint: 'вид', icon: Monitor, run: (c) => c.theme('auto') },
]
const GROUP = { recent: 'недавние', page: 'перейти', action: 'действия', found: 'найдено в мозге', ask: 'спросить' }

const norm = (s) => String(s).toLowerCase().replace(/ё/g, 'е')
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
    send: async (text) => { setBusy(true); setAnswer(null); try { const r = await api.chat(text); setAnswer(r.text) } catch (e) { setAnswer('Ядро не ответило: ' + e.message) } finally { setBusy(false) } },
    game: async () => { setBusy(true); try { const s = await api.status(); const r = await api.post('/api/game', { on: !s.game_mode }); setAnswer(r.text) } catch (e) { setAnswer(e.message) } finally { setBusy(false) } },
    theme: (m) => { setTheme(m); onClose() },
  }), [onClose, openChat, setTheme])

  const all = useMemo(() => [...PAGES.map((p) => ({ ...p, kind: 'page', hint: 'страница' })), ...ACTIONS.map((a) => ({ ...a, label: a.label, kind: 'action' }))], [])
  const items = useMemo(() => {
    const qq = q.trim()
    let out = []
    if (!qq) {
      const rec = recent().map((id) => all.find((x) => x.id === id)).filter(Boolean).map((x) => ({ ...x, group: 'recent' }))
      out = [...rec, ...all.filter((x) => !rec.some((r) => r.id === x.id)).map((x) => ({ ...x, group: x.kind }))]
    } else {
      out = all.map((x) => ({ ...x, group: x.kind, s: Math.max(score(qq, x.label), score(qq, x.hint || '') * 0.5) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s)
      for (const f of found) out.push({ id: `f-${f.kind}-${f.id}`, kind: 'found', group: 'found', label: f.title || f.text || f.url, hint: f.kind === 'note' ? 'заметка' : 'ссылка', icon: f.kind === 'link' ? Link2 : FileText, item: f })
      out.push({ id: 'ask', kind: 'ask', group: 'ask', label: `спросить ${gen()}: «${qq}»`, hint: 'enter', icon: MessageCircle })
    }
    return out.slice(0, 16)
  }, [q, found, all, open])

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
    <div className="fixed inset-0 z-[90] flex items-start justify-center px-3 pt-[10vh] sm:pt-[14vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()} style={{ background: 'rgba(10,10,12,.32)', animation: 'fade .16s ease-out' }}>
      <div className="elevated w-full max-w-[600px] overflow-hidden" style={{ animation: 'rise .22s var(--ease-out)' }} role="dialog" aria-label="Командная палитра">
        <div className="flex items-center gap-3 border-b hair px-4">
          <Search size={16} className="faint shrink-0" />
          <input ref={inp} value={q} onChange={(e) => setQ(e.target.value)} placeholder="куда, что сделать или о чём спросить…" className="h-[52px] w-full bg-transparent text-[15.5px] outline-none placeholder:text-[var(--ink-3)]" />
          <span className="kbd">esc</span>
        </div>
        {(answer || busy) && (
          <div className="border-b hair px-4 py-3 text-[14px] leading-relaxed animate-rise">
            {busy ? <span className="muted flex items-center gap-2 text-[13px]"><span className="thinking flex items-center gap-1 text-accent"><span /><span /><span /></span> думаю…</span>
              : <div className="md whitespace-pre-wrap">{renderMd(String(answer).replace(/\s*(⚡|🧠|☁️)\s*$/u, ''))}</div>}
          </div>
        )}
        <div ref={list} className="scroll-thin max-h-[50vh] overflow-y-auto py-1.5">
          {items.map((it, i) => {
            const I = it.icon
            const head = it.group !== lastGroup ? (lastGroup = it.group, GROUP[it.group]) : null
            return (
              <div key={it.id}>
                {head && <div className="label px-4 pb-1 pt-2.5 !text-[10px]">{head}</div>}
                <button data-i={i} onMouseMove={() => sel !== i && setSel(i)} onClick={() => run(it)}
                  className={`mx-1.5 flex w-[calc(100%-12px)] items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors ${i === sel ? 'fill' : ''}`} style={i === sel ? { background: 'var(--fill)' } : {}}>
                  <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-md ${i === sel ? 'text-accent' : 'muted'}`}><I size={15} /></span>
                  <span className="min-w-0 flex-1 truncate text-[14px]">{it.label}</span>
                  {it.kbd ? <span className="kbd">{it.kbd}</span> : <span className="faint text-[11px]">{it.hint}</span>}
                  {i === sel && <CornerDownLeft size={12} className="faint" />}
                </button>
              </div>
            )
          })}
          {!items.length && <div className="faint px-4 py-6 text-center text-[13px]">ничего не нашёл</div>}
        </div>
        <div className="faint flex items-center justify-between border-t hair px-4 py-2 text-[11px]">
          <span><span className="kbd">↑↓</span> выбрать · <span className="kbd">↵</span> выполнить · <span className="kbd">tab</span> дальше</span><span className="kbd">⌘K</span>
        </div>
      </div>
    </div>, document.body)
}
