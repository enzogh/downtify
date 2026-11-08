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
 * The artists the mixes are led by: those you play (or like, or simply
 * have the most songs from), with at least three songs in the library.
 * `{ key, name, tracks, score }` each, best first.
 */
export function mixSeeds(
  tracks,
  { plays = [], liked = new Set(), now = Date.now(), count = 4 } = {}
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
      byArtist.set(key, { key, name: artistOf(track), tracks: [], score: 0 })
    }
    const entry = byArtist.get(key)
    entry.tracks.push(track)
    entry.score +=
      (counts[track.file] || 0) * 3 + (liked.has(track.file) ? 2 : 0) + 0.01
  }
  return [...byArtist.values()]
    .filter((entry) => entry.tracks.length >= 3)
    .sort((a, b) => b.score - a.score || b.tracks.length - a.tracks.length)
    .slice(0, count)
}

function songArtists(song) {
  if (Array.isArray(song?.artists) && song.artists.length) return song.artists
  return song?.artist ? [song.artist] : []
}

function songIdentity(artist, title) {
  return `${keyOf(artist)}|${keyOf(title)}`
}

/**
 * Up to `count` mixes of up to `size` songs, each led by one artist (see
 * mixSeeds) and held together by what YouTube Music plays after them:
 * `similar[seed.key]` is that radio mix (search rows). A mix is
 *
 * - up to half the lead artist's own songs,
 * - songs you have by the artists of that radio mix,
 * - then the radio mix's songs themselves (streamed when not downloaded),
 *
 * in an order that holds for the day. Without a radio mix yet, it is the
 * lead artist's songs alone - never unrelated artists. Library songs are
 * tracks; the rest are search rows. `{ id, number, artist, artists,
 * items, covers }` each, `items` being `{ track }` or `{ song }`.
 */
export function buildMixes(
  tracks,
  {
    plays = [],
    liked = new Set(),
    similar = {},
    now = Date.now(),
    count = 4,
    size = 30,
  } = {}
) {
  const seeds = mixSeeds(tracks, { plays, liked, now, count })
  if (!seeds.length) return []
  const byArtist = new Map()
  for (const track of tracks || []) {
    if (!track?.file || !artistOf(track)) continue
    const key = keyOf(artistOf(track))
    if (!byArtist.has(key)) byArtist.set(key, [])
    byArtist.get(key).push(track)
  }
  const day = Math.floor(now / DAY_MS)
  return seeds.map((seed, index) => {
    const random = seeded(`${day}:${seed.key}`)
    const radio = similar[seed.key] || []
    const own = shuffled(seed.tracks, random).slice(0, Math.ceil(size / 2))
    const seen = new Set(
      own.map((track) => songIdentity(artistOf(track), track.title))
    )
    const items = own.map((track) => ({ track }))
    // Songs you have by the radio mix's artists, one artist at a time.
    const related = [
      ...new Set(
        radio
          .flatMap((song) => songArtists(song).map(keyOf))
          .filter((key) => key && key !== seed.key)
      ),
    ]
    const relatedLists = related
      .map((key) => shuffled(byArtist.get(key) || [], random))
      .filter((list) => list.length)
    for (let i = 0; items.length < size; i += 1) {
      let added = false
      for (const list of relatedLists) {
        const track = list[i]
        if (!track || items.length >= size) continue
        const id = songIdentity(artistOf(track), track.title)
        if (seen.has(id)) continue
        seen.add(id)
        items.push({ track })
        added = true
      }
      if (!added) break
    }
    // Then the radio mix itself, for what the library hasn't got.
    for (const song of radio) {
      if (items.length >= size) break
      const id = songIdentity(songArtists(song)[0], song?.name || song?.title)
      if (seen.has(id)) continue
      seen.add(id)
      items.push({ song })
    }
    const list = shuffled(items, random)
    const artists = [
      seed.name,
      ...new Set(
        list
          .map((item) =>
            item.track ? artistOf(item.track) : songArtists(item.song)[0]
          )
          .filter((name) => name && keyOf(name) !== seed.key)
      ),
    ].slice(0, 3)
    const covers = list
      .map((item) =>
        item.track
          ? item.track.hasCover
            ? item.track.cover
            : ''
          : item.song?.cover_url || ''
      )
      .filter((cover, i, all) => cover && all.indexOf(cover) === i)
      .slice(0, 4)
    return {
      id: String(index + 1),
      number: index + 1,
      artist: seed.name,
      artists,
      items: list,
      covers,
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
