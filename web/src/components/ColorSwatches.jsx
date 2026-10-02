import { Check } from 'lucide-react'
import { ACCENT_PALETTE, pickInk } from '../lib/color'
import { useI18n } from '../lib/i18n'

/* Компактные круглые свотчи 26px в одну строку, подпись раздела — слева.
   Выбранный цвет = кольцо (ring) + галочка; у каждого — тултип с названием цвета.
   На узком экране (375px) свотчи аккуратно переносятся — вёрстка не ломается. */

const inkFor = (hex) => (typeof hex === 'string' && /^#[0-9a-f]{3,6}$/i.test(hex) ? pickInk(hex) : 'var(--ink)')

export function Swatch({ hex, name, selected, onClick }) {
  return (
    <button
      type="button"
      data-tip={name}
      aria-label={name}
      aria-pressed={!!selected}
      onClick={onClick}
      className="grid h-[26px] w-[26px] shrink-0 place-items-center rounded-full transition-transform hover:scale-110"
      style={{
        background: hex,
        boxShadow: selected
          ? '0 0 0 2px var(--sf), 0 0 0 4px var(--acc)' // кольцо выбранного
          : 'inset 0 0 0 1px var(--line)',
      }}
    >
      {selected && <Check size={13} strokeWidth={3.5} style={{ color: inkFor(hex) }} />}
    </button>
  )
}

/* Строка «подпись слева + свотчи справа».
   showDefault — первый свотч «как всё» (цвет приложения); label пустой — ряд без подписи
   (им пользуется главный селектор «акцент приложения»). */
export function SwatchRow({ label, value, onChange, showDefault = false, colors = ACCENT_PALETTE }) {
  const { t } = useI18n()
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {label ? <span className="w-[96px] shrink-0 text-[13px] font-medium leading-tight">{label}</span> : null}
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        {showDefault && <Swatch hex="var(--sf2)" name={t('color.as_is')} selected={!value} onClick={() => onChange('')} />}
        {colors.map((c) => (
          <Swatch key={c.id} hex={c.hex} name={t(c.name)} selected={value === c.hex} onClick={() => onChange(c.hex)} />
        ))}
      </div>
    </div>
  )
}
