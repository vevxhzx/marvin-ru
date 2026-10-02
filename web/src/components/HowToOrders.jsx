// Подсказка «Как это работает» на странице заказов: 3 шага + схема воронки.
// Показывается при ПЕРВОМ заходе (метка в localStorage), потом свёрнута и открывается кнопкой «?».
// Кнопка «?» в шапке страницы тоже её открывает — через событие window 'orders:howto'.
import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, HelpCircle } from 'lucide-react'
import { ORDER_STAGES, ORDER_STAGE_TONE } from '../lib/crm'
import { useI18n } from '../lib/i18n'

const KEY = 'orders.howto.v1'
const TONE_VAR = { warn: 'var(--warn)', pos: 'var(--pos)', neg: 'var(--neg)' }

const STEPS = [
  { n: 1, title: 'howto.s1', text: 'howto.s1_text' },
  { n: 2, title: 'howto.s2', text: 'howto.s2_text' },
  { n: 3, title: 'howto.s3', text: 'howto.s3_text' },
]

export default function HowToOrders() {
  const { t } = useI18n()
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
        <button type="button" className="flex w-full items-center gap-2.5 text-left" onClick={toggle}
          aria-expanded={open} aria-controls="orders-howto"
          aria-label={open ? t('howto.collapse') : t('howto.show')}>
          <HelpCircle size={16} className="faint shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-[14px] font-medium leading-tight">{t('howto.title')}</span>
            <span className="faint block truncate text-[12px] leading-tight">{t('howto.subtitle')}</span>
          </span>
          {open ? <ChevronUp size={15} className="faint shrink-0" aria-hidden /> : <ChevronDown size={15} className="faint shrink-0" aria-hidden />}
        </button>
      </div>
      {open && (
        <div id="orders-howto" className="animate-rise mt-3 space-y-3">
          <ol className="grid gap-2 sm:grid-cols-3">
            {STEPS.map((s) => (
              <li key={s.n} className="flex gap-2.5 text-[12.5px]">
                <span className="num mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-medium"
                  style={{ background: 'var(--fill-2)', color: 'var(--ink-2)' }}>{s.n}</span>
                <span className="min-w-0"><b className="font-medium">{t(s.title)}</b><span className="muted block leading-snug">{t(s.text)}</span></span>
              </li>
            ))}
          </ol>
          <div>
            <div className="label mb-1.5">{t('howto.funnel')}</div>
            <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
              {ORDER_STAGES.map(([k, label], i) => (
                <span key={k} className="flex items-center gap-1.5">
                  {i > 0 && <span className="faint" aria-hidden>→</span>}
                  <span className="badge" style={ORDER_STAGE_TONE[k] ? { background: `color-mix(in srgb, ${TONE_VAR[ORDER_STAGE_TONE[k]]} 12%, var(--sf2))`, color: TONE_VAR[ORDER_STAGE_TONE[k]] } : undefined}>
                    {t(label)}
                  </span>
                </span>
              ))}
            </div>
            <div className="faint mt-1.5 text-[11.5px]">
              {t('howto.stage_note')}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}