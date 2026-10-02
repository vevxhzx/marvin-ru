import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../lib/api'
import { Section } from './ui'
import { useI18n, t as T } from '../lib/i18n'

/* Экранное время: сколько и где за ПК сегодня. Данные — от voice.bat (пульс раз в 20 с), только имя программы и сайт.
   Свернуто: итог + полоска дня по часам + топ-3. Развёрнуто: все программы с долями и подходы «сел/ушёл». */
const CAT_COLOR = { работа: 'var(--accent)', медиа: '#e0703a', общение: '#7c6bd6', браузер: '#5b8bd6', игра: '#d64b6b', прочее: 'var(--ink-3)' }
const CAT_PAIR = { работа: ['#5b8bff', '#0a3cff'], медиа: ['#ffb15c', '#e0703a'], общение: ['#a98cff', '#7c6bd6'], браузер: ['#8fb8ff', '#5b8bd6'], игра: ['#ff7d99', '#d64b6b'], прочее: ['#b9bcc6', '#8b8e98'] }
const catGrad = (cat, deg = 180) => { const [a, b] = CAT_PAIR[cat] || CAT_PAIR.прочее; return `linear-gradient(${deg}deg, ${a}, ${b})` }
/* Ключи категорий приходят с сервера по-русски и в интерфейс не показываются напрямую (см. t.sv) */
const DEF_CAT = 'работа' // i18n-raw
const fmt = (m) => { m = Math.round(m); if (m < 60) return `${m} ${T('unit.min')}`; const h = Math.floor(m / 60), r = m % 60; return r ? `${h} ${T('unit.hour')} ${String(r).padStart(2, '0')}` : `${h} ${T('unit.hour')}` }
const hm = (iso) => iso.slice(11, 16)

export default function ScreenTime({ tick, calm }) {
  const { t } = useI18n()
  const [d, setD] = useState(null)
  const [days, setDays] = useState(1)
  const [open, setOpen] = useState(false)
  useEffect(() => { api.get(`/api/screen?days=${days}`).then(setD).catch(() => setD(null)) }, [tick, days])
  if (!d) return null
  if (!d.recording) {
    return (
      <Section title={t('screen.title')}>
        <div className="muted text-[13px] leading-snug">{t('screen.off_hint')}</div>
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
    <Section title={t('screen.title')} idx={total ? fmt(total) : undefined}
      action={<div className="flex gap-1">{[[1, 'screen.today'], [7, 'screen.week']].map(([n, l]) => <button key={n} className={`btn-ghost btn-sm ${days === n ? 'text-accent' : ''}`} onClick={() => setDays(n)}>{t(l)}</button>)}</div>}>
      {!total ? (
        <div className="muted text-[13px]">{d.pc_alive ? t('screen.empty_live') : t('screen.empty_dead')}</div>
      ) : (
        <div className="space-y-3">
          {days === 1 && range.length > 0 && (
            <div>
              <div className="flex h-7 items-end gap-[3px]" aria-label={t('screen.by_hours')}>
                {range.map(({ v, h }) => (
                  <div key={h} className="flex-1 rounded-[3px]" title={`${h}:00 — ${fmt(v)}`}
                    style={{ height: `${v >= 3 ? Math.max(14, (v / maxHour) * 100) : 4}%`, background: v >= 3 ? catGrad(d.hour_cats?.[h] || DEF_CAT) : 'var(--line-2)', opacity: v >= 3 ? 0.5 + 0.5 * (v / maxHour) : 1 }} />
                ))}
              </div>
              <div className="faint mt-1 flex justify-between text-[11px] num"><span>{range[0].h}:00</span>{d.first && <span>{t('screen.sat_at', { time: hm(d.first) })}{d.sessions.length > 1 ? ` · ${t('screen.sessions', { count: d.sessions.length })}` : ''}</span>}<span>{range[range.length - 1].h + 1}:00</span></div>
            </div>
          )}
          <ul className="space-y-1.5">
            {shown.map(([name, mins, cat, sub]) => (
              <li key={name + sub} className="text-[13.5px]">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: CAT_COLOR[cat] || CAT_COLOR.прочее }} /><span className="truncate">{name}</span>{sub && sub !== name && <span className="faint truncate text-[12px]">{sub}</span>}</span>
                  <span className="num shrink-0 font-medium">{fmt(mins)}</span>
                </div>
                {!calm && <div className="mt-1 h-[3px] w-full rounded-full" style={{ background: 'var(--line-2)' }}><div className="h-full rounded-full" style={{ width: `${Math.max(2, (mins / total) * 100)}%`, background: catGrad(cat, 90) }} /></div>}
              </li>
            ))}
          </ul>
          {open && d.sessions.length > 0 && days === 1 && (
            <div className="muted text-[12.5px]">{t('screen.sessions_label')} {d.sessions.map(([a, b]) => `${hm(a)}–${hm(b)}`).join(', ')}{d.idle_min ? ` · ${t('screen.away', { m: fmt(d.idle_min) })}` : ''}</div>
          )}
          {open && d.cats && (
            <div className="faint flex flex-wrap gap-x-3 gap-y-1 text-[12px]">{Object.entries(d.cats).map(([c, m]) => <span key={c} className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full" style={{ background: CAT_COLOR[c] || CAT_COLOR.прочее }} />{t.sv(c) || c} {fmt(m)}</span>)}</div>
          )}
          {top.length > 3 && <button className="faint flex items-center gap-1 text-[12px] hover:text-accent" onClick={() => setOpen((v) => !v)}>{open ? <><ChevronUp size={12} /> {t('screen.collapse')}</> : <><ChevronDown size={12} /> {t('screen.more_and_sessions', { n: top.length - 3 })}</>}</button>}
        </div>
      )}
    </Section>
  )
}
