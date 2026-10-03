import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Users, Search, CalendarClock } from 'lucide-react'
import { api, money, listOf, shortDate } from '../lib/api'
import { Sheet, Field, Empty, useToast, PageHead, ListSkeleton } from '../components/ui'
import { StatRow } from './Orders'
import { useRefresh } from '../App'
import { usePageAccent } from '../lib/prefs'
import { ClientStageBadge, ClientStageSelect, ClientStageNote } from '../components/ClientStage'
import ClientNextStep from '../components/ClientNextStep'
import { CLIENT_STAGES, CLIENT_STAGE_TONE, clientStageApi, ORDER_STAGE_LABEL, stageOf } from '../lib/crm'
import { useI18n, SERVER, t as T } from '../lib/i18n'

// colleague есть в данных (Дмитрий Соколов) — без него на карточке светилось английское слово.
// Подписи типов — ключи словаря (см. lib/i18n.js)
const KIND_RU = { person: 'people.k_person', family: 'people.k_family', friend: 'people.k_friend', client: 'people.k_client', company: 'people.k_company', colleague: 'people.k_colleague' }
const kindLabel = (p) => p.kind_label || (KIND_RU[p.kind] ? T(KIND_RU[p.kind]) : null) || p.kind || T('people.k_person')
const initials = (name) => (name || '?').split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || '').join('')
// стадия клиента осмысленна только у клиентов и компаний — у «своих» людей её нет
const HAS_STAGE = new Set(['client', 'company'])

/* Стадия клиента и «следующий шаг» — две разные сущности, и берутся они из разных
   ответов: стадия — /api/crm/clients/{id}/stage (там авто-логика по оплатам), шаг — из
   карточки CRM. Один проход по клиентам, порциями по четыре: восемь запросов на порцию
   уходят одновременно, соединения не забиваются. Стадии грузим только для клиентов и
   компаний — у «своих» людей стадии нет. Больше CARD_LIMIT клиентов подряд не тянем. */
const CARD_LIMIT = 60
async function loadPeople(ids) {
  const stages = {}, steps = {}
  const list = [...new Set((ids || []).filter((x) => x != null))].slice(0, CARD_LIMIT)
  for (let i = 0; i < list.length; i += 4) {
    const part = list.slice(i, i + 4)
    await Promise.allSettled(part.flatMap((cid) => [
      clientStageApi.get(cid).then((v) => { stages[cid] = v }).catch(() => {}),
      api.crmClientCard(cid).then((c) => { if (c?.next_step) steps[cid] = { step: c.next_step, at: c.next_step_at } }).catch(() => {}),
    ]))
  }
  return { stages, steps }
}

