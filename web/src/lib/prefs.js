// Оформление и поведение сайта. Один источник: prefs.get()/prefs.set(); изменения применяются к <html> мгновенно.
// Хранится в localStorage (мгновенный старт) и зеркалится на сервер (/api/ui-prefs) — телефон и ПК выглядят одинаково.
import { useEffect, useState } from 'react'

/* Акценты: пара light/dark на каждый, чтобы контраст держался в обеих темах. hue — для «фон в тон». */
export const ACCENTS = {
  blue: { label: 'синий', light: '#0a2bff', dark: '#3b5bff', hue: 230 },
  black: { label: 'графит', light: '#111111', dark: '#f2f2f0', ink: { dark: '#0e0e0d' }, hue: 0, mono: true },
  indigo: { label: 'индиго', light: '#3730a3', dark: '#818cf8', hue: 243 },
  violet: { label: 'фиолетовый', light: '#6d28d9', dark: '#a78bfa', hue: 262 },
  plum: { label: 'слива', light: '#86198f', dark: '#e879f9', hue: 292 },
  rose: { label: 'розовый', light: '#c2185b', dark: '#f472b6', hue: 336 },
  red: { label: 'красный', light: '#b91c1c', dark: '#f87171', hue: 0 },
  orange: { label: 'оранжевый', light: '#d9480f', dark: '#ff8a4c', hue: 20 },
  amber: { label: 'янтарь', light: '#a16207', dark: '#fbbf24', hue: 43 },
  olive: { label: 'олива', light: '#4d7c0f', dark: '#a3e635', hue: 85 },
  green: { label: 'зелёный', light: '#0f8a4b', dark: '#34c77b', hue: 150 },
  teal: { label: 'бирюза', light: '#0f766e', dark: '#2dd4bf', hue: 175 },
  sky: { label: 'небо', light: '#0369a1', dark: '#38bdf8', hue: 200 },
}
/* Оттенок поверхностей: лёгкая подкраска фона/карточек. tint — в тон акценту (берём его hue). */
export const TINTS = {
  neutral: { label: 'нейтральный', light: null, dark: null },
  warm: { label: 'тёплый', light: [40, 12], dark: [35, 6] },     // [hue, насыщенность %]
  cool: { label: 'холодный', light: [215, 10], dark: [220, 8] },
  ink: { label: 'чернильный', light: [250, 6], dark: [250, 10] },
  accent: { label: 'в тон акценту', light: 'accent', dark: 'accent' },
}
export const FONT_SIZES = { sm: ['мельче', 0.92], md: ['обычный', 1], lg: ['крупнее', 1.1] }
/* 'strict' — старое имя «строгих» углов из настроек, оставлено как синоним 'sharp' */
export const RADII = { soft: ['мягкие', 1], sharp: ['строгие', 0.45], strict: ['строгие', 0.45], round: ['круглые', 1.35] }

