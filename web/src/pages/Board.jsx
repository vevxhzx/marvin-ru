import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Plus, MousePointer2, Hand, StickyNote, Type, Film, ArrowUpRight, Pencil, Eraser, Image as ImageIcon, Undo2, Redo2, Trash2, Copy, Maximize2, Minus, Download, ChevronLeft, LayoutGrid, Clock, MessageCircle, Archive, MoreHorizontal, X, Briefcase, Target, Bold, Italic, AlignLeft, AlignCenter, AlignRight, Keyboard, RefreshCw, Focus, ArrowLeft, ArrowRight } from 'lucide-react'
import { api } from '../lib/api'
import { PageHead, Empty, ErrorState, Sheet, Field, Seg, Pills, useToast, Confirm, Skeleton } from '../components/ui'
import BoardCanvas from '../components/BoardCanvas'
import { STICKY, RATIOS, FONTS, FONT_LABEL, FONT_SIZES, TEXT_COLORS, INK_COLORS, fmtSec, fontSize, themeColor } from '../lib/board'
import { useRefresh } from '../App'
import { useI18n, t as T } from '../lib/i18n'

const KIND_RU = { free: 'bd.k_free', storyboard: 'bd.k_storyboard', script: 'bd.k_script' }
const TOOLS = [
  ['hand', Hand, 'bd.t_hand', 'H'], ['select', MousePointer2, 'bd.t_select', 'V'], ['sticky', StickyNote, 'bd.t_sticky', 'S'], ['text', Type, 'bd.t_text', 'T'],
  ['frame', Film, 'bd.t_frame', 'F'], ['arrow', ArrowUpRight, 'bd.t_arrow', 'A'], ['pen', Pencil, 'bd.t_pen', 'P'], ['eraser', Eraser, 'bd.t_eraser', 'E'], ['image', ImageIcon, 'bd.t_image', 'I'],
]
/* Подсказки по горячим клавишам: [клавиши, ключ подписи] — тексты лежат в словаре */
const SHORTCUTS = [
  ['Wheel', 'bd.sc_pan'], ['Ctrl + wheel / pinch', 'bd.sc_zoom'], ['Space + drag · middle button', 'bd.sc_pan_any'], ['Ctrl+1 / Ctrl+2 / Ctrl+0', 'bd.sc_zoom_levels'],
  ['H · V', 'bd.sc_hand_select'], ['S · T · F · A · P · E · I', 'bd.sc_tools'], ['Tool + drag', 'bd.sc_create'], ['Shift + tool', 'bd.sc_keep_tool'],
  ['Double click', 'bd.sc_dblclick'], ['Enter · Esc', 'bd.sc_enter_esc'], ['Ctrl+Z · Ctrl+Shift+Z / Ctrl+Y', 'bd.sc_undo_redo'], ['Ctrl+C · Ctrl+V · Ctrl+X · Ctrl+D', 'bd.sc_clipboard'],
  ['Alt + drag', 'bd.sc_drag_copy'], ['Shift + drag', 'bd.sc_drag_axis'], ['Ctrl + drag', 'bd.sc_drag_grid'], ['Arrows · Shift+arrows', 'bd.sc_nudge'],
  ['Shift + click · marquee', 'bd.sc_marquee'], ['Ctrl+A', 'bd.sc_select_all'], ['Delete · Backspace', 'bd.sc_delete'], ['PgUp · PgDn', 'bd.sc_zorder'],
  ['Handle on an object', 'bd.sc_rotate'], ['Frame corner', 'bd.sc_resize'], ['Ctrl+V with an image', 'bd.sc_paste_img'], ['Drop a file on the canvas', 'bd.sc_drop_img'],
]

export default function BoardPage() { const { id } = useParams(); return id ? <BoardEditor id={Number(id)} /> : <BoardList /> }

/* ---------------------------------------------------------------- список досок */
function BoardList() {
  const { t } = useI18n()
  const [boards, setBoards] = useState(null)
  const [loadErr, setLoadErr] = useState(false)
  const [archived, setArchived] = useState(false)
  const [sheet, setSheet] = useState(false)
  const nav = useNavigate()
  const [, show] = useToast()
  const load = useCallback(() => { setLoadErr(false); return api.get(`/api/boards${archived ? '?archived=true' : ''}`).then(setBoards).catch(() => setLoadErr(true)) }, [archived])
  useEffect(() => { load() }, [load])
  // «+» дока на «Доске» открывает форму новой доски (AppShell шлёт board:add)
  useEffect(() => {
    const on = () => setSheet(true)
    window.addEventListener('board:add', on)
    return () => window.removeEventListener('board:add', on)
  }, [])
  const restore = async (b) => { try { await api.put(`/api/boards/${b.id}`, { archived: false }); load() } catch (er) { show.err(er) } }
  return (
    <div className="pg">
      <PageHead kicker={t('bd.kicker')} title={t('nav.board')} idx={boards?.length}
        right={<div className="flex items-center gap-2">
          <Seg className="min-h-[var(--tap)] [&>button]:!min-h-[var(--tap)]" value={archived ? 'arch' : 'live'} onChange={(v) => setArchived(v === 'arch')} options={[['live', t('bd.live')], ['arch', t('bd.arch')]]} />
          <button type="button" className="btn-primary head-primary max-[820px]:!hidden" onClick={() => setSheet(true)}><Plus size={15} /> {t('bd.new_board')}</button>
        </div>} />
      {boards === null || (loadErr && boards.length === 0) ? (
        loadErr ? (
          <div className="panel p-5 sm:p-7"><ErrorState onRetry={load} /></div>
        ) : (
          <div className="grid gap-3 min-[821px]:grid-cols-2 min-[1180px]:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} h={132} radius="var(--r-xl)" />)}</div>
        )
      ) : boards.length === 0 ? (
        /* пусто не «белым экраном»: что это, как начать и кнопка создания */
        <div className="panel p-5 sm:p-7">
          <Empty glyph="mind" text={t(archived ? 'bd.arch_empty' : 'bd.none')} sub={archived ? '' : t('bd.none_sub')}
            hint={archived ? undefined : t('bd.hint_example')} onHint={archived ? undefined : () => setSheet(true)}
            action={archived ? undefined : <button type="button" className="btn-primary head-primary" onClick={() => setSheet(true)}><Plus size={15} /> {t('bd.new_board')}</button>} />
        </div>
      ) : (
        /* доска — карточка с превью: сетка на десктопе, те же карточки в одну колонку на телефоне */
        <div className="stagger grid gap-3 min-[821px]:grid-cols-2 min-[1180px]:grid-cols-3">
          {boards.map((b) => <BoardRow key={b.id} b={b} archived={archived} onRestore={restore} />)}
        </div>
      )}
      <NewBoardSheet open={sheet} onClose={() => setSheet(false)} onDone={(b) => { setSheet(false); nav(`/board/${b.id}`) }} onErr={show.err} />
    </div>
  )
}

