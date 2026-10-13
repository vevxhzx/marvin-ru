import { useState } from 'react'
import { Check, Pipette } from 'lucide-react'
import { ACCENT_PALETTE, normHex, pickInk } from '../lib/color'
import { useI18n } from '../lib/i18n'

/* Палитра акцента — ряд круглых свотчей: слева подпись раздела, справа сами цвета.
   Размер и зона нажатия — из `.sw` в index.css: 38px на десктопе и --tap на тач-экране,
   радиус круглый, выбранный цвет помечен кольцом (`.sw button.on`) и галочкой.
   Подсказка — нативный `title`: карточка `.c` режет по overflow, а `title` не режется никогда. */

const inkFor = (hex) => (typeof hex === 'string' && /^#[0-9a-f]{3,6}$/i.test(hex) ? pickInk(hex) : 'var(--ink)')

export function Swatch({ hex, name, selected, onClick }) {
  return (
    <button
      type="button"
      style={{ '--c': hex }}
      className={`grid place-items-center active:scale-95 ${selected ? 'on' : ''}`}
      onClick={onClick}
      title={name}
      aria-label={name}
      aria-pressed={!!selected}
    >
      {selected && <Check size={13} strokeWidth={3.5} aria-hidden="true" style={{ color: inkFor(hex) }} />}
    </button>
  )
}

/* Строка «подпись слева + свотчи справа».
   showDefault — первый свотч «как всё» (цвет приложения); label пустой — ряд без подписи
   (им пользуется главный селектор «акцент приложения»). Разметка корня намеренно
   `flex flex-wrap`: свотчи переносятся на узком экране и никогда не растягивают строку.
   custom — пипетка + hex-поле для своего цвета (валидация через normHex, мусор не уходит). */
export function SwatchRow({ label, value, onChange, showDefault = false, colors = ACCENT_PALETTE, custom = false }) {
  const { t } = useI18n()
  const norm = normHex(value)
  const isCustom = custom && !!norm && !colors.some((c) => c.hex.toLowerCase() === norm)
  const [draft, setDraft] = useState(null)
  const shown = draft ?? (isCustom ? norm : '')
  const commit = (raw) => {
    setDraft(null)
    const hex = normHex(raw)
    if (hex) onChange(hex)
  }
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {label ? <span className="w-[96px] shrink-0 text-md font-medium leading-tight">{label}</span> : null}
      <div className="sw !m-0">
        {showDefault && <Swatch hex="var(--sf2)" name={t('color.as_is')} selected={!value} onClick={() => onChange('')} />}
        {colors.map((c) => (
          <Swatch key={c.id} hex={c.hex} name={t(c.name)} selected={value === c.hex} onClick={() => onChange(c.hex)} />
        ))}
        {custom && (
          <span className="relative grid place-items-center" title={t('bd.custom_color')}>
            <label
              className={`grid h-[38px] w-[38px] cursor-pointer place-items-center rounded-full border transition active:scale-95 ${isCustom ? 'on' : ''}`}
              style={{ ...(isCustom ? { background: norm, borderColor: 'transparent' } : { borderColor: 'var(--line)' }), color: isCustom ? pickInk(norm) : 'var(--ink2)' }}
            >
              <span className="sr-only">{t('bd.custom_color')}</span>
              {isCustom ? <Check size={13} strokeWidth={3.5} aria-hidden="true" /> : <Pipette size={15} aria-hidden="true" />}
              <input
                type="color"
                className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                value={norm || '#3458f5'}
                onChange={(e) => onChange(normHex(e.target.value) || '')}
                aria-label={t('bd.custom_color')}
                tabIndex={-1}
              />
            </label>
            <input
              value={shown}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={(e) => commit(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') setDraft(null) }}
              placeholder="#…"
              spellCheck={false}
              autoComplete="off"
              aria-label={t('bd.custom_color')}
              className="mono mt-1 w-[68px] rounded-lg border px-1.5 py-1 text-center text-[11px] outline-none"
              style={{ borderColor: 'var(--line)', background: 'transparent', color: 'var(--ink2)' }}
            />
          </span>
        )}
      </div>
    </div>
  )
}