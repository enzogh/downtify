<template>
  <details
    v-if="auth.isAdmin.value"
    class="group rounded-panel border border-line-2 bg-surface"
    @toggle="load"
  >
    <summary
      class="flex cursor-pointer list-none items-center gap-3 rounded-panel p-5 select-none sm:px-6 [&::-webkit-details-marker]:hidden"
    >
      <div class="min-w-0 flex-1">
        <h2
          class="text-display flex items-center gap-2 text-base font-semibold text-fg"
        >
          {{ t('downloadPolicy.exclusions') }}
          <UiBadge v-if="loaded && items.length">{{ items.length }}</UiBadge>
        </h2>
        <p class="mt-1 text-[13px] text-pretty text-muted">
          {{ t('queue.exclusionsHint') }}
        </p>
      </div>
      <AppIcon
        name="chevron-down"
        :size="18"
        class="shrink-0 text-muted transition-transform group-open:rotate-180"
      />
    </summary>
    <div class="px-5 pb-5 sm:px-6">
      <p v-if="error" role="alert" class="text-[13px] text-danger">
        {{ error }}
      </p>
      <p v-else-if="loaded && !items.length" class="text-[13px] text-muted">
        {{ t('downloadPolicy.empty') }}
      </p>
      <ul v-if="items.length" class="flex flex-col divide-y divide-line">
        <li
          v-for="item in items"
          :key="item.id"
          class="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0"
        >
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold">{{ item.title }}</p>
            <p class="truncate text-[13px] text-muted">
              {{ item.artist }} · {{ t(`downloadPolicy.${item.reason}`) }}
            </p>
          </div>
          <UiButton
            size="sm"
            variant="secondary"
            :disabled="busy"
            @click="resume(item.id)"
            >{{ t('downloadPolicy.resume') }}</UiButton
          >
        </li>
      </ul>
    </div>
  </details>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import API from '/src/model/api'
import { useAuth } from '/src/model/auth'
import { useI18n } from '/src/i18n'
import AppIcon from '/src/components/ui/AppIcon.vue'
import UiBadge from '/src/components/ui/UiBadge.vue'
import UiButton from '/src/components/ui/UiButton.vue'

const auth = useAuth(),
  { t } = useI18n()
const items = ref([]),
  error = ref(''),
  loaded = ref(false),
  busy = ref(false)
async function load() {
  if (!auth.isAdmin.value) return
  try {
    items.value = (await API.downloadExclusions()).data.items
    error.value = ''
    loaded.value = true
  } catch {
    error.value = t('downloadPolicy.error')
  }
}
async function resume(id) {
  busy.value = true
  try {
    await API.resumeDownload(id)
    await load()
  } catch {
    error.value = t('downloadPolicy.error')
  } finally {
    busy.value = false
  }
}
onMounted(() =>
  window.addEventListener('downtify-download-policy-changed', load)
)
onUnmounted(() =>
  window.removeEventListener('downtify-download-policy-changed', load)
)
</script>