/* Карточка доски: превью сцены сверху (16:9, не растягивается), под ним название и состав.
   На узком экране и в сетке десктопа раскладка одна; «вернуть» в архиве — соседняя кнопка,
   а не вложенная в кнопку перехода. */
function BoardRow({ b, archived, onRestore }) {
  const { t } = useI18n()
  const nav = useNavigate()
  const [coverBad, setCoverBad] = useState(false)   // битая обложка — показываем глиф типа доски, а не «дыру»
  const count = Array.isArray(b.items) ? b.items.length : (typeof b.items === 'number' ? b.items : 0)
  return (
    <div className="panel relative overflow-hidden">
      <button type="button" className="flex w-full flex-col text-left sm:flex-row min-[821px]:flex-col" onClick={() => nav(`/board/${b.id}`)}>
        <span className="relative block w-full shrink-0 sm:w-[210px] min-[821px]:!w-full" style={{ aspectRatio: '16 / 9', background: 'var(--fill)' }}>
          {b.cover && !coverBad
            ? <img src={`/media/${b.cover}`} alt="" loading="lazy" onError={() => setCoverBad(true)} className="absolute inset-0 h-full w-full" style={{ objectFit: 'cover' }} />
            : <span className="absolute inset-0"><BoardGlyph kind={b.kind} /></span>}
          <span className="badge absolute left-3 top-3">{t(KIND_RU[b.kind])}</span>
        </span>
        <span className="block flex-1 p-4">
          <span className="block h3" style={{ overflowWrap: 'anywhere' }}>{b.title}</span>
          <span className="muted mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
            <span>{t('bd.objects_n', { count })}</span>
            {b.order_title && <span className="flex min-w-0 items-center gap-1"><Briefcase size={12} />{b.order_title}</span>}
            {b.aim_title && <span className="flex min-w-0 items-center gap-1"><Target size={12} />{b.aim_title}</span>}
          </span>
        </span>
      </button>
      {archived && <button type="button" className="btn-soft btn-sm absolute right-3 top-3 z-10" onClick={() => onRestore(b)}>{t('aims.restore')}</button>}
    </div>
  )
}
function BoardGlyph({ kind }) {
  return (
    <svg viewBox="0 0 160 90" className="h-full w-full" style={{ color: 'var(--ink-3)' }} fill="none" stroke="currentColor" strokeWidth="1.2">
      {kind === 'storyboard' ? <><rect x="14" y="18" width="38" height="22" rx="3" /><rect x="61" y="18" width="38" height="22" rx="3" /><rect x="108" y="18" width="38" height="22" rx="3" /><path d="M14 48h24M61 48h30M108 48h20" /><rect x="14" y="58" width="38" height="22" rx="3" /><rect x="61" y="58" width="38" height="22" rx="3" /></>
        : kind === 'script' ? <path d="M40 18h80M50 30h60M40 40h50M55 52h50M40 62h70M50 72h40" />
          : <><rect x="18" y="16" width="34" height="34" rx="3" fill="currentColor" fillOpacity=".12" /><rect x="66" y="26" width="34" height="34" rx="3" fill="currentColor" fillOpacity=".12" /><path d="M52 33h14" /><path d="M100 43l22-12" /><circle cx="128" cy="26" r="9" /></>}
    </svg>
  )
}
function NewBoardSheet({ open, onClose, onDone, onErr, orderId, aimId }) {
  const { t } = useI18n()
  const [f, setF] = useState({ title: '', kind: 'storyboard', frames: 8, ratio: '16:9' })
  const [orders, setOrders] = useState([])
  useEffect(() => { if (open) { setF({ title: '', kind: 'storyboard', frames: 8, ratio: '16:9', order_id: orderId || null }); api.get('/api/orders').then(setOrders).catch(() => setOrders([])) } }, [open, orderId])
  const submit = async (e) => {
    e.preventDefault(); if (!f.title.trim()) return
    try { onDone(await api.post('/api/boards', { title: f.title.trim(), kind: f.kind, frames: f.kind === 'storyboard' ? Number(f.frames) || 0 : 0, ratio: f.ratio, order_id: f.order_id || null, aim_id: aimId || null })) } catch (er) { onErr?.(er) }
  }
  return (
    <Sheet open={open} onClose={onClose} title={t('bd.new_board')}>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('common.title')}><input autoFocus className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder={t('bd.ph_title')} /></Field>
        <Field label={t('bd.kind')}>
          <Pills value={f.kind} onChange={(v) => setF({ ...f, kind: v })} options={[['storyboard', t('bd.k_storyboard')], ['script', t('bd.k_script')], ['free', t('bd.k_free')]]} />
          <div className="muted mt-2 text-[12.5px]">{t(f.kind === 'storyboard' ? 'bd.d_storyboard' : f.kind === 'script' ? 'bd.d_script' : 'bd.d_free')}</div>
        </Field>
        {f.kind === 'storyboard' && <div className="grid grid-cols-2 gap-3">
          <Field label={t('bd.frames_word')}><input type="number" min={0} max={60} className="input num" value={f.frames} onChange={(e) => setF({ ...f, frames: e.target.value })} /></Field>
          <Field label={t('bd.ratio')}><select className="input" value={f.ratio} onChange={(e) => setF({ ...f, ratio: e.target.value })}>{Object.keys(RATIOS).map((r) => <option key={r} value={r}>{r}{r === '9:16' ? ' · ' + t('bd.reels') : r === '16:9' ? ' · ' + t('bd.youtube') : r === '2.39:1' ? ' · ' + t('bd.cinema') : ''}</option>)}</select></Field>
        </div>}
        {orders.length > 0 && !orderId && <Field label={t('bd.order_board')} hint={t('bd.order_board_hint')}>
          <select className="input" value={f.order_id || ''} onChange={(e) => setF({ ...f, order_id: Number(e.target.value) || null, title: f.title || orders.find((o) => o.id === Number(e.target.value))?.title || '' })}><option value="">{t('bd.none_opt')}</option>{orders.map((o) => <option key={o.id} value={o.id}>{o.title}{o.client ? ` · ${o.client}` : ''}</option>)}</select>
        </Field>}
        <button className="btn-primary w-full" type="submit">{t('bd.create')}</button>
      </form>
    </Sheet>
  )
}

