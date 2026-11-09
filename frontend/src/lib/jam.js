// Pure helpers for following a Jam's shared playback clock.
import { normalizeTrack } from '/src/lib/library'

/** Drift (seconds) past which a device jumps back in step. */
export const MAX_DRIFT_SECONDS = 2

/** Seconds to add to Date.now()/1000 to read the server's clock. */
export function clockOffset(snapshot, localNow = Date.now() / 1000) {
  const now = Number(snapshot?.now)
  return Number.isFinite(now) ? now - localNow : 0
}

/** Where the Jam's current song is right now, by the server's clock. */
export function expectedPosition(
  snapshot,
  offset = 0,
  localNow = Date.now() / 1000
) {
  if (!snapshot) return 0
  const base = Number(snapshot.position) || 0
  if (!snapshot.playing) return base
  const elapsed = Math.max(0, localNow + offset - Number(snapshot.updated))
  const position = base + (Number.isFinite(elapsed) ? elapsed : 0)
  const item = snapshot.queue?.[snapshot.index]
  const duration = Number(item?.duration) || 0
  return duration > 0 ? Math.min(position, duration) : position
}

/** Whether a device at `local` seconds should jump to `expected`. */
export function needsResync(local, expected, limit = MAX_DRIFT_SECONDS) {
  return Math.abs((Number(local) || 0) - (Number(expected) || 0)) > limit
}

/** The Jam's queue as player tracks, each knowing its Jam row. */
export function jamTracks(snapshot) {
  return (snapshot?.queue || []).map((item) => ({
    ...normalizeTrack({
      file: item.file,
      title: item.title,
      artist: item.artist,
      album: item.album,
      duration: item.duration,
    }),
    jamId: item.id,
    addedBy: Number(item.added_by) || 0,
    addedByName: String(item.added_by_name || ''),
  }))
}

/** A library track as the Jam API takes it. */
export function jamTrackPayload(track) {
  return {
    file: String(track?.file || ''),
    title: String(track?.title || ''),
    artist: String(track?.artist || ''),
    album: String(track?.album || ''),
    duration: Number(track?.duration) || 0,
  }
}

/** Only library songs (with a file) can join a Jam. */
export function jammable(tracks) {
  return (tracks || []).filter((track) => track?.file && !track.stream)
}

/** Whether `userId` may drive playback in `snapshot`. */
export function canControl(snapshot, userId) {
  if (!snapshot || !userId) return false
  return snapshot.host_id === userId || !!snapshot.guests_can_control
}

/** The code typed or pasted (a join link works too). */
export function codeFromInput(value) {
  let text = String(value || '').trim()
  const at = text.indexOf('code=')
  if (at >= 0) text = text.slice(at + 5).split('&')[0]
  return text.toUpperCase().replace(/[^A-HJ-NP-Z2-9]/g, '')
}

/** Shuffle a copy of `list` (the Jam takes songs in the order sent). */
export function shuffled(list, random = Math.random) {
  const out = list.slice()
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}
