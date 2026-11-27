// Recommendations for Home and the mix pages (/mix/discover, /mix/foryou):
// lib/recommender.js builds the taste profile from the account's history
// (model/playHistory.js), the library and the likes, and picks the seed
// songs; this asks YouTube Music for each seed's radio mix (kept for the
// day in the browser, and six hours on the server) and ranks what they
// suggest. Two lists come out:
//
// - discover: songs by artists one doesn't know yet;
// - foryou: songs one hasn't got, around the artists one loves (and the
//   ones one keeps streaming).
//
// "Not for me" on a song (dismiss) is remembered on this device, and a
// song offered day after day without being played steps aside.
import { computed, ref, shallowRef } from 'vue'
import API from '/src/model/api'
import { libraryOnly } from '/src/model/musicPolicy'
import { useLibrary } from '/src/model/library'
import { useLikes } from '/src/model/likes'
import { useListening } from '/src/model/listening'
import { importLegacyLog, usePlayHistory } from '/src/model/playHistory'
import {
  artistKey,
  keyOfRow,
  pickSeeds,
  rankCandidates,
  songKey,
  tasteProfile,
} from '/src/lib/recommender'

const RADIOS_KEY = 'downtify-reco-radios'
const DISMISSED_KEY = 'downtify-reco-dismissed'
const SHOWN_KEY = 'downtify-reco-shown'
const DAY_MS = 24 * 60 * 60 * 1000
const SEEDS = 8
const RADIO_SIZE = 40
const CONCURRENCY = 3

function today() {
  return Math.floor(Date.now() / DAY_MS)
}

function readJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null')
    return value ?? fallback
  } catch {
    return fallback
  }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Quota: fetched again next time.
  }
}

function readSaved() {
  const saved = readJson(RADIOS_KEY, null)
  return saved?.day === today() ? saved : { radios: {}, seeds: [] }
}

const saved = readSaved()
const radios = shallowRef(saved.radios || {})
// The day's seeds, kept once chosen: a song played this afternoon doesn't
// reshuffle the lists until tomorrow (or Refresh).
const frozenSeeds = shallowRef(saved.seeds || [])
// Refresh: another draw the same day.
const round = ref(saved.round || 0)
const dismissed = shallowRef(new Set(readJson(DISMISSED_KEY, [])))
const shownState = readJson(SHOWN_KEY, { day: 0, keys: [], counts: {} })
// How many days each song was offered without being played: read once,
// moved on once a day (see noteShown), so a list doesn't reshuffle itself.
const shown = { ...(shownState.counts || {}) }
const loading = ref(false)
const ready = ref(false)
const blockedNames = shallowRef(null)
let pending = null

async function fetchRadios(seeds) {
  const found = { ...radios.value }
  const queue = [...seeds]
  async function worker() {
    while (queue.length) {
      const seed = queue.shift()
      try {
        const res = await API.getSimilarTracks(
          seed.artist,
          seed.title,
          RADIO_SIZE
        )
        found[seed.key] = res.data?.tracks || []
      } catch {
        // One seed less today; the others still speak.
      }
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker))
  radios.value = found
  save()
}

function save() {
  writeJson(RADIOS_KEY, {
    day: today(),
    seeds: frozenSeeds.value,
    radios: radios.value,
    round: round.value,
  })
}

async function loadBlocked() {
  if (blockedNames.value) return
  try {
    const res = await API.getBlockedArtists()
    blockedNames.value = (res.data || []).map((row) => row.name)
  } catch {
    blockedNames.value = []
  }
}

export function useRecommendations() {
  const library = useLibrary()
  const likes = useLikes()
  const history = usePlayHistory()
  const listening = useListening()

  const profile = computed(() =>
    tasteProfile({
      plays: history.plays.value,
      tracks: library.tracksComplete.value ? library.tracks.value : [],
      liked: likes.liked.value,
    })
  )

  const seeds = computed(() =>
    frozenSeeds.value.length
      ? frozenSeeds.value
      : pickSeeds(profile.value, { count: SEEDS, salt: round.value })
  )

  const blocked = computed(
    () => new Set((blockedNames.value || []).map(artistKey))
  )

  const radioList = computed(() =>
    seeds.value
      .filter((seed) => radios.value[seed.key])
      .map((seed) => ({ seed, rows: radios.value[seed.key] }))
  )

  function ranked(mode) {
    if (libraryOnly.value || !radioList.value.length) return []
    return rankCandidates(profile.value, radioList.value, {
      mode,
      blocked: blocked.value,
      dismissed: dismissed.value,
      shown,
      size: 30,
      salt: round.value,
    })
  }

  const discover = computed(() => ranked('discover'))
  const forYou = computed(() => ranked('foryou'))

  /** Everything the lists need: songs, history, then the radio mixes. */
  async function ensure() {
    if (libraryOnly.value) return
    if (pending) return pending
    pending = (async () => {
      if (!library.tracksComplete.value) {
        await library.ensureTracks().catch(() => {})
      }
      await Promise.all([history.loadHistory(), loadBlocked()])
      // This device's older log becomes history, once.
      importLegacyLog(listening.plays.value, (file) =>
        library.tracks.value.find((track) => track.file === file)
      )
      if (!frozenSeeds.value.length && seeds.value.length) {
        frozenSeeds.value = seeds.value
        save()
      }
      const missing = seeds.value.filter((seed) => !radios.value[seed.key])
      if (missing.length) {
        loading.value = true
        await fetchRadios(missing)
      }
      noteShown()
      ready.value = true
    })().finally(() => {
      pending = null
      loading.value = false
    })
    return pending
  }

  // Once a day: the songs offered yesterday that weren't played count one
  // day more; today's first fifteen are what is offered now.
  function noteShown() {
    const day = today()
    if (shownState.day === day) return
    const played = new Set(
      history.plays.value.map((row) => songKey(row.artist, row.title))
    )
    for (const key of shownState.keys || []) {
      if (played.has(key)) delete shown[key]
      else shown[key] = (shown[key] || 0) + 1
    }
    shownState.day = day
    shownState.keys = [...discover.value, ...forYou.value]
      .slice(0, 30)
      .map((item) => item.key)
    // Keep the map small: what was offered long ago is forgotten.
    const entries = Object.entries(shown).slice(-800)
    shownState.counts = Object.fromEntries(entries)
    writeJson(SHOWN_KEY, shownState)
  }

  /** "Not for me": never suggest this song again (on this device). */
  function dismiss(song) {
    const key = keyOfRow(song)
    if (!key) return
    dismissed.value = new Set([...dismissed.value, key])
    writeJson(DISMISSED_KEY, [...dismissed.value].slice(-500))
  }

  /** New radio mixes now, instead of tomorrow (Refresh). */
  async function refresh() {
    radios.value = {}
    frozenSeeds.value = []
    round.value += 1
    save()
    return ensure()
  }

  return {
    discover,
    forYou,
    seeds,
    profile,
    loading,
    ready,
    ensure,
    refresh,
    dismiss,
  }
}

/** Up to four distinct covers of a list, for a mosaic. */
export function listCovers(list) {
  return list
    .map((item) => item.song?.cover_url || '')
    .filter((cover, i, all) => cover && all.indexOf(cover) === i)
    .slice(0, 4)
}
