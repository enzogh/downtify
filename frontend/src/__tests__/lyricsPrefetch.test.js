import { describe, expect, it, vi } from 'vitest'

const { getLyrics } = vi.hoisted(() => ({ getLyrics: vi.fn() }))

vi.mock('/src/model/api', () => ({ default: { getLyrics } }))

import {
  cachedLyrics,
  hasLyricsSource,
  loadLyrics,
  prefetchLyrics,
} from '../model/lyrics'

describe('lyrics prefetch', () => {
  it('only asks for library songs, never streams or podcasts', () => {
    getLyrics.mockReset()
    getLyrics.mockResolvedValue({ data: { plain: 'la la' } })
    prefetchLyrics([
      { file: 'Artist/next.mp3' },
      { file: 'x', stream: true },
      { file: 'y', isPodcast: true },
      { title: 'no file' },
    ])
    expect(getLyrics.mock.calls).toEqual([['Artist/next.mp3']])
    expect(hasLyricsSource({ file: 'a.mp3' })).toBe(true)
    expect(hasLyricsSource(null)).toBe(false)
  })

  it('exposes settled lyrics synchronously, once and only once loaded', async () => {
    getLyrics.mockReset()
    getLyrics.mockResolvedValue({
      data: { synced: '[00:01.00]Hello', plain: 'Hello' },
    })
    const pending = loadLyrics('Artist/song.flac')
    expect(cachedLyrics('Artist/song.flac')).toBeNull()
    await pending
    expect(cachedLyrics('Artist/song.flac')).toEqual({
      lines: [{ time: 1, text: 'Hello' }],
      plain: 'Hello',
    })
    // Cached: a second load doesn't hit the server again.
    await loadLyrics('Artist/song.flac')
    expect(getLyrics).toHaveBeenCalledTimes(1)
  })

  it('forgets a failed load so it can be retried', async () => {
    getLyrics.mockReset()
    getLyrics.mockRejectedValueOnce(new Error('offline'))
    expect(await loadLyrics('Artist/down.mp3')).toEqual({
      lines: [],
      plain: '',
    })
    expect(cachedLyrics('Artist/down.mp3')).toBeNull()
    getLyrics.mockResolvedValue({ data: { plain: 'back' } })
    expect((await loadLyrics('Artist/down.mp3')).plain).toBe('back')
  })
})
