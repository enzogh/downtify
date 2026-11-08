import { beforeEach, describe, expect, it } from 'vitest'
import {
  RECOMMENDATION_TTL_MS,
  cachedRecommendations,
  resetRecommendationCache,
  saveRecommendations,
  seedSignature,
} from '../lib/recommendationCache'
import { interleave } from '../lib/recommendations'

function memoryStorage() {
  const data = {}
  return {
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => {
      data[key] = String(value)
    },
    removeItem: (key) => delete data[key],
  }
}

describe('recommendation cache', () => {
  beforeEach(() => {
    globalThis.localStorage = memoryStorage()
    resetRecommendationCache()
  })

  const seeds = [{ file: 'a.mp3' }, { file: 'b.mp3' }]
  const songs = [{ name: 'X', artists: ['Y'] }]

  it('serves what was saved for the same newest songs', () => {
    const signature = seedSignature(seeds)
    saveRecommendations('Road trip', { signature, round: 2, songs }, 1000)
    const hit = cachedRecommendations('Road trip', signature, 2000)
    expect(hit.songs).toEqual(songs)
    expect(hit.round).toBe(2)
  })

  it('survives a reload (read back from storage)', () => {
    const signature = seedSignature(seeds)
    saveRecommendations('Road trip', { signature, songs }, 1000)
    resetRecommendationCache()
    expect(cachedRecommendations('Road trip', signature, 1000)?.songs).toEqual(
      songs
    )
  })

  it('misses once a song was added or a day went by', () => {
    const signature = seedSignature(seeds)
    saveRecommendations('Road trip', { signature, songs }, 0)
    const added = seedSignature([{ file: 'c.mp3' }, ...seeds])
    expect(cachedRecommendations('Road trip', added, 1)).toBeNull()
    expect(
      cachedRecommendations('Road trip', signature, RECOMMENDATION_TTL_MS)
    ).toBeNull()
    expect(cachedRecommendations('Other', signature, 1)).toBeNull()
  })

  it('keeps the 30 most recent playlists', () => {
    for (let i = 0; i < 35; i += 1) {
      saveRecommendations(`p${i}`, { signature: 's', songs }, i)
    }
    expect(cachedRecommendations('p0', 's', 40)).toBeNull()
    expect(cachedRecommendations('p34', 's', 40)).not.toBeNull()
  })
})

describe('interleave', () => {
  it('takes from each mix in turn without repeats', () => {
    const a = [
      { name: '1', artist: 'A' },
      { name: '2', artist: 'A' },
    ]
    const b = [
      { name: '1', artist: 'A' },
      { name: '3', artist: 'B' },
    ]
    expect(interleave([a, b]).map((song) => song.name)).toEqual(['1', '2', '3'])
  })
})
