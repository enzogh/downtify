// The recommendation engine: what to suggest, from what someone actually
// listens to. Pure (no Vue, no API), so every rule here is testable;
// model/recommendations.js feeds it and asks YouTube Music for the radio
// mixes of the seeds it picks.
//
// 1. tasteProfile: every play of the account's history (model/
//    playHistory.js) weighs on its song and artist - played through counts
//    most, a skip counts against, and older plays fade (half-life of a
//    month). Likes and the library add a little, and carry the profile on
//    their own for someone with no history yet (cold start).
// 2. pickSeeds: the songs to start from - what is on heavy rotation, what
//    was played these last days, and a few deeper picks that change every
//    day - never more than two of one artist.
// 3. rankCandidates: each seed's radio mix votes for its songs, earlier
//    places weighing more and a song found by several seeds weighing much
//    more (it fits the taste, not one song). Then it is shaped for its use:
//    "discover" wants artists one has never heard, "for you" leans on the
//    artists one loves; songs one skipped, dismissed, has on the server or
//    has kept seeing without playing fall away. Last, a diversity pass
//    keeps one artist or one seed from filling the list.

const DAY_MS = 24 * 60 * 60 * 1000
/** A play loses half its weight in this many days. */
export const HALF_LIFE_DAYS = 30

/** One key for an artist (case, accents and punctuation aside). */
export function artistKey(name) {
  return String(name || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim()
}

/** One key for a song: its first artist and its title, versions aside. */
export function songKey(artist, title) {
  const cleanTitle = String(title || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(
      /\s*[([][^)\]]*\b(feat|ft|with|remaster(ed)?|version|edit|official|audio|video|lyrics?)\b[^)\]]*[)\]]/g,
      ''
    )
    .replace(/\s+-\s+(official|audio|video|lyrics?).*$/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .trim()
  return `${artistKey(artist)}|${cleanTitle}`
}

/** The artists of a search row (YouTube Music), lead first. */
export function rowArtists(row) {
  if (Array.isArray(row?.artists) && row.artists.length) {
    return row.artists.map(String).filter(Boolean)
  }
  return row?.artist ? [String(row.artist)] : []
}

function rowTitle(row) {
  return String(row?.name || row?.title || '')
}

/** The key of a search row or a library track. */
export function keyOfRow(row) {
  return songKey(rowArtists(row)[0], rowTitle(row))
}

function decay(ageMs, halfLifeDays = HALF_LIFE_DAYS) {
  const days = Math.max(0, ageMs) / DAY_MS
  return 0.5 ** (days / halfLifeDays)
}

/** A small seeded PRNG: the same picks all day, others tomorrow. */
export function seededRandom(seedText) {
  let h = 2166136261
  for (const ch of String(seedText)) {
    h ^= ch.charCodeAt(0)
    h = Math.imul(h, 16777619)
  }
  return () => {
    h += 0x6d2b79f5
    let x = h
    x = Math.imul(x ^ (x >>> 15), x | 1)
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61)
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296
  }
}

function playTime(play) {
  if (typeof play?.played_at === 'number') return play.played_at
  const ms = Date.parse(play?.played_at || '')
  return Number.isFinite(ms) ? ms : 0
}

function completed(play) {
  const length = Number(play.duration_s) || 0
  const played = Number(play.played_s) || 0
  return !play.skipped && (length <= 0 || played >= length * 0.8)
}

/**
 * Someone's taste, from their `plays` (history rows), the library
 * `tracks`, the `liked` files and the time `now`:
 *
 * - `songs`: songKey → { artist, title, file, score, plays, skips,
 *   completes, lastAt };
 * - `artists`: artistKey → { name, score, plays, skips, library };
 * - `heard`: keys of songs played through at least once, `skipped`: keys
 *   of songs mostly skipped;
 * - `known`: artist keys one has heard or has songs of;
 * - `library`: song keys on the server;
 * - `coldStart`: too few real plays to go by - the library speaks instead.
 */
