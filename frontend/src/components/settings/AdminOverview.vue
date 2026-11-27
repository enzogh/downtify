<template>
  <!-- The admin panel's first page: what the server holds, who listens
       and to what (from everyone's listening history), what is playing
       now and what needs a look - each figure leading to where it is
       managed. -->
  <div class="flex min-w-0 flex-col gap-8">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="text-[13px] text-muted">{{ t('admin.periodHint') }}</p>
      <UiSegmented
        v-model="days"
        :options="periodOptions"
        show-labels
        :aria-label="t('admin.period')"
      />
    </div>

    <!-- Headline figures -->
    <Transition name="reveal" mode="out-in">
      <div
        v-if="!loaded"
        key="skeleton"
        class="grid grid-cols-2 gap-3 lg:grid-cols-4"
        aria-busy="true"
      >
        <UiSkeleton v-for="n in 4" :key="n" class="h-[104px] !rounded-panel" />
      </div>
      <div v-else key="tiles" class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <component
          :is="tile.to ? RouterLink : 'div'"
          v-for="tile in tiles"
          :key="tile.id"
          :to="tile.to"
          class="flex min-w-0 flex-col gap-1 rounded-panel border border-line-2 bg-surface px-4 py-3.5"
          :class="tile.to ? 'transition-colors hover:bg-surface-2' : ''"
        >
          <span
            class="flex items-center gap-1.5 text-[12px] font-semibold text-muted"
          >
            <AppIcon :name="tile.icon" :size="14" :class="tile.tone" />
            {{ tile.label }}
          </span>
          <span class="tabular text-display truncate text-2xl font-bold">{{
            tile.value
          }}</span>
          <span class="truncate text-[12px] text-faint">{{ tile.hint }}</span>
        </component>
      </div>
    </Transition>

    <!-- Plays per day: one series, so no legend - the title names it. -->
    <SettingGroup
      :title="t('admin.chartTitle')"
      :description="t('admin.chartHint', { days })"
    >
      <div class="px-5 pt-2 pb-4">
        <UiSkeleton v-if="!loaded" class="h-40 w-full" />
        <p
          v-else-if="!listening?.totals.plays"
          class="py-10 text-center text-sm text-muted"
        >
          {{ t('admin.noPlays') }}
        </p>
        <template v-else>
          <div
            class="relative flex h-40 items-end gap-[2px] border-b border-line"
            role="img"
            :aria-label="chartLabel"
            @pointerleave="hover = -1"
          >
            <div
              v-for="(day, i) in listening.per_day"
              :key="day.day"
              class="flex h-full min-w-0 flex-1 items-end"
              @pointerenter="hover = i"
            >
              <div
                class="w-full rounded-t-[4px] transition-opacity duration-(--dur-fast) ease-out-soft"
                :class="[
                  day.plays ? 'bg-accent' : 'bg-line',
                  hover >= 0 && hover !== i ? 'opacity-50' : '',
                ]"
                :style="{ height: barHeight(day.plays) }"
              />
            </div>
            <div
              v-if="hover >= 0"
              class="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full rounded-control border border-line-2 bg-raised px-2.5 py-1.5 text-[12px] whitespace-nowrap shadow-float"
              :style="{ left: tipLeft }"
            >
              <span class="font-semibold">{{
                dayLabel(listening.per_day[hover].day)
              }}</span>
              <span class="text-muted">
                ·
                {{
                  t('admin.plays', { count: listening.per_day[hover].plays })
                }}
                ·
                {{ hoursText(listening.per_day[hover].seconds) }}</span
              >
            </div>
          </div>
          <div class="mt-1.5 flex justify-between text-[11px] text-faint">
            <span>{{ dayLabel(listening.per_day[0].day) }}</span>
            <span>{{ t('admin.today') }}</span>
          </div>
          <p class="mt-3 text-[12px] text-muted">
            {{
              t('admin.chartSummary', {
                skips: percent(listening.totals.skip_rate),
                streamed: percent(listening.totals.stream_share),
              })
            }}
          </p>
        </template>
      </div>
    </SettingGroup>

    <!-- What is played most -->
    <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <SettingGroup
        v-for="list in topLists"
        :key="list.id"
        :title="list.title"
        :description="list.hint"
      >
        <UiSkeletonRows
          v-if="!loaded"
          :count="5"
          :cover="''"
          :lines="1"
          row-class="h-11 px-5"
        />
        <p v-else-if="!list.items.length" class="px-5 py-4 text-sm text-muted">
          {{ t('admin.noPlays') }}
        </p>
        <ol v-else class="flex flex-col pb-2">
          <li
            v-for="(item, i) in list.items"
            :key="`${item.artist}|${item.title || ''}`"
            class="flex items-center gap-3 px-5 py-2"
          >
            <span
              class="tabular w-5 shrink-0 text-right text-[13px] text-faint"
              >{{ i + 1 }}</span
            >
            <span class="flex min-w-0 flex-1 flex-col">
              <span class="truncate text-sm font-semibold">{{
                item.title || item.artist
              }}</span>
              <span v-if="item.title" class="truncate text-[12px] text-muted">{{
                item.artist
              }}</span>
            </span>
            <span class="tabular shrink-0 text-right text-[12px] text-muted">
              {{ t('admin.plays', { count: item.plays }) }}
              <span class="block text-faint">{{
                t('admin.listeners', { count: item.listeners })
              }}</span>
            </span>
          </li>
        </ol>
      </SettingGroup>
    </div>

    <!-- Who listens -->
    <SettingGroup
      :title="t('admin.usersTitle')"
      :description="t('admin.usersHint')"
    >
      <UiSkeletonRows
        v-if="!loaded"
        :count="3"
        cover="size-9"
        round
        row-class="h-14 px-5"
      />
      <p
        v-else-if="!listening?.users.length"
        class="px-5 py-4 text-sm text-muted"
      >
        {{ t('admin.noPlays') }}
      </p>
      <ul v-else class="flex flex-col pb-2">
        <li
          v-for="user in listening.users"
          :key="user.user_id"
          class="flex items-center gap-3 px-5 py-2.5"
        >
          <span
            class="flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-2 text-sm font-semibold"
            aria-hidden="true"
            >{{ avatarLetter(userName(user)) }}</span
          >
          <span class="flex min-w-0 flex-1 flex-col">
            <span class="truncate text-sm font-semibold">{{
              userName(user)
            }}</span>
            <span class="truncate text-[12px] text-muted">
              {{ t('admin.lastPlayed', { when: ago(user.last_played) }) }}
            </span>
          </span>
          <span class="tabular shrink-0 text-right text-[12px] text-muted">
            {{ t('admin.plays', { count: user.plays }) }} ·
            {{ hoursText(user.seconds) }}
            <span class="block text-faint">{{
              t('admin.skips', { rate: percent(user.skips / user.plays) })
            }}</span>
          </span>
        </li>
      </ul>
    </SettingGroup>

    <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <!-- Playing right now -->
      <SettingGroup
        :title="t('activity.nowTitle')"
        :description="t('admin.nowHint')"
      >
        <UiSkeletonRows
          v-if="!loaded"
          :count="2"
          cover="size-9"
          round
          row-class="h-14 px-5"
        />
        <p v-else-if="!playing.length" class="px-5 py-4 text-sm text-muted">
          {{ t('activity.nowEmpty') }}
        </p>
        <ul v-else class="flex flex-col pb-2">
          <li
            v-for="entry in playing"
            :key="`${entry.user_id}-${entry.client}`"
            class="flex items-center gap-3 px-5 py-2.5"
          >
            <span
              class="flex size-9 shrink-0 items-center justify-center rounded-full"
              :class="
                entry.paused
                  ? 'bg-surface-2 text-muted'
                  : 'bg-accent/15 text-accent'
              "
            >
              <AppIcon :name="entry.paused ? 'pause' : 'play'" :size="14" />
            </span>
            <span class="flex min-w-0 flex-1 flex-col">
              <span class="truncate text-sm font-semibold">{{
                [entry.track?.artist, entry.track?.title]
                  .filter(Boolean)
                  .join(' — ')
              }}</span>
              <span class="truncate text-[12px] text-muted"
                >{{ entry.username }} · {{ entry.client }}</span
              >
            </span>
          </li>
        </ul>
      </SettingGroup>

      <!-- The latest plays, everyone's -->
      <SettingGroup
        :title="t('admin.recentTitle')"
        :description="t('admin.recentHint')"
      >
        <UiSkeletonRows
          v-if="!loaded"
          :count="4"
          :cover="''"
          row-class="h-12 px-5"
        />
        <p
          v-else-if="!listening?.recent.length"
          class="px-5 py-4 text-sm text-muted"
        >
          {{ t('admin.noPlays') }}
        </p>
        <ul v-else class="flex flex-col pb-2">
          <li
            v-for="play in listening.recent.slice(0, 8)"
            :key="`${play.user_id}-${play.played_at}`"
            class="flex items-center gap-3 px-5 py-2"
          >
            <span class="flex min-w-0 flex-1 flex-col">
              <span class="truncate text-sm">
                <span class="font-semibold">{{ play.title }}</span>
                <span class="text-muted"> · {{ play.artist }}</span>
              </span>
              <span class="truncate text-[12px] text-faint">
                {{ userName(play) }} · {{ ago(play.played_at) }}
              </span>
            </span>
            <UiBadge v-if="play.skipped">{{ t('admin.skipped') }}</UiBadge>
            <UiBadge v-else-if="play.source === 'stream'" tone="accent">{{
              t('admin.streamed')
            }}</UiBadge>
          </li>
        </ul>
      </SettingGroup>
    </div>

    <!-- Where to go next -->
    <SettingGroup :title="t('admin.shortcutsTitle')">
      <div class="grid grid-cols-1 gap-2 p-3 sm:grid-cols-2 lg:grid-cols-3">
        <RouterLink
          v-for="link in shortcuts"
          :key="link.label"
          :to="link.to"
          class="flex items-center gap-3 rounded-control px-3 py-2.5 transition-colors hover:bg-surface-2"
        >
          <AppIcon :name="link.icon" :size="18" class="text-accent" />
          <span class="flex min-w-0 flex-col">
            <span class="truncate text-sm font-semibold">{{ link.label }}</span>
            <span class="truncate text-[12px] text-muted">{{ link.hint }}</span>
          </span>
        </RouterLink>
      </div>
    </SettingGroup>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppIcon from '../ui/AppIcon.vue'
