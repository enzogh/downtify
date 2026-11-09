// Autoplay (Settings > General, per device, on by default), as Spotify
// does it: as soon as something plays, "Up next" lists recommended songs
// like the end of the queue, right after it. When the queue reaches its
// last track (repeat off) they join it - streamed when they aren't
// downloaded, the next one prepared ahead (player.prepareNext) - and the
// following suggestions are fetched from the new end of the queue.
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
// The recommended songs shown after the queue (player tracks), and the
// seeds they came from.
const suggestions = ref([])
let suggestionsKey = ''
let fetchingKey = ''
let started = false

export function setAutoplay(on) {
  enabled.value = Boolean(on)
  try {
    localStorage.setItem(STORAGE_KEY, enabled.value ? '1' : '0')
  } catch {
    // ignore
  }
  if (!enabled.value) suggestions.value = []
  update()
}

function active(player) {
  const index = player.currentIndex.value
  const list = player.playlist.value
  return (
    enabled.value &&
    !libraryOnly.value &&
    // A Jam's queue is everyone's: nobody's device fills it on its own.
    !player.remoteControlled?.value &&
    index >= 0 &&
    list.length > 0 &&
    !list[index]?.isPodcast
  )
}

/** Fetch the suggestions for the end of the queue, when they changed. */
async function refreshSuggestions(player) {
  const list = player.playlist.value
  const seeds = autoplaySeeds(list, list.length - 1)
  const key = seedsKey(seeds)
  if (!seeds.length) {
    suggestions.value = []
    suggestionsKey = ''
    return
  }
  if (key === suggestionsKey || key === fetchingKey) return
  fetchingKey = key
  loading.value = true
  try {
    const results = await Promise.allSettled(
      seeds.map((track) =>
        API.getSimilarTracks(track.artist, track.title, AUTOPLAY_BATCH + 4)
      )
    )
    if (fetchingKey !== key) return
    const lists = results.map((res) =>
      res.status === 'fulfilled' ? res.value.data?.tracks || [] : []
    )
    const library = useLibrary()
    suggestions.value = freshSongs(
      interleave(lists),
      player.playlist.value
    ).map((song) => ({
      ...songToPlayerTrack(song, library.findTrack),
      autoplay: true,
    }))
    suggestionsKey = key
  } catch {
    // Autoplay is a bonus: the queue simply ends.
  } finally {
    if (fetchingKey === key) {
      fetchingKey = ''
      loading.value = false
    }
  }
}

/** Move the suggestions into the queue once it is about to run out. */
function promote(player) {
  // Checked again: a Jam may have taken the queue over while the
  // suggestions were loading.
  if (!active(player)) return
  if (player.repeatMode.value !== 'off') return
  if (player.upcoming.value.length > AUTOPLAY_THRESHOLD) return
  const tracks = freshSongs(
    suggestions.value.map((track) => ({ ...track, name: track.title })),
    player.playlist.value
  )
  if (!tracks.length) return
  suggestions.value = []
  suggestionsKey = ''
  player.enqueue(tracks)
  player.prepareNext()
}

async function update() {
  const player = usePlayer()
  if (!active(player)) return
  await refreshSuggestions(player)
  promote(player)
}

/** Play a suggestion now: it goes right after the current track. */
export function playSuggestion(track) {
  const player = usePlayer()
  suggestions.value = suggestions.value.filter((item) => item !== track)
  player.playNext([track])
  player.next()
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
      libraryOnly.value,
    ],
    () => update(),
    { immediate: true }
  )
}

export function useAutoplay() {
  return { enabled, loading, suggestions, setAutoplay, playSuggestion }
}
