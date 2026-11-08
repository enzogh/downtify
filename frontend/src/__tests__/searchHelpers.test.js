import { describe, expect, it } from 'vitest'
import { pickTopResult } from '../lib/topResult'
import { pickSeeds, recommendationKey } from '../lib/recommendations'
import { clampFade, fadeGain } from '../lib/fade'
import { DRAG_TYPE, readDragSongs, setDragSongs } from '../lib/dragSongs'

describe('pickTopResult', () => {
  const songs = [
    { name: 'Halo', artists: ['Beyoncé'] },
    { name: 'Single Ladies', artists: ['Beyoncé'] },
  ]
  const artists = [{ name: 'Beyoncé' }]
  const albums = [{ name: 'Lemonade', artist: 'Beyoncé' }]

  it('picks the artist the query names, accents aside', () => {
    expect(pickTopResult('beyonce', { songs, artists, albums })).toEqual({
      kind: 'artist',
      item: artists[0],
    })
  })

  it('picks an album or a song the query names', () => {
    expect(pickTopResult('Lemonade', { songs, artists, albums }).kind).toBe(
      'album'
    )
    expect(
      pickTopResult('single ladies', { songs, artists, albums }).item
    ).toBe(songs[1])
  })

  it('falls back to the first song, and to nothing', () => {
    expect(pickTopResult('xyz', { songs, artists, albums }).item).toBe(songs[0])
    expect(pickTopResult('xyz', {})).toBeNull()
  })
})

describe('recommendations', () => {
  it('keys search rows and library tracks alike', () => {
    expect(recommendationKey({ artists: ['A '], name: 'Song' })).toBe(
      recommendationKey({ artist: 'a', title: 'song' })
    )
  })

  it('seeds from different artists, newest first, rotating', () => {
    const tracks = [
      { artist: 'A', title: '1' },
      { artist: 'B', title: '2' },
      { artist: 'B', title: '3' },
      { artist: 'C', title: '4' },
    ]
    expect(pickSeeds(tracks, 2).map((t) => t.title)).toEqual(['4', '3'])
    expect(pickSeeds(tracks, 2, 1).map((t) => t.title)).toEqual(['2', '1'])
    expect(pickSeeds([], 2)).toEqual([])
  })
})

describe('fade', () => {
  it('clamps the setting', () => {
    expect(clampFade('5')).toBe(5)
    expect(clampFade(99)).toBe(12)
    expect(clampFade('x')).toBe(0)
  })

  it('ramps in and out', () => {
    const both = { fadeIn: true, fadeOut: true }
    expect(fadeGain(0, 200, 4, both)).toBe(0)
    expect(fadeGain(2, 200, 4, both)).toBe(0.5)
    expect(fadeGain(100, 200, 4, both)).toBe(1)
    expect(fadeGain(199, 200, 4, both)).toBe(0.25)
    expect(fadeGain(0, 200, 4, { fadeIn: false, fadeOut: true })).toBe(1)
  })

  it('leaves short tracks and a zero fade alone', () => {
    const both = { fadeIn: true, fadeOut: true }
    expect(fadeGain(1, 6, 4, both)).toBe(1)
    expect(fadeGain(0, 200, 0, both)).toBe(1)
  })
})

describe('dragSongs', () => {
  function transfer() {
    const data = {}
    return {
      data,
      types: [],
      setData(type, value) {
        data[type] = value
        this.types.push(type)
      },
      getData: (type) => data[type] || '',
    }
  }

  it('round-trips files and songs', () => {
    const dataTransfer = transfer()
    setDragSongs({ dataTransfer }, { files: ['a.mp3'], songs: [{ name: 'B' }] })
    expect(dataTransfer.types).toContain(DRAG_TYPE)
    expect(readDragSongs({ dataTransfer })).toEqual({
      files: ['a.mp3'],
      songs: [{ name: 'B' }],
    })
  })

  it('ignores drops that carry no songs', () => {
    expect(readDragSongs({ dataTransfer: transfer() })).toBeNull()
  })
})
