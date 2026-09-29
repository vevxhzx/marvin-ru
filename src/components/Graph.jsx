import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

/* Граф «второго мозга»: люди · заказы · заметки · ссылки · теги. Связи выводятся сами (имена, теги, [[скобки]], смысл).
   Простой force-layout на canvas без библиотек. Клик по узлу — фокус на его окрестности; двойной клик — открыть. */
const COLORS = {
  person: 'var(--accent)', order: 'var(--warn)', note: 'var(--ink)', link: 'var(--pos)', tag: 'var(--ink-3)',
  debt: 'var(--neg)', goal: 'var(--pos)', task: 'var(--ink-2)', event: 'var(--ink-2)', money: 'var(--warn)', project: 'var(--ink-3)',
}
const KIND_RU = { person: 'люди', order: 'заказы', note: 'мысли', link: 'ссылки', tag: 'теги', debt: 'долги', goal: 'цели', task: 'задачи', event: 'встречи', money: 'деньги', project: 'проекты' }
const KIND_ONE = { person: 'человек', order: 'заказ', note: 'мысль', link: 'ссылка', tag: 'тег', debt: 'долг', goal: 'цель', task: 'задача', event: 'встреча', money: 'категория', project: 'проект' }
// как связаны — по-русски, для подсказки при наведении
const REL_RU = { client: 'клиент', mention: 'упоминание', tag: 'тег', wiki: '[[ссылка]]', similar: 'по смыслу', debt: 'кредитор', work: 'работа', project: 'проект', pay: 'оплата', same: 'та же тема' }
const LEGEND = ['person', 'order', 'money', 'note', 'link', 'tag', 'debt', 'task']
const cssVar = (name, el) => getComputedStyle(el || document.documentElement).getPropertyValue(name.slice(4, -1)).trim() || '#888'

