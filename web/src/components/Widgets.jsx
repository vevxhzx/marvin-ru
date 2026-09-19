import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Flame, Upload, Cake } from 'lucide-react'
import { api, money } from '../lib/api'

/* ---------- Тепловая карта активности (как на GitHub) + стрик ---------- */
export function Heatmap({ days = [], heatmap = [], weeks = 26 }) {
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
  const [tip, setTip] = useState(null)
  return (
    <div className="relative">
      <div className="grid gap-[3px]" style={{ gridTemplateRows: 'repeat(7, 10px)', gridAutoFlow: 'column', gridAutoColumns: '10px' }}>
        {cells.map((c, i) => {
          const a = c.n ? 0.25 + 0.75 * Math.min(1, Math.log1p(c.n) / Math.log1p(max)) : 0
          return <span key={c.k} onMouseEnter={() => setTip(c)} onMouseLeave={() => setTip(null)}
            className="rounded-[2px] transition-transform hover:scale-125" style={{ background: a ? `color-mix(in srgb, var(--accent) ${Math.round(a * 100)}%, var(--fill))` : 'var(--fill)', animation: `fade .4s ease-out ${Math.min(600, i * 2)}ms both` }} />
        })}
      </div>
      <div className="faint mt-1.5 flex justify-between text-[10px]"><span>{cols} нед. назад</span><span>сегодня</span></div>
      {tip && <div className="panel absolute -top-9 left-0 !px-2.5 !py-1 text-[11px] shadow-md">{tip.day}.{String(tip.m + 1).padStart(2, '0')} · {tip.n ? `${tip.n} зап.` : 'пусто'}</div>}
    </div>
  )
}

export function Streak({ streak }) {
  if (!streak) return null
  const hot = streak.current >= 3
  return (
    <div className="flex items-center gap-3">
      <div className={`grid h-12 w-12 place-items-center rounded-full ${hot ? 'bg-accent text-accent-ink' : 'fill'}`} style={hot ? { animation: 'breathe 2.4s ease-in-out infinite' } : {}}>
        <Flame size={20} strokeWidth={2.2} />
      </div>
      <div>
        <div className="num text-[26px] font-medium leading-none tracking-[-0.04em]">{streak.current}<span className="muted ml-1 text-[14px] font-normal">{plural(streak.current)} подряд</span></div>
        <div className="muted mt-1 text-[12px]">рекорд {streak.best} · {streak.today_done ? 'сегодня уже записали ✓' : 'сегодня пока пусто'}</div>
      </div>
    </div>
  )
}
const plural = (n) => { const a = n % 100, b = n % 10; return a > 10 && a < 20 ? 'дней' : b === 1 ? 'день' : b > 1 && b < 5 ? 'дня' : 'дней' }

