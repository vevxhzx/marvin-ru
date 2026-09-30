import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../lib/api'
import { Section } from './ui'

/* Экранное время: сколько и где за ПК сегодня. Данные — от voice.bat (пульс раз в 20 с), только имя программы и сайт.
   Свернуто: итог + полоска дня по часам + топ-3. Развёрнуто: все программы с долями и подходы «сел/ушёл». */
const CAT_COLOR = { работа: 'var(--accent)', медиа: '#e0703a', общение: '#7c6bd6', браузер: '#5b8bd6', игра: '#d64b6b', прочее: 'var(--ink-3)' }
const fmt = (m) => { m = Math.round(m); if (m < 60) return `${m} мин`; const h = Math.floor(m / 60), r = m % 60; return r ? `${h} ч ${String(r).padStart(2, '0')}` : `${h} ч` }
const hm = (iso) => iso.slice(11, 16)

export default function ScreenTime({ tick, calm }) {
  const [d, setD] = useState(null)
  const [days, setDays] = useState(1)
  const [open, setOpen] = useState(false)
  useEffect(() => { api.get(`/api/screen?days=${days}`).then(setD).catch(() => setD(null)) }, [tick, days])
  if (!d) return null
  if (!d.recording) {
    return (
      <Section title="время за пк">
        <div className="muted text-[13px] leading-snug">Выключено. Включить: настройки → голос и ПК → «экранное время» (пишется только имя программы и сайт, всё остаётся на ПК), затем перезапустить voice.bat.</div>
      </Section>
    )
  }
  const total = d.active_min
  const top = d.apps.filter((a) => a[1] >= 2)
  const shown = open ? top : top.slice(0, 3)
  const maxHour = Math.max(1, ...d.hours)
  const firstH = d.hours.findIndex((h) => h > 0)
  const lastH = d.hours.length - 1 - [...d.hours].reverse().findIndex((h) => h > 0)
  const range = firstH >= 0 ? d.hours.map((v, h) => ({ v, h })).filter(({ h }) => h >= Math.max(0, firstH - 1) && h <= Math.min(23, lastH + 1)) : []
  const catOf = (name) => (d.apps.find((a) => a[0] === name) || [])[2]
  return (
    <Section title="время за пк" idx={total ? fmt(total) : undefined}
      action={<div className="flex gap-1">{[[1, 'сегодня'], [7, 'неделя']].map(([n, l]) => <button key={n} className={`btn-ghost btn-sm ${days === n ? 'text-accent' : ''}`} onClick={() => setDays(n)}>{l}</button>)}</div>}>
      {!total ? (
        <div className="muted text-[13px]">{d.pc_alive ? 'Пока пусто — первые минуты за ПК ещё не набежали.' : 'Данных нет: voice.bat не запущен (пульс идёт от него).'}</div>
      ) : (
        <div className="space-y-3">
          {days === 1 && range.length > 0 && (
            <div>
              <div className="flex h-7 items-end gap-[3px]" aria-label="активность по часам">
                {range.map(({ v, h }) => (
                  <div key={h} className="flex-1 rounded-[3px]" title={`${h}:00 — ${fmt(v)}`}
                    style={{ height: `${v >= 3 ? Math.max(14, (v / maxHour) * 100) : 4}%`, background: v >= 3 ? CAT_COLOR[d.hour_cats?.[h]] || 'var(--accent)' : 'var(--line-2)', opacity: v >= 3 ? 0.45 + 0.55 * (v / maxHour) : 1 }} />
                ))}
              </div>
              <div className="faint mt-1 flex justify-between text-[11px] num"><span>{range[0].h}:00</span>{d.first && <span>сели в {hm(d.first)}{d.sessions.length > 1 ? ` · ${d.sessions.length} подхода` : ''}</span>}<span>{range[range.length - 1].h + 1}:00</span></div>
            </div>
          )}
          <ul className="space-y-1.5">
            {shown.map(([name, mins, cat, sub]) => (
              <li key={name + sub} className="text-[13.5px]">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: CAT_COLOR[cat] || CAT_COLOR.прочее }} /><span className="truncate">{name}</span>{sub && sub !== name && <span className="faint truncate text-[12px]">{sub}</span>}</span>
                  <span className="num shrink-0 font-medium">{fmt(mins)}</span>
                </div>
                {!calm && <div className="mt-1 h-[3px] w-full rounded-full" style={{ background: 'var(--line-2)' }}><div className="h-full rounded-full" style={{ width: `${Math.max(2, (mins / total) * 100)}%`, background: CAT_COLOR[cat] || CAT_COLOR.прочее }} /></div>}
              </li>
            ))}
          </ul>
          {open && d.sessions.length > 0 && days === 1 && (
            <div className="muted text-[12.5px]">Подходы: {d.sessions.map(([a, b]) => `${hm(a)}–${hm(b)}`).join(', ')}{d.idle_min ? ` · отходил ${fmt(d.idle_min)}` : ''}</div>
          )}
          {open && d.cats && (
            <div className="faint flex flex-wrap gap-x-3 gap-y-1 text-[12px]">{Object.entries(d.cats).map(([c, m]) => <span key={c} className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full" style={{ background: CAT_COLOR[c] || CAT_COLOR.прочее }} />{c} {fmt(m)}</span>)}</div>
          )}
          {top.length > 3 && <button className="faint flex items-center gap-1 text-[12px] hover:text-accent" onClick={() => setOpen((v) => !v)}>{open ? <><ChevronUp size={12} /> свернуть</> : <><ChevronDown size={12} /> ещё {top.length - 3} и подходы</>}</button>}
        </div>
      )}
    </Section>
  )
}
