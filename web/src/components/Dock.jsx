/* components/Dock.jsx — нижняя навигация телефона: тёмная размытая плашка
   с ОДНОЙ прокручиваемой строкой, в которой лежат ВСЕ разделы.

   По макету-основе: слева/справа 10px, снизу max(10px, safe-area), радиус 23px,
   фон rgba(19,20,27,.94) с blur(20px). Внутри — ряд кнопок 75×60: иконка 19px
   и подпись 11px, радиус 17px, активная — заливкой акцентом. Ряд листается
   пальцем (горизонтальная прокрутка без полосы), поэтому из любой подвкладки
   можно уйти в любой раздел — «списка подвкладок» больше нет.

   Раньше здесь было 4 раздела из настроек + «Ещё» и подпись активного пункта,
   которая раскрывалась пружиной. Подписи теперь на всех пунктах (иначе строка
   не читается), поэтому морфинг подписи и ездящая подложка не нужны: активный
   пункт — обычное состояние .on.

   Геометрия и цвета — в index.css, блок «ДОК ТЕЛЕФОНА». Здесь только данные
   (список разделов), прокрутка и то, что док уезжает на время шторки/доски.
   Пружинное нажатие — lib/motion.js (press), как и раньше.
*/

import { useEffect, useMemo, useRef, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Grid3x3, MessageCircle, HelpCircle, Sun, Moon, Monitor, Download } from 'lucide-react'
import { useI18n, t as T } from '../lib/i18n'
import { motionOff, press, usePhone } from '../lib/motion'
import { toast } from './ui'
import { canInstall, installPwa } from '../lib/sw'
import { isActiveRoute, NAV } from '../lib/nav'
import SheetHost from './SheetHost'

/** Можно ли поставить приложение: браузер предложил — значит, кнопка живая. */
function useInstallable() {
  const [yes, setYes] = useState(() => (typeof canInstall === 'function' ? canInstall() : false))
  useEffect(() => {
    const on = () => setYes(!!canInstall())
    window.addEventListener('pwa:installable', on)
    on()
    return () => window.removeEventListener('pwa:installable', on)
  }, [])
  return yes
}

/** Канонический порядок разделов: им же приложение показывает их в строке и в «Ещё». */
const orderOf = (() => {
  const m = new Map()
  NAV.forEach((n, i) => m.set(n.to, i))
  return (to) => (m.has(to) ? m.get(to) : 999)
})()

export default function Dock({
  tabs, pathname, compact, more, onChat, onTheme, onHelp, mode = 'auto', langNode,
}) {
  const { t } = useI18n()
  const phone = usePhone()
  const [moreOpen, setMoreOpen] = useState(false)
  const installable = useInstallable()

  const rowRef = useRef(null)
  const items = useRef({})         // to → DOM-узел пункта
  const pressClean = useRef([])

  /* список разделов пересоздаётся на каждом рендере — для эффектов нужен ключ, а не массив */
  const tabsKey = (tabs || []).map((it) => it.to).join('|')

  /* Все разделы в одном списке: выбранные в настройках + остальные (то, что раньше
     было «Ещё»). Порядок — реестровый (lib/nav.js), чтобы строка не прыгала при
     смене настроек; скрытые разделы сюда не попадают, их отдаёт pickMore. */
  const sections = useMemo(() => {
    const seen = new Map()
    for (const s of [...(tabs || []), ...(more || [])]) if (s?.to) seen.set(s.to, s)
    return [...seen.values()].sort((a, b) => orderOf(a.to) - orderOf(b.to))
  }, [tabsKey, (more || []).map((it) => it.to).join('|')]) // eslint-disable-line

  const activeTo = useMemo(
    () => sections.find((it) => isActiveRoute(it.to, pathname))?.to || '',
    [sections, pathname],
  )

  /* активный пункт не должен прятаться за краем плашки — долистываем строку к нему */
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
    /* забытые разделы (пункт убрали из настроек) — выкидываем из реестра */
    const keep = new Set(sections.map((it) => it.to))
    for (const k of Object.keys(items.current)) if (!keep.has(k)) delete items.current[k]
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

  const doInstall = async () => {
    const ok = await installPwa()
    if (ok) { setMoreOpen(false); toast(t('common.done')) }
    else toast(t('st.install_failed'), { kind: 'err', sub: t('st.install_manual') })
  }

  const moreLabel = t('nav.more')

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
          {sections.map(({ to, label, icon: Icon }) => {
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
                <Icon size={19} strokeWidth={on ? 2.2 : 1.8} aria-hidden="true" />
                <span className="dock-l">{t(label)}</span>
              </NavLink>
            )
          })}
          {/* «Ещё» — последним пунктом строки (чат, язык, тема, справка, установка).
              Отдельной кнопкой-логотипом он не был и не должен становиться. */}
          <button
            type="button"
            className={`dock-item dock-more ${moreOpen ? 'on' : ''}`}
            onClick={() => setMoreOpen(true)}
            aria-label={moreLabel}
            aria-haspopup="dialog"
            aria-expanded={moreOpen}
            title={moreLabel}
          >
            <Grid3x3 size={19} strokeWidth={1.8} aria-hidden="true" />
            <span className="dock-l">{moreLabel}</span>
          </button>
        </div>
      </nav>

      <SheetHost
        open={moreOpen}
        onClose={() => setMoreOpen(false)}
        title={t('nav.more_title')}
        sub={t('nav.more_sub')}
      >
        <div className="space-y-2">
          {(more || []).map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className="more-row" onClick={() => setMoreOpen(false)}>
              <span className="more-ic"><Icon size={17} strokeWidth={1.8} aria-hidden="true" /></span>
              {t(label)}
            </NavLink>
          ))}
          <div className="rule !my-3" />
          <button type="button" className="more-row" onClick={() => { setMoreOpen(false); onChat?.() }}>
            <span className="more-ic"><MessageCircle size={17} strokeWidth={1.8} aria-hidden="true" /></span>
            {t('more.chat')}
          </button>
          {langNode && (
            <div className="more-row !cursor-default items-center justify-between" style={{ background: 'transparent' }}>
              <span className="flex items-center gap-3">
                <span className="more-ic"><Grid3x3 size={17} strokeWidth={1.8} aria-hidden="true" style={{ visibility: 'hidden' }} /></span>
                <span>{T('lang.aria')}</span>
              </span>
              {langNode}
            </div>
          )}
          <button type="button" className="more-row" onClick={() => { setMoreOpen(false); onTheme?.() }}>
            <span className="more-ic">
              {mode === 'light' ? <Sun size={17} /> : mode === 'dark' ? <Moon size={17} /> : <Monitor size={17} />}
            </span>
            {t('st.theme')}
          </button>
          <button type="button" className="more-row" onClick={() => { setMoreOpen(false); onHelp?.() }}>
            <span className="more-ic"><HelpCircle size={17} strokeWidth={1.8} aria-hidden="true" /></span>
            {t('more.keys')}
          </button>
          {installable && (
            <button type="button" className="more-row" onClick={() => { doInstall() }}>
              <span className="more-ic"><Download size={17} strokeWidth={1.8} aria-hidden="true" /></span>
              {t('st.install')}
            </button>
          )}
        </div>
      </SheetHost>
    </>
  )
}