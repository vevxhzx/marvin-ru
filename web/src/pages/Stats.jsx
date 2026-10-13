import { useCallback, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Cpu, Wallet, ArrowDownToLine, ArrowUpFromLine, Tag } from 'lucide-react'
import { api } from '../lib/api'
import { useI18n } from '../lib/i18n'
import { useLoad } from '../lib/useLoad'
import { useRefresh } from '../App'
import { usePhone } from '../lib/motion'
import { Card, Empty, ErrorState, ListSkeleton, Num, PageHead, Pills, Pressable, Section, SuccessState } from '../components/ui'

/* Статистика работы ассистента: во сколько обошёлся каждый ход.
 *
 * Зачем. Хозяин платит облаку (OpenRouter/DeepSeek) и хочет видеть деньги не в логе,
 * а на экране. Данные — из /api/runs и /api/runs/report (core/api/routers/system.py),
 * считает их core/services/trace.py.
 *
 * ГЛАВНОЕ ПРАВИЛО ЭКРАНА. Если цены моделей не заданы (brain.pricing пуст), расход = 0,
 * и это НЕ «потратил ноль» — это «не знаю». Поэтому:
 *   • показываем токены всегда (их считать можно честно, цена провайдера не нужна);
 *   • деньги показываем только когда цена есть, иначе — пустое состояние «задай цену»;
 *   • никогда не подставляем «примерную» цену: неправда о деньгах дороже нуля.
 */

const PERIODS = [[7, 'st.spend_p7'], [30, 'st.spend_p30'], [90, 'st.spend_p90']]

/* Правило без локальной модели → токенов не было, платить не надо. Название пути
 * приезжает с сервера (route_ru), но ключа слов нет — значит это оно. */
const isFreeRoute = (r) => r === 'rules' || r === 'none'

/* Подпись пути: сервер присылает route_ru по-русски, но интерфейс бывает английским —
 * поэтому у известных путей есть ключ словаря, неизвестные показываем как приехали. */
const ROUTE_KEY = { rules: 'st.spend_route_rules', ollama: 'st.spend_route_ollama', gemini: 'st.spend_route_cloud' }

function routeName(t, key, ru) {
  const k = ROUTE_KEY[key]
  return k ? t(k) : (ru || key)
}

