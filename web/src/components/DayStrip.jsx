import { useEffect, useState } from 'react'
import { hhmm, isAllDay } from '../lib/api'
import { useI18n, t as T } from '../lib/i18n'

/* Лента дня: одна тонкая линия времени, на ней точками — события/задачи/дедлайны с их временем, полосками — длительность,
   между соседними подписан промежуток («1 ч 40»), засечка — «сейчас». Видно, как день расставлен и сколько
   между делами, не читая список. Дела «на весь день» в ленту не ложатся — считаются отдельно подписью.

   Поверхность и цвет — только токены (--sf2/--line-2/--accent/--warn/--neg/--ai), поэтому лента одинаково
   читается в обеих темах. Подписи и точки позиционируются от краёв так, чтобы ничего не уезжало
   за пределы полосы: горизонтальной прокрутки страницы лента не создаёт.
   Зоны нажатия — --tap (кнопка точки), анимируется только transform. */

// gapText живёт на уровне модуля, поэтому перевод берём из импорта (T), а не из хука
const gapText = (m) => (m < 60 ? `${m} ${T('unit.min')}` : m % 60 ? `${Math.floor(m / 60)} ${T('unit.hour')} ${m % 60}` : `${m / 60} ${T('unit.hour')}`)

/* левая координата в процентах с отступом от краёв: подпись/кнопка не должна вылезти за полосу */
const inside = (pct, inset) => `clamp(${inset}px, ${pct.toFixed(3)}%, calc(100% - ${inset}px))`

/* цвет по смыслу события: задача — текстовый тон, просроченная — красный, заказ — янтарь, событие — акцент */
const tone = (e) => (e.kind === 'task' ? (e.priority === 1 ? 'var(--neg)' : 'var(--ink-2)') : e.kind === 'order' ? 'var(--warn)' : 'var(--accent)')
const toneGrad = (e) => {
  if (e.kind === 'task') {
    return e.priority === 1
      ? 'linear-gradient(90deg, var(--neg), color-mix(in srgb, var(--neg) 55%, var(--amber)))'
      : 'linear-gradient(90deg, var(--ink-3), color-mix(in srgb, var(--ink-3) 45%, var(--sf2)))'
  }
  if (e.kind === 'order') return 'linear-gradient(90deg, var(--amber), color-mix(in srgb, var(--amber) 55%, var(--neg)))'
  return 'linear-gradient(90deg, var(--accent), var(--ai))'
}

export default function DayStrip({ list, isToday, onPick }) {
  const { t } = useI18n()
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
    if (b - a >= 20 && x(b) - x(a) >= 8) gaps.push({ at: (x(a) + x(b)) / 2, text: gapText(b - a) })
  }
  // точки, стоящие вплотную, чуть разводим по вертикали
  let prevX = -10, lane = 0
  const dots = timed.map((e) => {
    const px = x(min(e.start))
    lane = px - prevX < 2.6 ? (lane + 1) % 2 : 0
    prevX = px
    const past = nowMin != null && endOf(e) < nowMin
    const live = nowMin != null && !e.done && min(e.start) <= nowMin && endOf(e) >= nowMin && endOf(e) > min(e.start)
    return { e, px, wx: x(endOf(e)) - px, lane, past, live }
  })

  return (
    <div className="animate-rise select-none pt-0.5" aria-label={t('daystrip.aria')}>
      <div className="relative mx-2 h-[60px]">
        {/* часы: подпись прижата к краю, если час самый первый или самый последний */}
        {hours.map((h) => {
          const p = x(h * 60)
          const tx = p < 3 ? '0%' : p > 97 ? '-100%' : '-50%'
          return (
            <span key={h}>
              <span className="num faint absolute top-0 whitespace-nowrap" style={{ left: `${p}%`, transform: `translateX(${tx})`, fontSize: 'var(--fs-xs)' }}>
                {h % step === 0 ? h : ''}
              </span>
              <span className="absolute top-[17px] h-[6px] w-px" style={{ left: `${p}%`, transform: 'translateX(-50%)', background: 'var(--line-2)', opacity: h % step === 0 ? 1 : 0.5 }} />
            </span>
          )
        })}
        {/* линия времени */}
        <div className="absolute left-0 right-0 top-[27px] h-px" style={{ background: 'var(--line-2)' }} />
        {/* длительность */}
        {dots.filter((d) => d.wx > 0.4).map((d) => (
          <span key={`w${d.e.id}${d.e.start}`} className="absolute top-[25px] h-[5px] rounded-full"
            style={{ left: `${d.px}%`, width: `${d.wx}%`, background: toneGrad(d.e), opacity: d.past || d.e.done ? 0.2 : 0.38 }} />
        ))}
        {/* точки: зона нажатия — --tap, сама точка маленькая */}
        {dots.map((d) => (
          <button key={`${d.e.id}${d.e.start}`} type="button" onClick={() => onPick?.(d.e)}
            aria-label={`${hhmm(d.e.start)} ${d.e.title}`} title={`${hhmm(d.e.start)} · ${d.e.title}`}
            className="absolute grid h-[var(--tap)] w-[var(--tap)] -translate-x-1/2 -translate-y-1/2 place-items-center transition-transform duration-200 hover:scale-105 active:scale-95"
            style={{ left: inside(d.px, 22), top: `${27 + (d.lane ? 9 : 0)}px`, opacity: d.past || d.e.done ? 0.4 : 1 }}>
            <span className={`block rounded-full ${d.live ? 'h-[11px] w-[11px] ring-2' : 'h-[8px] w-[8px]'}`}
              style={{ background: d.e.done ? 'transparent' : tone(d.e), boxShadow: d.e.done ? `inset 0 0 0 2px ${tone(d.e)}` : undefined, '--tw-ring-color': 'var(--pos)', '--tw-ring-offset-color': 'var(--bg)' }} />
          </button>
        ))}
        {/* сейчас */}
        {nowMin != null && (
          <span className="absolute top-[18px] -translate-x-1/2" style={{ left: `${x(nowMin)}%` }}>
            <span className="neg num absolute top-[-16px] whitespace-nowrap font-medium" style={{ left: x(nowMin) < 8 ? 0 : undefined, right: x(nowMin) > 92 ? 0 : undefined, transform: x(nowMin) < 8 ? 'none' : x(nowMin) > 92 ? 'none' : 'translateX(-50%)', fontSize: 'var(--fs-xs)' }}>{hhmm(now)}</span>
            <span className="block h-[19px] w-[2px] rounded-full" style={{ background: 'var(--neg)' }} />
          </span>
        )}
        {/* промежутки между делами */}
        {gaps.map((g, i) => (
          <span key={i} className="faint num absolute top-[40px] -translate-x-1/2 whitespace-nowrap" style={{ left: inside(g.at, 26), fontSize: 'var(--fs-xs)' }}>{g.text}</span>
        ))}
      </div>
      {allDay > 0 && <div className="faint mt-0.5" style={{ fontSize: 'var(--fs-xs)' }}>{t('daystrip.all_day', { count: allDay })}</div>}
    </div>
  )
}