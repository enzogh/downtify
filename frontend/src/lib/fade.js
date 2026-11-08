// The volume ramp of "Fade between songs": the player fades a song out
// over its last seconds and the next one in over its first.

/** Longest fade offered, in seconds. */
export const MAX_FADE_SECONDS = 12

export function clampFade(value) {
  const seconds = Math.round(Number(value) || 0)
  return Math.max(0, Math.min(MAX_FADE_SECONDS, seconds))
}

/**
 * The gain (0..1) to apply at `time` of a track lasting `duration`:
 * rising over the first `fade` seconds when `fadeIn`, falling over the
 * last `fade` seconds when `fadeOut`. A track too short for both fades
 * plays at full volume.
 */
export function fadeGain(time, duration, fade, { fadeIn, fadeOut }) {
  if (!(fade > 0) || !(duration > fade * 2)) return 1
  let gain = 1
  if (fadeIn && time < fade) gain = Math.min(gain, Math.max(0, time / fade))
  const left = duration - time
  if (fadeOut && left < fade) gain = Math.min(gain, Math.max(0, left / fade))
  return gain
}