/* ---------- Прогноз кассы на 30 дней ---------- */
export function Forecast({ f, compact = false }) {
  // хук — до раннего выхода: иначе при появлении данных менялся порядок хуков и React ронял страницу
  const [hover, setHover] = useState(null)
  if (!f?.points?.length) return null
  const pts = f.points
  // svg растягивается на всю ширину контейнера (preserveAspectRatio="none"), поэтому координаты X — в процентах,
  // а не в пикселях viewBox: раньше при широком окне график сжимался в середину, а курсор/подсказка считались по всему блоку
  const W = 1000, H = compact ? 90 : 160, P = 6
  const min = Math.min(0, ...pts.map((p) => p.balance)), max = Math.max(1, ...pts.map((p) => p.balance))
  const x = (i) => P + (i / (pts.length - 1)) * (W - 2 * P)
  const y = (v) => P + (1 - (v - min) / (max - min || 1)) * (H - 2 * P)
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.balance).toFixed(1)}`).join(' ')
  const zero = y(0)
  const ev = pts.map((p, i) => ({ ...p, i })).filter((p) => p.events.length)
  const lowIdx = pts.findIndex((p) => p.date === f.low_date)
  const cur = hover != null ? pts[hover] : null
  const dm = (s) => `${s.slice(8, 10)}.${s.slice(5, 7)}`
  // подсказка живёт в отдельной строке над графиком и никогда его не закрывает
  const first = pts[0]
  return (
    <div>
      <div className={`flex items-baseline gap-x-3 text-[12.5px] ${compact ? 'h-5' : 'h-6'}`} aria-live="polite">
        {cur ? (
          <>
            <span className="muted num">{dm(cur.date)}</span>
            <span className={`num font-medium ${cur.balance < 0 ? 'neg' : ''}`}>{money(cur.balance)}</span>
            {cur.events.slice(0, 3).map((e, i) => <span key={i} className={`truncate ${e.amount > 0 ? 'pos' : 'muted'}`}>{e.amount > 0 ? '+' : '−'}{money(Math.abs(e.amount))} {e.title}</span>)}
          </>
        ) : (
          <>
            <span className="muted num">сегодня</span>
            <span className="num font-medium">{money(first.balance)}</span>
            <span className="faint">наведите на график — покажу день</span>
          </>
        )}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="mt-1 block w-full cursor-crosshair" style={{ height: H }} onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHover(Math.max(0, Math.min(pts.length - 1, Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1))))) }}
        onTouchStart={(e) => { const r = e.currentTarget.getBoundingClientRect(); const t = e.touches[0]; setHover(Math.max(0, Math.min(pts.length - 1, Math.round(((t.clientX - r.left) / r.width) * (pts.length - 1))))) }}
        onTouchMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); const t = e.touches[0]; setHover(Math.max(0, Math.min(pts.length - 1, Math.round(((t.clientX - r.left) / r.width) * (pts.length - 1))))) }}>
        <defs><linearGradient id="fcg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="var(--accent)" stopOpacity=".22" /><stop offset="1" stopColor="var(--accent)" stopOpacity="0" /></linearGradient></defs>
        {min < 0 && <line x1={P} x2={W - P} y1={zero} y2={zero} stroke="var(--neg)" strokeDasharray="3 4" strokeWidth="1" vectorEffect="non-scaling-stroke" />}
        <path d={`${d} L${x(pts.length - 1)},${H - P} L${x(0)},${H - P} Z`} fill="url(#fcg)" />
        <path d={d} fill="none" stroke={f.ok ? 'var(--accent)' : 'var(--neg)'} strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" style={{ strokeDasharray: 3000, strokeDashoffset: 3000, animation: 'draw 1.4s cubic-bezier(.2,.8,.2,1) forwards' }} />
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={P} y2={H - P} stroke="var(--ink-3)" strokeWidth="1" vectorEffect="non-scaling-stroke" />}
      </svg>
      {/* точки — отдельным слоем поверх растянутого svg, иначе круги превращаются в овалы */}
      <div className="pointer-events-none relative" style={{ height: 0 }}>
        {ev.map((p) => <span key={p.i} className="absolute h-[9px] w-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full border-[1.5px] border-[var(--bg)]" style={{ left: `${(x(p.i) / W) * 100}%`, top: `${y(p.balance) - H}px`, background: p.events.some((e) => e.amount > 0) ? 'var(--green, #30d158)' : 'var(--ink)' }} />)}
        {lowIdx >= 0 && !f.ok && <span className="absolute h-[9px] w-[9px] -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${(x(lowIdx) / W) * 100}%`, top: `${y(pts[lowIdx].balance) - H}px`, background: 'var(--neg)' }} />}
        {cur && <span className="absolute h-[11px] w-[11px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[var(--bg)]" style={{ left: `${(x(hover) / W) * 100}%`, top: `${y(cur.balance) - H}px`, background: cur.balance < 0 ? 'var(--neg)' : 'var(--accent)' }} />}
      </div>
      <div className="faint mt-1 flex justify-between text-[11px] num"><span>{dm(pts[0].date)}</span><span>{dm(pts[Math.floor((pts.length - 1) / 2)].date)}</span><span>{dm(pts[pts.length - 1].date)}</span></div>
      {!compact && (
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
          <span className="muted">в среднем <b className="num" style={{ color: 'var(--ink)' }}>{money(f.per_day)}</b>/день</span>
          {f.safe_per_day != null && <span className="muted">безопасно <b className="num accent">{money(f.safe_per_day)}</b>/день до дохода ({f.days_to_income} дн)</span>}
          <span className={f.ok ? 'muted' : 'neg font-medium'}>{f.ok ? `минимум ${money(f.low)}` : `минус ${money(f.low)} к ${dm(f.low_date)}`}</span>
        </div>
      )}
    </div>
  )
}

/* ---------- Дни рождения ---------- */
export function Birthdays({ list }) {
  if (!list?.length) return null
  return (
    <div className="flex flex-wrap gap-2">
      {list.map((b) => (
        <Link to="/calendar" key={b.id} className="chip !py-1.5 flex items-center gap-1.5 hover:text-accent" style={{ animation: 'rise .4s ease-out both' }}>
          <Cake size={13} /> {b.who} · {b.in_days === 0 ? 'сегодня!' : b.in_days === 1 ? 'завтра' : `через ${b.in_days} дн`}
        </Link>
      ))}
    </div>
  )
}

/* ---------- Импорт выписки (CSV/PDF/XLSX Т-Банка) ---------- */
export function ImportButton({ onDone, onErr, className = '' }) {
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
      if (!r.ok) throw new Error(j.detail || 'ошибка импорта')
      onDone?.(j)
    } catch (e) { onErr?.(e) } finally { setBusy(false); if (inp.current) inp.current.value = '' }
  }
  return (
    <span className={className} onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files?.[0]) }}>
      <input ref={inp} type="file" accept=".csv,.pdf,.xlsx,.xls,.txt" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
      <button className={`btn-ghost ${drag ? '!border-accent text-accent' : ''}`} disabled={busy} onClick={() => inp.current?.click()} title="Выписка Т-Банка: CSV, PDF или Excel. Можно перетащить файл сюда. Дубликаты не задваиваются.">
        <Upload size={14} /> {busy ? 'читаю…' : drag ? 'отпускайте' : 'выписка'}
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
