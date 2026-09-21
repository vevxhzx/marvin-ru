/* Геометрия и модель доски — одна на редактор, экспорт и панели.
   Высота кадра считается так же, как на сервере (core/services/boards.py::frame_height):
   окно под соотношение + подпись, которая масштабируется вместе с кадром. */

export const RATIOS = { '16:9': 16 / 9, '9:16': 9 / 16, '1:1': 1, '4:5': 4 / 5, '4:3': 4 / 3, '2.39:1': 2.39 }
export const STICKY = {
  yellow: { light: '#fff3a3', dark: '#6b5f1e' }, pink: { light: '#ffd1dc', dark: '#6e2f40' }, blue: { light: '#cfe3ff', dark: '#274470' },
  green: { light: '#d5f2d5', dark: '#28522f' }, purple: { light: '#e6d5ff', dark: '#47306f' }, gray: { light: '#e8e8e6', dark: '#3f3f3f' },
}
export const FONTS = { inter: '"Inter Variable", Inter, system-ui, sans-serif', arial: 'Arial, Helvetica, sans-serif', serif: 'Georgia, "Times New Roman", serif', mono: '"JetBrains Mono Variable", ui-monospace, monospace' }
export const FONT_LABEL = { inter: 'Inter', arial: 'Arial', serif: 'Serif', mono: 'Mono' }
export const TEXT_COLORS = ['ink', 'accent', 'red', 'warn', 'green', 'white', 'black']
export const INK_COLORS = ['ink', 'accent', 'red', 'green', 'warn']
export const FONT_SIZES = [12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64, 96]
export const MIN_K = 0.05, MAX_K = 8
export const DEFAULT_SIZE = { sticky: [200, 200], text: [360, 120], frame: [320, 0], image: [320, 240] }
export const LEGACY_TEXT_SIZE = { sm: 13, md: 15, lg: 20, xl: 30 }

export const uid = () => -Math.floor(Math.random() * 2 ** 40) - 1

/** размер шрифта объекта с учётом старого поля size у текстов */
export function fontSize(it) {
  if (it.data.font_size) return +it.data.font_size
  if (it.type === 'text') return LEGACY_TEXT_SIZE[it.data.size] || 15
  if (it.type === 'frame') return 18
  return 18
}
export function fontFamily(it) { return FONTS[it.data.font] || FONTS.inter }

/** высота подписи кадра — зависит от ширины (масштаб) и длины подписи; та же формула на сервере */
export function captionHeight(w, data) {
  const scale = w / 320
  const size = +(data.font_size || 18)
  const chars = Math.max(1, Math.floor(292 / (size * .56)))
  const lines = String(data.label || '').split('\n').reduce((a, l) => a + Math.max(1, Math.ceil(l.length / chars)), 0)
  return Math.max(54, Math.min(8, lines) * size * 1.35 + 22) * scale
}
export function frameHeight(w, data) { return w / (RATIOS[data.ratio] || 16 / 9) + captionHeight(w, data) }
export function frameWindow(it) { return it.w / (RATIOS[it.data.ratio] || 16 / 9) }

export function itemBox(it) {
  if (it.type === 'ink') {
    const pts = it.data.points || []
    if (!pts.length) return { x: it.x, y: it.y, w: 1, h: 1 }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const [px, py] of pts) { if (px < x0) x0 = px; if (py < y0) y0 = py; if (px > x1) x1 = px; if (py > y1) y1 = py }
    const p = (it.data.width || 3) / 2 + 2
    return { x: x0 - p, y: y0 - p, w: x1 - x0 + p * 2, h: y1 - y0 + p * 2 }
  }
  if (it.type === 'arrow') return null
  return { x: it.x, y: it.y, w: it.w, h: it.type === 'frame' ? frameHeight(it.w, it.data) : it.h }
}
export function bbox(items) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, any = false
  for (const it of items) {
    const b = itemBox(it); if (!b) continue
    any = true; x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y); x1 = Math.max(x1, b.x + b.w); y1 = Math.max(y1, b.y + b.h)
  }
  return any ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null
}
export const inBox = (b, x, y) => !!b && x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h
export const normRect = (m) => ({ x: Math.min(m.x, m.x + m.w), y: Math.min(m.y, m.y + m.h), w: Math.abs(m.w), h: Math.abs(m.h) })
export const rectsIntersect = (a, b) => !!a && !!b && a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
export function distSeg(px, py, a, b) { const dx = b.x - a.x, dy = b.y - a.y; const l2 = dx * dx + dy * dy || 1; let t = ((px - a.x) * dx + (py - a.y) * dy) / l2; t = Math.max(0, Math.min(1, t)); return Math.hypot(px - (a.x + t * dx), py - (a.y + t * dy)) }

