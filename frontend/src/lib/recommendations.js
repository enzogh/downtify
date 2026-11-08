// Helpers for the "Recommended songs" list under a Library playlist.

function clean(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
}

/** A song's identity across search rows and library tracks. */
export function recommendationKey(song) {
  const artist = Array.isArray(song?.artists) ? song.artists[0] : song?.artist
  return `${clean(artist)}|${clean(song?.name || song?.title)}`
}

/**
 * Up to `count` distinct-artist tracks to seed the mixes from: the most
 * recently added first, then, for each `round` (the Refresh button), the
 * next ones back, wrapping around.
 */
export function pickSeeds(tracks, count = 3, round = 0) {
  const usable = (tracks || []).filter((track) => track?.artist && track?.title)
  if (!usable.length) return []
  const newestFirst = [...usable].reverse()
  const start = (round * count) % newestFirst.length
  const ordered = [...newestFirst.slice(start), ...newestFirst.slice(0, start)]
  const seeds = []
  const artists = new Set()
  for (const track of ordered) {
    const artist = clean(track.artist)
    if (artists.has(artist)) continue
    artists.add(artist)
    seeds.push(track)
    if (seeds.length >= count) break
  }
  return seeds.length ? seeds : ordered.slice(0, count)
}

/**
 * One list from several mixes, taking from each in turn so one seed
 * doesn't fill it, without repeating a song.
 */
export function interleave(lists, keyOf = recommendationKey) {
  const merged = []
  const seen = new Set()
  const longest = Math.max(0, ...lists.map((list) => list.length))
  for (let i = 0; i < longest; i += 1) {
    for (const list of lists) {
      const song = list[i]
      if (!song) continue
      const key = keyOf(song)
      if (seen.has(key)) continue
      seen.add(key)
      merged.push(song)
    }
  }
  return merged
}
