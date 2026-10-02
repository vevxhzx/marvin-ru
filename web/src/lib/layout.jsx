/* Раскладка карточек (bento) на страницах: порядок и ширина.
   Одна логика для «Сегодня», «Задач» и «Финансов» — переключатель «настроить» в шапке,
   стрелки — порядок, кнопка ширины — размер, глаз — спрятать. Хранится в localStorage. */
import { useEffect, useState, useCallback } from 'react'
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
        return { order: order.length ? order : [...ids], widths: { ...defaultWidths, ...(s.widths || {}) } }
      }
    } catch {}
    return { order: [...ids], widths: { ...defaultWidths } }
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
    const next = { ...cur, widths }
    try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch {}
    return next
  }), [storageKey, defaultWidths])

  const reset = useCallback(() => save({ order: [...ids], widths: { ...defaultWidths } }), [save, ids, defaultWidths])

  return { order: state.order, widths: state.widths, setOrder, move, drop, cycleWidth, reset }
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