/* ---- стрелки: концы привязаны к точке на объекте (u,v в долях его рамки), а не к центру ---- */
export function anchorPoint(end, byId) {
  if (!end) return null
  if (end.item != null) {
    const it = byId.get(end.item); if (!it) return null
    const b = itemBox(it); if (!b) return null
    const u = end.u == null ? .5 : end.u, v = end.v == null ? .5 : end.v
    return { x: b.x + b.w * u, y: b.y + b.h * v }
  }
  return { x: end.x, y: end.y }
}
/** ближайшая точка на границе рамки к (x,y) → доли u,v */
export function nearestAnchor(b, x, y) {
  const u = Math.max(0, Math.min(1, (x - b.x) / b.w)), v = Math.max(0, Math.min(1, (y - b.y) / b.h))
  const d = [u, 1 - u, v, 1 - v]; const i = d.indexOf(Math.min(...d))
  return i === 0 ? { u: 0, v } : i === 1 ? { u: 1, v } : i === 2 ? { u, v: 0 } : { u, v: 1 }
}
/** если конец привязан к центру (старые стрелки без u/v) — подрезать линию к границе рамки */
export function arrowPoints(it, byId) {
  const a = anchorPoint(it.data.from, byId), b = anchorPoint(it.data.to, byId)
  if (!a || !b) return null
  let p = a, q = b
  const fa = it.data.from, fb = it.data.to
  if (fa?.item != null && fa.u == null) p = clipToBox(b, a, itemBox(byId.get(fa.item)))
  if (fb?.item != null && fb.u == null) q = clipToBox(a, b, itemBox(byId.get(fb.item)))
  return [p, q]
}
function clipToBox(from, to, box) {
  if (!box) return to
  const cx = to.x, cy = to.y, dx = from.x - cx, dy = from.y - cy
  if (!dx && !dy) return to
  const hw = box.w / 2, hh = box.h / 2
  const t = Math.min(Math.abs(hw / (dx || 1e-9)), Math.abs(hh / (dy || 1e-9)))
  return { x: cx + dx * t, y: cy + dy * t }
}

export function fmtSec(x) { x = +x || 0; if (x < 60) return `${+x.toFixed(1)}с`; const m = Math.floor(x / 60), s = Math.round(x % 60); return `${m}:${String(s).padStart(2, '0')}` }
export function themeColor(name, dark) {
  const cs = getComputedStyle(document.documentElement)
  const v = (n) => cs.getPropertyValue(n).trim()
  return ({ ink: v('--ink') || (dark ? '#ecece9' : '#0e0e0e'), accent: v('--accent') || '#3b5bff', red: v('--neg') || '#dc2646', green: v('--pos') || '#15803d', warn: v('--warn') || '#c2700a', white: '#ffffff', black: '#111111' })[name] || (/^#/.test(name || '') ? name : (v('--ink') || '#0e0e0e'))
}
/** цвет текста по умолчанию для стикера: тёмный на светлом стикере и в светлой теме */
export function stickyInk(it, dark) { return it.data.text_color ? null : (dark ? '#f1f1ee' : '#1a1a1a') }
export const plural = (n, a, b, c) => { const x = n % 100, y = n % 10; return x > 10 && x < 20 ? c : y === 1 ? a : y > 1 && y < 5 ? b : c }
