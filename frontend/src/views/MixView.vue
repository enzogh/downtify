<template>
  <div>
    <DetailState
      :loaded="ready"
      :found="!!mix"
      icon="sparkle"
      :missing="t('mix.notFound')"
    >
      <CollectionHero
        :title="mix.title"
        :kicker="t('mix.kicker')"
        :covers="mix.covers"
        :cover="isReco ? '' : mix.covers[0] || ''"
        :name="mix.title"
        icon="sparkle"
      >
        <template #subtitle>{{ mix.description }}</template>
        <template #actions>
          <PlayButton
            :label="t('actions.playItem', { name: mix.title })"
            :playing="isThisPlaying"
            :disabled="!queue.length"
            @click="togglePlay"
          />
          <UiIconButton
            icon="shuffle"
            :label="t('actions.shuffle')"
            size="lg"
            round
            :disabled="!queue.length"
            @click="play({ shuffled: true })"
          />
          <UiIconButton
            v-if="isReco"
            icon="refresh"
            :label="t('reco.refresh')"
            size="lg"
            round
            :disabled="reco.loading.value"
            @click="reco.refresh()"
          />
          <!-- A recommended mix is all songs the server hasn't got. -->
          <UiButton
            v-if="isReco && missing.length"
            variant="secondary"
            icon="download"
            :loading="downloading"
            @click="downloadAll"
          >
            {{ t('mix.downloadAll', { count: missing.length }) }}
          </UiButton>
        </template>
      </CollectionHero>

      <div
        class="mx-auto flex max-w-[1680px] flex-col gap-3 px-4 pb-10 sm:px-6 lg:px-10"
      >
        <p
          v-if="mixes.loadingRadios.value || reco.loading.value"
          class="flex items-center gap-2 text-[13px] text-muted"
          role="status"
        >
          <AppIcon name="refresh" :size="14" class="animate-spin" />
          {{ t('mix.completing') }}
        </p>
        <TransitionGroup tag="div" name="list" class="-mx-3 flex flex-col">
          <div
            v-for="(song, i) in songs"
            :key="`${song.file || song.song_id || song.url}`"
            class="flex items-center"
          >
            <SongRow
              :song="song"
              :index="i"
              :songs="songs"
              :note="notes[i] || ''"
              :hide-add-on-phone="isReco"
              class="min-w-0 flex-1"
            />
            <!-- "Not for me": gone from every recommendation. -->
            <UiIconButton
              v-if="isReco"
              icon="x"
              size="sm"
              :label="t('reco.dismiss', { title: song.name })"
              :title="t('reco.dismissShort')"
              class="mr-2 shrink-0 text-faint"
              @click="dismiss(song)"
            />
          </div>
        </TransitionGroup>
      </div>
    </DetailState>
  </div>
</template>

<script setup>
// One "Made for you" mix (Home): a Daily Mix (the lead artist's songs,
// songs you have by related artists, similar songs streamed until you
// download them), On repeat, or a recommended mix - Discover or For you -
// where each song says why it is there and "Not for me" removes it.
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '/src/components/ui/AppIcon.vue'
import UiButton from '/src/components/ui/UiButton.vue'
import UiIconButton from '/src/components/ui/UiIconButton.vue'
import CollectionHero from '/src/components/library/CollectionHero.vue'
import DetailState from '/src/components/library/DetailState.vue'
import PlayButton from '/src/components/library/PlayButton.vue'
import SongRow from '/src/components/search/SongRow.vue'
import { useMixes } from '/src/model/mixes'
import { listCovers, useRecommendations } from '/src/model/recommendations'
import { usePlayer } from '/src/model/player'
import { useDownloadManager } from '/src/model/download'
import { useLibrary } from '/src/model/library'
import { useUi } from '/src/model/ui'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const route = useRoute()
const player = usePlayer()
const mixes = useMixes()
const library = useLibrary()
const downloads = useDownloadManager()
const ui = useUi()
const router = useRouter()
const reco = useRecommendations()
const ready = ref(false)
const id = computed(() => String(route.params.id || ''))

onMounted(async () => {
  if (isReco.value) await reco.ensure()
  else await mixes.ensure()
  ready.value = true
})

