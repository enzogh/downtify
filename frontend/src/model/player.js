// The built-in player: one <audio> element shared by the mini player and
// the Now playing view, with its queue, shuffle/repeat, sleep timer and
// OS media controls (Media Session). A second, silent element loads the
// next song ahead of time and takes over at the end of this one, so an
// album plays without a gap between tracks (see "Gapless playback").
import { ref, computed, watch } from 'vue'
import { libraryOnly } from '/src/model/musicPolicy'

import { normalizeTrack } from '/src/lib/library'
import { clampFade, fadeGain } from '/src/lib/fade'
import { attachEqualizer, resumeEqualizer } from '/src/model/equalizer'
import { resolveTrackUrl, warmServerCache } from '/src/model/streamResolve'
import {
  normalizationEnabled,
  knownTrackNormalization,
  getTrackNormalization,
  prefetchTrackNormalization,
  applyTrackNormalization,
} from '/src/model/normalization'
import { mediaSessionHandlers, positionState } from '/src/lib/mediaSession'

const VOLUME_KEY = 'downtify-player-volume'
const RATE_KEY = 'downtify-player-rate'
const SESSION_KEY = 'downtify-player-session'
const FADE_KEY = 'downtify-player-fade'
const GAPLESS_KEY = 'downtify-player-gapless'
// How long before a track ends its successor is prepared at the latest.
const PREPARE_BEFORE_END_SECONDS = 30
// Queues past this size aren't persisted across reloads (localStorage
// quota); the player still works, it just starts empty next time.
const MAX_PERSISTED_TRACKS = 2000

// Matches the `sm` breakpoint the mobile-only volume-UI hiding uses.
// Phones control the actual output level with their hardware volume
// buttons, which scale whatever this element outputs — so the element
// itself is kept at full volume there instead of applying the
// desktop-saved level on top of the hardware one.
const MOBILE_VOLUME_BREAKPOINT_PX = 640

function isMobileViewport() {
  return (
    typeof window !== 'undefined' &&
    window.innerWidth < MOBILE_VOLUME_BREAKPOINT_PX
  )
}

