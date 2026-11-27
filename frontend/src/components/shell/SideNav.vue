<template>
  <aside
    class="sticky top-0 h-dvh shrink-0 flex-col gap-5 overflow-hidden border-r border-line bg-side px-3 py-6 transition-[width] duration-300 ease-out-soft"
    :class="collapsed ? 'w-[72px]' : 'w-[72px] xl:w-[248px] xl:px-4'"
  >
    <div class="flex items-center gap-2.5 px-2.5">
      <RouterLink
        :to="{ name: 'Home' }"
        class="flex items-center gap-2.5"
        :title="t('nav.home')"
      >
        <AppLogo :size="28" />
        <span class="text-display text-[19px] font-bold" :class="labelClass"
          >Castify</span
        >
      </RouterLink>
    </div>

    <nav class="flex flex-col gap-0.5" :aria-label="t('nav.main')">
      <RouterLink
        v-for="item in items"
        :key="item.name"
        :to="{ name: item.name }"
        class="group relative flex h-10 items-center gap-3 rounded-control px-3 text-sm transition-colors"
        :class="
          isActive(item)
            ? 'bg-surface-2 font-semibold text-fg'
            : 'font-medium text-muted hover:bg-surface-2/60 hover:text-fg'
        "
        :title="t(item.label)"
      >
        <AppIcon
          :name="item.icon"
          :size="18"
          :class="isActive(item) ? 'text-accent' : ''"
        />
        <span :class="labelClass">{{ t(item.label) }}</span>
        <span
          v-if="item.name === 'Queue' && pending"
          class="tabular flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[11px] font-bold"
          :class="[
            collapsed
              ? 'absolute top-0.5 right-0.5 h-4 min-w-4 px-1 text-[10px]'
              : 'absolute top-0.5 right-0.5 h-4 min-w-4 px-1 text-[10px] xl:static xl:ml-auto xl:h-5 xl:min-w-5 xl:px-1.5 xl:text-[11px]',
            queuePaused
              ? 'bg-surface-2 text-muted'
              : 'bg-accent text-on-accent',
          ]"
          :title="queuePaused ? t('queue.pausedTitle') : undefined"
          >{{ pending }}</span
        >
      </RouterLink>
    </nav>

    <!-- Your playlists, as on Spotify: the one part that scrolls, so the
         pages above and the account below always stay in reach. Narrow
         (tablet, or collapsed) it keeps the covers, named on hover. -->
    <section
      class="-mx-1 flex min-h-0 flex-1 flex-col border-t border-line pt-4"
      :aria-label="t('nav.playlists')"
    >
      <div
        class="flex items-center gap-1 px-3 pb-2"
        :class="
          collapsed ? 'justify-center' : 'justify-center xl:justify-between'
        "
      >
        <RouterLink
          :to="{ name: 'Library', params: { tab: 'playlists' } }"
          class="eyebrow hover:text-fg"
          :class="labelClass"
          >{{ t('nav.playlists') }}</RouterLink
        >
        <button
          type="button"
          class="press transition-press flex size-8 shrink-0 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          :title="t('playlists.create')"
          :aria-label="t('playlists.create')"
          @click="playlistActions.openCreate()"
        >
          <AppIcon name="plus" :size="18" />
        </button>
      </div>
      <div
        class="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto overscroll-contain px-1 pb-2 [scrollbar-width:thin]"
      >
        <RouterLink
          v-for="playlist in navPlaylists"
          :key="playlist.key"
          :to="{ name: 'Playlist', query: { name: playlist.name } }"
          class="flex h-12 shrink-0 items-center gap-2.5 rounded-control px-2 transition-colors"
          :class="[
            rowAlign,
            dropTarget === playlist.key
              ? 'bg-accent/15 ring-2 ring-accent ring-inset'
              : isOpen(playlist)
                ? 'bg-surface-2'
                : 'hover:bg-surface-2/60',
          ]"
          :title="playlist.title"
          :aria-current="isOpen(playlist) ? 'page' : undefined"
          @dragover="onDragOver($event, playlist)"
          @dragleave="onDragLeave(playlist)"
          @drop="onDrop($event, playlist)"
        >
          <CoverArt
            :thumb="150"
            :src="playlist.cover"
            :covers="playlist.covers"
            :name="playlist.title"
            rounded="rounded-[7px]"
            :letter-size="13"
            :icon-size="16"
            :icon="playlist.liked ? 'heart' : 'playlist'"
            :symbol="playlist.liked"
            class="size-9 shrink-0"
          />
          <span class="min-w-0 flex-col" :class="labelFlex">
            <span
              class="truncate text-[13px] font-medium"
              :class="isPlaying(playlist) ? 'text-accent' : 'text-fg-2'"
              >{{ playlist.title }}</span
            >
            <span class="truncate text-[11px] text-faint">{{
              playlist.shared
                ? playlist.owner
                : t('common.tracks', { count: itemTrackCount(playlist) })
            }}</span>
          </span>
          <!-- Its own visibility class: the label's (inline, truncated)
               clipped the bars down to a single jittering one. -->
          <EqBars
            v-if="isPlaying(playlist)"
            :size="12"
            :playing="player.isAdvancing?.value !== false"
            class="mr-1 shrink-0"
            :class="markClass('bars')"
          />
          <span
            v-else-if="playlist.isNew"
            class="mr-1 size-2 shrink-0 rounded-full bg-accent"
            :class="markClass('dot')"
            :title="t('sharing.new')"
          />
        </RouterLink>
      </div>
    </section>

    <div class="flex shrink-0 flex-col gap-0.5">
      <a
        v-if="update?.update_available"
        :href="update.release_url"
        target="_blank"
        rel="noopener"
        class="mb-2 flex items-center gap-2.5 rounded-control bg-accent/12 px-3 py-2 text-[13px] font-semibold text-accent"
        :title="t('nav.updateAvailable', { version: update.latest_version })"
      >
        <AppIcon name="sparkle" :size="17" />
        <span :class="labelClass">{{
          t('nav.updateAvailable', { version: update.latest_version })
        }}</span>
      </a>
      <RouterLink
        :to="{ name: 'Settings' }"
        class="flex h-10 items-center gap-3 rounded-control px-3 text-sm transition-colors"
        :class="
          route.name === 'Settings'
            ? 'bg-surface-2 font-semibold text-fg'
            : 'font-medium text-muted hover:bg-surface-2/60 hover:text-fg'
        "
        :title="t('nav.settings')"
      >
        <AppIcon
          name="settings"
          :size="18"
          :class="route.name === 'Settings' ? 'text-accent' : ''"
        />
        <span :class="labelClass">{{ t('nav.settings') }}</span>
      </RouterLink>
      <button
        v-if="auth.user.value && !auth.authDisabled.value"
        type="button"
        class="flex h-10 items-center gap-3 rounded-control px-3 text-left text-sm font-medium text-muted transition-colors hover:bg-surface-2/60 hover:text-fg"
        :title="t('nav.signOutAs', { name: auth.user.value.username })"
        @click="auth.signOut"
      >
        <AppIcon name="log-out" :size="18" />
        <span :class="labelClass">{{ t('nav.signOut') }}</span>
        <span
          class="truncate text-[12px] text-faint"
          :class="collapsed ? 'hidden' : 'hidden xl:inline'"
          >{{ auth.user.value.username }}</span
        >
      </button>
      <button
        type="button"
        class="hidden h-10 items-center gap-3 rounded-control px-3 text-left text-sm font-medium text-faint transition-colors hover:bg-surface-2/60 hover:text-fg xl:flex"
        :title="collapsed ? t('nav.expand') : t('nav.collapse')"
        @click="collapsed = !collapsed"
      >
        <AppIcon name="panel-left" :size="18" />
        <span :class="labelClass">{{ t('nav.collapse') }}</span>
      </button>
      <p
        v-if="version"
        class="tabular px-3 pt-2 text-[11px] text-faint"
        :class="labelClass"
      >
        Castify {{ version }}
      </p>
    </div>
  </aside>
