import { describe, expect, it, vi } from 'vitest'
import {
  SKIP_SECONDS,
  mediaSessionHandlers,
  positionState,
} from '../lib/mediaSession.js'

function actions() {
  return {
    play: vi.fn(),
    pause: vi.fn(),
    prev: vi.fn(),
    next: vi.fn(),
    seek: vi.fn(),
    seekBy: vi.fn(),
  }
}

describe('lock screen controls', () => {
  it('skips songs, never 10-second jumps, for music', () => {
    const player = actions()
    const handlers = mediaSessionHandlers({ title: 'Roads' }, player)
    expect(handlers.seekbackward).toBeNull()
    expect(handlers.seekforward).toBeNull()
    handlers.previoustrack()
    handlers.nexttrack()
    expect(player.prev).toHaveBeenCalled()
    expect(player.next).toHaveBeenCalled()
    handlers.seekto({ seekTime: 42 })
    expect(player.seek).toHaveBeenCalledWith(42)
  })

  it('keeps the jumps for a podcast episode', () => {
    const player = actions()
    const handlers = mediaSessionHandlers({ isPodcast: true }, player)
    handlers.seekbackward({})
    handlers.seekforward({ seekOffset: 30 })
    expect(player.seekBy).toHaveBeenNthCalledWith(1, -SKIP_SECONDS)
    expect(player.seekBy).toHaveBeenNthCalledWith(2, 30)
  })

  it('draws the progress bar only with a known length', () => {
    expect(positionState(200, 50, 1.5)).toEqual({
      duration: 200,
      position: 50,
      playbackRate: 1.5,
    })
    expect(positionState(200, 250).position).toBe(200)
    expect(positionState(0, 10)).toBeNull()
    expect(positionState(Infinity, 10)).toBeNull()
  })
})