function storage() {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

const playlist = ref([])
const currentIndex = ref(-1)
const isPlaying = ref(false)
const isBuffering = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const volume = ref(
  isMobileViewport() ? 1 : parseFloat(storage()?.getItem(VOLUME_KEY) || '0.85')
)
const isMuted = ref(false)
// Podcast episodes only, for now — music always plays at 1x. Per device,
// like volume, so a listener doesn't have to reset it every episode.
const playbackRate = ref(parseFloat(storage()?.getItem(RATE_KEY) || '1'))
// "Fade between songs" (Settings > Playback), per device like volume:
// seconds of fade out at a song's end and fade in at the next one's start.
const fadeSeconds = ref(clampFade(storage()?.getItem(FADE_KEY)))
// "Gapless playback" (Settings > Playback), per device; on unless turned
// off. Only used while no fade is set: a fade overlaps songs on purpose.
const gapless = ref(storage()?.getItem(GAPLESS_KEY) !== '0')
const repeatMode = ref('off') // 'off' | 'all' | 'one'
const shuffle = ref(false)
// Where the queue came from: { type: 'album'|'playlist'|'artist'|
// 'library'|'search', title, route } — shown as "Playing from".
const context = ref(null)
// Sleep timer: epoch ms to stop at, or 'track' to stop after this one.
const sleepAt = ref(null)
const playError = ref('')
// The unstored stream track being resolved right now (a tap, or the
// queue advancing into it) - rows spin on it. Prefetches don't land
// here: they resolve silently one track ahead.
const resolving = ref(null)
// What playback waits on right now, for the loading state the players
// show: 'finding' while an unstored stream resolves, 'loading' while the
// audio waits for data, '' otherwise.
const loadingPhase = computed(() => {
  if (resolving.value) return 'finding'
  return isBuffering.value ? 'loading' : ''
})
// Whether the playhead really moves: playing, and not stalled waiting
// for data. Progress bars glide on this, never on isPlaying alone.
const isAdvancing = computed(() => isPlaying.value && !isBuffering.value)

// shuffleOrder is a plain array; this makes `upcoming` notice changes.
const shuffleVersion = ref(0)

let audio = null
// The element that loads the next song for a gapless change (see the
// "Gapless playback" section), and the queue slot it holds.
let standby = null
let standbyIndex = -1
let standbyTrack = null
let gaplessTimer = 0
let shuffleOrder = []
let shufflePos = 0
let sleepTimer = null
let restoreTime = 0
// Whether the current track began by the queue moving on by itself (it
// fades in then; a track the user picks starts at full volume).
let autoAdvanced = false
let fadeFrame = 0
// The track restoreTime belongs to: any other one starts at 0.
let restoreIndex = -1
let playbackAttempt = 0
// Start held until the track's loudness is known (startPlayback): the
// pause that hold causes isn't the listener's, so it keeps the spinner.
let holdingStart = false

// Stall watchdog: some browsers (iOS Safari above all) can go silent on
// a slow stream without ever firing `waiting`. Playing, yet the playhead
// hasn't moved for this long, counts as loading until it moves again.
export const STALL_MS = 2500
let lastAdvanceAt = 0
let lastSeenTime = -1
let stallTimer = 0
let stalledByWatchdog = false

function noteAdvance(time) {
  if (time === lastSeenTime) return
  lastSeenTime = time
  lastAdvanceAt = Date.now()
  if (stalledByWatchdog) {
    stalledByWatchdog = false
    isBuffering.value = false
  }
}

function checkStall() {
  if (!audio || audio.paused || !isPlaying.value || isBuffering.value) return
  // A hidden page gets throttled timers and timeupdates: no guessing then.
  if (typeof document !== 'undefined' && document.hidden) return
  if (Date.now() - lastAdvanceAt > STALL_MS) {
    stalledByWatchdog = true
    isBuffering.value = true
  }
}

function startStallWatch() {
  lastAdvanceAt = Date.now()
  if (stallTimer || typeof setInterval !== 'function') return
  stallTimer = setInterval(checkStall, 500)
}

function stopStallWatch() {
  clearInterval(stallTimer)
  stallTimer = 0
  if (stalledByWatchdog) {
    stalledByWatchdog = false
    isBuffering.value = false
  }
}

// ── Remote control (a Jam) ───────────────────────────────────────────
// While a hook is set, what the listener asks for (play, skip, seek,
// queue changes) goes to it instead of the local player; whoever set it
// applies the shared state back through withoutHook(). The hook answers
// false to let an action through locally.
let transportHook = null
let hookBypass = 0
const remoteControlled = ref(false)
// Silences this device without touching the listener's own mute: a Jam
// member following along without listening here.
const outputMuted = ref(false)

function setTransportHook(fn) {
  transportHook = typeof fn === 'function' ? fn : null
  remoteControlled.value = !!transportHook
}

function hooked(action, payload = {}) {
  if (!transportHook || hookBypass > 0) return false
  return transportHook(action, payload) !== false
}

/** Run `fn` straight on the local player, past the transport hook. */
function withoutHook(fn) {
  hookBypass += 1
  try {
    return fn()
  } finally {
    hookBypass -= 1
  }
}

function ensureAudio() {
  if (audio) return audio
  audio = createElement()
  applyVolume()
  audio.muted = isMuted.value || outputMuted.value
  audio.playbackRate = playbackRate.value
  return audio
}

function createElement() {
  const el = new Audio()
  // Buffer aggressively: a stream starts while it is still arriving, and
  // the next one is already resolved one track ahead (see prefetchNext).
  el.preload = 'auto'
  // The server may send the audio to another of its hostnames (one that
  // skips its CDN, DOWNTIFY_DIRECT_STREAM_URL). Without CORS, the
  // equalizer's Web Audio graph would play that audio as silence. The
  // cookie still goes to this site; the other host gets a signed URL.
  el.crossOrigin = 'anonymous'
  // Every event is the current song's only while this element plays it:
  // the standby one loads the next song in silence.
  const on = (name, fn) =>
    el.addEventListener(name, (event) => {
      if (el === audio) fn(event)
    })
  on('timeupdate', () => {
    currentTime.value = audio.currentTime
    noteAdvance(audio.currentTime)
    // Safety net near the end: whatever is next by now (a track queued
    // late, a prefetch that failed) gets prepared before it is due.
    if (duration.value - audio.currentTime < PREPARE_BEFORE_END_SECONDS) {
      prefetchNext()
      prepareStandby()
    }
    scheduleGaplessChange()
  })
  on('progress', () => {
    // The current track finished loading: warm the next one now, so a
    // skip starts instantly instead of waiting on the network.
    if (fullyBuffered()) maybePrefetch()
  })
  on('loadedmetadata', () => {
    duration.value = isFinite(audio.duration) ? audio.duration : 0
    if (restoreTime) {
      audio.currentTime = Math.min(restoreTime, duration.value || 0)
      restoreTime = 0
    }
  })
  on('durationchange', () => {
    duration.value = isFinite(audio.duration) ? audio.duration : 0
  })
  on('ended', onEnded)
  on('play', () => {
    isPlaying.value = true
    startStallWatch()
    scheduleFade()
  })
  on('pause', () => {
    isPlaying.value = false
    stopStallWatch()
    // Paused by the system (a call, headphones out) mid-stall: nothing
    // is loading for the listener any more.
    if (!holdingStart && !resolving.value) isBuffering.value = false
  })
  on('waiting', () => {
    isBuffering.value = true
  })
  on('playing', () => {
    stalledByWatchdog = false
    lastAdvanceAt = Date.now()
    isBuffering.value = false
    playError.value = ''
  })
  on('error', () => {
    stopStallWatch()
    isBuffering.value = false
    playError.value = 'unplayable'
  })
  attachEqualizer(el)
  return el
}

function toTrack(item) {
  return typeof item === 'string' ? normalizeTrack(item) : item
}

// ── Shuffle order ────────────────────────────────────────────────────
function buildShuffleOrder() {
  const indices = playlist.value.map((_, i) => i)
  for (let i = indices.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[indices[i], indices[j]] = [indices[j], indices[i]]
  }
  // The playing track stays first so shuffling never skips it.
  const current = currentIndex.value
  if (current >= 0) {
    indices.splice(indices.indexOf(current), 1)
    indices.unshift(current)
  }
  shuffleOrder = indices
  shufflePos = 0
  shuffleVersion.value += 1
}

function trackIdentity(track) {
  return track?.file || track?.url || ''
}

function sameTrackOrder(a, b) {
  if (a.length !== b.length) return false
  // A streamed track has no file: its (fresh, expiring) URL identifies
  // it instead, so re-selecting the playing stream never restarts it by
  // accident - and a new stream never compares equal to the old one.
  return a.every((track, i) => trackIdentity(track) === trackIdentity(b[i]))
}

// ── Queue ────────────────────────────────────────────────────────────
function setPlaylist(files, options = {}) {
  if (
    (typeof options.startIndex === 'number' || options.autoplay) &&
    hooked('replace', {
      tracks: (files || []).map(toTrack),
      startIndex: options.startIndex || 0,
    })
  )
    return
  const incoming = (files || []).map(toTrack)
  const tracks = incoming.filter((track) => !libraryOnly.value || !track.stream)
  if (libraryOnly.value && typeof options.startIndex === 'number') {
    const startIndex = tracks.indexOf(incoming[options.startIndex])
    if (startIndex < 0) return
    options = { ...options, startIndex }
  }
  if (options.context !== undefined) context.value = options.context
  if (
    typeof options.startIndex !== 'number' &&
    sameTrackOrder(tracks, playlist.value)
  ) {
    // Re-selecting the queue that's already loaded must not interrupt
    // what's currently playing.
    return
  }
  playlist.value = tracks
  if (typeof options.startIndex === 'number') {
    if (shuffle.value) {
      currentIndex.value = options.startIndex
      buildShuffleOrder()
    }
    playAt(options.startIndex)
    return
  }
  // Any other queue replacement drops whatever was playing/queued
  // before — a stale currentIndex would otherwise point at an unrelated
  // track in the new list that just happens to share the same position.
  currentIndex.value = -1
  pause()
  if (audio) {
    audio.removeAttribute('src')
  }
  currentTime.value = 0
  duration.value = 0
  if (shuffle.value) buildShuffleOrder()
  if (options.autoplay && tracks.length > 0) {
    playAt(shuffle.value ? shuffleOrder[0] : 0)
  }
}

/** Play a list, optionally shuffled, starting from the first track. */
function playList(files, { context: ctx = null, shuffled = false } = {}) {
  const tracks = (files || [])
    .map(toTrack)
    .filter((track) => !libraryOnly.value || !track.stream)
  if (!tracks.length) return
  if (hooked('replace', { tracks, startIndex: 0, shuffled })) return
  shuffle.value = shuffled
  playlist.value = tracks
  context.value = ctx
  currentIndex.value = -1
  if (shuffled) {
    buildShuffleOrder()
    playAt(shuffleOrder[0])
  } else {
    playAt(0)
  }
}

function insertTracks(files, position) {
  const tracks = (files || [])
    .map(toTrack)
    .filter((track) => !libraryOnly.value || !track.stream)
  if (!tracks.length) return
  if (hooked('insert', { tracks, position })) return
  if (!playlist.value.length) {
    setPlaylist(tracks, { autoplay: true, context: null })
    return
  }
  const list = playlist.value.slice()
  list.splice(position, 0, ...tracks)
  playlist.value = list
  // New rows may hold the next stream: let the loaded trigger below
  // reconsider what "one ahead" is.
  prefetchedFor = -1
  if (currentIndex.value >= position) currentIndex.value += tracks.length
  if (shuffle.value) {
    // Keep the shuffled path, slotting the new tracks in right after
    // the current one when asked to play them next.
    shuffleOrder = shuffleOrder.map((i) =>
      i >= position ? i + tracks.length : i
    )
    const added = tracks.map((_, k) => position + k)
    const at =
      position === currentIndex.value + 1 ? shufflePos + 1 : shuffleOrder.length
    shuffleOrder.splice(at, 0, ...added)
    shuffleVersion.value += 1
  }
  // The current track may have loaded long ago (the progress trigger has
  // fired): prepare the new next one now, not when it is already due.
  if (currentIndex.value >= 0) maybePrefetch()
}

/** Add to the end of the queue. */
function enqueue(files) {
  insertTracks(files, playlist.value.length)
}

/** Add right after the current track. */
function playNext(files) {
  insertTracks(files, currentIndex.value + 1)
}

function moveTrack(from, to) {
  const list = playlist.value.slice()
  if (from === to || from < 0 || to < 0) return
  if (from >= list.length || to >= list.length) return
  if (hooked('move', { from, to })) return
  const [track] = list.splice(from, 1)
  list.splice(to, 0, track)
  playlist.value = list
  const current = currentIndex.value
  if (current === from) currentIndex.value = to
  else if (from < current && to >= current) currentIndex.value = current - 1
  else if (from > current && to <= current) currentIndex.value = current + 1
  if (shuffle.value) buildShuffleOrder()
}

function removeAt(index) {
  if (index < 0 || index >= playlist.value.length) return
  if (hooked('remove', { index })) return
  const list = playlist.value.slice()
  list.splice(index, 1)
  prefetchedFor = -1
  const wasCurrent = index === currentIndex.value
  playlist.value = list
  if (index < currentIndex.value) currentIndex.value -= 1
  if (shuffle.value) buildShuffleOrder()
  if (wasCurrent) {
    if (!list.length) {
      stop()
    } else {
      playAt(Math.min(index, list.length - 1))
    }
  }
}

/** Drop everything after the current track. */
function clearUpcoming() {
  if (hooked('clear')) return
  if (currentIndex.value < 0) {
    stop()
    return
  }
  playlist.value = [playlist.value[currentIndex.value]]
  currentIndex.value = 0
  if (shuffle.value) buildShuffleOrder()
}

/** Remove files that no longer exist (deleted from the library). */
function forgetFiles(files) {
  // A Jam's queue is the server's: every member would remove the same
  // rows at once. It drops deleted songs when they fail to play.
  if (remoteControlled.value) return
  const gone = new Set(files)
  for (let i = playlist.value.length - 1; i >= 0; i--) {
    if (gone.has(playlist.value[i].file)) removeAt(i)
  }
}

/** Refresh queued track details (e.g. tags) from the library. */
function refreshTracks(byFile) {
  let changed = false
  const list = playlist.value.map((track) => {
    const fresh = byFile.get(track.file)
    if (fresh && fresh !== track) {
      changed = true
      return fresh
    }
    return track
  })
  if (changed) playlist.value = list
}

function stop() {
  withoutHook(pause)
  releaseStandby()
  if (audio) audio.removeAttribute('src')
  playlist.value = []
  currentIndex.value = -1
  currentTime.value = 0
  duration.value = 0
  context.value = null
}

// ── Transport ────────────────────────────────────────────────────────
function playAt(index, { auto = false } = {}) {
  if (libraryOnly.value && playlist.value[index]?.stream) return
  if (index < 0 || index >= playlist.value.length) return
  if (hooked('jump', { index })) return
  const a = ensureAudio()
  releaseStandby()
  autoAdvanced = auto
  applyVolume()
  if (index !== restoreIndex) restoreTime = 0
  restoreIndex = -1
  currentIndex.value = index
  prefetchedFor = -1
  syncShufflePos(index)
  playError.value = ''
  if (needsStreamUrl(playlist.value[index])) {
    void playUnresolved(index)
    return
  }
  startAudio(a, index)
}

function syncShufflePos(index) {
  if (!shuffle.value) return
  if (shuffleOrder.length !== playlist.value.length) buildShuffleOrder()
  const pos = shuffleOrder.indexOf(index)
  if (pos >= 0) shufflePos = pos
  shuffleVersion.value += 1
}

// Unresolved stream failures in a row before giving up on the queue
// (reset by any success) - a run of unresolvable tracks skips itself
// instead of stalling the player forever.
const MAX_RESOLVE_FAILURES = 3
let resolveFailures = 0

/** A streamed track whose fresh URL isn't known yet. */
function needsStreamUrl(track) {
  return !!track?.stream && !track.url
}

function startAudio(a, index) {
  if (libraryOnly.value && playlist.value[index]?.stream) return
  a.src = playlist.value[index].url
  a.currentTime = 0
  // A track change doesn't reliably keep the rate in every browser — a
  // podcast episode played at 1.5x shouldn't drop back to 1x on next.
  a.playbackRate = playbackRate.value
  currentTime.value = 0
  startPlayback(a)
  // One track ahead: the next stream resolves while this one plays, so
  // advancing into it (or the track ending) never waits on the network.
  maybePrefetch()
}

// The next track is warmed once per current track: at its start, and
// again the moment it has fully loaded (whichever finds work first).
let prefetchedFor = -1

function maybePrefetch() {
  if (currentIndex.value < 0 || prefetchedFor === currentIndex.value) return
  prefetchedFor = currentIndex.value
  prefetchTrackNormalization(playlist.value[nextIndex()])
  prefetchNext()
}

/** True once the audio element holds the whole current track. */
function fullyBuffered() {
  const total = duration.value
  if (!(total > 0) || !audio) return false
  try {
    const buffered = audio.buffered
    for (let i = 0; i < buffered.length; i++) {
      if (buffered.end(i) >= total - 1) return true
    }
  } catch {
    return false
  }
  return false
}

/** Resolve an unstored stream track, then play it - or skip past it. */
async function playUnresolved(index) {
  const track = playlist.value[index]
  ensureAudio()
  resolving.value = track
  isBuffering.value = true
  playError.value = ''
  currentTime.value = 0
  duration.value = 0
  let url = ''
  try {
    ;({ url } = await resolveTrackUrl(track))
  } catch {
    url = ''
  } finally {
    if (resolving.value === track) resolving.value = null
  }
  // The queue moved on (or the track left it) while resolving.
  if (playlist.value[index] !== track || currentIndex.value !== index) return
  if (!url) {
    resolveFailures += 1
    if (resolveFailures >= MAX_RESOLVE_FAILURES) {
      resolveFailures = 0
      playError.value = 'unplayable'
      isBuffering.value = false
      pause()
      return
    }
    next()
    return
  }
  resolveFailures = 0
  playlist.value[index] = { ...track, url }
  startAudio(ensureAudio(), index)
}

// The stream track being prepared right now, so the timeupdate safety
// net doesn't ask again on every tick.
let preparing = null

/** Resolve the next unstored track while this one plays, one ahead. */
function prefetchNext() {
  if (libraryOnly.value) return
  const upcoming = nextIndex()
  if (upcoming < 0) return
  const track = playlist.value[upcoming]
  if (!needsStreamUrl(track) || preparing === track) return
  preparing = track
  const list = playlist.value
  resolveTrackUrl(track).then(
    ({ url, videoId }) => {
      // Another queue took its place meanwhile: leave it alone.
      if (playlist.value === list && playlist.value[upcoming] === track) {
        playlist.value[upcoming] = { ...track, url }
      }
      // Warm the server download too, so the file (not just its URL)
      // already waits when the turn comes.
      warmServerCache(videoId)
    },
    () => {
      // Silent: advancing into it resolves again, with an error then.
      if (preparing === track) preparing = null
    }
  )
}

/** Prepare whatever is next now (tracks were added after the current
 * one started, e.g. by autoplay). */
function prepareNext() {
  prefetchedFor = -1
  if (currentIndex.value >= 0) maybePrefetch()
}

function startPlayback(a) {
  if (libraryOnly.value && playlist.value[currentIndex.value]?.stream) return
  const attempt = ++playbackAttempt
  const track = playlist.value[currentIndex.value]
  const known = knownTrackNormalization(track)
  if (known === undefined) {
    // Normalized but not measured yet: hold the start until the server
    // answers (the request gives up quickly), so no moment of the song
    // plays at the wrong level.
    const identity = trackIdentity(track)
    const url = a.src
    holdingStart = true
    a.pause()
    applyTrackNormalization(null)
    // Build/resume during the user gesture, before awaiting the measurement.
    resumeEqualizer()
    isBuffering.value = true
    void getTrackNormalization(track).then((profile) => {
      if (
        attempt !== playbackAttempt ||
        a.src !== url ||
        trackIdentity(playlist.value[currentIndex.value]) !== identity
      )
        return
      holdingStart = false
      applyTrackNormalization(profile)
      isBuffering.value = false
      resumeEqualizer()
      a.play().catch(() => {})
    })
    return
  }
  holdingStart = false
  applyTrackNormalization(known)
  resumeEqualizer()
  a.play().catch(() => {})
}

function play() {
  if (hooked('play')) return
  if (libraryOnly.value && playlist.value[currentIndex.value]?.stream) return
  if (playlist.value.length === 0) return
  const a = ensureAudio()
  if (currentIndex.value < 0) {
    playAt(shuffle.value && shuffleOrder.length ? shuffleOrder[0] : 0)
    return
  }
  if (!a.src) {
    // Paused mid-resolve (or before it started): go through playAt so an
    // unstored track resolves instead of loading an empty src.
    if (needsStreamUrl(playlist.value[currentIndex.value])) {
      playAt(currentIndex.value)
      return
    }
    a.src = playlist.value[currentIndex.value].url
  }
  startPlayback(a)
}

/** Try the current song again; a stream looks its audio up afresh. */
function retry() {
  const index = currentIndex.value
  const track = playlist.value[index]
  if (!track) return
  if (track.stream) playlist.value[index] = { ...track, url: '' }
  resolveFailures = 0
  playAt(index)
}

function pause() {
  if (hooked('pause')) return
  playbackAttempt += 1
  holdingStart = false
  isBuffering.value = false
  if (audio) audio.pause()
}

function toggle() {
  if (isPlaying.value) pause()
  else play()
}

function seek(seconds) {
  const max = duration.value || 0
  const clamped = Math.max(0, Math.min(max, seconds))
  if (hooked('seek', { position: clamped })) return
  const a = ensureAudio()
  clearTimeout(gaplessTimer)
  gaplessTimer = 0
  a.currentTime = clamped
  currentTime.value = clamped
}

function seekRatio(ratio) {
  if (!duration.value) return
  seek(duration.value * Math.max(0, Math.min(1, ratio)))
}

function seekBy(delta) {
  seek(currentTime.value + delta)
}

function setVolume(v) {
  const clamped = Math.max(0, Math.min(1, v))
  volume.value = clamped
  applyVolume()
  try {
    storage()?.setItem(VOLUME_KEY, String(clamped))
  } catch {
    // ignore
  }
  if (clamped > 0 && isMuted.value) {
    isMuted.value = false
    applyMuted()
  }
}

// ── Fade between songs ───────────────────────────────────────────────
function currentFadeGain() {
  const track = playlist.value[currentIndex.value]
  if (!audio || !fadeSeconds.value || track?.isPodcast) return 1
  // Fading out only makes sense when something follows.
  const fadeOut =
    repeatMode.value !== 'one' && sleepAt.value !== 'track' && nextIndex() >= 0
  return fadeGain(audio.currentTime, duration.value, fadeSeconds.value, {
    fadeIn: autoAdvanced,
    fadeOut,
  })
}

function applyVolume() {
  if (audio) audio.volume = volume.value * currentFadeGain()
}

// While playing with a fade set, the volume follows the playhead every
// frame (timeupdate alone ticks too coarsely for a smooth ramp).
function scheduleFade() {
  if (fadeFrame || typeof requestAnimationFrame === 'undefined') return
  const tick = () => {
    fadeFrame = 0
    applyVolume()
    if (isPlaying.value && fadeSeconds.value) {
      fadeFrame = requestAnimationFrame(tick)
    }
  }
  fadeFrame = requestAnimationFrame(tick)
}

function setFadeSeconds(value) {
  fadeSeconds.value = clampFade(value)
  try {
    storage()?.setItem(FADE_KEY, String(fadeSeconds.value))
  } catch {
    // ignore
  }
  if (fadeSeconds.value) releaseStandby()
  applyVolume()
  if (isPlaying.value) scheduleFade()
}

function toggleMute() {
  isMuted.value = !isMuted.value
  applyMuted()
}

function applyMuted() {
  if (audio) audio.muted = isMuted.value || outputMuted.value
}

/** Silence (or not) this device's output, the listener's mute aside. */
function setOutputMuted(muted) {
  outputMuted.value = !!muted
  applyMuted()
}

function setPlaybackRate(rate) {
  const clamped = Math.max(0.5, Math.min(3, rate))
  playbackRate.value = clamped
  if (audio) audio.playbackRate = clamped
  try {
    storage()?.setItem(RATE_KEY, String(clamped))
  } catch {
    // ignore
  }
}

function nextIndex() {
  if (playlist.value.length === 0) return -1
  if (shuffle.value) {
    if (shuffleOrder.length !== playlist.value.length) buildShuffleOrder()
    const nextPos = shufflePos + 1
    if (nextPos >= shuffleOrder.length) {
      return repeatMode.value === 'all' ? shuffleOrder[0] : -1
    }
    return shuffleOrder[nextPos]
  }
  const i = currentIndex.value + 1
  if (i >= playlist.value.length) {
    return repeatMode.value === 'all' ? 0 : -1
  }
  return i
}

function prevIndex() {
  if (playlist.value.length === 0) return -1
  if (shuffle.value) {
    if (shuffleOrder.length !== playlist.value.length) buildShuffleOrder()
    const prevPos = (shufflePos - 1 + shuffleOrder.length) % shuffleOrder.length
    return shuffleOrder[prevPos]
  }
  const i = currentIndex.value - 1
  if (i < 0) {
    return repeatMode.value === 'all' ? playlist.value.length - 1 : 0
  }
  return i
}

function next({ auto = false } = {}) {
  if (hooked('next')) return
  const i = nextIndex()
  if (i < 0) {
    pause()
    return
  }
  playAt(i, { auto })
}

function prev() {
  if (hooked('prev')) return
  const a = ensureAudio()
  if (a.currentTime > 3) {
    seek(0)
    return
  }
  const i = prevIndex()
  if (i < 0) return
  playAt(i)
}

function onEnded() {
  if (sleepAt.value === 'track') {
    setSleepTimer(null)
    pause()
    return
  }
  if (hooked('ended', { index: currentIndex.value })) return
  if (repeatMode.value === 'one') {
    seek(0)
    if (audio) startPlayback(audio)
    return
  }
  // The timed change didn't happen (a background tab's throttled timers,
  // a song that ended early): the loaded next song still starts at once.
  if (swapToStandby({ requireBuffered: false })) return
  next({ auto: true })
}

// ── Gapless playback ─────────────────────────────────────────────────
// The next song loads in the standby element while this one plays, and
// is started a moment before this one ends instead of after its `ended`
// event and a fresh load. Encoder padding (MP3, AAC) is trimmed by the
// browser from the files' own gapless headers.
//
// How early the next song is started: about what a browser needs to get
// sound out of an element that is already loaded.
const GAPLESS_LEAD_SECONDS = 0.03
// Within this much of the end, the change is timed by a timer instead of
// the (coarse) timeupdate events.
const GAPLESS_WINDOW_SECONDS = 1

function gaplessActive() {
  return (
    gapless.value &&
    !fadeSeconds.value &&
    !transportHook &&
    repeatMode.value !== 'one' &&
    sleepAt.value !== 'track'
  )
}

/** Whether the standby element holds the song that comes next. */
function standbyReady({ requireBuffered = true } = {}) {
  const index = nextIndex()
  if (!standby || index < 0 || index !== standbyIndex) return false
  if (playlist.value[index] !== standbyTrack || standby.error) return false
  // HAVE_FUTURE_DATA: it can start playing right away.
  return !requireBuffered || standby.readyState >= 3
}

/** Load what comes next into the standby element, once. */
function prepareStandby() {
  if (!audio || !gaplessActive() || !(duration.value > 0)) return
  const index = nextIndex()
  const track = playlist.value[index]
  if (index < 0 || index === currentIndex.value || !track?.url) return
  if (track.isPodcast || (libraryOnly.value && track.stream)) return
  if (standbyIndex === index && standbyTrack === track) return
  if (!standby) standby = createElement()
  standbyIndex = index
  standbyTrack = track
  standby.muted = true
  standby.src = track.url
  standby.load()
  prefetchTrackNormalization(track)
}

/** Drop what the standby element holds (the queue went elsewhere). */
function releaseStandby() {
  clearTimeout(gaplessTimer)
  gaplessTimer = 0
  standbyIndex = -1
  standbyTrack = null
  if (standby?.src) {
    standby.pause()
    standby.removeAttribute('src')
    standby.load()
  }
}

/** Near the end of the song, time the change to the standby element. */
function scheduleGaplessChange() {
  if (gaplessTimer || !audio || audio.paused || !gaplessActive()) return
  if (!standbyReady()) return
  const left = (duration.value - audio.currentTime) / (audio.playbackRate || 1)
  if (!(left > 0) || left > GAPLESS_WINDOW_SECONDS) return
  gaplessTimer = setTimeout(
    () => {
      gaplessTimer = 0
      if (!audio || audio.paused) return
      const rest =
        (duration.value - audio.currentTime) / (audio.playbackRate || 1)
      // Held up by a stall or moved by a seek: look again on the next tick.
      if (rest > GAPLESS_LEAD_SECONDS + 0.1) return
      swapToStandby()
    },
    Math.max(0, (left - GAPLESS_LEAD_SECONDS) * 1000)
  )
}

/**
 * Hand playback to the standby element, which already holds the next
 * song. Returns false (nothing changed) when it can't: the normal path
 * then loads the song as usual.
 */
function swapToStandby({ requireBuffered = true } = {}) {
  if (!gaplessActive() || !standbyReady({ requireBuffered })) return false
  // Normalized but not measured yet: the normal path holds the start.
  const known = knownTrackNormalization(standbyTrack)
  if (known === undefined) return false
  const index = standbyIndex
  const previous = audio
  const nextElement = standby
  audio = nextElement
  standby = previous
  standbyIndex = -1
  standbyTrack = null
  clearTimeout(gaplessTimer)
  gaplessTimer = 0
  previous.pause()
  autoAdvanced = true
  restoreTime = 0
  restoreIndex = -1
  currentIndex.value = index
  prefetchedFor = -1
  syncShufflePos(index)
  playError.value = ''
  currentTime.value = 0
  duration.value = isFinite(audio.duration) ? audio.duration : 0
  audio.playbackRate = playbackRate.value
  applyMuted()
  applyVolume()
  holdingStart = false
  const attempt = ++playbackAttempt
  applyTrackNormalization(known)
  resumeEqualizer()
  audio.play().then(
    () => {
      if (standby === previous && previous !== audio) {
        previous.removeAttribute('src')
        previous.load()
      }
    },
    () => {
      // Refused outside a gesture (iPhones want one per element): load
      // the song in the element that was playing instead.
      if (attempt !== playbackAttempt || audio !== nextElement) return
      nextElement.pause()
      audio = previous
      standby = nextElement
      playAt(index, { auto: true })
    }
  )
  maybePrefetch()
  return true
}

function setGapless(on) {
  gapless.value = !!on
  try {
    storage()?.setItem(GAPLESS_KEY, gapless.value ? '1' : '0')
  } catch {
    // ignore
  }
  if (!gapless.value) releaseStandby()
}

function setRepeat(mode) {
  if (hooked('repeat', { mode })) return
  if (['off', 'all', 'one'].includes(mode)) repeatMode.value = mode
}

function cycleRepeat() {
  const order = ['off', 'all', 'one']
  const i = order.indexOf(repeatMode.value)
  setRepeat(order[(i + 1) % order.length])
}

function setShuffle(v) {
  if (hooked('shuffle', { on: !!v })) return
  shuffle.value = !!v
  if (shuffle.value) buildShuffleOrder()
}

function toggleShuffle() {
  setShuffle(!shuffle.value)
}

// ── Following a shared queue ─────────────────────────────────────────
/**
 * Take `tracks` as the queue with `index` current, without restarting
 * the song already playing when it is still the current one. Returns
 * true when the current song changed (the caller cues it).
 */
function adoptQueue(tracks, index) {
  const before = playlist.value[currentIndex.value]
  shuffle.value = false
  repeatMode.value = 'off'
  context.value = null
  if (!sameTrackOrder(tracks, playlist.value)) {
    playlist.value = tracks
    prefetchedFor = -1
  }
  const after = tracks[index]
  const same =
    !!after && !!before && trackIdentity(after) === trackIdentity(before)
  currentIndex.value = after ? index : -1
  return !same || !audio?.src
}

/** Load song `index` at `seconds`, playing or paused. */
function cueAt(index, seconds = 0, playing = true) {
  if (index < 0 || index >= playlist.value.length) return
  withoutHook(() => {
    restoreTime = Math.max(0, seconds)
    restoreIndex = index
    if (playing) {
      playAt(index)
      return
    }
    const a = ensureAudio()
    pause()
    currentIndex.value = index
    restoreIndex = -1
    a.src = playlist.value[index].url
    currentTime.value = restoreTime
  })
}

// ── Sleep timer ──────────────────────────────────────────────────────
/** `minutes` (number), `'track'` (end of this track) or null (off). */
function setSleepTimer(minutes) {
  if (sleepTimer) {
    clearTimeout(sleepTimer)
    sleepTimer = null
  }
  if (minutes === 'track') {
    sleepAt.value = 'track'
    return
  }
  if (!minutes) {
    sleepAt.value = null
    return
  }
  sleepAt.value = Date.now() + minutes * 60 * 1000
  sleepTimer = setTimeout(
    () => {
      pause()
      sleepAt.value = null
      sleepTimer = null
    },
    minutes * 60 * 1000
  )
}

// ── Derived state ────────────────────────────────────────────────────
const currentTrack = computed(() =>
  currentIndex.value >= 0 && currentIndex.value < playlist.value.length
    ? playlist.value[currentIndex.value]
    : null
)

const progressPct = computed(() =>
  duration.value > 0 ? (currentTime.value / duration.value) * 100 : 0
)

/** Upcoming tracks, in the order they'll play: `[{ track, index }]`. */
const upcoming = computed(() => {
  const list = playlist.value
  // Reading these keeps the computed in step with shuffle/index changes.
  const current = currentIndex.value
  shuffleVersion.value
  if (shuffle.value && shuffleOrder.length === list.length) {
    return shuffleOrder
      .slice(shufflePos + 1)
      .map((index) => ({ track: list[index], index }))
  }
  return list
    .slice(current + 1)
    .map((track, k) => ({ track, index: current + 1 + k }))
})

// ── Media Session (lock screen / headset / keyboard media keys) ──────
function updateMediaSession(track) {
  if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) {
    return
  }
  const session = navigator.mediaSession
  if (!track) {
    session.metadata = null
    return
  }
  if (typeof MediaMetadata !== 'undefined') {
    const origin = typeof location !== 'undefined' ? location.origin : ''
    const cover = String(track.cover || '')
    const artwork =
      track.hasCover && cover
        ? [
            {
              src: cover.startsWith('http') ? cover : `${origin}${cover}`,
              sizes: '512x512',
            },
          ]
        : []
    session.metadata = new MediaMetadata({
      title: track.title,
      artist: track.artist,
      album: track.album || '',
      artwork,
    })
  }
  // Previous / next on the lock screen, like Spotify - never the
  // 10-second jumps iOS shows instead when seeking is handled (see
  // lib/mediaSession.js; a podcast keeps them).
  const handlers = mediaSessionHandlers(track, {
    play,
    pause,
    prev,
    next,
    seek,
    seekBy,
  })
  for (const [action, handler] of Object.entries(handlers)) {
    try {
      session.setActionHandler(action, handler)
    } catch {
      // Unsupported action on this browser.
    }
  }
  updatePositionState()
}

