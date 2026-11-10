import { describe, expect, it } from 'vitest'
import {
  SNOOZE_MS,
  installPlatform,
  isStandalone,
  shouldOffer,
} from '../lib/installPrompt'

const IPHONE_SAFARI =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1'
const IPHONE_CHROME =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0.6723.90 Mobile/15E148 Safari/604.1'
const IPHONE_INSTAGRAM =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 350.0.0.0'
const IPAD_DESKTOP_MODE =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15'
const ANDROID_CHROME =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36'
const WINDOWS_CHROME =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'

describe('installPlatform', () => {
  it('tells iOS browsers apart', () => {
    expect(installPlatform(IPHONE_SAFARI)).toBe('ios-safari')
    expect(installPlatform(IPHONE_CHROME)).toBe('ios-other')
    expect(installPlatform(IPHONE_INSTAGRAM)).toBe('ios-inapp')
  })

  it('spots an iPad posing as a Mac by its touch points', () => {
    expect(installPlatform(IPAD_DESKTOP_MODE, 5)).toBe('ios-safari')
    expect(installPlatform(IPAD_DESKTOP_MODE, 0)).toBe(null)
  })

  it('recognises Android and ignores computers', () => {
    expect(installPlatform(ANDROID_CHROME)).toBe('android')
    expect(installPlatform(WINDOWS_CHROME)).toBe(null)
    expect(installPlatform()).toBe(null)
  })
})

describe('isStandalone', () => {
  const win = (matches, standalone) => ({
    navigator: { standalone },
    matchMedia: (q) => ({ matches: matches.includes(q) }),
  })

  it('is true for the installed app on iOS and Android', () => {
    expect(isStandalone(win([], true))).toBe(true)
    expect(isStandalone(win(['(display-mode: standalone)']))).toBe(true)
  })

  it('is false in a browser tab', () => {
    expect(isStandalone(win([], false))).toBe(false)
    expect(isStandalone({})).toBe(false)
  })
})

describe('shouldOffer', () => {
  const base = {
    platform: 'ios-safari',
    standalone: false,
    installed: false,
    snoozedUntil: 0,
    now: 1_000_000,
  }

  it('offers on a phone browser tab', () => {
    expect(shouldOffer(base)).toBe(true)
  })

  it('stays quiet on a computer, in the app, or once installed', () => {
    expect(shouldOffer({ ...base, platform: null })).toBe(false)
    expect(shouldOffer({ ...base, standalone: true })).toBe(false)
    expect(shouldOffer({ ...base, installed: true })).toBe(false)
  })

  it('comes back once "Later" has worn off', () => {
    const snoozedUntil = base.now + SNOOZE_MS
    expect(shouldOffer({ ...base, snoozedUntil })).toBe(false)
    expect(shouldOffer({ ...base, snoozedUntil, now: snoozedUntil + 1 })).toBe(
      true
    )
  })
})
