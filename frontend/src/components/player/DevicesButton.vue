<template>
  <!-- Spotify Connect's button: green while music plays on another of
       the account's devices, with a dot when any other is open. -->
  <button
    type="button"
    class="relative inline-flex shrink-0 items-center justify-center rounded-full transition-colors"
    :class="[
      sizeClass,
      elsewhere ? 'text-accent' : toneClass,
      onDark ? 'hover:bg-white/10' : 'hover:bg-surface-2',
    ]"
    :aria-label="label"
    :title="label"
    @click="remote.openPicker()"
  >
    <AppIcon name="devices" :size="iconSize" />
    <span
      v-if="remote.devices.value.length"
      class="absolute right-1.5 bottom-1.5 size-1.5 rounded-full"
      :class="elsewhere ? 'bg-accent' : onDark ? 'bg-white/60' : 'bg-fg-3'"
      aria-hidden="true"
    />
  </button>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import { useRemotePlayback } from '/src/model/remotePlayback'
import { useI18n } from '/src/i18n'

const props = defineProps({
  size: { type: String, default: 'sm' },
  onDark: { type: Boolean, default: false },
})

const { t } = useI18n()
const remote = useRemotePlayback()

const elsewhere = computed(() =>
  remote.devices.value.some((row) => row.track && !row.paused)
)
const label = computed(() => {
  const playing = remote.devices.value.find((row) => row.track && !row.paused)
  return playing
    ? t('remotePlayback.playingOn', {
        device: playing.client || t('remotePlayback.otherDevice'),
      })
    : t('remotePlayback.devices')
})
const sizeClass = computed(() => (props.size === 'lg' ? 'size-11' : 'size-8'))
const iconSize = computed(() => (props.size === 'lg' ? 22 : 17))
const toneClass = computed(() =>
  props.onDark ? 'text-white/75 hover:text-white' : 'text-muted hover:text-fg'
)
</script>
