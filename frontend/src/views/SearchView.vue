<template>
  <div
    class="mx-auto flex max-w-[1680px] flex-col gap-8 px-4 pt-6 sm:px-6 md:pt-8 lg:px-10"
  >
    <template v-if="!query">
      <!-- Spotify's Search page: a big box, then everything to browse. -->
      <h1 class="text-display text-3xl font-bold sm:text-4xl">
        {{ t('search.title') }}
      </h1>
      <div class="-mt-4 flex flex-col gap-2.5">
        <button
          type="button"
          class="flex h-12 w-full max-w-2xl items-center gap-3 rounded-[10px] bg-invert px-4 text-left text-[15px] font-semibold text-on-invert/60 shadow-float transition-transform active:scale-[0.99]"
          @click="ui.focusSearch()"
        >
          <AppIcon name="search" :size="22" class="text-on-invert" />
          {{ t('search.whatToPlay') }}
        </button>
        <p class="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
          <AppIcon name="link" :size="14" class="shrink-0" />
          {{ t('search.linkHint') }}
          <span class="inline-flex items-center gap-1" aria-hidden="true">
            <AppIcon name="spotify" :size="14" class="text-spotify" />
            <AppIcon name="youtube-music" :size="14" class="text-src-ytm" />
            <AppIcon name="deezer" :size="14" class="text-deezer" />
            <AppIcon name="soundcloud" :size="14" class="text-src-soundcloud" />
          </span>
        </p>
      </div>
      <section v-if="recent.length" class="flex flex-col gap-3">
        <div class="flex items-center justify-between">
          <h2 class="text-display text-lg font-semibold">
            {{ t('search.recent') }}
          </h2>
          <button
            type="button"
            class="text-[13px] font-semibold text-muted hover:text-fg"
            @click="recent = []"
          >
            {{ t('common.clear') }}
          </button>
        </div>
        <div class="flex flex-wrap gap-2">
          <RouterLink
            v-for="term in recent"
            :key="term"
            :to="{ name: 'Search', params: { query: term } }"
            class="flex h-9 items-center gap-2 rounded-full bg-surface-2 px-3.5 text-sm text-fg-3 hover:bg-raised"
          >
            <AppIcon name="clock" :size="14" class="text-faint" />{{ term }}
          </RouterLink>
        </div>
      </section>

      <section class="flex flex-col gap-3">
        <h2 class="text-display text-lg font-semibold">
          {{ t('search.browseAll') }}
        </h2>
        <div
          class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
        >
          <component
            :is="tile.open ? 'button' : RouterLink"
            v-for="tile in browseTiles"
            :key="tile.id"
            :to="tile.open ? undefined : tile.to"
            :type="tile.open ? 'button' : undefined"
            @click="tile.open && openJamSheet()"
            class="group relative h-24 overflow-hidden rounded-[10px] p-3.5 text-left text-white transition-transform active:scale-[0.98] sm:h-28"
            :style="{ backgroundColor: tile.color }"
          >
            <span
              class="text-display relative z-10 block max-w-[75%] text-[17px] leading-tight font-bold text-balance"
              >{{ tile.label }}</span
            >
            <span
              class="absolute -right-2 -bottom-2 flex size-16 rotate-[25deg] items-center justify-center rounded-[8px] bg-black/20 shadow-lg transition-transform duration-300 group-hover:rotate-[18deg] sm:size-[4.5rem]"
              aria-hidden="true"
            >
              <AppIcon :name="tile.icon" :size="30" />
            </span>
          </component>
        </div>
      </section>
    </template>

    <template v-else>
      <div class="flex flex-col gap-4">
        <PageHeader
          :title="t('search.resultsFor', { query })"
          :subtitle="search.loading.value ? t('search.searching') : ''"
        />
        <UiChips v-model="filter" :items="filters" />
      </div>

      <div v-if="search.loading.value" class="flex flex-col gap-2">
        <div v-for="n in 6" :key="n" class="flex h-16 items-center gap-3 px-3">
          <UiSkeleton class="size-11 !rounded-[8px]" />
          <div class="flex flex-1 flex-col gap-2">
            <UiSkeleton class="h-3.5 w-1/3" />
            <UiSkeleton class="h-3 w-1/5" />
          </div>
        </div>
      </div>

      <UiEmpty
        v-else-if="search.error.value && !search.songs.value.length"
        icon="alert"
        :title="t('search.failed')"
        :body="search.error.value"
      >
        <UiButton icon="refresh" @click="search.searchFor(query)">{{
          t('common.retry')
        }}</UiButton>
      </UiEmpty>

      <UiEmpty
        v-else-if="!hasResults"
        icon="search"
        :title="t('search.noResults')"
        :body="t('search.noResultsHint')"
      />

      <template v-else>
        <!-- As on Spotify: the best hit next to the first songs. -->
        <div
          v-if="filter === 'all' && topResult"
          class="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]"
        >
          <section class="flex flex-col gap-3">
            <h2 class="text-display text-xl font-semibold">
              {{ t('search.topResult') }}
            </h2>
            <TopResult
              :key="topResultKey"
              :result="topResult"
              :songs="search.songs.value"
            />
          </section>
          <section
            v-if="search.songs.value.length"
            class="flex min-w-0 flex-col gap-3"
          >
            <h2 class="text-display text-xl font-semibold">
              {{ t('search.songs') }}
            </h2>
            <div class="-mx-3 flex flex-col">
              <SongRow
                v-for="song in topSongs"
                :key="song.song_id || song.url"
                compact
                :song="song"
                :songs="search.songs.value"
              />
            </div>
          </section>
        </div>

        <section
          v-if="filter === 'all' && libraryHits.length"
          class="flex flex-col gap-3"
        >
          <h2 class="text-display text-xl font-semibold">
            {{ t('search.inYourLibrary') }}
          </h2>
          <TrackList :tracks="libraryHits" />
        </section>

        <section
          v-if="
            show('songs') &&
            search.songs.value.length > (filter === 'all' ? topSongs.length : 0)
          "
          class="flex flex-col gap-3"
        >
          <h2
            v-if="filter === 'all' && !topResult"
            class="text-display text-xl font-semibold"
          >
            {{ t('search.songs') }}
          </h2>
          <div class="-mx-3 flex flex-col">
            <SongRow
              v-for="(song, i) in visibleSongs"
              :key="song.song_id || song.url"
              :song="song"
              :index="i + songOffset"
              :songs="search.songs.value"
            />
          </div>
          <button
            v-if="
              filter === 'all' &&
              search.songs.value.length > visibleSongs.length
            "
            type="button"
            class="self-start text-[13px] font-semibold text-muted hover:text-fg"
            @click="filter = 'songs'"
          >
            {{ t('search.showAllSongs', { count: search.songs.value.length }) }}
          </button>
        </section>

        <section
          v-if="show('albums') && search.albums.value.length"
          class="flex flex-col gap-4"
        >
          <h2
            v-if="filter === 'all'"
            class="text-display text-xl font-semibold"
          >
            {{ t('search.albums') }}
          </h2>
          <div
            class="grid grid-cols-2 gap-x-5 gap-y-7 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 2xl:grid-cols-6"
          >
            <ReleaseCard
              v-for="album in visibleAlbums"
              :key="album.album_id || album.url"
              :release="album"
            />
          </div>
        </section>

        <section
          v-if="show('artists') && search.artists.value.length"
          class="flex flex-col gap-4"
        >
          <h2
            v-if="filter === 'all'"
            class="text-display text-xl font-semibold"
          >
            {{ t('search.artists') }}
          </h2>
          <div
            class="grid grid-cols-2 gap-x-5 gap-y-7 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 2xl:grid-cols-6"
          >
            <ReleaseCard
              v-for="artist in visibleArtists"
              :key="artist.artist_id || artist.url"
              :release="withPhoto(artist)"
              :fallback="artist.cover_url"
              round
            />
          </div>
        </section>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useLocalStorage } from '@vueuse/core'
