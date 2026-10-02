/* Service worker — офлайн-шелл для собранного сайта (web/public → web/site → отдаётся с корня как /sw.js).
   Рукописный, без библиотек. Бэкенд отдаёт /sw.js из корня web/site (PUBLIC_EXACT в core/api/auth.py),
   путь /sw.js остаётся постоянным — только содержимое меняется.

   Стратегии:
     • навигация (req.mode === 'navigate') — network-first с гонкой против таймаута: сеть отвечает
       быстро → свежий index.html; сеть молчит или офлайн → закэшированный шелл. Так второй запуск
       мгновенный, а обновление шелла всё равно доезжает при первой сетевой загрузке;
     • хэшированная статика Vite (/assets/*) — cache-first: имя файла содержит хэш содержимого,
       попадание в кэш всегда актуально, перезапрашивать нечего;
     • остальная статика (шрифты, иконки, манифест) — stale-while-revalidate: отдаём кэш, обновляем фоном;
     • /api/*, /media/*, SSE и запросы с range — всегда сеть, мимо кэша.

   VERSION — часть имени кэша: при заметных правках шелла подними цифру, на activate старые
   кэши удалятся. self.skipWaiting() в install НЕ вызывается: новая версия ждёт в очереди и
   применяется только по кнопке (страница шлёт SKIP_WAITING) — иначе интерфейс подменяется под
   пользователем. Никакой перезагрузки страницы здесь нет: activate только чистит кэш и
   забирает клиентов (clients.claim), перезагрузку делает страница — и только если контроллер
   реально сменился, а не появился впервые. */
'use strict'

const VERSION = '2'
const CACHE = `marvin-shell-${VERSION}`
/* Старые кэши назывались jarvis-shell-* — вычищаем их тем же фильтром в activate. */
const CACHE_PREFIXES = ['marvin-shell-', 'jarvis-shell-']

/* Шелл: то, без чего приложение не стартует. Хэшированные /assets/* добавляются отдельно —
   install вытаскивает их из текста index.html (precacheAssets ниже). */
const PRECACHE = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/icon.svg',
  '/icon-192.png',
  '/icon-512.png',
  '/icon-maskable-512.png',
  '/apple-touch-icon.png',
  '/fonts/Onest-cyrillic.woff2',
  '/fonts/Onest-cyrillic-ext.woff2',
  '/fonts/Onest-latin.woff2',
  '/fonts/Onest-latin-ext.woff2',
]

/* Навигация: если сеть не ответила за NAV_TIMEOUT, отдаём шелл — «второй запуск» не должен ждать сеть. */
const NAV_TIMEOUT = 1500

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => Promise.all(PRECACHE.map((u) => c.add(u).catch(() => {}))))
      .then(() => precacheAssets())
  )
  // без self.skipWaiting(): новый SW ждёт в очереди и применяется по сообщению от страницы
})

/* Хэшированные бандлы Vite лежат в /assets/* и не известны заранее: имя меняется при каждой
   сборке. Достаём список из index.html и кладём рядом с шеллом — тогда второй запуск не тянет
   сеть даже для JS. Ошибка сети здесь не страшна: install не должен из-за неё падать. */
async function precacheAssets() {
  try {
    const res = await fetch('/index.html', { cache: 'no-cache' })
    if (!res || !res.ok) return
    const html = await res.text()
    const urls = new Set()
    for (const m of html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)) urls.add(m[1])
    if (!urls.size) return
    const cache = await caches.open(CACHE)
    await Promise.all([...urls].map((u) => cache.add(u).catch(() => {})))
  } catch { /* офлайн-установка — не помеха */ }
}

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => CACHE_PREFIXES.some((p) => k.startsWith(p)) && k !== CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting()
})

self.addEventListener('fetch', (e) => {
  const req = e.request
  if (req.method !== 'GET') return
  let url
  try { url = new URL(req.url) } catch { return }
  if (url.origin !== self.location.origin) return   // чужие домены — не трогаем
  if (url.pathname === '/api' || url.pathname.startsWith('/api/')) return   // данные и поток событий — всегда сеть
  if (url.pathname.startsWith('/media/')) return
  if (req.headers.get('range')) return              // диапазоны (видео/аудио) — сеть

  // data:/blob:/chrome-extension: — в Cache API не кладутся, отдаём как есть
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return

  if (req.mode === 'navigate') { e.respondWith(handleNav(req)); return }
  if (url.pathname.startsWith('/assets/')) { e.respondWith(handleImmutable(req)); return }
  e.respondWith(handleStatic(req))
})

/* ---------- навигация: сеть вперёд, но не ценой мгновенного старта ---------- */
async function handleNav(req) {
  const cache = await caches.open(CACHE)
  const shell = (await cache.match('/index.html')) || (await cache.match('/'))

  const fromNet = (async () => {
    const res = await fetch(req)
    if (res && res.ok) {
      const copy = res.clone()
      cache.put('/index.html', copy).catch(() => {})
    }
    return res
  })()

  const timeout = new Promise((resolve) => setTimeout(() => resolve(null), NAV_TIMEOUT))
  const res = await Promise.race([fromNet.catch(() => null), timeout])

  if (res) return res
  if (shell) return shell            // сеть молчит или офлайн — отдаём шелл
  const fallback = await fetch(req).catch(() => null)   // ни кэша, ни ответа по таймауту
  return fallback || offline()
}

/* ---------- /assets/*: имя содержит хэш → кэш навсегда, сеть не нужна ---------- */
async function handleImmutable(req) {
  const cache = await caches.open(CACHE)
  const hit = await cache.match(req, { ignoreSearch: true })
  if (hit) return hit
  const res = await fetch(req)
  if (res && res.ok) cache.put(req, res.clone()).catch(() => {})
  return res
}

/* ---------- прочая статика: stale-while-revalidate ---------- */
async function handleStatic(req) {
  const cache = await caches.open(CACHE)
  const hit = await cache.match(req, { ignoreSearch: true })
  // фоновую закачку не отменяем: ответ нужен только чтобы положить свежую копию в кэш
  const net = fetch(req)
    .then((res) => {
      if (res && res.ok && (res.type === 'basic' || res.type === 'default')) {
        cache.put(req, res.clone()).catch(() => {})
      }
      return res
    })
    .catch(() => null)
  if (hit) return hit               // stale: кэш сразу, свежая копия ляжет фоном
  const res = await net
  if (res) return res
  return offline()
}

function offline() {
  return new Response('Нет сети, а кэша ещё нет', {
    status: 503,
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  })
}