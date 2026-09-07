import { useEffect, useMemo, useRef, useState } from 'react'
import { dat, gen } from '../lib/name'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { Sparkles, Wallet, CalendarDays, CheckSquare, Brain, Settings, Search, MessageCircle, Plus, Moon, Sun, Monitor, Undo2, Gamepad2, BarChart3, Coins, Flame } from 'lucide-react'
import { api } from '../lib/api'

/* ⌘K — командная палитра: страницы, быстрые действия, поиск по Мозгу; всё остальное — фраза ассистенту. */
const PAGES = [
  { id: 'p-today', label: 'сегодня', hint: 'страница', icon: Sparkles, to: '/' },
  { id: 'p-fin', label: 'финансы', hint: 'страница', icon: Wallet, to: '/finance' },
  { id: 'p-cal', label: 'календарь', hint: 'страница', icon: CalendarDays, to: '/calendar' },
  { id: 'p-tasks', label: 'задачи', hint: 'страница', icon: CheckSquare, to: '/tasks' },
  { id: 'p-mind', label: 'мозг', hint: 'страница', icon: Brain, to: '/mind' },
  { id: 'p-mem', label: 'память', hint: 'страница', icon: Brain, to: '/memory' },
  { id: 'p-set', label: 'настройки', hint: 'страница', icon: Settings, to: '/settings' },
]
const ACTIONS = [
  { id: 'a-chat', label: `написать ${dat()}…`, hint: 'чат', icon: MessageCircle, run: (c) => c.openChat() },
  { id: 'a-tx', label: 'добавить трату', hint: 'финансы', icon: Plus, run: (c) => c.chat('потратил ') },
  { id: 'a-task', label: 'новая задача', hint: 'задачи', icon: Plus, run: (c) => c.chat('задача: ') },
  { id: 'a-ev', label: 'новая встреча', hint: 'календарь', icon: Plus, run: (c) => c.chat('встреча ') },
  { id: 'a-note', label: 'записать мысль', hint: 'мозг', icon: Plus, run: (c) => c.chat('мысль: ') },
  { id: 'a-fc', label: 'прогноз денег на месяц', hint: 'финансы', icon: BarChart3, run: (c) => c.send('прогноз') },
  { id: 'a-subs', label: 'найти подписки', hint: 'финансы', icon: Coins, run: (c) => c.send('подписки') },
  { id: 'a-streak', label: 'мой стрик', hint: 'мотивация', icon: Flame, run: (c) => c.send('стрик') },
  { id: 'a-undo', label: 'отменить последнее', hint: 'отмена', icon: Undo2, run: (c) => c.send('отмена') },
  { id: 'a-game', label: 'игровой режим вкл/выкл', hint: 'мозг', icon: Gamepad2, run: (c) => c.game() },
  { id: 'a-light', label: 'тема: светлая', hint: 'вид', icon: Sun, run: (c) => c.theme('light') },
  { id: 'a-dark', label: 'тема: тёмная', hint: 'вид', icon: Moon, run: (c) => c.theme('dark') },
  { id: 'a-auto', label: 'тема: как в системе', hint: 'вид', icon: Monitor, run: (c) => c.theme('auto') },
]

const norm = (s) => s.toLowerCase().replace(/ё/g, 'е')
const match = (q, s) => { q = norm(q); s = norm(s); if (!q) return true; let i = 0; for (const ch of s) { if (ch === q[i]) i++; if (i === q.length) return true } return s.includes(q) }

