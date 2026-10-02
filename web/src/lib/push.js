/* Web Push без новых зависимостей.

   Всё, что умеет браузер, делаем здесь: VAPID-пара (ECDSA P-256) через WebCrypto,
   подписка через PushManager.subscribe и отправка subscription на
   POST /api/push/subscribe через api.post.

   Честные ограничения:
   - только HTTPS или localhost (isSecureContext) + современный браузер;
   - service worker регистрируется только в проде (см. lib/sw.js) — в dev подписка
     невозможна, это не ошибка;
   - серверной части подписки может ещё не быть: 404/405 превращаем в спокойный
     reason: 'no-endpoint', интерфейс не падает и не показывает ошибок;
   - приватный ключ VAPID лежит в localStorage этого браузера: он нужен серверу,
     чтобы подписывать push-запросы. Пока бэкенда нет — подписка живёт только здесь.
   Никаких новых зависимостей: только WebCrypto, Push API и существующий api.post. */

import { api } from './api'

const LS_PRIV = 'push.vapid.priv'
const LS_PUB = 'push.vapid.pub'

/* --- поддержка: браузер + безопасный контекст (https / localhost) --- */
export function pushSupport() {
  if (typeof window === 'undefined') return false
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false
  if (!('Notification' in window)) return false
  if (!window.isSecureContext) return false   // http с другого хоста — не работает и не должно
  return true
}

/* --- base64url <-> Uint8Array --- */
const toB64url = (buf) => {
  const bytes = new Uint8Array(buf)
  let s = ''
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i])
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
const fromB64url = (s) => {
  const b64 = s.replace(/-/g, '+').replace(/_/g, '/')
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/* VAPID-пара: генерируется один раз и живёт в localStorage браузера.
   Нужен публичный ключ (applicationServerKey для подписки); приватный — для сервера,
   когда появится его часть. Подпись VAPID-JWT делает сервер, не страница. */
async function vapidKeys() {
  const priv = localStorage.getItem(LS_PRIV)
  const pub = localStorage.getItem(LS_PUB)
  if (priv && pub) return { priv, pub }
  const kp = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify'])
  const rawPub = await crypto.subtle.exportKey('raw', kp.publicKey)
  const pkcs8 = await crypto.subtle.exportKey('pkcs8', kp.privateKey)
  const out = { pub: toB64url(rawPub), priv: toB64url(pkcs8) }
  localStorage.setItem(LS_PUB, out.pub)
  localStorage.setItem(LS_PRIV, out.priv)
  return out
}

/* SW нужен и для подписки, и для показа пушей. Регистрируем точечно (на случай,
   если основная регистрация ещё не отработала), но только в проде — в dev'е SW
   ломает HMR. */
async function readySW() {
  if (!import.meta.env.PROD) return { ok: false, reason: 'dev' }
  const reg = await navigator.serviceWorker.register('/sw.js')
  await navigator.serviceWorker.ready
  return { ok: !!reg }
}

/** Текущее состояние: 'unsupported' | 'insecure' | 'dev' | 'denied' | 'on' | 'off' */
export async function pushState() {
  try {
    if (!pushSupport()) return window.isSecureContext === false ? 'insecure' : 'unsupported'
    if (!import.meta.env.PROD) return 'dev'
    if (Notification.permission === 'denied') return 'denied'
    const reg = await navigator.serviceWorker.getRegistration()
    const sub = reg ? await reg.pushManager.getSubscription() : null
    return sub ? 'on' : 'off'
  } catch { return 'unsupported' }
}

/**
 * Включить подписку.
 * @returns {{ok: boolean, reason?: string}} reason: 'permission' | 'no-endpoint' | 'dev' | 'unsupported' | 'error'
 */
export async function enablePush() {
  try {
    if (!pushSupport()) return { ok: false, reason: 'unsupported' }
    if (!import.meta.env.PROD) return { ok: false, reason: 'dev' }
    const sw = await readySW()
    if (!sw.ok) return { ok: false, reason: sw.reason || 'unsupported' }

    let perm = Notification.permission
    if (perm !== 'granted') {
      perm = await Notification.requestPermission()
      if (perm !== 'granted') return { ok: false, reason: 'permission' }
    }

    const registration = await navigator.serviceWorker.ready
    if (!registration.pushManager) return { ok: false, reason: 'unsupported' }

    const { pub } = await vapidKeys()
    const sub = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: fromB64url(pub),
    })
    const json = typeof sub.toJSON === 'function' ? sub.toJSON() : { endpoint: sub.endpoint, keys: sub.keys }

    try {
      await api.post('/api/push/subscribe', {
        endpoint: json.endpoint,
        keys: json.keys || {},
        vapid_public_key: pub,
        created_at: new Date().toISOString(),
      })
      return { ok: true }
    } catch (e) {
      // серверной части ещё нет (или метод не поддержан) — подписка в браузере есть,
      // сообщаем об этом спокойно, без ошибок в интерфейсе
      if (e?.status === 404 || e?.status === 405 || e?.status === 501) return { ok: false, reason: 'no-endpoint' }
      // но подписку не оставляем висеть, если сервер её не принял
      try { await sub.unsubscribe() } catch {}
      return { ok: false, reason: e?.status ? 'error' : 'offline', message: e?.message }
    }
  } catch {
    return { ok: false, reason: 'error' }
  }
}

/** Выключить: снимаем подписку у браузера и, если сервер отвечает, — у сервера. */
export async function disablePush() {
  try {
    if (!pushSupport()) return { ok: false, reason: 'unsupported' }
    const reg = await navigator.serviceWorker.getRegistration()
    const sub = reg?.pushManager ? await reg.pushManager.getSubscription() : null
    if (!sub) return { ok: true }
    const endpoint = sub.endpoint
    const res = await sub.unsubscribe()
    try { await api.post('/api/push/unsubscribe', { endpoint }) } catch {}  // эндпоинта может не быть — не беда
    return { ok: !!res }
  } catch {
    return { ok: false, reason: 'error' }
  }
}
