import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Flame, Upload, Cake } from 'lucide-react'
import { api, money } from '../lib/api'
import CashChart from './CashChart'
import { useTip } from './ChartTip'
import { useI18n, t as T } from '../lib/i18n'
import { CountUp } from './CountUp'
import { Skeleton } from './ui'
import { motionOff, stagger } from '../lib/motion'

/* ---------- общие примитивы редакционной раскладки (главная и финансы) ----------

   Три мелочи, которые нужны обоим экранам, чтобы иерархия выглядела одинаково:

   • useReveal — каскад появления блоков: transform + opacity, шаг 52 мс, только
     элементы с data-reveal. Движение выключено — ставится конечное состояние сразу.
   • useNumFormats — форматы чисел, где разряды разделены НЕРАЗРЫВНЫМ пробелом
     (число не переносится и не «прыгает» при смене разрядности).
   • BigMoney — одна строка денег: число весом, знак ₽ мельче и легче. */
export const CUR = '₽'

/* Неразрывный пробел везде, где стоит обычный: и в разрядах, и в «1,5 млн» */
const NBSP = (s) => String(s ?? '').replace(/[\s\u202f]/g, '\u00a0')

export function useNumFormats() {
  const { fmtNumber, fmtMoney } = useI18n()
  return useMemo(() => ({
    int: (n) => NBSP(fmtNumber(Math.round(Number(n) || 0), { maximumFractionDigits: 0 })),
    money: (n) => NBSP(fmtMoney(n)),
    short: (n) => NBSP(fmtMoney(n, { compact: true })),
    nb: NBSP,
  }), [fmtNumber, fmtMoney])
}

/* Каскад появления: ref на контейнер, data-reveal на блоках внутри. Ничего не
   скрываем намертво — после конца анимации элемент просто встаёт на место. */
export function useReveal(dep) {
  const ref = useRef(null)
  useEffect(() => {
    if (motionOff()) return undefined
    const host = ref.current
    if (!host) return undefined
    const els = host.querySelectorAll('[data-reveal]')
    if (!els.length) return undefined
    return stagger(els, { step: 52, dy: 12, duration: 420, from: 40, max: 24 })
  }, [dep])
  return ref
}

/* Сумма одной строкой: число тянет на себя вес, ₽ — на полтона кегля легче. */
export function BigMoney({ value, format, label, className = '', fs = 'var(--hero-fs)' }) {
  return (
    <span className={`big ${className}`} style={{ fontSize: fs }}>
      <span aria-hidden="true">
        <CountUp value={Number(value) || 0} format={format} roll={false} />
        <span style={{ fontSize: '0.5em', fontWeight: 400, opacity: 0.75, marginLeft: '0.18em' }}>{CUR}</span>
      </span>
      <span className="sr-only">{label}</span>
    </span>
  )
}

/* Строка «подпись — значение» прямо на поверхности героя: подпись приглушена,
   значение читается. Контраст подписи на лаймовом фоне ≈ 5.9:1 (AA). */
export function HeroLine({ label, value }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 opacity-75">
      <span className="trunc text-[length:var(--fs-md)]">{label}</span>
      <span className="num shrink-0 whitespace-nowrap opacity-100 text-[length:var(--fs-base)]">{value}</span>
    </div>
  )
}

