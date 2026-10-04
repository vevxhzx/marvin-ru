import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Pencil, Trash2, Plus, Search, X, Sparkles } from 'lucide-react'
import Graph from '../components/Graph'
import { api, relTime, listOf } from '../lib/api'
import { useToast, PageAccent, PageHead, Empty, ErrorState, ListSkeleton, Sheet, Field, Confirm, useLeave, useArrived } from '../components/ui'
import { useRefresh } from '../App'
import { usePageAccent } from '../lib/prefs'
import { useI18n } from '../lib/i18n'
import { usePhone } from '../lib/motion'

/* Подписи полей на узком телефоне (≤380px) — на ступень мельче: длинная подпись
   вроде «дата следующего шага» на 375px съедала строку и отжимала само поле. */
const FIELD_LABEL_M = 'max-[380px]:[&_.label]:text-[length:11px]'

/* Второй мозг: заметки, ссылки, фото и граф. Две раскладки, одна разметка:
   на десктопе (≥821px) мысли снова идут карточками сеткой по контенту (.mas — колонки,
   короткая мысль занимает две строки, длинная с картинкой — своя высота), фото — галерея,
   ссылки и граф — как раньше;
   на телефоне (≤820px) та же сетка становится плоским списком строк на фоне страницы.

   Кнопки AI-правки, история версий и удаление спрятаны не в меню, а в саму карточку:
   на телефоне до них один тап, зоны нажатия — --tap. */

/* Карточка мысли: на десктопе (≥821px) поверхность (.c + колонки .mas). На телефоне (≤820px)
   это тоже карточка, только легче: отступ 21px, радиус из токена (--r-lg), без тени и без
   хайрлайна — разделение тоном (макет). Разметка одна — переключают только классы max-[820px]. */
const CARD_M_LIGHT = 'max-[820px]:!bg-[var(--sf)] max-[820px]:!p-[21px] max-[820px]:!rounded-[var(--r-lg)] max-[820px]:!shadow-none max-[820px]:!transform-none'
const CARD_M = `c ${CARD_M_LIGHT}`
/* Поиск: та же поверхность, но на десктопе поле и кнопка сами за неё отступают. */
const FIELD_M = `c !px-3 !py-2 ${CARD_M_LIGHT}`

/* Ряд вкладок на телефоне: одна прокручиваемая строка вместо переноса */
const CHIPS_ROW_M = 'no-scrollbar fade-x max-[820px]:!flex-nowrap max-[820px]:!overflow-x-auto max-[820px]:!pb-1'

const URL_RE = /https?:\/\/[^\s]+/
const TABS = [
  ['all', 'common.all'], ['note', 'mind.tab_notes'], ['photo', 'mind.tab_photos'], ['link', 'mind.tab_links'], ['graph', 'mind.tab_graph'],
]
const EMPTY = {
  note: ['mind.empty_title', 'mind.empty_hint', 'mind.empty_hint_example'],
  photo: ['mind.empty_title', 'mind.empty_hint', 'mind.empty_hint_example'],
  link: ['mind.empty_title', 'mind.empty_hint', 'mind.empty_hint_example'],
  all: ['mind.empty_title', 'mind.empty_hint', 'mind.empty_hint_example'],
  graph: ['graph.empty_title', 'graph.empty_hint'],
}
const imgSrc = (s) => (!s ? '' : String(s).startsWith('http') ? String(s) : `/media/${s}`)

