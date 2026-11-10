<template>
  <UiButton
    v-if="offline.support !== 'unsupported' && savable.length"
    :variant="saved && !job ? 'secondary' : 'ghost'"
    :icon="icon"
    :loading="busy"
    :class="saved && !job ? 'text-accent' : ''"
    :title="hint"
    @click="onClick"
  >
    {{ label }}
  </UiButton>
</template>

<script setup>
// "Download to this device" on a playlist or album page: keeps its songs
// for offline listening (see model/offline.js). Opening the page of a
// saved one brings it up to date (songs added or taken out).
import { computed, onMounted, ref, watch } from 'vue'
import UiButton from '../ui/UiButton.vue'
import { savableTracks } from '/src/lib/offline'
import { formatBytes } from '/src/lib/format'
import { useOffline } from '/src/model/offline'
import { useUi } from '/src/model/ui'
import { useI18n } from '/src/i18n'

const props = defineProps({
  // { kind: 'playlist'|'album', id, title, subtitle, cover, route }
  collection: { type: Object, required: true },
  tracks: { type: Array, default: () => [] },
})

const { t } = useI18n()
const ui = useUi()
const offline = useOffline()
const removing = ref(false)

const savable = computed(() => savableTracks(props.tracks))
const entry = computed(() =>
  offline.loaded.value
    ? offline.entryFor(props.collection.kind, props.collection.id)
    : null
)
const job = computed(() =>
  offline.jobFor(props.collection.kind, props.collection.id)
)
const saved = computed(() => !!entry.value)
const busy = computed(() => job.value?.state === 'saving' || removing.value)

const icon = computed(() => {
  if (busy.value) return ''
  if (job.value?.state === 'full' || job.value?.state === 'error') {
    return 'alert'
  }
  return saved.value ? 'check-circle' : 'arrow-down-to-line'
})

const label = computed(() => {
  const state = job.value?.state
  if (state === 'saving') {
    return t('offline.saving', {
      done: job.value.done,
      total: job.value.total,
    })
  }
  if (state === 'full') return t('offline.full')
  if (state === 'error') {
    return t('offline.someFailed', { count: job.value.failed })
  }
  return saved.value ? t('offline.saved') : t('offline.save')
})

const hint = computed(() => {
  if (offline.support === 'insecure') return t('offline.needsHttps')
  return saved.value ? t('offline.savedHint') : t('offline.saveHint')
})

async function onClick() {
  if (offline.support === 'insecure') {
    ui.toast(t('offline.needsHttps'), { kind: 'error', timeout: 9000 })
    return
  }
  const state = job.value?.state
  if (state === 'full' || state === 'error') {
    await start()
    return
  }
  if (!saved.value) {
    await start()
    return
  }
  const ok = await ui.confirm({
    title: t('offline.removeTitle'),
    body: t('offline.removeBody', {
      name: props.collection.title,
      size: formatBytes(
        offline.collections.value.find((c) => c.key === entry.value.key)
          ?.size || 0
      ),
    }),
    confirmLabel: t('offline.remove'),
    danger: true,
  })
  if (!ok) return
  removing.value = true
  try {
    await offline.remove(props.collection.kind, props.collection.id)
    ui.toast(t('offline.removed', { name: props.collection.title }))
  } finally {
    removing.value = false
  }
}

async function start() {
  const result = await offline.save(props.collection, props.tracks)
  report(result)
}

function report(result) {
  if (!result) return
  if (result.state === 'full') {
    ui.toast(t('offline.full'), { kind: 'error', timeout: 9000 })
  } else if (result.state === 'error') {
    ui.toast(t('offline.someFailed', { count: result.failed }), {
      kind: 'error',
    })
  } else if (result.state === 'saving' && !result.failed) {
    ui.toast(t('offline.done', { name: props.collection.title }), {
      kind: 'success',
    })
  }
}

// A saved collection whose songs changed since: bring it up to date.
async function syncNow() {
  if (!saved.value || busy.value) return
  report(await offline.sync(props.collection, props.tracks))
}

onMounted(() => {
  void offline.ensureLoaded().then(syncNow)
})
watch(
  () => savable.value.map((track) => track.file).join('\n'),
  () => syncNow()
)
</script>
