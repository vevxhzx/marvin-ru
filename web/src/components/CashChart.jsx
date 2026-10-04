import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { money } from '../lib/api'
import { t as T } from '../lib/i18n'
import { useTip } from './ChartTip'
import { Skeleton } from './ui'
import { stagger } from '../lib/motion'

/* График «касса на N дней» — общий для раздела «финансы» и виджета на главной.
 *
 * Что рисуется: точка = БАЛАНС НА КОНЕЦ ДНЯ (а не дневная дельта). Ряд приходит с сервера
 * (/api/finance/forecast): прошлое — пересчёт по реальным операциям от текущего баланса,
 * будущее — прогноз. Подсказка поэтому показывает две подписанные строки: «баланс на …» и
 * «за день: ±Y ₽» — раньше число просто появлялось без подписи и читалось как дельта.
 *
 * «Сегодня» = последняя точка прошлого (kind !== 'future'), тот же источник, что и у сервера,
 * поэтому метка не может разъехаться с маркером на 1 день.
 *
 * Саму плашку рисует ChartTip — та же, что у столбиков на главной: тёмная, с safe-area,
 * не вылезает за края и не прыгает. Здесь она целиком в portal, поэтому карточка с
 * overflow:hidden её не срезает. Набор подписей (data-date/data-bal/data-kind) прежний —
 * на них завязан e2e-тест tests/e2e/specs/cash_chart.spec.js.
 *
 * Движение: только transform/opacity — маркеры событий проявляются каскадом (lib/motion),
 * высоты графика зарезервированы заранее (скелетон), поэтому данные не «прыгают».
 */
/* Серии в тёмной теме подсвечиваем: факт и маркер «сегодня» — светлее и насыщеннее,
   иначе на тёмном фоне они глохнут. Светлая тема — как было.
   (recharts в проекте нет: серии этого графика рисует SVG ниже, цвета задаются здесь
   и в легенде Today.jsx — обе точки берут цвет из cashFact.) */
