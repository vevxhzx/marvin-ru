/* mapp/screens/Settings.jsx — мобильные настройки (порт референса screens/Settings.tsx).
 *
 * Данные — только живые: GET /api/settings рядами с IconTile (группа — по префиксу
 * ключа, как разделы десктопных настроек), версия — из /api/status. Bool-ряды
 * переключаются сразу через PUT /api/settings; остальное пока только показывает
 * значение (мобильный редактор — вторая очередь, тап честно говорит об этом).
 */
import { useEffect, useMemo, useState } from 'react'
import { Activity, Brain, ChevronRight, Database, Mic, Plug, User } from 'lucide-react'
import { api } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { Avatar, Card, IconTile, Overline, ScreenTitle, Toggle } from '../ui.jsx'

const cx = (...parts) => parts.filter(Boolean).join(' ')

const GROUPS = [
  { id: 'main', key: 'm.set_g_main', icon: User, color: '#7d95ff', prefixes: ['owner.', 'assistant.', 'persona.', 'finance.'] },
  { id: 'brain', key: 'm.set_g_brain', icon: Brain, color: '#ff8da1', prefixes: ['brain.'] },
  { id: 'voice', key: 'm.set_g_voice', icon: Mic, color: '#3ddc97', prefixes: ['voice.', 'cards.'] },
  { id: 'int', key: 'm.set_g_int', icon: Plug, color: '#5ab8ff', prefixes: ['telegram.', 'google.', 'news.', 'weather.'] },
  { id: 'data', key: 'm.set_g_data', icon: Database, color: '#2bd4c0', prefixes: ['backup.'] },
  { id: 'sys', key: 'm.set_g_sys', icon: Activity, color: '#a9b3e0', prefixes: ['server.'] },
]

const shortVal = (v) => {
  if (v == null) return ''
  const s = String(v)
  return s.length > 26 ? `${s.slice(0, 26)}…` : s
}

/* Человеческое имя настройки: у API есть label, запасной — последний сегмент ключа. */
const prettyKey = (key) => String(key || '').split('.').pop().replace(/_/g, ' ')

/* Основной счёт — выпадашка из живых счетов (флаг is_main в БД, а не строка конфига).
   Выбор сразу пишет флаг и конфиг: мама на телефоне не должна думать про «Сохранить». */
