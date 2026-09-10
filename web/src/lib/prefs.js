// Оформление и поведение сайта — всё в localStorage этого браузера, ядро не трогаем.
// Один источник: prefs.get()/prefs.set(); изменения применяются к <html> мгновенно.
import { useEffect, useState } from 'react'

export const ACCENTS = {
  blue: { label: 'синий', light: '#0a2bff', dark: '#3b5bff' },
  black: { label: 'графит', light: '#111111', dark: '#f2f2f0', ink: { dark: '#0e0e0d' } },
  green: { label: 'зелёный', light: '#0f8a4b', dark: '#34c77b' },
  violet: { label: 'фиолетовый', light: '#6d28d9', dark: '#a78bfa' },
  orange: { label: 'оранжевый', light: '#d9480f', dark: '#ff8a4c' },
  rose: { label: 'розовый', light: '#c2185b', dark: '#f472b6' },
}
export const FONT_SIZES = { sm: ['мельче', 0.92], md: ['обычный', 1], lg: ['крупнее', 1.1] }
export const RADII = { soft: ['мягкие', 1], sharp: ['строгие', 0.45], round: ['круглые', 1.35] }

const KEY = 'ui.prefs.v1'
export const DEFAULTS = {
  accent: 'blue', font: 'md', radius: 'soft', motion: true, compactNav: false,
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

export const prefs = {
  get: () => _cur,
  set(patch) { _cur = { ..._cur, ...patch }; localStorage.setItem(KEY, JSON.stringify(_cur)); apply(_cur); subs.forEach((f) => f(_cur)) },
  reset() { localStorage.removeItem(KEY); _cur = { ...DEFAULTS }; apply(_cur); subs.forEach((f) => f(_cur)) },
}

/* Применяем к документу: CSS-переменные и классы */
export function apply(p = _cur) {
  const r = document.documentElement
  const a = ACCENTS[p.accent] || ACCENTS.blue
  r.style.setProperty('--accent-light', a.light)
  r.style.setProperty('--accent-dark', a.dark)
  r.style.setProperty('--accent-ink-dark', a.ink?.dark || '#ffffff')
  r.style.setProperty('--ui-zoom', String((FONT_SIZES[p.font] || FONT_SIZES.md)[1]))
  r.style.setProperty('--r-k', String((RADII[p.radius] || RADII.soft)[1]))
  r.classList.toggle('no-motion', !p.motion)
  r.classList.toggle('accent-custom', p.accent !== 'blue')
}
apply(_cur)

export function usePrefs() {
  const [p, setP] = useState(_cur)
  useEffect(() => { subs.add(setP); return () => subs.delete(setP) }, [])
  return [p, prefs.set]
}