</template>

<script setup>
import { useJamSheet } from '/src/model/jamSheet'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useLocalStorage } from '@vueuse/core'
import AppIcon from '../ui/AppIcon.vue'
import AppLogo from '../ui/AppLogo.vue'
import CoverArt from '../ui/CoverArt.vue'
import EqBars from '../ui/EqBars.vue'
import { useI18n } from '/src/i18n'
import { itemTrackCount } from '/src/lib/library'
import { useAuth } from '/src/model/auth'
import { useLibrary } from '/src/model/library'
import { useQueuePause } from '/src/model/queuePause'
import { useUpdateCheck } from '/src/model/updateCheck'
import { usePendingCount } from './navState'
import { usePlaylistActions } from '/src/model/playlistActions'
import { isSongDrag, readDragSongs } from '/src/lib/dragSongs'
import { useMyPlaylists } from '/src/model/myPlaylists'
import { usePlayer } from '/src/model/player'

const { t } = useI18n()
const playlistActions = usePlaylistActions()
const route = useRoute()
const jamSheet = useJamSheet()
const library = useLibrary()
const myPlaylists = useMyPlaylists()
const auth = useAuth()
const player = usePlayer()
const pending = usePendingCount()
const queuePaused = useQueuePause().paused
const update = useUpdateCheck().status
const collapsed = useLocalStorage('downtify-sidebar-collapsed', false)
const version = computed(() => {
  const v = localStorage.getItem('version')
  return v && v !== '0.0.0' ? v : ''
})