/* ---------------------------------------------------------------- редактор */
function BoardEditor({ id }) {
  const { t } = useI18n()
  const [board, setBoard] = useState(null)
  const [err, setErr] = useState(null)
  // инструмент доски запоминается: иначе после возврата на доску снова «рука»
  // и клик просто двигает холст — фигура «не появляется у курсора»
  const [tool, setTool] = useState(() => { try { return localStorage.getItem('board.tool') || 'hand' } catch { return 'hand' } })
  useEffect(() => { try { localStorage.setItem('board.tool', tool) } catch { /* приватный режим */ } }, [tool])
  const [style, setStyle] = useState(() => ({ stickyColor: 'yellow', inkColor: 'ink', inkWidth: 3, ratio: '16:9', fontSize: 18, ...JSON.parse(localStorage.getItem('board.style') || '{}') }))
  useEffect(() => { localStorage.setItem('board.style', JSON.stringify(style)) }, [style])
  const [selection, setSelection] = useState([])
  const [status, setStatus] = useState('saved')
  const [conflict, setConflict] = useState(null)
  const [zoom, setZoom] = useState(1)
  const [menu, setMenu] = useState(false)
  const [confirmArch, setConfirmArch] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [gridSheet, setGridSheet] = useState(false)
  const [keysSheet, setKeysSheet] = useState(false)
  // на телефоне мелкая панель инструментов не годится: те же действия — крупными кнопками и шторками
  const [framesSheet, setFramesSheet] = useState(false)
  const [textSheet, setTextSheet] = useState(false)
  const [rev, setRev] = useState(0)          // список кадров перечитываем сразу после перестановки
  const [side, setSide] = useState(() => localStorage.getItem('board.side') !== '0')
  const controls = useRef(null), fileRef = useRef(null)
  const nav = useNavigate()
  const [, show] = useToast()
  const { bump } = useRefresh()
  const [sp] = useSearchParams()
  const [tick, setTick] = useState(0)

  useEffect(() => { setBoard(null); api.get(`/api/boards/${id}`).then(setBoard).catch((e) => setErr(e)) }, [id])
  useEffect(() => { localStorage.setItem('board.side', side ? '1' : '0') }, [side])
  useEffect(() => { document.body.classList.add('board-page'); return () => document.body.classList.remove('board-page') }, [])
  useEffect(() => { const it = Number(sp.get('item')); if (board && it && controls.current) setTimeout(() => controls.current.focusItem(it), 250) }, [board, sp])
  const onDirty = useCallback((s, e) => {
    if (s === 'conflict') { setConflict(e); setStatus('conflict'); return }
    setStatus(s); if (s === 'err') show.err(e); if (s === 'saved') setTick((t) => t + 1)
  }, [show])
  const frames = useMemo(() => (controls.current?.items?.() || board?.items || []).filter((i) => i.type === 'frame').sort((a, b) => (a.data.n || 0) - (b.data.n || 0)), [board, status, selection, tick, rev]) // eslint-disable-line
  const total = frames.reduce((a, f) => a + (+f.data.seconds || 0), 0)

  const pick = (t) => { if (t === 'image') { fileRef.current?.click(); return } setTool(t) }
  const exportPng = (onlySel) => { const url = controls.current.exportPng(onlySel); if (!url) { show(t('bd.nothing_to_export'), 'err'); return } const a = document.createElement('a'); a.href = url; a.download = `${board.title}${onlySel ? ' ' + t('bd.sel_suffix') : ''}.png`; a.click() }
  const exportStoryboard = () => {
    const fr = controls.current.items().filter((i) => i.type === 'frame').sort((a, b) => (a.data.n || 0) - (b.data.n || 0))
    if (!fr.length) { show(t('bd.no_frames'), 'err'); return }
    const w = window.open('', '_blank'); if (!w) { show(t('bd.print_blocked'), 'err'); return }
    w.document.write(storyboardHtml(board, fr)); w.document.close(); setTimeout(() => w.print(), 500)
  }
  // фраза уходит в ядро — она на русском в любом режиме интерфейса   // i18n-raw
  const askAssistant = () => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: `что по доске «${board.title}»?`, send: true } }))
  const rename = async (t) => { setRenaming(false); if (!t.trim() || t === board.title) return; try { const b = await api.put(`/api/boards/${id}`, { title: t.trim() }); setBoard((x) => ({ ...x, title: b.title })); bump() } catch (e) { show.err(e) } }
  const patchSel = (data) => controls.current.setSelData(data)
  /* Перестановка сцен: меняем местами и номера, и координаты — список и холст остаются одной правдой.
     Холст нумерует кадры по положению (renumber), поэтому одних номеров мало. */
  const moveFrame = (i, dir) => {
    const j = i + dir
    const a = frames[i], b = frames[j]
    const c = controls.current
    if (!a || !b || !c) return
    c.focusItem(a.id); c.setSelProps({ x: b.x, y: b.y }); c.setSelData({ n: b.data.n })
    c.focusItem(b.id); c.setSelProps({ x: a.x, y: a.y }); c.setSelData({ n: a.data.n })
    setRev((r) => r + 1)
  }

  if (err) return <div className="py-16 text-center"><div className="label mb-2">{t('nav.board')}</div><div className="h1-sm">{t('bd.not_found')}</div><button className="btn-soft btn-sm mt-4" onClick={() => nav('/board')}>{t('bd.to_list')}</button></div>
  if (!board) return <Skeleton h={480} radius="var(--r-xl)" />
  const sel1 = selection.length === 1 ? selection[0] : null
  const types = new Set(selection.map((s) => s.type))
  const textLike = selection.filter((s) => ['sticky', 'text', 'frame', 'arrow'].includes(s.type))
  const first = textLike[0]
  const showTextBar = textLike.length > 0 && tool === 'select'
  const showStickyBar = tool === 'sticky' || types.has('sticky')
  const showPenBar = tool === 'pen' || tool === 'arrow' || types.has('ink') || types.has('arrow')
  const showFrameBar = tool === 'frame' || types.has('frame')
  const withFrames = board.kind !== 'script'

  return (
    // ширина и высота — от реальных отступов: раньше отрицательный отступ
    // затаскивал шапку доски под строку поиска, а высота считалась «на глаз»
    <div className="board-page-root flex flex-col" style={{
      marginLeft: 'calc(-1 * clamp(4px, 1vw, 16px))',
      marginRight: 'calc(-1 * clamp(4px, 1vw, 16px))',
      height: 'calc(100dvh - var(--app-pad, 16px) - 66px)',
    }}>
      {/* шапка */}
      <div className="flex shrink-0 items-center gap-2 border-b hair px-2 py-1.5 sm:px-4" style={{ background: 'var(--bg)' }}>
        <button className="btn-icon" onClick={() => nav('/board')} aria-label={t('bd.to_list')} data-tip={t('bd.all_boards')} title={t('bd.all_boards')}><ChevronLeft size={16} /></button>
        <div className="min-w-0 flex-1">
          {renaming ? <input autoFocus className="input !h-8 max-w-[360px] !text-[14px]" defaultValue={board.title} onBlur={(e) => rename(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') setRenaming(false) }} />
            : <button className="max-w-full truncate text-left text-[15px] font-semibold tracking-[-0.01em] hover:opacity-70" onClick={() => setRenaming(true)} title={t('common.rename')} aria-label={t('common.rename')}>{board.title}</button>}
          <div className="muted flex flex-wrap items-center gap-2 text-[12px]">
            <span>{t(KIND_RU[board.kind])}</span>
            {board.order_title && <span className="hidden items-center gap-1 sm:flex"><Briefcase size={11} />{board.order_title}</span>}
            {frames.length > 0 && <span className="hidden sm:inline">· {t('bd.frames_n', { count: frames.length })}{total ? ` · ${fmtSec(total)}` : ''}</span>}
            <span className={`ml-1 transition ${status === 'dirty' ? 'opacity-70' : status === 'err' || status === 'conflict' ? 'neg' : 'opacity-40'}`}>{t(status === 'dirty' ? 'people.saving' : status === 'err' ? 'bd.not_saved' : status === 'conflict' ? 'bd.changed_elsewhere' : 'common.saved')}</span>
          </div>
        </div>
        <div className="hidden items-center gap-0.5 md:flex">
          <button className="btn-icon" onClick={() => controls.current.undo()} data-tip={t('bd.undo_tip')} aria-label={t('bd.undo')} title={t('bd.undo_tip')}><Undo2 size={15} /></button>
          <button className="btn-icon" onClick={() => controls.current.redo()} data-tip={t('bd.redo_tip')} aria-label={t('bd.redo')} title={t('bd.redo_tip')}><Redo2 size={15} /></button>
          <div className="mx-1 h-5 w-px" style={{ background: 'var(--line)' }} />
          <button className="btn-icon" onClick={() => controls.current.zoomOut()} aria-label={t('bd.zoom_out')} data-tip="Ctrl −"><Minus size={15} /></button>
          <button className="mono min-w-[54px] rounded-md px-1.5 py-1 text-center text-[12px] hover:bg-[var(--fill)]" onClick={() => controls.current.zoomTo(1)} data-tip="100% · Ctrl+0">{Math.round(zoom * 100)}%</button>
          <button className="btn-icon" onClick={() => controls.current.zoomIn()} aria-label={t('bd.zoom_in')} data-tip="Ctrl +"><Plus size={15} /></button>
          <button className="btn-icon" onClick={() => controls.current.fit()} data-tip={t('bd.fit_tip')} aria-label={t('bd.fit')} title={t('bd.fit_tip')}><Maximize2 size={15} /></button>
          {selection.length > 0 && <button className="btn-icon" onClick={() => controls.current.fitSelection()} data-tip={t('bd.fit_sel_tip')} aria-label={t('bd.fit_sel')} title={t('bd.fit_sel_tip')}><Focus size={15} /></button>}
          <div className="mx-1 h-5 w-px" style={{ background: 'var(--line)' }} />
          <button className="btn-icon" onClick={() => setKeysSheet(true)} data-tip={t('hot.title')} aria-label={t('hot.title')} title={t('hot.title')}><Keyboard size={15} /></button>
          <button className="btn-ghost btn-sm ml-1" onClick={askAssistant}><MessageCircle size={14} /> {t('bd.discuss')}</button>
        </div>
        <div className="relative">
          <button className="btn-icon" onClick={() => setMenu((v) => !v)} aria-label={t('bd.menu')} title={t('bd.menu')}><MoreHorizontal size={16} /></button>
          {menu && <div className="elevated absolute right-0 top-[42px] z-[70] w-[250px] !p-1.5 text-[13px]" onMouseLeave={() => setMenu(false)}>
            <MenuItem icon={Download} onClick={() => { setMenu(false); exportPng(false) }}>{t('bd.export_all')}</MenuItem>
            {selection.length > 0 && <MenuItem icon={Download} onClick={() => { setMenu(false); exportPng(true) }}>{t('bd.export_sel')}</MenuItem>}
            {frames.length > 0 && <MenuItem icon={Film} onClick={() => { setMenu(false); exportStoryboard() }}>{t('bd.export_pdf')}</MenuItem>}
            {withFrames && frames.length > 0 && <MenuItem icon={Film} onClick={() => { setMenu(false); setFramesSheet(true) }}>{t('bd.frames_label')}</MenuItem>}
            <MenuItem icon={LayoutGrid} onClick={() => { setMenu(false); setGridSheet(true) }}>{t('bd.add_grid')}</MenuItem>
            <MenuItem icon={Keyboard} onClick={() => { setMenu(false); setKeysSheet(true) }}>{t('hot.title')}</MenuItem>
            <div className="my-1 border-t hair" />
            <MenuItem icon={MessageCircle} onClick={() => { setMenu(false); askAssistant() }}>{t('bd.ask')}</MenuItem>
            <MenuItem icon={Type} onClick={() => { setMenu(false); setRenaming(true) }}>{t('common.rename')}</MenuItem>
            <MenuItem icon={Archive} onClick={() => { setMenu(false); setConfirmArch(true) }} danger>{t('bd.to_archive')}</MenuItem>
          </div>}
        </div>
      </div>

      {/* контекстная панель — своя строка под шапкой, ничего не перекрывает (десктоп) */}
      <div className="board-ctx hidden h-[44px] shrink-0 items-center gap-x-3 overflow-x-auto overflow-y-hidden whitespace-nowrap border-b hair px-3 text-[12.5px] md:flex" style={{ background: 'var(--surface)' }}>
        {!showTextBar && !showStickyBar && !showPenBar && !showFrameBar && <span className="muted">{t(tool === 'hand' ? 'bd.hint_hand' : tool === 'select' ? 'bd.hint_select' : tool === 'eraser' ? 'bd.hint_eraser' : tool === 'image' ? 'bd.hint_image' : 'bd.hint_default')}</span>}
        {showStickyBar && <Group label={t('page_accent.short')}>{Object.keys(STICKY).map((c) => <Swatch key={c} color={STICKY[c][document.documentElement.classList.contains('dark') ? 'dark' : 'light']} on={(sel1?.type === 'sticky' ? sel1.data.color : style.stickyColor) === c} onClick={() => { setStyle({ ...style, stickyColor: c }); if (types.has('sticky')) patchSel({ color: c }) }} label={c} />)}</Group>}
        {showFrameBar && <Group label={t('board.frame')}>{Object.keys(RATIOS).map((r) => <button key={r} onClick={() => { setStyle({ ...style, ratio: r }); if (types.has('frame')) patchSel({ ratio: r }) }} className={`mono rounded-full px-2 py-0.5 text-[11px] ${(types.has('frame') ? sel1?.data?.ratio === r : style.ratio === r) ? 'bg-[var(--ink)] text-[var(--bg)]' : 'hover:bg-[var(--fill)]'}`}>{r}</button>)}
          {sel1?.type === 'frame' && <><span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} /><label className="flex items-center gap-1.5"><Clock size={12} className="faint" /><input type="number" min={0} step={0.5} className="input !h-7 !w-[64px] num !px-2 !text-[12px]" aria-label={t('bd.duration')} value={sel1.data.seconds || ''} placeholder={t('unit.sec')} onChange={(e) => patchSel({ seconds: Number(e.target.value) || 0 })} /></label>
            <button className="btn-soft btn-sm !h-7" onClick={() => fileRef.current?.click()}><ImageIcon size={12} /> {t('bd.image')}</button>{sel1.data.image && <button className="btn-icon !h-7 !w-7" data-tip={t('bd.remove_img')} aria-label={t('bd.remove_img')} title={t('bd.remove_img')} onClick={() => patchSel({ image: null })}><X size={12} /></button>}</>}
        </Group>}
        {showPenBar && <Group label={t(tool === 'arrow' || types.has('arrow') ? 'bd.line' : 'bd.pencil')}>
          {INK_COLORS.map((c) => <Swatch key={c} color={themeColor(c, document.documentElement.classList.contains('dark'))} on={(types.has('ink') || types.has('arrow') ? (sel1?.data?.color || 'ink') : style.inkColor) === c} onClick={() => { setStyle({ ...style, inkColor: c }); if (types.has('ink') || types.has('arrow')) patchSel({ color: c }) }} label={c} />)}
          <span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} />
          {[2, 3, 6, 10].map((w) => <button key={w} onClick={() => { setStyle({ ...style, inkWidth: w }); if (types.has('ink') || types.has('arrow')) patchSel({ width: w }) }} aria-label={t('bd.width', { n: w })} title={t('bd.width', { n: w })} className={`grid h-6 w-6 place-items-center rounded-full ${(types.has('ink') || types.has('arrow') ? (sel1?.data?.width || 3) === w : style.inkWidth === w) ? 'bg-[var(--fill-2)]' : 'hover:bg-[var(--fill)]'}`}><span className="rounded-full" style={{ width: w + 2, height: w + 2, background: 'var(--ink)' }} /></button>)}
          {types.has('arrow') && <><span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} /><Seg value={sel1?.data?.style || 'arrow'} onChange={(v) => patchSel({ style: v })} options={[['arrow', t('bd.arrow')], ['line', t('bd.line')]]} /></>}
        </Group>}
        {showTextBar && first && <Group label={t('board.text')}>
          <select className="input !h-7 !w-[92px] !rounded-lg !px-2 !text-[12px]" value={first.data.font || 'inter'} onChange={(e) => patchSel({ font: e.target.value })} aria-label={t('bd.font')}>{Object.keys(FONTS).map((f) => <option key={f} value={f}>{FONT_LABEL[f]}</option>)}</select>
          <SizeInput value={Math.round(fontSize(first))} onChange={(v) => patchSel({ font_size: v })} />
          <button className={`btn-icon !h-7 !w-7 ${first.data.bold ? 'bg-[var(--fill-2)]' : ''}`} onClick={() => patchSel({ bold: !first.data.bold })} aria-label={t('bd.bold')} data-tip={t('bd.bold')} title={t('bd.bold')}><Bold size={13} /></button>
          <button className={`btn-icon !h-7 !w-7 ${first.data.italic ? 'bg-[var(--fill-2)]' : ''}`} onClick={() => patchSel({ italic: !first.data.italic })} aria-label={t('bd.italic')} data-tip={t('bd.italic')} title={t('bd.italic')}><Italic size={13} /></button>
          {[['left', AlignLeft], ['center', AlignCenter], ['right', AlignRight]].map(([a, I]) => <button key={a} className={`btn-icon !h-7 !w-7 ${(first.data.align || 'left') === a ? 'bg-[var(--fill-2)]' : ''}`} onClick={() => patchSel({ align: a })} aria-label={a} title={a}><I size={13} /></button>)}
          <span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} />
          {TEXT_COLORS.map((c) => <Swatch key={c} color={themeColor(c, document.documentElement.classList.contains('dark'))} on={(first.data.text_color || (first.type === 'sticky' ? '' : 'ink')) === c} onClick={() => patchSel({ text_color: c })} label={c} />)}
          <input type="color" className="h-6 w-7 cursor-pointer rounded border-0 bg-transparent p-0" value={/^#/.test(first.data.text_color || '') ? first.data.text_color : '#3b5bff'} onChange={(e) => patchSel({ text_color: e.target.value })} aria-label={t('bd.custom_color')} title={t('bd.custom_color')} />
        </Group>}
        {selection.length > 0 && <div className="ml-auto flex shrink-0 items-center gap-0.5 pl-3">
          {selection.length > 1 && <>{[['left', 'bd.al_left'], ['hcenter', 'bd.al_hcenter'], ['right', 'bd.al_right'], ['top', 'bd.al_top'], ['vcenter', 'bd.al_vcenter'], ['bottom', 'bd.al_bottom'], ['row', 'bd.al_row']].map(([h, lk]) => <button key={h} className="rounded-md px-1.5 py-0.5 text-[11.5px] hover:bg-[var(--fill)]" onClick={() => controls.current.alignSel(h)}>{t(lk)}</button>)}<span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} /></>}
          <button className="btn-icon !h-7 !w-7" onClick={() => controls.current.duplicateSel()} data-tip={t('bd.dup_tip')} aria-label={t('bd.dup')} title={t('bd.dup_tip')}><Copy size={13} /></button>
          <button className="btn-icon !h-7 !w-7 neg" onClick={() => controls.current.deleteSel()} data-tip={t('bd.del_tip')} aria-label={t('common.delete')} title={t('bd.del_tip')}><Trash2 size={13} /></button>
        </div>}
      </div>

      {/* телефон: те же действия крупными кнопками (зона нажатия — --tap), детали — в шторках */}
      <div className="board-ctx flex shrink-0 items-center gap-2 overflow-x-auto border-b hair px-3 py-1 md:hidden" style={{ background: 'var(--surface)', minHeight: 'var(--tap)' }}>
        {!showTextBar && !showStickyBar && !showPenBar && !showFrameBar && !withFrames && <span className="muted min-w-0 flex-1 truncate text-[12.5px]">{t(tool === 'hand' ? 'bd.hint_hand' : tool === 'select' ? 'bd.hint_select' : tool === 'eraser' ? 'bd.hint_eraser' : tool === 'image' ? 'bd.hint_image' : 'bd.hint_default')}</span>}
        {showTextBar && <BarBtn icon={Type} onClick={() => setTextSheet(true)} label={t('board.text')} />}
        {showFrameBar && sel1?.type === 'frame' && <BarBtn icon={ImageIcon} onClick={() => fileRef.current?.click()} label={t('bd.image')} />}
        {withFrames && <BarBtn icon={Film} onClick={() => setFramesSheet(true)} label={t('bd.frames_label')} count={frames.length} />}
        {withFrames && <BarBtn icon={Plus} onClick={() => { controls.current.addFrameNext(); setRev((r) => r + 1) }} label={t('bd.add_frame')} />}
        {withFrames && <BarBtn icon={LayoutGrid} onClick={() => setGridSheet(true)} label={t('bd.grid')} />}
        {selection.length > 0 && <BarBtn icon={Copy} onClick={() => controls.current.duplicateSel()} label={t('bd.dup')} />}
        {selection.length > 0 && <BarBtn icon={Trash2} onClick={() => controls.current.deleteSel()} label={t('common.delete')} danger />}
      </div>

      {conflict && <div className="flex shrink-0 flex-wrap items-center gap-2 border-b hair px-3 py-1.5 text-[12.5px]" style={{ background: 'var(--warn-soft)' }}>
        <RefreshCw size={13} /> {t('bd.conflict')}
        <button className="btn-soft btn-sm !h-7" onClick={() => { controls.current.adoptFresh(conflict, true); setConflict(null); setStatus('saved') }}>{t('bd.conflict_keep')}</button>
        <button className="btn-ghost btn-sm !h-7" onClick={() => { controls.current.adoptFresh(conflict, false); setConflict(null); setStatus('saved') }}>{t('bd.conflict_take')}</button>
      </div>}

      <div className="relative flex min-h-0 flex-1">
        {/* панель инструментов: слева, вне холста, чтобы не прятать объекты */}
        <div className="hidden shrink-0 flex-col items-center gap-0.5 border-r hair px-1.5 py-2 md:flex" style={{ background: 'var(--surface)' }}>
          {TOOLS.map(([t, I, label, key]) => (
            <button key={t} onClick={() => pick(t)} data-tip={`${label} · ${key}`} data-tip-side="right" aria-label={label} title={`${label} · ${key}`}
              className={`grid h-9 w-9 place-items-center rounded-xl transition ${tool === t ? '' : 'hover:bg-[var(--fill)]'}`} style={tool === t ? { background: 'var(--ink)', color: 'var(--bg)' } : {}}><I size={16} /></button>
          ))}
          {withFrames && <><div className="my-1 w-6 border-t hair" /><button onClick={() => { controls.current.addFrameNext(); setRev((r) => r + 1) }} data-tip={t('bd.add_frame')} data-tip-side="right" aria-label={t('bd.add_frame')} title={t('bd.add_frame')} className="grid h-9 w-9 place-items-center rounded-xl hover:bg-[var(--fill)]"><Plus size={16} /></button></>}
        </div>

        <div className="min-w-0 flex-1">
          <BoardCanvas board={board} tool={tool} setTool={setTool} style={style} onDirty={onDirty} onSelectionChange={setSelection} onViewChange={(v) => setZoom(v.k)} controlsRef={controls} />
        </div>

        {side && withFrames && frames.length > 0 && (
          <aside aria-label={t('board.frames')} className="hidden w-[250px] shrink-0 overflow-y-auto border-l hair p-3 lg:block" style={{ background: 'var(--surface)' }}>
            <div className="mb-2 flex items-center justify-between"><div className="label">{t('bd.frames_label')} · {frames.length}{total ? ` · ${fmtSec(total)}` : ''}</div><button className="btn-icon !h-7 !w-7" onClick={() => setSide(false)} aria-label={t('bd.hide')} title={t('bd.hide')}><X size={13} /></button></div>
            <div className="space-y-0.5">{frames.map((f) => (
              <button key={f.id} onClick={() => controls.current.focusItem(f.id)} className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-[var(--fill)] ${sel1?.id === f.id ? 'bg-[var(--fill)]' : ''}`}>
                <span className="mono mt-0.5 w-5 shrink-0 text-[11.5px] font-semibold" style={{ color: 'var(--ink-2)' }}>{f.data.n}</span>
                <span className="min-w-0 flex-1"><span className={`block truncate text-[13px] ${f.data.label ? '' : 'faint'}`}>{f.data.label || t('bd.no_caption')}</span><span className="faint mono text-[11px]">{f.data.image ? t('bd.image') : t('bd.empty')}{f.data.seconds ? ` · ${fmtSec(f.data.seconds)}` : ''}</span></span>
              </button>))}</div>
            <button className="btn-soft btn-sm mt-3 w-full" onClick={() => { controls.current.addFrameNext(); setRev((r) => r + 1) }}><Plus size={14} /> {t('board.frame')}</button>
          </aside>
        )}
        {!side && withFrames && frames.length > 0 && <button className="btn-soft btn-sm absolute right-3 top-3 z-10 hidden lg:inline-flex" onClick={() => setSide(true)}><Film size={13} /> {t('bd.frames_label')}</button>}

        {/* телефон */}
        <div className="absolute inset-x-0 bottom-0 z-20 flex items-center justify-around gap-1 border-t hair px-2 py-1.5 md:hidden" style={{ background: 'var(--surface)' }}>
          {TOOLS.filter(([t]) => ['hand', 'select', 'sticky', 'text', 'frame', 'pen'].includes(t)).map(([t, I, label]) => <button key={t} onClick={() => pick(t)} aria-label={label} title={label} className="grid h-10 w-10 place-items-center rounded-xl" style={tool === t ? { background: 'var(--ink)', color: 'var(--bg)' } : {}}><I size={17} /></button>)}
          <button onClick={() => controls.current.undo()} aria-label={t('bd.undo')} title={t('bd.undo')} className="grid h-10 w-10 place-items-center rounded-xl"><Undo2 size={17} /></button>
          <button onClick={() => controls.current.fit()} aria-label={t('bd.fit')} title={t('bd.fit')} className="grid h-10 w-10 place-items-center rounded-xl"><Maximize2 size={17} /></button>
          {selection.length > 0 && <button onClick={() => controls.current.deleteSel()} aria-label={t('common.delete')} title={t('common.delete')} className="neg grid h-10 w-10 place-items-center rounded-xl"><Trash2 size={17} /></button>}
        </div>
      </div>

      <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { const fs = [...e.target.files]; e.target.value = ''; if (!fs.length) return; const fr = sel1?.type === 'frame' && fs.length === 1 ? sel1.id : null; fs.forEach((f) => controls.current.uploadImage(f, fr)) }} />
      <Confirm open={confirmArch} onClose={() => setConfirmArch(false)} title={t('bd.arch_q')} text={t('bd.arch_note')} onOk={async () => { try { await controls.current.flushNow(); await api.del(`/api/boards/${id}`); bump(); nav('/board') } catch (e) { show.err(e) } }} />
      <Sheet open={gridSheet} onClose={() => setGridSheet(false)} title={t('bd.grid')}><GridForm ratio={style.ratio} onDone={(n, ratio) => { setGridSheet(false); controls.current.addFramesGrid(n, ratio); setRev((r) => r + 1) }} /></Sheet>
      <Sheet open={keysSheet} onClose={() => setKeysSheet(false)} title={t('hot.title')} wide>
        <div className="grid gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-2">{SHORTCUTS.map(([k, v]) => <div key={k} className="flex items-baseline justify-between gap-3 border-b hair py-1.5"><span className="mono text-[12px]" style={{ color: 'var(--ink-2)' }}>{k}</span><span className="text-right">{t(v)}</span></div>)}</div>
      </Sheet>

      {/* Раскадровка: сетка кадров 2–3 колонки, тап — перейти к кадру на холсте,
          перестановка — стрелками (номер и место меняются местами), добавление — снизу. */}
      <Sheet open={framesSheet} onClose={() => setFramesSheet(false)} wide
        title={t('bd.frames_label')} sub={`${t('bd.frames_n', { count: frames.length })}${total ? ` · ${fmtSec(total)}` : ''}`}>
        {!withFrames ? (
          <Empty compact glyph="mind" text={t('bd.no_frames')} sub={t('bd.d_script')} />
        ) : !frames.length ? (
          <Empty compact glyph="mind" text={t('bd.no_frames')} sub={t('bd.d_storyboard')} hint={t('bd.hint_example')} onHint={() => { setFramesSheet(false); setGridSheet(true) }} />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {frames.map((f, i) => (
                <div key={f.id} className={`c !p-2 ${sel1?.id === f.id ? 'tint-acc' : ''}`}>
                  <button type="button" className="block w-full text-left" onClick={() => { controls.current.focusItem(f.id); setFramesSheet(false) }}>
                    <span className="relative block w-full overflow-hidden" style={{ aspectRatio: String(RATIOS[f.data.ratio] || 1.78), background: 'var(--sf2)', borderRadius: 'var(--r-sm)' }}>
                      {f.data.image
                        ? <img src={`/media/${f.data.image}`} alt="" className="absolute inset-0 h-full w-full" style={{ objectFit: 'cover' }} />
                        : <span className="mono absolute inset-0 grid place-items-center text-[13px]" style={{ color: 'var(--ink-3)' }}>{f.data.n}</span>}
                    </span>
                    <span className="clamp-2 mt-1.5 block text-[12.5px] leading-snug">{f.data.label || t('bd.no_caption')}</span>
                    <span className="faint mono block text-[12px]">{f.data.seconds ? fmtSec(f.data.seconds) : t('bd.empty')}</span>
                  </button>
                  <div className="mt-1 flex items-center justify-between">
                    <span className="mono text-[12px]" style={{ color: 'var(--ink-2)' }}>#{f.data.n}</span>
                    <span className="flex items-center">
                      <button type="button" className="btn-icon !h-9 !w-9" disabled={i === 0} onClick={() => moveFrame(i, -1)} aria-label={t('bd.al_left')} title={t('bd.al_left')}><ArrowLeft size={15} /></button>
                      <button type="button" className="btn-icon !h-9 !w-9" disabled={i === frames.length - 1} onClick={() => moveFrame(i, 1)} aria-label={t('bd.al_right')} title={t('bd.al_right')}><ArrowRight size={15} /></button>
                    </span>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
              <button type="button" className="btn-ghost min-h-[var(--tap)]" onClick={() => setGridSheet(true)}><LayoutGrid size={15} /> {t('bd.add_grid')}</button>
              <button type="button" className="btn-primary min-h-[var(--tap)]" onClick={() => { controls.current.addFrameNext(); setRev((r) => r + 1) }}><Plus size={15} /> {t('board.frame')}</button>
            </div>
          </>
        )}
      </Sheet>

      {/* Правка текста и шрифта крупными кнопками: на телефоне 28px пиксельные иконки не попасть пальцем */}
      <Sheet open={textSheet} onClose={() => setTextSheet(false)} title={t('board.text')}>
        {!first ? (
          <Empty compact glyph="mind" text={t('bd.hint_select')} />
        ) : (
          <div className="space-y-4">
            <Field label={t('bd.font')}>
              <select className="input" value={first.data.font || 'inter'} onChange={(e) => patchSel({ font: e.target.value })} aria-label={t('bd.font')}>
                {Object.keys(FONTS).map((f) => <option key={f} value={f}>{FONT_LABEL[f]}</option>)}
              </select>
            </Field>
            <Field label={t('bd.font_size')}>
              <div className="flex items-center gap-2">
                <button type="button" className="btn-icon outlined !h-[var(--tap)] !w-[var(--tap)]" onClick={() => patchSel({ font_size: FONT_SIZES.filter((s) => s < fontSize(first)).pop() || fontSize(first) - 1 })} aria-label={t('bd.smaller')} title={t('bd.smaller')}><Minus size={16} /></button>
                <div className="num flex-1 text-center" style={{ fontSize: 'var(--fs-xl)' }}>{Math.round(fontSize(first))}</div>
                <button type="button" className="btn-icon outlined !h-[var(--tap)] !w-[var(--tap)]" onClick={() => patchSel({ font_size: FONT_SIZES.find((s) => s > fontSize(first)) || fontSize(first) + 1 })} aria-label={t('bd.bigger')} title={t('bd.bigger')}><Plus size={16} /></button>
              </div>
            </Field>
            <div>
              <div className="label mb-1.5">{t('board.text')}</div>
              <div className="flex flex-wrap items-center gap-2">
                <BigToggle on={!!first.data.bold} onClick={() => patchSel({ bold: !first.data.bold })} label={t('bd.bold')}><Bold size={17} /></BigToggle>
                <BigToggle on={!!first.data.italic} onClick={() => patchSel({ italic: !first.data.italic })} label={t('bd.italic')}><Italic size={17} /></BigToggle>
                {[['left', AlignLeft], ['center', AlignCenter], ['right', AlignRight]].map(([a, I]) => (
                  <BigToggle key={a} on={(first.data.align || 'left') === a} onClick={() => patchSel({ align: a })} label={a}><I size={17} /></BigToggle>
                ))}
              </div>
            </div>
            <div>
              <div className="label mb-1.5">{t('bd.custom_color')}</div>
              <div className="flex flex-wrap items-center gap-2">
                {TEXT_COLORS.map((c) => (
                  <button key={c} type="button" onClick={() => patchSel({ text_color: c })} aria-label={c} title={c} aria-pressed={(first.data.text_color || (first.type === 'sticky' ? '' : 'ink')) === c}
                    className="grid !h-[var(--tap)] !w-[var(--tap)] place-items-center rounded-full" style={{ background: 'var(--fill)' }}>
                    <span className="h-5 w-5 rounded-full" style={{ background: themeColor(c, document.documentElement.classList.contains('dark')), boxShadow: (first.data.text_color || (first.type === 'sticky' ? '' : 'ink')) === c ? '0 0 0 2px var(--ink)' : 'inset 0 0 0 1px var(--line-2)' }} />
                  </button>
                ))}
                <input type="color" className="h-[var(--tap)] w-[var(--tap)] cursor-pointer rounded-xl border-0 bg-transparent p-0" value={/^#/.test(first.data.text_color || '') ? first.data.text_color : '#3b5bff'} onChange={(e) => patchSel({ text_color: e.target.value })} aria-label={t('bd.custom_color')} title={t('bd.custom_color')} />
              </div>
            </div>
          </div>
        )}
      </Sheet>
    </div>
  )
}

/* Крупная кнопка строки инструментов на телефоне */
function BarBtn({ icon: I, onClick, label, count, danger }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className={`btn-soft shrink-0 !h-[var(--tap)] gap-1.5 rounded-full px-3.5 text-[13px] ${danger ? 'neg' : ''}`}>
      {I && <I size={15} />}{label}{count != null ? <span className="num opacity-60">{count}</span> : null}
    </button>
  )
}
/* Крупный переключатель в шторке текста: зона нажатия — --tap */
function BigToggle({ on, onClick, label, children }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={!!on} aria-label={label} title={label}
      className="grid !h-[var(--tap)] min-w-[var(--tap)] place-items-center rounded-xl px-3"
      style={{ background: on ? 'var(--ink)' : 'var(--fill)', color: on ? 'var(--bg)' : 'var(--ink)' }}>
      {children}
    </button>
  )
}
function Group({ label, children }) { return <div className="flex shrink-0 items-center gap-1"><span className="label mr-1 !text-[12px]">{label}</span>{children}</div> }
function Swatch({ color, on, onClick, label }) { return <button type="button" onClick={onClick} aria-label={label} title={label} aria-pressed={!!on} className="h-6 w-6 rounded-full border-2 transition hover:scale-110" style={{ background: color, borderColor: on ? 'var(--ink)' : 'transparent', boxShadow: on ? '0 0 0 1px var(--bg) inset' : '0 0 0 1px var(--line) inset' }} /> }
function SizeInput({ value, onChange }) {
  const { t } = useI18n()
  const [v, setV] = useState(value); useEffect(() => setV(value), [value])
  const commit = (n) => { n = Math.max(6, Math.min(240, Math.round(Number(n) || value))); setV(n); if (n !== value) onChange(n) }
  return <div className="flex items-center">
    <button type="button" className="btn-icon !h-7 !w-6" onClick={() => commit(FONT_SIZES.filter((s) => s < value).pop() || value - 1)} aria-label={t('bd.smaller')} title={t('bd.smaller')}>−</button>
    <input className="input !h-7 !w-[46px] num !px-1 !text-center !text-[12px]" value={v} list="board-font-sizes" onChange={(e) => setV(e.target.value)} onBlur={(e) => commit(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} aria-label={t('bd.font_size')} />
    <datalist id="board-font-sizes">{FONT_SIZES.map((s) => <option key={s} value={s} />)}</datalist>
    <button type="button" className="btn-icon !h-7 !w-6" onClick={() => commit(FONT_SIZES.find((s) => s > value) || value + 1)} aria-label={t('bd.bigger')} title={t('bd.bigger')}>+</button>
  </div>
}
function MenuItem({ icon: I, children, onClick, danger }) { return <button type="button" className={`flex w-full min-h-[var(--tap)] items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left hover:bg-[var(--fill)] ${danger ? 'neg' : ''}`} onClick={onClick}><I size={14} className="faint" />{children}</button> }
function GridForm({ onDone, ratio: r0 }) {
  const { t } = useI18n()
  const [n, setN] = useState(6); const [ratio, setRatio] = useState(r0 || '16:9')
  return <div className="space-y-4">
    <div className="grid grid-cols-2 gap-3"><Field label={t('bd.frames_word')}><input type="number" min={1} max={40} className="input num" value={n} onChange={(e) => setN(Number(e.target.value))} /></Field><Field label={t('bd.ratio')}><select className="input" value={ratio} onChange={(e) => setRatio(e.target.value)}>{Object.keys(RATIOS).map((r) => <option key={r}>{r}</option>)}</select></Field></div>
    <button className="btn-primary w-full min-h-[var(--tap)]" onClick={() => onDone(Math.max(1, Math.min(40, n)), ratio)}>{t('common.add')}</button>
  </div>
}
/* Готовый HTML для печати/сохранения — это файл, а не интерфейс: подписи в нём
   всегда по-русски, независимо от языка сайта.   // i18n-raw */
function storyboardHtml(board, frames) {
  const esc = (s) => String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])
  const total = frames.reduce((a, f) => a + (+f.data.seconds || 0), 0)
  const cells = frames.map((f) => `<div class="c"><div class="p" style="aspect-ratio:${RATIOS[f.data.ratio] || 16 / 9}">${f.data.image ? `<img src="${location.origin}/media/${esc(f.data.image)}">` : ''}</div><div class="m"><b>${f.data.n}</b>${f.data.seconds ? `<span>${fmtSec(f.data.seconds)}</span>` : ''}</div><div class="l">${esc(f.data.label)}</div></div>`).join('')
  // файл для печати, не интерфейс — подписи всегда по-русски   // i18n-raw
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>${esc(board.title)} — раскадровка</title>
  <style>@page{margin:14mm}body{font:12px/1.4 -apple-system,Inter,system-ui,sans-serif;color:#111;margin:0}h1{font-size:20px;margin:0 0 2px;letter-spacing:-.02em}.s{color:#666;margin-bottom:14px}.g{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.c{break-inside:avoid}.p{background:#f2f2f0;border:1px solid #ddd;border-radius:6px;overflow:hidden}.p img{width:100%;height:100%;object-fit:cover;display:block}.m{display:flex;justify-content:space-between;margin-top:6px;font-family:Inter,-apple-system,sans-serif;font-size:11px;color:#444}.l{margin-top:2px;min-height:2.6em;white-space:pre-wrap}</style></head>
  <body><h1>${esc(board.title)}</h1><div class="s">${frames.length} кадров${total ? ` · хронометраж ${fmtSec(total)}` : ''}${board.order_title ? ` · заказ «${esc(board.order_title)}»` : ''}   // i18n-raw</div><div class="g">${cells}</div></body></html>`
}