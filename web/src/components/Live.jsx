import { useEffect, useRef, useState } from 'react'
import { lower } from '../lib/name'
import { Mic, MicOff, Square } from 'lucide-react'
import { api } from '../lib/api'

/* Индикатор состояния в шапке: ядро / мозг / ПК-клиент (слушает, думает, говорит) — живёт на SSE pc_state. */
const PC_LABEL = { get idle() { return `жду «${lower()}»` }, listening: 'слушаю', thinking: 'думаю', speaking: 'говорю', off: 'микрофон выключен' }

export function useLive(health) {
  const [pc, setPc] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () => api.get('/api/pc/state').then((s) => alive && setPc(s)).catch(() => {})
    load(); const t = setInterval(load, 25000)
    const h = (e) => { const d = e.detail; if (d?.kind === 'pc_state') setPc((p) => ({ ...(p || {}), alive: true, mode: d.mode, text: d.text })) }
    window.addEventListener('assistant:event', h)
    return () => { alive = false; clearInterval(t); window.removeEventListener('assistant:event', h) }
  }, [])
  const core = !health ? 'wait' : !health.ok ? 'down' : 'ok'
  return { core, brain: !!health?.ollama, pc }
}

export function LiveDot({ live, onClick }) {
  const busy = live.pc?.alive && ['listening', 'thinking', 'speaking'].includes(live.pc.mode)
  const c = live.core === 'wait' ? 'var(--ink-3)' : live.core === 'down' ? 'var(--neg)' : busy ? 'var(--green, #30d158)' : live.brain ? 'var(--accent)' : 'var(--warn)'
  const t = live.core === 'wait' ? 'подключение…' : live.core === 'down' ? 'ядро офлайн' : busy ? `ПК: ${PC_LABEL[live.pc.mode]}` : live.brain ? 'мозг онлайн' : 'только правила'
  return (
    <button onClick={onClick} title={t} className="relative grid h-5 w-5 place-items-center">
      <span className={`inline-block h-2 w-2 rounded-full ${live.core === 'ok' ? 'dot-live' : ''}`} style={{ background: c, color: c }} />
      {busy && <span className="absolute inset-0 rounded-full border" style={{ borderColor: c, animation: 'breathe 1.2s ease-in-out infinite' }} />}
    </button>
  )
}

/* Всплывающая карточка состояния при клике на точку */
export function LivePopover({ live, onClose }) {
  const pc = live.pc
  return (
    <div className="panel absolute left-0 top-[46px] z-[70] w-[280px] !p-3 text-[13px] shadow-xl" style={{ animation: 'rise .22s cubic-bezier(.2,.8,.2,1)' }} onMouseLeave={onClose}>
      <Row ok={live.core === 'ok'} label="ядро" val={live.core === 'ok' ? 'онлайн' : live.core === 'down' ? 'не отвечает' : '…'} />
      <Row ok={live.brain} label="локальный мозг" val={live.brain ? 'онлайн' : 'спит / не запущен'} />
      <Row ok={!!pc?.alive} label="ПК-клиент (voice.bat)" val={pc?.alive ? PC_LABEL[pc.mode] || pc.mode : 'не на связи'} />
      {pc?.alive && pc.text && <div className="muted mt-1 truncate pl-4 text-[12px]">{pc.text}</div>}
    </div>
  )
}
const Row = ({ ok, label, val }) => (
  <div className="flex items-center gap-2 py-1">
    <span className="h-1.5 w-1.5 rounded-full" style={{ background: ok ? 'var(--accent)' : 'var(--ink-3)' }} />
    <span className="muted">{label}</span><span className="ml-auto font-medium">{val}</span>
  </div>
)

/* Микрофон на сайте: Web Speech API браузера (Chrome/Edge). Распознанный текст → в чат ассистенту. */
export function MicButton({ onText, className = '' }) {
  const SR = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)
  const [on, setOn] = useState(false)
  const [interim, setInterim] = useState('')
  const rec = useRef(null)
  if (!SR) return null
  const start = () => {
    const r = new SR(); r.lang = 'ru-RU'; r.interimResults = true; r.maxAlternatives = 1
    let finalText = ''
    r.onresult = (e) => {
      let s = ''
      for (let i = e.resultIndex; i < e.results.length; i++) { if (e.results[i].isFinal) finalText += e.results[i][0].transcript; else s += e.results[i][0].transcript }
      setInterim(s || finalText)
    }
    r.onend = () => { setOn(false); setInterim(''); const t = finalText.trim(); if (t) onText(t) }
    r.onerror = () => { setOn(false); setInterim('') }
    rec.current = r; r.start(); setOn(true)
  }
  const stop = () => rec.current?.stop()
  return (
    <span className={`relative inline-flex items-center ${className}`}>
      <button onClick={on ? stop : start} className={`btn-icon !h-9 !w-9 ${on ? '!bg-red !text-white' : ''}`} title={on ? 'Остановить' : 'Сказать голосом (микрофон браузера)'}>
        {on ? <Square size={13} /> : <Mic size={15} />}
      </button>
      {on && <span className="absolute inset-0 rounded-full border-2" style={{ borderColor: 'var(--neg)', animation: 'breathe 1s ease-in-out infinite' }} />}
      {on && interim && <span className="panel absolute right-0 top-11 z-[70] max-w-[280px] truncate !px-3 !py-1.5 text-[12px] shadow-lg">{interim}</span>}
    </span>
  )
}

export function MicOffIcon() { return <MicOff size={15} /> }
