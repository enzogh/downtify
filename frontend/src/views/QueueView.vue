<template>
  <div
    class="mx-auto flex max-w-[1680px] flex-col gap-6 px-4 pt-6 sm:px-6 md:pt-8 lg:px-10"
  >
    <PageHeader :title="t('queue.title')" :subtitle="subtitle">
      <template v-if="auth.isAdmin.value">
        <UiButton
          v-if="queuePause.paused.value"
          variant="primary"
          icon="play"
          :loading="queuePause.busy.value"
          @click="toggleQueue(queuePause.resume)"
        >
          {{ t('queue.resume') }}
        </UiButton>
        <UiButton
          v-else
          variant="secondary"
          icon="pause"
          :loading="queuePause.busy.value"
          @click="toggleQueue(queuePause.pause)"
        >
          {{ t('queue.pause') }}
        </UiButton>
      </template>
    </PageHeader>

    <div
      v-if="queuePause.paused.value"
      role="status"
      class="flex items-start gap-3.5 rounded-panel border border-warn/25 bg-warn/6 p-4 sm:items-center"
    >
      <span
        class="flex size-10 shrink-0 items-center justify-center rounded-full bg-warn/12 text-warn"
      >
        <AppIcon
          :name="queuePause.draining.value ? 'clock' : 'pause'"
          :size="18"
        />
      </span>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold">
          {{
            queuePause.draining.value
              ? t('queue.pausingTitle')
              : t('queue.pausedTitle')
          }}
        </p>
        <p class="mt-0.5 text-[13px] text-muted">
          {{
            queuePause.draining.value
              ? t('queue.pausingBody', {
                  count: queuePause.status.active,
                })
              : t('queue.pausedBody')
          }}
          {{ t('queue.pausedKept') }}
        </p>
      </div>
    </div>

    <UiTabs :items="tabs" :model-value="tab" />

    <div class="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div class="flex min-w-0 flex-col gap-3">
        <!-- One action in plain words (retry what failed), the rest
             named in a menu - no row of bare icons. -->
        <div v-if="queue.length" class="flex items-center gap-2">
          <UiButton
            v-if="counts.failed"
            size="sm"
            variant="secondary"
            icon="retry"
            @click="dm.retryAllFailed()"
          >
            {{ t('queue.retryFailed', { count: counts.failed }) }}
          </UiButton>
          <UiMenu
            class="ml-auto"
            :items="queueMenu"
            :label="t('common.more')"
            size="sm"
          />
        </div>
        <UiEmpty
          v-if="!queue.length"
          icon="download"
          :title="t('queue.emptyTitle')"
          :body="t('queue.emptyBody')"
        >
          <UiButton variant="primary" icon="search" @click="ui.focusSearch()">
            {{ t('queue.emptyAction') }}
          </UiButton>
        </UiEmpty>

        <UiEmpty
          v-else-if="!items.length"
          :icon="tab === 'failed' ? 'check-circle' : 'clock'"
          :title="t(`queue.emptyTab.${tab}`)"
          :body="
            tab === 'active' && counts.queued
              ? queuePause.paused.value
                ? t('queue.pausedBody')
                : t('queue.waitingHint', { count: counts.queued })
              : ''
          "
        />

        <div
          v-else
          ref="listRoot"
          class="relative overflow-hidden rounded-panel border border-line-2 bg-surface"
          :style="{ height: `${totalSize + 2}px` }"
        >
          <div
            v-for="row in rows"
            :key="row.key"
            :ref="measureRow"
            :data-index="row.index"
            class="absolute inset-x-0 top-0"
            :class="row.index ? 'border-t border-line' : ''"
            :style="{ transform: `translateY(${row.start}px)` }"
          >
            <div
              v-if="row.header"
              class="flex h-[43px] items-center gap-2 bg-surface-2/40 px-4"
            >
              <span class="eyebrow">{{ sectionLabel(row.header) }}</span>
              <UiBadge :tone="row.header === 'failed' ? 'danger' : 'neutral'">
                {{ row.count }}
              </UiBadge>
            </div>
            <QueueItem
              v-else
              :item="row.item"
              :compact="
                row.item.state === 'queued' || row.item.state === 'done'
              "
            />
          </div>
        </div>
        <p
          v-if="doneTrimmed && items.length"
          class="mt-3 text-center text-xs text-muted"
        >
          {{
            t('queue.doneTrimmed', {
              shown: MAX_DONE_SHOWN,
              total: counts.done,
            })
          }}
        </p>
      </div>

      <aside class="flex flex-col gap-4 xl:sticky xl:top-[96px]">
        <DownloadExclusions />
        <UiPanel
          v-if="activeBatches.length"
          :title="t('queue.playlistDownloads')"
        >
          <ul class="flex flex-col gap-4">
            <li v-for="batch in activeBatches" :key="batch.spotify_playlist_id">
              <RouterLink
                :to="{ name: 'Playlist', query: { name: batch.playlist_name } }"
                class="flex items-center justify-between gap-3 text-sm"
              >
                <span class="truncate font-semibold hover:underline">{{
                  batch.playlist_name
                }}</span>
                <span class="tabular shrink-0 text-xs text-muted">
                  {{ batch.downloaded_count }} / {{ batch.expected_count }}
                </span>
              </RouterLink>
              <UiProgress
                class="mt-2"
                :value="
                  batch.expected_count
                    ? (batch.downloaded_count / batch.expected_count) * 100
                    : 0
                "
              />
            </li>
          </ul>
        </UiPanel>

        <UiPanel v-if="queue.length" :title="t('queue.sources')">
          <ul class="flex flex-col gap-2.5">
            <li
              v-for="source in sourceCounts"
              :key="source.id"
              class="flex items-center justify-between gap-3"
            >
              <SourceBadge :source="source.id" />
              <span class="tabular text-sm text-muted">{{ source.count }}</span>
            </li>
            <li v-if="!sourceCounts.length" class="text-[13px] text-muted">
              {{ t('queue.noSourcesYet') }}
            </li>
          </ul>
        </UiPanel>

        <UiPanel
          :title="t('queue.importTitle')"
          :description="t('queue.importHint')"
        >
          <CsvImport />
        </UiPanel>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWindowVirtualizer } from '@tanstack/vue-virtual'
