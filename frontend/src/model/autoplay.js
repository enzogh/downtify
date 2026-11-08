// Autoplay (Settings > General, per device, on by default): when the
// queue is about to run out, recommended songs like the last ones played
// are added after it, streamed when they aren't downloaded, and the next
// one is prepared ahead (see player.prepareNext) so playback carries on
// without a pause.
import { ref, watch } from 'vue'
import API from '/src/model/api'
import { libraryOnly } from '/src/model/musicPolicy'
import { usePlayer } from '/src/model/player'
import { useLibrary } from '/src/model/library'
import { songToPlayerTrack } from '/src/model/songPlay'
import { interleave } from '/src/lib/recommendations'
import {
  AUTOPLAY_BATCH,
  AUTOPLAY_THRESHOLD,
  autoplaySeeds,
  freshSongs,
  seedsKey,
} from '/src/lib/autoplay'

const STORAGE_KEY = 'downtify-player-autoplay'

function readEnabled() {
  try {
    return localStorage.getItem(STORAGE_KEY) !== '0'
  } catch {
    return true
  }
}

const enabled = ref(readEnabled())
const loading = ref(false)
let started = false
// The seeds last topped up from: the same ones never fetch twice, so
// clearing "Up next" doesn't bring the same songs straight back.
let lastKey = ''

export function setAutoplay(on) {
  enabled.value = Boolean(on)
  try {
    localStorage.setItem(STORAGE_KEY, enabled.value ? '1' : '0')
  } catch {
    // ignore
  }
  if (enabled.value) topUp()
}

async function topUp() {
  const player = usePlayer()
  if (!enabled.value || libraryOnly.value || loading.value) return
  if (player.repeatMode.value !== 'off') return
  const index = player.currentIndex.value
  const list = player.playlist.value
  if (index < 0 || !list.length || list[index]?.isPodcast) return
  if (player.upcoming.value.length > AUTOPLAY_THRESHOLD) return
  const seeds = autoplaySeeds(list, index)
  const key = seedsKey(seeds)
  if (!seeds.length || key === lastKey) return
  lastKey = key
  loading.value = true
  try {
    const results = await Promise.allSettled(
      seeds.map((track) =>
        API.getSimilarTracks(track.artist, track.title, AUTOPLAY_BATCH + 4)
      )
    )
    const lists = results.map((res) =>
      res.status === 'fulfilled' ? res.value.data?.tracks || [] : []
    )
    // The queue may have changed while asking: compare with it now.
    const songs = freshSongs(interleave(lists), player.playlist.value)
    if (!songs.length) return
    const library = useLibrary()
    player.enqueue(
      songs.map((song) => ({
        ...songToPlayerTrack(song, library.findTrack),
        autoplay: true,
      }))
    )
    player.prepareNext()
  } catch {
    // Autoplay is a bonus: the queue simply ends.
  } finally {
    loading.value = false
  }
}

/** Start watching the queue (once, from the app shell). */
export function startAutoplay() {
  if (started || typeof window === 'undefined') return
  started = true
  const player = usePlayer()
  watch(
    () => [
      player.currentIndex.value,
      player.playlist.value.length,
      player.repeatMode.value,
      player.shuffle.value,
    ],
    () => topUp()
  )
}

export function useAutoplay() {
  return { enabled, loading, setAutoplay }
}