export default function Graph({ height = 520, focus: initialFocus = null, compact = false }) {
  const [data, setData] = useState(null)
  const [focus, setFocus] = useState(initialFocus)
  const [hover, setHover] = useState(null)
  const hoverRef = useRef(null)          // наведение читаем из ref, а не из зависимостей эффекта — иначе физика стартовала бы с нуля на каждое движение мыши
  hoverRef.current = hover
  const alphaRef = useRef(1)             // «температура» раскладки: 1 — разлетается и ищет место, ~0 — стоит. Взаимодействие подогревает мягко
  const warm = (t) => { alphaRef.current = Math.max(alphaRef.current, t) }
  const [hidden, setHidden] = useState(() => new Set())
  const canvasRef = useRef(null)
  const nodesRef = useRef([])
  const dragRef = useRef(null)
  const viewRef = useRef({ x: 0, y: 0, k: 1, user: false })   // user=true — человек сам двигал/масштабировал, авто-подгонку выключаем
  const nav = useNavigate()

  useEffect(() => { api.get(`/api/graph${focus ? `?focus=${encodeURIComponent(focus)}` : ''}`).then(setData).catch(() => setData({ nodes: [], edges: [], stats: {} })) }, [focus])

  // раскладка: узлы с позициями сохраняются между перерисовками по id
  const layout = useMemo(() => {
    if (!data) return null
    const prev = new Map(nodesRef.current.map((n) => [n.id, n]))
    const nodes = data.nodes.filter((n) => !hidden.has(n.kind)).map((n, i) => {
      const p = prev.get(n.id)
      const a = (i / Math.max(1, data.nodes.length)) * Math.PI * 2
      return { ...n, x: p?.x ?? Math.cos(a) * 200 + (Math.random() - 0.5) * 40, y: p?.y ?? Math.sin(a) * 200 + (Math.random() - 0.5) * 40, vx: 0, vy: 0, r: 4 + Math.min(10, Math.sqrt(n.deg || 0) * 2.2) + (n.kind === 'person' ? 3 : 0) }
    })
    const idx = new Map(nodes.map((n) => [n.id, n]))
    const edges = data.edges.filter((e) => idx.has(e.source) && idx.has(e.target)).map((e) => ({ ...e, a: idx.get(e.source), b: idx.get(e.target) }))
    return { nodes, edges }
  }, [data, hidden])

  useEffect(() => {
    if (!layout) return
    nodesRef.current = layout.nodes
    const cv = canvasRef.current; if (!cv) return
    const ctx = cv.getContext('2d')
    let raf, running = true
    alphaRef.current = 1
    const dpr = window.devicePixelRatio || 1
    const resize = () => { const w = cv.clientWidth, h = cv.clientHeight; cv.width = w * dpr; cv.height = h * dpr }
    resize()
    const ro = new ResizeObserver(resize); ro.observe(cv)
    const { nodes, edges } = layout
    const col = (k) => cssVar(COLORS[k] || 'var(--ink-3)', cv)
    const palette = Object.fromEntries(Object.keys(COLORS).map((k) => [k, col(k)]))
    const line = cssVar('var(--line-2)', cv), ink = cssVar('var(--ink)', cv), bg = cssVar('var(--bg)', cv), ink3 = cssVar('var(--ink-3)', cv)

    const rep = Math.min(900, 220 + nodes.length * 6)   // маленький граф не разлетается
    const fit = () => {
      // подгоняем масштаб под всё облако с полями
      if (!nodes.length || viewRef.current.user) return
      const xs = nodes.map((n) => n.x).sort((a, b) => a - b), ys = nodes.map((n) => n.y).sort((a, b) => a - b)
      const q = (arr, p) => arr[Math.min(arr.length - 1, Math.floor(arr.length * p))]
      const x0 = q(xs, 0.04), x1 = q(xs, 0.96), y0 = q(ys, 0.04), y1 = q(ys, 0.96)
      const w = cv.width / dpr, h = cv.height / dpr
      const k = Math.max(0.5, Math.min(1.5, Math.min((w - 160) / Math.max(120, x1 - x0), (h - 170) / Math.max(120, y1 - y0))))
      const v = viewRef.current
      v.k += (k - v.k) * 0.08; v.x += (-(x0 + x1) / 2 * k - v.x) * 0.08; v.y += (-(y0 + y1) / 2 * k - v.y) * 0.08
    }
    const step = () => {
      // силы: отталкивание (грубое O(n²), до ~600 узлов ок), притяжение по рёбрам, к центру
      const alpha = alphaRef.current
      if (alpha > 0.005) {
        for (let i = 0; i < nodes.length; i++) {
          const a = nodes[i]
          for (let j = i + 1; j < nodes.length; j++) {
            const b = nodes[j]
            let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy + 0.01
            if (d2 > 90000) continue
            const f = rep / d2
            dx *= f; dy *= f
            a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy
          }
          const g = a.deg ? 0.008 : 0.02
          a.vx -= a.x * g; a.vy -= a.y * g
        }
        for (const e of edges) {
          const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y, d = Math.sqrt(dx * dx + dy * dy) || 1
          const want = e.rel === 'tag' || e.rel === 'work' ? 70 : e.rel === 'similar' ? 90 : e.rel === 'pay' || e.rel === 'project' ? 55 : 60
          const f = ((d - want) / d) * 0.03 * (e.w || 1)
          e.a.vx += dx * f; e.a.vy += dy * f; e.b.vx -= dx * f; e.b.vy -= dy * f
        }
        for (const n of nodes) {
          if (dragRef.current?.node === n) { n.vx = n.vy = 0; continue }
          n.vx *= 0.6; n.vy *= 0.6
          n.x += n.vx * alpha; n.y += n.vy * alpha
        }
        alphaRef.current = alpha * 0.985
      }
      fit()
      // рисуем
      const w = cv.width / dpr, h = cv.height / dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      const v = viewRef.current
      ctx.save(); ctx.translate(w / 2 + v.x, h / 2 + v.y); ctx.scale(v.k, v.k)
      const hover = hoverRef.current
      const hi = hover ? new Set([hover.id, ...edges.filter((e) => e.a.id === hover.id || e.b.id === hover.id).flatMap((e) => [e.a.id, e.b.id])]) : null
      for (const e of edges) {
        const dim = hi && !(hi.has(e.a.id) && hi.has(e.b.id) && (e.a.id === hover.id || e.b.id === hover.id))
        ctx.strokeStyle = e.rel === 'similar' ? ink3 : line
        ctx.globalAlpha = dim ? 0.15 : e.rel === 'similar' ? 0.5 : 0.9
        ctx.lineWidth = e.rel === 'client' || e.rel === 'wiki' || e.rel === 'pay' ? 1.6 : 1
        ctx.setLineDash(e.rel === 'similar' ? [3, 4] : [])
        ctx.beginPath(); ctx.moveTo(e.a.x, e.a.y); ctx.lineTo(e.b.x, e.b.y); ctx.stroke()
      }
      ctx.setLineDash([])
      for (const n of nodes) {
        const dim = hi && !hi.has(n.id)
        ctx.globalAlpha = dim ? 0.25 : 1
        ctx.fillStyle = palette[n.kind] || ink3
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill()
        if (n.kind === 'note' || n.kind === 'tag' || n.kind === 'money' || n.kind === 'project') { ctx.fillStyle = bg; ctx.beginPath(); ctx.arc(n.x, n.y, Math.max(1, n.r - 2), 0, Math.PI * 2); ctx.fill(); ctx.fillStyle = palette[n.kind]; ctx.beginPath(); ctx.arc(n.x, n.y, Math.max(0.5, n.r - 3.5), 0, Math.PI * 2); ctx.fill() }
        const showLabel = n.kind === 'person' || n.r > 8 || (hi && hi.has(n.id)) || v.k > 1.4 || nodes.length < 60
        if (showLabel) {
          ctx.globalAlpha = dim ? 0.3 : 0.9
          ctx.fillStyle = ink
          const fs = (n.kind === 'person' ? 12 : 11) / Math.max(0.75, Math.min(1, v.k))
          ctx.font = `${n.kind === 'person' ? 600 : 400} ${fs}px Inter, system-ui, sans-serif`
          ctx.textAlign = 'center'
          ctx.fillText(n.label.length > 26 ? n.label.slice(0, 25) + '…' : n.label, n.x, n.y + n.r + fs + 1)
        }
      }
      ctx.restore(); ctx.globalAlpha = 1
      if (running) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => { running = false; cancelAnimationFrame(raf); ro.disconnect() }
  }, [layout])

  // мышь: наведение, перетаскивание узла, панорама, колесо — масштаб
  const toWorld = (e) => {
    const cv = canvasRef.current, r = cv.getBoundingClientRect(), v = viewRef.current
    return { x: (e.clientX - r.left - r.width / 2 - v.x) / v.k, y: (e.clientY - r.top - r.height / 2 - v.y) / v.k }
  }
  const pick = (p) => nodesRef.current.find((n) => (n.x - p.x) ** 2 + (n.y - p.y) ** 2 <= (n.r + 4) ** 2)
  const onDown = (e) => { const p = toWorld(e); const n = pick(p); dragRef.current = n ? { node: n, moved: false } : { pan: true, sx: e.clientX, sy: e.clientY, ox: viewRef.current.x, oy: viewRef.current.y, moved: false }; e.currentTarget.setPointerCapture(e.pointerId) }
  const onMove = (e) => {
    const d = dragRef.current
    if (d?.node) { const p = toWorld(e); d.node.x = p.x; d.node.y = p.y; d.moved = true; warm(0.35); return }
    if (d?.pan) { viewRef.current.x = d.ox + (e.clientX - d.sx); viewRef.current.y = d.oy + (e.clientY - d.sy); if (Math.abs(e.clientX - d.sx) > 3) { d.moved = true; viewRef.current.user = true } return }
    const n = pick(toWorld(e)); if (n?.id !== hover?.id) { setHover(n || null); warm(0.12) }
  }
  const onUp = (e) => {
    const d = dragRef.current; dragRef.current = null
    if (d?.node && d.moved) warm(0.5)   // отпустили — соседи доезжают на новое место
    if (d?.node && !d.moved) setFocus((f) => (f === d.node.id ? null : d.node.id))
  }
  const onDbl = (e) => {
    const n = pick(toWorld(e)); if (!n) { viewRef.current.user = false; return }
    const to = { person: `/people?id=${n.ref_id}`, order: '/orders', note: `/mind?q=${encodeURIComponent(n.label.slice(0, 40))}`, link: n.url || '/mind', tag: `/mind?q=${encodeURIComponent(n.label)}`, debt: '/finance', goal: '/finance', task: '/tasks', event: '/calendar', money: '/finance', project: '/tasks' }[n.kind]
    if (!to) return
    if (to.startsWith('http')) window.open(to, '_blank', 'noopener'); else nav(to)
  }
  const onWheel = (e) => { e.preventDefault(); const v = viewRef.current; v.user = true; v.k = Math.max(0.3, Math.min(4, v.k * (e.deltaY < 0 ? 1.1 : 0.9))) }
  useEffect(() => { const cv = canvasRef.current; cv?.addEventListener('wheel', onWheel, { passive: false }); return () => cv?.removeEventListener('wheel', onWheel) }, [])

  const st = data?.stats || {}
  const empty = data && data.nodes.length === 0
  // «клиент: Кот Прод · оплата: Доход по заказам · упоминание: 3»
  const hoverRels = useMemo(() => {
    if (!hover || !layout) return ''
    const by = {}
    for (const e of layout.edges) {
      const other = e.a.id === hover.id ? e.b : e.b.id === hover.id ? e.a : null
      if (other) (by[e.rel] = by[e.rel] || []).push(other.label)
    }
    return Object.entries(by).map(([r, ls]) => `${REL_RU[r] || r}: ${ls.length <= 2 ? ls.map((l) => (l.length > 22 ? l.slice(0, 21) + '…' : l)).join(', ') : ls.length}`).join(' · ')
  }, [hover, layout])
  return (
    <div className="relative">
      <canvas ref={canvasRef} className="w-full rounded-3xl" style={{ height, background: 'var(--fill)', cursor: hover ? 'pointer' : 'grab', touchAction: 'none' }}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => setHover(null)} onDoubleClick={onDbl} />
      {!compact && (
        <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap gap-1.5">
          {LEGEND.map((k) => (
            <button key={k} type="button" className={`pointer-events-auto chip !bg-[var(--bg)] ${hidden.has(k) ? 'opacity-40' : ''}`} onClick={() => setHidden((h) => { const n = new Set(h); n.has(k) ? n.delete(k) : n.add(k); return n })}>
              <span className="h-2 w-2 rounded-full" style={k === 'money' || k === 'tag' || k === 'note' ? { border: `1.5px solid ${COLORS[k]}` } : { background: COLORS[k] }} />{KIND_RU[k]}
            </button>
          ))}
        </div>
      )}
      {focus && <button type="button" className="btn-soft btn-sm absolute right-3 top-3" onClick={() => { viewRef.current.user = false; setFocus(null) }}>весь граф</button>}
      {hover && <div className="pointer-events-none absolute bottom-3 left-3 max-w-[70%] rounded-xl px-3 py-1.5 text-[12.5px]" style={{ background: 'var(--ink)', color: 'var(--bg)' }}>
        {KIND_ONE[hover.kind] || hover.kind} · {hover.label}{hover.kind === 'money' && hover.total ? ` · ${hover.total.toLocaleString('ru-RU')} ₽` : ''}{hover.kind === 'order' && hover.price ? ` · ${hover.paid ? `${hover.paid.toLocaleString('ru-RU')} из ` : ''}${hover.price.toLocaleString('ru-RU')} ₽` : ''}
        {hoverRels && <div className="mt-0.5 text-[11.5px] opacity-75">{hoverRels}</div>}
      </div>}
      {!compact && data && !empty && <div className="faint absolute bottom-3 right-3 text-[11.5px]">{st.people || 0} людей · {st.notes || 0} мыслей · {st.links || 0} ссылок · {st.edges || 0} связей{st.lonely ? ` · без связей: ${st.lonely}` : ''}</div>}
      {empty && <div className="absolute inset-0 grid place-items-center text-center"><div><div className="text-[14px] font-medium">Связей пока нет</div><div className="muted mt-1 max-w-[320px] text-[12.5px]">Заведите людей («человек: Лена, сестра»), ставьте #теги в мыслях и ссылайтесь на другие мысли через [[двойные скобки]] — граф соберётся сам.</div></div></div>}
    </div>
  )
}
