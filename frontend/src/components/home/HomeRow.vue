<template>
  <section class="flex min-w-0 flex-col gap-3">
    <div class="flex items-end justify-between gap-4">
      <div class="min-w-0">
        <h2 class="text-display truncate text-xl font-bold">{{ title }}</h2>
        <p v-if="subtitle" class="line-clamp-2 text-[13px] text-muted">
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
         every row below the fold. A scroller clips both ways, so it keeps
         room above for a tile lifted on hover (and its shadow), or the
         lift cuts the top of a round photo flat. -->
    <div
      ref="scroller"
      class="-mx-4 -mt-3 flex snap-x scroll-px-4 gap-4 overflow-x-auto px-4 pt-3 pb-3 [scrollbar-width:none] sm:-mx-6 sm:scroll-px-6 sm:px-6 lg:-mx-10 lg:scroll-px-10 lg:px-10 [&::-webkit-scrollbar]:hidden"
    >
      <slot />
    </div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from '/src/i18n'

// Tiles added in front after the row is drawn (the mixes that arrive
// last) would land off screen: scroll snapping keeps the tile it was on.
// Until someone scrolls the row themselves, it stays at its start.
const scroller = ref(null)
let touched = false
let observer = null
const touch = () => (touched = true)
onMounted(() => {
  const el = scroller.value
  if (!el) return
  for (const name of ['pointerdown', 'wheel', 'touchstart', 'keydown']) {
    el.addEventListener(name, touch, { passive: true })
  }
  observer = new MutationObserver(() => {
    if (!touched) el.scrollLeft = 0
  })
  observer.observe(el, { childList: true })
})
onBeforeUnmount(() => observer?.disconnect())

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  seeAll: { type: [String, Object], default: null },
})
const { t } = useI18n()
</script>
