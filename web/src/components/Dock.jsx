/* components/Dock.jsx — нижняя навигация телефона по макету владельца «вариант B».

   Пилюля по центру, ширина по содержимому: два раздела, центральная кнопка «+»
   (лаймовый круг со свечением), ещё два раздела. Разделы — из настроек
   (prefs.tabbar, порядок реестровый, lib/nav.js). Активный пункт разворачивается
   в пилюлю с подписью СПРАВА от иконки (подпись выезжает по ширине и прозрачности —
   правила в index.css, блок «ДОК ТЕЛЕФОНА»), остальные — только иконки.

   Кнопка «+» открывает шторку быстрого ввода (components/CaptureSheet) — как в
   макете: «главная · кнопка „+“ открывает ввод». Остальные разделы (заказы, мозг,
   доска, люди, память, настройки) открываются из меню «…» в шапке телефона
   (components/AppShell) — там же чат, язык, тема и справка.

   Пилюля по центру, снизу max(10px, safe-area) — док всегда над домашним
   индикатором; сам док уезжает на время шторки и доски (тело получает класс
   .sheet-open / .board-page). Пружинное нажатие — lib/motion.js (press).
*/

import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Plus, Grid3x3 } from 'lucide-react'
import { useI18n, t as T } from '../lib/i18n'
import { motionOff, press, usePhone } from '../lib/motion'
import { isActiveRoute, NAV } from '../lib/nav'

