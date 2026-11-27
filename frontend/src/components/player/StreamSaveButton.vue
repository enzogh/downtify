<template>
  <!-- The player's "save to server" slot: a stream offers its download
       (a ring fills while it runs), a song on the server shows a check
       that does nothing - deleting happens from the library rows. -->
  <span
    v-if="save.state.value === 'saved'"
    class="inline-flex shrink-0 items-center justify-center text-accent"
    :class="box"
    role="img"
    :title="t('stream.saved')"
    :aria-label="t('stream.saved')"
  >
    <AppIcon name="check" :size="icon" />
  </span>
  <!-- Nothing to save it by yet (a stream restored from the last
       session gets its video once it plays): no dead button. -->
  <button
    v-else-if="save.song.value || save.busy.value"
    type="button"
    class="relative inline-flex shrink-0 items-center justify-center rounded-full transition-colors disabled:cursor-default"
    :class="[box, buttonClass]"
    :title="label"
    :aria-label="label"
    :disabled="save.busy.value"
    @click="save.save()"
  >
    <svg
      v-if="save.busy.value"
      :width="icon + 6"
      :height="icon + 6"
      viewBox="0 0 24 24"
      aria-hidden="true"
      :class="
        save.state.value === 'queued' || !save.progress.value
          ? 'animate-spin'
          : ''
      "
    >
      <circle
        cx="12"
        cy="12"
        r="9.5"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        opacity="0.25"
      />
      <circle
        cx="12"
        cy="12"
        r="9.5"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        pathLength="100"
        :stroke-dasharray="`${ringFill} 100`"
        transform="rotate(-90 12 12)"
        class="transition-[stroke-dasharray] duration-300"
      />
    </svg>
    <AppIcon
      v-else
      :name="save.state.value === 'failed' ? 'retry' : 'download'"
      :size="icon"
    />
  </button>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import { useStreamSave } from '/src/model/streamSave'
import { useI18n } from '/src/i18n'

const props = defineProps({
  // 'md' in the mini player, 'lg' in Now playing.
  size: { type: String, default: 'md' },
  onDark: { type: Boolean, default: false },
})

const { t } = useI18n()
const save = useStreamSave()

const icon = computed(() => (props.size === 'lg' ? 22 : 18))
const box = computed(() => (props.size === 'lg' ? 'size-11' : 'size-10'))

const buttonClass = computed(() => {
  if (save.state.value === 'failed') return 'text-danger hover:bg-danger/12'
  if (save.busy.value) return 'text-accent'
  return props.onDark
    ? 'text-white/80 hover:bg-white/10'
    : 'text-fg-3 hover:bg-surface-2 hover:text-fg'
})

// While queued the ring is a short arc that spins; while downloading
// it fills with the progress (spinning until the first percent).
const ringFill = computed(() =>
  save.state.value === 'active' && save.progress.value
    ? save.progress.value
    : 25
)

const label = computed(() => {
  const name = save.song.value?.name || ''
  switch (save.state.value) {
    case 'queued':
      return t('stream.queued')
    case 'active':
      return save.progress.value
        ? `${t('stream.saving')} ${save.progress.value}%`
        : t('stream.saving')
    case 'failed':
      return t('stream.saveFailed')
    default:
      return t('stream.saveItem', { name })
  }
})
</script>
