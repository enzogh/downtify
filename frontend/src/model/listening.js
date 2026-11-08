// What this device has listened to: one entry per library song played for
// at least half a minute (or to its end), kept in localStorage for a month.
// It only feeds the Home mixes (lib/mixes.js) - nothing leaves the browser.
import { ref, watch } from 'vue'
import { usePlayer } from '/src/model/player'
import { RECENT_DAYS } from '/src/lib/mixes'

const STORAGE_KEY = 'downtify-listening-log'
const MAX_ENTRIES = 3000
const COUNTS_AFTER_SECONDS = 30
const DAY_MS = 24 * 60 * 60 * 1000

function read() {
  try {
    const list = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

const plays = ref(read())
let started = false

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(plays.value))
  } catch {
    // Quota: the mixes simply know less.
  }
}

/** Remember one play of library `file` (pruning what is too old). */
export function recordPlay(file, now = Date.now()) {
  if (!file) return
  const since = now - RECENT_DAYS * DAY_MS
  plays.value = [
    ...plays.value.filter((play) => play.at >= since),
    { file, at: now },
  ].slice(-MAX_ENTRIES)
  persist()
}

/** Start logging the player's songs (once, from the app shell). */
export function startListeningLog() {
  if (started || typeof window === 'undefined') return
  started = true
  const player = usePlayer()
  let counted = ''
  watch(
    () => player.currentTrack.value?.file,
    () => {
      counted = ''
    }
  )
  watch(
    () => Math.floor(player.currentTime.value),
    (seconds) => {
      const track = player.currentTrack.value
      // Library songs only: a stream has no file to mix later.
      if (!track?.file || track.stream || track.isPodcast) return
      if (counted === track.file) return
      const length = player.duration.value || 0
      const enough =
        seconds >= COUNTS_AFTER_SECONDS || (length > 0 && seconds >= length - 1)
      if (!enough) return
      counted = track.file
      recordPlay(track.file)
    }
  )
}

export function useListening() {
  return { plays }
}
