<template>
  <div
    class="relative isolate flex min-h-dvh flex-col overflow-hidden bg-[#07080b] text-white"
  >
    <!-- Backdrop, as in Now playing: the artwork blown up and blurred. -->
    <div
      class="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
      aria-hidden="true"
    >
      <div
        class="absolute inset-0 transition-colors duration-700"
        :style="{ backgroundColor: tint }"
      />
      <img
        v-if="track.hasCover"
        :src="track.cover"
        alt=""
        class="absolute inset-0 size-full scale-125 object-cover opacity-55 blur-[90px] saturate-150"
      />
      <div
        class="absolute inset-0 bg-gradient-to-b from-black/25 via-black/45 to-black/80"
      />
    </div>

    <header
      class="flex h-16 shrink-0 items-center gap-2.5 px-5 pt-[env(safe-area-inset-top)] lg:px-10"
    >
      <AppLogo :size="26" />
      <span class="text-display text-[17px] font-bold">Castify</span>
    </header>

    <main
      class="mx-auto flex w-full max-w-[440px] flex-1 flex-col justify-center gap-7 px-5 pb-[max(1.5rem,env(safe-area-inset-bottom))]"
    >
      <template v-if="state === 'ready'">
        <CoverArt
          :src="track.hasCover ? track.cover : ''"
          :name="track.album || track.title"
          rounded="rounded-[18px]"
          :letter-size="120"
          :icon-size="72"
          shadow
          class="aspect-square w-full shadow-[0_30px_80px_rgba(0,0,0,0.55)]"
        />

        <div class="min-w-0">
          <h1 class="flex items-center gap-2">
            <span
              class="text-display line-clamp-2 text-[26px] leading-tight font-bold break-words"
              >{{ track.title }}</span
            >
            <ExplicitBadge v-if="track.explicit" class="shrink-0" />
          </h1>
          <p class="mt-1 truncate text-[15px] text-white/70">
            {{ byline }}
          </p>
        </div>

        <div>
          <WaveSeekBar
            :model-value="scrub ?? currentTime"
            :max="duration || 1"
            :label="t('player.seek')"
            :value-text="formatDuration(currentTime)"
            :playing="playing"
            :palette="palette"
            @update:model-value="(v) => (scrub = v)"
            @commit="commitSeek"
          />
          <div class="tabular mt-1 flex justify-between text-xs text-white/65">
            <span>{{ formatDuration(scrub ?? currentTime) }}</span>
            <span>{{ formatDuration(duration) }}</span>
          </div>
        </div>

        <div class="flex items-center justify-center gap-8">
          <button
            type="button"
            class="flex size-12 items-center justify-center rounded-full text-white/80 transition-colors hover:bg-white/10"
            :aria-label="t('songLink.back10')"
            @click="seekBy(-10)"
          >
            <AppIcon name="skip-back" :size="24" />
          </button>
          <button
            type="button"
            class="flex size-[68px] items-center justify-center rounded-full bg-white text-[#0b0c0e] shadow-[0_12px_30px_rgba(0,0,0,0.35)] transition-transform hover:scale-105 active:scale-95"
            :aria-label="playing ? t('player.pause') : t('player.play')"
            @click="toggle"
          >
            <span
              v-if="buffering && playing"
              class="size-6 animate-spin rounded-full border-[3px] border-current border-r-transparent"
            />
            <AppIcon v-else :name="playing ? 'pause' : 'play'" :size="28" />
          </button>
          <button
            type="button"
            class="flex size-12 items-center justify-center rounded-full text-white/80 transition-colors hover:bg-white/10"
            :aria-label="t('songLink.forward10')"
            @click="seekBy(10)"
          >
            <AppIcon name="skip-forward" :size="24" />
          </button>
        </div>

        <p
          v-if="failed"
          class="text-center text-[13px] text-white/70"
          role="alert"
        >
          {{ t('songLink.playFailed') }}
        </p>
      </template>

      <div
        v-else-if="state === 'missing'"
        class="flex flex-col items-center gap-3 text-center"
      >
        <span
          class="flex size-16 items-center justify-center rounded-full bg-white/10"
        >
          <AppIcon name="music" :size="28" />
        </span>
        <h1 class="text-display text-2xl font-bold">
          {{ t('songLink.notFound') }}
        </h1>
        <p class="text-[15px] text-white/70">
          {{ t('songLink.notFoundHint') }}
        </p>
      </div>

      <div v-else class="flex flex-col gap-7" aria-hidden="true">
        <div
          class="aspect-square w-full animate-pulse rounded-[18px] bg-white/10"
        />
        <div class="h-7 w-2/3 animate-pulse rounded bg-white/10" />
      </div>
    </main>

    <audio
      ref="audio"
      :src="state === 'ready' ? info.audio_url : undefined"
      preload="metadata"
      @play="playing = true"
      @pause="playing = false"
      @ended="onEnded"
      @timeupdate="currentTime = audio.currentTime"
      @durationchange="onDuration"
      @waiting="buffering = true"
      @playing="onPlaying"
      @canplay="buffering = false"
      @error="onError"
    />
  </div>
