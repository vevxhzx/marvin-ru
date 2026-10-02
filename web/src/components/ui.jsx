import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Trash2, Check, CalendarDays, Clock } from 'lucide-react'
import { parseNum } from '../lib/api'
import { ACCENTS, accentFor, usePageAccent, setPageAccent } from '../lib/prefs'
import { useI18n, t as T } from '../lib/i18n'
import { Pressable, useMotionOK } from './Pressable'
import { CountUp, useCountUp } from './CountUp'
import { ErrorState, OfflineState, SuccessState } from './States'
import { PullToRefresh } from './Refresh'
import { useSheetDrag, SHEET_SNAPS, SNAP_RATIO } from '../lib/gestures'

/* Примитивы из соседних файлов re-exportятся здесь, чтобы страницам хватало одного входа */
export { Pressable, CountUp, ErrorState, OfflineState, SuccessState, PullToRefresh }

export function Card({ className = '', variant = '', col = '', i = 0, children, lift, ...p }) {
  const vClass = variant === 'hero' ? 'hero' : variant === 'p1' ? 'p1' : variant === 'p2' ? 'p2' : variant === 'blk' ? 'blk' : variant === 'chart' ? 'chart' : ''
  const colClass = col ? (col.startsWith('s') ? col : `s${col}`) : ''
  return (
    <section className={`c ${vClass} ${colClass} r ${lift ? 'lift' : ''} ${className}`} style={{ '--i': i }} {...p}>
      {children}
    </section>
  )
}

/* Анимированное число: useCountUp живёт в components/CountUp.jsx (общий примитив),
   здесь он остаётся реэкспортом — старый контракт <Num value fmt /> прежний. */
export { useCountUp }

/* Обёртка: <Num value={84007} fmt={money} /> — анимированное число */
export function Num({ value, fmt, className = '' }) {
  const v = useCountUp(typeof value === 'number' ? value : 0)
  const { locale } = useI18n()
  const f = fmt || ((n) => Math.round(n).toLocaleString(locale).replace(/\s/g, '\u00a0'))
  /* tabular-nums: пока число докручивается, цифры не прыгают по ширине */
  return <span className={`n num tnum ${className}`} style={{ fontVariantNumeric: 'tabular-nums' }}>{f(v)}</span>
}

/* Заголовок раздела: компактный, спокойный. idx — счётчик справа от названия.
   hint — текст под заголовком; tip — то же, но в тултипе (для длинных пояснений). */
export function Section({ title, idx, hint, tip, action, children, className = '', i = 0 }) {
  return (
    <section className={`r ${className}`} style={{ '--i': i }}>
      {(title || action) && (
        <div className="mb-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="min-w-0">
            <div className="flex items-baseline gap-2">
              {title && <h2 data-tip={tip} className={`${tip ? 'tip-wide cursor-help underline decoration-dotted decoration-[var(--line-2)] underline-offset-[6px]' : ''} text-[20px] font-semibold tracking-[-0.03em]`}>{title}{tip ? ' ?' : ''}</h2>}
              {idx != null && idx !== 0 && <span className="mono text-[12px] text-accent">{idx}</span>}
            </div>
            {hint && !tip && <div className="muted mt-1 max-w-[520px] text-[13px] leading-snug">{hint}</div>}
          </div>
          {action && <div className="flex items-center gap-2">{action}</div>}
        </div>
      )}
      {children}
    </section>
  )
}

/* Шапка страницы: заголовок + подпись + действия справа */
export function PageHead({ kicker, title, idx, right, children, sub }) {
  return (
    <header className="top r mb-6 sm:mb-8" style={{ '--i': 0 }}>
      <div className="min-w-0">
        {kicker && <div className="mono text-[11px] uppercase tracking-wider text-[var(--ink3)] mb-1">{kicker}</div>}
        <h1 className="text-[34px] sm:text-[44px] font-semibold tracking-[-0.045em] leading-[1.04]">
          {title}{idx != null && idx !== 0 && <span className="mono text-[18px] ml-3 align-middle text-accent">{idx}</span>}
        </h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {right && <div className="hr head-actions">{right}</div>}
      {children}
    </header>
  )
}

