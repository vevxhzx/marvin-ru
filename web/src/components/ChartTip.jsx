/* Подсказки графиков — одна на весь проект.
 *
 * Заказ владельца: «посмотри, чтобы при наведении показывало, сколько трат на виджетах».
 * Раньше подсказки у столбиков не было вовсе, у части графиков были разные уловки
 * (нативный title, тёмная плашка в углу, ничего), и читались они по-разному.
 *
 * Что здесь единого:
 *   • вид — тот же, что у подсказки кассы и графа: тёмная плашка var(--ink)/var(--bg),
 *     класс .chart-tip в index.css;
 *   • поведение — мышь (наведение), палец (тап «залипает», повторный тап убирает),
 *     клавиатура (Tab/стрелки показывают, Esc и уход фокуса убирают);
 *   • место — панель живёт в portal на document.body и меряется по экрану:
 *     не вылезает за край окна и safe-area, не прыгает при прокрутке (слушаем scroll
 *     и пересчитываем), не обрезается карточкой: у .c стоит overflow:hidden.
 *
 * Никаких новых библиотек: только React + существующие классы проекта.
 */
import { useCallback, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { money } from '../lib/api'
import { useI18n } from '../lib/i18n'

/* Безопасные отступы экрана («чёлка»). Читаем один раз через невидимый элемент. */
let probe = null
function safeInsets() {
  if (typeof document === 'undefined') return { l: 0, r: 0 }
  if (!probe) {
    probe = document.createElement('div')
    probe.style.cssText = 'position:fixed;top:0;left:0;width:0;height:0;visibility:hidden;pointer-events:none;'
      + 'padding-left:env(safe-area-inset-left,0px);padding-right:env(safe-area-inset-right,0px)'
    document.body.appendChild(probe)
  }
  const cs = getComputedStyle(probe)
  return { l: parseFloat(cs.paddingLeft) || 0, r: parseFloat(cs.paddingRight) || 0 }
}

/* Верх нижней навигации телефона (она fixed и перекрывает низ экрана) — подсказка
   не должна на неё заезжать. На десктопе навигации нет, и тогда просто низ окна. */
function navTop() {
  if (typeof document === 'undefined') return 1e5
  const nav = document.querySelector('.tabbar')
  if (!nav) return 1e5
  const r = nav.getBoundingClientRect()
  return r.height && r.bottom > window.innerHeight - 4 ? r.top : 1e5
}

/* Сама плашка. anchor — элемент или функция (элемент может появиться только вместе
   с панелью, поэтому CashChart отдаёт функцию). Позицию ставим прямо в DOM:
   так подсказка не «прыгает» и не вызывает лишний рендер при каждом движении мыши. */
function ChartTipPanel({ anchor, hostRef, title, rows = [], children, ...rest }) {
  const ref = useRef(null)
  useLayoutEffect(() => {
    const tip = ref.current
    const el = typeof anchor === 'function' ? anchor() : anchor
    if (!tip || !el) return
    const place = () => {
      const t = ref.current
      if (!t) return
      // элемент мог перерисоваться (график с новыми данными) — тогда панель просто ждёт
      if (!el.isConnected) return
      const r = el.getBoundingClientRect()
      const host = hostRef?.current?.getBoundingClientRect?.() || null
      const safe = safeInsets()
      const vw = window.innerWidth, vh = window.innerHeight
      const pad = 8
      // сперва ширина: панель не шире окна (минус safe-area) и не шире самого графика
      const room = Math.min(vw - pad * 2 - safe.l - safe.r, host ? host.width - pad * 2 : 320)
      t.style.maxWidth = `${Math.round(Math.max(120, Math.min(320, room)))}px`
      const w = t.offsetWidth, h = t.offsetHeight
      // по горизонтали — внутри пересечения «график ∩ экран»: у краёв прилипает, а не уезжает
      const lo = Math.max(pad + safe.l, host ? host.left + pad : pad + safe.l)
      const hi = Math.min(vw - pad - safe.r, host ? host.right - pad : vw - pad - safe.r)
      const cx = (v) => Math.max(lo, Math.min(hi - w, v))
      // по вертикали: сначала над столбиком; если над графиком не влезает (высокий столбик) —
      // под ним; а у нижней навигации телефона — сбоку, чтобы не закрыть её
      const topLimit = Math.max(pad, host ? host.top : 0)
      const bottomLimit = Math.max(topLimit, Math.min(vh - h - pad, navTop() - pad, host ? host.bottom + 24 : vh))
      const above = r.top - h - 10
      let x, y
      if (above >= topLimit) { x = cx(r.left + r.width / 2 - w / 2); y = above }
      else if (r.bottom + 10 <= bottomLimit) { x = cx(r.left + r.width / 2 - w / 2); y = r.bottom + 10 }
      else { x = cx(r.right + 8 + w <= hi ? r.right + 8 : r.left - w - 8); y = Math.max(topLimit, Math.min(bottomLimit - h, r.top)) }
      t.style.left = `${Math.round(x)}px`
      t.style.top = `${Math.round(y)}px`
    }
    place()
    window.addEventListener('scroll', place, true)   // capture: ловим и прокрутку внутри карточек
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
    // rows/children — новые на каждый рендер: так панель перемеряется и после смены текста
  }, [anchor, hostRef, title, rows, children])
  if (typeof document === 'undefined') return null
  return createPortal(
    <div ref={ref} role="tooltip" className="chart-tip" {...rest}>
      {title ? <div className="ct-t">{title}</div> : null}
      {(rows || []).map((r, i) => <div key={i} className="ct-r">{r}</div>)}
      {children}
    </div>,
    document.body,
  )
}

/* Подсказка на экране всегда одна: открытая закрывает предыдущую (два виджета рядом
   не должны показывать по плашке, и на телефоне они перекрывают друг друга). */
let shown = null
const claim = (close) => { if (shown && shown.close !== close) shown.close(); shown = { close } }
const forget = (close) => { if (shown && shown.close === close) shown = null }

/**
 * Хук подсказки. Возвращает:
 *   active/pinned — что сейчас под курсором/фокусом и «залипло» ли тапом;
 *   hostRef       — вешаем на контейнер графика (по нему подсказка понимает границы);
 *   host          — onPointerLeave/onPointerCancel для контейнера;
 *   bind(i, aria) — набор свойств для столбика/точки (фокус, подписи, тап, стрелки);
 *   open/pin/close — управление вручную (графики, где точка выбирается движением мыши);
 *   panel({...})  — сама плашка в портале или null.
 */
export function useTip() {
  const [active, setActive] = useState(null)      // { i, anchor }
  const [pinned, setPinned] = useState(false)     // тап на телефоне: держим до повторного
  const hostRef = useRef(null)
  const els = useRef({})
  const id = useId()

  const close = useCallback(() => { forget(close); setActive(null); setPinned(false) }, [])
  const open = useCallback((i, anchor) => { claim(close); setActive({ i, anchor: anchor || null }) }, [close])
  const pin = useCallback((i, anchor) => { claim(close); setActive({ i, anchor: anchor || null }); setPinned(true) }, [close])

  const bind = useCallback((i, aria, role = 'img') => ({
    'data-tip-i': i,
    tabIndex: 0,
    role,
    // смысл столбика читается и с глаз, и слухом: подпись та же, что в подсказке.
    // aria-describedby не нужен — он прочитал бы то же самое второй раз
    'aria-label': aria,
    ref: (el) => { if (el) els.current[i] = el },
    onPointerEnter: (e) => { if (e.pointerType === 'mouse') open(i, e.currentTarget) },
    // палец: тап показывает, повторный по тому же столбику убирает. preventDefault не зовём —
    // жест должен остаться прокруткой, а не перехватом
    onPointerDown: (e) => {
      if (e.pointerType === 'mouse') return
      if (pinned && active?.i === i) close()
      else pin(i, e.currentTarget)
    },
    onFocus: (e) => open(i, e.currentTarget),
    onBlur: () => { if (!pinned) close() },
    onKeyDown: (e) => {
      if (e.key === 'Escape') { close(); return }
      const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : e.key === 'Home' ? -1e9 : e.key === 'End' ? 1e9 : 0
      if (!step) return
      const keys = Object.keys(els.current).map(Number).sort((a, b) => a - b)
      if (!keys.length) return
      const at = keys.indexOf(active?.i ?? i)
      const next = keys[Math.max(0, Math.min(keys.length - 1, (at < 0 ? 0 : at) + step))]
      const el = els.current[next]
      if (el) { el.focus(); open(next, el) }
      e.preventDefault()
    },
  }), [active, close, open, pin, pinned])

  const host = {
    onPointerLeave: () => { if (!pinned) close() },
    onPointerCancel: () => close(),   // палец увел в сторону — это прокрутка, подсказку убираем
  }

  const panel = useCallback((content) => {
    if (!active) return null
    return <ChartTipPanel id={id} anchor={active.anchor} hostRef={hostRef} {...content} />
  }, [active, hostRef, id])

  return { active, pinned, hostRef, host, bind, open, pin, close, panel, id }
}

/** Дни месяца, попавшие в заданный день недели (для подсказки «траты по дням недели»).
 *  weekday — как у сервера: 0 — понедельник. */
export function weekdayDates(weekday, now = new Date()) {
  const out = []
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()
  for (let d = 1; d <= last; d++) if (new Date(now.getFullYear(), now.getMonth(), d).getDay() === (weekday + 1) % 7) out.push(d)
  return out
}

/* Границы «столбиков по дням месяца» на главной: сервер складывает траты в семь корзин
 * по этим дням (core/services/finance.py, edges), подписи под осью — первые дни корзин. */
const MONTH_EDGES = [4, 9, 14, 19, 24, 29, 31]
const MONTH_STARTS = [1, 5, 10, 15, 20, 25, 30]

/**
 * Столбики с подсказкой — те же `.bars`/`.bl`, что были на главной, но под каждым числом.
 * kind: 'weekday' — дни недели (траты за месяц по дням недели),
 *       'month'   — пятидневки месяца (траты за месяц по периодам).
 * values — готовые суммы из ответа сводки; высоты считаются ровно так же, как раньше.
 */
export function TipBars({ kind = 'weekday', values = [], labels = [], barClass = 'bars', labelClass = 'bl mono' }) {
  const { t, fmtWeekday } = useI18n()
  const tip = useTip()
  const vals = Array.isArray(values) ? values : []
  const max = Math.max(1, ...vals)
  const now = new Date()
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()
  const total = vals.reduce((s, v) => s + (v || 0), 0)

  const info = (i) => {
    const v = vals[i] || 0
    const pct = Math.round((v / max) * 100)
    if (kind === 'weekday') {
      // 1 января 2024 — понедельник, поэтому день недели совпадает с индексом корзины
      const name = fmtWeekday(new Date(2024, 0, 1 + i), 'long')
      const rows = [t('tip.spent_month', { m: money(v) }), t('tip.days', { d: weekdayDates(i, now).join(', ') })]
      return { pct, aria: `${name}: ${rows.join(', ')}`, tip: { title: name, rows } }
    }
    const a = MONTH_STARTS[i], b = Math.min(MONTH_EDGES[i], daysInMonth)
    const title = t('tip.days_range', { a, b })
    const share = total > 0 ? Math.round((v / total) * 100) : 0
    const rows = [t('tip.spent_month', { m: money(v) }), t('tip.share', { p: share })]
    return { pct, aria: `${title}: ${rows.join(', ')}`, tip: { title, rows } }
  }

  const cur = tip.active?.i != null ? info(tip.active.i).tip : null

  return (
    <>
      <div className={`relative ${barClass}`} ref={tip.hostRef} {...tip.host}>
        {vals.map((_, i) => {
          const it = info(i)
          return <i key={i} className={`chart-pt ${it.pct ? '' : 'z'}`} style={{ '--h': `${it.pct}%`, '--k': i }} {...tip.bind(i, it.aria)} />
        })}
      </div>
      {labels.length > 0 && <div className={labelClass}>{labels.map((l, i) => <span key={i}>{l}</span>)}</div>}
      {tip.panel(cur || {})}
    </>
  )
}

