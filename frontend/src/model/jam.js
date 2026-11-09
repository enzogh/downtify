// Jam: listening together. One account starts a Jam, others join with
// its code, and everybody's player follows the same shared queue and
// clock kept by the server (see downtify/jam.py). While in a Jam, the
// player's own controls (play, skip, seek, "Play next", "Add to queue")
// are sent to the Jam instead, and come back to every device at once.
import { computed, ref, shallowRef, watch } from 'vue'

import API from '/src/model/api'
import { useAuth } from '/src/model/auth'
import { usePlayer } from '/src/model/player'
import { useUi } from '/src/model/ui'
import { t } from '/src/i18n'
import {
  canControl,
  clockOffset,
  expectedPosition,
  jamTrackPayload,
  jamTracks,
  jammable,
  needsResync,
  shuffled,
} from '/src/lib/jam'

const LISTEN_KEY = 'downtify-jam-listen'
// How often a device checks it is still in step, and how often it asks
// the server again (in case a WebSocket frame was missed).
const DRIFT_CHECK_MS = 5000
const REFRESH_MS = 20000
// "Play" on an album sends the songs from the one picked on.
const MAX_SENT = 200

const jam = shallowRef(null)
const busy = ref(false)
const listenHere = ref(readListen())
let offset = 0
let started = false
let driftTimer = null
let refreshTimer = null

function readListen() {
  try {
    return localStorage.getItem(LISTEN_KEY) !== 'false'
  } catch {
    return true
  }
}

function myId() {
  return Number(useAuth().user.value?.id) || 0
}

// ── Following the shared state ───────────────────────────────────────
function apply(snapshot) {
  if (!snapshot) {
    end()
    return
  }
  const known = jam.value
  // A late answer must not undo a newer frame.
  if (known && known.id === snapshot.id && snapshot.version < known.version)
    return
  const joined = !known || known.id !== snapshot.id
  jam.value = snapshot
  offset = clockOffset(snapshot)
  const player = usePlayer()
  player.setTransportHook(handle)
  player.setOutputMuted(!listenHere.value)
  if (joined) startTimers()
  follow()
}

function follow() {
  const snapshot = jam.value
  if (!snapshot) return
  const player = usePlayer()
  const tracks = jamTracks(snapshot)
  const index = snapshot.index < tracks.length ? snapshot.index : -1
  player.withoutHook(() => {
    const changed = player.adoptQueue(tracks, index)
    if (index < 0) {
      player.pause()
      return
    }
    const expected = expectedPosition(snapshot, offset)
    if (changed) {
      player.cueAt(index, expected, snapshot.playing)
      return
    }
    if (
      player.duration.value > 0 &&
      needsResync(player.currentTime.value, expected)
    ) {
      player.seek(expected)
    }
    if (snapshot.playing && !player.isPlaying.value) player.play()
    else if (!snapshot.playing && player.isPlaying.value) player.pause()
  })
}

function end() {
  const was = jam.value
  jam.value = null
  stopTimers()
  if (!was) return
  const player = usePlayer()
  player.setTransportHook(null)
  player.setOutputMuted(false)
  player.pause()
}

function startTimers() {
  stopTimers()
  driftTimer = setInterval(() => {
    if (jam.value?.playing) follow()
  }, DRIFT_CHECK_MS)
  refreshTimer = setInterval(refresh, REFRESH_MS)
}

function stopTimers() {
  clearInterval(driftTimer)
  clearInterval(refreshTimer)
  driftTimer = null
  refreshTimer = null
}

async function refresh() {
  if (!myId()) return
  try {
    const res = await API.getJam()
    apply(res.data?.jam || null)
  } catch {
    // Offline for a moment: the next refresh or frame catches up.
  }
}

// ── Sending what the listener asks for ───────────────────────────────
async function send(request) {
  try {
    const res = await request
    if (res?.data && 'jam' in res.data) apply(res.data.jam)
    return true
  } catch (err) {
    const status = err?.response?.status
    const ui = useUi()
    if (status === 403) ui.toast(t('jam.hostOnly'), { kind: 'error' })
    else if (status === 404) {
      ui.toast(t('jam.gone'), { kind: 'error' })
      refresh()
    } else ui.toast(t('jam.failed'), { kind: 'error' })
    return false
  }
}

function insertPosition(position) {
  const player = usePlayer()
  if (position >= player.playlist.value.length) return 'end'
  if (position === player.currentIndex.value + 1) return 'next'
  return position
}

