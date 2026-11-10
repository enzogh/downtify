// public/sw.js run against an in-memory Cache Storage: saved songs are
// served in the byte ranges an <audio> element asks for, offline covers
// and the app's own page come from the cache, the rest goes to the server.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const SOURCE = readFileSync(
  fileURLToPath(new URL('../../public/sw.js', import.meta.url)),
  'utf8'
)
const ORIGIN = 'https://music.example'

function memoryCaches() {
  const stores = new Map()
  const keyOf = (request) =>
    typeof request === 'string'
      ? new URL(request, ORIGIN).href
      : new URL(request.url, ORIGIN).href
  const open = async (name) => {
    if (!stores.has(name)) stores.set(name, new Map())
    const store = stores.get(name)
    return {
      match: async (request) => store.get(keyOf(request))?.clone(),
      put: async (request, response) => {
        store.set(keyOf(request), response)
      },
      delete: async (request) => store.delete(keyOf(request)),
    }
  }
  return {
    stores,
    open,
    delete: async (name) => stores.delete(name),
    match: async (request) => {
      for (const store of stores.values()) {
        const hit = store.get(keyOf(request))
        if (hit) return hit.clone()
      }
      return undefined
    },
  }
}

function startWorker() {
  const listeners = {}
  const self = {
    location: { origin: ORIGIN },
    clients: { claim: () => Promise.resolve() },
    skipWaiting: () => {},
    addEventListener: (name, fn) => {
      listeners[name] = fn
    },
  }
  const caches = memoryCaches()
  const fetch = vi.fn(async () => new Response('from server'))
  new Function('self', 'caches', 'fetch', SOURCE)(self, caches, fetch)
  /** What the worker answers for `request` (null: left to the browser). */
  const handle = async (url, init = {}) => {
    const request = new Request(new URL(url, ORIGIN), init)
    let answer = null
    listeners.fetch({
      request: Object.defineProperty(request, 'mode', {
        value: init.navigate ? 'navigate' : 'no-cors',
      }),
      respondWith: (promise) => {
        answer = promise
      },
    })
    return answer ? await answer : null
  }
  return { caches, fetch, handle, listeners }
}

async function saveSong(caches, path, bytes) {
  const store = await caches.open('castify-offline-v1')
  await store.put(
    `${ORIGIN}${path}`,
    new Response(new Uint8Array(bytes), {
      headers: { 'Content-Type': 'audio/mpeg' },
    })
  )
}

describe('service worker', () => {
  let worker

  beforeEach(() => {
    worker = startWorker()
  })

  it('serves a saved song whole, saying it takes ranges', async () => {
    await saveSong(worker.caches, '/downloads/A.mp3', [1, 2, 3, 4, 5])
    const response = await worker.handle('/downloads/A.mp3')
    expect(response.status).toBe(200)
    expect(response.headers.get('accept-ranges')).toBe('bytes')
    expect(response.headers.get('content-type')).toBe('audio/mpeg')
    expect([...new Uint8Array(await response.arrayBuffer())]).toEqual([
      1, 2, 3, 4, 5,
    ])
    expect(worker.fetch).not.toHaveBeenCalled()
  })

  it.each([
    ['bytes=1-3', '1-3/6', [1, 2, 3]],
    ['bytes=4-', '4-5/6', [4, 5]],
    ['bytes=-2', '4-5/6', [4, 5]],
    ['bytes=2-100', '2-5/6', [2, 3, 4, 5]],
  ])('answers %s with the bytes asked for', async (range, said, bytes) => {
    await saveSong(worker.caches, '/downloads/A.mp3', [0, 1, 2, 3, 4, 5])
    const response = await worker.handle('/downloads/A.mp3?x=1', {
      headers: { Range: range },
    })
    expect(response.status).toBe(206)
    expect(response.headers.get('content-range')).toBe(`bytes ${said}`)
    expect(response.headers.get('content-length')).toBe(String(bytes.length))
    expect([...new Uint8Array(await response.arrayBuffer())]).toEqual(bytes)
  })

  it('refuses a range past the end', async () => {
    await saveSong(worker.caches, '/downloads/A.mp3', [0, 1])
    const response = await worker.handle('/downloads/A.mp3', {
      headers: { Range: 'bytes=9-' },
    })
    expect(response.status).toBe(416)
    expect(response.headers.get('content-range')).toBe('bytes */2')
  })

  it('leaves songs that were not saved to the server', async () => {
    const response = await worker.handle('/downloads/B.mp3')
    expect(await response.text()).toBe('from server')
  })

  it('leaves the API alone', async () => {
    expect(await worker.handle('/api/server/info')).toBeNull()
    expect(
      await worker.handle('/api/download/url', { method: 'POST', body: '{}' })
    ).toBeNull()
  })

  it('serves a saved cover, whatever size is asked, once offline', async () => {
    const store = await worker.caches.open('castify-offline-v1')
    await store.put(
      `${ORIGIN}/cover?file=${encodeURIComponent('Dir/A.mp3')}`,
      new Response('cover')
    )
    worker.fetch.mockRejectedValue(new TypeError('offline'))
    const response = await worker.handle(
      `/cover?file=${encodeURIComponent('Dir/A.mp3')}&size=300`
    )
    expect(await response.text()).toBe('cover')
  })

  it('keeps the page online and opens it from the cache offline', async () => {
    worker.fetch.mockResolvedValueOnce(
      new Response('<html>v1</html>', {
        headers: { 'Content-Type': 'text/html' },
      })
    )
    const online = await worker.handle('/library/playlists', { navigate: true })
    expect(await online.text()).toBe('<html>v1</html>')
    worker.fetch.mockRejectedValue(new TypeError('offline'))
    const offline = await worker.handle('/library/offline', { navigate: true })
    expect(await offline.text()).toBe('<html>v1</html>')
  })

  it('keeps two versions of the app and deletes older ones', async () => {
    for (const version of ['v1', 'v2', 'v3']) {
      worker.fetch.mockResolvedValueOnce(
        new Response(`<html>${version}</html>`, {
          headers: { 'Content-Type': 'text/html' },
        })
      )
      await worker.handle('/', { navigate: true })
    }
    const shells = [...worker.caches.stores.keys()].filter((name) =>
      name.startsWith('castify-shell-')
    )
    expect(shells).toHaveLength(2)
  })
})
