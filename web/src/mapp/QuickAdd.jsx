/* mapp/QuickAdd.jsx — шторка «+» мобильной копии (порт референса QuickAdd.tsx).
 *
 * Стили, пилюли-превью и разбор — 1:1 с референсом, но разбор только визуальный:
 * ничего сам не создаёт. Отправка — POST /api/chat тем же текстом, что шлёт
 * десктопная CaptureSheet (префиксы «задача:»/«трата:»/«мозг:», событие и доход —
 * сырой фразой: ядро разбирает их само). Фразы ядру — всегда по-русски.
 * Свои элементы — с data-testid m-qa-*.
 */
import { useEffect, useRef, useState } from 'react'
import {
  Banknote, Brain, CalendarDays, Car, Clock, Coffee, Cpu, Flame, Mic,
  Receipt, ShoppingBasket, SquareCheckBig, User, Wallet, X,
} from 'lucide-react'
import { api, money } from '../lib/api'
import { t as T, useI18n } from '../lib/i18n'
import { Overline, Pill, useSheetFocus } from './ui.jsx'

const cx = (...parts) => parts.filter(Boolean).join(' ')

const KINDS = [
  { id: 'task', key: 'm.qa_task', icon: SquareCheckBig, color: '#7d95ff' },
  { id: 'event', key: 'm.qa_event', icon: CalendarDays, color: '#c9a7ff' },
  { id: 'expense', key: 'm.qa_expense', icon: Wallet, color: '#ffc24d' },
  { id: 'income', key: 'm.qa_income', icon: Banknote, color: '#3ddc97' },
  { id: 'note', key: 'm.qa_note', icon: Brain, color: '#ff8da1' },
]

const CAT_ICON = {
  // i18n-raw: ключи категорий визуального превью — не строки интерфейса
  taxi: [Car, '#3ddc97'],
  food: [ShoppingBasket, '#ffc24d'],
  cafe: [Coffee, '#ff8da1'],
  subs: [Receipt, '#c9a7ff'],
  tech: [Cpu, '#7d95ff'],
}

// i18n-raw: примеры уходят в ядро — ядро понимает русские фразы (как подсказки десктопного чата)
const EXAMPLES = [
  'завтра в 12 созвон с кадром', // i18n-raw
  'потратил 450 на такси', // i18n-raw
  'идея: ролик про свет', // i18n-raw
  'зерно оплатило 42 000', // i18n-raw
  'срочно отправить счёт анне', // i18n-raw
]

// i18n-raw: фраза голосового мока — уходит в тот же разбор, что и ввод
const VOICE_PHRASE = 'завтра в 11 выбрать свет для интервью'

/* Лёгкий визуальный разбор для пилюль-превью (ничего не решает за ядро).
   Паттерны — русские фразы ядру, как в десктопном чате. */
// i18n-raw: регулярки разбора русских фраз — не строки интерфейса
const RE_NOTE = /^(идея|мысль|заметка|запомни|ссылка)|https?:\/\//
// i18n-raw: см. выше
const RE_EXPENSE = /потратил|купил|заплатил|оплатил\s|списал|расход/
// i18n-raw: см. выше
const RE_INCOME = /оплатил[аои]|перевел[аи]|перевёл|пришл[оаи]|получил|аванс|доход/
// i18n-raw: см. выше
const RE_EVENT = /созвон|встреч|съемк|звонок|ужин с|обед с|день рождения/
// i18n-raw: см. выше
const RE_TIME = /(\d{1,2})[:.](\d{2})/
// i18n-raw: см. выше
const RE_AMOUNT = /(\d[\d\s\u00a0]*)(к|тыс\.?)?\s?(₽|руб)/
// i18n-raw: см. выше
const RE_URGENT = /срочно|важно|!{2,}/
// i18n-raw: имена для превью — из мок-данных референса
const PEOPLE = [[/кадр/, 'Студия «Кадр»'], [/зерн/, 'Кофейня «Зерно»'], [/анн/, 'Анна'], [/мам/, 'Мама']]
// i18n-raw: категории для превью — из мок-данных референса
const CATS = [[/такси|метро/, 'taxi'], [/продукт|еда|магнит/, 'food'], [/коф|кафе|обед|ужин/, 'cafe'], [/подписк|adobe/, 'subs'], [/техник|камер|диск/, 'tech']]

