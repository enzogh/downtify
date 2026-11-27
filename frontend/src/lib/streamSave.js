// What the player says about a song it streams live: that it isn't on
// the server, whether it is being saved there, and how many more plays
// before *Download after live plays* saves it on its own.

/** The watch URL a streamed video is downloaded (and keyed) by. */
export function watchUrl(videoId) {
  return `https://music.youtube.com/watch?v=${videoId}`
}

/**
 * The playing stream as a downloadable song, or `null` when the track
 * isn't a stream or there is nothing to download it by. The watch URL
 * is its queue key and the video id pins that exact version, like a
 * resolved search row; before a video is known (a stream restored from
 * the last session) the row it was started from is downloaded instead.
 */
export function streamSaveSong(track) {
  if (!track?.stream) return null
  if (!track.video_id) return track.song?.url ? track.song : null
  const cover = String(track.cover || '')
  return {
    name: track.title || '',
    artists: track.artist ? [track.artist] : [],
    artist: track.artist || '',
    album_name: track.album || '',
    cover_url: cover.startsWith('http') ? cover : '',
    duration: track.duration || 0,
    explicit: Boolean(track.explicit),
    url: watchUrl(track.video_id),
    youtube_id: track.video_id,
  }
}

/**
 * Every queue key the stream's download may be filed under: the one
 * the player queues, the row it was started from (a download asked for
 * there) and the bare video id (what *Download after live plays* uses).
 */
export function streamJobCandidates(track) {
  const own = streamSaveSong(track)
  if (!own) return []
  const byVideo = track.video_id ? { song_id: track.video_id } : null
  return [...new Set([own, track.song, byVideo])].filter(Boolean)
}

/**
 * `'saved'` (on the server), `'queued'`, `'active'`, `'failed'` or
 * `'new'` (nothing asked yet). A finished job counts as saved even
 * before the library has listed the file.
 */
export function streamSaveState(job, onServer) {
  if (onServer) return 'saved'
  const state = job?.state
  if (state === 'done') return 'saved'
  if (state === 'queued' || state === 'active' || state === 'failed')
    return state
  return 'new'
}

/**
 * Plays left before the server saves the song on its own, from
 * `GET /api/stream/live/plays`: `null` when that is off (or unknown),
 * `0` once it has been queued that way.
 */
export function autoSaveRemaining(info) {
  const threshold = Number(info?.threshold) || 0
  if (threshold <= 0) return null
  if (info.queued) return 0
  return Math.max(1, threshold - (Number(info.plays) || 0))
}
