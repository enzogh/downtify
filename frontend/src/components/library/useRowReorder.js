// Dragging a list's rows into a new order by a handle - or, with a mouse,
// by any part of the row, and with a finger by its cover - mouse, pen or
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

// How far (px) a press on a row moves before it becomes a drag.
const DRAG_THRESHOLD = 6

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
    try {
      handle.setPointerCapture?.(event.pointerId)
    } catch {
      // Followed on the window below either way.
    }
    begin(event.pointerId, index, event.clientY, event.clientY)
  }

  // Pressing anywhere else on a row (its cover, its title, an empty
  // column): the drag starts once the pointer has moved a few pixels, so
  // a click still plays or selects. A finger only drags from a
  // `[data-reorder-handle]` (the cover), the rest of the row scrolls the
  // page and keeps its long press for the menu.
  function press(event, index) {
    if (from.value >= 0) return
    if (event.button !== undefined && event.button !== 0) return
    const target = event.target
    const handle = target?.closest?.('[data-reorder-handle]')
    if (!handle && target?.closest?.('button, a, input, label, select')) return
    if (event.pointerType === 'touch' && !handle) return
    const pointer = event.pointerId
    const downY = event.clientY
    const downX = event.clientX
    const waitMove = (e) => {
      if (e.pointerId !== pointer) return
      const dy = e.clientY - downY
      const dx = e.clientX - downX
      if (Math.abs(dy) < DRAG_THRESHOLD || Math.abs(dy) < Math.abs(dx)) {
        if (Math.hypot(dx, dy) > DRAG_THRESHOLD * 3) cancelWait()
        return
      }
      cancelWait()
      // The click that ends this press must not play or select the row.
      swallowNextClick()
      begin(pointer, index, downY, e.clientY)
    }
    const cancelWait = () => {
      window.removeEventListener('pointermove', waitMove)
      window.removeEventListener('pointerup', cancelWait)
      window.removeEventListener('pointercancel', cancelWait)
    }
    window.addEventListener('pointermove', waitMove)
    window.addEventListener('pointerup', cancelWait)
    window.addEventListener('pointercancel', cancelWait)
  }

  function swallowNextClick() {
    const swallow = (e) => {
      e.preventDefault()
      e.stopPropagation()
    }
    window.addEventListener('click', swallow, { capture: true, once: true })
    // No click comes after a drag released outside the row.
    setTimeout(
      () => window.removeEventListener('click', swallow, { capture: true }),
      400
    )
  }

  // While a finger drags, the page mustn't pan under it.
  function holdScroll(e) {
    if (from.value >= 0 && e.cancelable) e.preventDefault()
  }

  function begin(pointer, index, downY, nowY) {
    from.value = index
    offset.value = 0
    startY = downY
    lastY = nowY
    startScroll = window.scrollY
    follow()
    frame = requestAnimationFrame(autoScroll)
    window.addEventListener('touchmove', holdScroll, { passive: false })

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
      window.removeEventListener('touchmove', holdScroll)
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
    press,
    key,
  }
}