function parsePreview(raw) {
  const text = String(raw || '').trim()
  if (!text) return null
  // i18n-raw: нормализация ё→е для разбора
  const low = ` ${text.toLowerCase().replace(/ё/g, 'е')} `
  let kind = 'task'
  if (RE_NOTE.test(low)) kind = 'note'
  else if (RE_EXPENSE.test(low)) kind = 'expense'
  else if (RE_INCOME.test(low)) kind = 'income'
  else if (RE_EVENT.test(low)) kind = 'event'
  let date = null
  // i18n-raw: слова-даты разбора русских фраз — не строки интерфейса
  if (low.includes('послезавтра')) date = 'after'
  else if (low.includes('завтра')) date = 'tomorrow'
  else if (low.includes('сегодня') || low.includes('утром') || low.includes('вечером')) date = 'today' // i18n-raw
  const tm = low.match(RE_TIME)
  const time = tm ? `${String(Math.min(23, +tm[1])).padStart(2, '0')}:${tm[2]}` : null
  const am = low.match(RE_AMOUNT)
  let amount = null
  if (am && (kind === 'expense' || kind === 'income' || am[3])) {
    let v = parseFloat(am[1].replace(/[\s\u00a0]/g, ''))
    if (am[2]) v *= 1000
    if (v > 0) amount = v
  }
  const person = (PEOPLE.find(([re]) => re.test(low)) || [])[1] || null
  const cat = kind === 'expense' ? ((CATS.find(([re]) => re.test(low)) || [])[1] || 'other') : null
  const urgent = RE_URGENT.test(low)
  return { kind, date, time, amount, person, cat, urgent }
}

/* Каким текстом уходит строка ядру — те же префиксы, что у CaptureSheet. */
function toCoreText(kind, text) {
  if (kind === 'task') return `${T('qa.seed_task')}: ${text}`
  if (kind === 'expense') return `${T('qa.seed_expense')}: ${text}`
  if (kind === 'note') return `${T('cap.seed_note')}: ${text}`
  return text
}

