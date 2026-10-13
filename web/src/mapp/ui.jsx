/* mapp/ui.jsx — JSX-кит мобильной копии (порт референса без типов TS).
 *
 * Иконки сверены с нашей lucide-react 0.446: SquareCheckBig, AudioLines,
 * Rows3 (rows-3), Ellipsis, House, Banknote, Clapperboard — есть; вместо
 * отсутствующего CircleQuestionMark — CircleHelp. Здесь используются только
 * Check и ChevronLeft. Вместо cn()/clsx — локальный cx().
 *
 * Состояния (загрузка/пусто/ошибка) НЕ дублируются: в конце файла тонкие
 * обёртки над десктопными примитивами components/ui.jsx — та же логика,
 * мобильный размер и отступы.
 */
import { useEffect, useRef } from 'react'
import { Check, ChevronLeft } from 'lucide-react'
import { getLang, useI18n } from '../lib/i18n'
import { Empty, ErrorState, ListSkeleton, Skeleton } from '../components/ui'

const cx = (...parts) => parts.filter(Boolean).join(' ')

/* Число по текущей локали (табличные цифры — классом tnum) */
const nfCache = {}
export const num = (n) => {
  const lang = getLang()
  nfCache[lang] ||= new Intl.NumberFormat(lang === 'ru' ? 'ru-RU' : 'en-US')
  return nfCache[lang].format(Math.round(Number(n) || 0))
}

/* Градиенты аватаров (те же 6, что в референсе) */
export const HUES = [
  'linear-gradient(135deg,#5b78ff,#9a7bff)',
  'linear-gradient(135deg,#ffb84d,#ff7a59)',
  'linear-gradient(135deg,#ff7eb3,#c084fc)',
  'linear-gradient(135deg,#3ddc97,#2bb3c0)',
  'linear-gradient(135deg,#6ee0ff,#5b78ff)',
  'linear-gradient(135deg,#ffd84d,#ff9f43)',
]

/* ───────── типографика ───────── */
export function Overline({ children, className }) {
  return (
    <div className={cx('text-[11px] font-semibold uppercase tracking-[0.14em] text-white/55', className)}>
      {children}
    </div>
  )
}

export function ScreenTitle({ overline, title, count, subtitle, right, back, onBack }) {
  const { t } = useI18n()
  return (
    <div className="px-5 pt-1">
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          data-testid="m-back"
          className="m-glass -ml-1 mb-3 inline-flex h-8 items-center gap-0.5 rounded-full pl-1.5 pr-3 text-[13.5px] font-medium text-white/80 transition active:scale-95"
        >
          <ChevronLeft size={17} strokeWidth={2.2} />
          {back || t('common.back')}
        </button>
      )}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {overline && <Overline className="mb-1.5">{overline}</Overline>}
          <h1 className="text-[32px] font-bold leading-[1.05] tracking-[-0.025em]">
            {title}
            {count != null && <span className="ml-2 font-semibold text-[#8ea3ff]">{count}</span>}
          </h1>
          {subtitle && <p className="mt-1.5 text-[13px] leading-snug text-white/60">{subtitle}</p>}
        </div>
        {right && <div className="flex shrink-0 items-center gap-2 pt-0.5">{right}</div>}
      </div>
    </div>
  )
}

export function SectionHead({ title, action, onAction, className }) {
  return (
    <div className={cx('mb-3 flex items-baseline justify-between px-1', className)}>
      <h2 className="text-[19px] font-semibold tracking-[-0.015em]">{title}</h2>
      {action && (
        <button type="button" onClick={onAction} className="text-[13px] font-medium text-[#a9bbff] transition active:opacity-60">
          {action}
        </button>
      )}
    </div>
  )
}

/* Сумма героя. Размер по ширине экрана: на 320 px «−1 234 567 ₽» в 54 px
   не влезает в карточку, поэтому верхняя граница — 13.5vw. Числа не режем. */
export function BigMoney({ value, size = 52, className }) {
  return (
    <div
      className={cx('tnum flex min-w-0 items-baseline gap-1.5 font-semibold leading-none tracking-[-0.035em] sm:gap-2', className)}
      style={{ fontSize: `min(${size}px, 13.5vw)` }}
    >
      <span className="min-w-0 truncate">{num(value)}</span>
      <span className="shrink-0 font-medium text-white/60" style={{ fontSize: '0.5em' }}>
        ₽
      </span>
    </div>
  )
}

