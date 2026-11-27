import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive, ref } from 'vue'

import {
  autoSaveRemaining,
  streamJobCandidates,
  streamSaveSong,
  streamSaveState,
} from '../lib/streamSave.js'

const fixture = vi.hoisted(() => ({
  state: null,
  version: null,
  queue: vi.fn(),
  retry: vi.fn(),
  toast: vi.fn(),
  plays: vi.fn(),
}))

vi.mock('/src/model/player', async () => {
  const { computed } = await import('vue')
  return {
    usePlayer: () => ({ currentTrack: computed(() => fixture.state.track) }),
  }
})
vi.mock('/src/model/library', () => ({
  useLibrary: () => ({
    hasSong: () => fixture.state.inLibrary,
  }),
}))
vi.mock('/src/model/download', () => ({
  jobSongKey: (song) => String(song?.song_id || song?.url || ''),
  useDownloadManager: () => ({ queue: fixture.queue, retry: fixture.retry }),
  useProgressTracker: () => ({
    queueVersion: fixture.version,
    getBySong: (song) =>
      fixture.state.jobs[String(song?.song_id || song?.url || '')] || null,
  }),
}))
vi.mock('/src/model/ui', () => ({ useUi: () => ({ toast: fixture.toast }) }))
vi.mock('/src/model/api', () => ({
  default: { getLiveStreamPlays: fixture.plays },
}))
vi.mock('/src/i18n', () => ({
  useI18n: () => ({ t: (key, params) => `${key}:${params?.name ?? ''}` }),
}))

const VID = 'dQw4w9WgXcQ'
const streamed = (extra = {}) => ({
  stream: true,
  video_id: VID,
  title: 'Song',
  artist: 'Artist',
  album: 'Album',
  cover: 'https://img/c.jpg',
  duration: 200,
  ...extra,
})

describe('streamSaveSong', () => {
  it('pins the streamed video and keys it by its watch URL', () => {
    expect(streamSaveSong(streamed())).toMatchObject({
      name: 'Song',
      artists: ['Artist'],
      url: `https://music.youtube.com/watch?v=${VID}`,
      youtube_id: VID,
      cover_url: 'https://img/c.jpg',
    })
  })

  it('is null for a library track or a stream without a video', () => {
    expect(streamSaveSong({ file: 'a.mp3', title: 'x' })).toBeNull()
    expect(streamSaveSong(streamed({ video_id: '' }))).toBeNull()
  })

  it('falls back to the source row before the video is known', () => {
    const row = { url: 'https://soundcloud.com/a/b', name: 'Song' }
    expect(streamSaveSong(streamed({ video_id: '', song: row }))).toBe(row)
    expect(streamJobCandidates(streamed({ video_id: '', song: row }))).toEqual([
      row,
    ])
  })

  it('drops a cover that is not a web URL', () => {
    expect(streamSaveSong(streamed({ cover: '/cover?x' })).cover_url).toBe('')
  })
})

describe('streamJobCandidates', () => {
  it('looks under the player key, the source row and the bare video id', () => {
    const row = { url: 'https://open.spotify.com/track/1' }
    const keys = streamJobCandidates(streamed({ song: row })).map(
      (song) => song.song_id || song.url
    )
    expect(keys).toEqual([
      `https://music.youtube.com/watch?v=${VID}`,
      'https://open.spotify.com/track/1',
      VID,
    ])
  })
})

describe('streamSaveState', () => {
  it('says saved once on the server or once the job finished', () => {
    expect(streamSaveState(null, true)).toBe('saved')
    expect(streamSaveState({ state: 'done' }, false)).toBe('saved')
  })

  it('follows the job otherwise', () => {
    expect(streamSaveState(null, false)).toBe('new')
    expect(streamSaveState({ state: 'queued' }, false)).toBe('queued')
    expect(streamSaveState({ state: 'active' }, false)).toBe('active')
    expect(streamSaveState({ state: 'failed' }, false)).toBe('failed')
  })
})

describe('autoSaveRemaining', () => {
  it('is null while Download after live plays is off', () => {
    expect(autoSaveRemaining(null)).toBeNull()
    expect(autoSaveRemaining({ plays: 4, threshold: 0 })).toBeNull()
  })

  it('counts the plays left, at least one until queued', () => {
    expect(autoSaveRemaining({ plays: 1, threshold: 3 })).toBe(2)
    expect(autoSaveRemaining({ plays: 5, threshold: 3 })).toBe(1)
    expect(autoSaveRemaining({ plays: 3, threshold: 3, queued: true })).toBe(0)
  })
})

describe('useStreamSave', () => {
  let useStreamSave
  let resetStreamSave

  beforeEach(async () => {
    vi.useFakeTimers()
    fixture.version = ref(0)
    fixture.state = reactive({ track: streamed(), inLibrary: false, jobs: {} })
    fixture.queue.mockReset()
    fixture.retry.mockReset()
    fixture.toast.mockReset()
    fixture.plays.mockReset()
    fixture.plays.mockResolvedValue({
      data: { plays: 1, threshold: 3, queued: false },
    })
    ;({ useStreamSave, resetStreamSave } =
      await import('../model/streamSave.js'))
    resetStreamSave()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('queues the stream once and says it will be saved', () => {
    const save = useStreamSave()
    expect(save.state.value).toBe('new')
    save.save()
    expect(fixture.queue).toHaveBeenCalledWith(
      expect.objectContaining({ youtube_id: VID })
    )
    expect(fixture.toast).toHaveBeenCalledWith(
      'stream.queuedToast:Song',
      expect.anything()
    )
  })

  it('finds a download started on the bare video id', () => {
    fixture.state.jobs = { [VID]: { state: 'active', progress: 41.6 } }
    const save = useStreamSave()
    expect(save.state.value).toBe('active')
    expect(save.progress.value).toBe(42)
    save.save()
    expect(fixture.queue).not.toHaveBeenCalled()
  })

  it('retries a failed download instead of queueing a new one', () => {
    const job = { state: 'failed', song: { url: 'row' } }
    fixture.state.jobs = { [`https://music.youtube.com/watch?v=${VID}`]: job }
    useStreamSave().save()
    expect(fixture.retry).toHaveBeenCalledWith({ url: 'row' })
    expect(fixture.queue).not.toHaveBeenCalled()
  })

  it('toasts once the playing stream lands on the server', async () => {
    fixture.state.jobs = { [VID]: { state: 'active', progress: 80 } }
    const save = useStreamSave()
    expect(save.state.value).toBe('active')
    fixture.state.inLibrary = true
    await nextTick()
    expect(save.state.value).toBe('saved')
    expect(fixture.toast).toHaveBeenCalledWith(
      'stream.savedToast:Song',
      expect.anything()
    )
  })

  it('asks the server how many plays are left, after the play counted', async () => {
    const save = useStreamSave()
    expect(fixture.plays).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(4000)
    expect(fixture.plays).toHaveBeenCalledWith(VID)
    expect(save.autoRemaining.value).toBe(2)
  })

  it('treats a library track as already saved', () => {
    fixture.state.track = { file: 'a.mp3', title: 'x', artist: 'y' }
    expect(useStreamSave().state.value).toBe('saved')
  })
})
