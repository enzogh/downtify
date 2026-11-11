<template>
  <Transition name="now-playing">
    <div
      v-if="track && !nowPlaying.isOpen.value"
      class="relative flex h-16 items-center gap-3 overflow-hidden rounded-[16px] border border-line-3 bg-glass pr-2 pl-2 shadow-float backdrop-blur-xl md:h-[76px] md:gap-5 md:rounded-[18px] md:pr-5 md:pl-3"
    >
      <!-- Progress: a hairline on phones, a scrubber on desktop. -->
      <div class="absolute inset-x-3 bottom-0 h-0.5 bg-line-2 md:hidden">
        <div class="h-full bg-accent" :style="{ width: `${smoothPercent}%` }" />
      </div>
      <!-- Waiting on the song: a sweep along the progress line says it's
           on its way (the bar itself holds still meanwhile). -->
      <Transition name="fade">
        <div
          v-if="loading.visible.value"
          class="pointer-events-none absolute inset-x-3 bottom-0 h-0.5 overflow-hidden md:inset-x-0 md:top-0 md:bottom-auto"
          aria-hidden="true"
        >
          <div class="mini-loading-sweep h-full w-1/3 rounded-full bg-accent" />
        </div>
      </Transition>
      <div class="absolute inset-x-0 -top-2 hidden md:block">
        <SliderBar
          :model-value="scrub ?? player.currentTime.value"
          :max="player.duration.value || 1"
          :label="t('player.seek')"
          :value-text="formatDuration(player.currentTime.value)"
          :hit-height="16"
          :playing="player.isAdvancing.value"
          track-class="bg-transparent"
          fill-class="bg-accent"
          thumb-class="bg-accent"
          @update:model-value="(v) => (scrub = v)"
          @commit="commitSeek"
        />
      </div>

      <!-- The heart sits beside the button that opens Now playing, not
           inside it, so tapping it never opens the overlay. -->
      <!-- Desktop: three columns like Spotify's (28 / 40 / 32 %, the
           right one holds more), so the sides grow and shrink with the
           window instead of overflowing. -->
      <div
        class="flex min-w-0 flex-1 items-center gap-1 md:w-[28%] md:min-w-[180px] md:flex-none"
      >
        <!-- Phones: swipe this sideways to skip, hold it for the
             song's menu (useMiniGestures). -->
        <button
          type="button"
          class="flex min-w-0 flex-1 touch-pan-y items-center gap-3 text-left transition-transform duration-150 select-none [-webkit-touch-callout:none]"
          :style="
            gestures.shift.value
              ? {
                  transform: `translateX(${gestures.shift.value}px)`,
                  transition: 'none',
                }
              : null
          "
          :aria-label="t('player.openNowPlaying')"
          v-on="gestures.handlers"
          @click="gestures.allowClick() && nowPlaying.open()"
        >
          <CoverArt
            :thumb="150"
            :src="track.hasCover ? track.cover : ''"
            :name="track.album || track.title"
            rounded="rounded-[10px]"
            :letter-size="18"
            :icon-size="18"
            class="size-11 md:size-[52px]"
          />
          <span class="flex min-w-0 flex-col">
            <span class="flex items-center gap-2">
              <span class="truncate text-sm font-semibold">{{
                track.title
              }}</span>
              <ExplicitBadge v-if="track.explicit" />
              <EqBars
                v-if="player.isPlaying.value"
                :size="10"
                :playing="player.isAdvancing.value"
                class="max-md:hidden"
              />
            </span>
            <span
              v-if="player.playError.value"
              class="truncate text-xs font-medium text-danger"
              role="alert"
            >
              {{ t('player.cannotPlaySong') }}
            </span>
            <span
              v-else-if="loading.labelKey.value"
              class="truncate text-xs font-medium text-accent"
              role="status"
            >
              {{ t(loading.labelKey.value) }}
            </span>
            <span v-else class="truncate text-xs text-muted">
              {{ [track.artist, track.album].filter(Boolean).join(' · ') }}
            </span>
          </span>
        </button>
        <span class="hidden">
          <UiMenu
            ref="songMenu"
            :items="songMenuItems"
            :label="t('common.more')"
          />
        </span>
        <!-- Phones have no room for it beside the transport buttons;
             the rows and the full player carry the heart there. -->
        <span
          v-if="!track?.isPodcast && !track?.stream"
          class="hidden sm:contents"
          ><LikeButton :file="track.file"
        /></span>
      </div>

      <div
        class="flex items-center justify-center gap-1 md:min-w-0 md:flex-1 md:gap-2 lg:gap-3"
      >
        <UiIconButton
          icon="shuffle"
          :label="t('player.shuffle')"
          :active="player.shuffle.value"
          toggle
          class="max-lg:hidden"
          @click="player.toggleShuffle()"
        />
        <UiIconButton
          icon="prev"
          :label="t('player.previous')"
          class="max-md:hidden"
          @click="player.prev()"
        />
        <DevicesButton v-if="auth.user.value" class="md:hidden" />
        <button
          type="button"
          class="flex size-11 items-center justify-center rounded-full text-fg md:bg-invert md:text-on-invert md:transition-transform md:hover:scale-105"
          :aria-label="
            player.playError.value
              ? t('common.retry')
              : player.isPlaying.value
                ? t('player.pause')
                : t('player.play')
          "
          :aria-busy="loading.visible.value"
          @click="player.playError.value ? player.retry() : player.toggle()"
        >
          <AppIcon
            v-if="player.playError.value"
            name="refresh"
            :size="18"
            class="text-danger md:text-current"
          />
          <span
            v-else-if="loading.visible.value"
            class="size-4 animate-spin rounded-full border-2 border-current border-r-transparent"
          />
          <AppIcon
            v-else
            :name="player.isPlaying.value ? 'pause' : 'play'"
            :size="18"
          />
        </button>
        <UiIconButton
          icon="next"
          :label="t('player.next')"
          @click="player.next()"
        />
        <UiIconButton
          :icon="player.repeatMode.value === 'one' ? 'repeat-one' : 'repeat'"
          :label="repeatLabel"
          :active="player.repeatMode.value !== 'off'"
          toggle
          class="max-lg:hidden"
          @click="player.cycleRepeat()"
        />
        <UiIconButton
          v-if="showMiniDownload"
          :icon="downloadBusy ? 'refresh' : 'download'"
          :label="t('actions.downloadItem', { name: trackTitle })"
          :disabled="downloadBusy"
          :class="downloadBusy ? '[&_svg]:animate-spin' : ''"
          @click="downloadCurrent"
        />
        <!-- Downloaded tracks show a static check in the download
             button's slot: it does nothing, deleting happens from the
             library rows. -->
        <span
          v-if="showDownloadedCheck"
          class="inline-flex size-10 shrink-0 items-center justify-center text-accent"
          :title="t('search.inLibrary')"
          aria-hidden="true"
        >
          <AppIcon name="check" :size="18" />
        </span>
      </div>

      <!-- A size container: the clock and the volume slider only show
           once this column is wide enough for them, so nothing here ever
           overlaps (the slider used to slide under the expand button). -->
      <div
        class="@container hidden items-center justify-end gap-1 md:flex md:w-[32%] md:min-w-[180px] md:flex-none"
      >
        <!-- Never wraps, and keeps one width for the whole track: the
             invisible copy is the widest the text will get, so the
             controls beside it don't shift as it ticks past 10:00. -->
        <span
          class="tabular mr-2 hidden shrink-0 text-xs whitespace-nowrap text-muted @min-[380px]:inline-grid"
        >
          <span class="invisible col-start-1 row-start-1" aria-hidden="true">{{
            clockSizer
          }}</span>
          <span class="col-start-1 row-start-1 text-right"
            >{{ formatDuration(player.currentTime.value) }} /
            {{ formatDuration(player.duration.value) }}</span
          >
        </span>
        <UiIconButton
          v-if="showLyrics"
          icon="lyrics"
          :label="t('player.lyrics')"
          size="sm"
          @click="nowPlaying.open('lyrics')"
        />
        <UiIconButton
          icon="users"
          :label="jam.active.value ? t('jam.inJam') : t('jam.start')"
          :active="jam.active.value"
          toggle
          size="sm"
          @click="openJamSheet()"
        />
        <UiIconButton
          icon="queue"
          :label="t('player.upNext')"
          size="sm"
          @click="nowPlaying.open('queue')"
        />
        <DevicesButton v-if="auth.user.value" />
        <!-- mr leaves room for the slider's thumb at 100 %. -->
        <VolumeControl
          class="mr-1.5 hidden shrink-0 @min-[275px]:flex"
          width="w-12 @min-[300px]:w-16 @min-[400px]:w-20 @min-[460px]:w-24"
        />
        <UiIconButton
          icon="expand"
          :label="t('player.openNowPlaying')"
          size="sm"
          @click="nowPlaying.open()"
        />
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import AppIcon from '../ui/AppIcon.vue'
import CoverArt from '../ui/CoverArt.vue'
import EqBars from '../ui/EqBars.vue'
import ExplicitBadge from '../ui/ExplicitBadge.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiMenu from '../ui/UiMenu.vue'
import { useMiniGestures } from '../player/useMiniGestures'
import { groupingArtistName } from '/src/lib/library'
import LikeButton from '../player/LikeButton.vue'
import DevicesButton from '../player/DevicesButton.vue'
import { useAuth } from '/src/model/auth'
import { useJamSheet } from '/src/model/jamSheet'
import SliderBar from '../player/SliderBar.vue'
import { useSmoothTime } from '../player/useSmoothTime'
import { usePlaybackLoading } from '../player/usePlaybackLoading'
import VolumeControl from '../player/VolumeControl.vue'
import { useRouter } from 'vue-router'
import { usePlayer } from '/src/model/player'
import { useJam } from '/src/model/jam'
import { useDownloadManager, useProgressTracker } from '/src/model/download'
import { useLibrary } from '/src/model/library'
import { usePlayerPrefs } from '/src/model/playerPrefs'
import { useNowPlaying, useUi } from '/src/model/ui'
import { usePlaylistActions } from '/src/model/playlistActions'
import { formatDuration, widestClock } from '/src/lib/format'
import { useI18n } from '/src/i18n'

