<template>
  <!-- A public page (a shared song) stands alone: no sign-in, no app
       around it. Nothing is drawn before the first route is known, so the
       app never starts - and asks the server for anything - on one. -->
  <template v-if="ready">
    <RouterView v-if="route.meta.public" />
    <AppShell v-else />
  </template>
</template>

<script setup>
import { defineAsyncComponent, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

// Loaded only off a public page: importing it starts the signed-in app
// (queue, likes, settings...), which a shared song's page must not.
const AppShell = defineAsyncComponent(
  () => import('./components/shell/AppShell.vue')
)

const route = useRoute()
const ready = ref(false)
useRouter()
  .isReady()
  .then(() => (ready.value = true))
</script>
