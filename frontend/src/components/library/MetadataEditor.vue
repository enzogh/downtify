<template>
  <UiModal
    :open="open"
    :title="t('metadataEditor.title')"
    :description="t('metadataEditor.description', { count: tracks.length })"
    @close="$emit('close')"
  >
    <p class="mb-4 text-sm text-muted">
      {{ t('metadataEditor.hint') }}
    </p>
    <div class="space-y-3">
      <label
        v-for="field in fields"
        :key="field.key"
        class="flex items-center gap-3 text-sm"
      >
        <input v-model="selected[field.key]" type="checkbox" />
        <span class="w-28 shrink-0">{{ t(field.label) }}</span>
        <select
          v-if="field.boolean"
          v-model="values[field.key]"
          :disabled="!selected[field.key]"
          class="min-w-0 flex-1 rounded border border-line-3 bg-surface-2 px-3 py-2 disabled:opacity-40"
        >
          <option value="">{{ t('metadataEditor.clear') }}</option>
          <option value="true">{{ t('metadataEditor.yes') }}</option>
          <option value="false">{{ t('metadataEditor.no') }}</option>
        </select>
        <input
          v-else
          v-model="values[field.key]"
          :disabled="!selected[field.key]"
          :type="field.key === 'track_number' ? 'number' : 'text'"
          class="min-w-0 flex-1 rounded border border-line-3 bg-surface-2 px-3 py-2 disabled:opacity-40"
        />
      </label>
    </div>
    <p v-if="error" role="alert" class="mt-4 text-sm text-danger">
      {{ error }}
    </p>
    <template #footer>
      <UiButton variant="ghost" @click="$emit('close')">{{
        t('common.close')
      }}</UiButton>
      <UiButton :loading="saving" :disabled="saving" @click="save">{{
        t('metadataEditor.save')
      }}</UiButton>
    </template>
  </UiModal>
</template>
<script setup>
import { reactive, ref, watch } from 'vue'
import UiModal from '/src/components/ui/UiModal.vue'
import UiButton from '/src/components/ui/UiButton.vue'
import API from '/src/model/api'
import { useLibrary } from '/src/model/library'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const props = defineProps({
  open: Boolean,
  tracks: { type: Array, default: () => [] },
})
const emit = defineEmits(['close'])
const fields = [
  {
    key: 'title',
    label: 'metadataEditor.field.title',
    prop: 'title',
    single: true,
  },
  {
    key: 'artist',
    label: 'metadataEditor.field.artist',
    prop: 'artist',
    single: true,
  },
  { key: 'album', label: 'metadataEditor.field.album', prop: 'album' },
  {
    key: 'album_artist',
    label: 'metadataEditor.field.albumArtist',
    prop: 'albumArtist',
  },
  {
    key: 'track_number',
    label: 'metadataEditor.field.trackNumber',
    prop: 'trackNumber',
    single: true,
  },
  {
    key: 'release_date',
    label: 'metadataEditor.field.releaseDate',
    prop: 'releaseDate',
  },
  { key: 'genre', label: 'metadataEditor.field.genre', prop: 'genre' },
  {
    key: 'explicit',
    label: 'metadataEditor.field.explicit',
    prop: 'explicit',
    boolean: true,
  },
  {
    key: 'compilation',
    label: 'metadataEditor.field.compilation',
    prop: 'compilation',
    boolean: true,
  },
].filter((f) => !f.single || props.tracks.length === 1)
const selected = reactive({})
const values = reactive({})
const error = ref('')
const saving = ref(false)
watch(
  () => props.open,
  (open) => {
    if (!open) return
    error.value = ''
    for (const field of fields) {
      selected[field.key] = false
      const first = props.tracks[0]?.[field.prop] ?? ''
      const same = props.tracks.every(
        (track) => (track[field.prop] ?? '') === first
      )
      values[field.key] = same
        ? field.boolean
          ? String(Boolean(first))
          : first
        : ''
    }
  }
)
async function save() {
  const changes = {}
  for (const field of fields)
    if (selected[field.key]) {
      changes[field.key] =
        values[field.key] === ''
          ? null
          : field.key === 'track_number'
            ? Number(values[field.key])
            : field.boolean
              ? values[field.key] === 'true'
              : values[field.key]
    }
  if (!Object.keys(changes).length) {
    error.value = t('metadataEditor.pickOne')
    return
  }
  saving.value = true
  error.value = ''
  try {
    const library = await API.metadataLibrary()
    const byFile = new Map(
      library.data.tracks.map((track) => [track.file, track.id])
    )
    const ids = props.tracks.map((track) => byFile.get(track.file))
    if (ids.some((id) => !id)) throw new Error(t('metadataEditor.gone'))
    const revisions = Object.fromEntries(
      library.data.tracks
        .filter((track) => ids.includes(track.id))
        .map((track) => [track.id, track.revision])
    )
    const response = await API.editMetadata(ids, changes, revisions)
    await useLibrary().load({ force: true })
    const failed = response.data.results.filter((result) => !result.ok)
    if (failed.length)
      error.value = t('metadataEditor.failed', {
        count: failed.length,
        total: ids.length,
        errors: failed.map((result) => result.error).join('; '),
      })
    else emit('close')
  } catch (err) {
    error.value =
      err?.response?.data?.detail ||
      err.message ||
      t('metadataEditor.saveFailed')
  } finally {
    saving.value = false
  }
}
</script>
