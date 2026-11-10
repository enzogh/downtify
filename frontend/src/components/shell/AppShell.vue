<template>
  <SignIn v-if="auth.mustSignIn.value" />
  <div v-else class="flex min-h-dvh bg-bg text-fg">
    <SideNav class="hidden md:flex" />
    <div class="flex min-w-0 flex-1 flex-col">
      <TopBar />
      <main class="flex-1 pb-8">
        <RouterView v-slot="{ Component, route: viewRoute }">
          <Transition name="page" mode="out-in">
            <component
              v-if="policyLoaded"
              :is="Component"
              :key="viewKey(viewRoute) + ':' + libraryOnly"
            />
          </Transition>
        </RouterView>
      </main>
      <!-- Sticky at the end of the content column, so it floats over the
           page yet lines up with the content next to the sidebar. -->
      <div
        class="sticky bottom-[calc(5.25rem+env(safe-area-inset-bottom))] z-40 mx-2 mb-2 flex flex-col gap-2 md:bottom-5 md:mx-6 md:mb-5"
      >
        <OfflineBanner />
        <JamStrip />
        <RemotePlaybackBar />
        <MiniPlayer />
      </div>
      <div class="h-[calc(4.75rem+env(safe-area-inset-bottom))] md:hidden" />
    </div>
    <BottomNav class="md:hidden" />
    <NowPlaying />
    <DevicePicker v-if="auth.user.value" />
    <JamSheet v-if="auth.user.value" />
    <ShortcutsDialog v-model:open="shortcutsOpen" />
    <UiToasts />
    <UiDialog />
    <CreatePlaylistModal />
    <RenamePlaylistModal />
    <PlaylistShareModal />
    <AddTracksToPlaylistModal />
    <PlaylistDropDock />
    <DefaultPasswordPrompt />
    <InstallPrompt />
    <ReplaceAudioDialog v-if="auth.isAdmin.value" />
    <BuyLinksDialog />
    <ShareCardDialog />
    <TrackOriginDialog />
  </div>
</template>

<script setup>
import { startListeningLog } from '/src/model/listening'
import { startAutoplay } from '/src/model/autoplay'
import { startJamSync } from '/src/model/jam'
import { ref, watch, onMounted, onUnmounted } from 'vue'
import {
  libraryOnly,
  policyLoaded,
  startMusicPolicy,
} from '/src/model/musicPolicy'
import { useRoute, useRouter } from 'vue-router'
import SideNav from './SideNav.vue'
import TopBar from './TopBar.vue'
import BottomNav from './BottomNav.vue'
import MiniPlayer from './MiniPlayer.vue'
import InstallPrompt from './InstallPrompt.vue'
import RemotePlaybackBar from './RemotePlaybackBar.vue'
import OfflineBanner from './OfflineBanner.vue'
import DevicePicker from '../player/DevicePicker.vue'
import JamSheet from '../jam/JamSheet.vue'
import JamStrip from '../jam/JamStrip.vue'
import NowPlaying from './NowPlaying.vue'
import ShortcutsDialog from './ShortcutsDialog.vue'
import UiToasts from '../ui/UiToasts.vue'
import UiDialog from '../ui/UiDialog.vue'
import CreatePlaylistModal from '../library/CreatePlaylistModal.vue'
import PlaylistShareModal from '../library/PlaylistShareModal.vue'
import RenamePlaylistModal from '../library/RenamePlaylistModal.vue'
import AddTracksToPlaylistModal from '../library/AddTracksToPlaylistModal.vue'
import PlaylistDropDock from './PlaylistDropDock.vue'
import SignIn from './SignIn.vue'
import DefaultPasswordPrompt from './DefaultPasswordPrompt.vue'
import ReplaceAudioDialog from '../library/ReplaceAudioDialog.vue'
import BuyLinksDialog from '../library/BuyLinksDialog.vue'
import ShareCardDialog from '../library/ShareCardDialog.vue'
import TrackOriginDialog from '../monitor/TrackOriginDialog.vue'
import API from '/src/model/api'
import { useAccount } from '/src/model/account'
import { useAuth } from '/src/model/auth'
import { useI18n } from '/src/i18n'
import { usePlayer } from '/src/model/player'
import { usePlayerPrefs } from '/src/model/playerPrefs'
import { useLibrary } from '/src/model/library'
import { useDiscover } from '/src/model/discover'
import { useNowPlaying, useUi } from '/src/model/ui'
import { useRemotePlayback } from '/src/model/remotePlayback'
import { useShortcuts } from './shortcuts'

const auth = useAuth()
const account = useAccount()
const { t } = useI18n()
const player = usePlayer()
const { showLyrics } = usePlayerPrefs()
const route = useRoute()
startListeningLog()
startAutoplay()
startJamSync()
const router = useRouter()
const ui = useUi()
const nowPlaying = useNowPlaying()
const shortcutsOpen = ref(false)
let stopPolicy
onMounted(() => {
  stopPolicy = startMusicPolicy()
})
onUnmounted(() => stopPolicy?.())

// The Now playing overlay lives in the query string (?np=1); it must not
// remount the page underneath it.
function viewKey(viewRoute) {
  return viewRoute.meta.viewKey || viewRoute.path
}

useLibrary().load()
// The account's own preferences (theme, language...) and telling the
// server what plays here, once someone is signed in.
watch(
  () => auth.user.value?.id,
  (id) => {
    if (!id) return
    account.start()
    account.startPlaybackReports()
    useRemotePlayback().start()
  },
  { immediate: true }
)
API.onForbidden(() => {
  ui.toast(t('account.needsAdmin'), { kind: 'error' })
})
// Count listens for Discover, whichever page the music is playing on.
useDiscover().startListenTracking()

useShortcuts({
  player,
  nowPlaying,
  // "L" opens the lyrics panel, which isn't there when they're hidden.
  lyricsEnabled: () => showLyrics.value,
  focusSearch: ui.focusSearch,
  openHelp: () => (shortcutsOpen.value = true),
  goTo: (name) => router.push({ name }),
  // A modal on top swallows every shortcut; Escape closes it.
  closeModal: () => {
    if (ui.closeTopModal()) return true
    if (ui.dialog.value) {
      ui.closeDialog(false)
      return true
    }
    if (shortcutsOpen.value) {
      shortcutsOpen.value = false
      return true
    }
    return false
  },
  hasModal: () =>
    Boolean(ui.dialog.value) ||
    shortcutsOpen.value ||
    ui.modals.value.length > 0,
})
</script>
