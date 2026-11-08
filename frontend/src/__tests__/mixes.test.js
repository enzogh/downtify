import { describe, expect, it } from 'vitest'
import { buildMixes, onRepeat, recentPlayCounts } from '../lib/mixes'

const DAY = 24 * 60 * 60 * 1000
const NOW = 1_800_000_000_000

function track(artist, n) {
  return {
    file: `${artist}/${n}.mp3`,
    artist,
    albumArtist: artist,
    title: `${artist} ${n}`,
    hasCover: true,
    cover: `/cover/${artist}.jpg`,
  }
}

const library = [
  ...[1, 2, 3, 4, 5, 6].map((n) => track('Alpha', n)),
  ...[1, 2, 3, 4].map((n) => track('Beta', n)),
  ...[1, 2, 3].map((n) => track('Gamma', n)),
  track('Solo', 1),
]

describe('recentPlayCounts', () => {
  it('counts only the last month', () => {
    const counts = recentPlayCounts(
      [
        { file: 'a', at: NOW - DAY },
        { file: 'a', at: NOW - 40 * DAY },
        { file: 'b', at: NOW },
      ],
      NOW
    )
    expect(counts).toEqual({ a: 1, b: 1 })
  })
})

describe('buildMixes', () => {
  it('needs a library big enough to mix', () => {
    expect(buildMixes(library.slice(0, 5), { now: NOW })).toEqual([])
  })

  it('leads with the artist played most', () => {
    const plays = [1, 2, 3].map(() => ({ file: 'Gamma/1.mp3', at: NOW }))
    const mixes = buildMixes(library, { plays, now: NOW })
    expect(mixes[0].artist).toBe('Gamma')
    // An artist with fewer than three songs never leads a mix.
    expect(mixes.map((mix) => mix.artist)).not.toContain('Solo')
  })

  it('without a radio mix, keeps to the lead artist', () => {
    const [mix] = buildMixes(library, { now: NOW, size: 10 })
    expect(new Set(mix.items.map((item) => item.track.artist))).toEqual(
      new Set([mix.artist])
    )
  })

  it('adds songs by the radio mix artists you have, then its own songs', () => {
    const plays = [1, 2, 3].map(() => ({ file: 'Alpha/1.mp3', at: NOW }))
    const radio = [
      { name: 'Beta 1', artists: ['Beta'] },
      { name: 'Elsewhere', artists: ['Delta'], cover_url: '/d.jpg' },
    ]
    const [mix] = buildMixes(library, {
      plays,
      now: NOW,
      count: 1,
      size: 12,
      similar: { alpha: radio },
    })
    expect(mix.artist).toBe('Alpha')
    const artists = mix.items.map((item) =>
      item.track ? item.track.artist : item.song.artists[0]
    )
    expect(artists).toContain('Beta')
    expect(artists).toContain('Delta')
    // Gamma isn't in Alpha's radio mix: it stays out.
    expect(artists).not.toContain('Gamma')
    // Beta 1 is in the library: it comes once, as the library track.
    const betaOne = mix.items.filter(
      (item) => (item.track?.title || item.song?.name) === 'Beta 1'
    )
    expect(betaOne).toHaveLength(1)
    expect(betaOne[0].track).toBeTruthy()
  })

  it('keeps the same order all day and changes it the next', () => {
    const order = (now) =>
      buildMixes(library, { now })[0].items.map((item) => item.track.file)
    expect(order(NOW)).toEqual(order(NOW + 1000))
    const days = [1, 2, 3, 4, 5].map((d) => order(NOW + d * DAY).join())
    expect(new Set(days).size).toBeGreaterThan(1)
  })
})

describe('onRepeat', () => {
  it('lists the songs played often lately, most first', () => {
    const plays = [
      ...[1, 2, 3, 4].map(() => ({ file: 'Beta/2.mp3', at: NOW })),
      ...[1, 2, 3].map(() => ({ file: 'Alpha/1.mp3', at: NOW })),
      { file: 'Gamma/1.mp3', at: NOW },
    ]
    expect(onRepeat(library, plays, { now: NOW }).map((t) => t.file)).toEqual([
      'Beta/2.mp3',
      'Alpha/1.mp3',
    ])
  })
})
