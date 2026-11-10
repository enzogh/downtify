// What the lock screen, a headset and media keys can do (Media Session).
//
// iOS - and some Android builds - show "back 10 s / forward 10 s" instead
// of "previous / next" as soon as the page handles seekbackward and
// seekforward. Music should skip songs like Spotify's, so those two are
// handled only for a podcast episode (where jumping 15 s back makes
// sense) and explicitly cleared (`null`) for a song.

export const SKIP_SECONDS = 15

/**
 * The Media Session handlers for `track`: `{ action: fn | null }`, built
 * from the player's own actions. A `null` handler removes that control.
 */
export function mediaSessionHandlers(track, actions) {
  const podcast = Boolean(track?.isPodcast)
  return {
    play: actions.play,
    pause: actions.pause,
    stop: actions.pause,
    previoustrack: actions.prev,
    nexttrack: actions.next,
    seekto: (details) => actions.seek(Number(details?.seekTime) || 0),
    seekbackward: podcast
      ? (details) => actions.seekBy(-(details?.seekOffset || SKIP_SECONDS))
      : null,
    seekforward: podcast
      ? (details) => actions.seekBy(details?.seekOffset || SKIP_SECONDS)
      : null,
  }
}

/**
 * The lock screen's progress bar (`setPositionState`), or `null` when
 * there's nothing valid to show (no length yet, a live stream).
 */
export function positionState(duration, position, rate = 1) {
  const length = Number(duration)
  if (!Number.isFinite(length) || length <= 0) return null
  const at = Math.min(Math.max(Number(position) || 0, 0), length)
  return {
    duration: length,
    position: at,
    playbackRate: Number(rate) > 0 ? Number(rate) : 1,
  }
}
