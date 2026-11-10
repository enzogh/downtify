<template>
  <!-- Not in a Jam: start one, or join with a code. -->
  <div v-if="!snapshot" class="flex flex-col gap-4">
    <section
      class="relative flex flex-col gap-4 overflow-hidden rounded-panel bg-gradient-to-br from-[#1e3264] via-[#2d46b9] to-[#509bf5] p-5 text-white"
    >
      <span
        class="pointer-events-none absolute -top-6 -right-6 flex size-32 items-center justify-center rounded-full bg-white/10"
        aria-hidden="true"
      >
        <AppIcon name="users" :size="56" class="text-white/70" />
      </span>
      <div class="relative max-w-[80%]">
        <h3 class="text-display text-xl font-bold">
          {{ t('jam.startTitle') }}
        </h3>
        <p class="mt-1 text-sm text-white/80">{{ t('jam.startBody') }}</p>
      </div>
      <div class="relative flex flex-wrap gap-2">
        <button
          type="button"
          class="inline-flex h-11 items-center gap-2 rounded-full bg-white px-5 text-sm font-bold text-[#0b0c0e] transition-transform active:scale-[0.97] disabled:opacity-60"
          :disabled="jam.busy.value"
          @click="start"
        >
          <AppIcon name="users" :size="18" />
          {{ t('jam.start') }}
        </button>
        <button
          v-if="player.currentTrack.value?.file"
          type="button"
          class="inline-flex h-11 items-center gap-2 rounded-full bg-white/15 px-4 text-sm font-semibold text-white transition-colors hover:bg-white/25 disabled:opacity-60"
          :disabled="jam.busy.value"
          @click="startWithQueue"
        >
          <AppIcon name="play" :size="16" />
          {{ t('jam.startWithQueue') }}
        </button>
      </div>
    </section>

    <form
      class="flex flex-col gap-3 rounded-panel border border-line-2 p-4"
      @submit.prevent="join"
    >
      <div>
        <p class="font-semibold">{{ t('jam.joinTitle') }}</p>
        <p class="mt-0.5 text-[13px] text-muted">{{ t('jam.joinBody') }}</p>
      </div>
      <div class="flex items-end gap-2">
        <UiInput
          v-model="code"
          class="min-w-0 flex-1"
          :label="t('jam.code')"
          :placeholder="t('jam.codePlaceholder')"
          mono
          :error="joinError"
        />
        <UiButton
          type="submit"
          variant="primary"
          :loading="jam.busy.value"
          :disabled="!cleanCode"
        >
          {{ t('jam.join') }}
        </UiButton>
      </div>
    </form>
  </div>

  <!-- In a Jam: invite, who's in, the switches and the shared queue. -->
  <div v-else class="flex flex-col gap-5">
    <section
      class="flex flex-col items-center gap-4 rounded-panel bg-gradient-to-br from-[#1e3264] via-[#2d46b9] to-[#509bf5] p-5 text-center text-white"
    >
      <p class="text-xs font-semibold tracking-wide text-white/75 uppercase">
        {{
          jam.isHost.value
            ? t('jam.yourJam')
            : t('jam.hostedBy', { name: hostName })
        }}
      </p>
      <svg
        :viewBox="`-2 -2 ${qr.size + 4} ${qr.size + 4}`"
        class="size-40 rounded-[14px] bg-white shadow-float"
        role="img"
        :aria-label="t('jam.qrLabel')"
        shape-rendering="crispEdges"
      >
        <path :d="qr.d" fill="#000" />
      </svg>
      <p
        class="tabular font-mono text-3xl font-bold tracking-[0.25em] select-all"
      >
        {{ snapshot.code }}
      </p>
      <div class="flex flex-wrap justify-center gap-2">
        <button
          type="button"
          class="inline-flex h-10 items-center gap-2 rounded-full bg-white px-4 text-sm font-bold text-[#0b0c0e] transition-transform active:scale-[0.97]"
          @click="invite"
        >
          <AppIcon :name="canShare ? 'share' : 'link'" :size="16" />
          {{ canShare ? t('jam.invite') : t('jam.copyLink') }}
        </button>
        <button
          type="button"
          class="inline-flex h-10 items-center gap-2 rounded-full bg-white/15 px-4 text-sm font-semibold transition-colors hover:bg-white/25"
          @click="copy(snapshot.code)"
        >
          <AppIcon name="copy" :size="16" />
          {{ t('jam.copyCode') }}
        </button>
      </div>
    </section>

    <section class="flex flex-col gap-2">
      <p class="eyebrow">
        {{ t('jam.people', { count: snapshot.members.length }) }}
      </p>
      <ul class="flex flex-wrap gap-2">
        <li
          v-for="member in snapshot.members"
          :key="member.id"
          class="flex items-center gap-2 rounded-full bg-surface-2 py-1 pr-3 pl-1 text-[13px] font-medium"
        >
          <span
            class="flex size-7 items-center justify-center rounded-full text-xs font-bold"
            :class="
              member.host
                ? 'bg-accent text-on-accent'
                : 'bg-invert text-on-invert'
            "
            >{{ avatarLetter(member.name) }}</span
          >
          {{ member.name }}
          <span v-if="member.host" class="text-[11px] text-accent">{{
            t('jam.host')
          }}</span>
        </li>
      </ul>
    </section>

    <div class="divide-y divide-line-2 rounded-panel border border-line-2">
      <div class="flex items-center justify-between gap-4 px-4 py-3.5">
        <div class="min-w-0">
          <p class="text-sm font-semibold">{{ t('jam.listenHere') }}</p>
          <p class="mt-0.5 text-[13px] text-muted">
            {{ t('jam.listenHereBody') }}
          </p>
        </div>
        <UiSwitch
          :model-value="jam.listenHere.value"
          :aria-label="t('jam.listenHere')"
          @update:model-value="jam.setListenHere($event)"
        />
      </div>
      <div
        v-if="jam.isHost.value"
        class="flex items-center justify-between gap-4 px-4 py-3.5"
      >
        <div class="min-w-0">
          <p class="text-sm font-semibold">{{ t('jam.guestsControl') }}</p>
          <p class="mt-0.5 text-[13px] text-muted">
            {{ t('jam.guestsControlBody') }}
          </p>
        </div>
        <UiSwitch
          :model-value="snapshot.guests_can_control"
          :aria-label="t('jam.guestsControl')"
          @update:model-value="jam.setGuestsCanControl($event)"
        />
      </div>
      <p
        v-else-if="!jam.mayControl.value"
        class="px-4 py-3.5 text-[13px] text-muted"
      >
        {{ t('jam.hostOnly') }}
      </p>
    </div>

    <!-- The shared queue -->
    <section class="flex flex-col gap-2">
      <div class="flex items-baseline justify-between gap-3">
        <h3 class="text-base font-bold">{{ t('jam.queue') }}</h3>
        <p class="text-[12px] text-muted">{{ t('jam.addHint') }}</p>
      </div>
      <UiEmpty
        v-if="!snapshot.queue.length"
        icon="playlist"
        :title="t('jam.emptyTitle')"
        :body="t('jam.emptyBody')"
      />
      <ol v-else class="flex flex-col gap-0.5">
        <li
          v-for="(item, index) in snapshot.queue"
          :key="item.id"
          class="group flex items-center gap-3 rounded-control px-2 py-1.5 transition-colors"
          :class="[
            index === snapshot.index ? 'bg-accent/10' : 'hover:bg-surface-2/60',
            index < snapshot.index ? 'opacity-55' : '',
          ]"
        >
          <button
            type="button"
            class="flex min-w-0 flex-1 items-center gap-3 text-left disabled:cursor-default"
            :disabled="!jam.mayControl.value"
            :aria-label="t('actions.playItem', { name: item.title })"
            @click="jam.jumpTo(index)"
          >
            <CoverArt
              :thumb="150"
              :src="coverURL(item.file)"
              :name="item.album || item.title"
              rounded="rounded-[8px]"
              :letter-size="14"
              :icon-size="14"
              class="size-10"
            />
            <span class="flex min-w-0 flex-col">
              <span
                class="flex items-center gap-2 truncate text-sm font-semibold"
                :class="index === snapshot.index ? 'text-accent' : ''"
              >
                <EqBars
                  v-if="index === snapshot.index && snapshot.playing"
                  :size="10"
                  class="shrink-0"
                />
                <span class="truncate">{{ item.title }}</span>
              </span>
              <span class="truncate text-xs text-muted">{{
                [
                  item.artist,
                  t('jam.addedBy', { name: item.added_by_name || '?' }),
                ]
                  .filter(Boolean)
                  .join(' · ')
              }}</span>
            </span>
          </button>
          <UiIconButton
            v-if="mayRemove(item)"
            icon="x"
            size="sm"
            :label="t('jam.remove', { name: item.title })"
            @click="jam.removeItem(item.id)"
          />
        </li>
      </ol>
    </section>

    <UiButton
      variant="secondary"
      icon="log-out"
      class="self-center"
      :loading="jam.busy.value"
      @click="leave"
    >
      {{ jam.isHost.value ? t('jam.end') : t('jam.leave') }}
    </UiButton>
  </div>
