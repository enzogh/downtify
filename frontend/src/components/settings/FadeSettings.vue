<template>
  <SettingGroup :title="t('fade.title')" :description="t('fade.hint')">
    <SettingRow :label="t('fade.length')" :description="lengthLabel" stacked>
      <input
        :value="player.fadeSeconds.value"
        type="range"
        min="0"
        :max="MAX_FADE_SECONDS"
        step="1"
        class="w-full accent-accent"
        :aria-label="t('fade.length')"
        :aria-valuetext="lengthLabel"
        @input="player.setFadeSeconds($event.target.value)"
      />
    </SettingRow>
    <SettingRow
      :label="t('fade.gapless')"
      :description="
        player.fadeSeconds.value
          ? t('fade.gaplessFading')
          : t('fade.gaplessHint')
      "
    >
      <UiSwitch
        :model-value="player.gapless.value"
        :disabled="!!player.fadeSeconds.value"
        :aria-label="t('fade.gapless')"
        @update:model-value="player.setGapless($event)"
      />
    </SettingRow>
  </SettingGroup>
</template>

<script setup>
// "Fade between songs" and "Gapless playback": per device, like the
// volume (see model/player.js).
import { computed } from 'vue'
import SettingGroup from './SettingGroup.vue'
import SettingRow from './SettingRow.vue'
import UiSwitch from '../ui/UiSwitch.vue'
import { MAX_FADE_SECONDS } from '/src/lib/fade'
import { usePlayer } from '/src/model/player'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const player = usePlayer()

const lengthLabel = computed(() =>
  player.fadeSeconds.value
    ? t('fade.seconds', { count: player.fadeSeconds.value })
    : t('fade.off')
)
</script>
