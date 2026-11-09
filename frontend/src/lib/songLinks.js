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

/** What a link's page shows (`GET /s/<token>/info`), or `null` when the
 * link doesn't play (unknown, revoked, or its song is gone). */
export async function loadSongLink(token, fetcher = globalThis.fetch) {
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(String(token || ''))) return null
  try {
    const res = await fetcher(`/s/${encodeURIComponent(token)}/info`, {
      credentials: 'omit',
    })
    if (!res.ok) return null
    const data = await res.json()
    return data && typeof data === 'object' ? data : null
  } catch {
    return null
  }
}

/** A link's info shaped like a player track (CoverArt, the palette). */
export function shareTrack(info) {
  return {
    title: String(info?.title || ''),
    artist: String(info?.artist || ''),
    album: String(info?.album || ''),
    duration: Number(info?.duration) || 0,
    explicit: Boolean(info?.explicit),
    hasCover: Boolean(info?.has_cover && info?.cover_url),
    cover: String(info?.cover_url || ''),
  }
}

/**
 * The `{ song }` body for a song that isn't downloaded, once `videoId`
 * (the YouTube video the player would stream) is known.
 */
export function streamSongPayload(song, videoId) {
  const artists = Array.isArray(song?.artists) ? song.artists : []
  return {
    video_id: videoId,
    title: String(song?.name || song?.title || ''),
    artist: artists.filter(Boolean).join(', ') || String(song?.artist || ''),
    album: String(song?.album_name || song?.album || ''),
    duration: Number(song?.duration) || 0,
    cover_url: String(song?.cover_url || song?.cover || ''),
    explicit: song?.explicit === true,
  }
}
