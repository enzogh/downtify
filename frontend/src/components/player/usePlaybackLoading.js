// The loading state the players show while a song isn't heard yet: a
// stream still being found, or audio waiting on the network. It appears
// only after a short wait, so a quick start never flashes a spinner, and
// says so when the wait drags on.
import { computed, onBeforeUnmount, ref, watch } from 'vue'

export const SHOW_AFTER_MS = 350
export const SLOW_AFTER_MS = 8000

/** The i18n key describing `phase` ('finding' | 'loading' | ''). */
export function loadingLabelKey(phase, slow = false) {
  if (!phase) return ''
  if (slow) return 'player.stillLoading'
  return phase === 'finding' ? 'player.findingSong' : 'player.loadingSong'
}

/**
 * `phase()` → the player's loadingPhase. Returns `{ visible, labelKey }`:
 * whether to show the loading state, and the key of the text for it.
 */
export function usePlaybackLoading(phase) {
  const visible = ref(false)
  const slow = ref(false)
  let showTimer = 0
  let slowTimer = 0

  function clear() {
    clearTimeout(showTimer)
    clearTimeout(slowTimer)
    showTimer = 0
    slowTimer = 0
  }

  // Keyed on "waiting at all", so finding → loading keeps counting.
  watch(
    () => !!phase(),
    (waiting) => {
      clear()
      visible.value = false
      slow.value = false
      if (!waiting) return
      showTimer = setTimeout(() => (visible.value = true), SHOW_AFTER_MS)
      slowTimer = setTimeout(() => (slow.value = true), SLOW_AFTER_MS)
    },
    { immediate: true }
  )
  onBeforeUnmount(clear)

  const labelKey = computed(() =>
    visible.value ? loadingLabelKey(phase(), slow.value) : ''
  )
  return { visible, labelKey }
}
