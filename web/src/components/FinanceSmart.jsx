import { useEffect, useState } from 'react'
import { Plus, Trash2, Check, Pencil, ChevronDown, ChevronUp, ArrowUpRight, ArrowDownRight } from 'lucide-react'
import { api, money, toLocalISO } from '../lib/api'
import { Section, Sheet, Field, Money, Pills, Empty, Confirm } from './ui'
import { useI18n, localeOf, t as T } from '../lib/i18n'
import { useBigSize } from './Widgets'

/* Переключатель на телефоне — одна прокручиваемая строка: четыре вкладки в два ряда
   съедали место и ломали ритм карточки. */
const SEG_ROW_M = 'no-scrollbar max-[820px]:!flex-nowrap max-[820px]:!overflow-x-auto max-[820px]:!max-w-full max-[820px]:!mb-4'

const BUCKET = { need: 'bucket.need', want: 'bucket.want', save: 'bucket.save' }
const BUCKET_TONE = { need: 'var(--ink)', want: 'var(--accent)', save: 'var(--pos)' }
const BUCKET_GRAD = {
  need: 'linear-gradient(90deg, var(--ink), #4b4b55)',
  want: 'linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--acc) 55%, #ffffff))',
  save: 'linear-gradient(90deg, #19b34a, #14b8a6)',
}
const ask = (text, send = true) => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text, send } }))
const ICONS = ['🎯', '🛟', '📷', '💻', '✈️', '🚗', '🏠', '🎁', '🎓', '💍', '🏋️', '🐶']

