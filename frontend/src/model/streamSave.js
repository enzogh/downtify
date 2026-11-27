// "Save to server" for the song the player streams live: one state for
// the mini player, Now playing and the details panel, so they always
// agree on whether the song is on the server, being saved, or not yet.
import { computed, effectScope, ref, watch } from 'vue'

import API from '/src/model/api'
import { useDownloadManager, useProgressTracker } from '/src/model/download'
import { useLibrary } from '/src/model/library'
import { usePlayer } from '/src/model/player'
import { useUi } from '/src/model/ui'
import { useI18n } from '/src/i18n'
import {
  autoSaveRemaining,
  streamJobCandidates,
  streamSaveSong,
  streamSaveState,
} from '/src/lib/streamSave'

// The play is counted once its audio starts flowing; ask a little later
// so the answer includes it.
const PLAYS_DELAY_MS = 4000

let shared = null

function createStreamSave() {
  const player = usePlayer()
  const library = useLibrary()
  const tracker = useProgressTracker()
  const dm = useDownloadManager()
  const ui = useUi()
  const { t } = useI18n()

  const track = computed(() => player.currentTrack.value)
  const isStream = computed(() => !!track.value?.stream)
  const song = computed(() => streamSaveSong(track.value))

  const job = computed(() => {
    tracker.queueVersion.value
    for (const candidate of streamJobCandidates(track.value)) {
      const item = tracker.getBySong(candidate)
      if (item) return item
    }
    return null
  })

  const onServer = computed(
    () =>
      isStream.value &&
      library.hasSong(track.value.artist || '', track.value.title || '')
  )

  const state = computed(() =>
    isStream.value ? streamSaveState(job.value, onServer.value) : 'saved'
  )
  const busy = computed(
    () => state.value === 'queued' || state.value === 'active'
  )
  const progress = computed(() =>
    state.value === 'active' ? Math.round(job.value?.progress || 0) : 0
  )

  // GET /api/stream/live/plays for the playing video.
  const plays = ref(null)
  const autoRemaining = computed(() =>
    state.value === 'new' ? autoSaveRemaining(plays.value) : null
  )

  function save() {
    const pending = song.value
    if (!pending || busy.value || state.value === 'saved') return
    if (state.value === 'failed') {
      dm.retry(job.value?.song || pending)
      return
    }
    dm.queue(pending)
    ui.toast(t('stream.queuedToast', { name: pending.name }), {
      kind: 'success',
    })
  }

  const scope = effectScope(true)
  scope.run(() => {
    let timer = 0
    watch(
      () => (isStream.value ? track.value.video_id || '' : ''),
      (videoId) => {
        clearTimeout(timer)
        plays.value = null
        if (!videoId) return
        timer = setTimeout(async () => {
          try {
            const res = await API.getLiveStreamPlays(videoId)
            if (track.value?.video_id === videoId) plays.value = res.data
          } catch {
            // Off, library-only or an old server: no hint, nothing else.
          }
        }, PLAYS_DELAY_MS)
      },
      { immediate: true }
    )

    // The playing stream just landed on the server (from here, a row,
    // or on its own after enough plays): say what that changes.
    watch(
      () => [track.value?.video_id || '', state.value],
      ([videoId, now], [before, was]) => {
        if (!videoId || videoId !== before || now !== 'saved') return
        if (was !== 'queued' && was !== 'active') return
        ui.toast(t('stream.savedToast', { name: track.value.title }), {
          kind: 'success',
        })
      }
    )
  })

  return {
    isStream,
    song,
    job,
    state,
    busy,
    progress,
    autoRemaining,
    save,
  }
}

/** The shared "save the playing stream to the server" state. */
export function useStreamSave() {
  if (!shared) shared = createStreamSave()
  return shared
}

/** Tests only: forget the shared state. */
export function resetStreamSave() {
  shared = null
}