/* ───────── кнопки ───────── */
export function IconBtn({ icon: Icon, onClick, active, dot, size = 40, label, className, testid }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      data-testid={testid}
      className={cx(
        'relative grid shrink-0 place-items-center rounded-full transition active:scale-90',
        active
          ? 'border border-white/10 bg-[#0f1640] shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_8px_20px_-8px_rgba(0,0,0,0.6)]'
          : 'm-glass',
        className,
      )}
      style={{ width: size, height: size }}
    >
      <Icon size={Math.round(size * 0.45)} strokeWidth={1.9} />
      {dot && <span className="absolute right-[8px] top-[8px] h-2 w-2 rounded-full bg-[#ff5c7a] ring-2 ring-[#33449c]" />}
    </button>
  )
}

/* сегмент-контрол со скользящей линзой (равные доли) */
export function Segmented({ options, value, onChange, className, size = 'md' }) {
  const idx = Math.max(0, options.findIndex((o) => o.id === value))
  return (
    <div className={cx('m-glass relative flex rounded-full p-1', className)}>
      <div
        className="m-active absolute bottom-1 left-1 top-1 rounded-full transition-transform duration-500 ease-[cubic-bezier(.3,1.25,.5,1)]"
        style={{ width: `calc((100% - 8px) / ${options.length})`, transform: `translateX(${idx * 100}%)` }}
      />
      {options.map((o) => (
        <button
          type="button"
          key={o.id}
          onClick={() => onChange(o.id)}
          className={cx(
            'relative z-10 flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-2 font-medium transition-colors',
            size === 'sm' ? 'h-8 text-[13px]' : 'h-9 text-[14px]',
            o.id === value ? 'text-white' : 'text-white/60',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/* скроллящиеся вкладки с затуханием края */
export function ScrollTabs({ options, value, onChange }) {
  const ref = useRef(null)
  return (
    <div ref={ref} className="no-scrollbar fade-x relative -mx-4 overflow-x-auto px-4">
      <div className="m-glass inline-flex gap-1 rounded-full p-1">
        {options.map((o) => (
          <button
            type="button"
            key={o.id}
            onClick={(e) => {
              onChange(o.id)
              const sc = ref.current
              const b = e.currentTarget
              if (sc) sc.scrollTo({ left: b.offsetLeft - sc.clientWidth / 2 + b.offsetWidth / 2, behavior: 'smooth' })
            }}
            className={cx(
              'h-9 whitespace-nowrap rounded-full px-4 text-[14px] font-medium transition',
              value === o.id ? 'm-active text-white' : 'text-white/60',
            )}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

/* фильтр-чип: белый = активный фильтр */
export function Chip({ active, children, onClick, count, className }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        'inline-flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-4 text-[13px] font-medium transition-all active:scale-95',
        active
          ? 'bg-white text-[#141b4a] shadow-[0_8px_22px_-8px_rgba(255,255,255,0.7)]'
          : 'border border-white/15 bg-white/[0.05] text-white/75',
        className,
      )}
    >
      {children}
      {count != null && <span className={active ? 'text-[#141b4a]/45' : 'text-white/40'}>{count}</span>}
    </button>
  )
}

const TONE = {
  red: 'border-[#ff5c7a]/40 bg-[#ff5c7a]/12 text-[#ff9aac]',
  blue: 'border-[#6b8cff]/45 bg-[#6b8cff]/14 text-[#aebfff]',
  amber: 'border-[#ffc24d]/40 bg-[#ffc24d]/12 text-[#ffd581]',
  green: 'border-[#3ddc97]/40 bg-[#3ddc97]/12 text-[#7cf0c0]',
  gray: 'border-white/14 bg-white/[0.06] text-white/65',
  violet: 'border-[#c9a7ff]/40 bg-[#c9a7ff]/12 text-[#dcc6ff]',
}

export function Pill({ tone = 'gray', children, className, dot, icon: Icon }) {
  return (
    <span
      className={cx(
        'tnum inline-flex h-[26px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-[12px] font-medium',
        TONE[tone] || TONE.gray,
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current shadow-[0_0_6px_currentColor]" />}
      {Icon && <Icon size={12} strokeWidth={2.2} />}
      {children}
    </span>
  )
}

/* ───────── поверхности ───────── */
export function Card({ className, children, style, testid }) {
  return (
    <div style={style} data-testid={testid} className={cx('m-card rounded-[28px]', className)}>
      {children}
    </div>
  )
}

export function Avatar({ initials, hue = 0, size = 44, className }) {
  return (
    <div
      className={cx(
        'grid shrink-0 place-items-center rounded-full font-semibold text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]',
        className,
      )}
      style={{ width: size, height: size, background: HUES[hue % HUES.length], fontSize: Math.round(size * 0.36) }}
    >
      {initials}
    </div>
  )
}

/* живая сфера ассистента */
export function MarvinOrb({ size = 40, className }) {
  return (
    <div
      className={cx('relative shrink-0 overflow-hidden rounded-full', className)}
      style={{
        width: size,
        height: size,
        boxShadow: `0 0 ${Math.round(size * 0.55)}px rgba(130,150,255,0.6), inset 0 0 0 1px rgba(255,255,255,0.3)`,
      }}
    >
      <div className="marvin-orb-core absolute -inset-[25%] rounded-full" />
      <div
        className="absolute inset-0 rounded-full"
        style={{
          background:
            'radial-gradient(circle at 30% 25%, rgba(255,255,255,0.95), rgba(255,255,255,0.2) 32%, transparent 60%)',
        }}
      />
    </div>
  )
}

export function Toggle({ on, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation()
        onChange(!on)
      }}
      data-testid="m-toggle"
      className={cx(
        'relative h-[30px] w-[50px] shrink-0 rounded-full transition-colors duration-300',
        on ? 'bg-[#4d6bff] shadow-[0_0_16px_rgba(77,107,255,0.6)]' : 'bg-white/15',
      )}
    >
      <span
        className={cx(
          'absolute top-[3px] h-6 w-6 rounded-full bg-white shadow-[0_2px_6px_rgba(0,0,0,0.3)] transition-all duration-300 ease-[cubic-bezier(.3,1.3,.5,1)]',
          on ? 'left-[23px]' : 'left-[3px]',
        )}
      />
    </button>
  )
}

/* кружок задачи: цвет обводки = приоритет, зона нажатия 44pt */
const RING = { high: '#ff6b86', mid: '#ffc24d', low: 'rgba(255,255,255,0.38)' }
export function TaskCheck({ done, priority, onToggle, size = 26 }) {
  const { t } = useI18n()
  const pad = Math.max(0, (44 - size) / 2)
  return (
    <button
      type="button"
      aria-label={done ? t('m.task_reopen') : t('m.task_close')}
      onClick={(e) => {
        e.stopPropagation()
        onToggle()
      }}
      data-testid="m-taskcheck"
      className="relative grid shrink-0 place-items-center transition active:scale-90"
      style={{ width: size + pad * 2, height: size + pad * 2, margin: -pad }}
    >
      <span
        className={cx(
          'grid place-items-center rounded-full border-2 transition-all duration-300',
          done && 'm-active border-transparent',
        )}
        style={{
          width: size,
          height: size,
          borderColor: done ? 'transparent' : (RING[priority] || RING.low),
          background: done ? undefined : priority === 'high' ? 'rgba(255,107,134,0.1)' : 'transparent',
        }}
      >
        {done && <Check size={Math.round(size * 0.6)} strokeWidth={3} className="anim-pop" />}
      </span>
    </button>
  )
}

export function Count({ n }) {
  return <span className="tnum font-normal opacity-55">{n}</span>
}

export function IconTile({ icon: Icon, color, size = 36, radius = 12 }) {
  return (
    <div
      className="grid shrink-0 place-items-center"
      style={{ width: size, height: size, borderRadius: radius, background: `${color}24`, color }}
    >
      <Icon size={Math.round(size * 0.5)} strokeWidth={2} />
    </div>
  )
}

/* ───────── состояния экранов: обёртки над десктопными примитивами ─────────
 * Логика (retry, роли, aria, «меньше движения») — в components/ui.jsx и
 * components/States.jsx. Здесь только вид: ширина телефона, отступы и то, что
 * состояние всегда лежит на тёмной карточке, а не на голом градиенте. */

/** Скелет списка на телефоне: строки по --tap, аватар как у настоящих строк. */
export function MListSkeleton({ n = 4, rowH = 56, avatar = true, className }) {
  return (
    <div className={cx('px-1', className)}>
      <ListSkeleton n={n} rowH={rowH} avatar={avatar} />
    </div>
  )
}

/** Одна «плашка» вместо контента: пока данных нет, высота не прыгает. */
export function MSkeleton({ h = 80, w, radius = 'var(--r-md)', className, style }) {
  return <Skeleton h={h} w={w} radius={radius} className={className} style={style} />
}

/** Пусто: что это за раздел и что сделать, чтобы стало не пусто (DESIGN.md). */
export function MEmpty({ glyph, icon, text, sub, hint, onHint, action, compact, className }) {
  return (
    <div className={cx('m-empty', className)}>
      <Empty
        glyph={glyph} icon={icon} text={text} sub={sub} hint={hint}
        onHint={onHint} action={action} compact={compact}
      />
    </div>
  )
}

/** Ошибка загрузки: что случилось + кнопка «проверить снова» (retry — onRetry). */
export function MError({ onRetry, title, sub, detail, compact, className }) {
  return (
    <div className={cx('m-state-error', className)}>
      <ErrorState title={title} sub={sub} detail={detail} onRetry={onRetry} compact={compact} />
    </div>
  )
}

/* Экраны повторяли один и тот же блок «загружаю…» семь раз — вынесли сюда,
   чтобы правка была одна. Подпись для скринридера — на самом контейнере. */
export function MLoading({ rows = 4, rowH = 56, avatar = true, className }) {
  const { t } = useI18n()
  return (
    <div className={cx('px-4 pt-6', className)} role="status" aria-live="polite" aria-busy="true" aria-label={t('m.loading')}>
      <MListSkeleton n={rows} rowH={rowH} avatar={avatar} />
    </div>
  )
}

/** Полноэкранная ошибка с повтором — то, что было инлайном в каждом экране. */
export function MLoadError({ onRetry, title, sub, className }) {
  const { t } = useI18n()
  return (
    <div className={cx('px-4 pt-10', className)}>
      <MError onRetry={onRetry} title={title || t('m.load_err')} sub={sub || t('m.load_err_sub')} />
    </div>
  )
}

/** Ловушка фокуса + Esc + возврат фокуса — как в десктопном Sheet (ui.jsx).
 * Мобильные шторки (QuickAdd, календарь) рисуются сами, поэтому поведение
 * вынесено в хук: одна реализация на обе шторки вместо копипасты. */
const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]'
export function useSheetFocus(open, onClose) {
  const rootRef = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  /* Кто открыл — ловим на первом рендере (до эффектов, иначе фокус уже увели на
     поле внутри шторки). Значение НЕ сбрасываем: в StrictMode эффект вызывается
     дважды, и сброс увёл бы фокус на поле, а не на вызвавший элемент. */
  const openerRef = useRef(null)
  if (openerRef.current === null && typeof document !== 'undefined') {
    openerRef.current = document.activeElement
  }
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); closeRef.current?.(); return }
      if (e.key !== 'Tab') return
      const root = rootRef.current
      if (!root) return
      const nodes = [...root.querySelectorAll(FOCUSABLE)].filter((el) =>
        !el.disabled && el.tabIndex >= 0 && el.getClientRects().length > 0)
      if (!nodes.length) return
      const i = nodes.indexOf(document.activeElement)
      if (e.shiftKey && i <= 0) { e.preventDefault(); nodes[nodes.length - 1].focus() }
      else if (!e.shiftKey && (i === -1 || i === nodes.length - 1)) { e.preventDefault(); nodes[0].focus() }
    }
    window.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      const back = openerRef.current
      if (back && back !== document.body && back.isConnected && typeof back.focus === 'function') {
        back.focus({ preventScroll: true })
      }
    }
  }, [open])
  return rootRef
}
