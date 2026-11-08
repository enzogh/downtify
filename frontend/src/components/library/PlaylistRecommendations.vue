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
        <SongRow :song="song" :songs="shown" class="min-w-0 flex-1" />
        <UiButton
          variant="secondary"
          size="sm"
          :loading="adding === songKey(song)"
          class="mr-2 shrink-0"
          @click="add(song)"
        >
          {{ t('playlists.recommendedAdd') }}
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
import { computed, onMounted, ref, watch } from 'vue'
import UiButton from '../ui/UiButton.vue'
import SongRow from '../search/SongRow.vue'
import API from '/src/model/api'
import { libraryOnly } from '/src/model/musicPolicy'
import { usePlaylistActions } from '/src/model/playlistActions'
import { pickSeeds, recommendationKey } from '/src/lib/recommendations'
import { useI18n } from '/src/i18n'

const props = defineProps({
  playlist: { type: Object, required: true },
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

const shown = computed(() =>
  found.value
    .filter((song) => {
      const key = songKey(song)
      return !have.value.has(key) && !added.value.has(key)
    })
    .slice(0, SHOWN)
)

async function load() {
  if (!enabled.value) return
  const mine = ++serial
  loading.value = true
  const seeds = pickSeeds(props.playlist.tracks || [], 3, round)
  try {
    const results = await Promise.allSettled(
      seeds.map((track) => API.getSimilarTracks(track.artist, track.title, 12))
    )
    if (mine !== serial) return
    const merged = []
    const seen = new Set()
    // Interleave the mixes so one seed doesn't fill the list.
    const lists = results.map((res) =>
      res.status === 'fulfilled' ? res.value.data?.tracks || [] : []
    )
    const longest = Math.max(0, ...lists.map((list) => list.length))
    for (let i = 0; i < longest; i += 1) {
      for (const list of lists) {
        const song = list[i]
        if (!song) continue
        const key = songKey(song)
        if (seen.has(key)) continue
        seen.add(key)
        merged.push(song)
      }
    }
    found.value = merged
  } finally {
    if (mine === serial) loading.value = false
  }
}

function refresh() {
  round += 1
  load()
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

onMounted(load)
watch(
  () => [props.playlist.name, enabled.value],
  () => {
    round = 0
    added.value = new Set()
    load()
  }
)
</script>
