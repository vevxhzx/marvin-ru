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
import { Sheet, Field, Empty, Money, Rowi, Skeleton, useToast, Confirm } from '../components/ui'
import { BigMoney, HeroLine, useNumFormats, useReveal } from '../components/Widgets'
import CashChart from '../components/CashChart'
import LifeRegime from '../components/LifeRegime'
import { ImportButton } from '../components/Widgets'
import { useRefresh } from '../App'
import { Plus, Search, Trash2, X, Edit2, CreditCard, Wallet, Landmark, PiggyBank, Target, ChevronLeft, ChevronRight, EyeOff, Settings2 } from 'lucide-react'
import { Techniques } from '../components/FinanceSmart'
import { useCardLayout, CardCtl } from '../lib/layout'
import { usePageAccent } from '../lib/prefs'
import { useI18n, localeOf, t as T } from '../lib/i18n'
import { usePhone } from '../lib/motion'
// Overview-only glass reskin lives here (NOT in index.css — owned by another agent).
import '../fin-glass.css'

/* Подписи полей на узком телефоне (≤380px) — на ступень мельче: длинная подпись
   вроде «дата следующего шага» на 375px съедала строку и отжимала само поле. */
const FIELD_LABEL_M = 'max-[380px]:[&_.label]:text-[length:11px]'

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
const FIN_CARD_WIDTHS = { flow: 12, budgets: 12, upcoming: 12 }
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
  ru: { credit_card: 'кредитка', debt_now: 'долг сейчас', debt: 'долг', period: 'период', monthly: 'месяц', weekly: 'неделя', yearly: 'год', day_of_week: 'день недели', month: 'месяц', amount: 'сумма, ₽', paused_section: 'на паузе', debt_hint: 'траты с неё растут в долг, перевод на неё — уменьшает' },   // i18n-raw
  en: { credit_card: 'credit card', debt_now: 'debt now', debt: 'debt', period: 'period', monthly: 'month', weekly: 'week', yearly: 'year', day_of_week: 'weekday', month: 'month', amount: 'amount, ₽', paused_section: 'paused', debt_hint: 'spending grows the debt, a transfer to it pays it down' },
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
    <section className={`${CARD_M} ${className}`} data-reveal>
      <div className="hd flex-wrap">
        <div className="min-w-0"><h2 className="trunc" title={title}>{title}</h2></div>
        <div className="flex items-center gap-2">
          {note && <small className="trunc">{note}</small>}
          {action}
        </div>
      </div>
      {children}
    </section>
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
  const [recurring, setRecurring] = useState([])
  const [goals, setGoals] = useState([])
  const [categories, setCategories] = useState([])
  const [techniquesData, setTechniquesData] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [budgets, setBudgets] = useState(null)
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
  const { order: cardOrder, setOrder: setCardOrder, move, reset: resetCards } = useCardLayout('finance', FIN_CARDS, FIN_CARD_WIDTHS)
  const pageAcc = usePageAccent('finance')
  const reveal = useReveal(tab)

  const [, show] = useToast()
  const { tick, bump } = useRefresh()
  const phone = usePhone()          // ≤820px: телефонная раскладка по макету

  const load = async () => {
    try {
      const [s, t, accs, d, rec, g, cats, tech, fc, bg, rg] = await Promise.all([
        api.finSummary(days).catch(() => null),
        api.txs(days).catch(() => []),
        api.accounts().catch(() => []),
        api.debts().catch(() => []),
        api.recurring(true).catch(() => []),   // с паузами: паузы нужно видеть и включать
        api.goals().catch(() => []),
        api.categories().catch(() => []),
        api.techniques().catch(() => null),
        api.finForecast(days || 90).catch(() => null),
        api.budgets().catch(() => null),
        api.get('/api/finance/regimes').catch(() => null),   // режим жизни (по умолчанию выключен)
      ])
      if (s) setSum(s)
      setTxs(t || [])
      setAccounts(accs || [])
      setDebts(d || [])
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
  // ДОЛГИ (visual-only): кольцо сводки — доля выплаченного, те же debts/total/paid
  const debtTotalAll = debts.reduce((s, d) => s + (Number(d.total) || 0), 0)
  const debtPaidAll = debts.reduce((s, d) => s + (Number(d.paid) || 0), 0)
  const debtPct = debtTotalAll > 0 ? Math.min(100, Math.round((debtPaidAll / debtTotalAll) * 100)) : 0
  const DONUT_C = 2 * Math.PI * 52

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
        : tab === 'debts' ? t('fin.n_debts', { count: debts.length })
          : tab === 'recurring' ? t('fin.n_rec', { n: recActive.length, paused: recPaused.length ? t('fin.n_rec_paused', { n: recPaused.length }) : '' })
            : tab === 'goals' ? t('fin.n_goals', { count: goals.length })
              : t('tech.title')

  return (
    <div className={`pg on ${FIELD_LABEL_M}`} id="p-fin" style={pageAcc.style} ref={reveal}>
      {/* Шапка экрана: заголовок, что показываем, и действия справа */}
      <header className="top" data-reveal>
        <div className="min-w-0">
          <h1>{t('nav.finance')}</h1>
          <p className="sub">{tabLine}</p>
        </div>
        <div className="hr">
          {/* Переключатель периода — в шапке: период режет данные ВСЕХ вкладок (обзор, операции,
              счета, долги), а не только списка операций. Тот же сегмент .sg в .top, что на
              задачах и календаре — и по нему ходят проверки e2e (#p-fin .top .sg[title^="период"]). */}
          <div className={`sg fg-seg ${SEG_ROW_M}`} role="group" aria-label={t('fin.period_tip')} title={t('fin.period_tip')}>
            {[[7, 'mem.d7'], [30, 'mem.d30'], [90, 'fin.d90'], [0, 'fin.d_all']].map(([v, key]) => (
              <button key={v} type="button" className={days === v ? 'on' : ''} aria-pressed={days === v} onClick={() => setDays(v)}>
                {t(key)}
              </button>
            ))}
          </div>
          {/* Настройка разделов — одна точка входа: на десктопе кнопка с подписью,
              на телефоне та же кнопка иконкой (aria-label и тултип на месте). */}
          {tab === 'overview' && (
            <button type="button" className={`btn-soft btn-sm ${phone ? '!px-2.5' : ''}`} onClick={() => setCardsEdit((v) => !v)}
              title={t('tk.layout_tip')} aria-label={t('fin.configure_cards')}>
              {phone ? <Settings2 size={15} /> : t('tk.layout')}
            </button>
          )}
          {/* Выписка — не в шапке: на телефоне она живёт рядом с фильтрами списка
              операций (там, где выгрузка и нужна), поэтому в шапке остаётся одно действие. */}
          {!phone && (
            <button type="button" className="btn-soft btn-sm" onClick={exportCSV}
              title={t('fin.csv_dl')} aria-label={t('fin.csv_dl')}>
              {t('fin.statement')}
            </button>
          )}
          {/* На ПК добавление в шапке; на телефоне — «+» в доке */}
          <button
            type="button"
            className="btn btn-sm head-primary fg-add max-[820px]:!hidden"
            title={t('fin.add_entry')}
            aria-label={t('fin.add_entry')}
            onClick={addForTab}
          >
            {t(tab === 'accounts' ? 'fin.add_account' : tab === 'debts' ? 'fin.add_debt' : tab === 'recurring' ? 'fin.add_pay' : tab === 'goals' ? 'fin.add_goal' : 'fin.add_tx')}
          </button>
        </div>
      </header>

      {/* Режим жизни перенесён в «Настройки» — на главной финансов его быть не должно */}

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
          <section className={`c hero fg-hero col-span-12 min-[821px]:col-span-7 ${CARD_M_LIGHT} ${HERO_M}`} data-reveal>
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
          </section>

          {/* Запас хода: кольцо тиков из референса (30 тиков, статичный инлайн-SVG).
              Значения переиспользуются: дни — forecast.runway_days, сумма — balance. */}
          <section className={`c fg-card fg-runway col-span-12 min-[821px]:col-span-5 ${CARD_M_LIGHT}`} data-reveal>
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
          </section>

          {/* Один график на экран: касса на N дней, интерактивный, с подсказками ChartTip */}
          <section className={`c chart fg-card fg-cash mt-4 ${CARD_M_LIGHT} col-span-12`} data-reveal>
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
              <span><i style={{ background: '#ff9f5c' }}></i>{t('chart.fact')}</span>
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
          </section>

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
                  <section key="flow" data-reveal className={`relative fg-card fg-flow col-span-12 min-[821px]:col-span-4 ${CARD_M}`}>
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
                  <section key="budgets" data-reveal className={`relative fg-card fg-limits col-span-12 min-[821px]:col-span-4 ${CARD_M}`}>
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
                <section key="upcoming" data-reveal className={`relative fg-card fg-upcoming col-span-12 min-[821px]:col-span-4 ${CARD_M}`}>
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
          <section className={`c fg-card fg-acc-hero col-span-12 ${CARD_M_LIGHT}`} data-reveal>
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
                  <section className={`c fg-card fg-acct ${CARD_M_LIGHT}`} data-reveal key={a.id || a.name}>
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

      {/* ---------------- ДОЛГИ (ver6: сводка с кольцом + тонкие бары + лаймовая кнопка) ---------------- */}
      {tab === 'debts' && (
        <div className="bento mt-4">
          <section className={`c s4 glass-card gc-debts fg-debt-top ${CARD_M_LIGHT}`} data-reveal>
            <div className="min-w-0">
              <div className="hd flex-wrap">
                <div className="min-w-0"><h2 className="trunc">{t('fin.total_debt')}</h2></div>
              </div>
              <BigMoney value={debtsTotal} format={fmt.int} label={money(debtsTotal)} fs="clamp(24px, 2.6vw, 34px)" />
              <div className="muted mt-2 text-[length:var(--fs-md)]">{t('fin.n_active_debt', { count: debts.length })}</div>
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
          {!debts.length ? (
            <section className={`c s8 ${CARD_M_LIGHT}`} data-reveal>
              <Empty glyph="debt" text={t('td.clean')} sub={t('td.nothing_missed')}
                action={<button type="button" className="btn" onClick={() => { setEditingItem(null); setSheet('debt') }}><Plus size={15} /> {t('fin.add_debt')}</button>} />
            </section>
          ) : (
            <CarRow count={debts.length} label={t('fin.total_debt')}>
              {debts.map((d) => {
              const total = d.total || 1
              const paid = d.paid || 0
              const left = Math.max(0, total - paid)
              const pct = Math.min(100, Math.round((paid / total) * 100))
              return (
                <section key={d.id} data-car className={`c s4 glass-card gc-debts ${CARD_M_LIGHT}`} data-reveal>
                  <div className="hd flex-wrap">
                    <div className="min-w-0"><h2 className="clamp-2" style={{ fontWeight: 600, color: 'var(--ink)' }}>{d.name || d.title}</h2></div>
                    <small className="trunc">{d.creditor || t('fin.creditor')}</small>
                  </div>
                  <BigMoney value={left} format={fmt.int} label={money(left)} fs="clamp(22px, 2.4vw, 30px)" />
                  <div className="progress fg-debtbar mt-3" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                    <div style={{ width: `${pct}%`, background: GRAD_BAR, boxShadow: BAR_GLOW }} />
                  </div>
                  <div className="muted mt-2 text-[length:var(--fs-xs)]">
                    {t('fin.paid_out')} <b className="num pos">{fmt.money(paid)}</b> (<b className="num">{fmt.int(pct)} %</b>) · {t('fin.of')} {fmt.money(total)}
                  </div>
                  <div className="mt-3">
                    <RowActions>
                      <button type="button" className="btn btn-sm fg-pay" onClick={() => { setEditingItem(d); setSheet('payDebt') }}>{t('fin.make_payment')}</button>
                      <IconBtn onClick={() => { setEditingItem(d); setSheet('debt') }} title={t('common.edit')}><Edit2 size={14} /></IconBtn>
                      <IconBtn
                        danger
                        title={t('common.delete_title')}
                        onClick={() => setAsk({
                          title: t('fin.del_debt_q_name', { name: d.name || d.title }),
                          text: t('fin.del_debt_text'),
                          msg: t('fin.debt_deleted'),
                          run: () => api.delDebt(d.id),
                        })}
                      >
                        <Trash2 size={14} />
                      </IconBtn>
                    </RowActions>
                  </div>
                </section>
              )
            })}
            </CarRow>
          )}
        </div>
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
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
      />

      <DebtSheet
        open={sheet === 'debt'}
        debt={editingItem}
        onClose={() => { setSheet(null); setEditingItem(null) }}
        onDone={() => { setSheet(null); setEditingItem(null); load(); bump() }}
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

function AccountSheet({ open, account, onClose, onDone }) {
  const { t, lang } = useI18n()
  const L = FIN[lang] || FIN.ru
  const isNew = !account?.id
  const [name, setName] = useState('')
  const [balance, setBalance] = useState('')
  const [type, setType] = useState('card')
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
      if (isNew) {
        await api.addAccount(payload)
      } else {
        await api.updateAccount(account.id, payload)
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
  const [total, setTotal] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setName(debt?.name || debt?.title || '')
    setCreditor(debt?.creditor || '')
    setTotal(debt?.total != null ? String(debt.total) : '')
  }, [open, debt])

  const submit = async (e) => {
    if (e) e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const payload = {
        title: name.trim(),   // API ждёт `title`; `name` — устаревший алиас (422 «Field required»)
        creditor: creditor.trim() || undefined,
        total: parseNum(total) || 0,
      }
      if (isNew) {
        await api.addDebt(payload)
      } else {
        await api.updateDebt(debt.id, payload)
      }
      onDone()
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
        <Field label={t('fin.total_amount')}>
          <Money value={total} onChange={setTotal} min={0} placeholder="50000" required />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn g" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn" disabled={saving || !name.trim()}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

function PayDebtSheet({ open, debt, accounts = [], onClose, onDone }) {
  const { t } = useI18n()
  const [amount, setAmount] = useState('')
  const [account, setAccount] = useState('none')
  const [accErr, setAccErr] = useState('')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  // по умолчанию — «не списывать»: счёт пользователь выбирает сам, а не таём первый попавшийся
  useEffect(() => { if (open) { setAccount('none'); setAccErr('') } }, [open])

  const submit = async (e) => {
    if (e) e.preventDefault()
    const a = parseNum(amount)
    if (!a || isNaN(a) || !debt?.id) return
    // PayIn принимает только amount/account/date: «не списывать» бэкенд не умеет,
    // а пустой счёт превратился бы в основной (деньги всё равно ушли бы) — просим выбрать честно
    if (account === 'none') { setAccErr(t('fin.pick_account')); return }
    setAccErr('')
    setSaving(true)
    try {
      await api.payDebt(debt.id, a, { account })
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
          <Money value={amount} onChange={setAmount} min={0} placeholder="5000" autoFocus required />
        </Field>
        <Field label={t('fin.charge')} error={accErr} hint={t('fin.charge_hint')}>
          <select className="input" value={account} onChange={(e) => { setAccount(e.target.value); if (accErr) setAccErr('') }}>
            <option value="none">{t('fin.no_charge')}</option>
            {accounts.map((a) => <option key={a.id || a.name} value={a.name}>{a.name}</option>)}
          </select>
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