const isDark = () => typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
export const cashFact = (dark) => (dark ? '#ffb37e' : '#ff9f5c')
const W = 600, H = 200                       // система координат viewBox
const dm = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`   // без new Date(iso) — иначе минус день у клиента в UTC−
// события прошедших дней: операции приходят отдельным запросом и в ряду их нет
const txEvents = (txs) => {
  const by = {}
  for (const t of (Array.isArray(txs) ? txs : [])) {
    if (!t?.date) continue
    const day = String(t.date).slice(0, 10)
    ;(by[day] = by[day] || []).push({
      title: t.kind === 'transfer'
        ? T('chart.transfer', { amount: money(t.amount), from: t.account, to: t.to_account || '—' })
        : t.note || t.category || (t.kind === 'income' ? T('chart.income') : T('chart.expense')),
      amount: t.kind === 'income' ? Math.round(t.amount) : t.kind === 'transfer' ? 0 : -Math.round(t.amount),
    })
  }
  return by
}

export default function CashChart({ f, height = 200, compact = false, txs = null, legend = true }) {
  const [sel, setSel] = useState(null)          // индекс точки под курсором/пальцем
  const tip = useTip()                          // общая подсказка (ChartTip.jsx)
  const dotRef = useRef(null)                   // маркер выбранной точки — к нему привязана плашка
  const hintId = useId()                        // подпись для скринридера про стрелки
  const pts = f?.points || []
  const n = pts.length

  const byDay = useMemo(() => txEvents(txs), [txs])
  const todayIdx = useMemo(() => {
    const i = pts.findIndex((p) => p.kind === 'future')
    return i === -1 ? n - 1 : Math.max(0, i - 1)
  }, [pts, n])
  const todayISO = pts[todayIdx]?.date || f?.today || ''

  const geo = useMemo(() => {
    if (n < 2) return null
    const vals = pts.map((p) => p.balance)
    let max = Math.max(...vals), min = Math.min(...vals)
    if (min > 0) min = 0
    if (max < 0) max = 0
    if (max === min) max = min + 1
    const hi = max + (max - min) * 0.1, lo = min - (min < 0 ? (max - min) * 0.1 : 0)
    const span = (hi - lo) || 1
    const X = (i) => (i / (n - 1)) * W
    const Y = (v) => H - 10 - ((v - lo) / span) * (H - 20)
    const path = (from, to) => pts.slice(from, to + 1).map((p, k) => `${k ? 'L' : 'M'}${X(from + k).toFixed(1)} ${Y(p.balance).toFixed(1)}`).join('')
    // заливка идёт до линии НУЛЯ, а не до низа холста: иначе отрицательный баланс выглядит как «площадь под графиком»
    const fill = `${path(0, n - 1)}L${X(n - 1).toFixed(1)} ${Y(0).toFixed(1)}L${X(0).toFixed(1)} ${Y(0).toFixed(1)}Z`
    return { X, Y, fill, fact: path(0, todayIdx), future: path(todayIdx, n - 1), zero: Y(0), negative: min < 0 }
  }, [pts, n, todayIdx])

  const xPct = (i) => ((geo?.X(i) ?? 0) / W) * 100
  const yPx = (v) => ((geo?.Y(v) ?? 0) / H) * height

  const cur = sel != null ? pts[sel] : null
  const delta = (i) => (pts[i]?.delta != null ? pts[i].delta : i > 0 ? pts[i].balance - pts[i - 1].balance : 0)
  const events = (i) => (pts[i]?.events?.length ? pts[i].events : byDay[pts[i]?.date] || [])

  // подписи оси X — реальные даты точек (3–5 штук) + метка «сегодня» ровно у маркера
  const axis = useMemo(() => {
    if (!geo) return []
    const raw = [0, 0.25, 0.5, 0.75, 1].map((k) => Math.round(k * (n - 1)))
    raw.push(todayIdx)
    const out = []
    for (const i of [...new Set(raw)].sort((a, b) => a - b)) {
      const x = xPct(i)
      const last = out[out.length - 1]
      const mk = { i, x, today: i === todayIdx, text: dm(pts[i].date) }
      if (last && x - last.x < 11) {
        // метка «сегодня» важнее обычной даты: вытесняем соседнюю, а не налезаем на неё
        if (mk.today && !last.today) out[out.length - 1] = mk
        continue
      }
      out.push(mk)
    }
    return out
  }, [geo, n, todayIdx, pts])

  const idxAt = (e, box) => {
    if (!box.width) return 0
    return Math.max(0, Math.min(n - 1, Math.round(((e.clientX - box.left) / box.width) * (n - 1))))
  }
  const pick = (e) => {
    const i = idxAt(e, e.currentTarget.getBoundingClientRect())
    if (i === sel) return
    setSel(i)
    tip.open(i, () => dotRef.current)      // плашка целится в маркер, он появится с ней же
  }
  const onDown = (e) => {
    const i = idxAt(e, e.currentTarget.getBoundingClientRect())
    if (tip.pinned && i === sel) { setSel(null); tip.close(); return }   // повторный тап — убрать подсказку
    setSel(i); tip.pin(i, () => dotRef.current)
  }
  const onLeave = () => { if (!tip.pinned) { setSel(null); tip.close() } }
  // палец увел в сторону — браузер отдаёт жест себе (вертикальная прокрутка), подсказку убираем
  const onCancel = () => { setSel(null); tip.close() }
  // клавиатура: стрелки — по дням, Esc — убрать подсказку
  const onKey = (e) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : e.key === 'Home' ? -1e9 : e.key === 'End' ? 1e9 : 0
    if (e.key === 'Escape') { setSel(null); tip.close(); return }
    if (!step) return
    e.preventDefault()
    const i = Math.max(0, Math.min(n - 1, (sel == null ? 0 : sel + step)))
    setSel(i); tip.open(i, () => dotRef.current)
  }

  /* Мало точек — честная подпись на месте скелетона: высота зарезервирована, страница не прыгает */
  if (!geo) {
    return (
      <Skeleton h={height} radius="var(--r-md)" className="my-2 grid place-items-center">
        <span className="text-[length:var(--fs-md)] text-[var(--ink-3)]">{T('chart.too_few')}</span>
      </Skeleton>
    )
  }

  const curX = sel != null ? xPct(sel) : 0
  const evs = cur ? events(sel) : []
  // подпись точки для скринридера и для подсказки — одна и та же строка
  const pointLabel = (p) => `${T(p.kind === 'future' ? 'chart.forecast_on' : 'chart.balance_on', { date: dm(p.date) })}: ${money(p.balance)}`
  const dayLine = (p, i) => `${T('chart.per_day')}${p.kind === 'future' ? T('chart.forecast_tag') : ''}: `
    + (delta(i) === 0 ? T('chart.no_change') : money(delta(i), { plus: true }))
  const tipId = `${hintId}-tip`

  /* Маркеры событий проявляются каскадом: только opacity, высоты не трогаем */
  useEffect(() => {
    if (!geo) return undefined
    const host = tip.hostRef.current
    if (!host) return undefined
    const els = host.querySelectorAll('[data-pt]')
    if (!els.length) return undefined
    return stagger(els, { step: 26, dy: 0, duration: 300, from: 120, max: 24 })
  }, [geo, pts, tip.hostRef])

  return (
    <div>
      <div ref={tip.hostRef} className="relative" style={{ height }} onPointerLeave={onLeave} onPointerCancel={onCancel}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={T('chart.aria')}
          aria-describedby={sel != null ? tipId : hintId} tabIndex={0}
          className="chart-pt block w-full cursor-crosshair" style={{ height, touchAction: 'pan-y' }}
          onPointerDown={onDown} onPointerMove={pick} onKeyDown={onKey}>
          <defs>
            <linearGradient id="cc-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--accent)" stopOpacity="0.22" />
              <stop offset="1" stopColor="var(--accent)" stopOpacity="0.02" />
            </linearGradient>
          </defs>
          {/* линия нуля — подписана, чтобы «точка выше пунктира» читалось однозначно */}
          <line x1="0" x2={W} y1={geo.zero} y2={geo.zero} stroke={geo.negative ? 'var(--neg)' : 'var(--ink3)'} strokeWidth="1" strokeDasharray="3 5" opacity="0.8" vectorEffect="non-scaling-stroke" />
          <path d={geo.fill} fill="url(#cc-fill)" />
          <path d={geo.fact} fill="none" stroke={cashFact(isDark())} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          <path d={geo.future} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
          {/* маркер «сегодня» — последняя точка факта, а не первый день прогноза */}
          <line x1={geo.X(todayIdx)} x2={geo.X(todayIdx)} y1="0" y2={H} stroke="var(--ink3)" strokeWidth="1" strokeDasharray="4 6" opacity="0.45" vectorEffect="non-scaling-stroke" />
          {sel != null && sel !== todayIdx && (
            <line x1={geo.X(sel)} x2={geo.X(sel)} y1="0" y2={H} stroke="var(--ink-2)" strokeWidth="1" strokeDasharray="4 6" opacity="0.55" vectorEffect="non-scaling-stroke" />
          )}
        </svg>

        {/* слой HTML: точки событий, подпись нуля, точка выбора — их нельзя рисовать в растянутом svg */}
        <div className="pointer-events-none absolute inset-0" style={{ height }}>
          <span className="absolute right-0 -translate-y-full pr-0.5 leading-none text-[length:var(--fs-xs)] text-[var(--ink3)]" style={{ top: yPx(0) }}>{T('chart.zero')}</span>
          {pts.map((p, i) => {
            const ev = events(i)
            if (!ev.length) return null
            const up = ev.some((e) => e.amount > 0)
            return <span key={i} data-pt className="absolute h-[7px] w-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full border-[1.5px] border-[var(--bg)]"
              style={{ left: `${xPct(i)}%`, top: yPx(p.balance), background: up ? 'var(--pos)' : 'var(--ink-3)' }} />
          })}
          <span className="absolute h-[7px] w-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--bg)]"
            style={{ left: `${xPct(todayIdx)}%`, top: yPx(pts[todayIdx].balance), background: cashFact(isDark()) }} />
          {sel != null && (
            <span ref={dotRef} className="absolute h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--bg)]"
              data-testid="cash-dot"
              style={{ left: `${curX}%`, top: yPx(cur.balance), background: cur.balance < 0 ? 'var(--neg)' : 'var(--accent)' }} />
          )}
        </div>
      </div>

      {/* подсказка — общая (ChartTip): в портале, поэтому карточка её не срезает */}
      <span id={hintId} className="sr-only">{T('chart.nav')}</span>
      {tip.panel({
        id: tipId,
        'data-testid': 'cash-tip',
        'data-date': cur?.date,
        'data-kind': cur?.kind,
        'data-bal': cur?.balance,
        'data-delta': sel != null ? delta(sel) : undefined,
        title: cur ? pointLabel(cur) : null,
        rows: cur ? [
          dayLine(cur, sel),
          ...evs.slice(0, compact ? 1 : 2).map((e) => (e.amount ? `${e.amount > 0 ? '+' : '−'}${money(Math.abs(e.amount)).replace(' ₽', '')} ₽ ` : '· ') + e.title),
        ] : [],
      })}

      {/* ось X: реальные даты точек, метка «сегодня» стоит ровно у маркера */}
      <div className="mono relative mt-1.5 h-4 text-[length:var(--fs-xs)] text-[var(--ink3)]" data-testid="cash-axis">
        {axis.map((a) => (
          <span key={a.i} data-testid="cash-tick" data-today={a.today ? '1' : '0'}
            className={`absolute top-0 -translate-x-1/2 whitespace-nowrap ${a.today ? 'text-[var(--ink2)]' : ''}`}
            style={{ left: `${a.x}%`, transform: a.x < 3 ? 'translateX(0)' : a.x > 97 ? 'translateX(-100%)' : 'translateX(-50%)' }}>
            {a.today ? T('chart.today_at', { date: a.text }) : a.text}
          </span>
        ))}
      </div>

      {legend && (
        <div className="lg">
          <span><i style={{ background: cashFact(isDark()) }}></i>{T('chart.fact')}</span>
          <span><i style={{ background: 'var(--accent)' }}></i>{T('chart.forecast')}</span>
          <span><i style={{ border: '1.5px dashed var(--ink3)', background: 'none' }}></i>{T('chart.zero')}</span>
        </div>
      )}
    </div>
  )
}