/* Конверты / цели: сколько отложено, сколько в месяц нужно, кнопка «отложить». Отложенное — расход «Накопления» с привязкой к цели. */
export function Goals({ goals, onChange, onErr, onOk }) {
  const { t } = useI18n()
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
    <Section title={t('gl.title')} idx={list.length} hint={t(list.length ? 'gl.hint' : 'gl.hint_empty', { saved: money(totalSaved), per: perMonth ? t('gl.per_month_tail', { per: money(perMonth) }) : '' })}
      action={<button className="btn-ghost !py-1.5 !text-[13px]" onClick={() => setSheet('new')}><Plus size={14} /> {t('gl.goal')}</button>}>
      <div className="rule pt-6">
        {list.length === 0 && <Empty glyph="money" text={t('gl.none')} sub={t('gl.none_hint')} hint={t('gl.hint_example')} compact />}
        {list.length > 0 && (
          <div className="grid grid-cols-1 gap-x-10 gap-y-6 md:grid-cols-2">
            {list.map((g) => (
              <div key={g.id} className="group">
                <div className="flex items-baseline justify-between gap-3">
                  <button className="min-w-0 truncate text-left text-[15px] font-medium hover:text-accent" onClick={() => setSheet(g)}>{g.icon} {g.title}</button>
                  <span className="num shrink-0 text-[14px]"><b>{money(g.saved)}</b> <span className="faint">/ {money(g.target)}</span></span>
                </div>
                <div className="progress mt-2 !h-[6px]"><div style={{ width: `${Math.round(g.pct * 100)}%`, background: g.pct >= 1 ? 'linear-gradient(90deg, #19b34a, #14b8a6)' : 'linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--acc) 55%, #ffffff))' }} /></div>
                <div className="mt-1.5 flex items-center justify-between gap-2 text-[12px]">
                  <span className="muted">{Math.round(g.pct * 100)} %{g.due ? ` · ${t('aims.by', { date: new Date(g.due).toLocaleDateString(localeOf(), { day: 'numeric', month: 'short' }).replace(/\.?\s*г\.$/u, '') })}` : ''}{g.per_month ? ` · ${t('gl.per_month', { m: money(g.per_month) })}` : g.left ? ` · ${t('gl.left', { m: money(g.left) })}` : ''}{g.days_left != null && g.days_left < 0 && g.left > 0 ? ` · ${t('aims.overdue')}` : ''}</span>
                  <div className="flex items-center gap-1">
                    <button className="btn-soft btn-sm !h-7" onClick={() => setPut(g)}><Plus size={12} /> {t('gl.put')}</button>
                    <button className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100 focus:opacity-100" data-tip={t('common.edit')} aria-label={t('common.edit')} title={t('common.edit')} onClick={() => setSheet(g)}><Pencil size={12} /></button>
                    <button className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100 focus:opacity-100" data-tip={t('common.delete')} aria-label={t('common.delete')} title={t('common.delete')} onClick={() => setDel(g)}><Trash2 size={12} /></button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-5">
          <button className="faint flex items-center gap-1 text-[12px] hover:text-accent" onClick={() => setShowClosed((v) => !v)}>{t('gl.reached')} {showClosed ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</button>
          {showClosed && (closed.length ? <div className="mt-2 flex flex-wrap gap-1.5">{closed.map((g) => <span key={g.id} className="badge pos"><Check size={11} /> {g.icon} {g.title} · {money(g.target)}</span>)}</div> : <div className="faint mt-2 text-[12px]">{t('gl.reached_none')}</div>)}
        </div>
      </div>

      <GoalSheet open={!!sheet} goal={sheet && sheet !== 'new' ? sheet : null} onClose={() => setSheet(null)} onDone={(m) => { setSheet(null); onOk?.(m); onChange() }} onErr={onErr} />
      <PutSheet goal={put} onClose={() => setPut(null)} onDone={(r) => { setPut(null); onOk?.(t(r.reached ? 'gl.put_reached' : 'gl.put_done', { title: r.goal.title })); onChange() }} onErr={onErr} />
      <Confirm open={!!del} title={t('gl.del_q')} text={del ? t('gl.del_text', { title: del.title }) : ''} danger onOk={async () => { try { await api.delGoal(del.id); setDel(null); onOk?.(t('gl.deleted')); onChange() } catch (e) { onErr(e) } }} onClose={() => setDel(null)} />
    </Section>
  )
}

function GoalSheet({ open, goal, onClose, onDone, onErr }) {
  const { t } = useI18n()
  const [f, setF] = useState({ title: '', target: '', due: '', icon: '🎯', saved: '' })
  useEffect(() => { if (open) setF(goal ? { title: goal.title, target: String(goal.target), due: goal.due ? toLocalISO(new Date(goal.due)).slice(0, 10) : '', icon: goal.icon, saved: String(goal.saved) } : { title: '', target: '', due: '', icon: '🎯', saved: '' }) }, [open, goal])
  const num = (v) => Number(String(v).replace(/\s/g, '').replace(',', '.')) || 0
  const submit = async (e) => {
    e.preventDefault()
    const body = { title: f.title.trim(), target: num(f.target), due: f.due ? `${f.due}T23:59:00` : null, icon: f.icon, saved: num(f.saved) }
    try {
      if (goal) await api.updateGoal(goal.id, body); else await api.addGoal(body)
      onDone(t(goal ? 'gl.updated' : 'gl.added'))
    } catch (err) { onErr(err) }
  }
  return (
    <Sheet open={open} onClose={onClose} title={t(goal ? 'gl.goal' : 'gl.new_goal')} sub={t(goal ? 'gl.edit_sub' : 'gl.new_sub')}>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid grid-cols-[auto_1fr] gap-3">
          <Field label={t('gl.icon')}><select className="input !w-[72px] text-center text-[20px]" value={f.icon} onChange={(e) => setF({ ...f, icon: e.target.value })}>{[...new Set([f.icon, ...ICONS])].map((i) => <option key={i} value={i}>{i}</option>)}</select></Field>
          <Field label={t('gl.for_what')}><input autoFocus={!goal} className="input !text-[17px] !font-medium" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} required placeholder={t('gl.ph_title')} /></Field>
        </div>
        <Field label={t('common.amount')}><Money value={f.target} onChange={(v) => setF({ ...f, target: v })} min={1} big required /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label={t('gl.which_date')} hint={t('common.optional')}><input type="date" className="input" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></Field>
          {goal && <Field label={t('gl.already_saved')}><Money value={f.saved} onChange={(v) => setF({ ...f, saved: v })} min={0} /></Field>}
        </div>
        <button className="btn-primary btn-lg w-full">{t(goal ? 'common.save' : 'common.add')}</button>
      </form>
    </Sheet>
  )
}

function PutSheet({ goal, onClose, onDone, onErr }) {
  const { t } = useI18n()
  const [amount, setAmount] = useState('')
  const [record, setRecord] = useState(true)
  useEffect(() => { if (goal) { setAmount(goal.per_month ? String(goal.per_month) : ''); setRecord(true) } }, [goal])
  const submit = async (e) => {
    e.preventDefault()
    const n = Number(String(amount).replace(/\s/g, '').replace(',', '.'))
    if (!n) return onErr(new Error(t('gl.enter_amount')))
    try { onDone(await api.putGoal(goal.id, n, { record_tx: record })) } catch (err) { onErr(err) }
  }
  return (
    <Sheet open={!!goal} onClose={onClose} title={t('gl.put')} sub={goal ? `${goal.icon} ${goal.title} · ${t('gl.of', { a: money(goal.saved), b: money(goal.target) })}` : ''}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('common.amount')} hint={t('gl.put_hint')}><Money value={amount} onChange={setAmount} big autoFocus /></Field>
        {goal?.left > 0 && <div className="flex flex-wrap gap-1.5">
          {[goal.per_month, 5000, 10000, goal.left].filter((v, i, a) => v && a.indexOf(v) === i).map((v) => <button type="button" key={v} className="chip" onClick={() => setAmount(String(Math.round(v)))}>{v === goal.left ? t('gl.close_it') : v === goal.per_month ? t('gl.by_plan') : ''} {money(Math.round(v))}</button>)}
        </div>}
        <label className="flex cursor-pointer items-start gap-3 text-[13.5px]">
          <input type="checkbox" className="mt-1" checked={record} onChange={(e) => setRecord(e.target.checked)} />
          <span><b>{t('gl.record')}</b><br /><span className="muted">{t('gl.record_hint')}</span></span>
        </label>
        <button className="btn-primary btn-lg w-full">{t('gl.put')}</button>
      </form>
    </Sheet>
  )
}

/* Умные финансы одним блоком: 50/30/20, месяц к месяцу, «на сколько хватит», хватит ли на платежи, годовые.
   Внутри — спокойные переключатели и числа, без « Bento V7»: раздел «финансы» держит
   один герой на экране, поэтому техники — ровнями и полосками внутри своей панели. */
export function Techniques({ t: data, onOpenCat }) {
  const { t } = useI18n()
  const [tab, setTab] = useState('buckets')
  if (!data) return null
  const tabs = [['buckets', t('tech.tab_buckets')], ['compare', t('tech.tab_compare')], ['runway', t('tech.tab_runway')], ['annual', t('tech.tab_annual')]]
  const pay = data.payments
  return (
    <div>
      <div className="hd flex-wrap">
        <div className="min-w-0"><h2 className="trunc">{t('tech.title')}</h2></div>
        <small className="trunc">{t('tech.hint')}</small>
      </div>
      {pay?.short > 0 && (
        <div className="soft-neg mb-4 flex flex-wrap items-center justify-between gap-2 rounded-2xl px-4 py-2.5 text-[length:var(--fs-md)]">
          <span>{t('tech.short_text', { days: pay.days, need: money(pay.need), bal: money(pay.balance), short: money(pay.short) })}</span>
          <button className="btn-ghost btn-sm" style={{ color: 'inherit', borderColor: 'currentColor' }} onClick={() => ask(T('tech.ask_enough'))}>{t('common.details')}</button>
        </div>
      )}
      <div className={`seg ${SEG_ROW_M}`} role="group" aria-label={t('tech.title')}>
        {tabs.map(([k, l]) => (
          <button key={k} type="button" className={tab === k ? 'on' : ''} aria-pressed={tab === k} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {tab === 'buckets' && <Buckets b={data.buckets} onOpenCat={onOpenCat} />}
      {tab === 'compare' && <Compare c={data.compare} />}
      {tab === 'runway' && <Runway r={data.runway} p={pay} />}
      {tab === 'annual' && <Annual a={data.annual} />}
    </div>
  )
}

function Buckets({ b, onOpenCat }) {
  const { t } = useI18n()
  if (!b?.base) return <Empty glyph="money" text={t('tech.no_ops')} sub={t('tech.no_ops_hint')} compact />
  return (
    <div>
      <div className="flex h-[10px] w-full overflow-hidden rounded-full" style={{ background: 'var(--fill-2)' }}>
        {b.buckets.map((x) => <div key={x.bucket} className="h-full transition-all duration-700" style={{ width: `${Math.min(100, x.share * 100)}%`, background: BUCKET_GRAD[x.bucket] || BUCKET_TONE[x.bucket] }} />)}
      </div>
      <div className="mt-1.5 flex h-[3px] w-full overflow-hidden rounded-full opacity-40" style={{ background: 'var(--fill-2)' }} title={t('tech.norm')}>
        {b.buckets.map((x) => <div key={x.bucket} className="h-full" style={{ width: `${x.norm * 100}%`, background: BUCKET_GRAD[x.bucket] || BUCKET_TONE[x.bucket] }} />)}
      </div>
      <div className="mt-5">
        {b.buckets.map((x) => (
          <div key={x.bucket} className="rule row">
            <span className="flex min-w-0 items-center gap-2">
              <i className="h-2 w-2 shrink-0 rounded-full" style={{ background: BUCKET_TONE[x.bucket] }} />
              <span className="label trunc">{t.sv(x.label) || x.label}</span>
            </span>
            <span className={`num shrink-0 text-[length:var(--fs-lg)] font-medium ${x.status === 'over' ? 'neg' : x.status === 'low' ? 'warn' : ''}`}>
              {Math.round(x.share * 100)} <span className="text-[length:var(--fs-md)]">%</span>
            </span>
            <span className="num ml-auto shrink-0 text-[length:var(--fs-md)] text-[var(--ink-2)]">{money(x.amount)}</span>
            <span className="muted shrink-0 truncate text-[length:var(--fs-xs)]">
              {t('tech.norm')} {Math.round(x.norm * 100)} %{x.status === 'over' ? t('tech.over') : x.status === 'low' ? t('tech.under') : ''}
            </span>
          </div>
        ))}
      </div>
      <div className="muted mt-4 text-[length:var(--fs-md)]">
        {t('tech.counting', { base: b.income > 0 ? t('tech.from_income') : t('tech.from_spend') })}{money(b.base)}.
        {b.unassigned > 0 && <> {t('tech.unassigned')} <b className="num">{money(b.unassigned)}</b> — {b.unassigned_cats.slice(0, 4).map((c, i) => <button key={c} className="underline decoration-dotted underline-offset-2 hover:text-accent" onClick={() => onOpenCat?.(c)}>{c}{i < Math.min(4, b.unassigned_cats.length) - 1 ? ', ' : ''}</button>)} — {t('tech.pick_cat')}</>}
      </div>
    </div>
  )
}

function Compare({ c }) {
  const { t } = useI18n()
  if (!c || (!c.spent && !c.spent_prev_same)) return <Empty glyph="money" text={t('cmp.none')} sub={t('cmp.none_hint')} compact />
  const d = c.spent - c.spent_prev_same
  const pct = c.spent_prev_same ? Math.round((d / c.spent_prev_same) * 100) : null
  return (
    <div>
      <div>
        <div className="row">
          <span className="label min-w-0 flex-1 trunc">{t('cmp.by_day', { day: c.day })}</span>
          <span className="num shrink-0 text-[length:var(--fs-lg)] font-medium">{money(c.spent)}</span>
          <span className="muted shrink-0 text-[length:var(--fs-xs)]">{t('cmp.prev_same_day')} · {money(c.spent_prev_same)}</span>
        </div>
        <div className="row">
          <span className="label min-w-0 flex-1 trunc">{t('cmp.diff')}</span>
          <span className={`num flex shrink-0 items-center gap-1 text-[length:var(--fs-lg)] font-medium ${d > 0 ? 'neg' : d < 0 ? 'pos' : ''}`}>
            {d > 0 ? <ArrowUpRight size={18} /> : d < 0 ? <ArrowDownRight size={18} /> : null}{money(Math.abs(d))}
          </span>
          <span className="muted shrink-0 text-[length:var(--fs-xs)]">{t(pct == null ? 'cmp.prev_empty' : d > 0 ? 'cmp.more' : d < 0 ? 'cmp.less' : 'cmp.same', { n: Math.abs(pct) })}</span>
        </div>
        <div className="row">
          <span className="label min-w-0 flex-1 trunc">{t('cmp.avg_check')}</span>
          <span className="num shrink-0 text-[length:var(--fs-lg)] font-medium">{money(c.avg_check)}</span>
          <span className="muted shrink-0 text-[length:var(--fs-xs)]">{t('cmp.prev')} · {money(c.avg_check_prev)}</span>
        </div>
        <div className="row">
          <span className="label min-w-0 flex-1 trunc">{t('cmp.income')}</span>
          <span className="num shrink-0 text-[length:var(--fs-lg)] font-medium">{money(c.earned)}</span>
          <span className="muted shrink-0 text-[length:var(--fs-xs)]">{t('cmp.prev_total')} · {money(c.earned_prev)}</span>
        </div>
      </div>
      {c.categories.length > 0 && (
        <div className="mt-3">
          {c.categories.slice(0, 8).map((r) => (
            <div key={r.category} className="row">
              <span className="truncate text-[length:var(--fs-md)]">{t.sv(r.category) || r.category}</span>
              <span className="num ml-auto shrink-0"><b>{money(r.current)}</b> <span className="faint">/ {money(r.prev_same)}</span></span>
              <span className={`num w-[64px] shrink-0 text-right text-[length:var(--fs-md)] ${r.delta > 0 ? 'neg' : r.delta < 0 ? 'pos' : 'faint'}`}>{r.delta_pct == null ? (r.current ? t('cmp.new') : '') : `${r.delta > 0 ? '+' : ''}${Math.round(r.delta_pct * 100)} %`}</span>
            </div>
          ))}
        </div>
      )}
      <div className="muted mt-3 text-[length:var(--fs-md)]">{t('cmp.note')}</div>
    </div>
  )
}

function Runway({ r, p }) {
  const { t } = useI18n()
  const big = useBigSize()
  if (!r) return null
  const days = r.runway_days
  return (
    <div>
      <div className="rule row">
        <span className="label min-w-0 flex-1 trunc">{t('run.will_last')}</span>
        <span className={`num shrink-0 font-medium tracking-[-0.03em] ${days == null ? 'muted' : r.ok ? 'accent' : 'neg'}`} style={{ fontSize: big }}>{days == null ? '—' : t('run.days_n', { count: days })}</span>
      </div>
      <div className="row">
        <span className="label min-w-0 flex-1 trunc">{t('run.free')}</span>
        <span className="num shrink-0 text-[length:var(--fs-lg)] font-medium">{money(r.free)}</span>
        <span className="muted shrink-0 text-[length:var(--fs-xs)]">{t('run.after_mandatory')}</span>
      </div>
      <div className="row">
        <span className="label min-w-0 flex-1 trunc">{t('run.per_day')}</span>
        <span className="num shrink-0 text-[length:var(--fs-lg)] font-medium">{money(r.per_day_avg)}</span>
        <span className="muted shrink-0 text-[length:var(--fs-xs)]">{t('run.avg30')}</span>
      </div>
      <div className="muted mt-3 text-[length:var(--fs-md)]">
        {days == null ? t('run.no_avg') : t(r.ok ? 'run.enough' : 'run.not_enough', { days: r.days_left_to_income, safe: money(r.safe_per_day) })}
      </div>
      {p && (
        <div className="muted mt-1 text-[length:var(--fs-md)]">
          {t('run.pays', { days: p.days, need: money(p.need), bal: money(p.balance) })}{p.payments.length ? ` (${p.payments.slice(0, 3).map((x) => x.title).join(', ')})` : ''}{p.incoming.length ? ` · ${t('run.incoming', { m: money(p.incoming.reduce((s, x) => s + x.amount, 0)) })}` : ''} → {p.short > 0 ? <b className="neg">{t('run.short', { m: money(p.short) })}</b> : <b className="pos">{t('run.enough_short')}</b>}
        </div>
      )}
    </div>
  )
}

function Annual({ a }) {
  const { t } = useI18n()
  if (!a?.items?.length) return <Empty glyph="money" text={t('ann.none')} sub={t('ann.none_hint')} hint={t('ann.hint_example')} compact />
  return (
    <div>
      <div className="row">
        <span className="label min-w-0 flex-1 trunc">{t('ann.per_year')}</span>
        <span className="num shrink-0 text-[length:var(--fs-lg)] font-medium">{money(a.total_year)}</span>
        <span className="muted shrink-0 text-[length:var(--fs-xs)]">{t('ann.note')}</span>
      </div>
      <div className="row">
        <span className="label min-w-0 flex-1 trunc">{t('ann.per_month_label')}</span>
        <span className="num accent shrink-0 text-[length:var(--fs-lg)] font-medium">{money(a.per_month)}</span>
      </div>
      <div className="mt-1">
        {a.items.map((i) => (
          <div key={i.title} className="row">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[length:var(--fs-base)] font-medium">{i.title}</span>
              <span className="muted block text-[length:var(--fs-xs)]">{new Date(i.next).toLocaleDateString(localeOf(), { day: 'numeric', month: 'long' }).replace(/\.?\s*г\.$/u, '')} · {t('ann.in_months', { count: i.months })}</span>
            </span>
            <span className="num shrink-0 text-right">
              <span className="block text-[length:var(--fs-base)] font-medium">{money(i.amount)}</span>
              <span className="muted block text-[length:var(--fs-xs)]">{money(Math.round(i.amount / 12))} / {t('unit.month')}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function BucketPills({ value, onChange }) {
  const { t } = useI18n()
  return <Pills value={value || ''} onChange={onChange} options={[[BUCKET.need, t('bucket.need')], [BUCKET.want, t('bucket.want')], [BUCKET.save, t('bucket.save')], ['', t('bucket.none')]]} />
}
