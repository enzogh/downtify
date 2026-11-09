<template>
  <component
    :is="linkTo ? RouterLink : 'div'"
    :to="linkTo || undefined"
    class="group relative flex h-full min-h-56 flex-col gap-4 rounded-panel bg-surface p-5 transition-colors hover:bg-surface-2"
    :draggable="result.kind === 'song' ? 'true' : undefined"
    @dragstart="onDragStart"
  >
    <CoverArt
      :src="cover"
      :name="result.item.name"
      :round="result.kind === 'artist'"
      :icon="result.kind === 'artist' ? 'user' : 'disc'"
      shadow
      :letter-size="36"
      class="size-24"
    />
    <div class="min-w-0">
      <p class="text-display truncate text-3xl font-bold">
        {{ result.item.name }}
      </p>
      <p class="mt-1 flex items-center gap-2 truncate text-sm text-muted">
        <span
          class="rounded-full bg-raised px-2.5 py-0.5 text-xs font-semibold text-fg-2"
          >{{ kindLabel }}</span
        >
        <span v-if="byline" class="truncate">{{ byline }}</span>
      </p>
    </div>
    <button
      v-if="result.kind === 'song'"
      type="button"
      class="absolute right-5 bottom-5 flex size-12 items-center justify-center rounded-full bg-accent text-on-accent shadow-float transition-all hover:scale-105 lg:translate-y-2 lg:opacity-0 lg:group-hover:translate-y-0 lg:group-hover:opacity-100"
      :class="play.isCurrent.value ? 'lg:translate-y-0 lg:opacity-100' : ''"
      :aria-label="play.playLabel.value"
      :disabled="!play.playable.value"
      @click.stop.prevent="play.toggle()"
    >
      <AppIcon
        v-if="play.loading.value"
        name="refresh"
        :size="20"
        class="animate-spin"
      />
      <AppIcon v-else :name="playIcon" :size="20" />
    </button>
  </component>
</template>

<script setup>
// The big card left of the songs on the search page, as on Spotify.
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from '../ui/AppIcon.vue'
import CoverArt from '../ui/CoverArt.vue'
import { useSongPlay } from '/src/model/songPlay'
import { usePlayer } from '/src/model/player'
import { localCatalogRoute } from '/src/lib/library'
import { deezerImage } from '/src/lib/deezerImage'
import { knownArtistPhoto } from '/src/lib/artistPhotoProxy'
import { useI18n } from '/src/i18n'
import { setDragSongs } from '/src/lib/dragSongs'
import { useLibrary } from '/src/model/library'

const props = defineProps({
  result: { type: Object, required: true },
  // The song list, for a mixed queue when the top result is a song.
  songs: { type: Array, default: null },
})
const { t } = useI18n()
const player = usePlayer()

// Getters keep useSongPlay following a new top result.
const play = useSongPlay({
  get song() {
    return props.result.kind === 'song' ? props.result.item : {}
  },
  get songs() {
    return props.songs
  },
})
const playIcon = computed(() =>
  play.isCurrent.value && player.isPlaying.value ? 'pause' : 'play'
)

const cover = computed(() => {
  const item = props.result.item
  if (props.result.kind === 'artist') {
    return knownArtistPhoto(item.name, item.cover_url).cover
  }
  return deezerImage(item.cover_url)
})

const kindLabel = computed(
  () =>
    ({
      artist: t('search.artist'),
      album: t('search.typeAlbum'),
      song: t('search.typeSong'),
    })[props.result.kind]
)

const byline = computed(() => {
  const item = props.result.item
  if (props.result.kind === 'artist') return ''
  if (Array.isArray(item.artists) && item.artists.length) {
    return item.artists.join(', ')
  }
  return item.artist || ''
})

// A song can be dragged onto a playlist, like the rows next to it.
const library = useLibrary()
function onDragStart(event) {
  if (props.result.kind !== 'song') return
  const song = props.result.item
  const artist = (song.artists || [])[0] || song.artist
  const track = library.findTrack(artist, song.name)
  if (track?.file) setDragSongs(event, { files: [track.file] }, song.name)
  else setDragSongs(event, { songs: [song] }, song.name)
}

const linkTo = computed(() => {
  const item = props.result.item
  if (props.result.kind === 'song') return null
  return (
    localCatalogRoute(item, props.result.kind) || {
      name: 'Link',
      query: { url: item.url },
    }
  )
})
</script>