/* Пустые состояния: короткий глиф на подложке (не безликая иконка) + строка в тоне
   проекта, пояснение и подсказка-кнопка, которая открывает чат с готовой фразой.
   Шрифты — только по шкале --fs-*, мелкий текст не меньше 12px, подписи --ink-2 (AA). */
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
export function Empty({ icon, glyph, text, sub, hint, onHint, compact, action }) {
  const size = compact ? 34 : 42
  const g = glyph && GLYPHS[glyph]
  return (
    <div className={`empty flex flex-col items-start justify-center ${compact ? 'py-5' : 'py-8 sm:py-10'}`}>
      {(g || icon) && (
        <span
          aria-hidden="true"
          className="empty-plate"
          style={{
            display: 'grid', placeItems: 'center', marginBottom: compact ? 10 : 14,
            width: size + 16, height: size + 16, borderRadius: 'var(--r-md)',
            background: 'var(--sf2)', color: 'var(--ink-3)',
            boxShadow: 'inset 0 0 0 1px var(--line)',
          }}
        >
          {g
            ? <svg width={size} height={size} viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="empty-glyph">{g}</svg>
            : <span style={{ fontSize: size * 0.52, lineHeight: 1 }}>{icon}</span>}
        </span>
      )}
      <div className="h4" style={{ fontSize: 'var(--fs-lg)', maxWidth: '40ch' }}>{text}</div>
      {sub && <div className="muted" style={{ marginTop: 4, fontSize: 'var(--fs-md)', lineHeight: 'var(--lh-snug)', maxWidth: '46ch' }}>{sub}</div>}
      {(hint || action) && (
        <div className="cluster" style={{ marginTop: compact ? 12 : 16 }}>
          {hint && (
            <Pressable
              className="btn-soft btn-sm"
              title={hint}
              onClick={() => (onHint ? onHint(hint) : window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: hint } })))}
            >
              {`«${hint}» `}<span>↗</span>
            </Pressable>
          )}
          {action}
        </div>
      )}
    </div>
  )
}

/* Свайп строки на телефоне: вправо — onRight (выполнить), влево — onLeft (удалить).
   Показывает подложку с иконкой; срабатывает при сдвиге > 88px или быстром флике. */
/* Свайп как в iOS: короткий свайп раскрывает кнопку (удалить / готово), длинный — выполняет сразу.
   Открытая строка одна на всю страницу; тап по строке или в стороне — закрывает. Только touch. */