const items = [
  { name: 'Home', icon: 'home', label: 'nav.home' },
  {
    name: 'Search',
    icon: 'search',
    label: 'nav.search',
    match: ['Link', 'TopSongs'],
  },
  {
    name: 'Library',
    icon: 'library',
    label: 'nav.library',
    match: ['Album', 'Artist', 'Playlist'],
  },
  { name: 'Queue', icon: 'download', label: 'nav.queue' },
  { name: 'Jam', icon: 'users', label: 'nav.jam' },
  {
    name: 'Discover',
    icon: 'sparkle',
    label: 'nav.discover',
    match: ['FinderBrowse'],
  },
  {
    name: 'Monitor',
    icon: 'radar',
    label: 'nav.monitor',
    match: ['MonitorWatch'],
  },
  { name: 'Charts', icon: 'trending', label: 'nav.charts' },
]

function isActive(item) {
  // The Jam is a sheet, not a page: lit while it is open.
  if (item.name === 'Jam') return jamSheet.open.value
  return route.name === item.name || (item.match || []).includes(route.name)
}

const labelClass = computed(() =>
  collapsed.value ? 'hidden' : 'hidden xl:inline xl:flex-1 xl:truncate'
)
// The mark at the end of a playlist row, shown with the labels but in
// its own display (the label's inline/truncate clipped it): the playing
// bars are a flex row, the "new" dot a block. Full class names, so
// Tailwind sees them.
const MARK_DISPLAY = {
  bars: 'hidden xl:inline-flex',
  dot: 'hidden xl:block',
}
function markClass(kind) {
  return collapsed.value ? 'hidden' : MARK_DISPLAY[kind]
}
// A playlist row's title block, and its alignment: centred on the cover
// while the bar is narrow.
const labelFlex = computed(() =>
  collapsed.value ? 'hidden' : 'hidden xl:flex xl:flex-1'
)
const rowAlign = computed(() =>
  collapsed.value ? 'justify-center' : 'justify-center xl:justify-start'
)

function isOpen(playlist) {
  return route.name === 'Playlist' && route.query.name === playlist.name
}

function isPlaying(playlist) {
  const ctx = player.context.value
  return (
    player.isPlaying?.value !== false &&
    ctx?.type === 'playlist' &&
    ctx?.title === playlist.title
  )
}

// Songs dragged from a list are dropped on a playlist here, as on
// Spotify: library files go in at once, the rest download first.
const dropTarget = ref('')

function onDragOver(event, playlist) {
  if (!playlist.canEditTracks || !isSongDrag(event)) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'copy'
  dropTarget.value = playlist.key
}

function onDragLeave(playlist) {
  if (dropTarget.value === playlist.key) dropTarget.value = ''
}

async function onDrop(event, playlist) {
  dropTarget.value = ''
  if (!playlist.canEditTracks) return
  const dropped = readDragSongs(event)
  if (!dropped) return
  event.preventDefault()
  await playlistActions.addDropped(playlist, dropped)
}

// Every playlist of the user's own (an admin may open everyone's, but
// "See all" is where those are; watched ones included), liked songs
// first, then the newest; then what was shared with them (new ones
// first) and the public ones they follow.
const NAV_PLAYLISTS_MAX = 80
const navPlaylists = computed(() => {
  const own = [...myPlaylists.value]
    // An empty Library playlist stays listed: songs can be dropped on it;
    // so does a watch still downloading its first songs.
    .filter(
      (playlist) =>
        itemTrackCount(playlist) || playlist.manual || playlist.batch
    )
    .sort((a, b) => Number(b.liked) - Number(a.liked) || b.added - a.added)
  const shared = [
    ...library.sharedPlaylists.value,
    ...library.publicPlaylists.value.filter((playlist) => playlist.followed),
  ]
    .sort((a, b) => Number(b.isNew) - Number(a.isNew))
    .map((playlist) => ({ ...playlist, shared: true }))
  const seen = new Set()
  return [...own, ...shared]
    .filter((playlist) => !seen.has(playlist.key) && seen.add(playlist.key))
    .slice(0, NAV_PLAYLISTS_MAX)
})
</script>
