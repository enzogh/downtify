// Autoplay: when the queue runs out, the player carries on with songs
// like the last ones played, as Spotify does. Pure helpers; the model is
// model/autoplay.js.

import { recommendationKey } from '/src/lib/recommendations'

/** How many recommended songs one top-up adds. */
export const AUTOPLAY_BATCH = 10
/** Upcoming tracks left when the next ones are fetched. */
export const AUTOPLAY_THRESHOLD = 1

/**
 * Up to `count` songs to seed the mixes from: the current track and
 * those before it, newest first, one per artist. Podcast episodes and
 * rows without an artist and title are skipped.
 */
export function autoplaySeeds(list, index, count = 3) {
  const seeds = []
  const artists = new Set()
  for (let i = Math.min(index, (list || []).length - 1); i >= 0; i -= 1) {
    const track = list[i]
    if (!track || track.isPodcast || !track.artist || !track.title) continue
    const artist = String(track.artist).trim().toLowerCase()
    if (artists.has(artist)) continue
    artists.add(artist)
    seeds.push(track)
    if (seeds.length >= count) break
  }
  return seeds
}

/** What a set of seeds is known by: one top-up per set. */
export function seedsKey(seeds) {
  return seeds.map((track) => recommendationKey(track)).join('\n')
}

/**
 * Songs from `found` the queue doesn't already hold (by artist and
 * title), at most `limit`.
 */
export function freshSongs(found, queue, limit = AUTOPLAY_BATCH) {
  const have = new Set((queue || []).map((track) => recommendationKey(track)))
  const out = []
  for (const song of found || []) {
    const key = recommendationKey(song)
    if (have.has(key)) continue
    have.add(key)
    out.push(song)
    if (out.length >= limit) break
  }
  return out
}
