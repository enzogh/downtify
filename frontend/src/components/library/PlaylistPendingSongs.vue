<template>
  <section v-if="songs.length" class="flex flex-col gap-2">
    <p class="eyebrow flex items-center gap-2">
      <AppIcon name="download" :size="13" />
      {{ t('playlists.pendingTitle', { count: songs.length }) }}
    </p>
    <ul class="-mx-3 flex flex-col">
      <li
        v-for="song in songs"
        :key="song.song_id"
        class="group/pending flex items-center"
      >
        <SongRow :song="song" :songs="songs" class="min-w-0 flex-1" />
        <UiIconButton
          v-if="canEdit"
          icon="x"
          size="sm"
          :label="t('playlists.removeTrack')"
          class="shrink-0"
          @click="remove(song)"
        />
      </li>
    </ul>
  </section>
</template>

<script setup>
// The songs a Library playlist waits on: added from a search, the charts
// or a recommendation before they were downloaded. They play streamed and
// move into the playlist proper once their download ends (the server
// writes them in, see downtify/playlist_pending.py).
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import SongRow from '../search/SongRow.vue'
import API from '/src/model/api'
import { useLibrary } from '/src/model/library'
import { usePlaylistActions } from '/src/model/playlistActions'
import { useI18n } from '/src/i18n'

const props = defineProps({
  playlist: { type: Object, required: true },
})
const { t } = useI18n()
const library = useLibrary()
const actions = usePlaylistActions()
const songs = ref([])
const canEdit = computed(() => Boolean(props.playlist.canEditTracks))
let serial = 0

async function load() {
  if (!props.playlist.manual) {
    songs.value = []
    return
  }
  const mine = ++serial
  try {
    const res = await API.getPlaylistPending(props.playlist.name)
    if (mine === serial) songs.value = res.data?.songs || []
  } catch {
    if (mine === serial) songs.value = []
  }
}

async function remove(song) {
  await actions.removePending(props.playlist, [song.song_id])
}

onMounted(load)
// Read again when songs were added or taken out here, and when the
// playlist itself changed (a waiting song finished and moved in).
watch(
  () => [
    props.playlist.name,
    props.playlist.tracks?.length,
    actions.pendingVersion.value,
    library.playlists.value,
  ],
  load
)
// While songs wait, the library refreshes as downloads end.
watch(
  () => library.tracks.value.length,
  () => {
    if (songs.value.length) load()
  }
)
</script>