// The lock screen's progress bar follows the song (and can be dragged).
let lastPositionSync = 0
function updatePositionState() {
  if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) {
    return
  }
  const session = navigator.mediaSession
  if (typeof session.setPositionState !== 'function') return
  lastPositionSync = Date.now()
  const state = positionState(
    duration.value,
    currentTime.value,
    playbackRate.value
  )
  try {
    session.setPositionState(state || undefined)
  } catch {
    // An invalid moment (a length not known yet): the next update fixes it.
  }
}

watch(currentTrack, (track) => updateMediaSession(track))
watch([duration, isAdvancing, playbackRate], () => updatePositionState())
watch(currentTime, (now, before) => {
  // A seek, or every few seconds while playing.
  const jumped = Math.abs((Number(now) || 0) - (Number(before) || 0)) > 2
  if (jumped || Date.now() - lastPositionSync > 5000) updatePositionState()
})

// Switched on mid-song: level the current one too (the equalizer ramps
// to it), instead of waiting for the next.
watch(normalizationEnabled, (on) => {
  const track = playlist.value[currentIndex.value]
  if (!on || !track?.file) return
  void getTrackNormalization(track).then((profile) => {
    if (
      normalizationEnabled.value &&
      playlist.value[currentIndex.value] === track
    )
      applyTrackNormalization(profile)
  })
})
watch(libraryOnly, (enabled) => {
  if (!enabled) return
  const selected = playlist.value[currentIndex.value]
  releaseStandby()
  if (selected?.stream) {
    pause()
    if (audio) {
      audio.removeAttribute('src')
      audio.load()
    }
    isBuffering.value = false
    resolving.value = null
  }
  playlist.value = playlist.value.filter((track) => !track.stream)
  currentIndex.value = playlist.value.indexOf(selected)
  if (shuffle.value) buildShuffleOrder()
})
// Stalled on the network counts as paused there too, or the lock
// screen's bar would run ahead of the silent song.
watch(isAdvancing, (advancing) => {
  if (typeof navigator !== 'undefined' && 'mediaSession' in navigator) {
    navigator.mediaSession.playbackState = advancing ? 'playing' : 'paused'
  }
})

