// What one play of a song tells: how long it really played and whether
// it was skipped. Pure, so the rules are testable; model/playHistory.js
// feeds it from the player and sends the rows to the server
// (POST /api/history/plays), where lib/recommender.js reads them back.

/** Shorter than this, a play is a mis-tap or a browse: not kept. */
export const MIN_PLAYED_SECONDS = 5
/** Played this long, a song is never a skip, however long it is. */
export const NOT_A_SKIP_SECONDS = 60
/** Within this much of its end, a song played through. */
const END_MARGIN_SECONDS = 8

/** The song's own words: library tags, else a search row's. */
export function trackIdentity(track) {
  const artist = String(
    track?.artist || track?.albumArtist || (track?.artists || [])[0] || ''
  ).trim()
  const title = String(track?.title || track?.name || '').trim()
  return { artist, title }
}

/**
 * Whether a play that stopped after `played` seconds (the playhead at
 * `position` of `duration`) was a skip: stopped early, before the end.
 */
export function wasSkipped(played, position, duration) {
  const length = Number(duration) || 0
  if (played >= NOT_A_SKIP_SECONDS) return false
  if (length > 0 && position >= length - END_MARGIN_SECONDS) return false
  if (length > 0 && played >= length * 0.5) return false
  return true
}

/**
 * The history row of a play that just ended (the song changed, the page
 * closed), or `null` when it played too little to tell anything.
 */
export function closePlay({
  track,
  played,
  position,
  duration,
  context = '',
  startedAt,
  playId,
}) {
  if (!track || track.isPodcast) return null
  const { artist, title } = trackIdentity(track)
  if (!artist || !title) return null
  const length = Number(duration) || Number(track.duration) || 0
  const seconds = Math.max(0, Number(played) || 0)
  const ended = length > 0 && position >= length - END_MARGIN_SECONDS
  if (seconds < MIN_PLAYED_SECONDS && !ended) return null
  return {
    play_id: playId,
    played_at: startedAt,
    artist,
    title,
    album: String(track.album || ''),
    file: String(track.file || ''),
    video_id: String(track.video_id || ''),
    source: track.file && !track.stream ? 'library' : 'stream',
    played_s: Math.round(seconds * 10) / 10,
    duration_s: Math.round(length * 10) / 10,
    skipped: wasSkipped(seconds, position, length),
    context: String(context || ''),
  }
}

/** A random id for one play (the server counts each once). */
export function newPlayId() {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  } catch {
    // Not a secure context: below.
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}