export default function MQuickAdd({ onClose, toast, go }) {
  const { t } = useI18n()
  const [text, setText] = useState('')
  const [override, setOverride] = useState(null)
  const [closing, setClosing] = useState(false)
  const [listening, setListening] = useState(false)
  const [busy, setBusy] = useState(false)
  const ref = useRef(null)
  const iv = useRef(0)
  /* Esc + ловушка Tab + возврат фокуса на кнопку «+» — как у десктопного Sheet. */
  const sheetRef = useSheetFocus(!closing, () => close())

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.focus({ preventScroll: true })
    el.setSelectionRange(el.value.length, el.value.length)
  }, [])
  const grow = (el) => {
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 148) + 'px'
  }
  useEffect(() => { grow(ref.current) }, [text])
  useEffect(() => () => window.clearInterval(iv.current), [])

  const p = text.trim() ? parsePreview(text) : null
  const kind = override || p?.kind || 'task'
  const K = KINDS.find((k) => k.id === kind) || KINDS[0]

  const close = () => {
    if (closing) return
    setClosing(true)
    window.setTimeout(onClose, 280)
  }

  /* Мок надиктовки из референса: печатает фразу как живую (визуал). */
  const listen = () => {
    if (listening) return
    setListening(true)
    setOverride(null)
    setText('')
    let i = 0
    window.clearInterval(iv.current)
    iv.current = window.setInterval(() => {
      i += 2
      setText(VOICE_PHRASE.slice(0, i))
      if (i >= VOICE_PHRASE.length) {
        window.clearInterval(iv.current)
        setListening(false)
      }
    }, 55)
  }

  const submit = async () => {
    const v = text.trim()
    if (!v || listening || busy) return
    setBusy(true)
    try {
      await api.chat(toCoreText(kind, v))
      const label = t('m.open')
      const where = kind === 'expense' || kind === 'income' ? 'finance' : kind === 'note' ? 'brain' : kind === 'event' ? 'calendar' : 'tasks'
      toast(t('m.qa_sent'), { label, fn: () => go(where) })
      close()
    } catch (e) {
      toast(String(e?.message || e) || t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const dateLabel = p?.date === 'tomorrow' ? t('m.tomorrow') : p?.date === 'today' ? t('m.today') : null

  return (
    <div data-testid="m-qa" className="absolute inset-0 z-[55]">
      <button
        type="button"
        onClick={close}
        aria-label={t('common.close')}
        className={cx(
          'absolute inset-0 cursor-default border-0 bg-[#060a24]/55 p-0 backdrop-blur-[3px] transition-opacity duration-300',
          closing ? 'opacity-0' : 'anim-fade',
        )}
      />
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('m.qa_title')}
        className={cx(
          'absolute inset-x-0 bottom-0 rounded-t-[34px] border-t border-white/15 px-5 pb-10 pt-2.5 shadow-[0_-30px_60px_-20px_rgba(0,0,0,0.6)] transition-transform duration-300',
          closing ? 'translate-y-full' : 'anim-sheet',
        )}
        style={{ background: 'linear-gradient(180deg, #1c2563 0%, #121850 100%)' }}
      >
        <div className="mx-auto h-1.5 w-10 rounded-full bg-white/25" />
        <div className="mt-4 flex items-start justify-between">
          <div>
            <Overline>{t('m.qa_hint')}</Overline>
            <h3 className="mt-1 text-[25px] font-bold tracking-[-0.02em]">{t('m.qa_title')}</h3>
          </div>
          <button
            type="button"
            onClick={close}
            aria-label={t('common.close')}
            data-testid="m-qa-close"
            className="grid h-9 w-9 place-items-center rounded-full bg-white/10 transition active:scale-90"
          >
            <X size={18} />
          </button>
        </div>

        <div
          className={cx(
            'mt-4 rounded-[24px] border bg-white/[0.06] p-4 transition',
            listening ? 'border-[#ff5c7a]/60' : 'border-white/12 focus-within:border-[#7d95ff]/60',
          )}
        >
          <textarea
            ref={ref}
            value={text}
            onChange={(e) => { setText(e.target.value); setOverride(null); grow(e.target) }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
            rows={2}
            placeholder={t('m.qa_ph')}
            data-testid="m-qa-input"
            className="w-full resize-none bg-transparent text-[17px] leading-snug outline-none placeholder:text-white/35"
          />
          <div className="mt-2 flex min-h-[28px] flex-wrap items-center gap-1.5">
            {p ? (
              <>
                <span
                  className="anim-pop inline-flex h-[26px] items-center gap-1.5 rounded-full px-2.5 text-[12px] font-semibold"
                  style={{ background: `${K.color}26`, color: K.color }}
                >
                  <K.icon size={13} />
                  {t(K.key)}
                </span>
                {(kind === 'task' || kind === 'event') && dateLabel && (
                  <Pill tone="blue" icon={CalendarDays}>{dateLabel}</Pill>
                )}
                {p.time && <Pill tone="blue" icon={Clock}>{p.time}</Pill>}
                {p.amount != null && (
                  <Pill tone={kind === 'income' ? 'green' : 'amber'}>{kind === 'income' ? `+${money(p.amount)}` : `−${money(p.amount)}`}</Pill>
                )}
                {p.cat && kind === 'expense' && p.cat !== 'other' && <Pill>{CAT_LABEL[p.cat] || p.cat}</Pill>}
                {p.person && <Pill tone="violet" icon={User}>{p.person}</Pill>}
                {p.urgent && <Pill tone="red" icon={Flame}>{t('m.urgent')}</Pill>}
              </>
            ) : (
              <span className="text-[12.5px] text-white/40">{t('m.qa_detect')}</span>
            )}
          </div>
        </div>

        {!text && (
          <div className="no-scrollbar -mx-5 mt-3 flex gap-2 overflow-x-auto px-5">
            {EXAMPLES.map((e) => (
              <button
                type="button"
                key={e}
                onClick={() => setText(e)}
                className="shrink-0 rounded-full border border-white/12 bg-white/[0.05] px-3.5 py-2 text-[13px] text-white/75 transition active:scale-95"
              >
                «{e}»
              </button>
            ))}
          </div>
        )}

        <div className="mt-4 grid grid-cols-5 gap-1.5">
          {KINDS.map((k) => {
            const on = kind === k.id
            const Icon = k.icon
            return (
              <button
                type="button"
                key={k.id}
                onClick={() => setOverride(k.id === override ? null : k.id)}
                aria-pressed={on}
                data-testid={`m-qa-kind-${k.id}`}
                className={cx(
                  'flex flex-col items-center gap-1.5 rounded-[18px] py-2.5 text-[11.5px] font-medium transition active:scale-95',
                  on ? 'bg-white/[0.12] text-white ring-1 ring-white/20' : 'text-white/55',
                )}
              >
                <span
                  className="grid h-9 w-9 place-items-center rounded-[12px]"
                  style={{ background: `${k.color}${on ? '33' : '1a'}`, color: k.color }}
                >
                  <Icon size={18} />
                </span>
                {t(k.key)}
              </button>
            )
          })}
        </div>

        <div className="mt-5 flex items-center gap-3">
          <button
            type="button"
            onClick={listen}
            aria-label={t('m.qa_voice')}
            data-testid="m-qa-mic"
            className={cx(
              'relative grid h-14 w-14 shrink-0 place-items-center rounded-full transition',
              listening ? 'bg-[#ff5c7a]' : 'm-glass',
            )}
          >
            {listening && <span className="pulse-ring absolute inset-0 rounded-full bg-[#ff5c7a]" />}
            <Mic size={22} className="relative" />
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!p || listening || busy}
            data-testid="m-qa-send"
            className={cx(
              'm-fab h-14 flex-1 rounded-full text-[16px] font-semibold transition active:scale-[0.98]',
              (!p || listening || busy) && 'opacity-45 saturate-50',
            )}
          >
            {listening ? t('m.qa_listen') : p ? t('m.qa_add_kind', { kind: t(K.key) }) : t('common.add')}
          </button>
        </div>
      </div>
    </div>
  )
}

/* Подписи категорий превью: данные разбора, не интерфейс. */
// i18n-raw: подписи категорий превью — из мок-данных референса
const CAT_LABEL = { taxi: 'такси', food: 'продукты', cafe: 'кафе', subs: 'подписки', tech: 'техника' }
