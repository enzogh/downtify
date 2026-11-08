// Lyrics for the Now playing view (GET /lyrics), cached per file.
import API from '/src/model/api'
import { parseLrc } from '/src/lib/lrc'

const EMPTY = Object.freeze({ lines: [], plain: '' })

const cache = new Map()
// Settled answers, readable without waiting a tick: the panel shows a
// prefetched song's lyrics the moment it starts instead of a skeleton.
const ready = new Map()

/** Resolves `{ lines: [{time, text}], plain: string }` for a track. */
export function loadLyrics(file) {
  if (!file) return Promise.resolve(EMPTY)
  if (!cache.has(file)) {
    cache.set(
      file,
      API.getLyrics(file)
        .then((res) => {
          const result = {
            lines: parseLrc(res.data?.synced),
            plain: String(res.data?.plain || ''),
          }
          ready.set(file, result)
          return result
        })
        .catch(() => {
          cache.delete(file)
          return EMPTY
        })
    )
  }
  return cache.get(file)
}

/** The lyrics already loaded for *file*, or `null` while unknown. */
export function cachedLyrics(file) {
  return (file && ready.get(file)) || null
}

/** Whether *track* is a library song whose lyrics GET /lyrics can read. */
export function hasLyricsSource(track) {
  return !!track?.file && !track.stream && !track.isPodcast
}

/** Load the lyrics of the songs coming up (library songs only). */
export function prefetchLyrics(tracks) {
  for (const track of tracks || []) {
    if (hasLyricsSource(track)) loadLyrics(track.file)
  }
}
