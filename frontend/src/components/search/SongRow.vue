<template>
  <div
    class="group flex h-16 items-center gap-3 rounded-[12px] px-3 transition-colors hover:bg-surface"
    @click="onRowClick"
    @dblclick="ensurePlaying"
    @pointerenter="warm"
    @focusin="warm"
    @contextmenu.prevent="contextMenu?.openAt($event)"
    draggable="true"
    @dragstart="onDragStart"
  >
    <UiMenu ref="contextMenu" :items="menuItems">
      <template #trigger><span /></template>
    </UiMenu>
    <span
      v-if="index !== null"
      class="tabular w-6 text-center text-[13px] text-faint max-sm:hidden"
    >
      {{ index + 1 }}
    </span>
    <button
      type="button"
      class="relative shrink-0"
      :aria-label="play.playLabel.value"
      :disabled="!play.playable.value"
      @click.stop="play.toggle()"
    >
      <CoverArt
        :src="song.cover_url"
        :name="song.album_name || song.name"
        rounded="rounded-[8px]"
        :letter-size="14"
        class="size-11"
      />
      <span
        v-if="play.playable.value"
        class="absolute inset-0 hidden items-center justify-center rounded-[8px] bg-black/45 text-white group-hover:flex"
        :class="play.isCurrent.value ? '!flex' : ''"
      >
        <AppIcon
          v-if="play.loading.value"
          name="refresh"
          :size="16"
          class="animate-spin"
        />
        <AppIcon v-else :name="overlayIcon" :size="16" />
      </span>
    </button>
    <div class="min-w-0 flex-1">
      <p class="flex items-center gap-1.5">
        <span class="truncate text-sm font-semibold">{{ song.name }}</span>
        <ExplicitBadge v-if="song.explicit" />
      </p>
      <p class="truncate text-[13px] text-muted">
        <template v-if="artistLinks.length">
          <template v-for="(artist, i) in artistLinks" :key="artist.name"
            ><template v-if="i">, </template
            ><RouterLink
              v-if="artist.to"
              :to="artist.to"
              class="hover:text-fg hover:underline"
              @click.stop
              @dblclick.stop
              >{{ artist.name }}</RouterLink
            ><template v-else>{{ artist.name }}</template></template
          >
        </template>
        <template v-else>{{ artists }}</template
        ><span v-if="song.album_name" :class="compact ? '' : 'lg:hidden'">
          ·
          <RouterLink
            v-if="albumTo"
            :to="albumTo"
            class="hover:text-fg hover:underline"
            @click.stop
            @dblclick.stop
            >{{ song.album_name }}</RouterLink
          ><template v-else>{{ song.album_name }}</template></span
        >
      </p>
    </div>
    <span
      v-if="!compact"
      class="hidden w-[30%] truncate text-[13px] text-muted lg:block"
    >
      <RouterLink
        v-if="albumTo"
        :to="albumTo"
        class="hover:text-fg hover:underline"
        @click.stop
        @dblclick.stop
        >{{ song.album_name }}</RouterLink
      ><template v-else>{{ song.album_name }}</template>
    </span>
    <span
      class="tabular hidden w-12 text-right text-[13px] text-muted sm:block"
    >
      {{ song.duration ? formatDuration(song.duration) : '' }}
    </span>
    <a
      v-if="sourceUrl"
      :href="sourceUrl"
      target="_blank"
      rel="noopener"
      class="hidden size-8 items-center justify-center rounded-control text-faint hover:bg-surface-2 hover:text-fg sm:flex lg:opacity-0 lg:group-hover:opacity-100"
      :title="openSourceLabel"
      :aria-label="openSourceLabel"
    >
      <AppIcon name="arrow-up-right" :size="16" />
    </a>
    <span
      class="flex lg:opacity-0 lg:group-hover:opacity-100 focus-within:opacity-100"
      @dblclick.stop
    >
      <UiMenu
        :items="menuItems"
        :label="t('playlists.addTo')"
        icon="plus"
        size="sm"
      />
    </span>
    <button
      v-if="firstArtist"
      type="button"
      class="hidden size-8 items-center justify-center rounded-control text-faint hover:bg-surface-2 hover:text-fg sm:flex lg:opacity-0 lg:group-hover:opacity-100 focus-visible:opacity-100"
      :title="t('buy.menu')"
      :aria-label="t('buy.menu')"
      @click.stop="buyLinks.open(buyTargetForSong(song))"
    >
      <AppIcon name="tag" :size="16" />
    </button>
    <div
      class="flex shrink-0 items-center justify-end gap-2"
      :class="compact ? '' : 'w-40'"
    >
      <SimilarButton :artist="firstArtist" :title="song.name" filled />
      <DownloadState :song="song" />
    </div>
  </div>
