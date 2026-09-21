import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { StickyNote, Type, Film, Pencil, Trash2, Copy, ArrowUpRight, ChevronDown, Lock } from 'lucide-react'
import { api } from '../lib/api'
import { RATIOS, STICKY, DEFAULT_SIZE, MIN_K, MAX_K, uid, fontSize, fontFamily, frameHeight, frameWindow, captionHeight, itemBox, bbox, inBox, normRect, rectsIntersect, distSeg, anchorPoint, nearestAnchor, arrowPoints, fmtSec, themeColor, stickyInk } from '../lib/board'

/* Холст доски. Canvas: сетка, кадры, картинки, стрелки, карандаш, выделение. HTML-слой поверх: текст стикеров,
   текстовых блоков и подписей кадров (правка на месте, тот же шрифт что на сайте).
   Объекты — в ref (много правок при перетаскивании), в React — только выделение/инструмент/счётчик перерисовок.
   Сохранение: вся доска одним снимком (`PUT /sync`, ревизия + ключ) через 0,5 с после последнего жеста;
   ответ сервера подменяет временные id. Undo/Redo — снимки в памяти, применяются тем же путём. */

const HANDLE = 7
const isDark = () => document.documentElement.classList.contains('dark')
const byIdOf = (items) => new Map(items.map((i) => [i.id, i]))
const clone = (items) => JSON.parse(JSON.stringify(items))
let keySeq = 0
const withKey = (i) => { if (!i._key) i._key = `k${++keySeq}`; return i }
const strip = (i) => i && ({ type: i.type, x: +(+i.x).toFixed(1), y: +(+i.y).toFixed(1), w: +(+i.w).toFixed(1), h: +(+i.h).toFixed(1), rot: i.rot || 0, data: i.data })
const tokenNew = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '') : Math.random().toString(36).slice(2) + Date.now().toString(36))

