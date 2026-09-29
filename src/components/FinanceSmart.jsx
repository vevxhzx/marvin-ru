import { useEffect, useState } from 'react'
import { Plus, Trash2, Check, Pencil, ChevronDown, ChevronUp, ArrowUpRight, ArrowDownRight } from 'lucide-react'
import { api, money, plural, toLocalISO } from '../lib/api'
import { Section, Sheet, Field, Money, Pills, Empty, Confirm } from './ui'

const BUCKET = { need: 'обязательное', want: 'хотелки', save: 'накопления' }
const BUCKET_TONE = { need: 'var(--ink)', want: 'var(--accent)', save: 'var(--pos)' }
const ask = (text, send = true) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text, send } }))
const ICONS = ['🎯', '🛟', '📷', '💻', '✈️', '🚗', '🏠', '🎁', '🎓', '💍', '🏋️', '🐶']

/* Конверты / цели: сколько отложено, сколько в месяц нужно, кнопка «отложить». Отложенное — расход «Накопления» с привязкой к цели. */
export function Goals({ goals, onChange, onErr, onOk }) {
  const [sheet, setSheet] = useState(null)   // 'new' | goal
  const [put, setPut] = useState(null)       // goal
  const [del, setDel] = useState(null)
  const [showClosed, setShowClosed] = useState(false)
  const [closed, setClosed] = useState([])
  useEffect(() => { if (showClosed) api.goals(true).then((all) => setClosed(all.filter((g) => g.closed))).catch(() => {}) }, [showClosed, goals])
  const list = goals || []
  const totalSaved = list.reduce((s, g) => s + g.saved, 0)
  const perMonth = list.reduce((s, g) => s + (g.per_month || 0), 0)
  return (
    <Section title="конверты" idx={list.length} hint={list.length ? `отложено ${money(totalSaved)}${perMonth ? ` · чтобы успеть везде — по ${money(perMonth)} в месяц` : ''}` : 'Цель — «подушка 300к к марту», «камера 120 тысяч». Отложенное уходит из «свободных» денег — так честнее.'}
      action={<button className="btn-ghost !py-1.5 !text-[13px]" onClick={() => setSheet('new')}><Plus size={14} /> цель</button>}>
      <div className="rule pt-6">
        {list.length === 0 && <Empty glyph="money" text="Целей пока нет" sub="Подушка безопасности — хорошее начало: 3 месяца обязательных трат" hint="цель: подушка 300к к марту" compact />}
        {list.length > 0 && (
          <div className="grid grid-cols-1 gap-x-10 gap-y-6 md:grid-cols-2">
            {list.map((g) => (
              <div key={g.id} className="group">
                <div className="flex items-baseline justify-between gap-3">
                  <button className="min-w-0 truncate text-left text-[15px] font-medium hover:text-accent" onClick={() => setSheet(g)}>{g.icon} {g.title}</button>
                  <span className="num shrink-0 text-[14px]"><b>{money(g.saved)}</b> <span className="faint">/ {money(g.target)}</span></span>
                </div>
                <div className="progress mt-2 !h-[6px]"><div style={{ width: `${Math.round(g.pct * 100)}%`, background: g.pct >= 1 ? 'var(--pos)' : 'var(--accent)' }} /></div>
                <div className="mt-1.5 flex items-center justify-between gap-2 text-[12px]">
                  <span className="muted">{Math.round(g.pct * 100)} %{g.due ? ` · к ${new Date(g.due).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}` : ''}{g.per_month ? ` · по ${money(g.per_month)} в месяц` : g.left ? ` · осталось ${money(g.left)}` : ''}{g.days_left != null && g.days_left < 0 && g.left > 0 ? ' · срок прошёл' : ''}</span>
                  <div className="flex items-center gap-1">
                    <button className="btn-soft btn-sm !h-7" onClick={() => setPut(g)}><Plus size={12} /> отложить</button>
                    <button className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100 focus:opacity-100" data-tip="изменить" onClick={() => setSheet(g)}><Pencil size={12} /></button>
                    <button className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100 focus:opacity-100" data-tip="удалить" onClick={() => setDel(g)}><Trash2 size={12} /></button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-5">
          <button className="faint flex items-center gap-1 text-[12px] hover:text-accent" onClick={() => setShowClosed((v) => !v)}>достигнутые {showClosed ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</button>
          {showClosed && (closed.length ? <div className="mt-2 flex flex-wrap gap-1.5">{closed.map((g) => <span key={g.id} className="badge pos"><Check size={11} /> {g.icon} {g.title} · {money(g.target)}</span>)}</div> : <div className="faint mt-2 text-[12px]">пока ни одной — всё впереди</div>)}
        </div>
      </div>

      <GoalSheet open={!!sheet} goal={sheet && sheet !== 'new' ? sheet : null} onClose={() => setSheet(null)} onDone={(m) => { setSheet(null); onOk?.(m); onChange() }} onErr={onErr} />
      <PutSheet goal={put} onClose={() => setPut(null)} onDone={(r) => { setPut(null); onOk?.(r.reached ? `«${r.goal.title}» — цель достигнута 🎉` : `В «${r.goal.title}» отложено`); onChange() }} onErr={onErr} />
      <Confirm open={!!del} title="Удалить цель?" text={del ? `«${del.title}». Записи о переводах останутся в операциях как «Накопления».` : ''} danger onOk={async () => { try { await api.delGoal(del.id); setDel(null); onOk?.('Цель удалена'); onChange() } catch (e) { onErr(e) } }} onClose={() => setDel(null)} />
    </Section>
  )
}

function GoalSheet({ open, goal, onClose, onDone, onErr }) {
  const [f, setF] = useState({ title: '', target: '', due: '', icon: '🎯', saved: '' })
  useEffect(() => { if (open) setF(goal ? { title: goal.title, target: String(goal.target), due: goal.due ? toLocalISO(new Date(goal.due)).slice(0, 10) : '', icon: goal.icon, saved: String(goal.saved) } : { title: '', target: '', due: '', icon: '🎯', saved: '' }) }, [open, goal])
  const num = (v) => Number(String(v).replace(/\s/g, '').replace(',', '.')) || 0
  const submit = async (e) => {
    e.preventDefault()
    const body = { title: f.title.trim(), target: num(f.target), due: f.due ? `${f.due}T23:59:00` : null, icon: f.icon, saved: num(f.saved) }
    try {
      if (goal) await api.updateGoal(goal.id, body); else await api.addGoal(body)
      onDone(goal ? 'Цель обновлена' : 'Цель добавлена')
    } catch (err) { onErr(err) }
  }
  return (
    <Sheet open={open} onClose={onClose} title={goal ? 'цель' : 'новая цель'} sub={goal ? 'сумму «отложено» лучше менять кнопкой «отложить» — тогда это попадёт в операции' : 'или скажите: «цель: подушка 300к к марту»'}>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-[auto_1fr] gap-3">
          <Field label="значок"><select className="input !w-[72px] text-center text-[20px]" value={f.icon} onChange={(e) => setF({ ...f, icon: e.target.value })}>{[...new Set([f.icon, ...ICONS])].map((i) => <option key={i} value={i}>{i}</option>)}</select></Field>
          <Field label="на что"><input autoFocus={!goal} className="input !text-[17px] !font-medium" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required placeholder="Подушка безопасности" /></Field>
        </div>
        <Field label="сумма"><Money value={f.target} onChange={(v) => setF({ ...f, target: v })} min={1} big required /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="к какой дате" hint="необязательно"><input type="date" className="input" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></Field>
          {goal && <Field label="уже отложено"><Money value={f.saved} onChange={(v) => setF({ ...f, saved: v })} min={0} /></Field>}
        </div>
        <button className="btn-primary btn-lg w-full">{goal ? 'сохранить' : 'добавить'}</button>
      </form>
    </Sheet>
  )
}

function PutSheet({ goal, onClose, onDone, onErr }) {
  const [amount, setAmount] = useState('')
  const [record, setRecord] = useState(true)
  useEffect(() => { if (goal) { setAmount(goal.per_month ? String(goal.per_month) : ''); setRecord(true) } }, [goal])
  const submit = async (e) => {
    e.preventDefault()
    const n = Number(String(amount).replace(/\s/g, '').replace(',', '.'))
    if (!n) return onErr(new Error('Введите сумму'))
    try { onDone(await api.putGoal(goal.id, n, { record_tx: record })) } catch (err) { onErr(err) }
  }
  return (
    <Sheet open={!!goal} onClose={onClose} title="отложить" sub={goal ? `${goal.icon} ${goal.title} · ${money(goal.saved)} из ${money(goal.target)}` : ''}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="сумма" hint="минус — забрать из конверта"><Money value={amount} onChange={setAmount} big autoFocus /></Field>
        {goal?.left > 0 && <div className="flex flex-wrap gap-1.5">
          {[goal.per_month, 5000, 10000, goal.left].filter((v, i, a) => v && a.indexOf(v) === i).map((v) => <button type="button" key={v} className="chip" onClick={() => setAmount(String(Math.round(v)))}>{v === goal.left ? 'закрыть' : v === goal.per_month ? 'по плану' : ''} {money(Math.round(v))}</button>)}
        </div>}
        <label className="flex cursor-pointer items-start gap-3 text-[13.5px]">
          <input type="checkbox" className="mt-1" checked={record} onChange={(e) => setRecord(e.target.checked)} />
          <span><b>Списать со счёта как «Накопления»</b><br /><span className="muted">деньги уйдут из «свободных» и прогноза. Снимите галочку, если просто отмечаете то, что уже лежит на вкладе.</span></span>
        </label>
        <button className="btn-primary btn-lg w-full">отложить</button>
      </form>
    </Sheet>
  )
}

/* Умные финансы одним блоком: 50/30/20, месяц к месяцу, «на сколько хватит», хватит ли на платежи, годовые. */
export function Techniques({ t, onOpenCat }) {
  const [tab, setTab] = useState('buckets')
  if (!t) return null
  const tabs = [['buckets', '50 / 30 / 20'], ['compare', 'месяц к месяцу'], ['runway', 'на сколько хватит'], ['annual', 'годовые']]
  const pay = t.payments
  return (
    <Section title="техники" hint="Не ради цифр — ради решений. Каждую можно спросить голосом: «50/30/20», «сравни с прошлым месяцем», «на сколько хватит».">
      {pay?.short > 0 && (
        <div className="soft-neg mb-5 flex flex-wrap items-center justify-between gap-2 rounded-2xl px-4 py-2.5 text-[13px]">
          <span>На ближайшие {pay.days} дн. платежей на <b className="num">{money(pay.need)}</b>, а на счетах <b className="num">{money(pay.balance)}</b> — не хватает <b className="num">{money(pay.short)}</b>.</span>
          <button className="btn-ghost btn-sm" style={{ color: 'inherit', borderColor: 'currentColor' }} onClick={() => ask('хватит ли на платежи')}>подробнее</button>
        </div>
      )}
      <div className="mb-5 flex flex-wrap gap-1">
        {tabs.map(([k, l]) => <button key={k} className={`rounded-md px-2.5 py-1 text-[13px] transition-colors ${tab === k ? 'bg-[var(--fill)] text-[var(--ink)]' : 'muted hover:text-[var(--ink)]'}`} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      <div className="rule pt-6">
        {tab === 'buckets' && <Buckets b={t.buckets} onOpenCat={onOpenCat} />}
        {tab === 'compare' && <Compare c={t.compare} />}
        {tab === 'runway' && <Runway r={t.runway} p={pay} />}
        {tab === 'annual' && <Annual a={t.annual} />}
      </div>
    </Section>
  )
}

function Buckets({ b, onOpenCat }) {
  if (!b?.base) return <Empty glyph="money" text="За этот месяц пока нет операций" sub="Как появятся траты — покажу, куда уходит доход" compact />
  return (
    <div>
      <div className="flex h-[10px] w-full overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
        {b.buckets.map((x) => <div key={x.bucket} className="h-full transition-all duration-700" style={{ width: `${Math.min(100, x.share * 100)}%`, background: BUCKET_TONE[x.bucket] }} />)}
      </div>
      <div className="mt-1.5 flex h-[3px] w-full overflow-hidden rounded-full opacity-40" style={{ background: 'var(--fill-2)' }} title="норма 50 / 30 / 20">
        {b.buckets.map((x) => <div key={x.bucket} className="h-full" style={{ width: `${x.norm * 100}%`, background: BUCKET_TONE[x.bucket] }} />)}
      </div>
      <div className="mt-6 grid grid-cols-3 gap-4">
        {b.buckets.map((x) => (
          <div key={x.bucket}>
            <div className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: BUCKET_TONE[x.bucket] }} /><span className="label">{x.label}</span></div>
            <div className={`num mt-2 text-[26px] font-medium leading-none tracking-[-0.03em] sm:text-[32px] ${x.status === 'over' ? 'neg' : x.status === 'low' ? 'warn' : ''}`}>{Math.round(x.share * 100)}<span className="text-[16px]"> %</span></div>
            <div className="muted mt-1 text-[12px]">{money(x.amount)} · норма {Math.round(x.norm * 100)} %{x.status === 'over' ? ' · много' : x.status === 'low' ? ' · мало' : ''}</div>
          </div>
        ))}
      </div>
      <div className="muted mt-5 text-[12.5px]">
        считаю {b.income > 0 ? 'от дохода' : 'от трат — доходов в этом месяце ещё нет'} за месяц: {money(b.base)}.
        {b.unassigned > 0 && <> Не размечено <b className="num">{money(b.unassigned)}</b> — {b.unassigned_cats.slice(0, 4).map((c, i) => <button key={c} className="underline decoration-dotted underline-offset-2 hover:text-accent" onClick={() => onOpenCat?.(c)}>{c}{i < Math.min(4, b.unassigned_cats.length) - 1 ? ', ' : ''}</button>)} — нажмите на категорию и отметьте корзину.</>}
      </div>
    </div>
  )
}

function Compare({ c }) {
  if (!c || (!c.spent && !c.spent_prev_same)) return <Empty glyph="money" text="Сравнивать пока нечего" sub="Нужны траты хотя бы за этот и прошлый месяц" compact />
  const d = c.spent - c.spent_prev_same
  const pct = c.spent_prev_same ? Math.round((d / c.spent_prev_same) * 100) : null
  return (
    <div>
      <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
        <div><div className="label">к {c.day}-му числу</div><div className="num mt-2 text-[26px] font-medium leading-none tracking-[-0.03em] sm:text-[32px]">{money(c.spent)}</div><div className="muted mt-1 text-[12px]">в прошлом к этому дню · {money(c.spent_prev_same)}</div></div>
        <div><div className="label">разница</div><div className={`num mt-2 flex items-center gap-1 text-[26px] font-medium leading-none tracking-[-0.03em] sm:text-[32px] ${d > 0 ? 'neg' : d < 0 ? 'pos' : ''}`}>{d > 0 ? <ArrowUpRight size={22} /> : d < 0 ? <ArrowDownRight size={22} /> : null}{money(Math.abs(d))}</div><div className="muted mt-1 text-[12px]">{pct == null ? 'прошлый месяц пустой' : d > 0 ? `тратите на ${Math.abs(pct)} % больше` : d < 0 ? `экономнее на ${Math.abs(pct)} %` : 'ровно так же'}</div></div>
        <div><div className="label">средний чек</div><div className="num mt-2 text-[26px] font-medium leading-none tracking-[-0.03em] sm:text-[32px]">{money(c.avg_check)}</div><div className="muted mt-1 text-[12px]">прошлый · {money(c.avg_check_prev)}</div></div>
        <div><div className="label">доход</div><div className="num mt-2 text-[26px] font-medium leading-none tracking-[-0.03em] sm:text-[32px]">{money(c.earned)}</div><div className="muted mt-1 text-[12px]">прошлый весь · {money(c.earned_prev)}</div></div>
      </div>
      {c.categories.length > 0 && (
        <div className="mt-6 grid grid-cols-1 gap-x-10 gap-y-2 md:grid-cols-2">
          {c.categories.slice(0, 8).map((r) => (
            <div key={r.category} className="flex items-baseline justify-between gap-3 text-[13.5px]">
              <span className="truncate">{r.category}</span>
              <span className="num shrink-0"><b>{money(r.current)}</b> <span className="faint">/ {money(r.prev_same)}</span> <span className={`ml-1 inline-block w-[64px] text-right text-[12px] ${r.delta > 0 ? 'neg' : r.delta < 0 ? 'pos' : 'faint'}`}>{r.delta_pct == null ? (r.current ? 'новое' : '') : `${r.delta > 0 ? '+' : ''}${Math.round(r.delta_pct * 100)} %`}</span></span>
            </div>
          ))}
        </div>
      )}
      <div className="muted mt-4 text-[12px]">сравниваю с прошлым месяцем на тот же день — так честно, а не «в прошлом было 30 дней, а сейчас 12»</div>
    </div>
  )
}

function Runway({ r, p }) {
  if (!r) return null
  const days = r.runway_days
  return (
    <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
      <div className="col-span-2">
        <div className="label">при текущем темпе хватит на</div>
        <div className={`num mt-2 text-[40px] font-medium leading-none tracking-[-0.04em] sm:text-[52px] ${days == null ? 'muted' : r.ok ? 'accent' : 'neg'}`}>{days == null ? '—' : `${days} ${plural(days, 'день', 'дня', 'дней')}`}</div>
        <div className="muted mt-2 text-[13px]">{days == null ? 'средних трат за 30 дней пока нет' : r.ok ? `до дохода ${r.days_left_to_income} ${plural(r.days_left_to_income, 'день', 'дня', 'дней')} — дотягиваете` : `до дохода ${r.days_left_to_income} ${plural(r.days_left_to_income, 'день', 'дня', 'дней')} — не дотягиваете, нужно ≤ ${money(r.safe_per_day)} в день`}</div>
      </div>
      <div><div className="label">свободно</div><div className="num mt-2 text-[24px] font-medium leading-none tracking-[-0.03em] sm:text-[30px]">{money(r.free)}</div><div className="muted mt-1.5 text-[12px]">после обязательных платежей</div></div>
      <div><div className="label">трачу в день</div><div className="num mt-2 text-[24px] font-medium leading-none tracking-[-0.03em] sm:text-[30px]">{money(r.per_day_avg)}</div><div className="muted mt-1.5 text-[12px]">среднее за 30 дней</div></div>
      {p && <div className="col-span-2 md:col-span-4 muted text-[12.5px]">
        платежей на {p.days} дн.: <b className="num">{money(p.need)}</b>{p.payments.length ? ` (${p.payments.slice(0, 3).map((x) => x.title).join(', ')})` : ''} · на счетах <b className="num">{money(p.balance)}</b>{p.incoming.length ? ` · ожидается доход ${money(p.incoming.reduce((s, x) => s + x.amount, 0))}` : ''} → {p.short > 0 ? <b className="neg">не хватает {money(p.short)}</b> : <b className="pos">хватает</b>}
      </div>}
    </div>
  )
}

function Annual({ a }) {
  if (!a?.items?.length) return <Empty glyph="money" text="Годовых платежей нет" sub="Страховка, налоги, домен, ТО — добавьте регулярный платёж с периодом «раз в год», и я скажу, сколько откладывать в месяц" hint="каждый год 15 мая страховка 45000" compact />
  return (
    <div>
      <div className="grid grid-cols-2 gap-6">
        <div><div className="label">за год</div><div className="num mt-2 text-[26px] font-medium leading-none tracking-[-0.03em] sm:text-[32px]">{money(a.total_year)}</div></div>
        <div><div className="label">откладывать в месяц</div><div className="num accent mt-2 text-[26px] font-medium leading-none tracking-[-0.03em] sm:text-[32px]">{money(a.per_month)}</div><div className="muted mt-1 text-[12px]">чтобы годовые не были «внезапными»</div></div>
      </div>
      <div className="rule mt-5">
        {a.items.map((i) => <div key={i.title} className="row"><div className="min-w-0 flex-1"><div className="truncate text-[14px] font-medium">{i.title}</div><div className="muted text-[12px]">{new Date(i.next).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })} · через {i.months} {plural(i.months, 'месяц', 'месяца', 'месяцев')}</div></div><div className="num text-right"><div className="text-[14px] font-medium">{money(i.amount)}</div><div className="muted text-[11.5px]">{money(Math.round(i.amount / 12))} / мес</div></div></div>)}
      </div>
    </div>
  )
}

export function BucketPills({ value, onChange }) {
  return <Pills value={value || ''} onChange={onChange} options={[['need', 'обязательное'], ['want', 'хотелки'], ['save', 'накопления'], ['', 'не размечать']]} />
}