</template>

<script setup>
// The page a public song link opens (/s/<token>): anyone listens to that
// one song without signing in. It is drawn like the app's Now playing -
// the same cover, wave seek bar and buttons - but plays on its own
// <audio>, outside the signed-in player and its reports to the server.
// See downtify/song_link_routes.py.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '/src/components/ui/AppIcon.vue'
import AppLogo from '/src/components/ui/AppLogo.vue'
import CoverArt from '/src/components/ui/CoverArt.vue'
import ExplicitBadge from '/src/components/ui/ExplicitBadge.vue'
import WaveSeekBar from '/src/components/player/WaveSeekBar.vue'
import { useCoverPalette } from '/src/model/coverPalette'
import { formatDuration, hueFor } from '/src/lib/format'
import { loadSongLink, shareTrack } from '/src/lib/songLinks'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const route = useRoute()
const audio = ref(null)
const info = ref(null)
const state = ref('loading')
const playing = ref(false)
const buffering = ref(false)
const failed = ref(false)
const currentTime = ref(0)
const knownDuration = ref(0)
const scrub = ref(null)

const track = computed(() => shareTrack(info.value))
const duration = computed(() => knownDuration.value || track.value.duration)
const byline = computed(() =>
  [track.value.artist, track.value.album].filter(Boolean).join(' · ')
)
const palette = useCoverPalette(track)
const tint = computed(
  () =>
    palette.value?.background ||
    `oklch(0.3 0.06 ${hueFor(track.value.album || track.value.title)})`
)

async function load(token) {
  state.value = 'loading'
  info.value = await loadSongLink(token)
  state.value = info.value ? 'ready' : 'missing'
}

watch(() => route.params.token, load, { immediate: true })

watch(
  () => track.value.title,
  (title) => {
    if (!title) return
    document.title = [title, track.value.artist].filter(Boolean).join(' · ')
    setMediaSession()
  }
)

function setMediaSession() {
  const session = globalThis.navigator?.mediaSession
  if (!session || typeof MediaMetadata === 'undefined') return
  session.metadata = new MediaMetadata({
    title: track.value.title,
    artist: track.value.artist,
    album: track.value.album,
    artwork: track.value.hasCover ? [{ src: track.value.cover }] : [],
  })
  session.setActionHandler?.('play', () => audio.value?.play())
  session.setActionHandler?.('pause', () => audio.value?.pause())
  session.setActionHandler?.('seekbackward', () => seekBy(-10))
  session.setActionHandler?.('seekforward', () => seekBy(10))
}

async function toggle() {
  const el = audio.value
  if (!el) return
  if (!el.paused) {
    el.pause()
    return
  }
  failed.value = false
  buffering.value = true
  try {
    await el.play()
  } catch {
    buffering.value = false
  }
}

function seekBy(seconds) {
  const el = audio.value
  if (!el) return
  const end = duration.value || el.duration || 0
  el.currentTime = Math.max(0, Math.min(end, el.currentTime + seconds))
  currentTime.value = el.currentTime
}

function commitSeek(value) {
  scrub.value = null
  if (!audio.value) return
  audio.value.currentTime = value
  currentTime.value = value
}

function onDuration() {
  const value = audio.value?.duration
  if (Number.isFinite(value) && value > 0) knownDuration.value = value
}

function onPlaying() {
  buffering.value = false
  playing.value = true
}

function onEnded() {
  playing.value = false
  currentTime.value = 0
  if (audio.value) audio.value.currentTime = 0
}

function onError() {
  if (state.value !== 'ready') return
  failed.value = true
  buffering.value = false
  playing.value = false
}

function onKey(event) {
  if (event.code !== 'Space' || event.target?.closest?.('input, button')) return
  event.preventDefault()
  toggle()
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>