let _closeOpenSwipe = null
export function Swipe({ children, onLeft, onRight, leftLabel, rightLabel, leftIcon, rightIcon, className = '', disabled }) {
  const { t } = useI18n()
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
    <div ref={box} className={`swipe ${openSide ? 'open' : ''} ${dx !== 0 || flying ? 'active' : ''} ${className}`} onTouchStart={onStart} onTouchMove={onMove} onTouchEnd={onEnd} onTouchCancel={onEnd}>
      {onRight && (
        <div className={`swipe-bg right ${dx > 0 ? 'show' : ''} ${armed && dx > 0 ? 'armed' : ''}`}>
          <button type="button" tabIndex={-1} className="swipe-act" onClick={(e) => { e.stopPropagation(); go('right') }} style={{ width: Math.max(BTN, reveal) }}>
            {RI}<span>{rightLabel || t('common.done')}</span>
          </button>
        </div>
      )}
      {onLeft && (
        <div className={`swipe-bg left ${dx < 0 ? 'show' : ''} ${armed && dx < 0 ? 'armed' : ''}`}>
          <button type="button" tabIndex={-1} className="swipe-act" onClick={(e) => { e.stopPropagation(); go('left') }} style={{ width: Math.max(BTN, reveal) }}>
            {LI}<span>{leftLabel || t('common.delete')}</span>
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
let _uidSeq = 0
const _stack = []
const _stackEv = new EventTarget()

/* фокусируемые элементы внутри шторки: видимые, не disabled, не tabindex=-1 */
const FOCUS_SEL = 'a[href], button, input, select, textarea, [tabindex]'
const focusables = (root) => [...root.querySelectorAll(FOCUS_SEL)].filter((el) =>
  !el.disabled && el.tabIndex >= 0 && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden')

const PHONE = 640                     // ниже — телефон: шторка выезжает снизу
const SHEET_MOTION = 'transform var(--t-base) var(--ease-out), height var(--t-base) var(--ease-out), opacity var(--t-base) linear, filter var(--t-base) linear'

/* размер окна + зум из настроек: высоты снапов считаем в тех же единицах, что и .sheet */
function useViewport() {
  const read = () => {
    const vv = typeof window !== 'undefined' ? window.visualViewport : null
    let z = 1
    try {
      const raw = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ui-zoom'))
      if (Number.isFinite(raw) && raw > 0) z = raw
    } catch { /* без вычисленных стилей — зум 1 */ }
    return {
      w: typeof window !== 'undefined' ? window.innerWidth : 1200,
      h: (vv?.height || (typeof window !== 'undefined' ? window.innerHeight : 800)) / z,
      top: (vv?.offsetTop || 0) / z,
    }
  }
  const [vp, setVp] = useState(read)
  useEffect(() => {
    const on = () => setVp(read())
    window.addEventListener('resize', on)
    window.addEventListener('orientationchange', on)
    window.visualViewport?.addEventListener('resize', on)
    return () => {
      window.removeEventListener('resize', on)
      window.removeEventListener('orientationchange', on)
      window.visualViewport?.removeEventListener('resize', on)
    }
  }, [])
  return vp
}

/* Три точки прилипания телефона — имена и доли высоты живут в lib/gestures.js
   (SHEET_SNAPS / SNAP_RATIO), здесь только пересчёт под размер окна и зум.
   Шаг по точкам и закрытие по скорости делает useSheetDrag оттуда же. */
function useSnaps(phone, vp) {
  return useMemo(() => {
    if (!phone) return []
    const avail = Math.max(240, vp.h - vp.top - 6)
    const half = Math.round(Math.max(avail * SNAP_RATIO.half, 240))
    const px = {
      peek: Math.round(Math.min(Math.max(avail * SNAP_RATIO.peek, 132), half - 80)),
      half,
      full: Math.round(avail * SNAP_RATIO.full),
    }
    const list = SHEET_SNAPS.map((id) => px[id]).sort((a, b) => a - b)
    return list.filter((v, i) => i === 0 || v - list[i - 1] > 24)
  }, [phone, vp.h, vp.top])
}

/* Шторка — единственное окно приложения. Здесь вся разметка и поведение
   (`.sheet-backdrop > .sheet > .sheet-grip`, role=dialog, ловушка фокуса, Esc,
   возврат фокуса, стек окон, блокировка фона), а components/SheetHost.jsx — тонкая
   обёртка над этим компонентом для оболочки: второй реализации нет.

   Высота и сдвиг — обычные инлайновые стили, а переход между ними живёт в CSS
   (SHEET_MOTION). Поэтому у .sheet в index.css НЕТ animation с fill: заполненная
   анимация перебила бы инлайновый transform, и свайп за ручку не двигал бы шторку.
   Свайп, точки прилипания и закрытие по скорости — useSheetDrag из lib/gestures.js. */
export function Sheet({ open, onClose, title, sub, hint, children, wide, snaps: snapProp, footer, bodyClass, ariaLabel }) {
  const { t } = useI18n()
  const [shown, closing] = useSheetPresence(open)
  const idRef = useRef(0)
  const uid = useRef('')
  if (!uid.current) uid.current = `sheet-t${++_uidSeq}`
  const rootRef = useRef(null)
  const sheetRef = useRef(null)
  const bodyRef = useRef(null)
  const prevFocus = useRef(null)
  const [, force] = useState(0)
  const vp = useViewport()
  const phone = vp.w < PHONE
  const snaps = useSnaps(phone && snapProp !== false, vp)
  const [snap, setSnap] = useState(1)
  const [contentH, setContentH] = useState(0)
  const last = Math.max(0, snaps.length - 1)
  const fits = (h) => !snaps.length || h <= snaps[0] + 8     // влезает в свёрнутый — растягивать нечего

  /* высота содержимого меряем по внутреннему блоку, а не по самой шторке: она обрезана
     по max-height, и её scrollHeight всегда равен текущей высоте */
  useLayoutEffect(() => {
    const el = bodyRef.current
    if (!open || !el) return undefined
    const read = () => setContentH(el.scrollHeight)
    read()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [open])

  /* при открытии берём минимальный снап, в который влезает содержимое (один раз за открытие) */
  const pickRef = useRef(false)
  useEffect(() => { if (open) pickRef.current = true }, [open])
  useEffect(() => {
    if (!open || !pickRef.current || !snaps.length || !contentH) return
    pickRef.current = false
    setSnap(fits(contentH) ? 0 : contentH <= snaps[1] ? 1 : last)
  }, [open, contentH, snaps]) // eslint-disable-line

  /* Высота = минимум из «снапа» и «контента»: пустого места снизу не появляется,
     короткая форма не растягивается, а длинная всё равно упирается в потолок шторки. */
  const snapIdx = Math.min(Math.max(snap, 0), last)
  const snapH = snaps[snapIdx] ?? snaps[last] ?? 0
  const prevH = snapIdx > 0 ? (snaps[snapIdx - 1] || 0) : 0
  const height = !snaps.length || !contentH || (snapIdx === 0 && fits(contentH))
    ? undefined
    : Math.min(snapH, Math.max(contentH, prevH))

  useEffect(() => {
    if (!open) return
    const h = (e) => {
      if (_stack[_stack.length - 1] !== idRef.current) return   // ловушку держит только верхняя шторка
      if (e.key === 'Escape') { onClose(); return }
      if (e.key !== 'Tab') return
      const root = rootRef.current
      if (!root) return
      const nodes = focusables(root)
      if (!nodes.length) return
      // циклический Tab/Shift+Tab: фокус не уходит за пределы шторки (D4)
      const idx = nodes.indexOf(document.activeElement)
      if (e.shiftKey) {
        if (idx <= 0) { e.preventDefault(); nodes[nodes.length - 1].focus() }
      } else if (idx === -1 || idx === nodes.length - 1) {
        e.preventDefault(); nodes[0].focus()
      }
    }
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
  // фокус возвращается на вызвавший элемент, если он ещё в DOM
  useEffect(() => {
    if (open) { prevFocus.current = document.activeElement; return }
    const el = prevFocus.current
    prevFocus.current = null
    if (el && el !== document.body && el.isConnected && typeof el.focus === 'function') el.focus()
  }, [open])
  // при открытии фокус заходит внутрь шторки — но только если поле не забрало его на себя
  useEffect(() => {
    if (!open || closing) return
    const root = rootRef.current
    if (!root || root.contains(document.activeElement)) return
    sheetRef.current?.focus({ preventScroll: true })
  }, [open, closing])
  useEffect(() => { const h = () => force((x) => x + 1); _stackEv.addEventListener('change', h); return () => _stackEv.removeEventListener('change', h) }, [])
  // свайп за «ручку»: шторка едет за пальцем между точками прилипания, быстрый флик вниз
  // закрывает, тап по ручке — шаг по точкам. Жест один на всё приложение (lib/gestures.js).
  const drag = useSheetDrag({ open, phone, snaps, snap, setSnap, height, onClose })
  if (!shown) return null
  const behind = open && _stack.length > 1 && _stack[_stack.length - 1] !== idRef.current
  const subText = sub || hint
  const titled = typeof title === 'string' && !!title
  // рисуем в <body>, а не внутри страницы: иначе анимация страницы (transform/filter)
  // превращает position:fixed в «относительно страницы» и окно уезжает
  return createPortal(
    <div ref={rootRef} className={`sheet-backdrop ${closing ? 'closing' : ''} ${behind ? 'behind' : ''}`} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={sheetRef}
        role="dialog" aria-modal="true" tabIndex={-1}
        aria-labelledby={titled ? uid.current : undefined}
        aria-label={ariaLabel || (titled ? title : undefined)}
        data-snap={snaps.length ? String(snap) : undefined}
        className={`sheet ${wide ? 'sm:!max-w-2xl' : ''} ${drag.dragging ? 'sheet-dragging' : ''} ${bodyClass || ''}`}
        style={{
          ...(height != null ? { height: `${height}px` } : null),
          ...(drag.dy ? { transform: `translateY(${drag.dy}px)` } : null),
          ...(drag.dragging ? null : { transition: SHEET_MOTION }),
        }}
      >
        <div className="sheet-grip" aria-hidden="true" {...drag.grip} />
        <div className="mb-5 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="h2" id={titled ? uid.current : undefined}>{title}</h3>
            {subText && <div className="muted" style={{ marginTop: 4, fontSize: 'var(--fs-md)' }}>{subText}</div>}
          </div>
          <Pressable className="btn-icon shrink-0" onClick={onClose} aria-label={t('common.close')} data-tip={t('common.close')} title={t('common.close')}>
            <X size={16} />
          </Pressable>
        </div>
        <div ref={bodyRef} className="sheet-body">{children}</div>
        {footer && <div className="sheet-foot" style={{ marginTop: 16 }}>{footer}</div>}
      </div>
    </div>,
    document.body
  )
}

export function Field({ label, hint, error, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="label">{label}</span>
        {hint && <span className="faint" style={{ fontSize: 'var(--fs-xs)' }}>{hint}</span>}
      </div>
      {children}
      {error && <div className="neg mt-1" style={{ fontSize: 'var(--fs-xs)' }}>{error}</div>}
    </label>
  )
}

/* Нативные date/time-поля показывают формат браузера: в en-US — «09/30/2026 10:30 PM».
   Прячем нативный вид (opacity-0) и показываем свой текст в 24-часовом формате «дд.мм.гггг чч:мм»;
   по клику открываем системный календарь через showPicker() с запасным фокусом. */
const _p2 = (n) => String(n).padStart(2, '0')

function _dtLabel(v) {
  const s = String(v || '')
  const [day, time] = s.split('T')
  if (!day) return ''
  const [y, m, d] = day.split('-')
  return `${d}.${m}.${y}${time ? ` ${time.slice(0, 5)}` : ''}`
}

function _openPicker(ref) {
  const el = ref.current
  if (!el) return
  try { el.showPicker ? el.showPicker() : el.focus() } catch { el.focus() }
}

export function DateTimeField({ value, onChange, required, className = '' }) {
  const { t } = useI18n()
  const ref = useRef(null)
  const label = _dtLabel(value)
  return (
    <div className="dt-field">
      <div className={`input flex items-center justify-between gap-2 pointer-events-none ${className}`}>
        <span className={label ? '' : 'faint'}>{label || t('common.choose_date')}</span>
        <CalendarDays size={16} className="faint shrink-0" />
      </div>
      <input ref={ref} type="datetime-local" value={value || ''} required={required}
        onClick={() => _openPicker(ref)} onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0" />
    </div>
  )
}

export function TimeField({ value, onChange, required, className = '' }) {
  const ref = useRef(null)
  return (
    <div className="dt-field">
      <div className={`input flex items-center justify-between gap-2 pointer-events-none ${className}`}>
        <span className={value ? '' : 'faint'}>{value ? value.slice(0, 5) : '--:--'}</span>
        <Clock size={15} className="faint shrink-0" />
      </div>
      <input ref={ref} type="time" value={value || ''} required={required}
        onClick={() => _openPicker(ref)} onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0" />
    </div>
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
export function Inline({ value, onSave, fmt = (v) => v, min, max, className = '', type = 'num', title }) {
  const { t } = useI18n()
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
      if (Number.isNaN(n)) { setErr(t('common.number')); return }
      if (min != null && n < min) { setErr(`≥ ${fmt(min)}`); return }
      if (max != null && n > max) { setErr(`≤ ${fmt(max)}`); return }
      out = n
    } else if (!String(v).trim()) { setErr(t('common.empty_value')); return }
    if (out === value) { setEdit(false); return }
    try { await onSave(out); setEdit(false) } catch (e) { setErr(e.message || t('common.error')) }
  }
  if (!edit) return <Pressable title={title || t('common.click_to_edit')} onClick={start} className={`editable text-left ${className}`}>{fmt(value)}</Pressable>
  return (
    <span className="relative inline-flex flex-col">
      <input ref={ref} value={v} onChange={(e) => setV(e.target.value)} inputMode={type === 'num' ? 'decimal' : 'text'}
        onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEdit(false) }}
        className={`inline-edit ${className}`} style={{ width: `${Math.max(4, String(v).length + 1)}ch` }} />
      {err && <span className="neg absolute -bottom-4 left-0 whitespace-nowrap" style={{ fontSize: 'var(--fs-xs)' }}>{err}</span>}
    </span>
  )
}

/* Сегменты: настоящие <button type="button"> с aria-pressed — как требует DESIGN.md
   («кликабельные span заменены на кнопки»). Классы .sg и .sg button в index.css
   описаны одинаково, поэтому вид не меняется; font-family — inherit, чтобы
   кнопка не подставила системный шрифт вместо Inter Tight. */
export function Seg({ value, onChange, options, className = '', label }) {
  return (
    <div className={`sg ${className}`} role="group" aria-label={label}>
      {options.map(([v, l]) => (
        <Pressable
          key={v}
          className={v === value ? 'on' : ''}
          aria-pressed={v === value}
          style={{ fontFamily: 'inherit' }}
          onClick={() => onChange(v)}
        >
          {l}
        </Pressable>
      ))}
    </div>
  )
}

export function Pill({ children, warn, className = '', ...p }) {
  return <span className={`pl ${warn ? 'y' : ''} ${className}`} {...p}>{children}</span>
}

/* Строка списка. onClick — это div, а не button: внутрь кладут кнопки (меню, чекбоксы),
   а <button> внутри <button> невалиден. Поэтому роль и клавиатура добавляются вручную. */
export function Rowi({ time, title, sub, right, className = '', onClick }) {
  return (
    <div
      className={`rowi ${onClick ? 'cursor-pointer' : ''} ${className}`}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(e) } } : undefined}
    >
      {time && <time>{time}</time>}
      <div className="t">
        {title}
        {sub && <small>{sub}</small>}
      </div>
      {right}
    </div>
  )
}

export function Bars({ values = [], labels = [], height = 62, className = '' }) {
  const max = Math.max(...values, 1)
  return (
    <div className={className}>
      <div className="bars" style={{ height }}>
        {values.map((v, i) => (
          <i
            key={i}
            className={v ? '' : 'z'}
            style={{
              '--h': `${Math.round((v / max) * 100)}%`,
              '--k': i,
            }}
          />
        ))}
      </div>
      {labels.length > 0 && (
        <div className="bl mono">
          {labels.map((l, i) => <span key={i}>{l}</span>)}
        </div>
      )}
    </div>
  )
}

export function FlowBar({ items = [], note, legend, className = '' }) {
  return (
    <div className={className}>
      <div className="flow">
        {items.map((it, i) => (
          <i key={i} style={{ width: `${it.pct}%`, background: it.color }} title={`${it.label}: ${it.pct}%`} />
        ))}
      </div>
      {(legend || note) && (
        <div className="fl">
          <span>{legend}</span>
          {note && <span>{note}</span>}
        </div>
      )}
    </div>
  )
}

export function Toggle({ on, onChange, label }) {
  return (
    <Pressable
      role="switch"
      aria-checked={!!on}
      aria-label={label}
      className={`tgl ${on ? '' : 'off'}`}
      onClick={() => onChange(!on)}
    />
  )
}

export function Swatch({ color, active, onClick, title, label }) {
  return (
    <button
      type="button"
      style={{ '--c': color }}
      className={active ? 'on' : ''}
      onClick={() => onClick(color)}
      title={title || label || color}
      aria-label={label || title || color}
      aria-pressed={!!active}
    />
  )
}

export function Pills({ value, onChange, options, className = '', label }) {
  return (
    <div className={`flex flex-wrap gap-1.5 ${className}`} role="group" aria-label={label}>
      {options.map(([v, l]) => (
        <Pressable key={v} className={`pill ${v === value ? 'on' : ''}`} aria-pressed={v === value} onClick={() => onChange(v)}>{l}</Pressable>
      ))}
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

/* ---------- уведомления: один глобальный стек (Toaster в App), страницы зовут useToast()/toast() ---------- */
const _toasts = { list: [], subs: new Set(), seq: 0 }
const _emit = () => _toasts.subs.forEach((f) => f([..._toasts.list]))
export function toast(title, { sub, kind = '', ms } = {}) {
  const id = ++_toasts.seq
  _toasts.list = [..._toasts.list.slice(-3), { id, title, sub, kind }]
  _emit()
  setTimeout(() => { _toasts.list = _toasts.list.map((t) => (t.id === id ? { ...t, out: true } : t)); _emit() }, ms || (kind === 'err' ? 4200 : 2600))
  setTimeout(() => { _toasts.list = _toasts.list.filter((t) => t.id !== id); _emit() }, (ms || (kind === 'err' ? 4200 : 2600)) + 240)
  return id
}
export function Toaster() {
  const [list, setList] = useState([])
  useEffect(() => { _toasts.subs.add(setList); return () => _toasts.subs.delete(setList) }, [])
  if (!list.length) return null
  return createPortal(
    <div className="pointer-events-none fixed inset-x-3 top-3 z-[120] flex flex-col items-center gap-2 sm:inset-x-auto sm:bottom-6 sm:right-6 sm:top-auto sm:items-end">
      {list.map((t) => (
        <div key={t.id} className={`toast toast-in ${t.kind} ${t.out ? 'out' : ''}`}>
          <span className="toast-ic">{t.kind === 'err' ? <X size={14} /> : <Check size={14} />}</span>
          <div className="min-w-0">
            <div className="font-medium leading-snug">{t.title}</div>
            {t.sub && <div className="muted mt-0.5 text-[12.5px] leading-snug">{t.sub}</div>}
          </div>
        </div>
      ))}
    </div>,
    document.body
  )
}
/* обратная совместимость: страницы рендерят <Toast {...toast} /> — теперь это ничего не рисует, всё идёт через Toaster */
export function Toast() { return null }
export function useToast() {
  const [t] = useState({ msg: '', kind: '' })
  const show = (msg, kind = '', sub) => { if (msg) toast(msg, { kind: kind === 'err' ? 'err' : kind || 'ok', sub }) }
  show.err = (e) => show(typeof e === 'string' ? e : (e?.message || T('common.error')), 'err')
  return [t, show]
}

/* Переключатель да/нет */
export function Switch({ on, onChange, label }) {
  return (
    <Pressable role="switch" aria-checked={!!on} aria-label={label} className={`switch ${on ? 'on' : ''}`} onClick={() => onChange(!on)} />
  )
}

/* Скелетоны: шимер по --sf2/--fill (тот же, что .animate-pulseSoft), без спиннера.
   Высота задаётся заранее, поэтому контент не «прыгает», когда данные пришли.
   prefers-reduced-motion / «меньше движения» → статичная заливка без блика.
   Скелетон скрыт от скринридера (aria-hidden) — озвучивать мельтешение незачем. */
const SHIMMER = {
  backgroundImage: 'linear-gradient(90deg, var(--fill) 25%, var(--fill-2) 50%, var(--fill) 75%)',
  backgroundSize: '800px 100%',
}
const STILL = { background: 'var(--fill)' }

export function Skeleton({ h = 80, w, radius, className = '', style, children }) {
  const ok = useMotionOK()
  return (
    <div
      aria-hidden="true"
      className={`sk ${className}`}
      style={{
        height: h,
        ...(w ? { width: w } : null),
        borderRadius: radius || 'var(--r-md)',
        ...STILL,
        ...(ok ? { ...SHIMMER, animation: 'shimmer 1.6s linear infinite' } : null),
        ...style,
      }}
    >
      {children}
    </div>
  )
}

/* Скелет списка: N строк высотой как настоящие (--tap + отступ), с аватаром и
   двумя полосами — под основной строкой и под подписью. Ширина полос «честная»:
   меняется по строке, чтобы список не выглядел пустым квадратом. */
export function ListSkeleton({ n = 4, rowH = 52, avatar = true, className = '' }) {
  return (
    <div className={`list-sk space-y-2 py-2 ${className}`} aria-hidden="true" role="presentation">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="flex items-center gap-3" style={{ height: rowH }}>
          {avatar && <Skeleton h={28} w={28} radius="50%" className="shrink-0" />}
          <div className="min-w-0 flex-1">
            <Skeleton h={12} w={`${58 + ((i * 13) % 26)}%`} radius="var(--r-sm)" />
            <Skeleton h={10} w={`${30 + ((i * 7) % 22)}%`} radius="var(--r-sm)" style={{ marginTop: 7, opacity: 0.7 }} />
          </div>
        </div>
      ))}
    </div>
  )
}

/* Подтверждение вместо window.confirm */
export function Confirm({ open, title, text, onOk, onClose, danger }) {
  const { t } = useI18n()
  return (
    <Sheet open={open} onClose={onClose} title={title} snaps={false}>
      {text && <div className="muted mb-5 text-[14px] leading-relaxed">{text}</div>}
      <div className="flex gap-2">
        <Pressable className="btn-ghost flex-1" onClick={onClose}>{t('common.cancel')}</Pressable>
        <Pressable
          className="btn-primary flex-1"
          style={danger ? { background: 'var(--neg)' } : undefined}
          onClick={onOk}
        >
          {t('common.yes')}
        </Pressable>
      </div>
    </Sheet>
  )
}

/* Приоритеты: label — ключ словаря (см. lib/i18n.js) */
export const PRIORITY = { 1: { dot: 'bg-red', label: 'task.prio_high', cls: 'neg' }, 2: { dot: 'bg-orange', label: 'task.prio_normal', cls: 'warn' }, 3: { dot: 'bg-green', label: 'task.prio_low', cls: 'pos' } }

/* Точка приоритета → всплывающий выбор. Рисуется через портал в body: строки задач лежат внутри
   .swipe с overflow:hidden, и обычный absolute-попап там просто обрезался. */
export function PriorityDot({ value, onChange, disabled }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)
  const btn = useRef(null)
  const toggle = () => {
    if (disabled) return
    if (open) return setOpen(false)
    const r = btn.current.getBoundingClientRect()
    const left = Math.min(r.right - 152, window.innerWidth - 160)
    const below = r.bottom + 6 + 120 < window.innerHeight
    setPos({ left: Math.max(8, left), top: below ? r.bottom + 6 : undefined, bottom: below ? undefined : window.innerHeight - r.top + 6 })
    setOpen(true)
  }
  useEffect(() => {
    if (!open) return
    const h = (e) => { if (!btn.current?.contains(e.target) && !e.target.closest?.('[data-pr-menu]')) setOpen(false) }
    const k = (e) => e.key === 'Escape' && setOpen(false)
    const s = () => setOpen(false)
    document.addEventListener('mousedown', h); document.addEventListener('touchstart', h, { passive: true }); document.addEventListener('keydown', k); window.addEventListener('scroll', s, true)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('touchstart', h); document.removeEventListener('keydown', k); window.removeEventListener('scroll', s, true) }
  }, [open])
  return (
    <>
      <button ref={btn} type="button" className="btn-icon !h-7 !w-7" data-tip={open ? undefined : t(PRIORITY[value]?.label)} onClick={toggle} aria-label={t('common.priority')} aria-expanded={open}>
        <span className={`h-2 w-2 rounded-full ${PRIORITY[value]?.dot}`} />
      </button>
      {open && pos && createPortal(
        <div data-pr-menu className="elevated fixed z-[120] w-[152px] !p-1" style={{ left: pos.left, top: pos.top, bottom: pos.bottom, animation: 'rise .16s var(--ease-out)' }}>
          <div className="label px-2.5 pb-1 pt-1.5 !text-[10px]">{t('common.importance')}</div>
          {[1, 2, 3].map((p) => (
            <button key={p} type="button" className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] hover:bg-[var(--fill)] ${p === value ? 'font-medium' : ''}`} onClick={() => { setOpen(false); if (p !== value) onChange(p) }}>
              <span className={`h-2 w-2 rounded-full ${PRIORITY[p].dot}`} />{t(PRIORITY[p].label)}{p === value && <Check size={12} className="ml-auto text-accent" />}
            </button>
          ))}
        </div>, document.body)}
    </>
  )
}

/* Цвет самой вкладки: «заказы» могут быть оранжевыми, «финансы» — зелёными.
   Выбор локальный (только этот браузер), общие настройки сайта не меняются. */
export function PageAccent({ page, className = '' }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)
  const { hex } = usePageAccent(page)
  const wrap = useRef(null)
  const btn = useRef(null)
  const pop = useRef(null)
  const dark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark')

  useEffect(() => {
    if (!open) return
    const h = (e) => { if (wrap.current && !wrap.current.contains(e.target) && !pop.current?.contains(e.target)) setOpen(false) }
    const k = (e) => e.key === 'Escape' && setOpen(false)
    const s = () => setOpen(false)
    document.addEventListener('mousedown', h)
    document.addEventListener('keydown', k)
    window.addEventListener('scroll', s, true)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k); window.removeEventListener('scroll', s, true) }
  }, [open])

  /* Попап рисуем порталом в body и клеим к кнопке: внутри шапки его перекрывало
     поле ввода (у той свой слой на transform/filter), и цвета уходили под карточки. */
  useLayoutEffect(() => {
    if (!open || !pop.current || !btn.current) return
    const r = pop.current.getBoundingClientRect()
    const b = btn.current.getBoundingClientRect()
    const top = b.bottom + 8 + r.height > window.innerHeight - 8 ? Math.max(8, b.top - r.height - 8) : b.bottom + 8
    const left = Math.max(8, Math.min(b.right - r.width, window.innerWidth - r.width - 8))
    setPos((p) => (p && p.top === top && p.left === left ? p : { top, left }))
  }, [open])

  const pick = (c) => { setPageAccent(page, c); setOpen(false) }

  return (
    <span className={`pa-wrap ${className}`} ref={wrap}>
      <button ref={btn} type="button" className={`btn-soft btn-sm ${open ? 'on' : ''}`} onClick={() => setOpen((v) => !v)}
        title={t('page_accent.hint')} aria-haspopup="dialog" aria-expanded={open}>
        <span className="pa-dot" style={{ background: hex || 'var(--acc)' }}></span>
        {t('page_accent.short')}
      </button>
      {open && createPortal(
        <div className="pa-pop elevated" ref={pop} role="dialog" aria-label={t('page_accent.title')}
          style={{ top: pos?.top ?? -9999, left: pos?.left ?? -9999, visibility: pos ? undefined : 'hidden' }}>
          <div className="label">{t('page_accent.title')}</div>
          <div className="pa-grid">
            <button type="button" className={`pa-sw pa-sw-reset ${!hex ? 'pa-sw-on' : ''}`} onClick={() => pick('')}
              title={t('page_accent.as_global')} aria-pressed={!hex}>
              <span>{t('page_accent.as_all')}</span>
            </button>
            {Object.entries(ACCENTS).map(([k, a]) => {
              const raw = dark ? a.dark : a.light
              return (
                <button key={k} type="button" className={`pa-sw ${hex && hex.toLowerCase() === String(raw).toLowerCase() ? 'pa-sw-on' : ''}`}
                  title={t(a.label)} aria-pressed={hex === raw}
                  style={{ background: accentFor(raw, dark) }}
                  onClick={() => pick(raw)} />
              )
            })}
          </div>
          <p className="pa-note">{t('page_accent.note')}</p>
        </div>, document.body)}
    </span>
  )
}
