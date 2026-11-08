// The search page's "Top result": the one hit that best answers the query.

function norm(value) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim()
}

function songArtist(song) {
  return Array.isArray(song?.artists) && song.artists.length
    ? song.artists[0]
    : song?.artist
}

/**
 * `{ kind: 'artist' | 'album' | 'song', item }`, or `null` with no hits.
 *
 * An artist whose name is the query wins (people search for artists by
 * name), then an album whose title is, then a song whose title is, then the
 * first song - the search ranks those already.
 */
export function pickTopResult(
  query,
  { songs = [], albums = [], artists = [] }
) {
  const q = norm(query)
  if (q) {
    const artist = artists.find((item) => norm(item?.name) === q)
    if (artist) return { kind: 'artist', item: artist }
    const album = albums.find((item) => norm(item?.name) === q)
    if (album) return { kind: 'album', item: album }
    const song = songs.find(
      (item) =>
        norm(item?.name) === q ||
        norm(`${songArtist(item)} ${item?.name}`) === q ||
        norm(`${item?.name} ${songArtist(item)}`) === q
    )
    if (song) return { kind: 'song', item: song }
  }
  if (songs.length) return { kind: 'song', item: songs[0] }
  if (artists.length) return { kind: 'artist', item: artists[0] }
  if (albums.length) return { kind: 'album', item: albums[0] }
  return null
}
