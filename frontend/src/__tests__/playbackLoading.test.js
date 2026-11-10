import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import {
  SHOW_AFTER_MS,
  SLOW_AFTER_MS,
  loadingLabelKey,
  usePlaybackLoading,
} from '../components/player/usePlaybackLoading.js'

describe('loadingLabelKey', () => {
  it('names what playback waits on', () => {
    expect(loadingLabelKey('')).toBe('')
    expect(loadingLabelKey('finding')).toBe('player.findingSong')
    expect(loadingLabelKey('loading')).toBe('player.loadingSong')
    expect(loadingLabelKey('loading', true)).toBe('player.stillLoading')
  })
})

describe('usePlaybackLoading', () => {
  let scope

  beforeEach(() => {
    vi.useFakeTimers()
    scope = effectScope()
  })
  afterEach(() => {
    scope.stop()
    vi.useRealTimers()
  })

  it('shows only after a short wait, then says it is slow', async () => {
    const phase = ref('finding')
    const loading = scope.run(() => usePlaybackLoading(() => phase.value))
    expect(loading.visible.value).toBe(false)
    vi.advanceTimersByTime(SHOW_AFTER_MS)
    expect(loading.labelKey.value).toBe('player.findingSong')
    // Found: now the audio loads, without starting the wait over.
    phase.value = 'loading'
    await nextTick()
    expect(loading.labelKey.value).toBe('player.loadingSong')
    vi.advanceTimersByTime(SLOW_AFTER_MS)
    expect(loading.labelKey.value).toBe('player.stillLoading')
  })

  it('never flashes for a quick start, and clears at once', async () => {
    const phase = ref('loading')
    const loading = scope.run(() => usePlaybackLoading(() => phase.value))
    vi.advanceTimersByTime(SHOW_AFTER_MS - 50)
    phase.value = ''
    await nextTick()
    vi.advanceTimersByTime(SLOW_AFTER_MS)
    expect(loading.visible.value).toBe(false)
    expect(loading.labelKey.value).toBe('')
  })
})