/* ---------- Тепловая карта активности (как на GitHub) + стрик ---------- */
export function Heatmap({ days = [], heatmap = [], weeks = 26 }) {
  const { t } = useI18n()
  const tip = useTip()
  const [cur, setCur] = useState(null)      // клетка под курсором/фокусом — для обводки и озвучки
  const map = useMemo(() => Object.fromEntries((heatmap || []).map((x) => [x.date, x.count])), [heatmap])
  const cells = useMemo(() => {
    const out = []; const today = new Date(); today.setHours(0, 0, 0, 0)
    const start = new Date(today); start.setDate(start.getDate() - (weeks * 7 - 1) - ((today.getDay() + 6) % 7))
    for (let d = new Date(start); d <= today; d.setDate(d.getDate() + 1)) {
      const k = d.toISOString().slice(0, 10)
      out.push({ k, n: map[k] || 0, m: d.getMonth(), day: d.getDate() })
    }
    return out
  }, [map, weeks])
  const max = Math.max(1, ...cells.map((c) => c.n))
  const cols = Math.ceil(cells.length / 7)
  const label = (c) => `${c.day}.${String(c.m + 1).padStart(2, '0')} · ${c.n ? t('heat.entries', { n: c.n }) : t('heat.empty')}`
  const cell = (i) => cells[i]
  // сетка идёт колонками по 7 дней: стрелки вправо/влево — неделя, вниз/вверх — день
  const onMove = (e) => {
    if (e.pointerType && e.pointerType !== 'mouse') return
    const el = e.target?.closest?.('[data-i]')
    if (!el) return
    const i = Number(el.getAttribute('data-i'))
    if (tip.active?.i === i) return
    setCur(i); tip.open(i, el)
  }
  const onDown = (e) => {
    if (e.pointerType === 'mouse') return
    const el = e.target?.closest?.('[data-i]')
    if (!el) return
    const i = Number(el.getAttribute('data-i'))
    if (tip.pinned && tip.active?.i === i) { setCur(null); tip.close(); return }
    setCur(i); tip.pin(i, el)
  }
  const onKey = (e) => {
    if (e.key === 'Escape') { setCur(null); tip.close(); return }
    const step = e.key === 'ArrowRight' ? 7 : e.key === 'ArrowLeft' ? -7 : e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const i = Math.max(0, Math.min(cells.length - 1, (cur ?? cells.length - 1) + step))
    const el = e.currentTarget.querySelector(`[data-i="${i}"]`)
    setCur(i); tip.open(i, el)
  }
  return (
    <div className="relative">
      {/* одна остановка Tab на всю карту: 91 клетка — это слишком много, поэтому шагаем стрелками */}
      <div className="chart-pt grid gap-[3px] outline-none" style={{ gridTemplateRows: 'repeat(7, 10px)', gridAutoFlow: 'column', gridAutoColumns: '10px' }}
        ref={tip.hostRef} tabIndex={0} role="group" aria-label={t('heat.aria')}
        onPointerMove={onMove} onPointerDown={onDown} onKeyDown={onKey} onBlur={() => { setCur(null); tip.close() }} onPointerCancel={() => { setCur(null); tip.close() }}>
        {cells.map((c, i) => {
          const a = c.n ? 0.25 + 0.75 * Math.min(1, Math.log1p(c.n) / Math.log1p(max)) : 0
          return <span key={c.k} data-i={i} data-cur={cur === i ? '1' : undefined} aria-hidden="true"
            className="heat-cell rounded-[2px] transition-transform hover:scale-125" style={{ background: a ? `color-mix(in srgb, var(--accent) ${Math.round(a * 100)}%, var(--fill))` : 'var(--fill)', animation: `fade .4s ease-out ${Math.min(600, i * 2)}ms both` }} />
        })}
      </div>
      <div className="faint mt-1.5 flex justify-between text-[10px]"><span>{t('heat.weeks_back', { n: cols })}</span><span>{t('common.today')}</span></div>
      {/* озвучка для клавиатуры и скринридера: подсказку слышно, а не только видно */}
      <span id={tip.id} className="sr-only" aria-live="polite">{cur != null ? label(cell(cur)) : ''}</span>
      {tip.panel({ 'aria-hidden': 'true', title: cur != null ? label(cell(cur)) : null })}
    </div>
  )
}

export function Streak({ streak }) {
  const { t } = useI18n()
  if (!streak) return null
  const hot = streak.current >= 3
  return (
    <div className="flex items-center gap-3">
      <div className={`grid h-12 w-12 place-items-center rounded-full ${hot ? 'bg-accent text-accent-ink' : 'fill'}`} style={hot ? { animation: 'breathe 2.4s ease-in-out infinite' } : {}}>
        <Flame size={20} strokeWidth={2.2} />
      </div>
      <div>
        <div className="num text-[26px] font-medium leading-none tracking-[-0.04em]">{streak.current}<span className="muted ml-1 text-[14px] font-normal">{t('streak.in_row', { count: streak.current })}</span></div>
        <div className="muted mt-1 text-[12px]">{t('streak.best', { n: streak.best })} · {streak.today_done ? t('streak.today_done') : t('streak.today_empty')}</div>
      </div>
    </div>
  )
}

