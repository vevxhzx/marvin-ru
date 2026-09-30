// Звук окончания помодоро в браузере — WebAudio, без файлов и библиотек.
// bell — три мягких удара, ding — один короткий, tick — быстрые щелчки, off — тишина.
// Браузер разрешает звук только после первого клика на странице — «разогреваем» контекст на pointerdown.
let ctx = null
const getCtx = () => {
  if (typeof window === 'undefined') return null
  const AC = window.AudioContext || window.webkitAudioContext
  if (!AC) return null
  if (!ctx) ctx = new AC()
  if (ctx.state === 'suspended') ctx.resume().catch(() => {})
  return ctx
}
if (typeof window !== 'undefined') window.addEventListener('pointerdown', () => getCtx(), { passive: true, once: true })

function note(ac, freq, at, dur, vol, type = 'sine') {
  const o = ac.createOscillator(), g = ac.createGain()
  o.type = type; o.frequency.value = freq
  g.gain.setValueAtTime(0.0001, at)
  g.gain.exponentialRampToValueAtTime(vol, at + 0.012)
  g.gain.exponentialRampToValueAtTime(0.0001, at + dur)
  o.connect(g).connect(ac.destination)
  o.start(at); o.stop(at + dur + 0.05)
}

export function playChime(kind = 'bell', volume = 0.6) {
  if (kind === 'off') return
  const ac = getCtx()
  if (!ac) return
  const v = Math.max(0.02, Math.min(1, Number(volume) || 0.6)) * 0.5
  const t = ac.currentTime + 0.02
  if (kind === 'ding') note(ac, 1320, t, 0.45, v)
  else if (kind === 'tick') { for (let i = 0; i < 6; i++) note(ac, 2000, t + i * 0.13, 0.05, v, 'square') }
  else { note(ac, 880, t, 0.6, v); note(ac, 1100, t + 0.55, 0.6, v); note(ac, 1320, t + 1.1, 1.0, v) }
  try { navigator.vibrate?.(kind === 'tick' ? [40, 60, 40, 60, 40] : [120, 80, 120]) } catch {}
}

const LAST = new Map()
/* SSE `timer` с done=true: сигнал один раз на сессию (несколько вкладок звонят каждая — как будильник в каждой комнате, это ок) */
export function chimeFromEvent(ev) {
  if (!ev || ev.kind !== 'timer' || !ev.done) return
  const key = String(ev.session_id || ev.text || Date.now())
  if (LAST.get(key) > Date.now() - 30_000) return
  LAST.set(key, Date.now())
  playChime(ev.sound || 'bell', ev.volume ?? 0.6)
}
