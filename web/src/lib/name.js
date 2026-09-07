// Имя ассистента приходит из /api/health; до первого ответа — из <title>. Падежи — простая эвристика для русского.
let NAME = (document.title || 'Ассистент').split('·')[0].trim() || 'Ассистент'
const subs = new Set()
export function setName(n) { if (!n || n === NAME) return; NAME = n; document.title = n; subs.forEach((f) => f(n)) }
export function onName(f) { subs.add(f); return () => subs.delete(f) }
export const name = () => NAME
export const lower = () => NAME.toLowerCase()
const cons = /[бвгджзклмнпрстфхцчшщ]$/i
export const dat = () => { const n = lower(); return cons.test(n) ? n + 'у' : n.endsWith('а') ? n.slice(0, -1) + 'е' : n.endsWith('я') ? n.slice(0, -1) + 'е' : n }
export const gen = () => { const n = lower(); return cons.test(n) ? n + 'а' : n.endsWith('а') ? n.slice(0, -1) + 'ы' : n.endsWith('я') ? n.slice(0, -1) + 'и' : n }