export default function Stats() {
  const { t, fmtNumber, fmtDate, fmtAgo } = useI18n()
  const [days, setDays] = useState(7)
  const { tick } = useRefresh()
  const nav = useNavigate()
  const phone = usePhone()

  const load = useCallback(async () => {
    const [rep, runs] = await Promise.all([api.runsReport(days), api.runs(60)])
    return { rep, runs }
  }, [days])
  const { data, err, loading, reload } = useLoad(load, [days, tick])

  const sp = data?.rep?.spend || null
  const items = data?.runs?.items || []

  /* Сколько стоил один ход: среднее по ходам с ценой. Не по всем — иначе «правила»
   * (их половина) разбавят облачную цену до нуля. */
  const perTurn = useMemo(() => {
    if (!sp) return 0
    const paid = items.filter((r) => r.tokens > 0 && r.priced)
    return paid.length ? paid.reduce((a, r) => a + r.cost_usd, 0) / paid.length : 0
  }, [sp, items])

  const showMoney = !!sp?.priced
  const noPrice = !!sp && !sp.priced && (sp.tokens_in > 0 || sp.tokens_out > 0)

  return (
    <div className="pg space-y-6">
      <PageHead
        kicker={t('nav.g_sys')}
        title={t('st.spend_title')}
        sub={t('st.spend_period')}
        right={
          <Pills
            value={days}
            onChange={setDays}
            label={t('st.spend_period')}
            options={PERIODS.map(([v, k]) => [v, t(k)])}
          />
        }
      />

      {err && !data ? <ErrorState onRetry={reload} detail={err} /> : null}
      {loading && !data ? <ListSkeleton n={5} avatar={false} rowH={56} /> : null}

      {data ? (
        <>
          {/* --- сводка: деньги (или честное «цены нет») + токены всегда --- */}
          <Card variant="hero" i={0}>
            <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
              <div className="min-w-0">
                <div className="label">{t('st.spend_total')}</div>
                <div className="mt-1 flex items-baseline gap-2">
                  <Num
                    value={showMoney ? sp.total_usd : 0}
                    fmt={(n) => `$${(Number(n) || 0).toFixed(4)}`}
                    className="text-[40px] font-semibold tracking-[-0.04em] leading-none"
                  />
                  {!showMoney ? (
                    <span className="mono text-[13px] text-[var(--ink-3)]">{t('st.spend_no_price_hint')}</span>
                  ) : null}
                </div>
                {showMoney ? (
                  <div className="muted mt-2 text-md">{t('st.spend_per_turn')}: ${perTurn.toFixed(4)}</div>
                ) : null}
              </div>

              <div className="flex flex-wrap gap-6">
                <Metric
                  icon={<ArrowDownToLine size={15} />}
                  label={t('st.spend_tokens_in')}
                  value={fmtNumber(sp.tokens_in)}
                />
                <Metric
                  icon={<ArrowUpFromLine size={15} />}
                  label={t('st.spend_tokens_out')}
                  value={fmtNumber(sp.tokens_out)}
                />
                <Metric icon={<Cpu size={15} />} label={t('st.spend_runs')} value={fmtNumber(sp.runs)} />
              </div>
            </div>

            {/* Нет цены — кнопка прямо к настройкам: путь короткий, искать нечего. */}
            {noPrice ? (
              <div className="mt-4">
                <PriceSetter onSaved={reload} />
                <p className="muted mt-2 max-w-[52ch] text-md">{t('st.spend_uncpriced_hint')}</p>
                <Pressable className="btn-soft btn-sm mt-3" onClick={() => nav('/settings')}>
                  {t('st.spend_no_price_action')}
                </Pressable>
              </div>
            ) : null}
          </Card>

          {/* --- разбивка по путям и по моделям --- */}
          <div className={`grid gap-4 ${phone ? 'grid-cols-1' : 'sm:grid-cols-2'}`}>
            <Section title={t('st.spend_by_route')} i={1}>
              <Breakdown
                rows={Object.entries(sp.by_route || {}).sort((a, b) => b[1].n - a[1].n).map(([k, v]) => ({
                  key: k,
                  name: routeName(t, k, v.ru),
                  n: v.n,
                  tokens: v.tokens_in + v.tokens_out,
                  usd: v.usd,
                  priced: !!sp.priced && !v.uncpriced,
                  free: isFreeRoute(k),
                }))}
                showMoney={showMoney}
                fmtNumber={fmtNumber}
                emptyText={t('st.spend_no_routes')}
              />
            </Section>

            <Section title={t('st.spend_by_model')} i={2}>
              <Breakdown
                rows={Object.entries(sp.by_model || {})
                  .filter(([k]) => k !== '—')
                  .sort((a, b) => (b[1].tokens_in + b[1].tokens_out) - (a[1].tokens_in + a[1].tokens_out))
                  .map(([k, v]) => ({
                    key: k,
                    name: k,
                    n: v.n,
                    tokens: v.tokens_in + v.tokens_out,
                    usd: v.usd,
                    priced: !!sp.priced && !v.uncpriced,
                  }))}
                showMoney={showMoney}
                fmtNumber={fmtNumber}
                emptyText={t('st.spend_no_models')}
              />
            </Section>
          </div>

          {/* --- последние ходы: та же цифра по каждой строке --- */}
          <Section title={t('st.spend_turns')} idx={items.length} i={3}>
            {items.length === 0 ? (
              <Card>
                <Empty glyph="memory" text={t('st.spend_no_turns')} sub={t('st.spend_no_turns_sub')} />
              </Card>
            ) : (
              <div className="rule">
                <div className="hidden items-center gap-3 px-3 py-2 sm:flex">
                  <span className="label flex-1">{t('st.spend_col_turn')}</span>
                  <span className="label w-[86px] text-right">{t('st.spend_col_tokens')}</span>
                  <span className="label w-[92px] text-right">{t('st.spend_col_cost')}</span>
                </div>
                {items.map((r) => (
                  <TurnRow key={r.id} r={r} t={t} fmtNumber={fmtNumber} fmtDate={fmtDate} fmtAgo={fmtAgo} showMoney={showMoney} />
                ))}
              </div>
            )}
          </Section>

          {/* --- тот же отчёт словами, что уходит в чат и Telegram: видно, что именно
              ассистент сказал бы хозяину про свой расход --- */}
          {data.rep.text ? (
            <Section title={t('st.spend_report')} hint={t('st.spend_report_hint')} i={4}>
              <Card className="r">
                <p className="mono whitespace-pre-line text-[13px] leading-[1.6]">{data.rep.text}</p>
              </Card>
            </Section>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

/* Одна цифра с подписью и иконкой: тон токенов тот же, что у стрелок вверх/вниз. */
function Metric({ icon, label, value }) {
  return (
    <div className="min-w-0">
      <div className="label flex items-center gap-1.5">
        <span className="text-[var(--ink-3)]">{icon}</span>
        {label}
      </div>
      <div className="num tnum mt-1 text-[22px] font-semibold tracking-[-0.03em]">{value}</div>
    </div>
  )
}

/* Разбивка: полоса «сколько токенов» + цифры. Денег нет → честная плашка «без цены»,
 * а не ноль с двумя нулями, который читается как «бесплатно». */
function Breakdown({ rows, showMoney, fmtNumber, emptyText }) {
  const { t } = useI18n()
  const max = Math.max(1, ...rows.map((r) => r.tokens))
  if (!rows.length) return <Empty compact text={emptyText} />
  return (
    <div className="rule">
      {rows.map((r) => (
        <div key={r.key} className="flex items-center gap-3 px-3 py-2.5">
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-3">
              <span className="truncate text-md font-medium" title={r.name}>{r.name}</span>
              <span className="mono shrink-0 text-xs text-[var(--ink-3)]">
                {fmtNumber(r.tokens)} · {fmtNumber(r.n)} {t('st.spend_runs_short')}
              </span>
            </div>
            <div className="mt-1.5 h-[4px] w-full overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(2, Math.round((r.tokens / max) * 100))}%`,
                  background: r.free ? 'var(--ink-3)' : 'var(--accent)',
                }}
              />
            </div>
          </div>
          <Cost usd={r.usd} priced={r.priced} showMoney={showMoney} />
        </div>
      ))}
    </div>
  )
}

function Cost({ usd, priced, showMoney }) {
  const { t } = useI18n()
  if (!showMoney) return <span className="mono w-[92px] shrink-0 text-right text-xs text-[var(--ink-3)]">—</span>
  if (!priced) {
    return (
      <span className="mono w-[92px] shrink-0 text-right text-xs text-[var(--warn)]" title={t('st.spend_uncpriced_hint')}>
        {t('st.spend_uncpriced')}
      </span>
    )
  }
  return <span className="num tnum w-[92px] shrink-0 text-right text-md">${(usd || 0).toFixed(4)}</span>
}

function TurnRow({ r, t, fmtNumber, fmtDate, fmtAgo, showMoney }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-md">{r.text || '—'}</span>
          {!r.ok ? <span className="mono shrink-0 text-xs text-[var(--neg)]">!</span> : null}
        </div>
        <div className="mono mt-0.5 truncate text-xs text-[var(--ink-3)]" title={`${fmtDate(r.at)}${r.model ? ` · ${r.model}` : ''}`}>
          {fmtAgo(r.at)} · {routeName(t, r.route, r.route_ru)}
          {r.model ? ` · ${r.model}` : ''}
        </div>
      </div>
      <span className="num tnum w-[86px] shrink-0 text-right text-md">
        {r.tokens ? fmtNumber(r.tokens) : '—'}
      </span>
      <Cost usd={r.cost_usd} priced={r.priced} showMoney={showMoney} />
    </div>
  )
}

/* Ввод цены прямо на экране: хозяину не нужно открывать yaml ради двух чисел.
   Пишем в brain.pricing.default_* (те же ключи, что в настройках → мозг → облако),
 * сервер применяет их на лету, перезапуск не нужен. */
function PriceSetter({ onSaved }) {
  const { t } = useI18n()
  const [inp, out, setInp] = useState('')
  const [outp, setOut] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [fail, setFail] = useState(null)

  const save = async () => {
    setBusy(true)
    setFail(null)
    try {
      await api.saveSettings({ 'brain.pricing.default_prompt': inp.trim(), 'brain.pricing.default_completion': outp.trim() })
      setDone(true)
      onSaved?.()
    } catch (e) {
      setFail(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="r p-4" style={{ background: 'var(--fill)', border: '1px solid var(--line)' }}>
      <div className="label flex items-center gap-1.5">
        <Tag size={13} />
        {t('st.spend_price_title')}
      </div>
      <p className="muted mt-1.5 max-w-[56ch] text-md">{t('st.spend_price_hint')}</p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="label">{t('st.spend_price_in')}</span>
          <input value={inp} onChange={(e) => setInp(e.target.value)} placeholder="0.14" inputMode="decimal"
            className="input num w-[120px] text-center" aria-label={t('st.spend_price_in')} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="label">{t('st.spend_price_out')}</span>
          <input value={outp} onChange={(e) => setOutp(e.target.value)} placeholder="0.28" inputMode="decimal"
            className="input num w-[120px] text-center" aria-label={t('st.spend_price_out')} />
        </label>
        <Pressable className="btn-primary btn-sm" disabled={busy || !(inp.trim() || outp.trim())} onClick={save}>
          {t('st.spend_price_save')}
        </Pressable>
      </div>
      {done ? <SuccessState ms={3200} text={t('st.spend_price_saved')} /> : null}
      {fail ? <ErrorState compact className="mt-3" title={t('common.error')} detail={fail} onRetry={save} /> : null}
    </div>
  )
}