/* ---------- Прогноз кассы на 30 дней ---------- */
export function Forecast({ f, compact = false, txs = null }) {
  const { t } = useI18n()
  // тот же CashChart, что и в «финансах»: точка = баланс на конец дня, подсказка в две строки
  const h = compact ? 120 : 170
  // высоту резервируем скелетом: когда данные приходят, график не «прыгает» вниз
  if (!f?.points?.length) return <Skeleton h={h} radius="var(--r-md)" className="my-3" />
  const dm = (s) => `${s.slice(8, 10)}.${s.slice(5, 7)}`
  const perDay = f.per_day ?? f.avg_day_spent
  const low = f.low ?? f.min_balance
  const lowDate = f.low_date ?? f.min_date
  const ok = f.ok ?? (low >= 0)
  return (
    <div>
      <CashChart f={f} height={h} compact={compact} txs={txs} />
      {!compact && (
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
          {perDay != null && <span className="muted">{t('fc.avg')} <b className="num" style={{ color: 'var(--ink)' }}>{money(perDay)}</b>{t('fc.per_day')}</span>}
          {f.safe_per_day != null && <span className="muted">{t('fc.safe')} <b className="num accent">{money(f.safe_per_day)}</b>{t('fc.safe_tail', { days: f.days_to_income })}</span>}
          {low != null && <span className={ok ? 'muted' : 'neg font-medium'}>{ok ? t('fc.min', { m: money(low) }) : t('fc.minus', { m: money(low), date: dm(lowDate) })}</span>}
        </div>
      )}
    </div>
  )
}

/* ---------- Дни рождения ---------- */
export function Birthdays({ list }) {
  const { t } = useI18n()
  if (!list?.length) return null
  const when = (n) => (n === 0 ? t('bday.today') : n === 1 ? t('bday.tomorrow') : t('bday.in_days', { count: n }))
  return (
    <div className="flex flex-wrap gap-2">
      {list.map((b) => (
        <Link to="/calendar" key={b.id} className="chip !py-1.5 flex items-center gap-1.5 hover:text-accent" style={{ animation: 'rise .4s ease-out both' }}>
          <Cake size={13} /> {b.who} · {when(b.in_days)}
        </Link>
      ))}
    </div>
  )
}

/* ---------- Импорт выписки (CSV/PDF/XLSX Т-Банка) ---------- */
export function ImportButton({ onDone, onErr, className = '' }) {
  const { t } = useI18n()
  const inp = useRef(null)
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)
  const upload = async (file) => {
    if (!file) return
    setBusy(true)
    try {
      const fd = new FormData(); fd.append('file', file)
      const r = await fetch('/api/finance/import', { method: 'POST', body: fd })
      const j = await r.json()
      if (!r.ok) throw new Error(j.detail || T('import.failed'))
      onDone?.(j)
    } catch (e) { onErr?.(e) } finally { setBusy(false); if (inp.current) inp.current.value = '' }
  }
  return (
    <span className={className} onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files?.[0]) }}>
      <input ref={inp} type="file" accept=".csv,.pdf,.xlsx,.xls,.txt" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
      <button className={`btn-ghost ${drag ? '!border-accent text-accent' : ''}`} disabled={busy} onClick={() => inp.current?.click()} title={t('import.hint')}>
        <Upload size={14} /> {busy ? t('import.reading') : drag ? t('import.drop') : t('import.button')}
      </button>
    </span>
  )
}

/* ---------- Перетаскиваемые секции «Сегодня» ---------- */
export function useOrder(key, ids) {
  const [order, setOrder] = useState(() => {
    try { const s = JSON.parse(localStorage.getItem(key) || 'null'); if (Array.isArray(s)) return [...s.filter((x) => ids.includes(x)), ...ids.filter((x) => !s.includes(x))] } catch {}
    return ids
  })
  useEffect(() => { localStorage.setItem(key, JSON.stringify(order)) }, [key, order])
  // ставим from на место to: при движении вперёд — после него, назад — перед ним
  const move = (from, to) => setOrder((o) => { const a = [...o]; const i = a.indexOf(from), j = a.indexOf(to); if (i < 0 || j < 0 || i === j) return o; a.splice(i, 1); a.splice(j, 0, from); return a })
  return [order, move, () => setOrder(ids)]
}

export function Draggable({ id, onMove, children, className = '', disabled = false }) {
  const [over, setOver] = useState(false)
  const [dragging, setDragging] = useState(false)
  if (disabled) return <div className={className}>{children}</div>
  return (
    <div className={`${className} transition-all duration-300 ${dragging ? 'opacity-40' : ''} ${over ? '!outline-[var(--accent)] !outline-2' : ''}`}
      draggable onDragStart={(e) => { e.dataTransfer.setData('text/widget', id); e.dataTransfer.effectAllowed = 'move'; setDragging(true) }}
      onDragEnd={() => setDragging(false)}
      onDragOver={(e) => { if (e.dataTransfer.types.includes('text/widget')) { e.preventDefault(); setOver(true) } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const from = e.dataTransfer.getData('text/widget'); if (from && from !== id) onMove(from, id) }}>
      {children}
    </div>
  )
}
