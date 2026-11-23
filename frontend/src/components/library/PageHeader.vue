<template>
  <!-- Mobile first: the title and its buttons share a row (Spotify's
       "Your Library"); on a phone the subtitle goes under that row so a
       long one doesn't push the buttons down. -->
  <div class="flex flex-col gap-1.5">
    <div
      class="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 sm:items-end"
    >
      <div class="flex min-w-0 items-center gap-4">
        <slot name="cover" />
        <div class="min-w-0">
          <h1 class="text-display text-[28px] font-bold sm:text-4xl">
            {{ title }}
          </h1>
          <p v-if="subtitle" class="mt-1.5 hidden text-sm text-muted sm:block">
            {{ subtitle }}
          </p>
        </div>
      </div>
      <div v-if="$slots.default" class="flex flex-wrap items-center gap-2">
        <slot />
      </div>
    </div>
    <p v-if="subtitle" class="text-[13px] text-muted sm:hidden">
      {{ subtitle }}
    </p>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>