// ── Persist the session across reloads ───────────────────────────────
// A stream's URL expires within hours, so a streamed track is saved
// without it: after a reload it resolves again when it plays (see
// needsStreamUrl), and a mixed queue picks up where it was.
export function persistedTrack(track) {
  return track?.stream && track.url ? { ...track, url: '' } : track
}

function saveSession() {
  const store = storage()
  if (!store) return
  if (!playlist.value.length || playlist.value.length > MAX_PERSISTED_TRACKS) {
    store.removeItem(SESSION_KEY)
    return
  }
  try {
    store.setItem(
      SESSION_KEY,
      JSON.stringify({
        tracks: playlist.value.map(persistedTrack),
        index: currentIndex.value,
        time: Math.floor(currentTime.value),
        context: context.value,
        shuffle: shuffle.value,
        repeat: repeatMode.value,
      })
    )
  } catch {
    // Quota exceeded — keep playing, just don't persist.
  }
}

function restoreSession() {
  const raw = storage()?.getItem(SESSION_KEY)
  if (!raw) return
  try {
    const saved = JSON.parse(raw)
    if (!Array.isArray(saved.tracks) || !saved.tracks.length) return
    playlist.value = saved.tracks
    currentIndex.value = Math.min(saved.index ?? -1, saved.tracks.length - 1)
    context.value = saved.context || null
    repeatMode.value = saved.repeat || 'off'
    shuffle.value = !!saved.shuffle
    if (shuffle.value) buildShuffleOrder()
    const track = currentTrack.value
    if (track) {
      const a = ensureAudio()
      restoreTime = saved.time || 0
      restoreIndex = currentIndex.value
      currentTime.value = restoreTime
      // A streamed track resolves when play() reaches it.
      if (!needsStreamUrl(track)) a.src = track.url
    }
  } catch {
    storage()?.removeItem(SESSION_KEY)
  }
}