export function tasteProfile({
  plays = [],
  tracks = [],
  liked = new Set(),
  now = Date.now(),
} = {}) {
  const songs = new Map()
  const artists = new Map()
  const library = new Set()
  let listened = 0

  function artistOf(name) {
    const key = artistKey(name)
    if (!key) return null
    if (!artists.has(key)) {
      artists.set(key, {
        key,
        name: String(name),
        score: 0,
        plays: 0,
        skips: 0,
        library: 0,
      })
    }
    return artists.get(key)
  }

  function songOf(artist, title, file = '') {
    const key = songKey(artist, title)
    if (!songs.has(key)) {
      songs.set(key, {
        key,
        artist: String(artist),
        title: String(title),
        file,
        positive: 0,
        negative: 0,
        score: 0,
        plays: 0,
        skips: 0,
        completes: 0,
        lastAt: 0,
      })
    }
    const song = songs.get(key)
    if (file && !song.file) song.file = file
    return song
  }

  for (const play of plays || []) {
    if (!play?.artist || !play?.title) continue
    const at = playTime(play)
    const weight = decay(now - at)
    const song = songOf(play.artist, play.title, play.file || '')
    const artist = artistOf(play.artist)
    song.plays += 1
    artist.plays += 1
    song.lastAt = Math.max(song.lastAt, at)
    if (play.skipped) {
      song.skips += 1
      artist.skips += 1
      song.negative += 0.7 * weight
    } else {
      listened += 1
      if (completed(play)) {
        song.completes += 1
        song.positive += weight
      } else {
        song.positive += 0.6 * weight
      }
    }
  }

  const DAYS_30 = 30 * DAY_MS
  for (const track of tracks || []) {
    const name = track?.albumArtist || track?.artist
    if (!name || !track?.title) continue
    const key = songKey(track.artist || name, track.title)
    library.add(key)
    library.add(songKey(name, track.title))
    const artist = artistOf(name)
    artist.library += 1
    const song = songOf(track.artist || name, track.title, track.file)
    // The library is a quiet vote; a fresh addition and a like say more.
    song.positive += 0.05
    if (track.added) {
      const addedMs = track.added > 1e12 ? track.added : track.added * 1000
      if (now - addedMs < DAYS_30)
        song.positive += 0.4 * decay(now - addedMs, 14)
    }
    if (track.file && liked.has(track.file)) song.positive += 1.5
  }

  const heard = new Set()
  const skipped = new Set()
  for (const song of songs.values()) {
    // Played over and over still counts, but less and less: one song on
    // loop mustn't be the whole taste.
    song.score = Math.log1p(song.positive) * 2 - song.negative
    if (song.completes > 0) heard.add(song.key)
    if (song.skips >= 2 && song.skips > song.completes * 2)
      skipped.add(song.key)
    if (song.skips >= 1 && song.completes === 0 && song.plays === song.skips) {
      skipped.add(song.key)
    }
    const artist = artists.get(artistKey(song.artist))
    if (artist) artist.score += song.score
  }

  const known = new Set()
  for (const artist of artists.values()) {
    if (artist.library > 0 || artist.plays > artist.skips) known.add(artist.key)
  }

  return {
    songs,
    artists,
    heard,
    skipped,
    known,
    library,
    coldStart: listened < 10,
  }
}

/** How much one dislikes an artist: 0 (fine) to 1 (always skipped). */
export function artistAversion(artist) {
  if (!artist || artist.plays < 3) return 0
  const rate = artist.skips / artist.plays
  return rate > 0.5 ? Math.min(1, (rate - 0.5) * 2) : 0
}

/**
 * Up to `count` songs to start the radio mixes from, `{ key, artist,
 * title, weight, why }` each - `why` is 'rotation' (played most),
 * 'recent' (these last days) or 'explore' (a deeper pick, another one
 * each day). Never more than two of one artist; disliked artists left out.
 */
