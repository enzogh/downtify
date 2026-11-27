<template>
  <div
    class="mx-auto flex max-w-[1680px] flex-col gap-9 px-4 pt-6 pb-10 sm:px-6 md:pt-8 lg:px-10"
  >
    <!-- Greeting, and what is downloading right now -->
    <header
      class="flex flex-wrap items-center justify-between gap-3 animate-rise"
    >
      <h1 class="text-display text-3xl font-bold sm:text-[34px]">
        {{ greeting }}
      </h1>
      <RouterLink
        v-if="pending"
        :to="{ name: 'Queue' }"
        class="flex h-9 items-center gap-2 rounded-full bg-surface-2 px-3.5 text-[13px] font-semibold text-fg-2 hover:bg-raised"
      >
        <AppIcon name="download" :size="15" class="text-accent" />
        {{ t('home.downloadingCount', { count: pending }) }}
      </RouterLink>
    </header>

    <!-- Quick access: what you play most, two to four a row -->
    <div
      v-if="quickAccess.length"
      class="grid grid-cols-2 gap-2 animate-rise md:grid-cols-3 xl:grid-cols-4"
      data-home-access
    >
      <HomeShortcut
        v-for="entry in quickAccess"
        :key="entry.id"
        :entry="entry"
        @play="favoriteActions.play($event)"
      />
    </div>

    <HomeRow
      v-if="madeForYou.length"
      :title="t('home.madeForYou')"
      :subtitle="t('home.madeForYouHint')"
    >
      <div
        v-for="mix in madeForYou"
        :key="mix.id"
        class="w-36 shrink-0 snap-start sm:w-44"
      >
        <MediaTile
          :to="{ name: 'Mix', params: { id: mix.id } }"
          :title="mix.title"
          :subtitle="mix.subtitle"
          :covers="mix.covers"
          :cover="mix.mosaic ? '' : mix.covers[0] || ''"
          :name="mix.title"
          icon="sparkle"
          :playing="isMixPlaying(mix)"
          @play="playMix(mix)"
        />
      </div>
    </HomeRow>

    <!-- Songs to try now: streamed until downloaded, each saying which
         artist of yours it comes from. -->
    <section
      v-if="suggested.length || (reco.loading.value && !reco.ready.value)"
      class="flex min-w-0 flex-col gap-3"
    >
      <div class="flex items-end justify-between gap-4">
        <div class="min-w-0">
          <h2 class="text-display truncate text-xl font-bold">
            {{ t('home.suggestedTitle') }}
          </h2>
          <p class="line-clamp-2 text-[13px] text-muted">
            {{ t('home.suggestedHint') }}
          </p>
        </div>
        <RouterLink
          v-if="suggested.length"
          :to="{ name: 'Mix', params: { id: 'foryou' } }"
          class="shrink-0 text-[13px] font-semibold text-muted hover:text-fg hover:underline"
          >{{ t('common.seeAll') }}</RouterLink
        >
      </div>
      <Transition name="reveal" mode="out-in">
        <UiSkeletonRows
          v-if="!suggested.length"
          :count="4"
          action
          :label="t('home.suggestedTitle')"
        />
        <div v-else class="-mx-3 grid gap-x-6 lg:grid-cols-2">
          <SongRow
            v-for="item in suggested"
            :key="item.key"
            :song="item.song"
            :songs="suggestedSongs"
            :note="reasonOf(item)"
            compact
          />
        </div>
      </Transition>
    </section>

    <HomeRow v-if="jumpBackIn.length" :title="t('home.jumpBackIn')">
      <div
        v-for="entry in jumpBackIn"
        :key="entry.id"
        class="w-36 shrink-0 snap-start sm:w-44"
      >
        <MediaTile
          :to="entry.route || { name: 'Home' }"
          :title="entry.title"
          :subtitle="entry.subtitle || t(`home.kind.${entry.type}`)"
          :cover="entry.cover || ''"
          :fallback="entry.fallback || ''"
          :covers="entry.covers || []"
          :name="entry.title"
          :round="entry.type === 'artist'"
          :icon="entryIcon(entry)"
          :playing="entry.playing"
          :playable="false"
        />
      </div>
    </HomeRow>

    <HomeRow
      v-if="recentPlaylists.length"
      :title="t('home.playlists')"
      :see-all="{ name: 'Library', params: { tab: 'playlists' } }"
    >
      <div
        v-for="playlist in recentPlaylists"
        :key="playlist.key"
        class="w-36 shrink-0 snap-start sm:w-44"
      >
        <MediaTile
          :to="{ name: 'Playlist', query: { name: playlist.name } }"
          :title="playlist.title"
          :subtitle="t('common.tracks', { count: itemTrackCount(playlist) })"
          :cover="playlist.cover"
          :covers="playlist.covers"
          :name="playlist.title"
          :icon="playlist.liked ? 'heart' : 'playlist'"
          :symbol="playlist.liked"
          @play="playlistActions.play(playlist)"
        />
      </div>
    </HomeRow>

    <HomeRow
      v-if="recentAlbums.length"
      :title="t('home.recentlyAdded')"
      :see-all="{ name: 'Library', params: { tab: 'albums' } }"
    >
      <div
        v-for="album in recentAlbums"
        :key="album.key"
        class="w-36 shrink-0 snap-start sm:w-44"
      >
        <MediaTile
          :to="{
            name: 'Album',
            query: { artist: album.artist, title: album.title },
          }"
          :title="album.title"
          :subtitle="[album.artist, album.year].filter(Boolean).join(' · ')"
          :cover="album.cover"
          :name="album.title"
          @play="playAlbum(album)"
        />
      </div>
    </HomeRow>

    <HomeRow
      v-if="topArtists.length"
      :title="t('home.yourArtists')"
      :see-all="{ name: 'Library', params: { tab: 'artists' } }"
    >
      <div
        v-for="artist in topArtists"
        :key="artist.name"
        class="w-36 shrink-0 snap-start sm:w-44"
      >
        <MediaTile
          :to="{ name: 'Artist', query: { name: artist.name } }"
          :title="artist.name"
          :subtitle="t('search.artist')"
          :cover="artist.cover"
          :fallback="artist.fallback"
          :name="artist.name"
          round
          icon="user"
          :playable="false"
        />
      </div>
    </HomeRow>

    <!-- First run: the search bar takes links as well as words -->
    <section
      v-if="library.loaded.value && !library.trackCount.value"
      class="grid gap-4 md:grid-cols-3"
    >
      <div
        v-for="(step, i) in onboarding"
        :key="step.title"
        class="flex flex-col gap-2 rounded-panel border border-dashed border-line-3 p-5"
      >
        <span class="text-display tabular text-sm font-semibold text-accent"
          >0{{ i + 1 }}</span
        >
        <p class="text-[15px] font-semibold">{{ step.title }}</p>
        <p class="text-[13px] text-pretty text-muted">{{ step.body }}</p>
      </div>
    </section>
  </div>
