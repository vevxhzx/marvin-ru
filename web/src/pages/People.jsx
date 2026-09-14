import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, Plus, Pencil, Check, MessageCircle, Cake, Briefcase, CalendarDays, CheckSquare, StickyNote, Link2, HandCoins, ExternalLink } from 'lucide-react'
import { api, money, relTime, shortDate, hhmm, plural } from '../lib/api'
import { Card, Empty, PageHead, Pills, Sheet, Field, Skeleton, useToast, Toast } from '../components/ui'
import { useRefresh } from '../App'

/* Люди и клиенты: кто это, что мы им должны и что они нам, встречи, задачи, мысли — всё, что ассистент собрал сам.
   Карточка редактируется прямо здесь; ассистент показывает то же самое на «что по Ване». */
const KIND_RU = { person: 'человек', client: 'клиент', company: 'компания' }
const KIND_OPTS = [['person', 'человек'], ['client', 'клиент'], ['company', 'компания']]

const initials = (name) => (name || '?').split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || '').join('')
const bdaySoon = (b) => {
  if (!b) return null
  const m = /^(\d{4})?-?(\d{2})-(\d{2})$/.exec(b.length === 5 ? `-${b}` : b) || /^(\d{2})\.(\d{2})/.exec(b)
  if (!m) return null
  const [mm, dd] = b.includes('.') ? [Number(b.split('.')[1]), Number(b.split('.')[0])] : [Number(m[2]), Number(m[3])]
  const now = new Date(); let next = new Date(now.getFullYear(), mm - 1, dd)
  if (next < new Date(now.getFullYear(), now.getMonth(), now.getDate())) next = new Date(now.getFullYear() + 1, mm - 1, dd)
  const days = Math.round((next - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 864e5)
  return days <= 14 ? days : null
}

export default function People() {
  const [list, setList] = useState(null)
  const [q, setQ] = useState('')
  const [tab, setTab] = useState('all')
  const [openId, setOpenId] = useState(null)
  const [adding, setAdding] = useState(false)
  const [params, setParams] = useSearchParams()
  const { tick, bump } = useRefresh()
  const { msg, show } = useToast()

  const load = () => api.people().then(setList).catch(() => setList([]))
  useEffect(() => { load() }, [tick])
  useEffect(() => { const id = Number(params.get('id')); if (id) { setOpenId(id); setParams({}, { replace: true }) } }, [params])

  const items = useMemo(() => {
    const s = q.trim().toLowerCase()
    return (list || [])
      .filter((p) => tab === 'all' || (tab === 'client' ? p.kind !== 'person' : p.kind === 'person'))
      .filter((p) => !s || [p.name, p.aliases, p.contact, ...(p.tags || [])].join(' ').toLowerCase().includes(s))
      .sort((a, b) => (b.open - a.open) || (b.unpaid - a.unpaid) || a.name.localeCompare(b.name, 'ru'))
  }, [list, q, tab])

  const unpaidTotal = (list || []).reduce((s, p) => s + (p.unpaid || 0), 0)
  return (
    <div className="space-y-8">
      <PageHead kicker="кто есть кто" title="люди" idx={list?.length}
        sub={list?.length ? `${(list || []).filter((p) => p.open).length} с открытыми заказами${unpaidTotal ? ` · не оплачено ${money(unpaidTotal)}` : ''}` : undefined}
        right={<div className="flex flex-wrap items-center gap-2"><Pills value={tab} onChange={setTab} options={[['all', 'все'], ['person', 'люди'], ['client', 'клиенты']]} /><button className="btn-primary btn-sm" onClick={() => setAdding(true)}><Plus size={14} /> человек</button></div>} />

      <div className="animate-rise relative">
        <Search size={17} className="faint absolute left-4 top-1/2 -translate-y-1/2" />
        <input value={q} onChange={(e) => setQ(e.target.value)} className="input !rounded-full !pl-11" placeholder="Имя, прозвище, тег, контакт…" />
      </div>

      {!list ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"><Skeleton h={120} /><Skeleton h={120} /><Skeleton h={120} /></div>
        : items.length === 0 ? (
          <Card><Empty glyph={q ? 'search' : 'memory'} text={q ? 'Никого не нашёл' : 'Пока никого'} hint={q ? undefined : 'человек: Лена, сестра, др 12 марта'}
            sub={q ? '' : 'Скажите ассистенту, кто есть кто — дальше он сам будет собирать заказы, встречи и мысли к карточке'} /></Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((p, i) => <PersonTile key={p.id} p={p} onOpen={() => setOpenId(p.id)} delay={i * 25} />)}
          </div>
        )}

      <PersonSheet id={openId} onClose={() => setOpenId(null)} onChanged={() => { load(); bump() }} show={show} />
      <AddSheet open={adding} onClose={() => setAdding(false)} onAdded={(c) => { setAdding(false); load(); bump(); setOpenId(c.id); show('Записал') }} />
      <Toast msg={msg} />
    </div>
  )
}

