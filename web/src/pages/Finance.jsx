/* Финансы: один герой на экран, остальное — спокойно.

   Иерархия вкладки «обзор»:
     1. лаймовый герой — баланс крупно (--hero-fs) и три строки мелким под ним:
        свободно, до зарплаты, сколько дней до нуля. Никаких карточек на каждое число;
     2. один график «касса на N дней» (CashChart + ChartTip) — широкая спокойная панель;
     3. дальше — разделы-строки на волосяных разделителях: поток денег, лимиты по
        категориям, ближайшие платежи. Порядок и состав — кнопкой «настроить».

   Остальные вкладки — то же правило: один блок с данными сверху и списки-строки ниже.
   Все формы остались в шторках Sheet — меняется только вид. */

import { useEffect, useMemo, useState, useRef, Children, cloneElement, useId } from 'react'
import { api, money, shortDate, toLocalISO, catColor, catLabel, parseNum } from '../lib/api'
import { Sheet, Field, Empty, Money, Rowi, Skeleton, useToast, Confirm, PageHead, Card, ErrorState } from '../components/ui'
import { BigMoney, HeroLine, useNumFormats, useReveal } from '../components/Widgets'
import CashChart from '../components/CashChart'
import LifeRegime from '../components/LifeRegime'
import { ImportButton } from '../components/Widgets'
import { useRefresh } from '../App'
import { Plus, Search, Trash2, X, Edit2, CreditCard, Wallet, Landmark, PiggyBank, Target, ChevronLeft, ChevronRight, ChevronDown, GripVertical, Calculator, History, EyeOff, Settings2 } from 'lucide-react'
import { Techniques } from '../components/FinanceSmart'
import { SwatchRow } from '../components/ColorSwatches'
import { normHex, pickInk } from '../lib/color'
import { debtView, sortDebts, payoffPlan, DEBT_SORTS } from '../lib/debts'
import { useCardLayout, CardCtl, useWide, usePressResize } from '../lib/layout'
import { usePageAccent } from '../lib/prefs'
import { useI18n, localeOf, t as T } from '../lib/i18n'
import { usePhone } from '../lib/motion'
// Overview-only glass reskin lives here (NOT in index.css — owned by another agent).
import '../fin-glass.css'

/* Подписи полей на узком телефоне (≤380px) — на ступень мельче: длинная подпись
   вроде «дата следующего шага» на 375px съедала строку и отжимала само поле. */
const FIELD_LABEL_M = 'max-[380px]:[&_.label]:text-[length:var(--fs-xs)]'

/* Две раскладки — одна разметка. На десктопе (≥821px) раздел становится поверхностью-карточкой
   (--sf, волосяная рамка --line, радиус --r-lg, отступы --card-pad). На телефоне (≤820px) это
   тоже карточка, только легче: отступ 21px, радиус из токена (--r-lg), без тени и без хайрлайна —
   разделение тоном (макет). Логика, данные и разметка строк общие, различается только обёртка. */
const CARD_M_LIGHT = 'max-[820px]:!bg-[var(--sf)] max-[820px]:!p-[21px] max-[820px]:!rounded-[var(--r-lg)] max-[820px]:!shadow-none max-[820px]:!transform-none'
const CARD_M = `c !rounded-[var(--r-lg)] ${CARD_M_LIGHT}`

/* Герой телефона: минимум 310px высотой, содержимое по центру. Лаймовый градиент
   и его мягкий собственный свет остаются — это идентичность карточки. */
const HERO_M = 'max-[820px]:!min-h-[310px] max-[820px]:!justify-center'

/* Шапка телефона: подписи на узком экране мельче (≤380px) */
const SMALL_M = 'max-[380px]:text-[length:var(--fs-xs)]'

/* Ряд чипов/фильтров на телефоне: одна прокручиваемая строка вместо трёх рядов */
const CHIPS_ROW_M = 'no-scrollbar fade-x max-[820px]:!flex-nowrap max-[820px]:!overflow-x-auto max-[820px]:!pb-1'

/* Переключатель .sg на телефоне: базовое правило разрешает перенос (flex-wrap: wrap),
   и на узком экране семь вкладок разъезжались на две строки. На телефоне — одна
   прокручиваемая строка, на десктопе вид прежний. */
const SEG_ROW_M = 'fade-x max-[820px]:!flex-nowrap max-[820px]:!overflow-x-auto'

/* Разделы вкладки «обзор»: порядок и ширина хранятся общим модулем lib/layout.
   Числа потока (доходы, регулярные, платежи по долгам, свободно) — это строки внутри раздела
   «поток денег», поэтому в списке он один. */
const FIN_CARDS = ['flow', 'budgets', 'upcoming']
const FIN_CARD_WIDTHS = { flow: 4, budgets: 4, upcoming: 4 }
const FIN_CARD_LABELS = { flow: 'fin.flow_month', budgets: 'fin.c_budgets', upcoming: 'fin.c_upcoming' }

/* Честная оценка «когда накоплю»: при темпе 5 000 ₽ в месяц — без обещаний точности */
const MON_SHORT = Array.from({ length: 12 }, (_, i) => new Date(2024, i, 1).toLocaleDateString(localeOf(), { month: 'short' }).replace(/\.$/, ''))
function goalEta(need) {
  const months = Math.ceil(need / 5000)
  if (!Number.isFinite(months) || months <= 0) return ''
  if (months > 60) return null
  const d0 = new Date()
  d0.setMonth(d0.getMonth() + months)
  return T('fin.on_day', { d: d0.getDate(), m: MON_SHORT[d0.getMonth()] })
}

/* Знак суммы: минус — типографский, разряды неразрывные (форматы даёт useNumFormats) */
const MINUS = '−'

/* Полоска расходов по категориям (вкладка «операции»).
   i18n-raw: локальная пара ru/en внутри файла — новых ключей в i18n.js не заводим. */
const CATBAR_REST = { ru: 'остальные', en: 'others' }
const CATBAR_TOP = 5                       // подписей больше пяти — строка спорит с покоем вёрстки
const pctText = (v) => `${v.toLocaleString(localeOf(), { maximumFractionDigits: 1 })} %`

/* Локальные подписи финансов — i18n-raw: новых ключей в i18n.js не заводим.
   Кредитка (счёт-долг), период регулярного платежа, группа «на паузе». */
const FIN = {
  ru: { credit_card: 'кредитка', debt_now: 'долг сейчас', debt: 'долг', period: 'период', monthly: 'месяц', weekly: 'неделя', yearly: 'год', day_of_week: 'день недели', month: 'месяц', amount: 'сумма, ₽', paused_section: 'на паузе', debt_hint: 'траты с неё растут в долг, перевод на неё — уменьшает', linked_debt: 'связан с долгом', link_debt: 'долг для связки', no_link: 'без связки', unlink: 'отвязать' },   // i18n-raw
  en: { credit_card: 'credit card', debt_now: 'debt now', debt: 'debt', period: 'period', monthly: 'month', weekly: 'week', yearly: 'year', day_of_week: 'weekday', month: 'month', amount: 'amount, ₽', paused_section: 'paused', debt_hint: 'spending grows the debt, a transfer to it pays it down', linked_debt: 'linked to debt', link_debt: 'debt to link', no_link: 'no link', unlink: 'unlink' },
}
const WEEKDAYS = {
  ru: ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'],   // i18n-raw
  en: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
}
const MONTHS = {
  ru: ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'],   // i18n-raw
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
}

/* Раздел с данными: карточка на десктопе, плоский раздел с шапкой .hd и волосяными
   разделителями строк на телефоне (переключает CARD_M, логика одна).
   Объявлена на уровне модуля, чтобы React не пересоздавал поддерево на каждом рендере.

   Разметка <section class="c"> — по ней ходят проверки e2e (история операций = секция с этим
   заголовком), поэтому класс .c остаётся и на десктопе, и на телефоне. */
function Block({ title, note, action, children, className = '' }) {
  return (
    <Card className={`${CARD_M} ${className}`} data-reveal>
      <div className="hd flex-wrap">
        <div className="min-w-0"><h2 className="trunc" title={title}>{title}</h2></div>
        <div className="flex items-center gap-2">
          {note && <small className="trunc">{note}</small>}
          {action}
        </div>
      </div>
      {children}
    </Card>
  )
}

/* Кнопки-иконки строки: видны всегда (на тап-экранах раньше прятались до наведения) */
function RowActions({ children }) {
  return <div className="flex shrink-0 items-center gap-1">{children}</div>
}

function IconBtn({ onClick, title, children, danger }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="btn-icon"
      style={danger ? { color: 'var(--neg)' } : { color: 'var(--ink-3)' }}
      title={title}
      aria-label={title}
    >
      {children}
    </button>
  )
}

/* КОНТРАКТ CSS-агента (.glass-card/.gc-subs/.gc-debts/.gc-goals/.gc-num/.dots/
/.car-count/.car-active) в web/src/index.css ОТСУТСТВУЕТ (проверено grep):
ниже — фолбэк на существующие .c/.num/.due-tag/.progress + инлайн-стили
в том же токенном масштабе (var(--fs-*), var(--tap)). Тап-зоны отдельно не
растим: на тач-экранах .btn-icon/.btn-sm уже дает --tap (@media pointer:coarse). */

/* Полоса прогресса акцент → роза (фолбэк .gc-debts/.gc-goals). Свечение — акцентом, как .gau в референсе. */
const GRAD_BAR = 'linear-gradient(90deg, var(--acc), var(--neg))'
const BAR_GLOW = '0 0 14px color-mix(in srgb, var(--acc) 55%, transparent)'

/* Долги: порядок карточек помним в localStorage, типы — ключами словаря
   (фильтр sortDebts живёт в lib/debts.js, здесь только подписи). */
const DEBT_SORT_KEY = 'jarvis.fin.debts.sort'
const DEBT_KIND_KEY = {
  credit: 'fin.debt_kind_credit',
  credit_card: 'fin.debt_kind_credit_card',
  installment: 'fin.debt_kind_installment',
  personal: 'fin.debt_kind_personal',
  receivable: 'fin.debt_kind_receivable',
}
const DEBT_SORT_KEY_OF = {
  manual: 'fin.debt_sort_manual',
  amount: 'fin.debt_sort_amount',
  rate: 'fin.debt_sort_rate',
  day: 'fin.debt_sort_day',
  progress: 'fin.debt_sort_progress',
}
function readDebtSort() {
  try {
    const v = localStorage.getItem(DEBT_SORT_KEY)
    return DEBT_SORTS.includes(v) ? v : 'manual'
  } catch { return 'manual' }
}
const round2 = (n) => Math.round((Number(n) || 0) * 100) / 100
const pctOf = (part, all) => (all > 0 ? Math.max(0, Math.min(100, Math.round((part / all) * 100))) : 0)
/* Длина окружности кольца (r = 52): одна константа на сводку и цели. */
const DONUT_C = 2 * Math.PI * 52

/* Банка-копилка из мокапа ver6 (rGoal): уровень воды = процент цели,
   две волны едут навстречу друг другу (мокап .wv и .wv.b), стекло — полупрозрачный
   тинт. id клип-пути берём из useId: карточек целей несколько, чужой clipPath
   обрезал бы воду не той банке. */
const JAR_WAVE = 'M-120,0 Q-90,-8 -60,0 T0,0 T60,0 T120,0 T180,0 T240,0 V150 H-120Z'
const JAR_WAVE_B = 'M-120,3 Q-90,11 -60,3 T0,3 T60,3 T120,3 T180,3 T240,3 V150 H-120Z'

function GoalJar({ pct }) {
  const cid = `jar${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const p = Math.max(0, Math.min(100, pct)) / 100
  const y = p > 0 ? 138 - p * 124 : 150            /* формула мокапа gv(): 150 = пусто */
  return (
    <svg className="gc-jar" viewBox="0 0 120 150" aria-hidden="true" focusable="false">
      <defs>
        <clipPath id={cid}><rect x="14" y="14" width="92" height="124" rx="28" /></clipPath>
      </defs>
      <rect className="gc-jar-glass" x="14" y="14" width="92" height="124" rx="28" strokeWidth="2" />
      <g clipPath={`url(#${cid})`}>
        <g className="gc-jar-fill" style={{ transform: `translateY(${y}px)` }}>
          <path className="gc-jar-wv" d={JAR_WAVE} />
          <path className="gc-jar-wv b" d={JAR_WAVE_B} />
        </g>
      </g>
      <rect className="gc-jar-shine" x="30" y="26" width="8" height="70" rx="4" />
    </svg>
  )
}

/* Цель-копилка и цель задач — одна карточка. main/target — деньги (финансы),
   для задач-целей опускаются, раскрытое тело едет children.
   jar: если не null — слева банка из мокапа (тогда полосы прогресса нет,
   сама банка и есть индикатор; роль progressbar убираем, чтобы не дублировать). */
export function GoalGlassCard({
  title, meta, pct = 0, main, target, sub, deadlineText, overdue = false,
  eta, onOpen, openLabel, expandIcon, barStyle, actions, children, style, className = '',
  jar = null,
}) {
  const safePct = Math.max(0, Math.min(100, Math.round(pct)))
  const body = (
    <>
      <button
        type="button"
        onClick={onOpen}
        aria-label={openLabel}
        title={openLabel}
        className="block w-full text-left"
        style={{ background: 'transparent', border: 0, padding: 0, margin: 0, cursor: onOpen ? 'pointer' : 'default', font: 'inherit', color: 'inherit' }}
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="clamp-2" style={{ fontSize: 'var(--fs-base)', fontWeight: 600, color: 'var(--ink)' }}>{title}</div>
            {meta ? <div className="muted mt-0.5 trunc text-[length:var(--fs-xs)]">{meta}</div> : null}
          </div>
          <span className="num shrink-0" style={{ fontSize: 'var(--fs-xl)', fontWeight: 700 }}>{safePct}&nbsp;%</span>
          {onOpen ? (expandIcon || <ChevronRight size={16} aria-hidden="true" className="mt-1 shrink-0" style={{ color: 'var(--ink-3)' }} />) : null}
        </div>
        {main ? (
          <div className="num mt-2" style={{ fontSize: 'var(--fs-2xl)', fontWeight: 600, letterSpacing: '-0.03em' }}>
            {main}
            {target ? <span style={{ fontSize: 'var(--fs-md)', fontWeight: 500, letterSpacing: 0, color: 'var(--ink-3)' }}> / {target}</span> : null}
          </div>
        ) : null}
      </button>
      {jar == null ? (
        <div className="progress mt-3" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={safePct}>
          <div style={{ width: `${Math.max(2, safePct)}%`, background: barStyle || GRAD_BAR, boxShadow: BAR_GLOW }} />
        </div>
      ) : null}
      {sub ? <div className="muted mt-2 text-[length:var(--fs-xs)]">{sub}</div> : null}
      {deadlineText ? (
        <div className="mt-1 text-[length:var(--fs-xs)]" style={overdue ? { color: 'var(--neg)', fontWeight: 600 } : undefined}>
          {deadlineText}
        </div>
      ) : null}
      {eta ? <div className="mt-1 text-[length:var(--fs-xs)] text-[var(--ink-3)]">{eta}</div> : null}
      {children}
      {actions ? <div className="mt-3 flex flex-wrap items-center gap-2">{actions}</div> : null}
    </>
  )
  return (
    <section
      className={`c glass-card gc-goals ${className}`}
      data-reveal
      data-car
      style={{ scrollSnapAlign: 'start', ...style }}
    >
      {jar == null ? body : (
        <div className="gc-jar-row">
          <GoalJar pct={safePct} />
          <div className="gc-jar-col">{body}</div>
        </div>
      )}
    </section>
  )
}

/* Карусель на телефоне (390px first): ряд со снапом + точки/счётчик.
   На десктопе (≥821px) обёртка — display:contents, карточки остаются
   элементами сетки .bento; точки скрыты. Активная карточка подсвечена
   рамкой (фолбэк отсутствующего .car-active; на телефоне рамок нет по
   макету — там индикатор это точки/счётчик). */
function useCarousel(n) {
  const ref = useRef(null)
  const [idx, setIdx] = useState(0)
  const onScroll = () => {
    const el = ref.current
    if (!el) return
    const card = el.querySelector('[data-car]')
    const w = card ? card.offsetWidth + 12 : Math.max(1, el.clientWidth * 0.8)
    setIdx(Math.min(Math.max(n - 1, 0), Math.round(el.scrollLeft / Math.max(1, w))))
  }
  return { ref, idx, onScroll }
}

