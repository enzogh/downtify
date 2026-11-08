<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 28 28"
    class="shrink-0"
    role="img"
    aria-label="Castify"
  >
    <circle cx="14" cy="14" r="14" class="fill-accent" />
    <path
      d="M19.3 8.7A7.5 7.5 0 1 0 19.3 19.3"
      fill="none"
      stroke-width="3"
      stroke-linecap="round"
      class="stroke-bg"
    />
    <path
      d="M12.6 10.9v6.2a.6.6 0 0 0 .9.5l5-3.1a.6.6 0 0 0 0-1l-5-3.1a.6.6 0 0 0-.9.5z"
      class="fill-bg"
    />
  </svg>
</template>

<script setup>
// Same mark as the app (frontend/src/components/ui/AppLogo.vue).
defineProps({ size: { type: Number, default: 28 } })
</script>
