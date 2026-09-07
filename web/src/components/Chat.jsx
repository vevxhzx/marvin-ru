import { useSheetPresence } from './ui'
import { lower } from '../lib/name'
import { useEffect, useRef, useState } from 'react'
import { ArrowUp, X, Undo2 } from 'lucide-react'
import { api, chatStream } from '../lib/api'
import { useRefresh } from '../App'

const HINTS = ['что сегодня', 'ужин в 7 вечера', 'тренировка каждый пн ср пт в 19', 'потратил 700 на такси', 'перенеси ужин на 8', 'отмена']
const VIA = { rules: '⚡ правила', ollama: '🧠 локально', gemini: '☁️ облако', none: '⚠️' }

const CH = { tg: 'telegram', 'tg-voice': 'telegram 🎙', voice: 'голос', web: 'сайт', system: 'авто' }
const fromServer = (h) => h.map((m) => ({ id: m.id, role: m.role === 'user' ? 'me' : 'bot', text: m.text, channel: m.channel, at: m.at }))

export default function Chat({ open, onClose, seed }) {
  const [msgs, setMsgs] = useState([{ role: 'bot', text: 'Система онлайн, сэр. Слушаю.' }])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef(null)
  const inp = useRef(null)
  const { tick, bump } = useRefresh()

  // одна история с Telegram: подгружаем при открытии и при каждом живом обновлении
  useEffect(() => {
    if (!open) return
    api.chatHistory(40).then((h) => { if (h.length) setMsgs(fromServer(h)) }).catch(() => {})
  }, [open, tick])
  useEffect(() => { box.current?.scrollTo({ top: 1e9, behavior: 'smooth' }) }, [msgs, open])
  useEffect(() => { if (open) setTimeout(() => inp.current?.focus(), 50) }, [open])
  useEffect(() => {
    if (!seed?.text) return
    if (seed.send) { setTimeout(() => send(seed.text), 120); return }
    setQ(seed.text); setTimeout(() => { inp.current?.focus(); inp.current?.select?.() }, 80)
  }, [seed?.n]) // eslint-disable-line
  useEffect(() => {
    if (!open) return
    const h = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [open, onClose])

  const send = async (text) => {
    text = (text ?? q).trim(); if (!text || busy) return
    setQ(''); setMsgs((m) => [...m, { role: 'me', text, channel: 'web' }]); setBusy(true)
    let streamed = false
    try {
      // ответ локальной модели приходит по словам; правила отвечают мгновенно целиком
      const r = await chatStream(text, (piece) => {
        setMsgs((m) => {
          const last = m[m.length - 1]
          if (streamed && last?.streaming) return [...m.slice(0, -1), { ...last, text: last.text + piece }]
          streamed = true
          return [...m, { role: 'bot', text: piece, channel: 'web', streaming: true }]
        })
      })
      setMsgs((m) => (streamed && m[m.length - 1]?.streaming ? m.slice(0, -1) : m).concat({ role: 'bot', text: r.text, via: r.via, channel: 'web' }))
      if (r.actions?.length) bump()
    } catch (e) {
      setMsgs((m) => [...m, { role: 'bot', text: 'Ядро не отвечает. Проверьте, что start.bat запущен, сэр.' }])
    } finally { setBusy(false) }
  }

  const undo = async () => {
    if (busy) return
    setBusy(true)
    try {
      const r = await api.undo()
      setMsgs((m) => [...m, { role: 'bot', text: r.text, via: 'rules', channel: 'web' }])
      if (r.ok) bump()
    } catch {} finally { setBusy(false) }
  }

  const [shown, closing] = useSheetPresence(open)
  if (!shown) return null
  return (
    <div className={`sheet-backdrop ${closing ? 'closing' : ''}`} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel flex h-[88dvh] w-full flex-col !rounded-t-[26px] !rounded-b-none sm:h-[76vh] sm:max-w-lg sm:!rounded-[26px]" style={{ animation: 'rise .3s cubic-bezier(.2,.8,.2,1) both', background: 'var(--bg)' }}>
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <div>
            <div className="h3">{lower()}</div>
            <div className="faint text-[12px]">{busy ? 'печатает…' : 'на связи · история общая с telegram · ⌘K'}</div>
          </div>
          <div className="flex items-center gap-1">
            <button className="btn-icon" onClick={undo} title="Отменить последнее действие"><Undo2 size={17} /></button>
            <button className="btn-icon" onClick={onClose}><X size={18} /></button>
          </div>
        </div>
        <div ref={box} className="scroll-thin flex-1 space-y-2 overflow-y-auto px-4 py-2">
          {msgs.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'me' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-[15px] leading-snug bubble-in ${m.role === 'me' ? 'me rounded-br-md bg-accent text-white' : 'rounded-bl-md'}`}
                style={m.role === 'me' ? {} : { background: 'var(--bubble)' }}>
                {renderMd(m.text.replace(/\s*(⚡|🧠|☁️)\s*$/u, ''))}
                {(m.via || (m.channel && m.channel !== 'web')) && <div className={`mt-1 text-[11px] ${m.role === 'me' ? 'text-white/70' : 'faint'}`}>{[m.via ? VIA[m.via] : null, m.channel && m.channel !== 'web' ? `из ${CH[m.channel] || m.channel}` : null].filter(Boolean).join(' · ')}</div>}
              </div>
            </div>
          ))}
          {busy && !msgs[msgs.length - 1]?.streaming && <div className="flex"><div className="rounded-2xl rounded-bl-md px-4 py-2.5" style={{ background: 'var(--bubble)' }}><Dots /></div></div>}
        </div>
        <div className="px-4 pb-2 pt-1">
          <div className="scroll-thin flex gap-1.5 overflow-x-auto pb-2">
            {HINTS.map((h) => <button key={h} onClick={() => send(h)} className="pill shrink-0">{h}</button>)}
          </div>
          <form onSubmit={(e) => { e.preventDefault(); send() }} className="flex items-center gap-2 pb-2 safe-b">
            <input ref={inp} value={q} onChange={(e) => setQ(e.target.value)} className="input !rounded-full" placeholder="Напишите как в Telegram…" />
            <button type="submit" disabled={!q.trim() || busy} className="btn-primary grid !h-11 !w-11 shrink-0 !rounded-full !p-0"><ArrowUp size={18} /></button>
          </form>
        </div>
      </div>
    </div>
  )
}

function Dots() {
  return (
    <div className="thinking flex items-center gap-1"><span /><span /><span /></div>
  )
}


/* лёгкий markdown для пузырей: **жирный**, *курсив*, `код`; всё остальное — как есть */
function renderMd(text) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`\n]+`|(?<![\w*])\*[^*\n]+\*(?![\w*]))/g)
  return parts.map((p, i) => {
    if (/^\*\*[^*]+\*\*$/.test(p)) return <b key={i} className="font-semibold">{p.slice(2, -2)}</b>
    if (/^`[^`]+`$/.test(p)) return <code key={i} className="mono rounded px-1 text-[13px]" style={{ background: 'color-mix(in srgb, currentColor 10%, transparent)' }}>{p.slice(1, -1)}</code>
    if (/^\*[^*]+\*$/.test(p)) return <i key={i}>{p.slice(1, -1)}</i>
    return p
  })
}
