// Recommended songs kept per playlist, so opening a playlist again shows
// them at once instead of asking YouTube Music every time. An entry holds
// while the playlist's newest songs (what the mixes are seeded from) stay
// the same and for a day at most; Refresh replaces it.

const STORAGE_KEY = 'downtify-playlist-recommendations'
export const RECOMMENDATION_TTL_MS = 24 * 60 * 60 * 1000
const MAX_PLAYLISTS = 30

function storage() {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

function readAll() {
  try {
    const raw = JSON.parse(storage()?.getItem(STORAGE_KEY) || '{}')
    return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}
  } catch {
    return {}
  }
}

let entries = null

function all() {
  if (!entries) entries = readAll()
  return entries
}

function persist() {
  try {
    storage()?.setItem(STORAGE_KEY, JSON.stringify(all()))
  } catch {
    // Quota: the memory copy still serves this visit.
  }
}

/** What identifies the songs a playlist's mixes start from. */
export function seedSignature(seeds) {
  return (seeds || [])
    .map((track) => track?.file || `${track?.artist}|${track?.title}`)
    .join('\n')
}

/**
 * The saved recommendations of `name`, or `null` when there are none,
 * they are older than a day, or the playlist's newest songs changed.
 */
export function cachedRecommendations(name, signature, now = Date.now()) {
  const entry = all()[name]
  if (!entry || entry.signature !== signature) return null
  if (!(now - entry.at < RECOMMENDATION_TTL_MS)) return null
  return entry
}

/** Save `songs` (fetched for `round` of Refresh) for playlist `name`. */
export function saveRecommendations(
  name,
  { signature, round = 0, songs = [] },
  now = Date.now()
) {
  const map = all()
  map[name] = { signature, round, songs, at: now }
  const names = Object.keys(map)
  if (names.length > MAX_PLAYLISTS) {
    names
      .sort((a, b) => map[a].at - map[b].at)
      .slice(0, names.length - MAX_PLAYLISTS)
      .forEach((old) => delete map[old])
  }
  persist()
}

/** Tests: forget the in-memory copy so the next read loads storage. */
export function resetRecommendationCache() {
  entries = null
}
