/* MBrain — мобильный мозг. Живые данные: GET /api/notes + /api/links,
   POST /api/notes (мысль/ссылка авто-типом), POST /api/notes/photo (фото).
   Голосовые бэкенд волной не отдаёт — показываем только длительность, если есть. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUp, Camera, Image, LayoutGrid, Link, Link2, Mic, Play, Rows3, Search } from 'lucide-react'
import { api, listOf, relTime } from '../../lib/api'
import { useI18n } from '../../lib/i18n'
import { Card, Chip, ScreenTitle } from '../ui.jsx'

const URL_RE = /https?:\/\/[^\s]+/
const imgSrc = (s) => (!s ? '' : String(s).startsWith('http') ? String(s) : `/media/${s}`)

export default function MBrain() {
  const { t } = useI18n()
  const [notes, setNotes] = useState(null)
  const [links, setLinks] = useState(null)
  const [err, setErr] = useState(null)
  const [filter, setFilter] = useState('all')
  const [view, setView] = useState('list')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [toastMsg, setToastMsg] = useState(null)
  const photoRef = useRef(null)

  const load = () => {
    setErr(null)
    return Promise.all([
      api.notes().then((n) => setNotes(n || [])).catch(() => setErr(true)),
      api.links().then((l) => setLinks(l || [])).catch(() => {}),
    ])
  }
  useEffect(() => { load() }, [])

  const toast = (msg) => {
    setToastMsg(msg)
    window.clearTimeout(toast._t)
    toast._t = window.setTimeout(() => setToastMsg(null), 3000)
  }

  const items = useMemo(() => {
    const all = [
      ...(notes || []).map((n) => ({ ...n, _t: 'note', kind: n.image ? 'photo' : (n.audio || n.duration ? 'voice' : (/https?:\/\//.test(n.text || '') ? 'link' : 'text')) })),
      ...(links || []).map((l) => ({ ...l, _t: 'link', kind: 'link' })),
    ].sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
    if (filter === 'all') return all
    // i18n-raw: id фильтра — тег из данных пользователя (#идея пишут в мыслях)
    if (filter === '#идея') return all.filter((x) => listOf(x.tags).some((g) => g.toLowerCase().includes('идея'))) // i18n-raw
    return all.filter((x) => x.kind === filter)
  }, [notes, links, filter])
  const total = (notes || []).length + (links || []).length

  const save = async () => {
    const v = text.trim()
    if (!v || busy) return
    setBusy(true)
    try {
      const m = v.match(URL_RE)
      if (m) await api.addLink(m[0], v.replace(m[0], '').trim() || null)
      else await api.addNote(v)
      setText('')
      setFilter('all')
      toast(t('m.saved_brain'))
      load()
    } catch (e) { toast(String(e?.message || e)) } finally { setBusy(false) }
  }

  const onPhoto = async (e) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    try {
      await api.addNotePhoto(f, text.trim())
      setText('')
      toast(t('m.saved_brain'))
      load()
    } catch (er) { toast(String(er?.message || er)) }
  }

  if (err) {
    return (
      <div className="px-5 pt-10 text-center">
        <div className="text-[15px] text-white/70">{t('m.load_err')}</div>
        <button className="m-glass mt-3 rounded-full px-4 py-2 text-[13.5px]" onClick={load}>{t('m.retry')}</button>
      </div>
    )
  }
  if (!notes) return <div className="px-5 pt-10 text-[15px] text-white/50">{t('m.loading')}</div>

  const filters = [
    { id: 'all', label: t('m.fl_all') },
    { id: '#идея', label: t('m.fl_ideas') }, // i18n-raw: id — тег из данных, подпись — ключом
    { id: 'voice', label: t('m.fl_voice') },
    { id: 'link', label: t('m.fl_links') },
    { id: 'photo', label: t('m.fl_photo') },
  ]

  return (
    <div>
      <ScreenTitle
        overline={t('m.second')}
        title={t('m.brain')}
        count={total}
        subtitle={t('m.brain_sub')}
        right={(
          <button aria-label={t('common.search')} onClick={() => toast(t('m.brain_sub'))} className="grid h-10 w-10 place-items-center rounded-full bg-white/[0.07] text-white/70 transition active:scale-90">
            <Search size={18} />
          </button>
        )}
      />

      <div className="mt-5 px-4">
        <div className="m-card rounded-[26px] p-3 transition focus-within:border-[#7d95ff]/40">
          <textarea
            rows={2}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save() } }}
            placeholder={t('m.capture_ph')}
            className="w-full resize-none bg-transparent px-2 pt-1 text-[16px] leading-snug outline-none placeholder:text-white/35"
          />
          <div className="mt-1 flex items-center gap-1">
            <button aria-label={t('m.fl_voice')} onClick={() => toast(t('m.saved_brain'))} className="grid h-10 w-10 place-items-center rounded-full text-white/60 transition active:bg-white/10">
              <Mic size={19} />
            </button>
            <button aria-label={t('m.fl_photo')} onClick={() => photoRef.current?.click()} className="grid h-10 w-10 place-items-center rounded-full text-white/60 transition active:bg-white/10">
              <Camera size={19} />
            </button>
            <input ref={photoRef} type="file" accept="image/*" className="hidden" tabIndex={-1} aria-hidden="true" onChange={onPhoto} />
            <button aria-label={t('m.fl_links')} onClick={save} disabled={!text.trim()} className="grid h-10 w-10 place-items-center rounded-full text-white/60 transition active:bg-white/10 disabled:opacity-40">
              <Link size={19} />
            </button>
            <span className="ml-1 hidden text-[12px] text-white/40 min-[360px]:inline">{t('m.tags_self')}</span>
            <button
              onClick={save}
              disabled={!text.trim() || busy}
              aria-label={t('m.save')}
              className={`ml-auto grid h-11 w-11 place-items-center rounded-full transition${text.trim() ? ' m-fab' : ' bg-white/10 text-white/35'}`}
            >
              <ArrowUp size={20} strokeWidth={2.4} />
            </button>
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2 pr-4">
        <div className="no-scrollbar fade-x flex min-w-0 flex-1 gap-2 overflow-x-auto pl-4 pr-6">
          {filters.map((f) => (
            <Chip key={f.id} active={filter === f.id} onClick={() => setFilter(f.id)}>{f.label}</Chip>
          ))}
        </div>
        <div className="m-glass flex shrink-0 rounded-full p-1">
          {[{ id: 'list', Icon: Rows3 }, { id: 'grid', Icon: LayoutGrid }].map(({ id, Icon }) => (
            <button
              key={id}
              aria-label={id}
              onClick={() => setView(id)}
              className={`grid h-8 w-8 place-items-center rounded-full transition${view === id ? ' m-active text-white' : ' text-white/55'}`}
            >
              <Icon size={15} />
            </button>
          ))}
        </div>
      </div>

      {view === 'list' ? (
        <div key="list" className="anim-rise mt-4 space-y-3 px-4">
          {items.map((n) => <NoteCard key={`${n._t}${n.id}`} n={n} />)}
        </div>
      ) : (
        <div key="grid" className="anim-rise mt-4 columns-2 gap-2.5 px-4">
          {items.map((n) => <NoteTile key={`${n._t}${n.id}`} n={n} />)}
        </div>
      )}
      {items.length === 0 && (
        <div className="px-4"><Card className="px-6 py-10 text-center text-[14px] text-white/55">{t('m.empty_brain')}</Card></div>
      )}

      {toastMsg && (
        <div className="anim-toast fixed bottom-24 left-1/2 z-50 -translate-x-1/2 rounded-full border border-white/10 bg-[#121a46]/95 px-4 py-2.5 text-[13.5px] shadow-xl backdrop-blur-xl">{toastMsg}</div>
      )}
    </div>
  )
}

const titleOf = (n) => n.title || (n.text || n.comment || n.url || '').split('\n')[0].slice(0, 60) || n.url || ''
const bodyOf = (n) => (n._t === 'link' ? (n.comment || n.url || '') : (n.text || n.summary || n.body || ''))

function NoteCard({ n }) {
  const { t } = useI18n()
  const tags = listOf(n.tags)
  return (
    <Card className="p-4">
      <div className="text-[16.5px] font-semibold leading-snug">{titleOf(n)}</div>

      {n.kind === 'text' && bodyOf(n) !== titleOf(n) && (
        <p className="mt-1.5 line-clamp-3 text-[14px] leading-[1.45] text-white/65">{bodyOf(n)}</p>
      )}

      {n.kind === 'voice' && (
        <div className="mt-2.5">
          <div className="flex items-center gap-3 rounded-[18px] bg-white/[0.06] p-2.5 pr-3.5">
            <button aria-label={t('m.fl_voice')} className="m-active grid h-9 w-9 shrink-0 place-items-center rounded-full">
              <Play size={15} fill="white" />
            </button>
            <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-white/15">
              <div className="h-full w-1/4 rounded-full bg-white/70" />
            </div>
            <span className="tnum shrink-0 text-[12px] text-white/55">{n.duration || n.audio_duration || '—'}</span>
          </div>
          {bodyOf(n) ? <p className="mt-2 line-clamp-2 text-[13.5px] italic leading-[1.45] text-white/55">«{bodyOf(n)}»</p> : null}
        </div>
      )}

      {n.kind === 'link' && (
        <a href={n.url} target="_blank" rel="noreferrer" className="mt-2.5 flex items-center gap-3 rounded-[18px] bg-white/[0.06] p-3">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-[12px] bg-gradient-to-br from-[#ffb84d] to-[#ff7eb3] text-[#0e1438]">
            <Link2 size={18} />
          </div>
          <div className="min-w-0">
            <div className="truncate text-[13.5px] font-medium">{n.url}</div>
            <div className="text-[12px] text-white/45">{t('m.link_sub')}{n.domain ? ` · ${n.domain}` : ''}</div>
          </div>
        </a>
      )}

      {n.kind === 'photo' && (
        <div className="mt-2.5">
          {n.image ? (
            <img src={imgSrc(n.image)} alt={titleOf(n)} loading="lazy" className="aspect-[4/3] w-full rounded-[12px] object-cover" />
          ) : (
            <div className="grid aspect-[4/3] place-items-center rounded-[12px]" style={{ background: 'linear-gradient(135deg,#ffb84d55,#7d95ff33)' }}>
              <Image size={20} className="text-white/60" />
            </div>
          )}
          {bodyOf(n) ? <p className="mt-2 text-[13.5px] leading-[1.45] text-white/60">{bodyOf(n)}</p> : null}
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12px] text-white/45">
        <span className="mr-1">{n.created_at ? relTime(n.created_at) : ''}</span>
        {tags.map((g) => (
          <span key={g} className="rounded-full bg-white/[0.07] px-2 py-0.5 text-white/65">#{g}</span>
        ))}
      </div>
    </Card>
  )
}

function NoteTile({ n }) {
  const tags = listOf(n.tags)
  return (
    <Card className="mb-2.5 break-inside-avoid rounded-[22px] p-3.5">
      {n.kind === 'photo' && (
        n.image
          ? <img src={imgSrc(n.image)} alt={titleOf(n)} loading="lazy" className="mb-2.5 aspect-[4/3] w-full rounded-[14px] object-cover" />
          : <div className="mb-2.5 grid aspect-[4/3] place-items-center rounded-[14px]" style={{ background: 'linear-gradient(135deg,#ffb84d55,#7d95ff33)' }}><Image size={20} className="text-white/60" /></div>
      )}
      <div className="text-[14.5px] font-semibold leading-snug">{titleOf(n)}</div>
      {n.kind !== 'photo' && bodyOf(n) !== titleOf(n) && (
        <p className="mt-1.5 line-clamp-4 text-[12.5px] leading-[1.45] text-white/55">{bodyOf(n)}</p>
      )}
      <div className="mt-2 text-[11px] text-white/40">
        {n.created_at ? relTime(n.created_at) : ''}{tags[0] ? ` · #${tags[0]}` : ''}
      </div>
    </Card>
  )
}