function CarDots({ n, i }) {
  return (
    <div className="flex items-center justify-center gap-2 pt-2 min-[821px]:hidden">
      <span className="flex items-center gap-1.5" aria-hidden="true">
        {Array.from({ length: n }, (_, k) => (
          <i
            key={k}
            style={k === i
              ? { width: 18, height: 6, borderRadius: 999, background: 'var(--acc)' }
              : { width: 6, height: 6, borderRadius: 999, background: 'var(--line-2)' }}
          />
        ))}
      </span>
      <span className="num" style={{ fontSize: 'var(--fs-xs)', color: 'var(--ink-3)' }}>{i + 1} / {n}</span>
    </div>
  )
}

function CarRow({ count, label, children }) {
  const { ref, idx, onScroll } = useCarousel(count)
  return (
    <>
      <div
        ref={ref}
        onScroll={onScroll}
        role="region"
        aria-roledescription="carousel"
        aria-label={label}
        className="no-scrollbar fade-x flex gap-3 overflow-x-auto pb-1 min-[821px]:contents"
        style={{ scrollSnapType: 'x mandatory' }}
      >
        {Children.map(children, (ch, i) => (ch ? cloneElement(ch, {
          className: `${ch.props.className || ''} max-[820px]:w-[78vw] max-[820px]:shrink-0`,
          style: { ...(ch.props.style || {}), scrollSnapAlign: 'start', ...(i === idx ? { borderColor: 'var(--acc)' } : null) },
        }) : ch))}
      </div>
      {count > 1 ? <CarDots n={count} i={idx} /> : null}
    </>
  )
}

/* ---------------- ДОЛГИ: карточка, панель, калькулятор, редактор платежа ---------------- */

/* Плашка типа долга: кредитка/кредит/рассрочка/личный/мне должны.
   Цвет берётся из --acc карточки (если задан свой цвет долга) — см. DebtCard. */
function DebtTypeBadge({ kind, t }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[length:var(--fs-xs)] font-medium"
      style={{ background: 'color-mix(in srgb, var(--acc) 18%, transparent)', color: 'var(--ink-2)' }}
    >
      {t(DEBT_KIND_KEY[kind] || DEBT_KIND_KEY.credit)}
    </span>
  )
}

/* Карточка долга. Для кредитки главное — «использовано из лимита», для остальных —
   остаток и выплаченная доля. Клик по карточке/шеврону раскрывает историю платежей;
   кнопки внутри клик не перехватывают. Архивная карточка read-only. */
