import { useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../lib/i18n'
import { useMotionOK } from './Pressable'
import { useCountValue } from '../lib/motion'

/* CountUp — числа, которые перекатываются при изменении.

   Вся числовая механика (докрут по expo-out, порция кадров, уважение «меньше движения»)
   живёт в lib/motion.js — там же press и остальные пружины. Здесь только вид:

   • `tabular-nums` + зарезервированная ширина: цифры не «прыгают» при пересчёте,
     колонка чисел в карточке остаётся на месте;
   • формат задаёт вызывающий код (`format`), по умолчанию — целое с разделителями
     текущей локали (то же, что у старого <Num>);
   • `prefers-reduced-motion` / «меньше движения» (классы .no-motion / .no-anim) →
     значение сразу, без анимации (это делает motion.useCountValue сам);
   • длинные/денежные форматы не прыгают: ширина резервируется «призраком» итоговой строки.

   Как катится: значение докручивается до цели (expo-out), а сама строка подъезжает
   снизу на пружине, пока предыдущая уходит вверх и гаснет — как барабан счётчика,
   но одним transform на два слоя. */

const DUR_IN = 900
const EASE = 'var(--ease-out, cubic-bezier(.2, .8, .2, 1))'
const defaultFormat = (n, loc) => {
  const r = Math.round(Number(n) || 0)
  return r.toLocaleString(loc || undefined).replace(/\s/g, '\u00a0')
}

/* Точка старта докрута: от того, что уже показано (барабан перекатывает текущее число
   в новое, а не от нуля). Стабильная ссылка: useCountValue не перезапускает анимацию
   из-за новой функции каждый рендер. */
const FROM_SHOWN = (prev) => prev
const FROM_ZERO = 0

/* Ширина резервируется «призраком» в той же ячейке грида: контейнер всегда шире
   максимума из двух строк, поэтому лента чисел не дёргается ни при анимации,
   ни при смене разрядности. */
function Reserved({ ghost, align, children }) {
  return (
    <span className="cnt" style={{ display: 'inline-grid', alignItems: 'baseline' }}>
      <span aria-hidden="true" style={{ gridArea: '1 / 1', opacity: 0, pointerEvents: 'none', userSelect: 'none', textAlign: align, whiteSpace: 'nowrap' }}>{ghost}</span>
      <span style={{ gridArea: '1 / 1', textAlign: align, whiteSpace: 'nowrap' }}>{children}</span>
    </span>
  )
}

/* ------------------------------------------------------------------ CountUp */
export function CountUp({
  value, format, duration = DUR_IN, delay = 0, roll = true,
  className = '', align, tone, title, onDone, style,
}) {
  const { locale } = useI18n()
  const ok = useMotionOK()
  const to = Number.isFinite(Number(value)) ? Number(value) : 0
  const fmt = useMemo(() => (typeof format === 'function' ? format : defaultFormat), [format])

  const [prev, setPrev] = useState(null)   // строка, которая уезжает вверх
  const [go, setGo] = useState(false)      // «слой встал на место» — включает переходы

  const idle = !ok || duration <= 0
  const arm = useRef([])                   // два кадра «до» перехода (см. onStart)
  const tail = useRef(0)                   // таймер уборки предыдущей строки
  const fire = useRef(onDone)
  fire.current = onDone
  /* формат и локаль в ref: колбэки докрута меняются каждый рендер, а анимация — нет */
  const view = useRef(null)
  view.current = { fmt, locale, roll }

  const [cur, done] = useCountValue(to, {
    from: idle ? to : FROM_SHOWN,
    duration: idle ? 0 : duration,
    delay,
    /* Барабан: первый кадр — оба слоя на стартовых позициях, дальше (через два rAF)
       включаем переходы, иначе браузер не успевает увидеть их раздельно. */
    onStart: (from) => {
      clearTimeout(tail.current)
      arm.current.forEach((id) => cancelAnimationFrame(id))
      setPrev(view.current.roll ? view.current.fmt(from, view.current.locale) : null)
      setGo(false)
      arm.current = [requestAnimationFrame(() => arm.current.push(requestAnimationFrame(() => setGo(true))))]
    },
    /* предыдущая строка уходит сразу после конца перехода — чуть позже, чтобы не мигнуть */
    onDone: () => {
      clearTimeout(tail.current)
      tail.current = setTimeout(() => setPrev(null), duration + 160)
      try { fire.current?.() } catch {}
    },
  })

  useEffect(() => () => {
    arm.current.forEach((id) => cancelAnimationFrame(id))
    clearTimeout(tail.current)
  }, [])

  const text = fmt(cur, locale)
  const inner = prev != null && roll
    ? (
      <span className="cnt-roll" style={{ display: 'inline-block', position: 'relative' }}>
        <span aria-hidden="true" style={{
          position: 'absolute', inset: 0, whiteSpace: 'nowrap', opacity: done ? 0 : 1,
          transform: go ? 'translateY(-104%)' : 'translateY(0)',
          transition: `transform ${duration}ms ${EASE}, opacity ${Math.round(duration * 0.3)}ms ${EASE}`,
        }}>{prev}</span>
        <span style={{
          display: 'inline-block', whiteSpace: 'nowrap',
          transform: go && !done ? 'translateY(0)' : 'translateY(104%)',
          transition: `transform ${duration}ms ${EASE}`,
        }}>{text}</span>
      </span>
    )
    : <span style={{ whiteSpace: 'nowrap' }}>{text}</span>

  return (
    <Reserved ghost={fmt(to, locale)} align={align}>
      <span
        className={`cnt-v num tnum ${className}`}
        title={title}
        style={{
          fontVariantNumeric: 'tabular-nums',
          display: 'inline-block',
          ...(tone ? { color: `var(--${tone})` } : null),
          ...style,
        }}
      >
        {inner}
      </span>
    </Reserved>
  )
}

/* ------------------------------------------------- старый <Num>/useCountUp (совместимость) */
/* Число, которое считает от 0 до значения: 1.8s expo-out, задержка 500ms ровно как в эталоне.
   Механика — та же, что у CountUp сверху (lib/motion.js), отличается только точка старта. */
export function useCountUp(target, { duration = 1800, delay = 500 } = {}) {
  const [v] = useCountValue(target, { from: FROM_ZERO, duration, delay })
  return v
}

/* Готовые форматы — чтобы не писать лямбды в разметке страниц. */
export function useFormats() {
  const { locale, fmtMoney, fmtNumber } = useI18n()
  return useMemo(() => ({
    int: (n) => fmtNumber(Math.round(n || 0), { maximumFractionDigits: 0 }),
    money: (n) => fmtMoney(n),
    compact: (n) => fmtMoney(n, { compact: true }),
    locale: (n) => defaultFormat(n, locale),
  }), [locale, fmtMoney, fmtNumber])
}
