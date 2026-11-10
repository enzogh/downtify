import { describe, expect, it } from 'vitest'
import {
  collectionSize,
  collectionTracks,
  coverKey,
  emptyIndex,
  missingTracks,
  needsSync,
  offlineSupport,
  parseIndex,
  savableTracks,
  songKey,
  storedTrack,
  totalSize,
  withCollection,
  withoutCollection,
} from '../lib/offline'

const song = (name, extra = {}) => ({
  file: `${name}.mp3`,
  title: name,
  artist: 'Artist',
  url: `/downloads/${name}.mp3`,
  cover: `/cover?file=${name}.mp3`,
  ...extra,
})

function saved(index, tracks, size = 10) {
  for (const track of tracks) {
    index.tracks[track.file] = { ...storedTrack(track), size }
  }
  return index
}

describe('offline index', () => {
  it('keeps only library songs, each once', () => {
    const list = [
      song('A'),
      song('A'),
      { title: 'Streamed', stream: true, url: 'https://x/y' },
      { file: '', title: 'No file', url: '/downloads/x.mp3' },
      song('B'),
    ]
    expect(savableTracks(list).map((t) => t.title)).toEqual(['A', 'B'])
  })

  it('keys songs and covers the way the service worker looks them up', () => {
    const origin = 'https://music.example'
    expect(songKey('/downloads/My%20Song.mp3?v=2', origin)).toBe(
      'https://music.example/downloads/My%20Song.mp3'
    )
    expect(coverKey('Dir/A & B.mp3', origin)).toBe(
      'https://music.example/cover?file=Dir%2FA%20%26%20B.mp3'
    )
  })

  it('deletes a song only when no saved collection holds it any more', () => {
    let index = emptyIndex()
    ;({ index } = withCollection(index, {
      key: 'playlist:mix',
      files: ['A.mp3', 'B.mp3'],
    }))
    ;({ index } = withCollection(index, {
      key: 'album:x',
      files: ['B.mp3', 'C.mp3'],
    }))
    saved(index, [song('A'), song('B'), song('C')])
    const result = withoutCollection(index, 'playlist:mix')
    expect(result.dropped.map((t) => t.file)).toEqual(['A.mp3'])
    expect(Object.keys(result.index.tracks).sort()).toEqual(['B.mp3', 'C.mp3'])
    // The index it started from is left as it was.
    expect(index.collections['playlist:mix']).toBeTruthy()
  })

  it('drops songs taken out of a collection when it is saved again', () => {
    let index = emptyIndex()
    ;({ index } = withCollection(index, {
      key: 'playlist:mix',
      files: ['A.mp3', 'B.mp3'],
    }))
    saved(index, [song('A'), song('B')])
    const result = withCollection(index, {
      key: 'playlist:mix',
      files: ['B.mp3', 'D.mp3'],
    })
    expect(result.dropped.map((t) => t.file)).toEqual(['A.mp3'])
    expect(missingTracks(result.index, [song('B'), song('D')])).toEqual([
      song('D'),
    ])
  })

  it('lists a collection in its order with its size', () => {
    let index = emptyIndex()
    ;({ index } = withCollection(index, {
      key: 'album:x',
      files: ['B.mp3', 'A.mp3', 'Z.mp3'],
    }))
    saved(index, [song('A'), song('B')], 25)
    expect(collectionTracks(index, 'album:x').map((t) => t.title)).toEqual([
      'B',
      'A',
    ])
    expect(collectionSize(index, 'album:x')).toBe(50)
    expect(totalSize(index)).toBe(50)
  })

  it('notices when a saved collection changed', () => {
    const entry = { files: ['A.mp3', 'B.mp3'] }
    expect(needsSync(entry, [song('A'), song('B')])).toBe(false)
    expect(needsSync(entry, [song('B'), song('A')])).toBe(true)
    expect(needsSync(entry, [song('A'), song('B'), song('C')])).toBe(true)
    expect(needsSync(null, [song('A')])).toBe(false)
  })

  it('starts over from an index it cannot read', () => {
    expect(parseIndex(null)).toEqual(emptyIndex())
    expect(parseIndex({ version: 99, collections: {} })).toEqual(emptyIndex())
    const index = parseIndex({
      version: 1,
      collections: { 'album:x': { files: ['A.mp3'] }, broken: {} },
      tracks: { 'A.mp3': { title: 'A' }, bad: null },
    })
    expect(Object.keys(index.collections)).toEqual(['album:x'])
    expect(index.collections['album:x'].key).toBe('album:x')
    expect(index.tracks['A.mp3'].file).toBe('A.mp3')
    expect(index.tracks.bad).toBeUndefined()
  })

  it('needs HTTPS (or localhost) and the browser APIs', () => {
    expect(offlineSupport({ isSecureContext: false })).toBe('insecure')
    expect(offlineSupport({ isSecureContext: true, navigator: {} })).toBe(
      'unsupported'
    )
    expect(
      offlineSupport({
        isSecureContext: true,
        caches: {},
        navigator: { serviceWorker: {} },
      })
    ).toBe('ok')
  })
})
