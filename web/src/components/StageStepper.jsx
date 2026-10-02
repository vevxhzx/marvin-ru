// Степпер стадий ЗАКАЗА. Два вида, одна логика:
//   compact — «рельс» из точек в строке списка (подпись стадии + тултип на каждой точке);
//   full    — чипы-подписи в панели заказа, клик меняет стадию.
// «потерян» требует причину: клик отдаёт 'lost' наверх, причину спрашивает вызывающий.
import { ORDER_STAGES, ORDER_STAGE_LABEL, ORDER_STAGE_TONE, stageOf } from '../lib/crm'
import { useI18n } from '../lib/i18n'

const TONE_VAR = { warn: 'var(--warn)', pos: 'var(--pos)', neg: 'var(--neg)' }

export default function StageStepper({ order, stage, onStage, revisions = 0, disabled = false, compact = false, className = '' }) {
  const { t } = useI18n()
  const cur = stage || stageOf(order)
  const pick = (k) => { if (!disabled && k !== cur) onStage?.(k) }

  if (compact) {
    return (
      <div className={`flex items-center gap-1.5 ${className}`} role="group" aria-label={t('stage.aria')}>
        <span className={`badge shrink-0 ${ORDER_STAGE_TONE[cur]}`}>{t(ORDER_STAGE_LABEL[cur])}{cur === 'revisions' && revisions > 0 ? ` ×${revisions}` : ''}</span>
        <span className="flex items-center">
          {ORDER_STAGES.map(([k, label]) => {
            const done = k === cur
            const tone = ORDER_STAGE_TONE[k]
            return (
              <button key={k} type="button" disabled={disabled || done} onClick={(e) => { e.stopPropagation(); pick(k) }}
                className={`h-1.5 rounded-full transition-all ${done ? 'w-4' : 'w-1.5 hover:w-3'}`}
                style={{ background: tone ? TONE_VAR[tone] : done ? 'var(--acc)' : 'var(--fill-2)' }}
                aria-label={t('stage.of', { label: t(label) })} data-tip={done ? t('stage.current') : t('stage.move_to', { label: t(label) })} tabIndex={-1} />
            )
          })}
        </span>
      </div>
    )
  }

  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${className}`} role="group" aria-label={t('stage.aria')}>
      {ORDER_STAGES.map(([k, label]) => (
        <button key={k} type="button" className={`chip ${cur === k ? 'on' : ''}`} disabled={disabled} aria-pressed={cur === k}
          onClick={() => pick(k)}>{t(label)}{k === 'revisions' && revisions > 0 ? ` ×${revisions}` : ''}</button>
      ))}
    </div>
  )
}