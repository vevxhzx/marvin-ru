/* PWA на стороне страницы: регистрация service worker, применение обновления по клику
   и перехват beforeinstallprompt (кнопка «установить» в настройках → «с телефона»).

   Регистрируется только в проде (import.meta.env.PROD): в dev-режиме Vite отдаёт
   исходники по сокращённым путям, и service worker их закэшировал бы — HMR сломался бы.

   Модуль сам себя регистрирует при импорте — main.jsx добавлена одна строка:
   import './lib/sw' */
import { toast } from '../components/ui'
import { t } from './i18n'

let waitingSW = null     // новый SW, ждущий активации (есть обновление)
let installEvent = null  // сохранённое событие beforeinstallprompt
let started = false

/* Кнопка «установить»: промпт живёт только до первого вызова/страницы. */
export const canInstall = () => !!installEvent

export async function installPwa() {
  const e = installEvent
  if (!e) return false
  installEvent = null
  try {
    e.prompt()
    const r = await e.userChoice
    return r?.outcome === 'accepted'
  } catch { return false }
}

/* Применить обновление: new SW → skipWaiting → controllerchange → перезагрузка. */
export function applyUpdate() {
  try { waitingSW?.postMessage({ type: 'SKIP_WAITING' }) } catch {}
  waitingSW = null
}

function offerUpdate(sw) {
  if (waitingSW === sw) return
  waitingSW = sw
  toast(t('pwa.update_ready'), { sub: t('pwa.update_hint'), ms: 20000 })
  const fire = () => { stop(); applyUpdate() }
  const stop = () => {
    window.removeEventListener('pointerdown', fire)
    window.removeEventListener('keydown', fire)
  }
  window.addEventListener('pointerdown', fire)
  window.addEventListener('keydown', fire)
  setTimeout(stop, 20000)
}

export function registerSW() {
  if (started) return
  started = true
  if (typeof window === 'undefined' || !import.meta.env.PROD) return
  if (!('serviceWorker' in navigator)) return

  const start = () => {
    navigator.serviceWorker.register('/sw.js').then((reg) => {
      if (reg.waiting && navigator.serviceWorker.controller) offerUpdate(reg.waiting)
      reg.addEventListener('updatefound', () => {
        const sw = reg.installing
        if (!sw) return
        sw.addEventListener('statechange', () => {
          // «installed» при наличии контроллера = есть предыдущая версия, значит это обновление
          if (sw.state === 'installed' && navigator.serviceWorker.controller) offerUpdate(sw)
        })
      })
    }).catch(() => {}) // офлайн-шелл — бонус, без него всё работает как раньше
  }
  if (document.readyState === 'complete') start()
  else window.addEventListener('load', start, { once: true })

  let reloading = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading) return
    reloading = true
    window.location.reload()
  })
}

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault()            // браузер не показывает свой баннер — кнопку показываем сами
    installEvent = e
    window.dispatchEvent(new Event('pwa:installable'))
  })
}

registerSW()
