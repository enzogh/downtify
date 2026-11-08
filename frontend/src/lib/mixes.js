// "Made for you" mixes on Home, built from the library and this device's
// listening log (model/listening.js). Pure, so the shelf is testable.

const DAY_MS = 24 * 60 * 60 * 1000
/** Plays older than this don't count towards what you like lately. */
export const RECENT_DAYS = 30

function artistOf(track) {
  return String(track?.albumArtist || track?.artist || '').trim()
}

function keyOf(name) {
  return String(name || '')
    .trim()
    .toLowerCase()
}

// A small seeded PRNG: the same mix all day, a new order tomorrow.
function seeded(seedText) {
  let h = 2166136261
  for (const ch of String(seedText)) {
    h ^= ch.charCodeAt(0)
    h = Math.imul(h, 16777619)
  }
  return () => {
    h += 0x6d2b79f5
    let x = h
    x = Math.imul(x ^ (x >>> 15), x | 1)
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61)
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296
  }
}

function shuffled(list, random) {
  const out = [...list]
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

/** `{ [file]: count }` of the plays within the last RECENT_DAYS. */
export function recentPlayCounts(plays, now = Date.now()) {
  const since = now - RECENT_DAYS * DAY_MS
  const counts = {}
  for (const play of plays || []) {
    if (!play?.file || !(play.at >= since)) continue
    counts[play.file] = (counts[play.file] || 0) + 1
  }
  return counts
}

/**
 * Up to `count` mixes of up to `size` tracks: each led by an artist you
 * play (or like, or simply have the most of), half their songs and half
 * from the other artists you return to, in an order that holds for the
 * day. `{ id, title, artist, artists, tracks, covers }` each.
 */
export function buildMixes(
  tracks,
  { plays = [], liked = new Set(), now = Date.now(), count = 4, size = 30 } = {}
) {
  const usable = (tracks || []).filter(
    (track) => track?.file && artistOf(track)
  )
  if (usable.length < 8) return []
  const counts = recentPlayCounts(plays, now)
  const byArtist = new Map()
  for (const track of usable) {
    const key = keyOf(artistOf(track))
    if (!byArtist.has(key)) {
      byArtist.set(key, { name: artistOf(track), tracks: [], score: 0 })
    }
    const entry = byArtist.get(key)
    entry.tracks.push(track)
    entry.score +=
      (counts[track.file] || 0) * 3 + (liked.has(track.file) ? 2 : 0) + 0.01
  }
  const ranked = [...byArtist.values()]
    .filter((entry) => entry.tracks.length >= 3)
    .sort((a, b) => b.score - a.score || b.tracks.length - a.tracks.length)
  const seeds = ranked.slice(0, count)
  const day = Math.floor(now / DAY_MS)
  return seeds.map((seed, index) => {
    const random = seeded(`${day}:${keyOf(seed.name)}`)
    const own = shuffled(seed.tracks, random).slice(0, Math.ceil(size / 2))
    // The others: the ranked artists after this one, round-robin, so a
    // mix mixes rather than repeating one neighbour.
    const others = ranked
      .filter((entry) => entry !== seed)
      .slice(0, 8)
      .map((entry) => shuffled(entry.tracks, random))
    const guests = []
    for (let i = 0; guests.length < size - own.length; i += 1) {
      let added = false
      for (const list of others) {
        if (list[i]) {
          guests.push(list[i])
          added = true
          if (guests.length >= size - own.length) break
        }
      }
      if (!added) break
    }
    const list = shuffled([...own, ...guests], random)
    const artists = [
      seed.name,
      ...new Set(guests.map(artistOf).filter((name) => name !== seed.name)),
    ].slice(0, 3)
    return {
      id: `mix-${index + 1}`,
      number: index + 1,
      artist: seed.name,
      artists,
      tracks: list,
      covers: list
        .filter((track) => track.hasCover && track.cover)
        .map((track) => track.cover)
        .filter((cover, i, all) => all.indexOf(cover) === i)
        .slice(0, 4),
    }
  })
}

/** The songs played most lately (at least `min` times), most first. */
export function onRepeat(
  tracks,
  plays,
  { now = Date.now(), min = 3, size = 30 } = {}
) {
  const counts = recentPlayCounts(plays, now)
  return (tracks || [])
    .filter((track) => (counts[track?.file] || 0) >= min)
    .sort((a, b) => counts[b.file] - counts[a.file])
    .slice(0, size)
}
