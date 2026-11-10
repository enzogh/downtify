// model/offline.js against an in-memory Cache Storage and a fake server.
import { beforeEach, describe, expect, it, vi } from 'vitest'

const ORIGIN = 'https://music.example'

function memoryCaches() {
  const stores = new Map()
  const keyOf = (request) =>
    new URL(typeof request === 'string' ? request : request.url, ORIGIN).href
  return {
    stores,
    full: false,
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Map())
      const store = stores.get(name)
      const caches = this
      return {
        match: async (request) => store.get(keyOf(request))?.clone(),
        put: async (request, response) => {
          if (caches.full && !keyOf(request).includes('__castify')) {
            throw Object.assign(new Error('full'), {
              name: 'QuotaExceededError',
            })
          }
          store.set(keyOf(request), response)
        },
        delete: async (request) => store.delete(keyOf(request)),
      }
    },
    async delete(name) {
      return stores.delete(name)
    },
  }
}

const song = (name) => ({
  file: `${name}.mp3`,
  title: name,
  artist: 'Artist',
  url: `/downloads/${name}.mp3`,
  cover: `/cover?file=${name}.mp3`,
  hasCover: true,
})

const playlist = {
  kind: 'playlist',
  id: 'Road trip',
  title: 'Road trip',
  route: { name: 'Playlist', query: { name: 'Road trip' } },
}

function savedUrls(caches) {
  return [...(caches.stores.get('castify-offline-v1')?.keys() || [])]
    .filter((key) => !key.includes('__castify'))
    .sort()
}

describe('offline model', () => {
  let caches
  let offline
  let fetch

  beforeEach(async () => {
    vi.resetModules()
    caches = memoryCaches()
    fetch = vi.fn(async (url) => {
      if (String(url).includes('Broken'))
        return new Response('', { status: 404 })
      return new Response('audio', {
        status: 200,
        headers: { 'Content-Length': '1000' },
      })
    })
    globalThis.caches = caches
    globalThis.fetch = fetch
    globalThis.location = { origin: ORIGIN }
    globalThis.isSecureContext = true
    Object.defineProperty(globalThis, 'navigator', {
      configurable: true,
      value: {
        onLine: true,
        serviceWorker: {},
        storage: {
          persist: vi.fn(async () => true),
          persisted: vi.fn(async () => false),
          estimate: vi.fn(async () => ({ usage: 4000, quota: 10000 })),
        },
      },
    })
    offline = (await import('../model/offline.js')).useOffline()
  })

  it('saves every song and its cover, then lists the collection', async () => {
    await offline.save(playlist, [song('A'), song('B')])
    expect(savedUrls(caches)).toEqual([
      `${ORIGIN}/cover?file=A.mp3`,
      `${ORIGIN}/cover?file=B.mp3`,
      `${ORIGIN}/downloads/A.mp3`,
      `${ORIGIN}/downloads/B.mp3`,
    ])
    const [entry] = offline.collections.value
    expect(entry.title).toBe('Road trip')
    expect(entry.tracks.map((t) => t.title)).toEqual(['A', 'B'])
    expect(entry.size).toBe(2000)
    expect(offline.savedFiles.value.has('A.mp3')).toBe(true)
    expect(offline.usage.value).toEqual({ usage: 4000, quota: 10000 })
    expect(navigator.storage.persist).toHaveBeenCalled()
    expect(offline.jobFor('playlist', 'Road trip')).toBeNull()
  })

  it('keeps the index with the songs, for the next visit', async () => {
    await offline.save(playlist, [song('A')])
    vi.resetModules()
    const again = (await import('../model/offline.js')).useOffline()
    await again.ensureLoaded()
    expect(again.collections.value.map((c) => c.title)).toEqual(['Road trip'])
  })

  it('only fetches what is missing when it is brought up to date', async () => {
    await offline.save(playlist, [song('A')])
    fetch.mockClear()
    await offline.sync(playlist, [song('A'), song('C')])
    const asked = fetch.mock.calls.map(([url]) => url)
    expect(asked).toEqual(['/downloads/C.mp3', '/cover?file=C.mp3'])
  })

  it('reports songs it could not get and keeps the others', async () => {
    const job = await offline.save(playlist, [song('A'), song('Broken')])
    expect(job.failed).toBe(1)
    expect(offline.jobFor('playlist', 'Road trip').state).toBe('error')
    expect(offline.collections.value[0].tracks.map((t) => t.title)).toEqual([
      'A',
    ])
  })

  it('stops when the device is full', async () => {
    caches.full = true
    const job = await offline.save(playlist, [song('A'), song('B')])
    expect(job.state).toBe('full')
  })

  it('removes a collection but not the songs another one still holds', async () => {
    await offline.save(playlist, [song('A'), song('B')])
    await offline.save({ kind: 'album', id: 'x', title: 'X' }, [song('B')])
    await offline.remove('playlist', 'Road trip')
    expect(savedUrls(caches)).toEqual([
      `${ORIGIN}/cover?file=B.mp3`,
      `${ORIGIN}/downloads/B.mp3`,
    ])
    expect(offline.collections.value.map((c) => c.key)).toEqual(['album:x'])
  })

  it('removes everything at once', async () => {
    await offline.save(playlist, [song('A')])
    await offline.removeAll()
    expect(caches.stores.has('castify-offline-v1')).toBe(false)
    expect(offline.collections.value).toEqual([])
  })
})