import AppIcon from '/src/components/ui/AppIcon.vue'
import UiButton from '/src/components/ui/UiButton.vue'
import UiBadge from '/src/components/ui/UiBadge.vue'
import UiEmpty from '/src/components/ui/UiEmpty.vue'
import UiMenu from '/src/components/ui/UiMenu.vue'
import UiPanel from '/src/components/ui/UiPanel.vue'
import UiProgress from '/src/components/ui/UiProgress.vue'
import UiTabs from '/src/components/ui/UiTabs.vue'
import SourceBadge from '/src/components/ui/SourceBadge.vue'
import PageHeader from '/src/components/library/PageHeader.vue'
import QueueItem from '/src/components/queue/QueueItem.vue'
import DownloadExclusions from '/src/components/queue/DownloadExclusions.vue'
import CsvImport from '/src/components/queue/CsvImport.vue'
import {
  useDownloadManager,
  useProgressTracker,
  syncQueueFromServer,
} from '/src/model/download'
import { useAuth } from '/src/model/auth'
import { useLibrary } from '/src/model/library'
import { useQueuePause } from '/src/model/queuePause'
import { useUi } from '/src/model/ui'
import {
  MAX_DONE_SHOWN,
  QUEUE_SECTION_ORDER,
  latestDone,
  queueRowEstimate,
  queueRows,
} from '/src/lib/queueList'
import { shouldJumpToActive } from '/src/lib/queueTab'
import { useI18n } from '/src/i18n'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const dm = useDownloadManager()
const tracker = useProgressTracker()
const library = useLibrary()
const ui = useUi()
const auth = useAuth()
const queuePause = useQueuePause()
const listRoot = ref(null)
const scrollMargin = ref(0)

syncQueueFromServer().catch(() => {})
queuePause.refresh().catch(() => {})

// In User view an admin's queue shows only their own downloads, like
// any user's.
const queue = computed(() => {
  tracker.queueVersion.value
  const all = tracker.downloadQueue.value
  return auth.isAdmin.value ? all : all.filter((item) => item.mine)
})

const counts = computed(() => {
  const result = { active: 0, queued: 0, done: 0, failed: 0, others: 0 }
  for (const item of queue.value) {
    result[item.state] += 1
    if (!item.mine) result.others += 1
  }
  return result
})

const TABS = ['active', 'queued', 'done', 'failed', 'all']
const tab = computed(() => {
  const requested = String(route.params.tab || '')
  if (TABS.includes(requested)) return requested
  return counts.value.active || counts.value.queued ? 'active' : 'all'
})

// Jump to "In progress" as soon as downloads start.
watch(
  () => counts.value.active,
  (now, before) => {
    if (shouldJumpToActive(now, before, tab.value)) {
      router.replace({ name: 'Queue', params: { tab: 'active' } })
    }
  }
)

const tabs = computed(() =>
  [
    ['active', t('queue.tabActive'), counts.value.active],
    ['queued', t('queue.tabQueued'), counts.value.queued],
    ['done', t('queue.tabDone'), counts.value.done],
    ['failed', t('queue.tabFailed'), counts.value.failed],
    ['all', t('queue.tabAll'), queue.value.length],
  ].map(([id, label, count]) => ({
    id,
    label,
    count,
    to: { name: 'Queue', params: { tab: id } },
  }))
)