</template>

<script setup>
// Home, laid out like Spotify's: a greeting, quick access to what you
// play, then rows that scroll sideways - your mixes, what you played,
// your playlists, what was added, your artists. Links go in the search
// bar at the top, which takes them as well as words.
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from '/src/components/ui/AppIcon.vue'
import HomeRow from '/src/components/home/HomeRow.vue'
import HomeShortcut from '/src/components/home/HomeShortcut.vue'
import MediaTile from '/src/components/library/MediaTile.vue'
import { useProgressTracker } from '/src/model/download'
import { useHistory } from '/src/model/history'
import { useLibrary } from '/src/model/library'
import { useLikes } from '/src/model/likes'
import { useListening } from '/src/model/listening'
import { useMixes } from '/src/model/mixes'
import { listCovers, useRecommendations } from '/src/model/recommendations'
import { songToPlayerTrack } from '/src/model/songPlay'
import SongRow from '/src/components/search/SongRow.vue'
import UiSkeletonRows from '/src/components/ui/UiSkeletonRows.vue'
import { usePlayer } from '/src/model/player'
import { usePlaylistActions } from '/src/model/playlistActions'
import { useTrackActions } from '/src/model/trackActions'
import { itemTrackCount } from '/src/lib/library'
import { useOffline } from '/src/model/offline'
import { mixSeeds } from '/src/lib/mixes'
import { artistPhotoSource } from '/src/lib/artistPhotoProxy'
import API from '/src/model/api'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const library = useLibrary()
const history = useHistory()
const likes = useLikes()
const listening = useListening()
const mixes = useMixes()
const player = usePlayer()
const tracker = useProgressTracker()
const actions = useTrackActions()
const playlistActions = usePlaylistActions()
const offline = useOffline()
const reco = useRecommendations()
const favoriteActions = playlistActions

const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 5) return t('home.greetingNight')
  if (hour < 12) return t('home.greetingMorning')
  if (hour < 18) return t('home.greetingAfternoon')
  return t('home.greetingEvening')
})

const pending = computed(() => {
  tracker.queueVersion.value
  return tracker.downloadQueue.value.filter((item) =>
    ['active', 'queued'].includes(item.state)
  ).length
})