export default function Mind() {
  const { t } = useI18n()
  const [params, setParams] = useSearchParams()
  const pageAcc = usePageAccent('mind')
  const [tab, setTab] = useState(() => (TABS.some(([id]) => id === params.get('tab')) ? params.get('tab') : 'all'))
  const [q, setQ] = useState(() => params.get('q') || '')
  const [notes, setNotes] = useState([])
  const [links, setLinks] = useState([])
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [loadErr, setLoadErr] = useState(false)
  // правка и удаление записи (сами записи храним, пока шторка закрывается — иначе заголовок мигает)
  const [edit, setEdit] = useState(null)
  const [editOpen, setEditOpen] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editText, setEditText] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editBusy, setEditBusy] = useState(false)
  const [askDel, setAskDel] = useState(null)
  const [askOpen, setAskOpen] = useState(false)
  // добавление мысли — шторка с тремя снапами и крупным полем
  const [addOpen, setAddOpen] = useState(false)
  const [text, setText] = useState('')
  // правка заметки нейронкой: было/стало + история версий (только заметки, ссылки не трогаем)
  const [pol, setPol] = useState(null)         // { note, mode, original, polished, hist }
  const [polOpen, setPolOpen] = useState(false)
  const [polBusy, setPolBusy] = useState('')   // '' | rewrite | expand | apply | revert
  const [hist, setHist] = useState([])
  const [histNote, setHistNote] = useState(null)
  const [histOpen, setHistOpen] = useState(false)
  const [histSel, setHistSel] = useState(null)
  const [histBusy, setHistBusy] = useState(false)
  const [, show] = useToast()
  const { tick, bump } = useRefresh()
  const phone = usePhone()          // ≤820px: телефонная раскладка по макету
  const [leavingCls, leave] = useLeave()
  const addRef = useRef(null)

  const load = () => {
    setLoadErr(false)
    const p = q.trim().length >= 3
      ? api.semantic(q, 30).then((r) => {
          setNotes(r.items.filter((x) => x.kind === 'note'))
          setLinks(r.items.filter((x) => x.kind === 'link'))
        }).catch(() => Promise.all([api.notes(q), api.links(q)]).then(([n, l]) => { setNotes(n || []); setLinks(l || []) }).catch(() => { setLoadErr(true) }))
      : Promise.all([api.notes(q), api.links(q)]).then(([n, l]) => { setNotes(n || []); setLinks(l || []) }).catch(() => { setLoadErr(true) })
    return p.finally(() => setLoaded(true))
  }

  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0)
    return () => clearTimeout(t)
  }, [q, tick])

  // «+» дока на «Мозге» открывает форму новой записи (AppShell шлёт mind:add)
  useEffect(() => {
    const on = () => setAddOpen(true)
    window.addEventListener('mind:add', on)
    return () => window.removeEventListener('mind:add', on)
  }, [])

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

  // удаление — строка сначала уезжает, потом уходит запрос: не остаётся «прыгающего» списка
  const doDel = async () => {
    const it = askDel
    setAskOpen(false)
    if (!it) return
    try {
      await leave(it._t + it.id, 'card', async () => {
        if (it._t === 'note') await api.delNote(it.id)
        else await api.delLink(it.id)
      })
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
      setPol({ note: it, mode, original: r.original, polished: r.polished, hist: revs || [] })
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

  const revertPol = async () => {   // «← предыдущая версия» прямо из шторки сравнения
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
      setAddOpen(false)
      load()
      bump()
    } catch (er) {
      show.err(er)
    } finally {
      setBusy(false)
    }
  }

  const items = useMemo(() => [
    ...(notes || []).map((n) => ({ ...n, _t: 'note' })),
    ...(links || []).map((l) => ({ ...l, _t: 'link' })),
  ].filter((x) => {
    if (tab === 'all') return true
    if (tab === 'photo') return !!x.image
    if (tab === 'note') return x._t === 'note' && !x.image
    if (tab === 'link') return x._t === 'link'
    return true
  }).sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)), [notes, links, tab])

  // честный счётчик: до загрузки — «—», а не выдуманные «25 записей»
  const count = loaded ? items.length : null
  const arrived = useArrived(items.map((x) => `${x._t}${x.id}`))

  // «← предыдущая версия» показываем, только если в истории есть куда откатываться
  // (первая версия обычно = оригинал; raw впереди может быть, если заметку уже причёсывали в фоне)
  const polCurIdx = pol ? (pol.hist || []).findIndex((v) => v.current) : -1
  const polHasPrev = !!pol && (polCurIdx > 0 || (!!pol.note.raw && pol.note.raw !== pol.original))

  const emptyKeys = EMPTY[tab] || EMPTY.all
  const emptyNode = (
    <div className="c" style={{ gridColumn: '1 / -1' }}>
      <Empty glyph={tab === 'graph' ? 'mind' : 'mind'} text={t(q && tab !== 'graph' ? 'common.no_results' : emptyKeys[0])} sub={t(q && tab !== 'graph' ? 'mind.empty_query' : emptyKeys[1])} hint={q || tab === 'graph' ? undefined : t(emptyKeys[2])} />
    </div>
  )

  return (
    <div className={`pg on ${FIELD_LABEL_M}`} id="p-brain" style={pageAcc.style}>
      <PageHead kicker={t('mind.second_brain')} title={t('nav.mind')} idx={count}
        sub={count != null ? t('mind.entries_n', { count }) : undefined}
        right={<>
          {/* Цвет раздела — вторичное действие: на телефоне его точка входа одна,
              и она уже есть в настройках вида, поэтому в шапке остаётся одно действие. */}
          {!phone && <PageAccent page="mind" />}
          <button type="button" className="btn-primary head-primary max-[820px]:!hidden" onClick={() => setAddOpen(true)}>
            <Plus size={15} /> {t('common.add')}
          </button>
        </>} />

      {/* вкладки — спокойные переключатели, а не «простыня кнопок» */}
      <div className={`flex flex-wrap items-center gap-1.5 ${CHIPS_ROW_M} fade-x`} role="tablist" aria-label={t('nav.mind')}>
        {TABS.map(([id, l]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={`pill max-[820px]:!shrink-0 !min-h-[var(--tap)] ${tab === id ? 'on' : ''}`}>{t(l)}</button>
        ))}
      </div>

      {tab === 'graph' ? (
        <div className="mt-4">{loaded ? <Graph /> : <div className="c"><ListSkeleton n={3} /></div>}</div>
      ) : !loaded ? (
        <div className="mt-4"><ListSkeleton n={5} /></div>
      ) : !items.length ? (
        loadErr ? <div className="mt-4"><ErrorState onRetry={load} /></div> : <div className="mt-4">{emptyNode}</div>
      ) : tab === 'photo' ? (
        /* Галерея: крупные превью в две колонки, кадр фиксированный (4:3) и картинка
           вписывается по object-fit — на телефоне фото не растягивается. */
        <div className="stagger mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 max-[380px]:grid-cols-1">
          {items.map((it) => (
            <figure key={`${it._t}-${it.id}`} className={`c overflow-hidden !p-0 ${arrived(`${it._t}${it.id}`)} ${leavingCls(it._t + it.id)}`}>
              <button type="button" className="block w-full text-left" onClick={() => startEdit(it)}>
                <Thumb src={imgSrc(it.image)} alt={it.title || it.text || it.summary || it.url || ''} ratio="4 / 3" />
                <span className="block p-3">
                  <span className="clamp-2 block text-[13.5px] leading-snug">{it.title || it.text || it.summary || it.url}</span>
                  <span className="faint mt-1 flex flex-wrap items-center gap-x-2 text-[12px]">
                    <time>{relTime(it.created_at)}</time>
                    {it._t === 'link' && it.domain && <span className="trunc">{it.domain}</span>}
                  </span>
                </span>
              </button>
              <div className="flex items-center justify-end gap-1 px-2 pb-2">
                <button type="button" className="btn-icon" title={t('common.edit')} aria-label={t('common.edit')} onClick={() => startEdit(it)}><Pencil size={15} /></button>
                <button type="button" className="btn-icon neg" title={t('common.delete')} aria-label={t('common.delete')}
                  onClick={() => { setAskDel(it); setAskOpen(true) }}><Trash2 size={15} /></button>
              </div>
            </figure>
          ))}
        </div>
      ) : (
        /* Лента мыслей: на десктопе карточки сеткой по контенту, на телефоне одна колонка
           карточек с зазором 12px. Каскад появления общий — 40 мс. */
        <div className={`stagger mas mt-4 ${phone ? '!columns-auto flex flex-col gap-3' : ''}`}>
          {items.map((it) => (
            <MindRow key={`${it._t}-${it.id}`} it={it} tag={q}
              cls={`${CARD_M} ${arrived(`${it._t}${it.id}`)} ${leavingCls(it._t + it.id)}`}
              polBusy={polBusy} onPolish={runPolish} onHistory={openHist} onEdit={startEdit}
              onAskDel={() => { setAskDel(it); setAskOpen(true) }} />
          ))}
        </div>
      )}

      {/* Добавление мысли: шторка (на телефоне — три снапа, ручка тянется, быстрый флик закрывает),
          поле крупное — 17px, чтобы iOS не зумил страницу. Ссылка в тексте сама уедет в «ссылки». */}
      <Sheet bodyClass={FIELD_LABEL_M} open={addOpen} onClose={() => !busy && setAddOpen(false)} title={t('nav.mind')} sub={t('mind.composer_ph')} ariaLabel={t('nav.mind')}>
        <form onSubmit={submit} onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(e) }}>
          <textarea ref={addRef} autoFocus value={text} onChange={(e) => setText(e.target.value)}
            rows={7} className="input !text-[17px] leading-relaxed" placeholder={t('mind.composer_ph')} aria-label={t('mind.composer_ph')} />
          <div className="mt-4 flex items-center justify-end gap-2">
            <button type="button" className="btn-ghost min-h-[var(--tap)]" onClick={() => setAddOpen(false)}>{t('common.cancel')}</button>
            <button type="submit" className="btn-primary min-h-[var(--tap)]" disabled={busy || !text.trim()}>{t(busy ? 'common.loading' : 'common.save')}</button>
          </div>
        </form>
      </Sheet>

      {/* Правка записи: тот же Sheet + Field, что и на остальных страницах */}
      <Sheet bodyClass={FIELD_LABEL_M} open={editOpen} onClose={() => setEditOpen(false)}
        title={t(edit?._t === 'link' ? 'mind.edit_link' : 'mind.edit_note')}
        sub={edit?._t === 'link' ? edit.url : undefined}>
        <form onSubmit={saveEdit} className="space-y-4">
          {edit?.image && (
            <div className="relative w-full overflow-hidden" style={{ aspectRatio: '16 / 9', borderRadius: 'var(--r-md)', background: 'var(--sf2)' }}>
              <img src={imgSrc(edit.image)} alt="" className="absolute inset-0 h-full w-full" style={{ objectFit: 'cover' }} />
            </div>
          )}
          <Field label={t('common.title')}>
            <input className="input" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} placeholder={t('mind.title_ph')} />
          </Field>
          <Field label={t(edit?._t === 'link' ? 'common.comment' : 'mind.note_text')}>
            <textarea className="input !text-[16px]" rows={edit?._t === 'link' ? 3 : 6} value={editText}
              onChange={(e) => setEditText(e.target.value)} required={edit?._t === 'note'} />
          </Field>
          <Field label={t('common.tags')} hint={t('mind.tags_hint')}>
            <input className="input" value={editTags} onChange={(e) => setEditTags(e.target.value)} placeholder={t('mind.tags_ph')} />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost min-h-[var(--tap)]" onClick={() => setEditOpen(false)}>{t('common.cancel')}</button>
            <button type="submit" className="btn-primary min-h-[var(--tap)]" disabled={editBusy}>{t(editBusy ? 'people.saving' : 'common.save')}</button>
          </div>
        </form>
      </Sheet>

      {/* Сравнение «было/стало»: две колонки, перенос строк сохранён, кнопки — во всю ширину тапа */}
      <Sheet bodyClass={FIELD_LABEL_M} open={polOpen} onClose={() => !polBusy && setPolOpen(false)}
        title={t(pol?.mode === 'expand' ? 'mind.pol_expand' : 'mind.pol_rewrite')}
        sub={pol?.note?.title || undefined}>
        {pol && (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <div className="label mb-1.5">{t('mind.before')}</div>
                <div className="rounded-2xl p-3 text-[14.5px] leading-relaxed" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', background: 'var(--sf)', border: '1px solid var(--line)', maxHeight: '38vh', overflow: 'auto' }}>{pol.original}</div>
              </div>
              <div>
                <div className="label mb-1.5">{t('mind.after')}</div>
                <textarea className="input !text-[16px] leading-relaxed" rows={8} value={pol.polished}
                  onChange={(e) => setPol({ ...pol, polished: e.target.value })} aria-label={t('mind.after')} />
              </div>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
              {polHasPrev && (
                <button type="button" className="btn-ghost min-h-[var(--tap)]" disabled={!!polBusy} onClick={revertPol}>
                  {t(polBusy === 'revert' ? 'mind.restoring' : 'mind.prev_version')}
                </button>
              )}
              <button type="button" className="btn-ghost min-h-[var(--tap)]" disabled={!!polBusy}
                onClick={() => setPolOpen(false)}>{t('mind.keep_original')}</button>
              <button type="button" className="btn-primary min-h-[var(--tap)]" disabled={!!polBusy || !pol.polished.trim()} onClick={applyPol}>
                {t(polBusy === 'apply' ? 'mind.applying' : 'common.apply')}
              </button>
            </div>
          </div>
        )}
      </Sheet>

      {/* История версий заметки: клик — показать версию, «вернуть эту» — откат на неё */}
      <Sheet bodyClass={FIELD_LABEL_M} open={histOpen} onClose={() => setHistOpen(false)} title={t('mind.version_history')}
        sub={histNote?.title || undefined}>
        {histBusy ? (
          <ListSkeleton n={3} />
        ) : !hist.length ? (
          <p className="muted text-[13.5px] leading-snug">{t('mind.no_versions')}</p>
        ) : (
          <div className="space-y-2">
            {[...hist].reverse().map((v) => (   // свежие сверху
              <button key={v.id} type="button" onClick={() => setHistSel(v)}
                className="block w-full rounded-2xl px-3 py-2.5 text-left transition hover:bg-[var(--fill)]"
                style={{
                  border: `1px solid ${histSel?.id === v.id ? 'var(--acc)' : 'var(--line)'}`,
                  background: histSel?.id === v.id ? 'var(--sf2)' : 'transparent',
                }}>
                <div className="flex flex-wrap items-center gap-2 text-[12px]" style={{ color: 'var(--ink-3)' }}>
                  <span className="num">#{v.id}</span>
                  <span>{relTime(v.at)}</span>
                  {v.action && <span>· {v.action}</span>}
                  {v.current && <span className="badge accent">{t('mind.current')}</span>}
                </div>
                <p className="mb-0 mt-1.5 text-[13.5px] leading-snug" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                  {String(v.text || '').slice(0, 400)}
                </p>
              </button>
            ))}
            {histSel && (
              <>
                <div className="rounded-2xl px-4 py-3 text-[14.5px] leading-relaxed"
                  style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: '30vh', overflow: 'auto', background: 'var(--sf2)', border: '1px solid var(--line)' }}>
                  {histSel.text}
                </div>
                <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                  <button type="button" className="btn-ghost min-h-[var(--tap)]" disabled={histBusy} onClick={() => setHistSel(null)}>{t('common.close')}</button>
                  <button type="button" className="btn-primary min-h-[var(--tap)]" disabled={histBusy || histSel.current}
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

/* Превью: кадр фиксированный, картинка вписывается по object-fit (не растягивается),
   а битая ссылка не оставляет «дыру» — блок просто исчезает, текст остаётся. */
function Thumb({ src, alt, ratio = '16 / 9', badge, className = '' }) {
  const [bad, setBad] = useState(false)
  if (!src || bad) return null
  return (
    <div className={`relative w-full overflow-hidden ${className}`} style={{ aspectRatio: ratio, borderRadius: 'var(--r-md)', background: 'var(--sf2)' }}>
      <img src={src} alt={alt} loading="lazy" onError={() => setBad(true)} className="absolute inset-0 h-full w-full" style={{ objectFit: 'cover' }} />
      {badge && <span className="absolute bottom-2 left-2 max-w-[calc(100%-16px)] truncate rounded-full px-2 py-[3px] text-[12px]" style={{ background: 'rgba(16, 17, 20, 0.55)', color: '#fff' }}>{badge}</span>}
    </div>
  )
}

/* Запись ленты: текст мысли или ссылки, теги чипами, время «20 ч назад»,
   правка и удаление — на расстоянии одного тапа от текста. Вид задаёт класс cls. */
function MindRow({ it, tag, cls, polBusy, onPolish, onHistory, onEdit, onAskDel }) {
  const { t } = useI18n()
  const tags = listOf(it.tags)
  const text = it.text || it.summary || it.body || it.url
  const shown = tag ? String(text || '').slice(0, 400) : text
  return (
    <article className={cls}>
        <Thumb className="mb-3" src={imgSrc(it.image)} alt={it.title || it.text || it.summary || it.url || ''}
          badge={it._t === 'link' ? it.domain : null} />
      {it.title && <h3 className="h3" style={{ overflowWrap: 'anywhere' }}>{it.title}</h3>}
      {it._t === 'link' && !it.title && it.url && (
        <h3 className="h3" style={{ overflowWrap: 'anywhere' }}>{it.url}</h3>
      )}
      {shown && (
        <p className="t-body muted mt-1" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{shown}</p>
      )}
      {/* ✨ правка нейронкой — только у заметок (у ссылок свой редактор) */}
      {it._t === 'note' && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <button type="button" className="btn-soft min-h-[var(--tap)] rounded-full px-3 text-[13px]" disabled={!!polBusy}
            onClick={() => onPolish(it, 'rewrite')} title={t('mind.pol_rewrite')}>
            <Sparkles size={14} /> {t(polBusy === 'rewrite' ? 'common.loading' : 'mind.pol_rewrite')}
          </button>
          <button type="button" className="btn-soft min-h-[var(--tap)] rounded-full px-3 text-[13px]" disabled={!!polBusy}
            onClick={() => onPolish(it, 'expand')} title={t('mind.pol_expand')}>
            <Sparkles size={14} /> {t(polBusy === 'expand' ? 'common.loading' : 'mind.pol_expand')}
          </button>
          <button type="button" className="btn-ghost min-h-[var(--tap)] rounded-full px-3 text-[13px]" onClick={() => onHistory(it)} title={t('mind.version_history')}>
            {t('mind.history')}
          </button>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t hair pt-3">
        <time className="faint shrink-0 text-[12px]">{relTime(it.created_at)}</time>
        {tags.length > 0 && (
          <div className="flex min-w-0 flex-wrap items-center gap-1">
            {tags.map((x) => <span key={x} className="chip">#{x}</span>)}
          </div>
        )}
        <div className="ml-auto flex items-center gap-1">
          <button type="button" className="btn-icon" title={t('common.edit')} aria-label={t('common.edit')} data-tip={t('common.edit')}
            onClick={() => onEdit(it)}><Pencil size={15} /></button>
          <button type="button" className="btn-icon neg" title={t('common.delete')} aria-label={t('common.delete')} data-tip={t('common.delete')}
            onClick={onAskDel}><Trash2 size={15} /></button>
        </div>
      </div>
    </article>
  )
}