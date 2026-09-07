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
      <div className={`grid h-12 w-12 place-items-center rounded-full ${hot ? 'bg-accent text-white' : 'fill'}`} style={hot ? { animation: 'breathe 2.4s ease-in-out infinite' } : {}}>
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
  if (!f?.points?.length) return null
  const pts = f.points
  const W = 600, H = compact ? 90 : 140, P = 6
  const min = Math.min(0, ...pts.map((p) => p.balance)), max = Math.max(1, ...pts.map((p) => p.balance))
  const x = (i) => P + (i / (pts.length - 1)) * (W - 2 * P)
  const y = (v) => P + (1 - (v - min) / (max - min || 1)) * (H - 2 * P)
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.balance).toFixed(1)}`).join(' ')
  const zero = y(0)
  const [hover, setHover] = useState(null)
  const ev = pts.map((p, i) => ({ ...p, i })).filter((p) => p.events.length)
  const lowIdx = pts.findIndex((p) => p.date === f.low_date)
  return (
    <div>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }} onMouseLeave={() => setHover(null)}
          onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHover(Math.round(((e.clientX - r.left) / r.width) * (pts.length - 1))) }}>
          <defs><linearGradient id="fcg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="var(--accent)" stopOpacity=".22" /><stop offset="1" stopColor="var(--accent)" stopOpacity="0" /></linearGradient></defs>
          {min < 0 && <line x1={P} x2={W - P} y1={zero} y2={zero} stroke="var(--neg)" strokeDasharray="3 4" strokeWidth="1" />}
          <path d={`${d} L${x(pts.length - 1)},${H - P} L${x(0)},${H - P} Z`} fill="url(#fcg)" />
          <path d={d} fill="none" stroke={f.ok ? 'var(--accent)' : 'var(--neg)'} strokeWidth="2" strokeLinejoin="round" style={{ strokeDasharray: 2000, strokeDashoffset: 2000, animation: 'draw 1.4s cubic-bezier(.2,.8,.2,1) forwards' }} />
          {ev.map((p) => <circle key={p.i} cx={x(p.i)} cy={y(p.balance)} r="3.5" fill={p.events.some((e) => e.amount > 0) ? 'var(--green, #30d158)' : 'var(--ink)'} stroke="var(--bg)" strokeWidth="1.5" />)}
          {lowIdx >= 0 && !f.ok && <circle cx={x(lowIdx)} cy={y(pts[lowIdx].balance)} r="4" fill="var(--neg)" />}
          {hover != null && <line x1={x(hover)} x2={x(hover)} y1={P} y2={H - P} stroke="var(--ink-3)" strokeWidth="1" />}
        </svg>
        {hover != null && pts[hover] && (
          <div className="panel pointer-events-none absolute top-0 !px-2.5 !py-1.5 text-[12px] shadow-md" style={{ left: `${(hover / (pts.length - 1)) * 100}%`, transform: `translateX(${hover > pts.length / 2 ? '-105%' : '5%'})` }}>
            <div className="muted">{pts[hover].date.slice(8, 10)}.{pts[hover].date.slice(5, 7)}</div>
            <div className={`num font-medium ${pts[hover].balance < 0 ? 'neg' : ''}`}>{money(pts[hover].balance)}</div>
            {pts[hover].events.map((e, i) => <div key={i} className="muted truncate">{e.amount > 0 ? '+' : '−'}{money(Math.abs(e.amount))} {e.title}</div>)}
          </div>
        )}
      </div>
      {!compact && (
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
          <span className="muted">в среднем <b className="num" style={{ color: 'var(--ink)' }}>{money(f.per_day)}</b>/день</span>
          {f.safe_per_day != null && <span className="muted">безопасно <b className="num accent">{money(f.safe_per_day)}</b>/день до дохода ({f.days_to_income} дн)</span>}
          <span className={f.ok ? 'muted' : 'neg font-medium'}>{f.ok ? `минимум ${money(f.low)}` : `минус ${money(f.low)} к ${f.low_date.slice(8, 10)}.${f.low_date.slice(5, 7)}`}</span>
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
  const move = (from, to) => setOrder((o) => { const a = [...o]; const [x] = a.splice(a.indexOf(from), 1); a.splice(a.indexOf(to), 0, x); return a })
  return [order, move, () => setOrder(ids)]
}

export function Draggable({ id, onMove, children, className = '' }) {
  const [over, setOver] = useState(false)
  const [dragging, setDragging] = useState(false)
  return (
    <div className={`${className} transition-all duration-300 ${dragging ? 'scale-[.98] opacity-40' : ''} ${over ? 'ring-2 ring-accent/40 rounded-2xl' : ''}`}
      draggable onDragStart={(e) => { e.dataTransfer.setData('text/widget', id); e.dataTransfer.effectAllowed = 'move'; setDragging(true) }}
      onDragEnd={() => setDragging(false)}
      onDragOver={(e) => { if (e.dataTransfer.types.includes('text/widget')) { e.preventDefault(); setOver(true) } }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const from = e.dataTransfer.getData('text/widget'); if (from && from !== id) onMove(from, id) }}>
      {children}
    </div>
  )
}