// The mixes and your artists need every song, which the Home summary
// alone doesn't load: fetched once the page is idle.
onMounted(() => {
  const later = window.requestIdleCallback || ((fn) => setTimeout(fn, 600))
  later(() => {
    mixes.ensure()
    reco.ensure()
  })
})

function isPlaying(entry) {
  const ctx = player.context.value
  return (
    player.isPlaying.value &&
    ctx?.type === entry.type &&
    ctx?.title === entry.title
  )
}

function entryIcon(entry) {
  if (entry.type === 'artist') return 'user'
  if (entry.type === 'playlist') return 'playlist'
  if (entry.type === 'mix') return 'sparkle'
  return 'disc'
}

// Saved artist photos (artist page picker), asked once per set of names.
const artistPhotos = ref({})
const artistPhotosLoaded = ref(false)

// An artist played from their page was remembered with a cover of one of
// their albums: shown with the artist's photo instead, like "Your artists".
function artistEntry(entry) {
  const name = String(entry.title || '')
  return {
    ...entry,
    covers: [],
    ...artistPhotoSource(
      name,
      artistPhotos.value[name],
      artistPhotosLoaded.value
    ),
  }
}

const jumpBackIn = computed(() =>
  history.recent.value
    .map((entry) => {
      if (entry.type === 'artist') return artistEntry(entry)
      if (entry.type !== 'playlist') return entry
      const name = String(entry.route?.query?.name || entry.title || '')
      const live = library.findPlaylist(name)
      if (!live) return null
      return {
        ...entry,
        title: live.title,
        cover: live.cover || live.covers[0] || entry.cover || '',
        covers: live.covers,
        route: { name: 'Playlist', query: { name: live.name } },
        playlist: live,
      }
    })
    .filter(Boolean)
    .map((entry) => ({ ...entry, playing: isPlaying(entry) }))
)

function playlistEntry(playlist) {
  return {
    id: `playlist:${playlist.key}`,
    type: 'playlist',
    title: playlist.title,
    subtitle: t('common.tracks', { count: itemTrackCount(playlist) }),
    cover: playlist.cover,
    covers: playlist.covers,
    route: { name: 'Playlist', query: { name: playlist.name } },
    playlist,
    playing: isPlaying({ type: 'playlist', title: playlist.title }),
  }
}

// Up to eight: liked songs and pinned playlists first, then what you
// played lately, then your newest playlists - each once.
const quickAccess = computed(() => {
  const own = library.ownPlaylists.value
  // Songs kept on this device (listening without a network), once any are.
  const saved = offline.savedFiles.value.size
  const candidates = [
    ...(saved
      ? [
          {
            id: 'offline',
            type: 'offline',
            icon: 'arrow-down-to-line',
            title: t('offline.title'),
            subtitle: t('common.tracks', { count: saved }),
            route: { name: 'Offline' },
          },
        ]
      : []),
    ...own.filter((playlist) => playlist.liked && itemTrackCount(playlist)),
    ...library.playlists.value.filter((playlist) => playlist.favorite),
  ].map(playlistEntry)
  for (const entry of jumpBackIn.value) {
    candidates.push({ ...entry, id: `${entry.type}:${entry.id}` })
  }
  candidates.push(
    ...[...own]
      .filter((playlist) => itemTrackCount(playlist))
      .sort((a, b) => b.added - a.added)
      .map(playlistEntry)
  )
  const seen = new Set()
  const picked = []
  for (const entry of candidates) {
    const key = JSON.stringify(entry.route || entry.id)
    if (seen.has(key)) continue
    seen.add(key)
    picked.push(entry)
    if (picked.length >= 8) break
  }
  return picked
})

const recentPlaylists = computed(() =>
  [...library.ownPlaylists.value]
    .filter((playlist) => itemTrackCount(playlist))
    .sort((a, b) => Number(b.liked) - Number(a.liked) || b.added - a.added)
    .slice(0, 12)
)

const recentAlbums = computed(() =>
  [...library.albums.value].sort((a, b) => b.added - a.added).slice(0, 12)
)

const artistsByName = computed(
  () =>
    new Map(
      library.artists.value.map((artist) => [
        String(artist.name || '').toLowerCase(),
        artist,
      ])
    )
)

// The artists you play (or like, or have the most of).
const topArtistSeeds = computed(() => {
  if (!library.tracksComplete.value) return []
  return mixSeeds(library.tracks.value, {
    plays: listening.plays.value,
    liked: likes.liked.value,
    count: 12,
  })
})