// The recommended mixes (lib/recommender.js via model/recommendations.js).
const RECO = {
  discover: {
    list: 'discover',
    title: 'home.discoverMix',
    hint: 'mix.discoverHint',
  },
  foryou: { list: 'forYou', title: 'home.forYouMix', hint: 'mix.forYouHint' },
}
const isReco = computed(() => id.value in RECO)
const recoList = computed(() =>
  isReco.value ? reco[RECO[id.value].list].value : []
)
const notes = computed(() =>
  isReco.value
    ? recoList.value.map((item) =>
        item.kind === 'again'
          ? t('reco.again')
          : item.because
            ? t('reco.because', { artist: item.because })
            : ''
      )
    : []
)

function dismiss(song) {
  reco.dismiss(song)
  ui.toast(t('reco.dismissed'), { kind: 'success' })
}

const mix = computed(() => {
  if (id.value === 'repeat') {
    const tracks = mixes.repeat.value
    if (!tracks.length) return null
    return {
      title: t('home.onRepeat'),
      description: t('home.onRepeatHint'),
      items: tracks.map((track) => ({ track })),
      covers: covers(tracks),
    }
  }
  if (isReco.value) {
    const list = recoList.value
    if (!list.length) return null
    const spec = RECO[id.value]
    return {
      title: t(spec.title),
      description: [
        t(spec.hint),
        t('common.tracks', { count: list.length }),
      ].join(' · '),
      items: list.map((item) => ({ song: item.song })),
      covers: listCovers(list),
    }
  }
  const found = mixes.findMix(id.value)
  if (!found) return null
  return {
    ...found,
    title: t('home.dailyMix', { n: found.number }),
    description: [
      t('mix.with', { artists: found.artists.join(', ') }),
      t('common.tracks', { count: found.items.length }),
    ].join(' · '),
  }
})

function covers(tracks) {
  return tracks
    .filter((track) => track.hasCover && track.cover)
    .map((track) => track.cover)
    .filter((cover, i, all) => all.indexOf(cover) === i)
    .slice(0, 4)
}

// Rows the search list knows how to show and play: library songs carry
// their file, the rest stream.
const songs = computed(() =>
  (mix.value?.items || []).map((item) =>
    item.track
      ? {
          name: item.track.title,
          artist: item.track.artist,
          artists: item.track.artists || [item.track.artist],
          album_name: item.track.album,
          cover_url: item.track.hasCover ? item.track.cover : '',
          duration: item.track.duration,
          explicit: item.track.explicit,
          file: item.track.file,
          source: 'library',
        }
      : item.song
  )
)

const queue = computed(() => mixes.queueOf(mix.value))

const context = computed(() => ({
  type: 'mix',
  title: mix.value?.title || '',
  route: { name: 'Mix', params: { id: id.value } },
}))

const isThisPlaying = computed(
  () =>
    player.isPlaying.value &&
    player.context.value?.type === 'mix' &&
    player.context.value?.title === mix.value?.title
)

function play({ shuffled = false } = {}) {
  if (!queue.value.length) return
  if (shuffled)
    player.playList(queue.value, { context: context.value, shuffled })
  else
    player.setPlaylist(queue.value, { startIndex: 0, context: context.value })
}

// Songs of the mix not on the server yet (the discover mix: all of them,
// until some are downloaded).
const missing = computed(() =>
  songs.value.filter(
    (song) =>
      !song.file &&
      !library.findTrack?.(song.artists?.[0] || song.artist, song.name)
  )
)
const downloading = ref(false)

async function downloadAll() {
  if (downloading.value || !missing.value.length) return
  downloading.value = true
  try {
    const count = await downloads.fromSongs(missing.value, { m3u: false })
    ui.toast(t('toast.queuedTracks', { count, name: mix.value.title }), {
      kind: 'success',
      action: {
        label: t('nav.queue'),
        run: () => router.push({ name: 'Queue' }),
      },
    })
  } catch (err) {
    ui.toast(err?.response?.data?.detail || t('toast.actionFailed'), {
      kind: 'error',
    })
  } finally {
    downloading.value = false
  }
}

function togglePlay() {
  if (isThisPlaying.value) player.pause()
  else play()
}
</script>
