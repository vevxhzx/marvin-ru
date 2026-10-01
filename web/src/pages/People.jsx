import { useEffect, useMemo, useState } from 'react'
import { Users } from 'lucide-react'
import { api, money, plural, listOf } from '../lib/api'
import { Sheet, Field, Empty, useToast, PageAccent, ListSkeleton } from '../components/ui'
import { ClientCardSheet } from './Orders'
import { useRefresh } from '../App'
import { usePageAccent } from '../lib/prefs'
import { ClientStageBadge } from '../components/ClientStage'
import ClientNextStep from '../components/ClientNextStep'
import { CLIENT_STAGES, CLIENT_STAGE_TONE, clientStageApi, loadClientStages } from '../lib/crm'

// colleague есть в данных (Дмитрий Соколов) — без него на карточке светилось английское слово
const KIND_RU = { person: 'человек', family: 'семья', friend: 'друг', client: 'клиент', company: 'компания', colleague: 'коллега' }
const kindLabel = (p) => p.kind_label || KIND_RU[p.kind] || p.kind || 'человек'
const chip = (on) => ({ background: on ? 'var(--ink)' : 'var(--sf)', color: on ? 'var(--bg)' : 'var(--ink2)' })
const initials = (name) => (name || '?').split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || '').join('')
// стадия клиента осмысленна только у клиентов и компаний — у «своих» людей её нет
const HAS_STAGE = new Set(['client', 'company'])

