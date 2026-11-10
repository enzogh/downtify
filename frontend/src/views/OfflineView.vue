<template>
  <div
    class="mx-auto flex max-w-[1280px] flex-col gap-6 px-4 pt-6 pb-10 sm:px-6 md:pt-8 lg:px-10"
  >
    <PageHeader :title="t('offline.title')" :subtitle="t('offline.subtitle')">
      <UiButton
        v-if="offline.online.value"
        variant="ghost"
        icon="library"
        :to="{ name: 'Library' }"
      >
        {{ t('library.backToLibrary') }}
      </UiButton>
    </PageHeader>

    <UiEmpty
      v-if="offline.support === 'insecure'"
      icon="lock"
      :title="t('offline.unavailable')"
      :body="t('offline.needsHttps')"
    />
    <UiEmpty
      v-else-if="offline.support === 'unsupported'"
      icon="alert"
      :title="t('offline.unavailable')"
      :body="t('offline.unsupported')"
    />

    <template v-else-if="offline.loaded.value">
      <section
        class="flex flex-col gap-3 rounded-[12px] border border-line bg-surface p-4"
        :aria-label="t('offline.storage')"
      >
        <div class="flex flex-wrap items-baseline justify-between gap-2">
          <p class="text-[15px] font-semibold">
            {{
              t('offline.used', {
                size: formatBytes(offline.savedBytes.value),
                count: songCount,
              })
            }}
          </p>
          <p v-if="room" class="text-[13px] text-muted">
            {{ t('offline.room', { size: formatBytes(room) }) }}
          </p>
        </div>
        <UiProgress v-if="quota" :value="usedPct" :height="6" />
        <p class="text-[13px] text-muted">
          {{
            offline.persisted.value
              ? t('offline.persisted')
              : t('offline.notPersisted')
          }}
        </p>
        <div v-if="offline.collections.value.length" class="flex">
          <UiButton variant="ghost" icon="trash" size="sm" @click="clearAll">
            {{ t('offline.removeAll') }}
          </UiButton>
        </div>
      </section>

      <UiEmpty
        v-if="!offline.collections.value.length"
        icon="arrow-down-to-line"
        :title="t('offline.empty')"
        :body="t('offline.emptyHint')"
      />

      <ul v-else class="flex flex-col gap-2">
        <li
          v-for="item in offline.collections.value"
          :key="item.key"
          class="rounded-[12px] border border-line bg-surface"
        >
          <div class="flex items-center gap-3 p-3">
            <button
              type="button"
              class="flex min-w-0 flex-1 items-center gap-3 text-left"
              :aria-expanded="open === item.key"
              @click="open = open === item.key ? '' : item.key"
            >
              <CoverArt
                :src="item.tracks[0]?.cover || ''"
                :name="item.title"
                :icon="item.kind === 'album' ? 'disc' : 'playlist'"
                class="size-14 shrink-0"
                :icon-size="22"
                :letter-size="22"
              />
              <span class="min-w-0">
                <span class="block truncate font-semibold">{{
                  item.title
                }}</span>
                <span class="block truncate text-[13px] text-muted">
                  {{ describe(item) }}
                </span>
              </span>
            </button>
            <UiIconButton
              icon="play"
              :label="t('actions.playItem', { name: item.title })"
              :disabled="!item.tracks.length"
              @click="play(item)"
            />
            <UiIconButton
              icon="shuffle"
              :label="t('actions.shuffle')"
              :disabled="!item.tracks.length"
              @click="play(item, true)"
            />
            <UiIconButton
              v-if="offline.online.value && item.route"
              icon="arrow-up-right"
              :label="t('offline.open')"
              class="max-sm:hidden"
              @click="router.push(item.route)"
            />
            <UiIconButton
              icon="trash"
              :label="t('offline.remove')"
              @click="removeOne(item)"
            />
          </div>
          <div v-if="jobOf(item)?.state === 'saving'" class="px-3 pb-3">
            <UiProgress
              :value="(100 * jobOf(item).done) / (jobOf(item).total || 1)"
            />
          </div>
          <ol
            v-if="open === item.key"
            class="border-t border-line px-1 py-1 text-[14px]"
          >
            <li v-for="(track, i) in item.tracks" :key="track.file">
              <button
                type="button"
                class="flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left hover:bg-raised"
                @click="play(item, false, i)"
              >
                <span class="w-6 shrink-0 text-right text-muted tabular-nums">
                  {{ i + 1 }}
                </span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate">{{ track.title }}</span>
                  <span class="block truncate text-[12px] text-muted">{{
                    track.artist
                  }}</span>
                </span>
                <span class="shrink-0 text-[12px] text-muted tabular-nums">
                  {{ formatDuration(track.duration) }}
                </span>
              </button>
            </li>
          </ol>
        </li>
      </ul>
    </template>
  </div>
</template>

<script setup>
// What is saved on this device for offline listening (model/offline.js):
// works with no connection at all, from the index kept with the songs.
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '/src/components/library/PageHeader.vue'
import CoverArt from '/src/components/ui/CoverArt.vue'
import UiButton from '/src/components/ui/UiButton.vue'
import UiEmpty from '/src/components/ui/UiEmpty.vue'
import UiIconButton from '/src/components/ui/UiIconButton.vue'
import UiProgress from '/src/components/ui/UiProgress.vue'
import { formatBytes, formatDuration } from '/src/lib/format'
import { useOffline } from '/src/model/offline'
import { usePlayer } from '/src/model/player'
import { useUi } from '/src/model/ui'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const router = useRouter()
const ui = useUi()
const player = usePlayer()
const offline = useOffline()
const open = ref('')

const songCount = computed(() => Object.keys(offline.index.value.tracks).length)
const quota = computed(() => offline.usage.value?.quota || 0)
const room = computed(() =>
  quota.value ? Math.max(0, quota.value - offline.usage.value.usage) : 0
)
const usedPct = computed(() =>
  quota.value ? (100 * offline.usage.value.usage) / quota.value : 0
)

function jobOf(item) {
  return offline.jobs[item.key] || null
}

function describe(item) {
  const parts = [
    item.kind === 'album'
      ? [t('offline.album'), item.subtitle].filter(Boolean).join(' · ')
      : t('offline.playlist'),
    t('common.tracks', { count: item.tracks.length }),
    formatBytes(item.size),
  ]
  return parts.join(' · ')
}

function play(item, shuffled = false, index = 0) {
  const context = {
    type: item.kind,
    title: item.title,
    route: { name: 'Offline' },
  }
  if (shuffled) player.playList(item.tracks, { context, shuffled: true })
  else player.setPlaylist(item.tracks, { startIndex: index, context })
}

async function removeOne(item) {
  const ok = await ui.confirm({
    title: t('offline.removeTitle'),
    body: t('offline.removeBody', {
      name: item.title,
      size: formatBytes(item.size),
    }),
    confirmLabel: t('offline.remove'),
    danger: true,
  })
  if (ok) await offline.remove(item.kind, item.id)
}

async function clearAll() {
  const ok = await ui.confirm({
    title: t('offline.removeAllTitle'),
    body: t('offline.removeAllBody', {
      size: formatBytes(offline.savedBytes.value),
    }),
    confirmLabel: t('offline.removeAll'),
    danger: true,
  })
  if (ok) await offline.removeAll()
}

onMounted(() => {
  void offline.ensureLoaded()
  void offline.refreshUsage()
})
</script>