const KEY = 'ui.prefs.v1'
export const DEFAULTS = {
  accent: 'blue', accentHex: '#0a3cff', tint: 'neutral', font: 'md', radius: 'soft', motion: true, compactNav: false,
  address: '', // как обращаться: пусто — берём из настроек ядра («сэр»)
  hiddenNav: [], // скрытые разделы в боковой панели (кроме «сегодня» и «настройки»)
  tabbar: ['/', '/tasks', '/calendar', '/finance', '/mind'], // нижняя панель телефона (5 макс)
  showGreeting: true, showContext: true, showQuick: true, density: 'calm',
  hiddenBlocks: ['upcoming', 'recent'], // блоки главной, скрытые по умолчанию
  tasksSort: 'priority', // сортировка внутри групп задач: priority | due | new
  // свой цвет у каждой вкладки: { page: '#hex' }. Локально, на сервер не уходит.
  pageAccents: {},
}
let _cur = load()
const subs = new Set()
function load() { try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') } } catch { return { ...DEFAULTS } } }

export const CLIENT_ID = (() => { let id = sessionStorage.getItem('client.id'); if (!id) { id = Math.random().toString(36).slice(2); sessionStorage.setItem('client.id', id) } return id })()
const SYNC_KEYS = ['accent', 'accentHex', 'tint', 'font', 'radius', 'motion', 'compactNav', 'address', 'hiddenNav', 'tabbar', 'showGreeting', 'showContext', 'showQuick', 'density', 'hiddenBlocks', 'tasksSort', 'theme', 'todayOrder', 'todayWidgets']
let pushTimer
function pushRemote() {
  clearTimeout(pushTimer)
  pushTimer = setTimeout(() => {
    const body = {}
    for (const k of SYNC_KEYS) if (k in _cur) body[k] = _cur[k]
    fetch('/api/ui-prefs', { method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-Client-Id': CLIENT_ID }, credentials: 'same-origin', body: JSON.stringify({ prefs: body }) }).catch(() => {})
  }, 600)
}
function applyRemote(remote) {
  if (!remote || typeof remote !== 'object') return
  const next = { ..._cur }
  let changed = false
  for (const k of SYNC_KEYS) if (k in remote && JSON.stringify(remote[k]) !== JSON.stringify(next[k])) { next[k] = remote[k]; changed = true }
  if (!changed) return
  _cur = next; localStorage.setItem(KEY, JSON.stringify(_cur)); apply(_cur); subs.forEach((f) => f(_cur))
  if ('theme' in remote) window.dispatchEvent(new CustomEvent('prefs:theme', { detail: remote.theme }))
}
/* При старте и при событии ui_prefs с сервера — подтянуть настройки с других устройств */
export async function pullRemote() {
  try {
    const r = await fetch('/api/ui-prefs', { credentials: 'same-origin' })
    if (!r.ok) return
    const d = await r.json()
    if (d?.prefs && Object.keys(d.prefs).length) applyRemote(d.prefs)
    else pushRemote()   // на сервере пусто — это устройство становится источником
  } catch {}
}

export const prefs = {
  get: () => _cur,
  set(patch) { _cur = { ..._cur, ...patch }; localStorage.setItem(KEY, JSON.stringify(_cur)); apply(_cur); subs.forEach((f) => f(_cur)); pushRemote() },
  reset() { localStorage.removeItem(KEY); _cur = { ...DEFAULTS }; apply(_cur); subs.forEach((f) => f(_cur)); pushRemote() },
}

/* Применяем к документу: CSS-переменные и классы.
   Всё, что раньше жило только в CSS (акцент, оттенок, углы), считается здесь — иначе настройки были «мёртвыми». */
const BOOT_AT = Date.now()
let _lastAccent = null, _lastAccentHex = null, _lastTint = null, _lastDark = null

const rgbOf = (hex) => {
  const s = String(hex || '').replace('#', '')
  const h = s.length === 3 ? s.split('').map((c) => c + c).join('') : s.padEnd(6, '0').slice(0, 6)
  const n = parseInt(h, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}
export const lumOf = (hex) => {
  const [r, g, b] = rgbOf(hex).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
const mixHex = (from, to, k) => '#' + rgbOf(from).map((v, i) => Math.round(v + (rgbOf(to)[i] - v) * k).toString(16).padStart(2, '0')).join('')
/* HSL из hex: нужен hue для «оттенка в тон акценту» и насыщенность,
   чтобы у серого акцента (графит) не получался синий подтон фона. */
export function hexHsl(hex) {
  const [r, g, b] = rgbOf(hex).map((v) => v / 255)
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn
  const l = (mx + mn) / 2
  if (!d) return [0, 0, Math.round(l * 100)]
  const s = d / (1 - Math.abs(2 * l - 1))
  let h
  if (mx === r) h = ((g - b) / d) % 6
  else if (mx === g) h = (b - r) / d + 2
  else h = (r - g) / d + 4
  return [Math.round(((h * 60) + 360) % 360), Math.round(s * 100), Math.round(l * 100)]
}
/* Акцент должен читаться и в светлой, и в тёмной теме: слишком светлый — притемняем, слишком тёмный — осветляем */
export function accentFor(hex, dark) {
  const base = /^#[0-9a-f]{6}$/i.test(String(hex)) ? hex : '#0a3cff'
  const L = lumOf(base)
  if (dark && L < 0.16) return mixHex(base, '#ffffff', 0.5)
  if (dark && L < 0.3) return mixHex(base, '#ffffff', 0.28)
  if (!dark && L > 0.62) return mixHex(base, '#101114', 0.55)
  return base
}

export function apply(p = _cur) {
  const r = document.documentElement
  const dark = r.classList.contains('dark')
  const accentHex = p.accentHex || DEFAULTS.accentHex
  const changed = _lastAccent !== null && (_lastAccent !== p.accent || _lastAccentHex !== accentHex || _lastTint !== p.tint || _lastDark !== dark)
  if (changed && p.motion !== false && Date.now() - BOOT_AT > 900) {
    r.classList.add('theme-anim'); clearTimeout(apply._t); apply._t = setTimeout(() => r.classList.remove('theme-anim'), 650)
  }
  _lastAccent = p.accent; _lastAccentHex = accentHex; _lastTint = p.tint; _lastDark = dark

  const acc = accentFor(accentHex, dark)
  r.style.setProperty('--acc', acc)
  r.style.setProperty('--accent-light', accentFor(accentHex, false))
  r.style.setProperty('--accent-dark', accentFor(accentHex, true))
  r.style.setProperty('--accent-ink', lumOf(acc) > 0.45 ? '#101114' : '#ffffff')
  r.style.setProperty('--accent-ink-dark', '#ffffff')
  r.style.setProperty('--ui-zoom', String((FONT_SIZES[p.font] || FONT_SIZES.md)[1]))
  r.style.setProperty('--r-k', String((RADII[p.radius] || RADII.soft)[1]))
  r.dataset.radius = RADII[p.radius] ? (p.radius === 'round' ? 'round' : p.radius === 'soft' ? 'soft' : 'sharp') : 'soft'
  r.classList.toggle('no-motion', !p.motion)
  r.classList.toggle('accent-custom', accentHex !== DEFAULTS.accentHex)

  /* Оттенок поверхностей: одна пара hue/насыщенность на тему, дальше всё считается в CSS через color-mix() */
  const t = TINTS[p.tint] || TINTS.neutral
  const [hue, sat] = hexHsl(acc)
  const nearGrey = sat < 14   // графит/белый: красить по их hue нельзя — остаёмся нейтральными
  const pick = (v) => (v === 'accent' ? (nearGrey ? null : [hue, 10]) : v)
  const L = pick(t.light), D = pick(t.dark)
  r.style.setProperty('--tint-h-light', L ? String(L[0]) : '60'); r.style.setProperty('--tint-s-light', L ? `${L[1]}%` : '0%')
  r.style.setProperty('--tint-h-dark', D ? String(D[0]) : '60'); r.style.setProperty('--tint-s-dark', D ? `${D[1]}%` : '0%')
  r.classList.toggle('tinted', !!(L || D))
}
apply(_cur)

export function usePrefs() {
  const [p, setP] = useState(_cur)
  useEffect(() => { subs.add(setP); return () => subs.delete(setP) }, [])
  return [p, prefs.set]
}

/* ---------------- Цветовая схема отдельной вкладки ----------------
   Пользователь может покрасить, например, «заказы» в оранжевый, а «финансы» — в зелёный.
   Цвет хранится только в этом браузере (не в SYNC_KEYS — на сервер не уходит)
   и применяется к корню страницы, не меняя общую тему сайта. */
export function setPageAccent(page, hex) {
  const cur = { ...(prefs.get().pageAccents || {}) }
  if (!hex) delete cur[page]
  else cur[page] = hex
  prefs.set({ pageAccents: cur })
}

/* hsl → hex; s и l приходят в процентах (как в hsl()), внутри — доли.
   Старая версия принимала l долей, а ей передавали 50/55 — из hsl() выходил
   «битый» 12-символьный цвет, и подсветка фона уходила в посторонний оттенок. */
const hslHex = (h, s, l) => {
  const ss = s / 100
  const ll = l / 100
  const a = ss * Math.min(ll, 1 - ll)
  const f = (n) => {
    const k = (n + h / 30) % 12
    const c = ll - a * Math.max(-1, Math.min(k - 3, Math.min(9 - k, 1)))
    return Math.round(255 * c).toString(16).padStart(2, '0')
  }
  return `#${f(0)}${f(8)}${f(4)}`
}

export function usePageAccent(page) {
  const [p] = usePrefs()
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  useEffect(() => {
    const upd = () => setDark(document.documentElement.classList.contains('dark'))
    const mo = new MutationObserver(upd)
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    upd() // тему могут включить раньше, чем мы подписались — сверяемся сразу
    return () => mo.disconnect()
  }, [])

  const hex = (p.pageAccents || {})[page]
  if (!hex) return { style: {}, hex: '' }

  const acc = accentFor(hex, dark)
  const [hue, sat] = hexHsl(acc)
  const nearGrey = sat < 14
  // подкраска фонов — аккуратная, как в глобальном «оттенке», но в тон вкладки
  const s = (nearGrey ? 0 : Math.min(sat, dark ? 16 : 12)) / 100
  const tintC = dark ? hslHex(hue, 55, 55) : hslHex(hue, 65, 50)
  const paint = (base, mult) => mixHex(tintC, base, 1 - Math.min(1, s * mult))

  return {
    hex,
    style: {
      '--acc': acc,
      '--accent': acc,
      '--accent-light': accentFor(hex, false),
      '--accent-dark': accentFor(hex, true),
      '--accent-ink': lumOf(acc) > 0.45 ? '#101114' : '#ffffff',
      '--accent-soft': `color-mix(in srgb, ${acc} 16%, transparent)`,
      '--bg': paint(dark ? '#050507' : '#e9ecf3', dark ? 2.4 : 1.7),
      '--sf': paint(dark ? '#131317' : '#ffffff', dark ? 2 : 1),
      '--sf2': paint(dark ? '#1e1e24' : '#f0f1f6', dark ? 2.4 : 1.4),
      '--g1': `color-mix(in srgb, ${acc} 30%, transparent)`,
    },
  }
}
