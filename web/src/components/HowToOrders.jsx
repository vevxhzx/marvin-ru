// Подсказка «Как это работает» на странице заказов: 3 шага + схема воронки.
// Показывается при ПЕРВОМ заходе (метка в localStorage), потом свёрнута и открывается кнопкой «?».
// Кнопка «?» в шапке страницы тоже её открывает — через событие window 'orders:howto'.
import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, HelpCircle } from 'lucide-react'
import { ORDER_STAGES, ORDER_STAGE_TONE } from '../lib/crm'

const KEY = 'orders.howto.v1'
const TONE_VAR = { warn: 'var(--warn)', pos: 'var(--pos)', neg: 'var(--neg)' }

const STEPS = [
  { n: 1, title: 'Создать заказ', text: 'Кнопка «заказ» в шапке — или своей фразой в поле сверху: «ролик для Пятёрочки, 25к, до пятницы».' },
  { n: 2, title: 'Двинуть по воронке', text: 'Клик по строке открывает панель заказа. В строке — кнопка «следующий шаг» с понятным действием. На канбане карточку можно перетащить в другую колонку.' },
  { n: 3, title: 'Записать оплату', text: 'Кнопка «Запросить оплату» → «Отметить оплату», или прямо в панели блок «оплата». Полная сумма закрывает заказ, частичная — ждёт остатка.' },
]

export default function HowToOrders() {
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(KEY) !== 'seen' } catch { return true }
  })
  const close = () => { setOpen(false); try { localStorage.setItem(KEY, 'seen') } catch { /* ignore */ } }
  const show = () => setOpen(true)
  const toggle = () => (open ? close() : show())

  // кнопка «?» в шапке страницы: один владелец состояния, внешняя кнопка — событие
  useEffect(() => {
    const h = (e) => (e.detail === 'toggle' ? toggle() : e.detail === 'close' ? close() : show())
    window.addEventListener('orders:howto', h)
    return () => window.removeEventListener('orders:howto', h)
  }, [open])

  return (
    <div className="animate-rise -mt-2 rounded-2xl px-4 py-3.5" style={{ background: 'var(--sf2)', boxShadow: 'inset 0 0 0 1px var(--line)' }}>
      <div className="flex items-center justify-between gap-3">
        <button type="button" className="flex items-center gap-2 text-left" onClick={toggle}
          aria-expanded={open} aria-controls="orders-howto"
          aria-label={open ? 'Свернуть подсказку «Как это работает»' : 'Показать подсказку «Как это работает»'}>
          <HelpCircle size={15} className="faint" aria-hidden />
          <span className="text-[14px] font-medium">Как это работает</span>
          <span className="faint text-[12px]">3 шага: создать заказ → двигать по стадиям → записать оплату</span>
          {open ? <ChevronUp size={14} className="faint" aria-hidden /> : <ChevronDown size={14} className="faint" aria-hidden />}
        </button>
      </div>
      {open && (
        <div id="orders-howto" className="animate-rise mt-3 space-y-3">
          <ol className="grid gap-2 sm:grid-cols-3">
            {STEPS.map((s) => (
              <li key={s.n} className="flex gap-2.5 text-[12.5px]">
                <span className="num mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-medium"
                  style={{ background: 'var(--fill-2)', color: 'var(--ink-2)' }}>{s.n}</span>
                <span className="min-w-0"><b className="font-medium">{s.title}</b><span className="muted block leading-snug">{s.text}</span></span>
              </li>
            ))}
          </ol>
          <div>
            <div className="label mb-1.5">воронка заказа — 9 стадий</div>
            <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
              {ORDER_STAGES.map(([k, label], i) => (
                <span key={k} className="flex items-center gap-1.5">
                  {i > 0 && <span className="faint" aria-hidden>→</span>}
                  <span className="badge" style={ORDER_STAGE_TONE[k] ? { background: `color-mix(in srgb, ${TONE_VAR[ORDER_STAGE_TONE[k]]} 12%, var(--sf2))`, color: TONE_VAR[ORDER_STAGE_TONE[k]] } : undefined}>
                    {label}
                  </span>
                </span>
              ))}
            </div>
            <div className="faint mt-1.5 text-[11.5px]">
              Стадия заказа — это про заказ. У клиента своя отдельная стадия (лид → переговоры → клиент → постоянный → спит/ушёл): она меняется сама по оплатам, вручную её трогают осознанно.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}