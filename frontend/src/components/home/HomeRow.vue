<template>
  <section class="flex min-w-0 flex-col gap-3">
    <div class="flex items-end justify-between gap-4">
      <div class="min-w-0">
        <h2 class="text-display truncate text-xl font-bold">{{ title }}</h2>
        <p v-if="subtitle" class="truncate text-[13px] text-muted">
          {{ subtitle }}
        </p>
      </div>
      <RouterLink
        v-if="seeAll"
        :to="seeAll"
        class="shrink-0 text-[13px] font-semibold text-muted hover:text-fg hover:underline"
        >{{ t('common.seeAll') }}</RouterLink
      >
    </div>
    <!-- One row that scrolls sideways, as on Spotify; a grid would push
         every row below the fold. -->
    <div
      class="-mx-4 flex snap-x scroll-px-4 gap-4 overflow-x-auto px-4 pb-2 [scrollbar-width:none] sm:-mx-6 sm:scroll-px-6 sm:px-6 lg:-mx-10 lg:scroll-px-10 lg:px-10 [&::-webkit-scrollbar]:hidden"
    >
      <slot />
    </div>
  </section>
</template>

<script setup>
import { useI18n } from '/src/i18n'

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  seeAll: { type: [String, Object], default: null },
})
const { t } = useI18n()
</script>
