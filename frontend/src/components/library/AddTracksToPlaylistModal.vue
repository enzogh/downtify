<template>
  <UiModal
    :open="open"
    :title="t('playlists.addSongsTitle', { name: playlist?.title || '' })"
    :description="t('playlists.addSongsHint')"
    width="sm:max-w-lg"
    @close="close"
  >
    <div class="flex flex-col gap-3">
      <label
        class="flex h-10 items-center gap-2.5 rounded-control border border-line-2 bg-surface px-3"
      >
        <AppIcon name="filter" :size="16" class="text-faint" />
        <input
          v-model="query"
          type="search"
          :placeholder="t('playlists.addSearchPlaceholder')"
          class="h-full min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
        />
      </label>
      <ul class="max-h-80 overflow-y-auto">
        <li
          v-for="track in hits"
          :key="track.file"
          class="flex h-12 items-center gap-3 rounded-[10px] px-1 hover:bg-surface-2"
        >
          <input
            :id="`add-${track.file}`"
            v-model="picked"
            type="checkbox"
            :value="track.file"
            class="size-4 accent-accent"
          />
          <label
            :for="`add-${track.file}`"
            class="min-w-0 flex-1 cursor-pointer"
          >
            <p class="truncate text-sm font-semibold">{{ track.title }}</p>
            <p class="truncate text-[13px] text-muted">{{ track.artist }}</p>
          </label>
          <UiBadge v-if="have.has(track.file)" icon="check">
            {{ t('playlists.inPlaylist') }}
          </UiBadge>
        </li>
      </ul>
      <template v-if="catalogHits.length || catalogLoading">
        <p class="eyebrow flex items-center gap-2 px-1 pt-1">
          {{ t('playlists.addFromCatalog') }}
          <AppIcon
            v-if="catalogLoading"
            name="refresh"
            :size="13"
            class="animate-spin"
          />
        </p>
        <ul class="max-h-72 overflow-y-auto">
          <li
            v-for="song in catalogHits"
            :key="song.song_id || song.url"
            class="flex h-12 items-center gap-3 rounded-[10px] px-1 hover:bg-surface-2"
          >
            <input
              :id="`add-song-${song.song_id || song.url}`"
              v-model="pickedSongs"
              type="checkbox"
              :value="song"
              class="size-4 accent-accent"
            />
            <CoverArt
              :src="song.cover_url"
              :name="song.album_name || song.name"
              rounded="rounded-[6px]"
              :letter-size="11"
              class="size-9"
            />
            <label
              :for="`add-song-${song.song_id || song.url}`"
              class="min-w-0 flex-1 cursor-pointer"
            >
              <p class="truncate text-sm font-semibold">{{ song.name }}</p>
              <p class="truncate text-[13px] text-muted">
                {{ (song.artists || []).join(', ') || song.artist }}
              </p>
            </label>
            <UiBadge icon="download">{{ t('playlists.toDownload') }}</UiBadge>
          </li>
        </ul>
      </template>
    </div>
    <template #footer>
      <UiButton variant="ghost" @click="close">{{
        t('common.cancel')
      }}</UiButton>
      <UiButton
        variant="primary"
        icon="plus"
        :disabled="!(picked.length + pickedSongs.length) || saving"
        :loading="saving"
        @click="submit"
      >
        {{ t('playlists.addSongs') }}
      </UiButton>
    </template>
  </UiModal>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { watchDebounced } from '@vueuse/core'
import AppIcon from '../ui/AppIcon.vue'
import UiBadge from '../ui/UiBadge.vue'
import UiButton from '../ui/UiButton.vue'
import UiModal from '../ui/UiModal.vue'
import CoverArt from '../ui/CoverArt.vue'
import API from '/src/model/api'
import { libraryOnly } from '/src/model/musicPolicy'
import { useLibrary } from '/src/model/library'
import { usePlaylistActions } from '/src/model/playlistActions'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const library = useLibrary()
const actions = usePlaylistActions()
const query = ref('')
const hits = ref([])
const picked = ref([])
const saving = ref(false)
// Songs found on Spotify / YouTube Music that the library hasn't got:
// picking one adds it and downloads it (it waits in the playlist).
const catalogHits = ref([])
const catalogLoading = ref(false)
const pickedSongs = ref([])
let catalogSerial = 0

async function searchCatalog(text) {
  const term = String(text || '').trim()
  const mine = ++catalogSerial
  if (term.length < 2 || libraryOnly.value) {
    catalogHits.value = []
    catalogLoading.value = false
    return
  }
  catalogLoading.value = true
  try {
    const res = await API.search(term)
    if (mine !== catalogSerial) return
    catalogHits.value = (res.data || [])
      .filter((song) => {
        const artist = (song.artists || [])[0] || song.artist
        return !library.hasSong(artist, song.name)
      })
      .slice(0, 12)
  } catch {
    if (mine === catalogSerial) catalogHits.value = []
  } finally {
    if (mine === catalogSerial) catalogLoading.value = false
  }
}

const open = computed({
  get: () => actions.addOpen.value,
  set: (value) => {
    actions.addOpen.value = value
  },
})
const playlist = computed(() => actions.addPlaylist.value)

// Songs the playlist already has stay pickable, marked: picking one adds
// it again.
const have = computed(
  () => new Set((playlist.value?.tracks || []).map((item) => item.file))
)

async function searchLibrary(text) {
  hits.value = await library.searchTracks(text, { limit: 80 })
}

watch(open, (value) => {
  if (value) {
    query.value = ''
    picked.value = []
    pickedSongs.value = []
    catalogHits.value = []
    searchLibrary('')
  }
})

watchDebounced(
  query,
  (text) => {
    if (open.value) searchLibrary(text)
  },
  { debounce: 200 }
)

watchDebounced(
  query,
  (text) => {
    if (open.value) searchCatalog(text)
  },
  { debounce: 450 }
)

function close() {
  open.value = false
}

async function submit() {
  const count = picked.value.length + pickedSongs.value.length
  if (!playlist.value || !count || saving.value) return
  saving.value = true
  try {
    // A marked song was picked knowing it is there already.
    if (picked.value.length) {
      await actions.addFiles(playlist.value, picked.value, {
        allowDuplicates: true,
      })
    }
    if (pickedSongs.value.length) {
      await actions.addSongs(playlist.value, pickedSongs.value)
    }
    close()
  } finally {
    saving.value = false
  }
}
</script>
