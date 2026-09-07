import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Trash2, Check } from 'lucide-react'
import { parseNum } from '../lib/api'

export function Card({ className = '', children, lift, ...p }) {
  return <div className={`panel p-5 sm:p-6 ${lift ? 'lift' : ''} ${className}`} {...p}>{children}</div>
}

/* Число, которое «накручивается» до значения при появлении и при изменении */
export function useCountUp(target, { duration = 900 } = {}) {
  const [v, setV] = useState(target)
  const prev = useRef(target)
  useEffect(() => {
    const from = Number.isFinite(prev.current) ? prev.current : 0
    const to = Number.isFinite(target) ? target : 0
    if (from === to) { setV(to); return }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setV(to); prev.current = to; return }
    let raf; const t0 = performance.now()
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / duration)
      const e = 1 - Math.pow(1 - p, 3)
      setV(from + (to - from) * e)
      if (p < 1) raf = requestAnimationFrame(tick); else prev.current = to
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])
  return v
}

/* Обёртка: <Num value={84007} fmt={money} /> — анимированное число */
export function Num({ value, fmt = (n) => Math.round(n).toLocaleString('ru-RU'), className = '' }) {
  const v = useCountUp(typeof value === 'number' ? value : 0)
  return <span className={`num-roll ${className}`}>{fmt(v)}</span>
}

