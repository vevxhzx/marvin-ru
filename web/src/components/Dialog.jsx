import { createPortal } from 'react-dom'

/* Общая оболочка модального диалога-поиска: затемнение, центрированная карточка
   600px, role=dialog. Используют Palette.jsx (командная палитра) и OmniSearch.jsx
   (общий поиск): внутренности у них свои, оболочка одна — правится в одном месте.
   testId — для e2e (OmniSearch: omni-dialog); остальным не ставится. */
export default function DialogShell({ onClose, label, testId, children }) {
  return createPortal(
    <div className="fixed inset-0 flex items-start justify-center px-3 pt-[calc(10vh/var(--ui-zoom))] sm:pt-[calc(14vh/var(--ui-zoom))]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}
      {...(testId ? { 'data-testid': testId } : {})}
      style={{ zIndex: 'var(--z-scrim)', background: 'color-mix(in srgb, var(--bg) 40%, rgba(8, 8, 12, .46))', animation: 'fade .16s ease-out' }}>
      <div className="elevated flex max-h-[86dvh] w-full max-w-[600px] flex-col overflow-hidden" style={{ animation: 'rise .22s var(--ease-out)' }}
        role="dialog" aria-modal="true" aria-label={label}>
        {children}
      </div>
    </div>, document.body)
}
