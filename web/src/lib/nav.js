/* lib/nav.js — реестр разделов и всё, что зависит от маршрута.

   Один список на сайдбар, палитру (⌘K), нижний dock телефона и шторку «Ещё»: добавили
   раздел здесь — он появился везде. label — ключ словаря (lib/i18n.js), не готовый текст.

   Здесь же маршрут → заголовок раздела для сворачивающейся шапки телефона
   (components/TitleHeader) и проверка «эта ли вкладка активна».
*/

import { Sparkles, CheckSquare, CalendarDays, Wallet, Briefcase, Brain, Clapperboard, Users, History, Settings as SettingsIcon } from 'lucide-react'

/* Навигация по смыслу: рабочее пространство и система. */
export const NAV_GROUPS = [
  { title: 'nav.g_work', items: [
    { to: '/', label: 'nav.today', icon: Sparkles, key: '1' },
    { to: '/tasks', label: 'nav.tasks', icon: CheckSquare, key: '2' },
    { to: '/calendar', label: 'nav.calendar', icon: CalendarDays, key: '3' },
    { to: '/finance', label: 'nav.finance', icon: Wallet, key: '4' },
    { to: '/orders', label: 'nav.orders', icon: Briefcase, key: '5' },
    { to: '/mind', label: 'nav.mind', icon: Brain, key: '6' },
    { to: '/board', label: 'nav.board', icon: Clapperboard, key: '0' },
    { to: '/people', label: 'nav.people', icon: Users, key: '9' },
  ] },
  { title: 'nav.g_sys', items: [
    { to: '/memory', label: 'nav.memory', icon: History, key: '7' },
    { to: '/settings', label: 'nav.settings', icon: SettingsIcon, key: '8' },
  ] },
]

export const NAV = NAV_GROUPS.flatMap((g) => g.items)

/** Нижняя панель телефона: до 4 разделов из настроек + «Ещё» (остальные разделы и действия). */
export const MOBILE_NAV = [NAV[0], NAV[1], NAV[3], NAV[5]]
export const MOBILE_TABS_MAX = 5        // 4 раздела + «Ещё» — ровно пять, как в обычном приложении

/** Разделы нижней панели: из настроек, без скрытых режимом фрилансера. */
export function pickTabs(tabbar, freelance = true) {
  const want = (tabbar || []).filter((to) => freelance || to !== '/orders')
  const list = want.map((to) => NAV.find((n) => n.to === to)).filter(Boolean).slice(0, MOBILE_TABS_MAX - 1)
  return list.length ? list : MOBILE_NAV.filter((n) => freelance || n.to !== '/orders')
}

/** «Ещё»: всё, чего нет в нижних вкладках, плюс выключенный фрилансером «заказы». */
export function pickMore(tabs, freelance = true) {
  return NAV.filter((n) => !tabs.some((t) => t.to === n.to) && (freelance || n.to !== '/orders'))
}

/** Раздел, которому принадлежит маршрут ('/board/12' → '/board'). */
export const sectionOf = (pathname) => {
  const p = String(pathname || '/').split('?')[0]
  const first = '/' + p.split('/').filter(Boolean)[0]
  return p === '/' ? '/' : (first || '/')
}

export const findNav = (to) => NAV.find((n) => n.to === to) || null

/** Активна ли вкладка: '/' — только корень, остальные — с вложенными маршрутами (/board/12). */
export const isActiveRoute = (to, pathname) => (to === '/' ? pathname === '/' : pathname === to || pathname.startsWith(to + '/'))

/* Шапка телефона: подпись раздела + короткая вторая строка.
   title — ключ словаря, sub — тоже ключ (добавляются в i18n координатором). */
export const ROUTE_HEADS = {
  '/':         { title: 'nav.today',    sub: 'title.today_sub' },
  '/tasks':    { title: 'nav.tasks',    sub: 'title.tasks_sub' },
  '/calendar': { title: 'nav.calendar', sub: 'title.calendar_sub' },
  '/finance':  { title: 'nav.finance',  sub: 'title.finance_sub' },
  '/orders':   { title: 'nav.orders',   sub: 'title.orders_sub' },
  '/mind':     { title: 'nav.mind',     sub: 'title.mind_sub' },
  '/board':    { title: 'nav.board',    sub: 'title.board_sub' },
  '/people':   { title: 'nav.people',   sub: 'title.people_sub' },
  '/memory':   { title: 'nav.memory',   sub: 'title.memory_sub' },
  '/settings': { title: 'nav.settings', sub: 'title.settings_sub' },
}

/** Заголовок раздела по маршруту. Для неизвестного пути — пусто (страница сама печатает своё). */
export function headOf(pathname) {
  const key = sectionOf(pathname)
  return ROUTE_HEADS[key] || { title: '', sub: '' }
}

/**
 * Текст ключа словаря или '' — если ключа в словаре нет.
 * Нужно для новых подписей оболочки (подзаголовок раздела, подсказка «потянуть»):
 * пока координатор не добавил ключ, t() вернёт humanize-заглушку («Today sub»),
 * и она не должна попадать в интерфейс.
 */
export function textOf(t, key) {
  if (!key) return ''
  const v = t(key)
  const words = String(key).replace(/[._-]+/g, ' ').trim()
  const human = words ? words[0].toUpperCase() + words.slice(1) : String(key)
  return v === human ? '' : v
}