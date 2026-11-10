// Castify's service worker: what lets the installed app open and play
// the songs saved on this device without a connection.
//
// - The app itself (the page and its hashed files) is kept as it loads,
//   one copy per version of the page, so it opens offline. The page is
//   always asked for first while online, so an upgrade still shows at once.
// - Songs and covers saved for offline listening are put in OFFLINE_CACHE
//   by the page (src/model/offline.js), never here; this only serves them,
//   in the byte ranges an <audio> element asks for.
// - Everything else (the API, songs that weren't saved) goes to the server
//   as if there were no service worker.

const OFFLINE_CACHE = 'castify-offline-v1'
const SHELL_PREFIX = 'castify-shell-'
const META_CACHE = 'castify-sw-meta'
const SHELLS_KEY = '/__castify-sw__/shells'
const PAGE_KEY = '/'

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

// The page names the app files it loaded before this worker took it over
// (the first visit, an update): kept now, so the app opens offline.
self.addEventListener('message', (event) => {
  const data = event.data || {}
  if (data.type !== 'keep-app' || !Array.isArray(data.urls)) return
  event.waitUntil(keepApp(data.urls))
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  const path = url.pathname
  if (isSongPath(path)) {
    event.respondWith(songResponse(request, url))
  } else if (path === '/cover') {
    event.respondWith(coverResponse(request, url))
  } else if (request.mode === 'navigate' && !isServerPage(path)) {
    event.respondWith(pageResponse(request))
  } else if (path.startsWith('/assets/') || isAppFile(path)) {
    event.respondWith(appFileResponse(request))
  }
})

function isSongPath(path) {
  return path.startsWith('/downloads/') || path.startsWith('/media/')
}

// Pages the server draws itself (the API docs) - left to it.
function isServerPage(path) {
  return path.startsWith('/api/') || path === '/docs' || path === '/redoc'
}

function isAppFile(path) {
  return (
    path === '/manifest.json' ||
    /^\/[\w-]+\.(png|svg|ico)$/.test(path) ||
    path.startsWith('/fonts/')
  )
}

/** The saved copy of a song or cover, under its URL without a query. */
function savedKey(url) {
  return url.origin + url.pathname
}

// ── Saved songs ──────────────────────────────────────────────────────
async function songResponse(request, url) {
  const cache = await caches.open(OFFLINE_CACHE)
  const saved = await cache.match(savedKey(url))
  if (saved) return rangeResponse(request, saved)
  return fetch(request)
}

/**
 * `bytes=start-end` within `size`: `{ start, end }` (end included), or
 * null when it can't be served. Only the first range of a list is kept,
 * which is all an audio element ever asks for.
 */
function parseRange(header, size) {
  const match = /^bytes=(\d*)-(\d*)/.exec(String(header || '').trim())
  if (!match || size <= 0) return null
  const [, from, to] = match
  let start
  let end
  if (from === '') {
    if (to === '') return null
    // The last `to` bytes.
    start = Math.max(0, size - Number(to))
    end = size - 1
  } else {
    start = Number(from)
    end = to === '' ? size - 1 : Math.min(Number(to), size - 1)
  }
  if (start > end || start >= size) return null
  return { start, end }
}

async function rangeResponse(request, saved) {
  const blob = await saved.blob()
  const type =
    saved.headers.get('content-type') || blob.type || 'application/octet-stream'
  const size = blob.size
  const header = request.headers.get('range')
  if (!header) {
    return new Response(blob, {
      status: 200,
      headers: {
        'Content-Type': type,
        'Content-Length': String(size),
        'Accept-Ranges': 'bytes',
      },
    })
  }
  const range = parseRange(header, size)
  if (!range) {
    return new Response(null, {
      status: 416,
      headers: { 'Content-Range': `bytes */${size}` },
    })
  }
  return new Response(blob.slice(range.start, range.end + 1), {
    status: 206,
    headers: {
      'Content-Type': type,
      'Content-Length': String(range.end - range.start + 1),
      'Content-Range': `bytes ${range.start}-${range.end}/${size}`,
      'Accept-Ranges': 'bytes',
    },
  })
}

// ── Covers ───────────────────────────────────────────────────────────
// The server's answer while it can be reached (a cover may change);
// offline, the saved one of that song, whatever size was asked for.
async function coverResponse(request, url) {
  try {
    return await fetch(request)
  } catch (error) {
    const file = url.searchParams.get('file')
    if (file) {
      const key = `${url.origin}/cover?file=${encodeURIComponent(file)}`
      const saved = await (await caches.open(OFFLINE_CACHE)).match(key)
      if (saved) return saved
    }
    throw error
  }
}

// ── The app itself ───────────────────────────────────────────────────
async function shells() {
  const meta = await caches.open(META_CACHE)
  const saved = await meta.match(SHELLS_KEY)
  try {
    const list = saved ? await saved.json() : []
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

/** A short, stable name for one version of the page. */
function versionOf(text) {
  let hash = 0
  for (let i = 0; i < text.length; i++) {
    hash = (hash * 31 + text.charCodeAt(i)) | 0
  }
  return (hash >>> 0).toString(36)
}

/**
 * Keep the page in the cache of its version. The files of the previous
 * version stay too (a tab still open on it may load one of its pages);
 * older ones go.
 */
async function keepPage(response) {
  const text = await response.clone().text()
  const name = SHELL_PREFIX + versionOf(text)
  const list = await shells()
  const cache = await caches.open(name)
  await cache.put(PAGE_KEY, response)
  if (list[0] === name) return
  const next = [name, ...list.filter((other) => other !== name)].slice(0, 2)
  await (
    await caches.open(META_CACHE)
  ).put(SHELLS_KEY, new Response(JSON.stringify(next)))
  for (const old of list.filter((other) => !next.includes(other))) {
    await caches.delete(old)
  }
}

async function pageResponse(request) {
  try {
    const response = await fetch(request)
    const type = response.headers.get('content-type') || ''
    if (response.ok && type.startsWith('text/html')) {
      await keepPage(response.clone()).catch(() => {})
    }
    return response
  } catch (error) {
    // Offline: the app's own page, which routes itself.
    const [current] = await shells()
    const saved = current
      ? await (await caches.open(current)).match(PAGE_KEY)
      : null
    if (saved) return saved
    throw error
  }
}

async function appFileResponse(request) {
  const hit = await caches.match(request)
  if (hit) return hit
  const response = await fetch(request)
  if (response.ok) {
    const [current] = await shells()
    if (current) {
      const cache = await caches.open(current)
      await cache.put(request, response.clone()).catch(() => {})
    }
  }
  return response
}

async function keepApp(urls) {
  try {
    const response = await fetch(PAGE_KEY, { cache: 'no-cache' })
    if (response.ok) await keepPage(response)
  } catch {
    return
  }
  for (const href of urls) {
    let url
    try {
      url = new URL(href, self.location.origin)
    } catch {
      continue
    }
    if (url.origin !== self.location.origin) continue
    if (!url.pathname.startsWith('/assets/') && !isAppFile(url.pathname)) {
      continue
    }
    try {
      await appFileResponse(new Request(url.href))
    } catch {
      // Gone already (an older version's file): nothing to keep.
    }
  }
}
