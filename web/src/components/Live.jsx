import { useEffect, useRef, useState } from 'react'
import { lower } from '../lib/name'
import { Mic, MicOff, Square } from 'lucide-react'
import { api } from '../lib/api'
import { useI18n, t as T, SERVER } from '../lib/i18n'

/* Индикатор состояния в шапке: ядро / мозг / ПК-клиент (слушает, думает, говорит) — живёт на SSE pc_state.
   Режим ПК-клиента → ключ словаря; «жду «марвин»» собирается из имени ассистента.
   Цвет — только смысловые токены (--pos/--warn/--neg/--accent/--ink-3), карточка состояния —
   обычная поверхность приложения (--surface-2 + --line), поэтому читается и в светлой теме. */
const PC_MODE_KEY = { listening: 'live.mode_listening', thinking: 'live.mode_thinking', speaking: 'live.mode_speaking', off: 'live.mode_mic_off' }
const pcLabel = (mode) => (mode === 'idle' ? T('live.mode_idle', { name: lower() }) : (PC_MODE_KEY[mode] ? T(PC_MODE_KEY[mode]) : mode))

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
  const { t } = useI18n()
  const busy = live.pc?.alive && ['listening', 'thinking', 'speaking'].includes(live.pc.mode)
  const c = live.core === 'wait' ? 'var(--ink-3)' : live.core === 'down' ? 'var(--neg)' : busy ? 'var(--pos)' : live.brain ? 'var(--accent)' : 'var(--warn)'
  const tip = live.core === 'wait' ? t('live.connecting') : live.core === 'down' ? t('live.core_offline') : busy ? t('live.pc', { mode: pcLabel(live.pc.mode) }) : live.brain ? t('live.brain_online') : t('live.rules_only')
  return (
    <button type="button" onClick={onClick} data-tip={tip} aria-label={tip} title={tip}
      className="relative -m-1.5 grid h-8 w-8 place-items-center transition-transform active:scale-95">
      <span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full ${live.core === 'ok' ? 'dot-live' : ''}`} style={{ background: c, color: c }} />
      {busy && <span aria-hidden="true" className="absolute inset-1 rounded-full border" style={{ borderColor: c, animation: 'breathe 1.2s ease-in-out infinite' }} />}
    </button>
  )
}

/* Всплывающая карточка состояния при клике на точку. place — позиция от вызывающего (сайдбар/шапка). */
export function LivePopover({ live, onClose, place = "absolute left-0 top-[46px]" }) {
  const { t } = useI18n()
  const pc = live.pc
  const [st, setSt] = useState(null)
  useEffect(() => { api.get('/api/state').then(setSt).catch(() => setSt(null)) }, [])
  const PRES = { active: 'live.at_pc', idle: 'live.stepped_away', away: 'live.long_gone', offline: 'live.pc_offline' }
  return (
    <div
      className={`${place} elevated z-[100] w-[300px] max-w-[calc(100vw-24px)] !p-3.5`}
      style={{ fontSize: 'var(--fs-md)', animation: 'rise .2s var(--ease-out)' }}
      role="dialog"
      aria-label={t('live.core')}
      onMouseLeave={onClose}
    >
      <Row ok={live.core === 'ok'} label={t('live.core')} val={live.core === 'ok' ? t('live.online') : live.core === 'down' ? t('live.no_answer') : '…'} />
      <Row ok={live.brain} label={t('live.local_brain')} val={live.brain ? t('live.online') : t('live.asleep')} />
      <Row ok={!!pc?.alive} label={t('live.pc_client')} val={pc?.alive ? pcLabel(pc.mode) : t('live.offline')} />
      {pc?.alive && pc.text && <div className="muted mt-1 truncate pl-5" style={{ fontSize: 'var(--fs-xs)' }}>{pc.text}</div>}
      {st && st.presence !== 'offline' && (
        <div className="mt-2.5 rule pt-2.5">
          <Row ok={st.presence === 'active'} label={t('live.you')} val={`${t(PRES[st.presence])}${st.presence === 'active' && st.session_min != null ? ` · ${fmtMin(st.session_min)}` : st.presence_min ? ` · ${fmtMin(st.presence_min)}` : ''}`} />
          {st.presence === 'active' && st.app && <div className="muted truncate pl-5" style={{ fontSize: 'var(--fs-xs)' }}>{st.cat === SERVER.live_cat_browser.ru ? t('live.browser') : st.app}{st.act_min ? ` · ${fmtMin(st.act_min)}` : ''}{st.heavy?.length ? ` · ${t('live.render', { what: st.heavy.join(', ') })}` : ''}</div>}
          {st.jobs?.length > 0 && <div className="muted truncate pl-5" style={{ fontSize: 'var(--fs-xs)' }}>{t('live.bg')}: {st.jobs.map((j) => `${j.name} ${Math.round((j.progress || 0) * 100)}%`).join(', ')}</div>}
          {st.pending && <div className="warn truncate pl-5" style={{ fontSize: 'var(--fs-xs)' }}>{st.pending}</div>}
          <div className="faint pl-5" style={{ fontSize: 'var(--fs-xs)' }}>{t('live.budget_left', { n: st.budget_left })}{st.deferred ? ` · ${t('live.deferred', { n: st.deferred })}` : ''}</div>
        </div>
      )}
    </div>
  )
}
const fmtMin = (m) => (m < 60 ? `${m} ${T('unit.min')}` : `${Math.floor(m / 60)} ${T('unit.hour')} ${String(m % 60).padStart(2, '0')}`)
const Row = ({ ok, label, val }) => (
  <div className="flex items-center gap-2 py-1" style={{ minHeight: 'var(--tap-sm)' }}>
    <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: ok ? 'var(--pos)' : 'var(--ink-3)' }} />
    <span className="muted">{label}</span><span className="ml-auto min-w-0 truncate pl-3 text-right font-medium">{val}</span>
  </div>
)

/* Микрофон на сайте: Web Speech API браузера (Chrome/Edge). Распознанный текст → в чат ассистенту. */
export function MicButton({ onText, className = '' }) {
  const { t, locale } = useI18n()
  const SR = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)
  const [on, setOn] = useState(false)
  const [interim, setInterim] = useState('')
  const rec = useRef(null)
  if (!SR) return null
  const start = () => {
    const r = new SR(); r.lang = locale; r.interimResults = true; r.maxAlternatives = 1
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
      <button type="button" onClick={on ? stop : start} className={`btn-icon ${on ? '!bg-red !text-white' : ''}`}
        data-tip={on ? t('live.stop') : t('live.speak')} aria-label={t('live.voice_input')} title={on ? t('live.stop') : t('live.speak')}>
        {on ? <Square size={13} /> : <Mic size={15} />}
      </button>
      {on && <span aria-hidden="true" className="absolute inset-0 rounded-full border-2" style={{ borderColor: 'var(--neg)', animation: 'breathe 1s ease-in-out infinite' }} />}
      {on && interim && <span className="elevated absolute right-0 top-11 z-[70] max-w-[280px] trunc !px-3 !py-1.5" style={{ fontSize: 'var(--fs-xs)' }}>{interim}</span>}
    </span>
  )
}

export function MicOffIcon() { return <MicOff size={15} /> }