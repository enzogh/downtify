<template>
  <SettingGroup :title="t('autoplay.title')">
    <SettingRow :label="t('autoplay.label')" :description="t('autoplay.hint')">
      <UiSwitch
        :model-value="autoplay.enabled.value"
        :aria-label="t('autoplay.label')"
        @update:model-value="autoplay.setAutoplay($event)"
      />
    </SettingRow>
  </SettingGroup>
</template>

<script setup>
// Autoplay: per device, like the volume (see model/autoplay.js).
import SettingGroup from './SettingGroup.vue'
import SettingRow from './SettingRow.vue'
import UiSwitch from '../ui/UiSwitch.vue'
import { useAutoplay } from '/src/model/autoplay'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const autoplay = useAutoplay()
</script>