const SECTION_LABELS = {
  active: 'queue.tabActive',
  queued: 'queue.tabQueued',
  done: 'queue.tabDone',
  failed: 'queue.tabFailed',
}
function sectionLabel(state) {
  return t(SECTION_LABELS[state])
}

const items = computed(() => {
  // Only the latest finished ones (newest first): the rest stay counted.
  if (tab.value === 'all') {
    return latestDone(queue.value).sort(
      (a, b) =>
        QUEUE_SECTION_ORDER.indexOf(a.state) -
        QUEUE_SECTION_ORDER.indexOf(b.state)
    )
  }
  const list = queue.value.filter((item) => item.state === tab.value)
  return tab.value === 'done' ? latestDone(list) : list
})
const doneTrimmed = computed(
  () =>
    (tab.value === 'done' || tab.value === 'all') &&
    counts.value.done > MAX_DONE_SHOWN
)

// The "All" tab splits the list into sections with a heading each.
const listRows = computed(() => queueRows(items.value, tab.value === 'all'))

const virtualizer = useWindowVirtualizer(
  computed(() => ({
    count: listRows.value.length,
    estimateSize: (index) => {
      const row = listRows.value[index]
      return queueRowEstimate(row?.header ? 'header' : row?.item.state)
    },
    getItemKey: (index) => listRows.value[index]?.key ?? index,
    overscan: 8,
    scrollMargin: scrollMargin.value,
  }))
)

function measureOffset() {
  if (!listRoot.value) return
  scrollMargin.value =
    listRoot.value.getBoundingClientRect().top + window.scrollY
}

function measureRow(el) {
  if (el) virtualizer.value.measureElement(el)
}

onMounted(measureOffset)
watch(
  () => [tab.value, items.value.length, queuePause.paused.value],
  () => requestAnimationFrame(measureOffset)
)

const totalSize = computed(() => virtualizer.value.getTotalSize())
const rows = computed(() =>
  virtualizer.value
    .getVirtualItems()
    .map((row) => ({
      ...listRows.value[row.index],
      index: row.index,
      start: row.start - scrollMargin.value,
    }))
    .filter((row) => row.key)
)

const subtitle = computed(() => {
  if (!queue.value.length) return ''
  return [
    t('queue.countActive', { count: counts.value.active }),
    t('queue.countQueued', { count: counts.value.queued }),
    counts.value.failed
      ? t('queue.countFailed', { count: counts.value.failed })
      : '',
  ]
    .filter(Boolean)
    .join(' · ')
})

const sourceCounts = computed(() => {
  const map = new Map()
  for (const item of queue.value) {
    if (item.state !== 'done' || !item.provider) continue
    map.set(item.provider, (map.get(item.provider) || 0) + 1)
  }
  return [...map.entries()]
    .map(([id, count]) => ({ id, count }))
    .sort((a, b) => b.count - a.count)
})

const activeBatches = computed(() =>
  library.batches.value.filter(
    (batch) => batch.active_in_queue || batch.status === 'in_progress'
  )
)

// Keep playlist progress fresh while something is downloading.
watch(
  () => counts.value.done,
  () => library.refreshSoon(1500)
)

async function toggleQueue(change) {
  try {
    await change()
  } catch {
    ui.toast(t('queue.pauseFailed'), { kind: 'error' })
  }
}

const queueMenu = computed(() => [
  {
    hidden: !counts.value.done,
    label: t('queue.clearDone', { count: counts.value.done }),
    icon: 'check',
    action: () => dm.clearCompleted(),
  },
  {
    hidden: !(auth.isAdmin.value && counts.value.others),
    label: t('queue.clearOthers', { count: counts.value.others }),
    icon: 'users',
    action: clearOthers,
  },
  { divider: true, hidden: !counts.value.done && !counts.value.others },
  {
    label: t('queue.clearAll'),
    icon: 'trash',
    danger: true,
    action: clearAll,
  },
])

async function clearOthers() {
  const ok = await ui.confirm({
    title: t('queue.clearOthersTitle'),
    body: t('queue.clearOthersBody'),
    confirmLabel: t('queue.clearOthers', { count: counts.value.others }),
  })
  if (!ok) return
  try {
    await dm.clearOthers()
  } catch {
    ui.toast(t('queue.clearOthersFailed'), { kind: 'error' })
  }
}

async function clearAll() {
  const ok = await ui.confirm({
    title: t('confirm.clearQueueTitle'),
    body: t('confirm.clearQueueBody'),
    confirmLabel: t('queue.clearAll'),
    danger: true,
  })
  if (ok) await dm.clearAll()
}
</script>