</template>

<script setup>
// What a Jam needs, in the Jam sheet (JamSheet.vue): starting or joining
// one, then inviting people (QR code, link, code), who's in, the
// switches and the shared queue - updated live from the server.
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../ui/AppIcon.vue'
import CoverArt from '../ui/CoverArt.vue'
import EqBars from '../ui/EqBars.vue'
import UiButton from '../ui/UiButton.vue'
import UiEmpty from '../ui/UiEmpty.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiInput from '../ui/UiInput.vue'
import UiSwitch from '../ui/UiSwitch.vue'
import { useJam } from '/src/model/jam'
import { useJamSheet } from '/src/model/jamSheet'
import { usePlayer } from '/src/model/player'
import { useUi } from '/src/model/ui'
import { qrPath } from '/src/lib/auth'
import { codeFromInput } from '/src/lib/jam'
import { coverURL } from '/src/lib/paths'
import { avatarLetter } from '/src/lib/viewMode'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const jam = useJam()
const sheet = useJamSheet()
const player = usePlayer()
const ui = useUi()
const router = useRouter()

const code = ref(sheet.pendingCode.value)
const joinError = ref('')
const cleanCode = computed(() => codeFromInput(code.value))
const snapshot = computed(() => jam.jam.value)
const hostName = computed(
  () => snapshot.value?.members.find((m) => m.host)?.name || ''
)
const shareLink = computed(() => {
  if (!snapshot.value || typeof location === 'undefined') return ''
  const href = router.resolve({
    name: 'Jam',
    query: { code: snapshot.value.code },
  }).href
  return `${location.origin}${href}`
})
const qr = computed(() => qrPath(shareLink.value || snapshot.value?.code))
const canShare = typeof navigator !== 'undefined' && !!navigator.share