function add(tracks, options) {
  const songs = jammable(tracks).slice(0, MAX_SENT).map(jamTrackPayload)
  if (!songs.length) {
    useUi().toast(t('jam.libraryOnly'), { kind: 'error' })
    return
  }
  // The track actions already say "Added to queue".
  void send(API.addToJam(songs, options))
}

function rowAt(index) {
  return usePlayer().playlist.value[index]?.jamId || ''
}

/** The player's transport hook while in a Jam. */
function handle(action, payload) {
  const snapshot = jam.value
  if (!snapshot) return false
  switch (action) {
    case 'play':
    case 'pause':
    case 'next':
    case 'prev':
      void send(API.controlJam(action))
      break
    case 'seek':
      void send(API.controlJam('seek', { position: payload.position }))
      break
    case 'jump':
      void send(API.controlJam('jump', { index: payload.index }))
      break
    case 'ended':
      void send(API.controlJam('ended', { from_index: snapshot.index }))
      break
    case 'insert':
      add(payload.tracks, { position: insertPosition(payload.position) })
      break
    case 'replace': {
      const from = (payload.tracks || []).slice(payload.startIndex || 0)
      add(payload.shuffled ? shuffled(from) : from, {
        position: 'next',
        play: true,
      })
      break
    }
    case 'remove': {
      const id = rowAt(payload.index)
      if (id) void send(API.removeFromJam(id))
      break
    }
    case 'move': {
      const id = rowAt(payload.from)
      if (id) void send(API.moveInJam(id, payload.to))
      break
    }
    case 'clear':
      void send(API.clearJam())
      break
    default:
      // Shuffle and repeat are each device's own, so not in a Jam.
      useUi().toast(t('jam.notInJam'))
  }
  return true
}

// ── Starting, joining, leaving ───────────────────────────────────────
async function run(request) {
  busy.value = true
  try {
    return await send(request)
  } finally {
    busy.value = false
  }
}

function start() {
  return run(API.startJam())
}

/** Start a Jam with what is playing now (and what comes next). */
async function startWithQueue() {
  const player = usePlayer()
  const index = Math.max(0, player.currentIndex.value)
  const tracks = jammable(player.playlist.value.slice(index)).slice(0, MAX_SENT)
  const position = player.currentTime.value
  const wasPlaying = player.isPlaying.value
  if (!(await start())) return false
  if (!tracks.length) return true
  const ok = await run(API.addToJam(tracks.map(jamTrackPayload)))
  if (ok && position > 1) {
    await run(API.controlJam('seek', { position }))
  }
  if (ok && wasPlaying) await run(API.controlJam('play'))
  return ok
}

function join(code) {
  return run(API.joinJam(code))
}

async function leave() {
  busy.value = true
  try {
    await API.leaveJam()
  } catch {
    // Left anyway as far as this device is concerned.
  } finally {
    busy.value = false
  }
  end()
}

function setGuestsCanControl(on) {
  return run(API.configureJam({ guests_can_control: !!on }))
}

function removeItem(itemId) {
  return run(API.removeFromJam(itemId))
}

function jumpTo(index) {
  return run(API.controlJam('jump', { index }))
}

function setListenHere(on) {
  listenHere.value = !!on
  try {
    localStorage.setItem(LISTEN_KEY, String(listenHere.value))
  } catch {
    // ignore
  }
  if (jam.value) {
    usePlayer().setOutputMuted(!listenHere.value)
    follow()
  }
}

/** Follow Jam frames and the signed-in user (once, from the shell). */
export function startJamSync() {
  if (started || typeof window === 'undefined') return
  started = true
  API.onMessage((data) => {
    if (data?.type === 'jam') apply(data.jam || null)
  })
  const { user } = useAuth()
  watch(
    () => user.value?.id || 0,
    (id) => {
      if (id) refresh()
      else end()
    },
    { immediate: true }
  )
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && jam.value) refresh()
  })
}

export function useJam() {
  const active = computed(() => !!jam.value)
  const isHost = computed(() => !!jam.value && jam.value.host_id === myId())
  const mayControl = computed(() => canControl(jam.value, myId()))
  return {
    jam,
    active,
    busy,
    isHost,
    mayControl,
    listenHere,
    myId,
    start,
    startWithQueue,
    join,
    leave,
    refresh,
    setGuestsCanControl,
    setListenHere,
    removeItem,
    jumpTo,
  }
}
