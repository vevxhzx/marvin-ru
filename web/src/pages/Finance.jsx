import { useEffect, useMemo, useState } from 'react'
import { Plus, Trash2, ArrowLeftRight, Check, X, ChevronRight, Star, Pencil, Wallet, RotateCcw, Pause, Play } from 'lucide-react'
import { ResponsiveContainer, BarChart, Bar, XAxis, Tooltip, Cell } from 'recharts'
import { api, money, moneyShort, catIcon, shortDate, hhmm, toLocalISO, fullDate, plural, dayLabel, parseNum } from '../lib/api'
import { Card, Section, PageHead, Empty, Sheet, Field, Seg, Pills, Skeleton, useToast, Toast, Money, Inline, Confirm, Num, useLeave, useArrived, Swipe } from '../components/ui'
import { useRefresh } from '../App'
import { Forecast, ImportButton } from '../components/Widgets'

const n = (v) => { const x = parseNum(v); return Number.isNaN(x) ? undefined : x }

export default function Finance() {
  const [days, setDays] = useState(30)
  const [sum, setSum] = useState(null)
  const [daily, setDaily] = useState([])
  const [txs, setTxs] = useState([])
  const [debts, setDebts] = useState([])
  const [rec, setRec] = useState([])
  const [cats, setCats] = useState([])
  const [accounts, setAccounts] = useState([])
  const [budgets, setBudgets] = useState([])
  const [safe, setSafe] = useState(null)
  const [forecast, setForecast] = useState(null)
  const [subs, setSubs] = useState([])
  const [sheet, setSheet] = useState(null) // 'tx' | 'debt' | 'rec' | 'account' | {pay} | {debt} | {tx} | {rec} | {confirm}
  const [showClosed, setShowClosed] = useState(false)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()

  const load = async () => {
    const [s, dl, t, d, r, c, a, b] = await Promise.all([api.finSummary(days), api.finDaily(days), api.txs(days), api.debts(), api.recurring(), api.categories(), api.accounts(), api.budgets()])
    setSum(s); setDaily(dl); setTxs(t); setDebts(d); setRec(r); setCats(c); setAccounts(a); setBudgets(b.budgets); setSafe(b.safe)
    api.get('/api/insights/forecast').then(setForecast).catch(() => {})
    api.get('/api/insights/subscriptions').then(setSubs).catch(() => {})
  }
  useEffect(() => { load().catch(show.err) }, [days, tick])

  // единая обёртка: действие → тост → перезагрузка; ошибки API показываем как есть («Платёж больше остатка…»)
  const act = async (fn, ok) => { try { await fn(); if (ok) show(ok); await load(); bump(); return true } catch (e) { show.err(e); return false } }
  const done = (msg) => { setSheet(null); if (msg) show(msg); load(); bump() }
  const [leaveCls, leave] = useLeave()
  const arrivedCls = useArrived(txs.map((t) => t.id))
  const [pick, setPick] = useState(null) // выбранный день на графике (тап на телефоне)

  if (!sum) return <div className="space-y-4"><Skeleton h={160} /><Skeleton h={200} /><Skeleton h={200} /></div>
  const cf = sum.cashflow
  const openDebts = debts.filter((d) => !d.closed)
  const closedDebts = debts.filter((d) => d.closed)
  const cats_ = Object.entries(sum.by_category).map(([name, value]) => ({ name, value }))
  const maxCat = Math.max(1, ...cats_.map((c) => c.value))
  const maxDay = Math.max(1, ...daily.map((d) => d.expense))
  const picked = daily.find((d) => d.date === pick)
  const recExp = rec.filter((r) => r.kind === 'expense' && !r.debt_id)
  const recInc = rec.filter((r) => r.kind === 'income')
  const recDebt = rec.filter((r) => r.debt_id)

  return (
    <div className="space-y-16 sm:space-y-24">
      <PageHead kicker="финансы · все счета" title={<Num value={sum.total_balance} fmt={money} />}
        right={<>
          <Seg value={days} onChange={setDays} options={[[7, '7 дн'], [30, '30 дн'], [90, '90 дн']]} />
          <ImportButton onDone={(r) => { show(r.text.split('\n').slice(0, 2).join(' ')); load(); bump() }} onErr={show.err} />
          <button className="btn-primary" onClick={() => setSheet('tx')}><Plus size={15} /> операция</button>
        </>}>
        <div className="muted mt-4 flex flex-wrap gap-x-6 gap-y-1 text-[14px]">
          <span>за {days} дн: −<b className="num">{money(sum.spent)}</b></span>
          <span>+<b className="num">{money(sum.earned)}</b></span>
          {openDebts.length > 0 && <span>долгов: <b className="num">{money(sum.debts_total)}</b></span>}
        </div>
      </PageHead>

      {forecast && (
        <Section title="касса на 30 дней" idx={0} hint={forecast.ok ? `Регулярные платежи + ваши средние траты. Минимум за месяц — ${money(forecast.low)}.` : `При текущем темпе уйдёте в минус. Точки — регулярные платежи и доходы.`}>
          <div className="rule pt-4"><Forecast f={forecast} /></div>
          {subs.length > 0 && (
            <div className="mt-5 flex flex-wrap items-center gap-2 text-[13px]">
              <span className="muted">похоже на подписки, которых нет в регулярных:</span>
              {subs.slice(0, 5).map((x) => <button key={x.name} className="chip hover:text-accent" title={`${x.times} раз, ~${money(x.yearly)} в год. Нажмите — добавлю в регулярные`} onClick={() => act(() => api.addRecurring({ title: x.name, amount: x.amount, day: new Date(x.last).getDate(), kind: 'expense', category: x.category }), `«${x.name}» — теперь в регулярных`)}>{x.name} · {money(x.amount)}</button>)}
            </div>
          )}
        </Section>
      )}

      {/* 01 · поток */}
      <Section title="поток в месяц" idx={1} hint="Доход минус обязательные платежи. Это то, чем реально можно распоряжаться.">
        <div className="rule grid grid-cols-2 gap-y-8 pt-6 md:grid-cols-4">
          <Flow label={cf.income_is_estimate ? 'доход · средний' : 'доход'} value={cf.income} />
          <Flow label="регулярные" value={cf.recurring} sign="−" />
          <Flow label="по долгам" value={cf.debt_payments} sign="−" />
          <Flow label="свободно" value={cf.free} sign="=" tone={cf.free < 0 ? 'neg' : 'accent'} big />
        </div>
        <div className="mt-8 flex h-[3px] w-full overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
          {cf.income > 0 && <>
            <div className="h-full" style={{ width: `${Math.min(100, (cf.recurring / cf.income) * 100)}%`, background: 'var(--ink)' }} />
            <div className="h-full" style={{ width: `${Math.min(100, (cf.debt_payments / cf.income) * 100)}%`, background: 'var(--ink-3)' }} />
            <div className="h-full" style={{ width: `${Math.max(0, Math.min(100, (cf.free / cf.income) * 100))}%`, background: 'var(--accent)' }} />
          </>}
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[13px]">
          <div className="flex gap-4"><Leg c="var(--ink)" t="регулярные" /><Leg c="var(--ink-3)" t="долги" /><Leg c="var(--accent)" t="свободно" /></div>
          <div className="muted">
            {cf.avg_variable > 0 && <>на жизнь обычно уходит <b className="num">{money(cf.avg_variable)}</b> → остаётся <b className={`num ${cf.left_after_all < 0 ? 'neg' : 'pos'}`}>{money(cf.left_after_all)}</b></>}
            {cf.income_is_estimate && cf.income === 0 && <>добавьте регулярный доход — посчитаю, сколько остаётся</>}
          </div>
        </div>
        {safe && (
          <div className="panel mt-8 grid grid-cols-2 gap-6 p-5 sm:p-6 md:grid-cols-4">
            <div className="col-span-2">
              <div className="label">можно потратить сегодня</div>
              <div className={`num mt-2 text-[40px] font-medium leading-none tracking-[-0.04em] sm:text-[52px] ${safe.per_day < 0 ? 'neg' : 'accent'}`}><Num value={safe.per_day} fmt={money} /></div>
              <div className="muted mt-2 text-[13px]">
                {safe.spent_today === 0 ? 'сегодня ещё ничего не потрачено' : safe.spent_today <= safe.per_day
                  ? <>сегодня потрачено {money(safe.spent_today)} · ещё можно <b className="num pos">{money(safe.per_day - safe.spent_today)}</b></>
                  : <>сегодня уже {money(safe.spent_today)} — <b className="num neg">перебор на {money(safe.spent_today - safe.per_day)}</b></>}
              </div>
            </div>
            <Flow label={`дней до дохода`} value={safe.days_left} raw />
            <Flow label="зарезервировано" value={safe.reserved} sign="−" sub={safe.upcoming.length ? safe.upcoming.slice(0, 2).map((u) => u.title).join(', ') : 'платежей нет'} />
            <div className="col-span-2 md:col-span-4 muted text-[12px]">на счетах {money(safe.balance)} − обязательные платежи до {new Date(safe.next_income).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })} = {money(safe.free)} ÷ {safe.days_left} {plural(safe.days_left, 'день', 'дня', 'дней')}</div>
          </div>
        )}
      </Section>

      {/* 01b · бюджеты */}
      <Section title="бюджеты" idx={2} hint="Лимит на категорию в месяц. Полоска желтеет на 80 %, краснеет при перерасходе. Свои категории — рядом."
        action={<button className="btn-ghost !py-1.5 !text-[13px]" onClick={() => setSheet('cat')}><Plus size={14} /> категория</button>}>
        <div className="rule pt-6">
          {budgets.length === 0 && <div className="muted mb-4 text-[14px]">Лимитов пока нет — нажмите на категорию ниже и задайте бюджет.</div>}
          {budgets.length > 0 && (
            <div className="grid grid-cols-1 gap-x-10 gap-y-4 md:grid-cols-2">
              {budgets.map((b) => {
                const color = b.status === 'over' ? 'var(--neg)' : b.status === 'warn' ? 'var(--warn)' : 'var(--accent)'
                return (
                  <button key={b.id} className="text-left" onClick={() => setSheet({ cat: cats.find((c) => c.id === b.id) })}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="truncate text-[15px] font-medium">{b.icon} {b.name}</span>
                      <span className="num shrink-0 text-[14px]"><b>{money(b.spent)}</b> <span className="faint">/ {money(b.budget)}</span></span>
                    </div>
                    <div className="relative mt-1.5 h-[6px] w-full overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
                      <div className="h-full rounded-full transition-all" style={{ width: `${Math.min(100, b.pct * 100)}%`, background: color }} />
                      <div className="absolute top-0 h-full w-[1px]" style={{ left: `${b.pace * 100}%`, background: 'var(--ink-3)' }} title="где должны быть по календарю" />
                    </div>
                    <div className="mt-1 flex justify-between text-[12px]"><span className="faint">{Math.round(b.pct * 100)} %</span><span className={b.left < 0 ? 'neg' : 'muted'}>{b.left < 0 ? `перерасход ${money(-b.left)}` : `осталось ${money(b.left)}`}</span></div>
                  </button>
                )
              })}
            </div>
          )}
          <div className="mt-6 flex flex-wrap gap-1.5">
            {cats.filter((c) => c.kind === 'expense').map((c) => (
              <button key={c.id} className={`pill ${c.budget > 0 ? 'on' : ''}`} onClick={() => setSheet({ cat: c })} title={c.budget > 0 ? `лимит ${money(c.budget)}` : 'без лимита'}>{c.icon} {c.name}{c.custom ? ' ·' : ''}</button>
            ))}
          </div>
        </div>
      </Section>

      {/* 02 · траты */}
      <Section title="траты" idx={3} hint={`${money(sum.spent)} за ${days} дн · ≈ ${money(sum.spent / Math.max(1, days))} в день`}>
        <div className="rule grid grid-cols-1 gap-10 pt-6 lg:grid-cols-5">
          <div className="lg:col-span-2">
            {cats_.length === 0 ? <Empty glyph="money" text="Трат нет" sub="За этот период ничего не списывалось" hint="потратил 700 на такси" /> : (
              <div>
                {cats_.map((c, i) => (
                  <div key={c.name} className="row !gap-3 !py-3">
                    <span className="idx w-6">{String(i + 1).padStart(2, '0')}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="truncate text-[15px] font-medium">{c.name}</span>
                        <span className="num shrink-0 text-[15px]">{money(c.value)}</span>
                      </div>
                      <div className="mt-1.5 flex items-center gap-2">
                        <div className="progress dark flex-1"><div style={{ width: `${(c.value / maxCat) * 100}%` }} /></div>
                        <span className="faint num w-8 text-right text-[11px]">{Math.round((c.value / sum.spent) * 100)}%</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="lg:col-span-3">
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={daily} barCategoryGap="30%" onClick={(e) => setPick(e?.activeLabel === pick ? null : (e?.activeLabel || null))}>
                  <XAxis dataKey="date" tickFormatter={(v) => new Date(v).getDate()} tick={{ fontSize: 11, fill: 'var(--ink-3)', fontFamily: 'JetBrains Mono Variable' }} axisLine={false} tickLine={false} interval={days > 30 ? 9 : days > 7 ? 4 : 0} />
                  <Tooltip cursor={{ fill: 'var(--fill)' }} content={<DayTT />} />
                  <Bar dataKey="expense" name="траты" radius={[3, 3, 0, 0]} minPointSize={2} isAnimationActive animationDuration={700} animationEasing="ease-out">
                    {daily.map((d) => <Cell key={d.date} className="bar-cell" opacity={pick && pick !== d.date ? 0.35 : 1}
                      fill={pick === d.date ? 'var(--accent)' : d.income > 0 ? 'var(--accent)' : d.expense >= maxDay * 0.7 ? 'var(--ink)' : 'var(--ink-3)'} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[13px]">
              <div className="flex gap-4"><Leg c="var(--ink-3)" t="день" /><Leg c="var(--ink)" t="пиковый" /><Leg c="var(--accent)" t="был доход" /></div>
              <div className="muted">макс <b className="num">{money(maxDay)}</b></div>
            </div>
            {picked && (
              <div className="animate-rise mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-2xl px-4 py-3 text-[14px]" style={{ background: 'var(--fill)' }}>
                <b>{fullDate(picked.date)}</b>
                <span>−<b className="num">{money(picked.expense)}</b></span>
                {picked.income > 0 && <span className="pos">+<b className="num">{money(picked.income)}</b></span>}
                {picked.top && <span className="muted">больше всего — {picked.top.name} · {money(picked.top.amount)}</span>}
                <span className="faint">{picked.count} {plural(picked.count, 'операция', 'операции', 'операций')}</span>
                <button className="faint ml-auto text-[12px] hover:text-ink" onClick={() => setPick(null)}>закрыть</button>
              </div>
            )}
          </div>
        </div>
      </Section>

      {/* 03 · долги */}
      <Section title="долги" idx={4} hint="Нажмите на число — измените прямо здесь. Внести больше остатка не получится."
        action={<button className="btn-ghost" onClick={() => setSheet('debt')}><Plus size={14} /> долг</button>}>
        <div className="rule pt-2">
          {openDebts.length === 0 && <Empty glyph="debt" text="Долгов нет" sub="Свободный человек, сэр" />}
          {openDebts.map((d, i) => (
            <Swipe key={d.id} onRight={() => setSheet({ pay: d })} rightLabel="внести" rightIcon={<Wallet size={18} strokeWidth={2.2} />}
              onLeft={() => setSheet({ confirm: { title: 'Удалить долг?', text: 'Долг и его регулярный платёж исчезнут. Уже проведённые платежи останутся в истории операций.', ok: () => leave(d.id, 'leaving', () => act(() => api.delDebt(d.id), 'Долг удалён')) } })}>
              <DebtRow d={d} i={i} act={act} onOpen={() => setSheet({ debt: d })} onPay={() => setSheet({ pay: d })} extra={leaveCls(d.id)} />
            </Swipe>
          ))}
          {closedDebts.length > 0 && (
            <div className="pt-4">
              <button className="label hover:text-accent" onClick={() => setShowClosed(!showClosed)}>{showClosed ? '— скрыть закрытые' : `+ закрытые · ${closedDebts.length}`}</button>
              {showClosed && closedDebts.map((d) => (
                <Swipe key={d.id} onLeft={() => leave(`c${d.id}`, 'leaving', () => act(() => api.delDebt(d.id), 'Удалено'))} onRight={() => act(() => api.updateDebt(d.id, { closed: false, remaining: d.total }), 'Долг открыт заново')} rightLabel="открыть" rightIcon={<RotateCcw size={18} strokeWidth={2.2} />}>
                <div className={`row muted !py-3 ${leaveCls(`c${d.id}`)}`}>
                  <span className="flex-1 line-through">{d.title}</span>
                  <span className="num">{money(d.total)}</span>
                  <button className="btn-ghost !py-1 !text-[12px]" onClick={() => act(() => api.updateDebt(d.id, { closed: false, remaining: d.total }), 'Долг открыт заново')}>открыть</button>
                  <button className="btn-icon !h-8 !w-8" onClick={() => setSheet({ confirm: { title: 'Удалить долг?', text: `«${d.title}» исчезнет из списка. История платежей останется в операциях.`, ok: () => act(() => api.delDebt(d.id), 'Удалено') } })}><Trash2 size={13} /></button>
                </div>
                </Swipe>
              ))}
            </div>
          )}
        </div>
      </Section>

      {/* 04 · регулярные */}
      <Section title="регулярные" idx={5} hint="Списываются сами в срок. Сумму и день можно править по клику."
        action={<button className="btn-ghost" onClick={() => setSheet('rec')}><Plus size={14} /> платёж</button>}>
        <div className="rule grid grid-cols-1 gap-x-12 pt-2 lg:grid-cols-2">
          <div>
            <div className="label pt-4 pb-1">расходы · {money(recExp.reduce((a, r) => a + r.amount, 0) + recDebt.reduce((a, r) => a + r.amount, 0))} в месяц</div>
            {recExp.length + recDebt.length === 0 && <Empty text="Пока пусто" sub="Подписки, аренда, связь" />}
            {[...recExp, ...recDebt].map((r) => <RecRow key={r.id} r={r} act={act} onOpen={() => setSheet({ rec: r })} leave={leave} extra={leaveCls(`r${r.id}`)} />)}
          </div>
          <div>
            <div className="label pt-4 pb-1">доходы · {money(recInc.reduce((a, r) => a + r.amount, 0))} в месяц</div>
            {recInc.length === 0 && <Empty text="Нет регулярного дохода" sub="Добавьте зарплату — поток станет точнее" />}
            {recInc.map((r) => <RecRow key={r.id} r={r} act={act} onOpen={() => setSheet({ rec: r })} leave={leave} extra={leaveCls(`r${r.id}`)} />)}
          </div>
        </div>
      </Section>

      {/* 05 · счета */}
      <Section title="счета" idx={6} hint="Открой банк, впиши реальный остаток — ассистент подстроится."
        action={<button className="btn-ghost" onClick={() => setSheet('account')}><Plus size={14} /> счёт</button>}>
        <div className="rule pt-2">
          {accounts.map((a) => (
            <Swipe key={a.id} onLeft={!a.is_main ? () => leave(`a${a.id}`, 'leaving', () => act(() => api.delAccount(a.id), 'Счёт удалён')) : undefined}>
            <div className={`row group ${leaveCls(`a${a.id}`)}`}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Inline type="text" value={a.name} className="text-[16px] font-medium" onSave={(v) => api.updateAccount(a.id, { name: v }).then(load)} />
                  {a.is_main ? <span className="chip on !py-0.5 !text-[10px]">основной</span>
                    : <button title="Сделать основным" className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100" onClick={() => act(() => api.updateAccount(a.id, { is_main: true }), `Основной счёт — ${a.name}`)}><Star size={12} /></button>}
                </div>
                <div className="faint text-[12px]">{a.kind === 'cash' ? 'наличные' : a.kind === 'debt_only' ? 'только обязательства' : 'банк'}</div>
              </div>
              <Inline value={a.balance} fmt={money} className={`num text-[18px] font-medium ${a.balance < 0 ? 'neg' : ''}`} onSave={(v) => api.updateAccount(a.id, { balance: v }).then(load).then(bump)} />
              <span className="w-8 shrink-0">{!a.is_main && <button className="btn-icon !h-8 !w-8 opacity-0 transition group-hover:opacity-100" onClick={() => act(() => api.delAccount(a.id), 'Счёт удалён')}><Trash2 size={13} /></button>}</span>
            </div>
            </Swipe>
          ))}
        </div>
      </Section>

      {/* 06 · операции */}
      <Section title="операции" idx={7} hint="Нажмите на строку, чтобы исправить сумму, категорию или дату.">
        <div className="rule pt-2">
          {txs.length === 0 ? <Empty glyph="money" text="Операций нет" sub="Первая запись — и здесь появится лента" hint="потратил 700 на такси" /> : groupByDay(txs).map(([day, list]) => (
            <div key={day}>
              <div className="label pt-6 pb-1">{dayLabel(day)} · {shortDate(day)} · <span className="num">−{moneyShort(list.filter((t) => t.kind === 'expense').reduce((a, t) => a + t.amount, 0))}</span></div>
              {list.map((t) => (
                <Swipe key={t.id} onLeft={() => leave(t.id, 'leaving', () => act(() => api.delTx(t.id), 'Операция удалена'))}>
                <div className={`row row-hover group cursor-pointer !py-3 ${leaveCls(t.id)} ${arrivedCls(t.id)}`} onClick={() => setSheet({ tx: t })}>
                  <span className="mono grid h-9 w-9 shrink-0 place-items-center rounded-full border hair text-[12px] uppercase">{t.kind === 'transfer' ? <ArrowLeftRight size={14} /> : t.kind === 'income' ? '+' : (t.category || '•')[0]}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[15px] font-medium">{t.note || t.category || (t.kind === 'transfer' ? 'Перевод' : '—')}</div>
                    <div className="faint text-[12px]">{t.category}{t.account ? ` · ${t.account}` : ''}{t.to_account ? ` → ${t.to_account}` : ''} · {hhmm(t.date)}{t.debt_id ? ' · по долгу' : ''}</div>
                  </div>
                  <div className={`num text-[16px] font-medium ${t.kind === 'income' ? 'pos' : ''}`}>{t.kind === 'income' ? '+' : t.kind === 'expense' ? '−' : ''}{money(t.amount)}</div>
                  <button className="btn-icon !h-8 !w-8 opacity-0 transition group-hover:opacity-100" onClick={(e) => { e.stopPropagation(); leave(t.id, 'leaving', () => act(() => api.delTx(t.id), 'Операция удалена')) }}><Trash2 size={13} /></button>
                </div>
                </Swipe>
              ))}
            </div>
          ))}
        </div>
      </Section>

      {/* ---- модалки ---- */}
      <TxSheet open={sheet === 'tx' || !!sheet?.tx} tx={sheet?.tx} onClose={() => setSheet(null)} cats={cats} accounts={accounts} onDone={done} onErr={show.err} />
      <DebtSheet open={sheet === 'debt' || !!sheet?.debt} debt={sheet?.debt} onClose={() => setSheet(null)} onDone={done} onErr={show.err} accounts={accounts} />
      <RecSheet open={sheet === 'rec' || !!sheet?.rec} rec={sheet?.rec} onClose={() => setSheet(null)} cats={cats} onDone={done} onErr={show.err} />
      <AccountSheet open={sheet === 'account'} onClose={() => setSheet(null)} onDone={done} onErr={show.err} />
      <CatSheet open={sheet === 'cat' || !!sheet?.cat} cat={sheet?.cat} onClose={() => setSheet(null)} onDone={done} onErr={show.err} />
      <PaySheet debt={sheet?.pay} accounts={accounts} onClose={() => setSheet(null)} onDone={done} onErr={show.err} />
      <Confirm open={!!sheet?.confirm} title={sheet?.confirm?.title} text={sheet?.confirm?.text} danger onClose={() => setSheet(null)} onOk={async () => { setSheet(null); await sheet.confirm.ok() }} />
    </div>
  )
}

/* ---------- элементы ---------- */
function Flow({ label, value, sign, tone, big, raw, sub }) {
  if (raw) return (<div><div className="label">{label}</div><div className="num mt-2 text-[26px] font-medium leading-none tracking-[-0.04em] sm:text-[30px]">{value}</div>{sub && <div className="muted mt-1.5 text-[12px]">{sub}</div>}</div>)
  const c = tone === 'neg' ? 'neg' : tone === 'accent' ? 'accent' : ''
  return (
    <div className="relative pr-2 min-w-0">
      {sign && <span className="faint absolute -left-4 top-1 hidden text-[20px] font-light md:block">{sign}</span>}
      <div className="label">{label}</div>
      <div className={`num mt-2 leading-none tracking-[-0.04em] ${big ? 'text-[30px] sm:text-[48px]' : 'text-[24px] sm:text-[32px]'} font-medium ${c}`}>{money(value)}</div>
    </div>
  )
}
const Leg = ({ c, t }) => <span className="flex items-center gap-1.5 text-[12px]"><i className="h-2 w-2 rounded-full" style={{ background: c }} /> {t}</span>

function DayTT({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload || {}
  return (
    <div className="tt">
      <div className="muted mb-0.5">{fullDate(label)}</div>
      <div className="flex items-center gap-3"><span>траты</span><b className="num ml-auto">{money(d.expense || 0)}</b></div>
      {d.income > 0 && <div className="flex items-center gap-3"><span>доход</span><b className="num pos ml-auto">+{money(d.income)}</b></div>}
      {d.top && <div className="faint mt-1 text-[11px]">{d.top.name} · {money(d.top.amount)}{d.count > 1 ? ` · ${d.count} оп.` : ''}</div>}
      {!d.count && <div className="faint mt-1 text-[11px]">без операций</div>}
    </div>
  )
}

function TT({ active, payload, label, fmt, label: lf }) {
  if (!active || !payload?.length) return null
  return (
    <div className="tt">
      {label && <div className="muted mb-0.5">{typeof lf === 'function' ? lf(label) : label}</div>}
      {payload.map((p) => <div key={p.name} className="flex items-center gap-2"><span>{p.name}</span><b className="num ml-auto">{fmt(p.value)}</b></div>)}
    </div>
  )
}

function DebtRow({ d, i, act, onOpen, onPay, extra = '' }) {
  const pct = Math.round((d.progress || 0) * 100)
  const save = (patch, msg) => act(() => api.updateDebt(d.id, patch), msg)
  return (
    <div className={`row !items-start !gap-4 !py-6 sm:!gap-8 ${extra}`}>
      <Ring pct={pct} idx={String(i + 1).padStart(2, '0')} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="min-w-0">
            <button onClick={onOpen} className="h3 flex items-center gap-1 text-left hover:text-accent">{d.title} <ChevronRight size={16} className="faint" /></button>
            <div className="muted mt-1 flex flex-wrap items-center gap-x-1 text-[13px]">
              <Inline value={d.payment} min={0} max={d.total} fmt={(v) => (v ? `${money(v)}/мес` : 'без графика')} onSave={(v) => save({ payment: v }).then((ok) => { if (!ok) throw new Error() })} />
              <span>·</span>
              <Inline value={d.pay_day} min={1} max={31} fmt={(v) => `${v}-го`} onSave={(v) => save({ pay_day: v }).then((ok) => { if (!ok) throw new Error() })} />
              {d.rate > 0 && <><span>·</span><Inline value={d.rate} min={0} max={1000} fmt={(v) => `${v}%`} onSave={(v) => save({ rate: v })} /></>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-primary" onClick={onPay}>внести</button>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <Inline value={d.remaining} min={0} max={d.total} fmt={money} className="num text-[28px] font-medium tracking-[-0.04em] sm:text-[34px]" title="Остаток — нажмите, чтобы исправить"
            onSave={(v) => save({ remaining: v }, 'Остаток обновлён').then((ok) => { if (!ok) throw new Error() })} />
          <span className="muted text-[14px]">из <Inline value={d.total} min={d.remaining} fmt={money} onSave={(v) => save({ total: v }).then((ok) => { if (!ok) throw new Error() })} /></span>
          <span className="faint text-[13px]">· выплачено {money(d.paid)}</span>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[13px]">
          <span className="muted">выплачено {pct}%</span>
          {d.months != null ? <span>{d.months === 0 ? 'закрыт' : <>ещё {d.months} {plural(d.months, 'месяц', 'месяца', 'месяцев')} · <span className="accent">{d.close_date}</span>{d.overpay > 0 && <span className="faint"> · переплата {money(d.overpay)}</span>}</>}</span>
            : <span className="warn">{d.warning || 'укажите платёж — посчитаю срок'}</span>}
        </div>
      </div>
    </div>
  )
}

function RecRow({ r, act, onOpen, leave, extra = '' }) {
  const save = (patch) => act(() => api.updateRecurring(r.id, patch)).then((ok) => { if (!ok) throw new Error() })
  const toggle = () => act(() => api.updateRecurring(r.id, { active: !r.active }), r.active ? 'Приостановлено' : 'Включено')
  return (
    <Swipe onLeft={!r.debt_id && leave ? () => leave(`r${r.id}`, 'leaving', () => act(() => api.delRecurring(r.id), 'Удалено')) : undefined}
      onRight={toggle} rightLabel={r.active ? 'пауза' : 'включить'} rightIcon={r.active ? <Pause size={18} strokeWidth={2.2} /> : <Play size={18} strokeWidth={2.2} />}>
    <div className={`row group !py-3.5 ${r.active ? '' : 'opacity-50'} ${extra}`}>
      <span className={`mono grid h-9 w-9 shrink-0 place-items-center rounded-full border hair text-[12px] uppercase ${r.debt_id ? 'bg-accent !border-transparent text-white' : ''}`}>{r.debt_id ? '%' : r.kind === 'income' ? '+' : (r.category || '•')[0]}</span>
      <div className="min-w-0 flex-1">
        <button className="truncate text-left text-[15px] font-medium hover:text-accent" onClick={onOpen}>{r.title}</button>
        <div className="faint text-[12px]">каждое <Inline value={r.day} min={1} max={31} fmt={(v) => `${v}-е`} onSave={(v) => save({ day: v })} /> · след. {shortDate(r.next_date)}{r.debt_id ? ' · долг' : ''}</div>
      </div>
      <Inline value={r.amount} min={0.01} fmt={(v) => `${r.kind === 'income' ? '+' : ''}${money(v)}`} className={`num text-[16px] font-medium ${r.kind === 'income' ? 'pos' : ''}`} onSave={(v) => save({ amount: v })} />
      <div className="flex w-[68px] shrink-0 items-center justify-end gap-1 opacity-0 transition group-hover:opacity-100">
        <button title={r.active ? 'Приостановить' : 'Включить'} className="btn-icon !h-8 !w-8" onClick={() => act(() => api.updateRecurring(r.id, { active: !r.active }), r.active ? 'Приостановлено' : 'Включено')}>{r.active ? <X size={13} /> : <Check size={13} />}</button>
        {!r.debt_id && <button className="btn-icon !h-8 !w-8" onClick={() => act(() => api.delRecurring(r.id), 'Удалено')}><Trash2 size={13} /></button>}
      </div>
    </div>
    </Swipe>
  )
}

function groupByDay(list) {
  const m = new Map()
  for (const t of list) { const k = new Date(t.date).toDateString(); if (!m.has(k)) m.set(k, []); m.get(k).push(t) }
  return [...m.entries()]
}

/* ---------- модалки ---------- */
function TxSheet({ open, tx, onClose, cats, accounts, onDone, onErr }) {
  const [kind, setKind] = useState('expense')
  const [f, setF] = useState({})
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!open) return
    if (tx) { setKind(tx.kind); setF({ amount: tx.amount.toLocaleString('ru-RU'), note: tx.note || '', category: tx.category || '', account: tx.account || '', to_account: tx.to_account || '', date: toLocalISO(tx.date) }) }
    else { setKind('expense'); setF({ amount: '', note: '', category: '', account: accounts.find((a) => a.is_main)?.name || accounts[0]?.name || '', to_account: '', date: toLocalISO(new Date()) }) }
  }, [open, tx])
  const amt = n(f.amount)
  const valid = amt > 0 && (kind !== 'transfer' || (f.to_account && f.to_account !== f.account))
  const submit = async (e) => {
    e.preventDefault(); if (!valid || busy) return
    setBusy(true)
    const body = { amount: amt, kind, note: f.note || null, category: kind === 'transfer' ? null : (f.category || null), account: f.account || null, to_account: kind === 'transfer' ? f.to_account : null, date: f.date || null }
    try { tx ? await api.updateTx(tx.id, body) : await api.addTx(body); onDone(tx ? 'Исправлено' : 'Записано') } catch (e) { onErr(e) } finally { setBusy(false) }
  }
  const catList = cats.filter((c) => c.kind === kind)
  return (
    <Sheet open={open} onClose={onClose} title={tx ? 'исправить' : 'операция'} sub={tx ? `#${tx.id} · ${fullDate(tx.date)}` : 'проще сказать в чат: «потратил 700 на такси»'}>
      <form onSubmit={submit} className="space-y-5">
        <Pills value={kind} onChange={(k) => { setKind(k); setF({ ...f, category: '' }) }} options={[['expense', 'расход'], ['income', 'доход'], ['transfer', 'перевод']]} />
        <Field label="сумма"><Money autoFocus big value={f.amount ?? ''} onChange={(v) => setF({ ...f, amount: v })} min={0.01} /></Field>
        {kind !== 'transfer' && (
          <Field label="категория" hint={f.category ? '' : 'определится сама по описанию'}>
            <div className="flex flex-wrap gap-1.5">{catList.map((c) => <button type="button" key={c.id} onClick={() => setF({ ...f, category: f.category === c.name ? '' : c.name })} className={`chip !py-1.5 ${f.category === c.name ? 'on' : ''}`}>{c.icon} {c.name}</button>)}</div>
          </Field>
        )}
        <Field label="описание"><input className="input" placeholder={kind === 'transfer' ? 'в наличные' : 'такси до дома'} value={f.note ?? ''} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label={kind === 'transfer' ? 'откуда' : 'счёт'}><select className="input" value={f.account ?? ''} onChange={(e) => setF({ ...f, account: e.target.value })}>{accounts.map((a) => <option key={a.id}>{a.name}</option>)}</select></Field>
          {kind === 'transfer'
            ? <Field label="куда" error={f.to_account && f.to_account === f.account ? 'тот же счёт' : ''}><select className="input" value={f.to_account ?? ''} onChange={(e) => setF({ ...f, to_account: e.target.value })}><option value="">—</option>{accounts.filter((a) => a.name !== f.account).map((a) => <option key={a.id}>{a.name}</option>)}</select></Field>
            : <Field label="дата"><input type="datetime-local" max={toLocalISO(new Date(Date.now() + 864e5))} className="input" value={f.date ?? ''} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>}
        </div>
        {kind === 'transfer' && <Field label="дата"><input type="datetime-local" className="input" value={f.date ?? ''} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>}
        <button className="btn-primary w-full !py-3" disabled={!valid || busy}>{tx ? 'сохранить' : 'записать'}</button>
      </form>
    </Sheet>
  )
}

function DebtSheet({ open, debt, onClose, onDone, onErr, accounts }) {
  const [f, setF] = useState({})
  const [hist, setHist] = useState([])
  const [busy, setBusy] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)
  useEffect(() => {
    if (!open) return
    if (debt) { setF({ title: debt.title, total: debt.total.toLocaleString('ru-RU'), remaining: debt.remaining.toLocaleString('ru-RU'), payment: debt.payment ? debt.payment.toLocaleString('ru-RU') : '', rate: debt.rate || '', pay_day: debt.pay_day }); api.debtPayments(debt.id).then(setHist).catch(() => setHist([])) }
    else { setF({ title: '', total: '', remaining: '', payment: '', rate: '', pay_day: 1 }); setHist([]) }
  }, [open, debt])
  const total = n(f.total), remaining = f.remaining === '' ? total : n(f.remaining), payment = n(f.payment) || 0, day = Number(f.pay_day)
  const errs = {
    remaining: remaining != null && total != null && remaining > total ? 'больше суммы долга' : '',
    payment: payment && total && payment > total ? 'больше самого долга' : '',
    pay_day: !(day >= 1 && day <= 31) ? '1–31' : '',
  }
  const valid = f.title?.trim() && total > 0 && !Object.values(errs).some(Boolean)
  const months = payment > 0 && remaining > 0 ? Math.ceil(remaining / payment) : null
  const submit = async (e) => {
    e.preventDefault(); if (!valid || busy) return
    setBusy(true)
    const body = { title: f.title.trim(), total, remaining: remaining ?? total, payment, rate: n(f.rate) || 0, pay_day: day }
    try { debt ? await api.updateDebt(debt.id, body) : await api.addDebt(body); onDone(debt ? 'Долг обновлён' : 'Долг добавлен') } catch (e) { onErr(e) } finally { setBusy(false) }
  }
  return (
    <Sheet open={open} onClose={onClose} title={debt ? debt.title : 'долг или кредит'} sub={debt ? `выплачено ${money(debt.paid)} из ${money(debt.total)}` : 'если указать платёж — он сам попадёт в регулярные'} wide={!!debt}>
      <div className={debt ? 'grid grid-cols-1 gap-8 sm:grid-cols-5' : ''}>
        <form onSubmit={submit} className={`space-y-4 ${debt ? 'sm:col-span-3' : ''}`}>
          <Field label="название"><input autoFocus={!debt} className="input" placeholder="Сбер кредит / долг Ване" value={f.title ?? ''} onChange={(e) => setF({ ...f, title: e.target.value })} required /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="сумма долга"><Money value={f.total ?? ''} onChange={(v) => setF({ ...f, total: v })} min={0.01} required /></Field>
            <Field label="остаток" hint={debt ? '' : 'если уже платили'} error={errs.remaining}><Money value={f.remaining ?? ''} onChange={(v) => setF({ ...f, remaining: v })} max={total} placeholder={f.total || '= сумме'} /></Field>
            <Field label="платёж в месяц" error={errs.payment}><Money value={f.payment ?? ''} onChange={(v) => setF({ ...f, payment: v })} max={total} /></Field>
            <Field label="день платежа" error={errs.pay_day}><input type="number" min="1" max="31" className={`input num ${errs.pay_day ? 'err' : ''}`} value={f.pay_day ?? 1} onChange={(e) => setF({ ...f, pay_day: e.target.value })} /></Field>
            <Field label="ставка, % годовых"><Money value={f.rate ?? ''} onChange={(v) => setF({ ...f, rate: v })} min={0} max={1000} suffix="%" placeholder="0" /></Field>
          </div>
          {months != null && <div className="muted text-[13px]">при таком платеже закроется примерно через <b>{months} {plural(months, 'месяц', 'месяца', 'месяцев')}</b>{n(f.rate) > 0 ? ' (без учёта процентов — точный срок покажу в списке)' : ''}</div>}
          <div className="flex gap-2 pt-1">
            {debt && <button type="button" className="btn-icon shrink-0" title="Удалить долг" onClick={() => setConfirmDel(true)}><Trash2 size={15} /></button>}
            <button className="btn-primary flex-1 !py-3" disabled={!valid || busy}>{debt ? 'сохранить' : 'добавить'}</button>
          </div>
        </form>
        {debt && (
          <div className="sm:col-span-2">
            <div className="label mb-2">платежи · {hist.length}</div>
            {hist.length === 0 ? <div className="faint text-[13px]">Ещё не вносили</div> : (
              <div className="max-h-[320px] overflow-auto scroll-thin">
                {hist.map((t) => (
                  <div key={t.id} className="row !gap-2 !py-2 text-[13px]">
                    <span className="muted flex-1">{shortDate(t.date)}{t.note?.includes('(авто)') ? ' · авто' : ''}</span>
                    <span className="num font-medium">{money(t.amount)}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="faint mt-3 text-[12px]">Удалить ошибочный платёж можно в «операциях» — остаток вернётся сам.</div>
          </div>
        )}
      </div>
      <Confirm open={confirmDel} danger title="Удалить долг?" text="Долг и его регулярный платёж исчезнут. Уже проведённые платежи останутся в истории операций." onClose={() => setConfirmDel(false)}
        onOk={async () => { setConfirmDel(false); try { await api.delDebt(debt.id); onDone('Долг удалён') } catch (e) { onErr(e) } }} />
    </Sheet>
  )
}

function RecSheet({ open, rec, onClose, cats, onDone, onErr }) {
  const [f, setF] = useState({})
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!open) return
    setF(rec ? { title: rec.title, amount: rec.amount.toLocaleString('ru-RU'), day: rec.day, kind: rec.kind, category: rec.category || '', period: rec.period } : { title: '', amount: '', day: 1, kind: 'expense', category: '', period: 'monthly' })
  }, [open, rec])
  const amt = n(f.amount), day = Number(f.day)
  const dayMax = f.period === 'weekly' ? 7 : 31
  const valid = f.title?.trim() && amt > 0 && day >= 1 && day <= dayMax
  const submit = async (e) => {
    e.preventDefault(); if (!valid || busy) return
    setBusy(true)
    const body = { title: f.title.trim(), amount: amt, day, kind: f.kind, category: f.category || null, period: f.period }
    try { rec ? await api.updateRecurring(rec.id, body) : await api.addRecurring(body); onDone(rec ? 'Сохранено' : 'Добавлено') } catch (e) { onErr(e) } finally { setBusy(false) }
  }
  return (
    <Sheet open={open} onClose={onClose} title={rec ? 'регулярный' : 'регулярный платёж'} sub={rec?.debt_id ? 'платёж по долгу — сумма и день синхронизируются с долгом' : 'подписки, аренда, зарплата'}>
      <form onSubmit={submit} className="space-y-4">
        {!rec?.debt_id && <Pills value={f.kind} onChange={(kind) => setF({ ...f, kind, category: '' })} options={[['expense', 'расход'], ['income', 'доход']]} />}
        <Field label="название"><input autoFocus={!rec} className="input" placeholder="Аренда / Spotify / Зарплата" value={f.title ?? ''} onChange={(e) => setF({ ...f, title: e.target.value })} required /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="сумма"><Money value={f.amount ?? ''} onChange={(v) => setF({ ...f, amount: v })} min={0.01} required /></Field>
          <Field label={f.period === 'weekly' ? 'день недели (1–7)' : 'день месяца'} error={!(day >= 1 && day <= dayMax) ? `1–${dayMax}` : ''}><input type="number" min="1" max={dayMax} className="input num" value={f.day ?? 1} onChange={(e) => setF({ ...f, day: e.target.value })} /></Field>
        </div>
        <Field label="период"><Pills value={f.period} onChange={(period) => setF({ ...f, period })} options={[['monthly', 'месяц'], ['weekly', 'неделя'], ['yearly', 'год']]} /></Field>
        {!rec?.debt_id && <Field label="категория">
          <div className="flex flex-wrap gap-1.5">{cats.filter((c) => c.kind === f.kind).map((c) => <button type="button" key={c.id} onClick={() => setF({ ...f, category: f.category === c.name ? '' : c.name })} className={`chip !py-1.5 ${f.category === c.name ? 'on' : ''}`}>{c.icon} {c.name}</button>)}</div>
        </Field>}
        <button className="btn-primary w-full !py-3" disabled={!valid || busy}>{rec ? 'сохранить' : 'добавить'}</button>
      </form>
    </Sheet>
  )
}

function AccountSheet({ open, onClose, onDone, onErr }) {
  const [f, setF] = useState({ name: '', kind: 'bank', balance: '' })
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (open) setF({ name: '', kind: 'bank', balance: '' }) }, [open])
  const submit = async (e) => {
    e.preventDefault(); if (!f.name.trim() || busy) return
    setBusy(true)
    try { await api.addAccount({ name: f.name.trim(), kind: f.kind, balance: n(f.balance) || 0 }); onDone('Счёт добавлен') } catch (e) { onErr(e) } finally { setBusy(false) }
  }
  return (
    <Sheet open={open} onClose={onClose} title="новый счёт" sub="банк, карта или наличные">
      <form onSubmit={submit} className="space-y-4">
        <Field label="название"><input autoFocus className="input" placeholder="Сбер / Альфа / Наличные" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></Field>
        <Pills value={f.kind} onChange={(kind) => setF({ ...f, kind })} options={[['bank', 'банк'], ['cash', 'наличные'], ['debt_only', 'только долги']]} />
        <Field label="текущий остаток"><Money value={f.balance} onChange={(v) => setF({ ...f, balance: v })} placeholder="0" /></Field>
        <button className="btn-primary w-full !py-3" disabled={!f.name.trim() || busy}>добавить</button>
      </form>
    </Sheet>
  )
}

function PaySheet({ debt, accounts, onClose, onDone, onErr }) {
  const [amount, setAmount] = useState('')
  const [account, setAccount] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (debt) { setAmount((Math.min(debt.payment || debt.remaining, debt.remaining) || '').toLocaleString('ru-RU')); setAccount(accounts.find((a) => a.is_main)?.name || '') } }, [debt])
  if (!debt) return null
  const amt = n(amount)
  const over = amt > debt.remaining
  const valid = amt > 0 && !over
  const left = valid ? debt.remaining - amt : null
  const submit = async (e) => {
    e.preventDefault(); if (!valid || busy) return
    setBusy(true)
    try { await api.payDebt(debt.id, amt, { account }); onDone(left === 0 ? `«${debt.title}» закрыт 🎉` : 'Платёж внесён') } catch (e) { onErr(e) } finally { setBusy(false) }
  }
  return (
    <Sheet open={!!debt} onClose={onClose} title="платёж" sub={debt.title}>
      <form onSubmit={submit} className="space-y-5">
        <div className="flex items-baseline justify-between"><span className="label">остаток</span><span className="num text-[18px] font-medium">{money(debt.remaining)}</span></div>
        <Field label="сумма" error={over ? `не больше остатка — ${money(debt.remaining)}` : ''}>
          <Money autoFocus big value={amount} onChange={setAmount} min={0.01} max={debt.remaining} />
        </Field>
        <div className="flex flex-wrap gap-1.5">
          {debt.payment > 0 && debt.payment <= debt.remaining && <button type="button" className={`chip ${amt === debt.payment ? 'on' : ''}`} onClick={() => setAmount(debt.payment.toLocaleString('ru-RU'))}>обычный · {money(debt.payment)}</button>}
          <button type="button" className={`chip ${amt === debt.remaining ? 'on' : ''}`} onClick={() => setAmount(debt.remaining.toLocaleString('ru-RU'))}>закрыть целиком · {money(debt.remaining)}</button>
        </div>
        <Field label="списать со счёта"><select className="input" value={account} onChange={(e) => setAccount(e.target.value)}>{accounts.map((a) => <option key={a.id}>{a.name}</option>)}</select></Field>
        {left != null && <div className="muted text-[13px]">после платежа останется <b className={`num ${left === 0 ? 'pos' : ''}`}>{money(left)}</b>{left === 0 ? ' — долг закроется, регулярный платёж отключится' : ''}. Спишется как трата «Долги».</div>}
        <button className="btn-primary w-full !py-3" disabled={!valid || busy}>внести {valid ? money(amt) : ''}</button>
      </form>
    </Sheet>
  )
}


const ICONS = ['🛒', '☕', '🍕', '🚗', '🏋️', '🎁', '🐶', '👶', '📚', '✈️', '💇', '🏥', '🎮', '🧾', '💄', '🍺', '🎓', '🔧', '📦', '•']

function CatSheet({ open, cat, onClose, onDone, onErr }) {
  const [f, setF] = useState({})
  useEffect(() => { if (open) setF(cat ? { name: cat.name, icon: cat.icon || '•', keywords: cat.keywords || '', budget: cat.budget || '' } : { name: '', icon: '🛒', keywords: '', budget: '' }) }, [open, cat])
  const submit = async (e) => {
    e.preventDefault()
    try {
      const body = { name: f.name, icon: f.icon, keywords: f.keywords, budget: n(f.budget) || 0 }
      if (cat) await api.updateCategory(cat.id, body); else await api.addCategory({ ...body, kind: 'expense' })
      onDone(cat ? 'Категория сохранена' : 'Категория добавлена')
    } catch (err) { onErr(err) }
  }
  const protectedCat = cat && !cat.custom && ['Другое', 'Долги', 'Прочий доход'].includes(cat.name)
  return (
    <Sheet open={open} onClose={onClose} title={cat ? cat.name : 'новая категория'} sub={cat ? 'лимит на месяц, значок и слова для авто-определения' : 'ассистент сам будет относить траты по ключевым словам'}>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-[auto_1fr] gap-3">
          <Field label="Значок">
            <select className="input !w-[72px] text-center text-[20px]" value={f.icon || '•'} onChange={(e) => setF({ ...f, icon: e.target.value })}>{[...new Set([f.icon, ...ICONS])].filter(Boolean).map((i) => <option key={i} value={i}>{i}</option>)}</select>
          </Field>
          <Field label="Название"><input autoFocus={!cat} className="input" value={f.name || ''} onChange={(e) => setF({ ...f, name: e.target.value })} required disabled={protectedCat} /></Field>
        </div>
        <Field label="Лимит в месяц" hint="0 — без лимита"><Money value={f.budget} onChange={(v) => setF({ ...f, budget: v })} min={0} big /></Field>
        <Field label="Ключевые слова" hint="через запятую"><input className="input" placeholder="кофейня, starbucks, кофе" value={f.keywords || ''} onChange={(e) => setF({ ...f, keywords: e.target.value })} /></Field>
        <div className="flex gap-2">
          {cat && !protectedCat && <button type="button" className="btn-icon" title="Удалить (операции уйдут в «Другое»)" onClick={async () => { try { await api.delCategory(cat.id); onDone('Категория удалена') } catch (err) { onErr(err) } }}><Trash2 size={15} /></button>}
          <button className="btn-primary flex-1 !py-3">{cat ? 'сохранить' : 'добавить'}</button>
        </div>
      </form>
    </Sheet>
  )
}


/* кольцо прогресса по долгу: внутри — порядковый номер */
function Ring({ pct, idx, size = 44 }) {
  const r = (size - 6) / 2, c = 2 * Math.PI * r
  return (
    <div className="relative shrink-0 self-start" style={{ width: size, height: size }} title={`выплачено ${pct}%`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth="3" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(1, pct / 100))} className="ring-fill" />
      </svg>
      <span className="idx absolute inset-0 grid place-items-center !text-[11px]">{idx}</span>
    </div>
  )
}
