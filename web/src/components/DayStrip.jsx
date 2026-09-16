import { useEffect, useState } from 'react'
import { hhmm, isAllDay, plural } from '../lib/api'

/* Лента дня: одна тонкая линия времени, на ней точками — события/задачи/дедлайны с их временем, полосками — длительность,
   между соседними подписан промежуток («1 ч 40»), красная засечка — «сейчас». Видно, как день расставлен и сколько
   между делами, не читая список. Дела «на весь день» в ленту не ложатся — считаются отдельно слева. */
const gapText = (m) => (m < 60 ? `${m} мин` : m % 60 ? `${Math.floor(m / 60)} ч ${m % 60}` : `${m / 60} ч`)

export default function DayStrip({ list, isToday, onPick }) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { if (!isToday) return; const t = setInterval(() => setNow(new Date()), 60000); return () => clearInterval(t) }, [isToday])
  const timed = list.filter((e) => !e.all_day && !isAllDay(e.start)).sort((a, b) => new Date(a.start) - new Date(b.start))
  const allDay = list.length - timed.length
  if (!timed.length) return null

  const day0 = new Date(timed[0].start); day0.setHours(0, 0, 0, 0)
  const min = (d) => Math.round((new Date(d) - day0) / 60000)
  const endOf = (e) => (e.end && new Date(e.end) > new Date(e.start) ? min(e.end) : min(e.start))
  const first = min(timed[0].start), last = Math.max(...timed.map(endOf))
  // окно: обычный день 7–22, растягивается под ранние/поздние дела (и под «сейчас»)
  let lo = Math.min(7 * 60, Math.floor(first / 60) * 60 - 60)
  let hi = Math.max(22 * 60, Math.ceil(last / 60) * 60 + 60)
  const nowMin = isToday ? min(now) : null
  if (nowMin != null) { lo = Math.min(lo, Math.floor(nowMin / 60) * 60); hi = Math.max(hi, Math.ceil(nowMin / 60) * 60 + 60) }
  lo = Math.max(0, lo); hi = Math.min(24 * 60, hi)
  const x = (m) => ((Math.min(hi, Math.max(lo, m)) - lo) / (hi - lo)) * 100
  const step = hi - lo > 12 * 60 ? 3 : 2   // подписи часов: каждые 3 ч на длинном окне, каждые 2 ч на коротком
  const hours = []
  for (let h = Math.ceil(lo / 60); h * 60 <= hi; h++) hours.push(h)

  // промежутки между соседними делами: подписываем, если есть куда поставить текст
  const gaps = []
  for (let i = 0; i < timed.length - 1; i++) {
    const a = endOf(timed[i]), b = min(timed[i + 1].start)
    if (b - a >= 20 && x(b) - x(a) >= 6) gaps.push({ at: (x(a) + x(b)) / 2, text: gapText(b - a) })
  }
  // точки, стоящие вплотную, чуть разводим по вертикали
  let prevX = -10, lane = 0
  const dots = timed.map((e) => {
    const px = x(min(e.start))
    lane = px - prevX < 2.2 ? (lane + 1) % 2 : 0
    prevX = px
    const past = nowMin != null && endOf(e) < nowMin
    const live = nowMin != null && !e.done && min(e.start) <= nowMin && endOf(e) >= nowMin && endOf(e) > min(e.start)
    return { e, px, wx: x(endOf(e)) - px, lane, past, live }
  })
  const tone = (e) => (e.kind === 'task' ? (e.priority === 1 ? 'var(--neg)' : 'var(--ink)') : e.kind === 'order' ? 'var(--warn)' : 'var(--accent)')

  return (
    <div className="animate-rise select-none pb-1 pt-0.5" aria-label="лента дня">
      <div className="relative mx-1 h-[56px]">
        {/* часы */}
        {hours.map((h) => (
          <span key={h} className="absolute top-0 -translate-x-1/2" style={{ left: `${x(h * 60)}%` }}>
            {h % step === 0 && <span className="faint num text-[10.5px]">{h}</span>}
            <span className="absolute left-1/2 top-[16px] h-[6px] w-px -translate-x-1/2" style={{ background: 'var(--line-2)', opacity: h % step === 0 ? 1 : .5 }} />
          </span>
        ))}
        {/* линия */}
        <div className="absolute left-0 right-0 top-[27px] h-px" style={{ background: 'var(--line-2)' }} />
        {/* длительность */}
        {dots.filter((d) => d.wx > 0.4).map((d) => (
          <span key={`w${d.e.id}${d.e.start}`} className="absolute top-[25px] h-[5px] rounded-full" style={{ left: `${d.px}%`, width: `${d.wx}%`, background: tone(d.e), opacity: d.past || d.e.done ? .18 : .32 }} />
        ))}
        {/* точки */}
        {dots.map((d) => (
          <button key={`${d.e.id}${d.e.start}`} type="button" onClick={() => onPick?.(d.e)} aria-label={`${hhmm(d.e.start)} ${d.e.title}`}
            className="absolute grid h-[18px] w-[18px] -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full transition-transform hover:scale-125"
            style={{ left: `${d.px}%`, top: `${27 + (d.lane ? 9 : 0)}px`, opacity: d.past || d.e.done ? .35 : 1 }}>
            {/* data-tip ставит position:relative — поэтому он на внутреннем span, а не на самой кнопке */}
            <span data-tip={`${hhmm(d.e.start)} · ${d.e.title}`} className={`block rounded-full ${d.live ? 'h-[11px] w-[11px] ring-2 ring-offset-2' : 'h-[8px] w-[8px]'}`}
              style={{ background: d.e.done ? 'transparent' : tone(d.e), boxShadow: d.e.done ? `inset 0 0 0 2px ${tone(d.e)}` : undefined, '--tw-ring-color': 'var(--pos)', '--tw-ring-offset-color': 'var(--bg)' }} />
          </button>
        ))}
        {/* сейчас */}
        {nowMin != null && (
          <span className="absolute top-[18px] -translate-x-1/2" style={{ left: `${x(nowMin)}%` }}>
            <span className="block h-[19px] w-[2px] rounded-full" style={{ background: 'var(--neg)' }} />
            <span className="neg num absolute left-1/2 top-[-15px] -translate-x-1/2 text-[10.5px] font-medium">{hhmm(now)}</span>
          </span>
        )}
        {/* промежутки */}
        {gaps.map((g, i) => <span key={i} className="faint num absolute top-[40px] -translate-x-1/2 whitespace-nowrap text-[10.5px]" style={{ left: `${g.at}%` }}>{g.text}</span>)}
      </div>
      {allDay > 0 && <div className="faint mt-0.5 text-[11px]">+ {allDay} {plural(allDay, 'дело', 'дела', 'дел')} на весь день</div>}
    </div>
  )
}
