import { describe, expect, it } from 'vitest'
import {
  artistAversion,
  diversify,
  pickSeeds,
  rankCandidates,
  songKey,
  tasteProfile,
} from '../lib/recommender'
import { closePlay, wasSkipped } from '../lib/playHistory'

const DAY = 24 * 60 * 60 * 1000
const NOW = 1_800_000_000_000

function play(
  artist,
  title,
  { daysAgo = 1, skipped = false, played = 200 } = {}
) {
  return {
    play_id: `${artist}-${title}-${daysAgo}-${Math.random()}`,
    played_at: NOW - daysAgo * DAY,
    artist,
    title,
    played_s: skipped ? 10 : played,
    duration_s: 200,
    skipped,
  }
}

function times(n, fn) {
  return Array.from({ length: n }, (_, i) => fn(i))
}

const row = (artist, name) => ({ name, artists: [artist] })

describe('songKey', () => {
  it('ignores case, accents and version marks', () => {
    expect(songKey('Favé', 'Flashé (feat. X)')).toBe(songKey('FAVE', 'flashe'))
    expect(songKey('A', 'Song - Official Video')).toBe(songKey('a', 'song'))
    expect(songKey('A', 'Song (Remastered 2011)')).toBe(songKey('a', 'song'))
  })
})

describe('closePlay / wasSkipped', () => {
  const track = { artist: 'A', title: 'S', file: 'a.mp3', duration: 200 }

  it('drops mis-taps and keeps skips and full plays', () => {
    expect(
      closePlay({
        track,
        played: 2,
        position: 2,
        duration: 200,
        playId: 'x',
        startedAt: 1,
      })
    ).toBeNull()
    const skip = closePlay({
      track,
      played: 12,
      position: 12,
      duration: 200,
      playId: 'x',
      startedAt: 1,
    })
    expect(skip.skipped).toBe(true)
    expect(skip.source).toBe('library')
    const full = closePlay({
      track,
      played: 195,
      position: 196,
      duration: 200,
      playId: 'y',
      startedAt: 1,
    })
    expect(full.skipped).toBe(false)
    const stream = closePlay({
      track: { ...track, file: '', stream: true, video_id: 'v' },
      played: 70,
      position: 70,
      duration: 200,
      playId: 'z',
      startedAt: 1,
    })
    expect(stream.source).toBe('stream')
    expect(stream.skipped).toBe(false)
  })

  it('a short song played through is not a skip', () => {
    expect(wasSkipped(28, 29, 30)).toBe(false)
    expect(wasSkipped(20, 20, 300)).toBe(true)
    expect(wasSkipped(61, 61, 400)).toBe(false)
  })
})

describe('tasteProfile', () => {
  it('weighs plays, skips and recency', () => {
    const profile = tasteProfile({
      plays: [
        ...times(5, () => play('Loved', 'Hit')),
        ...times(5, () => play('Old', 'Hit', { daysAgo: 200 })),
        ...times(3, () => play('Meh', 'Bad', { skipped: true })),
      ],
      now: NOW,
    })
    const loved = profile.songs.get(songKey('Loved', 'Hit'))
    const old = profile.songs.get(songKey('Old', 'Hit'))
    const bad = profile.songs.get(songKey('Meh', 'Bad'))
    expect(loved.score).toBeGreaterThan(old.score)
    expect(bad.score).toBeLessThan(0)
    expect(profile.skipped.has(songKey('Meh', 'Bad'))).toBe(true)
    expect(profile.heard.has(songKey('Loved', 'Hit'))).toBe(true)
    expect(profile.known.has('loved')).toBe(true)
    expect(profile.known.has('meh')).toBe(false)
    expect(artistAversion(profile.artists.get('meh'))).toBe(1)
  })

  it('starts from the library and likes when there is no history', () => {
    const profile = tasteProfile({
      tracks: [
        { file: 'a', artist: 'A', title: 'One', added: (NOW - DAY) / 1000 },
        { file: 'b', artist: 'B', title: 'Two' },
      ],
      liked: new Set(['b']),
      now: NOW,
    })
    expect(profile.coldStart).toBe(true)
    expect(profile.library.has(songKey('A', 'One'))).toBe(true)
    const seeds = pickSeeds(profile, { now: NOW, count: 2 })
    expect(seeds.map((seed) => seed.artist).sort()).toEqual(['A', 'B'])
  })
})

