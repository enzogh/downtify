import { ref, watch } from 'vue'
import API from '/src/model/api'

export const libraryOnly = ref(false)
export const policyLoaded = ref(false)
export const musicPolicyRevision = ref(0)
watch(
  libraryOnly,
  () => {
    musicPolicyRevision.value += 1
  },
  { flush: 'sync' }
)

export async function refreshMusicPolicy() {
  try {
    const response = await API.getServerInfo()
    libraryOnly.value = response.data?.library_only === true
  } catch {
    // Keep the last known policy when the server cannot be reached.
  } finally {
    policyLoaded.value = true
  }
}

// The server pushes `music_policy_changed`: while the WebSocket is open
// the policy is only checked again every few minutes (a missed frame),
// otherwise every 15 s. Never while the tab is hidden.
const POLICY_POLL_MS = 15000
const POLICY_POLL_CONNECTED_MS = 300000

export function startMusicPolicy() {
  void refreshMusicPolicy()
  let lastCheck = Date.now()
  const timer = setInterval(() => {
    if (typeof document !== 'undefined' && document.hidden) return
    const wait = API.socketOpen?.() ? POLICY_POLL_CONNECTED_MS : POLICY_POLL_MS
    if (Date.now() - lastCheck < wait - 100) return
    lastCheck = Date.now()
    void refreshMusicPolicy()
  }, POLICY_POLL_MS)
  const unsubscribe = API.onMessage((data) => {
    if (data?.type === 'music_policy_changed') {
      libraryOnly.value = data.library_only === true
    }
  })
  return () => {
    clearInterval(timer)
    unsubscribe()
  }
}
