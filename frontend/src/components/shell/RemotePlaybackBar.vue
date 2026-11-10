<template>
  <Transition name="now-playing">
    <div
      v-if="row"
      class="overflow-hidden rounded-[16px] border border-line-3 bg-glass shadow-float backdrop-blur-xl"
      role="status"
    >
      <div class="flex items-center gap-3 p-2 md:gap-4 md:pr-3">
        <CoverArt
          :thumb="150"
          :src="cover"
          :name="row.track.album || row.track.title"
          rounded="rounded-[10px]"
          :letter-size="16"
          :icon-size="16"
          class="size-11 shrink-0"
        />
        <button
          type="button"
          class="min-w-0 flex-1 text-left"
          :aria-label="t('remotePlayback.devices')"
          @click="remote.openPicker()"
        >
          <span class="flex min-w-0 items-center gap-2">
            <span class="truncate text-sm font-semibold">{{
              row.track.title || row.track.file
            }}</span>
            <EqBars v-if="!row.paused" :size="10" class="text-accent" />
          </span>
          <span class="block truncate text-xs text-muted">
            {{ row.track.artist }}
          </span>
        </button>
        <UiButton
          v-if="row.track.file"
          size="sm"
          variant="primary"
          icon="play"
          @click="listenHere"
        >
          <span class="max-sm:sr-only">{{
            t('remotePlayback.listenHere')
          }}</span>
        </UiButton>
        <UiIconButton
          :icon="row.paused ? 'play' : 'pause'"
          :label="
            row.paused ? t('remotePlayback.resume') : t('remotePlayback.pause')
          "
          size="sm"
          @click="toggle"
        />
        <UiIconButton
          icon="x"
          :label="t('remotePlayback.hide')"
          size="sm"
          class="max-sm:hidden"
          @click="remote.hide()"
        />
      </div>
      <!-- Spotify's green strip: where the music is coming from. -->
      <button
        type="button"
        class="flex w-full items-center gap-1.5 bg-accent px-3 py-1 text-left text-xs font-semibold text-on-accent"
        @click="remote.openPicker()"
      >
        <AppIcon :name="row.app ? 'smartphone' : 'devices'" :size="13" />
        <span class="truncate">{{
          row.paused
            ? t('remotePlayback.pausedOn', { device })
            : t('remotePlayback.playingOn', { device })
        }}</span>
      </button>
    </div>
  </Transition>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import CoverArt from '../ui/CoverArt.vue'
import EqBars from '../ui/EqBars.vue'
import UiButton from '../ui/UiButton.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import { useLibrary } from '/src/model/library'
import { usePlayer } from '/src/model/player'
import { useRemotePlayback } from '/src/model/remotePlayback'
import { useUi } from '/src/model/ui'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const ui = useUi()
const library = useLibrary()
const player = usePlayer()
const remote = useRemotePlayback()

// Only while nothing plays here: playing here already is the answer.
const row = computed(() =>
  player.isPlaying.value ? null : remote.remote.value
)
const device = computed(
  () => row.value?.client || t('remotePlayback.otherDevice')
)
const cover = computed(() => {
  const file = row.value?.track?.file
  const known = file ? library.tracksByFile.value.get(file) : null
  return known?.hasCover ? known.cover : ''
})

async function listenHere() {
  if (!(await remote.listenHere(row.value)))
    ui.toast(t('remotePlayback.cannotPlay'), { kind: 'error' })
}

async function toggle() {
  if (!(await remote.toggleRemote(row.value)))
    ui.toast(t('remotePlayback.gone'), { kind: 'error' })
}
</script>