function PersonTile({ p, onOpen, delay }) {
  const soon = bdaySoon(p.birthday)
  return (
    <button type="button" onClick={onOpen} className="animate-rise text-left" style={{ animationDelay: `${delay}ms` }}>
      <Card className="h-full transition hover:shadow-[var(--shadow-2)]">
        <div className="flex items-start gap-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-[13px] font-semibold" style={{ background: p.kind === 'person' ? 'var(--accent-soft)' : 'var(--fill-2)', color: p.kind === 'person' ? 'var(--accent)' : 'var(--ink)' }}>{initials(p.name)}</div>
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline justify-between gap-2">
              <div className="truncate text-[15px] font-medium">{p.name}</div>
              <span className="faint shrink-0 text-[11.5px]">{KIND_RU[p.kind] || p.kind}</span>
            </div>
            <div className="muted mt-0.5 truncate text-[12.5px]">{p.aliases ? `он же ${p.aliases}` : p.contact || (p.tags || []).map((t) => `#${t}`).join(' ') || ' '}</div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12px]">
          {p.open > 0 && <span className="badge accent">{p.open} {plural(p.open, 'заказ', 'заказа', 'заказов')} в работе</span>}
          {p.unpaid > 0 && <span className="badge warn">ждём {money(p.unpaid)}</span>}
          {soon != null && <span className="badge pos"><Cake size={11} /> {soon === 0 ? 'др сегодня' : `др через ${soon} ${plural(soon, 'день', 'дня', 'дней')}`}</span>}
          {!p.open && !p.unpaid && soon == null && <span className="faint">{p.last_order ? `последний заказ ${relTime(p.last_order)}` : p.paid ? `всего ${money(p.paid)}` : 'без заказов'}</span>}
        </div>
      </Card>
    </button>
  )
}

