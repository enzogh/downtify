import { beforeEach, describe, expect, it, vi } from 'vitest'

const { prefetchLiveStream } = vi.hoisted(() => ({
  prefetchLiveStream: vi.fn(),
}))

vi.mock('/src/model/api', () => ({
  default: { prefetchLiveStream, search: vi.fn() },
}))

// songPlay's other collaborators play no part in warming.
vi.mock('/src/model/library', () => ({ useLibrary: () => ({}) }))
vi.mock('/src/model/player', () => ({ usePlayer: () => ({}) }))
vi.mock('/src/model/trackActions', () => ({ useTrackActions: () => ({}) }))
vi.mock('/src/model/ui', () => ({ useUi: () => ({}) }))
vi.mock('/src/model/stream', () => ({}))
vi.mock('/src/i18n', () => ({ useI18n: () => ({ t: (k) => k }) }))

import { resetWarmed, warmSong } from '../model/songPlay.js'

const noTrack = () => null

describe('warmSong', () => {
  beforeEach(() => {
    resetWarmed()
    prefetchLiveStream.mockClear()
  })

  it('resolves a hovered song’s live URL ahead, once', () => {
    const song = { name: 'Urus', artists: ['Favé'], song_id: 'cmQohyB8YjE' }
    warmSong(song, noTrack)
    warmSong(song, noTrack)
    expect(prefetchLiveStream).toHaveBeenCalledOnce()
    expect(prefetchLiveStream).toHaveBeenCalledWith('cmQohyB8YjE')
  })

  it('leaves downloaded songs alone', () => {
    const song = { name: 'Urus', artists: ['Favé'], song_id: 'cmQohyB8YjE' }
    warmSong(song, () => ({ file: 'Favé - Urus.mp3' }))
    expect(prefetchLiveStream).not.toHaveBeenCalled()
  })

  it('never searches for a song without its own video id', () => {
    warmSong({ name: 'Urus', artists: ['Favé'] }, noTrack)
    expect(prefetchLiveStream).not.toHaveBeenCalled()
  })
})
