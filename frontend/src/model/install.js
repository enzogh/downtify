// The "install Castify on your phone" guide: shared state for the sheet
// (InstallPrompt.vue) and the account menu entry that reopens it.
//
// Chrome on Android fires `beforeinstallprompt` once, early - often
// before the shell mounts - so the listener lives here and main.js
// imports this module at startup.
import { computed, ref } from 'vue'
import {
  SNOOZE_MS,
  installPlatform,
  isStandalone,
  shouldOffer,
} from '/src/lib/installPrompt'

const SNOOZE_KEY = 'downtify-install-snoozed-until'
const DONE_KEY = 'downtify-install-done'

function read(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key, value) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // Private mode: the guide just comes back next time.
  }
}

const nav = globalThis.navigator
const platform = ref(installPlatform(nav?.userAgent, nav?.maxTouchPoints))
const standalone = ref(isStandalone(globalThis))
const installed = ref(read(DONE_KEY) === '1')
const snoozedUntil = ref(Number(read(SNOOZE_KEY)) || 0)
// Chrome's deferred install prompt, when it offered one.
const deferred = ref(null)
const open = ref(false)

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (event) => {
    // Keep Chrome's own mini-infobar quiet: our sheet asks instead.
    event.preventDefault()
    deferred.value = event
  })
  window.addEventListener('appinstalled', () => {
    deferred.value = null
    markInstalled()
  })
  // Launched from the home screen after all (or switched to it).
  window
    .matchMedia?.('(display-mode: standalone)')
    ?.addEventListener?.('change', (e) => {
      standalone.value = e.matches || isStandalone(window)
      if (standalone.value) open.value = false
    })
}

function markInstalled() {
  installed.value = true
  open.value = false
  write(DONE_KEY, '1')
}

function snooze() {
  snoozedUntil.value = Date.now() + SNOOZE_MS
  write(SNOOZE_KEY, String(snoozedUntil.value))
  open.value = false
}

/** Opens Chrome's install dialog; resolves true when accepted. */
async function promptInstall() {
  const event = deferred.value
  if (!event) return false
  deferred.value = null
  try {
    await event.prompt()
    const choice = await event.userChoice
    if (choice?.outcome === 'accepted') {
      markInstalled()
      return true
    }
  } catch {
    // Already used or blocked: the manual steps stay on screen.
  }
  return false
}

// A phone, in a browser tab: the menu entry stays available even after
// "Later" or "Already installed", so the guide can always be reopened.
const available = computed(() => !!platform.value && !standalone.value)

/** Opens the guide by itself when it's due (called once the shell shows). */
function offer() {
  if (
    shouldOffer({
      platform: platform.value,
      standalone: standalone.value,
      installed: installed.value,
      snoozedUntil: snoozedUntil.value,
      now: Date.now(),
    })
  )
    open.value = true
}

export function useInstall() {
  return {
    platform,
    available,
    open,
    canPrompt: computed(() => !!deferred.value),
    offer,
    show: () => (open.value = true),
    snooze,
    markInstalled,
    promptInstall,
  }
}
