<template>
  <Transition name="dock">
    <aside
      v-if="active"
      class="fixed top-20 right-4 bottom-28 z-[60] flex w-72 max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-panel border border-line-2 bg-surface shadow-float"
      :aria-label="t('playlists.dropTitle')"
    >
      <div class="border-b border-line px-4 py-3">
        <p class="text-sm font-bold">{{ t('playlists.dropTitle') }}</p>
        <p class="text-[12px] text-muted">{{ t('playlists.dropHint') }}</p>
      </div>
      <div class="flex-1 overflow-y-auto p-2">
        <template v-for="group in groups" :key="group.key">
          <div v-if="group.title" class="px-2 pt-3 pb-1">
            <p class="eyebrow">{{ group.title }}</p>
            <p class="text-[11px] text-faint">{{ group.hint }}</p>
          </div>
          <ul>
            <li v-for="playlist in group.items" :key="playlist.key">
              <div
                class="flex h-12 items-center gap-2.5 rounded-control px-2 transition-colors"
                :class="
                  target === playlist.key
                    ? 'bg-accent/15 ring-2 ring-accent ring-inset'
                    : ''
                "
                @dragenter.prevent="target = playlist.key"
                @dragover="onDragOver($event, playlist.key)"
                @dragleave="onDragLeave(playlist.key)"
                @drop="onDrop($event, playlist)"
              >
                <CoverArt
                  :thumb="150"
                  :src="playlist.cover"
                  :covers="playlist.covers"
                  :name="playlist.title"
                  rounded="rounded-[7px]"
                  :letter-size="13"
                  :icon-size="14"
                  icon="playlist"
                  class="pointer-events-none size-8"
                />
                <span class="pointer-events-none flex min-w-0 flex-1 flex-col">
                  <span class="truncate text-[13px] font-medium text-fg">{{
                    playlist.title
                  }}</span>
                  <span class="tabular text-[11px] text-faint">{{
                    t('common.tracks', { count: itemTrackCount(playlist) })
                  }}</span>
                </span>
                <AppIcon
                  v-if="!playlist.canEditTracks"
                  name="link"
                  :size="14"
                  class="pointer-events-none shrink-0 text-faint"
                />
              </div>
            </li>
          </ul>
        </template>
      </div>
      <div class="border-t border-line p-2">
        <div
          class="flex h-12 items-center gap-2.5 rounded-control border border-dashed border-line-3 px-3 text-[13px] font-semibold text-muted transition-colors"
          :class="target === NEW ? 'border-accent bg-accent/15 text-fg' : ''"
          @dragenter.prevent="target = NEW"
          @dragover="onDragOver($event, NEW)"
          @dragleave="onDragLeave(NEW)"
          @drop="onDrop($event, null)"
        >
          <AppIcon name="plus" :size="16" class="pointer-events-none" />
          <span class="pointer-events-none">{{ t('playlists.new') }}</span>
        </div>
      </div>
    </aside>
  </Transition>
</template>

<script setup>
// While songs are dragged anywhere in the app, every playlist of the
// user's (and those shared with them as an editor) is listed here as a
// drop target - the sidebar only shows a
// few, and only on a wide screen. Dropping on "New playlist" opens the
// create dialog with those songs.
import { computed, onMounted, onUnmounted, ref } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import CoverArt from '../ui/CoverArt.vue'
import { isSongDrag, readDragSongs } from '/src/lib/dragSongs'
import { itemTrackCount } from '/src/lib/library'
import { usePlaylistActions } from '/src/model/playlistActions'
import { useLibrary } from '/src/model/library'
import { useI18n } from '/src/i18n'

const NEW = '\u0000new'

const { t } = useI18n()
const playlistActions = usePlaylistActions()
const library = useLibrary()
const active = ref(false)
const target = ref('')

// The newest first. Library playlists take the songs at once; the
// user's imported ones (they follow a Spotify playlist or a watch) are
// listed apart, and a drop on one offers to detach it from its source
// first - the only way it can take songs of its own.
const newest = (a, b) => b.added - a.added
const groups = computed(() => {
  const editable = [...playlistActions.manuals()]
    .filter((playlist) => !playlist.liked)
    .sort(newest)
  const imported = library.ownPlaylists.value
    .filter(
      (playlist) =>
        !playlist.canEditTracks && !playlist.liked && !playlist.manual
    )
    .sort(newest)
  return [
    { key: 'editable', items: editable },
    ...(imported.length
      ? [
          {
            key: 'imported',
            title: t('playlists.dropImportedTitle'),
            hint: t('playlists.dropImportedHint'),
            items: imported,
          },
        ]
      : []),
  ]
})

function onDragOver(event, key) {
  if (!isSongDrag(event)) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'copy'
  target.value = key
}

function onDragLeave(key) {
  if (target.value === key) target.value = ''
}

async function onDrop(event, playlist) {
  const dropped = readDragSongs(event)
  close()
  if (!dropped) return
  event.preventDefault()
  if (!playlist) playlistActions.createFromDropped(dropped)
  else if (playlist.canEditTracks) {
    await playlistActions.addDropped(playlist, dropped)
  } else await playlistActions.detachThenAdd(playlist, dropped)
}

function close() {
  active.value = false
  target.value = ''
}

// Shown a tick after the drag starts: changing the page during
// `dragstart` itself can cancel the drag in some browsers.
let timer = 0
function onDragStart(event) {
  if (!isSongDrag(event)) return
  clearTimeout(timer)
  timer = setTimeout(() => (active.value = true), 0)
}

function onDragEnd() {
  clearTimeout(timer)
  close()
}

onMounted(() => {
  document.addEventListener('dragstart', onDragStart)
  document.addEventListener('dragend', onDragEnd)
  document.addEventListener('drop', onDragEnd)
})
onUnmounted(() => {
  clearTimeout(timer)
  document.removeEventListener('dragstart', onDragStart)
  document.removeEventListener('dragend', onDragEnd)
  document.removeEventListener('drop', onDragEnd)
})
</script>

<style scoped>
.dock-enter-active,
.dock-leave-active {
  transition:
    opacity 150ms ease,
    transform 150ms ease;
}
.dock-enter-from,
.dock-leave-to {
  opacity: 0;
  transform: translateX(12px);
}
</style>