/* Карточка человека: сводка → деньги → что дальше → всё остальное. Поля правятся по карандашу. */
function PersonSheet({ id, onClose, onChanged, show }) {
  const [c, setC] = useState(null)
  const [edit, setEdit] = useState(false)
  const [f, setF] = useState({})
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  useEffect(() => { if (!id) { setC(null); setEdit(false); return } api.person(id).then(setC).catch(() => onClose()) }, [id])
  const startEdit = () => { setF({ name: c.name, kind: c.kind || 'person', contact: c.contact || '', notes: c.about || '', aliases: c.aliases || '', birthday: c.birthday || '', tags: (c.tags || []).join(', ') }); setEdit(true) }
  const save = async (e) => {
    e.preventDefault(); setBusy(true)
    try { const r = await api.updatePerson(id, f); setC(r); setEdit(false); onChanged(); show('Сохранено') } catch (er) { show(er.message || 'Не вышло', 'err') } finally { setBusy(false) }
  }
  const ask = (t) => { window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: t } })); onClose() }
  const open = !!id
  return (
    <Sheet open={open} onClose={onClose} wide title={c ? c.name : '…'} sub={c ? [KIND_RU[c.kind] || c.kind, c.aliases && `он же ${c.aliases}`, c.contact, c.last_contact && `последний контакт ${relTime(c.last_contact)}`].filter(Boolean).join(' · ') : ''}>
      {!c ? <Skeleton h={200} /> : edit ? (
        <form onSubmit={save} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="имя"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required autoFocus /></Field>
            <Field label="кто это"><Pills value={f.kind} onChange={(v) => setF({ ...f, kind: v })} options={KIND_OPTS} className="pt-1" /></Field>
            <Field label="ещё зовут" hint="через запятую: Ваня, Иван Петрович"><input className="input" value={f.aliases} onChange={(e) => setF({ ...f, aliases: e.target.value })} placeholder="Ваня" /></Field>
            <Field label="контакт"><input className="input" value={f.contact} onChange={(e) => setF({ ...f, contact: e.target.value })} placeholder="@telegram, телефон" /></Field>
            <Field label="день рождения" hint="12.03 или 1990-03-12"><input className="input" value={f.birthday} onChange={(e) => setF({ ...f, birthday: e.target.value })} placeholder="12.03" /></Field>
            <Field label="теги" hint="через запятую"><input className="input" value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} placeholder="семья, монтаж" /></Field>
          </div>
          <Field label="заметка"><textarea className="input min-h-[80px] resize-none" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="Любит краткость, платит по пятницам…" /></Field>
          <div className="flex justify-end gap-2"><button type="button" className="btn-soft" onClick={() => setEdit(false)}>отмена</button><button className="btn-primary" disabled={busy}><Check size={14} /> сохранить</button></div>
        </form>
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-soft btn-sm" onClick={() => ask(`что по ${c.name}`)}><MessageCircle size={13} /> спросить ассистента</button>
            <button className="btn-soft btn-sm" onClick={startEdit}><Pencil size={13} /> править</button>
            {(c.tags || []).map((t) => <span key={t} className="chip">#{t}</span>)}
          </div>
          {c.about && <p className="text-[14px] leading-relaxed">{c.about}</p>}

          {(c.counts.orders > 0 || c.debts.length > 0) && (
            <div className="grid grid-cols-3 gap-2">
              <Stat label="получено" value={money(c.money.paid)} />
              <Stat label="ждём" value={money(c.money.unpaid)} tone={c.money.unpaid ? 'warn' : undefined} />
              <Stat label="в работе" value={c.money.open} />
            </div>
          )}

          <Block icon={CalendarDays} title="дальше" items={c.upcoming} render={(e) => <Row key={e.id} main={e.title} side={`${shortDate(e.start)} ${hhmm(e.start)}`} onClick={() => nav('/calendar')} />} />
          <Block icon={CheckSquare} title="задачи" items={c.tasks} render={(t) => <Row key={t.id} main={t.title} side={t.due ? shortDate(t.due) : ''} tone={t.due && new Date(t.due) < new Date() ? 'neg' : undefined} onClick={() => nav('/tasks')} />} />
          <Block icon={Briefcase} title={`заказы${c.orders_total > c.orders.length ? ` · ${c.orders_total}` : ''}`} items={c.orders}
            render={(o) => <Row key={o.id} main={o.title} sub={o.status_label + (o.deadline ? ` · до ${shortDate(o.deadline)}` : '')} side={o.unpaid ? `ждём ${money(o.left)}` : money(o.price)} tone={o.unpaid ? 'warn' : undefined} onClick={() => nav('/orders')} />} />
          <Block icon={HandCoins} title="долги" items={c.debts} render={(d) => <Row key={d.id} main={d.title} sub={d.creditor} side={money(d.remaining)} tone="neg" onClick={() => nav('/finance')} />} />
          <Block icon={StickyNote} title="мысли" items={c.notes} render={(n) => <Row key={n.id} main={n.title || n.text} sub={n.title ? n.text : ''} side={relTime(n.created_at)} onClick={() => nav(`/mind?q=${encodeURIComponent(c.name)}`)} />} />
          <Block icon={Link2} title="ссылки" items={c.links} render={(l) => <Row key={l.id} main={l.title || l.url} side={<ExternalLink size={13} />} onClick={() => window.open(l.url, '_blank', 'noopener')} />} />
          {c.past_events?.length > 0 && <Block icon={CalendarDays} title="было" items={c.past_events} render={(e) => <Row key={e.id} main={e.title} side={shortDate(e.start)} dim />} />}
          {c.transactions?.length > 0 && <Block icon={HandCoins} title="деньги вне заказов" items={c.transactions} render={(t) => <Row key={t.id} main={t.note} side={`${t.kind === 'income' ? '+' : '−'}${money(t.amount)}`} tone={t.kind === 'income' ? 'pos' : undefined} dim />} />}
          {!c.upcoming.length && !c.tasks.length && !c.orders.length && !c.debts.length && !(c.links || []).length && !(c.past_events || []).length && (
            <Empty compact glyph="memory" text="Пока только имя" sub="Заказы, встречи и мысли с этим именем появятся здесь сами" hint={`встреча с ${c.name} завтра в 15:00`} onHint={ask} />
          )}
        </div>
      )}
    </Sheet>
  )
}

