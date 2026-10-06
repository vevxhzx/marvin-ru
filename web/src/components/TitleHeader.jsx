/* components/TitleHeader.jsx — крупный заголовок, который сворачивается.

   На телефоне работает как в обычном приложении: большой заголовок раздела живёт в
   потоке страницы (его рисует сама страница через PageHead/.top — мы его не трогаем),
   а эта компактная шапка приезжает на его место, когда герой уходит под липкую строку.
   Прогресс сворачивания берётся из положения героя и сглаживается, поэтому шапка
   «сжимается» без скачков; при прокрутке вверх разворачивается обратно (как в iOS).

   Анимируются только transform и opacity. На десктопе компонент не рисуется — там
   остаётся нынешний вид шапки.

   Важно: подпись здесь — дубликат заголовка страницы, поэтому она не заголовок
   для доступности (не <h1>/<h2> и aria-hidden), иначе на странице будет два
   одинаковых заголовка, а экранные читалки прочитают её дважды.
*/

import { useEffect, useRef } from 'react'
import { motionOff } from '../lib/motion'

const SPAN = 56          // сколько пикселей скролла занимает «сворачивание» — короткое и мягкое
const LERP = 0.22        // сглаживание прогресса: без него шапка дёргается на телефоне

/** Заголовок страницы, по которому считаем точку сворачивания. */
const heroOf = (root) => root?.querySelector?.('h1') || null

export default function TitleHeader({ title, sub, contentRef, pathKey }) {
  const rootRef = useRef(null)
  const subRef = useRef(null)
  const hero = useRef({ bottom: 0 })
  const state = useRef({ p: 0, shown: 0, dir: 1, lastY: 0, raf: 0 })

  /* Точка перелома: низ героя в координатах документа. Меряем на смене раздела и ресайзе. */
  useEffect(() => {
    const measure = () => {
      const h = heroOf(contentRef.current)
      if (!h) { hero.current.bottom = 0; return }
      const r = h.getBoundingClientRect()
      hero.current.bottom = Math.max(0, r.bottom + window.scrollY)
    }
    measure()
    window.addEventListener('resize', measure)
    const t = setTimeout(measure, 120)      // карточки/шрифты успевают примениться
    return () => { window.removeEventListener('resize', measure); clearTimeout(t) }
  }, [contentRef, pathKey])

  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const st = state.current
    let last = -1

    const paint = () => {
      st.raf = 0
      const y = window.scrollY
      if (Math.abs(y - st.lastY) > 2) st.dir = y > st.lastY ? 1 : -1
      st.lastY = y
      /* прогресс: 0 — герой на месте, 1 — герой ушёл, шапка раскрыта */
      const span = Math.max(SPAN, hero.current.bottom - 24)
      const target = Math.min(1, Math.max(0, (y - Math.max(0, hero.current.bottom - span)) / span))
      /* вверх шапка прячется (освобождает место возвращающемуся герою) */
      const want = st.dir < 0 && y > 12 ? 0 : target
      st.p += (want - st.p) * (motionOff() ? 1 : LERP)
      if (Math.abs(want - st.p) < 0.002) st.p = want
      const v = Math.round(st.p * 100) / 100
      if (v !== last) {
        last = v
        const p = st.p
        el.style.opacity = String(p)
        el.style.transform = `translate3d(0, ${((1 - p) * 8).toFixed(2)}px, 0) scale(${(0.97 + 0.03 * p).toFixed(3)})`
        /* прогресс уходит в слот шапки (.th-slot): по нему гаснет дата под заголовком */
        el.parentElement?.style.setProperty('--th-p', String(v))
        if (subRef.current) {
          /* подзаголовок выезжает позже — он не должен спорить с заголовком */
          const q = Math.min(1, Math.max(0, (p - 0.55) / 0.45))
          subRef.current.style.opacity = String(q)
          subRef.current.style.transform = `translate3d(0, ${((1 - q) * 6).toFixed(2)}px, 0)`
        }
      }
      /* Один кадр — один шаг lerp. Без доводки шапка после смены раздела замерала
         между состояниями: титул полупрозрачный налезал на дату в слоте и так и
         стоял — перерисовка есть только на скролле/ресайзе. Доводим до цели. */
      if (st.p !== want) st.raf = requestAnimationFrame(paint)
    }
    const schedule = () => { if (!st.raf) st.raf = requestAnimationFrame(paint) }

    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    paint()
    return () => {
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      if (st.raf) cancelAnimationFrame(st.raf)
      st.raf = 0
    }
  }, [title, pathKey])

  /* Заголовок страницы (h1) получает имя для View Transitions в PageTransition —
     здесь оно не нужно: два элемента с одним view-transition-name ломают переход. */

  if (!title) return null

  return (
    <div
      ref={rootRef}
      className="th"
      aria-hidden="true"
      style={{
        flex: '1 1 auto',
        minWidth: 0,
        opacity: 0,
        transform: 'translate3d(0, 8px, 0) scale(0.97)',
        willChange: 'transform, opacity',
        pointerEvents: 'none',
      }}
    >
      <div
        className="th-t trunc"
        style={{ fontSize: 'var(--fs-xl, 18px)', fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1.15 }}
      >
        {title}
      </div>
      {sub && (
        <div
          ref={subRef}
          className="th-s trunc"
          style={{ marginTop: 2, fontSize: 'var(--fs-sm, 12.5px)', color: 'var(--ink-3)', opacity: 0, lineHeight: 1.2 }}
        >
          {sub}
        </div>
      )}
    </div>
  )
}