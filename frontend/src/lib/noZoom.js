// Castify behaves like an app, so the page never zooms. Android honours
// the viewport's user-scalable=no; iOS ignores it and still pinch-zooms
// the page, so its pinch gesture (Safari's non-standard gesture* events)
// and two-finger page pinches are cancelled here. Sliders and other
// controls keep their own one-finger touches.

const GESTURE_EVENTS = ['gesturestart', 'gesturechange', 'gestureend']

function cancel(event) {
  if (event.cancelable) event.preventDefault()
}

function cancelPinch(event) {
  if (event.touches?.length > 1) cancel(event)
}

/** Stops pinch zoom on `doc`. Returns a function that undoes it. */
export function blockPageZoom(doc = globalThis.document) {
  if (!doc?.addEventListener) return () => {}
  const passive = { passive: false }
  for (const name of GESTURE_EVENTS) doc.addEventListener(name, cancel, passive)
  doc.addEventListener('touchmove', cancelPinch, passive)
  return () => {
    for (const name of GESTURE_EVENTS) doc.removeEventListener(name, cancel)
    doc.removeEventListener('touchmove', cancelPinch)
  }
}
