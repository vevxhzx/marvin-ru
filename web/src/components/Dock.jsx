/* components/Dock.jsx — плавающая пилюля-док внизу (телефон).

   Не таб-бар на всю ширину, а пилюля по центру: 4 раздела из настроек + «Ещё».
   Активный пункт разворачивается в пилюлю с подписью — ширина и прозрачность идут
   пружиной (lib/motion.js), фон-подложка переезжает от пункта к пункту тем же
   движением. Ничего не зависит от наведения: подпись и подсветка приезжают по
   нажатию, всё работает пальцем.

   Размеры и отступы — из токенов A1 (--dock-h, --dock-gap, --tap) с запасными
   значениями, поэтому док корректен и без них. На десктопе док не рисуется вовсе
   (видимость переключает media-query, а не CSS-класс).
*/

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Grid3x3, MessageCircle, HelpCircle, Sun, Moon, Monitor, Download } from 'lucide-react'
import { useI18n, t as T } from '../lib/i18n'
import { animate, motionOff, press, springCurve, usePhone, EASE_OUT } from '../lib/motion'
import { toast } from './ui'
import { canInstall, installPwa } from '../lib/sw'
import { isActiveRoute } from '../lib/nav'
import SheetHost from './SheetHost'

const ICON = 20                                   // размер иконки в пилюле
const GAP = 8                                     // зазор иконка↔подпись
const PAD = 12                                    // поля пункта слева/справа
const SNAP_W = ICON + PAD * 2                     // свёрнутый пункт = var(--tap)
const PILL_SPRING = { stiffness: 360, damping: 30 }

/** Подпись пункта раскрывается/закрывается пружиной: width + opacity. */
function morphLabel(el, on) {
  if (!el) return
  const target = on ? Math.ceil(el.scrollWidth) : 0
  const from = el.getBoundingClientRect().width
  const commit = () => {
    try {
      el.style.width = `${target}px`
      el.style.opacity = on ? '1' : '0'
      el.getAnimations?.().forEach((a) => a.cancel())
    } catch {}
  }
  const anim = animate(el, [
    { width: `${from}px`, opacity: on ? '0' : '1' },
    { width: `${target}px`, opacity: on ? '1' : '0' },
  ], { ...springCurve(PILL_SPRING), fill: 'both' })
  if (anim) anim.finished.then(commit).catch(commit)
  else commit()
}

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