function Stat({ label, value, tone }) {
  return <div className="rounded-2xl px-3 py-2.5" style={{ background: 'var(--fill)' }}><div className="label">{label}</div><div className={`num mt-0.5 text-[17px] font-medium ${tone === 'warn' ? 'text-[var(--warn)]' : ''}`}>{value}</div></div>
}
function Block({ icon: Icon, title, items, render }) {
  if (!items || !items.length) return null
  return (
    <section>
      <div className="label mb-1.5 flex items-center gap-1.5"><Icon size={12} /> {title}</div>
      <div>{items.map(render)}</div>
    </section>
  )
}
function Row({ main, sub, side, tone, onClick, dim }) {
  const cls = tone === 'neg' ? 'text-[var(--neg)]' : tone === 'warn' ? 'text-[var(--warn)]' : tone === 'pos' ? 'text-[var(--pos)]' : 'muted'
  return (
    <div className={`row row-hover ${onClick ? 'cursor-pointer' : ''} ${dim ? 'opacity-70' : ''}`} onClick={onClick}>
      <div className="min-w-0 flex-1"><div className="truncate text-[14px]">{main}</div>{sub && <div className="muted truncate text-[12px]">{sub}</div>}</div>
      {side && <div className={`num shrink-0 text-[12.5px] ${cls}`}>{side}</div>}
    </div>
  )
}

function AddSheet({ open, onClose, onAdded }) {
  const blank = { name: '', kind: 'person', aliases: '', contact: '', birthday: '', tags: '', notes: '' }
  const [f, setF] = useState(blank)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  useEffect(() => { if (open) { setF(blank); setErr('') } }, [open])
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { onAdded(await api.addPerson(f)) } catch (er) { setErr(er.message || 'Не вышло') } finally { setBusy(false) }
  }
  return (
    <Sheet open={open} onClose={onClose} title="новый человек" sub="или просто скажите ассистенту: «человек: Лена, сестра»">
      <form onSubmit={submit} className="space-y-4">
        <Field label="имя" error={err}><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Лена" required autoFocus /></Field>
        <Field label="кто это"><Pills value={f.kind} onChange={(v) => setF({ ...f, kind: v })} options={KIND_OPTS} className="pt-1" /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="ещё зовут"><input className="input" value={f.aliases} onChange={(e) => setF({ ...f, aliases: e.target.value })} placeholder="Ленка, сестра" /></Field>
          <Field label="день рождения"><input className="input" value={f.birthday} onChange={(e) => setF({ ...f, birthday: e.target.value })} placeholder="12.03" /></Field>
        </div>
        <Field label="заметка"><input className="input" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="сестра, живёт в Питере" /></Field>
        <div className="flex justify-end gap-2"><button type="button" className="btn-soft" onClick={onClose}>отмена</button><button className="btn-primary" disabled={busy || !f.name.trim()}>добавить</button></div>
      </form>
    </Sheet>
  )
}
