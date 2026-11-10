<template>
  <RouterLink
    v-if="!offline.online.value && route.name !== 'Offline'"
    :to="{ name: 'Offline' }"
    class="flex items-center gap-3 rounded-[12px] border border-line bg-surface px-4 py-2.5 text-[14px] shadow-lg"
    role="status"
  >
    <AppIcon name="alert" :size="18" class="shrink-0 text-muted" />
    <span class="min-w-0 flex-1 truncate">{{ t('offline.banner') }}</span>
    <span class="shrink-0 font-semibold text-accent">
      {{ t('offline.bannerAction') }}
    </span>
  </RouterLink>
</template>

<script setup>
// Shown while the device has no connection: the songs saved for offline
// listening are one tap away (the rest of the app needs the server).
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import AppIcon from '../ui/AppIcon.vue'
import { useOffline } from '/src/model/offline'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const route = useRoute()
const offline = useOffline()

// With songs saved, load the offline page's code now (while online), so
// the service worker keeps it and it opens with no connection.
watch(
  () => offline.collections.value.length > 0 && offline.online.value,
  (warm) => {
    if (warm) import('/src/views/OfflineView.vue').catch(() => {})
  },
  { immediate: true }
)
</script>
