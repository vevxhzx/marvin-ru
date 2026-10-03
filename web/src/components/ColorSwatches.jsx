import { Check } from 'lucide-react'
import { ACCENT_PALETTE, pickInk } from '../lib/color'
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
   `flex flex-wrap`: свотчи переносятся на узком экране и никогда не растягивают строку. */
export function SwatchRow({ label, value, onChange, showDefault = false, colors = ACCENT_PALETTE }) {
  const { t } = useI18n()
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {label ? <span className="w-[96px] shrink-0 text-[13px] font-medium leading-tight">{label}</span> : null}
      <div className="sw !m-0">
        {showDefault && <Swatch hex="var(--sf2)" name={t('color.as_is')} selected={!value} onClick={() => onChange('')} />}
        {colors.map((c) => (
          <Swatch key={c.id} hex={c.hex} name={t(c.name)} selected={value === c.hex} onClick={() => onChange(c.hex)} />
        ))}
      </div>
    </div>
  )
}