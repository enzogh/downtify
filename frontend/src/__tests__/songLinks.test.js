import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  loadSongLink,
  shareSongUrl,
  shareTrack,
  songLinkUrl,
  streamSongPayload,
} from '../lib/songLinks'

function stubBrowser({ coarse = false, share, write, writeText, item } = {}) {
  vi.stubGlobal('matchMedia', () => ({ matches: coarse }))
  vi.stubGlobal('navigator', {
    share,
    clipboard: write || writeText ? { write, writeText } : undefined,
  })
  vi.stubGlobal('ClipboardItem', item)
}

afterEach(() => vi.unstubAllGlobals())

describe('songLinkUrl', () => {
  it('joins the origin and the path the server gave', () => {
    expect(songLinkUrl({ path: '/s/abc' }, 'https://music.home/')).toBe(
      'https://music.home/s/abc'
    )
    expect(songLinkUrl({}, 'https://music.home')).toBe('')
  })
})

describe('shareSongUrl', () => {
  it('opens the share sheet on a phone', async () => {
    const share = vi.fn().mockResolvedValue()
    stubBrowser({ coarse: true, share })
    await expect(
      shareSongUrl(Promise.resolve('https://x/s/a'), { title: 'Song' })
    ).resolves.toBe('shared')
    expect(share).toHaveBeenCalledWith({
      url: 'https://x/s/a',
      title: 'Song',
      text: '',
    })
  })

  it('says so when the share sheet is closed', async () => {
    const share = vi.fn().mockRejectedValue({ name: 'AbortError' })
    stubBrowser({ coarse: true, share })
    await expect(shareSongUrl('https://x/s/a')).resolves.toBe('cancelled')
  })

  it('starts the clipboard write before the link arrives', async () => {
    let resolveLink
    const link = new Promise((resolve) => (resolveLink = resolve))
    const write = vi.fn().mockResolvedValue()
    class Item {
      constructor(data) {
        this.data = data
      }
    }
    stubBrowser({ write, item: Item })
    const done = shareSongUrl(link)
    await Promise.resolve()
    expect(write).toHaveBeenCalledTimes(1)
    resolveLink('https://x/s/b')
    await expect(done).resolves.toBe('copied')
    const blob = await write.mock.calls[0][0][0].data['text/plain']
    expect(await blob.text()).toBe('https://x/s/b')
  })

  it('falls back to a plain copy', async () => {
    const writeText = vi.fn().mockResolvedValue()
    stubBrowser({ writeText })
    await expect(shareSongUrl('https://x/s/c')).resolves.toBe('copied')
    expect(writeText).toHaveBeenCalledWith('https://x/s/c')
  })

  it('hands back the link when nothing can take it', async () => {
    stubBrowser({})
    await expect(shareSongUrl('https://x/s/d')).rejects.toMatchObject({
      url: 'https://x/s/d',
    })
  })

  it('passes on the server refusing to make the link', async () => {
    stubBrowser({ writeText: vi.fn() })
    const refused = Promise.reject({ response: { status: 403 } })
    await expect(shareSongUrl(refused)).rejects.toMatchObject({
      response: { status: 403 },
    })
  })
})

describe('loadSongLink', () => {
  it('reads what the page shows', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ title: 'Song' }),
    })
    await expect(loadSongLink('AbCdEf123456', fetcher)).resolves.toEqual({
      title: 'Song',
    })
    expect(fetcher).toHaveBeenCalledWith('/s/AbCdEf123456/info', {
      credentials: 'omit',
    })
  })

  it('is null for a link that does not play or a malformed token', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false })
    await expect(loadSongLink('AbCdEf123456', fetcher)).resolves.toBeNull()
    await expect(loadSongLink('../api', fetcher)).resolves.toBeNull()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})

describe('shareTrack', () => {
  it('shapes the info like a player track', () => {
    expect(
      shareTrack({
        title: 'T',
        artist: 'A',
        duration: 12,
        has_cover: true,
        cover_url: '/s/x/cover',
      })
    ).toMatchObject({ title: 'T', hasCover: true, cover: '/s/x/cover' })
    expect(shareTrack(null).hasCover).toBe(false)
  })
})

describe('streamSongPayload', () => {
  it('describes a search row with the video to stream', () => {
    expect(
      streamSongPayload(
        {
          name: 'Teardrop',
          artists: ['Massive Attack', 'Liz Fraser'],
          album_name: 'Mezzanine',
          duration: 330,
          cover_url: 'https://img/x.jpg',
          explicit: false,
        },
        'abcdefghijk'
      )
    ).toEqual({
      video_id: 'abcdefghijk',
      title: 'Teardrop',
      artist: 'Massive Attack, Liz Fraser',
      album: 'Mezzanine',
      duration: 330,
      cover_url: 'https://img/x.jpg',
      explicit: false,
    })
  })
})