import UiBadge from '../ui/UiBadge.vue'
import UiSegmented from '../ui/UiSegmented.vue'
import UiSkeleton from '../ui/UiSkeleton.vue'
import UiSkeletonRows from '../ui/UiSkeletonRows.vue'
import SettingGroup from './SettingGroup.vue'
import API from '/src/model/api'
import { useAuth } from '/src/model/auth'
import { useProgressTracker } from '/src/model/download'
import { avatarLetter } from '/src/lib/viewMode'
import { formatBytes, timeAgo } from '/src/lib/format'
import { useI18n } from '/src/i18n'

const { t, locale } = useI18n()
const auth = useAuth()
const tracker = useProgressTracker()

const days = ref(30)
const periodOptions = computed(() =>
  [7, 30, 90].map((value) => ({
    value,
    label: t('admin.days', { count: value }),
  }))
)

const listening = ref(null)
const library = ref(null)
const users = ref(null)
const playing = ref([])
const loaded = ref(false)
let serial = 0

async function load() {
  const mine = ++serial
  const [history, summary, accounts, now] = await Promise.allSettled([
    API.getAdminListening(days.value),
    API.getLibrarySummary(),
    auth.authDisabled.value ? Promise.resolve({ data: [] }) : API.listUsers(),
    API.getNowPlaying(),
  ])
  if (mine !== serial) return
  const value = (res, fallback) =>
    res.status === 'fulfilled' ? res.value.data : fallback
  listening.value = value(history, null)
  library.value = value(summary, null)
  users.value = value(accounts, [])
  playing.value = value(now, []) || []
  loaded.value = true
}

