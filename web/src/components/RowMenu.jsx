// Кнопка «⋯» с выпадающим меню действий. Рисуем порталом в body: строка заказа лежит
// внутри .swipe с overflow:hidden, и обычный absolute-попап там обрезался (см. PriorityDot в ui.jsx).
// Все пункты — с ТЕКСТОВЫМИ подписями: в меню нет безымянных иконок.
// Поверхность — общая elevated-карточка (--surface-2 + --line), пункты — строки .more-row:
// зона нажатия --tap, радиус --r-md, появление через transform (rise). Длинная подпись
// усекается многоточием, полная — в title, чтобы ничего не обрезалось молча.
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MoreHorizontal } from 'lucide-react'
import { useI18n } from '../lib/i18n'

const W = 244

export default function MenuButton({ items, ariaLabel, tip, align = 'right', className = '', onOpen }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)
  const btn = useRef(null)
  const pop = useRef(null)

  const toggle = () => {
    if (open) return setOpen(false)
    const r = btn.current.getBoundingClientRect()
    const list = items.filter(Boolean)
    const left = align === 'right' ? Math.min(r.right - W, window.innerWidth - W - 12) : r.left
    const below = r.bottom + 8 + 44 * (list.length + 1) < window.innerHeight
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

  const label = ariaLabel || t('common.more_actions')
  return (
    <>
      <button ref={btn} type="button" className={`btn-icon ${className}`} onClick={(e) => { e.stopPropagation(); toggle() }}
        aria-label={label} title={tip || label} data-tip={open ? undefined : (tip || label)} aria-haspopup="menu" aria-expanded={open}>
        <MoreHorizontal size={15} />
      </button>
      {open && pos && createPortal(
        <div ref={pop} role="menu" className="elevated fixed z-[130] !p-1.5" style={{ left: pos.left, top: pos.top, bottom: pos.bottom, width: W, animation: 'rise .16s var(--ease-out)' }}
          aria-label={label}>
          {items.filter(Boolean).map((it) => (
            <button key={it.key} type="button" role="menuitem" title={it.text}
              className={`more-row !bg-transparent ${it.danger ? 'neg' : ''}`}
              onClick={(e) => { e.stopPropagation(); setOpen(false); it.onClick?.() }}>
              {it.icon && <span className="faint grid h-6 w-6 shrink-0 place-items-center" aria-hidden="true">{it.icon}</span>}
              <span className="min-w-0 flex-1 trunc">{it.text}</span>
            </button>
          ))}
        </div>, document.body)}
    </>
  )
}