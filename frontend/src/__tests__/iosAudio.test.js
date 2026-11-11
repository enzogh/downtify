import { describe, expect, it } from 'vitest'
import { backgroundAudioAtRisk, isIOS } from '../lib/iosAudio'

const IPHONE =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.7 Mobile/15E148 Safari/604.1'
const MAC =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'

describe('isIOS', () => {
  it('knows an iPhone, an iPad posing as a Mac, and a real Mac', () => {
    expect(isIOS(IPHONE, 5)).toBe(true)
    expect(isIOS(MAC, 5)).toBe(true)
    expect(isIOS(MAC, 0)).toBe(false)
  })
})

describe('backgroundAudioAtRisk', () => {
  it('is only a risk on iOS with Web Audio in use', () => {
    expect(
      backgroundAudioAtRisk({
        ios: true,
        equalizer: false,
        normalization: true,
      })
    ).toBe(true)
    expect(
      backgroundAudioAtRisk({
        ios: true,
        equalizer: true,
        normalization: false,
      })
    ).toBe(true)
    expect(
      backgroundAudioAtRisk({
        ios: true,
        equalizer: false,
        normalization: false,
      })
    ).toBe(false)
    expect(
      backgroundAudioAtRisk({
        ios: false,
        equalizer: true,
        normalization: true,
      })
    ).toBe(false)
  })
})
