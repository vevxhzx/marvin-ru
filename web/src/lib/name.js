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

/* Род по имени — только для «он же / она же» в карточках людей. Компании — «также». Без словаря на 100 %: женские имена
   почти всегда на -а/-я (Наталия, Мама, Оля), исключения — типичные мужские на -а (Никита, Илья, Саша…) и уменьшительные. */
const MALE_A = new Set(['никита', 'илья', 'кузьма', 'фома', 'лука', 'савва', 'данила', 'гаврила', 'миша', 'паша', 'саша', 'дима', 'вова', 'серёжа', 'сережа', 'лёша', 'леша', 'коля', 'ваня', 'петя', 'женя', 'гоша', 'тёма', 'тема', 'лёва', 'лева', 'юра', 'слава', 'толя', 'костя', 'витя', 'рома', 'сеня', 'гена', 'боря', 'стёпа', 'степа', 'федя', 'кеша', 'жора', 'валера', 'папа', 'дядя', 'дедушка', 'деда', 'батя'])
const FEMALE_OTHER = new Set(['любовь', 'нинель', 'рахиль', 'руфь', 'эстер', 'мам', 'мать'])
export function aka(name, kind) {
  if (kind === 'company') return 'также'
  const first = (name || '').trim().split(/\s+/)[0]?.toLowerCase().replace(/ё/g, 'е') || ''
  if (MALE_A.has(first)) return 'он же'
  if (FEMALE_OTHER.has(first) || /[ая]$/.test(first)) return 'она же'
  return 'он же'
}
