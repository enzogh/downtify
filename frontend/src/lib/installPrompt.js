// "Add Castify to your home screen": which guide a phone needs, and when
// to show it. Pure helpers - the browser plumbing is in model/install.js.

// In-app browsers (links opened from Instagram, Facebook, Gmail...) can't
// add anything to the home screen: they have to hand over to Safari.
const IN_APP =
  /FBAN|FBAV|FB_IAB|Instagram|Line\/|Twitter|LinkedInApp|Snapchat|GSA\/|MicroMessenger|TikTok/i
// Other iOS browsers wrap WebKit and add to the home screen from their
// own share button (iOS 16.4+).
const IOS_OTHER = /CriOS|FxiOS|EdgiOS|OPiOS|OPT\/|YaBrowser|DuckDuckGo/i

/**
 * The install guide this device needs: `'ios-safari'`, `'ios-other'`,
 * `'ios-inapp'`, `'android'`, or `null` (a computer - nothing to show).
 * iPadOS reports itself as a Mac; touch points give it away.
 */
export function installPlatform(userAgent = '', maxTouchPoints = 0) {
  const ua = String(userAgent)
  const ios =
    /iPhone|iPad|iPod/i.test(ua) ||
    (/Macintosh/i.test(ua) && Number(maxTouchPoints) > 1)
  if (ios) {
    if (IN_APP.test(ua)) return 'ios-inapp'
    return IOS_OTHER.test(ua) ? 'ios-other' : 'ios-safari'
  }
  if (/Android/i.test(ua)) return 'android'
  return null
}

/** True when the page runs as the installed app, not in a browser tab. */
export function isStandalone(win = globalThis) {
  if (win?.navigator?.standalone === true) return true
  const query = (q) => Boolean(win?.matchMedia?.(q)?.matches)
  return (
    query('(display-mode: standalone)') ||
    query('(display-mode: fullscreen)') ||
    query('(display-mode: minimal-ui)')
  )
}

// "Later" hides the guide for a day; it comes back until it's installed.
export const SNOOZE_MS = 24 * 60 * 60 * 1000

/**
 * Whether to open the guide by itself: on a phone, in a browser tab,
 * not marked as installed and not snoozed.
 */
export function shouldOffer({
  platform,
  standalone,
  installed,
  snoozedUntil,
  now,
}) {
  if (!platform || standalone || installed) return false
  return !(Number(snoozedUntil) > Number(now))
}
