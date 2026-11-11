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
          :cover="mix.covers[0] || ''"
          :name="mix.title"
          icon="sparkle"
          :playing="isMixPlaying(mix)"
          @play="playMix(mix)"
        />
      </div>
    </HomeRow>

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
import { computed, onMounted } from 'vue'
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
import { usePlayer } from '/src/model/player'
import { usePlaylistActions } from '/src/model/playlistActions'
import { useTrackActions } from '/src/model/trackActions'
import { itemTrackCount } from '/src/lib/library'
import { useOffline } from '/src/model/offline'
import { mixSeeds } from '/src/lib/mixes'
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
  later(() => mixes.ensure())
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

const jumpBackIn = computed(() =>
  history.recent.value
    .map((entry) => {
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

// The artists you play (or like, or have the most of), with their photo.
const topArtists = computed(() => {
  if (!library.tracksComplete.value) return []
  return mixSeeds(library.tracks.value, {
    plays: listening.plays.value,
    liked: likes.liked.value,
    count: 12,
  }).map((seed) => {
    const found = artistsByName.value.get(seed.name.toLowerCase())
    return {
      name: seed.name,
      cover:
        found?.cover ||
        seed.tracks.find((track) => track.hasCover)?.cover ||
        '',
    }
  })
})

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
  return made
})

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
