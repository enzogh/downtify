// Dragging songs onto a playlist in the sidebar, as on Spotify. Library
// rows carry their files; search / chart rows carry the songs themselves
// (they may not be downloaded yet).

export const DRAG_TYPE = 'application/x-downtify-songs'

/** Start a drag of library `files` and/or catalog `songs`. */
export function setDragSongs(event, { files = [], songs = [] }, label = '') {
  const transfer = event?.dataTransfer
  if (!transfer || (!files.length && !songs.length)) return
  transfer.effectAllowed = 'copy'
  transfer.setData(DRAG_TYPE, JSON.stringify({ files, songs }))
  transfer.setData('text/plain', label || files.join('\n'))
}

/** Whether a drag carries songs (the payload is hidden until the drop). */
export function isSongDrag(event) {
  return Array.from(event?.dataTransfer?.types || []).includes(DRAG_TYPE)
}

/** `{ files, songs }` from a drop, or `null` when it carries none. */
export function readDragSongs(event) {
  const raw = event?.dataTransfer?.getData(DRAG_TYPE)
  if (!raw) return null
  try {
    const data = JSON.parse(raw)
    const files = Array.isArray(data?.files)
      ? data.files.filter((item) => typeof item === 'string' && item)
      : []
    const songs = Array.isArray(data?.songs)
      ? data.songs.filter((item) => item && typeof item === 'object')
      : []
    return files.length || songs.length ? { files, songs } : null
  } catch {
    return null
  }
}
