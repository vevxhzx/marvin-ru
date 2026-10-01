import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Flame, Upload, Cake } from 'lucide-react'
import { api, money } from '../lib/api'
import CashChart from './CashChart'

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
export function Forecast({ f, compact = false, txs = null }) {
  // тот же CashChart, что и в «финансах»: точка = баланс на конец дня, подсказка в две строки
  if (!f?.points?.length) return null
  const dm = (s) => `${s.slice(8, 10)}.${s.slice(5, 7)}`
  const perDay = f.per_day ?? f.avg_day_spent
  const low = f.low ?? f.min_balance
  const lowDate = f.low_date ?? f.min_date
  const ok = f.ok ?? (low >= 0)
  return (
    <div>
      <CashChart f={f} height={compact ? 120 : 170} compact={compact} txs={txs} />
      {!compact && (
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
          {perDay != null && <span className="muted">в среднем <b className="num" style={{ color: 'var(--ink)' }}>{money(perDay)}</b>/день</span>}
          {f.safe_per_day != null && <span className="muted">безопасно <b className="num accent">{money(f.safe_per_day)}</b>/день до дохода ({f.days_to_income} дн)</span>}
          {low != null && <span className={ok ? 'muted' : 'neg font-medium'}>{ok ? `минимум ${money(low)}` : `минус ${money(low)} к ${dm(lowDate)}`}</span>}
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
