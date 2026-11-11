// The signed-in user's own preferences (Settings > General) and the
// "what am I playing" reports behind the admins' Activity page.
//
// Theme, language, "Show lyrics" and "Normalize playback volume" still
// apply at once in this browser (and are remembered in it); they are
// also kept with the account, so signing in somewhere else brings them
// along. "Albums in search" lives only with the account - and changing
// any of these changes nothing for anyone else.
import { ref, watch } from 'vue'

import API from '/src/model/api'
import {
  currentLocale,
  defaultedLocale,
  setLocale,
  takeFrenchDefault,
} from '/src/i18n'
import { playbackReport } from '/src/lib/auth'
import { useAuth } from '/src/model/auth'
import { useLibrary } from '/src/model/library'
import { usePlayer } from '/src/model/player'
import { usePlayerPrefs } from '/src/model/playerPrefs'
import { useTheme } from '/src/model/theme'

const searchAlbums = ref(true)
// Other people's public playlists in the lists (the server also applies
// it, so apps agree). On unless switched off.
const showPublicPlaylists = ref(true)
// Admins only: list every user's playlists, not just their own (they may
// open any of them either way). Off unless switched on.
const showAllPlaylists = ref(false)
// Whether the admin lets users share playlists at all.
const playlistSharing = ref(true)
const ready = ref(false)
let started = false
// True until the first account preferences of this browser are applied
// after the switch to French as the default language.
let frenchDefaultPending = takeFrenchDefault()

function current() {
  const theme = useTheme()
  const { showLyrics, normalizeVolume } = usePlayerPrefs()
  return {
    theme: theme.mode.value,
    locale: currentLocale.value,
    show_lyrics: showLyrics.value,
    normalize_volume: normalizeVolume.value,
    search_albums: searchAlbums.value,
    show_public_playlists: showPublicPlaylists.value,
    show_all_playlists: showAllPlaylists.value,
  }
}

function apply(prefs) {
  const theme = useTheme()
  const { showLyrics, normalizeVolume } = usePlayerPrefs()
  if (prefs.theme) theme.setMode(prefs.theme)
  if (prefs.locale) {
    // French is the default: the English an account saved back when it
    // was the default becomes French once (see i18n/index.js).
    const locale = defaultedLocale(prefs.locale, !frenchDefaultPending)
    if (locale !== currentLocale.value) setLocale(locale)
  }
  if (typeof prefs.show_lyrics === 'boolean')
    showLyrics.value = prefs.show_lyrics
  if (typeof prefs.normalize_volume === 'boolean')
    normalizeVolume.value = prefs.normalize_volume
  if (typeof prefs.search_albums === 'boolean')
    searchAlbums.value = prefs.search_albums
  if (typeof prefs.show_public_playlists === 'boolean')
    showPublicPlaylists.value = prefs.show_public_playlists
  if (typeof prefs.show_all_playlists === 'boolean')
    showAllPlaylists.value = prefs.show_all_playlists
}

async function save() {
  try {
    await API.setPreferences(current())
  } catch {
    // Kept in this browser anyway; the next change tries again.
  }
}

/** Load the account's preferences, then keep them in step. */
async function start() {
  if (started) return
  started = true
  let prefs = {}
  try {
    const me = (await API.getMe()).data || {}
    prefs = me.preferences || {}
    playlistSharing.value = me.playlist_sharing !== false
  } catch {
    started = false
    return
  }
  apply(prefs)
  ready.value = true
  // An account without them adopts this browser's; one switched to the
  // French default keeps it.
  const switched = frenchDefaultPending && prefs.locale === 'en'
  frenchDefaultPending = false
  if (Object.keys(prefs).length < 4 || switched) save()
  const theme = useTheme()
  const { showLyrics, normalizeVolume } = usePlayerPrefs()
  watch(
    [
      theme.mode,
      currentLocale,
      showLyrics,
      normalizeVolume,
      searchAlbums,
      showPublicPlaylists,
    ],
    () => save(),
    { flush: 'post' }
  )
  // The server picks the playlists listed: ask again once it knows.
  watch(
    showAllPlaylists,
    () => save().then(() => useLibrary().refreshPlaylists()),
    { flush: 'post' }
  )
}

// ── Playback reports ──────────────────────────────────────────────────
const HEARTBEAT_MS = 30000
let reporting = false

function startPlaybackReports() {
  if (reporting) return
  reporting = true
  const player = usePlayer()
  let lastSent = 0
  let lastState = ''
  let lastFile = ''

  function send(state) {
    const track = player.currentTrack.value
    const report = playbackReport(track, {
      player: API.clientId,
      state,
      position: player.currentTime.value,
    })
    if (!report) return
    lastSent = Date.now()
    lastState = state
    lastFile = track?.file || ''
    API.reportPlayback(report).catch(() => {
      // Best effort: it feeds the admins' Activity page and this
      // account's other devices.
    })
  }

  watch(
    () => [player.currentTrack.value?.file, player.isPlaying.value],
    ([file, playing]) => {
      if (!file) {
        if (lastFile) send('stopped')
        lastFile = ''
        return
      }
      const state = playing ? 'playing' : 'paused'
      if (file !== lastFile || state !== lastState) send(state)
    }
  )
  watch(player.currentTime, (now, before) => {
    if (!player.isPlaying.value) return
    // A jump (a seek) is told at once, so another device picking the
    // song up starts where it is - not where it was 30 s ago.
    const jumped = Math.abs((Number(now) || 0) - (Number(before) || 0)) > 4
    if (jumped || Date.now() - lastSent > HEARTBEAT_MS) send('playing')
  })
  window.addEventListener('pagehide', () => {
    if (lastFile) send('stopped')
  })
}

export function useAccount() {
  const auth = useAuth()
  return {
    searchAlbums,
    showPublicPlaylists,
    showAllPlaylists,
    playlistSharing,
    ready,
    start,
    startPlaybackReports,
    user: auth.user,
  }
}
