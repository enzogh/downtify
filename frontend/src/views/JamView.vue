<template>
  <div />
</template>

<script setup>
// `/jam` (and an invitation link, `/jam?code=`) no longer has a page of
// its own: it opens the Jam sheet over the page you came from - or over
// Home when the link was opened directly - so old links keep working.
import { useRoute, useRouter } from 'vue-router'
import { useJamSheet } from '/src/model/jamSheet'

const route = useRoute()
const router = useRouter()

useJamSheet().openJamSheet(String(route.query.code || ''))
if (window.history.state?.back) router.back()
else router.replace({ name: 'Home' })
</script>