function DebtCard({
  d, t, fmt, open, pays, archived, manual, className = '', style,
  cardRef, dragHandle, onToggle, onEdit, onPay, onEditPayment, onDeletePayment, onDelete,
}) {
  const v = debtView(d)
  const name = d.title || d.name || ''
  const accent = normHex(d.color)
  const colorStyle = accent ? { '--acc': accent, '--accent-ink': pickInk(accent) } : undefined
  const closedOn = d.closed_at
    ? new Date(d.closed_at).toLocaleDateString(localeOf(), { day: '2-digit', month: '2-digit', year: 'numeric' })
    : (d.close_date || t('fin.debt_na'))

  return (
    <section
      ref={cardRef}
      data-car
      data-debt-id={d.id}
      className={`c s4 glass-card gc-debts ${CARD_M_LIGHT} ${className}`}
      data-reveal
      style={{ ...colorStyle, ...style }}
      onClick={(e) => { if (!e.target.closest('button,a,input,select,textarea,label')) onToggle() }}
    >
      {/* Свой цвет долга: перекрываем розовую кромку .gc-debts её же геометрией.
          zIndex нужен, чтобы встать поверх ::after (он рисуется последним). */}
      {accent && (
        <span
          aria-hidden="true"
          style={{
            position: 'absolute', left: 0, top: 12, bottom: 12, width: 4, borderRadius: 99,
            background: accent, boxShadow: `0 0 12px ${accent}`, opacity: 0.95,
            pointerEvents: 'none', zIndex: 1,
          }}
        />
      )}
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <DebtTypeBadge kind={v.kind} t={t} />
            {manual && !archived && (
              <button
                type="button"
                className="btn-icon cursor-grab touch-none"
                title={t('fin.debt_drag')}
                aria-label={t('fin.debt_drag')}
                onClick={(e) => e.stopPropagation()}
                {...(dragHandle || {})}
              >
                <GripVertical size={15} aria-hidden="true" />
              </button>
            )}
          </div>
          <h2 className="clamp-2 mt-1.5" style={{ fontSize: 'var(--fs-base)', fontWeight: 600, color: 'var(--ink)' }}>{name}</h2>
          {d.creditor && <div className="muted mt-0.5 trunc text-[length:var(--fs-xs)]">{d.creditor}</div>}
        </div>
        <button
          type="button"
          className="btn-icon shrink-0"
          aria-expanded={!!open}
          aria-label={open ? t('common.close') : t('fin.debt_history')}
          title={open ? t('common.close') : t('fin.debt_history')}
          onClick={(e) => { e.stopPropagation(); onToggle() }}
        >
          <ChevronDown size={16} aria-hidden="true" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }} />
        </button>
      </div>

      <BigMoney value={v.remaining} format={fmt.int} label={fmt.money(v.remaining)} fs="clamp(22px, 2.4vw, 30px)" />
      <div className="progress fg-debtbar mt-3" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(v.pct)}>
        <div style={{ width: `${v.pct > 0 ? Math.max(2, v.pct) : 0}%`, background: GRAD_BAR, boxShadow: BAR_GLOW }} />
      </div>

      {v.isCard ? (
        <div className="muted mt-2 text-[length:var(--fs-xs)]">
          {t('fin.debt_used_of_limit', { used: fmt.money(v.remaining), limit: fmt.money(v.limit) })}
        </div>
      ) : (
        <div className="muted mt-2 text-[length:var(--fs-xs)]">
          {t('fin.paid_out')} <b className={`num ${v.paid > 0 ? 'pos' : ''}`}>{fmt.money(v.paid)}</b> (<b className="num">{fmt.int(v.pct)} %</b>) · {t('fin.of')} {fmt.money(v.total)}
        </div>
      )}

      {!archived && (v.payment > 0 || v.payDay > 0) && (
        <div className="faint mt-1 text-[length:var(--fs-xs)]">
          {v.payment > 0 ? `${t('fin.debt_min_payment')}: ${fmt.money(v.payment)} · ` : ''}
          {t('fin.day_of_month', { d: v.payDay })}
        </div>
      )}
      {d.linked_account && (
        <div className="muted mt-1 text-[length:var(--fs-xs)]">
          ↔ {t('fin.debt_kind_credit_card')}: <b>{d.linked_account.name}</b> · {fmt.money(Math.abs(Number(d.linked_account.balance) || 0))}
        </div>
      )}

      {archived ? (
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <span className="due-tag">{t('fin.debt_closed_on', { date: closedOn })}</span>
          <RowActions>
            <IconBtn danger title={t('common.delete_title')} onClick={onDelete}><Trash2 size={14} /></IconBtn>
          </RowActions>
        </div>
      ) : (
        <div className="mt-3">
          <RowActions>
            <button type="button" className="btn btn-sm fg-pay" onClick={onPay}>{t('fin.make_payment')}</button>
            <IconBtn onClick={onEdit} title={t('common.edit')}><Edit2 size={14} /></IconBtn>
            <IconBtn danger title={t('common.delete_title')} onClick={onDelete}><Trash2 size={14} /></IconBtn>
          </RowActions>
        </div>
      )}

      {open && (
        <div className="mt-3 border-t pt-3" style={{ borderColor: 'var(--line)' }} onClick={(e) => e.stopPropagation()}>
          <div className="mb-1 flex items-center gap-2">
            <History size={13} className="faint" aria-hidden="true" />
            <span className="muted text-[length:var(--fs-xs)]">{t('fin.debt_history')}</span>
            {pays?.rows?.length ? <span className="faint text-[length:var(--fs-xs)]">· {pays.rows.length}</span> : null}
          </div>
          {pays?.loading ? (
            <Skeleton h={42} />
          ) : pays?.error ? (
            <div className="neg text-[length:var(--fs-xs)]">{t('fin.debt_pay_load_err')}</div>
          ) : !pays?.rows?.length ? (
            <div className="faint text-[length:var(--fs-xs)]">{t('fin.debt_no_payments')}</div>
          ) : (
            <div>
              {pays.rows.map((p) => (
                <div key={p.id} className="flex items-start gap-1.5 py-2" style={{ borderTop: '1px solid var(--line)' }}>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                      <b className="num">{fmt.money(p.amount)}</b>
                      <span className="faint text-[length:var(--fs-xs)]">{shortDate(p.date)}</span>
                    </div>
                    <div className="muted mt-0.5 break-words text-[length:var(--fs-xs)]">
                      {p.account || t('fin.no_charge')}{p.note ? ` · ${p.note}` : ''}
                    </div>
                  </div>
                  {!archived && (
                    <>
                      <IconBtn onClick={() => onEditPayment(p)} title={t('fin.debt_pay_edit')}><Edit2 size={13} /></IconBtn>
                      <IconBtn danger onClick={() => onDeletePayment(p)} title={t('fin.debt_pay_delete')}><Trash2 size={13} /></IconBtn>
                    </>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

/* Вся вкладка «Долги»: сводка, план, сортировка/архив/калькулятор и карточки.
   Живёт отдельным компонентом, чтобы страница не обрастала состоянием аккордеона,
   drag-and-drop и подтверждений — всё это нужно только здесь. */
function DebtsPanel({ debts = [], summary, accounts = [], fmt, onAdd, onEdit, onPay, onChanged }) {
  const { t } = useI18n()
  const [, show] = useToast()
  const [archive, setArchive] = useState(false)
  const [sort, setSort] = useState(readDebtSort)
  const [openId, setOpenId] = useState(null)
  const [pays, setPays] = useState({})
  const [ask, setAsk] = useState(null)
  const [payEdit, setPayEdit] = useState(null)   // { debt, payment }
  const [calcOpen, setCalcOpen] = useState(false)
  const [drag, setDrag] = useState(null)         // { id, order } — предпросмотр перетаскивания
  const dragRef = useRef(null)
  const cleanupRef = useRef(null)
  const cardsRef = useRef(new Map())
  const listRef = useRef([])

  const active = useMemo(() => debts.filter((d) => !d.closed), [debts])
  const closed = useMemo(() => debts.filter((d) => d.closed), [debts])
  const list = useMemo(
    () => sortDebts(archive ? closed : active, archive ? 'manual' : sort),
    [archive, active, closed, sort],
  )
  listRef.current = list

  const agg = summary || {
    count: active.length,
    remaining_total: active.reduce((s, d) => s + (Number(d.remaining) || 0), 0),
    total_total: active.reduce((s, d) => s + (Number(d.total) || 0), 0),
    payment_total: active.reduce((s, d) => s + (Number(d.payment) || 0), 0),
    nearest: null,
    close_date: null,
    overpay: null,
  }
  const paidTotal = Math.max(0, (Number(agg.total_total) || 0) - (Number(agg.remaining_total) || 0))
  const debtPct = pctOf(paidTotal, Number(agg.total_total) || 0)

  const byId = useMemo(() => new Map(list.map((d) => [d.id, d])), [list])
  const viewList = drag ? drag.order.map((id) => byId.get(id)).filter(Boolean) : list

  const loadPays = async (id, force = false) => {
    if (!id) return
    if (!force && pays[id]?.rows) return
    setPays((p) => ({ ...p, [id]: { loading: true, rows: p[id]?.rows || [] } }))
    try {
      const rows = await api.debtPayments(id)
      setPays((p) => ({ ...p, [id]: { loading: false, rows: rows || [] } }))
    } catch {
      setPays((p) => ({ ...p, [id]: { loading: false, rows: [], error: true } }))
    }
  }

  // после любого изменения долга история открытой карточки перечитывается
  useEffect(() => {
    setPays({})
    if (openId) loadPays(openId, true)
  }, [debts]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => cleanupRef.current?.(), [])

  // Добавили долг, стоя в архиве, — показываем активные: иначе новая карточка
  // «пропадает» и кажется, что сохранение не сработало.
  const prevActiveRef = useRef(active.length)
  useEffect(() => {
    if (archive && active.length > prevActiveRef.current) setArchive(false)
    prevActiveRef.current = active.length
  }, [active.length, archive])

  const toggle = (d) => {
    if (openId === d.id) { setOpenId(null); return }
    setOpenId(d.id)
    if (!pays[d.id]?.rows) loadPays(d.id)
  }

  const askDelete = (d) => setAsk({
    title: t('fin.del_debt_q_name', { name: d.title || d.name || '' }),
    text: t('fin.del_debt_text'),
    run: async () => {
      await api.delDebt(d.id)
      setOpenId(null)
      onChanged()
      // мягкое удаление: возврат прямо из тоста (POST restore)
      show(t('fin.debt_deleted'), {
        action: {
          label: t('fin.debt_undo'),
          onClick: async () => {
            try {
              await api.restoreDebt(d.id)
              onChanged()
              show(t('fin.debt_restored'))
            } catch (e) { show.err(e) }
          },
        },
      })
    },
  })

  const askDeletePayment = (d, p) => setAsk({
    title: t('fin.debt_del_pay_q'),
    text: t('fin.debt_del_pay_text'),
    run: async () => {
      await api.deleteDebtPayment(d.id, p.id)
      await loadPays(d.id, true)
      onChanged()
      show(t('fin.debt_pay_deleted'))
    },
  })

  const changeSort = (v) => {
    setSort(v)
    try { localStorage.setItem(DEBT_SORT_KEY, v) } catch {}
  }

  /* Перетаскивание за ручку: HTML5 draggable на телефоне не работает, поэтому
     pointer events + elementFromPoint. Слушатели вешаем на window и снимаем
     в cleanup — карточки переставляются прямо во время жеста. */
  const startDrag = (e, d) => {
    if (archive || sort !== 'manual' || dragRef.current) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    const startOrder = listRef.current.map((x) => x.id)
    const st = { id: d.id, sx: e.clientX, sy: e.clientY, order: startOrder, startOrder, moved: false, overId: null }
    dragRef.current = st
    setDrag({ id: d.id, order: startOrder })

    const move = (ev) => {
      const cur = dragRef.current
      if (!cur) return
      if (!cur.moved && Math.hypot(ev.clientX - cur.sx, ev.clientY - cur.sy) < 8) return
      cur.moved = true
      ev.preventDefault()
      const node = document.elementFromPoint(ev.clientX, ev.clientY)
      let overId = Number(node?.closest?.('[data-debt-id]')?.getAttribute('data-debt-id') || 0)
      if (!overId) {
        let best = null
        let bestD = Infinity
        for (const [id, el] of cardsRef.current.entries()) {
          if (id === cur.id) continue
          const r = el.getBoundingClientRect()
          const dx = ev.clientX - (r.left + r.width / 2)
          const dy = ev.clientY - (r.top + r.height / 2)
          const dist = dx * dx + dy * dy
          if (dist < bestD) { bestD = dist; best = { id, r } }
        }
        if (best) overId = best.id
      }
      if (!overId || overId === cur.id || overId === cur.overId) return
      cur.overId = overId
      const ids = cur.order.filter((x) => x !== cur.id)
      const idx = ids.indexOf(overId)
      if (idx < 0) return
      const el = cardsRef.current.get(overId)
      const r = el?.getBoundingClientRect()
      const after = r
        ? (ev.clientY > r.top + r.height / 2 || (ev.clientY >= r.top && ev.clientY <= r.bottom && ev.clientX > r.left + r.width / 2))
        : false
      ids.splice(idx + (after ? 1 : 0), 0, cur.id)
      cur.order = ids
      setDrag({ id: cur.id, order: [...ids] })
    }

    const stop = (ev) => {
      const cur = dragRef.current
      dragRef.current = null
      cleanupRef.current?.()
      cleanupRef.current = null
      setDrag(null)
      if (ev?.type === 'pointercancel' || !cur?.moved) return
      if (cur.order.join(',') === cur.startOrder.join(',')) return
      api.reorderDebts(cur.order)
        .then(() => { show(t('fin.debt_order_saved')); onChanged() })
        .catch((err) => show.err(err))
    }

    window.addEventListener('pointermove', move, { passive: false })
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    cleanupRef.current = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
    }
  }

  const planMonthly = Number(agg.payment_total) || active.reduce((s, d) => s + (Number(d.payment) || 0), 0)

  return (
    <>
      <div className="bento mt-4">
        {/* Сводка: остаток, кольцо выплаченного и число активных долгов */}
        <section className={`c s4 glass-card gc-debts fg-debt-top ${CARD_M_LIGHT}`} data-reveal>
          <div className="min-w-0">
            <div className="hd flex-wrap">
              <div className="min-w-0"><h2 className="trunc">{t('fin.total_debt')}</h2></div>
            </div>
            <BigMoney value={agg.remaining_total} format={fmt.int} label={fmt.money(agg.remaining_total)} fs="clamp(24px, 2.6vw, 34px)" />
            <div className="muted mt-2 text-[length:var(--fs-md)]">{t('fin.n_active_debt', { count: agg.count })}</div>
          </div>
          <div className="fg-donut" role="img" aria-label={`${t('fin.paid_out')} ${debtPct} %`}>
            <svg viewBox="0 0 120 120" aria-hidden="true">
              <circle className="fg-track" cx="60" cy="60" r="52" strokeWidth="12" />
              <circle
                className="fg-val"
                cx="60"
                cy="60"
                r="52"
                strokeWidth="12"
                strokeLinecap="round"
                strokeDasharray={DONUT_C}
                strokeDashoffset={DONUT_C * (1 - debtPct / 100)}
                transform="rotate(-90 60 60)"
              />
            </svg>
            <div className="fg-donut-ct">
              <b className="num">{debtPct}&nbsp;%</b>
              <span>{t('fin.paid_out')}</span>
            </div>
          </div>
        </section>

        {/* Второй блок: ближайший платёж, минимальные платежи, свобода и переплата */}
        <section className={`c s8 ${CARD_M_LIGHT}`} data-reveal>
          <div className="hd"><div className="min-w-0"><h2 className="trunc">{t('fin.debt_plan')}</h2></div></div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-4 min-[821px]:grid-cols-4">
            <div className="min-w-0">
              <div className="faint text-[length:var(--fs-xs)]">{t('fin.debt_nearest')}</div>
              {agg.nearest ? (
                <>
                  <div className="num mt-1" style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{fmt.money(agg.nearest.amount)}</div>
                  <div className="muted mt-0.5 text-[length:var(--fs-xs)]">
                    {agg.nearest.date}{agg.nearest.title || agg.nearest.creditor ? ` · ${[agg.nearest.title, agg.nearest.creditor].filter(Boolean).join(' · ')}` : ''}
                  </div>
                  <div className="faint text-[length:var(--fs-xs)]">
                    {agg.nearest.days === 0 ? t('fin.due_today') : t('fin.in_days', { count: agg.nearest.days })}
                  </div>
                </>
              ) : (
                <div className="muted mt-1 text-[length:var(--fs-sm)]">{t('fin.debt_no_payment')}</div>
              )}
            </div>
            <div className="min-w-0">
              <div className="faint text-[length:var(--fs-xs)]">{t('fin.debt_min_month')}</div>
              <div className="num mt-1" style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{fmt.money(agg.payment_total || 0)}</div>
            </div>
            <div className="min-w-0">
              <div className="faint text-[length:var(--fs-xs)]">{t('fin.debt_freedom')}</div>
              <div className="num mt-1" style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{agg.close_date || t('fin.debt_na')}</div>
            </div>
            <div className="min-w-0">
              <div className="faint text-[length:var(--fs-xs)]">{t('fin.debt_overpay')}</div>
              <div className="num mt-1" style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>
                {agg.overpay == null ? t('fin.debt_na') : fmt.money(agg.overpay)}
              </div>
              {agg.overpay == null && <div className="faint text-[length:var(--fs-xs)]">{t('fin.debt_overpay_na')}</div>}
            </div>
          </div>
        </section>

        {/* Список: активные/архив, сортировка, калькулятор */}
        <section className={`c s12 ${CARD_M_LIGHT}`} data-reveal>
          <div className="flex flex-wrap items-center gap-2">
            <div className="seg" role="group" aria-label={t('fin.debt_status')}>
              <button type="button" className={!archive ? 'on' : ''} aria-pressed={!archive} onClick={() => setArchive(false)}>
                {t('fin.debt_active')} <span className="num faint">{active.length}</span>
              </button>
              <button type="button" className={archive ? 'on' : ''} aria-pressed={archive} onClick={() => setArchive(true)}>
                {t('fin.debt_archive', { count: closed.length })}
              </button>
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <label className="faint text-[length:var(--fs-xs)]" htmlFor="debt-sort">{t('fin.debt_sort')}</label>
              <select
                id="debt-sort"
                className="input !min-h-0 !w-auto !py-1.5 !text-[length:var(--fs-sm)]"
                value={sort}
                onChange={(e) => changeSort(e.target.value)}
              >
                {DEBT_SORTS.map((k) => <option key={k} value={k}>{t(DEBT_SORT_KEY_OF[k])}</option>)}
              </select>
              <button type="button" className="btn-soft btn-sm" onClick={() => setCalcOpen(true)}>
                <Calculator size={14} aria-hidden="true" /> {t('fin.debt_calc')}
              </button>
            </div>
          </div>
          {!archive && sort === 'manual' && active.length > 1 && (
            <div className="faint mt-2 text-[length:var(--fs-xs)]">{t('fin.debt_drag_hint')}</div>
          )}
        </section>

        {archive ? (
          !closed.length ? (
            <section className={`c s12 ${CARD_M_LIGHT}`} data-reveal>
              <Empty glyph="debt" text={t('fin.debt_archived_empty')} sub={t('fin.debt_archived_empty_sub')} compact />
            </section>
          ) : (
            <CarRow count={closed.length} label={t('fin.debt_archive', { count: closed.length })}>
              {viewList.map((d) => (
                <DebtCard
                  key={d.id}
                  d={d}
                  t={t}
                  fmt={fmt}
                  archived
                  open={openId === d.id}
                  pays={pays[d.id]}
                  onToggle={() => toggle(d)}
                  onDelete={() => askDelete(d)}
                />
              ))}
            </CarRow>
          )
        ) : !active.length ? (
          <section className={`c s12 ${CARD_M_LIGHT}`} data-reveal>
            <Empty glyph="debt" text={t('td.clean')} sub={t('td.nothing_missed')}
              action={<button type="button" className="btn" onClick={onAdd}><Plus size={15} /> {t('fin.add_debt')}</button>} />
          </section>
        ) : (
          <CarRow count={active.length} label={t('fin.total_debt')}>
            {viewList.map((d) => (
              <DebtCard
                key={d.id}
                d={d}
                t={t}
                fmt={fmt}
                open={openId === d.id}
                pays={pays[d.id]}
                manual={sort === 'manual'}
                cardRef={(el) => { if (el) cardsRef.current.set(d.id, el); else cardsRef.current.delete(d.id) }}
                dragHandle={sort === 'manual' ? { onPointerDown: (e) => startDrag(e, d) } : null}
                onToggle={() => toggle(d)}
                onEdit={() => onEdit(d)}
                onPay={() => onPay(d)}
                onDelete={() => askDelete(d)}
                onEditPayment={(p) => setPayEdit({ debt: d, payment: p })}
                onDeletePayment={(p) => askDeletePayment(d, p)}
              />
            ))}
          </CarRow>
        )}
      </div>

      <DebtPaymentSheet
        open={!!payEdit}
        debt={payEdit?.debt}
        payment={payEdit?.payment}
        accounts={accounts}
        onClose={() => setPayEdit(null)}
        onDone={() => {
          const d = payEdit?.debt
          setPayEdit(null)
          if (d) loadPays(d.id, true)
          onChanged()
          show(t('common.saved'))
        }}
        onDelete={() => {
          const d = payEdit?.debt
          const p = payEdit?.payment
          setPayEdit(null)
          if (d && p) askDeletePayment(d, p)
        }}
      />

      <DebtCalcSheet open={calcOpen} debts={active} defaultMonthly={planMonthly} onClose={() => setCalcOpen(false)} />

      <Confirm
        open={!!ask}
        danger
        title={ask?.title || ''}
        text={ask?.text || ''}
        onClose={() => setAsk(null)}
        onOk={async () => {
          const a = ask
          setAsk(null)
          if (!a) return
          try { await a.run() } catch (e) { show.err(e) }
        }}
      />
    </>
  )
}

/* Калькулятор погашения: помесячная симуляция из lib/debts.js.
   «Лавина» гасит сначала дорогой долг, «снежный ком» — самый маленький. */
function DebtCalcSheet({ open, debts = [], defaultMonthly = 0, onClose }) {
  const { t } = useI18n()
  const fmt = useNumFormats()
  const [monthly, setMonthly] = useState('')
  const [strategy, setStrategy] = useState('avalanche')
  // Сбрасываем поля только при открытии: фоновое обновление долгов не должно
  // затирать сумму, которую пользователь уже ввёл в калькулятор.
  useEffect(() => {
    if (!open) return
    setMonthly(String(Math.round(Number(defaultMonthly) || 0)))
    setStrategy('avalanche')
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const plan = useMemo(
    () => payoffPlan(debts, parseNum(monthly) || 0, strategy),
    [debts, monthly, strategy],
  )
  const fmtMonth = (date) => (date
    ? date.toLocaleDateString(localeOf(), { month: 'long', year: 'numeric' }).replace(/\s*г\.$/, '')
    : t('fin.debt_na'))

  return (
    <Sheet open={open} onClose={onClose} title={t('fin.debt_calc_title')} hint={t('fin.debt_calc_hint')} bodyClass={FIELD_LABEL_M}>
      <div className="space-y-4">
        <Field label={t('fin.debt_calc_monthly')}>
          <Money value={monthly} onChange={setMonthly} min={0} autoFocus />
        </Field>
        <Field label={t('fin.debt_calc_strategy')}>
          <div className="seg">
            <button type="button" className={strategy === 'avalanche' ? 'on' : ''} aria-pressed={strategy === 'avalanche'} onClick={() => setStrategy('avalanche')}>
              {t('fin.debt_calc_avalanche')}
            </button>
            <button type="button" className={strategy === 'snowball' ? 'on' : ''} aria-pressed={strategy === 'snowball'} onClick={() => setStrategy('snowball')}>
              {t('fin.debt_calc_snowball')}
            </button>
          </div>
          <div className="faint mt-1 text-[length:var(--fs-xs)]">
            {strategy === 'avalanche' ? t('fin.debt_calc_avalanche_hint') : t('fin.debt_calc_snowball_hint')}
          </div>
        </Field>

        {plan.insufficient && (
          <div className="rounded-xl px-3 py-2 text-[length:var(--fs-sm)]" style={{ background: 'var(--warn-soft)', color: 'var(--warn-ink)' }}>
            {t('fin.debt_calc_warn')}
          </div>
        )}
        {plan.capped && (
          <div className="rounded-xl px-3 py-2 text-[length:var(--fs-sm)]" style={{ background: 'var(--neg-soft)', color: 'var(--neg-ink)' }}>
            {t('fin.debt_calc_capped')}
          </div>
        )}

        {!plan.count ? (
          <div className="muted text-[length:var(--fs-md)]">{t('fin.debt_calc_empty')}</div>
        ) : (
          <>
            <div>
              <div className="label mb-1.5">{t('fin.debt_calc_order')}</div>
              <div className="overflow-x-auto">
                <table className="w-full" style={{ fontSize: 'var(--fs-sm)' }}>
                  <thead>
                    <tr className="faint" style={{ textAlign: 'left' }}>
                      <th className="py-1 pr-2 font-medium">{t('fin.debt_calc_num')}</th>
                      <th className="py-1 pr-2 font-medium">{t('fin.debt_calc_debt')}</th>
                      <th className="py-1 pr-2 font-medium">{t('fin.debt_calc_rate')}</th>
                      <th className="py-1 pr-2 font-medium">{t('fin.debt_calc_left')}</th>
                      <th className="py-1 font-medium">{t('fin.debt_calc_close')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.rows.map((r, i) => (
                      <tr key={r.id ?? i} style={{ borderTop: '1px solid var(--line)' }}>
                        <td className="num faint py-1.5 pr-2">{i + 1}</td>
                        <td className="max-w-[160px] trunc py-1.5 pr-2" title={r.title}>{r.title || t('fin.debt_na')}</td>
                        <td className="num py-1.5 pr-2">{r.rate > 0 ? `${r.rate.toLocaleString(localeOf(), { maximumFractionDigits: 2 })} %` : t('fin.debt_na')}</td>
                        <td className="num py-1.5 pr-2">{fmt.money(r.start)}</td>
                        <td className="num py-1.5 whitespace-nowrap">{r.closeDate ? fmtMonth(r.closeDate) : t('fin.debt_na')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <div className="faint text-[length:var(--fs-xs)]">{t('fin.debt_calc_freedom')}</div>
                <div className="num mt-0.5" style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{plan.freeDate ? fmtMonth(plan.freeDate) : t('fin.debt_na')}</div>
                {plan.months != null && <div className="muted text-[length:var(--fs-xs)]">{t('fin.debt_calc_months', { count: plan.months })}</div>}
              </div>
              <div>
                <div className="faint text-[length:var(--fs-xs)]">{t('fin.debt_calc_interest')}</div>
                <div className="num mt-0.5" style={{ fontSize: 'var(--fs-lg)', fontWeight: 600 }}>{fmt.money(plan.totalInterest)}</div>
              </div>
            </div>
          </>
        )}
      </div>
    </Sheet>
  )
}

/* Редактор платежа: сумма, дата, счёт и комментарий. Сохраняет через
   updateDebtPayment; удаление — отдельной кнопкой, подтверждение рисует панель. */
function DebtPaymentSheet({ open, debt, payment, accounts = [], onClose, onDone, onDelete }) {
  const { t } = useI18n()
  const [amount, setAmount] = useState('')
  const [account, setAccount] = useState('')
  const [date, setDate] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setAmount(payment?.amount != null ? String(payment.amount) : '')
    setAccount(payment?.account || '')
    setDate(payment?.date ? String(payment.date).slice(0, 10) : toLocalISO(new Date()).slice(0, 10))
    setNote(payment?.note || '')
  }, [open, payment])

  const max = Math.max(0, (Number(debt?.remaining) || 0) + (Number(payment?.amount) || 0))
  const known = accounts.some((a) => a.name === account)

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseNum(amount)
    if (!a || a <= 0 || !debt?.id || !payment?.id) return
    if (a > max + 0.005) { show(t('fin.debt_pay_err_max'), 'err'); return }
    setSaving(true)
    try {
      await api.updateDebtPayment(debt.id, payment.id, { amount: a, account, date, note: note.trim() })
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title={t('fin.debt_pay_edit')} sub={debt?.title || debt?.name || ''} bodyClass={FIELD_LABEL_M}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('fin.pay_amount')}>
          <Money value={amount} onChange={setAmount} min={0} max={max} autoFocus required />
        </Field>
        <Field label={t('fin.debt_pay_date')}>
          <input type="date" className="input" value={date} max={toLocalISO(new Date()).slice(0, 10)} onChange={(e) => setDate(e.target.value)} required />
        </Field>
        <Field label={t('fin.charge')} hint={t('fin.charge_hint')}>
          <select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">{t('fin.no_charge')}</option>
            {!known && account ? <option value={account}>{account}</option> : null}
            {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
          </select>
        </Field>
        <Field label={t('fin.debt_pay_note')}>
          <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('fin.debt_pay_note_ph')} />
        </Field>
        <div className="flex flex-wrap justify-end gap-2 pt-4">
          <button type="button" className="btn g mr-auto" style={{ color: 'var(--neg)' }} onClick={onDelete}>
            {t('fin.debt_pay_delete')}
          </button>
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !amount}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

export default function Finance() {
  const { t, lang } = useI18n()
  const L = FIN[lang] || FIN.ru
  const fmt = useNumFormats()
  const [tab, setTab] = useState('overview') // 'overview' | 'txs' | 'accounts' | 'debts' | 'recurring' | 'goals' | 'techniques'
  const [days, setDays] = useState(30)
  const [sum, setSum] = useState(null)
  const [txs, setTxs] = useState([])
  const [accounts, setAccounts] = useState([])
  const [debts, setDebts] = useState([])
  const [debtSum, setDebtSum] = useState(null)
  const [recurring, setRecurring] = useState([])
  const [goals, setGoals] = useState([])
  const [categories, setCategories] = useState([])
  const [techniquesData, setTechniquesData] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [budgets, setBudgets] = useState(null)
  const [loadErr, setLoadErr] = useState(false)
  // Режим жизни (services/regime.py): по умолчанию выключен, цифры считаются как раньше
  const [regime, setRegime] = useState(null)

  // Modal sheets
  const [sheet, setSheet] = useState(null) // 'tx' | 'account' | 'debt' | 'payDebt' | 'recurring' | 'goal' | 'putGoal' | 'budget'
  const [editingItem, setEditingItem] = useState(null)
  const [budgetCat, setBudgetCat] = useState(null) // категория/бюджет, для которого правим лимит
  // подтверждение удаления вместо нативного confirm(): { title, text, run }
  const [ask, setAsk] = useState(null)

  // Filters for txs
  const [txSearch, setTxSearch] = useState('')
  const [txCategory, setTxCategory] = useState('all')
  const [txAccount, setTxAccount] = useState('all')
  const [cardsEdit, setCardsEdit] = useState(false)
  const { order: cardOrder, setOrder: setCardOrder, widths: cardWidths, touched: cardTouched, move, setWidth, reset: resetCards } = useCardLayout('finance', FIN_CARDS, FIN_CARD_WIDTHS)
  const wide = useWide()
  const resize = usePressResize({ enabled: cardsEdit && wide, setWidth })
  /** ширину из настроек применяем, только если её задали жестом: старые сохранённые 12 — не в счёт */
  const finCard = (id) => {
    const saved = cardTouched[id] ? cardWidths[id] : FIN_CARD_WIDTHS[id]
    const { style, ...h } = resize.bind(id, saved)
    const custom = wide && (cardTouched[id] || (resize.live && resize.live.id === id))
    return { ...h, style: { ...(custom ? { gridColumn: `span ${resize.widthOf(id, saved)}` } : {}), ...style } }
  }
  const pageAcc = usePageAccent('finance')
  const reveal = useReveal(tab)

  const [, show] = useToast()
  const { tick, bump } = useRefresh()
  const phone = usePhone()          // ≤820px: телефонная раскладка по макету

  const load = async () => {
    try {
      const [s, t, accs, d, ds, rec, g, cats, tech, fc, bg, rg] = await Promise.all([
        api.finSummary(days).catch(() => null),
        api.txs(days).catch(() => []),
        api.accounts().catch(() => []),
        api.debts().catch(() => []),
        api.debtSummary().catch(() => null),   // ближайший платёж, свобода и переплата
        api.recurring(true).catch(() => []),   // с паузами: паузы нужно видеть и включать
        api.goals().catch(() => []),
        api.categories().catch(() => []),
        api.techniques().catch(() => null),
        api.finForecast(days || 90).catch(() => null),
        api.budgets().catch(() => null),
        api.get('/api/finance/regimes').catch(() => null),   // режим жизни (по умолчанию выключен)
      ])
      if (s) setSum(s)
      // сводка и прогноз оба не ответили — показывать «пустые нули» молча нельзя
      setLoadErr(!s && !fc)
      setTxs(t || [])
      setAccounts(accs || [])
      setDebts(d || [])
      setDebtSum(ds || null)
      setRecurring(rec || [])
      setGoals(g || [])
      setCategories(cats || [])
      if (tech) setTechniquesData(tech)
      if (fc) setForecast(fc)
      setBudgets(bg)
      // сводка/прогноз уже принесли regime — берём из них, отдельный ответ только как запасной вариант
      setRegime(s?.regime || fc?.regime || bg?.safe?.regime || rg || null)
    } catch (e) {
      show.err(e)
    }
  }

  useEffect(() => { load() }, [days, tick])
  // «+» дока на финансах открывает форму операции текущей вкладки (finance:add)
  useEffect(() => {
    const on = () => addForTab()
    window.addEventListener('finance:add', on)
    return () => window.removeEventListener('finance:add', on)
  }, [tab])

  const cf = sum?.cashflow || {
    income: 22844,
    recurring: 1528,
    debt_payments: 13500,
    free: 7816,
    income_is_estimate: true,
  }

  const balance = sum?.total_balance ?? sum?.balance ?? 0
  const spent = sum?.spent ?? 55950
  // Считаются ли цифры по режиму жизни: берём из ответа сервера (сводка/прогноз), иначе плашка
  const regCounted = !!(sum?.regime?.counted || forecast?.regime?.counted)
  const debtsTotal = sum?.debts_total ?? (debts.reduce((acc, x) => acc + ((x.total || 0) - (x.paid || 0)), 0) || 205700)

  // Расчет долей потока
  const totalFlow = (cf.recurring || 0) + (cf.debt_payments || 0) + Math.max(0, cf.free || 0) || 1
  const flowRecurringPct = Math.round(((cf.recurring || 1528) / totalFlow) * 100 * 10) / 10
  const flowDebtPct = Math.round(((cf.debt_payments || 13500) / totalFlow) * 100 * 10) / 10
  const flowFreePct = Math.max(0, Math.round((100 - flowRecurringPct - flowDebtPct) * 10) / 10)

  const livingSpent = spent || 40575
  const livingRemain = (cf.free || 7816) - livingSpent

  // График кассы рисует CashChart (общий с главной): точка = баланс на конец дня

  const now = new Date()
  const z = (n) => ('0' + n).slice(-2)

  // «До зарплаты» и «безопасно в день» — из того же ответа сводки (services/finance.safe_to_spend)
  const safe = sum?.safe || null
  const daysLeft = safe?.days_left ?? forecast?.days_to_income ?? null
  const safePerDay = safe?.per_day ?? null

  // Ближайшие списания: дата берётся из дня платежа, а не «ежемесячно» — так видно, когда придётся платить
  const nextPayments = useMemo(() => {
    const today0 = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    return recurring
      .filter((r) => r.active !== false && r.kind !== 'income')
      .map((r) => {
        const dom = Math.min(Number(r.day_of_month || r.day) || 1, 28)
        let d0 = new Date(now.getFullYear(), now.getMonth(), dom)
        if (d0 < today0) d0 = new Date(now.getFullYear(), now.getMonth() + 1, dom)
        return { ...r, on: d0, dom }
      })
      .sort((a, b) => a.on - b.on)
  }, [recurring, now.getMonth(), now.getDate()])

  // Активные и «на паузе»: расчёт (сводка, прогноз) считает только активные —
  // как и бэкенд (list_recurring(active_only=True)). Паузы показываем отдельной
  // группой ниже и НЕ прячем: выключенный тумблером платёж остаётся на месте
  // (раньше он молча исчезал из списка — выглядело как удаление).
  const recActive = useMemo(() => recurring.filter((r) => r.active !== false), [recurring])
  const recPaused = useMemo(() => recurring.filter((r) => r.active === false), [recurring])
  const recExpense = recActive.filter((r) => r.kind !== 'income').reduce((s, r) => s + Number(r.amount || 0), 0)
  const recIncome = recActive.filter((r) => r.kind === 'income').reduce((s, r) => s + Number(r.amount || 0), 0)
  const toggleActive = async (r) => {
    try { await api.updateRecurring(r.id, { active: r.active === false }); load(); bump() } catch (e) { show.err(e) }
  }

  // Когда платёж ждёт своё число: месяц — «{d} числа», неделя — день недели,
  // год — «{d} {месяц}» из next_date (месяц годового хранится именно там).
  const recWhen = (r) => {
    if (r.period === 'weekly') return (WEEKDAYS[lang] || WEEKDAYS.ru)[Math.abs(Number(r.day) || 0) % 7]
    if (r.period === 'yearly' && r.next_date) {
      return new Date(r.next_date).toLocaleDateString(localeOf(), { day: 'numeric', month: 'short' })
    }
    return t('fin.day_of_month', { d: r.day || r.day_of_month || 1 })
  }

  // Карточка регулярного платежа — одна на активные и «на паузе» (вторая группа
  // ниже): выключенный тумблером платёж остаётся видимым, просто приглушённым.
  const recCard = (r) => (
    <section
      key={r.id}
      data-car
      className={`c s4 glass-card gc-subs ${CARD_M_LIGHT}`}
      data-reveal
      role="button"
      tabIndex={0}
      title={t('fin.edit_pay')}
      aria-label={`${r.name || r.title} — ${t('fin.edit_pay')}`}
      onClick={() => { setEditingItem(r); setSheet('recurring') }}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setEditingItem(r); setSheet('recurring') } }}
      style={{ cursor: 'pointer', opacity: r.active === false ? 0.5 : 1 }}
    >
      <div className="hd flex-wrap">
        <span className="due-tag">{recWhen(r)}</span>
        <span className="flex items-center gap-1">
          <span className="num" style={{ color: r.kind === 'income' ? 'var(--pos)' : 'inherit', fontSize: 'var(--fs-lg)', fontWeight: 600, textAlign: 'right', whiteSpace: 'nowrap' }}>
            {r.kind === 'income' ? '+' : MINUS}{fmt.money(r.amount)}
          </span>
          <ChevronRight size={15} aria-hidden="true" style={{ color: 'var(--ink-3)', flex: 'none' }} />
        </span>
      </div>
      <div className="clamp-2" style={{ fontSize: 'var(--fs-base)', fontWeight: 600, color: 'var(--ink)' }}>{r.name || r.title}</div>
      <div className="muted mt-1 trunc text-[length:var(--fs-xs)]" title={[r.category, r.account].filter(Boolean).join(' · ')}>
        {[r.category, r.account].filter(Boolean).join(' · ') || (r.kind === 'income' ? t('fin.inflow') : t('fin.outflow'))}
        {' · '}{r.active === false ? t('fin.paused') : t('fin.status_active')}
      </div>
      <div className="mt-3 flex items-center justify-between gap-2" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
        {/* Тап по карточке открывает RecurringSheet (правка полей); здесь только
            тумблер паузы (тот же toggleActive) и удаление — иконок паузы больше нет. */}
        <button
          type="button"
          role="switch"
          aria-checked={r.active !== false}
          className={`switch ${r.active === false ? '' : 'on'}`}
          title={r.active === false ? t('fin.resume_tip') : t('fin.pause_tip')}
          aria-label={r.active === false ? t('fin.resume_tip') : t('fin.pause_tip')}
          onClick={() => toggleActive(r)}
        />
        <IconBtn
          danger
          title={t('fin.remove_pay')}
          onClick={() => setAsk({
            title: t('fin.del_rec_q_name', { name: r.name || r.title }),
            text: t('fin.pause_note'),
            msg: t('fin.paused'),
            run: () => api.delRecurring(r.id),
          })}
        >
          <X size={15} />
        </IconBtn>
      </div>
    </section>
  )

  const daysUntil = (d0) => Math.round((d0 - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5)
  // API отдаёт список лимитов в поле budgets (категории с лимитом > 0)
  const budgetItems = Array.isArray(budgets) ? budgets : (budgets?.budgets || [])
  const totalBudget = budgetItems.reduce((s, b) => s + (b.budget || 0), 0)
  const totalSpent = budgetItems.reduce((s, b) => s + (b.spent || 0), 0)
  const budgetLeft = totalBudget - totalSpent

  // Фильтрация транзакций: сперва общий срез (поиск + счёт) — его же рисует полоска
  // категорий ниже, потом уже категория для самого списка операций.
  const baseTxs = useMemo(() => {
    const q = txSearch.trim().toLowerCase()
    const list = txs.filter((t) => {
      const matchAcc = txAccount === 'all' || t.account === txAccount
      const matchSearch = !q ||
        (t.title && t.title.toLowerCase().includes(q)) ||
        (t.note && t.note.toLowerCase().includes(q)) ||
        (t.category && t.category.toLowerCase().includes(q)) ||
        (t.comment && t.comment.toLowerCase().includes(q)) ||
        (t.account && t.account.toLowerCase().includes(q))
      return matchAcc && matchSearch
    })
    // сумма в БД всегда положительная, знак хранится в kind — иначе траты считались бы доходом
    const income = list.filter((t) => t.kind === 'income').reduce((s, t) => s + Number(t.amount), 0)
    const expense = list.filter((t) => t.kind === 'expense').reduce((s, t) => s + Number(t.amount), 0)
    return { list, income: Math.round(income), expense: Math.round(expense) }
  }, [txs, txAccount, txSearch])

  const filteredTxs = useMemo(() => {
    // «без категории» — отдельный сегмент полоски: у него в БД category = null,
    // поэтому сравниваем по факту, а не строкой
    const list = baseTxs.list.filter((t) => txCategory === 'all'
      || (txCategory === '__other' ? !t.category : t.category === txCategory))
    const income = list.filter((t) => t.kind === 'income').reduce((s, t) => s + Number(t.amount), 0)
    const expense = list.filter((t) => t.kind === 'expense').reduce((s, t) => s + Number(t.amount), 0)
    return { list, income: Math.round(income), expense: Math.round(expense) }
  }, [baseTxs, txCategory])
  const shownTxs = filteredTxs.list

  // ПОЛОСКА РАСХОДОВ ПО КАТЕГОРИЯМ (мокап ver6): группы трат за период, отсортированы по
  // сумме — ширина сегмента и есть ответ «куда уходит больше всего». Своя выборка без
  // фильтра категории: полоска сравнивает категории между собой, а её сегмент как раз и
  // ставит этот фильтр (повторный клик снимает).
  const catBar = useMemo(() => {
    const m = new Map()
    for (const tx of baseTxs.list) {
      if (tx.kind !== 'expense') continue
      const key = tx.category || '__other'   // без категории — свой сегмент, не теряем его сумму
      m.set(key, (m.get(key) || 0) + (Number(tx.amount) || 0))
    }
    let rows = [...m.entries()]
      .map(([name, sum]) => ({
        name,
        sum,
        // i18n-raw: подпись «без категории» берём из существующего ключа common.other
        label: name === '__other' ? T('common.other') : catLabel(name),
        color: catColor(name),
      }))
      .sort((a, b) => b.sum - a.sum)
    const total = rows.reduce((s, r) => s + r.sum, 0)
    if (!total) return { total: 0, items: [] }
    // Хвост складываем в один нейтральный сегмент: иначе подписи разрастаются, а мелочь
    // на полоске всё равно не читается. Он не кликается — фильтра по «остальным» нет.
    if (rows.length > CATBAR_TOP) {
      const rest = rows.slice(CATBAR_TOP)
      rows = [...rows.slice(0, CATBAR_TOP), {
        name: '__rest', rest: true,
        label: CATBAR_REST[localeOf()] || CATBAR_REST.en,
        color: catColor('__other'),   // тот же нейтральный серый, что у сегмента «Другое»
        sum: rest.reduce((s, r) => s + r.sum, 0),
      }]
    }
    return {
      total,
      items: rows.map((r) => ({ ...r, share: r.sum / total, pct: (r.sum / total) * 100 })),
    }
  }, [baseTxs])

  // СЧЕТА (visual-only): итог и поток ± за период по счёту — из уже загруженных
  // txs (период days), новых запросов нет. История балансов на счёте не хранится
  // (Account: name/kind/balance) — спарклайна нет, опускаем.
  // «Счета» — деньги на руках: счета-кредитки (debt_only) сюда не входят, у них
  // отдельная строка «долг» ниже (как и в total_balance() на бэкенде).
  const accCash = accounts.filter((a) => a.kind !== 'debt_only')
  const accTotal = accCash.reduce((s, a) => s + (Number(a.balance) || 0), 0)
  const accDebt = accounts.filter((a) => a.kind === 'debt_only')
    .reduce((s, a) => s + Math.abs(Number(a.balance) || 0), 0)
  const accFlow = {}
  for (const tx of txs) {
    if (!tx.account) continue
    const e = accFlow[tx.account] || (accFlow[tx.account] = { in: 0, out: 0 })
    const v = Number(tx.amount) || 0
    if (tx.kind === 'income') e.in += v
    else if (tx.kind === 'expense') e.out += v
  }
  // Экспорт выписки в CSV — повторяет то, что видит пользователь: берём shownTxs
  // (учитывает период, фильтр по счёту/категории и поиск), а не все txs (D2)
  const exportCSV = () => {
    if (!shownTxs.length) return
    const rows = [
      [t('fin.csv.date'), t('fin.csv.amount'), t('fin.csv.category'), t('fin.csv.title'), t('fin.csv.account')],
      ...shownTxs.map(x => [
        x.date ? x.date.slice(0, 10) : '',
        x.amount,
        x.category || '',
        `"${(x.title || x.note || '').replace(/"/g, '""')}"`,
        x.account || ''
      ])
    ]
    // Файл отдаём объектом Blob, а не ссылкой вида data:text/csv;…:
    // percent-encoding всей выписки (encodeURIComponent) Chromium обрывает — скачивание
    // приходит отменённым, а «голый» data:-URL портится на «#» и «?» в описании операции.
    // BOM — чтобы Excel открыл кириллицу без плясок с кодировкой.
    const csvContent = '\uFEFF' + rows.map(e => e.join(';')).join('\n')
    const url = URL.createObjectURL(new Blob([csvContent], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.setAttribute('href', url)
    link.setAttribute('download', `statement_${toLocalISO(now).slice(0, 10)}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    // адрес живёт, пока Chromium читает файл: отпускаем его не в том же кадре
    setTimeout(() => URL.revokeObjectURL(url), 30_000)
  }

  const addForTab = () => {
    if (tab === 'accounts') { setEditingItem(null); setSheet('account') }
    else if (tab === 'debts') { setEditingItem(null); setSheet('debt') }
    else if (tab === 'recurring') { setEditingItem(null); setSheet('recurring') }
    else if (tab === 'goals') { setEditingItem(null); setSheet('goal') }
    else { setEditingItem(null); setSheet('tx') }
  }

  const tabLine = tab === 'overview' ? t('fin.sub_overview')
    : tab === 'txs' ? t('fin.n_txs', { count: shownTxs.length })
      : tab === 'accounts' ? t('fin.n_accounts', { count: accounts.length })
        : tab === 'debts' ? t('fin.n_debts', { count: debts.filter((d) => !d.closed).length })
          : tab === 'recurring' ? t('fin.n_rec', { n: recActive.length, paused: recPaused.length ? t('fin.n_rec_paused', { n: recPaused.length }) : '' })
            : tab === 'goals' ? t('fin.n_goals', { count: goals.length })
              : t('tech.title')

  return (
    <div className={`pg on ${FIELD_LABEL_M}`} id="p-fin" style={pageAcc.style} ref={reveal}>
      {/* Шапка через PageHead: .sg периодов в .top для e2e (#p-fin .top .sg). */}
      <PageHead
        title={t('nav.finance')}
        sub={tabLine}
        right={<>
          <div className={`sg fg-seg ${SEG_ROW_M}`} role="group" aria-label={t('fin.period_tip')} title={t('fin.period_tip')}>
            {[[7, 'mem.d7'], [30, 'mem.d30'], [90, 'fin.d90'], [0, 'fin.d_all']].map(([v, key]) => (
              <button key={v} type="button" className={days === v ? 'on' : ''} aria-pressed={days === v} onClick={() => setDays(v)}>
                {t(key)}
              </button>
            ))}
          </div>
          {tab === 'overview' && (
            <button type="button" className={`btn-soft btn-sm ${phone ? '!px-2.5' : ''}`} onClick={() => setCardsEdit((v) => !v)}
              title={t('tk.layout_tip')} aria-label={t('fin.configure_cards')}>
              {phone ? <Settings2 size={15} /> : t('tk.layout')}
            </button>
          )}
          {!phone && (
            <button type="button" className="btn-soft btn-sm" onClick={exportCSV}
              title={t('fin.csv_dl')} aria-label={t('fin.csv_dl')}>
              {t('fin.statement')}
            </button>
          )}
          <button
            type="button"
            className="btn btn-sm head-primary fg-add max-[820px]:!hidden"
            title={t('fin.add_entry')}
            aria-label={t('fin.add_entry')}
            onClick={addForTab}
          >
            {t(tab === 'accounts' ? 'fin.add_account' : tab === 'debts' ? 'fin.add_debt' : tab === 'recurring' ? 'fin.add_pay' : tab === 'goals' ? 'fin.add_goal' : 'fin.add_tx')}
          </button>
        </>}
      />

      {/* Режим жизни перенесён в «Настройки» — на главной финансов его быть не должно */}

      {loadErr && <div className="mt-3"><ErrorState onRetry={load} /></div>}

      {/* Вкладки разделов — прямой ребёнок .pg (без обёртки): на них завязаны проверки e2e
          (#p-fin > .sg). Спокойный сегмент, активная вкладка читается заливкой. */}
      <div className={`sg fg-seg fg-tabs mt-3 ${SEG_ROW_M}`} role="group" aria-label={t('nav.finance')}>
        {[['overview', 'fin.tab_overview'], ['txs', 'fin.tab_txs'], ['accounts', 'fin.tab_accounts'], ['debts', 'fin.tab_debts'],
          ['recurring', 'fin.tab_recurring'], ['goals', 'goals.title'], ['techniques', 'tech.title']].map(([k, key]) => (
            <button key={k} type="button" className={tab === k ? 'on' : ''} aria-pressed={tab === k} onClick={() => setTab(k)}>
              {t(key)}
            </button>
          ))}
      </div>

      {/* ---------------- ОБЗОР ---------------- */}
      {tab === 'overview' && (
        <>
          {/* Обзор — бенто-сетка блоками, как в макете: герой 4 колонки, график 8,
              дальше карточки по 4 в ряд. На телефоне всё в одну колонку. */}
          <div className="bento mt-4">
          {/* Герой: баланс крупно и три строки мелким под ним — без карточек на каждое число */}
          {/* Герой: баланс крупно и три строки мелким под ним — на телефоне и на ПК
              одна и та же акцентная карточка (герой везде акцентный). */}
          <Card variant="hero" className={`fg-hero col-span-12 min-[821px]:col-span-7 ${CARD_M_LIGHT} ${HERO_M}`} data-reveal>
            <div className="hd flex-wrap">
              <div className="min-w-0"><h2 className="trunc">{t('fin.c_balance')}</h2></div>
              <small className={`trunc ${SMALL_M}`}>{t('fin.all_accounts')}</small>
            </div>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
              <BigMoney value={balance} format={fmt.int} label={money(balance)} fs="clamp(30px, 3.4vw, 46px)" />
              <span className="tag" style={{ marginTop: 0 }}>{t('fin.for_days', { n: days || t('common.all'), m: money(spent) })}</span>
            </div>
            {regCounted && (
              <div className="mt-1 text-[length:var(--fs-md)] opacity-75">{t('reg.spent_by_regime')}</div>
            )}
            <div className="fg-stats mt-3" style={{ borderTop: '1px solid var(--hero-ink-16)', paddingTop: 'var(--s-2)' }}>
              <HeroLine label={`${t('fin.c_free')} / ${t('td.per_month').toLowerCase()}`} value={fmt.money(cf.free || 0)} />
              {daysLeft != null && (
                <HeroLine
                  label={t('spend.until_income', { count: daysLeft })}
                  value={safePerDay != null ? `${t('fc.safe')} ${fmt.money(Math.round(safePerDay))}` : '—'}
                />
              )}
              {forecast?.runway_days != null && (
                <HeroLine label={t('td.to_zero', { n: forecast.runway_days })} value={forecast?.min_balance != null ? fmt.money(forecast.min_balance) : '—'} />
              )}
            </div>
          </Card>

          {/* Запас хода: кольцо тиков из референса (30 тиков, статичный инлайн-SVG).
              Значения переиспользуются: дни — forecast.runway_days, сумма — balance. */}
          <Card className={`fg-card glass fg-runway col-span-12 min-[821px]:col-span-5 ${CARD_M_LIGHT}`} data-reveal>
            <div className="hd flex-wrap">
              <div className="min-w-0"><h2 className="trunc">{t('tech.tab_runway')}</h2></div>
              <small className="trunc">{forecast?.runway_days != null ? t('td.to_zero', { n: forecast.runway_days }) : t('fc.by_pace')}</small>
            </div>
            <div
              className="fg-ringw"
              role="img"
              aria-label={forecast?.runway_days != null ? t('td.to_zero', { n: forecast.runway_days }) : t('fc.by_pace')}
            >
              <svg viewBox="0 0 300 300" aria-hidden="true">
                {Array.from({ length: 30 }, (_, i) => {
                  const a = (i / 30) * Math.PI * 2 - Math.PI / 2
                  const lit = forecast?.runway_days != null
                    && i < Math.min(30, Math.max(0, Math.round(forecast.runway_days)))
                  return (
                    <line
                      key={i}
                      className={lit ? 'fg-tk-lit' : 'fg-tk'}
                      x1={150 + Math.cos(a) * 118}
                      y1={150 + Math.sin(a) * 118}
                      x2={150 + Math.cos(a) * 140}
                      y2={150 + Math.sin(a) * 140}
                    />
                  )
                })}
              </svg>
              <div className="fg-ct">
                <div className="fg-ring-num num">
                  {forecast?.runway_days != null ? `~${t('run.days_n', { count: forecast.runway_days })}` : '—'}
                </div>
                <span className="fg-ring-note">{t('fin.all_accounts')} · {fmt.money(balance)}</span>
              </div>
            </div>
          </Card>

          {/* Один график на экран: касса на N дней, интерактивный, с подсказками ChartTip */}
          <Card variant="chart" className={`fg-card glass fg-cash mt-4 ${CARD_M_LIGHT} col-span-12`} data-reveal>
            <div className="hd flex-wrap">
              <div className="min-w-0">
                <h2 className="trunc">{t('fin.cash_on', { n: days || t('common.all'), days: t('run.days_n', { count: days }) })}</h2>
              </div>
              <small className="trunc">
                {forecast
                  ? `${t('fin.fc_now', { bal: money(forecast.balance), pace: money(forecast.avg_day_spent) })}${regCounted ? ` · ${t('reg.by_regime')}` : ''}`
                  : t('fc.by_pace')}
              </small>
            </div>
            {forecast
              ? <CashChart f={forecast} height={220} txs={txs} legend={false} />
              : <Skeleton h={220} radius="var(--r-md)" />}
            <div className="lg">
              <span><i style={{ background: 'var(--warn)' }}></i>{t('chart.fact')}</span>
              <span><i style={{ background: 'var(--accent)' }}></i>{t('chart.forecast')}</span>
              <span><i style={{ border: '1.5px dashed var(--ink3)', background: 'none' }}></i>{t('chart.zero')}</span>
              {forecast?.runway_days != null && (
                <span className="text-[var(--neg)]">{t('td.to_zero', { n: forecast.runway_days })}</span>
              )}
              {forecast?.min_balance != null && forecast.min_balance >= 0 && (
                <span>{t('fc.min', { m: money(forecast.min_balance) })} · {forecast.min_date?.slice(8, 10)}.{forecast.min_date?.slice(5, 7)}</span>
              )}
            </div>
            {forecast?.scenarios?.realistic && forecast?.scenarios?.pessimistic
              && forecast.scenarios.realistic.low !== forecast.scenarios.pessimistic.low && (
              <div className="muted mt-2 text-[length:var(--fs-xs)]">
                {t('fin.scen_min')} <b className="num">{money(forecast.scenarios.realistic.low)}</b>
                {' · '}{t('fin.pessimistic', { n: forecast.scenarios.pessimistic.delay_days ?? 0 })} <b className={`num ${forecast.scenarios.pessimistic.ok ? '' : 'neg'}`}>{money(forecast.scenarios.pessimistic.low)}</b>
              </div>
            )}
          </Card>

          {/* Дальше — разделы-строки. Порядок и состав — кнопкой «настроить» */}
          <div className="contents">
            {cardOrder.map((id) => {
              const ctl = (
                <CardCtl id={id} order={cardOrder} edit={cardsEdit}
                  onMove={move} onHide={(x) => setCardOrder((o) => o.filter((w) => w !== x))}
                  Icon={ChevronLeft} HideIcon={EyeOff} />
              )

              /* Поток денег: четыре строки-числа и полоса долей */
              if (id === 'flow') {
                return (
                  <section key="flow" data-reveal {...finCard('flow')} className={`relative fg-card glass fg-flow col-span-12 min-[821px]:col-span-4 ${CARD_M}`}>
                    {ctl}
                    <div className="hd flex-wrap">
                      <div className="min-w-0"><h2 className="trunc">{t('fin.flow_month')}</h2></div>
                    </div>
                    <Rowi
                      title={t('fin.c_income')}
                      sub={cf.income_is_estimate ? t('fin.average') : t('fin.income_days', { n: days })}
                      right={<span className="amt pos">+{fmt.money(cf.income || 0)}</span>}
                    />
                    <Rowi title={t('fin.c_recurring')} right={<span className="amt">{MINUS}{fmt.money(cf.recurring || 0)}</span>} />
                    <Rowi title={t('fin.by_debts')} right={<span className="amt">{MINUS}{fmt.money(cf.debt_payments || 0)}</span>} />
                    <Rowi
                      title={t('fin.c_free')}
                      sub={t('td.per_month')}
                      right={<span className="num text-[length:var(--fs-lg)] font-medium text-[var(--pos)]">{fmt.money(cf.free || 0)}</span>}
                    />
                    <div className="rule mt-3 pt-1">
                      <div className="flow" style={{ marginTop: 0 }}>
                        <i style={{ width: `${flowRecurringPct}%`, background: 'var(--ink)' }} />
                        <i style={{ width: `${flowDebtPct}%`, background: 'var(--ink-3)' }} />
                        <i style={{ width: `${flowFreePct}%`, background: 'var(--accent)' }} />
                      </div>
                      <div className="fl">
                        <span>{t('fin.reg_debt_free')}</span>
                        <span>{t('fin.living_costs')} {fmt.money(livingSpent)} → {t('fin.remains')} <b className={livingRemain < 0 ? 'neg' : ''}>{livingRemain < 0 ? MINUS : ''}{fmt.money(Math.abs(livingRemain))}</b></span>
                      </div>
                    </div>
                  </section>
                )
              }

              /* Лимиты по категориям: строки с полосками */
              if (id === 'budgets') {
                return (
                  <section key="budgets" data-reveal {...finCard('budgets')} className={`relative fg-card glass fg-limits col-span-12 min-[821px]:col-span-4 ${CARD_M}`}>
                    {ctl}
                    <div className="hd flex-wrap">
                      <div className="min-w-0"><h2 className="trunc">{t('fin.budgets_month')}</h2></div>
                      <div className="flex items-center gap-2">
                        <small className="trunc">{budgetItems.length ? `${MON_SHORT[now.getMonth()]} · ${t(budgetLeft >= 0 ? 'fin.left' : 'fin.over')}` : ''}</small>
                        <button type="button" className="btn-soft btn-sm" onClick={() => { setBudgetCat(null); setSheet('budget') }}
                          title={t('fin.limit')}>
                          + {t('fin.limit')}
                        </button>
                      </div>
                    </div>
                    {!budgetItems.length ? (
                      <div className="py-4">
                        <p className="text-[length:var(--fs-md)] text-[var(--ink3)]">{t('fin.no_limits')}</p>
                        <button type="button" className="btn mt-3" onClick={() => { setBudgetCat(null); setSheet('budget') }}>
                          <Plus size={15} /> {t('fin.set_limit')}
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                          <span className="num text-[length:var(--fs-2xl)] font-medium tracking-[-0.03em]" style={{ color: budgetLeft < 0 ? 'var(--neg)' : 'inherit' }}>
                            {budgetLeft < 0 ? MINUS : ''}{fmt.money(Math.abs(budgetLeft))}
                          </span>
                          <span className="muted text-[length:var(--fs-md)]">{t(budgetLeft < 0 ? 'fin.over' : 'fin.left')} {t('fin.of', { m: money(totalBudget) })}</span>
                        </div>
                        {budgetItems.slice(0, 5).map((b) => (
                          <button
                            key={b.id || b.name}
                            type="button"
                            className="rule block w-full pb-3 pt-2 text-left"
                            title={t('fin.edit_limit')}
                            onClick={() => { setBudgetCat(b); setSheet('budget') }}
                          >
                            <div className="flex items-baseline justify-between gap-3">
                              <span className="trunc text-[length:var(--fs-base)]">{b.icon} {b.name}</span>
                              <span className="num shrink-0 text-[length:var(--fs-md)] text-[var(--ink-2)]">{fmt.nb(`${money(b.spent)} / ${money(b.budget)}`)}</span>
                            </div>
                            <div className="progress fg-gau mt-2">
                              <div style={{ width: `${Math.min(100, Math.round((b.pct || 0) * 100))}%`, background: b.status === 'over' ? 'var(--neg)' : b.status === 'warn' ? 'var(--warn)' : 'var(--accent)' }} />
                            </div>
                          </button>
                        ))}
                        <div className="rule flex flex-wrap items-center justify-between gap-2 pt-3 text-[length:var(--fs-md)] text-[var(--ink-3)]">
                          <span>{t('fin.over_note', { n: budgetItems.filter((b) => b.status === 'over').length })}</span>
                          <button type="button" className="btn-soft btn-sm" onClick={() => { setTxCategory('all'); setTab('txs') }}>{t('fin.see_txs')}</button>
                        </div>
                      </>
                    )}
                  </section>
                )
              }

              /* Ближайшие платежи: строки с датой и суммой + strip на 30 дней.
                 Высоты — из тех же nextPayments/daysUntil (сумма дня относительно
                 пикового дня); дней без платежей — плоские. Новых данных нет. */
              const stripByDay = Array.from({ length: 30 }, (_, i) =>
                nextPayments.reduce((s, r) => s + (daysUntil(r.on) === i ? Number(r.amount) || 0 : 0), 0))
              const stripMax = Math.max(1, ...stripByDay)
              return (
                <section key="upcoming" data-reveal {...finCard('upcoming')} className={`relative fg-card glass fg-upcoming col-span-12 min-[821px]:col-span-4 ${CARD_M}`}>
                  {ctl}
                  <div className="hd flex-wrap">
                    <div className="min-w-0"><h2 className="trunc">{t('fin.c_upcoming')}</h2></div>
                    <small className="trunc">{t('fin.recurring_pays')}</small>
                  </div>
                  {!nextPayments.length ? (
                    <div className="muted py-3 text-[length:var(--fs-md)]">{t('fin.no_recurring')}</div>
                  ) : nextPayments.slice(0, 5).map((r) => (
                    <Rowi
                      key={r.id}
                      time={`${z(r.on.getDate())}.${z(r.on.getMonth() + 1)}`}
                      title={r.title || r.name}
                      sub={`${t('fin.in_n', { n: daysUntil(r.on) })}${r.category ? ` · ${r.category}` : ''}`}
                      right={<span className="amt">{MINUS}{fmt.money(r.amount)}</span>}
                    />
                  ))}
                  {nextPayments.length > 0 && (
                    <div className="fg-strip" aria-hidden="true">
                      {stripByDay.map((v, i) => (
                        <i
                          key={i}
                          className={v > 0 ? 'fg-paid' : ''}
                          style={v > 0 ? { height: `${Math.max(16, Math.round((v / stripMax) * 100))}%` } : undefined}
                        />
                      ))}
                    </div>
                  )}
                  {nextPayments.length > 0 && (
                    <div className="rule flex flex-wrap items-center justify-between gap-2 pt-3 text-[length:var(--fs-md)] text-[var(--ink-3)]">
                      <span>{t('fin.last7')} {fmt.money(nextPayments.filter((r) => daysUntil(r.on) <= 7).reduce((s, r) => s + (r.amount || 0), 0))}</span>
                      <button type="button" className="btn-soft btn-sm" onClick={() => setTab('recurring')}>{t('fin.manage')}</button>
                    </div>
                  )}
                </section>
              )
            })}

            {cardsEdit && (
              <section className={`c ${CARD_M_LIGHT}`} data-reveal>
                <div className="hd flex-wrap">
                  <div className="min-w-0"><h2 className="trunc">{t('fin.cards_setup')}</h2></div>
                </div>
                <p className="muted text-[length:var(--fs-md)]">{t('fin.cards_setup_hint')}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {FIN_CARDS.filter((x) => !cardOrder.includes(x)).map((x) => (
                    <button key={x} className="btn-soft btn-sm" onClick={() => setCardOrder((o) => [...o, x])}>+ {t(FIN_CARD_LABELS[x])}</button>
                  ))}
                  <button className="btn-ghost btn-sm" onClick={resetCards}>{t('tk.restore_all')}</button>
                </div>
              </section>
            )}
          </div>
        </div>
          </>
      )}

      {/* ---------------- ОПЕРАЦИИ ---------------- */}
      {tab === 'txs' && (
        <>
          <section className={`c mt-4 ${CARD_M_LIGHT}`} data-reveal>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <label className="input flex min-w-[220px] flex-1 items-center gap-2.5">
                <Search size={16} className="faint shrink-0" aria-hidden="true" />
                <input
                  type="search"
                  aria-label={t('fin.search_ph')}
                  placeholder={t('fin.search_ph')}
                  value={txSearch}
                  onChange={(e) => setTxSearch(e.target.value)}
                  className="min-w-0 flex-1 bg-transparent outline-none"
                />
              </label>
              {/* импорт выписки Т-Банка: рядом с фильтрами и «выпиской» (CSV/PDF/XLSX, можно перетащить) */}
              <ImportButton
                onDone={(r) => {
                  if (r?.ok) { show(r.text || t('fin.import_added')); load(); bump() }
                  else show(r?.text || t('fin.import_bad'), 'err')
                }}
                onErr={show.err}
              />
              {phone && (
                <button type="button" className="btn-soft btn-sm" onClick={exportCSV}
                  title={t('fin.csv_dl')} aria-label={t('fin.csv_dl')}>
                  {t('fin.statement')}
                </button>
              )}
            </div>
            {/* Категории на телефоне — одна прокручиваемая строка: пятнадцать чипов в три
                ряда съедали пол-экрана и не давали добраться до списка операций. */}
            <div className={`mt-3 flex flex-wrap items-center gap-1.5 ${CHIPS_ROW_M}`}>
              <button type="button" className={`chip max-[820px]:!shrink-0 ${txCategory === 'all' ? 'on' : ''}`} aria-pressed={txCategory === 'all'} onClick={() => setTxCategory('all')}>
                {t('common.all')}
              </button>
              {categories.map((c) => (
                <button
                  type="button"
                  key={c.id || c.name}
                  className={`chip max-[820px]:!shrink-0 ${txCategory === (c.name || c) ? 'on' : ''}`}
                  aria-pressed={txCategory === (c.name || c)}
                  onClick={() => setTxCategory(c.name || c)}
                >
                  <span className="trunc">{c.name || c}</span>
                </button>
              ))}
            </div>
            <div className="rule mt-3 flex flex-wrap items-center gap-2 pt-3">
              <span className="label">{t('graph.one_account')}</span>
              <button type="button" className={`chip max-[820px]:!shrink-0 ${txAccount === 'all' ? 'on' : ''}`} aria-pressed={txAccount === 'all'} onClick={() => setTxAccount('all')}>{t('common.all')}</button>
              {accounts.map((a) => (
                <button key={a.id || a.name} type="button" className={`chip max-[820px]:!shrink-0 ${txAccount === a.name ? 'on' : ''}`} aria-pressed={txAccount === a.name} onClick={() => setTxAccount(a.name)}>
                  <span className="trunc">{a.name}</span>
                </button>
              ))}
              {(txCategory !== 'all' || txAccount !== 'all' || txSearch) && (
                <button type="button" className="btn-ghost btn-sm" onClick={() => { setTxCategory('all'); setTxAccount('all'); setTxSearch('') }}>{t('common.reset')}</button>
              )}
              <span className="num ml-auto text-[length:var(--fs-base)]">
                <b className="pos">+{fmt.money(filteredTxs.income)}</b>
                <span className="text-[var(--ink3)]"> / </span>
                <b>{MINUS}{fmt.money(filteredTxs.expense)}</b>
              </span>
            </div>
            {/* ПОЛОСКА РАСХОДОВ ПО КАТЕГОРИЯМ (мокап ver6, вкладка «операции»): сегмент ∝
                доле трат за период, цвет — из CAT_COLORS. Клик по сегменту или подписи ставит
                фильтр категории (повторно — снимает): выбранный горит акцентом, остальные
                гаснут. Хвост «остальные» — нейтральный и не кликается, фильтра по нему нет. */}
            {catBar.items.length > 0 && (
              <div className="mt-3">
                <div className="fg-catbar">
                  {catBar.items.map((c) => {
                    const on = txCategory === c.name
                    const off = txCategory !== 'all' && !on
                    const style = { '--c': c.color, flexGrow: c.share }
                    const label = `${c.label} · ${money(c.sum)} · ${pctText(c.pct)}`
                    return c.rest
                      ? <i key={c.name} style={style} title={label} aria-hidden="true" />
                      : (
                        <button
                          key={c.name}
                          type="button"
                          style={style}
                          className={`${off ? ' off' : ''}${on ? ' on' : ''}`}
                          title={label}
                          aria-label={label}
                          aria-pressed={on}
                          onClick={() => setTxCategory(on ? 'all' : c.name)}
                        />
                      )
                  })}
                </div>
                <div className="fg-cat-legend">
                  {catBar.items.map((c) => {
                    const on = txCategory === c.name
                    const off = txCategory !== 'all' && !on
                    const inner = (
                      <>
                        <i style={{ '--c': c.color }} aria-hidden="true" />
                        <span className="trunc">{c.label}</span>
                        <b>{money(c.sum)}</b>
                        <em>{pctText(c.pct)}</em>
                      </>
                    )
                    return c.rest
                      ? <span key={c.name}>{inner}</span>
                      : (
                        <button
                          key={c.name}
                          type="button"
                          className={`${off ? ' off' : ''}${on ? ' on' : ''}`}
                          aria-pressed={on}
                          onClick={() => setTxCategory(on ? 'all' : c.name)}
                        >{inner}</button>
                      )
                  })}
                </div>
              </div>
            )}
          </section>

          <Block
            className="mt-5"
            title={t('fin.tx_history')}
            note={`${t('mem.entries_n', { count: shownTxs.length })} · ${days ? t('fin.for_days_short', { n: days }) : t('fin.all_history')}`}
          >
            {!shownTxs.length ? (
              <div className="muted py-3 text-[length:var(--fs-md)]">{t('fin.no_txs_period')}</div>
            ) : shownTxs.map((tx) => (
              <div className="rowi" key={tx.id}>
                <time>{shortDate(tx.date || tx.created_at)}</time>
                <span className="t">
                  <span className="clamp-2 block">{tx.title || tx.note || tx.category || t('fin.tx')}</span>
                  {/* перевод: подпись «перевод» и «откуда → куда» (ключи новые не заводим) */}
                  <small>{[
                    tx.kind === 'transfer' ? t.kind_transfer : tx.category,
                    tx.kind === 'transfer' && tx.to_account ? `${tx.account || ''} → ${tx.to_account}` : tx.account,
                    tx.comment,
                  ].filter(Boolean).join(' · ')}</small>
                </span>
                {/* знак берём из kind: amount приходит из API положительным */}
                <span className="amt" style={{ color: tx.kind === 'income' ? 'var(--pos)' : 'inherit' }}>
                  {tx.kind === 'income' ? '+' : tx.kind === 'expense' ? MINUS : ''}{money(tx.amount)}
                </span>
                <RowActions>
                  <IconBtn onClick={() => { setEditingItem(tx); setSheet('tx') }} title={t('common.edit')}>
                    <Edit2 size={14} />
                  </IconBtn>
                  <IconBtn
                    danger
                    title={t('common.delete_title')}
                    onClick={() => setAsk({
                      title: t('fin.del_tx_q'),
                      text: t('fin.del_tx_text'),
                      msg: t('fin.tx_deleted'),
                      run: () => api.delTx(tx.id),
                    })}
                  >
                    <Trash2 size={14} />
                  </IconBtn>
                </RowActions>
              </div>
            ))}
          </Block>
        </>
      )}

      {/* ---------------- СЧЕТА (ver6: hero с итогом + лаймовый бар + карточки) ---------------- */}
      {tab === 'accounts' && (
        <div className="bento mt-4">
          <section className={`c fg-card glass fg-acc-hero col-span-12 ${CARD_M_LIGHT}`} data-reveal>
            <div className="hd flex-wrap">
              <div className="min-w-0"><h2 className="trunc">{t('fin.tab_accounts')}</h2></div>
              <small className="trunc">{t('fin.n_accounts', { count: accounts.length })}</small>
            </div>
            <BigMoney value={accTotal} format={fmt.int} label={money(accTotal)} fs="clamp(28px, 3vw, 42px)" />
            {accTotal > 0 && accCash.length > 0 && (
              <div className="fg-acc-bar mt-3" role="img" aria-label={t('fin.all_accounts')}>
                {accCash.map((a) => {
                  const w = Math.max(0, (Number(a.balance) || 0) / accTotal) * 100
                  return w > 0 ? <i key={a.id || a.name} style={{ width: `${w}%` }} /> : null
                })}
              </div>
            )}
            {accDebt > 0 && (
              <div className="num mt-2 text-[length:var(--fs-md)]" style={{ color: 'var(--neg)' }}>{L.debt}: {fmt.money(accDebt)}</div>
            )}
            <div className="muted mt-2 text-[length:var(--fs-md)]">
              {t('fin.for_days', { n: days || t('common.all'), m: money(filteredTxs.expense) })}
            </div>
          </section>
          {!accounts.length ? (
            <section className={`c col-span-12 ${CARD_M_LIGHT}`} data-reveal>
              <Empty glyph="money" text={t('fin.no_accounts')} sub={t('fin.no_accounts_hint')}
                action={<button type="button" className="btn" onClick={() => { setEditingItem(null); setSheet('account') }}><Plus size={15} /> {t('fin.add_account')}</button>} />
            </section>
          ) : (
            <div className="fg-accts col-span-12">
              {accounts.map((a) => {
                const atype = a.type || a.kind || 'bank'
                const isDebt = atype === 'debt_only'
                const Icon = (isDebt || atype === 'card') ? CreditCard : atype === 'cash' ? Wallet : atype === 'crypto' ? PiggyBank : Landmark
                const kindLabel = isDebt ? L.credit_card : ({ card: t('acc.card'), cash: t('acc.cash2'), bank: t('graph.one_account'), savings: t('acc.deposit'), crypto: t('acc.crypto') })[atype] || t('graph.one_account')
                const f = accFlow[a.name] || { in: 0, out: 0 }
                return (
                  <section className={`c fg-card glass fg-acct ${CARD_M_LIGHT}`} data-reveal key={a.id || a.name}>
                    <div className="flex items-center gap-2.5">
                      <span className="fg-chip" aria-hidden="true"><Icon size={18} /></span>
                      <span className="t min-w-0 flex-1">
                        <span className="clamp-2 block" style={{ fontWeight: 600 }}>{a.name}</span>
                        <small className="muted trunc">{a.comment || kindLabel} · {a.currency || 'RUB'}</small>
                      </span>
                      <RowActions>
                        <IconBtn onClick={() => { setEditingItem(a); setSheet('account') }} title={t('common.edit')}><Edit2 size={14} /></IconBtn>
                        <IconBtn
                          danger
                          title={t('fin.del_acc_q')}
                          onClick={() => setAsk({
                            title: t('fin.del_acc_q_name', { name: a.name }),
                            text: t('fin.del_acc_text'),
                            msg: t('fin.acc_deleted'),
                            run: () => api.delAccount(a.id),
                          })}
                        >
                          <Trash2 size={14} />
                        </IconBtn>
                      </RowActions>
                    </div>
                    {/* у кредитки баланс отрицательный (долг) — показываем его суммой долга */}
                    <div className="num fg-big mt-2" style={isDebt ? { color: 'var(--neg)' } : undefined} title={isDebt ? L.debt_hint : undefined}>
                      {isDebt ? fmt.money(Math.abs(Number(a.balance) || 0)) : fmt.money(a.balance || 0)}
                    </div>
                    {isDebt && <div className="muted mt-1 text-[length:var(--fs-xs)]">{L.debt} · {L.debt_hint}</div>}
                    {isDebt && (() => {
                      const linked = debts.find((d) => d.id === a.debt_id)
                      return linked ? (
                        <div className="muted mt-1 text-[length:var(--fs-xs)]">↔ {L.linked_debt}: <b>{linked.title || linked.name}</b> · {fmt.money(linked.remaining ?? 0)}</div>
                      ) : (
                        <div className="faint mt-1 text-[length:var(--fs-xs)]">↔ {L.no_link}</div>
                      )
                    })()}
                    {(f.in > 0 || f.out > 0) && (
                      <div className="fg-delta">
                        {t('fin.for_days_short', { n: days || t('common.all') })}: <span className="pos">+{fmt.money(f.in)}</span> / <span>{MINUS}{fmt.money(f.out)}</span>
                      </div>
                    )}
                  </section>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ---------------- ДОЛГИ: сводка, план, сортировка, архив и калькулятор ---------------- */}
      {tab === 'debts' && (
        <DebtsPanel
          debts={debts}
          summary={debtSum}
          accounts={accounts}
          fmt={fmt}
          onAdd={() => { setEditingItem(null); setSheet('debt') }}
          onEdit={(d) => { setEditingItem(d); setSheet('debt') }}
          onPay={(d) => { setEditingItem(d); setSheet('payDebt') }}
          onChanged={() => { load(); bump() }}
        />
      )}

      {/* ---------------- РЕГУЛЯРНЫЕ ---------------- */}
      {tab === 'recurring' && (
        <div className="bento mt-4">
          <section className={`c s4 glass-card gc-subs ${CARD_M_LIGHT}`} data-reveal>
            <div className="hd"><div className="min-w-0"><h2 className="trunc">{t('fin.c_recurring')}</h2></div></div>
            <div className="big num" style={{ fontSize: 'clamp(24px, 2.6vw, 34px)' }}>{fmt.money(recExpense)}</div>
            {recIncome > 0 && <div className="muted mt-1 text-[length:var(--fs-md)]">+{fmt.money(recIncome)}</div>}
          </section>
          {recActive.length === 0 ? (
            <section className={`c s8 ${CARD_M_LIGHT}`} data-reveal>
              <div className="muted text-[length:var(--fs-md)]">{recurring.length > 0 ? t('fin.all_paused') : t('fin.no_recurring')}</div>
            </section>
          ) : (
            <CarRow count={recActive.length} label={t('fin.c_recurring')}>
              {recActive.map(recCard)}
            </CarRow>
          )}
          {/* Паузы — отдельной группой и всегда видимые: тумблер выключает платёж,
              а не убирает его (иначе казалось, что платёж просто удалился). */}
          {recPaused.length > 0 && (
            <>
              <div className="s12 mt-1 flex items-center gap-2">
                <span className="muted text-[length:var(--fs-md)]">{L.paused_section}</span>
                <span className="num faint text-[length:var(--fs-xs)]">{recPaused.length}</span>
              </div>
              <CarRow count={recPaused.length} label={`${L.paused_section} · ${recPaused.length}`}>
                {recPaused.map(recCard)}
              </CarRow>
            </>
          )}
        </div>
      )}

      {/* ---------------- ЦЕЛИ ---------------- */}
      {tab === 'goals' && (
        <div className="bento mt-4">
          {!goals.length ? (
            <section className={`c s12 ${CARD_M_LIGHT}`} data-reveal>
              <Empty glyph="mind" text={t('fin.no_goals')} sub={t('fin.no_goals_hint')}
                action={<button type="button" className="btn" onClick={() => { setEditingItem(null); setSheet('goal') }}><Target size={15} /> {t('gl.goal')}</button>} />
            </section>
          ) : (
            <CarRow count={goals.length} label={t('goals.title')}>
              {goals.map((g) => {
            // API отдаёт накопленное в поле saved (GoalIn/GoalPatch), а не current:
            // раньше читался g.current → карточка всегда показывала 0 ₽ и 0 %
            const current = g.current ?? g.saved ?? 0
            const target = g.target || 1
            const pct = Math.min(100, Math.round((current / target) * 100))
            const eta = target > current ? goalEta(target - current) : null
            const day0 = new Date()
            day0.setHours(0, 0, 0, 0)
            const overdue = !!(g.deadline && current < target && new Date(g.deadline) < day0)
            return (
              <GoalGlassCard
                key={g.id}
                className={`s4 ${CARD_M_LIGHT}`}
                title={g.title || g.name}
                pct={pct}
                jar={pct}
                main={fmt.money(current)}
                target={fmt.money(target)}
                onOpen={() => { setEditingItem(g); setSheet('goal') }}
                openLabel={t('common.edit')}
                deadlineText={g.deadline
                  ? (overdue ? `${shortDate(g.deadline)} · ${t('aims.overdue')}` : shortDate(g.deadline))
                  : t('fin.forever')}
                overdue={overdue}
                eta={eta ? `${t('gl.at_rate', { m: money(5000) })} ${eta}` : null}
                actions={(
                  <>
                    <button type="button" className="btn btn-sm" onClick={() => { setEditingItem(g); setSheet('putGoal') }}>{t('fin.top_up')}</button>
                    <IconBtn onClick={() => { setEditingItem(g); setSheet('goal') }} title={t('common.edit')}><Edit2 size={14} /></IconBtn>
                    <IconBtn
                      danger
                      title={t('common.delete_title')}
                      onClick={() => setAsk({
                        title: t('fin.del_goal_q_name', { name: g.title || g.name }),
                        text: t('gl.del_text2'),
                        msg: t('gl.deleted'),
                        run: () => api.delGoal(g.id),
                      })}
                    >
                      <Trash2 size={14} />
                    </IconBtn>
                  </>
                )}
              />
            )
          })}
            </CarRow>
          )}
        </div>
      )}

      {/* ---------------- ТЕХНИКИ ---------------- */}
      {tab === 'techniques' && (
        <section className={`c mt-4 ${CARD_M_LIGHT}`} data-reveal>
          {techniquesData ? (
            <Techniques
              t={techniquesData}
              onOpenCat={(c) => { setTxCategory(c); setTab('txs') }}
            />
          ) : (
            <Empty
              glyph="money"
              text={t('tech.not_calc')}
              sub={t('tech.need_txs')}
              compact
            />
          )}
        </section>
      )}

      {/* Sheets: диалоги создания и редактирования сущностей финансов */}
      <TxSheet
        open={sheet === 'tx'}
        item={editingItem}
        categories={categories}
        accounts={accounts}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={(msg) => { setSheet(null); setEditingItem(null); load(); bump(); if (msg) show(msg) }}
      />

      <AccountSheet
        open={sheet === 'account'}
        account={editingItem}
        debts={debts}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
      />

      <DebtSheet
        open={sheet === 'debt'}
        debt={editingItem}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={(msg) => { setSheet(null); setEditingItem(null); load(); bump(); if (msg) show(msg) }}
      />

      <PayDebtSheet
        open={sheet === 'payDebt'}
        debt={editingItem}
        accounts={accounts}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={(msg) => { setSheet(null); setEditingItem(null); load(); bump(); if (msg) show(msg) }}
      />

      <RecurringSheet
        open={sheet === 'recurring'}
        item={editingItem}
        categories={categories}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
      />

      <GoalSheet
        open={sheet === 'goal'}
        goal={editingItem}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
      />

      <PutGoalSheet
        open={sheet === 'putGoal'}
        goal={editingItem}
        accounts={accounts}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={(msg) => { setSheet(null); setEditingItem(null); load(); bump(); if (msg) show(msg) }}
      />

      <BudgetSheet
        open={sheet === 'budget'}
        item={budgetCat}
        categories={categories}
        onClose={() => { setSheet(null); setBudgetCat(null) }}
        onDone={() => { setSheet(null); setBudgetCat(null); load(); bump() }}
      />

      {/* Подтверждение удаления вместо нативного confirm(): одна шторка на всю страницу */}
      <Confirm
        open={!!ask}
        danger
        title={ask?.title || ''}
        text={ask?.text || ''}
        onClose={() => setAsk(null)}
        onOk={async () => {
          const a = ask
          setAsk(null)
          if (!a) return
          try { await a.run(); if (a.msg) show(a.msg); load(); bump() } catch (e) { show.err(e) }
        }}
      />
    </div>
  )
}

/* =========================================================================
   Диалоги редактирования (Sheet)
   ========================================================================= */

function TxSheet({ open, item, categories = [], accounts = [], onClose, onDone }) {
  const { t } = useI18n()
  const isNew = !item?.id
  const [amount, setAmount] = useState('')
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('')
  const [account, setAccount] = useState('')
  const [comment, setComment] = useState('')
  const [kind, setKind] = useState('expense')
  const [to, setTo] = useState('')   // перевод: счёт-получатель (API: to_account)
  const [date, setDate] = useState('')
  const [saving, setSaving] = useState(false)
  const [amountErr, setAmountErr] = useState('')
  const [askDel, setAskDel] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    if (item) {
      setAmount(String(Math.abs(item.amount || 0)))
      setTitle(item.title || item.note || '')   // описание хранится в note
      setCategory(item.category || '')
      setAccount(item.account || '')
      setComment(item.comment || '')
      // переводы форма не редактирует — сохраняем их тип, иначе трата/доход «съест» перевод
      setKind(item.kind === 'income' ? 'income' : item.kind === 'transfer' ? 'transfer' : 'expense')
      setTo(item.to_account || '')
      setDate(item.date ? item.date.slice(0, 10) : toLocalISO(new Date()).slice(0, 10))
    } else {
      setAmount('')
      setTitle('')
      setCategory('')
      setAccount(accounts[0]?.name || '')
      setComment('')
      setKind('expense')
      setTo('')
      setDate(toLocalISO(new Date()).slice(0, 10))
    }
    setAmountErr('')
  }, [open, item])

  const submit = async (e) => {
    if (e) e.preventDefault()
    // parseNum, а не parseFloat: поле Money на blur форматирует «18 000» (пробел/NBSP),
    // parseFloat читает только «18» — сумма теряла разряды
    const a = parseNum(amount)
    if (isNaN(a)) return
    // нулевая сумма не «тихая»: кнопка активна, поэтому объясняем прямо в форме (D3);
    // отрицательные и нечисловые значения ведут себя как раньше (Math.abs / игнор)
    if (a === 0) { setAmountErr(t('or.amount_zero')); return }
    setAmountErr('')
    setSaving(true)
    try {
      // API принимает положительную сумму и kind; описание/комментарий кладём в note
      const payload = {
        amount: Math.abs(a),
        kind,
        category: kind === 'transfer' ? undefined : (category.trim() || undefined),
        note: [title.trim(), comment.trim()].filter(Boolean).join(' · ') || undefined,
        account: account.trim() || undefined,
        // перевод: счёт-получатель; ядро переводит сумму между двумя счетами
        to_account: kind === 'transfer' ? (to.trim() || undefined) : undefined,
        date: date ? `${date}T${item?.date ? item.date.slice(11, 19) : '12:00:00'}` : toLocalISO(new Date()).slice(0, 10),
      }
      if (isNew) {
        await api.addTx(payload)
      } else {
        await api.updateTx(item.id, payload)
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={isNew ? t('fin.add_tx') : t('fin.edit_tx')}>
      <form onSubmit={submit} className="space-y-4">
        <div className="seg">
          <button type="button" className={kind === 'expense' ? 'on' : ''} aria-pressed={kind === 'expense'} onClick={() => setKind('expense')}>{t('fin.expense')}</button>
          <button type="button" className={kind === 'income' ? 'on' : ''} aria-pressed={kind === 'income'} onClick={() => setKind('income')}>{t('fin.income')}</button>
          {/* t.kind_transfer — существующий ключ SERVER («перевод»), новых ключей i18n не добавляем */}
          <button type="button" className={kind === 'transfer' ? 'on' : ''} aria-pressed={kind === 'transfer'} onClick={() => { setKind('transfer'); if (!account && accounts[0]) setAccount(accounts[0].name) }}>{t.kind_transfer}</button>
        </div>
        <Field label={t('fin.amount_rub')} error={amountErr}>
          <Money value={amount} onChange={setAmount} min={0} placeholder="1000" autoFocus required />
        </Field>
        <Field label={t('fin.description')}>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('fin.desc_ph')} />
        </Field>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {/* у перевода категории нет — ядро её всё равно обнуляет */}
          {kind !== 'transfer' && (
            <Field label={t('common.category')}>
              <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} placeholder={t('fin.cat_ph')} list="cat-list" />
              <datalist id="cat-list">
                {categories.map(c => <option key={c.id || c.name || c} value={c.name || c} />)}
              </datalist>
            </Field>
          )}
          <Field label={t('graph.one_account')}>
            <select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>
              <option value="">{t('fin.not_set')}</option>
              {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
            </select>
          </Field>
          {kind === 'transfer' && (
            <Field label={t('or.to_account')}>
              <select className="input" value={to} onChange={(e) => setTo(e.target.value)} required>
                <option value="">{t('fin.not_set')}</option>
                {accounts.filter((a) => a.name !== account).map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
              </select>
            </Field>
          )}
        </div>
        <Field label={t('common.date')}>
          <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label={t('common.comment')}>
          <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder={t('common.optional')} />
        </Field>
        <div className="flex justify-between gap-2 pt-4">
          {!isNew && (
            <button type="button" className="btn g !text-[var(--neg)]" onClick={() => setAskDel(true)}>{t('common.delete')}</button>
          )}
          <div className="ml-auto flex gap-2">
            <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
            <button
              type="submit"
              className="btn"
              // перевод без получателя или «на тот же счёт» — ядро откажет, не даём отправить заранее
              disabled={saving || !amount || (kind === 'transfer' && (!to || (!!account && to === account)))}
            >{saving ? t('people.saving') : t('common.save')}</button>
          </div>
        </div>
      </form>
      <Confirm open={askDel} danger title={t('fin.del_tx_q')} text={t('fin.del_tx_text')}
        onOk={async () => { setAskDel(false); try { await api.delTx(item.id); onDone(t('fin.tx_deleted')) } catch (err) { show.err(err) } }}
        onClose={() => setAskDel(false)} />
    </Sheet>
  )
}

function AccountSheet({ open, account, debts = [], onClose, onDone }) {
  const { t, lang } = useI18n()
  const L = FIN[lang] || FIN.ru
  const isNew = !account?.id
  const [name, setName] = useState('')
  const [balance, setBalance] = useState('')
  const [type, setType] = useState('card')
  const [debtId, setDebtId] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  const isDebt = type === 'debt_only'

  useEffect(() => {
    if (!open) return
    const kind = account?.type || account?.kind || 'card'
    setName(account?.name || '')
    // у кредитки баланс — долг: в поле показываем его положительной суммой
    setBalance(account?.balance != null
      ? String(kind === 'debt_only' ? Math.abs(account.balance) : account.balance)
      : '')
    setType(kind)
    setDebtId(account?.debt_id != null ? String(account.debt_id) : '')
  }, [open, account])

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const amount = Math.abs(parseNum(balance) || 0)
      const payload = {
        name: name.trim(),
        // кредитка хранит долг со знаком минус, чтобы траты его увеличивали
        balance: type === 'debt_only' ? -amount : (parseNum(balance) || 0),
        type,
        kind: type,   // сиды хранят kind, форма — type: держим оба, чтобы иконка и расчёты сходились
      }
      let accId = account?.id
      if (isNew) {
        const created = await api.addAccount(payload)
        accId = created?.id || accId
      } else {
        await api.updateAccount(account.id, payload)
      }
      // связка с долгом — отдельным вызовом (бэкенд держит инвариант баланс = −remaining)
      if (isDebt && accId) {
        if (debtId) {
          await api.linkDebtAccount(accId, Number(debtId))
        } else if (!isNew && account?.debt_id) {
          await api.unlinkDebtAccount(accId)
        }
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={isNew ? t('fin.add_account') : t('fin.edit_account')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('acc.name')}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('acc.name_ph')} />
        </Field>
        <Field label={isDebt ? L.debt_now : t('acc.current_balance')} hint={isDebt ? L.debt_hint : undefined}>
          <Money value={balance} onChange={setBalance} placeholder="0" />
        </Field>
        <Field label={t('acc.type')}>
          <select className="input" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="card">{t('acc.bank_card')}</option>
            <option value="cash">{t('acc.cash')}</option>
            <option value="bank">{t('acc.deposit')}</option>
            <option value="crypto">{t('acc.crypto_wallet')}</option>
            <option value="debt_only">{L.credit_card}</option>
          </select>
        </Field>
        {isDebt && (
          <Field label={L.link_debt} hint={L.debt_hint}>
            <select className="input" value={debtId} onChange={(e) => setDebtId(e.target.value)}>
              <option value="">{L.no_link}</option>
              {debts.filter((d) => !d.closed).map((d) => (
                <option key={d.id} value={String(d.id)}>
                  {(d.title || d.name) + ' · ' + money(d.remaining ?? d.total ?? 0)}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !name.trim()}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function DebtSheet({ open, debt, onClose, onDone }) {
  const { t } = useI18n()
  const isNew = !debt?.id
  const [name, setName] = useState('')
  const [creditor, setCreditor] = useState('')
  const [kind, setKind] = useState('credit')
  const [total, setTotal] = useState('')
  const [remaining, setRemaining] = useState('')
  const [paid, setPaid] = useState('0')
  const [rate, setRate] = useState('0')
  const [payment, setPayment] = useState('0')
  const [payDay, setPayDay] = useState('1')
  const [limit, setLimit] = useState('0')
  const [color, setColor] = useState('')
  const [note, setNote] = useState('')
  const [remindDays, setRemindDays] = useState('3')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    const tot = Number(debt?.total)
    const rem = debt?.remaining != null ? Number(debt.remaining) : tot
    setName(debt?.name || debt?.title || '')
    setCreditor(debt?.creditor || '')
    setKind(debt?.kind || 'credit')
    setTotal(debt?.total != null ? String(round2(debt.total)) : '')
    setRemaining(Number.isFinite(rem) ? String(round2(rem)) : '')
    setPaid(Number.isFinite(tot) && Number.isFinite(rem) ? String(round2(Math.max(0, tot - rem))) : '0')
    setRate(debt?.rate != null ? String(debt.rate) : '0')
    setPayment(debt?.payment != null ? String(debt.payment) : '0')
    setPayDay(debt?.pay_day != null ? String(debt.pay_day) : '1')
    setLimit(debt?.credit_limit != null ? String(debt.credit_limit) : '0')
    setColor(debt?.color || '')
    setNote(debt?.note || '')
    setRemindDays(debt?.remind_days != null ? String(debt.remind_days) : '3')
  }, [open, debt])

  const nTotal = parseNum(total)
  const nRemaining = parseNum(remaining)
  const nPaid = parseNum(paid)
  const nRate = Number.isNaN(parseNum(rate)) ? 0 : parseNum(rate)
  const nPayment = Number.isNaN(parseNum(payment)) ? 0 : parseNum(payment)
  const nDay = Number.isNaN(parseNum(payDay)) ? 0 : parseNum(payDay)
  const nLimit = Number.isNaN(parseNum(limit)) ? 0 : parseNum(limit)
  const nRemind = Number.isNaN(parseNum(remindDays)) ? 0 : parseNum(remindDays)

  const errTotal = total !== '' && !(nTotal > 0) ? t('fin.debt_err_total') : ''
  const errRemaining = total !== '' && (Number.isNaN(nRemaining) || nRemaining < 0 || nRemaining > nTotal) ? t('fin.debt_err_remaining') : ''
  const errPaid = total !== '' && (Number.isNaN(nPaid) || nPaid < 0 || nPaid > nTotal) ? t('fin.debt_err_paid') : ''
  const errPayment = nPayment < 0 || nPayment > nTotal ? t('fin.debt_err_payment') : ''
  const errRate = nRate < 0 || nRate > 1000 ? t('fin.debt_err_rate') : ''
  const errDay = nDay < 1 || nDay > 31 ? t('fin.debt_err_day') : ''
  const errRemind = nRemind < 0 || nRemind > 60 ? t('fin.debt_err_remind') : ''
  const bad = !name.trim() || !(nTotal > 0) || !!(errTotal || errRemaining || errPaid || errPayment || errRate || errDay || errRemind)

  /* Остаток и «выплачено» — две стороны одной суммы: правишь одно, второе
     пересчитывается, но остаётся редактируемым вручную. */
  const changeTotal = (v) => {
    setTotal(v)
    const nt = parseNum(v)
    const p = parseNum(paid)
    if (!Number.isNaN(nt) && !Number.isNaN(p)) setRemaining(String(round2(Math.max(0, nt - p))))
  }
  const changePaid = (v) => {
    setPaid(v)
    const p = parseNum(v)
    const nt = parseNum(total)
    if (!Number.isNaN(p) && !Number.isNaN(nt)) setRemaining(String(round2(Math.max(0, nt - p))))
  }
  const changeRemaining = (v) => {
    setRemaining(v)
    const r = parseNum(v)
    const nt = parseNum(total)
    if (!Number.isNaN(r) && !Number.isNaN(nt)) setPaid(String(round2(Math.max(0, nt - r))))
  }

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (bad) return
    setSaving(true)
    try {
      const payload = {
        title: name.trim(),   // API ждёт `title`; `name` — устаревший алиас (422 «Field required»)
        creditor: creditor.trim(),
        total: round2(nTotal),
        payment: round2(nPayment) || 0,
        rate: nRate || 0,
        pay_day: Math.round(nDay) || 1,
        kind,
        credit_limit: round2(nLimit) || 0,
        color: normHex(color) || '',
        note: note.trim(),
        remind_days: Math.round(nRemind) || 0,
      }
      if (isNew) {
        payload.remaining = round2(nRemaining)
        await api.addDebt(payload)
      } else {
        // PUT принимает paid: остаток бэкенд пересчитает сам
        payload.paid = round2(nPaid)
        await api.updateDebt(debt.id, payload)
      }
      onDone(t('common.saved'))
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={isNew ? t('fin.add_debt') : t('fin.edit_debt')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('common.title')}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('fin.debt_ph')} />
        </Field>
        <Field label={t('fin.creditor2')}>
          <input className="input" value={creditor} onChange={(e) => setCreditor(e.target.value)} placeholder={t('fin.creditor_ph')} />
        </Field>
        <Field label={t('fin.debt_kind_field')}>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.keys(DEBT_KIND_KEY).map((k) => <option key={k} value={k}>{t(DEBT_KIND_KEY[k])}</option>)}
          </select>
        </Field>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label={t('fin.debt_initial')} error={errTotal}>
            <Money value={total} onChange={changeTotal} min={0} placeholder="50000" required />
          </Field>
          <Field label={t('fin.debt_remaining')} error={errRemaining}>
            <Money value={remaining} onChange={changeRemaining} min={0} max={Number.isNaN(nTotal) ? undefined : nTotal} required />
          </Field>
          <Field label={t('fin.debt_paid')} error={errPaid}>
            <Money value={paid} onChange={changePaid} min={0} max={Number.isNaN(nTotal) ? undefined : nTotal} />
          </Field>
          <Field label={t('fin.debt_rate')} error={errRate}>
            <input className="input num" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="0" />
          </Field>
          <Field label={t('fin.debt_payment')} error={errPayment}>
            <Money value={payment} onChange={setPayment} min={0} max={Number.isNaN(nTotal) ? undefined : nTotal} />
          </Field>
          <Field label={t('fin.debt_pay_day')} error={errDay}>
            <input className="input num" type="number" min={1} max={31} step={1} value={payDay} onChange={(e) => setPayDay(e.target.value)} />
          </Field>
        </div>

        {kind === 'credit_card' && (
          <Field label={t('fin.debt_limit')} hint={t('fin.debt_limit_hint')}>
            <Money value={limit} onChange={setLimit} min={0} placeholder="100000" />
          </Field>
        )}

        <SwatchRow label={t('fin.debt_color')} value={color} onChange={setColor} showDefault custom />
        <Field label={t('common.note')}>
          <textarea className="input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('fin.debt_note_ph')} />
        </Field>
        <Field label={t('fin.debt_remind')} hint={t('fin.debt_remind_hint')} error={errRemind}>
          <input className="input num" type="number" min={0} max={60} step={1} value={remindDays} onChange={(e) => setRemindDays(e.target.value)} />
        </Field>

        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || bad}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function PayDebtSheet({ open, debt, accounts = [], onClose, onDone }) {
  const { t } = useI18n()
  const [amount, setAmount] = useState('')
  const [account, setAccount] = useState('none')
  const [date, setDate] = useState('')
  const [note, setNote] = useState('')
  const [accErr, setAccErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  // по умолчанию — «не списывать»: счёт пользователь выбирает сам, а не таём первый попавшийся
  useEffect(() => {
    if (!open) return
    setAccount('none')
    setAccErr('')
    setAmount('')
    setDate(toLocalISO(new Date()).slice(0, 10))
    setNote('')
  }, [open, debt])

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseNum(amount)
    if (!a || isNaN(a) || !debt?.id) return
    if (debt?.remaining != null && a > Number(debt.remaining) + 0.005) {
      show(t('fin.debt_pay_err_max'), 'err')
      return
    }
    // «не списывать» бэкенд не умеет, а пустой счёт превратился бы в основной —
    // просим выбрать честно (деньги всё равно ушли бы)
    if (account === 'none') { setAccErr(t('fin.pick_account')); return }
    setAccErr('')
    setSaving(true)
    try {
      await api.payDebt(debt.id, a, {
        account,
        date: date || undefined,
        note: note.trim() || undefined,
      })
      onDone(t('fin.pay_made'))
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={t('fin.pay_debt_title', { name: debt?.name || debt?.title || '' })}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('fin.pay_amount')}>
          <Money value={amount} onChange={setAmount} min={0} max={debt?.remaining != null ? Number(debt.remaining) : undefined} placeholder="5000" autoFocus required />
        </Field>
        <Field label={t('fin.charge')} error={accErr} hint={t('fin.charge_hint')}>
          <select className="input" value={account} onChange={(e) => { setAccount(e.target.value); if (accErr) setAccErr('') }}>
            <option value="none">{t('fin.no_charge')}</option>
            {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
          </select>
        </Field>
        <Field label={t('fin.debt_pay_date')}>
          <input type="date" className="input" value={date} max={toLocalISO(new Date()).slice(0, 10)} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label={t('fin.debt_pay_note')}>
          <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('fin.debt_pay_note_ph')} />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !amount}>{saving ? t('people.saving') : t('fin.submit')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function RecurringSheet({ open, item, categories = [], onClose, onDone }) {
  const { t, lang } = useI18n()
  const L = FIN[lang] || FIN.ru
  const isNew = !item?.id
  const [name, setName] = useState('')
  const [amount, setAmount] = useState('')
  const [category, setCategory] = useState('')
  const [period, setPeriod] = useState('monthly')
  const [day, setDay] = useState('1')
  const [month, setMonth] = useState('1')
  const [kind, setKind] = useState('expense')   // expense — списание, income — регулярный доход
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    const p = item?.period || 'monthly'
    setName(item?.name || item?.title || '')
    setAmount(item?.amount != null ? String(item.amount) : '')
    setCategory(item?.category || '')
    setPeriod(p)
    setDay(item?.day != null ? String(item.day) : (p === 'weekly' ? '0' : '1'))
    // месяц годового платежа хранится в next_date — берём его, иначе текущий
    const m = item?.next_date ? new Date(item.next_date).getMonth() + 1 : new Date().getMonth() + 1
    setMonth(String(m))
    setKind(item?.kind === 'income' ? 'income' : 'expense')
  }, [open, item])

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const payload = {
        title: name.trim(),   // API ждёт `title`; `name` — устаревший алиас (422 «Field required»)
        amount: parseNum(amount) || 0,
        category: category.trim() || undefined,
        period,
        day: period === 'weekly' ? (parseInt(day, 10) || 0) : (parseInt(day, 10) || 1),
        kind,
        // месяц имеет смысл только у годового платежа
        month: period === 'yearly' ? (parseInt(month, 10) || 1) : undefined,
      }
      if (isNew) {
        await api.addRecurring(payload)
      } else {
        await api.updateRecurring(item.id, payload)
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  const isIncome = kind === 'income'
  const weekdays = WEEKDAYS[lang] || WEEKDAYS.ru
  const months = MONTHS[lang] || MONTHS.ru
  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={isNew ? t('fin.add_pay') : t('fin.edit_pay2')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('fin.kind')} hint={t('fin.outflow_hint')}>
          <div className="seg">
            <button type="button" className={!isIncome ? 'on' : ''} aria-pressed={!isIncome} onClick={() => setKind('expense')}>{t('fin.outflow')}</button>
            <button type="button" className={isIncome ? 'on' : ''} aria-pressed={isIncome} onClick={() => setKind('income')}>{t('fin.income')}</button>
          </div>
        </Field>
        <Field label={t('common.title')}>
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('fin.pay_ph2')} />
        </Field>
        <Field label={L.amount}>
          <Money value={amount} onChange={setAmount} min={0} placeholder="499" required />
        </Field>
        {/* Период: месяц / неделя / год. Раньше форма умела только «каждый месяц» —
            годовой платёж (сертификат, ОСАГО, налог) завести было нельзя. */}
        <Field label={L.period}>
          <div className="seg">
            <button type="button" className={period === 'monthly' ? 'on' : ''} aria-pressed={period === 'monthly'} onClick={() => setPeriod('monthly')}>{L.monthly}</button>
            <button type="button" className={period === 'weekly' ? 'on' : ''} aria-pressed={period === 'weekly'} onClick={() => setPeriod('weekly')}>{L.weekly}</button>
            <button type="button" className={period === 'yearly' ? 'on' : ''} aria-pressed={period === 'yearly'} onClick={() => setPeriod('yearly')}>{L.yearly}</button>
          </div>
        </Field>
        {period === 'weekly' ? (
          <Field label={L.day_of_week}>
            <select className="input" value={day} onChange={(e) => setDay(e.target.value)}>
              {weekdays.map((w, i) => <option key={i} value={String(i)}>{w}</option>)}
            </select>
          </Field>
        ) : (
          <Field label={t('fin.pay_day')}>
            <input className="input" type="number" min="1" max="31" value={day} onChange={(e) => setDay(e.target.value)} />
          </Field>
        )}
        {period === 'yearly' && (
          <Field label={L.month}>
            <select className="input" value={month} onChange={(e) => setMonth(e.target.value)}>
              {months.map((m, i) => <option key={i} value={String(i + 1)}>{m}</option>)}
            </select>
          </Field>
        )}
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !name.trim()}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function GoalSheet({ open, goal, onClose, onDone }) {
  const { t } = useI18n()
  const isNew = !goal?.id
  const [title, setTitle] = useState('')
  const [target, setTarget] = useState('')
  const [current, setCurrent] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setTitle(goal?.title || goal?.name || '')
    setTarget(goal?.target != null ? String(goal.target) : '')
    // у бэкенда поле называется saved — по current заполнялось нулём
    const saved0 = goal?.saved ?? goal?.current ?? 0
    setCurrent(String(saved0))
  }, [open, goal])

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (!title.trim()) return
    setSaving(true)
    try {
      const payload = {
        title: title.trim(),
        target: parseNum(target) || 0,
        // GoalIn/GoalPatch ждут saved: поле current бэкенд молча отбрасывал
        saved: parseNum(current) || 0,
      }
      if (isNew) {
        await api.addGoal(payload)
      } else {
        await api.updateGoal(goal.id, payload)
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={isNew ? t('fin.add_goal') : t('fin.edit_goal')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('gl.goal_name')}>
          <input className="input" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t('gl.goal_ph2')} />
        </Field>
        <Field label={t('gl.target')}>
          <Money value={target} onChange={setTarget} min={1} placeholder="100000" required />
        </Field>
        <Field label={t('gl.saved')}>
          <Money value={current} onChange={setCurrent} min={0} placeholder="0" />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !title.trim()}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function PutGoalSheet({ open, goal, accounts = [], onClose, onDone }) {
  const { t } = useI18n()
  const [amount, setAmount] = useState('')
  const [account, setAccount] = useState('none')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  // по умолчанию — «не списывать»: баланс не трогаем, пока пользователь сам не выберет счёт
  useEffect(() => { if (open) setAccount('none') }, [open])

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseNum(amount)
    if (!a || isNaN(a) || !goal?.id) return
    setSaving(true)
    try {
      // «не списывать» = просто отметить накопление: GoalPut.record_tx=false, транзакция не создаётся
      if (account === 'none') await api.putGoal(goal.id, a, { record_tx: false })
      else await api.putGoal(goal.id, a, { account })
      onDone(t('fin.topped_up'))
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={t('fin.top_up_title', { name: goal?.title || goal?.name || '' })}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('fin.top_amount')}>
          <Money value={amount} onChange={setAmount} min={0} placeholder="2000" autoFocus required />
        </Field>
        <Field label={t('fin.charge')} hint={t('fin.top_hint')}>
          <select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="none">{t('fin.no_charge')}</option>
            {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
          </select>
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !amount}>{saving ? t('people.saving') : t('fin.top_up')}</button>
        </div>
      </form>
    </Sheet>
  )
}

/* Месячный лимит категории: хранится в Category.budget, раздел «лимиты» читает его
   через /api/finance/budgets. Лимит необязателен — 0 или пусто означает «без контроля». */
function BudgetSheet({ open, item, categories = [], onClose, onDone }) {
  const { t } = useI18n()
  const [cid, setCid] = useState('')
  const [amount, setAmount] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()
  const options = useMemo(() => categories.filter((c) => c.kind !== 'income'), [categories])

  useEffect(() => {
    if (!open) return
    // item приходит со строки бюджета; для «+ лимит» берём первую расходную категорию
    const chosen = item?.id != null ? (options.find((c) => c.id === item.id) || item) : options[0]
    setCid(chosen?.id != null ? String(chosen.id) : '')
    setAmount(chosen?.budget ? String(chosen.budget) : '')
  }, [open, item?.id, options.length])

  const pick = (id) => {
    setCid(id)
    const c = options.find((x) => String(x.id) === id)
    setAmount(c?.budget ? String(c.budget) : '')
  }

  const submit = async (e) => {
    if (e) e.preventDefault()
    const id = Number(cid)
    if (!id) return
    setSaving(true)
    try {
      const n = parseFloat(String(amount).replace(/\s|\u00a0/g, '').replace(',', '.')) || 0
      await api.updateCategory(id, { budget: n })
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet bodyClass={FIELD_LABEL_M} open={open} onClose={onClose} title={t('fin.limit_month')} sub={t('fin.limit_optional')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('common.category')}>
          <select className="input" value={cid} onChange={(e) => pick(e.target.value)} autoFocus>
            {!options.length && <option value="">{t('fin.no_exp_cats')}</option>}
            {options.map((c) => <option key={c.id} value={c.id}>{c.icon} {c.name}{c.budget ? ` · ${money(c.budget)}` : ''}</option>)}
          </select>
        </Field>
        <Field label={t('fin.limit_month_rub')} hint={t('fin.zero_no_limit')}>
          <Money value={amount} onChange={setAmount} min={0} placeholder="0" />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !cid}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}