function MMainAccount({ onDone, notify }) {
  const [accs, setAccs] = useState()
  useEffect(() => { api.accounts().then((a) => setAccs(Array.isArray(a) ? a : [])).catch(() => setAccs(null)) }, [])
  if (!Array.isArray(accs)) return null
  const main = accs.find((a) => a.is_main)?.name || ''
  const cur = accs.some((a) => a.name === main) ? main : ''
  const pick = async (name) => {
    const a = accs.find((x) => x.name === name)
    if (!a || a.name === main) return
    try {
      await api.updateAccount(a.id, { is_main: true })
      await api.saveSettings({ 'finance.main_account': a.name })
      onDone()
    } catch (e) {
      notify(String(e?.message || e))
    }
  }
  const fmt = (n) => `${Number(n || 0).toLocaleString('ru-RU')} ₽`
  return (
    <select
      aria-label="main-account"
      value={cur}
      onChange={(e) => pick(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      style={{ colorScheme: 'dark' }}
      className="m-glass max-w-[150px] shrink-0 rounded-xl bg-transparent px-2.5 py-2 text-[13.5px] text-white outline-none"
    >
      {cur === '' && <option value="">—</option>}
      {accs.map((a) => <option key={a.id ?? a.name} value={a.name}>{a.name} · {fmt(a.balance)}</option>)}
    </select>
  )
}

export default function MSettings({ go }) {
  const { t } = useI18n()
  const [items, setItems] = useState(null)
  const [version, setVersion] = useState(null)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState(null)
  const [editKey, setEditKey] = useState(null)
  const [editVal, setEditVal] = useState('')

  const load = () => {
    setErr(null)
    api.settings().then((d) => setItems(d.items || [])).catch(() => setErr(true))
    api.status().then((s) => setVersion(s?.version)).catch(() => {})
  }
  useEffect(() => { load() }, [])

  useEffect(() => {
    if (!note) return
    const id = window.setTimeout(() => setNote(null), 2600)
    return () => window.clearTimeout(id)
  }, [note])

  const groups = useMemo(() => {
    const rest = [...(items || [])]
    const out = []
    for (const g of GROUPS) {
      const rows = rest.filter((it) => g.prefixes.some((p) => it.key.startsWith(p)))
      if (rows.length) out.push({ ...g, rows })
    }
    const used = new Set(out.flatMap((g) => g.rows.map((r) => r.key)))
    const other = rest.filter((it) => !used.has(it.key))
    if (other.length) out.push({ ...GROUPS[0], id: 'other', rows: other })
    return out
  }, [items])

  const startEdit = (it) => {
    if (it.type === 'bool') return
    setEditKey(it.key)
    setEditVal(it.secret ? '' : String(it.value ?? ''))
  }

  const saveEdit = async (it) => {
    let v = editVal
    if (it.type === 'int') {
      v = parseInt(String(v).replace(/[^\d-]/g, ''), 10)
      if (Number.isNaN(v)) { setNote(t('m.bad_number')); return }
    }
    try {
      await api.saveSettings({ [it.key]: v })
      setEditKey(null)
      setNote(t('common.saved'))
      load()
    } catch (e) {
      setNote(String(e?.message || e))
    }
  }
  const flip = async (it) => {
    const next = !it.value
    setItems((list) => (list || []).map((x) => (x.key === it.key ? { ...x, value: next } : x)))
    try {
      await api.saveSettings({ [it.key]: next })
      setNote(t('common.saved'))
    } catch (e) {
      setItems((list) => (list || []).map((x) => (x.key === it.key ? { ...x, value: it.value } : x)))
      setNote(String(e?.message || e))
    }
  }

  if (err) {
    return (
      <div className="px-5 pt-10 text-center">
        <div className="text-[15px] text-white/70">{t('m.load_err')}</div>
        <button className="m-glass mt-3 rounded-full px-4 py-2 text-[13.5px]" onClick={load}>{t('m.retry')}</button>
      </div>
    )
  }
  if (!items) return <div className="px-5 pt-10 text-[15px] text-white/50">{t('m.loading')}</div>

  const name = items.find((x) => x.key === 'owner.name')?.value || t('common.sir')
  const initial = String(name).trim().charAt(0).toUpperCase() || '?'

  return (
    <div data-testid="m-settings">
      <ScreenTitle
        onBack={() => go('more')}
        back={t('common.more')}
        title={t('nav.settings')}
        subtitle={t('m.set_sub')}
      />

      <div className="mt-5 px-4">
        <div className="m-glass flex w-full items-center gap-3.5 rounded-[26px] p-4 text-left">
          <Avatar initials={initial} hue={0} size={54} className="ring-2 ring-white/25" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[18px] font-semibold">{name}</div>
            <div className="text-[13px] text-white/60">{t('m.set_ver', { v: version || '…' })}</div>
          </div>
        </div>
      </div>

      <div className="mt-2 space-y-5 px-4">
        {groups.map((g) => (
          <div key={g.id}>
            <Overline className="mb-2 mt-4 px-3">{t(g.key)}</Overline>
            <Card className="overflow-hidden rounded-[24px]">
              {g.rows.map((r, i) => {
                const editing = editKey === r.key
                const title = r.label || prettyKey(r.key)
                return (
                <div
                  key={r.key}
                  data-testid={`m-set-row-${r.key}`}
                  role="button"
                  tabIndex={0}
                  aria-label={title}
                  onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && r.type !== 'bool' && r.key !== 'finance.main_account' && !editing) { e.preventDefault(); startEdit(r) } }}
                  onClick={() => { if (r.type !== 'bool' && r.key !== 'finance.main_account' && !editing) startEdit(r) }}
                  className={cx(
                    'flex items-center gap-3 px-4 py-3.5 transition active:bg-white/[0.04]',
                    i < g.rows.length - 1 && !editing && 'border-b border-white/[0.06]',
                  )}
                >
                  <IconTile icon={g.icon} color={g.color} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[15.5px] font-medium">{title}</div>
                    <div className="truncate text-[12.5px] text-white/50">{r.key}</div>
                  </div>
                  {r.key === 'finance.main_account' ? (
                    <MMainAccount onDone={load} notify={setNote} />
                  ) : r.type === 'bool' ? (
                    <Toggle on={!!r.value} onChange={() => flip(r)} label={title} />
                  ) : editing ? (
                    <div className="flex min-w-0 shrink-0 items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                      <input
                        autoFocus
                        value={editVal}
                        onChange={(e) => setEditVal(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') saveEdit(r); if (e.key === 'Escape') setEditKey(null) }}
                        type={r.type === 'int' ? 'numeric' : r.secret ? 'password' : 'text'}
                        inputMode={r.type === 'int' ? 'numeric' : undefined}
                        placeholder={r.secret ? t('st.pass_or_token') : shortVal(r.value)}
                        aria-label={title}
                        className="m-glass w-[130px] rounded-xl px-3 py-2 text-[14px] outline-none"
                      />
                      <button
                        aria-label={t('common.save')}
                        onClick={() => saveEdit(r)}
                        className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white/[0.12] text-[15px] transition active:scale-90"
                      >
                        ✓
                      </button>
                    </div>
                  ) : (
                    <div className="flex min-w-0 shrink-0 items-center gap-1.5">
                      <span className="max-w-[120px] truncate text-[13.5px] text-white/50">
                        {r.secret ? '•••' : shortVal(r.value)}
                      </span>
                      <ChevronRight size={17} className="shrink-0 text-white/35" />
                    </div>
                  )}
                </div>
                )
              })}
            </Card>
          </div>
        ))}
      </div>

      {note && (
        <div data-testid="m-set-note" className="anim-toast fixed bottom-24 left-1/2 z-50 -translate-x-1/2 rounded-full border border-white/10 bg-[#121a46]/95 px-4 py-2.5 text-[13.5px] shadow-xl backdrop-blur-xl">
          {note}
        </div>
      )}
    </div>
  )
}
