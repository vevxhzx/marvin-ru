import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, FileText, Link2, History, CheckSquare, CornerDownLeft } from 'lucide-react'
import { api } from '../lib/api'
import { useI18n } from '../lib/i18n'
import DialogShell from './Dialog'

/* Общий поиск: одно поле ищет сразу по Мозгу (заметки/ссылки — семантика с
   откатом на обычный поиск), Памяти (факты — ?q на бэке) и задачам
   (существующий GET /api/tasks?all=true, фильтр по подстроке — на клиенте,
   отдельного поискового эндпоинта задач на бэке нет и заводить его ради
   одного поля не стали). Результаты — группами, клик/Enter — переход к записи.

   Ctrl+K уже занят командной палитрой (App.jsx HOTKEYS), поэтому свой
   глобальный хендлер сюда не вешаем: диалог открывает владелец (сейчас —
   страница «Мозг»: кнопка + Ctrl+K через capture на document, палитра на
   остальных страницах не тронута). Снаружи открывается событием 'omni:open'
   — будущий mount в AppShell сведётся к одной строке. */
export const openOmniSearch = () => window.dispatchEvent(new CustomEvent('omni:open'))

const norm = (s) => String(s || '').toLowerCase().replace(/ё/g, 'е' /* i18n-raw */)
const MIN_Q = 2
const PER_GROUP = 8