// An invitation link opened the sheet: its code is ready to join.
watch(sheet.pendingCode, (value) => {
  if (value) code.value = value
})
watch(code, () => (joinError.value = ''))

function mayRemove(item) {
  return jam.mayControl.value || item.added_by === jam.myId()
}

async function start() {
  await jam.start()
}

async function startWithQueue() {
  await jam.startWithQueue()
}

async function join() {
  if (!cleanCode.value) return
  const ok = await jam.join(cleanCode.value)
  if (!ok) {
    joinError.value = t('jam.unknownCode')
    return
  }
  sheet.pendingCode.value = ''
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ui.toast(t('jam.copied'))
  } catch {
    ui.toast(text)
  }
}

// The phone's own share sheet when there is one, else the link copied.
async function invite() {
  if (!canShare) return copy(shareLink.value)
  try {
    await navigator.share({
      title: t('jam.title'),
      text: t('jam.inviteText', { code: snapshot.value.code }),
      url: shareLink.value,
    })
  } catch {
    // Dismissed: nothing to do.
  }
}

async function leave() {
  const ok = await ui.confirm({
    title: jam.isHost.value ? t('jam.endConfirm') : t('jam.leaveConfirm'),
    body: jam.isHost.value ? t('jam.endConfirmBody') : '',
    confirmLabel: jam.isHost.value ? t('jam.end') : t('jam.leave'),
    danger: jam.isHost.value,
  })
  if (ok) await jam.leave()
}
</script>