export default function Dock({
  tabs, pathname, compact, more, onChat, onTheme, onHelp, mode = 'auto', langNode,
}) {
  const { t } = useI18n()
  const phone = usePhone()
  const [moreOpen, setMoreOpen] = useState(false)
  const installable = useInstallable()

  const pillRef = useRef(null)
  const items = useRef({})         // to → { item, label }
  const rect = useRef(null)        // где подложка была в прошлый раз
  const pressClean = useRef([])

  /* список разделов пересоздаётся на каждом рендере — для эффектов нужен ключ, а не массив */
  const tabsKey = (tabs || []).map((it) => it.to).join('|')
  const activeTo = useMemo(
    () => (tabs || []).find((it) => isActiveRoute(it.to, pathname))?.to || '',
    [tabsKey, pathname], // eslint-disable-line
  )

  /* Подложка переезжает на активный пункт: left/width идут пружиной.
     widthHint — ширина, которую пункт получит, когда подпись раскроется (считаем сами,
     чтобы подложка поехала одновременно с подписью, а не после неё). */
  const movePill = useCallback((key, animateIt = true, widthHint = 0) => {
    const pill = pillRef.current
    if (!pill) return
    const rec = key ? items.current[key] : null
    if (!rec?.item || !rec.item.isConnected) {
      /* активного пункта в доке нет (раздел открыт из «Ещё») — подложка тихо гаснет */
      rect.current = null
      const a = animate(pill, [{ opacity: 1 }, { opacity: 0 }], { duration: motionOff() ? 0 : 160, easing: EASE_OUT, fill: 'forwards' })
      if (a) a.finished.then(() => { try { pill.style.opacity = '0' } catch {} }).catch(() => {})
      else { try { pill.style.opacity = '0' } catch {} }
      return
    }
    const el = rec.item
    const next = { left: el.offsetLeft, width: widthHint || el.offsetWidth }
    const prev = rect.current
    rect.current = next
    const finish = () => {
      try {
        pill.style.left = `${next.left}px`
        pill.style.width = `${next.width}px`
        pill.style.opacity = '1'
        pill.getAnimations?.().forEach((a) => a.cancel())
      } catch {}
    }
    if (!animateIt || !prev || motionOff()) { finish(); return }
    const anim = animate(pill, [
      { left: `${prev.left}px`, width: `${prev.width}px`, opacity: 1 },
      { left: `${next.left}px`, width: `${next.width}px`, opacity: 1 },
    ], { ...springCurve(PILL_SPRING), fill: 'both' })
    if (anim) anim.finished.then(finish).catch(finish)
    else finish()
  }, [])

  /* подписи: у активного раскрыта, у остальных свёрнуты (в компактном режиме — только иконки) */
  useEffect(() => {
    if (!phone) return
    let labelW = 0
    for (const it of tabs || []) {
      const rec = items.current[it.to]
      if (!rec?.label) continue
      const open = it.to === activeTo && !compact
      if (open) labelW = Math.ceil(rec.label.scrollWidth)
      morphLabel(rec.label, open)
    }
    /* подложка едет вместе с подписью, а не после неё */
    if (activeTo && !compact) movePill(activeTo, true, SNAP_W + GAP + labelW)
    else movePill(activeTo, true)
    /* и сверяем её с реальными размерами пункта, когда пружина отработает */
    const t = setTimeout(() => { if (activeTo) movePill(activeTo) }, 340)
    return () => clearTimeout(t)
  }, [activeTo, tabsKey, compact, phone, movePill])

  /* первый показ и смена размеров окна */
  useLayoutEffect(() => {
    if (!phone) return
    movePill(activeTo, false)
    const onResize = () => movePill(activeTo, false)
    window.addEventListener('resize', onResize)
    window.addEventListener('orientationchange', onResize)
    return () => { window.removeEventListener('resize', onResize); window.removeEventListener('orientationchange', onResize) }
  }, [phone, activeTo, tabsKey, movePill])

  /* пружинное нажатие на пунктах */
  useEffect(() => {
    pressClean.current.forEach((fn) => fn())
    pressClean.current = []
    /* забытые разделы (пункт убрали из настроек) — выкидываем из реестра */
    const keep = new Set((tabs || []).map((it) => it.to))
    for (const k of Object.keys(items.current)) if (!keep.has(k)) delete items.current[k]
    for (const rec of Object.values(items.current)) if (rec?.item) pressClean.current.push(press(rec.item))
    return () => { pressClean.current.forEach((fn) => fn()); pressClean.current = [] }
  }, [phone, tabsKey])

  /* Пока открыта шторка или открыта доска — док уезжает: правила для .tabbar в CSS
   относятся к старой разметке, поэтому прячем его сами. */
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
          position: 'fixed',
          left: '50%',
          /* Telegram отдаёт свою безопасную зону, обычный телефон — env() */
          bottom: 'calc(max(var(--safe-b, 0px), var(--tg-safe-area-inset-bottom, 0px)) + var(--dock-gap, 12px))',
          transform: `translateX(-50%) translate3d(0, ${muted ? 140 : 0}%, 0)`,
          opacity: muted ? 0 : 1,
          zIndex: 'var(--z-dock, 60)',
          alignItems: 'center',
          gap: 4,
          padding: 'var(--dock-pad, 6px)',
          maxWidth: 'calc(100vw - 16px - var(--safe-l, 0px) - var(--safe-r, 0px))',
          borderRadius: '999px',
          background: 'color-mix(in srgb, var(--bg) 78%, transparent)',
          WebkitBackdropFilter: 'blur(18px) saturate(160%)',
          backdropFilter: 'blur(18px) saturate(160%)',
          border: '1px solid var(--line)',
          boxShadow: 'var(--shadow-2)',
          transition: motionOff() ? 'none' : 'transform var(--t-base) var(--ease-out), opacity var(--t-base) var(--ease-out)',
          pointerEvents: muted ? 'none' : undefined,
        }}
      >
        <div className="dock-row" style={{ position: 'relative', display: 'flex', alignItems: 'stretch', gap: 2 }}>
          {/* подложка активного пункта — едет пружиной, а не щёлкает */}
          <span
            className="dock-pill"
            ref={pillRef}
            aria-hidden="true"
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: 0,
              width: SNAP_W,
              borderRadius: '999px',
              background: 'var(--accent-soft)',
              border: '1px solid color-mix(in srgb, var(--accent) 26%, transparent)',
              pointerEvents: 'none',
            }}
          />
          {(tabs || []).map(({ to, label, icon: Icon }) => {
            const on = to === activeTo && !compact      // в компактном режиме док — только иконки
            return (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                ref={(el) => { items.current[to] = { item: el, label: el?.querySelector('.dock-l') || null } }}
                className={`dock-item ${on ? 'on' : ''}`}
                aria-label={t(label)}
                aria-current={to === activeTo ? 'page' : undefined}
                title={t(label)}
                data-tip={t(label)}
                style={{
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: GAP,
                  height: 'var(--dock-h, 46px)',
                  minWidth: 'var(--tap, 44px)',
                  width: on ? undefined : 'var(--tap, 44px)',
                  padding: on ? `0 ${PAD}px` : 0,
                  borderRadius: '999px',
                  color: on ? 'var(--accent)' : 'var(--ink-3)',
                  fontSize: 13,
                  fontWeight: on ? 600 : 500,
                  textDecoration: 'none',
                  lineHeight: 1.1,
                  background: 'transparent',
                  transition: 'color var(--t-fast) var(--ease-out)',
                  WebkitTapHighlightColor: 'transparent',
                }}
              >
                <Icon size={ICON} strokeWidth={on ? 2.2 : 1.9} aria-hidden="true" style={{ flex: 'none' }} />
                <span
                  className="dock-l"
                  style={{
                    display: 'inline-block',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    verticalAlign: 'bottom',
                    width: 0,
                    opacity: 0,
                    willChange: 'width, opacity',
                  }}
                >
                  {t(label)}
                </span>
              </NavLink>
            )
          })}
          {/* «Ещё»: все остальные разделы и действия */}
          <button
            type="button"
            className={`dock-item dock-more ${moreOpen ? 'on' : ''}`}
            onClick={() => setMoreOpen(true)}
            aria-label={moreLabel}
            aria-haspopup="dialog"
            aria-expanded={moreOpen}
            title={moreLabel}
            style={{
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: GAP,
              height: 'var(--dock-h, 46px)',
              minWidth: 'var(--tap, 44px)',
              padding: 0,
              border: 0,
              borderRadius: '999px',
              background: 'transparent',
              color: 'var(--ink-3)',
              WebkitTapHighlightColor: 'transparent',
            }}
          >
            <Grid3x3 size={ICON} strokeWidth={1.9} aria-hidden="true" style={{ flex: 'none' }} />
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
            <button type="button" className="more-row" onClick={() => { doInstall(); }}>
              <span className="more-ic"><Download size={17} strokeWidth={1.8} aria-hidden="true" /></span>
              {t('st.install')}
            </button>
          )}
        </div>
      </SheetHost>
    </>
  )
}