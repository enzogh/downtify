// The signed-in account's other devices, Spotify Connect style: what
// they play, moving playback (and its queue) from one to another, and
// pausing or resuming them from here. Fed by `GET /api/activity/devices`
// and the `now_playing` / `player_command` WebSocket frames.
import { computed, ref, watch } from 'vue'
import API from '/src/model/api'
import { useLibrary } from '/src/model/library'
import { usePlayer } from '/src/model/player'
import { normalizeTrack } from '/src/lib/library'
import {
  isPlayingOn,
  otherDevices,
  pickRemote,
  queueToSend,
  remoteKey,
  remotePosition,
} from '/src/lib/remotePlayback'

// Players are dropped by the server after 90 s of silence without a
// frame: ask again now and then so a closed tab's bar goes away.
const REFRESH_MS = 45000
// How long "Listen here" waits for the other device to send its whole
// queue before picking up just its song (an app that can't send it).
const TRANSFER_WAIT_MS = 1800
// How long "Play on" waits for the other device to start before saying
// it needs a tap there (iPhones won't start a song nobody tapped for).
const START_WAIT_MS = 5000
// How long this page keeps playing for a device that needs that tap,
// pausing as soon as it starts.
const HANDOFF_WAIT_MS = 120000
// A refused start this soon after playback was sent here is that send's.
const SENT_HERE_WINDOW_MS = 15000

const players = ref([])
const receivedAt = ref(0)
const hidden = ref('')
const pickerOpen = ref(false)
// Set when this page just moved playback here (a toast says so).
const movedHere = ref(0)
// Set when playback sent here couldn't start without a tap on this
// device (a toast offers the button that starts it).
const needsTap = ref(0)
// The device this page hands its playback to once it starts.
let handoff = null
let started = false
let awaitingTransfer = null

function apply(rows) {
  players.value = Array.isArray(rows) ? rows : []
  receivedAt.value = Date.now()
  if (handoff && isPlayingOn(players.value, handoff.player)) {
    handoff.started()
    handoff = null
  }
}

async function refresh() {
  try {
    const res = await API.getMyPlayers()
    apply(res.data)
  } catch {
    // Signed out or an older server: no devices.
  }
}

const remote = computed(() => {
  const row = pickRemote(players.value, API.clientId)
  if (!row || remoteKey(row) === hidden.value) return null
  return row
})

/** Every other device, playing ones first, then paused, then idle. */
const devices = computed(() => otherDevices(players.value, API.clientId))

function trackFor(file) {
  return useLibrary().tracksByFile.value.get(file) || normalizeTrack(file)
}

/** Play `files` here from `index` at `position` seconds. */
function loadHere({ files, index = 0, position = 0, playing = true }) {
  const list = (Array.isArray(files) ? files : []).filter(Boolean)
  if (!list.length) return false
  const player = usePlayer()
  const at = Math.min(Math.max(Number(index) || 0, 0), list.length - 1)
  player.adoptQueue(list.map(trackFor), at)
  player.cueAt(at, Number(position) || 0, playing !== false)
  movedHere.value = Date.now()
  if (awaitingTransfer) {
    awaitingTransfer()
    awaitingTransfer = null
  }
  return true
}

function command(row, action, extra = {}) {
  return API.commandPlayer(row.player, action, extra)
    .then(() => true)
    .catch(() => false)
}

/** What plays here, as a `load` command's fields (null: nothing). */
function localQueue() {
  const player = usePlayer()
  return queueToSend(
    player.playlist.value,
    player.currentIndex.value,
    player.currentTime.value,
    player.isPlaying.value
  )
}

function onCommand(data) {
  const player = usePlayer()
  if (data.action === 'pause') player.pause()
  if (data.action === 'play' && player.currentTrack.value) player.play()
  if (data.action === 'load') loadHere(data)
  if (data.action === 'transfer' && data.to) {
    const queue = localQueue()
    if (!queue) return
    API.commandPlayer(data.to, 'load', queue)
      .then(() => player.pause())
      .catch(() => {})
  }
}

function start() {
  if (started) return
  started = true
  // iPhones refuse to start a song another device sent without a tap
  // here: offer the tap rather than stay silent.
  watch(usePlayer().playBlocked, (at) => {
    const sent = movedHere.value
    if (sent && at >= sent && at - sent < SENT_HERE_WINDOW_MS) {
      needsTap.value = at
    }
  })
  API.onMessage((data) => {
    if (data?.type === 'now_playing') apply(data.players)
    if (data?.type === 'player_command' && data.player === API.clientId)
      onCommand(data)
  })
  refresh()
  setInterval(() => {
    if (document.visibilityState === 'visible') refresh()
  }, REFRESH_MS)
}

function pickUpSong(row) {
  const file = row?.track?.file
  if (!file) return false
  const elapsed = (Date.now() - receivedAt.value) / 1000
  const ok = loadHere({
    files: [file],
    position: remotePosition(row, elapsed),
  })
  if (ok && !row.paused) command(row, 'pause')
  return ok
}

/**
 * Carry on here with what `row` plays: it sends its whole queue and
 * place (a `transfer`), then pauses. A device that can't (the phone
 * app) is picked up from its song alone. `false` when nothing could
 * play here.
 */
async function listenHere(row = remote.value) {
  if (!row?.track) return false
  hidden.value = remoteKey(row)
  const arrived = new Promise((resolve) => {
    awaitingTransfer = () => resolve(true)
    setTimeout(() => resolve(false), TRANSFER_WAIT_MS)
  })
  const asked = row.app
    ? false
    : await command(row, 'transfer', {
        to: API.clientId,
      })
  if (asked && (await arrived)) return true
  awaitingTransfer = null
  return pickUpSong(row)
}

/**
 * Move what plays here to `row` (its queue and place). This page pauses
 * once that device plays, not before, so the music never stops for a
 * device that can't start on its own (an iPhone wants a tap there).
 * `'moved'` when it plays there, `'waiting'` when it needs that tap
 * (this page keeps playing until it starts), `false` when nothing plays
 * here or the device is gone.
 */
async function sendTo(row) {
  const queue = localQueue()
  if (!queue || !row) return false
  const player = usePlayer()
  const wasPlaying = player.isPlaying.value
  const startedThere = new Promise((resolve) => {
    let done = false
    const finish = (value) => {
      if (done) return
      done = true
      resolve(value)
    }
    handoff = {
      player: row.player,
      started: () => {
        if (wasPlaying) player.pause()
        finish(true)
      },
    }
    setTimeout(() => finish(false), START_WAIT_MS)
  })
  if (!(await command(row, 'load', queue))) {
    handoff = null
    return false
  }
  if (!wasPlaying) {
    handoff = null
    return 'moved'
  }
  if (await startedThere) return 'moved'
  // Still waiting for a tap over there: give up after a while.
  const pending = handoff
  setTimeout(() => {
    if (handoff === pending) handoff = null
  }, HANDOFF_WAIT_MS)
  return 'waiting'
}

/** Pause or resume `row` on its own device. */
function toggleRemote(row = remote.value) {
  if (!row) return Promise.resolve(false)
  return command(row, row.paused ? 'play' : 'pause')
}

/** Hide the bar until that player plays another song. */
function hide(row = remote.value) {
  hidden.value = remoteKey(row)
}

function openPicker() {
  pickerOpen.value = true
  refresh()
}

export function useRemotePlayback() {
  return {
    players,
    devices,
    remote,
    pickerOpen,
    movedHere,
    needsTap,
    start,
    refresh,
    listenHere,
    sendTo,
    toggleRemote,
    hide,
    openPicker,
    localQueue,
  }
}