export function pickSeeds(
  profile,
  { count = 8, now = Date.now(), salt = '' } = {}
) {
  const day = Math.floor(now / DAY_MS)
  // `salt` (Refresh) draws other deeper picks the same day.
  const random = seededRandom(`seeds:${day}:${salt}`)
  const usable = [...profile.songs.values()].filter((song) => {
    if (song.score <= 0 || profile.skipped.has(song.key)) return false
    const artist = profile.artists.get(artistKey(song.artist))
    return artistAversion(artist) < 0.5
  })
  if (!usable.length) return []
  const byScore = [...usable].sort((a, b) => b.score - a.score)
  const top = byScore[0].score || 1
  const picked = []
  const perArtist = new Map()

  function take(song, why) {
    if (picked.length >= count) return false
    if (picked.some((seed) => seed.key === song.key)) return false
    const artist = artistKey(song.artist)
    if ((perArtist.get(artist) || 0) >= 2) return false
    perArtist.set(artist, (perArtist.get(artist) || 0) + 1)
    picked.push({
      key: song.key,
      artist: song.artist,
      title: song.title,
      weight: Math.max(0.35, Math.min(1, song.score / top)),
      why,
    })
    return true
  }

  const rotation = Math.ceil(count / 2)
  const recent = Math.max(1, Math.floor(count / 4))
  // On heavy rotation: one song per artist first, then a second.
  const seen = new Set()
  for (const song of byScore) {
    if (picked.length >= rotation) break
    const artist = artistKey(song.artist)
    if (seen.has(artist)) continue
    seen.add(artist)
    take(song, 'rotation')
  }
  // These last days.
  const lately = usable
    .filter((song) => song.lastAt && now - song.lastAt < 7 * DAY_MS)
    .sort((a, b) => b.lastAt - a.lastAt)
  let added = 0
  for (const song of lately) {
    if (added >= recent) break
    if (take(song, 'recent')) added += 1
  }
  // Deeper picks, drawn by weight from further down, a new draw each day.
  const deep = byScore.slice(rotation, 80)
  while (picked.length < count && deep.length) {
    const total = deep.reduce(
      (sum, song) => sum + Math.max(song.score, 0.05),
      0
    )
    let roll = random() * total
    let index = 0
    for (; index < deep.length - 1; index += 1) {
      roll -= Math.max(deep[index].score, 0.05)
      if (roll <= 0) break
    }
    const [song] = deep.splice(index, 1)
    take(song, 'explore')
  }
  // Still short (a small library): whatever is left, best first.
  for (const song of byScore) {
    if (picked.length >= count) break
    take(song, 'rotation')
  }
  return picked
}

/**
 * The songs to suggest from the seeds' radio mixes: `radios` is
 * `[{ seed, rows }]` (rows: YouTube Music search rows, most similar
 * first). `mode` is 'discover' (artists one doesn't know first) or
 * 'foryou' (around the artists one loves). Leaves out songs on the server,
 * skipped or `dismissed` ones and `blocked` artists; `shown` (songKey →
 * days it was offered without being played) makes a song step aside.
 * `{ song, score, because, support, kind }` each, best first, `size` at
 * most - `kind` is 'new' (an artist one doesn't know), 'familiar' or
 * 'again' (streamed and played through before).
 */
