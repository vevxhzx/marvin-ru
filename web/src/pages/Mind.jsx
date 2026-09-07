import { useEffect, useRef, useState } from 'react'
import { Search, Trash2, ExternalLink, Link2, StickyNote, ArrowUp, Sparkles, Quote, ImagePlus, X, Camera } from 'lucide-react'
import { api, relTime } from '../lib/api'
import { Card, Section, Empty, Seg, Pills, useToast, Toast, Skeleton, PageHead, useLeave, Swipe } from '../components/ui'
import { useRefresh } from '../App'

const URL_RE = /https?:\/\/[^\s]+/

export default function Mind() {
  const [tab, setTab] = useState('all')
  const [q, setQ] = useState('')
  const [notes, setNotes] = useState(null)
  const [links, setLinks] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [img, setImg] = useState(null)         // { file, url } — картинка к мысли
  const [zoom, setZoom] = useState(null)       // открытое на весь экран фото
  const fileRef = useRef(null)
  const pickImg = (f) => { if (!f || !f.type.startsWith('image/')) return; if (img) URL.revokeObjectURL(img.url); setImg({ file: f, url: URL.createObjectURL(f) }) }
  const clearImg = () => { if (img) URL.revokeObjectURL(img.url); setImg(null) }
  // вставка картинки из буфера (Ctrl+V скриншота) и перетаскивание файла на страницу
  useEffect(() => {
    const onPaste = (e) => { const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith('image/')); if (f) { e.preventDefault(); pickImg(f) } }
    const onDrop = (e) => { const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith('image/')); if (f) { e.preventDefault(); pickImg(f) } }
    const onDrag = (e) => { if ([...(e.dataTransfer?.types || [])].includes('Files')) e.preventDefault() }
    window.addEventListener('paste', onPaste); window.addEventListener('drop', onDrop); window.addEventListener('dragover', onDrag)
    return () => { window.removeEventListener('paste', onPaste); window.removeEventListener('drop', onDrop); window.removeEventListener('dragover', onDrag) }
  }, [img]) // eslint-disable-line
  const [mode, setMode] = useState('text')     // text | semantic — как искали в последний раз
  const [toast, show] = useToast()
  const [leaveCls, leave] = useLeave()
  const { tick, bump } = useRefresh()

  const load = () => {
    if (q.trim().length >= 3) {
      // смысловой поиск (локальные эмбеддинги Ollama); если модели нет — сервер сам вернёт обычный
      return api.semantic(q, 30).then((r) => {
        setMode(r.mode)
        setNotes(r.items.filter((x) => x.kind === 'note'))
        setLinks(r.items.filter((x) => x.kind === 'link'))
      }).catch(() => Promise.all([api.notes(q), api.links(q)]).then(([n, l]) => { setMode('text'); setNotes(n); setLinks(l) }).catch(() => {}))
    }
    setMode('text')
    return Promise.all([api.notes(q), api.links(q)]).then(([n, l]) => { setNotes(n); setLinks(l) }).catch(() => {})
  }
  useEffect(() => { const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t) }, [q, tick])
  useEffect(() => {
    const pending = (notes || []).some((n) => !n.polished) || (links || []).some((l) => !l.polished)
    if (!pending) return
    const t = setInterval(load, 4000); return () => clearInterval(t)
  }, [notes, links])

  const submit = async (e) => {
    e.preventDefault(); const t = text.trim(); if ((!t && !img) || busy) return
    setBusy(true)
    try {
      const m = !img && t.match(URL_RE)
      if (img) await api.addNotePhoto(img.file, t)
      else if (m) await api.addLink(m[0], t.replace(m[0], '').trim() || null)
      else await api.addNote(t)
      setText(''); clearImg(); show(img ? 'Фото в мозге' : m ? 'Ссылка сохранена' : 'Мысль сохранена'); load(); bump()
    } catch (er) { show(er.message || 'Не вышло', 'err') } finally { setBusy(false) }
  }

  const items = [
    ...(notes || []).map((n) => ({ ...n, _t: 'note' })),
    ...(links || []).map((l) => ({ ...l, _t: 'link' })),
  ].filter((x) => tab === 'all' || (tab === 'photo' ? !!x.image : tab === 'note' ? x._t === 'note' && !x.image : x._t === tab)).sort((a, b) => (mode === 'semantic' && q ? (b.score || 0) - (a.score || 0) : new Date(b.created_at) - new Date(a.created_at)))

  return (
    <div className="space-y-8">
      <PageHead kicker="второй мозг" title="мозг" idx={items.length}
        right={<Pills value={tab} onChange={setTab} options={[['all', 'всё'], ['note', 'мысли'], ['photo', 'фото'], ['link', 'ссылки']]} />} />

      <form onSubmit={submit} className="animate-rise">
        <Card className="!p-2 !rounded-[26px]">
          {img && (
            <div className="relative m-1 mb-0 inline-block animate-rise">
              <img src={img.url} alt="" className="max-h-40 rounded-2xl object-cover" />
              <button type="button" onClick={clearImg} className="absolute -right-2 -top-2 grid h-7 w-7 place-items-center rounded-full shadow" style={{ background: 'var(--ink)', color: 'var(--bg)' }}><X size={13} /></button>
            </div>
          )}
          <div className="flex items-end gap-2">
            <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => { pickImg(e.target.files?.[0]); e.target.value = '' }} />
            <button type="button" title="Добавить фото (или вставьте Ctrl+V / перетащите)" onClick={() => fileRef.current?.click()} className="btn-icon mb-1 shrink-0"><ImagePlus size={16} /></button>
            <textarea value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit(e) }}
              rows={text.split('\n').length > 2 ? 4 : 2} className="input !bg-transparent !border-0 !shadow-none resize-none !px-2" placeholder={img ? 'Подпись к фото (можно без неё)' : 'Мысль, идея, ссылка или фото — как есть, редактор причешет (Ctrl+Enter)'} />
            <button disabled={(!text.trim() && !img) || busy} className="mb-1 grid h-10 w-10 shrink-0 place-items-center rounded-full bg-accent text-white transition active:scale-95 disabled:opacity-40">{busy ? <Sparkles size={16} className="animate-pulse" /> : <ArrowUp size={18} />}</button>
          </div>
        </Card>
      </form>

      <div className="animate-rise relative">
        <Search size={17} className="faint absolute left-4 top-1/2 -translate-y-1/2" />
        <input value={q} onChange={(e) => setQ(e.target.value)} className="input !rounded-full !pl-11 !pr-28" placeholder="Поиск по смыслу: «та статья про сон», «идея для подарка»…" />
        {q.trim().length >= 3 && <span className="label absolute right-4 top-1/2 -translate-y-1/2 !normal-case !tracking-normal">{mode === 'semantic' ? '✦ по смыслу' : 'по словам'}</span>}
      </div>

      {!notes ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"><Skeleton h={140} /><Skeleton h={140} /><Skeleton h={140} /></div>
        : items.length === 0 ? <Card><Empty glyph={q ? 'search' : 'mind'} text={q ? 'Ничего не нашёл' : 'Пока пусто'} hint={q ? undefined : 'мысль: снять ролик про кофе'} sub={q ? '' : 'Напишите мысль или киньте ссылку — сюда или в Telegram'} /></Card> : (
          <div className="columns-1 gap-3 sm:columns-2 lg:columns-3 [&>*]:mb-3 [&>*]:break-inside-avoid">
            {items.map((x) => {
              const k = `${x._t === 'link' ? 'l' : 'n'}${x.id}`
              const del = () => leave(k, 'card', async () => { if (x._t === 'link') await api.delLink(x.id); else await api.delNote(x.id); show('Удалено'); await load() })
              return (
                <Swipe key={k} className="swipe-card" onLeft={del}>
                  {x._t === 'link' ? <LinkCard l={x} onTag={setQ} extra={leaveCls(k)} onDel={del} /> : <NoteCard n={x} onTag={setQ} extra={leaveCls(k)} onDel={del} onZoom={setZoom} />}
                </Swipe>
              )
            })}
          </div>
        )}
      {zoom && (
        <div className="fixed inset-0 z-[110] grid place-items-center p-3" style={{ background: 'rgba(0,0,0,.86)', animation: 'fade .18s ease-out' }} onClick={() => setZoom(null)}>
          <img src={zoom} alt="" className="max-h-full max-w-full rounded-2xl object-contain" style={{ animation: 'rise .3s var(--ease-out)' }} />
          <button className="absolute right-4 top-4 grid h-10 w-10 place-items-center rounded-full bg-white/15 text-white safe-t"><X size={18} /></button>
        </div>
      )}
      <Toast msg={toast.msg} kind={toast.kind} />
    </div>
  )
}

