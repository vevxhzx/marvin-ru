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
export const RADII = { soft: ['мягкие', 1], sharp: ['строгие', 0.45], round: ['круглые', 1.35] }

const KEY = 'ui.prefs.v1'
export const DEFAULTS = {
  accent: 'blue', tint: 'neutral', font: 'md', radius: 'soft', motion: true, compactNav: false,
  address: '', // как обращаться: пусто — берём из настроек ядра («сэр»)
  hiddenNav: [], // скрытые разделы в боковой панели (кроме «сегодня» и «настройки»)
  tabbar: ['/', '/tasks', '/calendar', '/finance', '/mind'], // нижняя панель телефона (5 макс)
  showGreeting: true, showContext: true, showQuick: true, density: 'calm',
  hiddenBlocks: ['upcoming', 'recent'], // блоки главной, скрытые по умолчанию
  tasksSort: 'priority', // сортировка внутри групп задач: priority | due | new
}
let _cur = load()
const subs = new Set()
function load() { try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') } } catch { return { ...DEFAULTS } } }

export const CLIENT_ID = (() => { let id = sessionStorage.getItem('client.id'); if (!id) { id = Math.random().toString(36).slice(2); sessionStorage.setItem('client.id', id) } return id })()
const SYNC_KEYS = ['accent', 'tint', 'font', 'radius', 'motion', 'compactNav', 'address', 'hiddenNav', 'tabbar', 'showGreeting', 'showContext', 'showQuick', 'density', 'hiddenBlocks', 'tasksSort', 'theme', 'todayOrder']
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

/* Применяем к документу: CSS-переменные и классы */
let _lastAccent = null, _lastTint = null
export function apply(p = _cur) {
  const r = document.documentElement
  if (_lastAccent !== null && (_lastAccent !== p.accent || _lastTint !== p.tint) && p.motion !== false) {
    r.classList.add('theme-anim'); clearTimeout(apply._t); apply._t = setTimeout(() => r.classList.remove('theme-anim'), 650)
  }
  _lastAccent = p.accent; _lastTint = p.tint
  const a = ACCENTS[p.accent] || ACCENTS.blue
  r.style.setProperty('--accent-light', a.light)
  r.style.setProperty('--accent-dark', a.dark)
  r.style.setProperty('--accent-ink-dark', a.ink?.dark || '#ffffff')
  r.style.setProperty('--ui-zoom', String((FONT_SIZES[p.font] || FONT_SIZES.md)[1]))
  r.style.setProperty('--r-k', String((RADII[p.radius] || RADII.soft)[1]))
  r.classList.toggle('no-motion', !p.motion)
  r.classList.toggle('accent-custom', p.accent !== 'blue')
  // оттенок поверхностей: одна пара hue/sat на тему, дальше всё считается в CSS через hsl()
  const t = TINTS[p.tint] || TINTS.neutral
  const pick = (v) => (v === 'accent' ? (a.mono ? null : [a.hue, 10]) : v)
  const L = pick(t.light), D = pick(t.dark)
  r.style.setProperty('--tint-h-light', L ? String(L[0]) : '60'); r.style.setProperty('--tint-s-light', L ? `${L[1]}%` : '4%')
  r.style.setProperty('--tint-h-dark', D ? String(D[0]) : '60'); r.style.setProperty('--tint-s-dark', D ? `${D[1]}%` : '2%')
  r.classList.toggle('tinted', !!(L || D))
}
apply(_cur)

export function usePrefs() {
  const [p, setP] = useState(_cur)
  useEffect(() => { subs.add(setP); return () => subs.delete(setP) }, [])
  return [p, prefs.set]
}
