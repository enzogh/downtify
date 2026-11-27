import { describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ track: null }))

vi.mock('/src/model/api', () => ({ default: {} }))
vi.mock('/src/model/library', () => ({
  useLibrary: () => ({ findTrack: () => state.track }),
}))
vi.mock('/src/model/player', () => ({
  usePlayer: () => ({
    currentTrack: { value: null },
    isPlaying: { value: false },
    resolving: { value: null },
  }),
}))
vi.mock('/src/model/stream', () => ({
  isStreamingSong: () => false,
  playStream: vi.fn(),
  resolvingFor: () => false,
}))
vi.mock('/src/model/trackActions', () => ({ useTrackActions: () => ({}) }))
vi.mock('/src/model/ui', () => ({ useUi: () => ({}) }))
vi.mock('/src/i18n', () => ({
  useI18n: () => ({ t: (key, params) => `${key}:${params?.name ?? ''}` }),
}))

import { useSongPlay } from '../model/songPlay.js'

const song = { name: 'Urus', artists: ['Favé'], song_id: 'cmQohyB8YjE' }

describe('useSongPlay playLabel', () => {
  it('says a song that is not on the server plays live', () => {
    state.track = null
    expect(useSongPlay({ song }).playLabel.value).toBe('stream.playLive:Urus')
  })

  it('plainly plays a song from the library', () => {
    state.track = { file: 'Favé - Urus.mp3', title: 'Urus' }
    expect(useSongPlay({ song }).playLabel.value).toBe('actions.playItem:Urus')
  })
})
