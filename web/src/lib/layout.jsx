/* Раскладка карточек (bento) на страницах: порядок и ширина.
   Одна логика для «Сегодня», «Задач» и «Финансов» — переключатель «настроить» в шапке,
   стрелки — порядок, кнопка ширины — размер, глаз — спрятать. Хранится в localStorage. */
import { useEffect, useState, useCallback, useRef } from 'react'
import { t } from './i18n'

export const COLS = [3, 4, 6, 8, 12]
const WIDTH_LABEL = { 3: 'layout.w3', 4: 'layout.w4', 6: 'layout.w6', 8: 'layout.w8', 12: 'layout.w12' }
export const widthLabel = (n) => t(WIDTH_LABEL[n] || 'layout.w4')

/** страница широкая (≥1061px): там имеет смысл задавать ширину вручную,
    на планшете и телефоне карточки и так подстраиваются под экран */
export function useWide() {
  const [wide, setWide] = useState(() => typeof matchMedia === 'function' && matchMedia('(min-width: 1061px)').matches)
  useEffect(() => {
    if (typeof matchMedia !== 'function') return
    const mq = matchMedia('(min-width: 1061px)')
    const h = () => setWide(mq.matches)
    h(); mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [])
  return wide
}

export function useCardLayout(key, ids, defaultWidths = {}) {
  const storageKey = `marvin.layout.${key}`
  const [state, setState] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem(storageKey) || 'null')
      // порядок сохраняется как есть: спрятанные карточки остаются спрятанными,
      // новые id подмешиваем только если сохранённого списка вообще нет
      if (s && Array.isArray(s.order)) {
        const order = s.order.filter((x) => ids.includes(x))
        return { order: order.length ? order : [...ids], widths: { ...defaultWidths, ...(s.widths || {}) }, touched: s.touched || {} }
      }
    } catch {}
    return { order: [...ids], widths: { ...defaultWidths }, touched: {} }
  })
  const save = useCallback((next) => {
    setState(next)
    try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch {}
  }, [storageKey])

  const setOrder = useCallback((v) => setState((cur) => {
    const order = typeof v === 'function' ? v(cur.order) : v
    const next = { ...cur, order }
    try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch {}
    return next
  }), [storageKey])

  /** сдвинуть на позицию: dir = -1/1 — влево-вправо в списке */
  const move = useCallback((id, dir) => setState((cur) => {
    const i = cur.order.indexOf(id), j = i + dir
    if (i < 0 || j < 0 || j >= cur.order.length) return cur
    const order = [...cur.order]
    ;[order[i], order[j]] = [order[j], order[i]]
    const next = { ...cur, order }
    try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch {}
    return next
  }), [storageKey])

  /** бросить one на место two (перетаскивание мышью) */
  const drop = useCallback((from, to) => setState((cur) => {
    const i = cur.order.indexOf(from), j = cur.order.indexOf(to)
    if (i < 0 || j < 0 || i === j) return cur
    const order = [...cur.order]
    order.splice(i, 1); order.splice(j, 0, from)
    const next = { ...cur, order }
    try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch {}
    return next
  }), [storageKey])

  /** следующий размер карточки по кругу */
  const cycleWidth = useCallback((id) => setState((cur) => {
    const curW = cur.widths[id] || defaultWidths[id] || 4
    const at = COLS.indexOf(curW)
    const widths = { ...cur.widths, [id]: COLS[(at < 0 ? 1 : at + 1) % COLS.length] }
    const next = { ...cur, widths, touched: { ...cur.touched, [id]: true } }
    try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch {}
    return next
  }), [storageKey, defaultWidths])

  /** задать ширину явно (жест «зажать и потянуть») */
  const setWidth = useCallback((id, w) => setState((cur) => {
    if (!COLS.includes(w)) return cur
    const next = { ...cur, widths: { ...cur.widths, [id]: w }, touched: { ...cur.touched, [id]: true } }
    try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch {}
    return next
  }), [storageKey])

  const reset = useCallback(() => save({ order: [...ids], widths: { ...defaultWidths }, touched: {} }), [save, ids, defaultWidths])

  return { order: state.order, widths: state.widths, touched: state.touched || {}, setOrder, move, drop, cycleWidth, setWidth, reset }
}

const HOLD_MS = 350
const HOLD_SLOP = 10
const INTERACTIVE = 'button,a,input,select,textarea,label,summary,[role="button"],[contenteditable="true"]'
const LIFT = {
  transform: 'scale(1.015)',
  boxShadow: '0 18px 48px rgba(0,0,0,.28)',
  outline: '2px solid var(--accent, currentColor)',
  zIndex: 40,
  cursor: 'ew-resize',
  userSelect: 'none',
  transition: 'transform .15s ease, box-shadow .15s ease',
}

/** ближайший предок с реальной боксовой моделью (display:contents его пропускаем) */
function gridOf(el) {
  let p = el.parentElement
  while (p && p.getBoundingClientRect().width === 0) p = p.parentElement
  return p
}

/** Зажать карточку на ~350мс и тянуть вправо-влево: ширина меняется вживую (превью),
    привязываясь к COLS; отпустить — сохранить, Esc / pointercancel — вернуть как было.
    Если сдвинуться раньше срабатывания удержания — всё остаётся как раньше (перетаскивание).
    Страница вешает rs.bind(id, w) на контейнер карточки (обработчики + style подъёма),
    а ширину берёт из rs.widthOf(id, w), чтобы видеть превью. Ширина тянется от текущей
    на сдвиг указателя по X. Работает только в 12-колоночной сетке (на телефоне — нет). */