// Their saved photos, and those of the artists in "Jump back in" (and
// the quick access above it), asked once per set of names, as the
// Library's artists tab does.
const photoNames = computed(() => {
  const names = new Set(topArtistSeeds.value.map((seed) => seed.name))
  for (const entry of history.recent.value) {
    if (entry.type === 'artist' && entry.title) names.add(entry.title)
  }
  return [...names]
})
watch(
  () => photoNames.value.join('\n'),
  async (joined) => {
    if (!joined) return
    try {
      const res = await API.getArtistArtBulk(joined.split('\n'))
      artistPhotos.value = res.data || {}
    } catch {
      artistPhotos.value = {}
    }
    artistPhotosLoaded.value = true
  },
  { immediate: true }
)

// Each with their photo: the saved one, else the display-only proxy's.
// Behind it, a cover of a song of their own - never one they only guest
// on, which is another artist's artwork.
const topArtists = computed(() =>
  topArtistSeeds.value.map((seed) => {
    const own = seed.tracks.find((track) => track.hasCover)?.cover || ''
    const found = artistsByName.value.get(seed.name.toLowerCase())
    return {
      name: seed.name,
      ...artistPhotoSource(
        seed.name,
        artistPhotos.value[seed.name],
        artistPhotosLoaded.value,
        own || found?.cover || ''
      ),
    }
  })
)

const madeForYou = computed(() => {
  const made = mixes.mixes.value.map((mix) => ({
    id: mix.id,
    title: t('home.dailyMix', { n: mix.number }),
    subtitle: mix.artists.join(', '),
    covers: mix.covers,
    mix,
  }))
  const repeat = mixes.repeat.value
  if (repeat.length >= 5) {
    made.unshift({
      id: 'repeat',
      title: t('home.onRepeat'),
      subtitle: t('home.onRepeatHint'),
      covers: repeat
        .filter((track) => track.hasCover && track.cover)
        .map((track) => track.cover)
        .filter((cover, i, all) => all.indexOf(cover) === i)
        .slice(0, 4),
      tracks: repeat,
    })
  }
  // The recommendations lead: what is new comes first.
  // Each a mosaic of its own songs, so the two never look alike.
  const discover = reco.discover.value
  const discoverCovers = listCovers(discover)
  const forYou = reco.forYou.value
  if (forYou.length >= 5) {
    made.unshift({
      id: 'foryou',
      title: t('home.forYouMix'),
      subtitle: t('home.forYouMixHint'),
      mosaic: true,
      covers: listCovers(
        forYou.filter((item) => !discoverCovers.includes(item.song?.cover_url))
      ),
      tracks: forYou.map((item) =>
        songToPlayerTrack(item.song, library.findTrack)
      ),
    })
  }
  if (discover.length >= 5) {
    made.unshift({
      id: 'discover',
      title: t('home.discoverMix'),
      subtitle: t('home.discoverMixHint'),
      mosaic: true,
      covers: listCovers(discover),
      tracks: discover.map((item) =>
        songToPlayerTrack(item.song, library.findTrack)
      ),
    })
  }
  return made
})

// A few songs to try right away, under the mixes.
// One song you already stream at most: this is for finding new ones.
const suggested = computed(() => {
  let again = 0
  return reco.forYou.value
    .filter((item) => item.kind !== 'again' || again++ < 1)
    .slice(0, 6)
})
const suggestedSongs = computed(() => suggested.value.map((item) => item.song))

/** Why a song is suggested, in a few words. */
function reasonOf(item) {
  if (item.kind === 'again') return t('reco.again')
  return item.because ? t('reco.because', { artist: item.because }) : ''
}

function isMixPlaying(mix) {
  const ctx = player.context.value
  return (
    player.isPlaying.value && ctx?.type === 'mix' && ctx.title === mix.title
  )
}

function playMix(mix) {
  if (isMixPlaying(mix)) {
    player.pause()
    return
  }
  const queue = mix.mix ? mixes.queueOf(mix.mix) : mix.tracks
  if (!queue.length) return
  // Not remembered in "Jump back in": a mix changes every day.
  player.setPlaylist(queue, {
    startIndex: 0,
    context: {
      type: 'mix',
      title: mix.title,
      route: { name: 'Mix', params: { id: mix.id } },
    },
  })
}

async function playAlbum(album) {
  await library.loadArtistTracks(album.artist)
  const live = library.findAlbum(album.artist, album.title) || album
  if (!live.tracks.length) return
  actions.play(live.tracks, 0, {
    type: 'album',
    title: live.title,
    subtitle: live.artist,
    cover: live.cover,
    route: {
      name: 'Album',
      query: { artist: live.artist, title: live.title },
    },
  })
}

const onboarding = computed(() => [
  { title: t('home.step1Title'), body: t('home.step1Body') },
  { title: t('home.step2Title'), body: t('home.step2Body') },
  { title: t('home.step3Title'), body: t('home.step3Body') },
])
</script>
