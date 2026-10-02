// Кнопка «⋯» с выпадающим меню действий. Рисуем порталом в body: строка заказа лежит
// внутри .swipe с overflow:hidden, и обычный absolute-попап там обрезался (см. PriorityDot в ui.jsx).
// Все пункты — с ТЕКСТОВЫМИ подписями: в меню нет безымянных иконок.
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MoreHorizontal } from 'lucide-react'
import { useI18n } from '../lib/i18n'

export default function MenuButton({ items, ariaLabel, tip, align = 'right', className = '', onOpen }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)
  const btn = useRef(null)
  const pop = useRef(null)

  const toggle = () => {
    if (open) return setOpen(false)
    const r = btn.current.getBoundingClientRect()
    const w = 232
    const left = align === 'right' ? Math.min(r.right - w, window.innerWidth - w - 12) : r.left
    const below = r.bottom + 8 + 40 * (items.length + 1) < window.innerHeight
    setPos({ left: Math.max(12, left), top: below ? r.bottom + 8 : undefined, bottom: below ? undefined : window.innerHeight - r.top + 8 })
    setOpen(true)
    onOpen?.()
  }

  useEffect(() => {
    if (!open) return
    const h = (e) => { if (!btn.current?.contains(e.target) && !pop.current?.contains(e.target)) setOpen(false) }
    const k = (e) => { if (e.key === 'Escape') setOpen(false) }
    const s = () => setOpen(false)
    document.addEventListener('mousedown', h); document.addEventListener('touchstart', h, { passive: true })
    document.addEventListener('keydown', k); window.addEventListener('scroll', s, true); window.addEventListener('resize', s)
    return () => {
      document.removeEventListener('mousedown', h); document.removeEventListener('touchstart', h)
      document.removeEventListener('keydown', k); window.removeEventListener('scroll', s, true); window.removeEventListener('resize', s)
    }
  }, [open])

  return (
    <>
      <button ref={btn} type="button" className={`btn-icon !h-7 !w-7 ${className}`} onClick={(e) => { e.stopPropagation(); toggle() }}
        aria-label={ariaLabel || t('common.more_actions')} data-tip={open ? undefined : (tip || t('common.more_actions'))} aria-haspopup="menu" aria-expanded={open}>
        <MoreHorizontal size={15} />
      </button>
      {open && pos && createPortal(
        <div ref={pop} role="menu" className="elevated fixed z-[130] w-[232px] !p-1"
          style={{ left: pos.left, top: pos.top, bottom: pos.bottom, animation: 'rise .16s var(--ease-out)' }}>
          {items.filter(Boolean).map((it) => (
            <button key={it.key} type="button" role="menuitem"
              className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] hover:bg-[var(--fill)] ${it.danger ? 'neg' : ''}`}
              onClick={(e) => { e.stopPropagation(); setOpen(false); it.onClick?.() }}>
              {it.icon && <span className="faint shrink-0">{it.icon}</span>}
              <span className="min-w-0 flex-1">{it.text}</span>
            </button>
          ))}
        </div>, document.body)}
    </>
  )
}