export default function Palette({ open, onClose, openChat, setTheme }) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const [found, setFound] = useState([])
  const [busy, setBusy] = useState(false)
  const [answer, setAnswer] = useState(null)
  const inp = useRef(null)
  const nav = useNavigate()

  useEffect(() => { if (open) { setQ(''); setSel(0); setAnswer(null); setFound([]); setTimeout(() => inp.current?.focus(), 30) } }, [open])
  // поиск по Мозгу с задержкой
  useEffect(() => {
    if (!open || q.trim().length < 3) { setFound([]); return }
    const t = setTimeout(() => api.semantic(q, 5).then((r) => setFound(r.items || [])).catch(() => setFound([])), 220)
    return () => clearTimeout(t)
  }, [q, open])

  const ctx = useMemo(() => ({
    openChat: () => { onClose(); openChat() },
    chat: (text) => { onClose(); window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text } })) },
    send: async (text) => { setBusy(true); try { const r = await api.chat(text); setAnswer(r.text) } catch (e) { setAnswer('Ошибка: ' + e.message) } finally { setBusy(false) } },
    game: async () => { setBusy(true); try { const s = await api.status(); const r = await api.post('/api/game', { on: !s.game_mode }); setAnswer(r.text) } catch (e) { setAnswer(e.message) } finally { setBusy(false) } },
    theme: (m) => { setTheme(m); onClose() },
  }), [onClose, openChat, setTheme])

  const items = useMemo(() => {
    const list = []
    for (const p of PAGES) if (match(q, p.label)) list.push({ ...p, kind: 'page' })
    for (const a of ACTIONS) if (match(q, a.label) || match(q, a.hint)) list.push({ ...a, kind: 'action' })
    for (const f of found) list.push({ id: `f-${f.kind}-${f.id}`, kind: 'found', label: f.title || f.text || f.url, hint: f.kind === 'note' ? 'заметка' : 'ссылка', icon: Search, item: f })
    if (q.trim()) list.push({ id: 'ask', kind: 'ask', label: `спросить ${gen()}: «${q.trim()}»`, hint: 'enter', icon: MessageCircle })
    return list.slice(0, 14)
  }, [q, found])

  useEffect(() => { setSel(0) }, [q])

  const run = (it) => {
    if (!it) return
    if (it.kind === 'page') { nav(it.to); onClose() }
    else if (it.kind === 'action') it.run(ctx)
    else if (it.kind === 'found') { if (it.item.kind === 'link' && it.item.url) window.open(it.item.url, '_blank'); else { nav('/mind'); onClose() } }
    else if (it.kind === 'ask') ctx.send(q.trim())
  }

  useEffect(() => {
    if (!open) return
    const h = (e) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(items.length - 1, s + 1)) }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(0, s - 1)) }
      else if (e.key === 'Enter') { e.preventDefault(); run(items[sel]) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [open, items, sel]) // eslint-disable-line

  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-[90] flex items-start justify-center px-3 pt-[12vh]" onClick={onClose} style={{ background: 'rgba(0,0,0,.28)', backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)', animation: 'fade .18s ease-out' }}>
      <div className="panel w-full max-w-[620px] overflow-hidden !p-0 shadow-2xl" onClick={(e) => e.stopPropagation()} style={{ animation: 'rise .26s cubic-bezier(.2,.8,.2,1)' }}>
        <div className="flex items-center gap-3 border-b hair px-4">
          <Search size={16} className="faint" />
          <input ref={inp} value={q} onChange={(e) => setQ(e.target.value)} placeholder="куда, что сделать или о чём спросить…" className="h-[54px] w-full bg-transparent text-[16px] outline-none placeholder:opacity-40" />
          <span className="chip !py-0.5 !text-[10px]">esc</span>
        </div>
        {answer && (
          <div className="border-b hair px-4 py-3 text-[14px] leading-relaxed animate-rise" style={{ whiteSpace: 'pre-wrap' }}>{answer.replace(/\*\*/g, '')}</div>
        )}
        <div className="max-h-[52vh] overflow-y-auto py-2">
          {busy && <div className="muted px-4 py-2 text-[13px]"><span className="dot-live inline-block h-2 w-2 rounded-full bg-accent" /> думаю…</div>}
          {items.map((it, i) => {
            const I = it.icon
            return (
              <button key={it.id} onMouseEnter={() => setSel(i)} onClick={() => run(it)}
                className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors ${i === sel ? 'bg-accent text-white' : ''}`}>
                <I size={15} className={i === sel ? '' : 'faint'} />
                <span className="min-w-0 flex-1 truncate text-[14px]">{it.label}</span>
                <span className={`text-[11px] ${i === sel ? 'opacity-80' : 'faint'}`}>{it.hint}</span>
              </button>
            )
          })}
          {!items.length && <div className="faint px-4 py-6 text-center text-[13px]">ничего не нашёл</div>}
        </div>
        <div className="faint flex items-center justify-between border-t hair px-4 py-2 text-[11px]">
          <span>↑↓ выбрать · enter выполнить</span><span>⌘K</span>
        </div>
      </div>
    </div>, document.body)
}
