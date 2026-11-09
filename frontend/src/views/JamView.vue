<template>
  <div
    class="mx-auto flex max-w-[1100px] flex-col gap-6 px-4 pt-6 pb-10 sm:px-6 md:pt-8 lg:px-10"
  >
    <PageHeader :title="t('jam.title')" :subtitle="t('jam.subtitle')" />

    <!-- Not in a Jam: start one, or join with a code -->
    <div v-if="!jam.active.value" class="grid gap-4 md:grid-cols-2">
      <UiPanel :title="t('jam.startTitle')" :description="t('jam.startBody')">
        <div class="flex flex-wrap gap-2">
          <UiButton
            variant="primary"
            icon="users"
            :loading="jam.busy.value"
            @click="jam.start()"
          >
            {{ t('jam.start') }}
          </UiButton>
          <UiButton
            v-if="player.currentTrack.value?.file"
            icon="play"
            :disabled="jam.busy.value"
            @click="jam.startWithQueue()"
          >
            {{ t('jam.startWithQueue') }}
          </UiButton>
        </div>
      </UiPanel>

      <UiPanel :title="t('jam.joinTitle')" :description="t('jam.joinBody')">
        <form class="flex flex-wrap items-end gap-2" @submit.prevent="join">
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
        </form>
      </UiPanel>
    </div>

    <template v-else>
      <!-- The Jam: its code, who is in, and the switches -->
      <section
        class="flex flex-col gap-5 rounded-panel border border-line-2 bg-surface p-5 md:flex-row md:items-center md:justify-between"
      >
        <div class="min-w-0">
          <p class="text-xs font-semibold tracking-wide text-muted uppercase">
            {{
              jam.isHost.value
                ? t('jam.yourJam')
                : t('jam.hostedBy', { name: hostName })
            }}
          </p>
          <p
            class="tabular mt-1 font-mono text-4xl font-bold tracking-[0.2em] text-accent"
          >
            {{ snapshot.code }}
          </p>
          <div class="mt-3 flex flex-wrap gap-2">
            <UiButton size="sm" icon="copy" @click="copy(snapshot.code)">
              {{ t('jam.copyCode') }}
            </UiButton>
            <UiButton size="sm" icon="link" @click="copy(shareLink)">
              {{ t('jam.copyLink') }}
            </UiButton>
          </div>
        </div>
        <div class="flex min-w-0 flex-col gap-3 md:items-end">
          <ul class="flex flex-wrap gap-1.5 md:justify-end">
            <li
              v-for="member in snapshot.members"
              :key="member.id"
              class="flex items-center gap-1.5 rounded-full bg-surface-2 px-3 py-1 text-[13px] font-medium"
            >
              <AppIcon :name="member.host ? 'user' : 'users'" :size="13" />
              {{ member.name }}
              <span v-if="member.host" class="text-[11px] text-accent">{{
                t('jam.host')
              }}</span>
            </li>
          </ul>
          <UiButton
            size="sm"
            icon="log-out"
            :loading="jam.busy.value"
            @click="leave"
          >
            {{ jam.isHost.value ? t('jam.end') : t('jam.leave') }}
          </UiButton>
        </div>
      </section>

      <UiPanel :padded="false">
        <div class="divide-y divide-line-2">
          <div class="flex items-center justify-between gap-4 px-5 py-4">
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
            class="flex items-center justify-between gap-4 px-5 py-4"
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
            class="px-5 py-4 text-[13px] text-muted"
          >
            {{ t('jam.hostOnly') }}
          </p>
        </div>
      </UiPanel>

      <!-- The shared queue -->
      <section class="flex flex-col gap-2">
        <div class="flex items-baseline justify-between gap-3">
          <h2 class="text-lg font-bold">{{ t('jam.queue') }}</h2>
          <p class="text-[13px] text-muted">{{ t('jam.addHint') }}</p>
        </div>
        <UiEmpty
          v-if="!snapshot.queue.length"
          icon="playlist"
          :title="t('jam.emptyTitle')"
          :body="t('jam.emptyBody')"
        />
        <ol v-else class="flex flex-col gap-1">
          <li
            v-for="(item, index) in snapshot.queue"
            :key="item.id"
            class="group flex items-center gap-3 rounded-control px-2 py-1.5 transition-colors"
            :class="[
              index === snapshot.index
                ? 'bg-accent/10'
                : 'hover:bg-surface-2/60',
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
              <span
                class="tabular w-6 shrink-0 text-center text-[13px] text-muted"
              >
                <EqBars
                  v-if="index === snapshot.index && snapshot.playing"
                  :size="10"
                />
                <template v-else>{{ index + 1 }}</template>
              </span>
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
                  class="truncate text-sm font-semibold"
                  :class="index === snapshot.index ? 'text-accent' : ''"
                  >{{ item.title }}</span
                >
                <span class="truncate text-xs text-muted">{{
                  [item.artist, item.album].filter(Boolean).join(' · ')
                }}</span>
              </span>
            </button>
            <span class="hidden shrink-0 text-xs text-faint sm:inline">{{
              t('jam.addedBy', { name: item.added_by_name || '?' })
            }}</span>
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
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '../components/ui/AppIcon.vue'
import CoverArt from '../components/ui/CoverArt.vue'
import EqBars from '../components/ui/EqBars.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiIconButton from '../components/ui/UiIconButton.vue'
import UiInput from '../components/ui/UiInput.vue'
import UiPanel from '../components/ui/UiPanel.vue'
import UiSwitch from '../components/ui/UiSwitch.vue'
import PageHeader from '../components/library/PageHeader.vue'
import { useJam } from '/src/model/jam'
import { usePlayer } from '/src/model/player'
import { useUi } from '/src/model/ui'
import { codeFromInput } from '/src/lib/jam'
import { coverURL } from '/src/lib/paths'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const jam = useJam()
const player = usePlayer()
const ui = useUi()
const route = useRoute()
const router = useRouter()

const code = ref(codeFromInput(route.query.code))
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

watch(
  () => route.query.code,
  (value) => {
    if (value) code.value = codeFromInput(value)
  }
)
watch(code, () => (joinError.value = ''))

function mayRemove(item) {
  return jam.mayControl.value || item.added_by === jam.myId()
}

async function join() {
  if (!cleanCode.value) return
  const ok = await jam.join(cleanCode.value)
  if (!ok) {
    joinError.value = t('jam.unknownCode')
    return
  }
  // The code has done its job: a reload shouldn't offer to join again.
  if (route.query.code) router.replace({ name: 'Jam' })
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ui.toast(t('jam.copied'))
  } catch {
    ui.toast(text)
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