export default function Dock({ tabs, more, pathname, compact, onMore, onAdd }) {
  const { t } = useI18n()
  const phone = usePhone()

  const rowRef = useRef(null)
  const items = useRef({})         // to → DOM-узел пункта
  const pressClean = useRef([])

  /* список разделов пересоздаётся на каждом рендере — для эффектов нужен ключ, а не массив */
  const tabsKey = (tabs || []).map((it) => it.to).join('|')

  const sections = useMemo(() => (tabs || []).filter((s) => s?.to), [tabsKey]) // eslint-disable-line

  const activeTo = useMemo(
    () => sections.find((it) => isActiveRoute(it.to, pathname))?.to || '',
    [sections, pathname],
  )

  /* Десктоп: все разделы в реестровом порядке (tabs + more покрывают весь NAV
     с учётом режима фрилансера) — ни одна вкладка не прячется за «Ещё». */
  const moreKey = (more || []).map((it) => it.to).join('|')
  const deskSections = useMemo(() => {
    const order = new Map(NAV.map((n, i) => [n.to, i]))
    const seen = new Set()
    return [...(tabs || []), ...(more || [])]
      .filter((s) => s?.to && !seen.has(s.to) && (seen.add(s.to), true))
      .sort((a, b) => (order.get(a.to) ?? 99) - (order.get(b.to) ?? 99))
  }, [tabsKey, moreKey]) // eslint-disable-line

  const deskActiveTo = useMemo(
    () => deskSections.find((it) => isActiveRoute(it.to, pathname))?.to || '',
    [deskSections, pathname],
  )

  /* активный пункт не должен прятаться за краем пилюли — долистываем строку к нему */
  const scrollTarget = phone ? activeTo : deskActiveTo
  const scrollLen = phone ? sections.length : deskSections.length
  useEffect(() => {
    const row = rowRef.current
    const el = scrollTarget ? items.current[scrollTarget] : null
    if (!row || !el || !el.isConnected) return
    const left = el.offsetLeft - (row.clientWidth - el.offsetWidth) / 2
    const to = Math.max(0, Math.min(left, row.scrollWidth - row.clientWidth))
    if (Math.abs(row.scrollLeft - to) < 2) return
    try { row.scrollTo({ left: to, behavior: motionOff() ? 'auto' : 'smooth' }) } catch { row.scrollLeft = to }
  }, [scrollTarget, scrollLen])

  /* пружинное нажатие на пунктах */
  useEffect(() => {
    pressClean.current.forEach((fn) => fn())
    pressClean.current = []
    for (const rec of Object.values(items.current)) if (rec) pressClean.current.push(press(rec))
    return () => { pressClean.current.forEach((fn) => fn()); pressClean.current = [] }
  }, [phone, tabsKey, moreKey, sections.length, deskSections.length])

  /* macOS-магнификация десктопной пилюли (только .dock.desk): масштаб иконки от
     расстояния курсора — как в мокапе (1 + max(0,1-d/110)*.55, вид — в index.css:
     origin снизу, переход 120мс, только pointer:fine). Только точный указатель и
     только если движение разрешено (motionOff из lib/motion.js); фаб-кнопка «+»
     не масштабируется (это действие, а не иконка раздела). Телефонная ветка ниже —
     без изменений; подсказки title — как были. */
  useEffect(() => {
    if (phone) return undefined
    if (motionOff()) return undefined
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined
    if (!window.matchMedia('(pointer: fine)').matches) return undefined
    const row = rowRef.current
    if (!row || !row.closest('.dock.desk')) return undefined
    const icons = [...row.querySelectorAll('.dock-item')]
    if (!icons.length) return undefined
    const onMove = (e) => {
      for (const el of icons) {
        const r = el.getBoundingClientRect()
        if (!r.width) continue
        const d = Math.abs(e.clientX - (r.left + r.width / 2))
        el.style.setProperty('--ds', (1 + Math.max(0, 1 - d / 110) * 0.55).toFixed(3))
      }
    }
    const onLeave = () => { for (const el of icons) el.style.setProperty('--ds', 1) }
    row.addEventListener('pointermove', onMove)
    row.addEventListener('pointerleave', onLeave)
    return () => {
      row.removeEventListener('pointermove', onMove)
      row.removeEventListener('pointerleave', onLeave)
      for (const el of icons) { try { el.style.removeProperty('--ds') } catch {} }
    }
  }, [phone, tabsKey, moreKey])

  /* Пока открыта шторка или открыта доска — док уезжает: правил для него в CSS нет,
     поэтому прячем его сами (тело получает класс .sheet-open / .board-page). */
  const [muted, setMuted] = useState(false)
  useEffect(() => {
    const check = () => setMuted(document.body.classList.contains('sheet-open') || document.body.classList.contains('board-page'))
    check()
    const mo = new MutationObserver(check)
    mo.observe(document.body, { attributes: true, attributeFilter: ['class'] })
    return () => mo.disconnect()
  }, [])

  /* Порядок слотов макета: [раздел][раздел] «+» [раздел][раздел]. Кнопка «+» идёт
     посередине ряда: первые два раздела слева, остальные справа от неё. */
  const head = sections.slice(0, 2)
  const tail = sections.slice(2, 4)
  const renderSlot = ({ to, label, icon: Icon }, on) => {
    return (
      <NavLink
        key={to}
        to={to}
        end={to === '/'}
        ref={(el) => { items.current[to] = el }}
        className={`dock-item ${on ? 'on' : ''}`}
        aria-label={t(label)}
        aria-current={on ? 'page' : undefined}
        title={t(label)}
      >
        <Icon size={22} strokeWidth={on ? 2.1 : 1.8} aria-hidden="true" />
        <span className="dock-l" aria-hidden="true">{t(label)}</span>
      </NavLink>
    )
  }
  const slot = (s) => renderSlot(s, s.to === activeTo)
  /* Десктоп: та же разметка (NavLink + href — e2e clickTab её находит), активный
     считается по полному списку разделов; подписи (.dock-l) на десктопе — тултипы
     над пилюлей через CSS (.dock.desk .dock-l: активный виден всегда, остальные по hover). */
  const deskSlot = (s) => renderSlot(s, s.to === deskActiveTo)
  const fab = (
    <button
      type="button"
      className="dock-fab"
      onClick={() => onAdd?.(pathname)}
      aria-label={T('cap.title')}
      title={t('cap.title')}
    >
      <Plus size={24} strokeWidth={2.2} aria-hidden="true" />
    </button>
  )

  /* Десктоп: все разделы одной пилюлей, «+» по центру, кнопки «…» нет —
     всё видно сразу. Телефонная ветка ниже — без изменений. */
  if (!phone) {
    const mid = Math.ceil(deskSections.length / 2)
    return (
      <nav
        className={`dock desk ${compact ? 'compact' : ''}`}
        aria-label={t('nav.mobile_menu')}
        data-dock=""
        style={{
          display: 'flex',
          transform: motionOff() ? 'none' : `translate3d(0, ${muted ? 140 : 0}%, 0)`,
          opacity: muted ? 0 : 1,
          transition: motionOff() ? 'none' : undefined,
          pointerEvents: muted ? 'none' : undefined,
        }}
      >
        <div className="dock-row" ref={rowRef}>
          {deskSections.slice(0, mid).map(deskSlot)}
          {fab}
          {deskSections.slice(mid).map(deskSlot)}
        </div>
      </nav>
    )
  }

  return (
    <>
      <nav
        className={`dock ${compact ? 'compact' : ''}`}
        aria-label={t('nav.mobile_menu')}
        data-dock=""
        style={{
          display: phone ? 'flex' : 'none',
          transform: motionOff() ? 'none' : `translate3d(0, ${muted ? 140 : 0}%, 0)`,
          opacity: muted ? 0 : 1,
          transition: motionOff() ? 'none' : undefined,
          pointerEvents: muted ? 'none' : undefined,
        }}
      >
        <div className="dock-row" ref={rowRef}>
          {head.map(slot)}
          {/* центральная кнопка «+» — контекстная: в задачах добавляет задачу,
              в календаре — встречу, в финансах — трату (решает AppShell по маршруту) */}
          {fab}
          {tail.map(slot)}
          {/* «все разделы» — шторка с заказами, мозгом, доской, людьми, памятью,
              настройками (и чатом, языком, темой). Отдельная иконка-сетка справа. */}
          {onMore && (
            <button
              type="button"
              className="dock-item"
              onClick={onMore}
              aria-label={t('nav.more_title')}
              aria-haspopup="dialog"
              title={t('nav.more')}
            >
              <Grid3x3 size={22} strokeWidth={1.8} aria-hidden="true" />
            </button>
          )}
        </div>
      </nav>
    </>
  )
}