import AppIcon from '/src/components/ui/AppIcon.vue'
import UiButton from '/src/components/ui/UiButton.vue'
import UiChips from '/src/components/ui/UiChips.vue'
import UiEmpty from '/src/components/ui/UiEmpty.vue'
import UiSkeleton from '/src/components/ui/UiSkeleton.vue'
import PageHeader from '/src/components/library/PageHeader.vue'
import ReleaseCard from '/src/components/search/ReleaseCard.vue'
import SongRow from '/src/components/search/SongRow.vue'
import TopResult from '/src/components/search/TopResult.vue'
import TrackList from '/src/components/library/TrackList.vue'
import { pickTopResult } from '/src/lib/topResult'
import { useSearch } from '/src/model/search'
import { useLibrary } from '/src/model/library'
import { useUi } from '/src/model/ui'
import { useJamSheet } from '/src/model/jamSheet'
import { knownArtistPhoto } from '/src/lib/artistPhotoProxy'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const route = useRoute()
const search = useSearch()
const library = useLibrary()
const ui = useUi()
const { openJamSheet } = useJamSheet()
const filter = ref('all')
const recent = useLocalStorage('downtify-recent-searches', [])

watch(
  () => search.songs.value,
  (songs) => library.lookupSongs(songs)
)

const query = computed(() => String(route.params.query || '').trim())