if (typeof window !== 'undefined' && typeof Audio !== 'undefined') {
  restoreSession()
  watch([playlist, currentIndex, context, shuffle, repeatMode], saveSession)
  window.addEventListener('pagehide', saveSession)
  setInterval(() => {
    if (isPlaying.value) saveSession()
  }, 5000)
}

// ── Public API ───────────────────────────────────────────────────────
export function formatTime(seconds) {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const total = Math.floor(seconds)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function trackInfoFromFile(file) {
  return normalizeTrack(file)
}

export function usePlayer() {
  return {
    playlist,
    currentIndex,
    currentTrack,
    upcoming,
    context,
    isPlaying,
    isBuffering,
    isAdvancing,
    loadingPhase,
    retry,
    playError,
    currentTime,
    duration,
    progressPct,
    volume,
    isMuted,
    playbackRate,
    fadeSeconds,
    setFadeSeconds,
    gapless,
    setGapless,
    repeatMode,
    shuffle,
    sleepAt,
    resolving,
    setPlaylist,
    playList,
    enqueue,
    prepareNext,
    playNext,
    moveTrack,
    removeAt,
    clearUpcoming,
    forgetFiles,
    refreshTracks,
    stop,
    playAt,
    play,
    pause,
    toggle,
    seek,
    seekRatio,
    seekBy,
    setVolume,
    toggleMute,
    setPlaybackRate,
    next,
    prev,
    setRepeat,
    cycleRepeat,
    setShuffle,
    toggleShuffle,
    setSleepTimer,
    remoteControlled,
    outputMuted,
    setOutputMuted,
    setTransportHook,
    withoutHook,
    adoptQueue,
    cueAt,
  }
}
