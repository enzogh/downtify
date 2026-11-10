<template>
  <UiModal
    :open="remote.pickerOpen.value"
    :title="t('remotePlayback.pickerTitle')"
    width="sm:max-w-md"
    @close="remote.pickerOpen.value = false"
  >
    <!-- This device: where the controls are. -->
    <p class="eyebrow mb-2">{{ t('remotePlayback.currentDevice') }}</p>
    <button
      type="button"
      class="flex w-full items-center gap-3.5 rounded-[14px] border p-3 text-left transition-colors"
      :class="
        hereActive
          ? 'border-accent/40 bg-accent/10'
          : 'border-line-2 hover:bg-surface-2'
      "
      :disabled="!canListenHere"
      @click="listenHere"
    >
      <span
        class="flex size-11 shrink-0 items-center justify-center rounded-full"
        :class="hereActive ? 'bg-accent text-on-accent' : 'bg-surface-2'"
      >
        <AppIcon :name="hereIcon" :size="20" />
      </span>
      <span class="min-w-0 flex-1">
        <span
          class="flex items-center gap-2 font-semibold"
          :class="hereActive ? 'text-accent' : ''"
        >
          {{ t('remotePlayback.thisDevice') }}
          <EqBars
            v-if="player.isPlaying.value"
            :size="11"
            class="text-accent"
          />
        </span>
        <span class="block truncate text-[13px] text-muted">
          {{ hereLine }}
        </span>
      </span>
    </button>

    <p class="eyebrow mt-6 mb-2">{{ t('remotePlayback.otherDevices') }}</p>
    <ul v-if="remote.devices.value.length" class="flex flex-col gap-1">
      <li v-for="row in remote.devices.value" :key="row.player">
        <div
          class="group flex items-center gap-3.5 rounded-[14px] p-3 transition-colors hover:bg-surface-2"
        >
          <button
            type="button"
            class="flex min-w-0 flex-1 items-center gap-3.5 text-left disabled:cursor-default"
            :disabled="!canSend && !row.track"
            :title="
              canSend
                ? t('remotePlayback.sendHere', { device: label(row) })
                : ''
            "
            @click="choose(row)"
          >
            <span
              class="flex size-11 shrink-0 items-center justify-center rounded-full"
              :class="
                isPlaying(row) ? 'bg-accent/15 text-accent' : 'bg-surface-2'
              "
            >
              <AppIcon :name="row.app ? 'smartphone' : 'monitor'" :size="20" />
            </span>
            <span class="min-w-0 flex-1">
              <span
                class="flex min-w-0 items-center gap-2 font-semibold"
                :class="isPlaying(row) ? 'text-accent' : ''"
              >
                <span class="truncate">{{ label(row) }}</span>
                <EqBars
                  v-if="isPlaying(row)"
                  :size="11"
                  class="shrink-0 text-accent"
                />
              </span>
              <span class="block truncate text-[13px] text-muted">
                {{ status(row) }}
              </span>
            </span>
          </button>
          <UiIconButton
            v-if="row.track"
            :icon="row.paused ? 'play' : 'pause'"
            :label="
              row.paused
                ? t('remotePlayback.resume')
                : t('remotePlayback.pause')
            "
            size="sm"
            @click="toggle(row)"
          />
        </div>
      </li>
    </ul>
    <UiEmpty
      v-else
      icon="devices"
      :title="t('remotePlayback.noOtherDevices')"
      :body="t('remotePlayback.noOtherDevicesHint')"
    />
    <!-- Spotify starts a Jam from here too: listening together. -->
    <button
      type="button"
      class="mt-5 flex w-full items-center gap-3.5 rounded-[14px] bg-gradient-to-r from-[#1e3264] via-[#2d46b9] to-[#509bf5] p-3 text-left text-white transition-transform active:scale-[0.99]"
      @click="openJam"
    >
      <span
        class="flex size-11 shrink-0 items-center justify-center rounded-full bg-white/15"
      >
        <AppIcon name="users" :size="20" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block font-semibold">{{
          jam.active.value ? t('jam.openJam') : t('jam.start')
        }}</span>
        <span class="block truncate text-[13px] text-white/75">{{
          jam.active.value
            ? t('jam.people', { count: jam.jam.value?.members.length || 0 })
            : t('jam.pickerHint')
        }}</span>
      </span>
      <AppIcon name="chevron-right" :size="18" class="text-white/70" />
    </button>

    <p
      v-if="remote.devices.value.length && !canSend"
      class="mt-3 text-[13px] text-muted"
    >
      {{ t('remotePlayback.nothingToSend') }}
    </p>
  </UiModal>
</template>

<script setup>
import { computed, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import AppIcon from '../ui/AppIcon.vue'
import EqBars from '../ui/EqBars.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiModal from '../ui/UiModal.vue'
import { usePlayer } from '/src/model/player'
import { useRemotePlayback } from '/src/model/remotePlayback'
import { useJam } from '/src/model/jam'
import { useJamSheet } from '/src/model/jamSheet'
import { useUi } from '/src/model/ui'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const ui = useUi()
const player = usePlayer()
const remote = useRemotePlayback()
const jam = useJam()
const jamSheet = useJamSheet()

function openJam() {
  remote.pickerOpen.value = false
  jamSheet.openJamSheet()
}
const touch = useMediaQuery('(pointer: coarse)')

// Playback sent here from another device: say so once.
watch(remote.movedHere, () =>
  ui.toast(t('remotePlayback.movedHere'), { kind: 'success' })
)

const hereIcon = computed(() => (touch.value ? 'smartphone' : 'monitor'))
const canSend = computed(() => Boolean(remote.localQueue()))
// The highlighted device: here while it plays, or while nothing plays
// anywhere else.
const hereActive = computed(
  () =>
    player.isPlaying.value ||
    !remote.devices.value.some((row) => isPlaying(row))
)
const canListenHere = computed(
  () => !player.isPlaying.value && Boolean(remote.remote.value)
)
const hereLine = computed(() => {
  const track = player.currentTrack.value
  if (track && player.isPlaying.value)
    return [track.title, track.artist].filter(Boolean).join(' · ')
  if (remote.remote.value) return t('remotePlayback.tapToListenHere')
  if (track) return t('remotePlayback.pausedState')
  return t('remotePlayback.idle')
})

function isPlaying(row) {
  return Boolean(row.track && !row.paused)
}

function label(row) {
  return row.client || t('remotePlayback.otherDevice')
}

function status(row) {
  if (!row.track) return t('remotePlayback.idle')
  const song = [row.track.title, row.track.artist].filter(Boolean).join(' · ')
  return row.paused
    ? `${t('remotePlayback.pausedState')} · ${song}`
    : song || t('remotePlayback.playingState')
}

async function choose(row) {
  if (!canSend.value) return
  if (await remote.sendTo(row)) {
    ui.toast(t('remotePlayback.playingOn', { device: label(row) }), {
      kind: 'success',
    })
    remote.pickerOpen.value = false
  } else {
    ui.toast(t('remotePlayback.gone'), { kind: 'error' })
  }
}

async function listenHere() {
  if (await remote.listenHere()) remote.pickerOpen.value = false
  else ui.toast(t('remotePlayback.cannotPlay'), { kind: 'error' })
}

async function toggle(row) {
  if (!(await remote.toggleRemote(row)))
    ui.toast(t('remotePlayback.gone'), { kind: 'error' })
}
</script>