export default function People() {
  const { t } = useI18n()
  const [list, setList] = useState(null)
  const pageAcc = usePageAccent('people')
  const [q, setQ] = useState('')
  const [tab, setTab] = useState('all')
  const [stageTab, setStageTab] = useState('all')
  const [stages, setStages] = useState({})             // id → стадия клиента (/stage)
  const [steps, setSteps] = useState({})               // id → «следующий шаг» (из карточки CRM)
  const [sheet, setSheet] = useState(null)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()

  const load = () => api.people().then(setList).catch(() => setList([]))
  useEffect(() => { load() }, [tick])

  // стадия клиента и следующий шаг — по одному проходу по клиентам
  useEffect(() => {
    const ids = (list || []).filter((p) => HAS_STAGE.has(p.kind)).map((p) => p.id)
    if (!ids.length) return
    let on = true
    loadPeople(ids).then((m) => { if (on) { setStages(m.stages); setSteps(m.steps) } }).catch(() => {})
    return () => { on = false }
  }, [list])

  const items = useMemo(() => {
    const s = q.trim().toLowerCase()
    return (list || [])
      .filter((p) => tab === 'all' || p.kind === tab)
      .filter((p) => stageTab === 'all' || stages[p.id]?.stage === stageTab)
      .filter((p) => !s || [p.name, p.aliases, p.contact, ...listOf(p.tags)].join(' ').toLowerCase().includes(s))
      .sort((a, b) => (b.open - a.open) || (b.unpaid - a.unpaid) || a.name.localeCompare(b.name, 'ru'))
  }, [list, q, tab, stageTab, stages])

  const stageCount = (k) => (list || []).filter((p) => HAS_STAGE.has(p.kind) && stages[p.id]?.stage === k).length
  const withStages = (list || []).some((p) => HAS_STAGE.has(p.kind))
  const unpaidTotal = (list || []).reduce((s, p) => s + (p.unpaid || 0), 0)
  const openCount = (list || []).filter((p) => p.open).length
  const ordersTotal = (list || []).reduce((s, p) => s + (p.orders || 0), 0)
  const ltvTotal = (list || []).reduce((s, p) => s + (p.paid || 0), 0)

  return (
    <div className="pg on" id="p-ppl" style={pageAcc.style}>
      <PageHead title={T('nav.people')}
        sub={<StatRow items={[
          { key: 'debt', label: t('or.cc_debt'), value: money(unpaidTotal), tone: unpaidTotal ? 'warn' : '' },
          { key: 'orders', label: t('or.cc_orders'), value: ordersTotal },
          { key: 'open', label: t('people.open_orders', { n: openCount }) },
          ltvTotal ? { key: 'ltv', label: 'LTV', value: money(ltvTotal), tone: 'ok' } : null,
        ].filter(Boolean)} />}
        right={<button type="button" className="btn-primary head-primary" onClick={() => setSheet('new')}>{t('people.add')}</button>} />

      {/* Тип контакта — спокойные пилюли с переносом, не одна «таблетка» на семь пунктов */}
      <div className="animate-rise flex flex-wrap items-center gap-1.5" role="group" aria-label={t('people.kind_label')}>
        {[['all', t('common.all')], ...Object.entries(KIND_RU).map(([k, label]) => [k, t(label)])].map(([k, l]) => (
          <button key={k} type="button" className={`pill !min-h-[var(--tap)] ${tab === k ? 'on' : ''}`} aria-pressed={tab === k} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>

      {/* Фильтр по стадии клиента — вторая, отдельная сущность (не стадия заказа) */}
      {withStages && (
        <div className="animate-rise flex flex-wrap items-center gap-1.5" role="group" aria-label={t('cstage.title')}>
          <span className="label mr-1">{t('cstage.title')}</span>
          {CLIENT_STAGES.map(([k, label]) => (
            <button key={k} type="button"
              className={`pill !min-h-[var(--tap)] ${stageTab === k ? 'on' : ''}`}
              aria-pressed={stageTab === k}
              data-tip={t(CLIENT_STAGE_TONE[k] === 'pos' ? 'people.tip_money' : CLIENT_STAGE_TONE[k] === 'neg' ? 'people.tip_risk' : 'people.tip_manual')}
              title={t(CLIENT_STAGE_TONE[k] === 'pos' ? 'people.tip_money' : CLIENT_STAGE_TONE[k] === 'neg' ? 'people.tip_risk' : 'people.tip_manual')}
              onClick={() => setStageTab(stageTab === k ? 'all' : k)}>{t(label)}{stageCount(k) ? ` · ${stageCount(k)}` : ''}</button>
          ))}
        </div>
      )}

      {/* Поиск */}
      <div className="search animate-rise" style={{ width: '100%', height: '54px' }}>
        <Search size={16} aria-hidden />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label={t('people.search_ph')}
          className="min-w-0 flex-1 bg-transparent outline-none"
          style={{ color: 'var(--ink)' }}
          placeholder={t('people.search_ph')}
        />
      </div>

      {/* Список: строки с волосяными разделителями. Разметка <section class="c"> — по ней
          ходят проверки e2e (карточка человека = секция с именем и бейджем стадии). */}
      {list === null ? <ListSkeleton n={6} rowH={62} avatar={false} /> : !items.length ? (
        <Empty
          icon={<Users size={38} />}
          text={t(list?.length ? 'people.none_found' : 'people.none_yet')}
          sub={t(list?.length ? 'people.none_found_hint' : 'people.none_yet_hint')}
        />
      ) : (
        <div className="stagger mt-6">
          {items.map((p) => (
            <PersonRow key={p.id} p={p} stage={stages[p.id]} next={steps[p.id]} onOpen={() => setSheet(p)}
              onStage={(v) => setStages((m) => ({ ...m, [p.id]: v }))}
              onErr={show.err} bump={bump} />
          ))}
        </div>
      )}

      <PersonSheet open={!!sheet} person={sheet} onClose={() => setSheet(null)} onDone={() => { setSheet(null); load(); bump() }} />
    </div>
  )
}

/* Строка человека: имя и тип, ближайший шаг с датой, деньги вторично, справа — стадия
   клиента (бейдж + список). Клик по строке открывает карточку человека шторкой.
   Список стадии стоит в правой колонке шириной меньше половины строки: он не должен
   попадать под клик в centre, который открывает карточку. */
function PersonRow({ p, stage, next, onOpen, onStage, onErr, bump }) {
  const { t } = useI18n()
  const tags = listOf(p.tags)
  const alias = p.aliases
    ? (p.aliases.startsWith(SERVER.alias_she.ru) || p.aliases.startsWith(SERVER.alias_he.ru) ? p.aliases : t('people.also', { names: p.aliases }))
    : tags.map((x) => `#${x}`).join(' ')
  const step = next?.step || ''
  const stepAt = next?.at || null
  const money2 = []
  if (p.unpaid) money2.push(<span key="d" className="warn num">{t('people.awaiting', { m: money(p.unpaid) })}</span>)
  if (p.paid) money2.push(<span key="l" className="faint num">LTV {money(p.paid)}</span>)
  if (p.open) money2.push(<span key="o" className="faint">{t('people.open_in_work', { n: p.open })}</span>)
  return (
    <section
      className="c !rounded-none !p-0 !bg-transparent !shadow-none !transform-none hover:!bg-[var(--fill)] border-b"
      style={{ borderColor: 'var(--line)', cursor: 'pointer' }}
      role="button" tabIndex={0} aria-label={t('people.open_card', { name: p.name })}
      onClick={onOpen}
      onKeyDown={(e) => {
        // Enter/Пробел открывают карточку, но не когда фокус на встроенном списке стадии
        if (e.target !== e.currentTarget && e.target.closest?.('select, input, textarea, button, a')) return
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() }
      }}>
      <div className="grid items-start gap-x-4 gap-y-2 px-1 py-3.5 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="flex min-w-0 items-start gap-3">
          <span className="av2 shrink-0">{initials(p.name)}</span>
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span className="truncate font-medium" style={{ fontSize: 'var(--fs-lg)' }}>{p.name}</span>
              <span className="faint shrink-0" style={{ fontSize: 'var(--fs-xs)' }}>{kindLabel(p)}</span>
              {HAS_STAGE.has(p.kind) && <ClientStageBadge view={stage} className="shrink-0" />}
            </div>
            {alias && <div className="muted truncate text-[12.5px]" title={alias}>{alias}</div>}
            {step && (
              <div className="mt-1 flex min-w-0 flex-wrap items-baseline gap-x-2 text-[12.5px]">
                <CalendarClock size={12} className="faint shrink-0" aria-hidden />
                <span className="truncate" style={{ maxWidth: '48ch' }} title={step}>{step}</span>
                {stepAt && <span className="faint num shrink-0">{shortDate(stepAt)}</span>}
              </div>
            )}
            {money2.length > 0 && <div className="mt-1 flex flex-wrap items-center gap-x-3 text-[12px]">{money2}</div>}
            {/* совсем пустая строка (новый контакт без заказов и без шага) — сказать об этом честно */}
            {!alias && !step && money2.length === 0 && <div className="muted mt-1 text-[12.5px]">{t('people.no_orders')}</div>}
          </div>
        </div>
        {HAS_STAGE.has(p.kind) ? (
          /* Список стадии — в правой колонке шириной меньше половины строки: он не должен
             попадать под клик в центре строки, который открывает карточку человека. */
          <div className="flex min-w-0 items-center gap-2 sm:justify-end" onClick={(e) => e.stopPropagation()}>
            <select className="input !w-full min-w-0 !text-[12.5px] sm:!w-[176px]" value={stage?.stage || 'lead'} disabled={!stage}
              aria-label={t('cstage.for', { name: p.name })} title={t('people.stage_tip')}
              onChange={async (e) => {
                const v = e.target.value
                try { onStage(await clientStageApi.set(p.id, v)); bump() } catch (err) { onErr(err) }
              }}>
              {CLIENT_STAGES.map(([k, l]) => <option key={k} value={k}>{t(l)}</option>)}
            </select>
          </div>
        ) : <div className="sm:justify-self-end" />}
      </div>
    </section>
  )
}

/* Карточка человека — шторка с разделами: контакт, следующий шаг, стадия клиента,
   деньги, заказы, теги. Правка полей контакта и создание нового человека — те же формы,
   что и раньше, просто разложены по разделам с волосяными линиями. */
function PersonSheet({ open, person, onClose, onDone, onDone2 }) {
  const { t } = useI18n()
  const nav = useNavigate()
  const isNew = person === 'new' || !person?.id
  const [name, setName] = useState('')
  const [aliases, setAliases] = useState('')
  const [contact, setContact] = useState('')
  const [kind, setKind] = useState('person')
  const [saving, setSaving] = useState(false)
  const [card, setCard] = useState(null)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setName(isNew ? '' : person?.name || '')
    setAliases(isNew ? '' : person?.aliases || '')
    setContact(isNew ? '' : person?.contact || '')
    setKind(isNew ? 'person' : person?.kind || 'person')
    setCard(null)
  }, [open, person, isNew])

  useEffect(() => {
    if (!open || isNew || !person?.id) return
    let on = true
    api.crmClientCard(person.id).then((r) => { if (on) setCard(r) }).catch(() => { if (on) setCard(null) })
    return () => { on = false }
  }, [open, isNew, person?.id])

  const save = async (e) => {
    if (e) e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      if (isNew) {
        await api.chat(`человек: ${name.trim()}${aliases ? `, ${aliases}` : ''}${contact ? `, ${contact}` : ''}`)   // i18n-raw — фраза для ядра
      } else {
        await api.updatePerson(person.id, { name: name.trim(), aliases: aliases.trim(), contact: contact.trim(), kind })
      }
      onDone()
    } catch (err) {
      show.err(err)
    } finally {
      setSaving(false)
    }
  }

  const Sec = ({ title, children }) => (
    <section className="border-t py-4 first:border-t-0 first:pt-0" style={{ borderColor: 'var(--line)' }}>
      {title && <div className="label mb-2">{title}</div>}
      {children}
    </section>
  )

  return (
    <Sheet open={open} onClose={onClose} title={t(isNew ? 'people.new_title' : 'people.title')}
      sub={isNew ? undefined : kindLabel({ kind: person?.kind })}>
      <form onSubmit={save} className="text-[13px]">
        {isNew ? (
          <div className="space-y-4">
            <Field label={t('common.name')}>
              <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={t('people.name_ph')} />
            </Field>
            <Field label={t('people.alias_label')}>
              <input className="input" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder={t('people.alias_ph')} />
            </Field>
            <Field label={t('people.kind_label')}>
              <KindPills value={kind} onChange={setKind} />
            </Field>
            <Field label={t('people.contact_label')}>
              <input className="input" value={contact} onChange={(e) => setContact(e.target.value)} placeholder={t('people.contact_ph')} />
            </Field>
          </div>
        ) : (
          <>
            {/* Первый раздел без подписи: он и так стоит под заголовком шторки («контакт»). */}
            <Sec>
              <div className="space-y-3">
                <Field label={t('common.name')}>
                  <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={t('people.name_ph')} />
                </Field>
                <Field label={t('people.alias_label')}>
                  <input className="input" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder={t('people.alias_ph')} />
                </Field>
                <Field label={t('people.kind_label')}>
                  <KindPills value={kind} onChange={setKind} />
                </Field>
                {contact !== undefined && (
                  <Field label={t('people.contact_label')}>
                    <input className="input" value={contact} onChange={(e) => setContact(e.target.value)} placeholder={t('people.contact_ph')} />
                  </Field>
                )}
              </div>
            </Sec>

            <Sec title={t('next_step.title')}>
              <ClientNextStep cid={person.id} card={card} onErr={show.err} onSaved={() => api.crmClientCard(person.id).then(setCard).catch(() => {})} />
            </Sec>

            {HAS_STAGE.has(kind) && (
              <Sec title={t('cstage.title')}>
                <ClientStageSelect
                  view={card?.stage}
                  onView={(v) => setCard((c) => ({ ...(c || {}), stage: v }))}
                  onErr={show.err}
                  label={t('cstage.for', { name: person?.name || '' })} />
                <ClientStageNote view={card?.stage} />
              </Sec>
            )}

            {card && (
              <Sec title={t('nav.g_money')}>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
                  <div><div className="label">LTV</div><div className="num mt-0.5 pos" style={{ fontSize: 'var(--fs-lg)' }}>{money(card.ltv || 0)}</div></div>
                  <div><div className="label">{t('or.avg_check')}</div><div className="num mt-0.5" style={{ fontSize: 'var(--fs-lg)' }}>{card.avg_check ? money(card.avg_check) : '—'}</div></div>
                  <div><div className="label">{t('or.cc_debt')}</div><div className={`num mt-0.5 ${card.debt > 0 ? 'warn' : ''}`} style={{ fontSize: 'var(--fs-lg)' }}>{money(card.debt || 0)}</div></div>
                  <div><div className="label">{t('or.cc_orders')}</div><div className="num mt-0.5" style={{ fontSize: 'var(--fs-lg)' }}>{card.orders_count || 0}</div></div>
                </div>
              </Sec>
            )}

            {card?.orders?.length > 0 && (
              <Sec title={t('or.cc_history')}>
                <div className="rule">
                  {card.orders.map((o) => (
                    <button key={o.id} type="button" className="row w-full !py-2 text-left" onClick={() => { onClose(); nav(`/orders?order=${o.id}`) }}>
                      <span className="min-w-0 truncate">{o.title} <span className="faint">· {t(ORDER_STAGE_LABEL[stageOf(o)])}</span></span>
                      <span className="num shrink-0">{o.price ? money(o.price) : '—'}{o.left > 0 ? <span className="faint"> · {t('or.debt', { m: money(o.left) })}</span> : ''}</span>
                    </button>
                  ))}
                </div>
              </Sec>
            )}

            {card?.tags?.length > 0 && (
              <Sec title={t('common.tags')}>
                <div className="flex flex-wrap gap-1.5">{card.tags.map((x) => <span key={x} className="chip on">{x}</span>)}</div>
              </Sec>
            )}
          </>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2 border-t pt-4" style={{ borderColor: 'var(--line)' }}>
          <button type="button" className="btn-ghost mr-auto" onClick={onClose}>{t('common.cancel')}</button>
          <button type="submit" className="btn-primary" disabled={saving || !name.trim()}>{saving ? t('people.saving') : t('common.save')}</button>
        </div>
      </form>
    </Sheet>
  )
}

/* Типы контакта — пилюли с переносом: .sg (одна таблетка) в пять-шесть пунктов не влезает. */
function KindPills({ value, onChange }) {
  const { t } = useI18n()
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('people.kind_label')}>
      {Object.entries(KIND_RU).map(([k, label]) => (
        <button key={k} type="button" className={`pill !min-h-[var(--tap)] ${value === k ? 'on' : ''}`} aria-pressed={value === k} onClick={() => onChange(k)}>{t(label)}</button>
      ))}
    </div>
  )
}