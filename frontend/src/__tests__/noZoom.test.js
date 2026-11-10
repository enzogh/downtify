import { describe, expect, it, vi } from 'vitest'
import { blockPageZoom } from '../lib/noZoom.js'

function fakeDocument() {
  const handlers = {}
  return {
    handlers,
    addEventListener: vi.fn((name, fn) => {
      handlers[name] = fn
    }),
    removeEventListener: vi.fn((name) => {
      delete handlers[name]
    }),
  }
}

const event = (extra = {}) => ({
  cancelable: true,
  preventDefault: vi.fn(),
  ...extra,
})

describe('blockPageZoom', () => {
  it("cancels iOS's pinch gesture", () => {
    const doc = fakeDocument()
    blockPageZoom(doc)
    const pinch = event()
    doc.handlers.gesturestart(pinch)
    expect(pinch.preventDefault).toHaveBeenCalled()
  })

  it('cancels two-finger moves but never a one-finger drag', () => {
    const doc = fakeDocument()
    blockPageZoom(doc)
    const drag = event({ touches: [{}] })
    const pinch = event({ touches: [{}, {}] })
    doc.handlers.touchmove(drag)
    doc.handlers.touchmove(pinch)
    expect(drag.preventDefault).not.toHaveBeenCalled()
    expect(pinch.preventDefault).toHaveBeenCalled()
  })

  it('can be undone, and does nothing without a document', () => {
    const doc = fakeDocument()
    blockPageZoom(doc)()
    expect(doc.handlers).toEqual({})
    expect(() => blockPageZoom(null)()).not.toThrow()
  })
})