const player = usePlayer()
const jam = useJam()
const playlistActions = usePlaylistActions()
const router = useRouter()
const { showLyrics } = usePlayerPrefs()
const nowPlaying = useNowPlaying()
const { t } = useI18n()
const auth = useAuth()
const { openJamSheet } = useJamSheet()
const library = useLibrary()
const dm = useDownloadManager()
const tracker = useProgressTracker()
const ui = useUi()
const scrub = ref(null)
const loading = usePlaybackLoading(() => player.loadingPhase.value)

const songMenu = ref(null)
const gestures = useMiniGestures({
  onNext: () => player.next(),
  onPrev: () => player.prev(),
  onLongPress: (point) =>
    songMenu.value?.openAt({ ...point, preventDefault() {} }),
})
// What holding the song offers: where it's from, and the player's panels.
const songMenuItems = computed(() => {
  const tr = track.value
  if (!tr) return []
  const artist = groupingArtistName(tr)
  const addTo = playlistActions.playerMenuItems(tr)
  return [
    ...(addTo.length ? [...addTo, { divider: true }] : []),
    {
      label: t('player.goToAlbum'),
      icon: 'disc',
      hidden: !tr.album || !!tr.stream,
      action: () =>
        router.push({
          name: 'Album',
          query: { artist: tr.albumArtist, title: tr.album },
        }),
    },
    {
      label: t('player.goToArtist'),
      icon: 'user',
      hidden: !artist,
      action: () => router.push({ name: 'Artist', query: { name: artist } }),
    },
    { divider: true },
    {
      label: t('player.lyrics'),
      icon: 'lyrics',
      hidden: !showLyrics.value || !!tr.stream,
      action: () => nowPlaying.open('lyrics'),
    },
    {
      label: t('player.upNext'),
      icon: 'queue',
      action: () => nowPlaying.open('queue'),
    },
    {
      label: t('player.details'),
      icon: 'info',
      action: () => nowPlaying.open('details'),
    },
  ]
})