watch(days, () => {
  loaded.value = false
  load()
})

// Who is playing changes by the minute: asked again while the page is open.
let timer = 0
onMounted(() => {
  load()
  timer = setInterval(async () => {
    try {
      playing.value = (await API.getNowPlaying()).data || []
    } catch {
      // The next tick tries again.
    }
  }, 30_000)
})
onBeforeUnmount(() => clearInterval(timer))

const queue = computed(() => {
  tracker.queueVersion.value
  const items = tracker.downloadQueue.value
  return {
    pending: items.filter((item) => ['active', 'queued'].includes(item.state))
      .length,
    failed: items.filter((item) => item.state === 'failed').length,
  }
})

function hoursText(seconds) {
  const hours = (Number(seconds) || 0) / 3600
  if (hours < 1) {
    return t('admin.minutes', { count: Math.round((seconds || 0) / 60) })
  }
  return t('admin.hours', {
    count: hours.toLocaleString(locale.value, { maximumFractionDigits: 1 }),
  })
}

function percent(ratio) {
  return `${Math.round((Number(ratio) || 0) * 100)} %`
}

function ago(when) {
  return when ? timeAgo(when, locale.value) : t('monitor.never')
}

function userName(entry) {
  return entry.username || t('admin.unknownUser')
}

function dayLabel(day) {
  try {
    return new Date(`${day}T12:00:00`).toLocaleDateString(locale.value, {
      day: 'numeric',
      month: 'short',
    })
  } catch {
    return day
  }
}

