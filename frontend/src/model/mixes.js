// "Made for you" mixes, shared by Home and the mix page (/mix/:id).
// lib/mixes.js builds them; this asks YouTube Music for each lead
// artist's radio mix (what holds a mix together), keeps those for the
// day in the browser, and turns a mix into the player's queue.
import { computed, ref, shallowRef } from 'vue'
import API from '/src/model/api'
import { libraryOnly } from '/src/model/musicPolicy'
import { useLibrary } from '/src/model/library'
import { useLikes } from '/src/model/likes'
import { useListening } from '/src/model/listening'
import { songToPlayerTrack } from '/src/model/songPlay'
import {
  buildMixes,
  mixSeeds,
  onRepeat,
  recentPlayCounts,
} from '/src/lib/mixes'

const STORAGE_KEY = 'downtify-mix-radios'
const DAY_MS = 24 * 60 * 60 * 1000

function readRadios() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    if (saved && saved.day === Math.floor(Date.now() / DAY_MS)) {
      return saved.radios || {}
    }
  } catch {
    // Start over.
  }
  return {}
}

const radios = shallowRef(readRadios())
const loadingRadios = ref(false)
let pending = null

function saveRadios() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        day: Math.floor(Date.now() / DAY_MS),
        radios: radios.value,
      })
    )
  } catch {
    // Quota: they are fetched again next time.
  }
}

export function useMixes() {
  const library = useLibrary()
  const likes = useLikes()
  const listening = useListening()

  const options = computed(() => ({
    plays: listening.plays.value,
    liked: likes.liked.value,
  }))

  const mixes = computed(() => {
    if (!library.tracksComplete.value) return []
    return buildMixes(library.tracks.value, {
      ...options.value,
      similar: libraryOnly.value ? {} : radios.value,
    })
  })

  const repeat = computed(() =>
    library.tracksComplete.value
      ? onRepeat(library.tracks.value, listening.plays.value)
      : []
  )

  /** Load every song, then the radio mixes the lead artists still lack. */
  async function ensure() {
    if (!library.tracksComplete.value) {
      await library.ensureTracks().catch(() => {})
    }
    if (libraryOnly.value || pending) return pending
    const seeds = mixSeeds(library.tracks.value, options.value).filter(
      (seed) => !radios.value[seed.key]
    )
    if (!seeds.length) return undefined
    const counts = recentPlayCounts(options.value.plays)
    loadingRadios.value = true
    pending = (async () => {
      const found = { ...radios.value }
      await Promise.allSettled(
        seeds.map(async (seed) => {
          // Its most played song speaks for the artist best.
          const lead = [...seed.tracks].sort(
            (a, b) => (counts[b.file] || 0) - (counts[a.file] || 0)
          )[0]
          const res = await API.getSimilarTracks(seed.name, lead.title, 40)
          found[seed.key] = res.data?.tracks || []
        })
      )
      radios.value = found
      saveRadios()
    })().finally(() => {
      pending = null
      loadingRadios.value = false
    })
    return pending
  }

  function findMix(id) {
    if (id === 'repeat') return null
    return mixes.value.find((mix) => mix.id === String(id)) || null
  }

  /** A mix's songs as player tracks (library files, else streamed). */
  function queueOf(mix) {
    return (mix?.items || []).map((item) =>
      item.track ? item.track : songToPlayerTrack(item.song, library.findTrack)
    )
  }

  return { mixes, repeat, ensure, findMix, queueOf, loadingRadios }
}
