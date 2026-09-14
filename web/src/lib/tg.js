// Telegram Mini App: сайт открыт внутри Telegram (кнопка-приложение в боте).
// Что делаем: 1) узнаём, что мы в Telegram; 2) входим на сервер подписанными данными Telegram (initData) —
// без QR и ключей; 3) подстраиваем оболочку под webview (развернуть, тема, кнопка «назад», не закрывать свайпом).
// В обычном браузере ничего из этого не запускается и скрипт Telegram не загружается.

const KEY = 'tg_init'  // sessionStorage: initData живёт, пока открыт webview (при переходах внутри SPA hash теряется)

export const tg = { active: false, ok: false, error: '', name: '', app: null }

function fromHash() {
  const h = location.hash || ''
  if (!h.includes('tgWebAppData')) return ''
  const p = new URLSearchParams(h.slice(1))
  return p.get('tgWebAppData') || ''
}

export function initData() {
  return window.Telegram?.WebApp?.initData || fromHash() || sessionStorage.getItem(KEY) || ''
}

export function inTelegram() {
  return !!initData()
}

function loadSdk(timeout = 4000) {
  // официальный скрипт Telegram; грузим только внутри Telegram. Не загрузился — не страшно: вход и так работает
  return new Promise((resolve) => {
    if (window.Telegram?.WebApp) return resolve(window.Telegram.WebApp)
    const s = document.createElement('script')
    const t = setTimeout(() => resolve(null), timeout)
    s.src = 'https://telegram.org/js/telegram-web-app.js?58'
    s.onload = () => { clearTimeout(t); resolve(window.Telegram?.WebApp || null) }
    s.onerror = () => { clearTimeout(t); resolve(null) }
    document.head.appendChild(s)
  })
}

async function login(data) {
  const r = await fetch('/api/tg/login', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ init_data: data }) })
  let j = {}
  try { j = await r.json() } catch {}
  if (!r.ok) throw new Error(typeof j.detail === 'string' ? j.detail : `вход не удался (${r.status})`)
  return j
}

function applyShell(app) {
  if (!app) return
  try { app.ready() } catch {}
  try { app.expand() } catch {}
  try { app.disableVerticalSwipes?.() } catch {}   // иначе скролл вниз может закрыть приложение
  try { app.setHeaderColor?.('bg_color'); app.setBackgroundColor?.('bg_color') } catch {}
  document.documentElement.classList.add('in-telegram')
}

/** Вызывается до первого рендера. Никогда не бросает. */
export async function tgBoot() {
  const data = initData()
  if (!data) {
    // открыт в Telegram, но не как приложение бота (ссылкой): initData не будет — вход невозможен, Gate объяснит
    if (/tgWebAppPlatform|tgWebAppVersion/.test(location.hash)) console.warn('Telegram открыл сайт без initData — открывайте кнопкой бота, а не ссылкой')
    return tg
  }
  tg.active = true
  sessionStorage.setItem(KEY, data)
  document.documentElement.classList.add('in-telegram')
  const [app, res] = await Promise.all([loadSdk(), login(data).then((j) => j).catch((e) => ({ error: e.message }))])
  tg.app = app
  applyShell(app)
  if (res?.error) { tg.error = res.error } else { tg.ok = true; tg.name = res?.name || '' }
  // цвет шапки Telegram — под нашу тему
  const sync = () => {
    const dark = document.documentElement.classList.contains('dark')
    try { app?.setHeaderColor?.(dark ? '#0e0e0d' : '#ecece9'); app?.setBackgroundColor?.(dark ? '#0e0e0d' : '#ecece9') } catch {}
  }
  sync()
  new MutationObserver(sync).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
  return tg
}

/** Кнопка «назад» в шапке Telegram: показываем не на главной. */
export function tgBackButton(show, onBack) {
  const bb = tg.app?.BackButton
  if (!bb) return () => {}
  if (!show) { try { bb.hide() } catch {}; return () => {} }
  try { bb.show(); bb.onClick(onBack) } catch {}
  return () => { try { bb.offClick(onBack) } catch {} }
}

export function tgHaptic(kind = 'light') {
  try { tg.app?.HapticFeedback?.impactOccurred(kind) } catch {}
}
