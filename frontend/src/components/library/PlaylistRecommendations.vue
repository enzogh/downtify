<template>
  <section v-if="enabled" class="flex flex-col gap-3">
    <div class="flex items-end justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-lg font-bold">{{ t('playlists.recommendedTitle') }}</h2>
        <p class="text-[13px] text-muted">
          {{ t('playlists.recommendedHint') }}
        </p>
      </div>
      <UiButton
        variant="ghost"
        size="sm"
        icon="refresh"
        :loading="loading"
        @click="refresh"
      >
        {{ t('playlists.recommendedRefresh') }}
      </UiButton>
    </div>
    <ul v-if="loading && !shown.length" class="flex flex-col gap-2">
      <li
        v-for="n in 5"
        :key="n"
        class="h-14 animate-pulse rounded-[10px] bg-surface-2"
      />
    </ul>
    <ul v-else-if="shown.length" class="-mx-3 flex flex-col">
      <li
        v-for="song in shown"
        :key="songKey(song)"
        class="flex items-center gap-1"
      >
        <SongRow
          :song="song"
          :songs="shown"
          hide-add-on-phone
          class="min-w-0 flex-1"
        />
        <!-- Icon only on a phone: the song's title needs the room. -->
        <UiButton
          variant="secondary"
          size="sm"
          icon="plus"
          :loading="adding === songKey(song)"
          :aria-label="t('playlists.recommendedAdd')"
          :title="t('playlists.recommendedAdd')"
          class="mr-2 shrink-0 max-sm:w-8 max-sm:px-0"
          @click="add(song)"
        >
          <span class="max-sm:hidden">{{ t('playlists.recommendedAdd') }}</span>
        </UiButton>
      </li>
    </ul>
    <p v-else-if="!loading" class="text-[13px] text-muted">
      {{ t('playlists.recommendedEmpty') }}
    </p>
  </section>
</template>

<script setup>
// "Recommended songs" under a Library playlist, like Spotify's: YouTube
// Music radio mixes seeded from a few of its songs, minus what it has.
// Adding one downloads it when the library hasn't got it.
import { computed, ref, watch } from 'vue'
import { watchDebounced } from '@vueuse/core'
import UiButton from '../ui/UiButton.vue'
import SongRow from '../search/SongRow.vue'
import API from '/src/model/api'
import { libraryOnly } from '/src/model/musicPolicy'
import { usePlaylistActions } from '/src/model/playlistActions'
import {
  interleave,
  pickSeeds,
  recommendationKey,
} from '/src/lib/recommendations'
import {
  cachedRecommendations,
  saveRecommendations,
  seedSignature,
} from '/src/lib/recommendationCache'
import { useI18n } from '/src/i18n'

const props = defineProps({
  playlist: { type: Object, required: true },
  // Songs the playlist is waiting on (downloading): not suggested again.
  pending: { type: Array, default: () => [] },
})
const { t } = useI18n()
const actions = usePlaylistActions()
const found = ref([])
const loading = ref(false)
const adding = ref('')
const added = ref(new Set())
let serial = 0
let round = 0

const SHOWN = 10
const songKey = recommendationKey

const enabled = computed(
  () =>
    !libraryOnly.value &&
    props.playlist.canEditTracks &&
    (props.playlist.tracks || []).length > 0
)

// What the playlist already has, by artist and title.
const have = computed(() => {
  const keys = new Set()
  for (const track of props.playlist.tracks || []) {
    keys.add(recommendationKey({ artist: track.artist, name: track.title }))
  }
  return keys
})

const waiting = computed(
  () => new Set(props.pending.map((song) => recommendationKey(song)))
)

const shown = computed(() =>
  found.value
    .filter((song) => {
      const key = songKey(song)
      return (
        !have.value.has(key) && !added.value.has(key) && !waiting.value.has(key)
      )
    })
    .slice(0, SHOWN)
)

// The newest songs the first mixes start from: when one is added (a song
// lands in the playlist), the recommendations are made again.
const baseSignature = computed(() =>
  seedSignature(pickSeeds(props.playlist.tracks || [], 3, 0))
)

// Shown from the cache when this playlist's are still good; fetched only
// the first time, after a new song, a day later, or on Refresh.
async function load({ force = false } = {}) {
  if (!enabled.value) return
  const name = props.playlist.name
  const signature = baseSignature.value
  if (!force) {
    const cached = cachedRecommendations(name, signature)
    if (cached) {
      serial += 1
      round = cached.round || 0
      found.value = cached.songs || []
      loading.value = false
      return
    }
    round = 0
  }
  const mine = ++serial
  loading.value = true
  const seeds = pickSeeds(props.playlist.tracks || [], 3, round)
  try {
    const results = await Promise.allSettled(
      seeds.map((track) => API.getSimilarTracks(track.artist, track.title, 12))
    )
    if (mine !== serial) return
    const lists = results.map((res) =>
      res.status === 'fulfilled' ? res.value.data?.tracks || [] : []
    )
    found.value = interleave(lists, songKey)
    // A failed lookup isn't remembered: the next visit tries again.
    if (results.some((res) => res.status === 'fulfilled')) {
      saveRecommendations(name, { signature, round, songs: found.value })
    }
  } finally {
    if (mine === serial) loading.value = false
  }
}

// On open, the saved list shows at once; the debounced check below only
// fetches when it no longer holds.
if (enabled.value) {
  const cached = cachedRecommendations(props.playlist.name, baseSignature.value)
  if (cached) {
    round = cached.round || 0
    found.value = cached.songs || []
  }
}

function refresh() {
  round += 1
  load({ force: true })
}

async function add(song) {
  const key = songKey(song)
  adding.value = key
  try {
    const res = await actions.addSongs(props.playlist, [song])
    if (res.added || res.pending) added.value = new Set([...added.value, key])
  } finally {
    adding.value = ''
  }
}

watch(
  () => props.playlist.name,
  () => {
    added.value = new Set()
  }
)
// Debounced: the playlist's rows arrive in a burst when it opens, and
// only the settled list should decide whether the cache still holds.
watchDebounced(
  () => [props.playlist.name, enabled.value, baseSignature.value],
  () => load(),
  { debounce: 350, immediate: true }
)
</script>
