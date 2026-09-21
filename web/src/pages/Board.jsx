import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Plus, MousePointer2, Hand, StickyNote, Type, Film, ArrowUpRight, Pencil, Eraser, Image as ImageIcon, Undo2, Redo2, Trash2, Copy, Maximize2, Minus, Download, ChevronLeft, LayoutGrid, Clock, MessageCircle, Archive, MoreHorizontal, X, Briefcase, Target, Bold, Italic, AlignLeft, AlignCenter, AlignRight, Keyboard, RefreshCw, Focus } from 'lucide-react'
import { api } from '../lib/api'
import { PageHead, Empty, Sheet, Field, Seg, Pills, useToast, Confirm, Skeleton } from '../components/ui'
import BoardCanvas from '../components/BoardCanvas'
import { STICKY, RATIOS, FONTS, FONT_LABEL, FONT_SIZES, TEXT_COLORS, INK_COLORS, fmtSec, fontSize, plural, themeColor } from '../lib/board'
import { useRefresh } from '../App'

const KIND_RU = { free: 'свободная', storyboard: 'раскадровка', script: 'сценарий' }
const TOOLS = [
  ['hand', Hand, 'рука — двигать холст', 'H'], ['select', MousePointer2, 'выбрать', 'V'], ['sticky', StickyNote, 'стикер — нажми или протяни', 'S'], ['text', Type, 'текст', 'T'],
  ['frame', Film, 'кадр раскадровки', 'F'], ['arrow', ArrowUpRight, 'стрелка', 'A'], ['pen', Pencil, 'карандаш', 'P'], ['eraser', Eraser, 'ластик', 'E'], ['image', ImageIcon, 'картинка', 'I'],
]
const SHORTCUTS = [
  ['Колесо', 'двигать холст'], ['Ctrl + колесо / пинч', 'масштаб'], ['Пробел + тянуть · средняя кнопка', 'двигать холст в любом режиме'], ['Ctrl+1 / Ctrl+2 / Ctrl+0', 'показать всё · выделенное · 100%'],
  ['H · V', 'рука · выбор'], ['S · T · F · A · P · E · I', 'стикер · текст · кадр · стрелка · карандаш · ластик · картинка'], ['Инструмент + протянуть', 'создать нужного размера (Shift — квадрат)'], ['Shift + инструмент', 'не переключаться на выбор после создания'],
  ['Двойной клик', 'редактировать · по пустому — стикер'], ['Enter · Esc', 'редактировать выделенное · закончить'], ['Ctrl+Z · Ctrl+Shift+Z / Ctrl+Y', 'отменить · вернуть'], ['Ctrl+C · Ctrl+V · Ctrl+X · Ctrl+D', 'копировать · вставить · вырезать · дублировать'],
  ['Alt + тянуть', 'тянуть копию'], ['Shift + тянуть', 'строго по оси'], ['Ctrl + тянуть', 'прилипание к сетке'], ['Стрелки · Shift+стрелки', 'сдвиг на 1 · на 10'],
  ['Shift + клик · рамка', 'добавить к выделению · выделить рамкой'], ['Ctrl+A', 'выделить всё'], ['Delete · Backspace', 'удалить'], ['PgUp · PgDn', 'на передний · задний план'],
  ['Ручка над объектом', 'поворот (Shift — по 15°)'], ['Угол рамки', 'размер (у стикера, картинки и кадра — с пропорцией)'], ['Ctrl+V с картинкой', 'вставить картинку (в выделенный кадр — внутрь)'], ['Перетащить файл на холст', 'картинка (на кадр — внутрь кадра)'],
]

export default function BoardPage() { const { id } = useParams(); return id ? <BoardEditor id={Number(id)} /> : <BoardList /> }