export default function People() {
  const [list, setList] = useState(null)
  const pageAcc = usePageAccent('people')
  const [q, setQ] = useState('')
  const [tab, setTab] = useState('all')
  const [stageTab, setStageTab] = useState('all')
  const [stages, setStages] = useState({})          // id → ответ /api/crm/clients/{id}/stage
  const [sheet, setSheet] = useState(null)
  const [crm, setCrm] = useState(null)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()

  const load = () => api.people().then(setList).catch(() => setList([]))
  useEffect(() => { load() }, [tick])

  // стадия клиента — отдельная сущность и отдельный эндпоинт: тянем по одному запросу на клиента
  useEffect(() => {
    const ids = (list || []).filter((p) => HAS_STAGE.has(p.kind)).map((p) => p.id)
    if (!ids.length) return
    let on = true
    loadClientStages(ids).then((m) => { if (on) setStages(m) }).catch(() => {})
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

  return (
    <div className="pg on" id="p-ppl" style={pageAcc.style}>
      {/* Шапка */}
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>люди</h1>
          <p className="sub r" style={{ '--i': 1 }}>
            {openCount} с открытыми заказами · не оплачено {money(unpaidTotal)}
          </p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          {/* переносимые «пилюли», а не .sg: шесть-семь пунктов в одну таблетку
              не влезали и превращались в странную пустую подложку */}
          <div className="flex flex-wrap gap-2">
            <button type="button" style={chip(tab === 'all')} className="rounded-full px-3.5 py-2 text-[13.5px] font-medium transition" onClick={() => setTab('all')}>все</button>
            {Object.entries(KIND_RU).map(([k, label]) => (
              <button type="button" key={k} style={chip(tab === k)} className="rounded-full px-3.5 py-2 text-[13.5px] font-medium transition" onClick={() => setTab(k)}>{label}</button>
            ))}
          </div>
          <span className="btn" onClick={() => setSheet('new')}>+ человек</span>
        </div>
      </div>

      {/* Фильтр по стадии клиента — вторая, отдельная сущность (не стадия заказа) */}
      {withStages && (
        <div className="r flex flex-wrap items-center gap-2" style={{ '--i': 2, marginTop: '14px' }}>
          <span className="label">стадия клиента</span>
          <button type="button" style={chip(stageTab === 'all')} className="rounded-full px-3 py-1.5 text-[12.5px] font-medium transition" onClick={() => setStageTab('all')}>все</button>
          {CLIENT_STAGES.map(([k, label]) => (
            <button key={k} type="button" style={chip(stageTab === k)} className="rounded-full px-3 py-1.5 text-[12.5px] font-medium transition"
              data-tip={CLIENT_STAGE_TONE[k] === 'pos' ? 'деньги есть' : CLIENT_STAGE_TONE[k] === 'neg' ? 'риск / ушёл' : 'стадия ставится и вручную'}
              onClick={() => setStageTab(stageTab === k ? 'all' : k)}>{label}{stageCount(k) ? ` · ${stageCount(k)}` : ''}</button>
          ))}
        </div>
      )}

      {/* Поиск */}
      <div className="search r" style={{ width: '100%', height: '54px', marginTop: '16px', '--i': 3 }}>
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <circle cx="9" cy="9" r="6" />
          <path d="m14 14 3.5 3.5" />
        </svg>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ background: 'transparent', border: 0, outline: 'none', width: '100%', color: 'inherit', font: 'inherit', marginLeft: '8px' }}
          placeholder="имя, прозвище, тег, контакт…"
        />
      </div>

      {/* Сетка карточек людей */}
      <div className="ppl" style={{ marginTop: '28px' }}>
        {list === null ? <ListSkeleton n={6} /> : !items.length ? (
          <Empty
            icon={<Users size={38} />}
            text={list?.length ? 'Никого не нашлось' : 'Никого пока нет'}
            sub={list?.length ? 'Попробуйте другой запрос или другую вкладку' : 'Добавьте человека кнопкой «+ человек» или скажите в чате «человек: …»'}
          />
        ) : items.map((p, idx) => (
          <section className="c r" key={p.id} style={{ '--i': 4 + (idx % 6), cursor: 'pointer' }} onClick={() => setSheet(p)}>
            <div className="pp">
              <span className="av2">{initials(p.name)}</span>
              <div>
                <b>{p.name}</b>
                <p>{p.aliases ? (p.aliases.startsWith('она') || p.aliases.startsWith('он') ? p.aliases : `также ${p.aliases}`) : (listOf(p.tags).map((t) => `#${t}`).join(' ') || '')}</p>
              </div>
              <small>{kindLabel(p)}</small>
            </div>
            <div className="pps">
              {p.open ? <span className="pl">{p.open} {plural(p.open, 'заказ в работе', 'заказа в работе', 'заказов в работе')}</span> : null}
              {p.unpaid ? <span className="pl y">ждём {money(p.unpaid)}</span> : null}
              {!p.open && !p.unpaid ? 'без заказов' : null}
            </div>
            {HAS_STAGE.has(p.kind) && (
              <div className="mt-2 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                <ClientStageBadge view={stages[p.id]} className="shrink-0" />
                <select className="input !h-7 flex-1 !text-[12px]" value={stages[p.id]?.stage || 'lead'} disabled={!stages[p.id]}
                  aria-label={`Стадия клиента: ${p.name}`} title="стадия клиента — ставится вручную или сама по оплатам"
                  onChange={async (e) => {
                    const v = e.target.value
                    try { const nv = await clientStageApi.set(p.id, v); setStages((m) => ({ ...m, [p.id]: nv })); bump() } catch (err) { show.err(err) }
                  }}>
                  {CLIENT_STAGES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </div>
            )}
          </section>
        ))}
      </div>

      <PersonSheet open={!!sheet} person={sheet} onClose={() => setSheet(null)} onDone={() => { setSheet(null); load(); bump() }}
        onCrm={(id) => { setSheet(null); setCrm(id) }} />
      <ClientCardSheet cid={crm} onClose={() => setCrm(null)} onOrder={() => setCrm(null)} />
    </div>
  )
}

function PersonSheet({ open, person, onClose, onDone, onCrm }) {
  const isNew = person === 'new' || !person?.id
  const [name, setName] = useState('')
  const [aliases, setAliases] = useState('')
  const [contact, setContact] = useState('')
  const [kind, setKind] = useState('person')
  const [saving, setSaving] = useState(false)
  const [, show] = useToast()

  useEffect(() => {
    if (!open) return
    setName(isNew ? '' : person?.name || '')
    setAliases(isNew ? '' : person?.aliases || '')
    setContact(isNew ? '' : person?.contact || '')
    setKind(isNew ? 'person' : person?.kind || 'person')
  }, [open, person, isNew])

  const save = async (e) => {
    if (e) e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      if (isNew) {
        await api.chat(`человек: ${name.trim()}${aliases ? `, ${aliases}` : ''}${contact ? `, ${contact}` : ''}`)
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

  return (
    <Sheet open={open} onClose={onClose} title={isNew ? 'новый контакт' : 'контакт'}>
      <form onSubmit={save} className="space-y-4">
        <Field label="имя">
          <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Иван Васильев" />
        </Field>
        <Field label="псевдоним / также">
          <input className="input" value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="Ваня, ivan_dev" />
        </Field>
        <Field label="тип контакта">
          {/* обычные «пилюли» с переносом: .sg — это одна кнопка-таблетка, в неё
              пять пунктов не влезают и получалась странная пустая подложка */}
          <div className="flex flex-wrap gap-2">
            {Object.entries(KIND_RU).map(([k, label]) => (
              <button type="button" key={k} onClick={() => setKind(k)}
                className="rounded-full px-3.5 py-2 text-[13.5px] font-medium transition"
                style={chip(kind === k)}>
                {label}
              </button>
            ))}
          </div>
        </Field>
        <Field label="контакт / телефон / telegram">
          <input className="input" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="@username или +7 999 123-45-67" />
        </Field>
        {!isNew && (
          <ClientNextStep cid={person.id} />
        )}
        {!isNew && HAS_STAGE.has(kind) && (
          <div className="muted text-[12.5px]">
            Стадия клиента (лид → переговоры → клиент → постоянный → спит/ушёл) — отдельная вещь от стадии заказа:
            меняется сама по оплатам, вручную её меняют в карточке CRM.
          </div>
        )}
        <div className="flex justify-end gap-2 pt-4">
          {!isNew && <button type="button" className="btn-soft mr-auto" onClick={() => onCrm?.(person.id)}>карточка CRM</button>}
          <button type="button" className="btn-ghost" onClick={onClose}>отмена</button>
          <button type="submit" className="btn-primary" disabled={saving || !name.trim()}>{saving ? 'сохраняю…' : 'сохранить'}</button>
        </div>
      </form>
    </Sheet>
  )
}