const track = computed(() => player.currentTrack.value)

const trackArtist = computed(
  () =>
    (track.value?.artists || [])[0] ||
    track.value?.artist ||
    t('common.unknownArtist')
)
const trackTitle = computed(() => track.value?.name || track.value?.title || '')

// A stream that isn't in the library yet can be queued from here; while
// queued it spins instead of queueing a duplicate.
const streamDownloadable = computed(
  () =>
    !!track.value?.stream &&
    !!track.value.video_id &&
    !library.hasSong(trackArtist.value, trackTitle.value)
)
const pendingSong = computed(() => {
  if (!streamDownloadable.value) return null
  const tr = track.value
  return {
    name: trackTitle.value,
    artists: tr.artist ? [tr.artist] : [],
    artist: tr.artist || '',
    album_name: tr.album || '',
    cover_url: tr.cover && String(tr.cover).startsWith('http') ? tr.cover : '',
    duration: tr.duration || 0,
    url: `https://music.youtube.com/watch?v=${tr.video_id}`,
    youtube_id: tr.video_id,
  }
})
const downloadJob = computed(() => {
  tracker.queueVersion.value
  return pendingSong.value ? tracker.getBySong(pendingSong.value) : null
})
const downloadBusy = computed(() => {
  const state = downloadJob.value?.state
  return state === 'queued' || state === 'active'
})
const showMiniDownload = computed(() => !!streamDownloadable.value)

