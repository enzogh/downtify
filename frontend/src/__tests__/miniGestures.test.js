import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  LONG_PRESS_MS,
  SWIPE_PX,
  swipeDirection,
  useMiniGestures,
} from '../components/player/useMiniGestures.js'

const touch = (x, y = 0) => ({
  pointerType: 'touch',
  isPrimary: true,
  clientX: x,
  clientY: y,
})

describe('swipeDirection', () => {
  it('reads a clear sideways swipe', () => {
    expect(swipeDirection(-SWIPE_PX - 1, 4)).toBe('next')
    expect(swipeDirection(SWIPE_PX + 1, -4)).toBe('prev')
  })

  it('ignores short moves and mostly vertical ones', () => {
    expect(swipeDirection(-20, 0)).toBe('')
    expect(swipeDirection(-70, 60)).toBe('')
  })
})

describe('useMiniGestures', () => {
  let actions
  let g

  beforeEach(() => {
    vi.useFakeTimers()
    actions = { onNext: vi.fn(), onPrev: vi.fn(), onLongPress: vi.fn() }
    g = useMiniGestures(actions)
  })
  afterEach(() => vi.useRealTimers())

  it('skips on a swipe and swallows the click that follows', () => {
    g.handlers.pointerdown(touch(200))
    g.handlers.pointermove(touch(120))
    expect(g.shift.value).toBeLessThan(0)
    g.handlers.pointerup(touch(120))
    expect(actions.onNext).toHaveBeenCalledOnce()
    expect(g.shift.value).toBe(0)
    expect(g.allowClick()).toBe(false)
    expect(g.allowClick()).toBe(true)
  })

  it('opens the menu on a hold, not on a tap', () => {
    g.handlers.pointerdown(touch(100, 10))
    g.handlers.pointerup(touch(100, 10))
    vi.advanceTimersByTime(LONG_PRESS_MS)
    expect(actions.onLongPress).not.toHaveBeenCalled()
    expect(g.allowClick()).toBe(true)

    g.handlers.pointerdown(touch(100, 10))
    vi.advanceTimersByTime(LONG_PRESS_MS)
    expect(actions.onLongPress).toHaveBeenCalledWith({
      clientX: 100,
      clientY: 10,
    })
    expect(g.allowClick()).toBe(false)
  })

  it('leaves the mouse alone', () => {
    g.handlers.pointerdown({ ...touch(200), pointerType: 'mouse' })
    g.handlers.pointerup({ ...touch(100), pointerType: 'mouse' })
    expect(actions.onNext).not.toHaveBeenCalled()
  })
})
