// Offline listening, like Spotify's "Download" switch: a playlist or album
// saved on this device plays without a connection. The songs and covers
// go to Cache Storage (see lib/offline.js), the service worker (public/
// sw.js) serves them, and the app itself opens offline. Per device.
import { computed, reactive, ref } from 'vue'

import {
  INDEX_KEY,
  OFFLINE_CACHE,
  collectionKey,
  collectionSize,
  collectionTracks,
  coverKey,
  emptyIndex,
  missingTracks,
  needsSync,
  offlineSupport,
  parseIndex,
  savableTracks,
  songKey,
  storedTrack,
  totalSize,
  withCollection,
  withoutCollection,
} from '/src/lib/offline'
import { coverURL } from '/src/lib/paths'

// Songs fetched at once while saving.
const PARALLEL = 2
// The index is written every this many songs (and at the end), so an
// interrupted save keeps what it already got.
const WRITE_EVERY = 5

const support = offlineSupport()
const index = ref(emptyIndex())
const loaded = ref(false)
const online = ref(globalThis.navigator?.onLine !== false)
// Saves in progress: key → { done, total, failed, state } with state
// 'saving', 'full' (the device ran out of room) or 'error'.
const jobs = reactive({})
const usage = ref(null) // { usage, quota } from the browser, when it says
const persisted = ref(false)

let loading = null

function origin() {
  return globalThis.location?.origin || 'http://localhost'
}

function openCache() {
  return globalThis.caches.open(OFFLINE_CACHE)
}

function ensureLoaded() {
  if (support !== 'ok') return Promise.resolve()
  if (!loading) {
    loading = (async () => {
      try {
        const cache = await openCache()
        const saved = await cache.match(INDEX_KEY)
        index.value = parseIndex(saved ? await saved.json() : null)
      } catch {
        index.value = emptyIndex()
      } finally {
        loaded.value = true
      }
    })()
  }
  return loading
}

async function writeIndex() {
  try {
    const cache = await openCache()
    await cache.put(
      INDEX_KEY,
      new Response(JSON.stringify(index.value), {
        headers: { 'Content-Type': 'application/json' },
      })
    )
  } catch {
    // Out of room: the songs saved so far stay listed next time anyway.
  }
}

async function refreshUsage() {
  try {
    const estimate = await globalThis.navigator?.storage?.estimate?.()
    if (estimate) {
      usage.value = { usage: estimate.usage || 0, quota: estimate.quota || 0 }
    }
  } catch {
    usage.value = null
  }
}

// Asked once something is saved: a browser may otherwise clear the songs
// to free room. Installed apps usually get it without a prompt.
async function requestPersist() {
  try {
    const storage = globalThis.navigator?.storage
    if (!storage?.persist) return
    persisted.value = (await storage.persisted?.()) || (await storage.persist())
  } catch {
    // Kept as best effort.
  }
}

async function deleteSongs(tracks) {
  if (!tracks.length) return
  const cache = await openCache()
  for (const track of tracks) {
    await cache.delete(songKey(track.url, origin())).catch(() => {})
    await cache.delete(coverKey(track.file, origin())).catch(() => {})
  }
}

async function saveSong(cache, track) {
  const response = await fetch(track.url, { credentials: 'same-origin' })
  if (!response.ok || response.status !== 200) {
    throw new Error(`HTTP ${response.status}`)
  }
  const size =
    Number(response.headers.get('content-length')) || Number(track.size) || 0
  await cache.put(songKey(track.url, origin()), response)
  if (track.hasCover !== false) {
    try {
      const cover = await fetch(coverURL(track.file))
      if (cover.ok) await cache.put(coverKey(track.file, origin()), cover)
    } catch {
      // A song without its cover still plays.
    }
  }
  return { ...storedTrack(track), size, savedAt: Date.now() }
}

async function download(key, tracks) {
  const job = { done: 0, total: tracks.length, failed: 0, state: 'saving' }
  jobs[key] = job
  const live = jobs[key]
  const cache = await openCache()
  const queue = tracks.slice()
  let sinceWrite = 0
  const worker = async () => {
    while (queue.length && live.state === 'saving') {
      // Removed meanwhile: stop, and leave nothing behind.
      if (!index.value.collections[key]) {
        live.state = 'cancelled'
        return
      }
      const track = queue.shift()
      try {
        const saved = await saveSong(cache, track)
        // Kept while any saved collection holds it (this one may have been
        // removed meanwhile).
        const wanted = Object.values(index.value.collections).some((entry) =>
          entry.files.includes(track.file)
        )
        if (wanted) index.value.tracks[track.file] = saved
        else await deleteSongs([track])
      } catch (error) {
        if (error?.name === 'QuotaExceededError') {
          live.state = 'full'
          return
        }
        live.failed += 1
      }
      live.done += 1
      sinceWrite += 1
      if (sinceWrite >= WRITE_EVERY) {
        sinceWrite = 0
        await writeIndex()
      }
    }
  }
  await Promise.all(Array.from({ length: PARALLEL }, worker))
  await writeIndex()
  await refreshUsage()
  if (live.state === 'saving') {
    if (live.failed) live.state = 'error'
    else if (jobs[key] === live) delete jobs[key]
  } else if (live.state === 'cancelled' && jobs[key] === live) {
    delete jobs[key]
  }
  return live
}

