<template>
  <!-- What a song row's marks mean, above lists that mix songs on the
       server with songs that would stream: a check is on the server, the
       rest play live from YouTube, the arrow saves one to the server. -->
  <p
    v-if="!libraryOnly"
    class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted"
  >
    <span class="inline-flex items-center gap-1.5">
      <AppIcon name="check-circle" :size="14" class="text-accent" />
      {{ t('search.legendOnServer') }}
    </span>
    <span class="inline-flex items-center gap-1.5">
      <AppIcon name="radio" :size="14" />
      {{ t('search.legendLive') }}
    </span>
    <span class="inline-flex items-center gap-1.5">
      <AppIcon name="download" :size="14" />
      {{ t('stream.save') }}
    </span>
  </p>
</template>

<script setup>
import AppIcon from '../ui/AppIcon.vue'
import { libraryOnly } from '/src/model/musicPolicy'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
</script>