function NoteCard({ n, onDel, onTag, onZoom, extra = '' }) {
  const [showRaw, setShowRaw] = useState(false)
  const [related, setRelated] = useState(null)   // null — не запрашивали, [] — нет
  const hasRaw = n.raw && n.raw.trim() !== n.text.trim()
  const loadRelated = () => { if (related === null) api.get(`/api/notes/${n.id}/related`).then(setRelated).catch(() => setRelated([])) }
  return (
    <Card lift className={`group animate-rise ${n.image ? '!pt-0 !px-0 overflow-hidden' : ''} ${extra}`} onMouseEnter={loadRelated}>
      {n.image && <img src={`/media/${n.image}`} alt="" loading="lazy" className="mb-3 w-full cursor-zoom-in object-cover max-h-72" onClick={() => onZoom?.(`/media/${n.image}`)} />}
      <div className={n.image ? 'px-5' : ''}>
      {n.title && <div className="h3 mb-1.5 leading-snug">{n.title}</div>}
      {(showRaw ? n.raw : n.text) !== 'Фото' && <div className="whitespace-pre-wrap text-[15px] leading-relaxed">{(showRaw ? n.raw : n.text).replace(/^📷 /m, '')}</div>}
      {related?.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5 animate-rise">
          <span className="faint text-[11px]">связано:</span>
          {related.map((r) => <button key={`${r.kind}${r.id}`} onClick={() => onTag(r.title || (r.text || '').slice(0, 30))} className="chip !py-0.5 max-w-[200px] truncate !text-[11px] hover:text-accent" title={r.text || r.title}>{r.kind === 'link' ? '🔗 ' : ''}{r.title || (r.text || '').slice(0, 40)}</button>)}
        </div>
      )}
      {!n.polished && <div className="mt-2 flex items-center gap-1.5 text-[11px] text-orange"><Sparkles size={11} /> ждёт редактора</div>}
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {n.image ? <Camera size={13} className="faint" /> : <StickyNote size={13} className="faint" />}
        <span className="faint text-[12px]">{relTime(n.created_at)}</span>
        {n.score != null && n.score < 1 && <span className="label !text-[10px] text-accent">✦ {Math.round(n.score * 100)}%</span>}
        {n.tags && n.tags.split(',').filter(Boolean).map((t) => <button key={t} onClick={() => onTag(t)} className="chip !py-0.5 !text-[11px] hover:text-accent">#{t}</button>)}
        <span className="ml-auto flex items-center gap-1">
          {hasRaw && <button onClick={() => setShowRaw(!showRaw)} title={showRaw ? 'Показать отредактированный' : 'Показать оригинал'} className={`btn-icon !h-7 !w-7 ${showRaw ? '!bg-accent !text-white' : 'opacity-0 group-hover:opacity-100'} transition`}><Quote size={12} /></button>}
          <button onClick={onDel} className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100"><Trash2 size={13} /></button>
        </span>
      </div>
      </div>
    </Card>
  )
}

function LinkCard({ l, onDel, onTag, extra = '' }) {
  const [imgOk, setImgOk] = useState(!!l.image)
  return (
    <Card lift className={`group animate-rise !p-0 overflow-hidden ${extra}`}>
      <a href={l.url} target="_blank" rel="noreferrer" className="block">
        {imgOk && <img src={l.image} alt="" onError={() => setImgOk(false)} className="aspect-video w-full object-cover" loading="lazy" />}
        <div className="p-4">
          <div className="faint mb-1 flex items-center gap-1.5 text-[12px]"><Link2 size={12} />{l.domain}</div>
          <div className="line-clamp-2 text-[15px] font-semibold leading-snug">{l.title || l.url}</div>
          {l.description && !l.summary && <div className="muted mt-1 line-clamp-2 text-[13px]">{l.description}</div>}
          {l.summary && <div className="mt-2 whitespace-pre-wrap rounded-xl fill px-3 py-2 text-[13px] leading-relaxed"><span className="label !text-[10px] text-accent">✦ выжимка</span><br />{l.summary}</div>}
          {l.comment && <div className="mt-2 rounded-xl fill px-3 py-2 text-[13px]">💬 {l.comment}</div>}
        </div>
      </a>
      <div className="flex flex-wrap items-center gap-1.5 px-4 pb-3">
        <span className="faint text-[12px]">{relTime(l.created_at)}</span>
        {l.score != null && l.score < 1 && <span className="label !text-[10px] text-accent">✦ {Math.round(l.score * 100)}%</span>}
        {l.tags && l.tags.split(',').filter(Boolean).map((t) => <button key={t} onClick={() => onTag(t)} className="chip !py-0.5 !text-[11px] hover:text-accent">#{t}</button>)}
        <a href={l.url} target="_blank" rel="noreferrer" className="btn-icon !h-7 !w-7 ml-auto"><ExternalLink size={13} /></a>
        <button onClick={onDel} className="btn-icon !h-7 !w-7 opacity-0 transition group-hover:opacity-100"><Trash2 size={13} /></button>
      </div>
    </Card>
  )
}
