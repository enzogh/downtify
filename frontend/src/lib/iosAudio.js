// iPhones and iPads run Web Audio (the equalizer, volume normalization)
// in an AudioContext that iOS may suspend once the screen locks or the
// app goes to the background: the music then stops there, where a plain
// <audio> element keeps playing. Pure helpers, so tests can use them.
import { installPlatform } from '/src/lib/installPrompt'

/** Whether this browser runs on iOS or iPadOS. */
export function isIOS(
  userAgent = globalThis.navigator?.userAgent || '',
  maxTouchPoints = globalThis.navigator?.maxTouchPoints || 0
) {
  return String(installPlatform(userAgent, maxTouchPoints) || '').startsWith(
    'ios'
  )
}

/**
 * Whether to warn that playback may stop with the screen locked: on iOS,
 * while the equalizer or normalization routes audio through Web Audio.
 */
export function backgroundAudioAtRisk({ ios, equalizer, normalization }) {
  return Boolean(ios && (equalizer || normalization))
}
