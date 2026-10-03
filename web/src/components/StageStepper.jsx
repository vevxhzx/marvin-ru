// Степпер стадий ЗАКАЗА. Два вида, одна логика:
//   compact — строка списка: бейдж текущей стадии + тихий «рельс» из девяти отрезков.
//             На тач-экране рельс НЕ интерактивен: отрезок 6px не нажать пальцем,
//             стадию двигает кнопка «следующий шаг», меню и панель заказа;
//   full    — чипы-подписи в панели заказа, клик меняет стадию.
// «потерян» требует причину: клик отдаёт 'lost' наверх, причину спрашивает вызывающий.
import { useCoarse } from '../lib/motion'
import { ORDER_STAGES, ORDER_STAGE_LABEL, ORDER_STAGE_TONE, stageOf } from '../lib/crm'
import { useI18n } from '../lib/i18n'

const TONE_VAR = { warn: 'var(--warn)', pos: 'var(--pos)', neg: 'var(--neg)' }
/* Отрезок рельса: текущая стадия — её цвет и длиннее остальных, остальные — приглушены
   (--line-2, а не --fill-2: на тёмной теме fill-2 почти не читается). */
const barColor = (k, on) => (on ? (TONE_VAR[ORDER_STAGE_TONE[k]] || 'var(--acc)') : (ORDER_STAGE_TONE[k] ? TONE_VAR[ORDER_STAGE_TONE[k]] : 'var(--line-2)'))

export default function StageStepper({ order, stage, onStage, revisions = 0, disabled = false, compact = false, className = '' }) {
  const { t } = useI18n()
  const coarse = useCoarse()
  const cur = stage || stageOf(order)
  const pick = (k) => { if (!disabled && k !== cur) onStage?.(k) }
  const tone = ORDER_STAGE_TONE[cur] || ''

  if (compact) {
    /* Рельс на пальце — только картинка (aria-hidden), стадию двигают крупные кнопки.
       На мыши отрезки остаются кнопками: там их удобно тыкать, и у каждого есть подпись.
       Ширина не анимируется намеренно: это единственное место в этих экранах, где
       пришлось бы двигать layout-свойство, а движение у нас только transform/opacity. */
    const bar = (k, label, on) => (coarse ? (
      <i key={k} aria-hidden="true" className={`block h-1.5 shrink-0 rounded-full ${on ? 'w-4' : 'w-1.5'}`}
        style={{ background: barColor(k, on) }} />
    ) : (
      <button key={k} type="button" disabled={disabled || on} onClick={(e) => { e.stopPropagation(); pick(k) }}
        className={`h-1.5 shrink-0 rounded-full ${on ? 'w-4' : 'w-1.5 hover:w-3'}`}
        style={{ background: barColor(k, on) }}
        aria-label={t('stage.of', { label: t(label) })}
        aria-current={on ? 'step' : undefined}
        data-tip={on ? t('stage.current') : t('stage.move_to', { label: t(label) })}
        title={on ? t('stage.current') : t('stage.move_to', { label: t(label) })} />
    ))
    return (
      <div className={`flex items-center gap-2 ${className}`} role="group" aria-label={t('stage.aria')}>
        <span className={`badge shrink-0 ${tone}`}>
          {t(ORDER_STAGE_LABEL[cur])}{cur === 'revisions' && revisions > 0 ? ` ×${revisions}` : ''}
        </span>
        <span className={`flex items-center gap-[3px] ${coarse ? '' : 'pl-0.5'}`} aria-hidden={coarse ? 'true' : undefined}>
          {ORDER_STAGES.map(([k, label]) => bar(k, label, k === cur))}
        </span>
      </div>
    )
  }

  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${className}`} role="group" aria-label={t('stage.aria')}>
      {ORDER_STAGES.map(([k, label]) => (
        <button key={k} type="button" className={`chip min-h-[var(--tap)] ${cur === k ? 'on' : ''}`} disabled={disabled}
          aria-pressed={cur === k} aria-current={cur === k ? 'step' : undefined}
          onClick={() => pick(k)}>{t(label)}{k === 'revisions' && revisions > 0 ? ` ×${revisions}` : ''}</button>
      ))}
    </div>
  )
}