describe('pickSeeds', () => {
  const plays = [
    ...times(10, () => play('Top', 'One')),
    ...times(8, () => play('Top', 'Two')),
    ...times(7, () => play('Top', 'Three')),
    ...times(6, () => play('Second', 'One')),
    ...times(2, () => play('Fresh', 'New', { daysAgo: 0.5 })),
    ...times(20, (i) => play(`Deep ${i}`, 'Cut', { daysAgo: 20 })),
    ...times(4, () => play('Skipped', 'Song', { skipped: true })),
  ]
  const profile = tasteProfile({ plays, now: NOW })

  it('mixes rotation, recent and deeper picks, two per artist at most', () => {
    const seeds = pickSeeds(profile, { now: NOW, count: 8 })
    expect(seeds).toHaveLength(8)
    expect(
      seeds.filter((seed) => seed.artist === 'Top').length
    ).toBeLessThanOrEqual(2)
    expect(seeds[0].artist).toBe('Top')
    expect(seeds.some((seed) => seed.artist === 'Fresh')).toBe(true)
    expect(seeds.some((seed) => seed.why === 'explore')).toBe(true)
    expect(seeds.some((seed) => seed.artist === 'Skipped')).toBe(false)
  })

  it('draws the same seeds all day and others another day', () => {
    const a = pickSeeds(profile, { now: NOW, count: 8 })
    const b = pickSeeds(profile, { now: NOW + 1000, count: 8 })
    expect(a).toEqual(b)
    const days = new Set(
      times(6, (i) =>
        pickSeeds(profile, { now: NOW + i * DAY, count: 8 })
          .filter((seed) => seed.why === 'explore')
          .map((seed) => seed.artist)
          .join()
      )
    )
    expect(days.size).toBeGreaterThan(1)
  })
})

describe('rankCandidates', () => {
  const profile = tasteProfile({
    plays: [
      ...times(6, () => play('Seed', 'A')),
      ...times(6, () => play('Other', 'B')),
      ...times(3, () => play('Known', 'Old')),
      ...times(3, () => play('Hated', 'X', { skipped: true })),
      ...times(2, () => play('Streamed', 'Loop')),
    ],
    tracks: [{ file: 'have.mp3', artist: 'Have', title: 'It' }],
    now: NOW,
  })
  const seeds = [
    { key: songKey('Seed', 'A'), artist: 'Seed', title: 'A', weight: 1 },
    { key: songKey('Other', 'B'), artist: 'Other', title: 'B', weight: 1 },
  ]
  const radios = [
    {
      seed: seeds[0],
      rows: [
        row('Seed', 'A'),
        row('Shared', 'Both'),
        row('Lonely', 'One'),
        row('Have', 'It'),
        row('Hated', 'Y'),
        row('Known', 'New one'),
        row('Streamed', 'Loop'),
        row('Blocked', 'Z'),
      ],
    },
    { seed: seeds[1], rows: [row('Late', 'Pick'), row('Shared', 'Both')] },
  ]

  it('discover: new artists, co-found songs first, nothing one has', () => {
    const out = rankCandidates(profile, radios, {
      mode: 'discover',
      blocked: new Set(['blocked']),
      now: NOW,
    })
    const names = out.map((item) => item.song.name)
    expect(names[0]).toBe('Both')
    expect(out[0].support).toBe(2)
    expect(names).not.toContain('A')
    expect(names).not.toContain('It')
    expect(names).not.toContain('Y')
    expect(names).not.toContain('Z')
    // Played through lately: not a discovery.
    expect(names).not.toContain('Loop')
    // A known artist comes after the new ones.
    expect(names.indexOf('New one')).toBeGreaterThan(names.indexOf('One'))
    expect(out.find((item) => item.song.name === 'One').because).toBe('Seed')
    expect(out.find((item) => item.song.name === 'One').kind).toBe('new')
  })

  it('for you: keeps the songs one streams again and again', () => {
    const out = rankCandidates(profile, radios, { mode: 'foryou', now: NOW })
    const loop = out.find((item) => item.song.name === 'Loop')
    expect(loop.kind).toBe('again')
  })

  it('steps aside for songs dismissed or shown for days', () => {
    const dismissed = new Set([songKey('Shared', 'Both')])
    const out = rankCandidates(profile, radios, { now: NOW, dismissed })
    expect(out.map((item) => item.song.name)).not.toContain('Both')
    const tired = rankCandidates(profile, radios, {
      now: NOW,
      shown: { [songKey('Lonely', 'One')]: 6 },
    })
    const fresh = rankCandidates(profile, radios, { now: NOW })
    const at = (list) => list.findIndex((item) => item.song.name === 'One')
    expect(at(tired)).toBeGreaterThanOrEqual(at(fresh))
  })
})

describe('diversify', () => {
  it('caps an artist and never plays it twice in a row', () => {
    const items = times(10, (i) => ({
      artists: [i < 6 ? 'a' : `b${i}`],
      score: 10 - i,
      because: 's',
      song: { name: String(i) },
    }))
    const out = diversify(items, { size: 10, perArtist: 2 })
    expect(out.filter((item) => item.artists[0] === 'a')).toHaveLength(2)
    for (let i = 1; i < out.length; i += 1) {
      expect(out[i].artists[0]).not.toBe(out[i - 1].artists[0])
    }
  })
})

describe('failureReasonKey', async () => {
  const { failureReasonKey } = await import('../lib/failureReason')
  it('says common download errors plainly', () => {
    expect(failureReasonKey('ERROR: Postprocessing: Conversion failed!')).toBe(
      'queue.reason.conversion'
    )
    expect(failureReasonKey("Sign in to confirm you're not a bot")).toBe(
      'queue.reason.blocked'
    )
    expect(failureReasonKey('Video unavailable')).toBe(
      'queue.reason.unavailable'
    )
    expect(failureReasonKey('something odd')).toBe('')
  })
})