</template>

<script setup>
// A search result: full playback on the cover (from the library, else
// streamed) without downloading anything, and the wand next to the
// download button, styled like it (as on Charts).
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { setDragSongs } from '/src/lib/dragSongs'
import { useLibrary } from '/src/model/library'
import AppIcon from '../ui/AppIcon.vue'
import CoverArt from '../ui/CoverArt.vue'
import ExplicitBadge from '../ui/ExplicitBadge.vue'
import DownloadState from './DownloadState.vue'
import SimilarButton from '../similar/SimilarButton.vue'
import UiMenu from '../ui/UiMenu.vue'
import { usePlaylistActions } from '/src/model/playlistActions'
import { libraryOnly as libraryOnlyMode } from '/src/model/musicPolicy'
import { formatDuration } from '/src/lib/format'
import { useSongPlay } from '/src/model/songPlay'
import { useBuyLinks } from '/src/model/buyLinks'
import { buyTargetForSong } from '/src/lib/buyLinks'
import { localCatalogRoute } from '/src/lib/library'
import { usePlayer } from '/src/model/player'
import { useI18n } from '/src/i18n'

const props = defineProps({
  song: { type: Object, required: true },
  index: { type: Number, default: null },
  // The whole song list, for a mixed queue (downloaded rows from the
  // library, the rest streamed) the player works through to the end.
  songs: { type: Array, default: null },
  // A narrow column (next to the search's top result): no album column.
  compact: { type: Boolean, default: false },
})
const { t } = useI18n()
const player = usePlayer()
const buyLinks = useBuyLinks()
const playlistActions = usePlaylistActions()
const library = useLibrary()

// Playing works like every other track row: a downloaded song plays in
// full through the built-in player, anything else streams in full.
const play = useSongPlay(props)
const overlayIcon = computed(() =>
  play.isCurrent.value && player.isPlaying.value ? 'pause' : 'play'
)
const { toggle, ensurePlaying, warm } = play

const router = useRouter()
const contextMenu = ref(null)

// The row's menu (the + button, and a right click): add to a playlist -
// downloading it when needed - and go to its artist or album.
const menuItems = computed(() => {
  const items = []
  if (play.playable.value) {
    items.push({
      label: play.playLabel.value,
      icon: 'play',
      action: () => ensurePlaying(),
    })
  }
  if (!libraryOnlyMode.value) {
    items.push(...playlistActions.songMenuItems([props.song]))
  }
  const artist = artistLinks.value.find((item) => item.to)
  if (artist || albumTo.value) items.push({ divider: true })
  if (artist) {
    items.push({
      label: t('actions.goToArtist'),
      icon: 'user',
      action: () => router.push(artist.to),
    })
  }
  if (albumTo.value) {
    items.push({
      label: t('actions.goToAlbum'),
      icon: 'disc',
      action: () => router.push(albumTo.value),
    })
  }
  return items
})

function onDragStart(event) {
  const artist = (props.song.artists || [])[0] || props.song.artist
  const track = library.findTrack(artist, props.song.name)
  if (track?.file) setDragSongs(event, { files: [track.file] }, props.song.name)
  else setDragSongs(event, { songs: [props.song] }, props.song.name)
}

// On a touch screen a tap on the row plays it (a double click can't).
function onRowClick() {
  if (window.matchMedia('(pointer: coarse)').matches) toggle()
}

const artists = computed(
  () =>
    (props.song.artists || []).join(', ') ||
    props.song.artist ||
    t('common.unknownArtist')
)
// The album and each artist open their page: a library row's Library
// page, else the YouTube Music album / channel resolved like a pasted
// link (the Link page), as the album and artist cards below do.
function linkPage(url) {
  return url ? { name: 'Link', query: { url } } : null
}
const artistLinks = computed(() => {
  const urls = props.song.artist_urls || {}
  return (props.song.artists || []).map((name) => ({
    name,
    to:
      localCatalogRoute({ ...props.song, name }, 'artist') ||
      linkPage(urls[name]),
  }))
})
const albumTo = computed(
  () =>
    (props.song.album_name && localCatalogRoute(props.song, 'album')) ||
    linkPage(props.song.album_url)
)
const firstArtist = computed(
  () => (props.song.artists || [])[0] || props.song.artist || ''
)
const sourceUrl = computed(() => {
  const url = String(props.song.url || '')
  return /^https?:\/\//.test(url) ? url : ''
})
// Charts' Deezer tracks reuse this row; their link opens Deezer, not
// YouTube Music.
const openSourceLabel = computed(() =>
  props.song.source === 'deezer' ? t('link.openDeezer') : t('search.openSource')
)
</script>
