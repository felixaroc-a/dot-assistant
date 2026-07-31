/* Service Worker para DOT Desktop - Cache estrategico de assets y API */
/* global self, caches, fetch, URL, Response, Headers */

const CACHE_NAME = 'dot-cache-v2'
const ASSET_CACHE = 'dot-assets-v2'
const API_CACHE = 'dot-api-v2'

// Assets a precachear al instalar
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/favicon.png',
  '/favicon.svg',
  '/icons.svg',
  '/nordika-icon.png',
  '/whatsapp-CgHrMqd9.png',
]

/**
 * Cache-First para assets estaticos (JS, CSS, imagenes).
 * Network-First para llamadas API.
 * Fallback a cache para API cuando offline.
 */

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(ASSET_CACHE).then((cache) => {
      return cache.addAll(PRECACHE_URLS)
    }),
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  // Limpiar caches viejos
  event.waitUntil(
    caches.keys().then((names) => {
      return Promise.all(
        names
          .filter((name) => name !== ASSET_CACHE && name !== API_CACHE && name !== CACHE_NAME)
          .map((name) => caches.delete(name)),
      )
    }),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)

  // No interceptar Vite dev server (HMR / módulos con ?t=)
  const isViteDev =
    (url.hostname === '127.0.0.1' || url.hostname === 'localhost') &&
    (url.port === '5173' || url.pathname.startsWith('/@vite/') || url.pathname.startsWith('/@fs/') || url.searchParams.has('t'))
  if (isViteDev) return

  // Solo interceptar requests de nuestra app
  if (!url.origin.startsWith('http://127.0.0.1') && !url.origin.startsWith('http://localhost') && !url.href.startsWith(self.location.origin)) {
    return
  }

  // Assets estaticos: cache-first
  if (request.destination === 'script' || request.destination === 'style' || request.destination === 'font' || request.destination === 'image') {
    event.respondWith(cacheFirst(request))
    return
  }

  // API calls: network-first con fallback a cache
  if (url.pathname.startsWith('/v1/') || url.pathname.startsWith('/oauth/') || url.pathname.startsWith('/users/')) {
    if (request.method === 'GET') {
      event.respondWith(networkFirstWithCache(request))
    }
    return
  }

  // Navegacion: network-first con fallback a index.html (SPA)
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match('/index.html')),
    )
  }
})

/**
 * Cache-First: busca en cache, si no encuentra va a red.
 */
async function cacheFirst(request) {
  const cached = await caches.match(request)
  if (cached) return cached
  try {
    const response = await fetch(request)
    if (response.ok) {
      const cache = await caches.open(ASSET_CACHE)
      cache.put(request, response.clone())
    }
    return response
  } catch {
    return new Response('Offline', { status: 503 })
  }
}

/**
 * Network-First con fallback a cache para API.
 */
async function networkFirstWithCache(request) {
  try {
    const response = await fetch(request)
    if (response.ok) {
      const cache = await caches.open(API_CACHE)
      cache.put(request, response.clone())
    }
    return response
  } catch {
    const cached = await caches.match(request)
    if (cached) {
      return new Response(cached.body, {
        status: cached.status,
        statusText: cached.statusText,
        headers: new Headers({
          'X-DOT-Cache': 'HIT',
          ...Object.fromEntries(cached.headers.entries()),
        }),
      })
    }
    return new Response(JSON.stringify({ error: 'offline', detail: 'Sin conexion y sin cache disponible.' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json', 'X-DOT-Cache': 'MISS' },
    })
  }
}
