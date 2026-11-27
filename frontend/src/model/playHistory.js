// The account's listening history, on every device: each song the player
// plays (library or streamed) becomes one row - how long it played, and
// whether it was skipped (lib/playHistory.js decides). Rows wait in an
// outbox in localStorage and go to the server in batches
// (POST /api/history/plays), so a play made offline is sent later; the
// server's copy (GET /api/history) is read back once per visit and kept
// here, so recommendations (lib/recommender.js) know at once.
//
// The older log of this device (model/listening.js, library files only)
// is sent once as history, so nobody starts from nothing.
import { ref, shallowRef, watch } from 'vue'
import API from '/src/model/api'
import { usePlayer } from '/src/model/player'
import { addPlayed } from '/src/lib/discover'
import { closePlay, newPlayId } from '/src/lib/playHistory'
import { mergePlays } from '/src/model/listening'

const CACHE_KEY = 'downtify-play-history'
const OUTBOX_KEY = 'downtify-play-outbox'
const IMPORTED_KEY = 'downtify-play-history-imported'
const DAYS = 180
const MAX_CACHED = 6000
const BATCH = 200
const FLUSH_DELAY_MS = 4000

function readList(key) {
  try {
    const list = JSON.parse(localStorage.getItem(key) || '[]')
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

function writeList(key, list) {
  try {
    localStorage.setItem(key, JSON.stringify(list))
  } catch {
    // Quota: what is in memory still serves this visit.
  }
}

/** Epoch ms of a row's `played_at` (ISO text or a number). */
export function playedAtMs(row) {
  const value = row?.played_at
  if (typeof value === 'number') return value
  const ms = Date.parse(value || '')
  return Number.isFinite(ms) ? ms : 0
}

// Newest first, each play once.
function merge(...lists) {
  const seen = new Set()
  const out = []
  for (const row of lists.flat()) {
    if (!row?.play_id || seen.has(row.play_id)) continue
    seen.add(row.play_id)
    out.push(row)
  }
  return out.sort((a, b) => playedAtMs(b) - playedAtMs(a)).slice(0, MAX_CACHED)
}

const outbox = shallowRef(readList(OUTBOX_KEY))
const plays = shallowRef(merge(outbox.value, readList(CACHE_KEY)))
const loaded = ref(false)
let loading = null
let flushTimer = 0
let flushing = false
let started = false

function feedListening(rows) {
  // The Daily Mixes count library plays (model/listening.js): give them
  // every device's, not only this one's.
  mergePlays(
    rows
      .filter((row) => row.file && row.source === 'library' && !row.skipped)
      .map((row) => ({ file: row.file, at: playedAtMs(row) }))
  )
}

/** Read the server's copy (once per visit unless `force`). */
export function loadHistory({ force = false } = {}) {
  if (loading && !force) return loading
  loading = (async () => {
    try {
      const res = await API.getHistory(DAYS)
      const server = Array.isArray(res.data?.plays) ? res.data.plays : []
      plays.value = merge(outbox.value, server)
      writeList(CACHE_KEY, plays.value.slice(0, MAX_CACHED))
      feedListening(server)
    } catch {
      // Offline, or an older server: what this device kept stands.
    } finally {
      loaded.value = true
    }
  })()
  return loading
}

async function flush() {
  clearTimeout(flushTimer)
  if (flushing || !outbox.value.length) return
  flushing = true
  const batch = outbox.value.slice(0, BATCH)
  try {
    await API.recordPlays(batch)
    const sent = new Set(batch.map((row) => row.play_id))
    outbox.value = outbox.value.filter((row) => !sent.has(row.play_id))
    writeList(OUTBOX_KEY, outbox.value)
  } catch (err) {
    // 4xx other than auth: these rows will never be taken - drop them.
    const status = err?.response?.status
    if (
      status &&
      status >= 400 &&
      status < 500 &&
      ![401, 403, 429].includes(status)
    ) {
      outbox.value = outbox.value.slice(batch.length)
      writeList(OUTBOX_KEY, outbox.value)
    }
  } finally {
    flushing = false
  }
  if (outbox.value.length) flushTimer = setTimeout(flush, FLUSH_DELAY_MS * 4)
}

function scheduleFlush() {
  clearTimeout(flushTimer)
  flushTimer = setTimeout(flush, FLUSH_DELAY_MS)
}

/** Keep one finished play (a row from lib/playHistory.js closePlay). */
export function addPlay(row) {
  if (!row?.play_id) return
  outbox.value = [...outbox.value, row].slice(-2000)
  writeList(OUTBOX_KEY, outbox.value)
  plays.value = merge([row], plays.value)
  scheduleFlush()
}

/**
 * Send this device's older log (library files with the time they played)
 * as history, once: `findByFile(file)` gives the library track.
 */
export function importLegacyLog(log, findByFile) {
  try {
    if (localStorage.getItem(IMPORTED_KEY)) return 0
  } catch {
    return 0
  }
  // Plays the server already has (they came back into the log from it).
  const known = new Map()
  for (const row of plays.value) {
    if (!row.file) continue
    if (!known.has(row.file)) known.set(row.file, [])
    known.get(row.file).push(playedAtMs(row))
  }
  const rows = []
  for (const entry of log || []) {
    const track = findByFile(entry?.file)
    if (!track?.artist || !track?.title || !entry.at) continue
    const times = known.get(entry.file) || []
    if (times.some((at) => Math.abs(at - entry.at) < 60_000)) continue
    rows.push({
      play_id: `log-${entry.at}-${track.file}`.slice(0, 64),
      played_at: entry.at,
      artist: track.artist,
      title: track.title,
      album: track.album || '',
      file: track.file,
      video_id: '',
      source: 'library',
      played_s: Math.min(track.duration || 30, 240),
      duration_s: track.duration || 0,
      skipped: false,
      context: 'import',
    })
  }
  try {
    localStorage.setItem(IMPORTED_KEY, '1')
  } catch {
    // It may be sent again: the server counts each play_id once.
  }
  if (!rows.length) return 0
  outbox.value = [...outbox.value, ...rows]
  writeList(OUTBOX_KEY, outbox.value)
  plays.value = merge(rows, plays.value)
  scheduleFlush()
  return rows.length
}

function identity(track) {
  if (!track) return ''
  return (
    track.file || track.video_id || `${track.artist || ''}|${track.title || ''}`
  )
}

const CURRENT_KEY = 'downtify-play-current'

// The play under way, written down now and then: a phone may close the
// app while a song plays (in the background, as music apps are), and the
// next visit still keeps it.
function checkpoint(current, duration) {
  try {
    if (!current) localStorage.removeItem(CURRENT_KEY)
    else
      localStorage.setItem(
        CURRENT_KEY,
        JSON.stringify({
          track: {
            artist: current.track.artist,
            title: current.track.title,
            album: current.track.album,
            file: current.track.file,
            stream: current.track.stream,
            video_id: current.track.video_id,
            duration: current.track.duration,
          },
          playId: current.playId,
          startedAt: current.startedAt,
          played: current.played,
          last: current.last,
          duration,
          context: current.context,
        })
      )
  } catch {
    // Without storage, a play cut short by closing the app is lost.
  }
}

function recoverCheckpoint() {
  let saved = null
  try {
    saved = JSON.parse(localStorage.getItem(CURRENT_KEY) || 'null')
    localStorage.removeItem(CURRENT_KEY)
  } catch {
    return
  }
  if (!saved?.track) return
  const row = closePlay({
    track: saved.track,
    played: saved.played,
    position: saved.last,
    duration: saved.duration,
    context: saved.context,
    startedAt: saved.startedAt,
    playId: saved.playId,
  })
  // Cut short by the app closing, not by the listener: not a skip.
  if (row) addPlay({ ...row, skipped: false })
}

/** Follow the player (once, from the app shell). */
export function startPlayHistory() {
  if (started || typeof window === 'undefined') return
  started = true
  const player = usePlayer()
  let current = null
  let savedAt = 0

  recoverCheckpoint()

  function open(track) {
    current = track
      ? {
          track,
          id: identity(track),
          playId: newPlayId(),
          startedAt: Date.now(),
          played: 0,
          last: player.currentTime.value || 0,
          context: player.context.value?.type || '',
        }
      : null
    savedAt = 0
  }

  function close() {
    if (!current) return
    const row = closePlay({
      track: current.track,
      played: current.played,
      position: current.last,
      duration: player.duration.value || current.track.duration,
      context: current.context,
      startedAt: current.startedAt,
      playId: current.playId,
    })
    current = null
    checkpoint(null)
    if (row) addPlay(row)
  }

  watch(
    () => identity(player.currentTrack.value),
    () => {
      close()
      open(player.currentTrack.value)
    },
    { immediate: true }
  )

  watch(player.currentTime, (now) => {
    if (!current) return
    // Repeat one: back to the start after playing through is a new play.
    if (now < 1 && current.last > now && current.played > 20) {
      close()
      open(player.currentTrack.value)
    }
    if (!current) return
    current.played = addPlayed(current.played, current.last, now)
    current.last = now
    if (current.played - savedAt >= 15) {
      savedAt = current.played
      checkpoint(current, player.duration.value)
    }
  })

  // Hidden (another app, the screen off): what waits is sent, and the
  // play under way written down - it carries on in the background.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'hidden') return
    if (current) checkpoint(current, player.duration.value)
    flush()
  })
  window.addEventListener('online', () => flush())

  loadHistory()
  if (outbox.value.length) scheduleFlush()
}

/** Forget one's history here and on the server. */
export async function clearHistory() {
  await API.clearHistory()
  outbox.value = []
  plays.value = []
  writeList(OUTBOX_KEY, [])
  writeList(CACHE_KEY, [])
}

export function usePlayHistory() {
  return { plays, loaded, loadHistory, addPlay, clearHistory }
}