export default function BoardCanvas({ board, tool, setTool, style, onDirty, onSelectionChange, onViewChange, controlsRef, readOnly = false }) {
  const wrapRef = useRef(null), canvasRef = useRef(null)
  const itemsRef = useRef([])
  const [ver, setVer] = useState(0); const bump = useCallback(() => setVer((v) => v + 1), [])
  const viewRef = useRef({ x: 0, y: 0, k: 1 }); const [view, setView] = useState(viewRef.current)
  const [sel, setSelState] = useState(() => new Set()); const selRef = useRef(sel)
  const setSel = useCallback((v) => { selRef.current = v; setSelState(v) }, [])
  const [editing, setEditingState] = useState(null); const editingRef = useRef(null)
  const setEditing = useCallback((v) => { editingRef.current = v; setEditingState(v) }, [])
  const editSnap = useRef(null)
  const [marquee, setMarquee] = useState(null)
  const [ghost, setGhost] = useState(null)          // рамка создаваемого объекта (протягивание)
  const [hoverEnd, setHoverEnd] = useState(null)    // объект под курсором при протяжке стрелки
  const [ctx, setCtx] = useState(null)
  const [spaceDown, setSpaceDown] = useState(false)
  const dragRef = useRef(null), imgCache = useRef(new Map()), toolRef = useRef(tool); toolRef.current = tool
  const styleRef = useRef(style); styleRef.current = style
  const undoRef = useRef([]), redoRef = useRef([])
  const revRef = useRef(0), pendingRef = useRef(null), saveTimer = useRef(null), inflightRef = useRef(false), againRef = useRef(false)
  const cbRef = useRef({}); cbRef.current = { onDirty, onSelectionChange, onViewChange, setTool }
  const fn = useRef({})                              // draw/fitAll/exportPng/schedule вызываются раньше объявления
  const clipRef = useRef(null), fileInputRef = useRef(null), imageDrop = useRef(null)
  const [hoverAnchor, setHoverAnchor] = useState(null)

  /* ---------- загрузка ---------- */
  useEffect(() => {
    itemsRef.current = clone(board.items || []).map((i) => withKey(i.type === 'frame' ? { ...i, h: frameHeight(i.w, i.data) } : i))
    revRef.current = board.revision || 0
    undoRef.current = []; redoRef.current = []; pendingRef.current = null
    setSel(new Set()); setEditing(null)
    const el = wrapRef.current, v = board.view
    let ok = false
    if (v && Number.isFinite(v.k) && el) {
      const b = bbox(itemsRef.current)
      if (!b) ok = true
      else { const cx = (b.x + b.w / 2) * v.k + v.x, cy = (b.y + b.h / 2) * v.k + v.y; ok = cx > 0 && cy > 0 && cx < el.clientWidth && cy < el.clientHeight }
    }
    if (ok) fn.current.setViewNow?.({ x: v.x, y: v.y, k: Math.min(MAX_K, Math.max(MIN_K, v.k)) }, false)
    else fn.current.fitAll?.()
    bump()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board.id])

  /* ---------- камера ---------- */
  const viewTimer = useRef(null)
  const setViewNow = useCallback((v, persist = true) => {
    viewRef.current = v; setView(v); cbRef.current.onViewChange?.(v)
    if (!persist) return
    clearTimeout(viewTimer.current)
    viewTimer.current = setTimeout(() => api.put(`/api/boards/${board.id}`, { view: { x: Math.round(v.x), y: Math.round(v.y), k: +v.k.toFixed(3) } }).catch(() => {}), 1200)
  }, [board.id])
  fn.current.setViewNow = setViewNow
  const toWorld = useCallback((cx, cy) => { const v = viewRef.current, r = wrapRef.current.getBoundingClientRect(); return { x: (cx - r.left - v.x) / v.k, y: (cy - r.top - v.y) / v.k } }, [])
  const zoomAt = useCallback((factor, cx, cy) => {
    const v = viewRef.current, r = wrapRef.current.getBoundingClientRect()
    const px = cx == null ? r.width / 2 : cx - r.left, py = cy == null ? r.height / 2 : cy - r.top
    const k = Math.min(MAX_K, Math.max(MIN_K, v.k * factor))
    setViewNow({ x: px - (px - v.x) / v.k * k, y: py - (py - v.y) / v.k * k, k })
  }, [setViewNow])
  const fitTo = useCallback((b, maxK = 1.5) => {
    const el = wrapRef.current; if (!el) return
    const W = el.clientWidth, H = el.clientHeight
    if (!b) { setViewNow({ x: W / 2 - 200, y: 120, k: 1 }); return }
    const pad = Math.min(80, W * .1)
    const k = Math.min(MAX_K, Math.max(MIN_K, Math.min((W - pad * 2) / Math.max(b.w, 1), (H - pad * 2) / Math.max(b.h, 1), maxK)))
    setViewNow({ x: W / 2 - (b.x + b.w / 2) * k, y: H / 2 - (b.y + b.h / 2) * k, k })
  }, [setViewNow])
  const fitAll = useCallback(() => fitTo(bbox(itemsRef.current)), [fitTo])
  fn.current.fitAll = fitAll

  /* ---------- сохранение: вся доска одним снимком ---------- */
  const flush = useCallback(async () => {
    if (readOnly) return
    if (inflightRef.current) { againRef.current = true; return }
    const items = itemsRef.current
    const token = pendingRef.current || tokenNew(); pendingRef.current = token
    inflightRef.current = true
    try {
      const r = await api.put(`/api/boards/${board.id}/sync`, { revision: revRef.current, token, items: items.map((i) => ({ id: i.id, type: i.type, x: i.x, y: i.y, w: i.w, h: i.h, z: i.z || 0, rot: i.rot || 0, data: i.data, note_id: i.note_id, link_id: i.link_id })) })
      revRef.current = r.revision
      const map = r.id_map || {}
      let changed = false
      for (const it of itemsRef.current) {
        const nid = map[String(it.id)]
        if (nid != null && nid !== it.id) {
          const old = it.id; it.id = nid; changed = true
          for (const a of itemsRef.current) if (a.type === 'arrow') { if (a.data.from?.item === old) a.data.from = { ...a.data.from, item: nid }; if (a.data.to?.item === old) a.data.to = { ...a.data.to, item: nid } }
          if (selRef.current.has(old)) { const s = new Set(selRef.current); s.delete(old); s.add(nid); setSel(s) }
          if (editingRef.current === old) setEditing(nid)
        }
      }
      // id в истории тоже переименовать, иначе undo вернёт временные id
      if (changed) {
        const fix = (json) => { let t = json; for (const [o, n] of Object.entries(map)) if (String(n) !== o) t = t.replace(new RegExp(`"id":${o}(?=[,}])`, 'g'), `"id":${n}`).replace(new RegExp(`"item":${o}(?=[,}])`, 'g'), `"item":${n}`); return t }
        undoRef.current = undoRef.current.map(fix); redoRef.current = redoRef.current.map(fix)
        bump()
      }
      pendingRef.current = null
      cbRef.current.onDirty?.(againRef.current ? 'dirty' : 'saved')
    } catch (e) {
      pendingRef.current = null
      if (e.status === 409) {
        // доска изменилась в другой вкладке/из чата: подтянуть свежую версию, свои правки не терять — положить поверх
        try {
          const fresh = await api.get(`/api/boards/${board.id}`)
          revRef.current = fresh.revision
          cbRef.current.onDirty?.('conflict', fresh)
        } catch {}
      } else cbRef.current.onDirty?.('err', e)
    } finally {
      inflightRef.current = false
      if (againRef.current) { againRef.current = false; fn.current.schedule?.(0) }
    }
  }, [board.id, readOnly, bump, setSel, setEditing])
  const flushRef = useRef(flush); flushRef.current = flush
  const schedule = useCallback((ms = 500) => { if (readOnly) return; cbRef.current.onDirty?.('dirty'); clearTimeout(saveTimer.current); saveTimer.current = setTimeout(() => flushRef.current(), ms) }, [readOnly])
  fn.current.schedule = schedule
  useEffect(() => () => { clearTimeout(saveTimer.current); if (saveTimer.current) flushRef.current() }, [])
  useEffect(() => { const h = () => { if (saveTimer.current) { clearTimeout(saveTimer.current); flushRef.current() } }; window.addEventListener('beforeunload', h); return () => window.removeEventListener('beforeunload', h) }, [])
  /** «принять чужие изменения»: перезагрузить объекты, свои несохранённые — сверху с новыми id */
  const adoptFresh = useCallback((fresh, keepMine) => {
    if (editingRef.current) { document.activeElement?.blur(); stopEdit() }   // текст из открытого редактора — в объект, до слияния
    const serverIds = new Set((fresh.items || []).map((i) => i.id))
    // «мои» = то, чего на сервере нет (новые, id<0) + то, что я менял, но сервер ещё не видел (id есть, но объект отличается)
    const mine = keepMine ? itemsRef.current.filter((i) => i.id < 0 || (serverIds.has(i.id) && JSON.stringify(strip(i)) !== JSON.stringify(strip((fresh.items || []).find((f) => f.id === i.id))))).map((i) => (i.id < 0 ? i : { ...clone(i), id: uid(), _key: null })) : []
    for (const m of mine) withKey(m)
    const mineIds = new Set(mine.filter((m) => m.id > 0).map((m) => m.id))
    itemsRef.current = clone(fresh.items || []).filter((i) => !mineIds.has(i.id)).map((i) => withKey(i.type === 'frame' ? { ...i, h: frameHeight(i.w, i.data) } : i)).concat(mine)
    revRef.current = fresh.revision; undoRef.current = []; redoRef.current = []; setSel(new Set()); setEditing(null); bump()
    if (mine.length) schedule(0)
  }, [bump, schedule, setSel, setEditing])

  /* ---------- история ---------- */
  const snapshot = useCallback(() => { undoRef.current.push(JSON.stringify(itemsRef.current)); if (undoRef.current.length > 100) undoRef.current.shift(); redoRef.current = [] }, [])
  const applyJson = useCallback((json) => { itemsRef.current = JSON.parse(json).map(withKey); setSel(new Set()); setEditing(null); bump(); schedule(150) }, [bump, schedule, setSel, setEditing])
  const undo = useCallback(() => { const j = undoRef.current.pop(); if (!j) return; redoRef.current.push(JSON.stringify(itemsRef.current)); applyJson(j) }, [applyJson])
  const redo = useCallback(() => { const j = redoRef.current.pop(); if (!j) return; undoRef.current.push(JSON.stringify(itemsRef.current)); applyJson(j) }, [applyJson])
  const commit = useCallback(() => { bump(); schedule() }, [bump, schedule])
  /** закончить правку (Esc / клик мимо / blur): если текст не менялся — снимок из истории убрать */
  function stopEdit() {
    if (!editingRef.current) return
    const last = undoRef.current[undoRef.current.length - 1]
    if (editSnap.current === undoRef.current.length && last === JSON.stringify(itemsRef.current)) undoRef.current.pop()
    editSnap.current = null; setEditing(null); bump(); schedule()
  }
  /** начать правку текста: один снимок для undo на сеанс правки */
  function startEdit(id) {
    if (editingRef.current === id) return
    if (editingRef.current) stopEdit()
    undoRef.current.push(JSON.stringify(itemsRef.current)); if (undoRef.current.length > 100) undoRef.current.shift(); redoRef.current = []
    editSnap.current = undoRef.current.length; setEditing(id)
  }

  /* ---------- операции ---------- */
  const topZ = () => Math.max(0, ...itemsRef.current.map((i) => i.z || 0)) + 1
  const addItem = useCallback((type, x, y, data = {}, size) => {
    if (readOnly) return null
    snapshot()
    const st = styleRef.current || {}
    let [w, h] = size || DEFAULT_SIZE[type] || [200, 120]
    const base = type === 'sticky' ? { text: '', color: st.stickyColor || 'yellow', font_size: 20 } : type === 'text' ? { text: '', font_size: st.fontSize || 18 } : type === 'frame' ? { label: '', ratio: st.ratio || '16:9', image: null, seconds: 0, n: 0, font_size: 18 } : type === 'arrow' ? { style: 'arrow', width: st.inkWidth || 2, color: st.inkColor || 'ink' } : {}
    const d = { ...base, ...data }
    if (type === 'frame') { w = Math.max(60, w); h = frameHeight(w, d) }
    const it = withKey({ id: uid(), type, x, y, w, h, z: topZ(), rot: 0, data: d })
    itemsRef.current.push(it)
    if (type === 'frame') renumber()
    commit()
    return it
  }, [readOnly, snapshot, commit])
  /** номера кадров по положению: ряды по вертикальному перекрытию, внутри ряда слева направо (как на сервере) */
  function renumber() {
    const fr = itemsRef.current.filter((i) => i.type === 'frame').sort((a, b) => a.y - b.y || a.x - b.x)
    const rows = []
    for (const f of fr) { const row = rows.find((r) => Math.abs(r[0].y - f.y) < r[0].h * .5); if (row) row.push(f); else rows.push([f]) }
    let n = 0
    for (const row of rows) for (const f of row.sort((a, b) => a.x - b.x)) f.data.n = ++n
  }
  const selected = () => itemsRef.current.filter((i) => selRef.current.has(i.id))
  const deleteSel = useCallback(() => {
    if (readOnly || !selRef.current.size) return
    snapshot()
    const ids = new Set(selRef.current)
    for (const it of itemsRef.current) if (it.type === 'arrow' && (ids.has(it.data.from?.item) || ids.has(it.data.to?.item))) ids.add(it.id)
    itemsRef.current = itemsRef.current.filter((i) => !ids.has(i.id))
    renumber(); setSel(new Set()); setEditing(null); commit()
  }, [readOnly, snapshot, commit, setSel, setEditing])
  const duplicateSel = useCallback(() => {
    if (readOnly) return
    const src = selected().filter((i) => i.type !== 'arrow'); if (!src.length) return
    snapshot()
    const map = new Map(), made = []
    for (const s of src) {
      const c = clone(s); c.id = uid(); c._key = null; withKey(c); c.z = topZ(); map.set(s.id, c.id)
      if (c.type === 'ink') c.data.points = c.data.points.map(([x, y]) => [x + 24, y + 24]); else { c.x += 24; c.y += 24 }
      itemsRef.current.push(c); made.push(c.id)
    }
    // стрелки между дублируемыми — тоже
    for (const a of itemsRef.current.filter((i) => i.type === 'arrow' && selRef.current.has(i.id))) {
      const f = a.data.from, t = a.data.to
      if ((f.item == null || map.has(f.item)) && (t.item == null || map.has(t.item))) {
        const c = clone(a); c.id = uid(); c._key = null; withKey(c); c.z = topZ(); c.data.from = f.item != null ? { ...f, item: map.get(f.item) } : { x: f.x + 24, y: f.y + 24 }; c.data.to = t.item != null ? { ...t, item: map.get(t.item) } : { x: t.x + 24, y: t.y + 24 }
        itemsRef.current.push(c); made.push(c.id)
      }
    }
    renumber(); setSel(new Set(made)); commit()
  }, [readOnly, snapshot, commit, setSel])
  const bringTo = useCallback((front) => {
    if (!selRef.current.size) return
    snapshot()
    const zs = itemsRef.current.map((i) => i.z || 0); const base = front ? Math.max(0, ...zs) + 1 : Math.min(0, ...zs) - selRef.current.size
    let i = 0; for (const it of itemsRef.current) if (selRef.current.has(it.id)) it.z = base + i++
    commit()
  }, [snapshot, commit])
  const setSelData = useCallback((patch) => {
    if (readOnly || !selRef.current.size) return
    snapshot()
    for (const it of selected()) {
      it.data = { ...it.data, ...patch }
      if (it.type === 'frame') it.h = frameHeight(it.w, it.data)
    }
    commit()
  }, [readOnly, snapshot, commit])
  const setSelProps = useCallback((patch) => { if (readOnly || !selRef.current.size) return; snapshot(); for (const it of selected()) Object.assign(it, patch); commit() }, [readOnly, snapshot, commit])
  const alignSel = useCallback((how) => {
    const its = selected().filter((i) => i.type !== 'arrow'); if (its.length < 2) return
    snapshot(); const b = bbox(its)
    for (const it of its) {
      const ib = itemBox(it); const dx = how === 'left' ? b.x - ib.x : how === 'right' ? b.x + b.w - ib.x - ib.w : how === 'hcenter' ? b.x + b.w / 2 - ib.x - ib.w / 2 : 0
      const dy = how === 'top' ? b.y - ib.y : how === 'bottom' ? b.y + b.h - ib.y - ib.h : how === 'vcenter' ? b.y + b.h / 2 - ib.y - ib.h / 2 : 0
      moveBy(it, dx, dy)
    }
    if (how === 'row') { let x = b.x; for (const it of its.sort((a, c) => itemBox(a).x - itemBox(c).x)) { const ib = itemBox(it); moveBy(it, x - ib.x, b.y - ib.y); x += ib.w + 24 } }
    renumber(); commit()
  }, [snapshot, commit])
  const uploadImage = useCallback(async (file, x, y, frameId) => {
    if (readOnly || !file || !file.type.startsWith('image/')) return
    cbRef.current.onDirty?.('dirty')
    const fd = new FormData(); fd.append('file', file)
    try {
      const r = await fetch(`/api/boards/${board.id}/asset`, { method: 'POST', body: fd })
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || 'Не удалось загрузить картинку')
      const a = await r.json()
      snapshot()
      const fr = frameId != null ? itemsRef.current.find((i) => i.id === frameId) : null
      if (fr) { fr.data = { ...fr.data, image: a.src } }
      else { const w = Math.min(480, a.w), h = w * a.h / a.w; itemsRef.current.push(withKey({ id: uid(), type: 'image', x: x - w / 2, y: y - h / 2, w, h, z: topZ(), rot: 0, data: { src: a.src, label: '' } })) }
      commit()
    } catch (e) { cbRef.current.onDirty?.('err', e) }
  }, [board.id, readOnly, snapshot, commit])

  /* ---------- внешние ручки ---------- */
  useEffect(() => {
    if (!controlsRef) return
    controlsRef.current = {
      addAtCenter: (type, data) => { const el = wrapRef.current, v = viewRef.current; const [w, h] = DEFAULT_SIZE[type] || [200, 120]; const it = addItem(type, (el.clientWidth / 2 - v.x) / v.k - w / 2, (el.clientHeight / 2 - v.y) / v.k - (h || 200) / 2, data); if (it) { setSel(new Set([it.id])); if (type !== 'frame') startEdit(it.id) } return it },
      addFrameNext: (ratio) => {
        const fr = itemsRef.current.filter((i) => i.type === 'frame')
        const r = ratio || (fr.length ? fr[fr.length - 1].data.ratio : styleRef.current?.ratio) || '16:9'
        const w = fr.length ? fr[fr.length - 1].w : 320
        let x = 0, y = 0
        if (fr.length) {
          const last = fr.reduce((a, b) => (b.y > a.y + a.h * .5 || (Math.abs(b.y - a.y) < a.h * .5 && b.x > a.x) ? b : a))
          const row = fr.filter((f) => Math.abs(f.y - last.y) < last.h * .5); const per = (RATIOS[r] || 1.78) >= 1 ? 4 : 6
          if (row.length >= per) { x = Math.min(...row.map((f) => f.x)); y = last.y + last.h + 60 } else { x = last.x + last.w + 28; y = last.y }
        }
        const it = addItem('frame', x, y, { ratio: r }, [w, 0]); if (!it) return
        setSel(new Set([it.id])); const b = itemBox(it), el = wrapRef.current, v = viewRef.current
        if (b.x * v.k + v.x > el.clientWidth - 80 || b.y * v.k + v.y > el.clientHeight - 80 || b.x * v.k + v.x < 0) setViewNow({ ...v, x: el.clientWidth / 2 - (b.x + b.w / 2) * v.k, y: el.clientHeight / 2 - (b.y + b.h / 2) * v.k })
      },
      addFramesGrid: (n, ratio) => { for (let i = 0; i < n; i++) controlsRef.current.addFrameNext(ratio); fitAll() },
      fit: fitAll, fitSelection: () => fitTo(bbox(selected()), 3), zoomIn: () => zoomAt(1.25), zoomOut: () => zoomAt(0.8),
      zoomTo: (k) => { const el = wrapRef.current, v = viewRef.current, cx = el.clientWidth / 2, cy = el.clientHeight / 2; setViewNow({ x: cx - (cx - v.x) / v.k * k, y: cy - (cy - v.y) / v.k * k, k }) },
      undo, redo, canUndo: () => undoRef.current.length > 0, canRedo: () => redoRef.current.length > 0,
      deleteSel, duplicateSel, bringTo, setSelData, setSelProps, alignSel, selectAll: () => setSel(new Set(itemsRef.current.map((i) => i.id))),
      edit: (id) => startEdit(id), items: () => itemsRef.current, selected, uploadImage: (file, frameId) => { const el = wrapRef.current, v = viewRef.current; uploadImage(file, (el.clientWidth / 2 - v.x) / v.k, (el.clientHeight / 2 - v.y) / v.k, frameId) },
      exportPng: (onlySel) => fn.current.exportPng?.(onlySel), focusItem: (id) => { const it = itemsRef.current.find((i) => i.id === id); if (!it) return; const b = itemBox(it), el = wrapRef.current, v = viewRef.current; setViewNow({ ...v, x: el.clientWidth / 2 - (b.x + b.w / 2) * v.k, y: el.clientHeight / 2 - (b.y + b.h / 2) * v.k }); setSel(new Set([id])) },
      adoptFresh, flushNow: () => { clearTimeout(saveTimer.current); return flushRef.current() },
    }
  })
  useEffect(() => { cbRef.current.onSelectionChange?.(selected()) }, [sel, ver]) // eslint-disable-line

  /* ---------- клавиатура ---------- */
  useEffect(() => {
    const down = (e) => {
      const ae = document.activeElement; const typing = ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.tagName === 'SELECT' || ae.isContentEditable)
      const mod = e.ctrlKey || e.metaKey
      if (e.code === 'Space' && !typing && !editingRef.current) { if (!e.repeat) setSpaceDown(true); e.preventDefault(); return }
      if (editingRef.current || typing) {
        if (e.key === 'Escape' && editingRef.current) { e.preventDefault(); ae?.blur(); stopEdit() }
        return   // в поле ввода браузерные Ctrl+Z/C/V работают сами
      }
      if (!wrapRef.current) return
      // сочетания редактора работают, когда фокус не в чужом поле (даже если курсор не над холстом)
      if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); return }
      if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return }
      if (mod && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicateSel(); return }
      if (mod && e.key.toLowerCase() === 'a') { e.preventDefault(); setSel(new Set(itemsRef.current.map((i) => i.id))); return }
      if (mod && e.key.toLowerCase() === 'c' && selRef.current.size) { e.preventDefault(); clipRef.current = clone(selected()); return }
      if (mod && e.key.toLowerCase() === 'x' && selRef.current.size) { e.preventDefault(); clipRef.current = clone(selected()); deleteSel(); return }
      if (mod && (e.key === '=' || e.key === '+')) { e.preventDefault(); zoomAt(1.25); return }
      if (mod && e.key === '-') { e.preventDefault(); zoomAt(0.8); return }
      if (mod && e.key === '0') { e.preventDefault(); controlsRef?.current?.zoomTo(1); return }
      if (mod && e.key === '1') { e.preventDefault(); fitAll(); return }
      if (mod && e.key === '2') { e.preventDefault(); fitTo(bbox(selected()), 3); return }
      if (mod) return
      if (e.key === 'Delete' || e.key === 'Backspace') { if (selRef.current.size) { e.preventDefault(); deleteSel() } return }
      if (e.key === 'Escape') { if (selRef.current.size) setSel(new Set()); else cbRef.current.setTool?.('select'); setCtx(null); return }
      if (e.key === 'Enter' && selRef.current.size === 1) { const it = selected()[0]; if (it && ['sticky', 'text', 'frame'].includes(it.type)) { e.preventDefault(); startEdit(it.id) } return }
      if (e.key === 'PageUp') { e.preventDefault(); bringTo(true); return }
      if (e.key === 'PageDown') { e.preventDefault(); bringTo(false); return }
      if (!e.altKey) {
        const map = { v: 'select', h: 'hand', s: 'sticky', n: 'sticky', t: 'text', f: 'frame', a: 'arrow', l: 'arrow', p: 'pen', i: 'image', e: 'eraser' }
        const k = e.key.toLowerCase(); if (map[k]) { cbRef.current.setTool?.(map[k]); return }
        if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key) && selRef.current.size) {
          e.preventDefault(); const d = e.shiftKey ? 10 : 1
          if (!e.repeat) snapshot()
          const dx = e.key === 'ArrowLeft' ? -d : e.key === 'ArrowRight' ? d : 0, dy = e.key === 'ArrowUp' ? -d : e.key === 'ArrowDown' ? d : 0
          for (const it of selected()) moveBy(it, dx, dy)
          renumber(); commit()
        }
      }
    }
    const up = (e) => { if (e.code === 'Space') setSpaceDown(false) }
    const blur = () => setSpaceDown(false)
    window.addEventListener('keydown', down); window.addEventListener('keyup', up); window.addEventListener('blur', blur)
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); window.removeEventListener('blur', blur) }
  }, [undo, redo, duplicateSel, deleteSel, zoomAt, fitAll, fitTo, bringTo, snapshot, commit, setSel, setEditing, controlsRef])
  // вставка: картинка/текст из буфера или наши скопированные объекты
  useEffect(() => {
    const onPaste = (e) => {
      if (readOnly) return
      const ae = document.activeElement; if (ae && (ae.tagName === 'INPUT' || ae.tagName === 'TEXTAREA' || ae.isContentEditable)) return
      const el = wrapRef.current, v = viewRef.current; const cx = (el.clientWidth / 2 - v.x) / v.k, cy = (el.clientHeight / 2 - v.y) / v.k
      const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith('image/'))
      if (f) { e.preventDefault(); const fr = selected().length === 1 && selected()[0].type === 'frame' ? selected()[0] : null; uploadImage(f, cx, cy, fr?.id); return }
      const t = e.clipboardData?.getData('text/plain')
      if (clipRef.current?.length && !t) { e.preventDefault(); setSel(new Set(clipRef.current.map((c) => c.id))); duplicateSel(); return }
      if (t && t.trim()) { e.preventDefault(); const it = addItem(t.length > 140 ? 'text' : 'sticky', cx - 100, cy - 100, { text: t.trim() }); if (it) setSel(new Set([it.id])) }
    }
    window.addEventListener('paste', onPaste); return () => window.removeEventListener('paste', onPaste)
  }, [readOnly, addItem, uploadImage, duplicateSel, setSel])

  /* ---------- картинки ---------- */
  const getImg = useCallback((src) => {
    if (!src) return null
    const c = imgCache.current
    if (c.has(src)) { const im = c.get(src); return im.complete && im.naturalWidth ? im : null }
    const im = new Image(); im.src = `/media/${src}`; im.onload = () => fn.current.draw?.(); c.set(src, im); return null
  }, [])

  /* ---------- отрисовка ---------- */
  const draw = useCallback(() => {
    const cv = canvasRef.current, el = wrapRef.current; if (!cv || !el) return
    const dpr = Math.min(2, window.devicePixelRatio || 1), W = el.clientWidth, H = el.clientHeight
    if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; cv.style.width = W + 'px'; cv.style.height = H + 'px' }
    const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H)
    const v = viewRef.current, dark = isDark(), ink = themeColor('ink', dark), accent = themeColor('accent', dark)
    const line = dark ? 'rgba(236,236,233,.22)' : 'rgba(14,14,14,.2)'
    const step = v.k > 2 ? 10 : v.k > .8 ? 20 : v.k > .35 ? 50 : v.k > .15 ? 100 : 250, gs = step * v.k
    if (gs >= 9) { g.fillStyle = dark ? 'rgba(236,236,233,.14)' : 'rgba(14,14,14,.13)'; const ox = ((v.x % gs) + gs) % gs, oy = ((v.y % gs) + gs) % gs; for (let x = ox; x < W; x += gs) for (let y = oy; y < H; y += gs) g.fillRect(x - .6, y - .6, 1.2, 1.2) }
    g.save(); g.translate(v.x, v.y); g.scale(v.k, v.k)
    const items = [...itemsRef.current].sort((a, b) => (a.z || 0) - (b.z || 0)), byId = byIdOf(items), S = selRef.current
    const rr = (x, y, w, h, r) => { g.beginPath(); g.roundRect(x, y, w, h, Math.min(r, w / 2, h / 2)) }
    const withRot = (it, b, f) => { if (!it.rot) return f(); g.save(); g.translate(b.x + b.w / 2, b.y + b.h / 2); g.rotate(it.rot * Math.PI / 180); g.translate(-(b.x + b.w / 2), -(b.y + b.h / 2)); f(); g.restore() }
    for (const it of items) {
      if (it.type === 'frame') {
        const b = itemBox(it), ih = frameWindow(it)
        withRot(it, b, () => {
          g.fillStyle = dark ? 'rgba(236,236,233,.05)' : 'rgba(14,14,14,.035)'; rr(it.x, it.y, it.w, b.h, 10 * it.w / 320); g.fill()
          g.fillStyle = dark ? '#0b0b0d' : '#ffffff'; rr(it.x, it.y, it.w, ih, 10 * it.w / 320); g.fill()
          const im = getImg(it.data.image)
          if (im) { g.save(); rr(it.x, it.y, it.w, ih, 10 * it.w / 320); g.clip(); const s = Math.max(it.w / im.width, ih / im.height); g.drawImage(im, it.x + (it.w - im.width * s) / 2, it.y + (ih - im.height * s) / 2, im.width * s, im.height * s); g.restore() }
          else { g.strokeStyle = dark ? 'rgba(236,236,233,.1)' : 'rgba(14,14,14,.08)'; g.lineWidth = 1 / v.k; g.beginPath(); g.moveTo(it.x, it.y); g.lineTo(it.x + it.w, it.y + ih); g.moveTo(it.x + it.w, it.y); g.lineTo(it.x, it.y + ih); g.stroke() }
          g.strokeStyle = line; g.lineWidth = 1 / v.k; rr(it.x, it.y, it.w, ih, 10 * it.w / 320); g.stroke(); rr(it.x, it.y, it.w, b.h, 10 * it.w / 320); g.stroke()
          // номер и длительность — в масштабе кадра, читаются на любом зуме
          const fs = Math.max(11, 13 * it.w / 320)
          if (it.data.n) { g.font = `600 ${fs}px ui-monospace, monospace`; const tw = g.measureText(String(it.data.n)).width + fs; g.fillStyle = dark ? 'rgba(0,0,0,.65)' : 'rgba(255,255,255,.9)'; rr(it.x + fs * .6, it.y + fs * .6, tw, fs * 1.6, fs * .4); g.fill(); g.fillStyle = ink; g.textBaseline = 'middle'; g.textAlign = 'left'; g.fillText(String(it.data.n), it.x + fs * 1.1, it.y + fs * 1.4) }
          if (it.data.seconds) { const s = fmtSec(it.data.seconds); g.font = `500 ${fs * .9}px ui-monospace, monospace`; const tw = g.measureText(s).width + fs; g.fillStyle = dark ? 'rgba(0,0,0,.65)' : 'rgba(255,255,255,.9)'; rr(it.x + it.w - tw - fs * .6, it.y + fs * .6, tw, fs * 1.5, fs * .4); g.fill(); g.fillStyle = ink; g.textBaseline = 'middle'; g.fillText(s, it.x + it.w - tw - fs * .1, it.y + fs * 1.35) }
        })
      } else if (it.type === 'image') {
        const b = itemBox(it), im = getImg(it.data.src)
        withRot(it, b, () => { rr(it.x, it.y, it.w, it.h, 8); if (im) { g.save(); g.clip(); g.drawImage(im, it.x, it.y, it.w, it.h); g.restore() } else { g.fillStyle = dark ? 'rgba(236,236,233,.06)' : 'rgba(14,14,14,.05)'; g.fill() } })
      } else if (it.type === 'ink') {
        const pts = it.data.points || []
        if (pts.length > 1) { g.strokeStyle = themeColor(it.data.color, dark); g.lineWidth = it.data.width || 3; g.lineCap = 'round'; g.lineJoin = 'round'; g.beginPath(); g.moveTo(pts[0][0], pts[0][1]); for (let i = 1; i < pts.length - 1; i++) g.quadraticCurveTo(pts[i][0], pts[i][1], (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2); const l = pts[pts.length - 1]; g.lineTo(l[0], l[1]); g.stroke() }
        else if (pts.length === 1) { g.fillStyle = themeColor(it.data.color, dark); g.beginPath(); g.arc(pts[0][0], pts[0][1], (it.data.width || 3) / 2, 0, Math.PI * 2); g.fill() }
      } else if (it.type === 'arrow') {
        const pq = arrowPoints(it, byId); if (!pq) continue
        const [p, q] = pq, col = S.has(it.id) ? accent : themeColor(it.data.color || 'ink', dark), lw = it.data.width || 2
        g.strokeStyle = col; g.lineWidth = lw; g.lineCap = 'round'; g.beginPath(); g.moveTo(p.x, p.y); g.lineTo(q.x, q.y); g.stroke()
        if (it.data.style !== 'line') { const ang = Math.atan2(q.y - p.y, q.x - p.x), L = 6 + lw * 3; g.fillStyle = col; g.beginPath(); g.moveTo(q.x, q.y); g.lineTo(q.x - L * Math.cos(ang - .42), q.y - L * Math.sin(ang - .42)); g.lineTo(q.x - L * Math.cos(ang + .42), q.y - L * Math.sin(ang + .42)); g.closePath(); g.fill() }
        if (it.data.label) { const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2, fs = fontSize(it) || 13; g.font = `500 ${fs}px ${fontFamily(it)}`; const tw = g.measureText(it.data.label).width + fs; g.fillStyle = dark ? '#141416' : '#fff'; rr(mx - tw / 2, my - fs * .8, tw, fs * 1.6, fs * .4); g.fill(); g.fillStyle = themeColor(it.data.text_color || 'ink', dark); g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(it.data.label, mx, my); g.textAlign = 'left' }
        if (S.has(it.id) && S.size === 1) { g.fillStyle = dark ? '#141416' : '#fff'; g.strokeStyle = accent; g.lineWidth = 1.5 / v.k; for (const e of [p, q]) { g.beginPath(); g.arc(e.x, e.y, HANDLE / v.k, 0, Math.PI * 2); g.fill(); g.stroke() } }
      }
    }
    // выделение
    for (const it of items) {
      if (!S.has(it.id) || it.type === 'arrow') continue
      const b = itemBox(it)
      withRot(it, b, () => {
        g.strokeStyle = accent; g.lineWidth = 1.5 / v.k; g.setLineDash([]); g.strokeRect(b.x, b.y, b.w, b.h)
        if (S.size === 1 && it.type !== 'ink') {
          g.fillStyle = dark ? '#141416' : '#fff'
          for (const [hx, hy] of handles(b)) { g.beginPath(); g.arc(hx, hy, HANDLE / v.k, 0, Math.PI * 2); g.fill(); g.stroke() }
          // ручка поворота над верхней серединой
          const ry = b.y - 28 / v.k; g.beginPath(); g.moveTo(b.x + b.w / 2, b.y); g.lineTo(b.x + b.w / 2, ry); g.stroke(); g.beginPath(); g.arc(b.x + b.w / 2, ry, HANDLE / v.k, 0, Math.PI * 2); g.fill(); g.stroke()
        }
      })
    }
    if (S.size > 1) { const b = bbox(items.filter((i) => S.has(i.id))); if (b) { g.strokeStyle = accent; g.setLineDash([6 / v.k, 4 / v.k]); g.lineWidth = 1 / v.k; g.strokeRect(b.x - 6 / v.k, b.y - 6 / v.k, b.w + 12 / v.k, b.h + 12 / v.k); g.setLineDash([]); g.fillStyle = dark ? '#141416' : '#fff'; for (const [hx, hy] of [[b.x - 6 / v.k, b.y - 6 / v.k], [b.x + b.w + 6 / v.k, b.y - 6 / v.k], [b.x + b.w + 6 / v.k, b.y + b.h + 6 / v.k], [b.x - 6 / v.k, b.y + b.h + 6 / v.k]]) { g.beginPath(); g.arc(hx, hy, HANDLE / v.k, 0, Math.PI * 2); g.fill(); g.stroke() } } }
    const d = dragRef.current
    if (d?.kind === 'arrow' && d.cur) { g.strokeStyle = accent; g.lineWidth = 2; g.setLineDash([6, 4]); g.beginPath(); g.moveTo(d.start.x, d.start.y); g.lineTo(d.cur.x, d.cur.y); g.stroke(); g.setLineDash([]) }
    if (d?.kind === 'ink' && d.pts.length) { const st = styleRef.current || {}; g.strokeStyle = themeColor(st.inkColor || 'ink', dark); g.lineWidth = st.inkWidth || 3; g.lineCap = 'round'; g.lineJoin = 'round'; g.beginPath(); g.moveTo(d.pts[0][0], d.pts[0][1]); for (const p of d.pts) g.lineTo(p[0], p[1]); g.stroke() }
    if (hoverEnd != null) { const it = byId.get(hoverEnd); const b = it && itemBox(it); if (b) { g.strokeStyle = accent; g.lineWidth = 2 / v.k; g.strokeRect(b.x - 3 / v.k, b.y - 3 / v.k, b.w + 6 / v.k, b.h + 6 / v.k); if (hoverAnchor) { g.fillStyle = accent; g.beginPath(); g.arc(hoverAnchor.x, hoverAnchor.y, 5 / v.k, 0, Math.PI * 2); g.fill() } } }
    if (ghost) { const m = normRect(ghost); g.strokeStyle = accent; g.setLineDash([6 / v.k, 4 / v.k]); g.lineWidth = 1.5 / v.k; g.strokeRect(m.x, m.y, m.w, m.h); g.setLineDash([]) }
    g.restore()
    if (marquee) { const m = normRect(marquee); g.fillStyle = accent + '22'; g.strokeStyle = accent; g.lineWidth = 1; g.fillRect(m.x * v.k + v.x, m.y * v.k + v.y, m.w * v.k, m.h * v.k); g.strokeRect(m.x * v.k + v.x, m.y * v.k + v.y, m.w * v.k, m.h * v.k) }
  }, [getImg, marquee, ghost, hoverEnd]) // eslint-disable-line
  fn.current.draw = draw
  useLayoutEffect(() => { draw() })
  useEffect(() => { const ro = new ResizeObserver(() => draw()); ro.observe(wrapRef.current); const mo = new MutationObserver(() => draw()); mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] }); return () => { ro.disconnect(); mo.disconnect() } }, [draw])

  /* ---------- попадание ---------- */
  const hit = useCallback((wx, wy, skipArrows = false) => {
    const v = viewRef.current, items = [...itemsRef.current].sort((a, b) => (b.z || 0) - (a.z || 0)), byId = byIdOf(items)
    for (const it of items) {
      if (it.type === 'arrow') { if (skipArrows) continue; const pq = arrowPoints(it, byId); if (pq && distSeg(wx, wy, pq[0], pq[1]) < 7 / v.k) return it; continue }
      const b = itemBox(it)
      if (it.type === 'ink') { if (!inBox(b, wx, wy)) continue; const pts = it.data.points, t = (it.data.width || 3) / 2 + 5 / v.k; if (pts.length === 1 && Math.hypot(wx - pts[0][0], wy - pts[0][1]) < t) return it; for (let i = 1; i < pts.length; i++) if (distSeg(wx, wy, { x: pts[i - 1][0], y: pts[i - 1][1] }, { x: pts[i][0], y: pts[i][1] }) < t) return it; continue }
      const p = unrotate(it, b, wx, wy)
      if (inBox(b, p.x, p.y)) return it
    }
    return null
  }, [])
  const hitHandle = useCallback((wx, wy) => {
    const S = selRef.current, v = viewRef.current, r = (HANDLE + 3) / v.k
    if (S.size === 1) {
      const it = selected()[0]; if (!it) return null
      if (it.type === 'arrow') { const pq = arrowPoints(it, byIdOf(itemsRef.current)); if (!pq) return null; if (Math.hypot(pq[0].x - wx, pq[0].y - wy) <= r) return { it, h: 'from' }; if (Math.hypot(pq[1].x - wx, pq[1].y - wy) <= r) return { it, h: 'to' }; return null }
      if (it.type === 'ink') return null
      const b = itemBox(it), p = unrotate(it, b, wx, wy)
      if (Math.hypot(b.x + b.w / 2 - p.x, b.y - 28 / v.k - p.y) <= r) return { it, h: 'rot' }
      const hs = handles(b), names = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']
      for (let i = 0; i < hs.length; i++) if (Math.hypot(hs[i][0] - p.x, hs[i][1] - p.y) <= r) return { it, h: names[i] }
      return null
    }
    if (S.size > 1) { const b = bbox(selected()); if (!b) return null; const cs = [['nw', b.x - 6 / v.k, b.y - 6 / v.k], ['ne', b.x + b.w + 6 / v.k, b.y - 6 / v.k], ['se', b.x + b.w + 6 / v.k, b.y + b.h + 6 / v.k], ['sw', b.x - 6 / v.k, b.y + b.h + 6 / v.k]]; for (const [h, x, y] of cs) if (Math.hypot(x - wx, y - wy) <= r) return { group: true, h, b } }
    return null
  }, [])

  /* ---------- указатель ---------- */
  const onPointerDown = (e) => {
    if (e.button === 2) return
    const el = e.currentTarget; const p = toWorld(e.clientX, e.clientY); const t = toolRef.current
    setCtx(null)
    const pan = e.button === 1 || (e.button === 0 && (spaceDown || t === 'hand'))
    if (pan) { dragRef.current = { kind: 'pan', sx: e.clientX, sy: e.clientY, vx: viewRef.current.x, vy: viewRef.current.y }; el.setPointerCapture(e.pointerId); return }
    if (e.button !== 0) return
    if (editingRef.current) stopEdit()
    if (readOnly && t !== 'select') return
    if (t === 'sticky' || t === 'text' || t === 'frame' || t === 'image') { dragRef.current = { kind: 'create', type: t, sx: p.x, sy: p.y, shift: e.shiftKey }; el.setPointerCapture(e.pointerId); return }
    if (t === 'pen') { dragRef.current = { kind: 'ink', pts: [[p.x, p.y]] }; el.setPointerCapture(e.pointerId); return }
    if (t === 'eraser') { dragRef.current = { kind: 'erase', done: new Set() }; eraseAt(p); el.setPointerCapture(e.pointerId); return }
    if (t === 'arrow') { const from = hit(p.x, p.y, true); dragRef.current = { kind: 'arrow', start: p, from: from && from.type !== 'ink' ? from : null, cur: p }; el.setPointerCapture(e.pointerId); return }
    // --- выбор ---
    const hh = hitHandle(p.x, p.y)
    if (hh) {
      snapshot()
      if (hh.group) { dragRef.current = { kind: 'gresize', h: hh.h, b: hh.b, orig: clone(selected()), sx: p.x, sy: p.y } }
      else if (hh.h === 'rot') { const b = itemBox(hh.it); dragRef.current = { kind: 'rotate', it: hh.it, cx: b.x + b.w / 2, cy: b.y + b.h / 2, start: hh.it.rot || 0, a0: Math.atan2(p.y - (b.y + b.h / 2), p.x - (b.x + b.w / 2)) } }
      else if (hh.h === 'from' || hh.h === 'to') { dragRef.current = { kind: 'arrowend', it: hh.it, end: hh.h } }
      else dragRef.current = { kind: 'resize', it: hh.it, h: hh.h, ox: hh.it.x, oy: hh.it.y, ow: hh.it.w, oh: itemBox(hh.it).h, sx: p.x, sy: p.y, shift: e.shiftKey }
      el.setPointerCapture(e.pointerId); return
    }
    const it = hit(p.x, p.y)
    if (it) {
      let next = new Set(selRef.current)
      if (e.shiftKey || e.ctrlKey || e.metaKey) { next.has(it.id) ? next.delete(it.id) : next.add(it.id) } else if (!next.has(it.id)) next = new Set([it.id])
      setSel(next)
      const moving = itemsRef.current.filter((i) => next.has(i.id))
      dragRef.current = { kind: 'move', sx: p.x, sy: p.y, alt: e.altKey, orig: clone(moving), ids: moving.map((i) => i.id), moved: false, single: it }
      el.setPointerCapture(e.pointerId)
    } else {
      if (!(e.shiftKey || e.ctrlKey || e.metaKey)) setSel(new Set())
      dragRef.current = { kind: 'marquee', sx: p.x, sy: p.y, add: e.shiftKey || e.ctrlKey || e.metaKey }
      el.setPointerCapture(e.pointerId)
    }
  }
  function eraseAt(p) {
    const d = dragRef.current; const v = viewRef.current
    for (const it of itemsRef.current) {
      if (it.type !== 'ink' || d.done.has(it.id)) continue
      const pts = it.data.points, t = (it.data.width || 3) / 2 + 8 / v.k
      if (!inBox(itemBox(it), p.x, p.y)) continue
      const near = pts.length === 1 ? Math.hypot(p.x - pts[0][0], p.y - pts[0][1]) < t : pts.some((q, i) => i > 0 && distSeg(p.x, p.y, { x: pts[i - 1][0], y: pts[i - 1][1] }, { x: q[0], y: q[1] }) < t)
      if (near) { if (!d.snap) { snapshot(); d.snap = true } d.done.add(it.id) }
    }
    if (d.done.size) { itemsRef.current = itemsRef.current.filter((i) => !d.done.has(i.id)); bump() }
  }
  const onPointerMove = (e) => {
    const d = dragRef.current, p = toWorld(e.clientX, e.clientY), t = toolRef.current
    if (!d) {
      if (t === 'arrow') { const h = hit(p.x, p.y, true); const ok = h && h.type !== 'ink'; setHoverEnd(ok ? h.id : null); setHoverAnchor(ok ? anchorOf(h, p) : null) }
      else if (t === 'select') {
        const hh = hitHandle(p.x, p.y)
        const cur = hh ? (hh.h === 'rot' ? 'grab' : hh.h === 'from' || hh.h === 'to' ? 'move' : ({ nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize', n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize' })[hh.h]) : hit(p.x, p.y) ? 'move' : 'default'
        if (wrapRef.current.style.cursor !== cur) wrapRef.current.style.cursor = cur
      }
      return
    }
    const v = viewRef.current
    switch (d.kind) {
      case 'pan': { setViewNow({ ...v, x: d.vx + (e.clientX - d.sx), y: d.vy + (e.clientY - d.sy) }, false); return }
      case 'ink': { const l = d.pts[d.pts.length - 1]; if (Math.hypot(p.x - l[0], p.y - l[1]) > 1 / v.k) { d.pts.push([p.x, p.y]); draw() } return }
      case 'erase': { eraseAt(p); return }
      case 'arrow': { d.cur = p; const h = hit(p.x, p.y, true); const ok = h && h.type !== 'ink' && h !== d.from; setHoverEnd(ok ? h.id : null); setHoverAnchor(ok ? anchorOf(h, p) : null); draw(); return }
      case 'arrowend': { const h = hit(p.x, p.y, true); const ok = h && h.type !== 'ink' && h.id !== d.it.id; setHoverEnd(ok ? h.id : null); d.it.data = { ...d.it.data, [d.end]: ok ? { item: h.id, ...nearestAnchor(itemBox(h), p.x, p.y) } : { x: p.x, y: p.y } }; bump(); return }
      case 'create': { let w = p.x - d.sx, h = p.y - d.sy; if (d.type === 'sticky' || d.shift) { const m = Math.max(Math.abs(w), Math.abs(h)); w = Math.sign(w || 1) * m; h = Math.sign(h || 1) * m } if (d.type === 'frame') { const r = RATIOS[styleRef.current?.ratio || '16:9'] || 1.78; h = Math.sign(h || 1) * Math.abs(w) / r } setGhost({ x: d.sx, y: d.sy, w, h }); return }
      case 'marquee': { setMarquee({ x: d.sx, y: d.sy, w: p.x - d.sx, h: p.y - d.sy }); return }
      case 'move': {
        if (!d.moved) { if (Math.hypot(p.x - d.sx, p.y - d.sy) * v.k < 3) return; d.moved = true; snapshot(); if (d.alt) { /* Alt+drag = дубликат */ duplicateSel(); const s = selected(); d.orig = clone(s); d.ids = s.map((i) => i.id) } }
        let dx = p.x - d.sx, dy = p.y - d.sy
        if (e.shiftKey) { if (Math.abs(dx) > Math.abs(dy)) dy = 0; else dx = 0 }
        const snap = e.ctrlKey || e.metaKey ? 20 : 0
        for (const o of d.orig) { const it = itemsRef.current.find((i) => i.id === o.id); if (!it) continue; placeFrom(it, o, dx, dy, snap) }
        bump(); return
      }
      case 'resize': {
        const it = d.it, dx = p.x - d.sx, dy = p.y - d.sy; let { ox, oy, ow, oh } = d; let x = ox, y = oy, w = ow, h = oh
        if (d.h.includes('e')) w = ow + dx; if (d.h.includes('s')) h = oh + dy; if (d.h.includes('w')) { x = ox + dx; w = ow - dx } if (d.h.includes('n')) { y = oy + dy; h = oh - dy }
        const corner = d.h.length === 2
        if (it.type === 'frame' || it.type === 'image' || (it.type === 'sticky' && !d.shift) || (corner && (d.shift || it.type === 'image'))) {
          const r = it.type === 'frame' ? ow / oh : ow / oh
          if (d.h === 'n' || d.h === 's') { w = h * r } else if (d.h === 'e' || d.h === 'w') { h = w / r } else { if (Math.abs(w / r) > Math.abs(h)) h = w / r; else w = h * r }
          if (d.h.includes('w')) x = ox + ow - w; if (d.h.includes('n')) y = oy + oh - h
        }
        const min = it.type === 'frame' ? 60 : 24
        if (w < min) { w = min; if (d.h.includes('w')) x = ox + ow - min } if (h < min) { h = min; if (d.h.includes('n')) y = oy + oh - min }
        it.x = x; it.y = y; it.w = w; it.h = it.type === 'frame' ? frameHeight(w, it.data) : h
        if (it.type === 'frame' && d.h.includes('n')) it.y = oy + oh - it.h
        bump(); return
      }
      case 'gresize': {
        const b = d.b; const ax = d.h.includes('w') ? b.x + b.w : b.x, ay = d.h.includes('n') ? b.y + b.h : b.y   // якорь — противоположный угол
        const sx = Math.max(.05, (d.h.includes('w') ? ax - p.x : p.x - ax) / b.w), sy = Math.max(.05, (d.h.includes('n') ? ay - p.y : p.y - ay) / b.h); const s = e.shiftKey ? Math.max(sx, sy) : Math.min(sx, sy)
        for (const o of d.orig) { const it = itemsRef.current.find((i) => i.id === o.id); if (!it) continue; scaleFrom(it, o, ax, ay, s) }
        bump(); return
      }
      case 'rotate': { const a = Math.atan2(p.y - d.cy, p.x - d.cx); let deg = d.start + (a - d.a0) * 180 / Math.PI; if (e.shiftKey) deg = Math.round(deg / 15) * 15; d.it.rot = ((deg % 360) + 360) % 360; if (Math.abs(d.it.rot) < 2 || Math.abs(d.it.rot - 360) < 2) d.it.rot = 0; bump(); return }
      default:
    }
  }
  const onPointerUp = (e) => {
    const d = dragRef.current; dragRef.current = null; if (!d) return
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch {}
    const p = toWorld(e.clientX, e.clientY), v = viewRef.current
    setHoverEnd(null); setHoverAnchor(null)
    switch (d.kind) {
      case 'pan': setViewNow(viewRef.current); return
      case 'ink': { if (d.pts.length) addItem('ink', 0, 0, { points: d.pts.map(([x, y]) => [+x.toFixed(2), +y.toFixed(2)]), color: styleRef.current?.inkColor || 'ink', width: styleRef.current?.inkWidth || 3 }, [0, 0]); draw(); return }
      case 'erase': { if (d.done.size) commit(); return }
      case 'arrow': {
        const to = hit(p.x, p.y, true); const okTo = to && to.type !== 'ink' && to !== d.from
        if (Math.hypot(p.x - d.start.x, p.y - d.start.y) * v.k < 8) { draw(); return }
        const from = d.from ? { item: d.from.id, ...anchorOf(d.from, d.start, true) } : { x: d.start.x, y: d.start.y }
        const toEnd = okTo ? { item: to.id, ...nearestAnchor(itemBox(to), p.x, p.y) } : { x: p.x, y: p.y }
        const it = addItem('arrow', 0, 0, { from, to: toEnd }, [0, 0]); if (it) setSel(new Set([it.id]))
        if (!e.shiftKey) cbRef.current.setTool?.('select'); return
      }
      case 'arrowend': { commit(); return }
      case 'create': {
        setGhost(null)
        const dragged = Math.hypot(p.x - d.sx, p.y - d.sy) * v.k >= 6
        let box
        if (dragged) { let w = p.x - d.sx, h = p.y - d.sy; if (d.type === 'sticky' || d.shift) { const m = Math.max(Math.abs(w), Math.abs(h)); w = Math.sign(w || 1) * m; h = Math.sign(h || 1) * m } if (d.type === 'frame') { const r = RATIOS[styleRef.current?.ratio || '16:9'] || 1.78; h = Math.sign(h || 1) * Math.abs(w) / r } box = normRect({ x: d.sx, y: d.sy, w, h }) }
        else { const [w, h] = DEFAULT_SIZE[d.type] || [200, 120]; box = { x: d.sx - w / 2, y: d.sy - (h || 180) / 2, w, h: h || 180 } }
        if (d.type === 'image') { imageDrop.current = { x: box.x + box.w / 2, y: box.y + box.h / 2 }; fileInputRef.current?.click(); if (!e.shiftKey) cbRef.current.setTool?.('select'); return }
        const it = addItem(d.type, box.x, box.y, {}, [Math.max(24, box.w), Math.max(24, box.h)])
        if (it) { setSel(new Set([it.id])); if (d.type !== 'frame') startEdit(it.id) }
        if (!e.shiftKey) cbRef.current.setTool?.('select'); return
      }
      case 'marquee': { if (marquee) { const m = normRect(marquee); const inside = itemsRef.current.filter((i) => rectsIntersect(m, itemBox(i)) || (i.type === 'arrow' && arrowInRect(i, m))).map((i) => i.id); setSel(d.add ? new Set([...selRef.current, ...inside]) : new Set(inside)) } setMarquee(null); return }
      case 'move': { if (d.moved) { renumber(); commit() } else if (!e.shiftKey && !e.ctrlKey && !e.metaKey && d.single && selRef.current.size > 1) setSel(new Set([d.single.id])); return }
      case 'resize': case 'gresize': case 'rotate': { renumber(); commit(); return }
      default:
    }
  }
  function arrowInRect(a, m) { const pq = arrowPoints(a, byIdOf(itemsRef.current)); return pq && (inBox(m, pq[0].x, pq[0].y) || inBox(m, pq[1].x, pq[1].y)) }
  function anchorOf(it, p) { return nearestAnchor(itemBox(it), p.x, p.y) }
  const onDoubleClick = (e) => {
    if (readOnly) return
    const p = toWorld(e.clientX, e.clientY), it = hit(p.x, p.y)
    if (it && ['sticky', 'text', 'frame', 'arrow'].includes(it.type)) { setSel(new Set([it.id])); startEdit(it.id); return }
    if (!it && !['hand', 'pen', 'eraser'].includes(toolRef.current)) { const n = addItem('sticky', p.x - 100, p.y - 100); if (n) { setSel(new Set([n.id])); startEdit(n.id) } }
  }
  useEffect(() => {
    const el = wrapRef.current; if (!el) return
    const onWheel = (e) => {
      e.preventDefault()
      if (e.ctrlKey || e.metaKey) { zoomAt(Math.exp(-e.deltaY * (e.deltaMode === 1 ? .05 : .0022)), e.clientX, e.clientY); return }
      const v = viewRef.current, mul = e.deltaMode === 1 ? 16 : 1
      const dx = (e.shiftKey && !e.deltaX ? e.deltaY : e.deltaX) * mul, dy = (e.shiftKey && !e.deltaX ? 0 : e.deltaY) * mul
      setViewNow({ ...v, x: v.x - dx, y: v.y - dy })
    }
    el.addEventListener('wheel', onWheel, { passive: false }); return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt, setViewNow])
  // пинч и тап на телефоне
  const pinchRef = useRef(null)
  const onTouchStart = (e) => { if (e.touches.length === 2) { const [a, b] = e.touches; pinchRef.current = { d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), k: viewRef.current.k, cx: (a.clientX + b.clientX) / 2, cy: (a.clientY + b.clientY) / 2, vx: viewRef.current.x, vy: viewRef.current.y }; dragRef.current = null; setGhost(null); setMarquee(null) } }
  const onTouchMove = (e) => {
    if (e.touches.length === 2 && pinchRef.current) {
      e.preventDefault(); const [a, b] = e.touches, P = pinchRef.current, r = wrapRef.current.getBoundingClientRect()
      const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), cx = (a.clientX + b.clientX) / 2 - r.left, cy = (a.clientY + b.clientY) / 2 - r.top
      const k = Math.min(MAX_K, Math.max(MIN_K, P.k * dist / P.d)); const wx = (P.cx - r.left - P.vx) / P.k, wy = (P.cy - r.top - P.vy) / P.k
      setViewNow({ k, x: cx - wx * k, y: cy - wy * k }, false)
    }
  }
  const onTouchEnd = () => { if (pinchRef.current) { pinchRef.current = null; setViewNow(viewRef.current) } }
  const onContextMenu = (e) => { e.preventDefault(); const p = toWorld(e.clientX, e.clientY), it = hit(p.x, p.y); if (it && !selRef.current.has(it.id)) setSel(new Set([it.id])); const r = wrapRef.current.getBoundingClientRect(); setCtx({ x: e.clientX - r.left, y: e.clientY - r.top, wx: p.x, wy: p.y, item: it }) }
  const onDrop = (e) => {
    e.preventDefault(); const p = toWorld(e.clientX, e.clientY)
    const files = [...(e.dataTransfer?.files || [])].filter((f) => f.type.startsWith('image/'))
    const target = hit(p.x, p.y, true)
    files.forEach((f, i) => uploadImage(f, p.x + i * 30, p.y + i * 30, target?.type === 'frame' && i === 0 ? target.id : null))
    const note = e.dataTransfer?.getData('application/x-note')
    if (note) { try { const n = JSON.parse(note); const it = addItem(n.image ? 'image' : (n.text || '').length > 140 ? 'text' : 'sticky', p.x, p.y, n.image ? { src: n.image, label: n.title || '' } : { text: [n.title, n.text].filter(Boolean).join('\n') }); if (it) { it.note_id = n.id; setSel(new Set([it.id])) } } catch {} }
    const txt = e.dataTransfer?.getData('text/plain')
    if (!files.length && !note && txt) { const it = addItem(txt.length > 140 ? 'text' : 'sticky', p.x, p.y, { text: txt }); if (it) setSel(new Set([it.id])) }
  }

  /* ---------- экспорт PNG ---------- */
  const exportPng = useCallback((onlySel) => {
    const items = onlySel && selRef.current.size ? selected() : itemsRef.current
    const b = bbox(items); if (!b) return null
    const pad = 40, scale = Math.min(2, 8000 / Math.max(b.w + pad * 2, b.h + pad * 2))
    const off = document.createElement('canvas'); off.width = Math.ceil((b.w + pad * 2) * scale); off.height = Math.ceil((b.h + pad * 2) * scale)
    const g = off.getContext('2d'), dark = isDark(), ink = themeColor('ink', dark)
    g.fillStyle = dark ? '#0e0e10' : '#ffffff'; g.fillRect(0, 0, off.width, off.height); g.scale(scale, scale); g.translate(pad - b.x, pad - b.y)
    const sorted = [...items].sort((a, c) => (a.z || 0) - (c.z || 0)), byId = byIdOf(itemsRef.current)
    const rr = (x, y, w, h, r) => { g.beginPath(); g.roundRect(x, y, w, h, Math.min(r, w / 2, h / 2)) }
    const rot = (it, bx, f) => { if (!it.rot) return f(); g.save(); g.translate(bx.x + bx.w / 2, bx.y + bx.h / 2); g.rotate(it.rot * Math.PI / 180); g.translate(-(bx.x + bx.w / 2), -(bx.y + bx.h / 2)); f(); g.restore() }
    for (const it of sorted) {
      const bx = itemBox(it)
      if (it.type === 'sticky') rot(it, bx, () => { g.fillStyle = STICKY[it.data.color]?.[dark ? 'dark' : 'light'] || it.data.color || '#fff3a3'; rr(it.x, it.y, it.w, it.h, 8); g.fill(); wrapText(g, it.data.text || '', it.x + 14, it.y + 14, it.w - 28, fontSize(it), it.data.text_color ? themeColor(it.data.text_color, dark) : stickyInk(it, dark), fontFamily(it), it.h - 24, it.data.align, it.data.bold, it.data.italic) })
      else if (it.type === 'text') rot(it, bx, () => wrapText(g, it.data.text || '', it.x + 8, it.y + 8, it.w - 16, fontSize(it), themeColor(it.data.text_color || 'ink', dark), fontFamily(it), it.h - 16, it.data.align, it.data.bold, it.data.italic))
      else if (it.type === 'frame') rot(it, bx, () => {
        const ih = frameWindow(it), fs = 13 * it.w / 320
        g.fillStyle = dark ? '#0b0b0d' : '#f3f3f1'; rr(it.x, it.y, it.w, ih, 8); g.fill()
        const im = imgCache.current.get(it.data.image); if (im?.complete && im.naturalWidth) { g.save(); rr(it.x, it.y, it.w, ih, 8); g.clip(); const s = Math.max(it.w / im.width, ih / im.height); g.drawImage(im, it.x + (it.w - im.width * s) / 2, it.y + (ih - im.height * s) / 2, im.width * s, im.height * s); g.restore() }
        g.strokeStyle = dark ? 'rgba(236,236,233,.3)' : 'rgba(14,14,14,.22)'; g.lineWidth = 1; rr(it.x, it.y, it.w, ih, 8); g.stroke()
        g.fillStyle = ink; g.font = `600 ${fs}px ui-monospace, monospace`; g.textBaseline = 'top'; g.textAlign = 'left'; g.fillText(String(it.data.n || ''), it.x + fs * .4, it.y + ih + fs * .6)
        if (it.data.seconds) { const s = fmtSec(it.data.seconds); g.font = `500 ${fs * .9}px ui-monospace, monospace`; g.fillText(s, it.x + it.w - g.measureText(s).width - fs * .4, it.y + ih + fs * .65) }
        wrapText(g, it.data.label || '', it.x + fs * 2, it.y + ih + fs * .5, it.w - fs * 5, fontSize(it) * it.w / 320, ink, fontFamily(it), captionHeight(it.w, it.data) - fs)
      })
      else if (it.type === 'image') rot(it, bx, () => { const im = imgCache.current.get(it.data.src); if (im?.complete && im.naturalWidth) { g.save(); rr(it.x, it.y, it.w, it.h, 6); g.clip(); g.drawImage(im, it.x, it.y, it.w, it.h); g.restore() } })
      else if (it.type === 'ink') { const pts = it.data.points || []; if (pts.length > 1) { g.strokeStyle = themeColor(it.data.color, dark); g.lineWidth = it.data.width || 3; g.lineCap = 'round'; g.lineJoin = 'round'; g.beginPath(); g.moveTo(pts[0][0], pts[0][1]); for (const p of pts) g.lineTo(p[0], p[1]); g.stroke() } }
      else if (it.type === 'arrow') { const pq = arrowPoints(it, byId); if (!pq) continue; const [p, q] = pq, lw = it.data.width || 2; g.strokeStyle = themeColor(it.data.color || 'ink', dark); g.lineWidth = lw; g.beginPath(); g.moveTo(p.x, p.y); g.lineTo(q.x, q.y); g.stroke(); if (it.data.style !== 'line') { const ang = Math.atan2(q.y - p.y, q.x - p.x), L = 6 + lw * 3; g.fillStyle = g.strokeStyle; g.beginPath(); g.moveTo(q.x, q.y); g.lineTo(q.x - L * Math.cos(ang - .42), q.y - L * Math.sin(ang - .42)); g.lineTo(q.x - L * Math.cos(ang + .42), q.y - L * Math.sin(ang + .42)); g.closePath(); g.fill() } if (it.data.label) { const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2, fs = fontSize(it) || 13; g.font = `500 ${fs}px ${fontFamily(it)}`; const tw = g.measureText(it.data.label).width + fs; g.fillStyle = dark ? '#141416' : '#fff'; rr(mx - tw / 2, my - fs * .8, tw, fs * 1.6, fs * .4); g.fill(); g.fillStyle = ink; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(it.data.label, mx, my); g.textAlign = 'left' } }
    }
    return off.toDataURL('image/png')
  }, [])
  fn.current.exportPng = exportPng

  /* ---------- HTML-слой ---------- */
  const dark = isDark()
  const htmlItems = itemsRef.current.filter((i) => i.type === 'sticky' || i.type === 'text' || i.type === 'frame' || (i.type === 'arrow' && editing === i.id))
  const cursor = spaceDown || tool === 'hand' ? (dragRef.current?.kind === 'pan' ? 'grabbing' : 'grab') : tool === 'select' ? undefined : tool === 'eraser' ? 'cell' : 'crosshair'
  const byId = byIdOf(itemsRef.current)
  return (
    <div ref={wrapRef} className="board-wrap relative h-full w-full select-none overflow-hidden" style={{ cursor, touchAction: 'none' }}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp} onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu} onDragOver={(e) => e.preventDefault()} onDrop={onDrop} onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}>
      <canvas ref={canvasRef} className="absolute inset-0" />
      <div className="absolute left-0 top-0" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`, transformOrigin: '0 0', pointerEvents: 'none' }}>
        {htmlItems.map((it) => {
          const isEd = editing === it.id, fs = fontSize(it), ff = fontFamily(it)
          const common = { fontFamily: ff, fontWeight: it.data.bold ? 700 : 400, fontStyle: it.data.italic ? 'italic' : 'normal', textAlign: it.data.align || 'left' }
          if (it.type === 'arrow') {
            const pq = arrowPoints(it, byId); if (!pq) return null
            const mx = (pq[0].x + pq[1].x) / 2, my = (pq[0].y + pq[1].y) / 2
            return <div key={it._key} className="absolute -translate-x-1/2 -translate-y-1/2 rounded-md px-2 py-0.5" style={{ left: mx, top: my, background: 'var(--surface)', outline: '1px solid var(--accent)', pointerEvents: 'auto', fontSize: fs || 13, minWidth: 60, ...common }}>
              <EditableText it={it} field="label" editing placeholder="подпись" single onChange={(v) => { it.data = { ...it.data, label: v } }} onDone={stopEdit} />
            </div>
          }
          const b = itemBox(it), rotStyle = it.rot ? { transform: `rotate(${it.rot}deg)`, transformOrigin: 'center' } : {}
          if (it.type === 'frame') {
            const ih = frameWindow(it), scale = it.w / 320, cap = b.h - ih
            return (
              <div key={it._key} className="absolute" style={{ left: it.x, top: it.y, width: it.w, height: b.h, zIndex: it.z, pointerEvents: 'none', ...rotStyle }}>
                <div className="absolute left-0 flex items-start gap-2" style={{ top: ih, width: it.w, height: cap, padding: `${8 * scale}px ${10 * scale}px`, pointerEvents: isEd ? 'auto' : 'none' }}>
                  <span className="mono shrink-0 font-semibold" style={{ fontSize: 13 * scale, lineHeight: 1.35, color: 'var(--ink-2)', paddingTop: 1 * scale }}>{it.data.n || '·'}</span>
                  <EditableText it={it} field="label" editing={isEd} placeholder="что в кадре" className="min-w-0 flex-1" style={{ fontSize: fs * scale, lineHeight: 1.35, color: it.data.text_color ? themeColor(it.data.text_color, dark) : 'var(--ink)', ...common }}
                    onChange={(v) => { it.data = { ...it.data, label: v }; it.h = frameHeight(it.w, it.data) }} onDone={stopEdit} />
                </div>
              </div>
            )
          }
          if (it.type === 'sticky') {
            const bg = STICKY[it.data.color]?.[dark ? 'dark' : 'light'] || it.data.color || STICKY.yellow.light
            const pad = Math.max(8, Math.min(it.w, it.h) * .07)
            return (
              <div key={it._key} className="absolute overflow-hidden" style={{ left: it.x, top: it.y, width: it.w, height: it.h, zIndex: it.z, background: bg, borderRadius: Math.max(4, Math.min(it.w, it.h) * .035), padding: pad, boxShadow: dark ? '0 8px 22px -10px rgba(0,0,0,.7)' : '0 8px 22px -12px rgba(14,14,14,.35)', pointerEvents: isEd ? 'auto' : 'none', color: it.data.text_color ? themeColor(it.data.text_color, dark) : stickyInk(it, dark), ...rotStyle }}>
                <div className="flex h-full w-full flex-col justify-center"><EditableText it={it} field="text" editing={isEd} placeholder="…" className="max-h-full w-full overflow-hidden" style={{ fontSize: fs, lineHeight: 1.25, ...common }} onChange={(v) => { it.data = { ...it.data, text: v } }} onDone={stopEdit} /></div>
              </div>
            )
          }
          return (
            <div key={it._key} className="absolute overflow-hidden" style={{ left: it.x, top: it.y, width: it.w, minHeight: it.h, zIndex: it.z, padding: 8, borderRadius: 8, color: themeColor(it.data.text_color || 'ink', dark), fontSize: fs, lineHeight: 1.4, pointerEvents: isEd ? 'auto' : 'none', background: isEd ? 'var(--surface)' : 'transparent', outline: isEd ? '1px solid var(--accent)' : 'none', ...common, ...rotStyle }}>
              <EditableText it={it} field="text" editing={isEd} placeholder="Текст" className="whitespace-pre-wrap" md onChange={(v) => { it.data = { ...it.data, text: v } }} onDone={stopEdit} onGrow={(h) => { if (h + 16 > it.h) { it.h = h + 16; bump() } }} />
            </div>
          )
        })}
      </div>
      <input ref={fileInputRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { const fs = [...e.target.files]; e.target.value = ''; const at = imageDrop.current || (() => { const el = wrapRef.current, v = viewRef.current; return { x: (el.clientWidth / 2 - v.x) / v.k, y: (el.clientHeight / 2 - v.y) / v.k } })(); imageDrop.current = null; fs.forEach((f, i) => uploadImage(f, at.x + i * 30, at.y + i * 30)) }} />
      {ctx && <ContextMenu m={ctx} onClose={() => setCtx(null)} hasSel={sel.size > 0} readOnly={readOnly} onAct={(a) => {
        setCtx(null)
        if (a === 'sticky' || a === 'text' || a === 'frame') { const [w, h] = DEFAULT_SIZE[a]; const it = addItem(a, ctx.wx - w / 2, ctx.wy - (h || 180) / 2); if (it) { setSel(new Set([it.id])); if (a !== 'frame') startEdit(it.id) } }
        if (a === 'dup') duplicateSel(); if (a === 'del') deleteSel(); if (a === 'front') bringTo(true); if (a === 'back') bringTo(false)
        if (a === 'edit') { const id = [...selRef.current][0]; if (id) startEdit(id) }
        if (a === 'lock') setSelData({ locked: !selected()[0]?.data?.locked })
      }} />}
    </div>
  )
}

/* Текст с правкой на месте. Пока объект не редактируется — обычный div. В режиме правки — contentEditable,
   куда текст кладётся ОДИН раз (не через children React — иначе на каждом вводе DOM переписывается и буквы прыгают/дублируются). */
function EditableText({ it, field, editing, placeholder, className = '', style, onChange, onDone, single, md, onGrow }) {
  const ref = useRef(null)
  const startVal = useRef('')
  useLayoutEffect(() => {
    if (!editing || !ref.current) return
    const el = ref.current; startVal.current = it.data[field] || ''
    el.textContent = startVal.current
    el.focus({ preventScroll: true })
    const sel = window.getSelection()
    // если правку открыли двойным кликом по тексту — браузер уже выделил слово под курсором; иначе каретка в конец
    const inside = sel && sel.rangeCount && el.contains(sel.anchorNode) && !sel.isCollapsed
    if (!inside) { const r = document.createRange(); r.selectNodeContents(el); r.collapse(false); sel.removeAllRanges(); sel.addRange(r) }
    onGrow?.(el.scrollHeight)
  }, [editing]) // eslint-disable-line
  const val = it.data[field] || ''
  if (!editing) return <div className={`${className} ${val ? '' : 'opacity-40'}`} style={style}>{val ? (md ? <Md text={val} /> : val) : placeholder}</div>
  return (
    <div ref={ref} contentEditable suppressContentEditableWarning spellCheck={false} className={`${className} outline-none`} style={{ ...style, whiteSpace: 'pre-wrap', wordBreak: 'break-word', cursor: 'text', minHeight: '1em' }}
      onInput={(e) => { onChange(e.currentTarget.innerText.replace(/\n$/, '')); onGrow?.(e.currentTarget.scrollHeight) }}
      onBlur={() => { if (ref.current) onDone() }}
      onPointerDown={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()} onContextMenu={(e) => e.stopPropagation()}
      onPaste={(e) => { e.preventDefault(); const t = e.clipboardData.getData('text/plain'); document.execCommand('insertText', false, single ? t.replace(/\n+/g, ' ') : t) }}
      onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Escape') { e.preventDefault(); e.currentTarget.textContent = startVal.current; onChange(startVal.current); e.currentTarget.blur(); return } if ((single && e.key === 'Enter') || (!single && e.key === 'Enter' && (e.ctrlKey || e.metaKey))) { e.preventDefault(); e.currentTarget.blur() } }} />
  )
}

/* Маркдаун-лайт для текстовых блоков и сценариев */
function Md({ text }) {
  return String(text).split('\n').map((l, i) => {
    if (/^#\s/.test(l)) return <div key={i} className="mb-1 text-[1.5em] font-semibold tracking-[-0.02em]">{inline(l.slice(2))}</div>
    if (/^##\s/.test(l)) return <div key={i} className="mb-0.5 mt-1 text-[1.2em] font-semibold">{inline(l.slice(3))}</div>
    if (/^(СЦЕНА|SCENE|ЭПИЗОД|КАДР)\b/i.test(l)) return <div key={i} className="mono mt-3 text-[.85em] font-semibold uppercase tracking-[0.06em]">{inline(l)}</div>
    if (/^[-•]\s/.test(l)) return <div key={i} className="flex gap-2"><span className="opacity-50">•</span><span>{inline(l.slice(2))}</span></div>
    if (/^[А-ЯЁA-Z][А-ЯЁA-Z -]{1,24}$/.test(l.trim()) && !/\d/.test(l) && l.trim().split(/\s+/).length <= 3) return <div key={i} className="mt-2 text-center font-semibold uppercase tracking-[0.04em] opacity-80">{l.trim()}</div>
    return <div key={i} className={l.trim() ? '' : 'h-[.8em]'}>{inline(l)}</div>
  })
}
function inline(s) { return s.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).map((p, i) => p.startsWith('**') && p.endsWith('**') ? <b key={i}>{p.slice(2, -2)}</b> : p.startsWith('_') && p.endsWith('_') && p.length > 2 ? <i key={i}>{p.slice(1, -1)}</i> : p) }

function ContextMenu({ m, onClose, onAct, hasSel, readOnly }) {
  useEffect(() => { const h = () => onClose(); window.addEventListener('pointerdown', h, { once: true, capture: true }); return () => window.removeEventListener('pointerdown', h, { capture: true }) }, [onClose])
  const Item = ({ a, icon: I, children, danger }) => <button className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[13px] hover:bg-[var(--fill)] ${danger ? 'neg' : ''}`} onPointerDown={(e) => { e.stopPropagation(); e.preventDefault(); onAct(a) }}><I size={14} className="faint" />{children}</button>
  const el = document.querySelector('.board-wrap'); const W = el?.clientWidth || 800, H = el?.clientHeight || 600
  return (
    <div className="elevated absolute z-[60] w-[210px] !p-1.5" style={{ left: Math.min(m.x, W - 220), top: Math.min(m.y, H - 260) }} onPointerDown={(e) => e.stopPropagation()}>
      {!readOnly && !m.item && <><Item a="sticky" icon={StickyNote}>стикер</Item><Item a="text" icon={Type}>текст</Item><Item a="frame" icon={Film}>кадр</Item></>}
      {m.item && ['sticky', 'text', 'frame', 'arrow'].includes(m.item.type) && !readOnly && <Item a="edit" icon={Pencil}>редактировать <span className="kbd ml-auto">↵</span></Item>}
      {hasSel && !readOnly && <>
        <Item a="dup" icon={Copy}>дублировать <span className="kbd ml-auto">⌘D</span></Item>
        <Item a="front" icon={ArrowUpRight}>на передний план <span className="kbd ml-auto">PgUp</span></Item>
        <Item a="back" icon={ChevronDown}>на задний план <span className="kbd ml-auto">PgDn</span></Item>
        <div className="my-1 border-t hair" />
        <Item a="del" icon={Trash2} danger>удалить <span className="kbd ml-auto">⌫</span></Item>
      </>}
    </div>
  )
}

