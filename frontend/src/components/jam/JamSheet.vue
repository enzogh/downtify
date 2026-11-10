<template>
  <!-- Spotify's Jam sheet: slides up over whatever plays (centred on a
       wide screen), so starting or running a Jam never leaves the music. -->
  <UiModal
    :open="sheet.open.value"
    :title="t('jam.title')"
    :description="jam.active.value ? '' : t('jam.subtitle')"
    width="sm:max-w-lg"
    @close="sheet.closeJamSheet()"
  >
    <JamPanel />
  </UiModal>
</template>

<script setup>
import UiModal from '../ui/UiModal.vue'
import JamPanel from './JamPanel.vue'
import { useJam } from '/src/model/jam'
import { useJamSheet } from '/src/model/jamSheet'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const jam = useJam()
const sheet = useJamSheet()
</script>