export default function OmniSearch({ open, onClose }) {
  const { t } = useI18n()
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const [busy, setBusy] = useState(false)
  const [brain, setBrain] = useState([])
  const [mem, setMem] = useState([])
  const [tasks, setTasks] = useState([])
  const inp = useRef(null)
  const list = useRef(null)
  const nav = useNavigate()

  useEffect(() => {
    if (open) {
      setQ(''); setSel(0); setBrain([]); setMem([]); setTasks([]); setBusy(false)
      setTimeout(() => inp.current?.focus(), 30)
    }
  }, [open ])

  useEffect(() => {
    const qq = q.trim()
    if (!open || qq.length < MIN_Q) { setBrain([]); setMem([]); setTasks([]); setBusy(false); return }
    let alive = true
    const timer = setTimeout(async () => {
      setBusy(true)
      const mindP = api.semantic(qq, 12).then((r) => r.items || []).catch(() =>
        Promise.all([api.notes(qq), api.links(qq)])
          .then(([n, l]) => [...(n || []).map((x) => ({ ...x, kind: 'note' })), ...(l || []).map((x) => ({ ...x, kind: 'link' }))])
          .catch(() => []))
      const memP = api.facts(null, qq).then((r) => r.items || []).catch(() => [])
      const taskP = api.tasks(true)
        .then((ts) => (ts || [])
          .filter((x) => x && norm(x.title).includes(norm(qq)))
          .sort((a, b) => Number(!!a.done) - Number(!!b.done))
          .slice(0, PER_GROUP))
        .catch(() => [])
      const [b, m, ts] = await Promise.all([mindP, memP, taskP])
      if (!alive) return
      setBrain(b.slice(0, PER_GROUP)); setMem(m.slice(0, PER_GROUP)); setTasks(ts)
      setBusy(false)
    }, 250)
    return () => { alive = false; clearTimeout(timer) }
  }, [q, open])

  const rows = useMemo(() => {
    const out = []
    for (const f of brain) out.push({ key: `brain-${f.kind}-${f.id}`, group: 'omni.brain', label: f.title || f.text || f.comment || f.url || '', hint: f.kind === 'link' ? (f.domain || t('common.link')) : t('common.note'), icon: f.kind === 'link' ? Link2 : FileText, item: f, kind: 'brain' })
    for (const f of mem) out.push({ key: `mem-fact-${f.id}`, group: 'omni.memory', label: f.text || '', hint: f.category || t('nav.memory'), icon: History, item: f, kind: 'mem' })
    for (const x of tasks) out.push({ key: `task-${x.id}`, group: 'omni.tasks', label: x.title || '', hint: x.done ? t('common.done') : t('nav.tasks'), icon: CheckSquare, item: x, kind: 'task' })
    return out
  }, [brain, mem, tasks, t])

  useEffect(() => { setSel(0) }, [q])
  useEffect(() => { list.current?.querySelector(`[data-i="${sel}"]`)?.scrollIntoView({ block: 'nearest' }) }, [sel])

  const run = (row) => {
    if (!row) return
    onClose?.()
    if (row.kind === 'brain') {
      const seed = String(row.item.title || row.item.text || row.item.comment || row.item.url || '').slice(0, 60)
      nav(`/mind${seed.trim() ? `?q=${encodeURIComponent(seed.trim())}` : ''}`)
    } else if (row.kind === 'mem') {
      nav('/memory')
    } else if (row.kind === 'task') {
      nav('/tasks')
    }
  }

  useEffect(() => {
    if (!open) return
    const h = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose?.() }
      else if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(rows.length - 1, s + 1)) }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(0, s - 1)) }
      else if (e.key === 'Enter') { e.preventDefault(); run(rows[sel]) }
    }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  }, [open, rows, sel]) // eslint-disable-line

  if (!open) return null
  const searched = q.trim().length >= MIN_Q
  const empty = searched && !busy && !rows.length
  let lastGroup = null
  return (
    <DialogShell onClose={onClose} label={t('omni.title')} testId="omni-dialog">
        <div className="hair flex items-center gap-3 border-b px-4">
          <Search size={16} className="faint shrink-0" aria-hidden="true" />
          <input ref={inp} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('omni.ph')} aria-label={t('omni.ph')}
            data-testid="omni-input"
            className="w-full bg-transparent outline-none placeholder:text-[var(--ink-3)]" style={{ height: 52, fontSize: 'var(--fs-base)' }} />
          <span className="kbd" aria-hidden="true">esc</span>
        </div>
        <div ref={list} className="scroll-thin min-h-0 flex-1 overflow-y-auto py-1.5">
          {rows.map((row, i) => {
            const I = row.icon
            const head = row.group !== lastGroup ? (lastGroup = row.group, t(row.group)) : null
            return (
              <div key={row.key}>
                {head && <div className="label px-4 pb-1 pt-2.5">{head}</div>}
                <button type="button" data-i={i} data-testid={row.key} onMouseMove={() => sel !== i && setSel(i)} onClick={() => run(row)} title={row.label}
                  aria-selected={i === sel}
                  className={`mx-1.5 flex min-h-[var(--tap)] w-[calc(100%-12px)] items-center gap-3 rounded-xl px-2.5 text-left transition-colors ${i === sel ? 'fill' : ''}`}>
                  <span aria-hidden="true" className={`grid h-6 w-6 shrink-0 place-items-center rounded-md ${i === sel ? 'text-accent' : 'muted'}`}><I size={15} /></span>
                  <span className="min-w-0 flex-1 truncate" style={{ fontSize: 'var(--fs-base)' }}>{String(row.label).slice(0, 140)}</span>
                  <span className="faint shrink-0 truncate" style={{ fontSize: 'var(--fs-xs)' }}>{String(row.hint).slice(0, 40)}</span>
                  {i === sel && <CornerDownLeft size={12} className="faint shrink-0" aria-hidden="true" />}
                </button>
              </div>
            )
          })}
          {empty && <p className="muted px-4 py-8 text-center text-[14px]" data-testid="omni-empty">{t('omni.empty')}</p>}
          {!searched && <p className="faint px-4 py-8 text-center text-md">{t('omni.ph')}</p>}
        </div>
        <div className="faint hair flex items-center justify-between gap-3 border-t px-4 py-2" style={{ fontSize: 'var(--fs-xs)' }}>
          <span className="truncate"><span className="kbd">↑↓</span> {t('pal.pick')} · <span className="kbd">↵</span> {t('pal.run')}</span>
          <span className="truncate">{t('omni.title')}</span>
        </div>
    </DialogShell>
  )
}