function downloadCurrent() {
  const song = pendingSong.value
  if (!song || downloadBusy.value) return
  if (downloadJob.value?.state === 'failed') dm.retry(song)
  else {
    dm.queue(song)
    ui.toast(t('toast.queuedTracks', { count: 1, name: song.name }), {
      kind: 'success',
    })
  }
}

// A downloaded track (or a stream that landed in the library while
// playing) shows a static check where the download button was.
const showDownloadedCheck = computed(
  () =>
    !!track.value &&
    !track.value.isPodcast &&
    (!track.value.stream ||
      library.hasSong(trackArtist.value, trackTitle.value))
)

// The phone hairline glides like the desktop scrubber (only animated
// while it's the one on screen).
const isPhone = useMediaQuery('(max-width: 767px)')
const smoothTime = useSmoothTime(
  () => player.currentTime.value,
  () => isPhone.value && player.isAdvancing.value,
  () => player.duration.value || 0
)
const smoothPercent = computed(() =>
  isPhone.value && player.duration.value
    ? Math.min(100, (smoothTime.value / player.duration.value) * 100)
    : player.progressPct.value
)

const clockSizer = computed(() => widestClock(player.duration.value))

const repeatLabel = computed(
  () =>
    ({
      off: t('player.repeatOff'),
      all: t('player.repeatAll'),
      one: t('player.repeatOne'),
    })[player.repeatMode.value]
)

function commitSeek(value) {
  player.seek(value)
  scrub.value = null
}
</script>

<style scoped>
.mini-loading-sweep {
  animation: mini-loading-sweep 1.2s var(--ease-out-soft) infinite;
}

@keyframes mini-loading-sweep {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(300%);
  }
}
</style>
