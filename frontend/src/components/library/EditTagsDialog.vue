<template>
  <UiModal
    :open="Boolean(track)"
    :title="t('tagEdit.title')"
    :description="t('tagEdit.body')"
    width="sm:max-w-3xl"
    @close="close"
  >
    <div v-if="track" class="flex flex-col gap-5">
      <!-- The fields, as they will be written -->
      <div class="flex flex-col gap-4 sm:flex-row">
        <div class="flex shrink-0 flex-col items-center gap-1.5">
          <CoverArt
            :src="coverUrl || (track.hasCover ? track.cover : '')"
            :name="form.name || track.title"
            class="size-28"
            rounded="rounded-[10px]"
            :letter-size="28"
            :icon-size="28"
          />
          <span class="text-[12px] text-muted">
            {{ coverUrl ? t('tagEdit.coverNew') : t('tagEdit.coverKept') }}
          </span>
          <button
            v-if="coverUrl"
            type="button"
            class="text-[12px] text-muted underline hover:text-fg"
            @click="coverUrl = ''"
          >
            {{ t('tagEdit.coverUndo') }}
          </button>
        </div>
        <div class="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
          <UiInput v-model="form.name" :label="t('tagEdit.fields.title')" />
          <UiInput
            v-model="form.artists"
            :label="t('tagEdit.fields.artists')"
            :hint="t('tagEdit.fields.artistsHint')"
          />
          <UiInput
            v-model="form.album_name"
            :label="t('tagEdit.fields.album')"
          />
          <UiInput
            v-model="form.album_artist"
            :label="t('tagEdit.fields.albumArtist')"
          />
          <div class="grid grid-cols-2 gap-3">
            <UiInput
              v-model="form.year"
              :label="t('tagEdit.fields.year')"
              inputmode="numeric"
            />
            <UiInput
              v-model="form.track_number"
              :label="t('tagEdit.fields.trackNumber')"
              inputmode="numeric"
            />
          </div>
          <UiInput v-model="form.genre" :label="t('tagEdit.fields.genre')" />
          <UiSwitch
            v-model="form.explicit"
            class="sm:col-span-2"
            :label="t('tagEdit.fields.explicit')"
          />
        </div>
      </div>

      <!-- Suggestions from the catalogs -->
      <div class="flex flex-col gap-3 border-t border-line-2 pt-4">
        <form class="flex gap-2" @submit.prevent="search">
          <UiInput
            v-model="query"
            class="min-w-0 flex-1"
            :label="t('tagEdit.search')"
            icon="search"
          />
          <UiButton
            type="submit"
            class="self-start sm:mt-[26px]"
            :loading="loading"
            :disabled="!query.trim()"
          >
            {{ t('tagEdit.searchButton') }}
          </UiButton>
        </form>

        <p v-if="error" class="text-[13px] text-danger" role="alert">
          {{ error }}
        </p>
        <p
          v-else-if="!loading && searched && !suggestions.length"
          class="text-sm text-muted"
        >
          {{ t('tagEdit.none') }}
        </p>

        <ul
          v-if="suggestions.length"
          class="flex max-h-72 flex-col gap-1 overflow-y-auto"
          :aria-label="t('tagEdit.suggestions')"
        >
          <li v-for="(item, i) in suggestions" :key="i">
            <button
              type="button"
              class="flex w-full items-center gap-3 rounded-control border px-2.5 py-2 text-left transition-colors"
              :class="
                picked === i
                  ? 'border-accent bg-accent/8'
                  : 'border-transparent hover:bg-surface-2'
              "
              :title="t('tagEdit.apply')"
              @click="use(item, i)"
            >
              <CoverArt
                :src="item.cover_url"
                :name="item.name"
                class="size-11 shrink-0"
                rounded="rounded-[6px]"
                :letter-size="16"
                :icon-size="18"
              />
              <span class="flex min-w-0 flex-1 flex-col">
                <span class="truncate text-sm font-medium">
                  {{ item.name }}
                </span>
                <span class="truncate text-[12px] text-muted">
                  {{
                    [
                      item.artists.join(', '),
                      item.album_name,
                      item.year,
                      item.track_number
                        ? t('tagEdit.trackNo', { n: item.track_number })
                        : '',
                      item.genre,
                    ]
                      .filter(Boolean)
                      .join(' · ')
                  }}
                </span>
              </span>
              <UiBadge :tone="item.source === 'youtube' ? 'ytm' : 'neutral'">
                {{ t(`tagEdit.source.${item.source}`) }}
              </UiBadge>
            </button>
          </li>
        </ul>
      </div>
    </div>

    <template #footer>
      <UiButton variant="ghost" @click="close">
        {{ t('common.cancel') }}
      </UiButton>
      <UiButton
        variant="primary"
        :loading="saving"
        :disabled="!form.name.trim() || !form.artists.trim()"
        @click="save"
      >
        {{ t('tagEdit.save') }}
      </UiButton>
    </template>
  </UiModal>
</template>

<script setup>
// "Edit info" (admins): rewrite a library track's tags - title, artists,
// album, year, track number, genre, explicit and cover - by hand or from a
// suggestion found on Apple Music, Deezer or YouTube Music. The file keeps
// its path and lyrics. Opened from a track's menu (model/editTags.js).
import { ref, watch } from 'vue'
import CoverArt from '../ui/CoverArt.vue'
import UiBadge from '../ui/UiBadge.vue'
import UiButton from '../ui/UiButton.vue'
import UiInput from '../ui/UiInput.vue'
import UiModal from '../ui/UiModal.vue'
import UiSwitch from '../ui/UiSwitch.vue'
import API from '/src/model/api'
import { useEditTags } from '/src/model/editTags'
import { useLibrary } from '/src/model/library'
import { useUi } from '/src/model/ui'
import { applySuggestion, editBody, formFrom } from '/src/lib/editTags'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const ui = useUi()
const library = useLibrary()
const { track, close: closeDialog } = useEditTags()

const form = ref(formFrom(null))
const coverUrl = ref('')
const query = ref('')
const suggestions = ref([])
const picked = ref(-1)
const loading = ref(false)
const searched = ref(false)
const saving = ref(false)
const error = ref('')

function errorOf(err) {
  return err?.response?.data?.detail || t('toast.actionFailed')
}

async function load(text = '', { fill = false } = {}) {
  if (!track.value) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await API.getTrackMetadata(track.value.file, text)
    if (fill) form.value = formFrom(data.track)
    query.value = data.query
    suggestions.value = data.suggestions
    picked.value = -1
  } catch (err) {
    suggestions.value = []
    error.value = errorOf(err)
  } finally {
    loading.value = false
    searched.value = true
  }
}

function search() {
  load(query.value.trim())
}

function use(item, index) {
  form.value = applySuggestion(form.value, item)
  if (item.cover_url) coverUrl.value = item.cover_url
  picked.value = index
}

async function save() {
  if (!track.value) return
  saving.value = true
  error.value = ''
  try {
    await API.editTrackMetadata(
      editBody(track.value.file, form.value, coverUrl.value)
    )
    ui.toast(t('tagEdit.saved'), { kind: 'success' })
    library.load({ force: true })
    close()
  } catch (err) {
    error.value = errorOf(err)
  } finally {
    saving.value = false
  }
}

function close() {
  closeDialog()
}

watch(
  () => track.value?.file,
  (file) => {
    form.value = formFrom({
      name: track.value?.title,
      artists: track.value?.artists,
    })
    coverUrl.value = ''
    query.value = ''
    suggestions.value = []
    picked.value = -1
    searched.value = false
    error.value = ''
    if (file) load('', { fill: true })
  }
)
</script>
