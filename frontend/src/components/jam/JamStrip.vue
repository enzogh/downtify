<template>
  <!-- While in a Jam: a coloured strip above the player, like Spotify's,
       saying who's listening along; a tap opens the Jam sheet. -->
  <Transition name="now-playing">
    <button
      v-if="snapshot"
      type="button"
      class="flex h-10 w-full items-center gap-2.5 rounded-[14px] bg-gradient-to-r from-[#1e3264] via-[#2d46b9] to-[#509bf5] px-3 text-left text-white shadow-float"
      :aria-label="t('jam.openJam')"
      @click="sheet.openJamSheet()"
    >
      <span class="flex -space-x-1.5" aria-hidden="true">
        <span
          v-for="member in faces"
          :key="member.id"
          class="flex size-6 items-center justify-center rounded-full bg-white text-[11px] font-bold text-[#1e3264] ring-2 ring-[#2d46b9]"
          >{{ avatarLetter(member.name) }}</span
        >
      </span>
      <span class="min-w-0 flex-1 truncate text-[13px] font-semibold">
        {{ t('jam.stripTitle') }} ·
        {{ t('jam.people', { count: snapshot.members.length }) }}
      </span>
      <span
        class="tabular rounded-full bg-white/15 px-2 py-0.5 font-mono text-[11px] font-bold tracking-[0.15em]"
        >{{ snapshot.code }}</span
      >
    </button>
  </Transition>
</template>

<script setup>
import { computed } from 'vue'
import { useJam } from '/src/model/jam'
import { useJamSheet } from '/src/model/jamSheet'
import { avatarLetter } from '/src/lib/viewMode'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const jam = useJam()
const sheet = useJamSheet()

const snapshot = computed(() => jam.jam.value)
const faces = computed(() => (snapshot.value?.members || []).slice(0, 4))
</script>
