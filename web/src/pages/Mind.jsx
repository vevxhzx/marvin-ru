import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Pencil, Trash2 } from 'lucide-react'
import Graph from '../components/Graph'
import { api, relTime, listOf } from '../lib/api'
import { useToast, PageAccent, Empty, ListSkeleton, Sheet, Field, Confirm } from '../components/ui'
import { useRefresh } from '../App'
import { usePageAccent } from '../lib/prefs'
import { useI18n } from '../lib/i18n'

const URL_RE = /https?:\/\/[^\s]+/
const TABS = ['all', 'note', 'photo', 'link', 'graph']

export default function Mind() {
  const { t } = useI18n()
  const [params, setParams] = useSearchParams()
  const pageAcc = usePageAccent('mind')
  const [tab, setTab] = useState(() => (TABS.includes(params.get('tab')) ? params.get('tab') : 'all'))
  const [q, setQ] = useState(() => params.get('q') || '')
  const [notes, setNotes] = useState([])
  const [links, setLinks] = useState([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  // правка и удаление записи (сами записи храним, пока шторка закрывается — иначе заголовок мигает)
  const [edit, setEdit] = useState(null)
  const [editOpen, setEditOpen] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editText, setEditText] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editBusy, setEditBusy] = useState(false)
  const [askDel, setAskDel] = useState(null)
  const [askOpen, setAskOpen] = useState(false)
  // правка заметки нейронкой: было/стало + история версий (только заметки, ссылки не трогаем)
  const [pol, setPol] = useState(null)         // { note, mode, original, polished, hist, tab }
  const [polOpen, setPolOpen] = useState(false)
  const [polBusy, setPolBusy] = useState('')   // '' | rewrite | expand | apply | revert
  const [hist, setHist] = useState([])
  const [histNote, setHistNote] = useState(null)
  const [histOpen, setHistOpen] = useState(false)
  const [histSel, setHistSel] = useState(null)
  const [histBusy, setHistBusy] = useState(false)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()

  const load = () => {
    const p = q.trim().length >= 3
      ? api.semantic(q, 30).then((r) => {
          setNotes(r.items.filter((x) => x.kind === 'note'))
          setLinks(r.items.filter((x) => x.kind === 'link'))
        }).catch(() => Promise.all([api.notes(q), api.links(q)]).then(([n, l]) => { setNotes(n || []); setLinks(l || []) }).catch(() => {}))
      : Promise.all([api.notes(q), api.links(q)]).then(([n, l]) => { setNotes(n || []); setLinks(l || []) }).catch(() => {})
    return p.finally(() => setLoaded(true))
  }

  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0)
    return () => clearTimeout(t)
  }, [q, tick])

  // вкладка и поиск живут в адресе: ссылку можно кинуть, reload ничего не теряет
  useEffect(() => {
    const next = new URLSearchParams(params)
    if (tab === 'all') next.delete('tab'); else next.set('tab', tab)
    if (q) next.set('q', q); else next.delete('q')
    if (next.toString() !== params.toString()) setParams(next, { replace: true })
  }, [tab, q, params, setParams])

  // Правка записи: у заметки — текст/заголовок/теги, у ссылки — заголовок/комментарий/теги
  // (сам адрес ссылки бэкенд править не даёт — PUT /api/links/{id} принимает только title/comment/tags)
  const startEdit = (it) => {
    setEdit(it)
    setEditTitle(it.title || '')
    setEditText(it._t === 'note' ? (it.text || '') : (it.comment || ''))
    setEditTags(listOf(it.tags).join(', '))
    setEditOpen(true)
  }

  const saveEdit = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    if (editBusy || !edit) return
    const body = editTags.split(',').map((s) => s.trim().replace(/^#/, '')).filter(Boolean)
    if (edit._t === 'note' && !editText.trim()) return
    setEditBusy(true)
    try {
      if (edit._t === 'note') await api.editNote(edit.id, { text: editText.trim(), title: editTitle.trim(), tags: body })
      else await api.editLink(edit.id, { title: editTitle.trim(), comment: editText.trim(), tags: body })
      show(t('mind.entry_updated'))
      setEditOpen(false)
      load()
      bump()
    } catch (er) {
      show.err(er)
    } finally {
      setEditBusy(false)
    }
  }

  const doDel = async () => {
    const it = askDel
    setAskOpen(false)
    if (!it) return
    try {
      if (it._t === 'note') await api.delNote(it.id)
      else await api.delLink(it.id)
      show(t(it._t === 'note' ? 'mind.note_deleted' : 'mind.link_deleted'))
      load()
      bump()
    } catch (er) {
      show.err(er)
    }
  }

  // ✨ правка нейронкой: сервер только ПРЕДЛАГАЕТ текст, применяем сами (иначе «было» не вернуть)
  const runPolish = async (it, mode) => {
    if (polBusy || !it || it._t !== 'note') return
    setPolBusy(mode)
    try {
      const r = await api.post(`/api/mind/notes/${it.id}/polish`, { mode })
      const revs = await api.get(`/api/mind/notes/${it.id}/revisions`).catch(() => [])
      setPol({ note: it, mode, original: r.original, polished: r.polished, hist: revs || [], tab: 'after' })
      setPolOpen(true)
    } catch (er) {
      show.err(er)   // 503 от сервера (LLM недоступна) — текст ошибки уходит в тост как есть
    } finally {
      setPolBusy('')
    }
  }

  const applyPol = async () => {
    if (!pol || polBusy || !pol.polished.trim()) return
    setPolBusy('apply')
    try {
      await api.post(`/api/mind/notes/${pol.note.id}/apply`, { text: pol.polished })
      setPolOpen(false)
      show(t('mind.note_updated'))
      load()
      bump()
    } catch (er) {
      show.err(er)
    } finally {
      setPolBusy('')
    }
  }

  const revertPol = async () => {   // «← предыдущая версия» прямо из шита сравнения
    if (!pol || polBusy) return
    setPolBusy('revert')
    try {
      await api.post(`/api/mind/notes/${pol.note.id}/revert`, {})
      setPolOpen(false)
      show(t('mind.reverted_prev'))
      load()
      bump()
    } catch (er) {
      show.err(er)
    } finally {
      setPolBusy('')
    }
  }

  const openHist = async (it) => {
    if (!it || it._t !== 'note') return
    setHistNote(it); setHist([]); setHistSel(null); setHistOpen(true); setHistBusy(true)
    try {
      const revs = await api.get(`/api/mind/notes/${it.id}/revisions`)
      setHist(revs || [])
    } catch (er) {
      show.err(er)
      setHistOpen(false)
    } finally {
      setHistBusy(false)
    }
  }

  const revertTo = async (rev) => {
    if (!histNote || !rev || histBusy || rev.current) return
    setHistBusy(true)
    try {
      await api.post(`/api/mind/notes/${histNote.id}/revert`, { revision_id: rev.id })
      setHistOpen(false)
      show(t('mind.reverted_this'))
      load()
      bump()
    } catch (er) {
      show.err(er)
    } finally {
      setHistBusy(false)
    }
  }

  const submit = async (e) => {
    if (e && e.preventDefault) e.preventDefault()
    const txt = text.trim()
    if (!txt || busy) return
    setBusy(true)
    try {
      const m = txt.match(URL_RE)
      if (m) {
        await api.addLink(m[0], txt.replace(m[0], '').trim() || null)
        show(t('mind.link_saved'))
      } else {
        await api.addNote(txt)
        show(t('mind.note_saved'))
      }
      setText('')
      load()
      bump()
    } catch (er) {
      show.err(er)
    } finally {
      setBusy(false)
    }
  }

  const items = [
    ...(notes || []).map((n) => ({ ...n, _t: 'note' })),
    ...(links || []).map((l) => ({ ...l, _t: 'link' })),
  ].filter((x) => {
    if (tab === 'all') return true
    if (tab === 'photo') return !!x.image
    if (tab === 'note') return x._t === 'note' && !x.image
    if (tab === 'link') return x._t === 'link'
    return true
  }).sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))

  // честный счётчик: до загрузки — «—», а не выдуманные «25 записей»
  const count = loaded ? items.length : null

  // «← предыдущая версия» показываем, только если в истории есть куда откатываться
  // (первая версия обычно = оригинал; raw впереди может быть, если заметку уже причёсывали в фоне)
  const polCurIdx = pol ? (pol.hist || []).findIndex((v) => v.current) : -1
  const polHasPrev = !!pol && (polCurIdx > 0 || (!!pol.note.raw && pol.note.raw !== pol.original))

  return (
    <div className="pg on" id="p-brain" style={pageAcc.style}>
      {/* Шапка */}
      <div className="top">
        <div>
          <h1 className="r" style={{ '--i': 0 }}>{t('nav.mind')}</h1>
          <p className="sub r" style={{ '--i': 1 }}>{t('mind.second_brain')} · {count != null ? t('mind.entries_n', { count }) : '—'}</p>
        </div>
        <div className="hr r" style={{ '--i': 1 }}>
          <div className="sg">
            <button type="button" className={tab === 'all' ? 'on' : ''} onClick={() => setTab('all')}>{t('common.all')}</button>
            <button type="button" className={tab === 'note' ? 'on' : ''} onClick={() => setTab('note')}>{t('mind.tab_notes')}</button>
            <button type="button" className={tab === 'photo' ? 'on' : ''} onClick={() => setTab('photo')}>{t('mind.tab_photos')}</button>
            <button type="button" className={tab === 'link' ? 'on' : ''} onClick={() => setTab('link')}>{t('mind.tab_links')}</button>
            <button type="button" className={tab === 'graph' ? 'on' : ''} onClick={() => setTab('graph')}>{t('mind.tab_graph')}</button>
          </div>
        </div>
      </div>

      {/* Быстрый ввод */}
      <div className="comp r" style={{ '--i': 2 }}>
        <i></i>
        <input
          className="ph0"
          style={{ background: 'transparent', border: 0, outline: 'none', width: '100%', color: 'inherit' }}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit(e)}
          placeholder={t('mind.composer_ph')}
        />
        <span className="send" style={{ fontSize: '24px', cursor: 'pointer' }} onClick={submit}>+</span>
      </div>

      {/* Поисковая строка по смыслу */}
      <div className="search r" style={{ width: '100%', height: '54px', marginTop: '16px', '--i': 3 }}>
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          <circle cx="9" cy="9" r="6" />
          <path d="m14 14 3.5 3.5" />
        </svg>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ background: 'transparent', border: 0, outline: 'none', width: '100%', color: 'inherit', font: 'inherit', marginLeft: '8px' }}
          placeholder={t('mind.search_ph')}
        />
      </div>

      {/* Masonry-сетка заметок или Граф */}
      {tab === 'graph' ? (
        <div className="mt-8 animate-rise">
          <Graph height={Math.max(450, window.innerHeight - 300)} />
        </div>
      ) : (
        <div className="mas" style={{ marginTop: '28px' }}>
          {!loaded ? (
            <ListSkeleton n={6} />
          ) : !items.length ? (
            <div className="c p2" style={{ gridColumn: '1 / -1' }}>
              <Empty glyph="mind" text={t(q ? 'common.no_results' : 'mind.empty_title')}
                sub={t(q ? 'mind.empty_query' : 'mind.empty_hint')}
                hint={q ? null : t('mind.empty_hint_example')} />
            </div>
          ) : items.map((it, idx) => (
            // id у заметок и ссылок начинаются с 1 — ключ составной, иначе дубли
            <section className="c r" key={`${it._t}-${it.id}`} style={{ '--i': 4 + (idx % 6) }}>
              {/* Превью показываем только когда картинка есть (иначе карточка остаётся текстовой) */}
              {it.image && (
                <div style={{
                  position: 'relative', width: '100%', aspectRatio: '16 / 9',
                  borderRadius: '18px', overflow: 'hidden', border: '1px solid var(--line)',
                  background: 'var(--sf2)', marginBottom: '14px',
                }}>
                  <img
                    src={it.image.startsWith('http') ? it.image : '/media/' + it.image}
                    alt={it.title || it.text || it.summary || it.url || ''}
                    loading="lazy"
                    onError={(e) => { const box = e.currentTarget.parentElement; if (box) box.style.display = 'none' }}
                    style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                  {it._t === 'link' && it.domain && (
                    <span style={{
                      position: 'absolute', left: '8px', bottom: '8px', maxWidth: 'calc(100% - 16px)',
                      padding: '2px 8px', borderRadius: '999px', background: 'rgba(16, 17, 20, 0.55)', color: '#fff',
                      font: '11px "Inter Tight", "Inter", sans-serif',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>{it.domain}</span>
                  )}
                </div>
              )}
              {it.title && <h3>{it.title}</h3>}
              <p>{it.text || it.summary || it.body || it.url}</p>
              {/* ✨ правка нейронкой — только у заметок (у ссылок свой редактор) */}
              {it._t === 'note' && (
                <div className="chips !m-0 !gap-1.5">
                  <button type="button" disabled={!!polBusy}
                    onClick={() => runPolish(it, 'rewrite')}>✨ {t(polBusy === 'rewrite' ? 'common.loading' : 'mind.pol_rewrite')}</button>
                  <button type="button" disabled={!!polBusy}
                    onClick={() => runPolish(it, 'expand')}>✨ {t(polBusy === 'expand' ? 'common.loading' : 'mind.pol_expand')}</button>
                  <button type="button" onClick={() => openHist(it)}>{t('mind.history')}</button>
                </div>
              )}
              <div className="tg">
                <small>{relTime(it.created_at)}</small>
                {listOf(it.tags).map((t) => <span key={t}>#{t}</span>)}
                <div className="ml-auto flex items-center gap-1">
                  <button type="button" className="btn-icon !h-7 !w-7" title={t('common.edit')} aria-label={t('common.edit')}
                    onClick={() => startEdit(it)}><Pencil size={13} /></button>
                  <button type="button" className="btn-icon !h-7 !w-7" style={{ color: 'var(--neg)' }} title={t('common.delete')} aria-label={t('common.delete')}
                    onClick={() => { setAskDel(it); setAskOpen(true) }}><Trash2 size={13} /></button>
                </div>
              </div>
            </section>
          ))}
        </div>
      )}

      {/* Правка записи: тот же Sheet + Field, что и на остальных страницах */}
      <Sheet open={editOpen} onClose={() => setEditOpen(false)}
        title={t(edit?._t === 'link' ? 'mind.edit_link' : 'mind.edit_note')}
        sub={edit?._t === 'link' ? edit.url : undefined}>
        <form onSubmit={saveEdit} className="space-y-4">
          <Field label={t('common.title')}>
            <input className="input" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} placeholder={t('mind.title_ph')} />
          </Field>
          <Field label={t(edit?._t === 'link' ? 'common.comment' : 'mind.note_text')}>
            <textarea className="input" rows={edit?._t === 'link' ? 3 : 6} value={editText}
              onChange={(e) => setEditText(e.target.value)} required={edit?._t === 'note'} />
          </Field>
          <Field label={t('common.tags')} hint={t('mind.tags_hint')}>
            <input className="input" value={editTags} onChange={(e) => setEditTags(e.target.value)} placeholder={t('mind.tags_ph')} />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn g" onClick={() => setEditOpen(false)}>{t('common.cancel')}</button>
            <button type="submit" className="btn" disabled={editBusy}>{t(editBusy ? 'people.saving' : 'common.save')}</button>
          </div>
        </form>
      </Sheet>

      {/* Сравнение «было/стало» после правки нейронкой: применяем только по кнопке */}
      <Sheet open={polOpen} onClose={() => !polBusy && setPolOpen(false)}
        title={t(pol?.mode === 'expand' ? 'mind.pol_expand' : 'mind.pol_rewrite')}
        sub={pol?.note?.title || undefined}>
        {pol && (
          <div className="space-y-3">
            <div className="flex gap-2">
              <button type="button" className={`chip !mt-0 ${pol.tab === 'before' ? 'on' : ''}`}
                onClick={() => setPol({ ...pol, tab: 'before' })}>{t('mind.before')}</button>
              <button type="button" className={`chip !mt-0 ${pol.tab === 'after' ? 'on' : ''}`}
                onClick={() => setPol({ ...pol, tab: 'after' })}>{t('mind.after')}</button>
            </div>
            {pol.tab === 'before' ? (
              <textarea className="input" rows={8} readOnly value={pol.original}
                style={{ opacity: 0.7, cursor: 'default' }} />
            ) : (
              <textarea className="input" rows={8} value={pol.polished}
                onChange={(e) => setPol({ ...pol, polished: e.target.value })} />
            )}
            <div className="flex flex-wrap justify-end gap-2">
              {polHasPrev && (
                <button type="button" className="btn g" disabled={!!polBusy} onClick={revertPol}>
                  {t(polBusy === 'revert' ? 'mind.restoring' : 'mind.prev_version')}
                </button>
              )}
              <button type="button" className="btn g" disabled={!!polBusy}
                onClick={() => setPolOpen(false)}>{t('mind.keep_original')}</button>
              <button type="button" className="btn" disabled={!!polBusy || !pol.polished.trim()} onClick={applyPol}>
                {t(polBusy === 'apply' ? 'mind.applying' : 'common.apply')}
              </button>
            </div>
          </div>
        )}
      </Sheet>

      {/* История версий заметки: клик — показать версию, «вернуть эту» — откат на неё */}
      <Sheet open={histOpen} onClose={() => setHistOpen(false)} title={t('mind.version_history')}
        sub={histNote?.title || undefined}>
        {histBusy ? (
          <ListSkeleton n={3} />
        ) : !hist.length ? (
          <p className="muted">{t('mind.no_versions')}</p>
        ) : (
          <div className="space-y-2">
            {[...hist].reverse().map((v) => (   // свежие сверху
              <div key={v.id} role="button" tabIndex={0}
                onClick={() => setHistSel(v)}
                onKeyDown={(e) => e.key === 'Enter' && setHistSel(v)}
                style={{
                  padding: '10px 12px', borderRadius: '14px', cursor: 'pointer',
                  border: `1px solid ${histSel?.id === v.id ? 'var(--acc)' : 'var(--line)'}`,
                  background: histSel?.id === v.id ? 'var(--sf2)' : 'transparent',
                }}>
                <div className="flex items-center gap-2" style={{ fontSize: '12px', opacity: 0.7 }}>
                  <span>#{v.id}</span>
                  <span>{relTime(v.at)}</span>
                  {v.action && <span>· {v.action}</span>}
                  {v.current && <span className="chip on !mt-0 !py-0.5">{t('mind.current')}</span>}
                </div>
                <p style={{ whiteSpace: 'pre-wrap', marginTop: '6px', marginBottom: 0 }}>
                  {String(v.text || '').slice(0, 400)}
                </p>
              </div>
            ))}
            {histSel && (
              <>
                <div className="rounded-2xl px-4 py-3 text-[13.5px] leading-relaxed"
                  style={{
                    whiteSpace: 'pre-wrap', maxHeight: '30vh', overflow: 'auto',
                    background: 'var(--sf2)', border: '1px solid var(--line)', opacity: 0.9,
                  }}>
                  {histSel.text}
                </div>
                <div className="flex justify-end gap-2">
                  <button type="button" className="btn g" disabled={histBusy} onClick={() => setHistSel(null)}>{t('common.close')}</button>
                  <button type="button" className="btn" disabled={histBusy || histSel.current}
                    onClick={() => revertTo(histSel)}>
                    {t(histBusy ? 'mind.restoring' : histSel.current ? 'mind.is_current' : 'mind.restore_this')}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </Sheet>

      {/* Удаление — только через подтверждение */}
      <Confirm open={askOpen} danger
        title={t(askDel?._t === 'link' ? 'mind.del_link_q' : 'mind.del_note_q')}
        text={askDel ? t('md.del_card_text', { title: String(askDel.title || askDel.text || askDel.comment || askDel.url || '').slice(0, 80) }) : ''}
        onOk={doDel} onClose={() => setAskOpen(false)} />
    </div>
  )
}