const tiles = computed(() => {
  const totals = listening.value?.totals || {}
  const lib = library.value || {}
  const accounts = users.value || []
  return [
    {
      id: 'plays',
      icon: 'play',
      tone: 'text-accent',
      label: t('admin.tilePlays'),
      value: (totals.plays || 0).toLocaleString(locale.value),
      hint: hoursText(totals.seconds || 0),
      to: { name: 'Admin', params: { section: 'activity' } },
    },
    {
      id: 'listeners',
      icon: 'users',
      tone: 'text-accent',
      label: t('admin.tileListeners'),
      value: String(totals.listeners || 0),
      hint: accounts.length
        ? t('admin.accounts', { count: accounts.length })
        : '',
      to: auth.authDisabled.value
        ? null
        : { name: 'Admin', params: { section: 'users' } },
    },
    {
      id: 'library',
      icon: 'library',
      tone: 'text-accent',
      label: t('admin.tileLibrary'),
      value: (lib.track_count || 0).toLocaleString(locale.value),
      hint: [
        t('admin.artists', { count: lib.artist_count || 0 }),
        formatBytes(lib.size || 0),
      ].join(' · '),
      to: { name: 'Storage' },
    },
    {
      id: 'queue',
      icon: queue.value.failed ? 'alert' : 'download',
      tone: queue.value.failed ? 'text-danger' : 'text-accent',
      label: t('admin.tileQueue'),
      value: String(queue.value.pending),
      hint: queue.value.failed
        ? t('admin.failed', { count: queue.value.failed })
        : t('admin.noFailures'),
      to: {
        name: 'Queue',
        params: queue.value.failed ? { tab: 'failed' } : {},
      },
    },
  ]
})

const topLists = computed(() => [
  {
    id: 'artists',
    title: t('admin.topArtists'),
    hint: t('admin.topHint'),
    items: listening.value?.top_artists || [],
  },
  {
    id: 'songs',
    title: t('admin.topSongs'),
    hint: t('admin.topHint'),
    items: listening.value?.top_songs || [],
  },
])

// The chart: bars to scale with the busiest day, a sliver for a day
// with no plays so the days stay countable.
const hover = ref(-1)
const peak = computed(() =>
  Math.max(1, ...(listening.value?.per_day || []).map((day) => day.plays))
)
function barHeight(plays) {
  return plays ? `${Math.max(4, (plays / peak.value) * 100)}%` : '2px'
}
const tipLeft = computed(() => {
  const count = listening.value?.per_day.length || 1
  const pct = ((hover.value + 0.5) / count) * 100
  return `clamp(4.5rem, ${pct}%, calc(100% - 4.5rem))`
})
// The chart in words, for a screen reader.
const chartLabel = computed(() => {
  const list = listening.value?.per_day || []
  const busiest = list.reduce(
    (best, day) => (day.plays > best.plays ? day : best),
    list[0] || { plays: 0, day: '' }
  )
  return t('admin.chartAria', {
    plays: listening.value?.totals.plays || 0,
    days: days.value,
    day: busiest.day ? dayLabel(busiest.day) : '',
    peak: busiest.plays,
  })
})

const shortcuts = computed(() =>
  [
    !auth.authDisabled.value && {
      icon: 'users',
      label: t('settings.users'),
      hint: t('admin.goUsers'),
      to: { name: 'Admin', params: { section: 'users' } },
    },
    {
      icon: 'activity',
      label: t('settings.activity'),
      hint: t('admin.goActivity'),
      to: { name: 'Admin', params: { section: 'activity' } },
    },
    {
      icon: 'hard-drive',
      label: t('admin.goStorageTitle'),
      hint: t('admin.goStorage'),
      to: { name: 'Storage' },
    },
    {
      icon: 'stethoscope',
      label: t('settings.doctor'),
      hint: t('admin.goDoctor'),
      to: { name: 'Admin', params: { section: 'doctor' } },
    },
    {
      icon: 'download',
      label: t('settings.sources'),
      hint: t('admin.goSources'),
      to: { name: 'Admin', params: { section: 'sources' } },
    },
    {
      icon: 'server',
      label: t('settings.server'),
      hint: t('admin.goServer'),
      to: { name: 'Admin', params: { section: 'server' } },
    },
  ].filter(Boolean)
)
</script>
