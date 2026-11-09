// Public links to one song, like Spotify's "Share → Copy link": anyone
// who opens one can listen without signing in (see
// downtify/song_link_routes.py).

/** The full address of a link the server answered with `{ path }`. */
export function songLinkUrl(link, origin = globalThis.location?.origin) {
  const path = String(link?.path || '')
  if (!path) return ''
  return `${String(origin || '').replace(/\/+$/, '')}${path}`
}

/**
 * Hands over the link `pending` resolves to: the phone's share sheet
 * when there is one, else the clipboard. Call it straight from the click:
 * the clipboard write starts at once and waits for the link, which is
 * what Safari needs to allow it after a request to the server.
 *
 * Resolves to `'shared'`, `'copied'` or `'cancelled'`; rejects when the
 * link couldn't be made (the server's error) or nothing could take it
 * (`{ url }` on the error then, to show it instead).
 */
export async function shareSongUrl(pending, { title = '', text = '' } = {}) {
  const nav = globalThis.navigator
  const coarse = globalThis.matchMedia?.('(pointer: coarse)')?.matches
  const link = Promise.resolve(pending)
  if (coarse && typeof nav?.share === 'function') {
    const url = await link
    try {
      await nav.share({ url, title, text })
      return 'shared'
    } catch (err) {
      if (err?.name === 'AbortError') return 'cancelled'
      // Refused outside a gesture: copy it instead.
    }
  }
  const Item = globalThis.ClipboardItem
  if (Item && nav?.clipboard?.write) {
    const blob = link.then((url) => new Blob([url], { type: 'text/plain' }))
    try {
      await nav.clipboard.write([new Item({ 'text/plain': blob })])
      return 'copied'
    } catch {
      // The link itself failed, or this browser wants a plain string.
    }
  }
  const url = await link
  try {
    await nav.clipboard.writeText(url)
    return 'copied'
  } catch {
    throw Object.assign(new Error('No clipboard'), { url })
  }
}
