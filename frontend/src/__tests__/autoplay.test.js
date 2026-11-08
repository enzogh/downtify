import { describe, expect, it } from 'vitest'
import { autoplaySeeds, freshSongs, seedsKey } from '../lib/autoplay'

const track = (artist, title, extra = {}) => ({ artist, title, ...extra })

describe('autoplaySeeds', () => {
  const list = [
    track('A', '1'),
    track('B', '2'),
    track('B', '3'),
    track('Pod', 'Ep', { isPodcast: true }),
    track('C', '4'),
    track('D', '5'),
  ]

  it('starts from the current track, newest first, one per artist', () => {
    expect(autoplaySeeds(list, 4).map((t) => t.title)).toEqual(['4', '3', '1'])
  })

  it('never looks past the current track', () => {
    expect(autoplaySeeds(list, 1).map((t) => t.title)).toEqual(['2', '1'])
  })

  it('skips rows it cannot seed from', () => {
    expect(
      autoplaySeeds(
        [track('', 'x'), track('Pod', 'Ep', { isPodcast: true })],
        1
      )
    ).toEqual([])
  })
})

describe('freshSongs', () => {
  it('leaves out what the queue holds and repeats, up to the limit', () => {
    const queue = [track('A', 'One')]
    const found = [
      { name: 'One', artists: ['A'] },
      { name: 'Two', artists: ['B'] },
      { name: 'Two', artists: ['B'] },
      { name: 'Three', artists: ['C'] },
    ]
    expect(freshSongs(found, queue, 1).map((s) => s.name)).toEqual(['Two'])
    expect(freshSongs(found, queue).map((s) => s.name)).toEqual([
      'Two',
      'Three',
    ])
  })
})

describe('seedsKey', () => {
  it('names the same seeds the same way', () => {
    expect(seedsKey([track('A', '1')])).toBe(
      seedsKey([{ artists: ['a'], name: '1' }])
    )
  })
})
