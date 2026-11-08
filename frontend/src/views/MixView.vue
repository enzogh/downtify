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
        :cover="mix.covers[0] || ''"
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
        </template>
      </CollectionHero>

      <div
        class="mx-auto flex max-w-[1680px] flex-col gap-3 px-4 pb-10 sm:px-6 lg:px-10"
      >
        <p
          v-if="mixes.loadingRadios.value"
          class="flex items-center gap-2 text-[13px] text-muted"
          role="status"
        >
          <AppIcon name="refresh" :size="14" class="animate-spin" />
          {{ t('mix.completing') }}
        </p>
        <div class="-mx-3 flex flex-col">
          <SongRow
            v-for="(song, i) in songs"
            :key="`${song.file || song.song_id || song.url}-${i}`"
            :song="song"
            :index="i"
            :songs="songs"
          />
        </div>
      </div>
    </DetailState>
  </div>
</template>

<script setup>
// One "Made for you" mix (Home): the lead artist's songs, songs you have
// by related artists, and similar songs streamed until you download them.
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '/src/components/ui/AppIcon.vue'
import UiIconButton from '/src/components/ui/UiIconButton.vue'
import CollectionHero from '/src/components/library/CollectionHero.vue'
import DetailState from '/src/components/library/DetailState.vue'
import PlayButton from '/src/components/library/PlayButton.vue'
import SongRow from '/src/components/search/SongRow.vue'
import { useMixes } from '/src/model/mixes'
import { usePlayer } from '/src/model/player'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const route = useRoute()
const player = usePlayer()
const mixes = useMixes()
const ready = ref(false)

onMounted(async () => {
  await mixes.ensure()
  ready.value = true
})

const id = computed(() => String(route.params.id || ''))

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

function togglePlay() {
  if (isThisPlaying.value) player.pause()
  else play()
}
</script>