/* ---------- геометрия перемещений ---------- */
function handles(b) { const { x, y, w, h } = b; return [[x, y], [x + w / 2, y], [x + w, y], [x + w, y + h / 2], [x + w, y + h], [x + w / 2, y + h], [x, y + h], [x, y + h / 2]] }
function unrotate(it, b, x, y) { if (!it.rot) return { x, y }; const cx = b.x + b.w / 2, cy = b.y + b.h / 2, a = -it.rot * Math.PI / 180, dx = x - cx, dy = y - cy; return { x: cx + dx * Math.cos(a) - dy * Math.sin(a), y: cy + dx * Math.sin(a) + dy * Math.cos(a) } }
function moveBy(it, dx, dy) { if (it.type === 'ink') it.data.points = it.data.points.map(([x, y]) => [x + dx, y + dy]); else if (it.type === 'arrow') { const f = it.data.from, t = it.data.to; if (f.item == null) it.data.from = { x: f.x + dx, y: f.y + dy }; if (t.item == null) it.data.to = { x: t.x + dx, y: t.y + dy } } else { it.x += dx; it.y += dy } }
function placeFrom(it, o, dx, dy, snap) {
  if (it.type === 'ink') { it.data.points = o.data.points.map(([x, y]) => [x + dx, y + dy]); return }
  if (it.type === 'arrow') { const f = o.data.from, t = o.data.to; if (f.item == null) it.data.from = { x: f.x + dx, y: f.y + dy }; if (t.item == null) it.data.to = { x: t.x + dx, y: t.y + dy }; return }
  it.x = o.x + dx; it.y = o.y + dy; if (snap) { it.x = Math.round(it.x / snap) * snap; it.y = Math.round(it.y / snap) * snap }
}
function scaleFrom(it, o, ax, ay, s) {
  if (it.type === 'ink') { it.data.points = o.data.points.map(([x, y]) => [ax + (x - ax) * s, ay + (y - ay) * s]); it.data.width = Math.max(1, o.data.width * s); return }
  if (it.type === 'arrow') { const f = o.data.from, t = o.data.to; if (f.item == null) it.data.from = { x: ax + (f.x - ax) * s, y: ay + (f.y - ay) * s }; if (t.item == null) it.data.to = { x: ax + (t.x - ax) * s, y: ay + (t.y - ay) * s }; return }
  it.x = ax + (o.x - ax) * s; it.y = ay + (o.y - ay) * s; it.w = Math.max(24, o.w * s); it.h = it.type === 'frame' ? frameHeight(it.w, it.data) : Math.max(24, o.h * s)
  if (it.type === 'sticky' || it.type === 'text') it.data = { ...it.data, font_size: Math.max(6, +((o.data.font_size || fontSize(o)) * s).toFixed(1)) }
}
function wrapText(g, text, x, y, maxW, size, color, font, maxH, align = 'left', bold, italic) {
  g.fillStyle = color; g.font = `${italic ? 'italic ' : ''}${bold ? 700 : 400} ${size}px ${font}`; g.textBaseline = 'top'; g.textAlign = 'left'
  const lh = size * 1.3; let yy = y
  const put = (line) => { const w = g.measureText(line).width; const lx = align === 'center' ? x + (maxW - w) / 2 : align === 'right' ? x + maxW - w : x; g.fillText(line, lx, yy); yy += lh }
  for (const para of String(text).split('\n')) {
    let line = ''
    for (const w of para.split(' ')) { const t = line ? line + ' ' + w : w; if (g.measureText(t).width > maxW && line) { put(line); line = w; if (maxH && yy - y > maxH - lh) return } else line = t }
    put(line); if (maxH && yy - y > maxH - lh) return
  }
}
