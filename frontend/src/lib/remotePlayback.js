// What the account's other players (`GET /api/activity/devices`, the
// `now_playing` WebSocket frame) are playing - pure helpers for the
// "Playing on another device" bar.

/** The rows of every player but this one (`selfId`) that have a song. */
export function otherPlayers(players, selfId) {
  return (Array.isArray(players) ? players : []).filter(
    (row) =>
      row &&
      row.player !== selfId &&
      row.track &&
      (row.track.file || row.track.track_id)
  )
}

/**
 * The one player to show: a playing one before a paused one, then the
 * one heard from last. `null` when there is none.
 */
export function pickRemote(players, selfId) {
  const rows = otherPlayers(players, selfId)
  if (!rows.length) return null
  return [...rows].sort(
    (a, b) =>
      Number(Boolean(a.paused)) - Number(Boolean(b.paused)) ||
      (Number(a.seconds_ago) || 0) - (Number(b.seconds_ago) || 0)
  )[0]
}

/**
 * Where `row`'s song is now, in seconds: its last reported position,
 * plus the time since the report while it plays (`elapsed`: seconds
 * since this page got the row). Never past the song's end.
 */
export function remotePosition(row, elapsed = 0) {
  if (!row) return 0
  let position = Math.max(0, Number(row.position) || 0)
  if (!row.paused) {
    position += Math.max(0, Number(row.seconds_ago) || 0)
    position += Math.max(0, Number(elapsed) || 0)
  }
  const duration = Number(row.track?.duration) || 0
  return duration > 0 ? Math.min(position, duration) : position
}

/** Identifies one song on one player, to hide the bar for just that. */
export function remoteKey(row) {
  if (!row) return ''
  return `${row.player}|${row.track?.file || row.track?.track_id || ''}`
}

/**
 * Every device but this one, Spotify Connect's order: playing, then
 * paused with a song, then idle (open, nothing loaded). Each group keeps
 * the most recently heard first.
 */
export function otherDevices(players, selfId) {
  const rank = (row) => (!row.track ? 2 : row.paused ? 1 : 0)
  return (Array.isArray(players) ? players : [])
    .filter((row) => row && row.player && row.player !== selfId)
    .map((row, order) => ({ row, order }))
    .sort((a, b) => rank(a.row) - rank(b.row) || a.order - b.order)
    .map(({ row }) => row)
}

// Mirrors the server's cap on a `load` command.
export const MAX_SEND = 500

/**
 * What a `load` command carries for the queue `playlist` playing
 * `index` at `position`: library files only (a stream can't move), at
 * most MAX_SEND around the current song. `null` when the current song
 * isn't a library file.
 */
export function queueToSend(playlist, index, position = 0, playing = true) {
  const list = Array.isArray(playlist) ? playlist : []
  const current = list[index]
  if (!current?.file || current.isPodcast) return null
  const files = []
  let at = 0
  list.forEach((track, i) => {
    if (!track?.file || track.isPodcast) return
    if (i === index) at = files.length
    files.push(track.file)
  })
  const start = Math.max(0, Math.min(at - 50, files.length - MAX_SEND))
  return {
    files: files.slice(start, start + MAX_SEND),
    index: at - start,
    position: Math.max(0, Math.round((Number(position) || 0) * 10) / 10),
    playing: Boolean(playing),
  }
}
