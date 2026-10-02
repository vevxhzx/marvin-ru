/* Service worker — офлайн-шелл для собранного сайта (web/site → отдаётся с корня как /sw.js).
   Рукописный, без библиотек. Vite копирует web/public/* в корень web/site при сборке,
   бэкенд отдаёт /sw.js из этого корня (см. PUBLIC_EXACT в core/api/auth.py).

   Стратегия — stale-while-revalidate: ответ идёт сразу из кэша, фоном качаем свежую
   версию и кладём в кэш. Навигация без кэша уходит в сеть, при отсутствии сети —
   закэшированный index.html. Данные (/api/*) и SSE никогда не кэшируются.

   VERSION — ключ кэша: поменяйте цифру при заметных правках шелла, на activate
   старые кэши удалятся, пользователь получит новую версию (тост «обновление»). */
'use strict'

const VERSION = '1'
const CACHE = `jarvis-shell-${VERSION}`
const PRECACHE = ['/', '/index.html', '/manifest.json', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png']

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => Promise.all(PRECACHE.map((u) => c.add(u).catch(() => {}))))
  )
  // без self.skipWaiting(): новый SW ждёт в очереди и применяется по сообщению
  // от страницы (тост «доступно обновление» → SKIP_WAITING), чтобы не подменять
  // интерфейс под пользователем
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k.startsWith('jarvis-shell-') && k !== CACHE).map((k) => caches.delete(k))
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
  if (url.pathname.startsWith('/api/')) return      // данные и поток событий — всегда сеть
  if (req.headers.get('range')) return              // диапазоны (видео/аудио) — сеть
  const nav = req.mode === 'navigate'
  e.respondWith(handle(req, nav))
})

async function handle(req, nav) {
  const cache = await caches.open(CACHE)
  const cached = await cache.match(req, { ignoreSearch: nav })
  // фоновое обновление кэша — идёт независимо от того, что отдаём сейчас
  const net = fetch(req)
    .then((res) => {
      if (res && res.status === 200 && (res.type === 'basic' || res.type === 'default')) {
        cache.put(req, res.clone()).catch(() => {})
      }
      return res
    })
    .catch(() => null)

  if (cached) return cached          // stale: отдаём кэш, свежая копия ляжет в кэш фоном

  const res = await net
  if (res && res.ok) return res

  if (nav) {                         // офлайн и ни разу не открывали — отдаём шелл
    const shell = (await cache.match('/index.html')) || (await cache.match('/'))
    if (shell) return shell
  }
  return new Response('Нет сети, а кэша ещё нет', {
    status: 503,
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  })
}