export function rankCandidates(
  profile,
  radios,
  {
    mode = 'discover',
    blocked = new Set(),
    dismissed = new Set(),
    shown = {},
    now = Date.now(),
    size = 30,
    salt = '',
  } = {}
) {
  const day = Math.floor(now / DAY_MS)
  const random = seededRandom(`${mode}:${day}:${salt}`)
  const seedKeys = new Set(radios.map((radio) => radio.seed?.key))
  const candidates = new Map()

  for (const { seed, rows } of radios || []) {
    if (!seed) continue
    ;(rows || []).forEach((row, index) => {
      const artists = rowArtists(row)
      const lead = artists[0]
      const title = rowTitle(row)
      if (!lead || !title) return
      const key = songKey(lead, title)
      if (seedKeys.has(key)) return
      if (!candidates.has(key)) {
        candidates.set(key, {
          key,
          song: row,
          artists: artists.map(artistKey),
          votes: new Map(),
        })
      }
      const vote = seed.weight / (1 + index / 8)
      const votes = candidates.get(key).votes
      votes.set(seed.key, Math.max(votes.get(seed.key) || 0, vote))
      // The seed's artist decides "because" - kept with the vote.
      candidates.get(key)[`because:${seed.key}`] = seed.artist
    })
  }

  const scored = []
  for (const candidate of candidates.values()) {
    const { key, artists } = candidate
    if (profile.library.has(key)) continue
    if (profile.skipped.has(key) || dismissed.has(key)) continue
    if (artists.some((artist) => blocked.has(artist))) continue
    const lead = profile.artists.get(artists[0])
    const aversion = artistAversion(lead)
    if (aversion >= 0.9) continue
    const isKnown = artists.some((artist) => profile.known.has(artist))
    const heard = profile.heard.has(key)
    const song = profile.songs.get(key)

    let fit = 0
    let best = ''
    let bestVote = 0
    for (const [seedKey, vote] of candidate.votes) {
      fit += vote
      if (vote > bestVote) {
        bestVote = vote
        best = candidate[`because:${seedKey}`]
      }
    }
    const support = candidate.votes.size
    // Found by several seeds: it fits the taste, not one song.
    let score = fit * (1 + 0.45 * (support - 1))

    let kind = isKnown ? 'familiar' : 'new'
    if (mode === 'discover') {
      if (heard && song && now - song.lastAt < 60 * DAY_MS) continue
      if (isKnown) score *= 0.3
    } else {
      const love = lead ? Math.max(0, lead.score) : 0
      score *= isKnown ? 1 + Math.min(0.8, love / 12) : 0.75
      if (heard && song) {
        // Streamed and played through more than once: one keeps coming
        // back to it - worth having.
        kind = 'again'
        score *= song.completes >= 2 ? 1.4 : 0.6
      }
    }
    score *= 1 - aversion * 0.7
    // Offered day after day and never played: give others a turn.
    score *= 0.75 ** Math.min(6, Number(shown[key]) || 0)
    // A little of the day's chance, so equals take turns.
    score *= 0.9 + random() * 0.2
    scored.push({
      song: candidate.song,
      key,
      artists,
      score,
      because: best,
      support,
      kind,
    })
  }

  // Songs one already streams are worth a reminder, not the whole list.
  return diversify(scored, {
    size,
    perArtist: mode === 'discover' ? 2 : 3,
    perKind: { again: Math.max(1, Math.round(size * 0.2)) },
  })
}

/**
 * The best `size` of `scored`, one at a time: each pick makes the rest
 * of its artist (and of the seed it came from) count less, and an artist
 * never comes more than `perArtist` times or twice in a row.
 */
export function diversify(
  scored,
  { size = 30, perArtist = 2, perKind = {} } = {}
) {
  const pool = [...scored].sort((a, b) => b.score - a.score)
  const artistCount = new Map()
  const becauseCount = new Map()
  const kindCount = new Map()
  const out = []
  while (out.length < size && pool.length) {
    let bestIndex = -1
    let bestValue = -Infinity
    for (let i = 0; i < pool.length; i += 1) {
      const item = pool[i]
      const lead = item.artists[0]
      const n = artistCount.get(lead) || 0
      if (n >= perArtist) continue
      if (
        item.kind in perKind &&
        (kindCount.get(item.kind) || 0) >= perKind[item.kind]
      )
        continue
      if (out.length && out[out.length - 1].artists[0] === lead) continue
      const fromSeed = becauseCount.get(item.because) || 0
      const value = item.score * 0.55 ** n * 0.85 ** Math.max(0, fromSeed - 2)
      if (value > bestValue) {
        bestValue = value
        bestIndex = i
      }
      // Sorted by score: nothing further down can beat an untouched one.
      if (n === 0 && fromSeed <= 2) break
    }
    if (bestIndex < 0) break
    const [item] = pool.splice(bestIndex, 1)
    artistCount.set(
      item.artists[0],
      (artistCount.get(item.artists[0]) || 0) + 1
    )
    becauseCount.set(item.because, (becauseCount.get(item.because) || 0) + 1)
    kindCount.set(item.kind, (kindCount.get(item.kind) || 0) + 1)
    out.push(item)
  }
  return out
}