/* Заголовок раздела в духе референса: большой строчный заголовок + моно-индекс + подпись справа */
export function Section({ title, idx, hint, action, children, className = '' }) {
  return (
    <section className={`animate-rise ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="flex items-baseline gap-3">
            {title && <h2 className="h2">{title}</h2>}
            {idx != null && <span className="idx">({String(idx).padStart(2, '0')})</span>}
          </div>
          <div className="flex items-center gap-3">
            {hint && <span className="muted hidden max-w-[320px] text-[13px] leading-snug sm:block">{hint}</span>}
            {action}
          </div>
        </div>
      )}
      {children}
    </section>
  )
}

/* Шапка страницы: огромный заголовок как «видеомонтажёр» */
export function PageHead({ kicker, title, idx, right, children }) {
  return (
    <header className="animate-rise mb-10 sm:mb-14">
      {kicker && <div className="label mb-3">{kicker}</div>}
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <h1 className="h1 max-w-[12ch]">{title}{idx != null && <span className="idx ml-3 align-middle text-[12px]">({String(idx).padStart(2, '0')})</span>}</h1>
        {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
      </div>
      {children}
    </header>
  )
}

/* Пустые состояния: тонкий глиф в стиле сайта + подсказка-кнопка, которая открывает чат с готовой фразой */
const GLYPHS = {
  calendar: <><rect x="6" y="10" width="36" height="32" rx="6" /><path d="M6 20h36M16 6v8M32 6v8" /><circle cx="24" cy="31" r="3" fill="currentColor" stroke="none" /></>,
  tasks: <><path d="M10 14l4 4 8-8" /><path d="M10 26l4 4 8-8" /><path d="M10 38l4 4 8-8" /><path d="M28 14h12M28 26h12M28 38h12" /></>,
  money: <><circle cx="24" cy="24" r="17" /><path d="M24 13v22M19 18h7a4 4 0 010 8h-7M19 30h9" /></>,
  debt: <><path d="M8 36V14a4 4 0 014-4h24a4 4 0 014 4v22" /><path d="M8 20h32" /><path d="M14 30h8" /></>,
  mind: <><path d="M17 40c-6 0-10-4-10-10 0-4 2-7 5-8-1-6 3-11 9-11 2 0 4 1 5 2 1-1 3-2 5-2 6 0 10 5 9 11 3 1 5 4 5 8 0 6-4 10-10 10H17z" /><path d="M24 22v18M19 30l5-4 5 4" /></>,
  memory: <><circle cx="24" cy="24" r="17" /><path d="M24 13v11l7 5" /></>,
  sleep: <><path d="M30 8a16 16 0 1010 24A14 14 0 0130 8z" /></>,
  search: <><circle cx="21" cy="21" r="12" /><path d="M30 30l10 10" /></>,
}
export function Empty({ icon, glyph, text, sub, hint, onHint }) {
  return (
    <div className="empty flex flex-col items-start justify-center py-8 sm:py-10">
      {glyph && GLYPHS[glyph] ? (
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="empty-glyph mb-4">{GLYPHS[glyph]}</svg>
      ) : icon ? <div className="mb-3 text-2xl">{icon}</div> : null}
      <div className="h4">{text}</div>
      {sub && <div className="muted mt-1 text-[14px]">{sub}</div>}
      {hint && <button type="button" className="pill mt-4 !text-[13px]" onClick={() => onHint ? onHint(hint) : window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: hint } }))}>сказать: «{hint}» ↗</button>}
    </div>
  )
}

/* Свайп строки на телефоне: вправо — onRight (выполнить), влево — onLeft (удалить).
   Показывает подложку с иконкой; срабатывает при сдвиге > 88px или быстром флике. */
/* Свайп как в iOS: короткий свайп раскрывает кнопку (удалить / готово), длинный — выполняет сразу.
   Открытая строка одна на всю страницу; тап по строке или в стороне — закрывает. Только touch. */
let _closeOpenSwipe = null
export function Swipe({ children, onLeft, onRight, leftLabel = 'удалить', rightLabel = 'готово', leftIcon, rightIcon, className = '', disabled }) {
  const [dx, setDx] = useState(0)
  const [openSide, setOpenSide] = useState(null)   // 'left' | 'right' | null — кнопка раскрыта
  const [flying, setFlying] = useState(false)
  const st = useRef(null)
  const box = useRef(null)
  const fire = useRef(false)
  const dxRef = useRef(0)
  const BTN = 84
  const fullTh = () => Math.max(150, (box.current?.offsetWidth || 360) * 0.5)
  const setX = (v) => { dxRef.current = v; setDx(v) }

  const close = () => { setOpenSide(null); setX(0); if (_closeOpenSwipe === close) _closeOpenSwipe = null }
  useEffect(() => {
    if (!openSide) return
    const h = (e) => { if (!box.current?.contains(e.target)) close() }
    document.addEventListener('touchstart', h, { passive: true })
    document.addEventListener('scroll', close, { passive: true, capture: true })
    return () => { document.removeEventListener('touchstart', h); document.removeEventListener('scroll', close, { capture: true }) }
  }, [openSide]) // eslint-disable-line
  useEffect(() => () => { if (_closeOpenSwipe === close) _closeOpenSwipe = null }, []) // eslint-disable-line

  const go = (side) => {
    setFlying(true); navigator.vibrate?.(10)
    const w = box.current?.offsetWidth || 400
    setX(side === 'right' ? w + 40 : -(w + 40))
    setTimeout(() => { setOpenSide(null); (side === 'right' ? onRight : onLeft)?.(); setTimeout(() => { setFlying(false); setX(0) }, 60) }, 180)
  }
  const open = (side) => {
    if (_closeOpenSwipe && _closeOpenSwipe !== close) _closeOpenSwipe()
    _closeOpenSwipe = close
    setOpenSide(side); setX(side === 'right' ? BTN : -BTN); navigator.vibrate?.(6)
  }

  const onStart = (e) => {
    if (disabled || flying) return
    const t = e.touches[0]
    st.current = { x: t.clientX, y: t.clientY, t: Date.now(), lock: null, base: dxRef.current }
  }
  const onMove = (e) => {
    if (!st.current) return
    const t = e.touches[0]; const ddx = t.clientX - st.current.x, ddy = t.clientY - st.current.y
    if (st.current.lock == null) { if (Math.abs(ddx) < 6 && Math.abs(ddy) < 6) return; st.current.lock = Math.abs(ddx) > Math.abs(ddy) ? 'x' : 'y' }
    if (st.current.lock !== 'x') return
    let v = st.current.base + ddx
    const allowed = (v > 0 && onRight) || (v < 0 && onLeft)
    if (!allowed) v = v * 0.15
    const th = fullTh()
    // за порогом «полного» свайпа строка идёт с сопротивлением
    if (Math.abs(v) > th) v = Math.sign(v) * (th + (Math.abs(v) - th) * 0.35)
    const armed = Math.abs(v) >= th
    if (armed && !fire.current) { fire.current = true; navigator.vibrate?.(8) }
    if (!armed) fire.current = false
    setX(v)
  }
  const onEnd = () => {
    if (!st.current) return
    const cur = dxRef.current
    const moved = st.current.lock === 'x'
    const dt = Date.now() - st.current.t
    const delta = cur - st.current.base
    const fast = dt < 250 && Math.abs(delta) > 30
    const side = cur > 0 ? 'right' : 'left'
    const can = side === 'right' ? !!onRight : !!onLeft
    st.current = null; fire.current = false
    if (!moved) return
    if (!can) { close(); return }
    if (Math.abs(cur) >= fullTh() || (fast && Math.abs(delta) > 110)) go(side)
    else if (Math.abs(cur) >= BTN * 0.55 || (fast && delta * (side === 'right' ? 1 : -1) > 0)) open(side)
    else close()
  }
  // пока строка раскрыта — тап по ней только закрывает, не открывает форму
  const onClickCapture = (e) => { if (openSide) { e.stopPropagation(); e.preventDefault(); close() } }

  const th = fullTh()
  const armed = Math.abs(dx) >= th && !openSide
  const reveal = Math.abs(dx)
  const LI = leftIcon || <Trash2 size={18} strokeWidth={2.2} />
  const RI = rightIcon || <Check size={18} strokeWidth={2.6} />
  const dragging = !!st.current
  const trans = dragging ? 'none' : flying ? 'transform .2s var(--ease-io)' : 'transform .34s var(--ease-spring)'
  return (
    <div ref={box} className={`swipe ${openSide ? 'open' : ''} ${className}`} onTouchStart={onStart} onTouchMove={onMove} onTouchEnd={onEnd} onTouchCancel={onEnd}>
      {onRight && (
        <div className={`swipe-bg right ${dx > 0 ? 'show' : ''} ${armed && dx > 0 ? 'armed' : ''}`}>
          <button type="button" tabIndex={-1} className="swipe-act" onClick={(e) => { e.stopPropagation(); go('right') }} style={{ width: Math.max(BTN, reveal) }}>
            {RI}<span>{rightLabel}</span>
          </button>
        </div>
      )}
      {onLeft && (
        <div className={`swipe-bg left ${dx < 0 ? 'show' : ''} ${armed && dx < 0 ? 'armed' : ''}`}>
          <button type="button" tabIndex={-1} className="swipe-act" onClick={(e) => { e.stopPropagation(); go('left') }} style={{ width: Math.max(BTN, reveal) }}>
            {LI}<span>{leftLabel}</span>
          </button>
        </div>
      )}
      <div className="swipe-fg" onClickCapture={onClickCapture} style={{ transform: `translateX(${dx}px)`, transition: trans }}>{children}</div>
    </div>
  )
}

/* Шторка остаётся в DOM ещё ~240 мс после закрытия, чтобы успеть уехать вниз */
export function useSheetPresence(open, ms = 240) {
  const [shown, setShown] = useState(open)
  const [closing, setClosing] = useState(false)
  useEffect(() => {
    if (open) { setShown(true); setClosing(false); return }
    if (!shown) return
    setClosing(true)
    const t = setTimeout(() => { setShown(false); setClosing(false) }, ms)
    return () => clearTimeout(t)
  }, [open]) // eslint-disable-line
  return [shown, closing]
}

/* стек открытых шторок: пока есть хоть одна — нижние вкладки спрятаны; верхняя знает, что она верхняя */
let _sheetSeq = 0
const _stack = []
const _stackEv = new EventTarget()
export function Sheet({ open, onClose, title, sub, children, wide }) {
  const [shown, closing] = useSheetPresence(open)
  const idRef = useRef(0)
  const [, force] = useState(0)
  useEffect(() => {
    if (!open) return
    const h = (e) => { if (e.key === 'Escape' && _stack[_stack.length - 1] === idRef.current) onClose() }
    window.addEventListener('keydown', h)
    document.body.style.overflow = 'hidden'
    idRef.current = ++_sheetSeq; _stack.push(idRef.current)
    document.body.classList.add('sheet-open'); _stackEv.dispatchEvent(new Event('change'))
    return () => {
      window.removeEventListener('keydown', h)
      const i = _stack.indexOf(idRef.current); if (i >= 0) _stack.splice(i, 1)
      if (!_stack.length) { document.body.style.overflow = ''; document.body.classList.remove('sheet-open') }
      _stackEv.dispatchEvent(new Event('change'))
    }
  }, [open, onClose])
  useEffect(() => { const h = () => force((x) => x + 1); _stackEv.addEventListener('change', h); return () => _stackEv.removeEventListener('change', h) }, [])
  if (!shown) return null
  const behind = open && _stack.length > 1 && _stack[_stack.length - 1] !== idRef.current
  // рисуем в <body>, а не внутри страницы: иначе анимация страницы (transform/filter)
  // превращает position:fixed в «относительно страницы» и окно уезжает
  return createPortal(
    <div className={`sheet-backdrop ${closing ? 'closing' : ''} ${behind ? 'behind' : ''}`} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`sheet ${wide ? 'sm:!max-w-2xl' : ''}`}>
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 className="h2">{title}</h3>
            {sub && <div className="muted mt-1 text-[13px]">{sub}</div>}
          </div>
          <button className="btn-icon shrink-0" onClick={onClose}><X size={16} /></button>
        </div>
        {children}
      </div>
    </div>,
    document.body
  )
}

export function Field({ label, hint, error, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      <div className="mb-1.5 flex items-baseline justify-between"><span className="label">{label}</span>{hint && <span className="faint text-[11px]">{hint}</span>}</div>
      {children}
      {error && <div className="neg mt-1 text-[12px]">{error}</div>}
    </label>
  )
}

/* Денежное поле: пробелы-разделители, запятая→точка, min/max с подсказкой */
export function Money({ value, onChange, min, max, placeholder = '0', className = '', big, autoFocus, required, suffix = '₽' }) {
  const n = parseNum(value)
  const tooBig = max != null && !Number.isNaN(n) && n > max
  const tooSmall = min != null && !Number.isNaN(n) && n < min
  const bad = tooBig || tooSmall || (value !== '' && Number.isNaN(n))
  return (
    <div className="relative">
      <input inputMode="decimal" autoFocus={autoFocus} required={required}
        className={`input num pr-9 ${big ? '!text-[30px] !font-medium !tracking-tight' : ''} ${bad ? 'err' : ''} ${className}`}
        placeholder={placeholder} value={value}
        onChange={(e) => onChange(e.target.value.replace(/[^\d\s.,\u00a0-]/g, ''))}
        onBlur={() => { if (!Number.isNaN(n)) onChange(n.toLocaleString('ru-RU')) }} />
      <span className={`faint pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 ${big ? 'text-[20px]' : 'text-[14px]'}`}>{suffix}</span>
    </div>
  )
}

/* Число, редактируемое прямо на месте (Enter — сохранить, Esc — отмена) */
export function Inline({ value, onSave, fmt = (v) => v, min, max, className = '', type = 'num', title = 'Нажмите, чтобы изменить' }) {
  const [edit, setEdit] = useState(false)
  const [v, setV] = useState('')
  const [err, setErr] = useState('')
  const ref = useRef(null)
  useEffect(() => { if (edit) { ref.current?.focus(); ref.current?.select() } }, [edit])
  const start = () => { setV(type === 'num' ? String(value ?? '') : (value ?? '')); setErr(''); setEdit(true) }
  const commit = async () => {
    if (!edit) return
    let out = v
    if (type === 'num') {
      const n = parseNum(v)
      if (Number.isNaN(n)) { setErr('число'); return }
      if (min != null && n < min) { setErr(`≥ ${fmt(min)}`); return }
      if (max != null && n > max) { setErr(`≤ ${fmt(max)}`); return }
      out = n
    } else if (!String(v).trim()) { setErr('пусто'); return }
    if (out === value) { setEdit(false); return }
    try { await onSave(out); setEdit(false) } catch (e) { setErr(e.message || 'ошибка') }
  }
  if (!edit) return <button type="button" title={title} onClick={start} className={`editable text-left ${className}`}>{fmt(value)}</button>
  return (
    <span className="relative inline-flex flex-col">
      <input ref={ref} value={v} onChange={(e) => setV(e.target.value)} inputMode={type === 'num' ? 'decimal' : 'text'}
        onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEdit(false) }}
        className={`inline-edit ${className}`} style={{ width: `${Math.max(4, String(v).length + 1)}ch` }} />
      {err && <span className="neg absolute -bottom-4 left-0 whitespace-nowrap text-[11px]">{err}</span>}
    </span>
  )
}

export function Seg({ value, onChange, options }) {
  return (
    <div className="seg">
      {options.map(([v, l]) => (
        <button key={v} type="button" className={v === value ? 'on' : ''} onClick={() => onChange(v)}>{l}</button>
      ))}
    </div>
  )
}

export function Pills({ value, onChange, options, className = '' }) {
  return (
    <div className={`flex flex-wrap gap-1.5 ${className}`}>
      {options.map(([v, l]) => <button type="button" key={v} className={`pill ${v === value ? 'on' : ''}`} onClick={() => onChange(v)}>{l}</button>)}
    </div>
  )
}

export function Stat({ label, value, sub, tone, big }) {
  const color = tone === 'green' ? 'pos' : tone === 'red' ? 'neg' : tone === 'orange' ? 'warn' : tone === 'accent' ? 'accent' : ''
  return (
    <div>
      <div className="label">{label}</div>
      <div className={`num mt-2 leading-none tracking-[-0.04em] ${big ? 'text-[36px] sm:text-[44px]' : 'text-[26px] sm:text-[30px]'} font-medium ${color}`}>{value}</div>
      {sub && <div className="muted mt-1.5 text-[13px]">{sub}</div>}
    </div>
  )
}

/* Анимация ухода элемента перед удалением/выполнением.
   const [leaving, leave] = useLeave(); leave(id, 'done', () => api.delete(id)) → строка уезжает, потом выполняется действие */
export function useLeave(ms = 460) {
  const [map, setMap] = useState({})
  const leave = (id, kind, action) => {
    setMap((m) => ({ ...m, [id]: kind || 'leaving' }))
    return new Promise((res) => setTimeout(async () => {
      try { await action?.() } finally { setMap((m) => { const c = { ...m }; delete c[id]; return c }); res() }
    }, ms))
  }
  const cls = (id) => map[id] === 'done' ? 'leaving-done' : map[id] === 'card' ? 'leaving-card' : map[id] ? 'leaving' : ''
  return [cls, leave]
}

/* Подсветка только что появившихся элементов: сравнивает список id с прошлым рендером */
export function useArrived(ids) {
  const prev = useRef(null)
  const [fresh, setFresh] = useState(new Set())
  useEffect(() => {
    const cur = new Set(ids)
    if (prev.current) {
      const add = [...cur].filter((x) => !prev.current.has(x))
      if (add.length && add.length < 6) { setFresh(new Set(add)); const t = setTimeout(() => setFresh(new Set()), 1500); prev.current = cur; return () => clearTimeout(t) }
    }
    prev.current = cur
  }, [ids.join(',')]) // eslint-disable-line
  return (id) => fresh.has(id) ? 'arrived' : ''
}

/* Кнопка, которая на секунду становится зелёной галочкой после успешного действия */
export function useDoneFlash(ms = 1100) {
  const [on, setOn] = useState(false)
  const flash = () => { setOn(true); setTimeout(() => setOn(false), ms) }
  return [on ? 'btn-done' : '', flash]
}

export function Toast({ msg, kind }) {
  if (!msg) return null
  return createPortal(
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[80] flex justify-center sm:bottom-8">
      <div className={`toast-in max-w-[90vw] rounded-full px-4 py-2.5 text-[14px] font-medium ${kind === 'err' ? 'bg-red text-white' : ''}`} style={kind === 'err' ? {} : { background: 'var(--ink)', color: 'var(--bg)' }}>{msg}</div>
    </div>,
    document.body
  )
}

export function useToast() {
  const [t, setT] = useState({ msg: '', kind: '' })
  const show = (msg, kind = '') => { setT({ msg, kind }); setTimeout(() => setT({ msg: '', kind: '' }), kind === 'err' ? 3800 : 2400) }
  const err = (e) => show(typeof e === 'string' ? e : (e?.message || 'Ошибка'), 'err')
  show.err = err
  return [t, show]
}

export function Skeleton({ h = 80 }) {
  return <div className="fill animate-pulseSoft rounded-2xl" style={{ height: h }} />
}

/* Подтверждение вместо window.confirm */
export function Confirm({ open, title, text, onOk, onClose, danger }) {
  return (
    <Sheet open={open} onClose={onClose} title={title}>
      {text && <div className="muted mb-5 text-[14px] leading-relaxed">{text}</div>}
      <div className="flex gap-2">
        <button className="btn-ghost flex-1" onClick={onClose}>Отмена</button>
        <button className={`btn-primary flex-1 ${danger ? '!bg-red' : ''}`} style={danger ? { background: 'var(--neg)' } : {}} onClick={onOk}>Да</button>
      </div>
    </Sheet>
  )
}

export const PRIORITY = { 1: { dot: 'bg-red', label: 'Важно' }, 2: { dot: 'bg-orange', label: 'Обычная' }, 3: { dot: 'bg-green', label: 'Низкая' } }
