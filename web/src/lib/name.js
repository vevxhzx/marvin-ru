// Имя ассистента приходит из /api/health; до первого ответа — из <title>. Падежи — простая эвристика для русского.
import { getLang, t } from './i18n'

let NAME = (document.title || t('common.assistant')).split('·')[0].trim() || t('common.assistant')
const subs = new Set()
export function setName(n) { if (!n || n === NAME) return; NAME = n; document.title = n; subs.forEach((f) => f(n)) }
export function onName(f) { subs.add(f); return () => subs.delete(f) }
export const name = () => NAME
export const lower = () => NAME.toLowerCase()
// Русские падежи строим только для RU: в английском имя не склоняется.
const cons = /[бвгджзклмнпрстфхцчшщ]$/i
export const dat = () => {
  const n = lower()
  if (getLang() !== 'ru') return n
  return cons.test(n) ? n + 'у' /* i18n-raw */ : n.endsWith('а') ? n.slice(0, -1) + 'е' : n.endsWith('я') ? n.slice(0, -1) + 'е' : n
}
export const gen = () => {
  const n = lower()
  if (getLang() !== 'ru') return n
  return cons.test(n) ? n + 'а' : n.endsWith('а') ? n.slice(0, -1) + 'ы' : n.endsWith('я') ? n.slice(0, -1) + 'и' : n // i18n-raw
}

/* Род по имени — только для «он же / она же» в карточках людей. Компании — «также». Без словаря на 100 %: женские имена
   почти всегда на -а/-я (Наталия, Мама, Оля), исключения — типичные мужские на -а (Никита, Илья, Саша…) и уменьшительные. */
const MALE_A = new Set(['никита', 'илья', 'кузьма', 'фома', 'лука', 'савва', 'данила', 'гаврила', 'миша', 'паша', 'саша', 'дима', 'вова', 'серёжа', 'сережа', 'лёша', 'леша', 'коля', 'ваня', 'петя', 'женя', 'гоша', 'тёма', 'тема', 'лёва', 'лева', 'юра', 'слава', 'толя', 'костя', 'витя', 'рома', 'сеня', 'гена', 'боря', 'стёпа', 'степа', 'федя', 'кеша', 'жора', 'валера', 'папа', 'дядя', 'дедушка', 'деда', 'батя']) // i18n-raw
const FEMALE_OTHER = new Set(['любовь', 'нинель', 'рахиль', 'руфь', 'эстер', 'мам', 'мать']) // i18n-raw
export function aka(name, kind) {
  if (kind === 'company') return t('people.also')
  const first = (name || '').trim().split(/\s+/)[0]?.toLowerCase().replace(/ё/g, 'е' /* i18n-raw */) || ''
  if (MALE_A.has(first)) return t('people.same_he')
  if (FEMALE_OTHER.has(first) || /[ая]$/.test(first)) return t('people.same_she')
  return t('people.same_he')
}
