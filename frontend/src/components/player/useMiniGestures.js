// Touch gestures on the mini player: swipe the song sideways to skip
// (left = next, right = previous, like a music app's card) and hold it
// to open its menu. Mouse input is left alone: desktop has buttons.
import { ref } from 'vue'

export const SWIPE_PX = 56
export const LONG_PRESS_MS = 500
export const MOVE_TOLERANCE_PX = 10
const MAX_SHIFT_PX = 80

/** 'next', 'prev' or '' for a gesture that moved `dx`, `dy` pixels. */
export function swipeDirection(dx, dy) {
  if (Math.abs(dx) < SWIPE_PX || Math.abs(dx) < Math.abs(dy) * 1.5) return ''
  return dx < 0 ? 'next' : 'prev'
}

/**
 * `{ onNext, onPrev, onLongPress(point) }` → `{ shift, handlers }`:
 * bind `handlers` on the element (v-on) and translate it by `shift` px
 * while it is dragged.
 */
export function useMiniGestures({ onNext, onPrev, onLongPress }) {
  const shift = ref(0)
  let start = null
  let timer = 0
  // A swipe or hold already acted: the click that follows mustn't too.
  let consumed = false

  function reset() {
    clearTimeout(timer)
    timer = 0
    start = null
    shift.value = 0
  }

  function down(event) {
    if (event.pointerType === 'mouse' || !event.isPrimary) return
    consumed = false
    start = { x: event.clientX, y: event.clientY }
    const point = { clientX: event.clientX, clientY: event.clientY }
    timer = setTimeout(() => {
      consumed = true
      reset()
      onLongPress?.(point)
    }, LONG_PRESS_MS)
  }

  function move(event) {
    if (!start) return
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (Math.hypot(dx, dy) > MOVE_TOLERANCE_PX) clearTimeout(timer)
    if (Math.abs(dx) > Math.abs(dy)) {
      shift.value = Math.max(-MAX_SHIFT_PX, Math.min(MAX_SHIFT_PX, dx))
    }
  }

  function up(event) {
    if (!start) return
    const direction = swipeDirection(
      event.clientX - start.x,
      event.clientY - start.y
    )
    reset()
    if (!direction) return
    consumed = true
    if (direction === 'next') onNext?.()
    else onPrev?.()
  }

  /** Whether a click is a real tap (not the end of a swipe or hold). */
  function allowClick() {
    if (!consumed) return true
    consumed = false
    return false
  }

  return {
    shift,
    handlers: {
      pointerdown: down,
      pointermove: move,
      pointerup: up,
      pointercancel: reset,
      // iOS's own long-press (image callout, text selection) would fight it.
      contextmenu: (event) => event.preventDefault(),
    },
    allowClick,
  }
}
