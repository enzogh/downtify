<template>
  <!-- Under the title in Now playing, while a song streams live: says
       it isn't on the server, offers to save it there (with progress),
       and when the server will save it on its own. -->
  <div
    v-if="save.isStream.value"
    class="flex w-full min-w-0 flex-wrap items-center gap-x-3 gap-y-2 text-sm"
    role="status"
  >
    <span class="flex min-w-0 items-center gap-2" :class="toneClass">
      <AppIcon :name="iconName" :size="16" class="shrink-0" />
      <span class="min-w-0">
        <span class="block">{{ message }}</span>
        <span v-if="hint" class="block text-xs text-white/55">{{ hint }}</span>
      </span>
    </span>
    <button
      v-if="canSave"
      type="button"
      class="flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-white px-4 text-xs font-semibold text-[#0b0c0e] transition-transform active:scale-95"
      @click="save.save()"
    >
      <AppIcon
        :name="save.state.value === 'failed' ? 'retry' : 'download'"
        :size="14"
      />{{
        save.state.value === 'failed' ? t('common.retry') : t('stream.save')
      }}
    </button>
    <UiProgress
      v-if="save.busy.value"
      class="basis-full"
      :value="save.progress.value"
      :indeterminate="!save.progress.value"
      :height="3"
      track="bg-white/15"
      color="bg-white/85"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiProgress from '../ui/UiProgress.vue'
import { useStreamSave } from '/src/model/streamSave'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const save = useStreamSave()

const canSave = computed(
  () =>
    !!save.song.value &&
    (save.state.value === 'new' || save.state.value === 'failed')
)

const iconName = computed(
  () =>
    ({
      saved: 'check-circle',
      failed: 'alert',
      queued: 'clock',
      active: 'download',
    })[save.state.value] || 'radio'
)

const toneClass = computed(
  () =>
    ({
      saved: 'text-accent',
      failed: 'text-danger',
    })[save.state.value] || 'text-white/80'
)

const message = computed(() => {
  switch (save.state.value) {
    case 'saved':
      return t('stream.savedHint')
    case 'queued':
      return t('stream.queued')
    case 'active':
      return save.progress.value
        ? `${t('stream.saving')} ${save.progress.value}%`
        : t('stream.saving')
    case 'failed':
      return t('stream.saveFailed')
    default:
      return t('stream.liveTitle')
  }
})

const hint = computed(() => {
  const left = save.autoRemaining.value
  if (left === null) return ''
  if (left === 0) return t('stream.autoQueued')
  return t('stream.autoIn', { count: left })
})
</script>