export function usePressResize({ enabled, setWidth }) {
  const [live, setLive] = useState(null)
  const ses = useRef(null)
  const setWidthRef = useRef(setWidth)
  setWidthRef.current = setWidth

  const end = useCallback((commit) => {
    const s = ses.current
    if (!s) return
    ses.current = null
    clearTimeout(s.timer)
    if (s.cleanup) s.cleanup()
    if (s.active) {
      try { s.el.releasePointerCapture(s.pid) } catch {}
      if (commit && s.w !== s.w0) setWidthRef.current(s.id, s.w)
      // отпускание после жеста не должно кликнуть по содержимому карточки
      const stop = (e) => { e.stopPropagation(); e.preventDefault() }
      window.addEventListener('click', stop, { capture: true, once: true })
      setTimeout(() => window.removeEventListener('click', stop, { capture: true }), 80)
    }
    setLive(null)
  }, [])

  useEffect(() => { if (!enabled) end(false) }, [enabled, end])
  useEffect(() => () => end(false), [end])

  const begin = useCallback((s) => {
    const grid = gridOf(s.el)
    if (!grid) { end(false); return }
    const cs = getComputedStyle(grid)
    const tracks = (cs.gridTemplateColumns || '').split(' ').filter(Boolean).length
    if (cs.display !== 'grid' || tracks !== 12) { end(false); return }   // телефон / не 12-колоночная сетка
    const gap = parseFloat(cs.columnGap) || 0
    const inner = grid.getBoundingClientRect().width - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0)
    s.step = (inner - gap * 11) / 12 + gap
    s.gap = gap
    s.px0 = s.el.getBoundingClientRect().width
    s.active = true
    try { s.el.setPointerCapture(s.pid) } catch {}
    const prevent = (e) => e.preventDefault()
    const onKey = (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); end(false) } }
    s.el.addEventListener('dragstart', prevent)
    s.el.addEventListener('contextmenu', prevent)
    s.el.addEventListener('touchmove', prevent, { passive: false })
    window.addEventListener('keydown', onKey, true)
    s.cleanup = () => {
      s.el.removeEventListener('dragstart', prevent)
      s.el.removeEventListener('contextmenu', prevent)
      s.el.removeEventListener('touchmove', prevent)
      window.removeEventListener('keydown', onKey, true)
    }
    setLive({ id: s.id, w: s.w })
  }, [end])

  const bind = useCallback((id, w0) => {
    if (!enabled) return {}
    const active = live && live.id === id
    return {
      onPointerDown: (e) => {
        if (ses.current || (e.pointerType === 'mouse' && e.button !== 0)) return
        if (e.target.closest && e.target.closest(INTERACTIVE)) return
        const s = { id, el: e.currentTarget, pid: e.pointerId, x0: e.clientX, y0: e.clientY, w0, w: w0, active: false }
        s.timer = setTimeout(() => begin(s), HOLD_MS)
        ses.current = s
      },
      onPointerMove: (e) => {
        const s = ses.current
        if (!s || s.pid !== e.pointerId) return
        if (!s.active) {
          if (Math.hypot(e.clientX - s.x0, e.clientY - s.y0) > HOLD_SLOP) end(false)
          return
        }
        const cols = (s.px0 + (e.clientX - s.x0) + s.gap) / s.step
        const w = COLS.reduce((best, c) => (Math.abs(c - cols) < Math.abs(best - cols) ? c : best), COLS[0])
        if (w !== s.w) { s.w = w; setLive({ id: s.id, w }) }
      },
      onPointerUp: (e) => { if (ses.current && ses.current.pid === e.pointerId) end(true) },
      onPointerCancel: (e) => { if (ses.current && ses.current.pid === e.pointerId) end(false) },
      onLostPointerCapture: (e) => { if (ses.current && ses.current.pid === e.pointerId) end(false) },
      'data-resizing': active ? 'true' : undefined,
      style: active ? LIFT : undefined,
    }
  }, [enabled, live, begin, end])

  /** ширина с учётом превью: пока тянем — живая, иначе сохранённая */
  const widthOf = (id, w) => (live && live.id === id ? live.w : w)
  return { bind, widthOf, live }
}

/** Стрелки порядка + кнопка ширины + «спрятать». Показываются только в режиме правки. */
export function CardCtl({ id, order, edit, onMove, onHide, onWidth, width, wide, Icon, HideIcon }) {
  if (!edit) return null
  const i = order.indexOf(id)
  const Btn = ({ children, ...p }) => (
    <button type="button" className="p-1 rounded-full text-[var(--ink2)] hover:text-[var(--ink)] hover:bg-[var(--sf2)] disabled:opacity-30 transition" {...p}>{children}</button>
  )
  return (
    <div className="absolute top-3 right-3 z-30 flex items-center gap-1 rounded-full p-1 bg-[var(--sf)] shadow-md border border-[var(--line)]"
      onPointerDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
      <Btn disabled={i <= 0} onClick={() => onMove(id, -1)} title={t('layout.move_up')}><Icon size={14} /></Btn>
      <Btn disabled={i < 0 || i >= order.length - 1} onClick={() => onMove(id, 1)} title={t('layout.move_down')}><Icon size={14} className="rotate-180" /></Btn>
      {wide && onWidth && <Btn onClick={() => onWidth(id)} title={t('layout.width_hint', { w: widthLabel(width) })}><span className="mono text-[11px] px-0.5">{width}</span></Btn>}
      {onHide && <Btn className="!text-[var(--neg)]" onClick={() => onHide(id)} title={t('layout.hide_card')}><HideIcon size={14} /></Btn>}
    </div>
  )
}
