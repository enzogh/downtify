// Offline listening: the pure part. Songs saved on this device live in the
// browser's Cache Storage (OFFLINE_CACHE), served by the service worker
// (public/sw.js) when the player asks for them; an index kept in the same
// cache says which playlists and albums were saved, and what each song is,
// so they can be listed and played with no connection at all.

/** Must match OFFLINE_CACHE in public/sw.js. */
export const OFFLINE_CACHE = 'castify-offline-v1'
export const INDEX_KEY = '/__castify-offline__/index.json'
const INDEX_VERSION = 1

export function emptyIndex() {
  return { version: INDEX_VERSION, collections: {}, tracks: {} }
}

/** The saved index, or an empty one when it is missing or unreadable. */
export function parseIndex(raw) {
  if (!raw || typeof raw !== 'object' || raw.version !== INDEX_VERSION) {
    return emptyIndex()
  }
  const collections = {}
  for (const [key, entry] of Object.entries(raw.collections || {})) {
    if (!entry || !Array.isArray(entry.files)) continue
    collections[key] = { ...entry, key, files: entry.files.map(String) }
  }
  const tracks = {}
  for (const [file, entry] of Object.entries(raw.tracks || {})) {
    if (entry && typeof entry === 'object') tracks[file] = { ...entry, file }
  }
  return { version: INDEX_VERSION, collections, tracks }
}

export function collectionKey(kind, id) {
  return `${kind}:${id}`
}

/**
 * The songs of a list that can be kept: files in the library (a song
 * that is only streamed has nothing to keep), each once.
 */
export function savableTracks(tracks) {
  const seen = new Set()
  const out = []
  for (const track of tracks || []) {
    const file = String(track?.file || '')
    if (!file || track.stream || !track.url || seen.has(file)) continue
    seen.add(file)
    out.push(track)
  }
  return out
}

const KEPT_FIELDS = [
  'file',
  'title',
  'artist',
  'artists',
  'album',
  'albumArtist',
  'compilation',
  'trackNumber',
  'year',
  'releaseDate',
  'duration',
  'explicit',
  'format',
  'url',
  'cover',
  'hasCover',
]

/** What the index keeps of a song: enough to list and play it. */
export function storedTrack(track) {
  const out = {}
  for (const field of KEPT_FIELDS) {
    if (track[field] !== undefined) out[field] = track[field]
  }
  return out
}

/** Where a saved song is kept: its URL without a query (see sw.js). */
export function songKey(url, origin) {
  const parsed = new URL(url, origin)
  return parsed.origin + parsed.pathname
}

/** Where a saved cover is kept (sw.js serves it for every size). */
export function coverKey(file, origin) {
  return `${new URL(origin).origin}/cover?file=${encodeURIComponent(file)}`
}

function filesInUse(index, skipKey = null) {
  const used = new Set()
  for (const [key, entry] of Object.entries(index.collections)) {
    if (key === skipKey) continue
    entry.files.forEach((file) => used.add(file))
  }
  return used
}

/**
 * `index` with `collection` saved (added or replaced), and the songs that
 * no saved collection holds any more (to delete from the device).
 */
export function withCollection(index, collection) {
  const next = {
    ...index,
    collections: { ...index.collections, [collection.key]: collection },
    tracks: { ...index.tracks },
  }
  return { index: next, dropped: dropUnused(next) }
}

/** `index` without the collection `key`, and the songs to delete. */
export function withoutCollection(index, key) {
  const collections = { ...index.collections }
  delete collections[key]
  const next = { ...index, collections, tracks: { ...index.tracks } }
  return { index: next, dropped: dropUnused(next) }
}

function dropUnused(index) {
  const used = filesInUse(index)
  const dropped = []
  for (const file of Object.keys(index.tracks)) {
    if (!used.has(file)) {
      dropped.push(index.tracks[file])
      delete index.tracks[file]
    }
  }
  return dropped
}

/** The songs of a collection that aren't on the device yet. */
export function missingTracks(index, tracks) {
  return savableTracks(tracks).filter((track) => !index.tracks[track.file])
}

/** A saved collection's songs, in its order (those already saved). */
export function collectionTracks(index, key) {
  const entry = index.collections[key]
  if (!entry) return []
  return entry.files.map((file) => index.tracks[file]).filter(Boolean)
}

/** Bytes the saved songs of a collection take. */
export function collectionSize(index, key) {
  return collectionTracks(index, key).reduce(
    (sum, track) => sum + (Number(track.size) || 0),
    0
  )
}

/** Bytes every saved song takes (each once). */
export function totalSize(index) {
  return Object.values(index.tracks).reduce(
    (sum, track) => sum + (Number(track.size) || 0),
    0
  )
}

/** Whether a saved collection's songs are not those of `tracks` any more. */
export function needsSync(entry, tracks) {
  if (!entry) return false
  const files = savableTracks(tracks).map((track) => track.file)
  return (
    files.length !== entry.files.length ||
    files.some((file, i) => file !== entry.files[i])
  )
}

/**
 * Whether this browser can keep songs: 'ok', 'insecure' (offline storage
 * needs HTTPS or localhost) or 'unsupported'.
 */
export function offlineSupport(env = globalThis) {
  if (env.isSecureContext === false) return 'insecure'
  if (!env.caches || !env.navigator?.serviceWorker) return 'unsupported'
  return 'ok'
}