watch(
  query,
  (value) => {
    filter.value = 'all'
    if (!value) return
    recent.value = [
      value,
      ...recent.value.filter((term) => term !== value),
    ].slice(0, 10)
    if (value !== search.query.value || !search.songs.value.length) {
      search.searchFor(value)
    }
  },
  { immediate: true }
)

const filters = computed(() => [
  { id: 'all', label: t('search.all') },
  { id: 'songs', label: t('search.songs'), count: search.songs.value.length },
  {
    id: 'albums',
    label: t('search.albums'),
    count: search.albums.value.length,
  },
  {
    id: 'artists',
    label: t('search.artists'),
    count: search.artists.value.length,
  },
])

function show(section) {
  return filter.value === 'all' || filter.value === section
}

const hasResults = computed(
  () =>
    search.songs.value.length ||
    search.albums.value.length ||
    search.artists.value.length ||
    libraryHits.value.length
)

// The first songs sit next to the top result; the list carries on below.
const TOP_SONGS = 4
const topResult = computed(() =>
  pickTopResult(query.value, {
    songs: search.songs.value,
    albums: search.albums.value,
    artists: search.artists.value,
  })
)
const topResultKey = computed(() => {
  const item = topResult.value?.item || {}
  return `${topResult.value?.kind}:${item.song_id || item.url || item.name}`
})
const topSongs = computed(() => search.songs.value.slice(0, TOP_SONGS))
const songOffset = computed(() =>
  filter.value === 'all' && topResult.value ? TOP_SONGS : 0
)
const visibleSongs = computed(() =>
  filter.value === 'all'
    ? search.songs.value.slice(songOffset.value, songOffset.value + 8)
    : search.songs.value
)

// Songs already in the library that match, wherever they came from (an
// extra folder, an old download): played straight from disk.
const libraryHits = ref([])
let librarySerial = 0
watch(
  query,
  async (value) => {
    const mine = ++librarySerial
    libraryHits.value = []
    if (!value) return
    try {
      const rows = await library.searchTracks(value, { limit: 5 })
      if (mine === librarySerial) libraryHits.value = rows
    } catch {
      // The online results stand on their own.
    }
  },
  { immediate: true }
)
const visibleAlbums = computed(() =>
  filter.value === 'all' ? search.albums.value.slice(0, 6) : search.albums.value
)
const visibleArtists = computed(() =>
  filter.value === 'all'
    ? search.artists.value.slice(0, 6)
    : search.artists.value
)

// An artist result shows the photo saved in the library when there is one,
// else its YouTube Music picture relayed by the photo proxy (Google's image
// CDN throttles a page's burst of hotlinked photos) - and that picture
// straight from YouTube Music if the proxy can't answer (`fallback`).
function withPhoto(artist) {
  return {
    ...artist,
    cover_url: knownArtistPhoto(artist.name, artist.cover_url).cover,
  }
}

// "Browse all": every place to go, each its own colour like Spotify's
// genre tiles - the way to Discover, Charts, Jam... on a phone too.
const browseTiles = computed(() => [
  {
    id: 'discover',
    label: t('nav.discover'),
    icon: 'sparkle',
    color: '#8d67ab',
    to: { name: 'Discover' },
  },
  {
    id: 'charts',
    label: t('nav.charts'),
    icon: 'trending',
    color: '#e8115b',
    to: { name: 'Charts' },
  },
  {
    id: 'jam',
    label: t('nav.jam'),
    icon: 'users',
    color: '#1e3264',
    to: { name: 'Jam' },
    open: true,
  },
  {
    id: 'liked',
    label: t('search.browseLibrary'),
    icon: 'library',
    color: '#148a08',
    to: { name: 'Library' },
  },
  {
    id: 'monitor',
    label: t('nav.monitor'),
    icon: 'radar',
    color: '#b06239',
    to: { name: 'Monitor' },
  },
  {
    id: 'queue',
    label: t('nav.queue'),
    icon: 'download',
    color: '#509bf5',
    to: { name: 'Queue' },
  },
])
</script>
