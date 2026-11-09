import { afterEach, describe, expect, it, vi } from 'vitest'
import { shareSongUrl, songLinkUrl } from '../lib/songLinks'

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
