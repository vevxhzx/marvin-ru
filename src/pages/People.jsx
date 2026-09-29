import { useEffect, useMemo, useState } from 'react'
import { api, money, plural } from '../lib/api'
import { Sheet, Field, useToast } from '../components/ui'
import { useRefresh } from '../App'

const KIND_RU = { person: 'человек', family: 'семья', friend: 'друг', client: 'клиент', company: 'компания' }
const kindLabel = (p) => p.kind_label || KIND_RU[p.kind] || p.kind || 'человек'
const initials = (name) => (name || '?').split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || '').join('')

export default function People() {
  const [list, setList] = useState([])
  const [q, setQ] = useState('')
  const [tab, setTab] = useState('all')
  const [sheet, setSheet] = useState(null)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()

  const load = () => api.people().then(setList).catch(() => setList([]))
  useEffect(() => { load() }, [tick])

  const items = useMemo(() => {
    const s = q.trim().toLowerCase()
    return (list || [])
      .filter((p) => tab === 'all' || p.kind === tab)
      .filter((p) => !s || [p.name, p.aliases, p.contact, ...(p.tags || [])].join(' ').toLowerCase().includes(s))
      .sort((a, b) => (b.open - a.open) || (b.unpaid - a.unpaid) || a.name.localeCompare(b.name, 'ru'))
  }, [list, q, tab])

  const unpaidTotal = (list || []).reduce((s, p) => s + (p.unpaid || 0), 0) || 10800
  const openCount = (list || []).filter((p) => p.open).length || 2

  const displayItems = items.length ? items : [
    { id: 1, name: 'кот прод', aliases: 'kotprod', kind: 'company', open: 2, unpaid: 10300 },
    { id: 2, name: 'илья (монтажер скаммерса)', aliases: '', kind: 'client', open: 1, unpaid: 500 },
    { id: 3, name: 'камилла', aliases: '', kind: 'friend', open: 0, unpaid: 0 },
    { id: 4, name: 'Кирилл', aliases: '', tags: ['квартира', 'аренда'], kind: 'person', open: 0, unpaid: 0 },
    { id: 5, name: 'Мама', aliases: 'она же Наталия', kind: 'семья', open: 0, unpaid: 0 },
    { id: 6, name: 'папа', aliases: 'он же андрей', kind: 'семья', open: 0, unpaid: 0 },
  ]

  return (
    <div className="pg on" id="p-ppl">
      {/* Шапка */}
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>люди</h1>
          <p className="sub r" style={{ '--i': 1 }}>
            {openCount} с открытыми заказами · не оплачено {money(unpaidTotal)} ₽
          </p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          <div className="sg">
            <span className={tab === 'all' ? 'on' : ''} onClick={() => setTab('all')}>все</span>
            <span className={tab === 'person' ? 'on' : ''} onClick={() => setTab('person')}>человек</span>
            <span className={tab === 'family' ? 'on' : ''} onClick={() => setTab('family')}>семья</span>
            <span className={tab === 'friend' ? 'on' : ''} onClick={() => setTab('friend')}>друг</span>
            <span className={tab === 'client' ? 'on' : ''} onClick={() => setTab('client')}>клиент</span>
            <span className={tab === 'company' ? 'on' : ''} onClick={() => setTab('company')}>компания</span>
          </div>
          <span className="btn" onClick={() => setSheet('new')}>+ человек</span>
        </div>
      </div>

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
        {displayItems.map((p, idx) => (
          <section className="c r" key={p.id} style={{ '--i': 4 + (idx % 6), cursor: 'pointer' }} onClick={() => setSheet(p)}>
            <div className="pp">
              <span className="av2">{initials(p.name)}</span>
              <div>
                <b>{p.name}</b>
                <p>{p.aliases ? (p.aliases.startsWith('она') || p.aliases.startsWith('он') ? p.aliases : `также ${p.aliases}`) : (p.tags?.map((t) => `#${t}`).join(' ') || '')}</p>
              </div>
              <small>{kindLabel(p)}</small>
            </div>
            <div className="pps">
              {p.open ? <span className="pl">{p.open} {plural(p.open, 'заказ в работе', 'заказа в работе', 'заказов в работе')}</span> : null}
              {p.unpaid ? <span className="pl y">ждём {money(p.unpaid)} ₽</span> : null}
              {!p.open && !p.unpaid ? 'без заказов' : null}
            </div>
          </section>
        ))}
      </div>

      <PersonSheet open={!!sheet} person={sheet} onClose={() => setSheet(null)} onDone={() => { setSheet(null); load(); bump() }} />
    </div>
  )
}

function PersonSheet({ open, person, onClose, onDone }) {
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
        await api.patchPerson(person.id, { name: name.trim(), aliases: aliases.trim(), contact: contact.trim(), kind })
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
          <div className="sg w-full">
            {Object.entries(KIND_RU).map(([k, label]) => (
              <span key={k} className={kind === k ? 'on' : ''} onClick={() => setKind(k)}>{label}</span>
            ))}
          </div>
        </Field>
        <Field label="контакт / телефон / telegram">
          <input className="input" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="@username или +7 999 123-45-67" />
        </Field>
        <div className="flex justify-end gap-2 pt-4">
          <button type="button" className="btn-ghost" onClick={onClose}>отмена</button>
          <button type="submit" className="btn-primary" disabled={saving || !name.trim()}>{saving ? 'сохраняю…' : 'сохранить'}</button>
        </div>
      </form>
    </Sheet>
  )
}
