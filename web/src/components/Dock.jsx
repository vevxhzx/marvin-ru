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
import { isActiveRoute } from '../lib/nav'
import SheetHost from './SheetHost'
import CaptureSheet from './CaptureSheet'

export default function Dock({ tabs, pathname, compact, onMore }) {
  const { t } = useI18n()
  const phone = usePhone()
  const [captureOpen, setCaptureOpen] = useState(false)

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

  /* активный пункт не должен прятаться за краем пилюли — долистываем строку к нему */
  useEffect(() => {
    const row = rowRef.current
    const el = activeTo ? items.current[activeTo] : null
    if (!row || !el || !el.isConnected) return
    const left = el.offsetLeft - (row.clientWidth - el.offsetWidth) / 2
    const to = Math.max(0, Math.min(left, row.scrollWidth - row.clientWidth))
    if (Math.abs(row.scrollLeft - to) < 2) return
    try { row.scrollTo({ left: to, behavior: motionOff() ? 'auto' : 'smooth' }) } catch { row.scrollLeft = to }
  }, [activeTo, sections.length])

  /* пружинное нажатие на пунктах */
  useEffect(() => {
    pressClean.current.forEach((fn) => fn())
    pressClean.current = []
    for (const rec of Object.values(items.current)) if (rec) pressClean.current.push(press(rec))
    return () => { pressClean.current.forEach((fn) => fn()); pressClean.current = [] }
  }, [phone, tabsKey, sections.length])

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
  const slot = ({ to, label, icon: Icon }) => {
    const on = to === activeTo
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
          {/* центральная кнопка «+» — быстрый ввод (макет «вариант B») */}
          <button
            type="button"
            className="dock-fab"
            onClick={() => setCaptureOpen(true)}
            aria-label={T('cap.title')}
            aria-haspopup="dialog"
            title={t('cap.title')}
          >
            <Plus size={24} strokeWidth={2.2} aria-hidden="true" />
          </button>
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

      <SheetHost open={captureOpen} onClose={() => setCaptureOpen(false)} title={t('cap.title')} sub={t('cap.sub')}>
        <CaptureSheet open={captureOpen} onClose={() => setCaptureOpen(false)} />
      </SheetHost>
    </>
  )
}
