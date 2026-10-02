/* components/SheetHost.jsx — хост окон оболочки.

   Оболочка (AppShell, Dock) открывает окна через этот компонент, но сам он ничего не
   реализует: разметка, поведение, ловушка фокуса, Esc, блокировка фона и свайп за
   ручку живут в единственной шторке — `Sheet` из components/ui.jsx. Это одна и та же
   реализация, которой пользуются все страницы, поэтому разметка, стили и e2e-селекторы
   (`.sheet-backdrop:not(.closing) .sheet`, первая кнопка внутри шторки — ✕, `h3.h2`)
   одинаковые везде.

   Именно поэтому файл оставлен, а не удалён: это имя хоста для окон оболочки
   (помогает «шторка одна — хост один»), а не копия шторки. */

import { Sheet } from './ui'

/**
 * Единственное окно оболочки: справка по горячим клавишам, меню «Ещё» дока и всё, что
 * откроет оболочка позже. Пропсы — как у Sheet: open, onClose, title, sub, wide, children.
 * ariaLabel — подпись для окна без заголовка.
 */
export default function SheetHost({ open, onClose, title, sub, wide, children, ariaLabel }) {
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={title}
      sub={sub}
      wide={wide}
      ariaLabel={ariaLabel}
    >
      {children}
    </Sheet>
  )
}