/* ---------------------------------------------------------------- список досок */
function BoardList() {
  const [boards, setBoards] = useState(null)
  const [archived, setArchived] = useState(false)
  const [sheet, setSheet] = useState(false)
  const nav = useNavigate()
  const [, show] = useToast()
  const load = useCallback(() => api.get(`/api/boards${archived ? '?archived=true' : ''}`).then(setBoards).catch(() => setBoards([])), [archived])
  useEffect(() => { load() }, [load])
  const restore = async (e, b) => { e.stopPropagation(); try { await api.put(`/api/boards/${b.id}`, { archived: false }); load() } catch (er) { show.err(er) } }
  return (
    <div>
      <PageHead kicker="раскадровки · сценарии · мысли на плоскости" title="доска" idx={boards?.length}
        right={<div className="flex items-center gap-2">
          <Seg value={archived ? 'arch' : 'live'} onChange={(v) => setArchived(v === 'arch')} options={[['live', 'активные'], ['arch', 'архив']]} />
          <button className="btn-primary head-primary" onClick={() => setSheet(true)}><Plus size={15} /> доска</button>
        </div>} />
      {boards === null ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} h={150} />)}</div>
        : boards.length === 0 ? <Empty glyph="mind" text={archived ? 'В архиве пусто' : 'Досок пока нет'} sub={archived ? '' : 'Раскадровка ролика, сценарий, идеи россыпью — на одном бесконечном листе'} hint={archived ? undefined : 'раскадровка: ролик на 8 кадров'} onHint={archived ? undefined : () => setSheet(true)} />
        : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {boards.map((b) => (
              <button key={b.id} onClick={() => nav(`/board/${b.id}`)} className="card animate-rise group overflow-hidden text-left transition hover:-translate-y-0.5" style={{ padding: 0 }}>
                <div className="relative aspect-[16/9] w-full overflow-hidden" style={{ background: 'var(--fill)' }}>
                  {b.cover ? <img src={`/media/${b.cover}`} alt="" className="h-full w-full object-cover" /> : <BoardGlyph kind={b.kind} />}
                  <span className="label absolute left-3 top-3 rounded-md px-1.5 py-0.5" style={{ background: 'var(--surface)', color: 'var(--ink-2)' }}>{KIND_RU[b.kind]}</span>
                  {archived && <span onClick={(e) => restore(e, b)} className="btn-soft btn-sm absolute right-3 top-3">вернуть</span>}
                </div>
                <div className="p-4">
                  <div className="truncate text-[15px] font-semibold tracking-[-0.01em]">{b.title}</div>
                  <div className="muted mt-1 flex items-center gap-2 truncate text-[12.5px]">
                    <span>{b.items} {plural(b.items, 'объект', 'объекта', 'объектов')}</span>
                    {b.order_title && <span className="flex items-center gap-1 truncate"><Briefcase size={11} />{b.order_title}</span>}
                    {b.aim_title && <span className="flex items-center gap-1 truncate"><Target size={11} />{b.aim_title}</span>}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      <NewBoardSheet open={sheet} onClose={() => setSheet(false)} onDone={(b) => { setSheet(false); nav(`/board/${b.id}`) }} onErr={show.err} />
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
  const [f, setF] = useState({ title: '', kind: 'storyboard', frames: 8, ratio: '16:9' })
  const [orders, setOrders] = useState([])
  useEffect(() => { if (open) { setF({ title: '', kind: 'storyboard', frames: 8, ratio: '16:9', order_id: orderId || null }); api.get('/api/orders').then(setOrders).catch(() => setOrders([])) } }, [open, orderId])
  const submit = async (e) => {
    e.preventDefault(); if (!f.title.trim()) return
    try { onDone(await api.post('/api/boards', { title: f.title.trim(), kind: f.kind, frames: f.kind === 'storyboard' ? Number(f.frames) || 0 : 0, ratio: f.ratio, order_id: f.order_id || null, aim_id: aimId || null })) } catch (er) { onErr?.(er) }
  }
  return (
    <Sheet open={open} onClose={onClose} title="новая доска">
      <form onSubmit={submit} className="space-y-4">
        <Field label="название"><input autoFocus className="input" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Ролик для Пятёрочки" /></Field>
        <Field label="тип">
          <Pills value={f.kind} onChange={(v) => setF({ ...f, kind: v })} options={[['storyboard', 'раскадровка'], ['script', 'сценарий'], ['free', 'свободная']]} />
          <div className="muted mt-2 text-[12.5px]">{f.kind === 'storyboard' ? 'Сетка пустых кадров под нужное соотношение: подписи, картинки, длительность — хронометраж считается сам.' : f.kind === 'script' ? 'Один длинный текст с шаблоном сцен. Рядом можно раскладывать стикеры и референсы.' : 'Пустой лист: стикеры, тексты, картинки, стрелки, карандаш.'}</div>
        </Field>
        {f.kind === 'storyboard' && <div className="grid grid-cols-2 gap-3">
          <Field label="кадров"><input type="number" min={0} max={60} className="input num" value={f.frames} onChange={(e) => setF({ ...f, frames: e.target.value })} /></Field>
          <Field label="соотношение"><select className="input" value={f.ratio} onChange={(e) => setF({ ...f, ratio: e.target.value })}>{Object.keys(RATIOS).map((r) => <option key={r} value={r}>{r}{r === '9:16' ? ' · рилсы' : r === '16:9' ? ' · ютуб' : r === '2.39:1' ? ' · кино' : ''}</option>)}</select></Field>
        </div>}
        {orders.length > 0 && !orderId && <Field label="доска заказа" hint="ассистент будет знать её содержимое в контексте заказа">
          <select className="input" value={f.order_id || ''} onChange={(e) => setF({ ...f, order_id: Number(e.target.value) || null, title: f.title || orders.find((o) => o.id === Number(e.target.value))?.title || '' })}><option value="">— нет —</option>{orders.map((o) => <option key={o.id} value={o.id}>{o.title}{o.client ? ` · ${o.client}` : ''}</option>)}</select>
        </Field>}
        <button className="btn-primary w-full" type="submit">создать</button>
      </form>
    </Sheet>
  )
}

/* ---------------------------------------------------------------- редактор */
function BoardEditor({ id }) {
  const [board, setBoard] = useState(null)
  const [err, setErr] = useState(null)
  const [tool, setTool] = useState('hand')
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
  const frames = useMemo(() => (controls.current?.items?.() || board?.items || []).filter((i) => i.type === 'frame').sort((a, b) => (a.data.n || 0) - (b.data.n || 0)), [board, status, selection, tick]) // eslint-disable-line
  const total = frames.reduce((a, f) => a + (+f.data.seconds || 0), 0)

  const pick = (t) => { if (t === 'image') { fileRef.current?.click(); return } setTool(t) }
  const exportPng = (onlySel) => { const url = controls.current.exportPng(onlySel); if (!url) { show('Нечего экспортировать', 'err'); return } const a = document.createElement('a'); a.href = url; a.download = `${board.title}${onlySel ? ' — выделенное' : ''}.png`; a.click() }
  const exportStoryboard = () => {
    const fr = controls.current.items().filter((i) => i.type === 'frame').sort((a, b) => (a.data.n || 0) - (b.data.n || 0))
    if (!fr.length) { show('На доске нет кадров', 'err'); return }
    const w = window.open('', '_blank'); if (!w) { show('Браузер заблокировал окно печати', 'err'); return }
    w.document.write(storyboardHtml(board, fr)); w.document.close(); setTimeout(() => w.print(), 500)
  }
  const askAssistant = () => window.dispatchEvent(new CustomEvent('assistant:chat', { detail: { text: `что по доске «${board.title}»?`, send: true } }))
  const rename = async (t) => { setRenaming(false); if (!t.trim() || t === board.title) return; try { const b = await api.put(`/api/boards/${id}`, { title: t.trim() }); setBoard((x) => ({ ...x, title: b.title })); bump() } catch (e) { show.err(e) } }
  const patchSel = (data) => controls.current.setSelData(data)

  if (err) return <div className="py-16 text-center"><div className="label mb-2">доска</div><div className="h1-sm">не нашлась</div><button className="btn-soft btn-sm mt-4" onClick={() => nav('/board')}>к списку</button></div>
  if (!board) return <Skeleton h={480} />
  const sel1 = selection.length === 1 ? selection[0] : null
  const types = new Set(selection.map((s) => s.type))
  const textLike = selection.filter((s) => ['sticky', 'text', 'frame', 'arrow'].includes(s.type))
  const first = textLike[0]
  const showTextBar = textLike.length > 0 && tool === 'select'
  const showStickyBar = tool === 'sticky' || types.has('sticky')
  const showPenBar = tool === 'pen' || tool === 'arrow' || types.has('ink') || types.has('arrow')
  const showFrameBar = tool === 'frame' || types.has('frame')

  return (
    <div className="board-page-root -mx-4 -mt-6 flex flex-col sm:-mx-8 sm:-mt-8" style={{ height: 'calc(100dvh - var(--topbar-h))' }}>
      {/* шапка */}
      <div className="flex shrink-0 items-center gap-2 border-b hair px-2 py-1.5 sm:px-4" style={{ background: 'var(--bg)' }}>
        <button className="btn-icon" onClick={() => nav('/board')} aria-label="К списку досок" data-tip="все доски"><ChevronLeft size={16} /></button>
        <div className="min-w-0 flex-1">
          {renaming ? <input autoFocus className="input !h-8 max-w-[360px] !text-[14px]" defaultValue={board.title} onBlur={(e) => rename(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') setRenaming(false) }} />
            : <button className="max-w-full truncate text-left text-[15px] font-semibold tracking-[-0.01em] hover:opacity-70" onClick={() => setRenaming(true)} title="переименовать">{board.title}</button>}
          <div className="muted flex items-center gap-2 text-[11.5px]">
            <span>{KIND_RU[board.kind]}</span>
            {board.order_title && <span className="hidden items-center gap-1 sm:flex"><Briefcase size={10} />{board.order_title}</span>}
            {frames.length > 0 && <span className="hidden sm:inline">· {frames.length} {plural(frames.length, 'кадр', 'кадра', 'кадров')}{total ? ` · ${fmtSec(total)}` : ''}</span>}
            <span className={`ml-1 transition ${status === 'dirty' ? 'opacity-70' : status === 'err' || status === 'conflict' ? 'neg' : 'opacity-40'}`}>{status === 'dirty' ? 'сохраняю…' : status === 'err' ? 'не сохранилось — повторю' : status === 'conflict' ? 'доска изменилась в другом месте' : 'сохранено'}</span>
          </div>
        </div>
        <div className="hidden items-center gap-0.5 md:flex">
          <button className="btn-icon" onClick={() => controls.current.undo()} data-tip="отменить · Ctrl+Z" aria-label="Отменить"><Undo2 size={15} /></button>
          <button className="btn-icon" onClick={() => controls.current.redo()} data-tip="вернуть · Ctrl+Shift+Z" aria-label="Вернуть"><Redo2 size={15} /></button>
          <div className="mx-1 h-5 w-px" style={{ background: 'var(--line)' }} />
          <button className="btn-icon" onClick={() => controls.current.zoomOut()} aria-label="Отдалить" data-tip="Ctrl −"><Minus size={15} /></button>
          <button className="mono min-w-[54px] rounded-md px-1.5 py-1 text-center text-[12px] hover:bg-[var(--fill)]" onClick={() => controls.current.zoomTo(1)} data-tip="100% · Ctrl+0">{Math.round(zoom * 100)}%</button>
          <button className="btn-icon" onClick={() => controls.current.zoomIn()} aria-label="Приблизить" data-tip="Ctrl +"><Plus size={15} /></button>
          <button className="btn-icon" onClick={() => controls.current.fit()} data-tip="показать всё · Ctrl+1" aria-label="Показать всё"><Maximize2 size={15} /></button>
          {selection.length > 0 && <button className="btn-icon" onClick={() => controls.current.fitSelection()} data-tip="к выделенному · Ctrl+2" aria-label="К выделенному"><Focus size={15} /></button>}
          <div className="mx-1 h-5 w-px" style={{ background: 'var(--line)' }} />
          <button className="btn-icon" onClick={() => setKeysSheet(true)} data-tip="горячие клавиши" aria-label="Горячие клавиши"><Keyboard size={15} /></button>
          <button className="btn-ghost btn-sm ml-1" onClick={askAssistant}><MessageCircle size={14} /> обсудить</button>
        </div>
        <div className="relative">
          <button className="btn-icon" onClick={() => setMenu((v) => !v)} aria-label="Меню доски"><MoreHorizontal size={16} /></button>
          {menu && <div className="elevated absolute right-0 top-[42px] z-[70] w-[250px] !p-1.5 text-[13px]" onMouseLeave={() => setMenu(false)}>
            <MenuItem icon={Download} onClick={() => { setMenu(false); exportPng(false) }}>экспорт PNG — вся доска</MenuItem>
            {selection.length > 0 && <MenuItem icon={Download} onClick={() => { setMenu(false); exportPng(true) }}>экспорт PNG — выделенное</MenuItem>}
            {frames.length > 0 && <MenuItem icon={Film} onClick={() => { setMenu(false); exportStoryboard() }}>раскадровка в PDF (печать)</MenuItem>}
            <MenuItem icon={LayoutGrid} onClick={() => { setMenu(false); setGridSheet(true) }}>добавить сетку кадров…</MenuItem>
            <MenuItem icon={Keyboard} onClick={() => { setMenu(false); setKeysSheet(true) }}>горячие клавиши</MenuItem>
            <div className="my-1 border-t hair" />
            <MenuItem icon={MessageCircle} onClick={() => { setMenu(false); askAssistant() }}>что по этой доске? (чат)</MenuItem>
            <MenuItem icon={Type} onClick={() => { setMenu(false); setRenaming(true) }}>переименовать</MenuItem>
            <MenuItem icon={Archive} onClick={() => { setMenu(false); setConfirmArch(true) }} danger>в архив</MenuItem>
          </div>}
        </div>
      </div>

      {/* контекстная панель — своя строка под шапкой, ничего не перекрывает */}
      <div className="board-ctx flex h-[44px] shrink-0 items-center gap-x-3 overflow-x-auto overflow-y-hidden whitespace-nowrap border-b hair px-3 text-[12.5px]" style={{ background: 'var(--surface)' }}>
        {!showTextBar && !showStickyBar && !showPenBar && !showFrameBar && <span className="muted">{tool === 'hand' ? 'Рука: тяни холст, колесо — двигать, Ctrl+колесо — масштаб. V — выбор объектов.' : tool === 'select' ? 'Клик — выбрать, рамкой — несколько, двойной клик — редактировать. H — рука.' : tool === 'eraser' ? 'Ластик: проведи по штриху карандаша.' : tool === 'image' ? 'Картинка: файл или Ctrl+V из буфера.' : 'Нажми или протяни на холсте, чтобы создать.'}</span>}
        {showStickyBar && <Group label="цвет">{Object.keys(STICKY).map((c) => <Swatch key={c} color={STICKY[c][document.documentElement.classList.contains('dark') ? 'dark' : 'light']} on={(sel1?.type === 'sticky' ? sel1.data.color : style.stickyColor) === c} onClick={() => { setStyle({ ...style, stickyColor: c }); if (types.has('sticky')) patchSel({ color: c }) }} label={c} />)}</Group>}
        {showFrameBar && <Group label="кадр">{Object.keys(RATIOS).map((r) => <button key={r} onClick={() => { setStyle({ ...style, ratio: r }); if (types.has('frame')) patchSel({ ratio: r }) }} className={`mono rounded-full px-2 py-0.5 text-[11px] ${(types.has('frame') ? sel1?.data?.ratio === r : style.ratio === r) ? 'bg-[var(--ink)] text-[var(--bg)]' : 'hover:bg-[var(--fill)]'}`}>{r}</button>)}
          {sel1?.type === 'frame' && <><span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} /><label className="flex items-center gap-1.5"><Clock size={12} className="faint" /><input type="number" min={0} step={0.5} className="input !h-7 !w-[64px] num !px-2 !text-[12px]" aria-label="Длительность кадра" value={sel1.data.seconds || ''} placeholder="сек" onChange={(e) => patchSel({ seconds: Number(e.target.value) || 0 })} /></label>
            <button className="btn-soft btn-sm !h-7" onClick={() => fileRef.current?.click()}><ImageIcon size={12} /> картинка</button>{sel1.data.image && <button className="btn-icon !h-7 !w-7" data-tip="убрать картинку" aria-label="Убрать картинку" onClick={() => patchSel({ image: null })}><X size={12} /></button>}</>}
        </Group>}
        {showPenBar && <Group label={tool === 'arrow' || types.has('arrow') ? 'линия' : 'карандаш'}>
          {INK_COLORS.map((c) => <Swatch key={c} color={themeColor(c, document.documentElement.classList.contains('dark'))} on={(types.has('ink') || types.has('arrow') ? (sel1?.data?.color || 'ink') : style.inkColor) === c} onClick={() => { setStyle({ ...style, inkColor: c }); if (types.has('ink') || types.has('arrow')) patchSel({ color: c }) }} label={c} />)}
          <span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} />
          {[2, 3, 6, 10].map((w) => <button key={w} onClick={() => { setStyle({ ...style, inkWidth: w }); if (types.has('ink') || types.has('arrow')) patchSel({ width: w }) }} aria-label={`толщина ${w}`} className={`grid h-6 w-6 place-items-center rounded-full ${(types.has('ink') || types.has('arrow') ? (sel1?.data?.width || 3) === w : style.inkWidth === w) ? 'bg-[var(--fill-2)]' : 'hover:bg-[var(--fill)]'}`}><span className="rounded-full" style={{ width: w + 2, height: w + 2, background: 'var(--ink)' }} /></button>)}
          {types.has('arrow') && <><span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} /><Seg value={sel1?.data?.style || 'arrow'} onChange={(v) => patchSel({ style: v })} options={[['arrow', 'стрелка'], ['line', 'линия']]} /></>}
        </Group>}
        {showTextBar && first && <Group label="текст">
          <select className="input !h-7 !w-[92px] !rounded-lg !px-2 !text-[12px]" value={first.data.font || 'inter'} onChange={(e) => patchSel({ font: e.target.value })} aria-label="Шрифт">{Object.keys(FONTS).map((f) => <option key={f} value={f}>{FONT_LABEL[f]}</option>)}</select>
          <SizeInput value={Math.round(fontSize(first))} onChange={(v) => patchSel({ font_size: v })} />
          <button className={`btn-icon !h-7 !w-7 ${first.data.bold ? 'bg-[var(--fill-2)]' : ''}`} onClick={() => patchSel({ bold: !first.data.bold })} aria-label="Жирный" data-tip="жирный"><Bold size={13} /></button>
          <button className={`btn-icon !h-7 !w-7 ${first.data.italic ? 'bg-[var(--fill-2)]' : ''}`} onClick={() => patchSel({ italic: !first.data.italic })} aria-label="Курсив" data-tip="курсив"><Italic size={13} /></button>
          {[['left', AlignLeft], ['center', AlignCenter], ['right', AlignRight]].map(([a, I]) => <button key={a} className={`btn-icon !h-7 !w-7 ${(first.data.align || 'left') === a ? 'bg-[var(--fill-2)]' : ''}`} onClick={() => patchSel({ align: a })} aria-label={a}><I size={13} /></button>)}
          <span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} />
          {TEXT_COLORS.map((c) => <Swatch key={c} color={themeColor(c, document.documentElement.classList.contains('dark'))} on={(first.data.text_color || (first.type === 'sticky' ? '' : 'ink')) === c} onClick={() => patchSel({ text_color: c })} label={c} />)}
          <input type="color" className="h-6 w-7 cursor-pointer rounded border-0 bg-transparent p-0" value={/^#/.test(first.data.text_color || '') ? first.data.text_color : '#3b5bff'} onChange={(e) => patchSel({ text_color: e.target.value })} aria-label="Свой цвет" title="свой цвет" />
        </Group>}
        {selection.length > 0 && <div className="ml-auto flex shrink-0 items-center gap-0.5 pl-3">
          {selection.length > 1 && <>{[['left', 'по левому'], ['hcenter', 'по центру'], ['right', 'по правому'], ['top', 'по верху'], ['vcenter', 'по середине'], ['bottom', 'по низу'], ['row', 'в ряд']].map(([h, l]) => <button key={h} className="rounded-md px-1.5 py-0.5 text-[11.5px] hover:bg-[var(--fill)]" onClick={() => controls.current.alignSel(h)}>{l}</button>)}<span className="mx-1 h-4 w-px" style={{ background: 'var(--line)' }} /></>}
          <button className="btn-icon !h-7 !w-7" onClick={() => controls.current.duplicateSel()} data-tip="дублировать · Ctrl+D" aria-label="Дублировать"><Copy size={13} /></button>
          <button className="btn-icon !h-7 !w-7 neg" onClick={() => controls.current.deleteSel()} data-tip="удалить · Delete" aria-label="Удалить"><Trash2 size={13} /></button>
        </div>}
      </div>

      {conflict && <div className="flex shrink-0 flex-wrap items-center gap-2 border-b hair px-3 py-1.5 text-[12.5px]" style={{ background: 'var(--warn-soft)' }}>
        <RefreshCw size={13} /> Доску изменили в другой вкладке или из чата.
        <button className="btn-soft btn-sm !h-7" onClick={() => { controls.current.adoptFresh(conflict, true); setConflict(null); setStatus('saved') }}>подтянуть и оставить мои правки</button>
        <button className="btn-ghost btn-sm !h-7" onClick={() => { controls.current.adoptFresh(conflict, false); setConflict(null); setStatus('saved') }}>взять их версию</button>
      </div>}

      <div className="relative flex min-h-0 flex-1">
        {/* панель инструментов: слева, вне холста, чтобы не прятать объекты */}
        <div className="hidden shrink-0 flex-col items-center gap-0.5 border-r hair px-1.5 py-2 md:flex" style={{ background: 'var(--surface)' }}>
          {TOOLS.map(([t, I, label, key]) => (
            <button key={t} onClick={() => pick(t)} data-tip={`${label} · ${key}`} data-tip-side="right" aria-label={label}
              className={`grid h-9 w-9 place-items-center rounded-xl transition ${tool === t ? '' : 'hover:bg-[var(--fill)]'}`} style={tool === t ? { background: 'var(--ink)', color: 'var(--bg)' } : {}}><I size={16} /></button>
          ))}
          {board.kind !== 'script' && <><div className="my-1 w-6 border-t hair" /><button onClick={() => controls.current.addFrameNext()} data-tip="следующий кадр" data-tip-side="right" aria-label="Следующий кадр" className="grid h-9 w-9 place-items-center rounded-xl hover:bg-[var(--fill)]"><Plus size={16} /></button></>}
        </div>

        <div className="min-w-0 flex-1">
          <BoardCanvas board={board} tool={tool} setTool={setTool} style={style} onDirty={onDirty} onSelectionChange={setSelection} onViewChange={(v) => setZoom(v.k)} controlsRef={controls} />
        </div>

        {side && board.kind !== 'free' && frames.length > 0 && (
          <aside aria-label="Кадры" className="hidden w-[250px] shrink-0 overflow-y-auto border-l hair p-3 lg:block" style={{ background: 'var(--surface)' }}>
            <div className="mb-2 flex items-center justify-between"><div className="label">кадры · {frames.length}{total ? ` · ${fmtSec(total)}` : ''}</div><button className="btn-icon !h-7 !w-7" onClick={() => setSide(false)} aria-label="Скрыть"><X size={13} /></button></div>
            <div className="space-y-0.5">{frames.map((f) => (
              <button key={f.id} onClick={() => controls.current.focusItem(f.id)} className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-[var(--fill)] ${sel1?.id === f.id ? 'bg-[var(--fill)]' : ''}`}>
                <span className="mono mt-0.5 w-5 shrink-0 text-[11.5px] font-semibold" style={{ color: 'var(--ink-2)' }}>{f.data.n}</span>
                <span className="min-w-0 flex-1"><span className={`block truncate text-[13px] ${f.data.label ? '' : 'faint'}`}>{f.data.label || 'без подписи'}</span><span className="faint mono text-[11px]">{f.data.image ? 'картинка' : 'пусто'}{f.data.seconds ? ` · ${fmtSec(f.data.seconds)}` : ''}</span></span>
              </button>))}</div>
            <button className="btn-soft btn-sm mt-3 w-full" onClick={() => controls.current.addFrameNext()}><Plus size={14} /> кадр</button>
          </aside>
        )}
        {!side && board.kind !== 'free' && frames.length > 0 && <button className="btn-soft btn-sm absolute right-3 top-3 z-10 hidden lg:inline-flex" onClick={() => setSide(true)}><Film size={13} /> кадры</button>}

        {/* телефон */}
        <div className="absolute inset-x-0 bottom-0 z-20 flex items-center justify-around gap-1 border-t hair px-2 py-1.5 md:hidden" style={{ background: 'var(--surface)' }}>
          {TOOLS.filter(([t]) => ['hand', 'select', 'sticky', 'text', 'frame', 'pen'].includes(t)).map(([t, I, label]) => <button key={t} onClick={() => pick(t)} aria-label={label} className="grid h-10 w-10 place-items-center rounded-xl" style={tool === t ? { background: 'var(--ink)', color: 'var(--bg)' } : {}}><I size={17} /></button>)}
          <button onClick={() => controls.current.undo()} aria-label="Отменить" className="grid h-10 w-10 place-items-center rounded-xl"><Undo2 size={17} /></button>
          <button onClick={() => controls.current.fit()} aria-label="Показать всё" className="grid h-10 w-10 place-items-center rounded-xl"><Maximize2 size={17} /></button>
          {selection.length > 0 && <button onClick={() => controls.current.deleteSel()} aria-label="Удалить" className="neg grid h-10 w-10 place-items-center rounded-xl"><Trash2 size={17} /></button>}
        </div>
      </div>

      <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { const fs = [...e.target.files]; e.target.value = ''; if (!fs.length) return; const fr = sel1?.type === 'frame' && fs.length === 1 ? sel1.id : null; fs.forEach((f) => controls.current.uploadImage(f, fr)) }} />
      <Confirm open={confirmArch} onClose={() => setConfirmArch(false)} title="Доску в архив?" text="Ничего не удаляется: доска пропадёт из списка, вернуть можно из вкладки «архив»." onOk={async () => { try { await controls.current.flushNow(); await api.del(`/api/boards/${id}`); bump(); nav('/board') } catch (e) { show.err(e) } }} />
      <Sheet open={gridSheet} onClose={() => setGridSheet(false)} title="сетка кадров"><GridForm ratio={style.ratio} onDone={(n, ratio) => { setGridSheet(false); controls.current.addFramesGrid(n, ratio) }} /></Sheet>
      <Sheet open={keysSheet} onClose={() => setKeysSheet(false)} title="горячие клавиши" wide>
        <div className="grid gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-2">{SHORTCUTS.map(([k, v]) => <div key={k} className="flex items-baseline justify-between gap-3 border-b hair py-1.5"><span className="mono text-[12px]" style={{ color: 'var(--ink-2)' }}>{k}</span><span className="text-right">{v}</span></div>)}</div>
      </Sheet>
    </div>
  )
}

function Group({ label, children }) { return <div className="flex shrink-0 items-center gap-1"><span className="label mr-1 !text-[10px]">{label}</span>{children}</div> }
function Swatch({ color, on, onClick, label }) { return <button onClick={onClick} aria-label={label} className="h-5 w-5 rounded-full border-2 transition hover:scale-110" style={{ background: color, borderColor: on ? 'var(--ink)' : 'transparent', boxShadow: on ? '0 0 0 1px var(--bg) inset' : '0 0 0 1px var(--line) inset' }} /> }
function SizeInput({ value, onChange }) {
  const [v, setV] = useState(value); useEffect(() => setV(value), [value])
  const commit = (n) => { n = Math.max(6, Math.min(240, Math.round(Number(n) || value))); setV(n); if (n !== value) onChange(n) }
  return <div className="flex items-center">
    <button className="btn-icon !h-7 !w-6" onClick={() => commit(FONT_SIZES.filter((s) => s < value).pop() || value - 1)} aria-label="Меньше">−</button>
    <input className="input !h-7 !w-[46px] num !px-1 !text-center !text-[12px]" value={v} list="board-font-sizes" onChange={(e) => setV(e.target.value)} onBlur={(e) => commit(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }} aria-label="Размер шрифта" />
    <datalist id="board-font-sizes">{FONT_SIZES.map((s) => <option key={s} value={s} />)}</datalist>
    <button className="btn-icon !h-7 !w-6" onClick={() => commit(FONT_SIZES.find((s) => s > value) || value + 1)} aria-label="Больше">+</button>
  </div>
}
function MenuItem({ icon: I, children, onClick, danger }) { return <button className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left hover:bg-[var(--fill)] ${danger ? 'neg' : ''}`} onClick={onClick}><I size={14} className="faint" />{children}</button> }
function GridForm({ onDone, ratio: r0 }) {
  const [n, setN] = useState(6); const [ratio, setRatio] = useState(r0 || '16:9')
  return <div className="space-y-4">
    <div className="grid grid-cols-2 gap-3"><Field label="кадров"><input type="number" min={1} max={40} className="input num" value={n} onChange={(e) => setN(Number(e.target.value))} /></Field><Field label="соотношение"><select className="input" value={ratio} onChange={(e) => setRatio(e.target.value)}>{Object.keys(RATIOS).map((r) => <option key={r}>{r}</option>)}</select></Field></div>
    <button className="btn-primary w-full" onClick={() => onDone(Math.max(1, Math.min(40, n)), ratio)}>добавить</button>
  </div>
}
function storyboardHtml(board, frames) {
  const esc = (s) => String(s || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])
  const total = frames.reduce((a, f) => a + (+f.data.seconds || 0), 0)
  const cells = frames.map((f) => `<div class="c"><div class="p" style="aspect-ratio:${RATIOS[f.data.ratio] || 16 / 9}">${f.data.image ? `<img src="${location.origin}/media/${esc(f.data.image)}">` : ''}</div><div class="m"><b>${f.data.n}</b>${f.data.seconds ? `<span>${fmtSec(f.data.seconds)}</span>` : ''}</div><div class="l">${esc(f.data.label)}</div></div>`).join('')
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>${esc(board.title)} — раскадровка</title>
  <style>@page{margin:14mm}body{font:12px/1.4 -apple-system,Inter,system-ui,sans-serif;color:#111;margin:0}h1{font-size:20px;margin:0 0 2px;letter-spacing:-.02em}.s{color:#666;margin-bottom:14px}.g{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.c{break-inside:avoid}.p{background:#f2f2f0;border:1px solid #ddd;border-radius:6px;overflow:hidden}.p img{width:100%;height:100%;object-fit:cover;display:block}.m{display:flex;justify-content:space-between;margin-top:6px;font-family:ui-monospace,monospace;font-size:11px;color:#444}.l{margin-top:2px;min-height:2.6em;white-space:pre-wrap}</style></head>
  <body><h1>${esc(board.title)}</h1><div class="s">${frames.length} кадров${total ? ` · хронометраж ${fmtSec(total)}` : ''}${board.order_title ? ` · заказ «${esc(board.order_title)}»` : ''}</div><div class="g">${cells}</div></body></html>`
}