/**
 * Save (or bring up to date) a playlist or album on this device.
 * `collection`: { kind: 'playlist'|'album', id, title, subtitle, cover,
 * route }. Resolves with the finished job, or null when nothing was
 * missing.
 */
async function save(collection, tracks) {
  if (support !== 'ok') return null
  await ensureLoaded()
  const key = collectionKey(collection.kind, collection.id)
  if (jobs[key]?.state === 'saving') return jobs[key]
  const songs = savableTracks(tracks)
  const before = index.value.collections[key]
  const { index: next, dropped } = withCollection(index.value, {
    ...collection,
    key,
    files: songs.map((track) => track.file),
    savedAt: before?.savedAt || Date.now(),
    updatedAt: Date.now(),
  })
  index.value = next
  await writeIndex()
  await deleteSongs(dropped)
  void requestPersist()
  const missing = missingTracks(index.value, songs)
  if (!missing.length) {
    delete jobs[key]
    await refreshUsage()
    return null
  }
  return download(key, missing)
}

/** Take a saved playlist or album off this device. */
async function remove(kind, id) {
  await ensureLoaded()
  const key = collectionKey(kind, id)
  if (jobs[key]) jobs[key].state = 'cancelled'
  const { index: next, dropped } = withoutCollection(index.value, key)
  index.value = next
  await writeIndex()
  await deleteSongs(dropped)
  delete jobs[key]
  await refreshUsage()
}

/** Delete every saved song from this device. */
async function removeAll() {
  for (const job of Object.values(jobs)) job.state = 'cancelled'
  try {
    await globalThis.caches?.delete(OFFLINE_CACHE)
  } catch {
    // Nothing left to delete.
  }
  index.value = emptyIndex()
  for (const key of Object.keys(jobs)) delete jobs[key]
  await refreshUsage()
}

/** Re-save a saved collection whose songs changed (songs added/removed). */
async function sync(collection, tracks) {
  await ensureLoaded()
  const entry =
    index.value.collections[collectionKey(collection.kind, collection.id)]
  if (!entry || !online.value) return null
  const key = entry.key
  if (jobs[key]?.state === 'saving') return null
  if (!needsSync(entry, tracks) && !missingTracks(index.value, tracks).length) {
    return null
  }
  return save(collection, tracks)
}

function entryFor(kind, id) {
  return index.value.collections[collectionKey(kind, id)] || null
}

function jobFor(kind, id) {
  return jobs[collectionKey(kind, id)] || null
}

const collections = computed(() =>
  Object.values(index.value.collections)
    .map((entry) => ({
      ...entry,
      tracks: collectionTracks(index.value, entry.key),
      size: collectionSize(index.value, entry.key),
    }))
    .sort((a, b) => (b.savedAt || 0) - (a.savedAt || 0))
)

const savedFiles = computed(() => new Set(Object.keys(index.value.tracks)))
const savedBytes = computed(() => totalSize(index.value))

/** Register the service worker (production builds only) and load the
 * index. Called once at startup. */
export function startOffline() {
  if (typeof window === 'undefined') return
  window.addEventListener?.('online', () => {
    online.value = true
  })
  window.addEventListener?.('offline', () => {
    online.value = false
  })
  if (support !== 'ok') return
  void ensureLoaded()
  if (!import.meta.env.PROD) return
  navigator.serviceWorker
    .register('/sw.js')
    .then(() => navigator.serviceWorker.ready)
    .then((registration) => {
      // What loaded before the worker took this page over (first visit).
      const urls = (performance.getEntriesByType?.('resource') || []).map(
        (entry) => entry.name
      )
      registration.active?.postMessage({ type: 'keep-app', urls })
    })
    .catch(() => {
      // No offline support this visit; everything else works the same.
    })
}

export function useOffline() {
  return {
    support,
    loaded,
    online,
    index,
    jobs,
    usage,
    persisted,
    collections,
    savedFiles,
    savedBytes,
    ensureLoaded,
    refreshUsage,
    entryFor,
    jobFor,
    save,
    sync,
    remove,
    removeAll,
  }
}
