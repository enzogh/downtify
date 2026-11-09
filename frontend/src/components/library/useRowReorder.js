// Dragging a list's rows into a new order by a handle - mouse, pen or
// finger alike (pointer events, like the player's sliders): the row
// follows the pointer, the others slide aside to show where it lands,
// and the page scrolls near the top and bottom edges. Arrow keys on the
// handle move a row one place. `onMove(from, to)` is called on release.
import { computed, onBeforeUnmount, ref } from 'vue'
import { dragTarget, edgeScroll, rowShift } from '/src/lib/playlistOrder'

// What stays covered at the bottom of the screen: the mini player, and
// the tab bar on a phone.
function coveredBottom() {
  return window.matchMedia?.('(min-width: 768px)').matches ? 110 : 170
}

export function useRowReorder({ rowHeight, count, onMove }) {
  const from = ref(-1)
  const offset = ref(0)
  // Just dropped: the rows jump to their new places without sliding.
  const settling = ref(false)
  const to = computed(() =>
    from.value < 0
      ? -1
      : dragTarget(from.value, offset.value, rowHeight, count())
  )

  let startY = 0
  let startScroll = 0
  let lastY = 0
  let frame = 0
  let stop = null

  function shift(index) {
    if (from.value < 0) return 0
    if (index === from.value) return offset.value
    return rowShift(index, from.value, to.value, rowHeight)
  }

  function follow() {
    offset.value = lastY - startY + (window.scrollY - startScroll)
  }

  function autoScroll() {
    const speed = edgeScroll(lastY, 64, window.innerHeight - coveredBottom())
    if (speed) {
      window.scrollBy(0, speed)
      follow()
    }
    frame = requestAnimationFrame(autoScroll)
  }

  function start(event, index) {
    if (event.button !== undefined && event.button !== 0) return
    // No text selection, no native drag, no page scroll from this touch.
    event.preventDefault()
    event.stopPropagation()
    const handle = event.currentTarget
    const pointer = event.pointerId
    try {
      handle.setPointerCapture?.(pointer)
    } catch {
      // Followed on the window below either way.
    }
    from.value = index
    offset.value = 0
    startY = lastY = event.clientY
    startScroll = window.scrollY
    frame = requestAnimationFrame(autoScroll)

    const move = (e) => {
      if (e.pointerId !== pointer) return
      lastY = e.clientY
      follow()
    }
    const end = (e) => {
      if (e.pointerId !== pointer) return
      const moved = e.type === 'pointerup' && to.value !== from.value
      const pair = [from.value, to.value]
      finish()
      if (moved) onMove(...pair)
    }
    stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
  }

  function finish() {
    cancelAnimationFrame(frame)
    stop?.()
    stop = null
    settling.value = true
    from.value = -1
    offset.value = 0
    requestAnimationFrame(() =>
      requestAnimationFrame(() => (settling.value = false))
    )
  }

  function key(event, index) {
    const step = { ArrowUp: -1, ArrowDown: 1 }[event.key]
    if (!step) return
    const next = index + step
    if (next < 0 || next >= count()) return
    event.preventDefault()
    onMove(index, next)
  }

  onBeforeUnmount(() => {
    if (from.value >= 0) finish()
  })

  return {
    dragging: computed(() => from.value),
    target: to,
    settling,
    shift,
    start,
    key,
  }
}
